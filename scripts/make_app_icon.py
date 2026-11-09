"""Build Iconbloom's own icon from installer/iconbloom.svg.

    uv run python -m scripts.make_app_icon

Writes installer/iconbloom.ico (exe and installer icon) and
app/ui/iconbloom.png (window icon).
"""

import sys
from pathlib import Path

from engine.ico import write_ico
from scripts.render_assets import render_svg

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    image = render_svg(ROOT / "installer" / "iconbloom.svg", width=256)
    write_ico(ROOT / "installer" / "iconbloom.ico", image)
    image.save(ROOT / "app" / "ui" / "iconbloom.png", optimize=True)
    print("installer/iconbloom.ico, app/ui/iconbloom.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
