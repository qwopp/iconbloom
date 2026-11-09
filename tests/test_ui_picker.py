"""The style picker: previews, shuffle, hover comparison, the detail line and notices."""

from pathlib import Path

from PySide6.QtCore import QPoint

from app.service import ChangeReport
from tests.ui_harness import Harness


def test_shuffle_rerolls_previews(harness: Harness) -> None:
    first = [card.image.copy() for card in harness.window.picker.cards]
    harness.window.picker.shuffle()
    harness.wait_for_previews()
    second = [card.image for card in harness.window.picker.cards]
    assert any(a != b for a, b in zip(first, second, strict=True))


def test_hover_shows_real_size_popup(harness: Harness) -> None:
    card = harness.window.picker.cards[0]
    card.hovered.emit(card, True)
    assert harness.window.picker.popup.isVisible()
    card.hovered.emit(card, False)
    assert not harness.window.picker.popup.isVisible()


def test_popup_handles_point(harness: Harness) -> None:
    harness.window.picker.popup.show_for(
        harness.window.picker.cards[0].image, harness.window.picker.cards[1].image, QPoint(10, 10)
    )
    assert harness.window.picker.popup.isVisible()


def test_detail_says_where_a_style_lands(harness: Harness) -> None:
    assert harness.window.picker.detail_label.text().startswith("Desktop \u00b7 original")


def test_taskbar_change_offers_a_refresh(harness: Harness) -> None:
    report = ChangeReport(dry_run=False, changed=[Path("C:/Users/x/User Pinned/TaskBar/A.lnk")])
    harness.window.changes.show_taskbar_notice(report)
    assert harness.window.notice.isVisibleTo(harness.window)


def test_picker_says_when_previews_are_still_drawing(harness: Harness) -> None:
    picker = harness.window.picker
    assert not picker.rendering
    picker.shuffle()
    assert picker.rendering
    harness.wait_for_previews()
    assert not picker.rendering
