from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("logs")
_configured = False


def setup_logging(level_str: str = "WARNING") -> None:
    """
    Configure the 'ai_playground' logger. Call once at startup before any
    other app imports so all modules get the configured logger on first use.

    File handler always captures DEBUG.
    Console handler respects level_str (set LOG_LEVEL=DEBUG in .env for
    full trace in the terminal).
    """
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    log_file = LOG_DIR / f"app_{ts}.log"

    level = getattr(logging, level_str.upper(), logging.WARNING)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)   # file always gets full trace

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(level)        # console respects LOG_LEVEL

    logger = logging.getLogger("ai_playground")
    logger.setLevel(logging.DEBUG)         # handlers decide what to show
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
