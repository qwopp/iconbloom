import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine.ico import build_ico
from platform_win.extract import (
    ExtractionError,
    extract_icon,
    largest_frame,
    read_icon_file,
    unpremultiply,
)
from platform_win.shortcuts import IconLocation
from tests.conftest import load_sample


def test_reads_largest_frame_of_ico(tmp_path: Path) -> None:
    ico = tmp_path / "app.ico"
    ico.write_bytes(build_ico(load_sample("multicolor"), sizes=[16, 48, 256]))
    image = read_icon_file(ico)
    assert image is not None
    assert image.size == (256, 256)


def test_reads_png(tmp_path: Path) -> None:
    png = tmp_path / "logo.png"
    load_sample("tiny").save(png)
    image = read_icon_file(png)
    assert image is not None
    assert image.size == (16, 16)


def test_unknown_file_type_is_not_an_icon_source(tmp_path: Path) -> None:
    doc = tmp_path / "notes.txt"
    doc.write_text("hi", encoding="utf-8")
    assert read_icon_file(doc) is None


def test_largest_frame_rejects_non_ico() -> None:
    buffer = io.BytesIO()
    load_sample("tiny").save(buffer, format="PNG")
    with pytest.raises(ValueError, match=r"not an \.ico"):
        largest_frame(buffer.getvalue())


def test_bad_pe_file_is_reported_as_value_error(tmp_path: Path) -> None:
    exe = tmp_path / "fake.exe"
    exe.write_bytes(b"MZ not really a program")
    with pytest.raises(ValueError):  # noqa: PT011 - message comes from icoextract
        read_icon_file(exe)


def test_extract_prefers_icon_location_then_target(tmp_path: Path) -> None:
    small = tmp_path / "small.ico"
    small.write_bytes(build_ico(load_sample("tiny"), sizes=[16, 32]))
    big = tmp_path / "big.ico"
    big.write_bytes(build_ico(load_sample("multicolor")))
    shortcut = tmp_path / "x.lnk"

    from_location = extract_icon(IconLocation(str(small), 0), str(big), shortcut)
    assert from_location.upscaled
    assert from_location.source.startswith(str(small))

    gone = IconLocation(str(tmp_path / "gone.ico"), 0)
    from_target = extract_icon(gone, str(big), shortcut, use_shell=False)
    assert not from_target.upscaled
    assert from_target.image.size == (256, 256)


def test_extract_expands_environment_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.ico").write_bytes(build_ico(load_sample("dark")))
    monkeypatch.setenv("ICONBLOOM_TEST_DIR", str(tmp_path))
    result = extract_icon(IconLocation("$ICONBLOOM_TEST_DIR/app.ico", 0), "", tmp_path / "a.lnk")
    assert result.image.size == (256, 256)


def test_named_icon_that_fails_prefers_shell_over_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = tmp_path / "big.ico"
    big.write_bytes(build_ico(load_sample("multicolor")))
    shell_icon = Image.new("RGBA", (256, 256), (1, 2, 3, 255))
    monkeypatch.setattr("platform_win.extract.shell_image", lambda path, size=256: shell_icon)
    missing = IconLocation(str(tmp_path / "gone.dll"), -114)
    assert extract_icon(missing, str(big), tmp_path / "a.lnk").source == "shell"
    themed = extract_icon(missing, str(big), tmp_path / "a.lnk", use_shell=False)
    assert themed.source == f"{big},0"


def test_system_dll_icons_are_looked_up_in_mun_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windir = tmp_path / "Windows"
    (windir / "System32").mkdir(parents=True)
    (windir / "SystemResources").mkdir()
    monkeypatch.setenv("SYSTEMROOT", str(windir))
    mun = windir / "SystemResources" / "imageres.dll.mun"
    mun.write_bytes(b"pretend PE")
    seen: list[Path] = []

    def fake_pe(path: Path, index: int) -> bytes:
        seen.append(path)
        if path != mun:
            raise ValueError("icons moved to .mun")
        return build_ico(load_sample("dark"))

    monkeypatch.setattr("platform_win.extract._pe_icon", fake_pe)
    location = IconLocation(str(windir / "System32" / "imageres.dll"), -114)
    result = extract_icon(location, "", tmp_path / "a.lnk", use_shell=False)
    assert result.source == f"{mun},-114"
    assert seen == [windir / "System32" / "imageres.dll", mun]


def test_nothing_to_extract(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="names no icon"):
        extract_icon(IconLocation(), "", tmp_path / "a.lnk", use_shell=False)


def test_extract_falls_back_to_shell_and_reports_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_shell(path: Path, size: int = 256) -> Image.Image:
        raise OSError("no shell here")

    monkeypatch.setattr("platform_win.extract.shell_image", no_shell)
    with pytest.raises(ExtractionError, match="no shell here"):
        extract_icon(IconLocation(), str(tmp_path / "readme.txt"), tmp_path / "a.lnk")

    shell_icon = Image.new("RGBA", (256, 256), (1, 2, 3, 255))
    monkeypatch.setattr("platform_win.extract.shell_image", lambda path, size=256: shell_icon)
    assert extract_icon(IconLocation(), "", tmp_path / "a.lnk").source == "shell"


def test_unpremultiply_restores_colors() -> None:
    premultiplied = Image.new("RGBA", (2, 1), (50, 25, 0, 128))
    straight = np.asarray(unpremultiply(premultiplied))
    assert tuple(straight[0, 0]) == (100, 50, 0, 128)


def test_unpremultiply_leaves_straight_alpha_alone() -> None:
    straight = Image.new("RGBA", (2, 1), (200, 25, 0, 128))
    assert unpremultiply(straight).getpixel((0, 0)) == (200, 25, 0, 128)


def test_unpremultiply_makes_alphaless_bitmap_opaque() -> None:
    no_alpha = Image.new("RGBA", (2, 1), (200, 25, 0, 0))
    assert unpremultiply(no_alpha).getpixel((0, 0)) == (200, 25, 0, 255)
