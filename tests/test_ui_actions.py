"""Applying, skipping, reverting and the permission prompt for shared shortcuts."""

import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QFileDialog, QGridLayout
from pytestqt.qtbot import QtBot

from app.changes import ChangeReport
from app.service import Status
from engine.families import Family
from engine.themes import Theme
from tests.conftest import load_sample
from tests.ui_harness import APPS, Harness, open_window


def test_launch_selects_first_untouched_and_shows_previews(harness: Harness) -> None:
    group = harness.window.shortcuts.current_group()
    assert group is not None
    assert group.name == "Arcade"  # desktop shortcuts first, the shared Admin Tool last
    assert harness.window.picker.apply_button.isEnabled()
    assert not harness.window.picker.revert_button.isEnabled()


def test_apply_themes_shortcut_and_stays_on_it(harness: Harness) -> None:
    picker = harness.window.picker
    picked = picker.cards[3]
    picker.choose(picked)
    before = harness.lnk("Arcade").read_bytes()
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED
    assert harness.lnk("Arcade").read_bytes() != before
    current = harness.window.shortcuts.current_group()
    assert current is not None
    assert current.name == "Arcade"
    # Same previews, the applied style still picked, and the details say so.
    assert picker.chosen is picked
    assert "themed" in picker.detail_label.text()
    assert picker.revert_button.isEnabled()


def test_double_click_applies_and_revert_restores(harness: Harness) -> None:
    before = harness.lnk("Arcade").read_bytes()
    card = harness.window.picker.cards[2]
    card.activated.emit(card)
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED

    harness.select("Arcade")
    assert harness.window.picker.revert_button.isEnabled()
    harness.window.revert_selected()
    harness.settle()
    assert harness.lnk("Arcade").read_bytes() == before
    assert harness.status("Arcade") is Status.ORIGINAL


def test_skip_marks_and_advances(harness: Harness) -> None:
    harness.window.skip_selected()
    assert harness.status("Arcade") is Status.SKIPPED
    current = harness.window.shortcuts.current_group()
    assert current is not None
    assert current.name == "Browser"


def test_revert_all_after_applying_everything(harness: Harness, say_yes: None) -> None:
    names = [*APPS, "Admin Tool"]
    originals = {name: harness.path(name).read_bytes() for name in names}
    harness.window.apply_style_to_all()
    harness.settle()
    assert all(harness.status(name) is Status.THEMED for name in names)
    harness.window.revert_all()
    harness.settle()
    assert harness.status("Admin Tool") is Status.ORIGINAL
    for name in APPS:
        assert harness.path(name).read_bytes() == originals[name]


def _pick_own_image(harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    picture = tmp_path / "kitty.png"
    load_sample("plate_glyph").save(picture)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(picture), "Images")
    )
    harness.window.picker.own_image_button.click()  # the real button, as a person would
    harness.wait_for_previews()


def test_use_own_image_as_it_is(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pick_own_image(harness, tmp_path, monkeypatch)
    picker = harness.window.picker
    assert picker.cards[0].label == "Your image"
    picker.choose(picker.cards[0])
    assert not picker.all_button.isEnabled()
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED


def test_own_image_gets_every_style_and_reverts_exactly(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kawaii: Theme
) -> None:
    before = harness.lnk("Arcade").read_bytes()
    _pick_own_image(harness, tmp_path, monkeypatch)
    picker = harness.window.picker
    labels = [c.label for c in picker.cards]
    assert labels[0] == "Your image"
    cut_outs = [r.label for r in kawaii.recipes if r.family is Family.CUTOUT]
    assert labels[-len(cut_outs) :] == cut_outs
    assert all(c.choice.custom_image == picker.custom_image for c in picker.cards)
    cut_out = picker.cards[-len(cut_outs)]
    picker.choose(cut_out)
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED
    arcade = harness.window.shortcuts.current_group()
    assert arcade is not None
    assert arcade.name == "Arcade"
    assert harness.service.choices.get(arcade.key) == cut_out.choice
    harness.window.revert_selected()
    harness.settle()
    assert harness.lnk("Arcade").read_bytes() == before


def test_cut_out_styles_get_a_row_of_their_own(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pick_own_image(harness, tmp_path, monkeypatch)  # "Your image" first shifts the rest
    first_cut_out = next(c for c in harness.window.picker.cards if c.label == "Cut out")
    host = first_cut_out.parentWidget()
    assert host is not None
    grid = host.layout()
    assert isinstance(grid, QGridLayout)
    position = grid.getItemPosition(grid.indexOf(first_cut_out))
    assert isinstance(position, tuple)
    assert position[1] == 0  # first column


def test_switching_back_to_the_apps_icon(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pick_own_image(harness, tmp_path, monkeypatch)
    picker = harness.window.picker
    assert picker.own_image_button.text() == "Use the app's icon"
    picker.own_image_button.click()
    harness.wait_for_previews()
    assert picker.custom_image is None
    assert not any(c.choice.uses_own_image for c in picker.cards)
    assert picker.own_image_button.text() == "Use my own image…"


def test_own_image_stays_with_its_app(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    _pick_own_image(harness, tmp_path, monkeypatch)
    picker = harness.window.picker
    image = picker.custom_image
    assert image is not None
    harness.select("Browser")
    assert picker.custom_image is None
    assert not any(c.choice.uses_own_image for c in picker.cards)
    harness.select("Arcade")
    assert picker.custom_image == image
    assert picker.cards[0].label == "Your image"
    assert picker.own_image_button.text() == "Use the app's icon"

    # A restart (an update, say) opens on Arcade with the image still in use.
    restarted = open_window(harness.desktop, harness.updater, qtbot)
    qtbot.waitUntil(lambda: bool(restarted.picker.cards), timeout=15_000)
    assert restarted.picker.custom_image == image
    assert restarted.picker.cards[0].label == "Your image"
    restarted.close()


def test_going_back_to_the_apps_icon_survives_a_restart(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    _pick_own_image(harness, tmp_path, monkeypatch)
    harness.window.picker.own_image_button.click()
    harness.wait_for_previews()
    restarted = open_window(harness.desktop, harness.updater, qtbot)
    qtbot.waitUntil(lambda: bool(restarted.picker.cards), timeout=15_000)
    assert restarted.picker.custom_image is None
    restarted.close()


def test_shared_shortcut_is_changed_after_permission(harness: Harness) -> None:
    harness.select("Admin Tool")
    assert harness.window.picker.apply_button.isEnabled()
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Admin Tool") is Status.THEMED
    assert len(harness.desktop.elevations) == 1


def test_shared_shortcut_left_alone_when_declined(harness: Harness) -> None:
    harness.desktop.decline_permission = True
    harness.select("Admin Tool")
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Admin Tool") is Status.ORIGINAL
    assert "Left 1 shared shortcut" in harness.window.statusBar().currentMessage()


def test_remembered_skip_never_asks_for_permission(harness: Harness) -> None:
    harness.window.settings.shared_shortcuts = "skip"
    harness.select("Admin Tool")
    harness.window.apply_chosen()
    harness.settle()
    assert harness.desktop.elevations == []
    assert harness.status("Admin Tool") is Status.ORIGINAL


def test_multi_select_previews_and_applies_to_all(harness: Harness) -> None:
    harness.select("Arcade", "Browser", "Music")
    window = harness.window
    assert window.picker.apply_button.text() == "Apply to 3"
    assert window.picker.selection_strip.isVisibleTo(window)
    harness.qtbot.waitUntil(
        lambda: len(harness.strip_pictures()) == 3 and all(harness.strip_pictures()), timeout=15_000
    )
    window.apply_chosen()
    harness.settle()
    assert all(harness.status(name) is Status.THEMED for name in APPS)
    harness.select("Arcade", "Music")
    window.revert_selected()
    harness.settle()
    assert harness.status("Arcade") is Status.ORIGINAL
    assert harness.status("Music") is Status.ORIGINAL
    assert harness.status("Browser") is Status.THEMED


def test_toolbar_actions(harness: Harness, say_yes: None) -> None:
    harness.window.apply_chosen()
    harness.settle()
    harness.window.reapply_all()
    assert "Nothing needed reapplying" in harness.window.statusBar().currentMessage()
    harness.window.clean_up()
    harness.settle()
    harness.window.refresh_icons()
    harness.settle()
    assert harness.refreshes == 1
    harness.window.theme_box.setCurrentIndex(0)
    harness.wait_for_previews()


def test_errors_become_a_dialog(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk is full")

    monkeypatch.setattr(harness.service, "apply_many", broken)
    harness.window.apply_chosen()
    harness.settle()
    assert len(harness.messages) == 1
    assert "disk is full" in harness.messages.pop()
    assert harness.status("Arcade") is Status.ORIGINAL


def test_every_button_works_when_clicked(harness: Harness, say_yes: None) -> None:
    """Clicking sends Qt's "checked" flag; no handler may mistake it for an argument."""
    window = harness.window
    for button in (
        window.picker.shuffle_button,
        window.picker.skip_button,
        window.picker.apply_button,
        window.picker.revert_button,
        window.picker.all_button,
    ):
        harness.wait_for_previews()
        if button.isEnabled():
            button.click()
            harness.settle()
    for action in window.more_menu.actions():
        action.trigger()
        harness.settle()
    assert harness.refreshes == 1


def test_instant_background_jobs_still_report(harness: Harness) -> None:
    """A job that finishes before its caller returns must not lose its result."""
    results: list[int] = []

    def collect(result: object) -> None:
        assert isinstance(result, int)
        results.append(result)

    for i in range(50):
        harness.window.jobs.start(lambda _report, i=i: i, on_done=collect)
    harness.settle()
    assert sorted(results) == list(range(50))


def test_one_change_at_a_time(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, say_yes: None
) -> None:
    """A quick second click while a change runs must not start another one."""
    window = harness.window
    release = threading.Event()
    calls: list[int] = []
    real = window.service.apply_many

    def slow(*args: Any, **kwargs: Any) -> ChangeReport:
        calls.append(1)
        release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(window.service, "apply_many", slow)
    window.apply_chosen()
    window.apply_chosen()
    window.revert_all()
    window.clean_up()
    assert not window.picker.apply_button.isEnabled()
    assert not window.revert_all_button.isEnabled()
    assert not any(a.isEnabled() for a in window.change_actions)
    release.set()
    harness.settle()
    assert calls == [1]
    assert window.picker.apply_button.isEnabled()
    assert window.revert_all_button.isEnabled()


def test_old_icons_are_offered_a_redraw_once(harness: Harness) -> None:
    window = harness.window
    window.picker.choose(window.picker.cards[3])
    window.apply_chosen()
    harness.settle()
    key = next(g.key for g in window.shortcuts.groups if g.name == "Arcade")
    window.service.choices._drawn[key] = 1  # pyright: ignore[reportPrivateUsage]
    window._on_scanned(4)  # pyright: ignore[reportPrivateUsage]
    assert "draws icons better now" in window.notice.label.text()
    window.redraw_old()
    harness.settle()
    assert window.service.drawn_before(window.shortcuts.groups) == []
    assert harness.status("Arcade") is Status.THEMED
