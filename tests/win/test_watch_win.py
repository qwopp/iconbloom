"""The sign-in copy's waiting, on real change notifications and named objects. Each test
uses names of its own, so a real Iconbloom keeping icons on this PC is never touched."""

import uuid
from pathlib import Path

from platform_win.watch import (
    Wake,
    WindowsFolderWatch,
    ask_keeper_to_stop,
    first_keeper,
)


def _name(what: str) -> str:
    return f"Local\\Iconbloom-test-{what}-{uuid.uuid4()}"


def test_a_new_shortcut_wakes_it_and_a_stop_ends_it(tmp_path: Path) -> None:
    folder = tmp_path / "Desktop" / "Games"
    folder.mkdir(parents=True)
    stop = _name("stop")
    watch = WindowsFolderWatch([tmp_path / "Desktop", tmp_path / "missing"], stop)
    assert watch.wait(0.2) is Wake.QUIET
    (folder / "Roblox Player.lnk").write_bytes(b"x")  # a folder inside counts too
    assert watch.wait(5) is Wake.CHANGED
    ask_keeper_to_stop(stop)
    assert watch.wait(5) is Wake.STOP


def test_stopping_with_none_running_is_fine() -> None:
    ask_keeper_to_stop(_name("stop"))


def test_one_keeper_at_a_time() -> None:
    name = _name("keeper")
    first = first_keeper(name)
    assert first is not None
    assert first_keeper(name) is None
