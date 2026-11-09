"""Ask Explorer to redraw icons after shortcuts change.

Windows caches icons hard. Telling Explorer exactly which shortcut files
changed is usually enough for the desktop and Start menu. Taskbar pins keep
their own cached copy, so a change there also asks Windows to rebuild its
icon cache; if that still isn't enough, the hard refresh restarts Explorer,
which must only run after the user agrees.
"""

import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger(__name__)

_PINNED_FOLDER = "user pinned"


def notify_icons_changed(paths: Sequence[Path] = ()) -> None:
    from win32com.shell import shell, shellcon

    for path in paths:
        try:
            shell.SHChangeNotify(shellcon.SHCNE_UPDATEITEM, shellcon.SHCNF_PATHW, str(path), None)
        except (TypeError, ValueError) as exc:
            log.debug("per-item refresh failed for %s: %s", path, exc)
    shell.SHChangeNotify(shellcon.SHCNE_ASSOCCHANGED, shellcon.SHCNF_IDLIST, None, None)
    if any(touches_taskbar(p) for p in paths):
        rebuild_icon_cache()


def touches_taskbar(path: Path) -> bool:
    """True for shortcuts pinned to the taskbar or Start, which Explorer caches separately."""
    return _PINNED_FOLDER in str(path).casefold()


def rebuild_icon_cache() -> None:
    """Ask Windows to refresh its icon cache without restarting Explorer."""
    subprocess.Popen(["ie4uinit.exe", "-show"])  # detached: nothing to wait for


def hard_refresh() -> None:
    """Rebuild the icon cache and restart Explorer. Briefly hides the taskbar."""
    subprocess.run(["ie4uinit.exe", "-show"], check=False, timeout=60)
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=False, timeout=60)
    subprocess.Popen(["explorer.exe"])  # detached: Explorer keeps running after we exit
