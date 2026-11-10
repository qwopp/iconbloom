"""The taskbar's settings: what is written, what is saved, and that revert puts it all back."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.taskbar import TaskbarChoice, TaskbarService
from engine import taskbar as engine_taskbar
from engine.taskbar import BarSpec, SearchMode, accent_shades
from platform_win import taskbar as tb
from platform_win.backup import BackupCorruptError, TaskbarBackup
from tests.fakes import USER_TASKBAR, FakeTaskbar

PINK = (186, 115, 143)
CHOICE = TaskbarChoice("kawaii_pink", "soft")


def _state(**changes: object) -> tb.TaskbarState:
    base = tb.TaskbarState(
        accent=None,
        transparency=False,
        centered=True,
        small=False,
        search=tb.Search.BOX,
        task_view=False,
        auto_hide=False,
        light_windows=False,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.fixture
def taskbar() -> FakeTaskbar:
    return FakeTaskbar()


@pytest.fixture
def service(taskbar: FakeTaskbar, tmp_path: Path) -> TaskbarService:
    return taskbar.service(tmp_path / "taskbar.json")


# ---- reading ------------------------------------------------------------------------


def test_reads_the_users_taskbar(taskbar: FakeTaskbar) -> None:
    assert taskbar.io.read() == _state()


def test_absent_values_read_as_windows_defaults() -> None:
    state = FakeTaskbar({}).io.read()
    assert state == tb.TaskbarState(
        accent=None,
        transparency=True,
        centered=True,
        small=False,
        search=tb.Search.BOX,
        task_view=True,
        auto_hide=False,
        light_windows=True,
    )


def test_unexpected_values_fall_back_to_defaults() -> None:
    values = {
        tb.SEARCH_MODE: (tb.REG_DWORD, 9),
        tb.TRANSPARENCY: (tb.REG_SZ, "not a number"),
        tb.TASK_VIEW: (tb.REG_BINARY, b"\x01"),
    }
    state = FakeTaskbar(values).io.read()
    assert state.search is tb.Search.BOX
    assert state.transparency
    assert state.task_view


def test_accent_reads_slot_five_only_when_shown_in_dark_mode() -> None:
    shades = accent_shades(PINK)
    palette = (tb.REG_BINARY, b"".join(bytes((*s, 0)) for s in shades))
    shown = {tb.PALETTE: palette, tb.ACCENT_ON_TASKBAR: (tb.REG_DWORD, 1)}
    assert FakeTaskbar({**shown, tb.LIGHT_MODE: (tb.REG_DWORD, 0)}).io.read().accent == PINK
    # Windows ignores the accent setting in light mode.
    assert FakeTaskbar({**shown, tb.LIGHT_MODE: (tb.REG_DWORD, 1)}).io.read().accent is None
    short = {**shown, tb.LIGHT_MODE: (tb.REG_DWORD, 0), tb.PALETTE: (tb.REG_BINARY, b"\x00")}
    assert FakeTaskbar(short).io.read().accent is None


def test_win10_is_never_centered_and_reads_its_own_small_value() -> None:
    io = FakeTaskbar({tb.SMALL_WIN10: (tb.REG_DWORD, 1)}, win11=False).io
    state = io.read()
    assert not state.centered
    assert state.small
    assert tb.Search.BUTTON not in io.search_modes()


def test_slot_matches_the_engine() -> None:
    assert tb.TASKBAR_SLOT == engine_taskbar.TASKBAR_SLOT


# ---- planning writes ------------------------------------------------------------------


def test_nothing_to_write_when_nothing_changes(taskbar: FakeTaskbar) -> None:
    assert taskbar.io.plan(_state()) == {}


def test_accent_writes_every_accent_value(taskbar: FakeTaskbar) -> None:
    shades = accent_shades(PINK)
    planned = taskbar.io.plan(_state(accent=PINK), shades)
    palette = planned["\\".join(tb.PALETTE)]
    assert palette[0] == tb.REG_BINARY
    assert isinstance(palette[1], bytes)
    assert palette[1][20:23] == bytes(PINK)
    menu = shades[3]
    assert planned["\\".join(tb.ACCENT_MENU)] == (
        tb.REG_DWORD,
        0xFF000000 | menu[2] << 16 | menu[1] << 8 | menu[0],
    )
    assert planned["\\".join(tb.DWM_COLOR)] == (
        tb.REG_DWORD,
        0xC4000000 | menu[0] << 16 | menu[1] << 8 | menu[2],
    )
    assert planned["\\".join(tb.ACCENT_ON_TASKBAR)] == (tb.REG_DWORD, 1)
    assert planned["\\".join(tb.AUTO_COLOR)] == (tb.REG_DWORD, 0)
    assert "\\".join(tb.LIGHT_MODE) not in planned  # already dark


def test_accent_in_light_mode_also_turns_windows_dark() -> None:
    io = FakeTaskbar({**USER_TASKBAR, tb.LIGHT_MODE: (tb.REG_DWORD, 1)}).io
    planned = io.plan(_state(accent=PINK), accent_shades(PINK))
    assert planned["\\".join(tb.LIGHT_MODE)] == (tb.REG_DWORD, 0)


def test_string_auto_color_keeps_its_type() -> None:
    io = FakeTaskbar({**USER_TASKBAR, tb.AUTO_COLOR: (tb.REG_SZ, "1")}).io
    planned = io.plan(_state(accent=PINK), accent_shades(PINK))
    assert planned["\\".join(tb.AUTO_COLOR)] == (tb.REG_SZ, "0")


def test_accent_needs_matching_shades(taskbar: FakeTaskbar) -> None:
    with pytest.raises(ValueError, match="8 accent shades"):
        taskbar.io.plan(_state(accent=PINK), accent_shades((1, 2, 3)))


def test_windows_default_only_turns_the_accent_off(taskbar: FakeTaskbar) -> None:
    taskbar.registry.values[tb.ACCENT_ON_TASKBAR] = (tb.REG_DWORD, 1)
    assert taskbar.io.plan(_state()) == {"\\".join(tb.ACCENT_ON_TASKBAR): (tb.REG_DWORD, 0)}


def test_layout_values(taskbar: FakeTaskbar) -> None:
    wanted = _state(
        transparency=True,
        centered=False,
        small=True,
        search=tb.Search.BUTTON,
        task_view=True,
        auto_hide=True,
    )
    assert taskbar.io.plan(wanted) == {
        "\\".join(tb.TRANSPARENCY): (tb.REG_DWORD, 1),
        "\\".join(tb.ALIGNMENT): (tb.REG_DWORD, 0),
        "\\".join(tb.SMALL_WIN11): (tb.REG_DWORD, 0),
        "\\".join(tb.SEARCH_MODE): (tb.REG_DWORD, 3),
        "\\".join(tb.TASK_VIEW): (tb.REG_DWORD, 1),
        tb.AUTO_HIDE: (tb.REG_DWORD, 1),
    }


def test_smaller_buttons_off_goes_back_to_windows_default() -> None:
    io = FakeTaskbar({**USER_TASKBAR, tb.SMALL_WIN11: (tb.REG_DWORD, 0)}).io
    assert io.plan(_state()) == {"\\".join(tb.SMALL_WIN11): (tb.REG_DWORD, 2)}


def test_win10_skips_what_it_lacks() -> None:
    io = FakeTaskbar(USER_TASKBAR, win11=False).io
    planned = io.plan(_state(centered=True, small=True, search=tb.Search.BUTTON))
    assert planned == {"\\".join(tb.SMALL_WIN10): (tb.REG_DWORD, 1)}


def test_write_broadcasts_and_sets_auto_hide(taskbar: FakeTaskbar) -> None:
    taskbar.io.write(taskbar.io.plan(_state(task_view=True, auto_hide=True)))
    assert taskbar.registry.values[tb.TASK_VIEW] == (tb.REG_DWORD, 1)
    assert taskbar.appbar.hidden
    assert taskbar.broadcasts == ["ImmersiveColorSet", "TraySettings"]


# ---- snapshots ----------------------------------------------------------------------


def test_snapshot_round_trips_through_json(taskbar: FakeTaskbar) -> None:
    before = taskbar.state()
    saved = json.loads(json.dumps(taskbar.io.snapshot()))
    taskbar.io.write(taskbar.io.plan(_state(accent=PINK, auto_hide=True), accent_shades(PINK)))
    del taskbar.registry.values[tb.SEARCH_MODE]
    taskbar.registry.values[tb.ALIGNMENT] = (tb.REG_DWORD, 0)  # absent before: must go again
    taskbar.io.restore(saved)
    assert taskbar.state() == before


@pytest.mark.parametrize("bad", [[1], ["x", 1], [4, 1.5], [4, True], "text"])
def test_decode_rejects_damaged_values(bad: object) -> None:
    with pytest.raises(ValueError, match="not a saved registry value"):
        tb.decode(bad)


def test_adopting_outside_changes() -> None:
    current = {"a": 1, "b": 2}
    assert tb.adopt_outside_changes(None, None, current) == current
    # Saved original but nothing applied: a crash mid-write, so the original stands.
    assert tb.adopt_outside_changes({"a": 0, "b": 0}, None, current) == {"a": 0, "b": 0}
    # "b" moved since Iconbloom applied it, so it's the user's now; "a" is still ours.
    assert tb.adopt_outside_changes({"a": 0, "b": 0}, {"a": 1, "b": 5}, current) == {
        "a": 0,
        "b": 2,
    }


def test_revert_plan_keeps_what_the_user_changed() -> None:
    original = {"a": 0, "b": 0, "c": 7}
    applied = {"a": 1, "b": 1, "c": 7}
    assert tb.revert_plan(original, applied, {"a": 1, "b": 9, "c": 7}) == {"a": 0}
    assert tb.revert_plan(original, None, {"a": 1, "b": 9, "c": 7}) == {"a": 0, "b": 0}


def test_labels_name_each_setting_once() -> None:
    assert set(tb.LABELS.values()) | {tb.AUTO_HIDE_LABEL} == set(tb._LABEL_ORDER)  # pyright: ignore[reportPrivateUsage]
    ids = ["\\".join(tb.PALETTE), "\\".join(tb.ACCENT_MENU), tb.AUTO_HIDE, "\\".join(tb.TASK_VIEW)]
    assert tb.labels(ids) == ["taskbar color", "Task view", "hide automatically"]


# ---- the service --------------------------------------------------------------------


def _wanted(service: TaskbarService, **changes: object) -> BarSpec:
    return replace(service.current(), **changes)  # type: ignore[arg-type]


def test_current_as_a_preview(service: TaskbarService) -> None:
    assert service.current() == BarSpec(
        color=None,
        transparency=False,
        centered=True,
        small=False,
        search=SearchMode.BOX,
        task_view=False,
        auto_hide=False,
        win11=True,
        light=False,
    )
    assert service.search_modes() == tuple(SearchMode)


def test_apply_then_revert_restores_everything(
    taskbar: FakeTaskbar, service: TaskbarService
) -> None:
    before = taskbar.state()
    wanted = _wanted(service, color=PINK, transparency=True, centered=False, auto_hide=True)
    changed = service.apply(wanted, CHOICE)
    assert changed == [
        "taskbar color",
        "frosted glass",
        "alignment",
        "hide automatically",
    ]
    assert service.current() == replace(wanted, light=False)
    assert service.is_changed
    assert service.applied_choice() == CHOICE

    assert service.revert() == changed
    assert taskbar.state() == before
    assert not service.is_changed
    assert service.applied_choice() is None
    assert service.revert() == []


def test_backup_survives_a_restart(taskbar: FakeTaskbar, tmp_path: Path) -> None:
    before = taskbar.state()
    first = taskbar.service(tmp_path / "taskbar.json")
    first.apply(_wanted(first, color=PINK), CHOICE)
    again = taskbar.service(tmp_path / "taskbar.json")
    assert again.applied_choice() == CHOICE
    again.revert()
    assert taskbar.state() == before


def test_applying_twice_keeps_the_first_original(
    taskbar: FakeTaskbar, service: TaskbarService
) -> None:
    before = taskbar.state()
    service.apply(_wanted(service, color=PINK), CHOICE)
    service.apply(_wanted(service, color=(40, 30, 90), small=True), TaskbarChoice("x", "deep"))
    assert service.applied_choice() == TaskbarChoice("x", "deep")
    service.revert()
    assert taskbar.state() == before


def test_revert_leaves_settings_the_user_changed_since(
    taskbar: FakeTaskbar, service: TaskbarService
) -> None:
    service.apply(_wanted(service, color=PINK, centered=False), CHOICE)
    taskbar.registry.values[tb.ALIGNMENT] = (tb.REG_DWORD, 1)  # the user, in Settings
    taskbar.registry.values[tb.SEARCH_MODE] = (tb.REG_DWORD, 0)
    service.revert()
    assert taskbar.registry.values[tb.ALIGNMENT] == (tb.REG_DWORD, 1)
    assert taskbar.registry.values[tb.SEARCH_MODE] == (tb.REG_DWORD, 0)
    assert taskbar.registry.values[tb.ACCENT_ON_TASKBAR] == (tb.REG_DWORD, 0)


def test_a_change_the_user_made_between_applies_is_theirs(
    taskbar: FakeTaskbar, service: TaskbarService
) -> None:
    service.apply(_wanted(service, color=PINK), CHOICE)
    taskbar.registry.values[tb.TASK_VIEW] = (tb.REG_DWORD, 1)  # the user turns Task view on
    service.apply(_wanted(service, small=True), CHOICE)
    service.revert()
    assert taskbar.registry.values[tb.TASK_VIEW] == (tb.REG_DWORD, 1)
    assert tb.SMALL_WIN11 not in taskbar.registry.values  # absent before, so absent again


def test_original_is_saved_before_anything_is_written(
    taskbar: FakeTaskbar, service: TaskbarService, tmp_path: Path
) -> None:
    before = taskbar.state()
    taskbar.registry.fail_after = 3  # a policy blocks a value part way through
    with pytest.raises(PermissionError):
        service.apply(_wanted(service, color=PINK, centered=False), CHOICE)
    saved = json.loads((tmp_path / "taskbar.json").read_text(encoding="utf-8"))
    assert saved["original"] is not None
    assert saved["applied"] is None

    taskbar.registry.fail_after = None
    reopened = taskbar.service(tmp_path / "taskbar.json")
    reopened.revert()
    assert taskbar.state() == before


def test_light_mode_is_switched_and_put_back(tmp_path: Path) -> None:
    taskbar = FakeTaskbar({**USER_TASKBAR, tb.LIGHT_MODE: (tb.REG_DWORD, 1)})
    service = taskbar.service(tmp_path / "taskbar.json")
    before = taskbar.state()
    wanted = _wanted(service, color=PINK)
    assert service.needs_dark_windows(wanted)
    assert not service.needs_dark_windows(_wanted(service, color=None))
    assert "Windows mode" in service.apply(wanted, CHOICE)
    assert taskbar.registry.values[tb.LIGHT_MODE] == (tb.REG_DWORD, 0)
    assert not service.needs_dark_windows(wanted)
    service.revert()
    assert taskbar.state() == before


def test_dry_run_changes_nothing(
    taskbar: FakeTaskbar, service: TaskbarService, tmp_path: Path
) -> None:
    before = taskbar.state()
    assert service.apply(_wanted(service, color=PINK), CHOICE, dry_run=True)
    assert taskbar.state() == before
    assert not (tmp_path / "taskbar.json").exists()
    service.apply(_wanted(service, color=PINK), CHOICE)
    applied = taskbar.state()
    assert service.revert(dry_run=True) == ["taskbar color"]
    assert taskbar.state() == applied
    assert service.is_changed


# ---- the backup file ------------------------------------------------------------------


def test_taskbar_backup_keeps_the_previous_version(tmp_path: Path) -> None:
    backup = TaskbarBackup(tmp_path / "taskbar.json")
    assert backup.original is None
    backup.save({"a": 1})
    backup.save({"a": 1}, {"a": 2}, {"theme": "t", "look": "soft"})
    previous = json.loads((tmp_path / "taskbar.json.prev").read_text(encoding="utf-8"))
    assert previous["applied"] is None
    reread = TaskbarBackup(tmp_path / "taskbar.json")
    assert (reread.original, reread.applied, reread.choice) == (
        {"a": 1},
        {"a": 2},
        {"theme": "t", "look": "soft"},
    )
    reread.forget()
    assert not (tmp_path / "taskbar.json").exists()
    assert not (tmp_path / "taskbar.json.prev").exists()


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"version": 2, "original": {}}',
        '{"version": 1, "original": null}',
        '{"version": 1, "original": {}, "applied": []}',
        "[]",
    ],
)
def test_damaged_taskbar_backup_is_refused_and_left_alone(tmp_path: Path, content: str) -> None:
    path = tmp_path / "taskbar.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BackupCorruptError, match="has not been changed"):
        TaskbarBackup(path)
    assert path.read_text(encoding="utf-8") == content


def test_missing_taskbar_backup_with_previous_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / "taskbar.json.prev").write_text('{"version": 1, "original": {}}', encoding="utf-8")
    with pytest.raises(BackupCorruptError, match="is missing"):
        TaskbarBackup(tmp_path / "taskbar.json")
