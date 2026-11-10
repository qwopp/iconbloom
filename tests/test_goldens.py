"""Every recipe of every theme on sample icons, compared with checked-in renders.

Kawaii Pink, the default, is checked on every sample; the other themes on a
few that cover the main kinds of icon. When a styling change is intended,
regenerate with:

    uv run pytest tests/test_goldens.py --update-goldens

and review the changed PNGs in the diff before committing them.
"""

from functools import cache
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine import ops
from engine.recipes import render
from engine.themes import DEFAULT_THEME, Theme, list_themes, load_theme
from tests.conftest import REPRESENTATIVE_SAMPLES, load_sample, sample_names

GOLDENS_DIR = Path(__file__).parent / "goldens"
# Allows for tiny rounding differences between platforms, nothing visible.
MAX_CHANNEL_DIFF = 2
MIN_MATCHING_SHARE = 0.995
# The taskbar previews keep their goldens here; test_taskbar_engine checks those.
TASKBAR_GOLDENS = GOLDENS_DIR / "taskbar"


@cache
def _theme(theme_id: str) -> Theme:
    return load_theme(theme_id)


def _cases() -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    for theme_id in list_themes():
        samples = sample_names() if theme_id == DEFAULT_THEME else REPRESENTATIVE_SAMPLES
        cases += [(theme_id, s, r.id) for s in samples for r in _theme(theme_id).recipes]
    return cases


def test_representative_samples_exist() -> None:
    assert set(REPRESENTATIVE_SAMPLES) <= set(sample_names())


@pytest.mark.parametrize(("theme_id", "sample", "recipe_id"), _cases())
def test_recipe_matches_golden(
    theme_id: str, sample: str, recipe_id: str, update_goldens: bool
) -> None:
    theme = _theme(theme_id)
    icon, _ = ops.prepare(load_sample(sample))
    result = render(theme.recipe(recipe_id), icon, theme)
    golden_path = GOLDENS_DIR / theme_id / f"{sample}__{recipe_id}.png"

    if update_goldens:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(golden_path, optimize=True)
        return

    assert golden_path.exists(), f"missing golden {golden_path.name}; run with --update-goldens"
    with Image.open(golden_path) as golden:
        expected = np.asarray(golden.convert("RGBA"), dtype=np.int16)
    actual = np.asarray(result, dtype=np.int16)
    assert actual.shape == expected.shape
    close = (np.abs(actual - expected) <= MAX_CHANNEL_DIFF).all(axis=-1)
    assert close.mean() >= MIN_MATCHING_SHARE, (
        f"{theme_id}/{golden_path.name}: only {close.mean():.2%} of pixels match"
    )


def test_no_stale_goldens() -> None:
    """A renamed or removed recipe must take its golden with it."""
    expected = {GOLDENS_DIR / t / f"{s}__{r}.png" for t, s, r in _cases()}
    found = {p for p in GOLDENS_DIR.rglob("*.png") if TASKBAR_GOLDENS not in p.parents}
    assert found == expected
