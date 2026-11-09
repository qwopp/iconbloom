"""The backup manifest: how to put every changed shortcut back exactly as it was.

Rules this module enforces:

* A shortcut's original state is recorded, and the manifest saved to disk,
  before the shortcut is touched. A crash at any later point loses nothing.
* A recorded original is never replaced by a themed state.
* The manifest is replaced atomically, and the previous version is kept as
  ``backup.json.prev``.
* A manifest that can't be read is reported and left untouched; nothing that
  changes shortcuts runs until a person looks at it.

Nothing here calls Windows APIs, so all of it is tested on every OS.
"""

import hashlib
import json
import shutil
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from platform_win.fileio import atomic_write, write_json
from platform_win.shortcuts import IconLocation, normalize_path

MANIFEST_VERSION = 1


class BackupCorruptError(Exception):
    """backup.json exists but can't be trusted. It is left exactly as found."""


@dataclass(frozen=True)
class BackupEntry:
    shortcut: str
    original_icon_path: str
    original_icon_index: int
    original_sha256: str
    # File name of the byte-for-byte copy under AppPaths.originals.
    original_copy: str
    recorded_at: str
    # Filled in once the themed icon is saved into the shortcut.
    applied_sha256: str | None = None
    applied_icon: str | None = None

    @property
    def original_icon(self) -> IconLocation:
        return IconLocation(self.original_icon_path, self.original_icon_index)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BackupManifest:
    def __init__(self, manifest_path: Path, originals_dir: Path) -> None:
        self._path = manifest_path
        self._prev = manifest_path.with_name(manifest_path.name + ".prev")
        self._originals = originals_dir
        self._entries = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def __iter__(self) -> Iterator[BackupEntry]:
        return iter(list(self._entries.values()))

    def __len__(self) -> int:
        return len(self._entries)

    def reload(self) -> None:
        """Re-read the file after another process (the elevated helper) changed it."""
        self._entries = self._load()

    def get(self, shortcut: Path) -> BackupEntry | None:
        return self._entries.get(_key(shortcut))

    def record_original(self, shortcut: Path, icon: IconLocation) -> BackupEntry:
        """Save the shortcut's current bytes and icon location as its original.

        If an original is already recorded, it's kept and returned unchanged.
        """
        existing = self.get(shortcut)
        if existing is not None:
            return existing
        return self._record(shortcut, icon)

    def rerecord_original(self, shortcut: Path, icon: IconLocation) -> BackupEntry:
        """Replace the recorded original after something else rewrote the shortcut.

        Only for a shortcut whose current icon is not one of ours, typically
        because an app update reinstalled it. Its current state is then the
        app's real original, and the old record would undo the update.
        """
        old = self.get(shortcut)
        entry = self._record(shortcut, icon)
        if old is not None and old.original_copy != entry.original_copy:
            (self._originals / old.original_copy).unlink(missing_ok=True)
        return entry

    def mark_applied(self, shortcut: Path, icon_file: Path) -> BackupEntry:
        entry = self._require(shortcut)
        updated = replace(entry, applied_sha256=file_sha256(shortcut), applied_icon=str(icon_file))
        self._entries[_key(shortcut)] = updated
        self._save()
        return updated

    def original_bytes(self, entry: BackupEntry) -> bytes | None:
        """The saved original, or None if the copy is missing or doesn't match its hash."""
        try:
            data = (self._originals / entry.original_copy).read_bytes()
        except OSError:
            return None
        return data if hashlib.sha256(data).hexdigest() == entry.original_sha256 else None

    def forget(self, shortcut: Path) -> None:
        """Drop an entry once its shortcut is back to the original."""
        entry = self._entries.pop(_key(shortcut), None)
        if entry is None:
            return
        self._save()
        (self._originals / entry.original_copy).unlink(missing_ok=True)

    def _record(self, shortcut: Path, icon: IconLocation) -> BackupEntry:
        data = shortcut.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        copy_name = f"{hashlib.sha256(_key(shortcut).encode()).hexdigest()[:16]}_{digest[:8]}.lnk"
        self._originals.mkdir(parents=True, exist_ok=True)
        atomic_write(self._originals / copy_name, data)
        entry = BackupEntry(
            shortcut=str(shortcut),
            original_icon_path=icon.path,
            original_icon_index=icon.index,
            original_sha256=digest,
            original_copy=copy_name,
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._entries[_key(shortcut)] = entry
        self._save()
        return entry

    def _require(self, shortcut: Path) -> BackupEntry:
        entry = self.get(shortcut)
        if entry is None:
            raise KeyError(f"no backup recorded for {shortcut}")
        return entry

    def _load(self) -> dict[str, BackupEntry]:
        if not self._path.exists():
            if self._prev.exists():
                raise BackupCorruptError(
                    f"{self._path} is missing but {self._prev.name} exists. "
                    f"Restore it from {self._prev.name} before changing any icons."
                )
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return _parse(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BackupCorruptError(
                f"{self._path} can't be read ({exc}). It has not been changed; "
                f"the previous version is {self._prev.name}."
            ) from exc

    def _save(self) -> None:
        if self._path.exists():
            # Copy, not move: backup.json must exist at every instant.
            tmp_prev = self._prev.with_name(self._prev.name + ".tmp")
            shutil.copyfile(self._path, tmp_prev)
            tmp_prev.replace(self._prev)
        write_json(
            self._path,
            {"version": MANIFEST_VERSION, "entries": [asdict(e) for e in self._entries.values()]},
        )


def _parse(raw: object) -> dict[str, BackupEntry]:
    if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
        raise ValueError(f"expected a version {MANIFEST_VERSION} manifest")
    items = raw.get("entries")
    if not isinstance(items, list):
        raise ValueError("'entries' must be a list")
    entries: dict[str, BackupEntry] = {}
    for item in items:
        entry = _parse_entry(item)
        entries[_key(Path(entry.shortcut))] = entry
    return entries


def _parse_entry(item: object) -> BackupEntry:
    if not isinstance(item, dict):
        raise ValueError("each entry must be an object")
    strings = ("shortcut", "original_icon_path", "original_sha256", "original_copy", "recorded_at")
    for name in strings:
        if not isinstance(item.get(name), str):
            raise ValueError(f"entry field '{name}' must be a string")
    index = item.get("original_icon_index")
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError("entry field 'original_icon_index' must be an integer")
    for name in ("applied_sha256", "applied_icon"):
        if item.get(name) is not None and not isinstance(item.get(name), str):
            raise ValueError(f"entry field '{name}' must be a string or null")
    try:
        return BackupEntry(**item)
    except TypeError as exc:
        raise ValueError(f"unexpected entry fields: {exc}") from exc


def _key(shortcut: Path) -> str:
    return normalize_path(str(shortcut))
