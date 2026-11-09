"""Measure an icon's colors to decide which recipes to show it first."""

import colorsys
import math
from collections.abc import Iterable, Mapping
from typing import Protocol

import numpy as np
import numpy.typing as npt
from PIL import Image

from engine.ops import RGB

# Hasler-Suesstrunk scores at or above this count as colorful. On the sample
# icons, flat glyphs, line art and dark icons score under 40; vivid icons
# score over 60, whether they use one strong hue or many.
COLORFUL_THRESHOLD = 45.0
_OPAQUE = 128
_MIN_SATURATION = 0.25


class Orderable(Protocol):
    @property
    def keeps_color(self) -> bool: ...


def colorfulness(img: Image.Image) -> float:
    """Hasler-Suesstrunk colorfulness over the icon's opaque pixels.

    Roughly 0 for gray, 15-35 for one or two muted hues, 60+ for vivid multicolor.
    """
    pixels = _opaque_rgb(img)
    if len(pixels) == 0:
        return 0.0
    r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    rg = r - g
    yb = (r + g) / 2 - b
    spread = math.hypot(float(rg.std()), float(yb.std()))
    mean = math.hypot(float(rg.mean()), float(yb.mean()))
    return spread + 0.3 * mean


def is_colorful(img: Image.Image) -> bool:
    return colorfulness(img) >= COLORFUL_THRESHOLD


def dominant_hue(img: Image.Image) -> float | None:
    """Most common hue in degrees, weighted by saturation, or None for gray icons."""
    pixels = _opaque_rgb(img) / 255
    if len(pixels) == 0:
        return None
    high = pixels.max(axis=1)
    low = pixels.min(axis=1)
    saturation = np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0.0)
    vivid = saturation >= _MIN_SATURATION
    if vivid.sum() < max(16, len(pixels) * 0.05):
        return None
    hues = _hues(pixels[vivid], high[vivid], low[vivid])
    histogram, edges = np.histogram(hues, bins=36, range=(0, 360), weights=saturation[vivid])
    peak = int(np.argmax(histogram))
    return float(edges[peak] + 5.0)


def nearest_shade(img: Image.Image, palette: Mapping[str, RGB]) -> RGB:
    """Palette color closest in hue to the icon, so a blue icon goes lavender, not muddy pink.

    Gray icons, and palettes with no saturated colors, get the most saturated
    palette color.
    """
    candidates = [(c, *_hsv(c)) for c in palette.values()]
    saturated = [c for c in candidates if c[2] >= 0.2] or candidates
    hue = dominant_hue(img)
    if hue is None:
        return max(saturated, key=lambda c: c[2])[0]
    return min(saturated, key=lambda c: _hue_distance(c[1], hue))[0]


def order_recipes[R: Orderable](recipes: Iterable[R], icon: Image.Image) -> list[R]:
    """Best-first order: color-keeping recipes lead for busy icons, tints for simple ones.

    The sort is stable, so the theme's own order holds within each group.
    """
    colorful = is_colorful(icon)
    return sorted(recipes, key=lambda r: r.keeps_color != colorful)


def _hues(
    rgb: npt.NDArray[np.float64], high: npt.NDArray[np.float64], low: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Vectorized HSV hue in degrees for pixels already known to be saturated."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    span = np.maximum(high - low, 1e-6)
    hue = np.where(
        high == r,
        ((g - b) / span) % 6,
        np.where(high == g, (b - r) / span + 2, (r - g) / span + 4),
    )
    return (hue * 60).astype(np.float64)


def _opaque_rgb(img: Image.Image) -> npt.NDArray[np.float64]:
    arr = np.asarray(img.convert("RGBA"), dtype=np.float64)
    mask = arr[..., 3] >= _OPAQUE
    return arr[mask][:, :3]


def _hsv(color: RGB) -> tuple[float, float]:
    h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in color))
    return h * 360, s


def _hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)
