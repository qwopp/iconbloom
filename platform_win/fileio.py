"""Crash-safe file writes shared by everything that saves user state."""

import json
import os
import tempfile
import time
from pathlib import Path

# About 2 seconds in total before giving up and reporting the error.
_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8)


def atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so a crash leaves either the old or the new file.

    The bytes are flushed to disk before the swap, so after a power cut the
    file is never empty or half-written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique name, so two writers of the same file never share a temp file.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _replace(source: Path, target: Path) -> None:
    """Rename over ``target``, waiting out brief locks.

    Antivirus scanners and the search indexer often hold a just-written file
    open for a moment, and Windows refuses to replace an open file.
    """
    for delay in _RETRY_DELAYS:
        try:
            source.replace(target)
        except PermissionError:
            time.sleep(delay)
        else:
            return
    source.replace(target)


def write_json(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    atomic_write(path, text.encode("utf-8"))
