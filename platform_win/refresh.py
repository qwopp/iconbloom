"""Ask Explorer to redraw icons after shortcuts change.

Windows caches icons hard. Telling Explorer exactly which shortcut files
changed is usually enough for the desktop and Start menu. Taskbar pins keep
their own cached copy, so a change there also asks Windows to rebuild its
icon cache; if that still isn't enough, the hard refresh restarts Explorer,
which must only run after the user agrees.

The icon cache lives on disk and outlives Explorer restarts. A pin that has
been on the taskbar for a while has its old picture saved there, and after a
restart the taskbar takes that picture instead of reading the shortcut, so
the hard refresh deletes the cache files while Explorer is closed.
"""

import logging
import subprocess
import time
from collections.abc import Callable, Sequence
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
    """Restart Explorer with an empty icon cache. Briefly hides the taskbar."""
    from platform_win.paths import known_folder

    # Forced, so Explorer can't write its in-memory cache back on the way out.
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=False, timeout=60)
    try:
        clear_icon_cache(known_folder("LocalAppData"))
    finally:
        subprocess.Popen(["explorer.exe"])  # detached: Explorer keeps running after we exit


def icon_cache_files(local_appdata: Path) -> list[Path]:
    """Windows' icon cache: one file from Windows 7 days, and one per icon size since."""
    explorer = local_appdata / "Microsoft" / "Windows" / "Explorer"
    legacy = local_appdata / "IconCache.db"
    return [p for p in (legacy, *sorted(explorer.glob("iconcache_*.db"))) if p.is_file()]


def clear_icon_cache(
    local_appdata: Path,
    *,
    attempts: int = 10,
    wait: Callable[[float], None] = time.sleep,
) -> list[Path]:
    """Delete the icon cache files Explorer has let go of; returns the ones left behind.

    Explorer takes a moment to release them after it is killed, so each file
    gets a few tries. Another program can hold one open too; Windows rebuilds
    whatever is deleted, and anything left only means older icons may linger.
    """
    remaining = icon_cache_files(local_appdata)
    for attempt in range(attempts):
        locked: list[Path] = []
        for path in remaining:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                locked.append(path)
        remaining = locked
        if not remaining or attempt == attempts - 1:
            break
        wait(0.2)
    for path in remaining:
        log.warning("could not delete icon cache file %s", path)
    return remaining
