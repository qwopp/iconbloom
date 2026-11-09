"""The milestone 6 check on real .lnk files: apply then revert is byte-identical."""

from pathlib import Path

from app.choices import Choice
from app.service import IconService
from platform_win.paths import AppPaths
from platform_win.shortcuts import IconLocation, ScanRoot, ShellLinkIO, Source
from tests.win.conftest import NOTEPAD, SYSTEM32

TARGETS = ["notepad.exe", "mspaint.exe", "calc.exe", "charmap.exe", "cmd.exe"]


def _service(tmp_path: Path, shell_io: ShellLinkIO) -> IconService:
    desktop = tmp_path / "Desktop"
    return IconService(
        AppPaths(tmp_path / "Iconbloom"),
        shell_io,
        [ScanRoot(desktop, Source.DESKTOP, recursive=False)],
    )


def test_apply_and_revert_five_real_shortcuts(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    links: list[Path] = []
    for i, exe in enumerate(TARGETS):
        link = desktop / f"{Path(exe).stem}.lnk"
        icon = IconLocation(str(SYSTEM32 / "shell32.dll"), i) if i % 2 else None
        shell_io.create(link, str(SYSTEM32 / exe), icon)
        links.append(link)
    before = {link: link.read_bytes() for link in links}
    service = _service(tmp_path, shell_io)

    groups = service.scan()
    assert len(groups) == len(TARGETS)
    for group in groups:
        original = service.original_icon(group).image
        choice = Choice("kawaii_pink", "sticker_face")
        full, simple = service.render_choice(choice, original)
        report = service.apply(group, full, simple, choice)
        assert report.changed == [group.primary.path]

    for link in links:
        icon = shell_io.read(link).icon
        assert service.is_ours(icon), icon
        assert Path(icon.path).is_file()

    for group in service.scan():
        service.revert(group)
    assert {link: link.read_bytes() for link in links} == before


def test_original_icon_comes_back_from_backup(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shell_io.create(desktop / "Notepad.lnk", str(NOTEPAD))
    service = _service(tmp_path, shell_io)
    (group,) = service.scan()
    original = service.original_icon(group).image
    choice = Choice("kawaii_pink", "mono_rose")
    service.apply(group, *service.render_choice(choice, original), choice)
    (themed,) = service.scan()
    again = service.original_icon(themed)
    assert "notepad" in again.source.casefold()
