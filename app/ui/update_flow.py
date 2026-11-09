"""Check GitHub for a newer release and, when the user asks, install it."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from app.ui.jobs import JobRunner
from app.ui.notice import NoticeBar
from app.updates import Release, Updater

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
        if release is None:
            return
        dialog = QProgressDialog("Downloading the update…", "Cancel", 0, 100, self._parent)
        dialog.setMinimumDuration(0)

        def work(report: Callable[[object], None]) -> Path:
            return self._updater.download(
                release, self._folder, lambda done, total: report(DownloadStep(done, total))
            )

        def on_progress(item: object) -> None:
            if isinstance(item, DownloadStep) and item.total > 0:
                dialog.setValue(min(99, item.done * 100 // item.total))

        def on_done(result: object) -> None:
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
            dialog.reset()
            QMessageBox.warning(self._parent, "The update didn't download", message)

        self._jobs.start(work, on_done=on_done, on_failed=on_failed, on_progress=on_progress)
