"""Render the README images from the real window and engine, using the sample icons.

    QT_QPA_PLATFORM=offscreen uv run python -m scripts.make_screenshots

Writes docs/screenshots/{picker.png, picker.gif, before-after.png}. The
shortcuts are stand-ins in a temp folder, so this never touches a real desktop.
"""

import io
import sys
import tempfile
import time
from pathlib import Path
from typing import override

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

from app.choices import Choice
from app.main import load_style
from app.ui.main_window import MainWindow
from app.ui.widgets import PreviewCard
from app.updates import Release, Updater
from engine import ops
from engine.recipes import render
from engine.themes import DEFAULT_THEME, load_theme
from tests.fakes import SAMPLES_DIR, FakeDesktop

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
APPS = {
    "Arcade": "non_square",
    "Browser": "multicolor",
    "Camera": "gradient_app",
    "Files": "tiny",
    "Music": "simple_glyph",
    "Settings": "thin_line",
    "Terminal": "dark",
    "Weather": "semi_transparent",
}
# One cohesive pick per app, as a person might choose in the picker.
PICKS = {
    "Arcade": "sticker_face",
    "Browser": "tile_bow",
    "Camera": "bubble_cream",
    "Files": "pastel_tint",
    "Music": "gradient_white",
    "Settings": "mono_rose",
    "Terminal": "bubble_pink",
    "Weather": "tint_sparkle",
}


class OfflineUpdater(Updater):
    """Screenshots never touch the network."""

    @override
    def check(self, timeout: float = 5.0) -> Release | None:
        return None


def _sample(app: str) -> Image.Image:
    with Image.open(SAMPLES_DIR / f"{APPS[app]}.png") as img:
        return img.convert("RGBA")


def _grab(app: QApplication, window: MainWindow) -> Image.Image:
    # Let the selection delay fire and every background render land.
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        app.processEvents()
        window.wait_for_jobs()
        time.sleep(0.02)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    window.grab().save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data().data()))).convert("RGB")


def picker_media(app: QApplication) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        desktop = FakeDesktop(Path(tmp), icons=APPS)
        for name in APPS:
            desktop.make(name)
        service = desktop.service()
        for target in service.scan():
            if target.name in ("Camera", "Music"):
                service.apply(target, Choice(DEFAULT_THEME, PICKS[target.name]))
        window = MainWindow(service, hard_refresh=lambda: None, updater=OfflineUpdater())
        window.resize(1180, 760)
        window.show()
        frames = [_grab(app, window)]

        def click(card: int) -> None:
            chosen = window.findChildren(PreviewCard)[card]
            chosen.clicked.emit(chosen)
            frames.append(_grab(app, window))

        click(2)
        click(3)
        window.apply_chosen()
        frames.append(_grab(app, window))
        click(1)
        window.apply_chosen()
        frames.append(_grab(app, window))
        frames[1].save(OUT / "picker.png", optimize=True)
        small = [
            f.resize((900, round(f.height * 900 / f.width)), Image.Resampling.LANCZOS)
            for f in frames
        ]
        palette = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in small]
        palette[0].save(
            OUT / "picker.gif",
            save_all=True,
            append_images=palette[1:],
            duration=[1400, 1000, 1000, 1400, 1000, 1800],
            loop=0,
            optimize=True,
        )
        window.close()


def before_after() -> None:
    theme = load_theme(DEFAULT_THEME)
    size, gap, label_w = 64, 26, 90
    width = label_w + len(APPS) * (size + gap) + gap
    sheet = Image.new("RGB", (width, 2 * (size + 40) + 20), (0, 0, 0))
    wallpaper = ops.linear_gradient(sheet.size, (92, 120, 168), (170, 140, 190), 20)
    sheet.paste(wallpaper)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=15)
    for row, caption in enumerate(("Before", "After")):
        y = 20 + row * (size + 40)
        draw.text((18, y + size // 2), caption, fill=(255, 255, 255), font=font, anchor="lm")
        for col, app in enumerate(APPS):
            icon, _ = ops.prepare(_sample(app))
            if row == 1:
                icon = render(theme.recipe(PICKS[app]), icon, theme)
            x = label_w + gap + col * (size + gap)
            small = icon.resize((size, size), Image.Resampling.LANCZOS)
            sheet.paste(small, (x, y), small)
            draw.text(
                (x + size // 2, y + size + 14), app, fill=(255, 255, 255), font=font, anchor="mm"
            )
    sheet.save(OUT / "before-after.png", optimize=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    load_style(app)
    picker_media(app)
    before_after()
    print("\n".join(str(p.relative_to(ROOT)) for p in sorted(OUT.iterdir())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
