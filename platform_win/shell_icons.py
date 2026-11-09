"""Windows' own desktop icons: Recycle Bin, This PC, Network and your user folder.

Their icons are per-user registry settings, the same ones Windows' "Desktop
icon settings > Change Icon" writes, under
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CLSID\\{CLSID}\\DefaultIcon.
No administrator permission is needed. The saved state is those values (and
whether their keys existed), so revert puts the registry back exactly.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from platform_win.item_io import parse_icon_string
from platform_win.shortcuts import IconLocation, LinkInfo, WindowsIcon, variant_path

RECYCLE_BIN = WindowsIcon("{645FF040-5081-101B-9F08-00AA002F954E}", "Recycle Bin")
WINDOWS_ICONS = (
    RECYCLE_BIN,
    WindowsIcon("{20D04FE0-3AEA-1069-A2D8-08002B30309D}", "This PC"),
    WindowsIcon("{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}", "Network"),
    WindowsIcon("{59031A47-3F72-44A7-89C5-5595FE6B30EE}", "User folder"),
)
USER_CLSID_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\CLSID"
REG_SZ = 1
REG_EXPAND_SZ = 2

# The Recycle Bin shows "empty" or "full"; every icon also has an unnamed default.
_DEFAULT = ""
_EMPTY = "empty"
_FULL = "full"

type RegValue = tuple[int, str]


class Registry(Protocol):
    """The few registry operations Windows icons need, relative to the user's CLSID key."""

    def read_values(self, key: str, names: Sequence[str]) -> dict[str, RegValue | None]: ...

    def key_exists(self, key: str) -> bool: ...

    def write_value(self, key: str, name: str, value: RegValue) -> None: ...

    def delete_value(self, key: str, name: str) -> None: ...

    def delete_key_if_empty(self, key: str) -> None: ...

    def system_default(self, clsid: str, name: str) -> str | None:
        """The icon Windows itself sets, from HKEY_CLASSES_ROOT\\CLSID\\{clsid}\\DefaultIcon."""
        ...


class WindowsIconIO:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def exists(self, path: Path) -> bool:
        return True

    def read(self, path: Path) -> LinkInfo:
        clsid = _clsid(path)
        values = self._registry.read_values(_icon_key(clsid), self._names(clsid))
        current = values.get(_EMPTY) or values.get(_DEFAULT)
        icon = parse_icon_string(current[1]) if current else IconLocation()
        return LinkInfo(target="", arguments="", icon=icon)

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        clsid = _clsid(path)
        key = _icon_key(clsid)
        if not icon.path:
            for name in self._names(clsid):
                self._registry.delete_value(key, name)
            return
        text = f"{icon.path},{icon.index}"
        self._registry.write_value(key, _DEFAULT, (REG_EXPAND_SZ, text))
        if clsid == RECYCLE_BIN.clsid:
            self._registry.write_value(key, _EMPTY, (REG_EXPAND_SZ, text))
            full = variant_path(Path(icon.path), _FULL)
            if full.is_file():
                full_text = f"{full},{icon.index}"
            else:
                full_text = self._registry.system_default(clsid, _FULL) or text
            self._registry.write_value(key, _FULL, (REG_EXPAND_SZ, full_text))

    def snapshot(self, path: Path) -> bytes | None:
        clsid = _clsid(path)
        key = _icon_key(clsid)
        values = self._registry.read_values(key, self._names(clsid))
        state = {
            "clsid_key": self._registry.key_exists(clsid),
            "icon_key": self._registry.key_exists(key),
            "values": {name: list(value) if value else None for name, value in values.items()},
        }
        return json.dumps(state, sort_keys=True).encode("utf-8")

    def restore(self, path: Path, state: bytes | None) -> None:
        if state is None:
            return
        clsid = _clsid(path)
        key = _icon_key(clsid)
        saved = json.loads(state.decode("utf-8"))
        for name, value in saved["values"].items():
            if value is None:
                self._registry.delete_value(key, name)
            else:
                self._registry.write_value(key, name, (int(value[0]), str(value[1])))
        # Remove only the keys this app created; never ones that were there before.
        if not saved["icon_key"]:
            self._registry.delete_key_if_empty(key)
        if not saved["clsid_key"]:
            self._registry.delete_key_if_empty(clsid)

    def variants(self, path: Path) -> Mapping[str, IconLocation]:
        clsid = _clsid(path)
        if clsid != RECYCLE_BIN.clsid:
            return {}
        full = self._registry.system_default(clsid, _FULL)
        return {_FULL: parse_icon_string(full)} if full else {}

    def _names(self, clsid: str) -> list[str]:
        return [_DEFAULT, _EMPTY, _FULL] if clsid == RECYCLE_BIN.clsid else [_DEFAULT]


class WindowsRegistry:
    """Registry access through winreg, rooted at the current user's Explorer CLSID key."""

    def __init__(self, base: str = USER_CLSID_KEY) -> None:
        self._base = base

    def read_values(self, key: str, names: Sequence[str]) -> dict[str, RegValue | None]:
        import winreg

        found: dict[str, RegValue | None] = dict.fromkeys(names)
        try:
            handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._path(key))
        except FileNotFoundError:
            return found
        with handle:
            for name in names:
                try:
                    data, kind = winreg.QueryValueEx(handle, name)
                except FileNotFoundError:
                    continue
                found[name] = (int(kind), str(data))
        return found

    def key_exists(self, key: str) -> bool:
        import winreg

        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._path(key)).Close()
        except FileNotFoundError:
            return False
        return True

    def write_value(self, key: str, name: str, value: RegValue) -> None:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, self._path(key), 0, winreg.KEY_SET_VALUE
        ) as handle:
            winreg.SetValueEx(handle, name, 0, value[0], value[1])

    def delete_value(self, key: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._path(key), 0, winreg.KEY_SET_VALUE
            ) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass  # already gone, which is what we wanted

    def delete_key_if_empty(self, key: str) -> None:
        import winreg

        path = self._path(key)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as handle:
                subkeys, values, _ = winreg.QueryInfoKey(handle)
            if subkeys == 0 and values == 0:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass

    def system_default(self, clsid: str, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\DefaultIcon") as h:
                data, _ = winreg.QueryValueEx(h, name)
        except FileNotFoundError:
            return None
        return str(data) or None

    def _path(self, key: str) -> str:
        return f"{self._base}\\{key}"


def _clsid(path: Path) -> str:
    return str(path).removeprefix("::")


def _icon_key(clsid: str) -> str:
    return f"{clsid}\\DefaultIcon"
