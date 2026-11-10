"""Which wallpaper picture the taskbar preview uses, and what happens when there is none."""

from pathlib import Path

from PIL import Image

from platform_win.wallpaper import MAX_SIZE, load_wallpaper, wallpaper_file


def _themes(appdata: Path) -> Path:
    folder = appdata / "Microsoft" / "Windows" / "Themes"
    folder.mkdir(parents=True)
    return folder


def test_prefers_the_file_windows_names(tmp_path: Path) -> None:
    named = tmp_path / "beach.jpg"
    named.write_bytes(b"x")
    (_themes(tmp_path) / "TranscodedWallpaper").write_bytes(b"x")
    assert wallpaper_file(str(named), tmp_path) == named


def test_falls_back_to_windows_copy(tmp_path: Path) -> None:
    copy = _themes(tmp_path) / "TranscodedWallpaper"
    copy.write_bytes(b"x")
    assert wallpaper_file("", tmp_path) == copy
    assert wallpaper_file(str(tmp_path / "moved.jpg"), tmp_path) == copy


def test_none_without_a_picture(tmp_path: Path) -> None:
    # A solid color, or an app like Wallpaper Engine drawing the desktop.
    assert wallpaper_file("", tmp_path) is None
    assert load_wallpaper(None) is None


def test_loads_big_pictures_at_preview_size(tmp_path: Path) -> None:
    # Windows' own copy has no extension, so the format comes from the content.
    path = tmp_path / "TranscodedWallpaper"
    Image.new("RGB", (3840, 2160), (20, 40, 60)).save(path, format="JPEG")
    picture = load_wallpaper(path)
    assert picture is not None
    assert picture.mode == "RGBA"
    assert picture.width <= MAX_SIZE[0]
    assert picture.height <= MAX_SIZE[1]
    pixel = picture.getpixel((10, 10))
    assert isinstance(pixel, tuple)
    assert all(abs(a - b) <= 3 for a, b in zip(pixel[:3], (20, 40, 60), strict=True))  # JPEG


def test_unreadable_pictures_give_none(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not a picture")
    assert load_wallpaper(broken) is None
    assert load_wallpaper(tmp_path / "missing.jpg") is None
