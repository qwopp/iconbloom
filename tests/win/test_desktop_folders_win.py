"""Real Windows file attributes drive which desktop folders are scanned."""

from pathlib import Path

import pytest
import win32api
import win32con

from platform_win.item_io import ShellLinkIO
from platform_win.shortcuts import (
    FILE_ATTRIBUTE_HIDDEN,
    desktop_folders_root,
    file_attributes,
    scan,
)
from tests.win.conftest import NOTEPAD


def test_hidden_attribute_is_read(tmp_path: Path) -> None:
    folder = tmp_path / "Secret"
    folder.mkdir()
    assert not file_attributes(folder) & FILE_ATTRIBUTE_HIDDEN
    win32api.SetFileAttributes(str(folder), win32con.FILE_ATTRIBUTE_HIDDEN)
    assert file_attributes(folder) & FILE_ATTRIBUTE_HIDDEN


def test_nested_real_shortcuts_are_found_but_not_in_hidden_folders(
    tmp_path: Path, shell_io: ShellLinkIO
) -> None:
    (tmp_path / "Tools").mkdir()
    (tmp_path / "Secret").mkdir()
    shell_io.create(tmp_path / "Tools" / "Editor.lnk", str(NOTEPAD))
    shell_io.create(tmp_path / "Secret" / "Hidden.lnk", str(NOTEPAD))
    win32api.SetFileAttributes(str(tmp_path / "Secret"), win32con.FILE_ATTRIBUTE_HIDDEN)
    names = {g.name for g in scan([desktop_folders_root(tmp_path)], shell_io)}
    assert "Editor" in names
    assert not {"Secret", "Hidden"} & names


def test_corrupt_shortcut_is_an_os_error_and_the_scan_goes_on(
    tmp_path: Path, shell_io: ShellLinkIO
) -> None:
    (tmp_path / "Old").mkdir()
    broken = tmp_path / "Old" / "Broken.lnk"
    broken.write_bytes(b"not a shortcut at all")
    shell_io.create(tmp_path / "Old" / "Editor.lnk", str(NOTEPAD))
    with pytest.raises(OSError, match=r"Broken\.lnk"):
        shell_io.read(broken)
    assert {g.name for g in scan([desktop_folders_root(tmp_path)], shell_io)} == {"Editor"}
