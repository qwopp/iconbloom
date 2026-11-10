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
    assert "Admin  (original)  [shared: needs administrator permission]" in out
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
    assert "needs administrator permission" in capsys.readouterr().out


def test_service_type_is_used(env: FakeDesktop) -> None:
    assert isinstance(env.service(), IconService)


def test_taskbar_show_apply_and_revert(
    env: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    before = env.taskbar.state()
    assert _run(env, "taskbar") == 0
    out = capsys.readouterr().out
    assert "color:         Windows' own" in out
    assert "alignment:     centered" in out
    assert "Iconbloom:     not changed" in out

    assert _run(env, "taskbar", "apply", "--look", "deep", "--left", "--dry-run") == 0
    assert capsys.readouterr().out.strip() == "would change taskbar color, alignment"
    assert env.taskbar.state() == before

    args = ("taskbar", "apply", "--look", "soft", "--frosted", "--search", "button")
    assert _run(env, *args, "--auto-hide") == 0
    assert "changed taskbar color, frosted glass, search, hide automatically" in (
        capsys.readouterr().out
    )
    assert _run(env, "taskbar") == 0
    assert "Iconbloom:     kawaii_pink / soft" in capsys.readouterr().out

    assert _run(env, "taskbar", "revert") == 0
    assert env.taskbar.state() == before
    assert _run(env, "taskbar", "revert") == 0
    assert capsys.readouterr().out.strip().endswith("nothing to do")


def test_taskbar_rejects_an_unknown_look(
    env: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(env, "taskbar", "apply", "--look", "sparkly") == 1
    assert "no look 'sparkly'" in capsys.readouterr().err


def test_revert_all_also_restores_the_taskbar(
    env: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    before = env.taskbar.state()
    assert _run(env, "taskbar", "apply", "--look", "deep", "--small") == 0
    capsys.readouterr()
    assert _run(env, "revert-all", "--dry-run") == 0
    assert "would restore the taskbar's taskbar color, smaller buttons" in capsys.readouterr().out
    assert _run(env, "revert-all") == 0
    assert "did restore the taskbar's" in capsys.readouterr().out
    assert env.taskbar.state() == before


def test_store_apps_are_listed_and_get_a_shortcut_to_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app_id = "Microsoft.XboxGamingOverlay_8wekyb3d8bbwe!App"
    env = FakeDesktop(tmp_path, store_apps={app_id: "Game Bar"})
    assert _run(env, "scan") == 0
    out = capsys.readouterr().out
    assert "Game Bar  (original)" in out
    assert f"target: Store app {app_id}" in out
    assert _run(env, "apply", "Game Bar", "--recipe", "pastel_recolor") == 0
    link = env.desktop / "Game Bar.lnk"
    assert f"pin {link} yourself" in capsys.readouterr().out
    assert link.exists()
