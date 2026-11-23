"""JobRunner: background work reports back on the UI thread, and never to a closed window."""

import threading

from pytestqt.qtbot import QtBot

from app.ui.jobs import JobRunner


def test_a_job_reports_its_result(qtbot: QtBot) -> None:
    jobs = JobRunner()
    results: list[object] = []
    jobs.start(lambda _report: 42, on_done=results.append)
    qtbot.waitUntil(lambda: not jobs.busy)
    assert results == [42]


def test_jobs_that_finish_at_once_still_report(qtbot: QtBot) -> None:
    """A job that finishes before start() returns must not lose its result."""
    jobs = JobRunner()
    results: list[object] = []
    for i in range(50):
        jobs.start(lambda _report, i=i: i, on_done=results.append)
    qtbot.waitUntil(lambda: not jobs.busy)
    assert len(results) == 50
    assert set(results) == set(range(50))


def test_a_failing_job_reports_its_message(qtbot: QtBot) -> None:
    jobs = JobRunner()
    messages: list[str] = []

    def work(_report: object) -> object:
        raise ValueError("broken")

    jobs.start(work, on_failed=messages.append)
    qtbot.waitUntil(lambda: not jobs.busy)
    assert messages == ["broken"]


def test_after_shutdown_a_finishing_job_reports_to_nobody(qtbot: QtBot) -> None:
    jobs = JobRunner()
    release = threading.Event()
    results: list[object] = []

    def work(_report: object) -> object:
        release.wait(5)
        return "late"

    jobs.start(work, on_done=results.append)
    threading.Timer(0.05, release.set).start()
    jobs.shutdown()  # waits for the job, whose result is then queued for the UI thread
    qtbot.wait(50)
    assert results == []


def test_after_shutdown_nothing_new_starts(qtbot: QtBot) -> None:
    jobs = JobRunner()
    jobs.shutdown()
    ran = threading.Event()
    jobs.start(lambda _report: ran.set())
    qtbot.wait(50)
    assert not ran.is_set()
    assert not jobs.busy
