"""Render each theme's hand-drawn SVG decorations to the PNGs the engine loads.

Run after editing any SVG under themes/<theme>/src/:

    uv run python -m scripts.render_assets

The PNGs are committed so the app never needs an SVG renderer at runtime.
"""

import argparse
import io
import sys
from pathlib import Path

import resvg_py
from PIL import Image

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"
# Rendered larger than any badge will be drawn, so downscaling stays crisp.
RENDER_WIDTH = 512


def render_svg(svg_path: Path, width: int = RENDER_WIDTH) -> Image.Image:
    png = resvg_py.svg_to_bytes(svg_path=str(svg_path), width=width)
    return Image.open(io.BytesIO(bytes(png))).convert("RGBA")


def render_theme(theme_dir: Path) -> list[Path]:
    written: list[Path] = []
    for svg_path in sorted((theme_dir / "src").glob("*.svg")):
        out_path = theme_dir / f"{svg_path.stem}.png"
        render_svg(svg_path).save(out_path, optimize=True)
        written.append(out_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render theme SVG decorations to PNG.")
    parser.add_argument("themes", nargs="*", help="theme folder names (default: all)")
    args = parser.parse_args(argv)
    names: list[str] = args.themes or sorted(p.name for p in THEMES_DIR.iterdir() if p.is_dir())
    for name in names:
        for path in render_theme(THEMES_DIR / name):
            print(path.relative_to(THEMES_DIR.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
