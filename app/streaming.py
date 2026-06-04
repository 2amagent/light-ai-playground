from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator

import litellm

from .config import settings
from .events import EVT_DELTA, EVT_DONE, EVT_ERROR, emit
from app.tools.registry import registry
from .prompts import load_system_prompt, load_user_prompt, load_tools_list

litellm.suppress_debug_info = True

_logger = logging.getLogger("ai_playground.streaming")


def _fmt(obj: object) -> str:
    return json.dumps(obj, indent=2, default=str)


async def stream_chat_response(
    messages: list[dict],
    model_override: str | None = None,
    agent_name: str | None = None,
    api_key: str = "",
    base_url: str = "",
) -> AsyncGenerator[str, None]:
    """
    Yields SSE frames. Single-shot: one LLM call per HTTP request.

    api_key is passed directly to LiteLLM — no os.environ mutation.
    If api_key is empty, LiteLLM falls back to the provider env var
    (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) already in the environment.

    All event shapes are defined in app/events.py.
    """
    start = time.monotonic()

    system_prompt = load_system_prompt(agent_name)
    user_prefix = load_user_prompt(agent_name)

    full_messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if user_prefix and messages:
        first_user_idx = next(
            (i for i, m in enumerate(messages) if m["role"] == "user"), None
        )
        if first_user_idx is not None:
            messages = list(messages)
            first_msg = messages[first_user_idx]
            if isinstance(first_msg["content"], str):
                messages[first_user_idx] = {
                    **first_msg,
                    "content": f"{user_prefix}\n\n{first_msg['content']}",
                }

    full_messages.extend(messages)
    model = model_override  # caller (api.py) always passes conv.model

    # Load per-agent tool allowlist from tools.md (hot-reloaded each call).
    # None means no tools.md found → send no tools.
    allowed_tool_names = load_tools_list(agent_name)
    tools = registry.tools_for(allowed_tool_names) if allowed_tool_names is not None else []

    try:
        kwargs: dict = dict(
            model=model,
            messages=full_messages,
            stream=True,
            max_tokens=settings.max_tokens,
            temperature=settings.temperature,
        )
        if api_key:
            kwargs["api_key"] = api_key      # per-call override; no env mutation
        if base_url:
            kwargs["api_base"] = base_url
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        _logger.debug(
            "LLM request | model=%s | messages=%d | tools=%s",
            model, len(full_messages), [t["function"]["name"] for t in tools],
        )
        _logger.debug("LLM messages:\n%s", _fmt(full_messages))

        response = await litellm.acompletion(**kwargs)

        usage: dict = {"prompt": 0, "completion": 0}
        tool_calls_acc: dict[int, dict] = {}
        finish_reason: str | None = None

        async for chunk in response:
            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = choice.finish_reason or finish_reason

            if delta and delta.content:
                yield emit({"type": EVT_DELTA, "content": delta.content})

            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_acc[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["arguments"] += tc.function.arguments

            if hasattr(chunk, "usage") and chunk.usage:
                usage["prompt"]     = getattr(chunk.usage, "prompt_tokens", 0) or 0
                usage["completion"] = getattr(chunk.usage, "completion_tokens", 0) or 0

        _logger.debug("Stream finished | finish_reason=%s", finish_reason)

        # ── Tool calls — dispatch, emit display events, then pause ─────────
        if finish_reason == "tool_calls" and tool_calls_acc:
            sorted_tcs = sorted(tool_calls_acc.values(), key=lambda t: t["id"])
            # tool_results keyed by tool_call_id for api.py to store
            tool_results: dict[str, str] = {}

            for tc in sorted_tcs:
                _logger.debug(
                    "Tool call | name=%s | id=%s | args=%s",
                    tc["name"], tc["id"], tc["arguments"],
                )
                result = await registry.dispatch(tc)
                if result is None:
                    _logger.warning("Unknown tool '%s' — skipping", tc["name"])
                    continue
                # Emit for display only — result_content stays server-side
                yield emit({"type": result.evt_type, **result.payload})
                tool_results[tc["id"]] = result.result_content

            # Embed in done: raw tool_calls (for assistant history message)
            # and tool_results (for api.py to store on pending_tool_call).
            # Frontend must NOT use tool_results — it sends [tool_results_ready]
            # and api.py injects from here.
            raw_tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in sorted_tcs
            ]
            elapsed = round(time.monotonic() - start, 2)
            _logger.debug(
                "Done payload | tool_calls=%d | tool_results keys=%s",
                len(raw_tool_calls), list(tool_results.keys()),
            )
            yield emit({
                "type": EVT_DONE,
                "usage": usage,
                "elapsed": elapsed,
                "tool_calls": raw_tool_calls,
                "tool_results": tool_results,   # server-side only; api.py reads this
            })
            return

        # ── Normal text turn ───────────────────────────────────────────────
        elapsed = round(time.monotonic() - start, 2)
        yield emit({"type": EVT_DONE, "usage": usage, "elapsed": elapsed})

    except litellm.exceptions.AuthenticationError as e:
        _logger.error("Auth error: %s", e)
        yield emit({"type": EVT_ERROR, "message": f"Authentication error: {e}"})
    except litellm.exceptions.RateLimitError as e:
        _logger.error("Rate limit: %s", e)
        yield emit({"type": EVT_ERROR, "message": f"Rate limit exceeded: {e}"})
    except litellm.exceptions.BadRequestError as e:
        _logger.error("Bad request: %s", e)
        yield emit({"type": EVT_ERROR, "message": f"Bad request: {e}"})
    except Exception as e:
        _logger.exception("Unexpected error in stream_chat_response")
        yield emit({"type": EVT_ERROR, "message": str(e)})
