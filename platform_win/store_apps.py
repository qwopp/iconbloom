"""Microsoft Store apps (Game Bar, the new Outlook, Calculator...).

A Store app has no shortcut file whose icon we could change, and its taskbar pin
keeps no file either. What works instead is a shortcut that starts the app
through Explorer, ``explorer.exe shell:AppsFolder\\<app id>``, carrying the app's
id (AppUserModelID) so Windows treats its window as the same app. Pinned, it
shows our icon, and the running app joins that pin. Windows won't let programs
pin, so Iconbloom puts the shortcut on the desktop for the person to pin.

Until that shortcut exists, each Store app is listed under a made-up path,
``shell:AppsFolder\\<app id>``, the way Windows' own icons use ``::{CLSID}``.
"""

import logging
import ntpath
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from platform_win.shortcuts import (
    STORE_APP_PREFIX,
    IconLocation,
    LinkInfo,
    Shortcut,
    Source,
    is_store_app_id,
)

log = logging.getLogger(__name__)


def explorer_path() -> str:
    return ntpath.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "explorer.exe")


@dataclass(frozen=True)
class StoreApp:
    app_id: str
    name: str

    @property
    def path(self) -> Path:
        return Path(STORE_APP_PREFIX + self.app_id)

    def info(self, explorer: str) -> LinkInfo:
        return LinkInfo(explorer, STORE_APP_PREFIX + self.app_id, IconLocation())

    def shortcut(self, explorer: str) -> Shortcut:
        return Shortcut(self.path, Source.STORE_APPS, self.info(explorer), label=self.name)


def app_id_from_path(path: Path) -> str:
    return str(path)[len(STORE_APP_PREFIX) :]


class StoreApps(Protocol):
    """The Store apps on this PC, and making the shortcut that themes one."""

    @property
    def explorer(self) -> str: ...

    def list(self) -> Sequence[StoreApp]: ...

    def create_link(self, path: Path, app: StoreApp, icon: IconLocation) -> None: ...


class StoreAppIO:
    """The ItemIO for a Store app that has no shortcut yet: it only describes it.

    Theming one creates a new shortcut instead (``IconService`` does that), so
    nothing here ever changes.
    """

    def __init__(self, explorer: str) -> None:
        self._explorer = explorer

    def exists(self, path: Path) -> bool:
        return True

    def read(self, path: Path) -> LinkInfo:
        return StoreApp(app_id_from_path(path), "").info(self._explorer)

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        raise OSError("a Store app gets a new shortcut instead")

    def snapshot(self, path: Path) -> bytes | None:
        return None

    def restore(self, path: Path, state: bytes | None) -> None:
        pass

    def variants(self, path: Path) -> Mapping[str, IconLocation]:
        return {}


class WindowsStoreApps:
    """The real thing: Windows' Apps folder and IShellLink with its property store."""

    def __init__(self) -> None:
        self.explorer = explorer_path()

    def list(self) -> Sequence[StoreApp]:
        try:
            return _apps_folder()
        except Exception:
            log.warning("could not list Store apps", exc_info=True)
            return []

    def create_link(self, path: Path, app: StoreApp, icon: IconLocation) -> None:
        import pythoncom
        from win32com.propsys import propsys, pscon

        from platform_win.item_io import new_link, shell_errors_as_os_errors

        with shell_errors_as_os_errors(path):
            link, persist = new_link()
            # pywin32's stubs don't know a link can be asked for its property store.
            com_link: Any = link
            link.SetPath(self.explorer)
            link.SetArguments(STORE_APP_PREFIX + app.app_id)
            link.SetIconLocation(icon.path, icon.index)
            store = com_link.QueryInterface(propsys.IID_IPropertyStore)
            value = propsys.PROPVARIANTType(app.app_id, pythoncom.VT_LPWSTR)
            store.SetValue(pscon.PKEY_AppUserModel_ID, value)
            store.Commit()
            persist.Save(str(path), True)


def show_in_explorer(path: Path) -> None:
    """Open the folder holding ``path`` with it selected, so the person can pin it."""
    import subprocess

    # Explorer wants /select,"path" exactly; the list form would quote it all as one.
    subprocess.Popen(f'explorer.exe /select,"{path}"')


def _apps_folder() -> list[StoreApp]:
    from win32com.propsys import pscon
    from win32com.shell import shell, shellcon

    from platform_win.item_io import ensure_com

    ensure_com()
    # pywin32's stubs want a bind context where None is what the API takes.
    win: Any = shell
    folder = win.SHCreateItemFromParsingName("shell:AppsFolder", None, win.IID_IShellItem)
    items = folder.BindToHandler(None, win.BHID_EnumItems, win.IID_IEnumShellItems)
    apps: dict[str, StoreApp] = {}
    for item in items:
        try:
            item2 = item.QueryInterface(win.IID_IShellItem2)
            app_id = str(item2.GetString(pscon.PKEY_AppUserModel_ID))
            name = str(item.GetDisplayName(shellcon.SIGDN_NORMALDISPLAY))
        except Exception:  # noqa: BLE001 - one odd entry shouldn't hide the rest
            continue
        # Desktop programs listed here already have Start menu shortcuts of their own.
        if is_store_app_id(app_id) and name:
            apps.setdefault(app_id.casefold(), StoreApp(app_id, name))
    return sorted(apps.values(), key=lambda a: a.name.casefold())
