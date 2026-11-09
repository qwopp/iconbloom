import numpy as np
import pytest
from PIL import Image

from engine import ops
from engine.families import Family
from engine.recipes import Json, RecipeError, Step, parse_hex, parse_recipe, render
from engine.themes import Theme
from tests.conftest import load_sample

PALETTE = {"main": (255, 158, 196), "ink": (168, 67, 111)}
ASSETS = ["bow"]
MONO: list[Json] = [{"op": "mono", "color": "ink"}]


def _recipe(steps: list[Json], **fields: Json) -> Json:
    return {"id": "r", "label": "R", "family": "mono", "ops": steps} | fields


def _parse(raw: Json) -> None:
    parse_recipe(raw, PALETTE, ASSETS)


def test_parse_recipe_keeps_steps_and_family() -> None:
    recipe = parse_recipe(
        {"id": "x", "label": "X", "family": "sticker", "ops": [{"op": "mono", "color": "ink"}]},
        PALETTE,
        ASSETS,
    )
    assert recipe.family is Family.STICKER
    assert recipe.steps == (Step(op="mono", params={"color": "ink"}),)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not an object", "JSON object"),
        ({"label": "no id", "ops": []}, "missing a string 'id'"),
        (_recipe(MONO, label=3), "'label'"),
        (_recipe(MONO, family="sparkly"), "'family' must be"),
        ({"id": "r", "ops": [{"op": "mono", "color": "ink"}]}, "'family' must be"),
        (_recipe(MONO, keeps_color=True), "unknown field"),
        (_recipe([]), "non-empty list"),
        (_recipe(["mono"]), "step 1: must be a JSON object"),
        (_recipe([{"op": "explode"}]), "unknown op 'explode'"),
        (_recipe([{"op": "mono", "color": "ink", "size": 3}]), "unknown parameter"),
        (_recipe([{"op": "mono"}]), "missing required parameter 'color'"),
        (_recipe([{"op": "mono", "color": "chartreuse"}]), "not a palette name"),
        (_recipe([{"op": "mono", "color": 7}]), "palette names or #RRGGBB"),
        (_recipe([{"op": "mono", "color": []}]), "list of choices is empty"),
        (_recipe([{"op": "mono", "color": [["ink"]]}]), "single values, not lists"),
        (_recipe([{"op": "tint", "stops": 5}]), "color or a list of colors"),
        (_recipe([{"op": "tint", "stops": [["ink", "nope"]]}]), "'nope'"),
        (_recipe([{"op": "badge", "asset": "crown"}]), "unknown asset 'crown'"),
        (_recipe([{"op": "glow", "color": "ink", "radius": "big"}]), "expected a number"),
        (_recipe([{"op": "glow", "color": "ink", "radius": 99}]), "outside"),
        (_recipe([{"op": "tile", "fill": "main", "shadow": "yes"}]), "true or false"),
        (_recipe([{"op": "tile", "fill": "main", "shape": "star"}]), "expected one of"),
        (_recipe([{"op": "tile", "fill": "main", "pattern": "plaid"}]), "expected one of"),
    ],
)
def test_parse_recipe_reports_problems(raw: Json, message: str) -> None:
    with pytest.raises(RecipeError, match=message):
        _parse(raw)


def test_errors_name_the_recipe_and_step() -> None:
    with pytest.raises(RecipeError, match=r"recipe 'r', step 2 \(mono\)"):
        _parse(_recipe([{"op": "mono", "color": "ink"}, {"op": "mono"}]))


@pytest.mark.parametrize("bad", ["#12345", "123456", "#GGGGGG"])
def test_parse_hex_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError, match="RRGGBB"):
        parse_hex(bad)


def test_parse_hex() -> None:
    assert parse_hex("#FF9ec4") == (255, 158, 196)


def _icon() -> Image.Image:
    icon, _ = ops.prepare(load_sample("multicolor"))
    return icon


def test_seed_zero_is_deterministic(kawaii: Theme) -> None:
    recipe = kawaii.recipe("tile_bow")
    first = np.asarray(render(recipe, _icon(), kawaii))
    second = np.asarray(render(recipe, _icon(), kawaii))
    assert np.array_equal(first, second)


def test_shuffle_seeds_give_variety(kawaii: Theme) -> None:
    recipe = kawaii.recipe("tile_bow")
    renders = {render(recipe, _icon(), kawaii, seed=s).tobytes() for s in range(1, 7)}
    assert len(renders) > 1


def test_simplified_render_drops_decorations(kawaii: Theme) -> None:
    recipe = kawaii.recipe("tile_bow")
    plain = render(kawaii.recipe("bubble_cream"), _icon(), kawaii)
    simplified = render(recipe, _icon(), kawaii, simplified=True)
    full = render(recipe, _icon(), kawaii)
    # Without the bow, the top-right corner holds only the tile.
    assert simplified.getpixel((236, 30)) != full.getpixel((236, 30))
    assert plain.size == simplified.size


def test_auto_color_follows_icon_hue() -> None:
    palette = {"pink": (255, 158, 196), "lavender": (201, 182, 255)}
    theme = Theme(
        id="t",
        name="T",
        palette=palette,
        assets={},
        recipes=(parse_recipe(_recipe([{"op": "mono", "color": "auto"}]), palette, []),),
    )
    blue, _ = ops.prepare(Image.new("RGBA", (16, 16), (40, 90, 230, 255)))
    out = render(theme.recipes[0], blue, theme)
    assert out.getpixel((128, 128)) == (*palette["lavender"], 255)


def test_random_corner_and_choice_lists_resolve(kawaii: Theme) -> None:
    raw: Json = _recipe(
        [
            {"op": "tile", "fill": [["main"], ["ink"]], "shape": ["circle", "rounded"]},
            {"op": "badge", "asset": "bow", "corner": "random"},
        ]
    )
    recipe = parse_recipe(raw, PALETTE | dict(kawaii.palette), list(kawaii.assets))
    for seed in range(4):
        assert render(recipe, _icon(), kawaii, seed=seed).size == (256, 256)
