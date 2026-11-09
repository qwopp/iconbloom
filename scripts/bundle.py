"""The theme files the packaged app ships, shared by the PyInstaller spec and its test.

Only what the app reads at runtime goes in: each theme's theme.json and PNGs,
and the shared recipe library. SVG sources stay out.
"""

from pathlib import Path

from engine.themes import LIBRARY, LIBRARY_RECIPES, THEME_FILE


def theme_files(root: Path) -> list[tuple[Path, str]]:
    """(source file, destination folder in the bundle) for every runtime theme file."""
    themes = root / "themes"
    files = [(themes / LIBRARY / LIBRARY_RECIPES, f"themes/{LIBRARY}")]
    for theme in sorted(themes.iterdir()):
        if (theme / THEME_FILE).is_file():
            dest = f"themes/{theme.name}"
            files.append((theme / THEME_FILE, dest))
            files += [(png, dest) for png in sorted(theme.glob("*.png"))]
    return files
