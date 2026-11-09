"""Run a copy of Iconbloom with administrator rights, after Windows asks the user.

Only used for shortcuts in folders shared by every user on the PC. The
elevated copy gets a request file, does that one job and exits.
"""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from platform_win.shortcuts import normalize_path

# Working folder for the elevated copy; running from source needs the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ERROR_CANCELLED = 1223


class ElevationDeclinedError(Exception):
    """The user said No to Windows' permission prompt."""


def run_elevated(arguments: Sequence[str]) -> int:
    """Start this app elevated with ``arguments``, wait for it, and return its exit code."""
    import pywintypes
    import win32con
    import win32event
    import win32process
    from win32com.shell import shell, shellcon

    executable = sys.executable
    if getattr(sys, "frozen", False):
        parameters = list(arguments)
    else:
        # From source, run the same interpreter on the package.
        parameters = ["-m", "app.main", *arguments]
    try:
        info = shell.ShellExecuteEx(
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
            lpVerb="runas",
            lpFile=executable,
            lpParameters=subprocess.list2cmdline(parameters),
            lpDirectory=str(PROJECT_ROOT),
            nShow=win32con.SW_HIDE,
        )
    except pywintypes.error as exc:
        if exc.winerror == _ERROR_CANCELLED:
            raise ElevationDeclinedError from exc
        raise OSError(f"could not start the permission helper: {exc.strerror}") from exc
    handle = info["hProcess"]
    win32event.WaitForSingleObject(handle, win32event.INFINITE)
    return int(win32process.GetExitCodeProcess(handle))


def shared_folders() -> list[Path]:
    """The all-users shortcut folders, resolved through the shell."""
    from platform_win.paths import known_folder

    return [known_folder("CommonPrograms"), known_folder("PublicDesktop")]


def is_inside(path: Path, folders: Sequence[Path]) -> bool:
    target = normalize_path(str(path))
    return any(target.startswith(normalize_path(str(f)).rstrip("\\") + "\\") for f in folders)
