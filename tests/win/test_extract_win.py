"""Icon extraction against real Windows binaries and the shell."""

from pathlib import Path

from platform_win.extract import extract_icon, read_icon_file, shell_image
from platform_win.item_io import ShellLinkIO
from platform_win.shortcuts import IconLocation
from tests.win.conftest import NOTEPAD


def test_reads_icon_resources_from_exe() -> None:
    image = read_icon_file(NOTEPAD)
    assert image is not None
    assert max(image.size) >= 32
    assert image.getbbox() is not None


def test_shell_image_of_a_shortcut(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    link = tmp_path / "Notepad.lnk"
    shell_io.create(link, str(NOTEPAD))
    image = shell_image(link)
    assert image.size == (256, 256)
    assert image.getchannel("A").getbbox() is not None


def test_extract_uses_target_when_no_icon_location(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    link = tmp_path / "Notepad.lnk"
    shell_io.create(link, str(NOTEPAD))
    info = shell_io.read(link)
    result = extract_icon(info.icon, info.target, link)
    assert result.image.getbbox() is not None
    assert "notepad" in result.source.casefold()


def test_extract_handles_resource_moved_to_mun_file(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    # Many system DLLs keep their icons in a separate .mun file; extraction
    # must still produce an icon, via the target or the shell.
    link = tmp_path / "Folder icon.lnk"
    shell_io.create(link, str(NOTEPAD), IconLocation(r"%SystemRoot%\System32\imageres.dll", 3))
    info = shell_io.read(link)
    assert extract_icon(info.icon, info.target, link).image.getbbox() is not None
