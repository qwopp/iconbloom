"""Each kind of item: read, change, and put back exactly from a saved state."""

from pathlib import Path

import pytest

from platform_win.item_io import (
    HIDDEN,
    READ_ONLY,
    SYSTEM,
    FolderIO,
    ItemRouter,
    UrlFileIO,
    parse_icon_string,
)
from platform_win.shortcuts import IconLocation, ItemKind, kind_of
from tests.fakes import FakeAttributes, FakeDesktop

PINK = IconLocation(r"C:\Users\x\AppData\Local\Iconbloom\icons\a_pink.ico", 0)


@pytest.mark.parametrize(
    ("text", "icon"),
    [
        (
            r"%SystemRoot%\System32\imageres.dll,-55",
            IconLocation(r"%SystemRoot%\System32\imageres.dll", -55),
        ),
        (r'"C:\Apps\a b.ico",3', IconLocation(r"C:\Apps\a b.ico", 3)),
        (r"C:\Apps\app.ico", IconLocation(r"C:\Apps\app.ico")),
        (r"C:\odd,name.ico", IconLocation(r"C:\odd,name.ico")),
    ],
)
def test_parse_icon_string(text: str, icon: IconLocation) -> None:
    assert parse_icon_string(text) == icon


def test_kinds(tmp_path: Path) -> None:
    (folder := tmp_path / "Games").mkdir()
    assert kind_of(tmp_path / "a.lnk") is ItemKind.SHORTCUT
    assert kind_of(tmp_path / "a.URL") is ItemKind.WEB_SHORTCUT
    assert kind_of(folder) is ItemKind.FOLDER
    assert kind_of(Path("::{645FF040-5081-101B-9F08-00AA002F954E}")) is ItemKind.WINDOWS_ICON


class TestUrlFile:
    def test_read_steam_shortcut(self, env: FakeDesktop) -> None:
        path = env.make_url("Counter-Strike 2", "steam://rungameid/730", r"C:\Steam\cs2.ico")
        info = UrlFileIO().read(path)
        assert info.target == "steam://rungameid/730"
        assert info.icon == IconLocation(r"C:\Steam\cs2.ico", 0)

    def test_set_and_restore_exactly(self, env: FakeDesktop) -> None:
        io = UrlFileIO()
        path = env.make_url("Game", "steam://rungameid/1", r"C:\Steam\game.ico")
        saved = io.snapshot(path)
        io.set_icon(path, PINK)
        assert io.read(path).icon == PINK
        assert b"Prop3=19,0" in path.read_bytes()
        io.restore(path, saved)
        assert path.read_bytes() == saved

    def test_web_link_without_icon_gets_one_and_loses_it(self, env: FakeDesktop) -> None:
        io = UrlFileIO()
        path = env.make_url("YouTube", "https://www.youtube.com/")
        io.set_icon(path, PINK)
        assert io.read(path).icon == PINK
        io.set_icon(path, IconLocation())
        assert io.read(path).icon == IconLocation()


class TestFolder:
    def test_plain_folder_has_default_icon(self, tmp_path: Path) -> None:
        assert FolderIO(FakeAttributes()).read(tmp_path).icon == IconLocation()

    def test_set_icon_writes_hidden_desktop_ini_and_marks_folder(self, tmp_path: Path) -> None:
        attributes = FakeAttributes()
        io = FolderIO(attributes)
        io.set_icon(tmp_path, PINK)
        ini = tmp_path / "desktop.ini"
        assert ini.read_bytes().startswith(b"\xff\xfe")  # UTF-16, as Windows writes it
        assert io.read(tmp_path).icon == PINK
        assert attributes.values[ini] == HIDDEN | SYSTEM
        assert attributes.values[tmp_path] & READ_ONLY

    def test_restore_removes_what_was_added(self, tmp_path: Path) -> None:
        attributes = FakeAttributes()
        io = FolderIO(attributes)
        saved = io.snapshot(tmp_path)
        io.set_icon(tmp_path, PINK)
        io.restore(tmp_path, saved)
        assert not (tmp_path / "desktop.ini").exists()
        assert not attributes.values[tmp_path] & READ_ONLY

    def test_existing_desktop_ini_is_kept_and_restored(self, tmp_path: Path) -> None:
        attributes = FakeAttributes()
        io = FolderIO(attributes)
        ini = tmp_path / "desktop.ini"
        original = b"[.ShellClassInfo]\r\nLocalizedResourceName=@shell32.dll,-21770\r\n"
        ini.write_bytes(original)
        attributes.values[ini] = HIDDEN | SYSTEM | 0x20
        attributes.values[tmp_path] = READ_ONLY | 0x80000  # OneDrive "always keep" bit
        saved = io.snapshot(tmp_path)
        io.set_icon(tmp_path, PINK)
        assert b"LocalizedResourceName" in ini.read_bytes()
        attributes.values[tmp_path] |= 0x100000  # OneDrive changes its own bits meanwhile
        io.restore(tmp_path, saved)
        assert ini.read_bytes() == original
        assert attributes.values[ini] == HIDDEN | SYSTEM | 0x20
        assert attributes.values[tmp_path] == READ_ONLY | 0x80000 | 0x100000

    def test_reads_older_iconfile_style(self, tmp_path: Path) -> None:
        (tmp_path / "desktop.ini").write_bytes(
            b"[.ShellClassInfo]\r\nIconFile=C:\\icons\\box.ico\r\nIconIndex=2\r\n"
        )
        assert FolderIO(FakeAttributes()).read(tmp_path).icon == IconLocation(
            r"C:\icons\box.ico", 2
        )

    def test_windows_is_told_only_about_new_icons(self, tmp_path: Path) -> None:
        """Windows' own call clears Explorer's stale folder thumbnail. Clearing or
        restoring writes desktop.ini back exactly, which Explorer already notices."""
        told: list[tuple[Path, IconLocation]] = []
        io = FolderIO(FakeAttributes(), lambda path, icon: told.append((path, icon)))
        saved = io.snapshot(tmp_path)
        io.set_icon(tmp_path, PINK)
        assert told == [(tmp_path, PINK)]
        io.set_icon(tmp_path, IconLocation())
        io.restore(tmp_path, saved)
        assert told == [(tmp_path, PINK)]

    def test_clearing_the_only_entry_removes_the_file(self, tmp_path: Path) -> None:
        io = FolderIO(FakeAttributes())
        io.set_icon(tmp_path, PINK)
        io.set_icon(tmp_path, IconLocation())
        assert not (tmp_path / "desktop.ini").exists()


def test_router_sends_each_kind_to_its_handler(env: FakeDesktop) -> None:
    router: ItemRouter = env.io
    url = env.make_url("Game", "steam://rungameid/1")
    folder = env.make_folder("Stuff")
    lnk = env.make("App")
    bin_path = Path("::{645FF040-5081-101B-9F08-00AA002F954E}")
    for path in (url, folder, lnk, bin_path):
        router.set_icon(path, PINK)
        assert router.read(path).icon == PINK
        assert router.exists(path)
    assert router.variants(bin_path)
    assert router.variants(lnk) == {}
