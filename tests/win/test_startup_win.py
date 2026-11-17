"""The sign-in entry in the real Run key, under a throwaway name so the user's own
"Iconbloom" entry is never touched."""

import uuid
from collections.abc import Iterator

import pytest

from platform_win.startup import RUN_KEY, SignInRun
from platform_win.taskbar import REG_SZ, WindowsUserRegistry


@pytest.fixture
def name() -> Iterator[str]:
    name = f"Iconbloom-test-{uuid.uuid4()}"
    yield name
    WindowsUserRegistry().delete(RUN_KEY, name)


def test_switching_on_and_off_in_the_real_run_key(name: str) -> None:
    registry = WindowsUserRegistry()
    command = r'"C:\Iconbloom\Iconbloom.exe" --fix-icons'
    sign_in = SignInRun(registry, command, name)
    assert not sign_in.is_on()
    sign_in.set(True)
    assert sign_in.is_on()
    assert registry.read(RUN_KEY, name) == (REG_SZ, command)
    sign_in.set(False)
    assert not sign_in.is_on()
    sign_in.set(False)  # already off is fine
