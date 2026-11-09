"""Get the original, full-resolution icon behind a shortcut.

Order of preference:
1. The shortcut's own icon location (an .ico, or an .exe/.dll plus index).
2. The target program's first icon.
3. Whatever Explorer shows for the shortcut, via the shell's image factory.
   This is the only route for Store apps and installer-advertised shortcuts,
   which have no .exe to read.

Reading icon resources straight from the file (via icoextract) gets the real
256 px frame, where the classic ExtractIconEx API tops out at 48 px.
"""

import io
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import IcoImagePlugin, Image, UnidentifiedImageError

from platform_win.shortcuts import IconLocation

log = logging.getLogger(__name__)
# icoextract warns about every .mun redirect; we handle those ourselves.
logging.getLogger("icoextract").setLevel(logging.ERROR)

# Below this, the source is too small to style well; the UI warns that the
# result may look soft.
SHARP_MIN = 128
_PE_SUFFIXES = frozenset({".exe", ".dll", ".cpl", ".ocx", ".scr", ".mun", ".icl", ".sys"})
_IMAGE_SUFFIXES = frozenset({".png", ".bmp"})


class ExtractionError(Exception):
    """No route produced an icon. The message lists what was tried."""


@dataclass(frozen=True)
class ExtractedIcon:
    image: Image.Image
    # True when the best frame found was small, so styled results may look soft.
    upscaled: bool
    source: str


def extract_icon(
    icon: IconLocation, target: str, shortcut: Path, *, use_shell: bool = True
) -> ExtractedIcon:
    """Best available original icon for a shortcut.

    ``use_shell`` must be False while the shortcut shows a themed icon, since
    the shell would then hand back our own icon instead of the original.
    """
    attempts: list[tuple[str, Callable[[], ExtractedIcon | None]]] = []
    if icon.path:
        location = Path(os.path.expandvars(icon.path))
        attempts.append((f"{location},{icon.index}", lambda: _from_file(location, icon.index)))
        moved = _mun_location(location)
        if moved is not None:
            attempts.append((f"{moved},{icon.index}", lambda: _from_file(moved, icon.index)))
        if use_shell:
            # The shortcut names a specific icon; the shell resolves it more
            # faithfully than falling back to the target program's icon.
            attempts.append(("shell", lambda: _from_shell(shortcut)))
    if target:
        program = Path(os.path.expandvars(target))
        attempts.append((f"{program},0", lambda: _from_file(program, 0)))
    if use_shell and not icon.path:
        attempts.append(("shell", lambda: _from_shell(shortcut)))

    tried: list[str] = []
    for label, attempt in attempts:
        try:
            result = attempt()
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            tried.append(f"{label}: {exc}")
            log.debug("icon read failed for %s: %s", label, exc)
            continue
        if result is not None:
            return result
        tried.append(f"{label}: not an icon source")
    raise ExtractionError("; ".join(tried) or "the shortcut names no icon and no target")


def _from_file(path: Path, index: int) -> ExtractedIcon | None:
    image = read_icon_file(path, index)
    if image is None:
        return None
    return ExtractedIcon(image, max(image.size) < SHARP_MIN, f"{path},{index}")


def _from_shell(shortcut: Path) -> ExtractedIcon:
    return ExtractedIcon(shell_image(shortcut), upscaled=False, source="shell")


def _mun_location(path: Path) -> Path | None:
    r"""Since Windows 10 1903, many system DLLs keep their icons in SystemResources\*.mun."""
    windir = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    if path.parent.parent.name.casefold() != windir.name.casefold():
        return None
    return windir / "SystemResources" / f"{path.name}.mun"


def read_icon_file(path: Path, index: int = 0) -> Image.Image | None:
    """Largest frame of an icon stored in an .ico, image or PE file; None for other files."""
    suffix = path.suffix.casefold()
    if suffix == ".ico":
        return largest_frame(path.read_bytes())
    if suffix in _IMAGE_SUFFIXES:
        with Image.open(path) as img:
            return img.convert("RGBA")
    if suffix in _PE_SUFFIXES:
        return largest_frame(_pe_icon(path, index))
    return None


def largest_frame(ico_data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(ico_data)) as img:
        if not isinstance(img, IcoImagePlugin.IcoImageFile):
            raise ValueError("not an .ico file")
        biggest = max(img.ico.sizes(), key=lambda s: s[0] * s[1])
        return img.ico.getimage(biggest).convert("RGBA")


def _pe_icon(path: Path, index: int) -> bytes:
    from icoextract import IconExtractor, IconExtractorError

    try:
        extractor = IconExtractor(str(path))
        # Windows icon indexes: zero or more is a position, negative is a resource id.
        if index < 0:
            data = extractor.get_icon(resource_id=-index)
        else:
            data = extractor.get_icon(num=index)
    except IconExtractorError as exc:
        raise ValueError(str(exc)) from exc
    return data.getvalue()


def shell_image(path: Path, size: int = 256) -> Image.Image:
    """The icon Explorer draws for ``path``, via IShellItemImageFactory."""
    if sys.platform != "win32":
        raise OSError("shell icons are only available on Windows")
    import ctypes
    from ctypes import wintypes

    import pythoncom

    pythoncom.CoInitialize()
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32

    class Size(ctypes.Structure):
        _fields_ = (("cx", wintypes.LONG), ("cy", wintypes.LONG))

    iid = (ctypes.c_byte * 16)()
    ole32.CLSIDFromString(ctypes.c_wchar_p(_IID_IMAGE_FACTORY), ctypes.byref(iid))
    factory = ctypes.c_void_p()
    shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
    shell32.SHCreateItemFromParsingName(
        ctypes.c_wchar_p(str(path)), None, ctypes.byref(iid), ctypes.byref(factory)
    )
    vtable = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    get_image = ctypes.WINFUNCTYPE(
        ctypes.HRESULT, ctypes.c_void_p, Size, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP)
    )(vtable[3])
    bitmap = wintypes.HBITMAP()
    try:
        get_image(factory, Size(size, size), _SIIGBF_ICONONLY, ctypes.byref(bitmap))
    finally:
        release(factory)
    try:
        return _bitmap_to_image(bitmap)
    finally:
        ctypes.windll.gdi32.DeleteObject(bitmap)


_IID_IMAGE_FACTORY = "{bcc18b79-ba16-442f-80c4-8a59c30c463b}"
_SIIGBF_ICONONLY = 0x4


def _bitmap_to_image(bitmap: object) -> Image.Image:
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    class Bitmap(ctypes.Structure):
        _fields_ = (
            ("bmType", wintypes.LONG),
            ("bmWidth", wintypes.LONG),
            ("bmHeight", wintypes.LONG),
            ("bmWidthBytes", wintypes.LONG),
            ("bmPlanes", wintypes.WORD),
            ("bmBitsPixel", wintypes.WORD),
            ("bmBits", ctypes.c_void_p),
        )

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = (
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        )

    info = Bitmap()
    gdi32.GetObjectW(bitmap, ctypes.sizeof(info), ctypes.byref(info))
    width, height = info.bmWidth, abs(info.bmHeight)
    header = BitmapInfoHeader()
    header.biSize = ctypes.sizeof(header)
    header.biWidth = width
    header.biHeight = -height  # negative = rows top-down
    header.biPlanes = 1
    header.biBitCount = 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    dc = user32.GetDC(None)
    try:
        rows = gdi32.GetDIBits(dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    finally:
        user32.ReleaseDC(None, dc)
    if rows != height:
        raise OSError("could not read the icon bitmap")
    image = Image.frombuffer("RGBA", (width, height), buffer.raw, "raw", "BGRA", 0, 1)
    return unpremultiply(image)


def unpremultiply(image: Image.Image) -> Image.Image:
    """Undo premultiplied alpha, which the shell uses for its bitmaps.

    A bitmap with no alpha at all is treated as opaque, and one whose colors
    exceed their alpha is already straight alpha and is returned as is.
    """
    arr = np.asarray(image.convert("RGBA"), dtype=np.float64)
    alpha = arr[..., 3:4]
    if not alpha.any():
        arr[..., 3] = 255
    elif (arr[..., :3] <= alpha + 0.5).all():
        arr[..., :3] = np.where(alpha > 0, arr[..., :3] * 255 / np.maximum(alpha, 1), 0)
    return Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), "RGBA")
