# Technical Implementation Details

Reference documentation for contributors and developers working on the internals of AI Playground.

---

## Architecture

```
main.py                 # Startup: loads config, starts server, opens browser
app/
  config.py             # Server settings (port, host, persist, log_level)
  api.py                # FastAPI routes
  streaming.py          # SSE generator wrapping litellm.acompletion()
  conversations.py      # In-memory conversation store (+ optional JSON persistence)
  prompts.py            # Hot-reload loader for agent .md files
  events.py             # Typed SSE event shapes + tool definitions
  logging_setup.py      # Structured logging to logs/app_*.log
  tools/
    registry.py         # ToolRegistry — register, dispatch, filter by agent
    base.py             # ToolResult dataclass
    ask_user.py         # ask_user tool
    run_command.py      # run_command tool
static/
  index.html            # Full frontend — HTML + CSS + JS, no build step
agents/
  {name}/               # Agent files (system.md, user.md, description.md, tools.md)
```

### How a conversation works

1. **New Chat** → modal asks for agent, model, optional API key and base URL
2. The `Conversation` object stores these per-conversation (API key in memory only, never persisted)
3. Each message: `api.py` passes `conv.model`, `conv.api_key`, `conv.agent_name` to `streaming.py`
4. `streaming.py` loads the system prompt and tool list for the agent, calls LiteLLM
5. Responses stream back as SSE events (`delta`, `tool_result`, `questionnaire`, `done`)
6. When a tool is called: the tool executes server-side, the result is stored on the conversation, and the frontend sends a resume signal — the result never comes back from the browser

---

## SSE event types

All event shapes are defined in `app/events.py` and available at `GET /api/events-schema`.

| Event | When |
|---|---|
| `delta` | Each streamed token |
| `done` | Stream complete (includes token usage) |
| `error` | LLM or tool error |
| `questionnaire` | Agent called `ask_user` — renders choice card |
| `tool_result` | Auto-executing tool finished — renders accordion |
| `thinking` | Reserved for reasoning model output |

When adding a new event type:
1. Add the TypedDict and `EVT_*` constant to `app/events.py`
2. `emit()` it in `streaming.py`
3. Add a `case` to the `switch` in `static/index.html`'s `handleStreamEvent()`

---

## Debugging

Set `LOG_LEVEL=DEBUG` in your `.env` to get full traces in `logs/app_YYYYMMDD_HH.log`:

```
2026-06-04 09:31:02 DEBUG ai_playground.api       | Chat request | conv=abc123 | agent=code-explorer | model=anthropic/claude-haiku-4-5
2026-06-04 09:31:02 DEBUG ai_playground.streaming  | LLM request | model=anthropic/claude-haiku-4-5 | messages=3 | tools=['run_command']
2026-06-04 09:31:04 DEBUG ai_playground.streaming  | Stream finished | finish_reason=tool_calls
2026-06-04 09:31:04 DEBUG ai_playground.streaming  | Tool call | name=run_command | id=call_abc | args={"command":"git log --oneline -5"}
2026-06-04 09:31:04 INFO  ai_playground.tools      | TOOL CALL | run_command | OK | input={...} | output=abc1234 Add feature...
```

Press `R + Enter` in the terminal running `main.py` to restart the server without losing conversation history.

Log files are written to `logs/` (gitignored). At `LOG_LEVEL=DEBUG` the full conversation message array is written to disk — avoid this when working with sensitive content.

---

## Security notes

- API keys entered in the UI are held **in server memory only** — never written to disk, never sent back to the browser
- `run_command` executes with `shell=False` — shell injection via `;`, `&&`, `$(...)` is not possible
- The command allowlist (`git`, `grep`, etc.) is enforced server-side regardless of what the model requests
- `run_command` `working_dir` is restricted to paths within the project root — agents cannot read arbitrary filesystem paths
- Tool results are stored server-side — the frontend sends a `[tool_results_ready]` signal with no data payload, preventing result tampering
- LLM error messages are sanitised before being sent to the browser — full errors are logged server-side only
- All HTTP responses include `Content-Security-Policy`, `X-Frame-Options: DENY`, and `X-Content-Type-Options: nosniff` headers
- All `marked.parse()` output is passed through DOMPurify before being assigned to `innerHTML`
- Agent names are validated to `[a-zA-Z0-9_-]+` with path resolution checks — no path traversal via crafted names
- `conversations.json` (when `PERSIST=true`) is written with `0o600` permissions — owner-readable only
- `.env` is gitignored — API keys set via environment variables are never committed

---

## Tool result flow (server-side only)

When the LLM calls a tool:

1. `streaming.py` dispatches to `registry.dispatch(tc)` — the tool handler runs and returns a `ToolResult`
2. `ToolResult.result_content` is stored on `conv.pending_tool_call` in memory
3. `ToolResult.payload` is emitted as an SSE frame for display in the UI (accordion / choice card)
4. The frontend sees the display event but **never** sees `result_content`
5. The frontend sends `[tool_results_ready]` as the next message
6. `api.py` detects the resume signal, injects `{"role": "tool", "content": pending_tool_call.result_content}` into the message history, and calls the LLM again

This design means tool result content cannot be tampered with by a compromised browser or extension.

---

## Conversation history format

`conv.messages` stores raw OpenAI-format message dicts. After a tool exchange the sequence is:

```
{"role": "user", "content": "..."}
{"role": "assistant", "content": null, "tool_calls": [...]}
{"role": "tool", "tool_call_id": "...", "content": "result"}
{"role": "user", "content": "[tool_results_ready]"}   ← stripped before LLM call
```

`pending_tool_call` is ephemeral and not serialized to `conversations.json`.
