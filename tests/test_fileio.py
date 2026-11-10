import json
import threading
from pathlib import Path

import pytest

from platform_win import fileio


def test_atomic_write_creates_folders_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "new" / "data.bin"
    fileio.atomic_write(target, b"hello")
    assert target.read_bytes() == b"hello"
    assert list(target.parent.iterdir()) == [target]


def test_write_json(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    fileio.write_json(target, {"a": [1, 2]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": [1, 2]}


def test_replace_waits_out_a_brief_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"old")
    real_replace = Path.replace
    failures = iter([True, True, False])

    def flaky(self: Path, other: Path) -> Path:
        if next(failures):
            raise PermissionError("locked by a scanner")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(fileio, "_RETRY_DELAYS", (0.0, 0.0, 0.0))
    fileio.atomic_write(target, b"new")
    assert target.read_bytes() == b"new"


def test_replace_gives_up_on_a_lasting_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(self: Path, other: Path) -> Path:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(fileio, "_RETRY_DELAYS", (0.0,))
    with pytest.raises(PermissionError):
        fileio.atomic_write(tmp_path / "data.bin", b"x")


def test_two_writers_of_one_file_both_succeed(tmp_path: Path) -> None:
    target = tmp_path / "choices.json"
    errors: list[BaseException] = []

    def write(n: int) -> None:
        try:
            for _ in range(50):
                fileio.atomic_write(target, str(n).encode())
        except BaseException as exc:  # noqa: BLE001 - collected for the assert below
            errors.append(exc)

    workers = [threading.Thread(target=write, args=(n,)) for n in (1, 2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert not errors
    assert target.read_bytes() in (b"1", b"2")
    assert [p.name for p in tmp_path.iterdir()] == ["choices.json"]
