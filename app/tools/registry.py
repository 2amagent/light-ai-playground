from __future__ import annotations

import json
from typing import Callable

from .base import ToolResult


class ToolRegistry:
    _handlers: dict[str, Callable] = {}
    _schemas:  dict[str, dict]     = {}

    # ── Registration ──────────────────────────────────────────────────────

    @classmethod
    def register(cls, func: Callable) -> Callable:
        """Decorator — registers an async tool handler by function name."""
        cls._handlers[func.__name__] = func
        return func

    @classmethod
    def register_schema(cls, name: str, schema: dict) -> None:
        """Register the LiteLLM tool definition dict for a tool."""
        cls._schemas[name] = schema

    # ── Accessors ─────────────────────────────────────────────────────────

    @classmethod
    def tools_list(cls) -> list[dict]:
        """Returns all registered tool schemas."""
        return list(cls._schemas.values())

    @classmethod
    def tools_for(cls, names: list[str]) -> list[dict]:
        """Returns schemas for only the named tools. Unknown names are logged and skipped."""
        import logging
        _log = logging.getLogger("ai_playground.tools")
        result = []
        for name in names:
            schema = cls._schemas.get(name)
            if schema is None:
                _log.warning("tools.md references unknown tool '%s' — skipping", name)
            else:
                result.append(schema)
        return result

    @classmethod
    async def dispatch(cls, tc: dict) -> ToolResult | None:
        """
        Dispatch a completed tool call to its registered handler.

        tc = {"id": str, "name": str, "arguments": str (raw JSON)}

        Returns None for unknown tool names (caller should skip/warn).
        """
        name = tc["name"]
        handler = cls._handlers.get(name)
        if handler is None:
            return None

        try:
            args = json.loads(tc["arguments"])
        except json.JSONDecodeError:
            # Import lazily to avoid circular import at module load time
            from app.events import EVT_ERROR
            return ToolResult(
                evt_type=EVT_ERROR,
                payload={"message": f"Tool '{name}' returned malformed JSON arguments"},
            )

        result = await handler(args=args, tool_call_id=tc["id"])

        # Log every tool invocation — one place covers all tools
        from app.tool_log import log_tool_call
        content = result.payload.get("content", "") if result else ""
        log_tool_call(
            tool_name=name,
            args=args,
            result_content=str(content),
            is_error=result.payload.get("is_error", False) if result else False,
        )

        return result


registry = ToolRegistry()
