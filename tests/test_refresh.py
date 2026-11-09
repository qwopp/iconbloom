from pathlib import Path

import pytest

from platform_win.refresh import feeds_taskbar, is_pinned

ROAMING = r"C:\Users\a\AppData\Roaming\Microsoft"
PIN = ROAMING + r"\Internet Explorer\Quick Launch\User Pinned\TaskBar\Chrome.lnk"
START = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk"
DESKTOP = r"C:\Users\a\Desktop\Chrome.lnk"


@pytest.mark.parametrize(
    ("path", "pinned", "feeds"),
    [(PIN, True, True), (START, False, True), (DESKTOP, False, False)],
)
def test_which_shortcuts_the_taskbar_draws_from(path: str, pinned: bool, feeds: bool) -> None:
    assert is_pinned(Path(path)) is pinned
    assert feeds_taskbar(Path(path)) is feeds
