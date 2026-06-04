# AI Playground

A local developer tool for experimenting with LLM agents across multiple providers. Create agents by writing markdown files, launch the server, and get a chat interface in your browser.

## What it does

- **Multi-provider** — Anthropic, OpenAI, Together.ai, Replicate, Ollama, or any OpenAI-compatible endpoint
- **Per-conversation config** — choose agent, model, and API key when starting each conversation
- **Agent editor** — create and edit agents directly in the UI (system prompt, user prompt, tools)
- **Tool use** — agents can run shell commands, ask structured questions, and more
- **Streaming** — responses stream token by token with markdown rendering
- **No build step** — pure HTML/CSS/JS frontend, no npm, no bundler

---

## Quick start

**Requirements:** Python 3.13, [uv](https://docs.astral.sh/uv/)

```bash
git clone <repo>
cd ai-playground
uv sync
uv run python main.py
```

The browser opens automatically. Click **New Chat** to start a conversation — you'll be asked which agent to use and what model.

API keys are entered per-conversation in the UI. Alternatively, set them as environment variables and leave the UI field blank:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
uv run python main.py
```

---

## Configuration

Copy `.env.example` to `.env` to set server-level options:

```dotenv
PORT=8000
HOST=127.0.0.1
PERSIST=false          # true = save conversations to conversations.json
AUTO_OPEN_BROWSER=true
LOG_LEVEL=WARNING      # set to DEBUG for full trace in logs/
MAX_TOKENS=4096
TEMPERATURE=0.7
```

None of these are required — defaults work out of the box.

---

## Creating an agent

### Via the UI

Click **✎ Edit Agents** in the sidebar → **+ New Agent**. Fill in:
- **Name** — used as the folder name under `agents/`
- **Description** — shown in the New Conversation dropdown
- **System Prompt** — the agent's core instructions
- **User Prompt** — optional text prepended to every user message
- **Tools** — which tools the agent is allowed to use

Click **Save Agent**. The agent appears immediately in the New Conversation modal.

### Via files

Create a folder under `agents/` with a `system.md` file:

```
agents/
  my-agent/
    system.md        # required — the system prompt
    user.md          # optional — prepended to every user message
    description.md   # optional — shown in the UI dropdown
    tools.md         # optional — list of allowed tools, one per line
```

All files are **hot-reloaded** — edits take effect on the next message without restarting.

If `tools.md` is absent, no tools are available to the agent. To enable tools:

```
# agents/my-agent/tools.md
ask_user
run_command
```

---

## Supported model strings

The model field uses LiteLLM's `provider/model` format:

| Provider | Example model string |
|---|---|
| Anthropic | `anthropic/claude-haiku-4-5` |
| OpenAI | `openai/gpt-4o` |
| Together.ai | `together_ai/Qwen/Qwen2.5-7B-Instruct-Turbo` |
| Replicate | `replicate/meta/meta-llama-3-70b-instruct` |
| Groq | `groq/llama3-8b-8192` |
| Ollama (local) | `ollama/llama3` + Base URL `http://localhost:11434` |
| Any OpenAI-compatible | `openai/your-model` + Base URL pointing to your endpoint |

The **Base URL** field in the New Conversation modal is for providers that use a custom endpoint (Together.ai, Ollama, local servers).

---

## Built-in tools

### `run_command`

Runs shell commands and returns the output. Only these commands are allowed:

```
git  sed  cat  head  find  ls  grep
```

Parameters:
- `command` — the full command string, e.g. `git log --oneline -10`
- `working_dir` — optional absolute path to run from
- `max_lines` — output line limit (default 200, max 1000)

The agent receives the output and continues the conversation. The result is stored server-side — it never round-trips through the browser.

### `ask_user`

Lets the agent ask a structured question with predefined options. The UI renders a choice card (single-select or multi-select). The agent continues after the user picks an option.

---

## Adding a new tool

1. Create `app/tools/your_tool.py`:

```python
from app.events import EVT_TOOL_RESULT
from .base import ToolResult
from .registry import registry

MY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "What this tool does.",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
            },
            "required": ["input"],
        },
    },
}
registry.register_schema("my_tool", MY_TOOL_SCHEMA)


@registry.register
async def my_tool(args: dict, tool_call_id: str) -> ToolResult:
    result = do_something(args["input"])
    return ToolResult(
        evt_type=EVT_TOOL_RESULT,
        payload={"tool_call_id": tool_call_id, "content": result, "is_error": False},
        result_content=result,
    )
```

2. Register it in `app/tools/__init__.py`:

```python
from app.tools import ask_user, run_command, your_tool  # noqa: F401
```

3. Add it to any agent's `tools.md` to make it available.

No other files need to change.

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

### SSE event types

All event shapes are defined in `app/events.py` and available at `GET /api/events-schema`.

| Event | When |
|---|---|
| `delta` | Each streamed token |
| `done` | Stream complete (includes token usage) |
| `error` | LLM or tool error |
| `questionnaire` | Agent called `ask_user` — renders choice card |
| `tool_result` | Auto-executing tool finished — renders accordion |
| `thinking` | Reserved for reasoning model output |

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

---

## Security notes

- API keys entered in the UI are held **in server memory only** — never written to disk, never sent back to the browser
- `run_command` executes with `shell=False` — shell injection via `;`, `&&`, `$(...)` is not possible
- The command allowlist (`git`, `grep`, etc.) is enforced server-side regardless of what the model requests
- Tool results are stored server-side — the frontend sends a `[tool_results_ready]` signal with no data payload, preventing result tampering
- `.env` is gitignored — API keys set via environment variables are never committed
