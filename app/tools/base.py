from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """Return value from every registered tool handler."""

    # SSE event type to emit (must match an EVT_* constant in app/events.py)
    evt_type: str

    # Payload dict emitted as an SSE frame (for frontend display only)
    payload: dict

    # The content to inject as the tool-result message into conversation history.
    # Stored server-side on conv.pending_tool_call — never round-tripped through
    # the browser, so the client cannot tamper with it.
    result_content: str = ""
