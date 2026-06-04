#!/usr/bin/env python3
"""
AI Playground
Usage: uv run python main.py
"""
import os
import sys
import threading
import time
import webbrowser

try:
    from app.config import settings
except Exception as e:
    print(f"\n  ERROR: Configuration failed\n  {e}\n")
    print("  Make sure you have a .env file. Copy .env.example to get started:\n")
    print("    cp .env.example .env\n")
    sys.exit(1)

from app.logging_setup import setup_logging
setup_logging(settings.log_level)

import uvicorn
from app.api import app  # noqa: F401


def _open_browser(url: str, delay: float = 1.5):
    time.sleep(delay)
    webbrowser.open(url)


def _watch_for_restart():
    """Background thread: type R + Enter to restart the process."""
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == "R":
            print("\n  Restarting...\n")
            os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    url = f"http://{settings.host}:{settings.port}"

    print()
    print("  AI Playground")
    print(f"  URL   : {url}")
    print("  by The 2 a.m. Agent · https://2amagent.com")
    if settings.persist:
        print("  Persist: on (conversations.json)")
    print()

    if settings.auto_open_browser and settings.host in ("127.0.0.1", "localhost"):
        t = threading.Thread(target=_open_browser, args=(url,), daemon=True)
        t.start()

    threading.Thread(target=_watch_for_restart, daemon=True).start()
    print("  Press R + Enter to restart\n")

    uvicorn.run(
        "app.api:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="warning",
    )
