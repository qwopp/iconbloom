"""Read and change the icon of each kind of item, and save or restore its full state.

Every kind implements ``shortcuts.ItemIO``:

* ``ShellLinkIO``: .lnk shortcuts, through Windows' own IShellLink.
* ``UrlFileIO``: .url shortcuts (web links and most Steam/Epic game shortcuts),
  which are small INI files.
* ``FolderIO``: folders, whose custom icon lives in a hidden desktop.ini.
* ``shell_icons.WindowsIconIO``: the Recycle Bin, This PC and friends.
* ``store_apps.StoreAppIO``: Store apps that don't have a shortcut yet.

``ItemRouter`` picks the right one from the item's path.
"""

import base64
import json
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from platform_win.fileio import atomic_write
from platform_win.ini import IniFile
from platform_win.shortcuts import IconLocation, ItemIO, ItemKind, LinkInfo, kind_of

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from _win32typing import PyIPersistFile, PyIShellLink


class FileStateIO:
    """Items whose whole state is one file: a copy of its bytes is a perfect backup."""

    def exists(self, path: Path) -> bool:
        return path.is_file()

    def snapshot(self, path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def restore(self, path: Path, state: bytes | None) -> None:
        if state is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, state)

    def variants(self, path: Path) -> Mapping[str, IconLocation]:
        return {}


class ShellLinkIO(FileStateIO):
    """.lnk shortcuts, through the Windows shell's own IShellLink implementation."""

    def read(self, path: Path) -> LinkInfo:
        with shell_errors_as_os_errors(path):
            link, persist = new_link()
            persist.Load(str(path), _STGM_READ)
            target, _ = link.GetPath(0, _MAX_PATH)
            icon_path, icon_index = link.GetIconLocation(_MAX_PATH)
            arguments = link.GetArguments(_MAX_PATH)
        return LinkInfo(
            target=str(target),
            arguments=str(arguments),
            icon=IconLocation(str(icon_path), int(icon_index)),
        )

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        with shell_errors_as_os_errors(path):
            link, persist = new_link()
            persist.Load(str(path), _STGM_READWRITE)
            link.SetIconLocation(icon.path, icon.index)
            persist.Save(str(path), True)

    def create(self, path: Path, target: str, icon: IconLocation | None = None) -> None:
        """Make a new shortcut. Used by tests to build real .lnk fixtures."""
        link, persist = new_link()
        link.SetPath(target)
        if icon is not None:
            link.SetIconLocation(icon.path, icon.index)
        persist.Save(str(path), True)


class UrlFileIO(FileStateIO):
    """.url shortcuts: [InternetShortcut] URL=, IconFile= and IconIndex= in an INI file."""

    SECTION = "InternetShortcut"

    def read(self, path: Path) -> LinkInfo:
        ini = IniFile.parse(path.read_bytes())
        index = ini.get(self.SECTION, "IconIndex") or "0"
        return LinkInfo(
            target=ini.get(self.SECTION, "URL") or "",
            arguments="",
            icon=IconLocation(ini.get(self.SECTION, "IconFile") or "", _int(index)),
        )

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        ini = IniFile.parse(path.read_bytes())
        if icon.path:
            ini.set(self.SECTION, "IconFile", icon.path)
            ini.set(self.SECTION, "IconIndex", str(icon.index))
        else:
            ini.remove(self.SECTION, "IconFile")
            ini.remove(self.SECTION, "IconIndex")
        atomic_write(path, ini.to_bytes())


class Attributes(Protocol):
    """File attribute bits (FILE_ATTRIBUTE_*); None when the path doesn't exist."""

    def get(self, path: Path) -> int | None: ...

    def set(self, path: Path, value: int) -> None: ...


READ_ONLY = 0x1
HIDDEN = 0x2
SYSTEM = 0x4
NORMAL = 0x80


def shell_set_folder_icon(path: Path, icon: IconLocation) -> None:
    """Set a folder's icon through SHGetSetFolderCustomSettings, the call behind
    Properties > Customize > Change Icon. It writes the same desktop.ini entry
    FolderIO already wrote, and makes Explorer drop its stale thumbnail."""
    import ctypes
    from ctypes import wintypes

    class FolderCustomSettings(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("dwMask", wintypes.DWORD),
            ("pvid", ctypes.c_void_p),
            ("pszWebViewTemplate", wintypes.LPWSTR),
            ("cchWebViewTemplate", wintypes.DWORD),
            ("pszWebViewTemplateVersion", wintypes.LPWSTR),
            ("pszInfoTip", wintypes.LPWSTR),
            ("cchInfoTip", wintypes.DWORD),
            ("pclsid", ctypes.c_void_p),
            ("dwFlags", wintypes.DWORD),
            ("pszIconFile", wintypes.LPWSTR),
            ("cchIconFile", wintypes.DWORD),
            ("iIconIndex", ctypes.c_int),
            ("pszLogo", wintypes.LPWSTR),
            ("cchLogo", wintypes.DWORD),
        )

    settings = FolderCustomSettings()
    settings.dwSize = ctypes.sizeof(FolderCustomSettings)
    settings.dwMask = _FCSM_ICONFILE
    settings.pszIconFile = icon.path
    settings.iIconIndex = icon.index
    result = ctypes.windll.shell32.SHGetSetFolderCustomSettings(
        ctypes.byref(settings), str(path), _FCS_FORCEWRITE
    )
    if result != 0:
        # The icon is already in desktop.ini; only the redraw may lag behind.
        log.warning("Windows didn't take the icon for %s (HRESULT %#x)", path, result & 0xFFFFFFFF)


_FCSM_ICONFILE = 0x10
_FCS_FORCEWRITE = 0x2


class WindowsAttributes:
    def get(self, path: Path) -> int | None:
        import ctypes

        value = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return None if value == 0xFFFFFFFF else int(value)

    def set(self, path: Path, value: int) -> None:
        import ctypes

        if not ctypes.windll.kernel32.SetFileAttributesW(str(path), value or NORMAL):
            raise ctypes.WinError()


class FolderIO:
    """Folder icons, set the way Explorer's own "Change Icon" does.

    The icon goes in the folder's desktop.ini ([.ShellClassInfo] IconResource),
    which is hidden and marked as a system file, and the folder gets the
    read-only attribute, which is how Windows knows to read that file. The
    saved state covers all three, so revert puts the folder back exactly.

    ``shell_set_icon`` then hands the same icon to Windows itself. Explorer keeps
    a thumbnail of each folder that outlives restarts; only Windows' own call
    replaces it, so without it the folder can stay plain.
    """

    INI = "desktop.ini"
    SECTION = ".ShellClassInfo"

    def __init__(
        self,
        attributes: Attributes,
        shell_set_icon: Callable[[Path, IconLocation], None] | None = None,
    ) -> None:
        self._attributes = attributes
        self._shell_set_icon = shell_set_icon

    def exists(self, path: Path) -> bool:
        return path.is_dir()

    def read(self, path: Path) -> LinkInfo:
        ini = self._load(path)
        icon = IconLocation()
        if ini is not None:
            resource = ini.get(self.SECTION, "IconResource")
            if resource:
                icon = parse_icon_string(resource)
            elif file := ini.get(self.SECTION, "IconFile"):
                icon = IconLocation(file, _int(ini.get(self.SECTION, "IconIndex") or "0"))
        return LinkInfo(target="", arguments="", icon=icon)

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        ini = self._load(path) or IniFile([], encoding="utf-16")
        if icon.path:
            ini.set(self.SECTION, "IconResource", f"{icon.path},{icon.index}")
        else:
            ini.remove(self.SECTION, "IconResource")
        self._write_ini(path, ini.to_bytes() if ini.has_entries() else None, HIDDEN | SYSTEM)
        if icon.path:
            folder = self._attributes.get(path) or 0
            self._attributes.set(path, folder | READ_ONLY)
            if self._shell_set_icon is not None:
                self._shell_set_icon(path, icon)

    def snapshot(self, path: Path) -> bytes | None:
        ini_path = path / self.INI
        data = ini_path.read_bytes() if ini_path.is_file() else None
        folder = self._attributes.get(path)
        state = {
            "ini": base64.b64encode(data).decode("ascii") if data is not None else None,
            "ini_attributes": self._attributes.get(ini_path) if data is not None else None,
            # Only the read-only bit: the folder's other attributes (OneDrive's
            # "always keep on this device", for one) are not ours to touch.
            "folder_read_only": None if folder is None else bool(folder & READ_ONLY),
        }
        return json.dumps(state, sort_keys=True).encode("utf-8")

    def restore(self, path: Path, state: bytes | None) -> None:
        if state is None:
            return
        saved = json.loads(state.decode("utf-8"))
        data = base64.b64decode(saved["ini"]) if saved["ini"] is not None else None
        self._write_ini(path, data, saved["ini_attributes"] or 0)
        folder = self._attributes.get(path)
        if folder is not None and saved["folder_read_only"] is not None:
            wanted = folder | READ_ONLY if saved["folder_read_only"] else folder & ~READ_ONLY
            self._attributes.set(path, wanted)

    def variants(self, path: Path) -> Mapping[str, IconLocation]:
        return {}

    def _load(self, path: Path) -> IniFile | None:
        ini_path = path / self.INI
        return IniFile.parse(ini_path.read_bytes()) if ini_path.is_file() else None

    def _write_ini(self, folder: Path, data: bytes | None, attributes: int) -> None:
        ini_path = folder / self.INI
        if ini_path.exists():
            # Windows won't overwrite or replace a hidden or system file; clear those first.
            self._attributes.set(ini_path, NORMAL)
        if data is None:
            ini_path.unlink(missing_ok=True)
            return
        atomic_write(ini_path, data)
        self._attributes.set(ini_path, attributes)


class ItemRouter:
    """Sends each item to the ItemIO for its kind."""

    def __init__(
        self,
        *,
        shortcut: ItemIO,
        web_shortcut: ItemIO,
        folder: ItemIO,
        windows_icon: ItemIO,
        store_app: ItemIO,
    ) -> None:
        self._by_kind: dict[ItemKind, ItemIO] = {
            ItemKind.SHORTCUT: shortcut,
            ItemKind.WEB_SHORTCUT: web_shortcut,
            ItemKind.FOLDER: folder,
            ItemKind.WINDOWS_ICON: windows_icon,
            ItemKind.STORE_APP: store_app,
        }

    def exists(self, path: Path) -> bool:
        return self._for(path).exists(path)

    def read(self, path: Path) -> LinkInfo:
        return self._for(path).read(path)

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        self._for(path).set_icon(path, icon)

    def snapshot(self, path: Path) -> bytes | None:
        return self._for(path).snapshot(path)

    def restore(self, path: Path, state: bytes | None) -> None:
        self._for(path).restore(path, state)

    def variants(self, path: Path) -> Mapping[str, IconLocation]:
        return self._for(path).variants(path)

    def _for(self, path: Path) -> ItemIO:
        return self._by_kind[kind_of(path)]


def windows_item_io() -> ItemRouter:
    """The real thing, for every kind of item."""
    from platform_win.shell_icons import WindowsIconIO, WindowsRegistry
    from platform_win.store_apps import StoreAppIO, explorer_path

    return ItemRouter(
        shortcut=ShellLinkIO(),
        web_shortcut=UrlFileIO(),
        folder=FolderIO(WindowsAttributes(), shell_set_folder_icon),
        windows_icon=WindowsIconIO(WindowsRegistry()),
        store_app=StoreAppIO(explorer_path()),
    )


def parse_icon_string(text: str) -> IconLocation:
    """Windows' "path,index" icon notation; the index is optional, quotes are allowed."""
    path, sep, index = text.strip().rpartition(",")
    if not sep or not index.strip().lstrip("-").isdigit():
        return IconLocation(text.strip().strip('"'))
    return IconLocation(path.strip().strip('"'), int(index))


def _int(text: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        return 0


_STGM_READ = 0x00000000
_STGM_READWRITE = 0x00000002
# Generous buffer for paths in shortcuts; long-path-aware apps can exceed MAX_PATH.
_MAX_PATH = 32767

_com_ready = threading.local()
# CoInitialize's error when the thread already runs COM in another threading
# model. COM is still usable then, so it isn't a failure for us.
_RPC_E_CHANGED_MODE = -2147417850


def ensure_com() -> None:
    """Make COM usable on the current thread (UI worker threads need this). Idempotent."""
    if getattr(_com_ready, "done", False):
        return
    import pythoncom

    try:
        pythoncom.CoInitialize()
    except pythoncom.com_error as exc:
        # com_error's first argument is the HRESULT.
        if not exc.args or exc.args[0] != _RPC_E_CHANGED_MODE:
            raise
    _com_ready.done = True


@contextmanager
def shell_errors_as_os_errors(path: Path) -> Iterator[None]:
    """A corrupt, locked or half-synced .lnk makes the shell raise com_error. It means
    the same as any unreadable file, so callers handle it the same way: as OSError."""
    import pythoncom

    try:
        yield
    except pythoncom.com_error as exc:
        raise OSError(f"Windows couldn't use the shortcut {path} ({exc})") from exc


def new_link() -> "tuple[PyIShellLink, PyIPersistFile]":
    import pythoncom
    from win32com.shell import shell

    ensure_com()
    unknown = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
    )
    link = cast("PyIShellLink", unknown)
    persist = cast("PyIPersistFile", unknown.QueryInterface(pythoncom.IID_IPersistFile))
    return link, persist
