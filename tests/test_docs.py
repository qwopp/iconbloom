"""The docs people read first must not point at things that don't exist."""

import re
import shutil
import tomllib
from pathlib import Path

import pytest

from app import __version__
from engine.themes import LIBRARY, THEME_FILE, load_theme
from scripts.render_assets import render_theme

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
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


def test_theme_guide_example_loads(tmp_path: Path) -> None:
    """The theme.json in docs/THEMES.md is a working theme, decorations and all."""
    guide = (ROOT / "docs" / "THEMES.md").read_text(encoding="utf-8")
    example = re.search(r"```json\n(\{\n.*?\n\})\n```", guide, re.DOTALL)
    assert example is not None
    themes = tmp_path / "themes"
    shutil.copytree(ROOT / "themes" / LIBRARY, themes / LIBRARY)
    folder = themes / "my_theme"
    folder.mkdir()
    (folder / THEME_FILE).write_text(example.group(1), encoding="utf-8")
    render_theme(folder)
    theme = load_theme("my_theme", themes)
    assert [r.id for r in theme.recipes] == ["pastel_tint", "bubble_cream", "star_tile"]


def test_version_is_the_same_everywhere() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
