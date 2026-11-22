"""Keeping icons fixed while signed in: a pass now, then one after each burst of changes."""

from collections.abc import Iterable

import pytest

from app import keeper
from app.keeper import keep_icons
from platform_win.backup import BackupCorruptError
from platform_win.watch import Wake
from tests.fakes import FakeClock, ScriptedWatch


def _run(
    wakes: Iterable[Wake], still_on: bool = True, after_pass: Iterable[Wake] = ()
) -> tuple[int, ScriptedWatch]:
    clock = FakeClock()
    watch = ScriptedWatch(wakes, clock, after_pass)
    passes = 0

    def fix() -> None:
        nonlocal passes
        passes += 1

    keep_icons(fix, watch, lambda: still_on, clock)
    return passes, watch


def test_a_pass_at_once_then_one_per_burst_of_changes() -> None:
    passes, watch = _run([Wake.CHANGED, Wake.CHANGED, Wake.QUIET, Wake.CHANGED, Wake.QUIET])
    assert passes == 3
    # Asleep until a change; then short waits until the folders go quiet.
    assert watch.waits[0] == keeper.CHECK_EVERY_SECONDS
    assert watch.waits[1:3] == [keeper.SETTLE_SECONDS] * 2


def test_an_hourly_pass_even_without_changes() -> None:
    passes, _ = _run([Wake.QUIET, Wake.QUIET])
    assert passes == 3


def test_endless_changes_still_get_a_pass() -> None:
    # A change every second for 1000 s: a pass at least every two minutes of it.
    passes, _ = _run([Wake.CHANGED] * 1000)
    assert passes >= 1 + 1000 // (keeper.MOST_SETTLING_SECONDS + 1)


def test_a_stop_while_settling_ends_it_without_a_pass() -> None:
    passes, _ = _run([Wake.CHANGED, Wake.STOP])
    assert passes == 1


def test_switched_off_in_windows_ends_it() -> None:
    passes, watch = _run([Wake.CHANGED], still_on=False)
    assert passes == 1
    assert watch.waits == []


def test_a_failing_pass_is_logged_and_the_next_change_tries_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def fix() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("shortcut locked")

    clock = FakeClock()
    keep_icons(fix, ScriptedWatch([Wake.QUIET], clock), lambda: True, clock)
    assert calls == 2
    assert "trying again" in caplog.text


def test_a_damaged_backup_ends_it() -> None:
    def fix() -> None:
        raise BackupCorruptError("backup.json is damaged")

    clock = FakeClock()
    with pytest.raises(BackupCorruptError):
        keep_icons(fix, ScriptedWatch([Wake.QUIET], clock), lambda: True, clock)


def test_the_changes_a_pass_made_itself_bring_on_no_other() -> None:
    passes, watch = _run([Wake.QUIET], after_pass=[Wake.CHANGED, Wake.CHANGED])
    assert passes == 2
    assert watch.waits == [keeper.CHECK_EVERY_SECONDS, keeper.CHECK_EVERY_SECONDS]


def test_a_stop_among_a_pass_own_changes_ends_it() -> None:
    passes, _ = _run([Wake.QUIET], after_pass=[Wake.CHANGED, Wake.STOP])
    assert passes == 1
