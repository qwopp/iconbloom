"""The shortcut list: search, place tabs and rescanning."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from platform_win.shortcuts import Place, ShortcutGroup
from tests.ui_harness import Harness


def test_search_and_place_tabs_filter_the_grid(harness: Harness) -> None:
    window = harness.window

    def visible() -> list[str]:
        model = window.shortcuts.model
        return [
            model.item(r).text()
            for r in range(model.rowCount())
            if not window.shortcuts.grid.isRowHidden(r)
        ]

    assert visible() == ["Arcade", "Browser", "Music", "Admin Tool"]
    window.shortcuts.search.setText("mu")
    assert visible() == ["Music"]
    assert window.shortcuts.current_group() is not None
    window.shortcuts.search.setText("nothing like this")
    assert visible() == []
    assert window.shortcuts.empty_label.isVisibleTo(window)
    window.shortcuts.search.clear()
    window.shortcuts.place_buttons[Place.START_MENU].click()
    assert visible() == ["Admin Tool"]
    assert window.shortcuts.place_buttons[Place.DESKTOP].text() == "Desktop (3)"


def test_coming_back_to_the_window_picks_up_new_shortcuts(
    harness: Harness, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = harness.window
    scans = 0
    real_scan = harness.service.scan

    def counting_scan() -> list[ShortcutGroup]:
        nonlocal scans
        scans += 1
        return real_scan()

    monkeypatch.setattr(harness.service, "scan", counting_scan)
    harness.select("Browser", "Music")

    # Nothing changed: the grid is left alone, so the multi-selection survives.
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    harness.settle()
    assert scans == 1
    assert [g.name for g in window.shortcuts.selected_groups()] == ["Browser", "Music"]

    # A new desktop shortcut takes its sorted place, and the current icon stays current.
    harness.desktop.make("Camera")
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    harness.settle()
    model = window.shortcuts.model
    names = [model.item(r).text() for r in range(model.rowCount())]
    assert names == ["Arcade", "Browser", "Camera", "Music", "Admin Tool"]
    current = window.shortcuts.current_group()
    assert current is not None
    assert current.name == "Browser"

    # Leaving the app doesn't scan.
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    harness.settle()
    assert scans == 2
