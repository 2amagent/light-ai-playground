# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Install / sync dependencies (Python 3.13, managed by uv)
uv sync

# Start the server (reads .env in the project root)
uv run python main.py
```

`main.py` validates config and the system prompt file at startup, prints a clear error if either is missing, and auto-opens the browser.

## Creating an agent

Copy `.env.example` to `.env` and fill in at minimum `AGENT_NAME`, `MODEL`, and `API_KEY`. Then create the system prompt file for the agent:

```
# Either of these layouts works — prompts.py checks both:
{AGENT_NAME}.system.md              # root-level flat layout
agents/{AGENT_NAME}/system.md       # subdirectory layout
```

Optional files loaded the same way: `{name}.user.md` (prepended to every user message), `{name}.description.md` (shown in UI header).

**Tool selection** — create `{name}.tools.md` (or `agents/{name}/tools.md`) listing one tool name per line. Lines starting with `#` are comments. If the file is absent, no tools are sent to the LLM. If present, only the listed tools are active for that agent:

```
# agents/my-agent/tools.md
ask_user
run_command
```

**All agent files are hot-reloaded** — they are read on every request, so edits take effect without restarting.

## LiteLLM model strings

`MODEL` follows LiteLLM's `provider/model` format. `API_KEY` is automatically mapped to the correct provider env var by `app/config.py`:

| MODEL prefix | Provider env var set |
|---|---|
| `openai/` | `OPENAI_API_KEY` |
| `anthropic/` | `ANTHROPIC_API_KEY` |
| `together_ai/` | `TOGETHERAI_API_KEY` |
| `replicate/` | `REPLICATE_API_KEY` |
| `ollama/` | (no key needed, set `BASE_URL=http://localhost:11434`) |

`BASE_URL` is passed as `api_base` to LiteLLM and also sets `OPENAI_API_BASE` for OpenAI-compatible endpoints.

## Architecture

```
main.py                 # Startup: validates config + system prompt, opens browser
app/
  config.py             # pydantic-settings Settings singleton; auto-maps API_KEY to provider env var
  events.py             # Single source of truth for SSE event shapes (TypedDicts + emit() + tool defs)
  streaming.py          # litellm.acompletion(stream=True) wrapper; yields SSE frames via emit()
  api.py                # FastAPI app; all HTTP routes; wires streaming → StreamingResponse
  conversations.py      # In-memory Conversation store; optional JSON persistence (PERSIST=true)
  prompts.py            # Hot-reload loader for .md files (system/user/description)
static/
  index.html            # Entire frontend: HTML + CSS + JS in one file, no build step
agents/
  {name}/               # Optional: store agent files here instead of root
```

### SSE event protocol

All SSE event shapes are defined in `app/events.py` and served at `GET /api/events-schema`. The frontend dispatches on `evt.type` in a `switch` in `handleStreamEvent()`. When adding a new event type:

1. Add the TypedDict and `EVT_*` constant to `app/events.py`
2. `emit()` it in `streaming.py`
3. Add a `case` to the `switch` in `static/index.html`

Current event types: `delta`, `thinking`, `done`, `error`, `questionnaire`, `tool_call`, `tool_result`.

### Tool use / questionnaire flow

Tools are defined in `app/tools/` and registered via a `ToolRegistry` in `app/tools/registry.py`. Each tool is a self-contained module with a schema dict and an async handler function. `streaming.py` calls `registry.tools_list()` and `registry.dispatch()` — it has no tool-specific logic.

When the model calls a tool:
- `streaming.py` accumulates fragmented tool call chunks (arguments arrive as partial JSON across multiple chunks), then calls `registry.dispatch(tc)` post-stream
- The handler returns a `ToolResult(evt_type, payload, awaits_user)` which `streaming.py` emits as an SSE frame
- The `done` event carries the raw `tool_calls` payload so `api.py` can write the correct `{"role":"assistant","content":null,"tool_calls":[...]}` history entry
- `api.py` stores `conv.pending_tool_call` on the `Conversation` object; on the next user message it injects a `{"role":"tool",...}` message before the user message to satisfy the OpenAI/Anthropic tool protocol
- `pending_tool_call` is ephemeral — not serialized to `conversations.json`

**To add a new tool** (only 2 steps):
1. Create `app/tools/your_tool.py` — call `registry.register_schema(name, schema)` and decorate an `async def your_tool(args, tool_call_id) -> ToolResult` with `@registry.register`
2. Add `from app.tools import your_tool  # noqa: F401` to `app/tools/__init__.py`

Nothing else changes — `streaming.py`, `api.py`, and `events.py` pick it up automatically.

### Conversation history

`conv.messages` stores raw OpenAI-format message dicts. After a questionnaire exchange the sequence is:
```
{"role": "user", ...}
{"role": "assistant", "content": null, "tool_calls": [...]}   ← written by api.py on done
{"role": "tool", "tool_call_id": "...", "content": "answer"}  ← injected by api.py on next request
{"role": "user", "content": "answer"}                         ← the actual user message
```

### Frontend state

The frontend maintains a client-side `msgCache` keyed by conversation ID. This is rebuilt from rendered messages when switching conversations (the server's `/api/conversations` only returns metadata, not full message bodies). `state.pendingQuestionnaire` disables the text input while a questionnaire card awaits an answer.
