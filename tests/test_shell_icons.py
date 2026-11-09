from pathlib import Path

from platform_win.shell_icons import RECYCLE_BIN, REG_EXPAND_SZ, WINDOWS_ICONS, WindowsIconIO
from platform_win.shortcuts import IconLocation, variant_path
from tests.fakes import FakeRegistry

THIS_PC = WINDOWS_ICONS[1]


def _io() -> tuple[WindowsIconIO, FakeRegistry]:
    registry = FakeRegistry()
    return WindowsIconIO(registry), registry


def test_default_icon_reads_as_empty() -> None:
    io, _ = _io()
    assert io.read(THIS_PC.path).icon == IconLocation()
    assert io.exists(THIS_PC.path)


def test_set_icon_writes_the_users_default_icon(tmp_path: Path) -> None:
    io, registry = _io()
    icon = IconLocation(str(tmp_path / "pc.ico"), 0)
    io.set_icon(THIS_PC.path, icon)
    key = f"{THIS_PC.clsid}\\DefaultIcon"
    assert registry.keys[key] == {"": (REG_EXPAND_SZ, f"{icon.path},0")}
    assert io.read(THIS_PC.path).icon == icon


def test_recycle_bin_gets_its_full_variant(tmp_path: Path) -> None:
    io, registry = _io()
    icon_file = tmp_path / "bin.ico"
    icon_file.write_bytes(b"ico")
    variant_path(icon_file, "full").write_bytes(b"ico")
    io.set_icon(RECYCLE_BIN.path, IconLocation(str(icon_file), 0))
    values = registry.keys[f"{RECYCLE_BIN.clsid}\\DefaultIcon"]
    assert values["empty"][1] == f"{icon_file},0"
    assert values["full"][1] == f"{variant_path(icon_file, 'full')},0"


def test_recycle_bin_without_variant_keeps_windows_full_icon(tmp_path: Path) -> None:
    io, registry = _io()
    io.set_icon(RECYCLE_BIN.path, IconLocation(str(tmp_path / "custom.ico"), 0))
    values = registry.keys[f"{RECYCLE_BIN.clsid}\\DefaultIcon"]
    assert values["full"][1] == FakeRegistry.SYSTEM["full"]


def test_variants_only_for_the_recycle_bin() -> None:
    io, _ = _io()
    assert io.variants(RECYCLE_BIN.path) == {
        "full": IconLocation(r"%SystemRoot%\System32\imageres.dll", -54)
    }
    assert io.variants(THIS_PC.path) == {}


def test_restore_removes_keys_it_created(tmp_path: Path) -> None:
    io, registry = _io()
    saved = io.snapshot(RECYCLE_BIN.path)
    io.set_icon(RECYCLE_BIN.path, IconLocation(str(tmp_path / "bin.ico"), 0))
    io.restore(RECYCLE_BIN.path, saved)
    assert registry.keys == {}


def test_restore_keeps_what_was_there_before(tmp_path: Path) -> None:
    io, registry = _io()
    key = f"{THIS_PC.clsid}\\DefaultIcon"
    registry.keys[THIS_PC.clsid] = {"Other": (1, "kept")}
    registry.keys[key] = {"": (1, r"C:\mine\pc.ico,0")}
    saved = io.snapshot(THIS_PC.path)
    io.set_icon(THIS_PC.path, IconLocation(str(tmp_path / "pink.ico"), 0))
    io.restore(THIS_PC.path, saved)
    assert registry.keys == {
        THIS_PC.clsid: {"Other": (1, "kept")},
        key: {"": (1, r"C:\mine\pc.ico,0")},
    }


def test_clearing_returns_to_windows_default(tmp_path: Path) -> None:
    io, registry = _io()
    io.set_icon(RECYCLE_BIN.path, IconLocation(str(tmp_path / "bin.ico"), 0))
    io.set_icon(RECYCLE_BIN.path, IconLocation())
    assert registry.keys[f"{RECYCLE_BIN.clsid}\\DefaultIcon"] == {}
    assert io.read(RECYCLE_BIN.path).icon == IconLocation()
