"""Changes to shortcuts every user shares, done by an elevated copy of the app.

The normal app writes a request file and starts a copy of itself with
administrator rights (Windows asks the user first). That copy runs
``handle_request``, which trusts nothing in the request: it only touches shortcut
files inside the shared shortcut folders, only changes their icon field,
and only points them at icons in Iconbloom's own folder or back at their
recorded original. So a tampered request can't be used to write anywhere else.
(Folders and Windows' own icons are per-user and never need this helper.)
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from platform_win.elevate import is_inside, run_elevated
from platform_win.fileio import write_json
from platform_win.paths import AppPaths, is_network_path

log = logging.getLogger(__name__)

type Action = Literal["apply", "revert"]

REQUEST_FILE = "elevated-request.json"
RESULT_FILE = "elevated-result.json"
ELEVATED_FLAG = "--elevated"
# The only things in shared folders the helper will ever change.
SHORTCUT_SUFFIXES = frozenset({".lnk", ".url"})


@dataclass
class ElevatedResult:
    changed: list[Path] = field(default_factory=list[Path])
    skipped: list[tuple[Path, str]] = field(default_factory=list[tuple[Path, str]])


@dataclass(frozen=True)
class ElevatedItem:
    shortcut: Path
    # The .ico to apply; None when reverting.
    icon: Path | None = None


class Elevator(Protocol):
    def __call__(self, action: Action, items: Sequence[ElevatedItem]) -> ElevatedResult: ...


class WindowsElevator:
    """Runs a request through an elevated copy of the app, which Windows asks permission for."""

    def __init__(self, paths: AppPaths, launch: Callable[[Sequence[str]], int] = run_elevated):
        self._paths = paths
        self._launch = launch

    def __call__(self, action: Action, items: Sequence[ElevatedItem]) -> ElevatedResult:
        request = self._paths.root / REQUEST_FILE
        result_path = self._paths.root / RESULT_FILE
        result_path.unlink(missing_ok=True)
        write_json(
            request,
            {
                "action": action,
                "items": [
                    {"shortcut": str(i.shortcut), "icon": str(i.icon) if i.icon else None}
                    for i in items
                ],
            },
        )
        try:
            code = self._launch([ELEVATED_FLAG, str(request)])
        finally:
            request.unlink(missing_ok=True)
        if code != 0 or not result_path.exists():
            raise OSError(f"the permission helper failed (exit code {code}); see the log")
        try:
            return read_result(result_path)
        finally:
            result_path.unlink(missing_ok=True)


def read_result(path: Path) -> ElevatedResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ElevatedResult(
        changed=[Path(p) for p in raw["changed"]],
        skipped=[(Path(p), str(why)) for p, why in raw["skipped"]],
    )


class ElevatedWork(Protocol):
    """What the elevated copy needs from IconService."""

    @property
    def paths(self) -> AppPaths: ...

    def apply_files(self, items: Sequence[tuple[Path, Path]]) -> ElevatedResult: ...

    def restore_icon_fields(self, shortcuts: Sequence[Path]) -> ElevatedResult: ...


def handle_request(request_path: Path, work: ElevatedWork, shared: Sequence[Path]) -> int:
    """Carry out a request inside the elevated copy. Returns the process exit code."""
    try:
        raw = json.loads(request_path.read_text(encoding="utf-8"))
        action = raw["action"]
        items = [(Path(i["shortcut"]), i.get("icon")) for i in raw["items"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.error("unreadable elevated request %s: %s", request_path, exc)
        return 2

    allowed: list[tuple[Path, Path | None]] = []
    result = ElevatedResult()
    for shortcut, icon in items:
        problem = _check(shortcut, icon, action, work.paths, shared)
        if problem:
            log.warning("refused elevated %s of %s: %s", action, shortcut, problem)
            result.skipped.append((shortcut, problem))
        else:
            allowed.append((shortcut, Path(icon) if icon else None))

    if action == "apply":
        done = work.apply_files([(s, i) for s, i in allowed if i is not None])
    else:
        done = work.restore_icon_fields([s for s, _ in allowed])
    result.changed += done.changed
    result.skipped += done.skipped
    write_json(
        work.paths.root / RESULT_FILE,
        {
            "changed": [str(p) for p in result.changed],
            "skipped": [[str(p), why] for p, why in result.skipped],
        },
    )
    return 0


def requester_paths(request: Path) -> AppPaths | None:
    """The data folder of the user who asked, from where their request file sits.

    The elevated copy may run as a different account (a standard user typing an
    administrator's password), so its own %LOCALAPPDATA% would be the wrong
    folder: wrong backups, wrong icons, and a result the app never finds.
    """
    if request.name != REQUEST_FILE or not request.is_absolute() or is_network_path(str(request)):
        return None
    return AppPaths(request.parent)


def _check(
    shortcut: Path, icon: object, action: object, paths: AppPaths, shared: Sequence[Path]
) -> str | None:
    if action not in ("apply", "revert"):
        return "unknown action"
    if shortcut.suffix.casefold() not in SHORTCUT_SUFFIXES or not is_inside(shortcut, shared):
        return "not a shortcut in a shared folder"
    if not shortcut.is_file():
        return "shortcut not found"
    if action == "apply":
        if not isinstance(icon, str) or not is_inside(Path(icon), [paths.icons]):
            return "icon is not one of Iconbloom's"
        if not Path(icon).is_file():
            return "icon file not found"
    return None
