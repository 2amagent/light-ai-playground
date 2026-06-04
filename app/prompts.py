from pathlib import Path
from .config import settings


def _find_md(filename: str, agent_name: str | None = None) -> Path | None:
    name = agent_name or settings.agent_name
    candidates = [
        Path(f"{name}.{filename}"),                          # my-agent.system.md
        Path("agents") / name / filename,                    # agents/my-agent/system.md
        Path("agents") / name / f"{filename}.md",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_system_prompt(agent_name: str | None = None) -> str:
    p = _find_md("system.md", agent_name)
    if not p:
        name = agent_name or settings.agent_name
        raise FileNotFoundError(
            f"No system prompt found for agent '{name}'.\n"
            f"  Create one of:\n"
            f"    {name}.system.md\n"
            f"    agents/{name}/system.md"
        )
    return p.read_text(encoding="utf-8").strip()


def load_user_prompt(agent_name: str | None = None) -> str | None:
    p = _find_md("user.md", agent_name)
    return p.read_text(encoding="utf-8").strip() if p else None


def load_description(agent_name: str | None = None) -> str | None:
    p = _find_md("description.md", agent_name)
    return p.read_text(encoding="utf-8").strip() if p else None


def load_tools_list(agent_name: str | None = None) -> list[str] | None:
    """
    Returns tool names for the given agent from tools.md, or None if absent.
    None means no tools — the caller should send tools=[].
    Hot-reloaded on every call.
    """
    p = _find_md("tools.md", agent_name)
    if not p:
        return None
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names
