"""Apply / revert / reapply through IconService, using JSON stand-in shortcuts."""

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.choices import Choice
from app.service import DECLINED_REASON, SHARED_REASON, IconService, Status
from engine.themes import DEFAULT_THEME
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
        # Not an OSError: that is one locked item, which a batch skips and goes on.
        raise RuntimeError("simulated crash while saving the shortcut")

    monkeypatch.setattr(env.link_io, "set_icon", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
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
        raise RuntimeError("simulated crash before the hash was noted")

    monkeypatch.setattr(service.manifest, "mark_applied", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
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


def test_our_icon_without_backup_is_taken_on(env: FakeDesktop) -> None:
    """With no record of where it came from, it reverts to the program's own icon."""
    lnk = env.make("Paint")
    env.paths.ensure()
    env.link_io.set_icon(lnk, IconLocation(str(env.paths.icons / "stray.ico"), 0))
    service = env.service()
    report = service.apply(_group(service, "Paint"), CHOICE)
    assert report.changed == [lnk]
    service.revert(_group(service, "Paint"))
    assert env.link_io.read(lnk).icon == IconLocation()
    assert len(service.manifest) == 0


def test_renamed_styled_shortcut_reverts(env: FakeDesktop) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    renamed = lnk.with_name("My Paint.lnk")
    lnk.rename(renamed)
    report = service.revert(_group(service, "My Paint"))
    assert renamed in report.changed
    assert env.link_io.read(renamed).icon == IconLocation(r"C:\Apps\paint.ico", 1)
    assert len(service.manifest) == 0


def test_renamed_styled_shortcut_can_be_styled_again(env: FakeDesktop) -> None:
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    renamed = lnk.with_name("My Paint.lnk")
    lnk.rename(renamed)
    report = service.apply(_group(service, "My Paint"), Choice("kawaii_pink", "pastel_recolor"))
    assert report.changed == [renamed]
    service.revert_all()
    assert env.link_io.read(renamed).icon == IconLocation(r"C:\Apps\paint.ico", 1)


def test_copied_styled_shortcut_reverts_with_revert_all(env: FakeDesktop) -> None:
    """Pinning makes Windows copy the shortcut into the taskbar folder."""
    lnk = env.make("Paint", icon=r"C:\Apps\paint.ico")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    pinned = env.pinned / "Paint.lnk"
    pinned.write_bytes(lnk.read_bytes())
    report = service.revert_all()
    assert set(report.changed) == {lnk, pinned}
    assert env.link_io.read(pinned).icon == IconLocation(r"C:\Apps\paint.ico", 1)
    assert not report.skipped


def test_cleanup_keeps_an_icon_only_a_copy_uses(env: FakeDesktop) -> None:
    lnk = env.make("Paint")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    icon = Path(env.link_io.read(lnk).icon.path)
    lnk.rename(lnk.with_name("My Paint.lnk"))
    service.manifest.forget(lnk)
    assert service.cleanup().removed == []
    assert icon.exists()


@pytest.mark.parametrize("own_image", [False, True], ids=["theme", "own-image"])
def test_reapply_after_app_update_rewrites_shortcut(
    env: FakeDesktop, tmp_path: Path, own_image: bool
) -> None:
    lnk = env.make("Paint")
    service = env.service()
    choice = _cutout_of_own_image(service, tmp_path) if own_image else CHOICE
    service.apply(_group(service, "Paint"), choice)

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
    assert choice.uses_own_image
    assert choice.custom_image is not None
    assert choice.custom_image.endswith(".png")
    assert service.styles.store_custom_image(picture) == choice
    full, simple = service.styles.render(choice)
    assert full.size == (256, 256)
    assert simple is full

    lnk = env.make("Paint")
    service.apply(_group(service, "Paint"), choice)
    assert service.is_ours(env.link_io.read(lnk).icon)


def test_own_image_is_remembered_until_its_file_is_gone(env: FakeDesktop, tmp_path: Path) -> None:
    env.make("Paint")
    service = env.service()
    image = _cutout_of_own_image(service, tmp_path).custom_image
    assert image is not None
    service.set_own_image(_group(service, "Paint"), image)
    restarted = env.service()
    assert restarted.own_image(_group(restarted, "Paint")) == image
    (env.paths.custom_images / image).unlink()  # deleted by hand
    assert restarted.own_image(_group(restarted, "Paint")) is None
    assert restarted.choices.image(_group(restarted, "Paint").key) is None


def _cutout_of_own_image(service: IconService, tmp_path: Path) -> Choice:
    picture = tmp_path / "kitty.png"
    load_sample("plate_glyph").save(picture)
    image = service.styles.store_custom_image(picture).custom_image
    assert image is not None
    return Choice(DEFAULT_THEME, "cutout", custom_image=image)


def test_styles_draw_from_the_users_image(env: FakeDesktop, tmp_path: Path) -> None:
    service = env.service()
    choice = _cutout_of_own_image(service, tmp_path)
    assert choice.custom_image is not None
    as_is, _ = service.styles.render(Choice.custom(choice.custom_image))
    cut, _ = service.styles.render(choice)  # no app icon needed: the image is the source
    assert cut.tobytes() != as_is.tobytes()
    lnk = env.make("Paint")
    service.apply(_group(service, "Paint"), choice)
    assert service.is_ours(env.link_io.read(lnk).icon)
    assert service.choices.get(_group(service, "Paint").key) == choice


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


def test_revert_forgets_shortcuts_deleted_since_styling(env: FakeDesktop) -> None:
    folder = env.desktop / "Games"
    folder.mkdir()
    kept = env.make("Paint")
    gone = env.make("Paint", folder=folder)
    env.make("Other")
    service = env.service()
    service.apply(_group(service, "Paint"), CHOICE)
    service.apply(_group(service, "Other"), CHOICE)
    gone.unlink()
    service.revert(_group(service, "Paint"))
    assert service.manifest.get(gone) is None
    assert service.manifest.get(kept) is None
    assert len(service.manifest) == 1  # Other's entry stays


def test_custom_image_must_have_visible_pixels(env: FakeDesktop, tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGBA", (16, 16)).save(blank)
    with pytest.raises(ValueError, match="no visible pixels"):
        env.service().styles.store_custom_image(blank)


def _lock(env: FakeDesktop, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make one shortcut fail to save, like a read-only or locked file on Windows."""
    real_set, real_restore = env.link_io.set_icon, env.link_io.restore

    def set_icon(path: Path, icon: IconLocation) -> None:
        if path.stem == name:
            raise PermissionError(f"{path} is read-only")
        real_set(path, icon)

    def restore(path: Path, state: bytes | None) -> None:
        if path.stem == name:
            raise PermissionError(f"{path} is read-only")
        real_restore(path, state)

    monkeypatch.setattr(env.link_io, "set_icon", set_icon)
    monkeypatch.setattr(env.link_io, "restore", restore)


def test_a_locked_shortcut_does_not_stop_the_batch(
    env: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("Alpha", "Locked", "Gamma"):
        env.make(name)
    service = env.service()
    _lock(env, monkeypatch, "Locked")
    report = service.apply_many(service.scan(), lambda g: CHOICE)
    assert sorted(p.stem for p in report.changed) == ["Alpha", "Gamma"]
    assert [p.stem for p, _ in report.skipped] == ["Locked"]
    assert service.status(_group(service, "Gamma")) is Status.THEMED
    assert service.choices.get(_group(service, "Gamma").key) == CHOICE


def test_revert_all_goes_on_past_a_locked_shortcut(
    env: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("Alpha", "Locked", "Gamma"):
        env.make(name)
    service = env.service()
    service.apply_many(service.scan(), lambda g: CHOICE)
    _lock(env, monkeypatch, "Locked")
    report = service.revert_all()
    assert [p.stem for p, _ in report.skipped] == ["Locked"]
    assert service.status(_group(service, "Alpha")) is Status.ORIGINAL
    assert service.status(_group(service, "Gamma")) is Status.ORIGINAL


def test_a_failing_permission_helper_skips_only_shared_items(
    env: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.make("Paint")
    env.make("Admin", folder=env.common)
    service = env.service()

    def broken(action: object, items: object) -> object:
        raise OSError("the helper ended with exit code 3")

    monkeypatch.setattr(service, "_elevator", broken)
    report = service.apply_many(service.scan(), lambda g: CHOICE, include_shared=True)
    assert [p.stem for p in report.changed] == ["Paint"]
    assert "permission helper failed" in report.skipped[0][1]
    assert service.choices.get(_group(service, "Paint").key) == CHOICE


def test_changes_from_two_threads_take_turns(env: FakeDesktop) -> None:
    for name in ("Alpha", "Beta", "Gamma", "Delta"):
        env.make(name)
    service = env.service()
    groups = service.scan()
    inside: list[int] = []
    overlaps: list[int] = []
    real = service._themed_icon  # pyright: ignore[reportPrivateUsage]

    def watched(*args: Any, **kwargs: Any) -> Path:
        inside.append(1)
        if len(inside) > 1:
            overlaps.append(1)
        try:
            time.sleep(0.01)
            return real(*args, **kwargs)
        finally:
            inside.pop()

    service._themed_icon = watched  # type: ignore[method-assign]
    workers = [
        threading.Thread(target=service.apply_many, args=(groups[i::2], lambda g: CHOICE))
        for i in (0, 1)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert not overlaps
    assert all(service.status(g) is Status.THEMED for g in service.scan())


def test_a_sideways_phone_photo_is_used_upright(env: FakeDesktop, tmp_path: Path) -> None:
    photo = Image.new("RGB", (80, 40), (220, 60, 120))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: stored sideways, shown turned 90 degrees
    path = tmp_path / "cat.jpg"
    photo.save(path, exif=exif)
    service = env.service()
    choice = service.styles.store_custom_image(path)
    assert choice.custom_image is not None
    source = service.styles.custom_source(choice.custom_image)
    left, top, right, bottom = source.getbbox() or (0, 0, 0, 0)
    assert bottom - top > right - left  # tall, as the phone showed it
