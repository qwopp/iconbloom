"""The window's colors, light and dark, by name.

style.qss refers to these names as ``@name``; the tile painter reads them from
``current()``. Every color the UI draws lives here, so a mode is one palette.
"""

import re
from dataclasses import dataclass, fields
from functools import cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

from app.ui import UI_DIR

STYLE_TEMPLATE = UI_DIR / "style.qss"
_TOKEN = re.compile(r"@(\w+)")


@dataclass(frozen=True)
class UiPalette:
    text: str
    muted: str
    title: str
    window: str
    card: str
    card_border: str
    border: str
    hover: str
    hover_border: str
    selected: str
    accent: str
    primary: str
    primary_hover: str
    on_primary: str
    preview: str
    preview_border: str
    preview_hover_border: str
    preview_selected: str
    danger_border: str
    danger_text: str
    danger_hover: str
    disabled: str
    disabled_border: str
    disabled_text: str
    notice: str
    notice_border: str
    icon_muted: str
    tile_selected: str
    tile_border: str
    shield: str

    def color(self, name: str) -> QColor:
        return QColor(getattr(self, name))


LIGHT = UiPalette(
    text="#7A3E5D",
    muted="#A87A93",
    title="#E8689A",
    window="#FFF4F8",
    card="#FFFFFF",
    card_border="#F8DCE8",
    border="#FBD3E3",
    hover="#FFF0F6",
    hover_border="#FFB3D0",
    selected="#FFE4EE",
    accent="#FF9EC4",
    primary="#F27AAA",
    primary_hover="#E8689A",
    on_primary="#FFFFFF",
    preview="#FFF9FB",
    preview_border="#FBE3EE",
    preview_hover_border="#FFC2DA",
    preview_selected="#FFEAF2",
    danger_border="#F5C2CE",
    danger_text="#C9506F",
    danger_hover="#FFEEF2",
    disabled="#FBF3F7",
    disabled_border="#F6E8EE",
    disabled_text="#D5BCC9",
    notice="#FFF3E8",
    notice_border="#FFD9B8",
    icon_muted="#B58AA2",
    tile_selected="#FFD3E4",
    tile_border="#F6DCE8",
    shield="#F3E6FF",
)

DARK = UiPalette(
    text="#F5DDE9",
    muted="#B89AAB",
    title="#FF8FBE",
    window="#1D1620",
    card="#2A2030",
    card_border="#3A2C41",
    border="#4A3851",
    hover="#36293C",
    hover_border="#8A5476",
    selected="#4A2C43",
    accent="#FF9EC4",
    primary="#E8689A",
    primary_hover="#F27AAA",
    on_primary="#FFFFFF",
    preview="#30243A",
    preview_border="#3F2F47",
    preview_hover_border="#7A4A66",
    preview_selected="#4A2C43",
    danger_border="#7A3A4D",
    danger_text="#FF8FA8",
    danger_hover="#3A222B",
    disabled="#251D28",
    disabled_border="#322836",
    disabled_text="#6E5B69",
    notice="#3A2A22",
    notice_border="#6B4A33",
    icon_muted="#B89AAB",
    tile_selected="#5A3050",
    tile_border="#3A2C41",
    shield="#3E3256",
)


class _Active:
    """The palette in use; the tile painter asks for it every paint."""

    palette: UiPalette = LIGHT


def current() -> UiPalette:
    return _Active.palette


def windows_prefers_dark() -> bool:
    """True when Windows' app mode is dark (Settings > Personalization > Colors)."""
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def stylesheet(palette: UiPalette, template: str | None = None) -> str:
    """style.qss with every ``@name`` replaced by the palette's color."""
    text = _template() if template is None else template
    names = {f.name for f in fields(palette)}

    def color(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in names:
            raise KeyError(f"style.qss uses @{name}, which the palette doesn't define")
        return str(getattr(palette, name))

    return _TOKEN.sub(color, text)


@cache
def _template() -> str:
    return STYLE_TEMPLATE.read_text(encoding="utf-8")


def apply(app: QApplication, palette: UiPalette) -> None:
    """Restyle the whole app. Re-applying the palette already in use does nothing:
    a new stylesheet repolishes every widget."""
    if palette is _Active.palette and app.styleSheet():
        return
    _Active.palette = palette
    app.setStyleSheet(stylesheet(palette))
