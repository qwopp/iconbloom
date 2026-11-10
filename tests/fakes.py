"""Stand-ins for Windows pieces, so every kind of item is testable on any OS."""

import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path, PureWindowsPath
from types import MappingProxyType

from PIL import Image

from app.elevation import ELEVATED_FLAG, WindowsElevator, handle_request
from app.service import IconService
from app.taskbar import TaskbarService
from platform_win import taskbar as tb
from platform_win.backup import TaskbarBackup
from platform_win.elevate import ElevationDeclinedError
from platform_win.extract import SHARP_MIN, ExtractedIcon
from platform_win.item_io import FileStateIO, FolderIO, ItemRouter, UrlFileIO
from platform_win.paths import AppPaths
from platform_win.shell_icons import RECYCLE_BIN, WINDOWS_ICONS, RegValue, WindowsIconIO
from platform_win.shortcuts import (
    IconLocation,
    LinkInfo,
    ScanRoot,
    Source,
    desktop_folders_root,
)

SAMPLES_DIR = Path(__file__).parent / "samples"


class FakeLinkIO(FileStateIO):
    """Shortcuts stored as small JSON files with a .lnk name.

    Writing rewrites the whole file like IShellLink does, so byte-level
    backup and restore behave as they would on Windows.
    """

    def create(self, path: Path, target: str, icon: IconLocation | None = None) -> None:
        icon = icon or IconLocation()
        data = {"target": target, "args": "", "icon": icon.path, "index": icon.index}
        path.write_text(json.dumps(data), encoding="utf-8")

    def read(self, path: Path) -> LinkInfo:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OSError(f"not a shortcut: {path}") from exc
        return LinkInfo(data["target"], data["args"], IconLocation(data["icon"], data["index"]))

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["icon"], data["index"] = icon.path, icon.index
        # Key order changes on purpose: a real save does not keep bytes stable either.
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


class FakeAttributes:
    """File attributes kept in memory; every existing path starts with none set."""

    def __init__(self) -> None:
        self.values: dict[Path, int] = {}

    def get(self, path: Path) -> int | None:
        return self.values.get(path, 0) if path.exists() else None

    def set(self, path: Path, value: int) -> None:
        self.values[path] = value


class FakeRegistry:
    """The user's Explorer CLSID key as a dict of {key: {value name: value}}."""

    # What Windows itself ships for the Recycle Bin, by value name.
    SYSTEM: Mapping[str, str] = MappingProxyType(
        {
            "": r"%SystemRoot%\System32\imageres.dll,-55",
            "empty": r"%SystemRoot%\System32\imageres.dll,-55",
            "full": r"%SystemRoot%\System32\imageres.dll,-54",
        }
    )

    def __init__(self) -> None:
        self.keys: dict[str, dict[str, RegValue]] = {}

    def read_values(self, key: str, names: Sequence[str]) -> dict[str, RegValue | None]:
        values = self.keys.get(key, {})
        return {name: values.get(name) for name in names}

    def key_exists(self, key: str) -> bool:
        return any(k == key or k.startswith(key + "\\") for k in self.keys)

    def write_value(self, key: str, name: str, value: RegValue) -> None:
        self.keys.setdefault(key, {})[name] = value

    def delete_value(self, key: str, name: str) -> None:
        self.keys.get(key, {}).pop(name, None)

    def delete_key_if_empty(self, key: str) -> None:
        has_subkeys = any(k.startswith(key + "\\") for k in self.keys)
        if key in self.keys and not self.keys[key] and not has_subkeys:
            del self.keys[key]

    def system_default(self, clsid: str, name: str) -> str | None:
        return self.SYSTEM.get(name) if clsid == RECYCLE_BIN.clsid else None


class FakeUserRegistry:
    """HKEY_CURRENT_USER as a dict of {(key, value name): (type, data)}."""

    def __init__(self, values: Mapping[tuple[str, str], tb.RegValue] | None = None) -> None:
        self.values: dict[tuple[str, str], tb.RegValue] = dict(values or {})
        # Set to make every write after this many fail, like a policy-locked value.
        self.fail_after: int | None = None
        self.writes = 0

    def read(self, key: str, name: str) -> tb.RegValue | None:
        return self.values.get((key, name))

    def write(self, key: str, name: str, value: tb.RegValue) -> None:
        if self.fail_after is not None and self.writes >= self.fail_after:
            raise PermissionError(f"access denied: {key}\\{name}")
        self.writes += 1
        self.values[(key, name)] = value

    def delete(self, key: str, name: str) -> None:
        self.values.pop((key, name), None)


class FakeAppBar:
    def __init__(self) -> None:
        self.hidden = False

    def auto_hide(self) -> bool:
        return self.hidden

    def set_auto_hide(self, on: bool) -> None:
        self.hidden = on


# The user's own Windows 11 taskbar when this was written: dark, Windows' gray, frosted glass
# off, centered, a search box, no Task view.
USER_TASKBAR: Mapping[tuple[str, str], tb.RegValue] = MappingProxyType(
    {
        tb.LIGHT_MODE: (tb.REG_DWORD, 0),
        tb.TRANSPARENCY: (tb.REG_DWORD, 0),
        tb.ACCENT_ON_TASKBAR: (tb.REG_DWORD, 0),
        tb.PALETTE: (
            tb.REG_BINARY,
            bytes.fromhex("69fcff0029f7ff0000d5e10000b7c300009faa000067700000343b004a545900"),
        ),
        tb.ACCENT_MENU: (tb.REG_DWORD, 0xFFC3B700),
        tb.START_MENU: (tb.REG_DWORD, 0xFFAA9F00),
        tb.DWM_ACCENT: (tb.REG_DWORD, 0xFFC3B700),
        tb.DWM_COLOR: (tb.REG_DWORD, 0xC400B7C3),
        tb.DWM_AFTERGLOW: (tb.REG_DWORD, 0xC400B7C3),
        tb.AUTO_COLOR: (tb.REG_DWORD, 1),
        tb.SEARCH_MODE: (tb.REG_DWORD, 2),
        tb.TASK_VIEW: (tb.REG_DWORD, 0),
    }
)


class FakeTaskbar:
    """A taskbar's settings in memory, with the same TaskbarIO the app uses."""

    def __init__(
        self,
        values: Mapping[tuple[str, str], tb.RegValue] = USER_TASKBAR,
        *,
        win11: bool = True,
    ) -> None:
        self.registry = FakeUserRegistry(values)
        self.appbar = FakeAppBar()
        self.broadcasts: list[str] = []
        self.io = tb.TaskbarIO(self.registry, self.appbar, self.broadcasts.append, win11=win11)

    def service(self, backup: Path) -> TaskbarService:
        return TaskbarService(self.io, TaskbarBackup(backup))

    def state(self) -> tuple[dict[tuple[str, str], tb.RegValue], bool]:
        """Everything a revert must put back exactly."""
        return dict(self.registry.values), self.appbar.hidden


class FakeDesktop:
    """A temp-folder stand-in for the user's shortcut folders, wired to an IconService.

    ``icons`` maps app name to a sample icon; apps not listed get ``default``.
    Apps named in ``unreadable`` fail extraction, like a broken program file.
    """

    def __init__(
        self,
        root: Path,
        icons: Mapping[str, str] | None = None,
        default: str = "multicolor",
        unreadable: Collection[str] = (),
        windows_icons: bool = False,
    ) -> None:
        self.desktop = root / "Desktop"
        self.common = root / "Common"
        self.desktop.mkdir()
        self.common.mkdir()
        self.paths = AppPaths(root / "Iconbloom")
        self.link_io = FakeLinkIO()
        self.attributes = FakeAttributes()
        self.registry = FakeRegistry()
        self.taskbar = FakeTaskbar()
        self.io = ItemRouter(
            shortcut=self.link_io,
            web_shortcut=UrlFileIO(),
            folder=FolderIO(self.attributes),
            windows_icon=WindowsIconIO(self.registry),
        )
        self.windows_icons = WINDOWS_ICONS if windows_icons else ()
        self.notified = 0
        self.refreshed: list[Path] = []
        self.roots = [
            ScanRoot(self.desktop, Source.DESKTOP, folders=True),
            ScanRoot(self.common, Source.ALL_USERS_START_MENU, max_depth=None),
            desktop_folders_root(self.desktop),
        ]
        # Plays Windows' permission prompt: True = the user says No.
        self.decline_permission = False
        self.elevations: list[list[str]] = []
        self._icons = dict(icons or {})
        self._default = default
        self._unreadable = set(unreadable)

    def make(self, name: str, folder: Path | None = None, icon: str = "") -> Path:
        path = (folder or self.desktop) / f"{name}.lnk"
        self.link_io.create(path, rf"C:\Apps\{name}.exe", IconLocation(icon, 1 if icon else 0))
        return path

    def make_url(
        self, name: str, url: str, icon_file: str = "", folder: Path | None = None
    ) -> Path:
        """A .url shortcut laid out the way Steam writes them."""
        path = (folder or self.desktop) / f"{name}.url"
        lines = [
            "[{000214A0-0000-0000-C000-000000000046}]",
            "Prop3=19,0",
            "[InternetShortcut]",
            "IDList=",
            "IconIndex=0",
            f"URL={url}",
        ]
        if icon_file:
            lines.append(f"IconFile={icon_file}")
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
        return path

    def make_folder(self, name: str) -> Path:
        path = self.desktop / name
        path.mkdir()
        return path

    def service(self) -> IconService:
        return IconService(
            self.paths,
            self.io,
            self.roots,
            windows_icons=self.windows_icons,
            extractor=self.extract,
            notify=self._notify,
            elevator=WindowsElevator(self.paths, launch=self._launch_elevated),
            taskbar=self.taskbar.service(self.paths.taskbar),
        )

    def _launch_elevated(self, arguments: Sequence[str]) -> int:
        """Stand-in for starting the elevated copy: same request file, same checks."""
        self.elevations.append(list(arguments))
        if self.decline_permission:
            raise ElevationDeclinedError
        flag, request = arguments
        assert flag == ELEVATED_FLAG
        admin = IconService(self.paths, self.io, roots=[])
        return handle_request(Path(request), admin, [self.common])

    def extract(
        self, icon: IconLocation, target: str, shortcut: Path, *, use_shell: bool = True
    ) -> ExtractedIcon:
        """Stand-in extractor: the sample icon for the app, labelled with where it came from."""
        app = PureWindowsPath(target).stem
        if app in self._unreadable:
            raise OSError(f"{app}: unreadable icon")
        sample = self._icons.get(app, self._default)
        with Image.open(SAMPLES_DIR / f"{sample}.png") as img:
            image = img.convert("RGBA")
        source = icon.path if not use_shell else f"{icon.path} (shell allowed)"
        return ExtractedIcon(image, max(image.size) < SHARP_MIN, source)

    def _notify(self, paths: Sequence[Path]) -> None:
        self.notified += 1
        self.refreshed.extend(paths)
