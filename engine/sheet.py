"""Render every recipe of a theme for a folder of icons into one PNG grid.

    uv run python -m engine.sheet tests/samples -o contact_sheet.png

Each cell shows the 128 px render and, underneath on a desktop-like
background, the 48, 32 and 16 px versions at the sizes Windows really uses.
Use it to judge a theme before touching any shortcut.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from engine import analyze, ops
from engine.ico import frame_source
from engine.recipes import render
from engine.themes import DEFAULT_THEME, THEMES_DIR, Theme, load_theme

CELL = 128
GAP = 14
LABEL_H = 36
SMALL_H = 56
ROW_LABEL_W = 150
BACKGROUND = (255, 247, 250)
DESKTOP = (74, 106, 150)
TEXT = (120, 60, 90)
SMALL_SIZES = (48, 32, 16)


def build_sheet(
    icons: Sequence[tuple[str, Image.Image]], theme: Theme, seed: int = 0
) -> Image.Image:
    columns = len(theme.recipes) + 1
    row_h = CELL + SMALL_H + GAP
    width = ROW_LABEL_W + columns * (CELL + GAP) + GAP
    height = LABEL_H + len(icons) * row_h + GAP
    sheet = Image.new("RGBA", (width, height), (*BACKGROUND, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=13)

    headers = ["original", *(r.label for r in theme.recipes)]
    for col, header in enumerate(headers):
        x = ROW_LABEL_W + col * (CELL + GAP) + CELL // 2
        draw.text((x, LABEL_H // 2), header, fill=TEXT, font=font, anchor="mm")

    for row, (name, raw) in enumerate(icons):
        y = LABEL_H + row * row_h
        icon, upscaled = ops.prepare(raw)
        score = analyze.colorfulness(icon)
        caption = f"{name}\ncolor {score:.0f}" + ("\n(upscaled)" if upscaled else "")
        draw.multiline_text((GAP, y + CELL // 2), caption, fill=TEXT, font=font, anchor="lm")
        renders = [(icon, icon)] + [
            (
                render(recipe, icon, theme, seed=seed),
                render(recipe, icon, theme, seed=seed, simplified=True),
            )
            for recipe in theme.recipes
        ]
        for col, (full, simple) in enumerate(renders):
            x = ROW_LABEL_W + col * (CELL + GAP)
            _paste_cell(sheet, full, simple, x, y)
    return sheet


def _paste_cell(sheet: Image.Image, full: Image.Image, simple: Image.Image, x: int, y: int) -> None:
    sheet.alpha_composite(full.resize((CELL, CELL), Image.Resampling.LANCZOS), (x, y))
    strip = Image.new("RGBA", (CELL, SMALL_H - 6), (*DESKTOP, 255))
    cursor = 6
    for size in SMALL_SIZES:
        small = frame_source(size, full, simple).resize((size, size), Image.Resampling.LANCZOS)
        strip.alpha_composite(small, (cursor, (strip.height - size) // 2))
        cursor += size + 10
    sheet.alpha_composite(strip, (x, y + CELL + 4))


def load_icons(folder: Path) -> list[tuple[str, Image.Image]]:
    icons: list[tuple[str, Image.Image]] = []
    for path in sorted(folder.glob("*.png")):
        with Image.open(path) as img:
            icons.append((path.stem, img.convert("RGBA")))
    return icons


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m engine.sheet", description="Render a theme contact sheet."
    )
    parser.add_argument("icons", type=Path, help="folder of .png icons")
    parser.add_argument("--theme", default=DEFAULT_THEME, help="theme folder name")
    parser.add_argument("--themes-dir", type=Path, default=THEMES_DIR)
    parser.add_argument("--seed", type=int, default=0, help="0 = default look, others shuffle")
    parser.add_argument("-o", "--output", type=Path, default=Path("contact_sheet.png"))
    args = parser.parse_args(argv)

    icons = load_icons(args.icons)
    if not icons:
        print(f"no .png icons found in {args.icons}", file=sys.stderr)
        return 1
    theme = load_theme(args.theme, args.themes_dir)
    build_sheet(icons, theme, seed=args.seed).save(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
