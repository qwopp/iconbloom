"""Start Iconbloom.

uv run python -m app.main               # the picker window
uv run python -m app.main --revert-all  # undo everything, no window (used by the uninstaller)
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from app.elevation import ELEVATED_FLAG, handle_request
from app.logs import log_uncaught, setup_logging
from app.service import IconService, windows_service
from app.ui import UI_DIR, palette
from app.ui.main_window import MainWindow
from platform_win.backup import BackupCorruptError
from platform_win.elevate import shared_folders
from platform_win.item_io import windows_item_io
from platform_win.paths import AppPaths, default_app_paths
from platform_win.refresh import hard_refresh

log = logging.getLogger("iconbloom")


def load_style(app: QApplication, dark: bool = False) -> None:
    """Fonts and stylesheet. The window switches modes later from the user's setting."""
    for font in (UI_DIR / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))
    palette.apply(app, palette.DARK if dark else palette.LIGHT)


def run_window(paths: AppPaths) -> int:
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
    window = MainWindow(service, hard_refresh=hard_refresh)
    window.show()
    log.info("window shown")
    return app.exec()


def revert_everything(paths: AppPaths) -> int:
    try:
        report = windows_service(paths).revert_all()
    except BackupCorruptError as exc:
        log.error("revert-all refused: %s", exc)
        return 2
    log.info("revert-all restored %d shortcuts", len(report.changed))
    return 0


def run_elevated_request(paths: AppPaths, request: Path) -> int:
    """The elevated copy: carry out one request from the normal app, then exit."""
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
    parser.add_argument(ELEVATED_FLAG, type=Path, metavar="REQUEST", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    paths = default_app_paths().ensure()
    setup_logging(paths.logs)
    sys.excepthook = log_uncaught
    if args.elevated is not None:
        return run_elevated_request(paths, args.elevated)
    return revert_everything(paths) if args.revert_all else run_window(paths)


if __name__ == "__main__":
    sys.exit(main())
