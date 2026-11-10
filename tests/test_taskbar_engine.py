"""Taskbar looks and the taskbar preview (engine/taskbar.py).

The preview is pinned by goldens in tests/goldens/taskbar/; regenerate them with
``uv run pytest tests/test_taskbar_engine.py --update-goldens`` and look at each one.
"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from engine import taskbar as tb
from engine.themes import DEFAULT_THEME, list_themes, load_theme
from tests.conftest import load_sample
from tests.test_goldens import MAX_CHANNEL_DIFF, MIN_MATCHING_SHARE, TASKBAR_GOLDENS

PINK = (201, 125, 155)
GOLDEN_SIZE = (720, 96)
GOLDEN_ICONS = ("multicolor", "gradient_app", "simple_glyph", "plate_glyph", "thin_line")


def _rgb() -> st.SearchStrategy[tuple[int, int, int]]:
    return st.tuples(st.integers(0, 255), st.integers(0, 255), st.integers(0, 255))


def _palette() -> dict[str, tb.RGB]:
    return dict(load_theme(DEFAULT_THEME).palette)


def _icons() -> list[Image.Image]:
    return [load_sample(name) for name in GOLDEN_ICONS]


def _wallpaper() -> Image.Image:
    return tb.gradient_wallpaper((1280, 720), _palette())


# ---- looks and colors ---------------------------------------------------------------


@pytest.mark.parametrize("theme_id", list_themes())
def test_every_theme_has_three_readable_looks(theme_id: str) -> None:
    found = tb.looks(load_theme(theme_id).palette)
    assert [look.id for look in found] == ["soft", "deep", "windows"]
    for look in found:
        if look.color is None:
            assert not look.show_accent
        else:
            assert look.show_accent
            assert tb.contrast(look.color, tb.WHITE) >= tb.READABLE_RATIO


def test_soft_and_deep_differ_and_windows_keeps_its_own_color() -> None:
    soft, deep, windows = tb.looks(_palette())
    assert soft.color != deep.color
    assert windows.color is None


def test_contrast_bounds() -> None:
    assert tb.contrast(tb.BLACK, tb.WHITE) == pytest.approx(21)
    assert tb.contrast(PINK, PINK) == pytest.approx(1)
    assert tb.contrast(PINK, tb.WHITE) == tb.contrast(tb.WHITE, PINK)


@settings(max_examples=60, deadline=None)
@given(color=_rgb(), ratio=st.floats(1.0, 20.0))
def test_readable_under_white_only_darkens_as_needed(color: tb.RGB, ratio: float) -> None:
    result = tb.readable_under_white(color, ratio)
    assert tb.contrast(result, tb.WHITE) >= ratio
    assert all(r <= c for r, c in zip(result, color, strict=True))
    if tb.contrast(color, tb.WHITE) >= ratio:
        assert result == color


@settings(max_examples=40, deadline=None)
@given(color=_rgb(), slot=st.integers(0, tb.SHADES - 1))
def test_accent_shades_put_the_color_at_its_slot(color: tb.RGB, slot: int) -> None:
    shades = tb.accent_shades(color, slot)
    assert len(shades) == tb.SHADES
    assert shades[slot] == color
    brightness = [sum(shade) for shade in shades]
    assert brightness == sorted(brightness, reverse=True)


def test_accent_shades_default_to_the_taskbar_slot() -> None:
    assert tb.TASKBAR_SLOT == 5
    assert tb.accent_shades(PINK)[5] == PINK


@pytest.mark.parametrize("slot", [-1, tb.SHADES])
def test_accent_shades_rejects_a_missing_slot(slot: int) -> None:
    with pytest.raises(ValueError, match="slot"):
        tb.accent_shades(PINK, slot)


# ---- the preview --------------------------------------------------------------------


@pytest.mark.parametrize(("size", "scale"), [((720, 96), 1.0), ((200, 64), 0.42), ((333, 51), 0.5)])
def test_preview_has_the_requested_size(size: tuple[int, int], scale: float) -> None:
    image = tb.render_preview(_wallpaper(), size, tb.BarSpec(PINK, False), _icons(), scale=scale)
    assert image.size == size
    assert image.mode == "RGBA"


def test_preview_is_deterministic() -> None:
    bar = tb.BarSpec(PINK, True)
    first = tb.render_preview(_wallpaper(), GOLDEN_SIZE, bar, _icons())
    second = tb.render_preview(_wallpaper(), GOLDEN_SIZE, bar, _icons())
    assert first.tobytes() == second.tobytes()


def _variation(image: Image.Image, left: float, right: float) -> float:
    """How much the bar's middle varies between two fractions of the width (0 = flat)."""
    arr = np.asarray(image.convert("RGB"), dtype=np.float64)
    w, h = image.size
    region = arr[h - 40 : h - 8, int(w * left) : int(w * right)]
    return float(region.std(axis=(0, 1)).max())


def test_left_alignment_moves_the_buttons_left() -> None:
    bar = tb.BarSpec(PINK, False)
    centered = tb.render_preview(None, GOLDEN_SIZE, bar, _icons())
    left = tb.render_preview(None, GOLDEN_SIZE, replace(bar, centered=False), _icons())
    # The left fifth of a centered bar is plain color; left-aligned, it holds Start and more.
    assert _variation(centered, 0.01, 0.2) < 1
    assert _variation(left, 0.01, 0.2) > 10


def test_auto_hide_leaves_only_a_sliver() -> None:
    bar = tb.BarSpec(PINK, False)
    hidden = np.asarray(
        tb.render_preview(_wallpaper(), GOLDEN_SIZE, replace(bar, auto_hide=True), [])
    )
    w, h = GOLDEN_SIZE
    assert tuple(hidden[h - 1, w // 2, :3]) == PINK
    assert tuple(hidden[h - 20, w // 2, :3]) != PINK


@pytest.mark.parametrize(("transparency", "shows_through"), [(False, False), (True, True)])
def test_transparency_lets_the_wallpaper_through(transparency: bool, shows_through: bool) -> None:
    bar = tb.BarSpec(PINK, transparency)
    w, h = GOLDEN_SIZE

    def bar_pixel(wallpaper_color: tb.RGB) -> tuple[int, ...]:
        wallpaper = Image.new("RGBA", (1280, 720), (*wallpaper_color, 255))
        image = tb.render_preview(wallpaper, GOLDEN_SIZE, bar, [])
        return tuple(image.getpixel((w // 20, h - 20)))  # pyright: ignore[reportArgumentType]

    assert (bar_pixel(tb.BLACK) != bar_pixel(tb.WHITE)) == shows_through


@pytest.mark.parametrize("centered", [True, False])
def test_crowded_bar_stays_clear_of_the_clock(centered: bool) -> None:
    bar = tb.BarSpec(PINK, False, centered=centered)
    alone = tb.render_preview(None, GOLDEN_SIZE, bar, [])
    crowded = tb.render_preview(None, GOLDEN_SIZE, bar, _icons() * 6)
    # The tray and clock, in the right fifth, look the same however many apps are pinned.
    w = GOLDEN_SIZE[0]
    tray = (int(w * 0.8), 0, w, GOLDEN_SIZE[1])
    assert crowded.crop(tray).tobytes() == alone.crop(tray).tobytes()


def test_windows_10_has_no_search_button() -> None:
    bar = tb.BarSpec(PINK, False, win11=False)
    button = tb.render_preview(None, GOLDEN_SIZE, replace(bar, search=tb.SearchMode.BUTTON), [])
    icon = tb.render_preview(None, GOLDEN_SIZE, replace(bar, search=tb.SearchMode.ICON), [])
    assert button.tobytes() == icon.tobytes()


# ---- goldens ------------------------------------------------------------------------


def _golden_cases() -> dict[str, tb.BarSpec]:
    soft, deep, windows = tb.looks(_palette())
    base = tb.BarSpec(soft.color, False)
    return {
        "soft": base,
        "deep": tb.BarSpec(deep.color, False),
        "frosted": replace(base, transparency=True),
        "windows": tb.BarSpec(windows.color, True),
        "windows_light": tb.BarSpec(windows.color, True, light=True),
        "left": replace(base, centered=False),
        "small": replace(base, small=True),
        "search_box": replace(base, search=tb.SearchMode.BOX, task_view=False),
        "search_button": replace(base, search=tb.SearchMode.BUTTON),
        "auto_hide": replace(base, auto_hide=True),
        "win10": replace(base, win11=False, search=tb.SearchMode.BOX),
    }


@pytest.mark.parametrize("case", sorted(_golden_cases()))
def test_preview_matches_golden(case: str, update_goldens: bool) -> None:
    result = tb.render_preview(_wallpaper(), GOLDEN_SIZE, _golden_cases()[case], _icons())
    golden_path = TASKBAR_GOLDENS / f"{case}.png"
    if update_goldens:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(golden_path, optimize=True)
        return
    assert golden_path.exists(), f"missing golden {golden_path.name}; run with --update-goldens"
    with Image.open(golden_path) as golden:
        expected = np.asarray(golden.convert("RGBA"), dtype=np.int16)
    actual = np.asarray(result, dtype=np.int16)
    assert actual.shape == expected.shape
    close = (np.abs(actual - expected) <= MAX_CHANNEL_DIFF).all(axis=-1)
    assert close.mean() >= MIN_MATCHING_SHARE, f"{case}: only {close.mean():.2%} of pixels match"


def test_no_stale_taskbar_goldens() -> None:
    expected = {TASKBAR_GOLDENS / f"{case}.png" for case in _golden_cases()}
    assert set(TASKBAR_GOLDENS.glob("*.png")) == expected


# ---- the sheet ----------------------------------------------------------------------


def test_sheet_command_with_placeholder_icons(tmp_path: Path) -> None:
    out = tmp_path / "taskbar.png"
    assert tb.main(["--theme", DEFAULT_THEME, "-o", str(out)]) == 0
    with Image.open(out) as sheet:
        rows = len(tb.sheet_rows(tb.looks(_palette())))
        assert sheet.width > tb.SHEET_WIDTH
        assert sheet.height > rows * tb.SHEET_ROW_H


def test_sheet_command_with_icons_and_wallpaper(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    for name in GOLDEN_ICONS[:2]:
        load_sample(name).save(icons / f"{name}.png")
    wallpaper = tmp_path / "wall.png"
    _wallpaper().save(wallpaper)
    out = tmp_path / "taskbar.png"
    args = ["--icons", str(icons), "--wallpaper", str(wallpaper), "-o", str(out)]
    assert tb.main(args) == 0
    assert out.is_file()
