"""Start Iconbloom.

uv run python -m app.main               # the picker window
uv run python -m app.main --revert-all  # undo everything, no window (used by the uninstaller)
uv run python -m app.main --fix-icons   # put back icons app updates reset, no window (at sign-in);
                                        # with the option on, keeps doing it until sign-out
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from app.changes import SKIPPED_EXIT, ChangeReport
from app.elevation import ELEVATED_FLAG, handle_request, requester_paths
from app.keeper import keep_icons
from app.logs import log_uncaught, setup_logging
from app.service import IconService, windows_service
from platform_win import watch
from platform_win.backup import BackupCorruptError
from platform_win.elevate import shared_folders
from platform_win.item_io import windows_item_io
from platform_win.paths import AppPaths, default_app_paths, is_redirected
from platform_win.startup import FIX_ICONS_FLAG

# Qt is loaded only for the window (see pyproject's ruff ignores).
if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

log = logging.getLogger("iconbloom")


def load_style(app: "QApplication") -> None:
    """Fonts and the light stylesheet, which dialogs before the window use too.
    The window switches to dark mode itself if that's the user's setting."""
    from PySide6.QtGui import QFontDatabase

    from app.ui import UI_DIR, palette

    for font in (UI_DIR / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))
    palette.apply(app, palette.LIGHT)


def run_window(paths: AppPaths) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.ui.main_window import MainWindow
    from platform_win.refresh import hard_refresh
    from platform_win.wallpaper import current_wallpaper

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


def _run_headless(
    paths: AppPaths, name: str, change: Callable[[IconService], ChangeReport]
) -> ChangeReport | None:
    """A change with no window: what it left alone goes to the log. None means the
    backup is damaged, so nothing was changed."""
    try:
        report = change(windows_service(paths))
    except BackupCorruptError as exc:
        log.error("%s refused: %s", name, exc)
        return None
    for path, reason in report.skipped:
        log.warning("%s skipped %s: %s", name, path, reason)
    return report


def revert_everything(paths: AppPaths) -> int:
    report = _run_headless(paths, "revert-all", lambda service: service.revert_all())
    if report is None:
        return 2
    log.info(
        "revert-all restored %d shortcuts and taskbar settings %s",
        len(report.changed),
        report.taskbar,
    )
    # The uninstaller deletes the backups only on 0, so anything left themed must not be 0.
    return SKIPPED_EXIT if report.skipped else 0


def fix_reset_icons(paths: AppPaths) -> int:
    """At sign-in: put back the user's own icons an app update reset. With the option
    on, keep doing it whenever a shortcut folder changes, until sign-out or a stop.
    Never a window, a dialog or a permission prompt, and never a new shortcut."""
    keeper = watch.first_keeper()  # held until this returns
    if keeper is None:
        log.info("fix-icons: another copy is already keeping icons")
        return 0
    try:
        service = windows_service(paths)
    except BackupCorruptError as exc:
        log.error("fix-icons refused: %s", exc)
        return 2

    def fix() -> None:
        report = service.reapply(service.scan(store_apps=False), recreate_deleted=False)
        for path, reason in report.skipped:
            log.warning("fix-icons skipped %s: %s", path, reason)
        if report.changed:
            log.info("fix-icons put back %d icons", len(report.changed))

    sign_in = service.sign_in
    try:
        if sign_in is None or not sign_in.is_on():
            fix()  # asked for once, from the command line
        else:
            folders = service.own_folders()
            log.info("fix-icons: keeping icons, watching %d folders", len(folders))
            keep_icons(fix, watch.windows_folder_watch(folders), sign_in.is_on)
    except BackupCorruptError as exc:
        log.error("fix-icons stopped: %s", exc)
        return 2
    return 0


def run_elevated_request(paths: AppPaths, request: Path) -> int:
    """The elevated copy: carry out one request from the normal app, then exit."""
    redirected = [f for f in (paths.root, paths.originals, paths.icons) if is_redirected(f)]
    if redirected:
        # An admin process must not follow a link the user made into another folder.
        log.error("elevated request refused: %s is a link", redirected[0])
        return 2
    try:
        service = IconService(paths, windows_item_io(), roots=[], process_lock=False)
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
