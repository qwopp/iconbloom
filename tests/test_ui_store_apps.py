"""Styling a Store app from the window: the themed shortcut, then the pin guide."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from app.service import Status
from app.ui import change_runner
from app.ui.change_runner import pin_guide_text
from platform_win.store_apps import StoreApp
from tests.ui_harness import APPS, Harness

OUTLOOK = "Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows"


class Guides:
    """Records each pin guide instead of showing it, and can press "Show me"."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, show_me: bool = False) -> None:
        self.texts: list[str] = []
        self.shown: list[Path] = []

        # A plain function, so the box it's called on arrives as its argument.
        def fake_exec(box: QMessageBox) -> int:
            self.texts.append(box.text())
            if show_me:
                next(b for b in box.buttons() if b.text() == "Show me").click()
            return 0

        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        monkeypatch.setattr(change_runner, "show_in_explorer", self.shown.append)


def _with_outlook(harness: Harness) -> None:
    harness.desktop.store_apps.apps.append(StoreApp(OUTLOOK, "Outlook"))
    harness.window.shortcuts.rescan()
    rows = len(APPS) + 2
    harness.qtbot.waitUntil(lambda: harness.window.shortcuts.model.rowCount() == rows)
    harness.select("Outlook")


def test_styling_a_store_app_shows_how_to_pin_it(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    guides = Guides(monkeypatch)
    _with_outlook(harness)
    harness.window.apply_chosen()
    harness.settle()
    assert harness.lnk("Outlook").exists()
    assert harness.status("Outlook") is Status.THEMED
    assert len(guides.texts) == 1
    assert "<b>Outlook</b> is on your desktop" in guides.texts[0]
    assert "Pin to taskbar" in guides.texts[0]
    assert guides.shown == []
    current = harness.window.shortcuts.current_group()
    assert current is not None
    assert current.name == "Outlook"
    assert harness.window.picker.revert_button.isEnabled()


def test_show_me_opens_the_desktop_at_the_new_shortcut(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    guides = Guides(monkeypatch, show_me=True)
    _with_outlook(harness)
    harness.window.apply_chosen()
    harness.settle()
    assert guides.shown == [harness.lnk("Outlook")]


def test_ordinary_apps_get_no_pin_guide(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    guides = Guides(monkeypatch)
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED
    assert guides.texts == []


@pytest.mark.parametrize(
    ("names", "start"),
    [
        (["Outlook"], "<p><b>Outlook</b> is on your desktop"),
        (["Outlook", "Game Bar"], "<p><b>Outlook and Game Bar</b> are on your desktop"),
        (["A", "B", "C"], "<p><b>A, B and C</b> are"),
        (["Tom & Jerry"], "<p><b>Tom &amp; Jerry</b>"),
    ],
)
def test_pin_guide_text(names: list[str], start: str) -> None:
    text = pin_guide_text(names)
    assert text.startswith(start)
    assert ("each one" in text) == (len(names) > 1)
