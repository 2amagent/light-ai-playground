import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import settings

PERSIST_FILE = Path("conversations.json")


class Conversation:
    def __init__(self, cid: str | None = None):
        self.id = cid or str(uuid.uuid4())
        self.title: str = "New conversation"
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.messages: list[dict] = []
        # ephemeral; not persisted.
        # List of {"id": str, "result_content": str} — one entry per tool call in
        # the last assistant turn. Empty string result_content means still waiting
        # (ask_user fills it when the user answers; auto-tools pre-fill immediately).
        self.pending_tool_calls: list[dict] = []

        # Per-conversation config — set at creation, not changed thereafter
        self.agent_name: str = "example"
        self.model: str = "openai/gpt-4o"
        self.api_key: str = ""      # NOT persisted — stays in memory only
        self.base_url: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "messages": self.messages,
            "agent_name": self.agent_name,
            "model": self.model,
            # api_key intentionally excluded from persistence
            "base_url": self.base_url,
        }


_store: dict[str, Conversation] = {}


def create_conversation(
    agent_name: str = "example",
    model: str = "openai/gpt-4o",
    api_key: str = "",
    base_url: str = "",
) -> Conversation:
    conv = Conversation()
    conv.agent_name = agent_name
    conv.model = model
    conv.api_key = api_key
    conv.base_url = base_url
    _store[conv.id] = conv
    if settings.persist:
        _save()
    return conv


def get_conversation(cid: str) -> Conversation | None:
    return _store.get(cid)


def delete_conversation(cid: str) -> bool:
    if cid in _store:
        del _store[cid]
        if settings.persist:
            _save()
        return True
    return False


def list_conversations() -> list[dict]:
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at,
            "agent_name": c.agent_name,
            "model": c.model,
        }
        for c in sorted(_store.values(), key=lambda c: c.created_at, reverse=True)
    ]


def save_if_persist():
    if settings.persist:
        _save()


def _save():
    data = {cid: c.to_dict() for cid, c in _store.items()}
    PERSIST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(PERSIST_FILE, 0o600)


def _load():
    if settings.persist and PERSIST_FILE.exists():
        try:
            data = json.loads(PERSIST_FILE.read_text(encoding="utf-8"))
            for cid, d in data.items():
                c = Conversation(cid)
                c.title = d.get("title", "Untitled")
                c.created_at = d.get("created_at", datetime.now(timezone.utc).isoformat())
                c.messages = d.get("messages", [])
                c.agent_name = d.get("agent_name", "example")
                c.model = d.get("model", "openai/gpt-4o")
                c.base_url = d.get("base_url", "")
                # api_key not persisted — stays empty after restore
                _store[cid] = c
        except (json.JSONDecodeError, KeyError):
            pass


_load()
