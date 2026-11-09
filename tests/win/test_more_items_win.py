"""Real Windows behavior for folders, registry-backed icons and the Recycle Bin."""

import contextlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from platform_win.extract import extract_icon, shell_image
from platform_win.item_io import (
    HIDDEN,
    READ_ONLY,
    SYSTEM,
    FolderIO,
    WindowsAttributes,
    shell_set_folder_icon,
)
from platform_win.shell_icons import RECYCLE_BIN, WindowsIconIO, WindowsRegistry
from platform_win.shortcuts import IconLocation
from tests.win.conftest import SYSTEM32

PINK = IconLocation(r"C:\Iconbloom-test\pink.ico", 0)


@pytest.fixture
def registry() -> Iterator[WindowsRegistry]:
    """A throwaway key, so tests never touch the real desktop icon settings."""
    base = rf"Software\IconbloomTests\{uuid.uuid4()}"
    yield WindowsRegistry(base)
    _delete_tree(base)


def _delete_tree(path: str) -> None:
    import winreg

    with contextlib.suppress(FileNotFoundError):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as handle:
            children = [winreg.EnumKey(handle, i) for i in range(winreg.QueryInfoKey(handle)[0])]
        for child in children:
            _delete_tree(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def test_registry_round_trip(registry: WindowsRegistry) -> None:
    io = WindowsIconIO(registry)
    saved = io.snapshot(RECYCLE_BIN.path)
    io.set_icon(RECYCLE_BIN.path, PINK)
    assert io.read(RECYCLE_BIN.path).icon == PINK
    io.restore(RECYCLE_BIN.path, saved)
    assert io.read(RECYCLE_BIN.path).icon == IconLocation()
    assert not registry.key_exists(RECYCLE_BIN.clsid)


def test_windows_ships_a_full_recycle_bin_icon(registry: WindowsRegistry) -> None:
    (full,) = WindowsIconIO(registry).variants(RECYCLE_BIN.path).values()
    image = extract_icon(full, "", RECYCLE_BIN.path, use_shell=False).image
    assert image.getbbox() is not None


def test_shell_draws_the_recycle_bin() -> None:
    image = shell_image(RECYCLE_BIN.path)
    assert image.getchannel("A").getbbox() is not None


def test_folder_icon_and_exact_restore(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Through Windows' own folder-icon call too, as the app does."""
    attributes = WindowsAttributes()
    folder = tmp_path / "Games"
    folder.mkdir()
    io = FolderIO(attributes, shell_set_folder_icon)
    icon = IconLocation(str(SYSTEM32 / "shell32.dll"), 4)
    saved = io.snapshot(folder)
    io.set_icon(folder, icon)
    assert "didn't take the icon" not in caplog.text
    ini = folder / "desktop.ini"
    assert io.read(folder).icon == icon
    assert (attributes.get(ini) or 0) & (HIDDEN | SYSTEM) == HIDDEN | SYSTEM
    assert (attributes.get(folder) or 0) & READ_ONLY
    io.set_icon(folder, PINK)  # rewrite a hidden file
    io.restore(folder, saved)
    assert not ini.exists()
    assert not (attributes.get(folder) or 0) & READ_ONLY
