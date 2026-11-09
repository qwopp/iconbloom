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
    # Cut a logo out of its plain background; only offered for icons that have one,
    # always as the last row.
    CUTOUT = "cutout"


# Recipes that flatten an icon's colors into one ramp; busy icons show them last.
FLATTENING = frozenset({Family.TINT, Family.GLOW})
# Recipes shown last, in a row of their own.
OWN_ROW = frozenset({Family.CUTOUT})
