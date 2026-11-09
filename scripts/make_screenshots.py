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
from app.updates import Release, Updater
from engine import ops
from engine.families import Family
from engine.recipes import render
from engine.themes import DEFAULT_THEME, Theme, list_themes, load_theme
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
# One pick per app, as a person might choose in the picker: the nth style of a
# family in the theme's list, so every theme shows its own version of the look.
PICKS: dict[str, tuple[Family, int]] = {
    "Arcade": (Family.RECOLOR, 1),  # the theme's second recolor, on a sticker
    "Browser": (Family.PATTERN, 1),  # gingham tile + badge
    "Camera": (Family.PATTERN, 0),  # polka-dot tile
    "Files": (Family.RECOLOR, 0),
    "Music": (Family.GRADIENT, 0),
    "Settings": (Family.MONO, 0),
    "Terminal": (Family.TILE, 0),  # bubble tile
    "Weather": (Family.GLOW, 0),  # tint + glow + badge
}
# How long the event loop runs after the previews land, so they are shown and laid out.
LAYOUT_SETTLE_S = 0.2
# The picker GIF switches to this theme halfway through.
SECOND_THEME = "lavender_dream"


def pick(theme: Theme, app: str) -> str:
    family, nth = PICKS[app]
    return [r.id for r in theme.recipes if r.family is family][nth]


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
    settled = time.monotonic() + 0.5
    give_up = time.monotonic() + 20
    while True:
        window.jobs.wait()
        app.processEvents()
        if time.monotonic() >= settled and not window.jobs.busy and _previews_ready(window):
            break
        if time.monotonic() > give_up:
            raise TimeoutError("previews never finished rendering")
        time.sleep(0.02)
    # New cards are shown and laid out on later event-loop passes; let those run.
    shown = time.monotonic() + LAYOUT_SETTLE_S
    while time.monotonic() < shown:
        app.processEvents()
        time.sleep(0.02)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    window.grab().save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data().data()))).convert("RGB")


def _previews_ready(window: MainWindow) -> bool:
    return not window.picker.rendering and bool(window.picker.cards)


def picker_media(app: QApplication) -> None:
    """picker.png, and picker.gif: pick, apply, switch theme, pick again, go dark."""
    kawaii = load_theme(DEFAULT_THEME)
    with tempfile.TemporaryDirectory() as tmp:
        desktop = FakeDesktop(Path(tmp), icons=APPS)
        for name in APPS:
            desktop.make(name)
        service = desktop.service()
        for target in service.scan():
            if target.name in ("Camera", "Music"):
                service.apply(target, Choice(DEFAULT_THEME, pick(kawaii, target.name)))
        window = MainWindow(service, hard_refresh=lambda: None, updater=OfflineUpdater())
        window.set_dark_mode(False, save=False)
        window.resize(1180, 760)
        window.show()
        frames = [_grab(app, window)]

        def click(card: int) -> None:
            chosen = window.picker.cards[card]
            chosen.clicked.emit(chosen)
            frames.append(_grab(app, window))

        click(2)
        click(3)
        window.apply_chosen()
        frames.append(_grab(app, window))
        window.theme_box.setCurrentIndex(window.theme_box.findData(SECOND_THEME))
        frames.append(_grab(app, window))
        click(1)
        window.apply_chosen()
        frames.append(_grab(app, window))
        window.set_dark_mode(True, save=False)
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
            duration=[1400, 1000, 1000, 1400, 1400, 1000, 1400, 2200],
            loop=0,
            optimize=True,
        )
        window.set_dark_mode(False, save=False)
        window.close()


def before_after() -> None:
    """The sample icons as they come, then in every bundled theme."""
    themes = [load_theme(t) for t in list_themes()]
    themes.sort(key=lambda t: t.id != DEFAULT_THEME)
    size, gap, label_w, row_h = 64, 26, 150, 104
    width = label_w + len(APPS) * (size + gap) + gap
    sheet = Image.new("RGB", (width, (1 + len(themes)) * row_h + 20), (0, 0, 0))
    wallpaper = ops.linear_gradient(sheet.size, (92, 120, 168), (170, 140, 190), 20)
    sheet.paste(wallpaper)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=15)
    rows: list[tuple[str, Theme | None]] = [("Before", None), *((t.name, t) for t in themes)]
    for row, (caption, theme) in enumerate(rows):
        y = 20 + row * row_h
        draw.text((18, y + size // 2), caption, fill=(255, 255, 255), font=font, anchor="lm")
        for col, app in enumerate(APPS):
            icon, _ = ops.prepare(_sample(app))
            if theme is not None:
                icon = render(theme.recipe(pick(theme, app)), icon, theme)
            x = label_w + gap + col * (size + gap)
            small = icon.resize((size, size), Image.Resampling.LANCZOS)
            sheet.paste(small, (x, y), small)
            if row == 0:
                draw.text(
                    (x + size // 2, y + size + 14),
                    app,
                    fill=(255, 255, 255),
                    font=font,
                    anchor="mm",
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
