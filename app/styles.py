"""Styles: loading themes, rendering a choice, and the icon files that come out of it.

Nothing here changes a shortcut; ``IconService`` decides what to change and
uses these files.
"""

import hashlib
import io
from collections.abc import Mapping
from pathlib import Path

from PIL import Image, ImageOps

from app.choices import Choice
from engine import ops
from engine.ico import build_ico
from engine.recipes import RENDER_VERSION, render
from engine.themes import THEMES_DIR, Theme, list_themes, load_theme, theme_name
from platform_win.fileio import atomic_write
from platform_win.paths import AppPaths
from platform_win.shortcuts import normalize_path, variant_path


class Styles:
    def __init__(self, paths: AppPaths, themes_dir: Path = THEMES_DIR) -> None:
        self._paths = paths
        self._themes_dir = themes_dir
        self._themes: dict[str, Theme] = {}
        # Prepared own images by file name; names are content hashes, so never stale.
        self._sources: dict[str, Image.Image] = {}

    def theme_names(self) -> list[tuple[str, str]]:
        """(id, display name) of every installed theme, without loading them."""
        return [(t, theme_name(t, self._themes_dir)) for t in list_themes(self._themes_dir)]

    def theme(self, theme_id: str) -> Theme:
        """A loaded theme, read from disk once per session."""
        if theme_id not in self._themes:
            self._themes[theme_id] = load_theme(theme_id, self._themes_dir)
        return self._themes[theme_id]

    def render(
        self, choice: Choice, prepared: Image.Image | None = None
    ) -> tuple[Image.Image, Image.Image]:
        """Full and simplified renders for a choice.

        Theme choices need ``prepared``, the original icon after ``ops.prepare``;
        a choice with the user's own image draws from that image instead.
        """
        if choice.custom_image is not None:
            prepared = self.custom_source(choice.custom_image)
            if choice.as_is:
                own = ops.fit_output(prepared)
                return own, own
        if prepared is None:
            raise ValueError(f"rendering {choice.file_tag} needs the original icon")
        theme = self.theme(choice.theme)
        recipe = theme.recipe(choice.recipe)
        return (
            render(recipe, prepared, theme, seed=choice.seed),
            render(recipe, prepared, theme, seed=choice.seed, simplified=True),
        )

    def custom_source(self, image_name: str) -> Image.Image:
        """The user's stored image, prepared like an app's icon so any style applies."""
        if image_name not in self._sources:
            with Image.open(self._paths.custom_images / image_name) as img:
                self._sources[image_name], _ = ops.prepare(_upright(img))
        return self._sources[image_name]

    def store_custom_image(self, source: Path) -> Choice:
        """Copy a user-picked image into app data and return the choice that uses it."""
        with Image.open(source) as img:
            ops.prepare(_upright(img))  # raises on an unusable image before anything is stored
        data = source.read_bytes()
        name = f"{hashlib.sha256(data).hexdigest()[:12]}{source.suffix.casefold()}"
        destination = self._paths.custom_images / name
        if not destination.exists():
            atomic_write(destination, data)
        return Choice.custom(name)

    def icon_path(self, slug: str, choice: Choice) -> Path:
        # The render version is in the name: a redrawn icon at the old path would keep
        # showing the old picture from Windows' icon cache.
        return self._paths.icons / f"{slug}_{choice.file_tag}-r{RENDER_VERSION}.ico"

    def write_icon(
        self,
        slug: str,
        choice: Choice,
        prepared: Image.Image | None,
        variants: Mapping[str, Image.Image | None] | None = None,
    ) -> Path:
        """Render ``choice`` into the item's .ico, plus one .ico per variant original."""
        icon_file = self.icon_path(slug, choice)
        atomic_write(icon_file, build_ico(*self.render(choice, prepared)))
        for name, variant in (variants or {}).items():
            atomic_write(variant_path(icon_file, name), build_ico(*self.render(choice, variant)))
        return icon_file

    def unused_icons(self, in_use: set[str]) -> list[Path]:
        """Generated icons nothing points at; a variant counts as used with its main icon."""
        unused: list[Path] = []
        for path in sorted(self._paths.icons.glob("*.ico")):
            main = path.with_name(path.name.split(".", 1)[0] + path.suffix)
            if normalize_path(str(main)) not in in_use:
                unused.append(path)
        return unused

    def save_original(self, slug: str, prepared: Image.Image) -> None:
        """Keep a picture of an item's own icon; Windows reports ours once it's styled."""
        buffer = io.BytesIO()
        prepared.save(buffer, format="PNG")
        atomic_write(self._original_path(slug), buffer.getvalue())

    def saved_original(self, slug: str) -> Image.Image | None:
        path = self._original_path(slug)
        if not path.is_file():
            return None
        with Image.open(path) as img:
            return img.convert("RGBA")

    def _original_path(self, slug: str) -> Path:
        return self._paths.original_icons / f"{slug}.png"


def _upright(img: Image.Image) -> Image.Image:
    """Phone photos are stored sideways with a note saying how to turn them."""
    return ImageOps.exif_transpose(img) or img
