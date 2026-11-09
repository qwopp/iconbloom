"""Opt-in check for a newer release on GitHub. Never downloads anything."""

import json
import re
import urllib.request
from dataclasses import dataclass

from app import __version__

RELEASES_API = "https://api.github.com/repos/qwopp/iconbloom/releases/latest"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Release:
    version: str
    url: str


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
    return Release(tag.lstrip("v"), url)


def check(timeout: float = 5.0) -> Release | None:
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Iconbloom"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return newer_release(json.load(response))
