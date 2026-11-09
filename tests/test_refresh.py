"""Clearing Windows' icon cache files, which the hard refresh does while Explorer is closed."""

from pathlib import Path

import pytest

from platform_win.refresh import clear_icon_cache, icon_cache_files


def _cache(local: Path) -> list[Path]:
    explorer = local / "Microsoft" / "Windows" / "Explorer"
    explorer.mkdir(parents=True)
    files = [local / "IconCache.db", explorer / "iconcache_32.db", explorer / "iconcache_256.db"]
    for path in files:
        path.write_bytes(b"cache")
    # Neighbours that must survive: thumbnails and anything else Explorer keeps there.
    (explorer / "thumbcache_256.db").write_bytes(b"thumbs")
    (explorer / "iconcache_32.db.bak").write_bytes(b"other")
    return files


def test_finds_every_icon_cache_file_and_nothing_else(tmp_path: Path) -> None:
    files = _cache(tmp_path)
    assert sorted(icon_cache_files(tmp_path)) == sorted(files)


def test_no_cache_yet_is_fine(tmp_path: Path) -> None:
    assert icon_cache_files(tmp_path) == []
    assert clear_icon_cache(tmp_path) == []


def test_clears_the_cache_and_keeps_thumbnails(tmp_path: Path) -> None:
    files = _cache(tmp_path)
    assert clear_icon_cache(tmp_path, wait=lambda _s: None) == []
    assert not any(p.exists() for p in files)
    assert (tmp_path / "Microsoft" / "Windows" / "Explorer" / "thumbcache_256.db").exists()


def test_retries_files_explorer_has_not_let_go_of_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _cache(tmp_path)
    busy = {files[1]: 2}  # still open for the first two tries
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if busy.get(self, 0) > 0:
            busy[self] -= 1
            raise PermissionError(f"in use: {self}")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    waits: list[float] = []
    assert clear_icon_cache(tmp_path, wait=waits.append) == []
    assert len(waits) == 2
    assert not any(p.exists() for p in files)


def test_gives_up_on_a_file_another_program_keeps_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    files = _cache(tmp_path)
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self == files[0]:
            raise PermissionError(f"in use: {self}")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert clear_icon_cache(tmp_path, attempts=3, wait=lambda _s: None) == [files[0]]
    assert not files[1].exists()
    assert "could not delete icon cache file" in caplog.text
