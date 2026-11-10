"""The desktop wallpaper as a picture, for the taskbar preview.

Windows names the wallpaper file it shows, and keeps a resized copy of it too. Some
desktops have no file to read: a solid color, a slideshow before its first change, or an
app such as Wallpaper Engine drawing the desktop itself. Then this returns None and the
preview uses the theme's own gradient instead.
"""

import logging
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

# Big enough for a sharp preview; wallpapers are often 4K or larger.
MAX_SIZE = (1920, 1080)
_SPI_GETDESKWALLPAPER = 0x0073


def wallpaper_file(named: str, appdata: Path) -> Path | None:
    """The picture to read: the file Windows names, else its resized copy, else None."""
    transcoded = appdata / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
    for candidate in (Path(named) if named else None, transcoded):
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def load_wallpaper(path: Path | None) -> Image.Image | None:
    """The picture at ``path``, at most MAX_SIZE; None if there is none or it won't open."""
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            image.draft("RGB", MAX_SIZE)  # JPEGs decode at a smaller size straight away
            picture = image.convert("RGBA")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        log.info("can't read the wallpaper %s: %s", path, exc)
        return None
    picture.thumbnail(MAX_SIZE)
    return picture


def current_wallpaper() -> Image.Image | None:
    """The user's wallpaper on Windows, or None (see the module docstring)."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(520)
    if not ctypes.windll.user32.SystemParametersInfoW(_SPI_GETDESKWALLPAPER, 520, buffer, 0):
        buffer.value = ""
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return load_wallpaper(wallpaper_file(buffer.value, appdata))
