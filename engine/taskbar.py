"""Taskbar looks for a theme, and a picture of how the taskbar would look.

    uv run python -m engine.taskbar --theme mint_matcha -o taskbar.png

A look is what Windows itself can do with a taskbar: an accent color (shown only
in dark Windows mode, under white text) and the transparency effect. The looks
come from the theme's palette, so every theme gets them without extra data.
``render_preview`` draws a mockup of the bottom of the screen; nothing here
reads or changes Windows' settings.
"""

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from engine import ops
from engine.themes import DEFAULT_THEME, THEMES_DIR, load_theme

type RGB = ops.RGB
type Box = tuple[float, float, float, float]

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)
# The taskbar's clock is small, but WCAG's 3:1 for large text keeps pastels recognizable.
READABLE_RATIO = 3.0
# Windows keeps eight shades of the accent color, lightest first.
SHADES = 8
_SHADE_STEP = 0.16

# Windows' own taskbar colors, for the look that keeps Windows' default.
_DEFAULT_DARK: RGB = (32, 32, 32)
_DEFAULT_LIGHT: RGB = (238, 238, 238)
# How much of the bar's color shows over the blurred wallpaper with transparency on.
_FROSTED_OPACITY = 0.72
_FROSTED_BLUR = 28
_SUPERSAMPLE = 2
# Logical pixels, as on a 100% scaled screen.
_SCREEN_ASPECT = 9 / 16
_START_BLUE: RGB = (96, 178, 255)


class SearchMode(StrEnum):
    HIDDEN = "hidden"
    ICON = "icon"
    BOX = "box"
    BUTTON = "button"


@dataclass(frozen=True)
class Look:
    """One choice in "Looks for <theme>". ``id`` is stable: settings save it."""

    id: str
    label: str
    # None keeps Windows' own taskbar color (no accent on the taskbar).
    color: RGB | None
    transparency: bool

    @property
    def show_accent(self) -> bool:
        return self.color is not None


@dataclass(frozen=True)
class BarSpec:
    """Everything the preview draws."""

    color: RGB | None
    transparency: bool
    centered: bool = True
    small: bool = False
    search: SearchMode = SearchMode.ICON
    task_view: bool = True
    auto_hide: bool = False
    win11: bool = True
    # Light Windows mode; only Windows' own color can be light (accents need dark mode).
    light: bool = False


def looks(palette: Mapping[str, RGB]) -> tuple[Look, ...]:
    """Soft, deep, frosted and Windows' default, worked out from a theme palette."""
    soft = readable_under_white(palette["main"])
    return (
        Look("soft", "Soft", soft, False),
        Look("deep", "Deep", readable_under_white(palette["ink"]), False),
        Look("frosted", "Frosted", soft, True),
        Look("windows", "Windows default", None, True),
    )


def contrast(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio, from 1 (same) to 21 (black on white)."""
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_under_white(color: RGB, ratio: float = READABLE_RATIO) -> RGB:
    """``color``, darkened only as far as white text on it needs; readable colors stay."""
    for step in range(101):
        candidate = ops.mix(color, BLACK, step / 100)
        if contrast(candidate, WHITE) >= ratio:
            return candidate
    return BLACK


def accent_shades(color: RGB, slot: int) -> tuple[RGB, ...]:
    """Windows' eight accent shades, lightest first, with ``color`` exactly at ``slot``."""
    if not 0 <= slot < SHADES:
        raise ValueError(f"slot must be 0 to {SHADES - 1}, got {slot}")
    shades: list[RGB] = []
    for i in range(SHADES):
        if i < slot:
            shades.append(ops.mix(color, WHITE, min(1.0, (slot - i) * _SHADE_STEP)))
        else:
            shades.append(ops.mix(color, BLACK, min(1.0, (i - slot) * _SHADE_STEP)))
    return tuple(shades)


def gradient_wallpaper(size: tuple[int, int], palette: Mapping[str, RGB]) -> Image.Image:
    """A soft wallpaper in the theme's colors, for when the real one isn't available."""
    width, height = size
    base = ops.linear_gradient(size, palette["light"], palette["accent"], 35).convert("RGBA")
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for (cx, cy, r), name in zip(
        ((0.22, 0.75, 0.32), (0.7, 0.35, 0.28), (0.9, 0.95, 0.22)),
        ("main", "peach", "deep"),
        strict=True,
    ):
        radius = r * max(width, height)
        box = (cx * width - radius, cy * height - radius, cx * width + radius, cy * height + radius)
        draw.ellipse(box, fill=(*palette[name], 150))
    glow = glow.filter(ImageFilter.GaussianBlur(max(width, height) * 0.08))
    return Image.alpha_composite(base, glow)


def render_preview(
    wallpaper: Image.Image | None,
    size: tuple[int, int],
    bar: BarSpec,
    icons: Sequence[Image.Image],
    clock: str = "10:42 AM\n11/9/2026",
    scale: float = 1.0,
) -> Image.Image:
    """The bottom of the screen with the taskbar ``bar`` describes, as an RGBA image.

    ``scale`` is output pixels per logical pixel: 1 draws a 48 px Windows 11 bar, and
    smaller values fit a wider screen into a small picture.
    """
    width, height = size
    s = scale * _SUPERSAMPLE
    big = (round(width * _SUPERSAMPLE), round(height * _SUPERSAMPLE))
    screen = _screen(wallpaper, big)
    layout = _Layout.of(bar)
    bar_h = round((3 if bar.auto_hide else layout.height) * s)
    top = big[1] - bar_h
    _paint_bar(screen, bar, top, s)
    if not bar.auto_hide:
        _draw_contents(screen, bar, layout, icons, clock, top, s)
    return screen.resize(size, Image.Resampling.LANCZOS)


# ---- drawing ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Layout:
    height: int
    slot: int
    icon: int
    margin: int

    @classmethod
    def of(cls, bar: BarSpec) -> "_Layout":
        if bar.win11:
            return cls(48, 36, 18, 12) if bar.small else cls(48, 44, 24, 12)
        return cls(30, 40, 16, 0) if bar.small else cls(40, 48, 24, 0)


def _screen(wallpaper: Image.Image | None, size: tuple[int, int]) -> Image.Image:
    """The bottom ``size`` of a 16:9 screen as wide as the picture, wallpaper filling it."""
    width, height = size
    if wallpaper is None:
        return Image.new("RGBA", size, (58, 78, 110, 255))
    screen_h = max(height, round(width * _SCREEN_ASPECT))
    source = wallpaper.convert("RGBA")
    zoom = max(width / source.width, screen_h / source.height)
    scaled = source.resize(
        (max(width, round(source.width * zoom)), max(screen_h, round(source.height * zoom))),
        Image.Resampling.LANCZOS,
    )
    left = (scaled.width - width) // 2
    return scaled.crop((left, scaled.height - height, left + width, scaled.height))


def _bar_color(bar: BarSpec) -> RGB:
    if bar.color is not None:
        return bar.color
    return _DEFAULT_LIGHT if bar.light else _DEFAULT_DARK


def _ink(bar: BarSpec) -> RGB:
    """Text and glyph color: white, except on Windows' own light taskbar."""
    return (26, 26, 26) if bar.light and bar.color is None else WHITE


def _paint_bar(screen: Image.Image, bar: BarSpec, top: int, s: float) -> None:
    box = (0, top, screen.width, screen.height)
    color = _bar_color(bar)
    if bar.transparency:
        behind = screen.crop(box).filter(ImageFilter.GaussianBlur(_FROSTED_BLUR * s))
        tint = Image.new("RGBA", behind.size, (*color, round(255 * _FROSTED_OPACITY)))
        screen.paste(Image.alpha_composite(behind, tint), box[:2])
    else:
        screen.paste((*color, 255), box)
    # Windows draws a faint line along the top of the taskbar.
    line = Image.new("RGBA", (screen.width, max(1, round(s))), (*_ink(bar), 26))
    screen.alpha_composite(line, (0, top))


def _draw_contents(
    screen: Image.Image,
    bar: BarSpec,
    layout: _Layout,
    icons: Sequence[Image.Image],
    clock: str,
    top: int,
    s: float,
) -> None:
    overlay = Image.new("RGBA", screen.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ink = _ink(bar)
    mid = top + layout.height * s / 2
    items = _items(bar, layout, len(icons))
    group = sum(w for _, w in items) * s
    clock_w = _draw_clock(draw, clock, screen.width, mid, ink, s)
    if bar.win11 and bar.centered:
        x = (screen.width - group) / 2
        x = max(layout.margin * s, min(x, screen.width - clock_w - group))
    else:
        x = layout.margin * s
    # Like Windows, buttons that don't fit before the tray aren't shown.
    limit = screen.width - clock_w
    icon_index = 0
    for kind, w in items:
        slot = (x, top, x + w * s, top + layout.height * s)
        if slot[2] > limit:
            break
        if kind == "start":
            _draw_start(draw, bar, slot, layout, s)
        elif kind == "search":
            _draw_search(draw, bar, slot, layout, ink, s)
        elif kind == "task_view":
            _draw_task_view(draw, slot, layout, ink, s)
        else:
            # Open apps get Windows' little line underneath. ImageDraw replaces pixels
            # rather than blending, so this goes down before the icon.
            if icon_index < 2:
                _draw_running(draw, bar, slot, icon_index == 0, s)
            _paste_icon(overlay, icons[icon_index], slot, layout, s)
            icon_index += 1
        x += w * s
    screen.alpha_composite(overlay)


def _items(bar: BarSpec, layout: _Layout, icon_count: int) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = [("start", layout.slot)]
    if bar.search is not SearchMode.HIDDEN:
        items.append(("search", _search_width(bar, layout)))
    if bar.task_view:
        items.append(("task_view", layout.slot))
    items += [("icon", layout.slot)] * icon_count
    return items


def _search_width(bar: BarSpec, layout: _Layout) -> int:
    if bar.search is SearchMode.ICON or (bar.search is SearchMode.BUTTON and not bar.win11):
        return layout.slot
    if bar.search is SearchMode.BUTTON:
        return 96 if not bar.small else 84
    return 200 if bar.win11 else 260


def _draw_start(
    draw: ImageDraw.ImageDraw, bar: BarSpec, slot: Box, layout: _Layout, s: float
) -> None:
    cx, cy = (slot[0] + slot[2]) / 2, (slot[1] + slot[3]) / 2
    half = layout.icon * s / 2
    gap = max(1.0, 1.4 * s)
    pane = half - gap / 2
    color = _START_BLUE if bar.win11 else _ink(bar)
    radius = pane * 0.22 if bar.win11 else 0
    for dx in (0, 1):
        for dy in (0, 1):
            x0 = cx - half + dx * (pane + gap)
            y0 = cy - half + dy * (pane + gap)
            draw.rounded_rectangle((x0, y0, x0 + pane, y0 + pane), radius, fill=(*color, 255))


def _draw_search(
    draw: ImageDraw.ImageDraw, bar: BarSpec, slot: Box, layout: _Layout, ink: RGB, s: float
) -> None:
    cy = (slot[1] + slot[3]) / 2
    if _search_width(bar, layout) == layout.slot:
        _magnifier(draw, (slot[0] + slot[2]) / 2, cy, layout.icon * 0.38 * s, ink, s)
        return
    pill_h = (32 if bar.win11 else layout.height - 6) * s
    pad = 4 * s
    box = (slot[0] + pad, cy - pill_h / 2, slot[2] - pad, cy + pill_h / 2)
    radius = pill_h / 2 if bar.win11 else 0
    fill = (*ink, 22) if bar.win11 else (*WHITE, 235)
    draw.rounded_rectangle(box, radius, fill=fill, outline=(*ink, 30), width=max(1, round(s)))
    text_ink = ink if bar.win11 else (40, 40, 40)
    lens_x = box[0] + 16 * s
    _magnifier(draw, lens_x, cy, 6.5 * s, text_ink, s)
    label = "Search" if bar.win11 else "Type here to search"
    draw.text(
        (lens_x + 14 * s, cy),
        label,
        fill=(*text_ink, 200),
        font=_font(12 * s),
        anchor="lm",
    )


def _magnifier(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, ink: RGB, s: float
) -> None:
    lens_r = r * 0.62
    lx, ly = cx - r * 0.18, cy - r * 0.18
    stroke = max(1, round(1.6 * s))
    draw.ellipse(
        (lx - lens_r, ly - lens_r, lx + lens_r, ly + lens_r), outline=(*ink, 255), width=stroke
    )
    hx, hy = lx + lens_r * 0.72, ly + lens_r * 0.72
    draw.line((hx, hy, cx + r * 0.85, cy + r * 0.85), fill=(*ink, 255), width=stroke)


def _draw_task_view(
    draw: ImageDraw.ImageDraw, slot: Box, layout: _Layout, ink: RGB, s: float
) -> None:
    cx, cy = (slot[0] + slot[2]) / 2, (slot[1] + slot[3]) / 2
    half = layout.icon * s / 2
    stroke = max(1, round(1.4 * s))
    back = (cx - half * 0.55, cy - half * 0.85, cx + half * 0.95, cy + half * 0.45)
    front = (cx - half * 0.95, cy - half * 0.45, cx + half * 0.55, cy + half * 0.85)
    radius = 2.5 * s
    draw.rounded_rectangle(back, radius, outline=(*ink, 150), width=stroke)
    draw.rounded_rectangle(front, radius, fill=(*ink, 40), outline=(*ink, 255), width=stroke)


def _paste_icon(
    overlay: Image.Image, icon: Image.Image, slot: Box, layout: _Layout, s: float
) -> None:
    px = max(1, round(layout.icon * s))
    small = icon.convert("RGBA").resize((px, px), Image.Resampling.LANCZOS)
    x = round((slot[0] + slot[2]) / 2 - px / 2)
    y = round((slot[1] + slot[3]) / 2 - px / 2)
    overlay.alpha_composite(small, (x, y))


def _draw_running(
    draw: ImageDraw.ImageDraw, bar: BarSpec, slot: Box, focused: bool, s: float
) -> None:
    cx = (slot[0] + slot[2]) / 2
    if focused:
        # The app in front gets a soft highlight behind it, like Windows 11.
        pad = 3 * s
        draw.rounded_rectangle(
            (slot[0] + pad, slot[1] + pad, slot[2] - pad, slot[3] - pad),
            4 * s,
            fill=(*_ink(bar), 22),
        )
    width = (16 if focused else 6) * s
    color = _START_BLUE if bar.color is None else _ink(bar)
    y = slot[3] - 4 * s
    draw.rounded_rectangle(
        (cx - width / 2, y - 1.5 * s, cx + width / 2, y + 1.5 * s),
        1.5 * s,
        fill=(*color, 255 if focused else 170),
    )


def _draw_clock(
    draw: ImageDraw.ImageDraw, clock: str, right: int, mid: float, ink: RGB, s: float
) -> float:
    """Draws the tray icons and clock against the right edge; returns the width they take."""
    font = _font(12 * s)
    lines = clock.split("\n")
    text_w = max(draw.textlength(line, font=font) for line in lines)
    margin = 12 * s
    text_x = right - margin - text_w / 2
    draw.multiline_text(
        (text_x, mid), clock, fill=(*ink, 255), font=font, anchor="mm", align="right", spacing=2 * s
    )
    # Wi-Fi and volume, then the "show hidden icons" chevron.
    x = right - margin - text_w - 18 * s
    _wifi(draw, x, mid, s, ink)
    _speaker(draw, x - 22 * s, mid, s, ink)
    _chevron(draw, x - 50 * s, mid, s, ink)
    return right - (x - 62 * s)


def _wifi(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, ink: RGB) -> None:
    stroke = max(1, round(1.4 * s))
    base_y = cy + 5 * s
    for r in (4.5, 8.5):
        rr = r * s
        draw.arc(
            (cx - rr, base_y - rr, cx + rr, base_y + rr), 225, 315, fill=(*ink, 255), width=stroke
        )
    dot = 1.4 * s
    draw.ellipse((cx - dot, base_y - dot - 1 * s, cx + dot, base_y + dot - 1 * s), fill=(*ink, 255))


def _speaker(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, ink: RGB) -> None:
    body = [
        (cx - 6 * s, cy - 2.5 * s),
        (cx - 3 * s, cy - 2.5 * s),
        (cx + 1 * s, cy - 6 * s),
        (cx + 1 * s, cy + 6 * s),
        (cx - 3 * s, cy + 2.5 * s),
        (cx - 6 * s, cy + 2.5 * s),
    ]
    draw.polygon(body, fill=(*ink, 255))
    stroke = max(1, round(1.3 * s))
    rr = 5 * s
    draw.arc(
        (cx - rr + 1 * s, cy - rr, cx + rr + 1 * s, cy + rr),
        300,
        60,
        fill=(*ink, 255),
        width=stroke,
    )


def _chevron(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, ink: RGB) -> None:
    w, h = 4.5 * s, 2.5 * s
    draw.line(
        ((cx - w, cy + h), (cx, cy - h), (cx + w, cy + h)),
        fill=(*ink, 255),
        width=max(1, round(1.4 * s)),
        joint="curve",
    )


def _font(px: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=max(1, round(px)))


def _luminance(color: RGB) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---- contact sheet ----------------------------------------------------------------

SHEET_WIDTH = 960
SHEET_ROW_H = 120
_SHEET_GAP = 12
_SHEET_LABEL_H = 22
_SHEET_BACKGROUND = (255, 247, 250, 255)
_SHEET_TEXT = (120, 60, 90)


def sheet_rows(theme_looks: Sequence[Look]) -> list[tuple[str, BarSpec]]:
    """Every look, then the layout options on the first one."""
    rows = [(look.label, BarSpec(look.color, look.transparency)) for look in theme_looks]
    first = BarSpec(theme_looks[0].color, theme_looks[0].transparency)
    rows += [
        ("Left aligned", replace(first, centered=False)),
        ("Smaller buttons", replace(first, small=True)),
        ("Search box, no Task view", replace(first, search=SearchMode.BOX, task_view=False)),
        ("Search button", replace(first, search=SearchMode.BUTTON)),
        ("Hide automatically", replace(first, auto_hide=True)),
        ("Windows 10", replace(first, win11=False, search=SearchMode.BOX)),
        ("Windows default, light mode", BarSpec(None, True, light=True)),
    ]
    return rows


def build_sheet(
    rows: Sequence[tuple[str, BarSpec]], wallpaper: Image.Image, icons: Sequence[Image.Image]
) -> Image.Image:
    row_h = _SHEET_LABEL_H + SHEET_ROW_H + _SHEET_GAP
    sheet = Image.new("RGBA", (SHEET_WIDTH + 2 * _SHEET_GAP, len(rows) * row_h + _SHEET_GAP))
    sheet.paste(_SHEET_BACKGROUND, (0, 0, *sheet.size))
    draw = ImageDraw.Draw(sheet)
    font = _font(14)
    for i, (label, bar) in enumerate(rows):
        y = _SHEET_GAP + i * row_h
        draw.text((_SHEET_GAP, y), label, fill=_SHEET_TEXT, font=font)
        preview = render_preview(wallpaper, (SHEET_WIDTH, SHEET_ROW_H), bar, icons)
        sheet.alpha_composite(preview, (_SHEET_GAP, y + _SHEET_LABEL_H))
    return sheet


def _placeholder_icons(palette: Mapping[str, RGB], count: int = 5) -> list[Image.Image]:
    names = ("deep", "main", "accent", "peach", "ink")
    icons: list[Image.Image] = []
    for i in range(count):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle(
            (6, 6, 58, 58), 14, fill=(*palette[names[i % 5]], 255)
        )
        icons.append(img)
    return icons


def _load_icons(folder: Path) -> list[Image.Image]:
    icons: list[Image.Image] = []
    for path in sorted(folder.glob("*.png"))[:8]:
        with Image.open(path) as img:
            icons.append(img.convert("RGBA"))
    return icons


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m engine.taskbar", description="Preview a theme's taskbar looks."
    )
    parser.add_argument("--theme", default=DEFAULT_THEME, help="theme folder name")
    parser.add_argument("--themes-dir", type=Path, default=THEMES_DIR)
    parser.add_argument("--icons", type=Path, help="folder of .png icons to pin (up to 8)")
    parser.add_argument("--wallpaper", type=Path, help="image to use instead of a theme gradient")
    parser.add_argument("-o", "--output", type=Path, default=Path("taskbar.png"))
    args = parser.parse_args(argv)

    theme = load_theme(args.theme, args.themes_dir)
    icons = _load_icons(args.icons) if args.icons else _placeholder_icons(theme.palette)
    if args.wallpaper:
        with Image.open(args.wallpaper) as img:
            wallpaper = img.convert("RGBA")
    else:
        wallpaper = gradient_wallpaper((1920, 1080), theme.palette)
    build_sheet(sheet_rows(looks(theme.palette)), wallpaper, icons).save(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
