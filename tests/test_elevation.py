"""The elevated copy must refuse anything outside its narrow job, whatever the request says."""

import json
from pathlib import Path

import pytest

from app.elevation import RESULT_FILE, WindowsElevator, handle_request, read_result
from app.service import IconService
from platform_win.shortcuts import IconLocation
from tests.fakes import FakeDesktop


@pytest.fixture
def admin(env: FakeDesktop) -> IconService:
    """The service as the elevated copy builds it: no scan roots, same data folder."""
    return IconService(env.paths, env.link_io, roots=[])


def _request(env: FakeDesktop, action: str, items: list[dict[str, str | None]]) -> Path:
    path = env.paths.root / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"action": action, "items": items}), encoding="utf-8")
    return path


def _our_icon(env: FakeDesktop) -> Path:
    icon = env.paths.icons / "ours.ico"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(b"ico")
    return icon


def _skips(env: FakeDesktop) -> list[str]:
    return [why for _, why in read_result(env.paths.root / RESULT_FILE).skipped]


def test_applies_to_a_shared_shortcut(env: FakeDesktop, admin: IconService) -> None:
    lnk = env.make("Tool", folder=env.common)
    icon = _our_icon(env)
    request = _request(env, "apply", [{"shortcut": str(lnk), "icon": str(icon)}])
    assert handle_request(request, admin, [env.common]) == 0
    assert env.link_io.read(lnk).icon == IconLocation(str(icon), 0)
    assert read_result(env.paths.root / RESULT_FILE).changed == [lnk]


@pytest.mark.parametrize(
    ("where", "reason"),
    [
        ("desktop", "not a shortcut in a shared folder"),
        ("not_lnk", "not a shortcut in a shared folder"),
        ("missing", "shortcut not found"),
        ("foreign_icon", "icon is not one of Iconbloom's"),
        ("missing_icon", "icon file not found"),
    ],
)
def test_refuses_anything_outside_its_job(
    env: FakeDesktop, admin: IconService, tmp_path: Path, where: str, reason: str
) -> None:
    icon = _our_icon(env)
    shortcut = env.make("Tool", folder=env.common)
    if where == "desktop":
        shortcut = env.make("Mine")
    elif where == "not_lnk":
        shortcut = env.common / "notes.txt"
        shortcut.write_text("x", encoding="utf-8")
    elif where == "missing":
        shortcut = env.common / "Gone.lnk"
    elif where == "foreign_icon":
        icon = tmp_path / "elsewhere.ico"
        icon.write_bytes(b"ico")
    elif where == "missing_icon":
        icon = env.paths.icons / "never-made.ico"
    before = shortcut.read_bytes() if shortcut.exists() else None
    request = _request(env, "apply", [{"shortcut": str(shortcut), "icon": str(icon)}])
    assert handle_request(request, admin, [env.common]) == 0
    assert _skips(env) == [reason]
    if before is not None:
        assert shortcut.read_bytes() == before


def test_unknown_action_and_unreadable_request(env: FakeDesktop, admin: IconService) -> None:
    lnk = env.make("Tool", folder=env.common)
    request = _request(env, "delete", [{"shortcut": str(lnk), "icon": None}])
    assert handle_request(request, admin, [env.common]) == 0
    assert _skips(env) == ["unknown action"]
    request.write_text("{oops", encoding="utf-8")
    assert handle_request(request, admin, [env.common]) == 2


@pytest.mark.parametrize(
    "remote",
    [
        r"\\server\share\evil.ico",
        "//server/share/evil.ico",
        r"\\?\UNC\server\share\evil.ico",
        r"%LOGONSERVER%\share\evil.ico",
    ],
)
def test_revert_never_points_at_a_network_path(
    env: FakeDesktop, admin: IconService, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGONSERVER", r"\\DC1")
    lnk = env.make("Tool", folder=env.common, icon=remote)
    admin.apply_files([(lnk, _our_icon(env))])
    request = _request(env, "revert", [{"shortcut": str(lnk), "icon": None}])
    assert handle_request(request, admin, [env.common]) == 0
    assert _skips(env) == ["original icon is on a network path"]
    assert admin.is_ours(env.link_io.read(lnk).icon)


def test_helper_failure_is_reported(env: FakeDesktop) -> None:
    elevator = WindowsElevator(env.paths, launch=lambda arguments: 3)
    env.paths.ensure()
    with pytest.raises(OSError, match="exit code 3"):
        elevator("revert", [])
    assert not (env.paths.root / "elevated-request.json").exists()


def test_paths_are_compared_like_windows(env: FakeDesktop, admin: IconService) -> None:
    lnk = env.make("Tool", folder=env.common)
    shouty = Path(str(env.common).upper())
    request = _request(env, "apply", [{"shortcut": str(lnk), "icon": str(_our_icon(env))}])
    # Case and slash differences must not let anything slip past or block a real folder.
    assert handle_request(request, admin, [shouty]) == 0
    assert read_result(env.paths.root / RESULT_FILE).changed == [lnk]
