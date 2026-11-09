"""Crash-safe file writes shared by everything that saves user state."""

import json
import os
from pathlib import Path


def atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so a crash leaves either the old or the new file.

    The bytes are flushed to disk before the swap, so after a power cut the
    file is never empty or half-written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def write_json(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    atomic_write(path, text.encode("utf-8"))
