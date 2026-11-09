"""The shortcut list: search and place tabs."""

from platform_win.shortcuts import Place
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
