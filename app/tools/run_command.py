from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .base import ToolResult
from .registry import registry

ALLOWED_COMMANDS = {"git", "sed", "cat", "head", "find", "ls", "grep"}
DEFAULT_MAX_LINES = 200
MAX_LINES_CEILING = 1000   # hard cap regardless of what the model requests

RUN_COMMAND_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            f"Run a local shell command and return its output. "
            f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}. "
            "Pass the full command as a single string, e.g. 'git log --oneline -10' "
            "or 'grep -rn MyClass src/'. "
            "Output is truncated to max_lines (default 200, max 1000)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Full command string to run, e.g. 'ls -la' or 'grep -r TODO src/'",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Absolute path to run the command in. Defaults to project root.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": f"Maximum output lines to return (default {DEFAULT_MAX_LINES}, max {MAX_LINES_CEILING}).",
                },
            },
            "required": ["command"],
        },
    },
}
registry.register_schema("run_command", RUN_COMMAND_SCHEMA)


@registry.register
async def run_command(args: dict, tool_call_id: str) -> ToolResult:
    from app.events import EVT_TOOL_RESULT

    command_str: str = args.get("command", "").strip()
    working_dir: str | None = args.get("working_dir")
    max_lines: int = min(
        int(args.get("max_lines", DEFAULT_MAX_LINES)),
        MAX_LINES_CEILING,
    )

    # ── Parse and gate-check ───────────────────────────────────────────────
    try:
        parts = shlex.split(command_str)
    except ValueError as e:
        return _error(tool_call_id, f"Invalid command syntax: {e}")

    if not parts:
        return _error(tool_call_id, "Empty command.")

    binary = parts[0]
    if binary not in ALLOWED_COMMANDS:
        return _error(
            tool_call_id,
            f"Command '{binary}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}.",
        )

    # ── Resolve working directory ──────────────────────────────────────────
    cwd: Path | None = None
    if working_dir:
        cwd = Path(working_dir).expanduser().resolve()
        if not cwd.is_dir():
            return _error(tool_call_id, f"working_dir '{working_dir}' is not a directory.")

    # ── Execute — shell=False prevents injection ───────────────────────────
    try:
        proc = subprocess.run(
            parts,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return _error(tool_call_id, "Command timed out after 30 seconds.")
    except FileNotFoundError:
        return _error(tool_call_id, f"Binary '{binary}' not found on PATH.")

    output = proc.stdout
    stderr = proc.stderr.strip()

    # ── Truncate ───────────────────────────────────────────────────────────
    lines = output.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    result_text = "\n".join(lines)
    if truncated:
        result_text += f"\n\n[truncated — showing {max_lines} of {len(output.splitlines())} lines]"
    if stderr and proc.returncode != 0:
        result_text += f"\n\nstderr:\n{stderr}"

    content = result_text or stderr or "(no output)"
    is_error = proc.returncode != 0 and not result_text.strip()
    return ToolResult(
        evt_type=EVT_TOOL_RESULT,
        payload={
            "tool_call_id": tool_call_id,
            "content": content,
            "is_error": is_error,
        },
        result_content=content,   # stored server-side; never round-tripped through browser
    )


def _error(tool_call_id: str, message: str) -> ToolResult:
    from app.events import EVT_TOOL_RESULT
    return ToolResult(
        evt_type=EVT_TOOL_RESULT,
        payload={"tool_call_id": tool_call_id, "content": message, "is_error": True},
        result_content=message,
    )
