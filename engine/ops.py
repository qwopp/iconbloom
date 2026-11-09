"""Image operations that recipes are built from.

Every op is a pure function that takes an RGBA image plus keyword parameters
and returns a new RGBA image of the same size. Ops never read files or pick
random values; the recipe runner resolves palette names, assets and shuffle
choices before calling them, so the same inputs always give the same pixels.
"""

import functools
import math
from collections.abc import Sequence
from typing import Literal, get_args

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageChops, ImageDraw, ImageFilter

type RGB = tuple[int, int, int]
type FloatArray = npt.NDArray[np.float64]
type Shape = Literal["squircle", "circle", "rounded"]
type Pattern = Literal["dots", "stripes", "gingham", "hearts"]
PATTERNS: tuple[Pattern, ...] = get_args(Pattern.__value__)
type Corner = Literal["top-left", "top-right", "bottom-left", "bottom-right"]

CANVAS = 256
# Transparent border every op leaves untouched, so outlines and shadows never clip.
PAD = 2
# Share of the canvas the prepared icon fills. The rest is headroom for
# outlines, glows and shadows added by later ops.
CONTENT_FILL = 0.78
# Supersampling factor for drawn shapes, which Pillow does not anti-alias.
_SUPERSAMPLE = 4
_ALPHA_VISIBLE = 8
# Two tones must differ this much in luminance before mono cuts one out.
_KNOCKOUT_CONTRAST = 0.25
_KNOCKOUT_SOFTNESS = 0.08
# duotone measures colors this many pixels inside the icon's outline.
_TONE_EDGE = 2
# recolor treats chroma below this as gray, and at this much above it as fully colored.
_NEUTRAL_CHROMA = 0.05
_FULL_CHROMA = 0.25
_RECOLOR_SATURATION = 1.35
_RECOLOR_LIFT = 0.4
# remove_background: a plain plate behind a logo (a colored square or circle) is found
# from a ring just inside the icon's outline, which must be mostly one color.
_PLATE_RING = 4
# Too few solid pixels to tell a plate from noise, and the faintest alpha still counted.
_PLATE_MIN_PIXELS = 64
_PLATE_VISIBLE = 0.02
_PLATE_SHARE = 0.85
# Color distance (RGB, 0..1 per channel) still counted as the plate.
_PLATE_TOLERANCE = 0.12
# Width of the logo's anti-aliased edge that gets the plate color taken back out.
_PLATE_EDGE = 3
# The plate's own anti-aliased rim drifts further in color (resampling rings), so the
# few pixels next to the outside match more loosely.
_PLATE_RIM = 3
_PLATE_RIM_TOLERANCE = 0.3
# A real logo leaves this share of the icon behind; anything else means the "plate"
# was the logo itself (a solid glyph's edge is one color too), so nothing is cut.
_LOGO_MIN_SHARE = 0.03
_LOGO_MAX_SHARE = 0.7


def prepare(icon: Image.Image, size: int = CANVAS) -> tuple[Image.Image, bool]:
    """Center an icon of any size on a square transparent canvas, ready for ops.

    Returns the canvas and whether the icon had to be enlarged a lot, in which
    case results may look soft.
    """
    rgba = icon.convert("RGBA")
    bbox = _visible_bbox(rgba)
    if bbox is None:
        raise ValueError("icon has no visible pixels")
    content = rgba.crop(bbox)
    target = round(size * CONTENT_FILL)
    scale = target / max(content.size)
    upscaled = max(content.size) * 2 <= target
    new_size = (max(1, round(content.width * scale)), max(1, round(content.height * scale)))
    if scale >= 3:
        # Pixel-art sized icons: grow with hard edges first, then smooth the
        # final step, which keeps them crisp instead of a blurry blob.
        whole = int(scale)
        content = content.resize(
            (content.width * whole, content.height * whole), Image.Resampling.NEAREST
        )
    content = content.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(content, ((size - new_size[0]) // 2, (size - new_size[1]) // 2))
    return canvas, upscaled


def tint(img: Image.Image, *, stops: Sequence[RGB], strength: float = 1.0) -> Image.Image:
    """Gradient-map the icon's luminance onto palette stops, darkest stop first."""
    if len(stops) < 2:
        raise ValueError("tint needs at least two color stops")
    arr = _to_array(img)
    lum = _luminance(arr)
    opaque = arr[..., 3] > _ALPHA_VISIBLE / 255
    t = _normalized(lum, opaque)
    mapped = _gradient_map(t, stops)
    arr[..., :3] = arr[..., :3] * (1 - strength) + mapped * strength
    return _finish(_from_array(arr))


def soft_tint(img: Image.Image, *, color: RGB, amount: float = 0.45) -> Image.Image:
    """Pull the icon toward one color while keeping a hint of its own hues."""
    stops = [mix(color, (40, 20, 30), 0.55), color, mix(color, (255, 255, 255), 0.75)]
    return tint(img, stops=stops, strength=amount)


def recolor(img: Image.Image, *, stops: Sequence[RGB], strength: float = 1.0) -> Image.Image:
    """Repaint each of the icon's hues with a palette shade.

    The icon's hues are laid out in order around the color wheel, starting
    after its widest unused stretch, and spread across ``stops``. Nearby hues
    get nearby shades, so a smooth gradient stays smooth, while separate color
    blocks get clearly different shades. Grays, whites and blacks keep their
    brightness and stay neutral.
    """
    if len(stops) < 2:
        raise ValueError("recolor needs at least two color stops")
    arr = _to_array(img)
    hue, sat, val = _rgb_to_hsv(arr[..., :3])
    # Chroma, unlike saturation, is near zero for near-black pixels, so dark
    # parts count as neutral instead of turning into a muddy brown.
    chroma = sat * val * (arr[..., 3] > _ALPHA_VISIBLE / 255)
    target_h, target_s, target_v = _rgb_to_hsv(_gradient_map(_hue_positions(hue, chroma), stops))
    color = np.clip((chroma - _NEUTRAL_CHROMA) / _FULL_CHROMA, 0.0, 1.0)
    # Pastel stops are pale; a little extra saturation keeps colored parts from washing out.
    out_s = np.clip(target_s * _RECOLOR_SATURATION, 0.0, 1.0) * color
    # Keep most of the icon's own light and shade so shapes stay readable.
    out_v = val * (1.0 - _RECOLOR_LIFT * color) + target_v * _RECOLOR_LIFT * color
    painted = _hsv_to_rgb(target_h, out_s, out_v)
    arr[..., :3] = arr[..., :3] * (1 - strength) + painted * strength
    return _finish(_from_array(arr))


def mono(img: Image.Image, *, color: RGB, knockout: bool = True) -> Image.Image:
    """Flatten the icon to one color.

    With ``knockout``, inner details that contrast with the body (a glyph on a
    tile, a prompt in a terminal) become see-through instead of vanishing into
    a solid blob.
    """
    arr = _to_array(img)
    if knockout:
        arr[..., 3] = _knockout_alpha(arr)
    arr[..., :3] = np.asarray(color, dtype=np.float64) / 255
    return _finish(_from_array(arr))


def gradient_fill(
    img: Image.Image, *, stops: Sequence[RGB], angle: float = 90.0, knockout: bool = True
) -> Image.Image:
    """Like mono, but filled with a two-color linear gradient."""
    if len(stops) != 2:
        raise ValueError("gradient_fill needs exactly two color stops")
    arr = _to_array(img)
    alpha = _knockout_alpha(arr) if knockout else arr[..., 3]
    gradient = np.asarray(linear_gradient(img.size, stops[0], stops[1], angle), dtype=np.float64)
    out = np.dstack([gradient / 255, alpha])
    return _finish(_from_array(out))


def duotone(img: Image.Image, *, body: RGB | None = None, detail: RGB | None = None) -> Image.Image:
    """Paint the icon's main tone and its contrasting details two flat colors.

    A color left out takes the other part's own color, so with neither given the
    two trade places: a white cat with pink whiskers becomes a pink cat with white
    whiskers. One-tone icons get ``body`` all over, or stay as they are.
    """
    arr = _to_array(img)
    split = _split_tones(arr, by_color=True)
    if split is None:
        if body is not None:
            arr[..., :3] = np.asarray(body, dtype=np.float64) / 255
        return _finish(_from_array(arr))
    ramp, own_body, own_detail = split
    body_rgb = own_detail if body is None else np.asarray(body, dtype=np.float64) / 255
    detail_rgb = own_body if detail is None else np.asarray(detail, dtype=np.float64) / 255
    arr[..., :3] = body_rgb * (1.0 - ramp[..., None]) + detail_rgb * ramp[..., None]
    return _finish(_from_array(arr))


def tile(
    img: Image.Image,
    *,
    fill: Sequence[RGB],
    shape: Shape = "squircle",
    angle: float = 90.0,
    scale: float = 0.7,
    shadow: bool = True,
    outline: RGB | None = None,
    pattern: Pattern | None = None,
    pattern_color: RGB = (255, 255, 255),
) -> Image.Image:
    """Shrink the icon and center it on a filled shape.

    ``fill`` is one color for a solid tile or two for a linear gradient.
    ``pattern`` adds polka dots, stripes, gingham or little hearts over the fill.
    """
    if not 1 <= len(fill) <= 2:
        raise ValueError("tile fill needs one or two colors")
    width, height = img.size
    margin = round(width * 0.055)
    shadow_drop = round(width * 0.02) if shadow else 0
    box = (margin, margin - shadow_drop // 2, width - margin, height - margin - shadow_drop)
    mask = shape_mask(img.size, box, shape)

    if len(fill) == 1:
        surface = Image.new("RGBA", img.size, (*fill[0], 255))
    else:
        surface = linear_gradient(img.size, fill[0], fill[1], angle).convert("RGBA")
    if pattern is not None:
        surface.alpha_composite(_solid(img.size, pattern_color, pattern_mask(img.size, pattern)))
    surface.putalpha(mask)

    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    if shadow:
        out.alpha_composite(_shadow(mask, mix(fill[-1], (60, 20, 40), 0.6), shadow_drop, 0.35))
    out.alpha_composite(surface)
    if outline is not None:
        ring = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(5)))
        out.alpha_composite(_solid(img.size, outline, ring))

    inner = (box[2] - box[0], box[3] - box[1])
    icon = _fit_content(img, (round(inner[0] * scale), round(inner[1] * scale)))
    out.alpha_composite(
        icon,
        (box[0] + (inner[0] - icon.width) // 2, box[1] + (inner[1] - icon.height) // 2),
    )
    return _finish(out)


def sticker_outline(
    img: Image.Image,
    *,
    thickness: float = 10.0,
    color: RGB = (255, 255, 255),
    shadow: bool = True,
) -> Image.Image:
    """Put a die-cut sticker border behind the icon."""
    border = dilate(img.getchannel("A"), thickness)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    if shadow:
        out.alpha_composite(_shadow(border, (120, 60, 90), round(img.width * 0.015), 0.3))
    out.alpha_composite(_solid(img.size, color, border))
    out.alpha_composite(img)
    return _finish(out)


def glow(
    img: Image.Image, *, color: RGB, radius: float = 10.0, strength: float = 0.8
) -> Image.Image:
    """Soft colored halo around the icon."""
    halo = img.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    halo = halo.point(_scale_lut(2 * strength))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(_solid(img.size, color, halo))
    out.alpha_composite(img)
    return _finish(out)


def overlay_face(
    img: Image.Image,
    *,
    face: Image.Image,
    scale: float = 0.42,
    offset_x: float = 0.0,
    offset_y: float = 0.16,
) -> Image.Image:
    """Put a tiny face on the lower middle of the icon's visible area.

    Scale and offsets are fractions of the icon's visible width and height, so
    the face lands in the same spot on a wide icon and a narrow one.
    """
    bbox = _visible_bbox(img)
    if bbox is None:
        return _finish(img.copy())
    left, top, right, bottom = bbox
    content_w, content_h = right - left, bottom - top
    face = _trim(face)
    face_w = max(1, round(content_w * scale))
    face = face.resize(
        (face_w, max(1, round(face.height * face_w / face.width))), Image.Resampling.LANCZOS
    )
    cx = left + content_w / 2 + offset_x * content_w
    cy = top + content_h / 2 + offset_y * content_h
    out = img.copy()
    out.alpha_composite(face, _clamped_origin(img.size, face.size, cx, cy))
    return _finish(out)


def badge(
    img: Image.Image,
    *,
    asset: Image.Image,
    corner: Corner = "top-right",
    scale: float = 0.35,
    rotation: float = 0.0,
) -> Image.Image:
    """Stick a decoration on one corner of the canvas."""
    deco = _trim(asset)
    if rotation:
        deco = _trim(deco.rotate(rotation, Image.Resampling.BICUBIC, expand=True))
    deco = _fit_content(deco, (round(img.width * scale), round(img.height * scale)))
    inset = PAD + round(img.width * 0.02)
    x = inset if corner.endswith("left") else img.width - inset - deco.width
    y = inset if corner.startswith("top") else img.height - inset - deco.height
    out = img.copy()
    out.alpha_composite(deco, (x, y))
    return _finish(out)


def remove_background(img: Image.Image) -> Image.Image:
    """Cut away a plain plate behind a logo, keeping the logo, re-centered and enlarged.

    Icons without such a plate come back unchanged; ``has_plate`` says which is which.
    """
    found = _find_plate(img)
    if found is None:
        return img.copy()
    plate_color, plate = found
    arr = _to_array(img)
    alpha = arr[..., 3]
    alpha[plate] = 0
    # The logo's anti-aliased edge mixes logo and plate colors. Compare each edge pixel
    # with the plate color and the nearest pure logo color to tell how much of it is
    # logo, then keep only that part (no colored fringe).
    near_plate = _grow(plate, _PLATE_EDGE)
    edge = near_plate & ~plate & (alpha > 0)
    logo = _nearest_color(arr[..., :3], (alpha > 0) & ~near_plate, _PLATE_EDGE)
    rgb = arr[..., :3][edge]
    toward_logo = logo[edge] - plate_color
    reach = np.maximum((toward_logo**2).sum(axis=-1), 1e-6)
    share = np.clip(((rgb - plate_color) * toward_logo).sum(axis=-1) / reach, 0.0, 1.0)
    alpha[edge] *= share
    keep = np.maximum(share, 1e-3)[:, None]
    arr[..., :3][edge] = np.clip((rgb - (1 - keep) * plate_color) / keep, 0.0, 1.0)
    cut = _from_array(arr)
    if _visible_bbox(cut) is None:
        return img.copy()
    return _finish(prepare(cut, img.width)[0])


def has_plate(img: Image.Image) -> bool:
    """True when the icon is a logo on a plain plate that ``remove_background`` can cut."""
    return _find_plate(img) is not None


def mix(a: RGB, b: RGB, amount: float) -> RGB:
    """Blend color ``a`` toward ``b``; amount 0 keeps ``a``, 1 gives ``b``."""
    r, g, bl = (round(x + (y - x) * amount) for x, y in zip(a, b, strict=True))
    return (r, g, bl)


def linear_gradient(size: tuple[int, int], start: RGB, end: RGB, angle: float) -> Image.Image:
    """RGB image fading from ``start`` to ``end``; angle 90 runs top to bottom."""
    width, height = size
    rad = math.radians(angle)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    proj = xs * math.cos(rad) + ys * math.sin(rad)
    t = (proj - proj.min()) / max(float(proj.max() - proj.min()), 1e-6)
    a = np.asarray(start, dtype=np.float64)
    b = np.asarray(end, dtype=np.float64)
    rgb = a + (b - a) * t[..., None]
    return Image.fromarray(np.clip(rgb + 0.5, 0, 255).astype(np.uint8), "RGB")


def shape_mask(size: tuple[int, int], box: tuple[int, int, int, int], shape: Shape) -> Image.Image:
    """Anti-aliased L-mode mask of a squircle, circle or rounded square."""
    # Every tile recipe asks for the same few masks; drawing one costs ~5 ms.
    return _cached_shape_mask(size, box, shape).copy()


@functools.lru_cache(maxsize=16)
def _cached_shape_mask(
    size: tuple[int, int], box: tuple[int, int, int, int], shape: Shape
) -> Image.Image:
    s = _SUPERSAMPLE
    big = Image.new("L", (size[0] * s, size[1] * s), 0)
    draw = ImageDraw.Draw(big)
    left, top, right, bottom = (v * s for v in box)
    if shape == "circle":
        draw.ellipse((left, top, right, bottom), fill=255)
    elif shape == "rounded":
        draw.rounded_rectangle(
            (left, top, right, bottom), radius=round((right - left) * 0.22), fill=255
        )
    else:
        draw.polygon(_squircle_points(left, top, right, bottom), fill=255)
    return big.resize(size, Image.Resampling.LANCZOS)


def pattern_mask(size: tuple[int, int], pattern: Pattern) -> Image.Image:
    """L-mode mask of a repeating pattern covering the whole canvas."""
    return _cached_pattern_mask(size, pattern).copy()


# How strongly a pattern shows over its tile; gingham overlaps itself, so it starts lighter.
_PATTERN_STRENGTH = {"dots": 0.75, "stripes": 0.45, "gingham": 0.32, "hearts": 0.75}


@functools.lru_cache(maxsize=16)
def _cached_pattern_mask(size: tuple[int, int], pattern: Pattern) -> Image.Image:
    s = _SUPERSAMPLE
    width, height = size[0] * s, size[1] * s
    step = round(width * (0.17 if pattern == "hearts" else 0.125))
    big = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(big)
    if pattern == "stripes":
        band = step // 2
        for offset in range(-height, width, step):
            draw.polygon(
                [
                    (offset, 0),
                    (offset + band, 0),
                    (offset + band + height, height),
                    (offset + height, height),
                ],
                fill=255,
            )
    elif pattern == "gingham":
        band = step // 2
        layer = Image.new("L", (width, height), 0)
        layer_draw = ImageDraw.Draw(layer)
        for offset in range(0, width, step):
            draw.rectangle((offset, 0, offset + band, height), fill=128)
            layer_draw.rectangle((0, offset, width, offset + band), fill=128)
        big = ImageChops.add(big, layer)
    else:
        radius = step * (0.2 if pattern == "dots" else 0.28)
        for row, y in enumerate(range(step // 2, height + step, step)):
            shift = step // 2 if row % 2 else 0
            for x in range(step // 2 - shift, width + step, step):
                if pattern == "dots":
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
                else:
                    _draw_heart(draw, x, y, radius)
    strength = _PATTERN_STRENGTH[pattern]
    small = big.resize(size, Image.Resampling.LANCZOS)
    return small.point(_scale_lut(strength))


def _draw_heart(draw: ImageDraw.ImageDraw, x: float, y: float, r: float) -> None:
    """A small heart centered on (x, y), about 2r wide."""
    lobe = r * 0.55
    draw.ellipse((x - r, y - r * 0.75, x - r + 2 * lobe, y - r * 0.75 + 2 * lobe), fill=255)
    draw.ellipse((x + r - 2 * lobe, y - r * 0.75, x + r, y - r * 0.75 + 2 * lobe), fill=255)
    draw.polygon([(x - r * 0.98, y - r * 0.1), (x + r * 0.98, y - r * 0.1), (x, y + r)], fill=255)


def dilate(alpha: Image.Image, radius: float) -> Image.Image:
    """Grow a mask outward by about ``radius`` px with round, anti-aliased corners."""
    solid = alpha.point(_threshold_lut(_ALPHA_VISIBLE * 4))
    # A blurred step edge falls to ~2.3% of full value two sigmas out, so a low
    # threshold on a blur of sigma radius/2 lands the new edge about radius px out.
    spread = np.asarray(solid.filter(ImageFilter.GaussianBlur(radius / 2)), dtype=np.float64)
    grown = np.clip((spread - 3.0) / 6.0, 0.0, 1.0)
    return Image.fromarray((grown * 255 + 0.5).astype(np.uint8), "L")


def _find_plate(img: Image.Image) -> tuple[FloatArray, npt.NDArray[np.bool_]] | None:
    """The plate's color and which pixels are plate; None when there's no plain plate."""
    arr = _to_array(img)
    alpha = arr[..., 3]
    opaque = alpha > 0.5
    if opaque.sum() < _PLATE_MIN_PIXELS:
        return None
    ring = opaque & ~_shrink(opaque, _PLATE_RING)
    plate_color = np.median(arr[..., :3][ring], axis=0)
    distance = np.linalg.norm(arr[..., :3] - plate_color, axis=-1)
    if (distance[ring] < _PLATE_TOLERANCE).mean() < _PLATE_SHARE:
        return None
    visible = alpha > _PLATE_VISIBLE
    rim = visible & ~_shrink(visible, _PLATE_RIM)
    similar = visible & ((distance < _PLATE_TOLERANCE) | (rim & (distance < _PLATE_RIM_TOLERANCE)))
    plate = ring & similar
    while True:  # flood from the ring through connected plate-colored pixels
        grown = _grow(plate, 1) & similar
        if np.array_equal(grown, plate):
            break
        plate = grown
    logo_share = (opaque & ~plate).sum() / opaque.sum()
    if not _LOGO_MIN_SHARE <= logo_share <= _LOGO_MAX_SHARE:
        return None
    return plate_color, plate


def _nearest_color(rgb: FloatArray, known: npt.NDArray[np.bool_], steps: int) -> FloatArray:
    """Each pixel's color, filled in from the nearest ``known`` pixel up to ``steps`` away."""
    filled = np.where(known[..., None], rgb, np.nan)
    for _ in range(steps):
        missing = np.isnan(filled[..., 0])
        if not missing.any():
            break
        step = filled.copy()
        for neighbor, target in _neighbor_pairs(filled, step):
            take = np.isnan(target[..., 0]) & ~np.isnan(neighbor[..., 0])
            target[take] = neighbor[take]
        filled = step
    return np.where(np.isnan(filled), rgb, filled)


def _grow(mask: npt.NDArray[np.bool_], steps: int) -> npt.NDArray[np.bool_]:
    """The mask plus every pixel within ``steps`` 4-connected steps of it."""
    grown = mask.copy()
    for _ in range(steps):
        step = grown.copy()
        for neighbor, target in _neighbor_pairs(grown, step):
            target |= neighbor
        grown = step
    return grown


def _neighbor_pairs[T: np.generic](
    source: npt.NDArray[T], target: npt.NDArray[T]
) -> tuple[tuple[npt.NDArray[T], npt.NDArray[T]], ...]:
    """(neighbor, pixel) views of two same-shaped arrays, for each of the 4 directions:
    writing to the pixel view updates each pixel from its neighbor in ``source``."""
    return (
        (source[:-1], target[1:]),
        (source[1:], target[:-1]),
        (source[:, :-1], target[:, 1:]),
        (source[:, 1:], target[:, :-1]),
    )


def _shrink(mask: npt.NDArray[np.bool_], steps: int) -> npt.NDArray[np.bool_]:
    """The mask minus every pixel within ``steps`` of its outside."""
    return ~_grow(~mask, steps)


def _squircle_points(
    left: float, top: float, right: float, bottom: float, exponent: float = 4.5
) -> list[tuple[float, float]]:
    cx, cy = (left + right) / 2, (top + bottom) / 2
    rx, ry = (right - left) / 2, (bottom - top) / 2
    points: list[tuple[float, float]] = []
    for i in range(360):
        theta = math.radians(i)
        c, s = math.cos(theta), math.sin(theta)
        points.append(
            (
                cx + rx * math.copysign(abs(c) ** (2 / exponent), c),
                cy + ry * math.copysign(abs(s) ** (2 / exponent), s),
            )
        )
    return points


def _shadow(mask: Image.Image, color: RGB, drop: int, opacity: float) -> Image.Image:
    blurred = mask.filter(ImageFilter.GaussianBlur(max(1, drop * 1.5)))
    blurred = blurred.point(_scale_lut(opacity))
    layer = Image.new("L", mask.size, 0)
    layer.paste(blurred, (0, drop))
    return _solid(mask.size, color, layer)


def _solid(size: tuple[int, int], color: RGB, alpha: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", size, (*color, 255))
    layer.putalpha(alpha)
    return layer


def _fit_content(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Crop to visible pixels and scale to fit inside ``box``, keeping aspect."""
    content = _trim(img)
    scale = min(box[0] / content.width, box[1] / content.height)
    size = (max(1, round(content.width * scale)), max(1, round(content.height * scale)))
    return content.resize(size, Image.Resampling.LANCZOS)


def _trim(img: Image.Image) -> Image.Image:
    bbox = _visible_bbox(img)
    return img.crop(bbox) if bbox is not None else img


def _visible_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    return img.getchannel("A").point(_threshold_lut(_ALPHA_VISIBLE)).getbbox()


def _threshold_lut(level: int) -> list[int]:
    return [255 if v > level else 0 for v in range(256)]


def _scale_lut(factor: float) -> list[int]:
    return [min(255, round(v * factor)) for v in range(256)]


def _clamped_origin(
    canvas: tuple[int, int], item: tuple[int, int], cx: float, cy: float
) -> tuple[int, int]:
    x = round(cx - item[0] / 2)
    y = round(cy - item[1] / 2)
    x = min(max(x, PAD), canvas[0] - PAD - item[0])
    y = min(max(y, PAD), canvas[1] - PAD - item[1])
    return x, y


def _luminance(arr: FloatArray) -> FloatArray:
    return arr[..., 0] * 0.2126 + arr[..., 1] * 0.7152 + arr[..., 2] * 0.0722


def _normalized(lum: FloatArray, opaque: npt.NDArray[np.bool_]) -> FloatArray:
    """Stretch luminance over the icon's own range so dark icons still use every stop."""
    if not opaque.any():
        return lum
    values = lum[opaque]
    low, high = (float(v) for v in np.percentile(values, [2, 98]))
    if high - low < 0.08:
        # Flat single-tone glyph: give it the darkest stop so it stays readable.
        return np.zeros_like(lum)
    return np.clip((lum - low) / (high - low), 0.0, 1.0)


def _knockout_alpha(arr: FloatArray) -> FloatArray:
    """Alpha with the icon's minority tone cut out, when it has two distinct tones."""
    alpha = arr[..., 3]
    split = _split_tones(arr)
    if split is None:
        return alpha
    # Keep the cutout from eating the whole icon when the "detail" touches the edge.
    return alpha * (1.0 - split[0] * 0.92)


def _split_tones(
    arr: FloatArray, *, by_color: bool = False
) -> tuple[FloatArray, FloatArray, FloatArray] | None:
    """How much each pixel belongs to the icon's detail, plus the body and detail colors.

    Splits opaque pixels into two groups (Otsu's method), by brightness or, with
    ``by_color``, along the icon's main color difference, which also tells yellow
    from white. If the groups differ enough, the smaller one is the detail. None
    for one-tone icons.
    """
    opaque = arr[..., 3] > 0.5
    if opaque.sum() < 32:
        return None
    sample = opaque
    if by_color:
        # A cut-out's outermost pixels can keep specks of the old background, which
        # would otherwise count as a third color.
        core = _shrink(opaque, _TONE_EDGE)
        sample = core if core.sum() >= 32 else opaque
    level = _color_axis(arr, sample) if by_color else _luminance(arr)
    values = level[sample]
    threshold = _otsu(values)
    low, high = values <= threshold, values > threshold
    if not low.any() or not high.any():
        return None
    rgb = arr[..., :3][sample]
    low_rgb, high_rgb = np.median(rgb[low], axis=0), np.median(rgb[high], axis=0)
    if by_color:
        contrast = float(np.linalg.norm(high_rgb - low_rgb))
        # Otsu's cut can land at either end of an empty gap; soften around its middle.
        threshold = float(values[low].mean() + values[high].mean()) / 2
    else:
        contrast = float(values[high].mean() - values[low].mean())
    if contrast < _KNOCKOUT_CONTRAST:
        return None
    ramp = np.clip((level - threshold) / _KNOCKOUT_SOFTNESS + 0.5, 0.0, 1.0)
    if high.sum() < low.sum():
        return ramp, low_rgb, high_rgb
    return 1.0 - ramp, high_rgb, low_rgb


def _color_axis(arr: FloatArray, sample: npt.NDArray[np.bool_]) -> FloatArray:
    """Each pixel's place (0 to 1) along the line through color space the icon varies most on."""
    rgb = arr[..., :3]
    points = rgb[sample]
    center = points.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov((points - center).T))
    along = (rgb - center) @ vectors[:, -1]
    low, high = (float(v) for v in np.percentile(along[sample], [1, 99]))
    if high - low < 1e-6:
        return np.zeros_like(along)
    return np.clip((along - low) / (high - low), 0.0, 1.0)


def _otsu(values: FloatArray) -> float:
    histogram, edges = np.histogram(values, bins=64, range=(0.0, 1.0))
    weights = histogram.astype(np.float64)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(weights)
    w1 = w0[-1] - w0
    m0 = np.cumsum(weights * centers) / np.maximum(w0, 1e-9)
    m1 = (np.sum(weights * centers) - np.cumsum(weights * centers)) / np.maximum(w1, 1e-9)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(edges[int(np.argmax(between)) + 1])


def _hue_positions(hue: FloatArray, weight: FloatArray) -> FloatArray:
    """Each pixel's place (0 to 1) along the icon's own run of hues.

    The run starts just after the widest stretch of the color wheel the icon
    doesn't use, so hues that sit together on the wheel stay together.
    """
    bins = 72
    histogram, _ = np.histogram(hue, bins=bins, range=(0.0, 360.0), weights=weight)
    if histogram.sum() <= 0:
        return np.zeros_like(hue)
    used = histogram > histogram.max() * 0.01
    # Longest circular run of unused bins.
    best_len, best_end, run = 0, 0, 0
    for i in range(bins * 2):
        if used[i % bins]:
            run = 0
            continue
        run += 1
        if run > best_len and run <= bins:
            best_len, best_end = run, i % bins
    start = (best_end + 1) * 360.0 / bins if best_len else 0.0
    span = max(360.0 - best_len * 360.0 / bins, 1e-6)
    return np.clip(((hue - start) % 360.0) / span, 0.0, 1.0)


def _rgb_to_hsv(rgb: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Hue in degrees, saturation and value in 0..1, for float RGB in 0..1."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    high = rgb.max(axis=-1)
    span = high - rgb.min(axis=-1)
    safe = np.maximum(span, 1e-9)
    hue = np.where(
        high == r, ((g - b) / safe) % 6, np.where(high == g, (b - r) / safe + 2, (r - g) / safe + 4)
    )
    hue = np.where(span > 0, hue * 60.0, 0.0)
    sat = np.where(high > 0, span / np.maximum(high, 1e-9), 0.0)
    return hue, sat, high


def _hsv_to_rgb(hue: FloatArray, sat: FloatArray, val: FloatArray) -> FloatArray:
    sector = (hue / 60.0) % 6
    chroma = val * sat
    x = chroma * (1 - np.abs(sector % 2 - 1))
    zero = np.zeros_like(hue)
    index = np.floor(sector).astype(int)
    choices_r = [chroma, x, zero, zero, x, chroma]
    choices_g = [x, chroma, chroma, x, zero, zero]
    choices_b = [zero, zero, x, chroma, chroma, x]
    m = val - chroma
    channels = [np.choose(index, options) + m for options in (choices_r, choices_g, choices_b)]
    return np.stack(channels, axis=-1)


def _gradient_map(t: FloatArray, stops: Sequence[RGB]) -> FloatArray:
    colors = np.asarray(stops, dtype=np.float64) / 255
    positions = np.linspace(0.0, 1.0, len(stops), dtype=np.float64)
    channels = [np.interp(t, positions, colors[:, c]).astype(np.float64) for c in range(3)]
    return np.stack(channels, axis=-1)


def _to_array(img: Image.Image) -> FloatArray:
    return np.asarray(img.convert("RGBA"), dtype=np.float64) / 255


def _from_array(arr: FloatArray) -> Image.Image:
    return Image.fromarray(np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def _finish(img: Image.Image) -> Image.Image:
    """Clear the padding ring so no op ever draws to the canvas edge."""
    keep = Image.new("L", img.size, 0)
    ImageDraw.Draw(keep).rectangle((PAD, PAD, img.width - PAD - 1, img.height - PAD - 1), fill=255)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), keep))
    return img
