import io
import struct

import numpy as np
import pytest
from PIL import IcoImagePlugin, Image, ImageDraw

from engine import ops
from engine.ico import ICO_SIZES, build_ico
from engine.recipes import render
from engine.themes import Theme
from tests.conftest import load_sample


def _full_and_simple(theme: Theme) -> tuple[Image.Image, Image.Image]:
    icon, _ = ops.prepare(load_sample("multicolor"))
    recipe = theme.recipe("sticker_face")
    return render(recipe, icon, theme), render(recipe, icon, theme, simplified=True)


def _frames(data: bytes) -> dict[int, Image.Image]:
    with Image.open(io.BytesIO(data)) as ico:
        assert isinstance(ico, IcoImagePlugin.IcoImageFile)
        frames: dict[int, Image.Image] = {}
        for width, height in ico.ico.sizes():
            assert width == height
            frames[width] = ico.ico.getimage((width, height)).convert("RGBA")
        return frames


def test_round_trip_contains_every_size(kawaii: Theme) -> None:
    full, simple = _full_and_simple(kawaii)
    frames = _frames(build_ico(full, simple))
    assert sorted(frames) == sorted(ICO_SIZES)
    for size, frame in frames.items():
        assert frame.size == (size, size)


def test_256_frame_is_lossless_png(kawaii: Theme) -> None:
    full, simple = _full_and_simple(kawaii)
    data = build_ico(full, simple)
    assert b"\x89PNG" in data
    assert np.array_equal(np.asarray(_frames(data)[256]), np.asarray(full))


@pytest.mark.parametrize("size", [16, 24])
def test_small_frames_come_from_simplified_render(kawaii: Theme, size: int) -> None:
    full, simple = _full_and_simple(kawaii)
    frame = np.asarray(_frames(build_ico(full, simple))[size], dtype=np.int16)
    expected_simple = np.asarray(simple.resize((size, size), Image.Resampling.LANCZOS), np.int16)
    expected_full = np.asarray(full.resize((size, size), Image.Resampling.LANCZOS), np.int16)
    assert np.abs(frame - expected_simple).max() <= 1
    assert np.abs(frame - expected_full).max() > 1


@pytest.mark.parametrize("size", [32, 48, 128])
def test_larger_frames_come_from_full_render(kawaii: Theme, size: int) -> None:
    full, simple = _full_and_simple(kawaii)
    frame = np.asarray(_frames(build_ico(full, simple))[size], dtype=np.int16)
    expected = np.asarray(full.resize((size, size), Image.Resampling.LANCZOS), np.int16)
    assert np.abs(frame - expected).max() <= 1


def test_directory_entries_point_inside_the_file(kawaii: Theme) -> None:
    full, _ = _full_and_simple(kawaii)
    data = build_ico(full)
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, len(ICO_SIZES))
    for i in range(count):
        width, _, _, _, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i
        )
        assert planes == 1
        assert bits == 32
        assert offset + length <= len(data)
        assert width in {*ICO_SIZES, 0}


def test_and_mask_marks_transparent_pixels() -> None:
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((0, 0, 7, 15), fill=(255, 0, 0, 255))
    data = build_ico(img, sizes=[16])
    _, _, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", data, 6)
    mask = data[offset + 40 + 16 * 16 * 4 : offset + length]
    assert len(mask) == 16 * 4  # 16 rows padded to 32 bits
    assert mask[:4] == bytes([0x00, 0xFF, 0x00, 0x00])


@pytest.mark.parametrize("sizes", [[], [0], [512]])
def test_rejects_bad_sizes(sizes: list[int]) -> None:
    with pytest.raises(ValueError, match="size"):
        build_ico(Image.new("RGBA", (8, 8)), sizes=sizes)
