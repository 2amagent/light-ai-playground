from __future__ import annotations

import litellm

from .base import ToolResult
from .registry import registry

CALL_AGENT_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "call_agent",
        "description": (
            "Call another agent by name with a message and get its response. "
            "Use list_agents first to discover valid agent names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name of the agent to call (e.g. 'code-explorer').",
                },
                "message": {
                    "type": "string",
                    "description": "The message or prompt to send to the agent.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "LiteLLM model string to use (e.g. 'anthropic/claude-sonnet-4-6'). "
                        "If omitted, falls back to the LITELLM_MODEL env var or the default model."
                    ),
                },
            },
            "required": ["agent_name", "message"],
        },
    },
}
registry.register_schema("call_agent", CALL_AGENT_SCHEMA)


@registry.register
async def call_agent(args: dict, tool_call_id: str) -> ToolResult:
    from app.events import EVT_TOOL_RESULT
    from app.prompts import load_system_prompt, load_user_prompt, load_tools_list

    agent_name: str = args.get("agent_name", "").strip()
    message: str = args.get("message", "").strip()
    model: str | None = args.get("model", "").strip() or None

    if not agent_name:
        return _error(tool_call_id, "agent_name is required.")
    if not message:
        return _error(tool_call_id, "message is required.")

    try:
        system_prompt = load_system_prompt(agent_name)
    except FileNotFoundError as e:
        return _error(tool_call_id, str(e))

    user_prefix = load_user_prompt(agent_name)
    user_content = f"{user_prefix}\n\n{message}" if user_prefix else message

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    allowed_tool_names = load_tools_list(agent_name)
    tools = registry.tools_for(allowed_tool_names) if allowed_tool_names is not None else []

    if not model:
        return _error(
            tool_call_id,
            "No model specified. Pass the 'model' argument (e.g. 'anthropic/claude-sonnet-4-6').",
        )

    try:
        kwargs: dict = dict(
            model=model,
            messages=messages,
            stream=False,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await litellm.acompletion(**kwargs)
        text: str = response.choices[0].message.content or ""
    except litellm.exceptions.AuthenticationError:
        return _error(tool_call_id, "Authentication failed — check your API key environment variable.")
    except litellm.exceptions.BadRequestError as e:
        return _error(tool_call_id, f"Bad request: {e}")
    except Exception as e:
        return _error(tool_call_id, f"Unexpected error calling agent '{agent_name}': {e}")

    return ToolResult(
        evt_type=EVT_TOOL_RESULT,
        payload={"tool_call_id": tool_call_id, "content": text, "is_error": False},
        result_content=text,
    )


def _error(tool_call_id: str, message: str) -> ToolResult:
    from app.events import EVT_TOOL_RESULT
    return ToolResult(
        evt_type=EVT_TOOL_RESULT,
        payload={"tool_call_id": tool_call_id, "content": message, "is_error": True},
        result_content=message,
    )
