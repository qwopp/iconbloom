"""Update checks and one-click updates."""

from pathlib import Path

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDesktop
from tests.ui_harness import RELEASE, FakeUpdater, Harness, open_window


def test_first_launch_checks_for_updates_without_asking(
    tmp_path: Path, qtbot: QtBot, qapp: QApplication
) -> None:
    desktop = FakeDesktop(tmp_path)
    updater = FakeUpdater()
    updater.release = RELEASE
    window = open_window(desktop, updater, qtbot)
    assert window.update_box.isChecked()
    qtbot.waitUntil(lambda: "ready to install" in window.notice.label.text(), timeout=5_000)
    window.close()


def test_switching_update_checks_off_sticks(
    tmp_path: Path, qtbot: QtBot, qapp: QApplication
) -> None:
    desktop = FakeDesktop(tmp_path)
    updater = FakeUpdater()
    window = open_window(desktop, updater, qtbot)
    window.update_box.setChecked(False)
    window.close()

    updater.release = RELEASE
    window = open_window(desktop, updater, qtbot)
    assert not window.update_box.isChecked()
    qtbot.wait(100)
    assert not window.notice.isVisible()
    window.close()


def test_update_downloads_installs_and_closes(harness: Harness) -> None:
    harness.updater.release = RELEASE
    harness.window.updates.check()  # what happens at every launch
    harness.qtbot.waitUntil(
        lambda: "9.9.9 is ready" in harness.window.notice.label.text(), timeout=5_000
    )
    harness.window.updates.install()
    harness.qtbot.waitUntil(lambda: bool(harness.updater.launched), timeout=5_000)
    assert harness.updater.launched[0].name == "Iconbloom-Setup-9.9.9.exe"
    assert not harness.window.isVisible()
