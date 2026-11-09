"""Recipes: named, ordered lists of ops, and the runner that renders them.

A recipe step names an op and gives its parameters in theme terms: palette
keys instead of RGB values, asset names instead of images. This module checks
those parameters when a theme loads, then turns them into concrete values at
render time.

Shuffle works through the same parameters. Any value written as a JSON list
where a single value is expected is a set of choices, and a number parameter
may jitter. Seed 0 always takes the first choice with no jitter, so the
default look is stable; other seeds pick from a ``random.Random`` derived
from the seed and the recipe id.
"""

import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from PIL import Image

from engine import analyze, ops
from engine.families import Family

if TYPE_CHECKING:
    from engine.themes import Theme

type ParamKind = Literal["color", "colors", "asset", "number", "bool", "choice"]
type Json = str | int | float | bool | list[Json] | dict[str, Json] | None

AUTO_COLOR = "auto"
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class RecipeError(ValueError):
    """A recipe in a theme file is malformed. The message names where."""


@dataclass(frozen=True)
class Param:
    kind: ParamKind
    default: Json = None
    required: bool = False
    low: float = 0.0
    high: float = 1.0
    choices: tuple[str, ...] = ()
    # Largest random nudge a shuffled render may add to a number parameter.
    jitter: float = 0.0


@dataclass(frozen=True)
class OpDef:
    func: Callable[..., Image.Image]
    params: Mapping[str, Param]
    # Decorative ops are dropped from the simplified render used for the
    # 16 and 24 px icon frames, where they would only add noise.
    decorative: bool = False


_SHAPES = ("squircle", "circle", "rounded")
_PATTERNS = ("dots", "stripes", "gingham", "hearts")
_CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")

OPS: Mapping[str, OpDef] = {
    "tint": OpDef(
        ops.tint,
        {
            "stops": Param("colors", required=True),
            "strength": Param("number", 1.0),
        },
    ),
    "soft_tint": OpDef(
        ops.soft_tint,
        {
            "color": Param("color", required=True),
            "amount": Param("number", 0.45, jitter=0.08),
        },
    ),
    "recolor": OpDef(
        ops.recolor,
        {
            "stops": Param("colors", required=True),
            "strength": Param("number", 1.0),
        },
    ),
    "mono": OpDef(
        ops.mono,
        {"color": Param("color", required=True), "knockout": Param("bool", True)},
    ),
    "gradient_fill": OpDef(
        ops.gradient_fill,
        {
            "stops": Param("colors", required=True),
            "angle": Param("number", 90.0, low=-360, high=360, jitter=20),
            "knockout": Param("bool", True),
        },
    ),
    "tile": OpDef(
        ops.tile,
        {
            "fill": Param("colors", required=True),
            "shape": Param("choice", "squircle", choices=_SHAPES),
            "angle": Param("number", 90.0, low=-360, high=360, jitter=20),
            "scale": Param("number", 0.7, low=0.3, high=1.0),
            "shadow": Param("bool", True),
            "outline": Param("color"),
            "pattern": Param("choice", choices=_PATTERNS),
            "pattern_color": Param("color", "#FFFFFF"),
        },
    ),
    "sticker_outline": OpDef(
        ops.sticker_outline,
        {
            "thickness": Param("number", 10.0, low=1, high=24),
            "color": Param("color", "#FFFFFF"),
            "shadow": Param("bool", True),
        },
    ),
    "glow": OpDef(
        ops.glow,
        {
            "color": Param("color", required=True),
            "radius": Param("number", 10.0, low=1, high=24),
            "strength": Param("number", 0.8),
        },
    ),
    "overlay_face": OpDef(
        ops.overlay_face,
        {
            "face": Param("asset", required=True),
            "scale": Param("number", 0.42, low=0.1, high=0.9),
            "offset_x": Param("number", 0.0, low=-0.5, high=0.5, jitter=0.06),
            "offset_y": Param("number", 0.16, low=-0.5, high=0.5, jitter=0.05),
        },
        decorative=True,
    ),
    "badge": OpDef(
        ops.badge,
        {
            "asset": Param("asset", required=True),
            "corner": Param("choice", "top-right", choices=(*_CORNERS, "random")),
            "scale": Param("number", 0.35, low=0.1, high=0.6),
            "rotation": Param("number", 0.0, low=-180, high=180, jitter=12),
        },
        decorative=True,
    ),
}


@dataclass(frozen=True)
class Step:
    op: str
    params: Mapping[str, Json] = field(default_factory=dict[str, Json])


_RECIPE_FIELDS = frozenset({"id", "label", "family", "ops"})


@dataclass(frozen=True)
class Recipe:
    id: str
    label: str
    family: Family
    steps: tuple[Step, ...]


def parse_recipe(raw: Json, palette: Mapping[str, ops.RGB], assets: Sequence[str]) -> Recipe:
    """Build a Recipe from its theme.json form, checking every field, step and parameter."""
    if not isinstance(raw, dict):
        raise RecipeError("each recipe must be a JSON object")
    data = dict(raw)
    recipe_id = data.get("id")
    if not isinstance(recipe_id, str) or not recipe_id:
        raise RecipeError("recipe is missing a string 'id'")
    where = f"recipe '{recipe_id}'"
    unknown = sorted(set(data) - _RECIPE_FIELDS)
    if unknown:
        raise RecipeError(f"{where}: unknown field(s) {', '.join(unknown)}")
    label = data.get("label", recipe_id)
    family = data.get("family")
    raw_steps = data.get("ops")
    if not isinstance(label, str):
        raise RecipeError(f"{where}: 'label' must be a string")
    if family not in set(Family):
        known = ", ".join(Family)
        raise RecipeError(f"{where}: 'family' must be one of {known}")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RecipeError(f"{where}: 'ops' must be a non-empty list")
    steps = tuple(
        _parse_step(step, f"{where}, step {i + 1}", palette, assets)
        for i, step in enumerate(raw_steps)
    )
    return Recipe(id=recipe_id, label=label, family=Family(family), steps=steps)


def render(
    recipe: Recipe,
    icon: Image.Image,
    theme: "Theme",
    *,
    seed: int = 0,
    simplified: bool = False,
) -> Image.Image:
    """Run a recipe on a prepared icon (see ``ops.prepare``)."""
    rng = random.Random(f"{seed}:{recipe.id}")
    resolver = _Resolver(icon, theme, rng, shuffle=seed != 0)
    out = icon
    for step in recipe.steps:
        op_def = OPS[step.op]
        if simplified and op_def.decorative:
            continue
        kwargs = {
            name: resolver.resolve(spec, step.params.get(name, spec.default))
            for name, spec in op_def.params.items()
            if name in step.params or spec.default is not None
        }
        out = op_def.func(out, **kwargs)
    return out


def _parse_step(
    raw: Json, where: str, palette: Mapping[str, ops.RGB], assets: Sequence[str]
) -> Step:
    if not isinstance(raw, dict):
        raise RecipeError(f"{where}: must be a JSON object")
    data = dict(raw)
    op_name = data.pop("op", None)
    if not isinstance(op_name, str) or op_name not in OPS:
        known = ", ".join(sorted(OPS))
        raise RecipeError(f"{where}: unknown op {op_name!r} (known ops: {known})")
    where = f"{where} ({op_name})"
    op_def = OPS[op_name]
    unknown = sorted(set(data) - set(op_def.params))
    if unknown:
        raise RecipeError(f"{where}: unknown parameter(s) {', '.join(unknown)}")
    for name, spec in op_def.params.items():
        if name in data:
            _check_value(spec, data[name], f"{where}, '{name}'", palette, assets)
        elif spec.required:
            raise RecipeError(f"{where}: missing required parameter '{name}'")
    return Step(op=op_name, params=data)


def _check_value(
    spec: Param, value: Json, where: str, palette: Mapping[str, ops.RGB], assets: Sequence[str]
) -> None:
    # A list where one value is expected means "pick one when shuffling".
    if isinstance(value, list) and spec.kind != "colors":
        if not value:
            raise RecipeError(f"{where}: list of choices is empty")
        for choice in value:
            _check_value(spec, choice, where, palette, assets)
        return
    if spec.kind == "color":
        _check_color(value, where, palette)
    elif spec.kind == "colors":
        _check_colors(value, where, palette)
    elif spec.kind == "asset":
        if value not in assets:
            raise RecipeError(f"{where}: unknown asset {value!r}")
    elif spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RecipeError(f"{where}: expected a number")
        if not spec.low <= value <= spec.high:
            raise RecipeError(f"{where}: {value} is outside {spec.low}..{spec.high}")
    elif spec.kind == "bool":
        if not isinstance(value, bool):
            raise RecipeError(f"{where}: expected true or false")
    elif value not in spec.choices:
        raise RecipeError(f"{where}: expected one of {', '.join(spec.choices)}")


def _check_color(value: Json, where: str, palette: Mapping[str, ops.RGB]) -> None:
    if not isinstance(value, str):
        raise RecipeError(f"{where}: colors are palette names or #RRGGBB strings")
    if value != AUTO_COLOR and value not in palette and not _HEX_COLOR.match(value):
        raise RecipeError(f"{where}: {value!r} is not a palette name or #RRGGBB color")


def _check_colors(value: Json, where: str, palette: Mapping[str, ops.RGB]) -> None:
    if isinstance(value, str):
        _check_color(value, where, palette)
        return
    if not isinstance(value, list) or not value:
        raise RecipeError(f"{where}: expected a color or a list of colors")
    if all(isinstance(v, list) for v in value):
        # A list of lists is a set of stop lists to choose between.
        for option in value:
            _check_colors(option, where, palette)
        return
    for color in value:
        _check_color(color, where, palette)


def parse_hex(value: str) -> ops.RGB:
    if not _HEX_COLOR.match(value):
        raise ValueError(f"{value!r} is not a #RRGGBB color")
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


class _Resolver:
    """Turns validated theme-level values into the concrete values ops take."""

    def __init__(
        self, icon: Image.Image, theme: "Theme", rng: random.Random, *, shuffle: bool
    ) -> None:
        self._icon = icon
        self._theme = theme
        self._rng = rng
        self._shuffle = shuffle
        self._auto: ops.RGB | None = None

    def resolve(self, spec: Param, value: Json) -> object:
        if spec.kind == "colors":
            if isinstance(value, list) and all(isinstance(v, list) for v in value):
                value = self._pick(value)
            items = value if isinstance(value, list) else [value]
            return [self._color(item) for item in items]
        if isinstance(value, list):
            value = self._pick(value)
        if spec.kind == "color":
            return self._color(value)
        if spec.kind == "asset":
            return self._theme.assets[str(value)]
        if spec.kind == "number" and isinstance(value, int | float):
            number = float(value)
            if self._shuffle and spec.jitter:
                number += self._rng.uniform(-spec.jitter, spec.jitter)
            return min(max(number, spec.low), spec.high)
        if spec.kind == "choice" and value == "random":
            options = [c for c in spec.choices if c != "random"]
            return self._pick(options)
        return value

    def _pick[T](self, options: Sequence[T]) -> T:
        return self._rng.choice(options) if self._shuffle else options[0]

    def _color(self, value: Json) -> ops.RGB:
        name = str(value)
        if name == AUTO_COLOR:
            if self._auto is None:
                self._auto = analyze.nearest_shade(self._icon, self._theme.palette)
            return self._auto
        if name in self._theme.palette:
            return self._theme.palette[name]
        return parse_hex(name)
