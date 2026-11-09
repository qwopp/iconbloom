"""Find, download and start newer releases from GitHub, only after the user agreed.

Iconbloom asks before its first check. When a newer release exists, the user
clicks Update; only then is the installer downloaded, and it only runs if its
SHA-256 matches the checksum file published with the same release.
"""

import hashlib
import json
import re
import subprocess
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import __version__

RELEASES_API = "https://api.github.com/repos/qwopp/iconbloom/releases/latest"
CHECKSUMS_ASSET = "SHA256SUMS.txt"
# Silent: shows progress but asks nothing; the installer reopens Iconbloom when done.
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_CHUNK = 256 * 1024

type Progress = Callable[[int, int], None]


class UpdateError(Exception):
    """The update could not be downloaded or didn't match its published checksum."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    # Direct download links; missing if the release has no installer for some reason.
    installer_url: str | None = None
    checksums_url: str | None = None

    @property
    def installer_name(self) -> str:
        return f"Iconbloom-Setup-{self.version}.exe"


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(text.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def newer_release(payload: object, current: str = __version__) -> Release | None:
    """The release described by a GitHub API response, if it beats ``current``."""
    if not isinstance(payload, dict):
        return None
    tag, url = payload.get("tag_name"), payload.get("html_url")
    if not isinstance(tag, str) or not isinstance(url, str):
        return None
    latest, mine = parse_version(tag), parse_version(current)
    if latest is None or mine is None or latest <= mine:
        return None
    version = tag.lstrip("v")
    assets = _asset_links(payload.get("assets"))
    return Release(
        version,
        url,
        installer_url=assets.get(f"Iconbloom-Setup-{version}.exe"),
        checksums_url=assets.get(CHECKSUMS_ASSET),
    )


def parse_checksums(text: str) -> dict[str, str]:
    """``sha256sum``-style lines ("<hash>  <file name>") as {file name: hash}."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


class Updater:
    """Talks to GitHub. Every method is a deliberate user action; nothing runs on its own."""

    # ``opener`` is urlopen, or a stand-in returning anything with read() and headers.
    def __init__(self, opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self._open = opener

    def check(self, timeout: float = 5.0) -> Release | None:
        with self._get(RELEASES_API, timeout) as response:
            return newer_release(json.load(response))

    def download(self, release: Release, folder: Path, progress: Progress | None = None) -> Path:
        """Download the installer and verify it; returns its path."""
        if release.installer_url is None or release.checksums_url is None:
            raise UpdateError("this release has no installer to download; see its web page")
        with self._get(release.checksums_url, 30) as response:
            expected = parse_checksums(response.read().decode("ascii", "replace"))
        want = expected.get(release.installer_name)
        if want is None:
            raise UpdateError("the release's checksum file doesn't list its installer")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / release.installer_name
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        with self._get(release.installer_url, 60) as response, partial.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(_CHUNK):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        if digest.hexdigest() != want:
            partial.unlink(missing_ok=True)
            raise UpdateError("the download didn't match its published checksum, so it was deleted")
        partial.replace(target)
        return target

    def launch(self, installer: Path) -> None:
        """Start the installer, detached: it waits for Iconbloom to close, then upgrades it."""
        subprocess.Popen([str(installer), *INSTALLER_ARGS])

    def _get(self, url: str, timeout: float) -> Any:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Iconbloom"}
        )
        return self._open(request, timeout=timeout)


def _asset_links(assets: object) -> Mapping[str, str]:
    links: dict[str, str] = {}
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict):
                name, link = asset.get("name"), asset.get("browser_download_url")
                if isinstance(name, str) and isinstance(link, str) and link.startswith("https://"):
                    links[name] = link
    return links
