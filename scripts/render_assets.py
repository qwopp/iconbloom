"""Render each theme's decorations to the PNGs the engine loads.

The decorations are hand-drawn SVG templates in themes/_library/decorations/,
shared by every theme. Their colors are tokens such as ``{fill}`` or
``{outline}``, filled from the theme's ``"decor"`` colors, so one bow drawing
becomes a pink bow, a mint bow or a neon bow. A theme can also keep its own
SVGs in themes/<theme>/src/, with the same tokens.

Run after editing any SVG or a theme's decor colors:

    uv run python -m scripts.render_assets

Each PNG a theme lists under "assets" is rendered from the SVG of the same
name. The PNGs are committed so the app never needs an SVG renderer at runtime.
"""

import argparse
import io
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import resvg_py
from PIL import Image

from engine.themes import LIBRARY, THEME_FILE, THEMES_DIR, list_themes

DECORATIONS = THEMES_DIR / LIBRARY / "decorations"
# Rendered larger than any badge will be drawn, so downscaling stays crisp.
RENDER_WIDTH = 512
_TOKEN = re.compile(r"\{(\w+)\}")


def fill_tokens(svg: str, colors: Mapping[str, str]) -> str:
    """Replace every ``{token}`` with the theme's color for it."""

    def color(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in colors:
            raise KeyError(f"no decor color '{token}'")
        return colors[token]

    return _TOKEN.sub(color, svg)


def render_svg(svg: str, width: int = RENDER_WIDTH) -> Image.Image:
    png = resvg_py.svg_to_bytes(svg_string=svg, width=width)
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


def find_source(theme_dir: Path, stem: str, decorations: Path = DECORATIONS) -> Path | None:
    """The theme's own SVG for an asset if it has one, otherwise the shared template."""
    for folder in (theme_dir / "src", decorations):
        path = folder / f"{stem}.svg"
        if path.is_file():
            return path
    return None


def render_theme(theme_dir: Path, decorations: Path = DECORATIONS) -> list[Path]:
    raw = json.loads((theme_dir / THEME_FILE).read_text(encoding="utf-8"))
    colors: dict[str, str] = raw.get("decor", {})
    written: list[Path] = []
    for filename in raw.get("assets", {}).values():
        out_path = theme_dir / filename
        source = find_source(theme_dir, out_path.stem, decorations)
        if source is None:
            continue  # a plain PNG the theme ships as it is
        try:
            svg = fill_tokens(source.read_text(encoding="utf-8"), colors)
        except KeyError as exc:
            raise SystemExit(f"{theme_dir.name}/{filename}: {exc.args[0]}") from exc
        render_svg(svg).save(out_path, optimize=True)
        written.append(out_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render theme decorations to PNG.")
    parser.add_argument("themes", nargs="*", help="theme folder names (default: all)")
    args = parser.parse_args(argv)
    names: list[str] = args.themes or list_themes()
    for name in names:
        for path in render_theme(THEMES_DIR / name):
            print(path.relative_to(THEMES_DIR.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
