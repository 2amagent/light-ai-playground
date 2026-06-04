# AI Playground

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![By The 2 a.m. Agent](https://img.shields.io/badge/by-The%202%20a.m.%20Agent-8b5cf6)](https://2amagent.com)

A local developer tool for experimenting with LLM agents across multiple providers. Create agents by writing markdown files, launch the server, and get a chat interface in your browser.

## Why this playground?

Most chat playgrounds are wrappers around a single API call. This one is built for **agent experimentation** — where the model takes actions, asks clarifying questions, and works with your local environment.

**The model can ask you structured questions mid-conversation.**
The `ask_user` tool lets an agent pause and present you with a choice card before proceeding — single or multi-select. This is closer to a real agentic workflow than a back-and-forth chat, and it's something you won't find in typical playgrounds.

**Your private and intranet models work out of the box.**
Point the Base URL field at any OpenAI-compatible endpoint — a model running on your own server, behind a VPN, or on a local Ollama instance. No traffic leaves your network. Cloud playgrounds can't do this by definition.

**Tool results never leave the server.**
When an agent runs a shell command or executes a tool, the output is stored server-side and injected directly into the next LLM call. It never round-trips through your browser. Sensitive codebase contents stay where they are.

**Agents are markdown files, hot-reloaded.**
Edit a system prompt in your editor and the next message picks it up — no restart, no form submission, no redeploy. Rapid agent iteration with no friction.

**Each conversation is independently configured.**
Different agent, model, provider, and API key per conversation — all open simultaneously in the same session. Switch between GPT-4o and Claude mid-session without touching settings.

**Zero frontend setup.**
`uv sync` and `uv run python main.py` is everything. Single HTML file, no Node.js, no npm, no bundler. Gradio and Chainlit both require more ceremony to get running and customise.

**Real local tool execution, safely.**
Agents can run `git`, `grep`, `find`, `cat` and a handful of other shell commands against your local filesystem via an explicit allowlist — no Docker, no sandbox configuration. Built for the code-exploration and devops agent use cases.

---

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
git clone git@github.com:2amagent/light-ai-playground.git
cd light-ai-playground
uv sync
uv run main.py
```

The browser opens automatically. Click **New Chat** to start a conversation — you'll be asked which agent to use and what model.

API keys are entered per-conversation in the UI. Alternatively, set them as environment variables (via export or in the .env file) and leave the UI field blank:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
uv run main.py
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

> **Conversations are not persisted by default.** Restarting the server clears all conversation history. Set `PERSIST=true` to save conversations to `conversations.json` so they survive restarts. Note that API keys are never written to disk regardless of this setting.

None of these are required — defaults work out of the box.

---

## Creating an agent

### Via the UI

Click **✎ Edit Agents** in the sidebar → **+ New Agent**. Fill in:
- **Name** — used as the folder name under `agents/`
- **Description** — shown in the New Conversation dropdown
- **System Prompt** — the agent's core instructions
- **User Prompt** — (optional) text prepended to every user message
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
- `working_dir` — optional path within the project root to run from
- `max_lines` — output line limit (default 200, max 1000)

The agent receives the output and continues the conversation. The result is stored server-side — it never round-trips through the browser.

### `ask_user`

Lets the agent ask a structured question with predefined options. The UI renders a choice card (single-select or multi-select). The agent continues after the user picks an option.

---

## Creating a new tool

Tools are self-contained modules that plug into the registry with no changes to core files.

### 1. Create `app/tools/your_tool.py`

```python
from app.events import EVT_TOOL_RESULT
from .base import ToolResult
from .registry import registry

MY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "A clear description of what this tool does and when to use it.",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "The input to process.",
                },
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

**`ToolResult` fields:**
- `evt_type` — always `EVT_TOOL_RESULT` for standard tools
- `payload` — sent to the browser for display (accordion in the UI); `content` is what's shown, `is_error` controls styling
- `result_content` — stored server-side and injected into the LLM's message history; the browser never sees this value

If the tool should pause and wait for user input (like `ask_user`), set `result_content=""` initially — `api.py` will fill it from the user's next message.

### 2. Register in `app/tools/__init__.py`

```python
from app.tools import ask_user, run_command, your_tool  # noqa: F401
```

### 3. Add to an agent's `tools.md`

```
# agents/my-agent/tools.md
my_tool
```

Only agents that list the tool in `tools.md` will have access to it. No other files need to change — `streaming.py`, `api.py`, and `events.py` pick it up automatically.

### Error handling

Return a `ToolResult` with `is_error=True` for recoverable failures — the LLM will see the error message and can decide how to proceed:

```python
return ToolResult(
    evt_type=EVT_TOOL_RESULT,
    payload={"tool_call_id": tool_call_id, "content": "Something went wrong: reason", "is_error": True},
    result_content="Something went wrong: reason",
)
```

---

For architecture details, SSE event types, debugging, and security implementation notes, see [TECHNICAL.md](TECHNICAL.md).

---

Made with ☕ by [The 2 a.m. Agent](https://2amagent.com) · [MIT License](LICENSE)
