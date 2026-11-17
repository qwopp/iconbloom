"""Start Iconbloom.

uv run python -m app.main               # the picker window
uv run python -m app.main --revert-all  # undo everything, no window (used by the uninstaller)
uv run python -m app.main --fix-icons   # put back icons app updates reset, no window (at sign-in)
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from app.changes import SKIPPED_EXIT
from app.elevation import ELEVATED_FLAG, handle_request, requester_paths
from app.logs import log_uncaught, setup_logging
from app.service import IconService, windows_service
from app.ui import UI_DIR, palette
from app.ui.main_window import MainWindow
from platform_win.backup import BackupCorruptError
from platform_win.elevate import shared_folders
from platform_win.item_io import windows_item_io
from platform_win.paths import AppPaths, default_app_paths, is_redirected
from platform_win.refresh import hard_refresh
from platform_win.startup import FIX_ICONS_FLAG
from platform_win.wallpaper import current_wallpaper

log = logging.getLogger("iconbloom")

# The sign-in run and a window are two processes that would both write the backup.
# A window holds WINDOW_LOCK while open, and the sign-in run leaves the work to it;
# the sign-in run holds FIX_LOCK while it works, and a window opening then waits for it.
WINDOW_LOCK = "window.lock"
FIX_LOCK = "fix.lock"
FIX_WAIT_MS = 30_000


def load_style(app: QApplication) -> None:
    """Fonts and the light stylesheet, which dialogs before the window use too.
    The window switches to dark mode itself if that's the user's setting."""
    for font in (UI_DIR / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))
    palette.apply(app, palette.LIGHT)


def run_window(paths: AppPaths) -> int:
    window_lock = QLockFile(str(paths.root / WINDOW_LOCK))
    window_lock.tryLock(0)  # held by another window already: that's fine
    fixing = QLockFile(str(paths.root / FIX_LOCK))
    if fixing.tryLock(FIX_WAIT_MS):
        fixing.unlock()
    else:
        log.warning("the sign-in run is still working; opening anyway")
    app = QApplication(sys.argv)
    app.setApplicationName("Iconbloom")
    load_style(app)
    try:
        service = windows_service(paths)
    except BackupCorruptError as exc:
        log.error("refusing to start: %s", exc)
        QMessageBox.critical(
            None,
            "Iconbloom can't read its backup",
            f"{exc}\n\nTo keep your original icons safe, Iconbloom won't change anything "
            "until this file is fixed or restored.",
        )
        return 2
    window = MainWindow(service, hard_refresh=hard_refresh, wallpaper=current_wallpaper)
    window.show()
    log.info("window shown")
    return app.exec()


def revert_everything(paths: AppPaths) -> int:
    try:
        report = windows_service(paths).revert_all()
    except BackupCorruptError as exc:
        log.error("revert-all refused: %s", exc)
        return 2
    log.info(
        "revert-all restored %d shortcuts and taskbar settings %s",
        len(report.changed),
        report.taskbar,
    )
    for path, reason in report.skipped:
        log.warning("revert-all skipped %s: %s", path, reason)
    # The uninstaller deletes the backups only on 0, so anything left themed must not be 0.
    return SKIPPED_EXIT if report.skipped else 0


def fix_reset_icons(paths: AppPaths) -> int:
    """At sign-in: put back the user's own icons an app update reset, then exit.
    Never a window, a dialog or a permission prompt."""
    fixing = QLockFile(str(paths.root / FIX_LOCK))
    if not fixing.tryLock(0):
        return 0
    try:
        window = QLockFile(str(paths.root / WINDOW_LOCK))
        if not window.tryLock(0):
            log.info("fix-icons: a window is open and does this itself")
            return 0
        window.unlock()
        service = windows_service(paths)
        report = service.reapply(service.reset_by_apps(service.scan()))
    except BackupCorruptError as exc:
        log.error("fix-icons refused: %s", exc)
        return 2
    finally:
        fixing.unlock()
    log.info("fix-icons put back %d icons", len(report.changed))
    for path, reason in report.skipped:
        log.info("fix-icons left %s: %s", path, reason)
    return 0


def run_elevated_request(paths: AppPaths, request: Path) -> int:
    """The elevated copy: carry out one request from the normal app, then exit."""
    redirected = [f for f in (paths.root, paths.originals, paths.icons) if is_redirected(f)]
    if redirected:
        # An admin process must not follow a link the user made into another folder.
        log.error("elevated request refused: %s is a link", redirected[0])
        return 2
    try:
        service = IconService(paths, windows_item_io(), roots=[])
        return handle_request(request, service, shared_folders())
    except BackupCorruptError as exc:
        log.error("elevated request refused: %s", exc)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="Iconbloom")
    parser.add_argument(
        "--revert-all", action="store_true", help="restore every original icon and exit"
    )
    parser.add_argument(
        FIX_ICONS_FLAG, action="store_true", help="put back icons app updates reset and exit"
    )
    parser.add_argument(ELEVATED_FLAG, type=Path, metavar="REQUEST", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.elevated is not None:
        return run_elevated(args.elevated)
    paths = default_app_paths().ensure()
    setup_logging(paths.logs)
    sys.excepthook = log_uncaught
    if args.revert_all:
        return revert_everything(paths)
    if args.fix_icons:
        return fix_reset_icons(paths)
    return run_window(paths)


def run_elevated(request: Path) -> int:
    """The elevated copy works in the requesting user's folder, not its own account's."""
    paths = requester_paths(request)
    if paths is None:
        setup_logging(default_app_paths().ensure().logs)
        log.error("elevated request refused: %s is not a request file", request)
        return 2
    setup_logging(paths.ensure().logs)
    sys.excepthook = log_uncaught
    return run_elevated_request(paths, request)


if __name__ == "__main__":
    sys.exit(main())
