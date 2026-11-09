"""Rotating log file in the app data folder, plus a last-resort error hook."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_NAME = "iconbloom.log"


def setup_logging(folder: Path, level: int = logging.INFO) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    return path


def log_uncaught(kind: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
    """sys.excepthook replacement: errors go to the log instead of vanishing."""
    logging.getLogger("iconbloom").critical("unexpected error", exc_info=(kind, value, tb))
    sys.__excepthook__(kind, value, tb)
