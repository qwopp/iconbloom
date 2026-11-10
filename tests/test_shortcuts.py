from pathlib import Path

import pytest

from platform_win.shortcuts import (
    IconLocation,
    Place,
    ScanRoot,
    Source,
    group_key,
    is_noise,
    scan,
)
from tests.fakes import FakeDesktop, FakeLinkIO


@pytest.fixture
def link_io() -> FakeLinkIO:
    return FakeLinkIO()


def _roots(tmp_path: Path) -> list[ScanRoot]:
    desktop = tmp_path / "Desktop"
    start = tmp_path / "Start"
    common = tmp_path / "Common"
    for folder in (desktop, start / "Games", common):
        folder.mkdir(parents=True)
    return [
        ScanRoot(desktop, Source.DESKTOP),
        ScanRoot(start, Source.START_MENU, max_depth=None),
        ScanRoot(common, Source.ALL_USERS_START_MENU, max_depth=None),
        ScanRoot(tmp_path / "missing", Source.TASKBAR),
    ]


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("Uninstall Foo", r"C:\Foo\foo.exe"),
        ("Foo", r"C:\Foo\unins000.exe"),
        ("Read Me", r"C:\Foo\foo.exe"),
        ("Foo Readme", r"C:\Foo\notes.exe"),
        ("Foo Website", r"C:\Foo\site.exe"),
        ("Foo", r"C:\Foo\manual.pdf"),
        ("Foo Help", r"C:\Foo\foo.exe"),
        ("Foo", r"C:\Foo\README.TXT"),
    ],
)
def test_noise_is_filtered(name: str, target: str) -> None:
    assert is_noise(name, target)


@pytest.mark.parametrize("name", ["Firefox", "Helper Studio", "Licensed Paint", "Remover Pro"])
def test_real_apps_are_kept(name: str) -> None:
    assert not is_noise(name, rf"C:\Apps\{name}.exe")


def test_scan_groups_same_target_and_prefers_own_desktop(
    tmp_path: Path, link_io: FakeLinkIO
) -> None:
    roots = _roots(tmp_path)
    link_io.create(roots[2].path / "Paint.lnk", r"C:\Paint\paint.exe")
    link_io.create(roots[1].path / "Games" / "Paint.lnk", r"C:\PAINT\paint.exe")
    link_io.create(roots[0].path / "My Paint.lnk", r"C:\Paint\paint.exe")
    link_io.create(roots[0].path / "Notes.lnk", r"C:\Notes\notes.exe")
    link_io.create(roots[0].path / "Uninstall Notes.lnk", r"C:\Notes\unins000.exe")

    groups = scan(roots, link_io)

    assert [g.name for g in groups] == ["My Paint", "Notes"]
    paint = groups[0]
    assert [s.source for s in paint.shortcuts] == [
        Source.DESKTOP,
        Source.START_MENU,
        Source.ALL_USERS_START_MENU,
    ]
    assert len(paint.own_shortcuts) == 2
    assert len(paint.shared_shortcuts) == 1
    assert len(paint.slug) == 12


def test_shared_only_group(tmp_path: Path, link_io: FakeLinkIO) -> None:
    roots = _roots(tmp_path)
    link_io.create(roots[2].path / "Admin Tool.lnk", r"C:\Tool\tool.exe")
    (group,) = scan(roots, link_io)
    assert not group.own_shortcuts
    assert group.primary.shared


def test_unreadable_links_are_skipped(tmp_path: Path, link_io: FakeLinkIO) -> None:
    roots = _roots(tmp_path)
    (roots[0].path / "Broken.lnk").write_text("not json", encoding="utf-8")
    link_io.create(roots[0].path / "Ok.lnk", r"C:\ok.exe")
    assert [g.name for g in scan(roots, link_io)] == ["Ok"]


def test_store_apps_without_target_stand_alone(tmp_path: Path, link_io: FakeLinkIO) -> None:
    roots = _roots(tmp_path)
    link_io.create(roots[0].path / "Calculator.lnk", "")
    link_io.create(roots[0].path / "Photos.lnk", "")
    groups = scan(roots, link_io)
    assert len(groups) == 2
    assert all(g.key.startswith("lnk:") for g in groups)


def test_arguments_split_groups(tmp_path: Path, link_io: FakeLinkIO) -> None:
    roots = _roots(tmp_path)
    link_io.create(roots[0].path / "A.lnk", r"C:\Chrome\chrome.exe")
    link_io.create(roots[0].path / "B.lnk", r"C:\Chrome\chrome.exe")
    a, b = (s for g in scan(roots, link_io) for s in g.shortcuts)
    profile = type(b.info)(b.info.target, "--profile-directory=Work", IconLocation())
    assert group_key(a) != group_key(type(b)(b.path, b.source, profile))


def test_desktop_comes_first_and_windows_tools_last(
    tmp_path: Path, link_io: FakeLinkIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    roots = _roots(tmp_path)
    link_io.create(roots[1].path / "Aardvark.lnk", r"C:\Apps\aardvark.exe")
    link_io.create(roots[1].path / "Command Prompt.lnk", r"C:\Windows\System32\cmd.exe")
    link_io.create(roots[1].path / "Zebra.lnk", r"C:\Apps\zebra.exe")
    link_io.create(roots[0].path / "Zoom.lnk", r"C:\Apps\zoom.exe")
    names = [g.name for g in scan(roots, link_io)]
    assert names == ["Zoom", "Aardvark", "Zebra", "Command Prompt"]


def test_groups_know_where_they_appear(tmp_path: Path, link_io: FakeLinkIO) -> None:
    roots = _roots(tmp_path)
    link_io.create(roots[0].path / "Paint.lnk", r"C:\Paint\paint.exe")
    link_io.create(roots[2].path / "Paint.lnk", r"C:\Paint\paint.exe")
    (paint,) = scan(roots, link_io)
    assert paint.places == {Place.DESKTOP, Place.START_MENU}


def test_one_unreadable_text_file_does_not_break_the_scan(tmp_path: Path) -> None:
    env = FakeDesktop(tmp_path)
    env.make("Paint")
    (env.desktop / "Broken.url").write_bytes(b"\xff\xfe[\x00I\x00n")  # UTF-16, cut mid-character
    names = [g.name for g in env.service().scan()]
    assert names == ["Paint"]
