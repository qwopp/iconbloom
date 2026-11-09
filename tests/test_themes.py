import json
from pathlib import Path

import pytest
from PIL import Image

from engine.themes import ThemeError, list_themes, load_theme

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


def test_kawaii_pink_loads_with_twelve_recipes() -> None:
    theme = load_theme("kawaii_pink")
    assert theme.name == "Kawaii Pink"
    assert len(theme.recipes) == 12
    assert set(theme.assets) == {"bow", "heart", "face", "sparkle"}


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
    _write_library(tmp_path, [_RECIPE | {"id": "inky", "ops": [{"op": "mono", "color": "ink"}]}])
    _write_theme(tmp_path, _valid() | {"recipes": ["inky"]})
    with pytest.raises(ThemeError, match=r"recipe 'inky'.*'ink'"):
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
