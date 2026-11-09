"""Recipe families: the kind of look a recipe makes."""

from enum import StrEnum


class Family(StrEnum):
    """A theme orders its recipes so that neighbors come from different families."""

    RECOLOR = "recolor"
    GRADIENT = "gradient"
    MONO = "mono"
    TILE = "tile"
    PATTERN = "pattern"
    STICKER = "sticker"
    TINT = "tint"
    GLOW = "glow"


# Recipes that flatten an icon's colors into one ramp; busy icons show them last.
FLATTENING = frozenset({Family.TINT, Family.GLOW})
