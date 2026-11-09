"""Apply / revert / reapply through IconService, using JSON stand-in shortcuts."""

from pathlib import Path

import pytest
from PIL import Image

from app.choices import Choice
from app.service import IconService, Status
from platform_win.backup import BackupCorruptError
from platform_win.extract import ExtractedIcon
from platform_win.paths import AppPaths
from platform_win.shortcuts import IconLocation, ScanRoot, ShortcutGroup, Source
from tests.conftest import load_sample
from tests.fakes import FakeLinkIO

CHOICE = Choice("kawaii_pink", "sticker")


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.desktop = tmp_path / "Desktop"
        self.common = tmp_path / "Common"
        self.desktop.mkdir()
        self.common.mkdir()
        self.paths = AppPaths(tmp_path / "Iconbloom")
        self.link_io = FakeLinkIO()
        self.notified = 0
        self.roots = [
            ScanRoot(self.desktop, Source.DESKTOP, recursive=False),
            ScanRoot(self.common, Source.ALL_USERS_START_MENU, recursive=True),
        ]

    def service(self) -> IconService:
        def notify() -> None:
            self.notified += 1

        def extractor(
            icon: IconLocation, target: str, shortcut: Path, *, use_shell: bool = True
        ) -> ExtractedIcon:
            source = icon.path if not use_shell else f"{icon.path} (shell allowed)"
            return ExtractedIcon(load_sample("multicolor"), upscaled=False, source=source)

        return IconService(self.paths, self.link_io, self.roots, extractor=extractor, notify=notify)

    def make(self, name: str, folder: Path | None = None, icon: str = "") -> Path:
        path = (folder or self.desktop) / f"{name}.lnk"
        self.link_io.create(path, rf"C:\Apps\{name}.exe", IconLocation(icon, 1 if icon else 0))
        return path


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def _renders() -> tuple[Image.Image, Image.Image]:
    image = load_sample("multicolor")
    return image, image


def _group(service: IconService, name: str) -> ShortcutGroup:
    return next(g for g in service.scan() if g.name == name)


def test_apply_then_revert_is_byte_identical_for_five_shortcuts(env: Env) -> None:
    paths = [env.make(f"App {i}", icon=rf"C:\Apps\App {i}.exe" if i % 2 else "") for i in range(5)]
    before = {p: p.read_bytes() for p in paths}
    service = env.service()

    for target in service.scan():
        report = service.apply(target, *_renders(), CHOICE)
        assert report.changed == [target.primary.path]
    assert all(p.read_bytes() != before[p] for p in paths)
    assert all(service.status(g) is Status.THEMED for g in service.scan())

    for target in service.scan():
        service.revert(target)
    assert {p: p.read_bytes() for p in paths} == before
    assert len(service.manifest) == 0
    assert all(service.status(g) is Status.ORIGINAL for g in service.scan())


def test_apply_points_shortcut_at_generated_ico(env: Env) -> None:
    lnk = env.make("Paint")
    service = env.service()
    report = service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    (ico,) = report.written
    assert ico.exists()
    assert ico.parent == env.paths.icons
    assert env.link_io.read(lnk).icon == IconLocation(str(ico), 0)
    assert service.choices.get(_group(service, "Paint").key) == CHOICE
    assert env.notified == 1


def test_dry_run_changes_nothing(env: Env) -> None:
    lnk = env.make("Paint")
    before = lnk.read_bytes()
    service = env.service()
    report = service.apply(_group(service, "Paint"), *_renders(), CHOICE, dry_run=True)
    assert report.dry_run
    assert report.changed == [lnk]
    assert lnk.read_bytes() == before
    assert not any(env.paths.icons.iterdir())
    assert len(service.manifest) == 0

    service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    themed = lnk.read_bytes()
    assert service.revert(_group(service, "Paint"), dry_run=True).changed == [lnk]
    assert service.revert_all(dry_run=True).changed == [lnk]
    assert lnk.read_bytes() == themed


def test_backup_is_on_disk_before_the_shortcut_changes(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    original = lnk.read_bytes()
    service = env.service()

    def crash(path: Path, icon: IconLocation) -> None:
        raise OSError("simulated crash while saving the shortcut")

    monkeypatch.setattr(env.link_io, "set_icon", crash)
    with pytest.raises(OSError, match="simulated crash"):
        service.apply(_group(service, "Paint"), *_renders(), CHOICE)

    # A fresh process sees the recorded original and the untouched shortcut.
    monkeypatch.undo()
    restarted = env.service()
    entry = restarted.manifest.get(lnk)
    assert entry is not None
    assert entry.original_icon == IconLocation(r"C:\Apps\paint.ico", 1)
    assert lnk.read_bytes() == original
    restarted.revert(_group(restarted, "Paint"))
    assert lnk.read_bytes() == original
    assert len(restarted.manifest) == 0


def test_crash_after_shortcut_saved_still_reverts(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()

    def crash(path: Path, icon_file: Path) -> None:
        raise OSError("simulated crash before the hash was noted")

    monkeypatch.setattr(service.manifest, "mark_applied", crash)
    with pytest.raises(OSError, match="simulated crash"):
        service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    monkeypatch.undo()

    restarted = env.service()
    restarted.revert(_group(restarted, "Paint"))
    assert env.link_io.read(lnk).icon == IconLocation(r"C:\Apps\paint.ico", 1)


def test_corrupt_manifest_blocks_the_service(env: Env) -> None:
    env.paths.ensure()
    env.paths.manifest.write_text("{ broken", encoding="utf-8")
    with pytest.raises(BackupCorruptError):
        env.service()
    assert env.paths.manifest.read_text(encoding="utf-8") == "{ broken"


def test_read_only_shortcuts_are_never_written(env: Env) -> None:
    lnk = env.make("Admin Tool", folder=env.common)
    before = lnk.read_bytes()
    service = env.service()
    report = service.apply(_group(service, "Admin Tool"), *_renders(), CHOICE)
    assert report.changed == []
    assert report.skipped == [(lnk, "read-only location")]
    assert lnk.read_bytes() == before


def test_group_applies_to_every_writable_copy(env: Env) -> None:
    desktop = env.make("Paint")
    start = env.make("Paint", folder=env.common)
    (copy := env.desktop / "Paint 2.lnk").write_bytes(desktop.read_bytes())
    service = env.service()
    (target,) = service.scan()
    report = service.apply(target, *_renders(), CHOICE)
    assert sorted(report.changed) == sorted([desktop, copy])
    assert env.link_io.read(start).icon == IconLocation()


def test_icon_without_backup_is_refused(env: Env) -> None:
    lnk = env.make("Paint")
    env.paths.ensure()
    env.link_io.set_icon(lnk, IconLocation(str(env.paths.icons / "stray.ico"), 0))
    service = env.service()
    report = service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    assert report.changed == []
    assert "no backup entry" in report.skipped[0][1]


def test_reapply_after_app_update_rewrites_shortcut(env: Env) -> None:
    lnk = env.make("Paint")
    service = env.service()
    service.apply(_group(service, "Paint"), *_renders(), CHOICE)

    # The app's updater recreates its shortcut with a new icon.
    env.link_io.create(lnk, r"C:\Apps\Paint.exe", IconLocation(r"C:\Apps\paint-v2.ico", 0))
    updated = lnk.read_bytes()
    assert service.status(_group(service, "Paint")) is Status.NEEDS_REAPPLY

    report = service.reapply(service.scan())
    assert report.changed == [lnk]
    assert service.status(_group(service, "Paint")) is Status.THEMED

    # Reverting now restores the updater's version, not the pre-update one.
    service.revert(_group(service, "Paint"))
    assert lnk.read_bytes() == updated


def test_revert_leaves_shortcut_alone_once_something_else_replaced_our_icon(env: Env) -> None:
    lnk = env.make("Paint")
    service = env.service()
    service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    env.link_io.set_icon(lnk, IconLocation(r"C:\Elsewhere\custom.ico", 0))
    after_user_change = lnk.read_bytes()
    service.revert(_group(service, "Paint"))
    assert lnk.read_bytes() == after_user_change
    assert len(service.manifest) == 0


def test_revert_restores_icon_field_when_bytes_changed_but_icon_is_ours(env: Env) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    # Something rewrites the file without changing the icon (e.g. a target fix-up).
    lnk.write_text(lnk.read_text(encoding="utf-8") + " ", encoding="utf-8")
    service.revert(_group(service, "Paint"))
    assert env.link_io.read(lnk).icon == IconLocation(r"C:\Apps\paint.ico", 1)


def test_revert_all_handles_deleted_shortcuts(env: Env) -> None:
    keep = env.make("Keep")
    gone = env.make("Gone")
    original = keep.read_bytes()
    service = env.service()
    for target in service.scan():
        service.apply(target, *_renders(), CHOICE)
    gone.unlink()
    report = service.revert_all()
    assert sorted(report.changed) == sorted([keep, gone])
    assert keep.read_bytes() == original
    assert len(service.manifest) == 0
    assert service.choices.items() == []


def test_cleanup_removes_only_unused_icons(env: Env) -> None:
    env.make("Paint")
    service = env.service()
    first = service.apply(_group(service, "Paint"), *_renders(), CHOICE).written[0]
    second = service.apply(
        _group(service, "Paint"), *_renders(), Choice("kawaii_pink", "tile_bow")
    ).written[0]
    assert service.cleanup(dry_run=True).removed == [first]
    assert first.exists()
    assert service.cleanup().removed == [first]
    assert not first.exists()
    assert second.exists()


def test_skip_and_status(env: Env) -> None:
    env.make("Paint")
    service = env.service()
    target = _group(service, "Paint")
    assert service.status(target) is Status.ORIGINAL
    service.skip(target)
    assert service.status(target) is Status.SKIPPED


def test_original_icon_of_themed_shortcut_comes_from_backup(env: Env) -> None:
    env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), *_renders(), CHOICE)
    themed = _group(service, "Paint")
    assert service.original_icon(themed).source == r"C:\Apps\paint.ico"
    assert service.reload(themed).primary.info.icon.path.endswith(".ico")


def test_custom_image_round_trip(env: Env, tmp_path: Path) -> None:
    picture = tmp_path / "bunny.PNG"
    load_sample("gradient_app").save(picture)
    service = env.service()
    name = service.store_custom_image(picture)
    assert name.endswith(".png")
    assert service.store_custom_image(picture) == name
    full, simple = service.render_choice(
        Choice("", "custom", custom_image=name), Image.new("RGBA", (1, 1))
    )
    assert full.size == (256, 256)
    assert simple is full


def test_custom_image_must_have_visible_pixels(env: Env, tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGBA", (16, 16)).save(blank)
    with pytest.raises(ValueError, match="no visible pixels"):
        env.service().store_custom_image(blank)
