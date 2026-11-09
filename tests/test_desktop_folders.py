"""Shortcuts kept in folders on the desktop."""

from pathlib import Path

import pytest

from app.choices import Choice
from engine.themes import DEFAULT_THEME
from platform_win import shortcuts
from platform_win.shortcuts import (
    DESKTOP_FOLDER_DEPTH,
    FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    FILE_ATTRIBUTE_RECALL_ON_OPEN,
    ItemIO,
    ItemKind,
    Place,
    ScanRoot,
    Source,
    desktop_folders_root,
    scan,
)
from tests.fakes import FakeDesktop, FakeLinkIO


@pytest.fixture
def desktop(env: FakeDesktop) -> Path:
    return env.desktop


@pytest.fixture
def link_io(env: FakeDesktop) -> FakeLinkIO:
    return env.link_io


@pytest.fixture
def io(env: FakeDesktop) -> ItemIO:
    return env.io


def _roots(desktop: Path, *extra: ScanRoot) -> list[ScanRoot]:
    return [
        ScanRoot(desktop, Source.DESKTOP, folders=True),
        *extra,
        desktop_folders_root(desktop),
    ]


def _make(link_io: FakeLinkIO, path: Path, target: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    link_io.create(path, target)
    return path


def test_nested_shortcut_is_found_after_the_start_menu(
    desktop: Path, tmp_path: Path, link_io: FakeLinkIO, io: ItemIO
) -> None:
    start = tmp_path / "Start"
    _make(link_io, desktop / "Games" / "Chess.lnk", r"C:\Games\chess.exe")
    _make(link_io, start / "Paint.lnk", r"C:\Paint\paint.exe")
    groups = scan(_roots(desktop, ScanRoot(start, Source.START_MENU, max_depth=None)), io)
    assert [g.name for g in groups] == ["Games", "Paint", "Chess"]
    chess = groups[2]
    assert chess.primary.source is Source.DESKTOP_FOLDERS
    assert chess.places == frozenset({Place.DESKTOP})


def test_nested_copy_joins_its_desktop_twin(desktop: Path, link_io: FakeLinkIO, io: ItemIO) -> None:
    _make(link_io, desktop / "Discord.lnk", r"C:\Discord\Update.exe")
    _make(link_io, desktop / "Apps" / "Discord.lnk", r"C:\Discord\Update.exe")
    groups = [g for g in scan(_roots(desktop), io) if g.primary.kind is ItemKind.SHORTCUT]
    assert len(groups) == 1
    assert [s.source for s in groups[0].shortcuts] == [Source.DESKTOP, Source.DESKTOP_FOLDERS]
    assert groups[0].primary.path == desktop / "Discord.lnk"


def test_only_top_level_folders_are_folder_items(
    desktop: Path, link_io: FakeLinkIO, io: ItemIO
) -> None:
    (desktop / "Projects" / "Inner").mkdir(parents=True)
    groups = scan(_roots(desktop), io)
    assert [g.name for g in groups] == ["Projects"]


def test_depth_is_limited(desktop: Path, link_io: FakeLinkIO, io: ItemIO) -> None:
    folder = desktop
    for level in range(DESKTOP_FOLDER_DEPTH + 1):
        folder /= f"Level{level + 1}"
        _make(link_io, folder / f"App{level + 1}.lnk", rf"C:\Apps\app{level + 1}.exe")
    names = {g.name for g in scan(_roots(desktop), io)}
    assert {f"App{n}" for n in range(1, DESKTOP_FOLDER_DEPTH + 1)} <= names
    assert f"App{DESKTOP_FOLDER_DEPTH + 1}" not in names


@pytest.mark.parametrize("skipped", [".git", "node_modules", ".hidden", "$Recycle"])
def test_tool_and_hidden_folders_are_not_entered(
    desktop: Path, link_io: FakeLinkIO, io: ItemIO, skipped: str
) -> None:
    _make(link_io, desktop / "Code" / skipped / "Tool.lnk", r"C:\Tools\tool.exe")
    assert "Tool" not in {g.name for g in scan(_roots(desktop), io)}


def test_hidden_attribute_hides_folders_but_system_does_not(
    desktop: Path, link_io: FakeLinkIO, io: ItemIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = _make(link_io, desktop / "Secret" / "Hidden.lnk", r"C:\Apps\hidden.exe")
    themed = _make(link_io, desktop / "Themed" / "Shown.lnk", r"C:\Apps\shown.exe")
    # A folder with a custom icon is marked system by Windows; it must stay visible.
    system = 0x4
    attributes = {secret.parent: FILE_ATTRIBUTE_HIDDEN, themed.parent: system}
    monkeypatch.setattr(shortcuts, "file_attributes", lambda item: attributes.get(Path(item), 0))
    names = {g.name for g in scan(_roots(desktop), io)}
    assert {"Themed", "Shown"} <= names
    assert not {"Secret", "Hidden"} & names


@pytest.mark.parametrize(
    "attribute",
    [FILE_ATTRIBUTE_OFFLINE, FILE_ATTRIBUTE_RECALL_ON_OPEN, FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS],
)
def test_onedrive_online_only_files_are_never_read(
    desktop: Path, link_io: FakeLinkIO, io: ItemIO, monkeypatch: pytest.MonkeyPatch, attribute: int
) -> None:
    cloud = _make(link_io, desktop / "Cloud.lnk", r"C:\Apps\cloud.exe")
    nested = _make(link_io, desktop / "Stuff" / "Far.lnk", r"C:\Apps\far.exe")
    local = _make(link_io, desktop / "Local.lnk", r"C:\Apps\local.exe")
    cloud_only = {cloud, nested}
    monkeypatch.setattr(
        shortcuts, "file_attributes", lambda item: attribute if Path(item) in cloud_only else 0
    )
    read: list[Path] = []
    original = link_io.read
    monkeypatch.setattr(link_io, "read", lambda path: read.append(path) or original(path))
    names = {g.name for g in scan(_roots(desktop), io)}
    assert "Local" in names
    assert not {"Cloud", "Far"} & names
    assert local in read
    assert not cloud_only & set(read)


def test_scan_stops_after_the_file_limit(
    desktop: Path, link_io: FakeLinkIO, io: ItemIO, caplog: pytest.LogCaptureFixture
) -> None:
    for n in range(5):
        _make(link_io, desktop / "Many" / f"App{n}.lnk", rf"C:\Apps\app{n}.exe")
    root = ScanRoot(desktop, Source.DESKTOP_FOLDERS, min_depth=2, max_depth=None, limit=3)
    names = {g.name for g in scan([root], io)}
    assert names == {"App0", "App1", "App2"}
    assert "stopped scanning" in caplog.text


def test_file_attributes_of_missing_path_is_zero(tmp_path: Path) -> None:
    """Paths and directory entries both work; a vanished file reads as no attributes."""
    assert shortcuts.file_attributes(tmp_path / "missing") == 0


def test_styling_a_group_changes_and_reverts_the_nested_copy(env: FakeDesktop) -> None:
    env.make("Notes")
    nested = env.make("Notes", folder=env.make_folder("Work"))
    before = nested.read_bytes()
    service = env.service()
    notes = next(g for g in service.scan() if g.name == "Notes")
    assert nested in [s.path for s in notes.shortcuts]
    service.apply(notes, Choice(DEFAULT_THEME, "pastel_recolor"))
    assert nested.read_bytes() != before
    service.revert(notes)
    assert nested.read_bytes() == before
