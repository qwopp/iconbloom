"""Which style the user picked for each app, kept so icons can be reapplied.

App updates often rewrite their shortcuts and drop the custom icon. Choices
are keyed by what the shortcut launches, not by its file, so they still match
after the shortcut is recreated.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from engine.recipes import RENDER_VERSION
from platform_win.fileio import write_json

log = logging.getLogger(__name__)

CHOICES_VERSION = 1
CUSTOM_RECIPE = "custom"


@dataclass(frozen=True)
class Choice:
    theme: str
    recipe: str
    seed: int = 0
    # The user's own image, a file name under AppPaths.custom_images, styled in place
    # of the app's icon. With the "custom" recipe it's used exactly as it is.
    custom_image: str | None = None

    @classmethod
    def custom(cls, image_name: str) -> "Choice":
        """A choice that uses the user's own image as it is."""
        return cls(theme="", recipe=CUSTOM_RECIPE, custom_image=image_name)

    @property
    def uses_own_image(self) -> bool:
        """Drawn from the user's own image rather than the app's icon."""
        return self.custom_image is not None

    @property
    def as_is(self) -> bool:
        """The user's own image exactly as it is, no style."""
        return self.recipe == CUSTOM_RECIPE

    @property
    def file_tag(self) -> str:
        """Part of the generated .ico name; differs whenever the picture would."""
        # "-" never appears in an id (a-z, 0-9 and _ only), so no two looks share a tag.
        style = f"{self.theme}-{self.recipe}" + (f"-s{self.seed}" if self.seed else "")
        if self.custom_image is None:
            return style
        image = f"{CUSTOM_RECIPE}-{Path(self.custom_image).stem}"
        return image if self.as_is else f"{image}-{style}"


class ChoiceStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._choices: dict[str, Choice] = {}
        self._skipped: set[str] = set()
        # The user's own image per app, shown in the picker until they go back to the
        # app's icon. Kept apart from choices so a revert doesn't forget it.
        self._images: dict[str, str] = {}
        # Which RENDER_VERSION drew each app's icon; files from before this was kept say 1.
        self._drawn: dict[str, int] = {}
        self._load()

    def get(self, key: str) -> Choice | None:
        return self._choices.get(key)

    def items(self) -> list[tuple[str, Choice]]:
        return list(self._choices.items())

    def set(self, key: str, choice: Choice) -> None:
        self._choices[key] = choice
        self._drawn[key] = RENDER_VERSION
        self._skipped.discard(key)
        self._save()

    def drawn_with(self, key: str) -> int:
        """The RENDER_VERSION that drew this app's current icon."""
        return self._drawn.get(key, 1)

    def clear(self, key: str) -> None:
        if self._choices.pop(key, None) is not None or key in self._skipped:
            self._skipped.discard(key)
            self._save()

    def clear_all(self) -> None:
        self._choices.clear()
        self._skipped.clear()
        self._save()

    def image(self, key: str) -> str | None:
        return self._images.get(key)

    def set_image(self, key: str, image_name: str | None) -> None:
        """Remember ``key``'s own image; None forgets it."""
        if self._images.get(key) == image_name:
            return
        if image_name is None:
            del self._images[key]
        else:
            self._images[key] = image_name
        self._save()

    def is_skipped(self, key: str) -> bool:
        return key in self._skipped

    def skip(self, key: str) -> None:
        self._skipped.add(key)
        self._save()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if raw.get("version") != CHOICES_VERSION:
                raise ValueError("unknown version")
            self._choices = {k: Choice(**v) for k, v in raw["choices"].items()}
            self._skipped = set(raw["skipped"])
            self._drawn = {str(k): int(v) for k, v in raw.get("drawn", {}).items()}
            if "images" in raw:
                self._images = {str(k): str(v) for k, v in raw["images"].items()}
            else:
                # Older files only had applied choices; their own images carry over.
                self._images = {
                    k: c.custom_image for k, c in self._choices.items() if c.custom_image
                }
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # Losing choices only means "Reapply" forgets them; never block the app.
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            aside = self._path.with_name(f"{self._path.name}.unreadable-{stamp}")
            self._path.replace(aside)
            log.warning("could not read %s (%s); moved it to %s", self._path, exc, aside.name)
            self._choices, self._skipped, self._images, self._drawn = {}, set(), {}, {}

    def _save(self) -> None:
        payload = {
            "version": CHOICES_VERSION,
            "choices": {k: asdict(v) for k, v in self._choices.items()},
            "skipped": sorted(self._skipped),
            "images": self._images,
            "drawn": {k: v for k, v in self._drawn.items() if k in self._choices},
        }
        write_json(self._path, payload)
