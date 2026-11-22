"""Keeping icons fixed while signed in: a pass now, then one after each burst of changes."""

from collections.abc import Iterable

import pytest

from app import keeper
from app.keeper import keep_icons
from platform_win.backup import BackupCorruptError
from platform_win.watch import Wake


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class ScriptedWatch:
    """Answers each wait with the next scripted wake (STOP once it runs out), moving the
    clock on by the time each wait took: all of it unless something changed."""

    def __init__(self, clock: FakeClock, wakes: Iterable[Wake]) -> None:
        self._clock = clock
        self._wakes = list(wakes)
        self.waits: list[float] = []

    def wait(self, seconds: float) -> Wake:
        self.waits.append(seconds)
        wake = self._wakes.pop(0) if self._wakes else Wake.STOP
        self._clock.now += 1.0 if wake is Wake.CHANGED else seconds
        return wake


def _run(wakes: Iterable[Wake], still_on: bool = True) -> tuple[int, ScriptedWatch]:
    clock = FakeClock()
    watch = ScriptedWatch(clock, wakes)
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
    keep_icons(fix, ScriptedWatch(clock, [Wake.QUIET]), lambda: True, clock)
    assert calls == 2
    assert "trying again" in caplog.text


def test_a_damaged_backup_ends_it() -> None:
    def fix() -> None:
        raise BackupCorruptError("backup.json is damaged")

    clock = FakeClock()
    with pytest.raises(BackupCorruptError):
        keep_icons(fix, ScriptedWatch(clock, [Wake.QUIET]), lambda: True, clock)
