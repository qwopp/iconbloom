"""User preferences stored in settings.json."""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platform_win.fileio import write_json

log = logging.getLogger(__name__)


@dataclass
class Settings:
    # Asks GitHub for the latest version number at start; the only network request
    # Iconbloom makes. Nothing is downloaded unless the user clicks Update now.
    check_for_updates: bool = True
    # True once the user has switched the check on or off themselves.
    update_check_chosen: bool = False
    # Shortcuts every user shares need a permission prompt: "ask", "include" or "skip".
    shared_shortcuts: str = "ask"
    # True or False once chosen in More > Dark mode; until then, follow Windows.
    dark_mode: bool | None = None
    # The RENDER_VERSION whose "redraw your icons" notice the user said Not now to.
    redraw_declined: int = 0

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable %s: %s", path, exc)
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in raw.items() if k in known}
        # 0.2/0.3 asked first and saved "off" until answered; only an answer counts as a choice.
        if raw.get("asked_about_updates") is True:
            values.setdefault("update_check_chosen", True)
        if not values.get("update_check_chosen"):
            values["check_for_updates"] = True
        return cls(**values)

    def save(self, path: Path) -> None:
        write_json(path, asdict(self))
