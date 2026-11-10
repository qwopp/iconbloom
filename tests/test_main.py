import logging
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from app import logs, main
from app.choices import Choice
from app.service import IconService
from app.taskbar import TaskbarChoice
from platform_win.backup import BackupCorruptError
from platform_win.paths import AppPaths
from tests.fakes import FakeDesktop


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDesktop]:
    """A fake desktop that app.main's Windows wiring is pointed at."""
    env = FakeDesktop(tmp_path)
    monkeypatch.setattr(main, "default_app_paths", lambda: env.paths)
    monkeypatch.setattr(main, "windows_service", lambda paths: env.service())
    # setup_logging adds a file handler to the root logger; drop it after the test.
    root = logging.getLogger()
    handlers = list(root.handlers)
    yield env
    for handler in root.handlers[len(handlers) :]:
        handler.close()
        root.removeHandler(handler)
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)


def test_revert_all_flag_restores_everything(desktop: FakeDesktop) -> None:
    lnk = desktop.make("Paint")
    original = lnk.read_bytes()
    service = desktop.service()
    service.apply(service.scan()[0], Choice("kawaii_pink", "sticker"))
    assert lnk.read_bytes() != original

    taskbar = desktop.taskbar
    before = taskbar.state()
    current = service.taskbar.current() if service.taskbar else None
    assert current is not None
    assert service.taskbar is not None
    service.taskbar.apply(replace(current, color=(90, 40, 80)), TaskbarChoice("x", "deep"))
    assert taskbar.state() != before

    assert main.main(["--revert-all"]) == 0
    assert lnk.read_bytes() == original
    assert taskbar.state() == before
    assert (desktop.paths.logs / logs.LOG_NAME).exists()


def test_revert_all_flag_refuses_on_corrupt_backup(
    desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(paths: AppPaths) -> IconService:
        raise BackupCorruptError("backup.json can't be read")

    monkeypatch.setattr(main, "windows_service", broken)
    assert main.main(["--revert-all"]) == 2


def test_uncaught_errors_are_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        with caplog.at_level(logging.CRITICAL):
            logs.log_uncaught(RuntimeError, exc, exc.__traceback__)
    assert "unexpected error" in caplog.text
