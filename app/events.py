from __future__ import annotations

import json
from typing import Literal, TypedDict

# ── Event type constants — import these instead of repeating string literals ──
EVT_DELTA         = "delta"
EVT_THINKING      = "thinking"
EVT_TOOL_CALL     = "tool_call"
EVT_TOOL_RESULT   = "tool_result"
EVT_QUESTIONNAIRE = "questionnaire"
EVT_DONE          = "done"
EVT_ERROR         = "error"


# ── Sub-types ─────────────────────────────────────────────────────────────────

class UsageInfo(TypedDict):
    prompt: int
    completion: int


class QuestionOption(TypedDict):
    id: str
    label: str


# ── Event TypedDicts ──────────────────────────────────────────────────────────

class DeltaEvent(TypedDict):
    type: Literal["delta"]
    content: str


class ThinkingEvent(TypedDict):
    type: Literal["thinking"]
    content: str


class ToolCallEvent(TypedDict):
    type: Literal["tool_call"]
    id: str
    name: str
    input: dict


class ToolResultEvent(TypedDict):
    type: Literal["tool_result"]
    tool_call_id: str
    content: str
    is_error: bool


class QuestionnaireEvent(TypedDict):
    type: Literal["questionnaire"]
    id: str
    question: str
    style: Literal["single", "multi"]
    options: list[QuestionOption]


class DoneEvent(TypedDict):
    type: Literal["done"]
    usage: UsageInfo
    elapsed: float
    # tool_calls is optional — present only when finish_reason == "tool_calls"


class ErrorEvent(TypedDict):
    type: Literal["error"]
    message: str


StreamEvent = (
    DeltaEvent
    | ThinkingEvent
    | ToolCallEvent
    | ToolResultEvent
    | QuestionnaireEvent
    | DoneEvent
    | ErrorEvent
)


# ── Serializer ────────────────────────────────────────────────────────────────

def emit(event: StreamEvent | dict) -> str:
    """Serialize a StreamEvent to a complete SSE frame (ends with \\n\\n)."""
    return f"data: {json.dumps(event)}\n\n"


# ── Tool registry ─────────────────────────────────────────────────────────────
# Tools live in app/tools/. Importing the package triggers all @registry.register
# decorators. events.py imports it here so any module that imports events.py
# (streaming.py, api.py) automatically has a populated registry.
import app.tools  # noqa: F401

from app.tools.registry import registry as _tool_registry


# ── Schema endpoint payload ───────────────────────────────────────────────────
# tools list is built dynamically from the registry so it stays in sync.

EVENTS_SCHEMA: dict = {
    "version": "1",
    "events": {
        EVT_DELTA:         {"content": "str"},
        EVT_THINKING:      {"content": "str"},
        EVT_TOOL_CALL:     {"id": "str", "name": "str", "input": "dict"},
        EVT_TOOL_RESULT:   {"tool_call_id": "str", "content": "str", "is_error": "bool"},
        EVT_QUESTIONNAIRE: {
            "id": "str",
            "question": "str",
            "style": "single|multi",
            "options": [{"id": "str", "label": "str"}],
        },
        EVT_DONE:  {
            "usage": {"prompt": "int", "completion": "int"},
            "elapsed": "float",
            "tool_calls?": "list  # present when finish_reason == tool_calls",
        },
        EVT_ERROR: {"message": "str"},
    },
    "tools": _tool_registry.tools_list(),
}
