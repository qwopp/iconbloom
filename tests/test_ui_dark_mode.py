"""Dark mode: the More menu toggle, the saved choice and the two palettes."""

from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from app.settings import Settings
from app.ui import palette
from app.ui.main_window import MainWindow
from app.ui.palette import DARK, LIGHT, UiPalette, stylesheet
from tests.fakes import FakeDesktop
from tests.ui_harness import FakeUpdater, Harness, open_window

COLOR_NAMES = [f.name for f in fields(UiPalette) if f.name != "dark"]
# WCAG AA for body text.
MIN_TEXT_CONTRAST = 4.5


@pytest.fixture(autouse=True)
def back_to_light(qapp: QApplication) -> Iterator[None]:
    yield
    palette.apply(qapp, LIGHT)


def _window(tmp_path: Path, qtbot: QtBot, saved: bool | None) -> MainWindow:
    desktop = FakeDesktop(tmp_path)
    Settings(dark_mode=saved).save(desktop.service().paths.settings)
    return open_window(desktop, FakeUpdater(), qtbot)


def test_starts_light_and_unchecked(harness: Harness, qapp: QApplication) -> None:
    assert not harness.window.dark_mode_action.isChecked()
    assert palette.current() is LIGHT
    assert LIGHT.window in qapp.styleSheet()


def test_toggle_switches_live_and_remembers(harness: Harness, qapp: QApplication) -> None:
    harness.window.dark_mode_action.trigger()
    assert palette.current() is DARK
    assert DARK.window in qapp.styleSheet()
    assert LIGHT.window not in qapp.styleSheet()
    assert Settings.load(harness.service.paths.settings).dark_mode is True

    harness.window.dark_mode_action.trigger()
    assert palette.current() is LIGHT
    assert Settings.load(harness.service.paths.settings).dark_mode is False


@pytest.mark.parametrize(
    ("windows_dark", "saved", "expected"),
    [
        (True, None, True),  # nothing chosen yet: follow Windows
        (False, None, False),
        (False, True, True),  # a choice beats Windows' setting
        (True, False, False),
    ],
)
def test_start_mode(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    windows_dark: bool,
    saved: bool | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(palette, "windows_prefers_dark", lambda: windows_dark)
    window = _window(tmp_path, qtbot, saved)
    assert window.dark_mode_action.isChecked() is expected
    assert palette.current() is (DARK if expected else LIGHT)
    # Following Windows isn't a choice, so it isn't saved as one.
    assert Settings.load(window.service.paths.settings).dark_mode is saved
    window.close()


@pytest.mark.parametrize("colors", [LIGHT, DARK], ids=["light", "dark"])
def test_stylesheet_uses_only_defined_colors(colors: UiPalette) -> None:
    sheet = stylesheet(colors)
    assert "@" not in sheet
    assert all(QColor(getattr(colors, name)).isValid() for name in COLOR_NAMES)


def test_unknown_color_name_is_reported() -> None:
    with pytest.raises(KeyError, match="@sparkle"):
        stylesheet(LIGHT, "QWidget { color: @sparkle; }")


def _luminance(hex_color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    color = QColor(hex_color)
    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("colors", [LIGHT, DARK], ids=["light", "dark"])
@pytest.mark.parametrize("background", ["window", "card", "preview", "hover", "tile_selected"])
def test_text_is_readable(colors: UiPalette, background: str) -> None:
    assert _contrast(colors.text, getattr(colors, background)) >= MIN_TEXT_CONTRAST


def test_palettes_say_which_mode_they_are() -> None:
    assert not LIGHT.dark
    assert DARK.dark


def test_old_settings_files_follow_windows(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"check_for_updates": true}', encoding="utf-8")
    assert Settings.load(path).dark_mode is None
