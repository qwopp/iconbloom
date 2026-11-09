"""Write multi-size Windows .ico files.

Pillow can write .ico, but it scales every frame from one source image. We
need the 16 and 24 px frames to come from a simpler render (no face, no
badges), so this module packs the frames itself.

Frames under 256 px are stored as 32-bit DIBs, which every Windows icon API
reads. The 256 px frame is stored as PNG, which is what Windows expects at
that size and keeps the file small.
"""

import io
import struct
from collections.abc import Sequence

import numpy as np
from PIL import Image

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Frames at or below this size come from the simplified render.
SIMPLIFIED_MAX = 24
_PNG_MIN = 256
_HEADER = struct.Struct("<HHH")
_ENTRY = struct.Struct("<BBBBHHII")
_BITMAPINFOHEADER = struct.Struct("<IiiHHIIiiII")


def build_ico(
    full: Image.Image, simple: Image.Image | None = None, sizes: Sequence[int] = ICO_SIZES
) -> bytes:
    """Pack an icon into .ico bytes, one frame per size, largest last.

    ``full`` and ``simple`` should be square; ``simple`` defaults to ``full``.
    """
    if not sizes:
        raise ValueError("an .ico needs at least one size")
    if any(not 1 <= s <= 256 for s in sizes):
        raise ValueError("icon sizes must be between 1 and 256")
    simple = simple or full
    frames: list[tuple[int, bytes]] = []
    for size in sorted(set(sizes)):
        frame = (
            frame_source(size, full, simple)
            .convert("RGBA")
            .resize((size, size), Image.Resampling.LANCZOS)
        )
        frames.append((size, _encode_png(frame) if size >= _PNG_MIN else _encode_dib(frame)))

    out = bytearray(_HEADER.pack(0, 1, len(frames)))
    offset = _HEADER.size + _ENTRY.size * len(frames)
    for size, data in frames:
        dim = 0 if size == 256 else size  # 0 means 256 in the directory entry
        out += _ENTRY.pack(dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in frames:
        out += data
    return bytes(out)


def frame_source(size: int, full: Image.Image, simple: Image.Image) -> Image.Image:
    """Which render a frame of this size is drawn from."""
    return simple if size <= SIMPLIFIED_MAX else full


def _encode_png(frame: Image.Image) -> bytes:
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _encode_dib(frame: Image.Image) -> bytes:
    width, height = frame.size
    # DIB rows run bottom-up, in BGRA order.
    pixels = frame.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
    mask_stride = ((width + 31) // 32) * 4
    mask = _and_mask(frame, mask_stride)
    header = _BITMAPINFOHEADER.pack(
        _BITMAPINFOHEADER.size,
        width,
        height * 2,  # the height covers the color data plus the AND mask
        1,
        32,
        0,
        len(pixels) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + pixels + mask


def _and_mask(frame: Image.Image, stride: int) -> bytes:
    """1-bit transparency mask: set bits are fully transparent pixels.

    Modern Windows reads the alpha channel; the mask is for old code paths
    that still look at it.
    """
    alpha = np.asarray(frame.getchannel("A"))[::-1]
    bits = np.packbits(alpha == 0, axis=1)  # most significant bit = leftmost pixel
    padded = np.zeros((alpha.shape[0], stride), dtype=np.uint8)
    padded[:, : bits.shape[1]] = bits
    return padded.tobytes()
