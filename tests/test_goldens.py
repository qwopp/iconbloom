"""Every Kawaii Pink recipe on every sample icon, compared with checked-in renders.

When a styling change is intended, regenerate with:

    uv run pytest tests/test_goldens.py --update-goldens

and review the changed PNGs in the diff before committing them.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine import ops
from engine.recipes import render
from engine.themes import Theme, load_theme
from tests.conftest import load_sample, sample_names

GOLDENS_DIR = Path(__file__).parent / "goldens"
# Allows for tiny rounding differences between platforms, nothing visible.
MAX_CHANNEL_DIFF = 2
MIN_MATCHING_SHARE = 0.995

_THEME = load_theme("kawaii_pink")
CASES = [(s, r.id) for s in sample_names() for r in _THEME.recipes]


@pytest.mark.parametrize(("sample", "recipe_id"), CASES)
def test_recipe_matches_golden(
    sample: str, recipe_id: str, kawaii: Theme, update_goldens: bool
) -> None:
    icon, _ = ops.prepare(load_sample(sample))
    result = render(kawaii.recipe(recipe_id), icon, kawaii)
    golden_path = GOLDENS_DIR / f"{sample}__{recipe_id}.png"

    if update_goldens:
        GOLDENS_DIR.mkdir(exist_ok=True)
        result.save(golden_path, optimize=True)
        return

    assert golden_path.exists(), f"missing golden {golden_path.name}; run with --update-goldens"
    with Image.open(golden_path) as golden:
        expected = np.asarray(golden.convert("RGBA"), dtype=np.int16)
    actual = np.asarray(result, dtype=np.int16)
    assert actual.shape == expected.shape
    close = (np.abs(actual - expected) <= MAX_CHANNEL_DIFF).all(axis=-1)
    assert close.mean() >= MIN_MATCHING_SHARE, (
        f"{golden_path.name}: only {close.mean():.2%} of pixels match"
    )
