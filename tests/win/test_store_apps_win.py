"""Store-app shortcuts on real .lnk files: the app id must survive, or a pin stops
joining the running app's window."""

from pathlib import Path

import pytest

from platform_win.extract import shell_image
from platform_win.item_io import ShellLinkIO
from platform_win.shortcuts import IconLocation
from platform_win.store_apps import StoreApp, WindowsStoreApps

# Any id works for writing a shortcut; it doesn't have to be installed.
CALCULATOR = StoreApp("Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", "Calculator")


def _app_id(path: Path) -> str:
    from win32com.propsys import propsys, pscon
    from win32com.shell import shellcon

    store = propsys.SHGetPropertyStoreFromParsingName(
        str(path), None, shellcon.GPS_DEFAULT, propsys.IID_IPropertyStore
    )
    return str(store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue())


def test_create_link_starts_the_app_through_explorer(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    apps = WindowsStoreApps()
    link = tmp_path / "Calculator.lnk"
    icon = IconLocation(str(tmp_path / "pink.ico"), 0)
    apps.create_link(link, CALCULATOR, icon)
    info = shell_io.read(link)
    assert Path(info.target).name.casefold() == "explorer.exe"
    assert info.store_app_id == CALCULATOR.app_id
    assert info.icon == icon
    assert _app_id(link) == CALCULATOR.app_id


def test_restyling_keeps_the_app_id(tmp_path: Path, shell_io: ShellLinkIO) -> None:
    link = tmp_path / "Calculator.lnk"
    WindowsStoreApps().create_link(link, CALCULATOR, IconLocation(str(tmp_path / "a.ico"), 0))
    shell_io.set_icon(link, IconLocation(str(tmp_path / "b.ico"), 0))
    assert _app_id(link) == CALCULATOR.app_id


def test_listed_apps_have_ids_and_pictures() -> None:
    apps = WindowsStoreApps().list()
    if not apps:
        pytest.skip("no Store apps on this machine")
    for app in apps:
        assert "!" in app.app_id
        assert app.name
    image = shell_image(apps[0].path)
    assert image.width >= 32
