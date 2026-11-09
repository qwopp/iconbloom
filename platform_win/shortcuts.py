"""Find .lnk shortcuts and read or change the icon they point at.

Only one field of a shortcut is ever written: its icon location. Targets,
arguments and everything else are left exactly as they are.
"""

import hashlib
import ntpath
import os
import re
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from _win32typing import PyIPersistFile, PyIShellLink


class Source(StrEnum):
    DESKTOP = "Desktop"
    PUBLIC_DESKTOP = "Public desktop"
    START_MENU = "Start menu"
    ALL_USERS_START_MENU = "Start menu (all users)"
    TASKBAR = "Taskbar"


# Folders shared by all users need admin rights to write, which v1 never asks for.
READ_ONLY_SOURCES = frozenset({Source.PUBLIC_DESKTOP, Source.ALL_USERS_START_MENU})

# Most useful first: when two shortcuts launch the same app, the tile shows
# the name and icon of the one found in the earliest source.
_SOURCE_ORDER = list(Source)


@dataclass(frozen=True)
class IconLocation:
    """Where a shortcut's icon comes from. Empty path means "use the target's icon"."""

    path: str = ""
    index: int = 0


@dataclass(frozen=True)
class LinkInfo:
    target: str
    arguments: str
    icon: IconLocation


@dataclass(frozen=True)
class Shortcut:
    path: Path
    source: Source
    info: LinkInfo

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def writable(self) -> bool:
        return self.source not in READ_ONLY_SOURCES


@dataclass(frozen=True)
class ShortcutGroup:
    """All shortcuts that launch the same thing, themed together as one tile."""

    key: str
    shortcuts: tuple[Shortcut, ...]

    @property
    def primary(self) -> Shortcut:
        return self.shortcuts[0]

    @property
    def name(self) -> str:
        return self.primary.name

    @property
    def writable_shortcuts(self) -> tuple[Shortcut, ...]:
        return tuple(s for s in self.shortcuts if s.writable)

    @property
    def writable(self) -> bool:
        return bool(self.writable_shortcuts)

    @property
    def slug(self) -> str:
        """Short stable id used in generated file names."""
        return hashlib.sha256(self.key.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class ScanRoot:
    path: Path
    source: Source
    recursive: bool


class LinkIO(Protocol):
    """Reads and writes shortcut files. The Windows version wraps IShellLink."""

    def read(self, path: Path) -> LinkInfo: ...

    def set_icon(self, path: Path, icon: IconLocation) -> None: ...


class ShellLinkIO:
    """LinkIO backed by the Windows shell's own IShellLink implementation."""

    def read(self, path: Path) -> LinkInfo:
        link, persist = _new_link()
        persist.Load(str(path), _STGM_READ)
        target, _ = link.GetPath(0, _MAX_PATH)
        icon_path, icon_index = link.GetIconLocation(_MAX_PATH)
        return LinkInfo(
            target=str(target),
            arguments=str(link.GetArguments(_MAX_PATH)),
            icon=IconLocation(str(icon_path), int(icon_index)),
        )

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        link, persist = _new_link()
        persist.Load(str(path), _STGM_READWRITE)
        link.SetIconLocation(icon.path, icon.index)
        persist.Save(str(path), True)

    def create(self, path: Path, target: str, icon: IconLocation | None = None) -> None:
        """Make a new shortcut. Used by tests to build real .lnk fixtures."""
        link, persist = _new_link()
        link.SetPath(target)
        if icon is not None:
            link.SetIconLocation(icon.path, icon.index)
        persist.Save(str(path), True)


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


def _new_link() -> "tuple[PyIShellLink, PyIPersistFile]":
    import pythoncom
    from win32com.shell import shell

    ensure_com()
    unknown = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
    )
    link = cast("PyIShellLink", unknown)
    persist = cast("PyIPersistFile", unknown.QueryInterface(pythoncom.IID_IPersistFile))
    return link, persist


def default_roots() -> list[ScanRoot]:
    """The shortcut folders Iconbloom looks in, resolved through the shell."""
    from platform_win.paths import known_folder

    appdata = known_folder("RoamingAppData")
    pinned = appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned"
    return [
        ScanRoot(known_folder("Desktop"), Source.DESKTOP, recursive=False),
        ScanRoot(known_folder("PublicDesktop"), Source.PUBLIC_DESKTOP, recursive=False),
        ScanRoot(known_folder("Programs"), Source.START_MENU, recursive=True),
        ScanRoot(known_folder("CommonPrograms"), Source.ALL_USERS_START_MENU, recursive=True),
        ScanRoot(pinned / "TaskBar", Source.TASKBAR, recursive=False),
    ]


_NOISE_NAME = re.compile(
    r"uninstall|deinstall|\bremove\b|read ?me|release notes|change ?log|\blicen[cs]e\b"
    r"|\bhelp\b|documentation|\bmanual\b|\bwebsite\b|home ?page|\bfaq\b",
    re.IGNORECASE,
)
_NOISE_TARGET = re.compile(
    r"(unins\d*\.exe|uninstall[^\\/]*\.exe|\.(txt|rtf|pdf|chm|html?|url|md))$", re.IGNORECASE
)


def is_noise(name: str, target: str) -> bool:
    """Uninstallers, readmes and help links: nobody wants to theme those."""
    return bool(_NOISE_NAME.search(name) or _NOISE_TARGET.search(target))


def scan(roots: Sequence[ScanRoot], link_io: LinkIO) -> list[ShortcutGroup]:
    """Read every shortcut under ``roots`` and group the ones that launch the same thing."""
    shortcuts: list[Shortcut] = []
    for root in roots:
        for path in _lnk_files(root):
            try:
                info = link_io.read(path)
            except OSError:
                continue  # unreadable or half-written link; leave it alone
            if not is_noise(path.stem, info.target):
                shortcuts.append(Shortcut(path=path, source=root.source, info=info))
    return group(shortcuts)


def group(shortcuts: Iterable[Shortcut]) -> list[ShortcutGroup]:
    groups: dict[str, list[Shortcut]] = {}
    for shortcut in shortcuts:
        groups.setdefault(group_key(shortcut), []).append(shortcut)
    result = [
        ShortcutGroup(key, tuple(sorted(members, key=_preference)))
        for key, members in groups.items()
    ]
    return sorted(result, key=lambda g: g.name.casefold())


def group_key(shortcut: Shortcut) -> str:
    """Shortcuts with the same target and arguments are the same app.

    Store-app and installer-advertised shortcuts have no target path, so each
    of those stands alone, keyed by its own location.
    """
    target = shortcut.info.target.strip()
    if not target:
        return "lnk:" + normalize_path(str(shortcut.path))
    expanded = normalize_path(os.path.expandvars(target))
    return f"target:{expanded}|{shortcut.info.arguments.strip().casefold()}"


def normalize_path(path: str) -> str:
    """Windows paths compare case-insensitively and with either slash."""
    return ntpath.normcase(ntpath.normpath(path))


def _preference(shortcut: Shortcut) -> tuple[int, int, str]:
    return (not shortcut.writable, _SOURCE_ORDER.index(shortcut.source), str(shortcut.path))


def _lnk_files(root: ScanRoot) -> list[Path]:
    if not root.path.is_dir():
        return []
    pattern = "**/*.lnk" if root.recursive else "*.lnk"
    return sorted(p for p in root.path.glob(pattern, case_sensitive=False) if p.is_file())
