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

    def with_image(self, image_name: str) -> "Choice":
        """This style, drawn from the user's own image instead of the app's icon."""
        return Choice(self.theme, self.recipe, self.seed, custom_image=image_name)

    @property
    def is_custom(self) -> bool:
        return self.custom_image is not None

    @property
    def file_tag(self) -> str:
        """Part of the generated .ico name; differs whenever the picture would."""
        style = f"{self.theme}_{self.recipe}" + (f"_s{self.seed}" if self.seed else "")
        if self.custom_image is None:
            return style
        image = f"{CUSTOM_RECIPE}_{Path(self.custom_image).stem}"
        return image if self.recipe == CUSTOM_RECIPE else f"{image}_{style}"


class ChoiceStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._choices: dict[str, Choice] = {}
        self._skipped: set[str] = set()
        self._load()

    def get(self, key: str) -> Choice | None:
        return self._choices.get(key)

    def items(self) -> list[tuple[str, Choice]]:
        return list(self._choices.items())

    def set(self, key: str, choice: Choice) -> None:
        self._choices[key] = choice
        self._skipped.discard(key)
        self._save()

    def clear(self, key: str) -> None:
        if self._choices.pop(key, None) is not None or key in self._skipped:
            self._skipped.discard(key)
            self._save()

    def clear_all(self) -> None:
        self._choices.clear()
        self._skipped.clear()
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
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # Losing choices only means "Reapply" forgets them; never block the app.
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            aside = self._path.with_name(f"{self._path.name}.unreadable-{stamp}")
            self._path.replace(aside)
            log.warning("could not read %s (%s); moved it to %s", self._path, exc, aside.name)
            self._choices, self._skipped = {}, set()

    def _save(self) -> None:
        payload = {
            "version": CHOICES_VERSION,
            "choices": {k: asdict(v) for k, v in self._choices.items()},
            "skipped": sorted(self._skipped),
        }
        write_json(self._path, payload)
