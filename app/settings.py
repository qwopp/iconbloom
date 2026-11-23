"""User preferences stored in settings.json."""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from types import UnionType
from typing import Any, cast, get_type_hints

from platform_win.fileio import json_object, write_json

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
    # At start, put chosen styles back on icons an app update reset (Chrome does this
    # every update). Shared shortcuts are only offered, never changed without asking.
    reapply_at_start: bool = True
    # True once the user said Not now to fixing reset icons automatically.
    auto_fix_declined: bool = False
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
        saved = json_object(raw)
        if saved is None:
            return cls()
        values = {k: v for k, v in saved.items() if _fits(v, _FIELD_TYPES.get(k))}
        # 0.2/0.3 asked first and saved "off" until answered; only an answer counts as a choice.
        if saved.get("asked_about_updates") is True:
            values.setdefault("update_check_chosen", True)
        if not values.get("update_check_chosen"):
            values["check_for_updates"] = True
        return cls(**cast("dict[str, Any]", values))  # each value checked by _fits

    def save(self, path: Path) -> None:
        write_json(path, asdict(self))


# A hand-edited or damaged file can hold anything: a value of the wrong type falls
# back to the default instead of reaching code that expects, say, a bool.
_FIELD_TYPES: dict[str, type | UnionType] = get_type_hints(Settings)


def _fits(value: object, kind: type | UnionType | None) -> bool:
    if kind is None:
        return False  # not a setting (an old or unknown key)
    if isinstance(value, bool) and kind is int:
        return False  # JSON true is not a number of anything
    return isinstance(value, kind)
