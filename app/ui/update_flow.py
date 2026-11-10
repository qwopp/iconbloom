"""Check GitHub for a newer release and, when the user asks, install it."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from app.ui.jobs import JobRunner
from app.ui.notice import NoticeBar
from app.updates import Release, Updater, clear_downloads

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadStep:
    done: int
    total: int


class UpdateFlow:
    def __init__(
        self,
        parent: QWidget,
        jobs: JobRunner,
        notice: NoticeBar,
        updater: Updater,
        download_folder: Path,
        *,
        close_app: Callable[[], object],
    ) -> None:
        self._parent = parent
        self._jobs = jobs
        self._notice = notice
        self._updater = updater
        self._folder = download_folder
        self._close_app = close_app
        self._release: Release | None = None
        self._downloading = False
        # Installers from earlier updates have done their job by now.
        jobs.start(lambda _report: clear_downloads(download_folder))

    def check(self) -> None:
        self._jobs.start(lambda _report: self._updater.check(), on_done=self._on_checked)

    def _on_checked(self, result: object) -> None:
        if not isinstance(result, Release):
            return
        self._release = result
        self._notice.show_message(
            f"Iconbloom {result.version} is ready to install. Your icons and backups stay "
            "as they are.",
            [
                ("Update now", self.install, "Download, check and install the update"),
                (
                    "What's new",
                    lambda: QDesktopServices.openUrl(QUrl(result.url)),
                    "Open the release notes in your browser",
                ),
            ],
        )

    def install(self) -> None:
        """Download the installer, verify it, start it and close so it can replace the app."""
        release = self._release
        if release is None or self._downloading:
            return
        self._downloading = True
        dialog = QProgressDialog("Downloading the update…", "Cancel", 0, 100, self._parent)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        stop = threading.Event()
        dialog.canceled.connect(stop.set)

        def step(done: int, total: int, report: Callable[[object], None]) -> bool:
            report(DownloadStep(done, total))
            return not stop.is_set()

        def work(report: Callable[[object], None]) -> Path:
            return self._updater.download(
                release, self._folder, lambda done, total: step(done, total, report)
            )

        def on_progress(item: object) -> None:
            if isinstance(item, DownloadStep) and item.total > 0:
                dialog.setValue(min(99, item.done * 100 // item.total))

        def on_done(result: object) -> None:
            self._downloading = False
            cancelled = dialog.wasCanceled()
            dialog.reset()
            if cancelled or not isinstance(result, Path):
                return
            try:
                self._updater.launch(result)
            except OSError as exc:
                log.exception("could not start the installer")
                QMessageBox.warning(self._parent, "The update didn't start", str(exc))
                return
            self._close_app()  # the installer replaces the app's files once it has closed

        def on_failed(message: str) -> None:
            self._downloading = False
            cancelled = stop.is_set()
            dialog.reset()
            if not cancelled:
                QMessageBox.warning(self._parent, "The update didn't download", message)

        self._jobs.start(work, on_done=on_done, on_failed=on_failed, on_progress=on_progress)
