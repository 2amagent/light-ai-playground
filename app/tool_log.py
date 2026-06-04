from __future__ import annotations

import logging

_logger = logging.getLogger("ai_playground.tools")
_TRUNCATE = 200


def log_tool_call(tool_name: str, args: dict, result_content: str, is_error: bool) -> None:
    """Log one tool invocation at INFO level (appears in file regardless of LOG_LEVEL)."""
    preview = result_content[:_TRUNCATE]
    if len(result_content) > _TRUNCATE:
        preview += f"… [{len(result_content)} chars total]"

    status = "ERROR" if is_error else "OK"
    _logger.info(
        "TOOL CALL | %s | %s | input=%r | output=%s",
        tool_name, status, args, preview,
    )
