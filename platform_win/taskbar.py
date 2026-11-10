"""The taskbar's look: the per-user Windows settings behind it, read, written and put back.

Every value here is one Windows' own Settings app changes (Personalization > Colors and
Taskbar), stored per user under HKEY_CURRENT_USER, so no administrator permission is
needed. Measured on Windows 11 26H2: each value takes effect as soon as it is written,
the taskbar paints shade 5 of the accent palette, and Windows keeps its text white.

Saved states ("snapshots") are plain JSON-ready dicts, so the backup file can compare
and store them without knowing about registry types.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

log = logging.getLogger(__name__)

type RGB = tuple[int, int, int]
type RegData = int | bytes | str
type RegValue = tuple[int, RegData]
# {"<key>\\<name>": [type, data] or None, ..., "auto_hide": bool}; bytes are stored as hex.
type Snapshot = dict[str, object]

REG_SZ = 1
REG_BINARY = 3
REG_DWORD = 4

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ACCENT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
DWM = r"Software\Microsoft\Windows\DWM"
DESKTOP = r"Control Panel\Desktop"
ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
SEARCH = r"Software\Microsoft\Windows\CurrentVersion\Search"
STUCK_RECTS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3"

LIGHT_MODE = (PERSONALIZE, "SystemUsesLightTheme")
TRANSPARENCY = (PERSONALIZE, "EnableTransparency")
ACCENT_ON_TASKBAR = (PERSONALIZE, "ColorPrevalence")
PALETTE = (ACCENT, "AccentPalette")
ACCENT_MENU = (ACCENT, "AccentColorMenu")
START_MENU = (ACCENT, "StartColorMenu")
DWM_ACCENT = (DWM, "AccentColor")
DWM_COLOR = (DWM, "ColorizationColor")
DWM_AFTERGLOW = (DWM, "ColorizationAfterglow")
AUTO_COLOR = (DESKTOP, "AutoColorization")
ALIGNMENT = (ADVANCED, "TaskbarAl")
SMALL_WIN11 = (ADVANCED, "IconSizePreference")
SMALL_WIN10 = (ADVANCED, "TaskbarSmallIcons")
TASK_VIEW = (ADVANCED, "ShowTaskViewButton")
SEARCH_MODE = (SEARCH, "SearchboxTaskbarMode")

# What the user would call each value, for reports.
LABELS: Mapping[tuple[str, str], str] = {
    LIGHT_MODE: "Windows mode",
    TRANSPARENCY: "frosted glass",
    ACCENT_ON_TASKBAR: "taskbar color",
    PALETTE: "taskbar color",
    ACCENT_MENU: "taskbar color",
    START_MENU: "taskbar color",
    DWM_ACCENT: "taskbar color",
    DWM_COLOR: "taskbar color",
    DWM_AFTERGLOW: "taskbar color",
    AUTO_COLOR: "taskbar color",
    ALIGNMENT: "alignment",
    SMALL_WIN11: "smaller buttons",
    SMALL_WIN10: "smaller buttons",
    TASK_VIEW: "Task view",
    SEARCH_MODE: "search",
}
AUTO_HIDE = "auto_hide"
AUTO_HIDE_LABEL = "hide automatically"
VALUES = tuple(LABELS)

WIN11_BUILD = 22000
# The accent shade the taskbar paints, and the ones Windows uses for its accent and Start.
TASKBAR_SLOT = 5
_MENU_SLOT = 3
_START_SLOT = 4
# IconSizePreference: 0 always small; 2 is Windows' default, small only when the bar is full.
_SMALL = 0
_NOT_SMALL = 2
# Byte 8 of StuckRects3's Settings is what Explorer reads at start: 3 hides, 2 shows.
_STUCK_AUTO_HIDE_BYTE = 8


class Search(IntEnum):
    """SearchboxTaskbarMode's values."""

    HIDDEN = 0
    ICON = 1
    BOX = 2
    BUTTON = 3  # Windows 11 only: a small "Search" pill


@dataclass(frozen=True)
class TaskbarState:
    """What the taskbar looks like, in Windows' own terms."""

    # The color the taskbar shows, or None for Windows' own dark or light gray.
    accent: RGB | None
    transparency: bool
    centered: bool
    small: bool
    search: Search
    task_view: bool
    auto_hide: bool
    # Read only: writing turns Windows dark only when an accent needs it.
    light_windows: bool = False


class UserRegistry(Protocol):
    """HKEY_CURRENT_USER, one value at a time."""

    def read(self, key: str, name: str) -> RegValue | None: ...

    def write(self, key: str, name: str, value: RegValue) -> None: ...

    def delete(self, key: str, name: str) -> None: ...


class AppBar(Protocol):
    def auto_hide(self) -> bool: ...

    def set_auto_hide(self, on: bool) -> None: ...


class TaskbarIO:
    def __init__(
        self,
        registry: UserRegistry,
        appbar: AppBar,
        broadcast: Callable[[str], None],
        *,
        win11: bool,
    ) -> None:
        self._registry = registry
        self._appbar = appbar
        self._broadcast = broadcast
        self.win11 = win11

    def search_modes(self) -> tuple[Search, ...]:
        return tuple(Search) if self.win11 else (Search.HIDDEN, Search.ICON, Search.BOX)

    def read(self) -> TaskbarState:
        light = self._int(LIGHT_MODE, 1) == 1
        accent = None
        if self._int(ACCENT_ON_TASKBAR, 0) == 1 and not light:
            accent = _palette_color(self._registry.read(*PALETTE), TASKBAR_SLOT)
        small = (
            self._int(SMALL_WIN11, _NOT_SMALL) == _SMALL
            if self.win11
            else self._int(SMALL_WIN10, 0) == 1
        )
        search = self._int(SEARCH_MODE, Search.BOX)
        return TaskbarState(
            accent=accent,
            transparency=self._int(TRANSPARENCY, 1) != 0,
            centered=self.win11 and self._int(ALIGNMENT, 1) != 0,
            small=small,
            search=Search(search) if search in {mode.value for mode in Search} else Search.BOX,
            task_view=self._int(TASK_VIEW, 1) != 0,
            auto_hide=self._appbar.auto_hide(),
            light_windows=light,
        )

    def plan(self, wanted: TaskbarState, shades: Sequence[RGB] = ()) -> dict[str, RegValue]:
        """The registry writes that turn the current taskbar into ``wanted``, by value id.

        ``shades`` are the accent palette's eight shades, ``wanted.accent`` at TASKBAR_SLOT.
        """
        now = self.read()
        writes: dict[tuple[str, str], RegValue] = {}
        if wanted.accent is not None and (wanted.accent != now.accent or now.light_windows):
            if len(shades) != 8 or shades[TASKBAR_SLOT] != wanted.accent:
                raise ValueError("shades must be the 8 accent shades with the color at slot 5")
            writes.update(self._accent_writes(shades))
            writes[ACCENT_ON_TASKBAR] = (REG_DWORD, 1)
            if now.light_windows:
                writes[LIGHT_MODE] = (REG_DWORD, 0)
        elif wanted.accent is None and now.accent is not None:
            writes[ACCENT_ON_TASKBAR] = (REG_DWORD, 0)
        if wanted.transparency != now.transparency:
            writes[TRANSPARENCY] = (REG_DWORD, int(wanted.transparency))
        if self.win11 and wanted.centered != now.centered:
            writes[ALIGNMENT] = (REG_DWORD, int(wanted.centered))
        if wanted.small != now.small:
            if self.win11:
                writes[SMALL_WIN11] = (REG_DWORD, _SMALL if wanted.small else _NOT_SMALL)
            else:
                writes[SMALL_WIN10] = (REG_DWORD, int(wanted.small))
        if wanted.search != now.search and wanted.search in self.search_modes():
            writes[SEARCH_MODE] = (REG_DWORD, int(wanted.search))
        if wanted.task_view != now.task_view:
            writes[TASK_VIEW] = (REG_DWORD, int(wanted.task_view))
        planned: dict[str, RegValue] = {_id(value): data for value, data in writes.items()}
        if wanted.auto_hide != now.auto_hide:
            planned[AUTO_HIDE] = (REG_DWORD, int(wanted.auto_hide))
        return planned

    def write(self, planned: Mapping[str, RegValue]) -> None:
        for value_id, value in planned.items():
            if value_id == AUTO_HIDE:
                continue
            key, name = _split(value_id)
            self._registry.write(key, name, value)
        self._broadcast("ImmersiveColorSet")
        self._broadcast("TraySettings")
        if AUTO_HIDE in planned:
            self._appbar.set_auto_hide(bool(planned[AUTO_HIDE][1]))

    def snapshot(self) -> Snapshot:
        state: Snapshot = {_id(value): encode(self._registry.read(*value)) for value in VALUES}
        state[AUTO_HIDE] = self._appbar.auto_hide()
        return state

    def restore(self, saved: Snapshot) -> None:
        """Put back each value in ``saved``; a None value is deleted, as it was absent."""
        for value_id, value in saved.items():
            if value_id == AUTO_HIDE:
                continue
            key, name = _split(value_id)
            decoded = decode(value)
            if decoded is None:
                self._registry.delete(key, name)
            else:
                self._registry.write(key, name, decoded)
        self._broadcast("ImmersiveColorSet")
        self._broadcast("TraySettings")
        if isinstance(saved.get(AUTO_HIDE), bool):
            self._appbar.set_auto_hide(bool(saved[AUTO_HIDE]))

    def _accent_writes(self, shades: Sequence[RGB]) -> dict[tuple[str, str], RegValue]:
        palette = b"".join(bytes((*shade, 0)) for shade in shades)
        menu, start = shades[_MENU_SLOT], shades[_START_SLOT]
        auto_color = self._registry.read(*AUTO_COLOR)
        # Keep its type: it is a DWORD on current Windows, a string on some older ones.
        off = (
            (REG_SZ, "0") if auto_color is not None and auto_color[0] == REG_SZ else (REG_DWORD, 0)
        )
        return {
            AUTO_COLOR: off,
            PALETTE: (REG_BINARY, palette),
            ACCENT_MENU: (REG_DWORD, _abgr(menu)),
            START_MENU: (REG_DWORD, _abgr(start)),
            DWM_ACCENT: (REG_DWORD, _abgr(menu)),
            DWM_COLOR: (REG_DWORD, _argb(menu)),
            DWM_AFTERGLOW: (REG_DWORD, _argb(menu)),
        }

    def _int(self, value: tuple[str, str], default: int) -> int:
        found = self._registry.read(*value)
        if found is None or not isinstance(found[1], int | str):
            return default
        try:
            return int(found[1])
        except ValueError:
            return default


def adopt_outside_changes(
    original: Mapping[str, object] | None,
    applied: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> Snapshot:
    """The originals to keep before applying again.

    The first time, everything as it is now is the original. After that, a value the user
    changed outside Iconbloom since it last applied is theirs: it becomes its original, so a
    later revert doesn't undo it. With an original but no applied state (a crash part way
    through applying), the recorded original stands.
    """
    if original is None:
        return dict(current)
    if applied is None:
        return dict(original)
    adopted = dict(original)
    for value_id, value in current.items():
        if value != applied.get(value_id):
            adopted[value_id] = value
    return adopted


def revert_plan(
    original: Mapping[str, object],
    applied: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> Snapshot:
    """The originals to put back: only values still as Iconbloom left them, and different now."""
    return {
        value_id: value
        for value_id, value in original.items()
        if (applied is None or current.get(value_id) == applied.get(value_id))
        and current.get(value_id) != value
    }


def labels(value_ids: Sequence[str]) -> list[str]:
    """Readable names for changed values, each once, in the order the page shows them."""
    names = {
        AUTO_HIDE_LABEL if value_id == AUTO_HIDE else LABELS.get(_split(value_id))
        for value_id in value_ids
    }
    return [name for name in _LABEL_ORDER if name in names]


_LABEL_ORDER = (
    "taskbar color",
    "Windows mode",
    "frosted glass",
    "alignment",
    "smaller buttons",
    "search",
    "Task view",
    AUTO_HIDE_LABEL,
)


def encode(value: RegValue | None) -> list[object] | None:
    if value is None:
        return None
    kind, data = value
    return [kind, data.hex() if isinstance(data, bytes) else data]


def decode(saved: object) -> RegValue | None:
    if saved is None:
        return None
    if not isinstance(saved, list) or len(saved) != 2 or not isinstance(saved[0], int):
        raise ValueError(f"not a saved registry value: {saved!r}")
    kind, data = saved
    if kind == REG_BINARY and isinstance(data, str):
        return kind, bytes.fromhex(data)
    if isinstance(data, int | str) and not isinstance(data, bool):
        return kind, data
    raise ValueError(f"not a saved registry value: {saved!r}")


def _id(value: tuple[str, str]) -> str:
    return f"{value[0]}\\{value[1]}"


def _split(value_id: str) -> tuple[str, str]:
    key, _, name = value_id.rpartition("\\")
    return key, name


def _palette_color(value: RegValue | None, slot: int) -> RGB | None:
    if value is None or not isinstance(value[1], bytes) or len(value[1]) < (slot + 1) * 4:
        return None
    r, g, b = value[1][slot * 4 : slot * 4 + 3]
    return (r, g, b)


def _abgr(color: RGB) -> int:
    r, g, b = color
    return (0xFF << 24) | (b << 16) | (g << 8) | r


def _argb(color: RGB) -> int:
    r, g, b = color
    return (0xC4 << 24) | (r << 16) | (g << 8) | b


# ---- Windows ------------------------------------------------------------------------


def is_win11() -> bool:
    import sys

    return sys.platform == "win32" and sys.getwindowsversion().build >= WIN11_BUILD


class WindowsUserRegistry:
    def read(self, key: str, name: str) -> RegValue | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                data, kind = winreg.QueryValueEx(handle, name)
        except FileNotFoundError:
            return None
        if isinstance(data, int | bytes | str):
            return int(kind), data
        return None

    def write(self, key: str, name: str, value: RegValue) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as h:
            winreg.SetValueEx(h, name, 0, value[0], value[1])

    def delete(self, key: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as h:
                winreg.DeleteValue(h, name)
        except FileNotFoundError:
            pass  # already absent, which is what restoring "absent" means


class WindowsAppBar:
    """Auto-hide through the shell's app bar messages, the way Settings does it.

    Explorer keeps the state in memory and saves it to StuckRects3 later, so a forced
    Explorer restart (Refresh Windows icons) could bring back the old state. Writing the
    saved byte too keeps the two in step.
    """

    def __init__(self, registry: UserRegistry | None = None) -> None:
        self._registry = registry or WindowsUserRegistry()

    def auto_hide(self) -> bool:
        return bool(_app_bar_message(_ABM_GETSTATE, 0) & _ABS_AUTOHIDE)

    def set_auto_hide(self, on: bool) -> None:
        _app_bar_message(_ABM_SETSTATE, _ABS_AUTOHIDE if on else _ABS_ALWAYSONTOP)
        saved = self._registry.read(STUCK_RECTS, "Settings")
        if saved is not None and isinstance(saved[1], bytes) and len(saved[1]) > 8:
            data = bytearray(saved[1])
            data[_STUCK_AUTO_HIDE_BYTE] = 3 if on else 2
            self._registry.write(STUCK_RECTS, "Settings", (REG_BINARY, bytes(data)))


_ABM_GETSTATE = 4
_ABM_SETSTATE = 10
_ABS_AUTOHIDE = 1
_ABS_ALWAYSONTOP = 2


def _app_bar_message(message: int, state: int) -> int:
    import ctypes
    from ctypes import wintypes

    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uCallbackMessage", wintypes.UINT),
            ("uEdge", wintypes.UINT),
            ("rc", wintypes.RECT),
            ("lParam", wintypes.LPARAM),
        ]

    user32 = ctypes.WinDLL("user32")
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    data = APPBARDATA(
        cbSize=ctypes.sizeof(APPBARDATA), hWnd=user32.FindWindowW("Shell_TrayWnd", None)
    )
    data.lParam = state
    return int(shell32.SHAppBarMessage(message, ctypes.byref(data)))


def broadcast_setting_change(area: str) -> None:
    """Tell running programs a setting changed, without waiting on any that hang."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPCWSTR,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    result = ctypes.c_size_t()
    sent = user32.SendMessageTimeoutW(
        _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, area, _SMTO_ABORTIFHUNG, 2000, ctypes.byref(result)
    )
    if not sent:
        log.debug("setting-change broadcast %s timed out", area)


_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A
_SMTO_ABORTIFHUNG = 0x0002


def windows_taskbar_io() -> TaskbarIO:
    registry = WindowsUserRegistry()
    return TaskbarIO(registry, WindowsAppBar(registry), broadcast_setting_change, win11=is_win11())
