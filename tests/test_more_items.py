"""Web/game shortcuts, folders and Windows' own icons, end to end through IconService."""

import json
from pathlib import Path

from app.choices import Choice
from app.service import IconService, Status
from platform_win.item_io import READ_ONLY
from platform_win.shell_icons import RECYCLE_BIN
from platform_win.shortcuts import ItemKind, ScanRoot, ShortcutGroup, Source, variant_path
from tests.fakes import FakeDesktop

CHOICE = Choice("kawaii_pink", "pastel_recolor")


def _group(service: IconService, name: str) -> ShortcutGroup:
    return next(g for g in service.scan() if g.name == name)


def test_scan_lists_every_kind(tmp_path: Path) -> None:
    env = FakeDesktop(tmp_path, windows_icons=True)
    env.make("Paint")
    env.make_url("Counter-Strike 2", "steam://rungameid/730", r"C:\Steam\cs2.ico")
    env.make_folder("Homework v2.1")
    env.make_folder(".hidden")
    groups = {g.name: g for g in env.service().scan()}
    assert groups["Counter-Strike 2"].primary.kind is ItemKind.WEB_SHORTCUT
    assert groups["Homework v2.1"].primary.kind is ItemKind.FOLDER
    assert groups["Recycle Bin"].primary.source is Source.WINDOWS
    assert {"This PC", "Network", "User folder", "Paint"} <= set(groups)
    assert ".hidden" not in groups


def test_game_shortcut_styles_and_reverts_exactly(env: FakeDesktop) -> None:
    path = env.make_url("Game", "steam://rungameid/1", r"C:\Steam\game.ico")
    before = path.read_bytes()
    service = env.service()
    service.apply(_group(service, "Game"), CHOICE)
    assert service.is_ours(env.io.read(path).icon)
    assert service.status(_group(service, "Game")) is Status.THEMED
    service.revert(_group(service, "Game"))
    assert path.read_bytes() == before


def test_folder_styles_and_reverts_exactly(env: FakeDesktop) -> None:
    folder = env.make_folder("Games")
    service = env.service()
    service.apply(_group(service, "Games"), CHOICE)
    assert (folder / "desktop.ini").exists()
    assert env.attributes.values[folder] & READ_ONLY
    assert service.status(_group(service, "Games")) is Status.THEMED
    service.revert(_group(service, "Games"))
    assert not (folder / "desktop.ini").exists()
    assert not env.attributes.values[folder] & READ_ONLY
    assert len(service.manifest) == 0


def test_recycle_bin_gets_both_icons_and_reverts(tmp_path: Path) -> None:
    env = FakeDesktop(tmp_path, windows_icons=True)
    service = env.service()
    report = service.apply(_group(service, "Recycle Bin"), CHOICE)
    (icon_file,) = report.written
    assert variant_path(icon_file, "full").is_file()
    values = env.registry.keys[f"{RECYCLE_BIN.clsid}\\DefaultIcon"]
    assert values["full"][1].startswith(str(variant_path(icon_file, "full")))
    assert service.cleanup().removed == []  # the variant counts as in use

    service.revert(_group(service, "Recycle Bin"))
    assert env.registry.keys == {}
    assert set(service.cleanup().removed) == {icon_file, variant_path(icon_file, "full")}


def test_revert_all_covers_every_kind(tmp_path: Path) -> None:
    env = FakeDesktop(tmp_path, windows_icons=True)
    lnk = env.make("Paint")
    url = env.make_url("Game", "steam://rungameid/1")
    env.make_folder("Games")
    before = {lnk: lnk.read_bytes(), url: url.read_bytes()}
    service = env.service()
    service.apply_many(service.scan(), lambda g: CHOICE)
    assert all(service.status(g) is Status.THEMED for g in service.scan())
    service.revert_all()
    assert {p: p.read_bytes() for p in before} == before
    assert env.registry.keys == {}
    assert not (env.desktop / "Games" / "desktop.ini").exists()
    assert all(service.status(g) is Status.ORIGINAL for g in service.scan())


def test_same_program_and_name_is_one_app(env: FakeDesktop) -> None:
    exe = r"C:\Users\x\AppData\Local\Discord\Discord.exe"
    start = env.common.parent / "Start"
    start.mkdir()
    env.roots.append(ScanRoot(start, Source.START_MENU, recursive=True))
    env.link_io.create(env.desktop / "Discord.lnk", exe)
    _set_args(env, env.desktop / "Discord.lnk", "--processStart Discord.exe")
    env.link_io.create(start / "Discord.lnk", exe)  # no arguments
    env.link_io.create(start / "Work - Chrome.lnk", r"C:\Chrome\chrome.exe")
    _set_args(env, start / "Work - Chrome.lnk", "--profile-directory=Profile 1")
    env.link_io.create(start / "Chrome.lnk", r"C:\Chrome\chrome.exe")
    names = sorted(g.name for g in env.service().scan())
    assert names == ["Chrome", "Discord", "Work - Chrome"]
    discord = _group(env.service(), "Discord")
    assert len(discord.shortcuts) == 2
    assert discord.primary.source is Source.DESKTOP


def test_group_that_lost_part_of_its_style_needs_reapply(env: FakeDesktop) -> None:
    desktop = env.make("Paint")
    start = env.common.parent / "Start"
    start.mkdir()
    env.roots.append(ScanRoot(start, Source.START_MENU, recursive=True))
    env.link_io.create(start / "Paint.lnk", r"C:\Apps\Paint.exe")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    assert service.status(_group(service, "Paint")) is Status.THEMED
    # An update recreates the Start menu shortcut only.
    env.link_io.create(start / "Paint.lnk", r"C:\Apps\Paint.exe")
    assert service.status(_group(service, "Paint")) is Status.NEEDS_REAPPLY
    report = service.reapply(service.scan())
    assert start / "Paint.lnk" in report.changed
    assert desktop in report.changed
    assert service.status(_group(service, "Paint")) is Status.THEMED


def _set_args(env: FakeDesktop, path: Path, args: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["args"] = args
    path.write_text(json.dumps(data), encoding="utf-8")
