import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import logs, main
from app.choices import Choice
from app.service import IconService
from platform_win.backup import BackupCorruptError
from platform_win.paths import AppPaths
from tests.conftest import load_sample
from tests.test_service import Env


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    env = Env(tmp_path)
    monkeypatch.setattr(main, "default_app_paths", lambda: AppPaths(tmp_path / "Iconbloom"))
    monkeypatch.setattr(main, "windows_service", env.service)
    # setup_logging adds a file handler to the root logger; drop it after the test.
    root = logging.getLogger()
    handlers = list(root.handlers)
    yield env
    for handler in root.handlers[len(handlers) :]:
        handler.close()
        root.removeHandler(handler)
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)


def test_revert_all_flag_restores_everything(env: Env) -> None:
    lnk = env.make("Paint")
    original = lnk.read_bytes()
    service: IconService = env.service()
    target = service.scan()[0]
    image = load_sample("dark")
    service.apply(target, image, image, Choice("kawaii_pink", "sticker"))
    assert lnk.read_bytes() != original

    assert main.main(["--revert-all"]) == 0
    assert lnk.read_bytes() == original
    assert (env.paths.logs / logs.LOG_NAME).exists()


def test_revert_all_flag_refuses_on_corrupt_backup(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> IconService:
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
