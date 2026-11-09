"""Where Iconbloom keeps its own files, and where Windows keeps shortcuts."""

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Iconbloom"


@dataclass(frozen=True)
class AppPaths:
    """Per-user data folder layout, normally %LOCALAPPDATA%\\Iconbloom."""

    root: Path

    @property
    def icons(self) -> Path:
        """Generated .ico files that shortcuts point at."""
        return self.root / "icons"

    @property
    def originals(self) -> Path:
        """Byte-for-byte copies of each shortcut before its first change."""
        return self.root / "originals"

    @property
    def custom_images(self) -> Path:
        """Images the user picked with "Use my own image", kept for reapplying."""
        return self.root / "custom"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def manifest(self) -> Path:
        return self.root / "backup.json"

    @property
    def choices(self) -> Path:
        return self.root / "choices.json"

    @property
    def settings(self) -> Path:
        return self.root / "settings.json"

    def ensure(self) -> "AppPaths":
        for folder in (self.icons, self.originals, self.custom_images, self.logs):
            folder.mkdir(parents=True, exist_ok=True)
        return self


def default_app_paths() -> AppPaths:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return AppPaths(Path(base) / APP_NAME)


def known_folder(name: str) -> Path:
    """Resolve a shell known folder, e.g. "Desktop", honoring OneDrive redirection.

    ``name`` is the suffix of a ``FOLDERID_*`` constant in ``win32com.shell.shellcon``.
    """
    from win32com.shell import shell, shellcon

    folder_id = getattr(shellcon, f"FOLDERID_{name}")
    return Path(shell.SHGetKnownFolderPath(folder_id, 0, None))
