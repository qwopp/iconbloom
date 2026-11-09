"""Apply / revert / reapply through IconService, using JSON stand-in shortcuts."""

from pathlib import Path

import pytest
from PIL import Image

from app.choices import Choice
from app.service import DECLINED_REASON, SHARED_REASON, IconService, Status
from platform_win.backup import BackupCorruptError
from platform_win.shortcuts import IconLocation, ShortcutGroup
from tests.conftest import load_sample
from tests.fakes import FakeDesktop

CHOICE = Choice("kawaii_pink", "sticker")


def _group(service: IconService, name: str) -> ShortcutGroup:
    return next(g for g in service.scan() if g.name == name)


def test_apply_then_revert_is_byte_identical_for_five_shortcuts(env: FakeDesktop) -> None:
    paths = [env.make(f"App {i}", icon=rf"C:\Apps\App {i}.exe" if i % 2 else "") for i in range(5)]
    before = {p: p.read_bytes() for p in paths}
    service = env.service()

    for target in service.scan():
        report = service.apply(target, CHOICE)
        assert report.changed == [target.primary.path]
    assert all(p.read_bytes() != before[p] for p in paths)
    assert all(service.status(g) is Status.THEMED for g in service.scan())

    for target in service.scan():
        service.revert(target)
    assert {p: p.read_bytes() for p in paths} == before
    assert len(service.manifest) == 0
    assert all(service.status(g) is Status.ORIGINAL for g in service.scan())


def test_apply_points_shortcut_at_generated_ico(env: FakeDesktop) -> None:
    lnk = env.make("Paint")
    service = env.service()
    report = service.apply(_group(service, "Paint"), CHOICE)
    (ico,) = report.written
    assert ico.exists()
    assert ico.parent == env.paths.icons
    assert env.link_io.read(lnk).icon == IconLocation(str(ico), 0)
    assert service.choices.get(_group(service, "Paint").key) == CHOICE
    assert env.notified == 1


def test_dry_run_changes_nothing(env: FakeDesktop) -> None:
    lnk = env.make("Paint")
    before = lnk.read_bytes()
    service = env.service()
    report = service.apply(_group(service, "Paint"), CHOICE, dry_run=True)
    assert report.dry_run
    assert report.changed == [lnk]
    assert lnk.read_bytes() == before
    assert not any(env.paths.icons.iterdir())
    assert len(service.manifest) == 0

    service.apply(_group(service, "Paint"), CHOICE)
    themed = lnk.read_bytes()
    assert service.revert(_group(service, "Paint"), dry_run=True).changed == [lnk]
    assert service.revert_all(dry_run=True).changed == [lnk]
    assert lnk.read_bytes() == themed


def test_backup_is_on_disk_before_the_shortcut_changes(
    env: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    original = lnk.read_bytes()
    service = env.service()

    def crash(path: Path, icon: IconLocation) -> None:
        raise OSError("simulated crash while saving the shortcut")

    monkeypatch.setattr(env.link_io, "set_icon", crash)
    with pytest.raises(OSError, match="simulated crash"):
        service.apply(_group(service, "Paint"), CHOICE)

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
    env: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()

    def crash(path: Path, icon_file: Path, state: bytes | None) -> None:
        raise OSError("simulated crash before the hash was noted")

    monkeypatch.setattr(service.manifest, "mark_applied", crash)
    with pytest.raises(OSError, match="simulated crash"):
        service.apply(_group(service, "Paint"), CHOICE)
    monkeypatch.undo()

    restarted = env.service()
    restarted.revert(_group(restarted, "Paint"))
    assert env.link_io.read(lnk).icon == IconLocation(r"C:\Apps\paint.ico", 1)


def test_corrupt_manifest_blocks_the_service(env: FakeDesktop) -> None:
    env.paths.ensure()
    env.paths.manifest.write_text("{ broken", encoding="utf-8")
    with pytest.raises(BackupCorruptError):
        env.service()
    assert env.paths.manifest.read_text(encoding="utf-8") == "{ broken"


def test_shared_shortcuts_are_left_alone_unless_asked(env: FakeDesktop) -> None:
    lnk = env.make("Admin Tool", folder=env.common)
    before = lnk.read_bytes()
    service = env.service()
    report = service.apply(_group(service, "Admin Tool"), CHOICE)
    assert report.changed == []
    assert report.written == []  # nothing to theme, so no icon file either
    assert report.skipped == [(lnk, SHARED_REASON)]
    assert lnk.read_bytes() == before
    assert env.elevations == []


def test_shared_shortcuts_change_with_permission_and_revert(env: FakeDesktop) -> None:
    mine = env.make("Paint")
    shared = env.make("Paint", folder=env.common, icon=r"C:\Apps\paint.ico")
    service = env.service()
    report = service.apply(_group(service, "Paint"), CHOICE, include_shared=True)
    assert sorted(report.changed) == sorted([mine, shared])
    assert len(env.elevations) == 1
    assert service.is_ours(env.link_io.read(shared).icon)
    assert service.manifest.get(shared) is not None  # the elevated copy's backup is picked up

    service.revert(_group(service, "Paint"))
    assert env.link_io.read(shared).icon == IconLocation(r"C:\Apps\paint.ico", 1)
    assert len(env.elevations) == 2
    assert len(service.manifest) == 0


def test_one_permission_prompt_for_a_whole_batch(env: FakeDesktop) -> None:
    for name in ("Alpha", "Beta", "Gamma"):
        env.make(name, folder=env.common)
    service = env.service()
    report = service.apply_many(service.scan(), lambda g: CHOICE, include_shared=True)
    assert len(report.changed) == 3
    assert len(env.elevations) == 1
    assert len(service.revert_all().changed) == 3
    assert len(env.elevations) == 2


def test_declined_permission_changes_nothing_shared(env: FakeDesktop) -> None:
    mine = env.make("Paint")
    shared = env.make("Paint", folder=env.common)
    before = shared.read_bytes()
    env.decline_permission = True
    service = env.service()
    report = service.apply(_group(service, "Paint"), CHOICE, include_shared=True)
    assert report.changed == [mine]
    assert report.skipped == [(shared, DECLINED_REASON)]
    assert shared.read_bytes() == before


def test_group_applies_to_every_own_copy(env: FakeDesktop) -> None:
    desktop = env.make("Paint")
    start = env.make("Paint", folder=env.common)
    (copy := env.desktop / "Paint 2.lnk").write_bytes(desktop.read_bytes())
    service = env.service()
    (target,) = service.scan()
    report = service.apply(target, CHOICE)
    assert sorted(report.changed) == sorted([desktop, copy])
    assert env.link_io.read(start).icon == IconLocation()


def test_icon_without_backup_is_refused(env: FakeDesktop) -> None:
    lnk = env.make("Paint")
    env.paths.ensure()
    env.link_io.set_icon(lnk, IconLocation(str(env.paths.icons / "stray.ico"), 0))
    service = env.service()
    report = service.apply(_group(service, "Paint"), CHOICE)
    assert report.changed == []
    assert "no backup entry" in report.skipped[0][1]


def test_reapply_after_app_update_rewrites_shortcut(env: FakeDesktop) -> None:
    lnk = env.make("Paint")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)

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


def test_revert_leaves_shortcut_alone_once_something_else_replaced_our_icon(
    env: FakeDesktop,
) -> None:
    lnk = env.make("Paint")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    env.link_io.set_icon(lnk, IconLocation(r"C:\Elsewhere\custom.ico", 0))
    after_user_change = lnk.read_bytes()
    service.revert(_group(service, "Paint"))
    assert lnk.read_bytes() == after_user_change
    assert len(service.manifest) == 0


def test_revert_restores_icon_field_when_bytes_changed_but_icon_is_ours(env: FakeDesktop) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    # Something rewrites the file without changing the icon (e.g. a target fix-up).
    lnk.write_text(lnk.read_text(encoding="utf-8") + " ", encoding="utf-8")
    service.revert(_group(service, "Paint"))
    assert env.link_io.read(lnk).icon == IconLocation(r"C:\Apps\paint.ico", 1)


def test_revert_all_handles_deleted_shortcuts(env: FakeDesktop) -> None:
    keep = env.make("Keep")
    gone = env.make("Gone")
    original = keep.read_bytes()
    service = env.service()
    for target in service.scan():
        service.apply(target, CHOICE)
    gone.unlink()
    report = service.revert_all()
    assert sorted(report.changed) == sorted([keep, gone])
    assert keep.read_bytes() == original
    assert len(service.manifest) == 0
    assert service.choices.items() == []


def test_cleanup_removes_only_unused_icons(env: FakeDesktop) -> None:
    env.make("Paint")
    service = env.service()
    first = service.apply(_group(service, "Paint"), CHOICE).written[0]
    second = service.apply(_group(service, "Paint"), Choice("kawaii_pink", "tile_bow")).written[0]
    assert service.cleanup(dry_run=True).removed == [first]
    assert first.exists()
    assert service.cleanup().removed == [first]
    assert not first.exists()
    assert second.exists()


def test_skip_and_status(env: FakeDesktop) -> None:
    env.make("Paint")
    service = env.service()
    target = _group(service, "Paint")
    assert service.status(target) is Status.ORIGINAL
    service.skip(target)
    assert service.status(target) is Status.SKIPPED


def test_original_icon_of_styled_item_is_the_saved_picture(env: FakeDesktop) -> None:
    env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    themed = _group(service, "Paint")
    original = service.original_icon(themed)
    assert original.source == "saved original"
    assert original.image.size == (256, 256)
    assert service.reload(themed).primary.info.icon.path.endswith(".ico")


def test_without_a_saved_picture_the_backup_location_is_used(env: FakeDesktop) -> None:
    env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    for saved in env.paths.original_icons.iterdir():
        saved.unlink()
    original = service.original_icon(_group(service, "Paint"))
    assert original.source == r"C:\Apps\paint.ico"  # no "(shell allowed)": Windows would show ours


def test_custom_image_round_trip(env: FakeDesktop, tmp_path: Path) -> None:
    picture = tmp_path / "bunny.PNG"
    load_sample("gradient_app").save(picture)
    service = env.service()
    choice = service.styles.store_custom_image(picture)
    assert choice.is_custom
    assert choice.custom_image is not None
    assert choice.custom_image.endswith(".png")
    assert service.styles.store_custom_image(picture) == choice
    full, simple = service.styles.render(choice)
    assert full.size == (256, 256)
    assert simple is full

    lnk = env.make("Paint")
    service.apply(_group(service, "Paint"), choice)
    assert service.is_ours(env.link_io.read(lnk).icon)


def test_theme_choice_needs_the_original(env: FakeDesktop) -> None:
    with pytest.raises(ValueError, match="needs the original icon"):
        env.service().styles.render(CHOICE)


def test_themes_are_listed_and_cached(env: FakeDesktop) -> None:
    service = env.service()
    assert ("kawaii_pink", "Kawaii Pink") in service.styles.theme_names()
    assert service.styles.theme("kawaii_pink") is service.styles.theme("kawaii_pink")


def test_batch_records_failures_and_notifies_once(tmp_path: Path) -> None:
    env = FakeDesktop(tmp_path, unreadable={"Broken"})
    for name in ("Alpha", "Broken", "Gamma"):
        env.make(name)
    service = env.service()
    seen: list[str] = []

    def progress(i: int, target: ShortcutGroup) -> bool:
        seen.append(target.name)
        return True

    report = service.apply_many(service.scan(), lambda g: CHOICE, progress=progress)
    assert seen == ["Alpha", "Broken", "Gamma"]
    assert len(report.changed) == 2
    assert "unreadable icon" in report.skipped[0][1]
    assert env.notified == 1


def test_batch_can_be_stopped(env: FakeDesktop) -> None:
    for name in ("Alpha", "Beta"):
        env.make(name)
    service = env.service()
    report = service.apply_many(service.scan(), lambda g: CHOICE, progress=lambda i, g: i == 0)
    assert len(report.changed) == 1


def test_custom_image_must_have_visible_pixels(env: FakeDesktop, tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGBA", (16, 16)).save(blank)
    with pytest.raises(ValueError, match="no visible pixels"):
        env.service().styles.store_custom_image(blank)
