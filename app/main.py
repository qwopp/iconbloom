"""Start Iconbloom.

uv run python -m app.main               # the picker window
uv run python -m app.main --revert-all  # undo everything, no window (used by the uninstaller)
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from app.logs import log_uncaught, setup_logging
from app.service import windows_service
from app.ui import UI_DIR
from app.ui.main_window import MainWindow
from platform_win.backup import BackupCorruptError
from platform_win.paths import default_app_paths
from platform_win.refresh import hard_refresh

log = logging.getLogger("iconbloom")


def load_style(app: QApplication) -> None:
    for font in (UI_DIR / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet((UI_DIR / "style.qss").read_text(encoding="utf-8"))


def run_window() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Iconbloom")
    load_style(app)
    try:
        service = windows_service()
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


def revert_everything() -> int:
    try:
        report = windows_service().revert_all()
    except BackupCorruptError as exc:
        log.error("revert-all refused: %s", exc)
        return 2
    log.info("revert-all restored %d shortcuts", len(report.changed))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="Iconbloom")
    parser.add_argument(
        "--revert-all", action="store_true", help="restore every original icon and exit"
    )
    args = parser.parse_args(argv)
    paths = default_app_paths().ensure()
    setup_logging(paths.logs)
    sys.excepthook = log_uncaught
    return revert_everything() if args.revert_all else run_window()


if __name__ == "__main__":
    sys.exit(main())
