import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine.themes import LIBRARY, THEMES_DIR, list_themes
from scripts.render_assets import DECORATIONS, fill_tokens, find_source, render_theme

TEMPLATES = sorted(p.stem for p in DECORATIONS.glob("*.svg"))


def test_fill_tokens_replaces_every_token() -> None:
    svg = '<path fill="{fill}" stroke="{outline}"/>'
    assert fill_tokens(svg, {"fill": "#111111", "outline": "#222222"}) == (
        '<path fill="#111111" stroke="#222222"/>'
    )


def test_fill_tokens_names_a_missing_color() -> None:
    with pytest.raises(KeyError, match="no decor color 'blush'"):
        fill_tokens('<ellipse fill="{blush}"/>', {})


def test_kawaii_decor_colors_cover_every_template() -> None:
    kawaii = json.loads((THEMES_DIR / "kawaii_pink" / "theme.json").read_text(encoding="utf-8"))
    for name in TEMPLATES:
        fill_tokens((DECORATIONS / f"{name}.svg").read_text(encoding="utf-8"), kawaii["decor"])


def test_new_decorations_exist() -> None:
    assert {"star", "flower", "cloud", "moon", "leaf", "sun"} <= set(TEMPLATES)


@pytest.mark.parametrize("theme_id", list_themes())
def test_committed_pngs_match_their_templates(theme_id: str, tmp_path: Path) -> None:
    """Editing an SVG or a theme's decor colors without re-rendering fails here."""
    source = THEMES_DIR / theme_id
    copy = tmp_path / theme_id
    copy.mkdir()
    (copy / "theme.json").write_bytes((source / "theme.json").read_bytes())
    if (source / "src").is_dir():
        shutil.copytree(source / "src", copy / "src")
    for path in render_theme(copy):
        fresh = np.asarray(Image.open(path).convert("RGBA"), dtype=int)
        committed = np.asarray(Image.open(source / path.name).convert("RGBA"), dtype=int)
        assert fresh.shape == committed.shape, path.name
        # Allow tiny rasterizer differences between platforms, nothing a person could see.
        assert np.abs(fresh - committed).max() <= 2, path.name


def test_theme_svg_overrides_the_shared_template(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    own = tmp_path / "src" / "bow.svg"
    own.write_text("<svg/>", encoding="utf-8")
    assert find_source(tmp_path, "bow") == own
    assert find_source(tmp_path, "star") == THEMES_DIR / LIBRARY / "decorations" / "star.svg"
    assert find_source(tmp_path, "nothing") is None


def test_plain_png_assets_are_left_alone(tmp_path: Path) -> None:
    theme = {"decor": {}, "assets": {"photo": "photo.png"}}
    (tmp_path / "theme.json").write_text(json.dumps(theme), encoding="utf-8")
    assert render_theme(tmp_path) == []
