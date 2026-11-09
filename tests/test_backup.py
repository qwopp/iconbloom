import json
from pathlib import Path

import pytest

from platform_win.backup import BackupCorruptError, BackupManifest, file_sha256
from platform_win.shortcuts import IconLocation

ORIGINAL = IconLocation(r"C:\Apps\app.exe", 2)


@pytest.fixture
def lnk(tmp_path: Path) -> Path:
    path = tmp_path / "App.lnk"
    path.write_bytes(b"original link bytes")
    return path


def _manifest(tmp_path: Path) -> BackupManifest:
    return BackupManifest(tmp_path / "data" / "backup.json", tmp_path / "data" / "originals")


def test_new_manifest_is_empty(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    assert len(manifest) == 0
    assert not manifest.path.exists()


def test_record_saves_copy_and_survives_reload(tmp_path: Path, lnk: Path) -> None:
    entry = _manifest(tmp_path).record_original(lnk, ORIGINAL)
    reloaded = _manifest(tmp_path)
    assert reloaded.get(lnk) == entry
    assert entry.original_icon == ORIGINAL
    assert reloaded.original_bytes(entry) == b"original link bytes"


def test_record_never_overwrites_existing_original(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    first = manifest.record_original(lnk, ORIGINAL)
    lnk.write_bytes(b"themed bytes")
    second = manifest.record_original(lnk, IconLocation(r"C:\themed.ico", 0))
    assert second == first
    assert manifest.original_bytes(second) == b"original link bytes"


def test_keys_ignore_case_and_slashes(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.record_original(lnk, ORIGINAL)
    assert manifest.get(Path(str(lnk).upper().replace("/", "\\"))) is not None


def test_mark_applied_records_hash(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.record_original(lnk, ORIGINAL)
    lnk.write_bytes(b"themed bytes")
    entry = manifest.mark_applied(lnk, tmp_path / "pink.ico")
    assert entry.applied_sha256 == file_sha256(lnk)
    assert entry.applied_icon == str(tmp_path / "pink.ico")


def test_mark_applied_needs_a_recorded_original(tmp_path: Path, lnk: Path) -> None:
    with pytest.raises(KeyError, match="no backup"):
        _manifest(tmp_path).mark_applied(lnk, tmp_path / "pink.ico")


def test_rerecord_replaces_original_and_its_copy(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    old = manifest.record_original(lnk, ORIGINAL)
    lnk.write_bytes(b"reinstalled by updater")
    new = manifest.rerecord_original(lnk, IconLocation(r"C:\Apps\v2.exe", 0))
    assert manifest.original_bytes(new) == b"reinstalled by updater"
    assert not (tmp_path / "data" / "originals" / old.original_copy).exists()


def test_forget_removes_entry_and_copy(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    entry = manifest.record_original(lnk, ORIGINAL)
    manifest.forget(lnk)
    manifest.forget(lnk)  # forgetting twice is harmless
    assert _manifest(tmp_path).get(lnk) is None
    assert not (tmp_path / "data" / "originals" / entry.original_copy).exists()


def test_tampered_copy_is_not_trusted(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    entry = manifest.record_original(lnk, ORIGINAL)
    (tmp_path / "data" / "originals" / entry.original_copy).write_bytes(b"something else")
    assert manifest.original_bytes(entry) is None
    (tmp_path / "data" / "originals" / entry.original_copy).unlink()
    assert manifest.original_bytes(entry) is None


def test_previous_generation_is_kept(tmp_path: Path, lnk: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.record_original(lnk, ORIGINAL)
    manifest.mark_applied(lnk, tmp_path / "pink.ico")
    prev = json.loads((tmp_path / "data" / "backup.json.prev").read_text(encoding="utf-8"))
    assert prev["entries"][0]["applied_sha256"] is None


@pytest.mark.parametrize(
    "content",
    [
        "{ not json",
        "[]",
        '{"version": 99, "entries": []}',
        '{"version": 1, "entries": {}}',
        '{"version": 1, "entries": ["x"]}',
        '{"version": 1, "entries": [{"shortcut": 3}]}',
        '{"version": 1, "entries": [{"shortcut": "a", "original_icon_path": "", '
        '"original_sha256": "", "original_copy": "", "recorded_at": "", '
        '"original_icon_index": "0"}]}',
        '{"version": 1, "entries": [{"shortcut": "a", "original_icon_path": "", '
        '"original_sha256": "", "original_copy": "", "recorded_at": "", '
        '"original_icon_index": 0, "applied_icon": 5}]}',
        '{"version": 1, "entries": [{"shortcut": "a", "original_icon_path": "", '
        '"original_sha256": "", "original_copy": "", "recorded_at": "", '
        '"original_icon_index": 0, "surprise": true}]}',
    ],
)
def test_corrupt_manifest_is_refused_and_left_alone(tmp_path: Path, content: str) -> None:
    path = tmp_path / "data" / "backup.json"
    path.parent.mkdir()
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BackupCorruptError, match="has not been changed"):
        _manifest(tmp_path)
    assert path.read_text(encoding="utf-8") == content


def test_missing_manifest_with_previous_generation_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "backup.json.prev").write_text('{"version": 1, "entries": []}', encoding="utf-8")
    with pytest.raises(BackupCorruptError, match="is missing"):
        _manifest(tmp_path)
