import logging
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from app import logs, main
from app.changes import SKIPPED_EXIT
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


def test_elevated_copy_refuses_a_linked_data_folder(tmp_path: Path) -> None:
    real = tmp_path / "elsewhere"
    real.mkdir()
    linked = tmp_path / "Iconbloom"
    linked.symlink_to(real, target_is_directory=True)
    request = tmp_path / "request.json"
    request.write_text('{"action": "revert", "items": []}', encoding="utf-8")
    assert main.run_elevated_request(AppPaths(linked), request) == 2


def test_revert_all_flag_reports_skips(desktop: FakeDesktop) -> None:
    """The uninstaller keeps the backups unless this exits 0, so a skip must not be 0."""
    desktop.make("Admin", folder=desktop.common)
    service = desktop.service()
    service.apply(service.scan()[0], Choice("kawaii_pink", "sticker"), include_shared=True)
    assert len(service.manifest) == 1
    desktop.decline_permission = True
    assert main.main(["--revert-all"]) == SKIPPED_EXIT
    assert len(service.manifest) == 1


def test_uninstaller_deletes_data_only_after_a_clean_revert() -> None:
    script = (Path(__file__).parents[1] / "installer" / "iconbloom.iss").read_text(encoding="utf-8")
    revert = script.index("'--revert-all'")
    gate = script.index("(ResultCode = 0) then", revert)
    assert script.index("DelTree(DataDir", revert) > gate
    assert script.count("DelTree(DataDir") == 1
