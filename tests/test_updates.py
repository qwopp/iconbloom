import io
import json
import tomllib
from pathlib import Path

import pytest

from app import __version__, updates
from app.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__


@pytest.mark.parametrize(
    ("text", "parsed"),
    [("v1.2.3", (1, 2, 3)), ("0.1.0", (0, 1, 0)), ("v1.2", None), ("1.2.3-beta", None)],
)
def test_parse_version(text: str, parsed: tuple[int, int, int] | None) -> None:
    assert updates.parse_version(text) == parsed


def _payload(tag: str) -> dict[str, str]:
    return {"tag_name": tag, "html_url": f"https://github.com/qwopp/iconbloom/releases/{tag}"}


def test_newer_release_found() -> None:
    release = updates.newer_release(_payload("v0.2.0"), current="0.1.0")
    assert release == updates.Release("0.2.0", _payload("v0.2.0")["html_url"])


@pytest.mark.parametrize(
    "payload",
    [_payload("v0.1.0"), _payload("v0.0.9"), _payload("nightly"), {"tag_name": 3}, []],
)
def test_no_update_when_not_newer_or_malformed(payload: object) -> None:
    assert updates.newer_release(payload, current="0.1.0") is None


def test_check_reads_github_api(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_urlopen(request: object, timeout: float) -> io.BytesIO:
        seen.append(getattr(request, "full_url", ""))
        return io.BytesIO(json.dumps(_payload("v99.0.0")).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    release = updates.check()
    assert release is not None
    assert release.version == "99.0.0"
    assert seen == [updates.RELEASES_API]


def test_settings_default_off_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert not Settings.load(path).check_for_updates
    Settings(check_for_updates=True).save(path)
    assert Settings.load(path).check_for_updates


def test_settings_ignore_junk(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"check_for_updates": true, "mystery": 1}', encoding="utf-8")
    assert Settings.load(path).check_for_updates
    path.write_text("not json", encoding="utf-8")
    assert not Settings.load(path).check_for_updates
    path.write_text("[1, 2]", encoding="utf-8")
    assert not Settings.load(path).check_for_updates
