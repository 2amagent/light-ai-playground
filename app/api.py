import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote as _url_quote

_logger = logging.getLogger("ai_playground.api")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .conversations import (
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    save_if_persist,
)
from .events import EVT_DELTA, EVT_DONE, EVENTS_SCHEMA
from .prompts import load_description, load_system_prompt
from .streaming import stream_chat_response
from .tools.registry import registry as _tool_registry

# Frontend sends this exact string to resume after an auto-executing tool.
# api.py recognises it and skips adding it to conversation history.
TOOL_RESUME_SIGNAL = "[tool_results_ready]"

app = FastAPI(title="AI Playground", docs_url="/docs", redoc_url=None)

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "img-src 'self' data:; "
    "connect-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'"
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _Request
from starlette.responses import Response as _Response

class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: _Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(_SecurityHeadersMiddleware)


# ── Request models ────────────────────────────────────────────────────────────

class NewConversationRequest(BaseModel):
    agent_name: str
    model: str
    api_key: str = ""     # optional — LiteLLM falls back to provider env var if blank
    base_url: str = ""


_SAFE_NAME = re.compile(r'^[a-zA-Z0-9_-]+$')
_AGENTS_ROOT = Path("agents").resolve()


def _validate_agent_name(name: str) -> None:
    """Raise 422 if name contains path traversal characters or is unsafe."""
    if not _SAFE_NAME.match(name):
        raise HTTPException(
            status_code=422,
            detail="Agent name may only contain letters, digits, hyphens and underscores",
        )
    resolved = (_AGENTS_ROOT / name).resolve()
    if not str(resolved).startswith(str(_AGENTS_ROOT)):
        raise HTTPException(status_code=422, detail="Invalid agent name")


class AgentSaveRequest(BaseModel):
    name: str = Field(..., max_length=64)
    system_prompt: str = Field(..., max_length=32_000)
    user_prompt: str = Field(default="", max_length=8_000)
    description: str = Field(default="", max_length=500)
    tools: list[str] = Field(default=[], max_items=20)


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    images: list[str] = []
    model_override: Optional[str] = None


# ── Agent discovery ───────────────────────────────────────────────────────────

@app.get("/api/agents")
async def list_agents():
    """Scan for available agents — subdirectories under agents/ + root-level *.system.md files."""
    agents = []
    agents_dir = Path("agents")
    if agents_dir.is_dir():
        for d in sorted(agents_dir.iterdir()):
            if d.is_dir() and (d / "system.md").exists():
                desc_file = d / "description.md"
                agents.append({
                    "name": d.name,
                    "description": desc_file.read_text(encoding="utf-8").strip() if desc_file.exists() else "",
                })
    for f in sorted(Path(".").glob("*.system.md")):
        name = f.name.removesuffix(".system.md")
        if not any(a["name"] == name for a in agents):
            agents.append({"name": name, "description": ""})
    return agents


@app.get("/api/tools")
async def list_tools():
    """Return all registered tool names and descriptions."""
    return [
        {
            "name": schema["function"]["name"],
            "description": schema["function"].get("description", ""),
        }
        for schema in _tool_registry.tools_list()
    ]


@app.get("/api/agents/{name}")
async def get_agent(name: str):
    """Load full agent data from disk."""
    _validate_agent_name(name)
    agent_dir = Path("agents") / name
    if not agent_dir.is_dir() or not (agent_dir / "system.md").exists():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    system = (agent_dir / "system.md").read_text(encoding="utf-8")
    user   = (agent_dir / "user.md").read_text(encoding="utf-8") if (agent_dir / "user.md").exists() else ""
    desc   = (agent_dir / "description.md").read_text(encoding="utf-8") if (agent_dir / "description.md").exists() else ""
    tools: list[str] = []
    tools_file = agent_dir / "tools.md"
    if tools_file.exists():
        for line in tools_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                tools.append(line)
    return {"name": name, "system_prompt": system, "user_prompt": user, "description": desc, "tools": tools}


@app.put("/api/agents/{name}")
async def save_agent(name: str, req: AgentSaveRequest):
    """Write agent files to disk. Renames the directory if req.name differs from name."""
    _validate_agent_name(name)
    _validate_agent_name(req.name)
    if not req.system_prompt.strip():
        raise HTTPException(status_code=422, detail="system_prompt is required")

    old_dir = Path("agents") / name
    new_dir = Path("agents") / req.name

    if req.name != name and old_dir.exists():
        old_dir.rename(new_dir)

    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / "system.md").write_text(req.system_prompt, encoding="utf-8")
    _write_or_delete(new_dir / "user.md", req.user_prompt)
    _write_or_delete(new_dir / "description.md", req.description)

    tools_content = "\n".join(req.tools) + "\n" if req.tools else ""
    (new_dir / "tools.md").write_text(tools_content, encoding="utf-8")

    return {"ok": True, "name": req.name}


def _write_or_delete(path: Path, content: str) -> None:
    if content.strip():
        path.write_text(content, encoding="utf-8")
    elif path.exists():
        path.unlink()


# ── Conversation routes ───────────────────────────────────────────────────────

@app.get("/api/conversations")
async def get_conversations():
    return list_conversations()


@app.post("/api/conversations/new")
async def new_conversation(req: NewConversationRequest):
    conv = create_conversation(
        agent_name=req.agent_name,
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "agent_name": conv.agent_name,
        "model": conv.model,
    }


@app.delete("/api/conversations/{cid}")
async def delete_conv(cid: str):
    if not delete_conversation(cid):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@app.get("/api/agent-info/{agent_name}")
async def agent_info(agent_name: str):
    """Return metadata for a specific agent."""
    return {
        "name": agent_name,
        "description": load_description(agent_name),
    }


@app.get("/api/agent-info/{agent_name}/system-prompt")
async def get_system_prompt(agent_name: str):
    try:
        return {"content": load_system_prompt(agent_name)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/events-schema")
async def events_schema():
    return EVENTS_SCHEMA


# ── Chat route ────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    conv = get_conversation(req.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Build content: text + optional images (OpenAI vision format)
    if req.images:
        content: list | str = [{"type": "text", "text": req.message}]
        for b64 in req.images:
            data_uri = b64 if b64.startswith("data:") else f"data:image/jpeg;base64,{b64}"
            content.append({"type": "image_url", "image_url": {"url": data_uri}})
    else:
        content = req.message

    _logger.debug(
        "Chat request | conv=%s | agent=%s | model=%s | pending_tool_call=%s",
        conv.id[:8], conv.agent_name, conv.model, conv.pending_tool_call,
    )

    # ── Tool result injection (server-side only) ───────────────────────────
    pending = conv.pending_tool_call
    if pending is not None:
        is_auto_resume = req.message == TOOL_RESUME_SIGNAL
        result_content = pending.get("result_content") or (
            req.message if not is_auto_resume else ""
        )
        _logger.debug(
            "Injecting tool result | tool_call_id=%s | auto_resume=%s | content=%r",
            pending["id"], is_auto_resume, result_content,
        )
        conv.messages.append({
            "role": "tool",
            "tool_call_id": pending["id"],
            "content": result_content,
        })
        conv.pending_tool_call = None

        if not is_auto_resume:
            conv.messages.append({"role": "user", "content": req.message})
    else:
        if not conv.messages:
            conv.title = req.message[:60] + ("..." if len(req.message) > 60 else "")
        conv.messages.append({"role": "user", "content": content})

    _logger.debug("Conv messages before LLM call:\n%s",
        json.dumps(conv.messages, indent=2, default=str))

    full_content: list[str] = []

    async def generate():
        async for chunk in stream_chat_response(
            conv.messages,
            model_override=req.model_override or conv.model,
            agent_name=conv.agent_name,
            api_key=conv.api_key,
            base_url=conv.base_url,
        ):
            yield chunk
            if not chunk.startswith("data: "):
                continue
            try:
                evt = json.loads(chunk[6:])
            except json.JSONDecodeError:
                continue

            etype = evt.get("type")

            if etype == EVT_DELTA:
                full_content.append(evt["content"])

            elif etype == EVT_DONE:
                if "tool_calls" in evt:
                    conv.messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": evt["tool_calls"],
                    })
                    first_tc = evt["tool_calls"][0]
                    tool_results = evt.get("tool_results", {})
                    conv.pending_tool_call = {
                        "id": first_tc["id"],
                        "result_content": tool_results.get(first_tc["id"], ""),
                    }
                    _logger.debug(
                        "Tool call turn done | pending_tool_call=%s",
                        conv.pending_tool_call,
                    )
                else:
                    conv.messages.append({
                        "role": "assistant",
                        "content": "".join(full_content),
                    })
                    conv.pending_tool_call = None
                    _logger.debug(
                        "Text turn done | assistant content length=%d",
                        len("".join(full_content)),
                    )
                save_if_persist()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Export route ──────────────────────────────────────────────────────────────

@app.get("/api/conversations/{cid}/export")
async def export_conversation(cid: str):
    conv = get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    lines = [f"# {conv.title}\n\n*Agent: {conv.agent_name} · Model: {conv.model}*\n\n---\n\n"]
    for msg in conv.messages:
        role = msg["role"].capitalize()
        body = msg.get("content") or ""
        if isinstance(body, list):
            body = "\n".join(p.get("text", "") for p in body if p.get("type") == "text")
        if msg["role"] == "tool":
            continue
        lines.append(f"## {role}\n\n{body}\n\n")

    md_bytes = "".join(lines).encode("utf-8")
    return Response(
        content=md_bytes,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(cid)}.md"},
    )


# ── Retry support ─────────────────────────────────────────────────────────────

@app.post("/api/conversations/{cid}/retry")
async def retry_last(cid: str):
    conv = get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.messages and conv.messages[-1]["role"] == "assistant":
        conv.messages.pop()
    save_if_persist()
    return {"ok": True}


# ── Static files (must be last) ───────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")
