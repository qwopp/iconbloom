"""Putting back, at start, the styles an app update reset (Chrome does at every update)."""

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from app.service import Status
from app.ui.main_window import MainWindow
from platform_win.shortcuts import IconLocation
from tests.ui_harness import APPS, Harness, open_window


def _style(harness: Harness, name: str) -> None:
    harness.select(name)
    harness.window.picker.choose(harness.window.picker.cards[3])
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status(name) is Status.THEMED


def _update_resets(harness: Harness, lnk: Path) -> None:
    harness.desktop.link_io.set_icon(lnk, IconLocation(rf"C:\Apps\{lnk.stem}.exe", 0))


def _reopen(harness: Harness) -> MainWindow:
    window = open_window(harness.desktop, harness.updater, harness.qtbot)
    rows = len(APPS) + 1
    harness.qtbot.waitUntil(lambda: window.shortcuts.model.rowCount() == rows, timeout=10_000)
    harness.qtbot.waitUntil(lambda: not window.jobs.busy, timeout=15_000)
    return window


def test_icons_an_update_reset_are_put_back_at_start(harness: Harness) -> None:
    _style(harness, "Arcade")
    _update_resets(harness, harness.lnk("Arcade"))
    assert harness.status("Arcade") is Status.NEEDS_REAPPLY

    window = _reopen(harness)
    harness.qtbot.waitUntil(lambda: harness.status("Arcade") is Status.THEMED, timeout=10_000)
    assert window.reapply_box.isChecked()  # on unless switched off
    assert "Put back 1 icon an app update had reset" in window.statusBar().currentMessage()
    window.close()


def test_switching_it_off_sticks_and_leaves_reset_icons(harness: Harness) -> None:
    _style(harness, "Arcade")
    harness.window.reapply_box.setChecked(False)
    _update_resets(harness, harness.lnk("Arcade"))

    window = _reopen(harness)
    assert not window.reapply_box.isChecked()
    assert harness.status("Arcade") is Status.NEEDS_REAPPLY
    window.close()


def test_shared_shortcuts_are_offered_not_changed(harness: Harness) -> None:
    _style(harness, "Admin Tool")
    _update_resets(harness, harness.desktop.common / "Admin Tool.lnk")

    window = _reopen(harness)
    # No permission prompt nobody asked for: just an offer.
    assert "every user on this PC shares" in window.notice.label.text()
    assert harness.status("Admin Tool") is Status.NEEDS_REAPPLY

    window.settings.shared_shortcuts = "include"  # answer the prompt the button brings up
    put_back = next(b for b in window.notice.findChildren(QPushButton) if b.text() == "Put back")
    put_back.click()
    harness.qtbot.waitUntil(lambda: harness.status("Admin Tool") is Status.THEMED, timeout=10_000)
    window.close()


def test_fix_at_sign_in_is_off_until_ticked_and_revert_all_unticks_it(
    harness: Harness, say_yes: None
) -> None:
    window = harness.window
    action = window.sign_in_action
    assert action.isVisible()
    assert not action.isChecked()  # off by default
    action.trigger()
    assert harness.desktop.sign_in.is_on()

    window.revert_all()
    harness.settle()
    assert not harness.desktop.sign_in.is_on()
    assert not action.isChecked()
