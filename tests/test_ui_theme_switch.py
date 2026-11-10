"""Switching themes changes every preview after it, including the next icon's."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from app.styles import Styles
from engine.themes import DEFAULT_THEME, Theme, ThemeError, load_theme
from tests.fakes import FakeDesktop
from tests.ui_harness import FakeUpdater, Harness, open_window

SECOND = "lavender_dream"


def test_next_icon_after_apply_uses_the_new_theme(harness: Harness) -> None:
    window = harness.window
    window.theme_box.setCurrentIndex(window.theme_box.findData(SECOND))
    harness.wait_for_previews()
    labels = {r.label for r in load_theme(SECOND).recipes}
    assert {c.label for c in window.picker.cards} <= labels
    window.picker.choose(window.picker.cards[1])
    window.apply_chosen()
    harness.settle()
    harness.select("Browser")
    harness.wait_for_previews()
    assert all(c.choice.theme == SECOND for c in window.picker.cards)


def test_a_broken_theme_keeps_the_window_on_a_working_one(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = harness.window
    real = window.service.styles.theme

    def theme(theme_id: str) -> Theme:
        if theme_id == SECOND:
            raise ThemeError("lavender_dream/theme.json: isn't UTF-8 text; save it as UTF-8")
        return real(theme_id)

    monkeypatch.setattr(window.service.styles, "theme", theme)
    before = window.theme_box.currentData()
    window.theme_box.setCurrentIndex(window.theme_box.findData(SECOND))
    assert "UTF-8" in harness.messages.pop()
    assert window.theme_box.currentData() == before
    harness.wait_for_previews()
    assert all(c.choice.theme == before for c in window.picker.cards)


def test_a_broken_default_theme_still_opens_the_window(
    tmp_path: Path, qtbot: QtBot, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Styles.theme

    def theme(self: Styles, theme_id: str) -> Theme:
        if theme_id == DEFAULT_THEME:
            raise ThemeError("kawaii_pink/theme.json: invalid JSON")
        return real(self, theme_id)

    monkeypatch.setattr(Styles, "theme", theme)
    window = open_window(FakeDesktop(tmp_path), FakeUpdater(), qtbot)
    assert window.theme_box.currentData() != DEFAULT_THEME
    assert "couldn't be loaded" in window.notice.label.text()
    qtbot.waitUntil(lambda: not window.jobs.busy, timeout=5_000)
    window.close()
