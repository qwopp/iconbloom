import hashlib
import io
import tomllib
from pathlib import Path

import pytest

from app import __version__, updates
from app.settings import Settings
from app.updates import Release, UpdateError, Updater

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = b"pretend installer bytes" * 1000


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class FakeGitHub:
    """Serves a release, its checksum file and its installer by URL."""

    def __init__(self, checksums: str | None = None, installer: bytes = INSTALLER) -> None:
        digest = hashlib.sha256(installer).hexdigest()
        self.files = {
            updates.RELEASES_API: (
                b'{"tag_name": "v9.0.0", "html_url": "https://github.com/x/releases/v9.0.0", '
                b'"assets": [{"name": "Iconbloom-Setup-9.0.0.exe", '
                b'"browser_download_url": "https://dl/setup.exe"}, '
                b'{"name": "SHA256SUMS.txt", "browser_download_url": "https://dl/sums"}]}'
            ),
            "https://dl/sums": (
                checksums
                if checksums is not None
                else f"{digest}  Iconbloom-Setup-9.0.0.exe\n{'0' * 64}  other.zip\n"
            ).encode(),
            "https://dl/setup.exe": installer,
        }
        self.requested: list[str] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        url = getattr(request, "full_url", "")
        self.requested.append(url)
        return FakeResponse(self.files[url])


def test_version_matches_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__


@pytest.mark.parametrize(
    ("text", "parsed"),
    [("v1.2.3", (1, 2, 3)), ("0.1.0", (0, 1, 0)), ("v1.2", None), ("1.2.3-beta", None)],
)
def test_parse_version(text: str, parsed: tuple[int, int, int] | None) -> None:
    assert updates.parse_version(text) == parsed


@pytest.mark.parametrize(
    "payload",
    [
        {"tag_name": "v0.1.0", "html_url": "https://x"},
        {"tag_name": "v0.0.9", "html_url": "https://x"},
        {"tag_name": "nightly", "html_url": "https://x"},
        {"tag_name": 3},
        [],
    ],
)
def test_no_update_when_not_newer_or_malformed(payload: object) -> None:
    assert updates.newer_release(payload, current="0.1.0") is None


def test_check_finds_the_installer_and_checksums() -> None:
    release = Updater(FakeGitHub()).check()
    assert release == Release(
        "9.0.0",
        "https://github.com/x/releases/v9.0.0",
        installer_url="https://dl/setup.exe",
        checksums_url="https://dl/sums",
    )


def test_download_verifies_the_checksum(tmp_path: Path) -> None:
    github = FakeGitHub()
    updater = Updater(github)
    release = updater.check()
    assert release is not None
    seen: list[tuple[int, int]] = []
    installer = updater.download(release, tmp_path, lambda done, total: seen.append((done, total)))
    assert installer.read_bytes() == INSTALLER
    assert installer.name == "Iconbloom-Setup-9.0.0.exe"
    assert seen[-1] == (len(INSTALLER), len(INSTALLER))
    assert not list(tmp_path.glob("*.part"))


def test_tampered_download_is_deleted(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.files["https://dl/setup.exe"] = b"something else entirely"
    updater = Updater(github)
    release = updater.check()
    assert release is not None
    with pytest.raises(UpdateError, match="didn't match"):
        updater.download(release, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("release", "message"),
    [
        (Release("9.0.0", "https://x"), "no installer"),
        (
            Release("9.0.0", "https://x", "https://dl/setup.exe", "https://dl/sums"),
            "doesn't list its installer",
        ),
    ],
)
def test_download_refuses_without_a_checksum(
    tmp_path: Path, release: Release, message: str
) -> None:
    with pytest.raises(UpdateError, match=message):
        Updater(FakeGitHub(checksums="not a checksum file")).download(release, tmp_path)


def test_parse_checksums_accepts_binary_marker() -> None:
    digest = "A" * 64
    assert updates.parse_checksums(f"{digest} *Setup.exe\njunk line\n") == {
        "Setup.exe": digest.lower()
    }


def test_launch_starts_installer_silently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(updates.subprocess, "Popen", started.append)
    Updater().launch(tmp_path / "Setup.exe")
    assert started == [[str(tmp_path / "Setup.exe"), *updates.INSTALLER_ARGS]]


def test_update_checks_default_on(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "settings.json").check_for_updates


def test_switching_off_is_remembered(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    Settings(check_for_updates=False, update_check_chosen=True).save(path)
    assert not Settings.load(path).check_for_updates


@pytest.mark.parametrize(
    ("saved", "checks"),
    [
        # 0.2/0.3 saved "off" before the user answered; that was never a choice.
        ('{"check_for_updates": false, "asked_about_updates": false}', True),
        ('{"check_for_updates": false, "shared_shortcuts": "include"}', True),
        # They answered "No thanks" (or unticked the box): keep it off.
        ('{"check_for_updates": false, "asked_about_updates": true}', False),
        ('{"check_for_updates": true, "asked_about_updates": true}', True),
    ],
)
def test_settings_from_earlier_versions(tmp_path: Path, saved: str, checks: bool) -> None:
    path = tmp_path / "settings.json"
    path.write_text(saved, encoding="utf-8")
    assert Settings.load(path).check_for_updates is checks


def test_settings_ignore_junk(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"shared_shortcuts": "skip", "mystery": 1}', encoding="utf-8")
    assert Settings.load(path).shared_shortcuts == "skip"
    path.write_text("not json", encoding="utf-8")
    assert Settings.load(path) == Settings()
    path.write_text("[1, 2]", encoding="utf-8")
    assert Settings.load(path) == Settings()


class DroppingResponse(FakeResponse):
    """A connection that breaks partway through the installer."""

    def read(self, size: int | None = -1) -> bytes:
        if self.tell() > 1000:
            raise ConnectionResetError("connection reset by peer")
        return super().read(1000)


def test_a_broken_download_leaves_nothing_behind(tmp_path: Path) -> None:
    github = FakeGitHub()
    updater = Updater(github)
    release = updater.check()
    assert release is not None
    real = github.__call__

    def opener(request: object, timeout: float) -> FakeResponse:
        response = real(request, timeout)
        if getattr(request, "full_url", "") == "https://dl/setup.exe":
            return DroppingResponse(response.getvalue())
        return response

    with pytest.raises(ConnectionResetError):
        Updater(opener).download(release, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelling_stops_and_cleans_up(tmp_path: Path) -> None:
    updater = Updater(FakeGitHub())
    release = updater.check()
    assert release is not None
    seen: list[int] = []

    def progress(done: int, total: int) -> bool:
        seen.append(done)
        return False

    with pytest.raises(updates.UpdateCancelledError):
        updater.download(release, tmp_path, progress)
    assert len(seen) == 1
    assert list(tmp_path.iterdir()) == []


def test_old_installers_are_removed(tmp_path: Path) -> None:
    (tmp_path / "Iconbloom-Setup-0.1.0.exe").write_bytes(b"old")
    (tmp_path / "Iconbloom-Setup-0.2.0.exe.part").write_bytes(b"half")
    updater = Updater(FakeGitHub())
    release = updater.check()
    assert release is not None
    installer = updater.download(release, tmp_path)
    assert list(tmp_path.iterdir()) == [installer]
