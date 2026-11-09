"""The docs people read first must not point at things that don't exist."""

import re
from pathlib import Path

import pytest

from engine.themes import list_themes

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    *ROOT.glob("docs/*.md"),
]
LINK = re.compile(r"\]\(([^)#\s]+)")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_local_links_and_images_exist(doc: Path) -> None:
    missing = [
        target
        for target in LINK.findall(doc.read_text(encoding="utf-8"))
        if not target.startswith(("http://", "https://")) and not (doc.parent / target).exists()
    ]
    assert missing == []


def test_readme_needs_no_edit_per_release() -> None:
    """Version numbers in the README go stale; it links to the latest release instead."""
    assert not re.search(r"\b\d+\.\d+\.\d+\b", (ROOT / "README.md").read_text(encoding="utf-8"))


README_MAX_LINES = 40


def test_readme_stays_short() -> None:
    """The README is a front page: pictures, download, FAQ. Details live in docs/."""
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= README_MAX_LINES


def test_readme_shows_every_theme() -> None:
    """The showcase image has a row per bundled theme; its alt text says so."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"each of the {_NUMBER_WORDS[len(list_themes())]} themes" in readme


_NUMBER_WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
