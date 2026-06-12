from __future__ import annotations

import json
from pathlib import Path

from .base import ToolResult
from .registry import registry

LIST_AGENTS_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "list_agents",
        "description": (
            "List all available agents and their descriptions. "
            "Call this before call_agent to discover valid agent names."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}
registry.register_schema("list_agents", LIST_AGENTS_SCHEMA)


@registry.register
async def list_agents(args: dict, tool_call_id: str) -> ToolResult:
    from app.events import EVT_TOOL_RESULT
    from app.prompts import load_description

    agents: list[dict] = []

    agents_dir = Path("agents")
    if agents_dir.is_dir():
        for d in sorted(agents_dir.iterdir()):
            if d.is_dir() and (d / "system.md").exists():
                agents.append({
                    "name": d.name,
                    "description": load_description(d.name) or "",
                })

    for f in sorted(Path(".").glob("*.system.md")):
        name = f.name.removesuffix(".system.md")
        agents.append({
            "name": name,
            "description": load_description(name) or "",
        })

    content = json.dumps(agents, indent=2)
    return ToolResult(
        evt_type=EVT_TOOL_RESULT,
        payload={"tool_call_id": tool_call_id, "content": content, "is_error": False},
        result_content=content,
    )
