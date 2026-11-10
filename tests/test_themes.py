import itertools
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine import ops, taskbar
from engine.families import Family
from engine.recipes import render
from engine.themes import (
    DEFAULT_THEME,
    THEMES_DIR,
    ThemeError,
    list_themes,
    load_theme,
    theme_name,
)
from tests.conftest import REPRESENTATIVE_SAMPLES, load_sample, sample_names

STYLES_PER_THEME = 20
CUTOUT_ROW = [
    "cutout",
    "cutout_recolor",
    "cutout_mono",
    "cutout_tile",
    "cutout_swap",
    "cutout_duotone",
    "cutout_tint",
    "cutout_sticker",
]

_RECIPE = {"id": "a", "label": "A", "family": "mono", "ops": [{"op": "mono", "color": "main"}]}


def _write_library(root: Path, recipes: object) -> None:
    folder = root / "_library"
    folder.mkdir()
    (folder / "recipes.json").write_text(json.dumps({"recipes": recipes}), encoding="utf-8")


def _write_theme(root: Path, theme: object, assets: dict[str, bytes] | None = None) -> None:
    folder = root / "t"
    folder.mkdir()
    (folder / "theme.json").write_text(json.dumps(theme), encoding="utf-8")
    for name, data in (assets or {}).items():
        (folder / name).write_bytes(data)


def _valid() -> dict[str, object]:
    return {
        "name": "Test",
        "palette": {"main": "#FF9EC4"},
        "recipes": [_RECIPE],
    }


def test_kawaii_pink_loads() -> None:
    theme = load_theme("kawaii_pink")
    assert theme.name == "Kawaii Pink"
    assert theme.recipes[0].id == "pastel_recolor"
    assert {"bow", "heart", "face", "sparkle", "star", "cloud"} <= set(theme.assets)


@pytest.mark.parametrize("theme_id", list_themes())
def test_bundled_themes_follow_the_style_rules(theme_id: str) -> None:
    """20 styles, a recolor first, never two of a kind side by side, then the cut-out row."""
    recipes = load_theme(theme_id).recipes
    styles, cutouts = recipes[:STYLES_PER_THEME], recipes[STYLES_PER_THEME:]
    assert [r.id for r in cutouts] == CUTOUT_ROW
    assert all(r.family is Family.CUTOUT for r in cutouts)
    assert styles[0].family is Family.RECOLOR
    for before, after in itertools.pairwise(styles):
        assert before.family is not after.family, (
            f"{before.id} and {after.id} are both {after.family}"
        )


@pytest.mark.parametrize("theme_id", list_themes())
def test_bundled_themes_render_every_style_on_every_sample(theme_id: str) -> None:
    """The goldens pin the default look on some samples; this covers the rest, plus a
    shuffled look of every style. Every style, framed or not, comes out one size."""
    theme = load_theme(theme_id)
    golden = sample_names() if theme_id == DEFAULT_THEME else REPRESENTATIVE_SAMPLES
    cases = [(name, 0) for name in sample_names() if name not in golden]
    fitted = round(ops.CANVAS * ops.OUTPUT_FILL)
    for name, seed in [*cases, ("multicolor", 7)]:
        icon, _ = ops.prepare(load_sample(name))
        for recipe in theme.recipes:
            for simplified in (False, True):
                out = render(recipe, icon, theme, seed=seed, simplified=simplified)
                assert out.size == icon.size
                assert abs(_visible_extent(out) - fitted) <= 1, (recipe.id, name, simplified)


def _visible_extent(img: Image.Image) -> int:
    alpha = np.asarray(img.getchannel("A")) > 8
    rows, cols = np.flatnonzero(alpha.any(axis=1)), np.flatnonzero(alpha.any(axis=0))
    return max(rows[-1] - rows[0], cols[-1] - cols[0]) + 1


def test_list_themes_finds_bundled_theme() -> None:
    assert "kawaii_pink" in list_themes()


def test_list_themes_ignores_folders_without_theme_file(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "_library").mkdir()
    (tmp_path / "_library" / "theme.json").write_text("{}", encoding="utf-8")
    _write_theme(tmp_path, _valid())
    assert list_themes(tmp_path) == ["t"]
    assert list_themes(tmp_path / "missing") == []


def test_recipe_lookup(tmp_path: Path) -> None:
    _write_theme(tmp_path, _valid())
    theme = load_theme("t", tmp_path)
    assert theme.recipe("a").label == "A"
    with pytest.raises(KeyError, match="no recipe 'b'"):
        theme.recipe("b")


def test_asset_loading(tmp_path: Path) -> None:
    png = tmp_path / "bow.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(png)
    theme = _valid() | {"assets": {"bow": "bow.png"}}
    _write_theme(tmp_path, theme, {"bow.png": png.read_bytes()})
    assert load_theme("t", tmp_path).assets["bow"].mode == "RGBA"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": 5}, "'name' must be a string"),
        ({"palette": []}, "'palette' must be an object"),
        ({"palette": {"main": 3}}, "palette color 'main'"),
        ({"palette": {"main": "pink"}}, "palette color 'main'"),
        ({"assets": ["bow.png"]}, "'assets' must be an object"),
        ({"assets": {"bow": 1}}, "asset 'bow' must be a file name"),
        ({"assets": {"bow": "bow.png"}}, "bow.png not found"),
        ({"assets": {"bow": "theme.json"}}, "is not an image"),
        ({"recipes": []}, "'recipes' must be a non-empty list"),
        ({"recipes": [_RECIPE | {"ops": [{"op": "nope"}]}]}, "unknown op"),
        ({"recipes": ["nope"]}, "no library recipe called 'nope'"),
        ({"recipes": [{"use": "nope"}]}, "no library recipe called 'nope'"),
        ({"colors": {}}, "unknown field"),
        ({"decor": {"fill": "pink"}}, "decor color 'fill'"),
        ({"palette": {"deep": "#112233"}}, "needs at least a 'main' color"),
        ({"assets": {"bow": "../outside.png"}}, "must be inside the theme folder"),
        ({"recipes": [_RECIPE | {"family": ["mono"]}]}, "'family' must be one of"),
        ({"recipes": [_RECIPE | {"id": "My Style"}]}, "may only use a-z, 0-9 and _"),
        ({"recipes": [_RECIPE | {"ops": [{"op": "tint", "stops": "main"}]}]}, "at least 2"),
        ({"recipes": [_RECIPE | {"ops": [{"op": "tint", "stops": ["main"]}]}]}, "at least 2"),
        (
            {
                "recipes": [
                    _RECIPE | {"ops": [{"op": "tint", "stops": [["main"], ["ink", "main"]]}]}
                ]
            },
            "at least 2",
        ),
        (
            {"recipes": [_RECIPE | {"ops": [{"op": "gradient_fill", "stops": ["main"] * 3}]}]},
            "exactly 2",
        ),
        (
            {"recipes": [_RECIPE | {"ops": [{"op": "tile", "fill": ["main", "main", "main"]}]}]},
            "1 to 2",
        ),
    ],
)
def test_bad_theme_is_reported(tmp_path: Path, change: dict[str, object], message: str) -> None:
    _write_theme(tmp_path, _valid() | change)
    with pytest.raises(ThemeError, match=message):
        load_theme("t", tmp_path)


def test_duplicate_recipe_ids_are_rejected(tmp_path: Path) -> None:
    theme = _valid()
    theme["recipes"] = [_RECIPE, _RECIPE]
    _write_theme(tmp_path, theme)
    with pytest.raises(ThemeError, match="duplicate recipe id"):
        load_theme("t", tmp_path)


def test_top_level_must_be_object(tmp_path: Path) -> None:
    _write_theme(tmp_path, ["not", "a", "theme"])
    with pytest.raises(ThemeError, match="top level"):
        load_theme("t", tmp_path)


def test_missing_and_invalid_json(tmp_path: Path) -> None:
    with pytest.raises(ThemeError, match="file not found"):
        load_theme("nope", tmp_path)
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "theme.json").write_text("{", encoding="utf-8")
    with pytest.raises(ThemeError, match="invalid JSON"):
        load_theme("broken", tmp_path)


def test_recipes_come_from_the_library(tmp_path: Path) -> None:
    _write_library(tmp_path, [_RECIPE | {"id": "shared", "label": "Shared"}])
    theme = _valid() | {
        "recipes": ["shared", {"use": "shared", "id": "again", "label": "Again"}, _RECIPE]
    }
    _write_theme(tmp_path, theme)
    loaded = load_theme("t", tmp_path)
    assert [(r.id, r.label) for r in loaded.recipes] == [
        ("shared", "Shared"),
        ("again", "Again"),
        ("a", "A"),
    ]
    assert loaded.recipe("again").steps == loaded.recipe("shared").steps


def test_library_recipes_use_the_theme_palette(tmp_path: Path) -> None:
    recipe = _RECIPE | {"id": "inky", "ops": [{"op": "mono", "color": "glitter"}]}
    _write_library(tmp_path, [recipe])
    _write_theme(tmp_path, _valid() | {"recipes": ["inky"]})
    with pytest.raises(ThemeError, match=r"recipe 'inky'.*'glitter'"):
        load_theme("t", tmp_path)


def test_use_entries_may_only_rename(tmp_path: Path) -> None:
    _write_library(tmp_path, [_RECIPE])
    _write_theme(tmp_path, _valid() | {"recipes": [{"use": "a", "ops": []}]})
    with pytest.raises(ThemeError, match="may only change 'id' and 'label'"):
        load_theme("t", tmp_path)


@pytest.mark.parametrize(
    ("library", "message"),
    [
        ("{", "invalid JSON"),
        ('{"recipes": {}}', "'recipes' must be a list"),
        ('{"recipes": [{"label": "x"}]}', "string 'id'"),
    ],
)
def test_bad_library_is_reported(tmp_path: Path, library: str, message: str) -> None:
    (tmp_path / "_library").mkdir()
    (tmp_path / "_library" / "recipes.json").write_text(library, encoding="utf-8")
    _write_theme(tmp_path, _valid())
    with pytest.raises(ThemeError, match=message):
        load_theme("t", tmp_path)


@pytest.mark.parametrize("encoding", ["utf-16", "cp1252"])
def test_a_theme_not_saved_as_utf8_is_reported(tmp_path: Path, encoding: str) -> None:
    folder = tmp_path / "t"
    folder.mkdir()
    text = json.dumps(_valid() | {"name": "Pinkë"}, ensure_ascii=False)
    (folder / "theme.json").write_bytes(text.encode(encoding))
    with pytest.raises(ThemeError, match="save it as UTF-8"):
        load_theme("t", tmp_path)
    assert theme_name("t", tmp_path) == "t"


def test_a_utf8_theme_with_a_byte_order_mark_loads(tmp_path: Path) -> None:
    folder = tmp_path / "t"
    folder.mkdir()
    (folder / "theme.json").write_bytes(json.dumps(_valid()).encode("utf-8-sig"))
    assert load_theme("t", tmp_path).name == "Test"


def test_an_asset_that_is_a_folder_is_reported(tmp_path: Path) -> None:
    _write_theme(tmp_path, _valid() | {"assets": {"bow": "bow.png"}})
    (tmp_path / "t" / "bow.png").mkdir()
    with pytest.raises(ThemeError, match="asset 'bow'"):
        load_theme("t", tmp_path)


def test_theme_folder_names_are_checked(tmp_path: Path) -> None:
    with pytest.raises(ThemeError, match="may only use"):
        load_theme("My Theme", tmp_path)


def test_one_color_is_enough_for_every_library_style(tmp_path: Path) -> None:
    """Library recipes and the Taskbar page use seven names; the rest come from main."""
    bundled = load_theme(DEFAULT_THEME)
    library = json.loads((THEMES_DIR / "_library" / "recipes.json").read_text(encoding="utf-8"))
    (tmp_path / "_library").mkdir()
    (tmp_path / "_library" / "recipes.json").write_text(json.dumps(library), encoding="utf-8")
    theme = {
        "name": "One color",
        "palette": {"main": "#3FA7D6"},
        "assets": {name: f"{name}.png" for name in bundled.assets},
        "recipes": [r["id"] for r in library["recipes"]],
    }
    _write_theme(tmp_path, theme)
    for name in bundled.assets:
        bundled.assets[name].save(tmp_path / "t" / f"{name}.png")
    one = load_theme("t", tmp_path)
    icon, _ = ops.prepare(load_sample("multicolor"))
    for recipe in one.recipes:
        render(recipe, icon, one)
    taskbar.looks(one.palette)
    taskbar.gradient_wallpaper((64, 36), one.palette)
