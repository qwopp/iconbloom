"""Load themes: a palette, decoration assets and recipes, all from data files.

A theme is a folder containing ``theme.json`` and the PNG assets it names.
Adding a theme means adding a folder; no code changes. Recipes shared by
several themes live once in ``_library/recipes.json`` and are listed by id.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from engine import ops
from engine.recipes import Json, Recipe, RecipeError, parse_hex, parse_recipe

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"
THEME_FILE = "theme.json"
# Shared by every theme: recipes listed by id, and decoration templates.
LIBRARY = "_library"
LIBRARY_RECIPES = "recipes.json"
DEFAULT_THEME = "kawaii_pink"
_THEME_FIELDS = frozenset({"name", "palette", "decor", "assets", "recipes"})


class ThemeError(ValueError):
    """A theme folder can't be loaded. The message says which file and why."""


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    palette: Mapping[str, ops.RGB]
    assets: Mapping[str, Image.Image]
    recipes: tuple[Recipe, ...]

    def recipe(self, recipe_id: str) -> Recipe:
        for recipe in self.recipes:
            if recipe.id == recipe_id:
                return recipe
        raise KeyError(f"theme '{self.id}' has no recipe '{recipe_id}'")


def list_themes(themes_dir: Path = THEMES_DIR) -> list[str]:
    """Ids of the theme folders found, in alphabetical order."""
    if not themes_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in themes_dir.iterdir()
        if not p.name.startswith("_") and (p / THEME_FILE).is_file()
    )


def theme_name(theme_id: str, themes_dir: Path = THEMES_DIR) -> str:
    """Display name without loading assets or recipes, for menus."""
    try:
        raw: Json = json.loads((themes_dir / theme_id / THEME_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return theme_id
    name = raw.get("name") if isinstance(raw, dict) else None
    return name if isinstance(name, str) else theme_id


def load_theme(theme_id: str, themes_dir: Path = THEMES_DIR) -> Theme:
    folder = themes_dir / theme_id
    path = folder / THEME_FILE
    raw = _read_json(path)
    try:
        return _build(theme_id, folder, raw, load_library(themes_dir))
    except (ThemeError, RecipeError) as exc:
        raise ThemeError(f"{path}: {exc}") from exc


def load_library(themes_dir: Path = THEMES_DIR) -> dict[str, dict[str, Json]]:
    """The shared recipes, by id, still in their JSON form (each theme validates its own)."""
    path = themes_dir / LIBRARY / LIBRARY_RECIPES
    if not path.is_file():
        return {}
    raw = _read_json(path)
    items = raw.get("recipes") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ThemeError(f"{path}: 'recipes' must be a list")
    library: dict[str, dict[str, Json]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ThemeError(f"{path}: every recipe needs a string 'id'")
        library[str(item["id"])] = item
    return library


def _read_json(path: Path) -> Json:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ThemeError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise ThemeError(f"{path}: invalid JSON ({exc})") from exc


def _resolve(entry: Json, library: Mapping[str, dict[str, Json]]) -> Json:
    """A theme's recipe entry: a library id, {"use": id, "label": ...}, or a full recipe."""
    if isinstance(entry, str):
        if entry not in library:
            raise ThemeError(f"no library recipe called '{entry}'")
        return library[entry]
    if isinstance(entry, dict) and "use" in entry:
        used = entry["use"]
        if not isinstance(used, str) or used not in library:
            raise ThemeError(f"no library recipe called {used!r}")
        overrides = {k: v for k, v in entry.items() if k != "use"}
        if set(overrides) - {"id", "label"}:
            raise ThemeError(f"'use' entries may only change 'id' and 'label' ({used})")
        return library[used] | overrides
    return entry


def _build(theme_id: str, folder: Path, raw: Json, library: Mapping[str, dict[str, Json]]) -> Theme:
    if not isinstance(raw, dict):
        raise ThemeError("top level must be a JSON object")
    unknown = sorted(set(raw) - _THEME_FIELDS)
    if unknown:
        raise ThemeError(f"unknown field(s) {', '.join(unknown)}")
    name = raw.get("name", theme_id)
    if not isinstance(name, str):
        raise ThemeError("'name' must be a string")
    palette = _palette(raw.get("palette"))
    if "decor" in raw:  # only scripts/render_assets.py reads it; check it here all the same
        _palette(raw["decor"], "decor")
    assets = _assets(folder, raw.get("assets", {}))
    raw_recipes = raw.get("recipes")
    if not isinstance(raw_recipes, list) or not raw_recipes:
        raise ThemeError("'recipes' must be a non-empty list")
    recipes = tuple(
        parse_recipe(_resolve(entry, library), palette, list(assets)) for entry in raw_recipes
    )
    ids = [r.id for r in recipes]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ThemeError(f"duplicate recipe id(s): {', '.join(duplicates)}")
    return Theme(id=theme_id, name=name, palette=palette, assets=assets, recipes=recipes)


def _palette(raw: Json, field: str = "palette") -> dict[str, ops.RGB]:
    if not isinstance(raw, dict) or not raw:
        raise ThemeError(f"'{field}' must be an object of name: \"#RRGGBB\" pairs")
    palette: dict[str, ops.RGB] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise ThemeError(f"{field} color '{key}' must be a \"#RRGGBB\" string")
        try:
            palette[key] = parse_hex(value)
        except ValueError as exc:
            raise ThemeError(f"{field} color '{key}': {exc}") from exc
    return palette


def _assets(folder: Path, raw: Json) -> dict[str, Image.Image]:
    if not isinstance(raw, dict):
        raise ThemeError("'assets' must be an object of name: \"file.png\" pairs")
    assets: dict[str, Image.Image] = {}
    for key, filename in raw.items():
        if not isinstance(filename, str):
            raise ThemeError(f"asset '{key}' must be a file name")
        path = folder / filename
        try:
            with Image.open(path) as img:
                assets[key] = img.convert("RGBA")
        except FileNotFoundError as exc:
            raise ThemeError(f"asset '{key}': {filename} not found") from exc
        except UnidentifiedImageError as exc:
            raise ThemeError(f"asset '{key}': {filename} is not an image") from exc
    return assets
