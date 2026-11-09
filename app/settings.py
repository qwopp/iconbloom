"""User preferences stored in settings.json. Everything defaults to off."""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platform_win.fileio import write_json

log = logging.getLogger(__name__)


@dataclass
class Settings:
    # Opt-in: checking for updates is the only network request Iconbloom makes.
    check_for_updates: bool = False
    # Whether the user has answered the one-time "check for updates?" question.
    asked_about_updates: bool = False
    # Shortcuts every user shares need a permission prompt: "ask", "include" or "skip".
    shared_shortcuts: str = "ask"

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable %s: %s", path, exc)
            return cls()
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in raw.items() if k in known} if isinstance(raw, dict) else {}
        return cls(**values)

    def save(self, path: Path) -> None:
        write_json(path, asdict(self))
