from collections.abc import Callable

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image, ImageDraw

from engine import ops

PINK = (255, 158, 196)
CREAM = (255, 247, 240)
INK = (168, 67, 111)
DECORATION = Image.new("RGBA", (40, 30), (*INK, 255))


@st.composite
def icons(draw: st.DrawFn) -> Image.Image:
    """Random icons: a few shapes of random color, alpha and placement."""
    size = draw(st.integers(8, 96))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(img)
    for _ in range(draw(st.integers(1, 4))):
        x0, y0 = draw(st.integers(0, size - 2)), draw(st.integers(0, size - 2))
        x1, y1 = draw(st.integers(x0 + 1, size - 1)), draw(st.integers(y0 + 1, size - 1))
        color = tuple(draw(st.integers(0, 255)) for _ in range(3))
        alpha = draw(st.integers(40, 255))
        shape = canvas.ellipse if draw(st.booleans()) else canvas.rectangle
        shape((x0, y0, x1, y1), fill=(*color, alpha))
    prepared, _ = ops.prepare(img)
    return prepared


def _rgb() -> st.SearchStrategy[tuple[int, int, int]]:
    return st.tuples(st.integers(0, 255), st.integers(0, 255), st.integers(0, 255))


OPS: dict[str, Callable[[Image.Image, st.DataObject], Image.Image]] = {
    "tint": lambda img, d: ops.tint(
        img,
        stops=d.draw(st.lists(_rgb(), min_size=2, max_size=4)),
        strength=d.draw(st.floats(0, 1)),
    ),
    "soft_tint": lambda img, d: ops.soft_tint(
        img, color=d.draw(_rgb()), amount=d.draw(st.floats(0, 1))
    ),
    "mono": lambda img, d: ops.mono(img, color=d.draw(_rgb()), knockout=d.draw(st.booleans())),
    "gradient_fill": lambda img, d: ops.gradient_fill(
        img, stops=[d.draw(_rgb()), d.draw(_rgb())], angle=d.draw(st.floats(-360, 360))
    ),
    "tile": lambda img, d: ops.tile(
        img,
        fill=d.draw(st.lists(_rgb(), min_size=1, max_size=2)),
        shape=d.draw(st.sampled_from(["squircle", "circle", "rounded"])),
        scale=d.draw(st.floats(0.3, 1.0)),
        shadow=d.draw(st.booleans()),
        outline=d.draw(st.none() | _rgb()),
    ),
    "sticker_outline": lambda img, d: ops.sticker_outline(
        img, thickness=d.draw(st.floats(1, 24)), shadow=d.draw(st.booleans())
    ),
    "glow": lambda img, d: ops.glow(
        img, color=d.draw(_rgb()), radius=d.draw(st.floats(1, 24)), strength=d.draw(st.floats(0, 1))
    ),
    "overlay_face": lambda img, d: ops.overlay_face(
        img,
        face=DECORATION,
        scale=d.draw(st.floats(0.1, 0.9)),
        offset_x=d.draw(st.floats(-0.5, 0.5)),
        offset_y=d.draw(st.floats(-0.5, 0.5)),
    ),
    "badge": lambda img, d: ops.badge(
        img,
        asset=DECORATION,
        corner=d.draw(st.sampled_from(["top-left", "top-right", "bottom-left", "bottom-right"])),
        scale=d.draw(st.floats(0.1, 0.6)),
        rotation=d.draw(st.floats(-180, 180)),
    ),
}


def _px(img: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    value = img.getpixel(xy)
    assert isinstance(value, tuple)
    return value


def _alpha(img: Image.Image) -> np.ndarray[tuple[int, int], np.dtype[np.uint8]]:
    return np.asarray(img.getchannel("A"))


@pytest.mark.parametrize("op_name", sorted(OPS))
@settings(max_examples=25, deadline=None)
@given(icon=icons(), data=st.data())
def test_op_properties(op_name: str, icon: Image.Image, data: st.DataObject) -> None:
    out = OPS[op_name](icon, data)
    alpha = _alpha(out)
    assert out.size == icon.size
    assert out.mode == "RGBA"
    assert alpha.max() > 0, "output must never be fully transparent"
    pad = ops.PAD
    border = np.concatenate(
        [alpha[:pad].ravel(), alpha[-pad:].ravel(), alpha[:, :pad].ravel(), alpha[:, -pad:].ravel()]
    )
    assert not border.any(), "ops must leave the padding ring transparent"


def test_prepare_centers_and_fills_canvas() -> None:
    small = Image.new("RGBA", (10, 20), (*PINK, 255))
    canvas, upscaled = ops.prepare(small)
    assert canvas.size == (ops.CANVAS, ops.CANVAS)
    assert upscaled
    left, top, right, bottom = canvas.getbbox() or (0, 0, 0, 0)
    assert bottom - top == round(ops.CANVAS * ops.CONTENT_FILL)
    assert abs((left + right) - ops.CANVAS) <= 1
    assert abs((top + bottom) - ops.CANVAS) <= 1


def test_prepare_large_icon_is_not_flagged_upscaled() -> None:
    _, upscaled = ops.prepare(Image.new("RGBA", (256, 256), (*PINK, 255)))
    assert not upscaled


def test_prepare_rejects_invisible_icon() -> None:
    with pytest.raises(ValueError, match="no visible pixels"):
        ops.prepare(Image.new("RGBA", (32, 32), (255, 0, 0, 0)))


def test_tint_maps_flat_glyph_to_darkest_stop() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (64, 64), (20, 20, 20, 255)))
    out = ops.tint(icon, stops=[INK, PINK, CREAM])
    assert _px(out, (128, 128)) == (*INK, 255)


def test_tint_spreads_light_and_dark_over_stops() -> None:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    ImageDraw.Draw(img).rectangle((32, 0, 63, 63), fill=(255, 255, 255, 255))
    icon, _ = ops.prepare(img)
    out = ops.tint(icon, stops=[INK, CREAM])
    assert _px(out, (60, 128)) == (*INK, 255)
    assert _px(out, (196, 128)) == (*CREAM, 255)


def test_tint_needs_two_stops() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (8, 8), (*PINK, 255)))
    with pytest.raises(ValueError, match="at least two"):
        ops.tint(icon, stops=[PINK])


def test_tint_strength_zero_keeps_original() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (8, 8), (10, 200, 30, 255)))
    assert ops.tint(icon, stops=[INK, CREAM], strength=0).getpixel((128, 128)) == (10, 200, 30, 255)


def test_mono_knocks_out_contrasting_detail() -> None:
    img = Image.new("RGBA", (64, 64), (30, 30, 30, 255))
    ImageDraw.Draw(img).rectangle((24, 24, 40, 40), fill=(255, 255, 255, 255))
    icon, _ = ops.prepare(img)
    knocked = ops.mono(icon, color=PINK)
    solid = ops.mono(icon, color=PINK, knockout=False)
    assert _px(knocked, (128, 128))[3] < 40
    assert _px(knocked, (40, 128))[3] == 255
    assert _px(solid, (128, 128)) == (*PINK, 255)


def test_mono_keeps_flat_glyph_whole() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (64, 64), (30, 30, 30, 255)))
    assert ops.mono(icon, color=PINK).getpixel((128, 128)) == (*PINK, 255)


def test_gradient_fill_runs_between_stops() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (64, 64), (0, 0, 0, 255)))
    out = ops.gradient_fill(icon, stops=[PINK, INK], angle=90)
    assert _px(out, (128, 40))[0] > _px(out, (128, 215))[0]


def test_gradient_fill_needs_two_stops() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (8, 8), (*PINK, 255)))
    with pytest.raises(ValueError, match="exactly two"):
        ops.gradient_fill(icon, stops=[PINK, INK, CREAM])


def test_tile_puts_fill_behind_shrunken_icon() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (64, 64), (0, 0, 0, 255)))
    out = ops.tile(icon, fill=[CREAM], shadow=False)
    assert _px(out, (30, 128)) == (*CREAM, 255)
    assert _px(out, (128, 128)) == (0, 0, 0, 255)


def test_tile_rejects_three_fill_colors() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (8, 8), (*PINK, 255)))
    with pytest.raises(ValueError, match="one or two"):
        ops.tile(icon, fill=[PINK, INK, CREAM])


def test_sticker_outline_grows_border_around_icon() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (64, 64), (0, 0, 0, 255)))
    before = icon.getbbox()
    out = ops.sticker_outline(icon, thickness=10, shadow=False)
    after = out.getbbox()
    assert before is not None
    assert after is not None
    assert after[0] <= before[0] - 8
    assert _px(out, (before[0] - 4, 128)) == (255, 255, 255, 255)


def test_overlay_face_on_invisible_canvas_is_noop() -> None:
    empty = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    assert ops.overlay_face(empty, face=DECORATION).getbbox() is None


def test_badge_lands_in_requested_corner() -> None:
    icon, _ = ops.prepare(Image.new("RGBA", (64, 64), (*CREAM, 255)))
    out = ops.badge(icon, asset=DECORATION, corner="bottom-left", scale=0.3)
    assert _px(out, (12, 240)) == (*INK, 255)
    assert _px(out, (243, 12))[3] == 0


def test_mix_endpoints() -> None:
    assert ops.mix(PINK, INK, 0) == PINK
    assert ops.mix(PINK, INK, 1) == INK


@pytest.mark.parametrize("shape", ["squircle", "circle", "rounded"])
def test_shape_mask_is_filled_in_the_middle_and_empty_at_corners(shape: ops.Shape) -> None:
    mask = ops.shape_mask((64, 64), (4, 4, 60, 60), shape)
    assert mask.getpixel((32, 32)) == 255
    assert mask.getpixel((5, 5)) == 0
