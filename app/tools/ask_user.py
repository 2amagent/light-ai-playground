from __future__ import annotations

import uuid

from .base import ToolResult
from .registry import registry

ASK_USER_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "Ask the user a clarifying question with structured answer options. "
            "Use when you need the user to choose from a defined set before proceeding."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "style": {
                    "type": "string",
                    "enum": ["single", "multi"],
                    "description": "'single' = pick exactly one, 'multi' = pick one or more",
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":    {"type": "string"},
                            "label": {"type": "string"},
                        },
                        "required": ["id", "label"],
                    },
                    "minItems": 2,
                },
            },
            "required": ["question", "style", "options"],
        },
    },
}
registry.register_schema("ask_user", ASK_USER_SCHEMA)


@registry.register
async def ask_user(args: dict, tool_call_id: str) -> ToolResult:
    # Import EVT_QUESTIONNAIRE lazily to keep the circular-import boundary clean
    from app.events import EVT_QUESTIONNAIRE
    # result_content is empty here — api.py fills it from the user's answer
    # when submitQuestionnaire() fires the resume request.
    return ToolResult(
        evt_type=EVT_QUESTIONNAIRE,
        payload={
            "id": tool_call_id or str(uuid.uuid4()),
            "question": args.get("question", ""),
            "style": args.get("style", "single"),
            "options": args.get("options", []),
        },
        result_content="",   # filled by api.py from req.message on resume
    )
