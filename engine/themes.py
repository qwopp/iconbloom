"""Load themes: a palette, decoration assets and recipes, all from data files.

A theme is a folder containing ``theme.json`` and the PNG assets it names.
Adding a theme means adding a folder; no code changes.
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
DEFAULT_THEME = "kawaii_pink"


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
    return sorted(p.name for p in themes_dir.iterdir() if (p / THEME_FILE).is_file())


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
    try:
        raw: Json = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ThemeError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise ThemeError(f"{path}: invalid JSON ({exc})") from exc
    try:
        return _build(theme_id, folder, raw)
    except (ThemeError, RecipeError) as exc:
        raise ThemeError(f"{path}: {exc}") from exc


def _build(theme_id: str, folder: Path, raw: Json) -> Theme:
    if not isinstance(raw, dict):
        raise ThemeError("top level must be a JSON object")
    name = raw.get("name", theme_id)
    if not isinstance(name, str):
        raise ThemeError("'name' must be a string")
    palette = _palette(raw.get("palette"))
    assets = _assets(folder, raw.get("assets", {}))
    raw_recipes = raw.get("recipes")
    if not isinstance(raw_recipes, list) or not raw_recipes:
        raise ThemeError("'recipes' must be a non-empty list")
    recipes = tuple(parse_recipe(r, palette, list(assets)) for r in raw_recipes)
    ids = [r.id for r in recipes]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ThemeError(f"duplicate recipe id(s): {', '.join(duplicates)}")
    return Theme(id=theme_id, name=name, palette=palette, assets=assets, recipes=recipes)


def _palette(raw: Json) -> dict[str, ops.RGB]:
    if not isinstance(raw, dict) or not raw:
        raise ThemeError("'palette' must be an object of name: \"#RRGGBB\" pairs")
    palette: dict[str, ops.RGB] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise ThemeError(f"palette color '{key}' must be a \"#RRGGBB\" string")
        try:
            palette[key] = parse_hex(value)
        except ValueError as exc:
            raise ThemeError(f"palette color '{key}': {exc}") from exc
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
