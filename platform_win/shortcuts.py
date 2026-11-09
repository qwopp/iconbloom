"""What Iconbloom can restyle, where it finds it, and which items belong together.

"Shortcut" covers everything with a changeable icon: .lnk and .url shortcut
files, folders on the desktop, and Windows' own desktop icons such as the
Recycle Bin. How each kind is read and changed lives in ``item_io``; only the
icon is ever changed, never what an item opens.
"""

import hashlib
import logging
import ntpath
import os
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class Source(StrEnum):
    DESKTOP = "Desktop"
    WINDOWS = "Windows icons"
    PUBLIC_DESKTOP = "Public desktop"
    TASKBAR = "Taskbar"
    START_MENU = "Start menu"
    ALL_USERS_START_MENU = "Start menu (all users)"
    DESKTOP_FOLDERS = "In desktop folders"


class Place(StrEnum):
    """Where a person sees the shortcut, for filtering the grid."""

    DESKTOP = "Desktop"
    TASKBAR = "Taskbar"
    START_MENU = "Start menu"


class ItemKind(StrEnum):
    SHORTCUT = "Shortcut"
    WEB_SHORTCUT = "Web or game shortcut"
    FOLDER = "Folder"
    WINDOWS_ICON = "Windows icon"


# Windows' own name for a shell object such as the Recycle Bin: "::{CLSID}".
WINDOWS_ICON_PREFIX = "::{"


def kind_of(path: Path) -> ItemKind:
    if str(path).startswith(WINDOWS_ICON_PREFIX):
        return ItemKind.WINDOWS_ICON
    suffix = path.suffix.casefold()
    if suffix == ".lnk" and not path.is_dir():
        return ItemKind.SHORTCUT
    if suffix == ".url" and not path.is_dir():
        return ItemKind.WEB_SHORTCUT
    return ItemKind.FOLDER


_PLACES = {
    Source.DESKTOP: Place.DESKTOP,
    Source.WINDOWS: Place.DESKTOP,
    Source.PUBLIC_DESKTOP: Place.DESKTOP,
    Source.TASKBAR: Place.TASKBAR,
    Source.START_MENU: Place.START_MENU,
    Source.ALL_USERS_START_MENU: Place.START_MENU,
    Source.DESKTOP_FOLDERS: Place.DESKTOP,
}


# Folders shared by every user on the PC; changing them needs administrator permission.
SHARED_SOURCES = frozenset({Source.PUBLIC_DESKTOP, Source.ALL_USERS_START_MENU})

# Most useful first: when two shortcuts launch the same app, the tile shows
# the name and icon of the one found in the earliest source.
_SOURCE_ORDER = list(Source)


@dataclass(frozen=True)
class IconLocation:
    """Where an item's icon comes from. Empty path means the item's default icon."""

    path: str = ""
    index: int = 0


@dataclass(frozen=True)
class LinkInfo:
    target: str
    arguments: str
    icon: IconLocation
    # The shortcut's AppUserModelID. Windows 11 keeps taskbar pins by this id and,
    # after Explorer restarts, takes their icon from the Start menu shortcut with it.
    app_id: str = ""


@dataclass(frozen=True)
class Shortcut:
    path: Path
    source: Source
    info: LinkInfo
    # Display name for items whose path doesn't make one, like the Recycle Bin.
    label: str = ""

    @property
    def kind(self) -> ItemKind:
        return kind_of(self.path)

    @property
    def name(self) -> str:
        if self.label:
            return self.label
        return self.path.name if self.kind is ItemKind.FOLDER else self.path.stem

    @property
    def place(self) -> Place:
        return _PLACES[self.source]

    @property
    def shared(self) -> bool:
        """In a folder every user sees; changing it needs administrator permission."""
        return self.source in SHARED_SOURCES


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
    def own_shortcuts(self) -> tuple[Shortcut, ...]:
        """The ones in this user's own folders, which need no extra permission."""
        return tuple(s for s in self.shortcuts if not s.shared)

    @property
    def shared_shortcuts(self) -> tuple[Shortcut, ...]:
        return tuple(s for s in self.shortcuts if s.shared)

    @property
    def places(self) -> frozenset[Place]:
        return frozenset(s.place for s in self.shortcuts)

    @property
    def is_windows_tool(self) -> bool:
        """Built into Windows (Command Prompt, Character Map...): listed after real apps."""
        target = self.primary.info.target
        windir = normalize_path(os.environ.get("SYSTEMROOT", r"C:\Windows")) + "\\"
        return bool(target) and normalize_path(os.path.expandvars(target)).startswith(windir)

    @property
    def slug(self) -> str:
        """Short stable id used in generated file names."""
        return hashlib.sha256(self.key.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class ScanRoot:
    path: Path
    source: Source
    # Which levels hold shortcuts: 1 is the folder itself, 2 the folders inside it,
    # and so on. max_depth None means the whole tree.
    min_depth: int = 1
    max_depth: int | None = 1
    # Also list the folders directly inside (only the desktop does).
    folders: bool = False
    # Stop after this many files at those levels, so a huge folder can't stall the scan.
    limit: int | None = None


@dataclass(frozen=True)
class WindowsIcon:
    """One of Windows' own desktop icons, identified by its shell CLSID."""

    clsid: str
    name: str

    @property
    def path(self) -> Path:
        return Path(f"::{self.clsid}")


class ItemIO(Protocol):
    """Reads and changes one kind of item's icon, and saves or restores its full state.

    The state is whatever decides the icon (a shortcut file's bytes, a folder's
    desktop.ini, a few registry values), so a backup of it can undo a change exactly.
    """

    def exists(self, path: Path) -> bool: ...

    def read(self, path: Path) -> LinkInfo: ...

    def set_icon(self, path: Path, icon: IconLocation) -> None: ...

    def snapshot(self, path: Path) -> bytes | None: ...

    def restore(self, path: Path, state: bytes | None) -> None: ...

    def variants(self, path: Path) -> Mapping[str, IconLocation]:
        """Extra icons the item needs styled too, by name (the Recycle Bin's "full")."""
        ...


def variant_path(icon_file: Path, variant: str) -> Path:
    """Where the styled ``variant`` of a generated icon is written."""
    return icon_file.with_name(f"{icon_file.stem}.{variant}{icon_file.suffix}")


def default_roots() -> list[ScanRoot]:
    """The shortcut folders Iconbloom looks in, resolved through the shell."""
    from platform_win.paths import known_folder

    appdata = known_folder("RoamingAppData")
    pinned = appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned"
    desktop = known_folder("Desktop")
    return [
        ScanRoot(desktop, Source.DESKTOP, folders=True),
        ScanRoot(known_folder("PublicDesktop"), Source.PUBLIC_DESKTOP),
        ScanRoot(known_folder("Programs"), Source.START_MENU, max_depth=None),
        ScanRoot(known_folder("CommonPrograms"), Source.ALL_USERS_START_MENU, max_depth=None),
        ScanRoot(pinned / "TaskBar", Source.TASKBAR),
        desktop_folders_root(desktop),
    ]


# Shortcuts kept in folders on the desktop: up to three folders deep.
DESKTOP_FOLDER_DEPTH = 3
DESKTOP_FOLDER_FILE_LIMIT = 2000


def desktop_folders_root(desktop: Path) -> ScanRoot:
    return ScanRoot(
        desktop,
        Source.DESKTOP_FOLDERS,
        min_depth=2,
        max_depth=1 + DESKTOP_FOLDER_DEPTH,
        limit=DESKTOP_FOLDER_FILE_LIMIT,
    )


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


def scan(
    roots: Sequence[ScanRoot], io: ItemIO, windows_icons: Sequence[WindowsIcon] = ()
) -> list[ShortcutGroup]:
    """Read everything under ``roots`` (plus Windows' own icons) and group what belongs together."""
    shortcuts: list[Shortcut] = []
    for root in roots:
        for path in _items(root):
            try:
                info = io.read(path)
            except OSError:
                continue  # unreadable or half-written; leave it alone
            shortcut = Shortcut(path=path, source=root.source, info=info)
            if not is_noise(shortcut.name, info.target):
                shortcuts.append(shortcut)
    for icon in windows_icons:
        try:
            info = io.read(icon.path)
        except OSError:
            continue
        shortcuts.append(Shortcut(icon.path, Source.WINDOWS, info, label=icon.name))
    return group(shortcuts)


def group(shortcuts: Iterable[Shortcut]) -> list[ShortcutGroup]:
    """Shortcuts that launch the same thing become one group, styled together.

    Two shortcuts belong together when they run the same program and either
    pass it the same arguments or have the same name, or when they carry the
    same app id. A Start-menu "Discord"
    that runs Discord.exe plainly joins the desktop "Discord" that adds a
    launcher flag, while Chrome profiles, web apps and Steam games stay apart.
    """
    items = list(shortcuts)
    parent = list(range(len(items)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[str, int] = {}
    for i, shortcut in enumerate(items):
        for key in _match_keys(shortcut):
            if key in first:
                parent[root(i)] = root(first[key])
            else:
                first[key] = i
    clusters: dict[int, list[Shortcut]] = {}
    for i, shortcut in enumerate(items):
        clusters.setdefault(root(i), []).append(shortcut)
    result: list[ShortcutGroup] = []
    for members in clusters.values():
        ordered = tuple(sorted(members, key=_preference))
        # Keyed by its preferred member, so saved choices keep matching.
        result.append(ShortcutGroup(group_key(ordered[0]), ordered))
    return sorted(result, key=_display_order)


def _match_keys(shortcut: Shortcut) -> list[str]:
    keys = [group_key(shortcut)]
    target = shortcut.info.target.strip()
    if target:
        keys.append(f"name:{_normal_target(target)}|{shortcut.name.casefold()}")
    if app_id := shortcut.info.app_id.strip():
        # The taskbar draws a pin with the Start menu shortcut of the same id, so
        # those must always be styled together, whatever they point at.
        keys.append(f"app:{app_id.casefold()}")
    return keys


def _display_order(target: ShortcutGroup) -> tuple[int, bool, str]:
    """Desktop first, then taskbar, then Start menu; Windows' own tools after real apps."""
    return (
        _SOURCE_ORDER.index(target.primary.source),
        target.is_windows_tool,
        target.name.casefold(),
    )


def group_key(shortcut: Shortcut) -> str:
    """Shortcuts with the same target and arguments are the same app.

    Store-app and installer-advertised shortcuts have no target path, so each
    of those stands alone, keyed by its own location.
    """
    target = shortcut.info.target.strip()
    if not target:
        return "lnk:" + normalize_path(str(shortcut.path))
    return f"target:{_normal_target(target)}|{shortcut.info.arguments.strip().casefold()}"


def _normal_target(target: str) -> str:
    return normalize_path(os.path.expandvars(target))


def normalize_path(path: str) -> str:
    """Windows paths compare case-insensitively and with either slash."""
    return ntpath.normcase(ntpath.normpath(path))


def _preference(shortcut: Shortcut) -> tuple[int, int, str]:
    return (shortcut.shared, _SOURCE_ORDER.index(shortcut.source), str(shortcut.path))


_SHORTCUT_SUFFIXES = frozenset({".lnk", ".url"})
# Folders full of files nobody launches from; never worth walking.
_SKIPPED_FOLDERS = frozenset({".git", "node_modules", "__pycache__"})

# Windows file attributes (winnt.h) the scan looks at.
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# OneDrive "online-only" files: reading one downloads it, so the scan leaves them alone.
_CLOUD_ONLY = (
    FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


def file_attributes(item: Path | os.DirEntry[str]) -> int:
    """The Windows attribute bits of ``item`` (0 elsewhere). Reading them never downloads,
    and for a directory entry Windows already listed them, so they cost nothing."""
    try:
        info = item.lstat() if isinstance(item, Path) else item.stat(follow_symlinks=False)
    except OSError:
        return 0
    return getattr(info, "st_file_attributes", 0)


def _items(root: ScanRoot) -> list[Path]:
    found: list[Path] = []
    looked_at = 0
    for entry, depth in _walk(root.path, root.max_depth):
        if entry.is_file():
            if depth < root.min_depth:
                continue
            looked_at += 1
            if root.limit is not None and looked_at > root.limit:
                log.warning("stopped scanning %s after %d files", root.path, root.limit)
                break
            is_shortcut = Path(entry.name).suffix.casefold() in _SHORTCUT_SUFFIXES
            if is_shortcut and not file_attributes(entry) & _CLOUD_ONLY:
                found.append(Path(entry.path))
        elif root.folders and depth == 1 and _is_visible_folder(entry):
            found.append(Path(entry.path))
    return found


def _walk(
    folder: Path, max_depth: int | None, depth: int = 1
) -> Iterator[tuple[os.DirEntry[str], int]]:
    """Everything under ``folder`` in path order with its depth, skipping hidden folders."""
    try:
        with os.scandir(folder) as listing:
            entries = sorted(listing, key=lambda entry: Path(entry.path))
    except OSError:
        return  # missing, gone, or not ours to read
    for entry in entries:
        yield entry, depth
        deeper = max_depth is None or depth < max_depth
        if deeper and entry.name not in _SKIPPED_FOLDERS and _is_visible_folder(entry):
            yield from _walk(Path(entry.path), max_depth, depth + 1)


def _is_visible_folder(entry: os.DirEntry[str]) -> bool:
    """Folders a person sees in Explorer, not links to them. "System" folders count:
    Windows marks every folder with a custom icon as system, including themed ones."""
    return (
        entry.is_dir(follow_symlinks=False)
        and not entry.name.startswith((".", "$"))
        and not file_attributes(entry) & FILE_ATTRIBUTE_HIDDEN
    )
