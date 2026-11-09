"""IShellLink round trips on real .lnk files in a temp folder."""

from pathlib import Path

from platform_win.item_io import ShellLinkIO
from platform_win.paths import known_folder
from platform_win.shortcuts import IconLocation, ScanRoot, Source, scan
from tests.win.conftest import NOTEPAD, SYSTEM32


def test_create_and_read_link(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    link = tmp_path / "Notepad.lnk"
    shell_io.create(link, str(NOTEPAD))
    info = shell_io.read(link)
    assert Path(info.target).name.casefold() == "notepad.exe"
    assert info.icon.path == ""


def test_reads_the_app_id(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    plain = tmp_path / "Notepad.lnk"
    shell_io.create(plain, str(NOTEPAD))
    pinned = tmp_path / "Pinned.lnk"
    shell_io.create(pinned, str(NOTEPAD), app_id="Iconbloom.Test")
    assert shell_io.read(plain).app_id == ""
    assert shell_io.read(pinned).app_id == "Iconbloom.Test"
    shell_io.set_icon(pinned, IconLocation(str(tmp_path / "pink.ico"), 0))
    assert shell_io.read(pinned).app_id == "Iconbloom.Test"


def test_set_icon_changes_only_the_icon(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    link = tmp_path / "Notepad.lnk"
    shell_io.create(link, str(NOTEPAD))
    before = shell_io.read(link)
    icon = IconLocation(str(tmp_path / "pink.ico"), 0)
    shell_io.set_icon(link, icon)
    after = shell_io.read(link)
    assert after.icon == icon
    assert after.target == before.target
    assert after.arguments == before.arguments


def test_scan_reads_real_links(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    shell_io.create(tmp_path / "Notepad.lnk", str(NOTEPAD))
    shell_io.create(tmp_path / "Notepad again.lnk", str(NOTEPAD))
    shell_io.create(tmp_path / "Paint.lnk", str(SYSTEM32 / "mspaint.exe"))
    groups = scan([ScanRoot(tmp_path, Source.DESKTOP)], shell_io)
    assert sorted(len(g.shortcuts) for g in groups) == [1, 2]


def test_known_desktop_folder_resolves() -> None:
    assert known_folder("Desktop").is_absolute()


def test_explorer_accepts_per_file_refresh(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    from platform_win.refresh import notify_icons_changed

    link = tmp_path / "Notepad.lnk"
    shell_io.create(link, str(NOTEPAD))
    notify_icons_changed([link])  # must not raise for real paths
