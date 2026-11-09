from dataclasses import dataclass

import pytest
from PIL import Image, ImageDraw

from engine import analyze, ops
from engine.families import Family
from tests.conftest import load_sample

PALETTE = {
    "light": (255, 228, 238),
    "main": (255, 158, 196),
    "accent": (201, 182, 255),
}


@dataclass(frozen=True)
class FakeRecipe:
    id: str
    family: Family


RECIPES = [
    FakeRecipe("tint", Family.TINT),
    FakeRecipe("recolor", Family.RECOLOR),
    FakeRecipe("glow", Family.GLOW),
    FakeRecipe("tile", Family.TILE),
    FakeRecipe("mono", Family.MONO),
]


@pytest.mark.parametrize("name", ["simple_glyph", "thin_line", "dark"])
def test_plain_icons_are_not_colorful(name: str) -> None:
    assert not analyze.is_colorful(load_sample(name))


@pytest.mark.parametrize("name", ["multicolor", "gradient_app"])
def test_busy_icons_are_colorful(name: str) -> None:
    assert analyze.is_colorful(load_sample(name))


def test_colorfulness_of_transparent_image_is_zero() -> None:
    assert analyze.colorfulness(Image.new("RGBA", (8, 8))) == 0.0


def test_colorful_icons_get_flattening_recipes_last() -> None:
    ordered = analyze.order_recipes(RECIPES, load_sample("multicolor"))
    assert [r.id for r in ordered] == ["recolor", "tile", "mono", "tint", "glow"]


def test_plain_icons_keep_the_theme_order() -> None:
    ordered = analyze.order_recipes(RECIPES, load_sample("simple_glyph"))
    assert [r.id for r in ordered] == ["tint", "recolor", "glow", "tile", "mono"]


def test_cutout_recipes_only_for_plated_icons_and_always_last() -> None:
    recipes = [FakeRecipe("cut", Family.CUTOUT), *RECIPES]
    plated, _ = ops.prepare(load_sample("plate_glyph"))
    assert [r.id for r in analyze.order_recipes(recipes, plated)][-1] == "cut"
    plain = analyze.order_recipes(recipes, load_sample("multicolor"))
    assert "cut" not in [r.id for r in plain]


def test_dominant_hue_of_red_icon() -> None:
    hue = analyze.dominant_hue(Image.new("RGBA", (32, 32), (230, 20, 20, 255)))
    assert hue is not None
    assert hue < 15 or hue > 345


def test_dominant_hue_of_gray_icon_is_none() -> None:
    assert analyze.dominant_hue(Image.new("RGBA", (32, 32), (90, 90, 90, 255))) is None
    assert analyze.dominant_hue(Image.new("RGBA", (32, 32))) is None


def test_blue_icon_gets_lavender_shade() -> None:
    blue = Image.new("RGBA", (32, 32), (40, 90, 230, 255))
    assert analyze.nearest_shade(blue, PALETTE) == PALETTE["accent"]


def test_gray_icon_gets_most_saturated_shade() -> None:
    gray = Image.new("RGBA", (32, 32), (90, 90, 90, 255))
    assert analyze.nearest_shade(gray, PALETTE) == PALETTE["main"]


def test_hue_wraps_around() -> None:
    magenta_red = Image.new("RGBA", (32, 32), (240, 20, 60, 255))
    assert analyze.nearest_shade(magenta_red, PALETTE) == PALETTE["main"]


def test_mostly_gray_icon_with_a_speck_of_color_has_no_dominant_hue() -> None:
    img = Image.new("RGBA", (64, 64), (100, 100, 100, 255))
    ImageDraw.Draw(img).point((3, 3), fill=(255, 0, 0, 255))
    icon, _ = ops.prepare(img)
    assert analyze.dominant_hue(icon) is None
