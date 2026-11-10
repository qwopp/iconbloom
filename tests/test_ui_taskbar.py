"""The Taskbar page, driven through the real window against a fake taskbar."""

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from app.ui.taskbar_page import TaskbarPage
from platform_win import taskbar as tb
from tests.fakes import USER_TASKBAR, FakeTaskbar
from tests.ui_harness import FakeUpdater, Harness, open_window


def _open(harness: Harness) -> TaskbarPage:
    harness.window.page_buttons[1].click()
    page = harness.window.taskbar_page
    assert page is not None
    harness.settle()
    return page


def _pick(page: TaskbarPage, look_id: str) -> None:
    card = next(c for c in page.cards if c.look.id == look_id)
    card.clicked.emit(card)


def _preview(page: TaskbarPage) -> bytes:
    return bytes(page.preview.pixmap().toImage().constBits())


def test_switching_pages_keeps_the_icon_selection(harness: Harness) -> None:
    harness.select("Browser")
    page = _open(harness)
    assert harness.window.pages.currentWidget() is page
    assert [c.look.label for c in page.cards] == ["Soft", "Deep", "Windows default"]
    harness.window.page_buttons[0].click()
    assert harness.window.pages.currentIndex() == 0
    current = harness.window.shortcuts.current_group()
    assert current is not None
    assert current.name == "Browser"


def test_starts_from_the_taskbar_as_it_is(harness: Harness) -> None:
    page = _open(harness)
    selected = [c.look.id for c in page.cards if c.property("selected")]
    assert selected == ["windows"]  # the fake taskbar shows Windows' own color
    assert page.centered.isChecked()
    assert not page.frosted.isChecked()
    assert page.search.currentText() == "Search box"
    assert not page.apply_button.isEnabled()
    assert not page.revert_button.isEnabled()


def test_controls_only_change_the_picture(harness: Harness) -> None:
    page = _open(harness)
    before = harness.desktop.taskbar.state()
    picture = _preview(page)
    _pick(page, "deep")
    page.left.setChecked(True)
    assert _preview(page) != picture
    assert page.apply_button.isEnabled()
    assert "accent color" in page.note.text()
    assert harness.desktop.taskbar.state() == before


def test_apply_then_revert(harness: Harness) -> None:
    page = _open(harness)
    before = harness.desktop.taskbar.state()
    _pick(page, "soft")
    page.frosted.setChecked(True)
    page.auto_hide.setChecked(True)
    page.apply_button.click()
    harness.settle()
    values = harness.desktop.taskbar.registry.values
    assert values[tb.ACCENT_ON_TASKBAR] == (tb.REG_DWORD, 1)
    assert values[tb.TRANSPARENCY] == (tb.REG_DWORD, 1)
    assert harness.desktop.taskbar.appbar.hidden
    assert harness.window.statusBar().currentMessage() == "Taskbar updated"
    assert not page.apply_button.isEnabled()  # it now looks like this
    assert page.revert_button.isEnabled()
    assert [c.look.id for c in page.cards if c.property("selected")] == ["soft"]

    page.revert_button.click()
    harness.settle()
    assert harness.desktop.taskbar.state() == before
    assert harness.window.statusBar().currentMessage() == "Taskbar back the way it was"
    assert not page.revert_button.isEnabled()


def test_theme_change_updates_the_looks(harness: Harness) -> None:
    page = _open(harness)
    _pick(page, "soft")
    pink = page.wanted().color
    box = harness.window.theme_box
    box.setCurrentIndex(box.findData("mint_matcha"))
    assert page.heading.text() == "Looks for Mint Matcha"
    assert [c.look.id for c in page.cards if c.property("selected")] == ["soft"]
    assert page.wanted().color != pink


def test_revert_all_puts_the_taskbar_back(harness: Harness, say_yes: None) -> None:
    page = _open(harness)
    before = harness.desktop.taskbar.state()
    _pick(page, "deep")
    page.apply_button.click()
    harness.settle()
    assert harness.desktop.taskbar.state() != before
    harness.window.revert_all()
    harness.settle()
    assert harness.desktop.taskbar.state() == before
    assert "and the taskbar" in harness.window.statusBar().currentMessage()
    assert not page.revert_button.isEnabled()


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
def test_light_windows_asks_before_turning_dark(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, answer: QMessageBox.StandardButton
) -> None:
    harness.desktop.taskbar.registry.values[tb.LIGHT_MODE] = (tb.REG_DWORD, 1)
    page = _open(harness)
    asked: list[str] = []

    def question(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        asked.append(str(args[1]))
        return answer

    monkeypatch.setattr(QMessageBox, "question", question)
    _pick(page, "soft")
    assert "dark mode" in page.note.text()
    page.apply_button.click()
    harness.settle()
    assert asked == ["Switch Windows to dark mode?"]
    light = harness.desktop.taskbar.registry.values[tb.LIGHT_MODE]
    assert light == (tb.REG_DWORD, 1 if answer == QMessageBox.StandardButton.No else 0)


def test_windows_10_hides_what_it_lacks(harness: Harness, qtbot: QtBot) -> None:
    harness.desktop.taskbar = FakeTaskbar(USER_TASKBAR, win11=False)
    window = open_window(harness.desktop, FakeUpdater(), qtbot)
    window.page_buttons[1].click()
    page = window.taskbar_page
    assert page is not None
    assert page.centered.isHidden()
    assert page.left.isHidden()
    assert page.search.findText("Search button") == -1
    qtbot.waitUntil(lambda: not window.jobs.busy, timeout=15_000)
    window.close()


def test_no_taskbar_page_without_a_taskbar(harness: Harness, qtbot: QtBot) -> None:
    window = open_window(harness.desktop, FakeUpdater(), qtbot)
    window.service.taskbar = None
    window.show_taskbar()
    assert window.taskbar_page is None
    window.close()


def test_a_failed_apply_explains_and_can_be_reverted(harness: Harness) -> None:
    page = _open(harness)
    before = harness.desktop.taskbar.state()
    harness.desktop.taskbar.registry.fail_after = 2
    _pick(page, "deep")
    page.apply_button.click()
    harness.settle()
    assert len(harness.messages) == 1
    assert "put back with Revert" in harness.messages.pop()
    harness.desktop.taskbar.registry.fail_after = None
    assert page.revert_button.isEnabled()
    page.revert_button.click()
    harness.settle()
    assert harness.desktop.taskbar.state() == before
