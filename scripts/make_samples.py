"""Draw the sample icons used by tests and the contact sheet.

They're drawn here instead of copied from real apps, so the repo ships no
third-party artwork. Each one covers a case the style engine has to handle.

    uv run python scripts/make_samples.py
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "tests" / "samples"
SIZE = 256


def _canvas(size: int = SIZE) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def simple_glyph() -> Image.Image:
    """A flat single-color music note, like a minimal media app."""
    img, draw = _canvas()
    color = (40, 40, 48, 255)
    draw.ellipse((44, 168, 116, 226), fill=color)
    draw.ellipse((150, 140, 222, 198), fill=color)
    draw.rectangle((100, 48, 116, 196), fill=color)
    draw.rectangle((206, 24, 222, 168), fill=color)
    draw.polygon([(100, 48), (222, 24), (222, 64), (100, 88)], fill=color)
    return img


def multicolor() -> Image.Image:
    """A four-color pinwheel disc, the busy case (think browsers and games)."""
    img, draw = _canvas()
    colors = [(234, 67, 53), (251, 188, 5), (52, 168, 83), (66, 133, 244)]
    for i, color in enumerate(colors):
        draw.pieslice((16, 16, 240, 240), i * 90 - 45, i * 90 + 45, fill=(*color, 255))
    draw.ellipse((78, 78, 178, 178), fill=(255, 255, 255, 255))
    draw.ellipse((92, 92, 164, 164), fill=(66, 133, 244, 255))
    return img


def tiny() -> Image.Image:
    """A 16 px pixel-art folder: only a tiny frame exists, so it must be upscaled."""
    img, draw = _canvas(16)
    draw.rectangle((1, 3, 6, 5), fill=(214, 160, 40, 255))
    draw.rectangle((1, 5, 14, 13), fill=(244, 196, 72, 255))
    draw.line((1, 13, 14, 13), fill=(180, 130, 30, 255))
    return img


def non_square() -> Image.Image:
    """A wide game-controller shape that only fills the middle band."""
    img, draw = _canvas()
    body = (120, 90, 200, 255)
    draw.rounded_rectangle((12, 84, 244, 176), radius=46, fill=body)
    draw.rectangle((52, 116, 92, 128), fill=(255, 255, 255, 255))
    draw.rectangle((66, 102, 78, 142), fill=(255, 255, 255, 255))
    draw.ellipse((170, 100, 190, 120), fill=(255, 214, 90, 255))
    draw.ellipse((194, 124, 214, 144), fill=(110, 220, 170, 255))
    return img


def semi_transparent() -> Image.Image:
    """A glassy rounded square with a fading alpha gradient."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, 232, 232), radius=48, fill=255)
    fade = Image.linear_gradient("L").rotate(90).resize((SIZE, SIZE))
    alpha = fade.point([90 + v * 140 // 255 for v in range(256)])
    glass = Image.new("RGBA", (SIZE, SIZE), (70, 170, 230, 255))
    glass.putalpha(Image.composite(alpha, mask, mask))
    img.alpha_composite(glass)
    ImageDraw.Draw(img).ellipse((88, 88, 168, 168), fill=(255, 255, 255, 230))
    return img


def dark() -> Image.Image:
    """A near-black terminal window with a green prompt."""
    img, draw = _canvas()
    draw.rounded_rectangle((20, 36, 236, 220), radius=22, fill=(24, 26, 32, 255))
    draw.rounded_rectangle((20, 36, 236, 66), radius=22, fill=(52, 56, 66, 255))
    draw.rectangle((20, 52, 236, 66), fill=(52, 56, 66, 255))
    draw.line([(56, 104), (92, 132), (56, 160)], fill=(80, 230, 120, 255), width=14)
    draw.rectangle((108, 152, 168, 164), fill=(80, 230, 120, 255))
    return img


def thin_line() -> Image.Image:
    """A hairline gear outline: thin strokes that vanish if handled carelessly."""
    img, draw = _canvas()
    color = (60, 60, 70, 255)
    cx = cy = SIZE / 2
    points: list[tuple[float, float]] = []
    for i in range(48):
        angle = i * math.tau / 48
        radius = 104 if (i // 3) % 2 == 0 else 84
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, outline=color, width=6)
    draw.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), outline=color, width=6)
    return img


def gradient_app() -> Image.Image:
    """A modern app tile: diagonal orange-to-magenta gradient with a white camera glyph."""
    gradient = Image.linear_gradient("L").rotate(45, expand=False).resize((SIZE, SIZE))
    start, end = (255, 170, 60), (220, 40, 140)
    rgb = Image.merge(
        "RGB",
        [
            gradient.point([a + (b - a) * v // 255 for v in range(256)])
            for a, b in zip(start, end, strict=True)
        ],
    )
    img = rgb.convert("RGBA")
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((16, 16, 240, 240), radius=56, fill=255)
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((60, 60, 196, 196), radius=40, outline=(255, 255, 255, 255), width=14)
    draw.ellipse((98, 98, 158, 158), outline=(255, 255, 255, 255), width=14)
    draw.ellipse((164, 74, 180, 90), fill=(255, 255, 255, 255))
    return img


SAMPLES = {
    "simple_glyph": simple_glyph,
    "multicolor": multicolor,
    "tiny": tiny,
    "non_square": non_square,
    "semi_transparent": semi_transparent,
    "dark": dark,
    "thin_line": thin_line,
    "gradient_app": gradient_app,
}


def main() -> int:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for name, draw in SAMPLES.items():
        path = SAMPLES_DIR / f"{name}.png"
        draw().save(path, optimize=True)
        print(path.relative_to(SAMPLES_DIR.parent.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
