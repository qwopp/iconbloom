from pathlib import Path

import pytest

from app import cli
from app.service import IconService
from tests.fakes import FakeDesktop


def _run(env: FakeDesktop, *argv: str) -> int:
    return cli.main(list(argv), make_service=env.service)


def test_scan_lists_and_dumps(
    env: FakeDesktop, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env.make("Paint", icon=r"C:\Apps\paint.ico")
    env.make("Admin", folder=env.common)
    assert _run(env, "scan", "--dump-dir", str(tmp_path / "dump")) == 0
    out = capsys.readouterr().out
    assert "Paint  (original)" in out
    assert "Admin  (original)  [read-only]" in out
    assert r"icon:   C:\Apps\paint.ico,1" in out
    assert "2 shortcut groups" in out
    assert len(list((tmp_path / "dump").glob("*.png"))) == 2


def test_apply_dry_run_then_real_then_revert(
    env: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    lnk = env.make("Paint")
    original = lnk.read_bytes()

    assert _run(env, "apply", "paint", "--recipe", "tile_bow", "--dry-run") == 0
    assert "would change" in capsys.readouterr().out
    assert lnk.read_bytes() == original

    assert _run(env, "apply", "Paint", "--recipe", "tile_bow", "--seed", "2") == 0
    assert "did change" in capsys.readouterr().out
    assert lnk.read_bytes() != original

    assert _run(env, "revert", "Paint") == 0
    assert lnk.read_bytes() == original


def test_revert_all_cleanup_and_reapply(
    env: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    env.make("Paint")
    assert _run(env, "apply", "Paint", "--recipe", "sticker") == 0
    assert _run(env, "reapply", "--dry-run") == 0
    assert _run(env, "revert-all") == 0
    capsys.readouterr()
    assert _run(env, "cleanup", "--dry-run") == 0
    assert "would delete" in capsys.readouterr().out
    assert _run(env, "cleanup") == 0
    assert _run(env, "cleanup") == 0
    assert "nothing to do" in capsys.readouterr().out


def test_errors_are_reported(env: FakeDesktop, capsys: pytest.CaptureFixture[str]) -> None:
    env.make("Paint")
    assert _run(env, "apply", "Nope", "--recipe", "sticker") == 1
    assert _run(env, "apply", "Paint", "--recipe", "nope") == 1
    err = capsys.readouterr().err
    assert "no shortcut named 'Nope'" in err
    assert "no recipe 'nope'" in err


def test_corrupt_backup_refuses(env: FakeDesktop, capsys: pytest.CaptureFixture[str]) -> None:
    env.paths.ensure()
    env.paths.manifest.write_text("{", encoding="utf-8")
    assert _run(env, "revert-all") == 2
    assert "Refusing to change anything" in capsys.readouterr().err


def test_reported_skips(env: FakeDesktop, capsys: pytest.CaptureFixture[str]) -> None:
    env.make("Admin", folder=env.common)
    assert _run(env, "apply", "Admin", "--recipe", "sticker") == 0
    assert "read-only location" in capsys.readouterr().out


def test_service_type_is_used(env: FakeDesktop) -> None:
    assert isinstance(env.service(), IconService)
