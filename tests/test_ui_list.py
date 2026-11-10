"""The shortcut list: search, place tabs and rescanning."""

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from app.changes import Status
from app.ui.shortcut_list import Thumbnail
from app.ui.widgets import STATUS_ROLE
from platform_win.shortcuts import IconLocation, Place, ShortcutGroup
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


def _tile_status(harness: Harness, name: str) -> str:
    model = harness.window.shortcuts.model
    row = next(r for r in range(model.rowCount()) if model.item(r).text() == name)
    return str(model.item(row).data(STATUS_ROLE))


def test_a_scan_from_before_a_change_does_not_undo_it(
    harness: Harness, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Switching back to the window starts a scan; Apply right after must still show."""
    window = harness.window
    real_scan = harness.service.scan
    # The stale scan saw a shortcut that is gone by now, so its list differs.
    harness.desktop.make("Camera")
    before = real_scan()
    harness.lnk("Camera").unlink()
    started, release = threading.Event(), threading.Event()
    calls = 0

    def slow_scan() -> list[ShortcutGroup]:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            release.wait(5)
            return before  # what the folders looked like before the change
        return real_scan()

    harness.select("Arcade")
    window.picker.choose(window.picker.cards[3])
    monkeypatch.setattr(harness.service, "scan", slow_scan)
    window.shortcuts.rescan()
    assert started.wait(5)
    window.apply_chosen()
    qtbot.waitUntil(lambda: not window.changes.running and calls >= 1)
    release.set()
    harness.settle()
    harness.settle()
    assert _tile_status(harness, "Arcade") == str(Status.THEMED)
    assert "Camera" not in [g.name for g in window.shortcuts.groups]


def test_needs_reapply_can_be_reverted(harness: Harness) -> None:
    window = harness.window
    harness.select("Arcade")
    window.picker.choose(window.picker.cards[3])
    window.apply_chosen()
    harness.settle()
    # An app update rewrites the shortcut with its own icon again.
    lnk = harness.lnk("Arcade")
    harness.desktop.link_io.set_icon(lnk, IconLocation(r"C:\Apps\Arcade.exe", 0))
    window.shortcuts.reload()
    harness.settle()
    harness.select("Arcade")
    assert harness.status("Arcade") is Status.NEEDS_REAPPLY
    assert window.picker.revert_button.isEnabled()
    window.revert_selected()
    harness.settle()
    assert harness.status("Arcade") is Status.ORIGINAL


def test_an_older_thumbnail_does_not_replace_a_newer_one(harness: Harness) -> None:
    shortcuts = harness.window.shortcuts
    arcade = next(g for g in shortcuts.groups if g.name == "Arcade")
    shortcuts.refresh_group(arcade)  # asks for a newer thumbnail than the startup one
    harness.settle()
    model = shortcuts.model
    row = next(r for r in range(model.rowCount()) if model.item(r).text() == "Arcade")
    shown = model.item(row).data(Qt.ItemDataRole.DecorationRole).cacheKey()
    stale = Thumbnail(arcade.key, QImage(8, 8, QImage.Format.Format_ARGB32), token=1)
    shortcuts._on_thumbnail(stale)  # pyright: ignore[reportPrivateUsage]
    assert model.item(row).data(Qt.ItemDataRole.DecorationRole).cacheKey() == shown
