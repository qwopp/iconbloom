"""Switching themes changes every preview after it, including the next icon's."""

from engine.themes import load_theme
from tests.ui_harness import RECIPES, Harness

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
    harness.qtbot.waitUntil(
        lambda: (
            len(window.picker.cards) == RECIPES
            and all(c.choice.theme == SECOND for c in window.picker.cards)
        ),
        timeout=15_000,
    )
