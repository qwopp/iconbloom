"""Store apps (Game Bar, the new Outlook...), end to end through IconService.

A Store app has no shortcut to restyle, so styling one makes a desktop shortcut
that starts it through Explorer. The person pins that; Windows copies it into
the taskbar folder, and that copy must revert to the app's own look, never vanish.
"""

import json
from pathlib import Path

import pytest

from app.choices import Choice
from app.service import IconService, Status
from platform_win.paths import AppPaths
from platform_win.shortcuts import (
    IconLocation,
    ItemKind,
    LinkInfo,
    Place,
    ShortcutGroup,
    Source,
    kind_of,
)
from tests.fakes import EXPLORER, FakeDesktop

CHOICE = Choice("kawaii_pink", "pastel_recolor")
OTHER = Choice("mint_matcha", "pastel_recolor")
OUTLOOK = "Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows"
GAME_BAR = "Microsoft.XboxGamingOverlay_8wekyb3d8bbwe!App"
APPS = {OUTLOOK: "Outlook", GAME_BAR: "Game Bar", "Microsoft.GetHelp_8wekyb3d8bbwe!App": "Get Help"}


@pytest.fixture
def env(tmp_path: Path) -> FakeDesktop:
    return FakeDesktop(tmp_path, icons={OUTLOOK: "plate_glyph"}, store_apps=APPS)


def _group(service: IconService, name: str) -> ShortcutGroup:
    return next(g for g in service.scan() if g.name == name)


def _link(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_store_apps_are_listed_with_the_start_menu(env: FakeDesktop) -> None:
    env.make("Paint")
    groups = {g.name: g for g in env.service().scan()}
    outlook = groups["Outlook"]
    assert outlook.primary.kind is ItemKind.STORE_APP
    assert outlook.primary.source is Source.STORE_APPS
    assert outlook.places == {Place.START_MENU}
    assert not outlook.is_windows_tool
    assert "Get Help" not in groups  # help apps are noise, like readmes
    assert "Paint" in groups


def test_the_original_icon_is_the_app_as_explorer_draws_it(env: FakeDesktop) -> None:
    service = env.service()
    extracted = service.original_icon(_group(service, "Outlook"))
    assert extracted.source == " (shell allowed)"  # no icon file: straight to the shell


def test_styling_one_puts_a_themed_shortcut_on_the_desktop(env: FakeDesktop) -> None:
    service = env.service()
    report = service.apply(_group(service, "Outlook"), CHOICE)
    link = env.desktop / "Outlook.lnk"
    assert report.created == [link]
    assert report.changed == [link]
    data = _link(link)
    assert data["target"] == EXPLORER
    assert data["args"] == f"shell:AppsFolder\\{OUTLOOK}"
    assert data["app_id"] == OUTLOOK
    assert service.is_ours(IconLocation(str(data["icon"])))
    entry = service.manifest.get(link)
    assert entry is not None
    original = service.manifest.original_state(entry)
    assert original is not None
    assert original.data is None  # "wasn't there": revert deletes it


def test_after_styling_the_app_is_its_desktop_shortcut(env: FakeDesktop) -> None:
    service = env.service()
    listed = _group(service, "Outlook")
    service.apply(listed, CHOICE)
    # Right away, without a rescan: the tile follows the new shortcut.
    reloaded = service.reload(listed)
    assert reloaded.primary.path == env.desktop / "Outlook.lnk"
    assert service.status(reloaded) is Status.THEMED
    # And on the next scan the listed app gives way to it, under the same key.
    fresh = _group(service, "Outlook")
    assert [s.path for s in fresh.shortcuts] == [env.desktop / "Outlook.lnk"]
    assert fresh.key == listed.key
    assert service.status(fresh) is Status.THEMED


def test_dry_run_creates_nothing(env: FakeDesktop) -> None:
    service = env.service()
    report = service.apply(_group(service, "Outlook"), CHOICE, dry_run=True)
    assert report.created == [env.desktop / "Outlook.lnk"]
    assert not any(env.desktop.iterdir())
    assert len(service.manifest) == 0


def test_revert_takes_the_desktop_shortcut_away(env: FakeDesktop) -> None:
    service = env.service()
    service.apply(_group(service, "Outlook"), CHOICE)
    report = service.revert(_group(service, "Outlook"))
    assert report.changed == [env.desktop / "Outlook.lnk"]
    assert not (env.desktop / "Outlook.lnk").exists()
    assert len(service.manifest) == 0
    assert _group(service, "Outlook").primary.kind is ItemKind.STORE_APP


def test_a_name_already_on_the_desktop_is_left_alone(env: FakeDesktop) -> None:
    (env.desktop / "Outlook.lnk").write_text("someone else's", encoding="utf-8")
    service = env.service()
    report = service.apply(_group(service, "Outlook"), CHOICE)
    assert report.created == [env.desktop / "Outlook (Iconbloom).lnk"]
    assert (env.desktop / "Outlook.lnk").read_text(encoding="utf-8") == "someone else's"


def test_names_windows_cant_use_in_files_are_dropped(tmp_path: Path) -> None:
    env = FakeDesktop(tmp_path, store_apps={"A.B_x!App": 'Notes: "Q4"?'})
    service = env.service()
    report = service.apply(_group(service, 'Notes: "Q4"?'), CHOICE)
    assert report.created == [env.desktop / "Notes Q4.lnk"]


def _pinned(env: FakeDesktop, service: IconService) -> Path:
    """Style Outlook, then pin its shortcut the way the person would."""
    service.apply(_group(service, "Outlook"), CHOICE)
    return env.pin(env.desktop / "Outlook.lnk")


def test_the_pin_joins_the_app(env: FakeDesktop) -> None:
    service = env.service()
    pin = _pinned(env, service)
    group = _group(service, "Outlook")
    assert {s.path for s in group.shortcuts} == {env.desktop / "Outlook.lnk", pin}
    assert group.places == {Place.DESKTOP, Place.TASKBAR}
    assert service.status(group) is Status.THEMED


def test_restyling_takes_on_windows_copy_of_the_pin(env: FakeDesktop) -> None:
    service = env.service()
    pin = _pinned(env, service)
    report = service.apply(_group(service, "Outlook"), OTHER)
    assert pin in report.changed
    assert report.created == []
    assert "mint_matcha" in str(_link(pin)["icon"])
    entry = service.manifest.get(pin)
    assert entry is not None
    # Its original is the app's own icon, kept beside Iconbloom's data folder.
    assert Path(entry.original_icon_path).parent == env.paths.pin_icons


def test_reverting_keeps_the_pin_and_gives_it_the_apps_own_icon(env: FakeDesktop) -> None:
    service = env.service()
    pin = _pinned(env, service)
    report = service.revert(_group(service, "Outlook"))
    assert set(report.changed) == {env.desktop / "Outlook.lnk", pin}
    assert not (env.desktop / "Outlook.lnk").exists()
    data = _link(pin)
    assert data["target"] == EXPLORER  # still starts Outlook
    icon = Path(str(data["icon"]))
    assert icon.parent == env.paths.pin_icons
    assert icon.is_file()
    group = _group(service, "Outlook")
    assert [s.path for s in group.shortcuts] == [pin]
    assert service.status(group) is Status.ORIGINAL
    assert len(service.manifest) == 0


def test_a_reverted_pin_outlives_iconbloom(env: FakeDesktop) -> None:
    service = env.service()
    pin = _pinned(env, service)
    service.revert_all()
    # The uninstaller deletes the data folder after Revert all; the pin's icon isn't in it.
    assert not Path(str(_link(pin)["icon"])).is_relative_to(env.paths.root)


def test_revert_all_finds_pins_it_never_recorded(env: FakeDesktop) -> None:
    service = env.service()
    pin = _pinned(env, service)
    dry = service.revert_all(dry_run=True)
    assert pin in dry.changed
    assert service.is_ours(IconLocation(str(_link(pin)["icon"])))
    service.revert_all()
    assert not service.is_ours(IconLocation(str(_link(pin)["icon"])))
    assert not (env.desktop / "Outlook.lnk").exists()


def test_a_reverted_pin_can_be_styled_again(env: FakeDesktop) -> None:
    service = env.service()
    pin = _pinned(env, service)
    service.revert(_group(service, "Outlook"))
    report = service.apply(_group(service, "Outlook"), OTHER)
    assert report.changed == [pin]
    assert report.created == []
    service.revert(_group(service, "Outlook"))
    assert Path(str(_link(pin)["icon"])).parent == env.paths.pin_icons


def test_reapply_brings_back_a_deleted_desktop_shortcut(env: FakeDesktop) -> None:
    service = env.service()
    service.apply(_group(service, "Outlook"), CHOICE)
    (env.desktop / "Outlook.lnk").unlink()  # the person tidied the desktop
    groups = service.scan()
    assert service.status(_group(service, "Outlook")) is Status.NEEDS_REAPPLY
    report = service.reapply(groups)
    assert report.created == [env.desktop / "Outlook.lnk"]


def test_kind_of_knows_store_apps() -> None:
    assert kind_of(Path(f"shell:AppsFolder\\{OUTLOOK}")) is ItemKind.STORE_APP
    assert kind_of(Path(f"shell:appsfolder\\{OUTLOOK}")) is ItemKind.STORE_APP


@pytest.mark.parametrize(
    ("target", "args", "app_id"),
    [
        (EXPLORER, f"shell:AppsFolder\\{OUTLOOK}", OUTLOOK),
        (r"%SystemRoot%\explorer.exe", f'"shell:AppsFolder\\{OUTLOOK}"', OUTLOOK),
        (EXPLORER, "", None),  # File Explorer itself
        (EXPLORER, r"shell:AppsFolder\Microsoft.Windows.Explorer", None),  # not a Store app
        (r"C:\Apps\Outlook.exe", f"shell:AppsFolder\\{OUTLOOK}", None),
    ],
)
def test_store_app_id(target: str, args: str, app_id: str | None) -> None:
    assert LinkInfo(target, args, IconLocation()).store_app_id == app_id


def test_pin_icons_live_beside_the_data_folder(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "Iconbloom")
    assert paths.pin_icons == tmp_path / "Iconbloom pins"
