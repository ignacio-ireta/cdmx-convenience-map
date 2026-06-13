"""Logging setup (engineering standards §I).

Console output via rich; an optional per-run file handler writes
``runs/<run_id>/run.log``. Privacy (§P): callers must not log raw crime/victim
rows or full PII coordinates — source URLs and counts only.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from rich.logging import RichHandler

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def resolve_level(level: str | None) -> int:
    name = (level or os.environ.get("CDMXMAP_LOG_LEVEL") or "info").strip().lower()
    return _LEVELS.get(name, logging.INFO)


def setup_logging(level: str | None = None, *, log_file: Path | None = None) -> None:
    """Configure root logging. Idempotent: clears existing handlers first."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(resolve_level(level))

    console = RichHandler(rich_tracebacks=True, show_path=False, markup=False)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
        )
        root.addHandler(file_handler)
