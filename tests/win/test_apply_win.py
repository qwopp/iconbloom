"""The milestone 6 check on real .lnk files: apply then revert is byte-identical."""

from pathlib import Path

from app.choices import Choice
from app.service import IconService
from platform_win.item_io import ShellLinkIO
from platform_win.paths import AppPaths
from platform_win.shortcuts import IconLocation, ScanRoot, Source
from tests.win.conftest import NOTEPAD, SYSTEM32

TARGETS = ["notepad.exe", "mspaint.exe", "calc.exe", "charmap.exe", "cmd.exe"]


def _service(tmp_path: Path, shell_io: ShellLinkIO) -> IconService:
    desktop = tmp_path / "Desktop"
    return IconService(
        AppPaths(tmp_path / "Iconbloom"),
        shell_io,
        [ScanRoot(desktop, Source.DESKTOP)],
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
    report = service.apply_many(groups, lambda g: Choice("kawaii_pink", "sticker_face"))
    assert sorted(report.changed) == sorted(links)
    assert report.skipped == []

    for link in links:
        icon = shell_io.read(link).icon
        assert service.is_ours(icon), icon
        assert Path(icon.path).is_file()

    for group in service.scan():
        service.revert(group)
    assert {link: link.read_bytes() for link in links} == before


def test_original_icon_survives_styling(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shell_io.create(desktop / "Notepad.lnk", str(NOTEPAD))
    service = _service(tmp_path, shell_io)
    (group,) = service.scan()
    service.apply(group, Choice("kawaii_pink", "mono_rose"))
    (themed,) = service.scan()
    assert service.original_icon(themed).source == "saved original"
    # Without the saved picture, the recorded location still leads back to notepad.exe.
    for saved in service.paths.original_icons.iterdir():
        saved.unlink()
    assert "notepad" in service.original_icon(themed).source.casefold()
