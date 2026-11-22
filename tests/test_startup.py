"""Running at sign-in: one value in the user's Run key, and Revert all removes it."""

import subprocess
import sys

import pytest

from app.choices import Choice
from platform_win import startup, watch
from platform_win.startup import (
    FIX_ICONS_FLAG,
    RUN_KEY,
    STARTUP_APPROVED_KEY,
    VALUE_NAME,
    SignInRun,
)
from platform_win.taskbar import REG_BINARY
from tests.fakes import FakeDesktop, FakeUserRegistry

# How Settings > Apps > Startup records an entry it switched off: 3, then a timestamp.
SWITCHED_OFF = (REG_BINARY, bytes([3, 0, 0, 0]) + bytes(8))
SWITCHED_ON = (REG_BINARY, bytes([2, 0, 0, 0]) + bytes(8))


def _none() -> None:
    pass


def test_switching_on_and_off_writes_one_run_value() -> None:
    registry = FakeUserRegistry()
    sign_in = SignInRun(
        registry, rf'"C:\Iconbloom\Iconbloom.exe" {FIX_ICONS_FLAG}', start=_none, stop=_none
    )
    assert not sign_in.is_on()
    sign_in.set(True)
    assert sign_in.is_on()
    assert registry.values == {
        (RUN_KEY, VALUE_NAME): (1, r'"C:\Iconbloom\Iconbloom.exe" --fix-icons')
    }
    sign_in.set(False)
    sign_in.set(False)  # already off is fine
    assert registry.values == {}


def test_only_the_built_app_offers_it(monkeypatch: pytest.MonkeyPatch) -> None:
    assert startup.windows_sign_in_run() is None  # running from source: no exe to start

    exe = r"C:\Users\Ana Lee\AppData\Local\Programs\Iconbloom\Iconbloom.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    registry = FakeUserRegistry()
    monkeypatch.setattr(startup, "WindowsUserRegistry", lambda: registry)
    started: list[list[str]] = []
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(startup.subprocess, "Popen", lambda args, **_: started.append(args))
    monkeypatch.setattr(watch, "is_running", lambda: False)
    sign_in = startup.windows_sign_in_run()
    assert sign_in is not None
    sign_in.set(True)
    # Quoted, so a path with spaces starts the app rather than "C:\Users\Ana".
    assert registry.values[(RUN_KEY, VALUE_NAME)] == (1, f'"{exe}" --fix-icons')
    assert started == [[exe, "--fix-icons"]]  # keeping icons from now, not next sign-in


def test_revert_all_stops_the_sign_in_run(env: FakeDesktop) -> None:
    env.make("Paint")
    service = env.service()
    service.apply(service.scan()[0], Choice("kawaii_pink", "sticker"))
    env.sign_in.set(True)
    service.revert_all(dry_run=True)
    assert env.sign_in.is_on()
    service.revert_all()
    assert not env.sign_in.is_on()
    assert env.keeper_stops == 1


def test_switched_off_in_windows_startup_apps_reads_off_until_ticked_again() -> None:
    registry = FakeUserRegistry()
    starts: list[str] = []
    sign_in = SignInRun(registry, "cmd", start=lambda: starts.append("start"), stop=_none)
    sign_in.set(True)
    registry.write(STARTUP_APPROVED_KEY, VALUE_NAME, SWITCHED_OFF)
    assert not sign_in.is_on()
    sign_in.run_now()
    assert starts == ["start"]  # only the one from switching it on

    sign_in.set(True)
    assert sign_in.is_on()
    assert registry.read(STARTUP_APPROVED_KEY, VALUE_NAME) is None
    registry.write(STARTUP_APPROVED_KEY, VALUE_NAME, SWITCHED_ON)
    assert sign_in.is_on()
    sign_in.run_now()
    assert starts == ["start"] * 3


def test_switching_off_stops_the_running_copy() -> None:
    registry = FakeUserRegistry()
    stops: list[str] = []
    sign_in = SignInRun(registry, "cmd", start=_none, stop=lambda: stops.append("stop"))
    sign_in.set(True)
    registry.write(STARTUP_APPROVED_KEY, VALUE_NAME, SWITCHED_OFF)
    sign_in.set(False)
    assert stops == ["stop"]
    assert registry.values == {}
