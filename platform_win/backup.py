"""The backup manifest: how to put every changed item back exactly as it was.

An item's "state" is whatever decides its icon, as its ItemIO saves it: a
shortcut file's bytes, a folder's desktop.ini, a few registry values. A state
of None means "nothing there" (a folder without a desktop.ini), which is a
real original too: restoring it removes what was added.

Rules this module enforces:

* An item's original state is recorded, and the manifest saved to disk,
  before the item is touched. A crash at any later point loses nothing.
* A recorded original is never replaced by a themed state.
* The manifest is replaced atomically, and the previous version is kept as
  ``backup.json.prev``.
* A manifest that can't be read is reported and left untouched; nothing that
  changes icons runs until a person looks at it.

Nothing here calls Windows APIs, so all of it is tested on every OS.
"""

import hashlib
import json
import shutil
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from platform_win.fileio import atomic_write, write_json
from platform_win.shortcuts import IconLocation, normalize_path

MANIFEST_VERSION = 1
TASKBAR_VERSION = 1


class BackupCorruptError(Exception):
    """backup.json exists but can't be trusted. It is left exactly as found."""


# Hash recorded for an item whose original state was "nothing there".
ABSENT = "absent"


@dataclass(frozen=True)
class BackupEntry:
    # The item's path (named for the shortcuts it first covered; kept for compatibility).
    shortcut: str
    original_icon_path: str
    original_icon_index: int
    original_sha256: str
    # File name of the saved state under AppPaths.originals; None when it was absent.
    original_copy: str | None
    recorded_at: str
    # Filled in once the themed icon is saved into the shortcut.
    applied_sha256: str | None = None
    applied_icon: str | None = None

    @property
    def original_icon(self) -> IconLocation:
        return IconLocation(self.original_icon_path, self.original_icon_index)


@dataclass(frozen=True)
class SavedState:
    """A recorded original state; ``data`` None means the item had none."""

    data: bytes | None


def state_hash(state: bytes | None) -> str:
    return ABSENT if state is None else hashlib.sha256(state).hexdigest()


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

    def get(self, item: Path) -> BackupEntry | None:
        return self._entries.get(_key(item))

    def record_original(self, item: Path, icon: IconLocation, state: bytes | None) -> BackupEntry:
        """Save the item's current state and icon location as its original.

        If an original is already recorded, it's kept and returned unchanged.
        """
        existing = self.get(item)
        if existing is not None:
            return existing
        return self._record(item, icon, state)

    def rerecord_original(self, item: Path, icon: IconLocation, state: bytes | None) -> BackupEntry:
        """Replace the recorded original after something else rewrote the item.

        Only for an item whose current icon is not one of ours, typically
        because an app update reinstalled it. Its current state is then the
        app's real original, and the old record would undo the update.
        """
        old = self.get(item)
        entry = self._record(item, icon, state)
        if old is not None and old.original_copy not in (None, entry.original_copy):
            (self._originals / old.original_copy).unlink(missing_ok=True)
        return entry

    def mark_applied(self, item: Path, icon_file: Path, state: bytes | None) -> BackupEntry:
        entry = self._require(item)
        updated = replace(entry, applied_sha256=state_hash(state), applied_icon=str(icon_file))
        self._entries[_key(item)] = updated
        self._save()
        return updated

    def original_state(self, entry: BackupEntry) -> SavedState | None:
        """The recorded original, or None if its copy is missing or doesn't match its hash."""
        if entry.original_copy is None:
            return SavedState(None) if entry.original_sha256 == ABSENT else None
        try:
            data = (self._originals / entry.original_copy).read_bytes()
        except OSError:
            return None
        return SavedState(data) if state_hash(data) == entry.original_sha256 else None

    def forget(self, item: Path) -> None:
        """Drop an entry once its item is back to the original."""
        entry = self._entries.pop(_key(item), None)
        if entry is None:
            return
        self._save()
        if entry.original_copy is not None:
            (self._originals / entry.original_copy).unlink(missing_ok=True)

    def _record(self, item: Path, icon: IconLocation, state: bytes | None) -> BackupEntry:
        digest = state_hash(state)
        copy_name = None
        if state is not None:
            copy_name = f"{hashlib.sha256(_key(item).encode()).hexdigest()[:16]}_{digest[:8]}.bak"
            atomic_write(self._originals / copy_name, state)
        entry = BackupEntry(
            shortcut=str(item),
            original_icon_path=icon.path,
            original_icon_index=icon.index,
            original_sha256=digest,
            original_copy=copy_name,
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._entries[_key(item)] = entry
        self._save()
        return entry

    def _require(self, item: Path) -> BackupEntry:
        entry = self.get(item)
        if entry is None:
            raise KeyError(f"no backup recorded for {item}")
        return entry

    def _load(self) -> dict[str, BackupEntry]:
        raw = _load_guarded(self._path, self._prev, _parse)
        return {} if raw is None else raw

    def _save(self) -> None:
        _save_guarded(
            self._path,
            self._prev,
            {"version": MANIFEST_VERSION, "entries": [asdict(e) for e in self._entries.values()]},
        )


class TaskbarBackup:
    """taskbar.json: the taskbar settings before Iconbloom changed them, and after.

    Same guarantees as backup.json: written atomically with the previous version kept,
    and a file that can't be read is refused and left as it is. ``original`` is saved
    before any setting is touched; ``applied`` once they are written. The values are
    opaque JSON here (``platform_win.taskbar`` decides what they mean).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._prev = path.with_name(path.name + ".prev")
        data = _load_guarded(self._path, self._prev, _parse_taskbar)
        self.original: dict[str, object] | None = data.get("original") if data else None
        self.applied: dict[str, object] | None = data.get("applied") if data else None
        self.choice: dict[str, object] | None = data.get("choice") if data else None

    def save(
        self,
        original: dict[str, object],
        applied: dict[str, object] | None = None,
        choice: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "version": TASKBAR_VERSION,
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "original": original,
            "applied": applied,
            "choice": choice,
        }
        _save_guarded(self._path, self._prev, payload)
        self.original, self.applied, self.choice = original, applied, choice

    def forget(self) -> None:
        """Once everything is back to the original, nothing is left to restore."""
        self._path.unlink(missing_ok=True)
        self._prev.unlink(missing_ok=True)
        self.original = self.applied = self.choice = None


def _load_guarded[T](path: Path, prev: Path, parse: Callable[[object], T]) -> T | None:
    """``parse`` of the JSON at ``path``; None when there is none yet.

    Raises BackupCorruptError, leaving the file alone, when it can't be trusted.
    """
    if not path.exists():
        if prev.exists():
            raise BackupCorruptError(
                f"{path} is missing but {prev.name} exists. "
                f"Restore it from {prev.name} before changing anything."
            )
        return None
    try:
        return parse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BackupCorruptError(
            f"{path} can't be read ({exc}). It has not been changed; "
            f"the previous version is {prev.name}."
        ) from exc


def _save_guarded(path: Path, prev: Path, payload: object) -> None:
    if path.exists():
        # Copy, not move: the file must exist at every instant.
        tmp_prev = prev.with_name(prev.name + ".tmp")
        shutil.copyfile(path, tmp_prev)
        tmp_prev.replace(prev)
    write_json(path, payload)


def _parse_taskbar(raw: object) -> dict[str, dict[str, object] | None]:
    if not isinstance(raw, dict) or raw.get("version") != TASKBAR_VERSION:
        raise ValueError(f"expected a version {TASKBAR_VERSION} taskbar backup")
    parsed: dict[str, dict[str, object] | None] = {}
    for name in ("original", "applied", "choice"):
        value = raw.get(name)
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"'{name}' must be an object or null")
        parsed[name] = value
    if parsed["original"] is None:
        raise ValueError("'original' is missing")
    return parsed


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
    for name in ("shortcut", "original_icon_path", "original_sha256", "recorded_at"):
        if not isinstance(item.get(name), str):
            raise ValueError(f"entry field '{name}' must be a string")
    index = item.get("original_icon_index")
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError("entry field 'original_icon_index' must be an integer")
    for name in ("original_copy", "applied_sha256", "applied_icon"):
        if item.get(name) is not None and not isinstance(item.get(name), str):
            raise ValueError(f"entry field '{name}' must be a string or null")
    copy = item.get("original_copy")
    if copy is not None and not _is_copy_name(copy):
        # Copies are deleted by name, so a path here could aim that delete anywhere.
        raise ValueError(f"entry field 'original_copy' is not a backup file name: {copy!r}")
    try:
        return BackupEntry(**item)
    except TypeError as exc:
        raise ValueError(f"unexpected entry fields: {exc}") from exc


def _is_copy_name(name: str) -> bool:
    return (
        name.strip(". ") != ""
        and PureWindowsPath(name).name == name
        and PurePosixPath(name).name == name
        and ":" not in name
    )


def _key(item: Path) -> str:
    return normalize_path(str(item))
