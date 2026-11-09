"""Background work: run a function on a thread pool and hear back on the UI thread."""

import logging
from collections.abc import Callable
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)

# ``work`` receives a callback for reporting progress items as it goes.
type Work = Callable[[Callable[[object], None]], object]


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class Job(QRunnable):
    def __init__(self, work: Work) -> None:
        super().__init__()
        self.signals = JobSignals()
        self._work = work

    @override
    def run(self) -> None:
        try:
            result = self._work(self.signals.progress.emit)
        except Exception as exc:  # reported to the UI; the worker thread must not die silently
            log.exception("background job failed")
            self.signals.failed.emit(str(exc))
            return
        self.signals.done.emit(result)


class JobRunner(QObject):
    """Owns the thread pool and keeps each running job alive until it reports back."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._jobs: set[Job] = set()

    @property
    def busy(self) -> bool:
        return bool(self._jobs)

    def start(
        self,
        work: Work,
        *,
        on_done: Callable[[object], None] | None = None,
        on_failed: Callable[[str], None] | None = None,
        on_progress: Callable[[object], None] | None = None,
    ) -> None:
        """Run ``work`` in the background; handlers run on the UI thread.

        Handlers are connected before the job starts: a job that finishes
        straight away would otherwise report to nobody.
        """
        job = Job(work)
        job.setAutoDelete(False)
        self._jobs.add(job)
        if on_progress is not None:
            job.signals.progress.connect(on_progress)
        if on_done is not None:
            job.signals.done.connect(on_done)
        if on_failed is not None:
            job.signals.failed.connect(on_failed)
        job.signals.done.connect(lambda _result: self._jobs.discard(job))
        job.signals.failed.connect(lambda _message: self._jobs.discard(job))
        self._pool.start(job)

    def wait(self, msecs: int = 30_000) -> bool:
        return self._pool.waitForDone(msecs)

    def shutdown(self) -> None:
        """Drop queued jobs and give running ones a moment to finish."""
        self._pool.clear()
        self._pool.waitForDone(5_000)
