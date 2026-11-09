"""Apply, revert and reapply themed icons: the one place shortcuts get changed.

The UI and the CLI both go through ``IconService``. Every change follows the
same order, so a crash at any step leaves a recoverable state:

1. write the generated .ico file
2. record the shortcut's original in the backup manifest (saved to disk)
3. point the shortcut at the new .ico
4. note the shortcut's new hash in the manifest, and the choice in choices.json
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PIL import Image

from app.choices import Choice, ChoiceStore
from engine import ops
from engine.ico import build_ico
from engine.recipes import render
from engine.themes import THEMES_DIR, Theme, list_themes, load_theme, theme_name
from platform_win.backup import BackupManifest, file_sha256
from platform_win.extract import ExtractedIcon, extract_icon, read_icon_file
from platform_win.fileio import atomic_write
from platform_win.paths import AppPaths, default_app_paths
from platform_win.refresh import notify_icons_changed
from platform_win.shortcuts import (
    IconLocation,
    LinkIO,
    ScanRoot,
    ShellLinkIO,
    Shortcut,
    ShortcutGroup,
    default_roots,
    normalize_path,
    scan,
)

log = logging.getLogger(__name__)


class Extractor(Protocol):
    def __call__(
        self, icon: IconLocation, target: str, shortcut: Path, *, use_shell: bool = True
    ) -> ExtractedIcon: ...


class Status(StrEnum):
    ORIGINAL = "original"
    THEMED = "themed"
    SKIPPED = "skipped"
    # A style was chosen, but the shortcut lost it (usually an app update).
    NEEDS_REAPPLY = "needs reapply"


class ShortcutStateError(Exception):
    """A shortcut is in a state Iconbloom won't change without a person deciding."""


@dataclass
class ChangeReport:
    """What a command changed, or with dry_run, what it would change."""

    dry_run: bool
    changed: list[Path] = field(default_factory=list[Path])
    written: list[Path] = field(default_factory=list[Path])
    removed: list[Path] = field(default_factory=list[Path])
    skipped: list[tuple[Path, str]] = field(default_factory=list[tuple[Path, str]])

    def extend(self, other: "ChangeReport") -> None:
        self.changed += other.changed
        self.written += other.written
        self.removed += other.removed
        self.skipped += other.skipped


# Called before each shortcut group in a batch; returning False stops the batch.
type Progress = Callable[[int, ShortcutGroup], bool]


class IconService:
    def __init__(
        self,
        paths: AppPaths,
        link_io: LinkIO,
        roots: Sequence[ScanRoot],
        *,
        extractor: Extractor = extract_icon,
        notify: Callable[[], None] = lambda: None,
        themes_dir: Path = THEMES_DIR,
    ) -> None:
        self.paths = paths.ensure()
        self._link_io = link_io
        self._roots = roots
        self._extract = extractor
        self._notify = notify
        self._themes_dir = themes_dir
        self._themes: dict[str, Theme] = {}
        self._icons_prefix = normalize_path(str(self.paths.icons)).rstrip("\\") + "\\"
        # Raises BackupCorruptError on a damaged manifest, before anything can change.
        self.manifest = BackupManifest(paths.manifest, paths.originals)
        self.choices = ChoiceStore(paths.choices)

    def scan(self) -> list[ShortcutGroup]:
        return scan(self._roots, self._link_io)

    def theme_names(self) -> list[tuple[str, str]]:
        """(id, display name) of every installed theme, without loading them."""
        return [(t, theme_name(t, self._themes_dir)) for t in list_themes(self._themes_dir)]

    def theme(self, theme_id: str) -> Theme:
        """A loaded theme, read from disk once per session."""
        if theme_id not in self._themes:
            self._themes[theme_id] = load_theme(theme_id, self._themes_dir)
        return self._themes[theme_id]

    def reload(self, target: ShortcutGroup) -> ShortcutGroup:
        """Re-read a group's shortcuts after they changed."""
        fresh = tuple(
            Shortcut(s.path, s.source, self._link_io.read(s.path))
            for s in target.shortcuts
            if s.path.exists()
        )
        return ShortcutGroup(target.key, fresh or target.shortcuts)

    def is_ours(self, icon: IconLocation) -> bool:
        return bool(icon.path) and normalize_path(icon.path).startswith(self._icons_prefix)

    def status(self, target: ShortcutGroup) -> Status:
        if any(self.is_ours(s.info.icon) for s in target.shortcuts):
            return Status.THEMED
        if self.choices.is_skipped(target.key):
            return Status.SKIPPED
        if self.choices.get(target.key) is not None:
            return Status.NEEDS_REAPPLY
        return Status.ORIGINAL

    def is_untouched(self, target: ShortcutGroup) -> bool:
        """Can be themed and hasn't been themed or skipped yet."""
        return target.writable and self.status(target) is Status.ORIGINAL

    def original_icon(self, target: ShortcutGroup) -> ExtractedIcon:
        """The app's own icon, even when the shortcut currently shows a themed one."""
        primary = target.primary
        icon = primary.info.icon
        themed = self.is_ours(icon)
        if themed:
            entry = self.manifest.get(primary.path)
            icon = entry.original_icon if entry is not None else IconLocation()
        return self._extract(icon, primary.info.target, primary.path, use_shell=not themed)

    def current_icon(self, target: ShortcutGroup) -> Image.Image:
        """What the shortcut shows right now: our .ico when themed, else the original."""
        icon = target.primary.info.icon
        if self.is_ours(icon):
            try:
                image = read_icon_file(Path(icon.path))
            except (OSError, ValueError):
                image = None
            if image is not None:
                return image
            log.warning("themed icon %s is unreadable; showing the original", icon.path)
        return self.original_icon(target).image

    def apply(
        self,
        target: ShortcutGroup,
        choice: Choice,
        *,
        prepared: Image.Image | None = None,
        dry_run: bool = False,
        notify: bool = True,
    ) -> ChangeReport:
        """Theme every writable shortcut in a group with ``choice``.

        ``prepared`` is the original icon after ``ops.prepare``, when the caller
        already has it; otherwise it is extracted here.
        """
        report = ChangeReport(dry_run)
        writable = target.writable_shortcuts
        if not writable:
            report.skipped.extend((s.path, "read-only location") for s in target.shortcuts)
            return report
        if prepared is None and not choice.is_custom:
            prepared, _ = ops.prepare(self.original_icon(target).image)
        full, simple = self.render_choice(choice, prepared)
        icon_file = self.paths.icons / f"{target.slug}_{choice.file_tag}.ico"
        report.written.append(icon_file)
        if not dry_run:
            atomic_write(icon_file, build_ico(full, simple))
        for shortcut in writable:
            try:
                self._apply_one(shortcut.path, icon_file, dry_run=dry_run)
            except ShortcutStateError as exc:
                report.skipped.append((shortcut.path, str(exc)))
                continue
            report.changed.append(shortcut.path)
        if not dry_run and report.changed:
            self.choices.set(target.key, choice)
            if notify:
                self._notify()
            log.info("applied %s to %s", choice.file_tag, target.name)
        return report

    def apply_many(
        self,
        targets: Sequence[ShortcutGroup],
        choice_for: Callable[[ShortcutGroup], Choice | None],
        *,
        dry_run: bool = False,
        progress: Progress | None = None,
    ) -> ChangeReport:
        """Apply to many groups, refreshing Explorer once at the end.

        A failure on one group is recorded in ``skipped`` and the batch goes on.
        """
        report = ChangeReport(dry_run)
        for i, target in enumerate(targets):
            if progress is not None and not progress(i, target):
                break
            choice = choice_for(target)
            if choice is None:
                continue
            try:
                report.extend(self.apply(target, choice, dry_run=dry_run, notify=False))
            except Exception as exc:  # one bad icon must not stop the batch
                log.exception("could not theme %s", target.name)
                report.skipped.append((target.primary.path, str(exc)))
        if not dry_run and report.changed:
            self._notify()
        return report

    def reapply(
        self,
        groups: Sequence[ShortcutGroup],
        *,
        dry_run: bool = False,
        progress: Progress | None = None,
    ) -> ChangeReport:
        """Re-theme every shortcut that lost its chosen icon, e.g. after an app update."""
        lost = [g for g in groups if self.status(g) is Status.NEEDS_REAPPLY]
        return self.apply_many(
            lost, lambda g: self.choices.get(g.key), dry_run=dry_run, progress=progress
        )

    def revert(self, target: ShortcutGroup, *, dry_run: bool = False) -> ChangeReport:
        report = ChangeReport(dry_run)
        for shortcut in target.shortcuts:
            if self._revert_one(shortcut.path, dry_run=dry_run):
                report.changed.append(shortcut.path)
        if not dry_run:
            self.choices.clear(target.key)
            if report.changed:
                self._notify()
                log.info("reverted %s", target.name)
        return report

    def revert_all(self, *, dry_run: bool = False) -> ChangeReport:
        report = ChangeReport(dry_run)
        for entry in self.manifest:
            if self._revert_one(Path(entry.shortcut), dry_run=dry_run):
                report.changed.append(Path(entry.shortcut))
        if not dry_run:
            self.choices.clear_all()
            self._notify()
            log.info("reverted all (%d shortcuts)", len(report.changed))
        return report

    def skip(self, target: ShortcutGroup) -> None:
        self.choices.skip(target.key)

    def cleanup(self, *, dry_run: bool = False) -> ChangeReport:
        """Delete generated .ico files that no shortcut points at any more."""
        report = ChangeReport(dry_run)
        in_use = {
            normalize_path(e.applied_icon) for e in self.manifest if e.applied_icon is not None
        }
        for path in sorted(self.paths.icons.glob("*.ico")):
            if normalize_path(str(path)) not in in_use:
                report.removed.append(path)
                if not dry_run:
                    path.unlink(missing_ok=True)
        return report

    def render_choice(
        self, choice: Choice, prepared: Image.Image | None = None
    ) -> tuple[Image.Image, Image.Image]:
        """Full and simplified renders for a choice.

        Theme choices need ``prepared``, the original icon after ``ops.prepare``;
        a custom image is its own source.
        """
        if choice.custom_image is not None:
            with Image.open(self.paths.custom_images / choice.custom_image) as img:
                image, _ = ops.prepare(img)
            return image, image
        if prepared is None:
            raise ValueError(f"rendering {choice.file_tag} needs the original icon")
        theme = self.theme(choice.theme)
        recipe = theme.recipe(choice.recipe)
        return (
            render(recipe, prepared, theme, seed=choice.seed),
            render(recipe, prepared, theme, seed=choice.seed, simplified=True),
        )

    def store_custom_image(self, source: Path) -> Choice:
        """Copy a user-picked image into app data and return the choice that uses it."""
        with Image.open(source) as img:
            ops.prepare(img)  # raises on an unusable image before anything is stored
        data = source.read_bytes()
        name = f"{hashlib.sha256(data).hexdigest()[:12]}{source.suffix.casefold()}"
        destination = self.paths.custom_images / name
        if not destination.exists():
            atomic_write(destination, data)
        return Choice.custom(name)

    def _apply_one(self, path: Path, icon_file: Path, *, dry_run: bool) -> None:
        current = self._link_io.read(path)
        entry = self.manifest.get(path)
        ours = self.is_ours(current.icon)
        if entry is None and ours:
            raise ShortcutStateError(
                "already uses an Iconbloom icon but has no backup entry; revert it by hand first"
            )
        if dry_run:
            return
        if entry is None:
            self.manifest.record_original(path, current.icon)
        elif not ours and file_sha256(path) not in (entry.original_sha256, entry.applied_sha256):
            # Rewritten by something else (an app update): that is the new original.
            self.manifest.rerecord_original(path, current.icon)
        self._link_io.set_icon(path, IconLocation(str(icon_file), 0))
        self.manifest.mark_applied(path, icon_file)

    def _revert_one(self, path: Path, *, dry_run: bool) -> bool:
        entry = self.manifest.get(path)
        if entry is None:
            return False
        if dry_run:
            return True
        if path.exists():
            current_sha = file_sha256(path)
            original = self.manifest.original_bytes(entry)
            if current_sha == entry.applied_sha256 and original is not None:
                # Nothing else touched the shortcut since we did: restore it byte for byte.
                atomic_write(path, original)
            elif current_sha != entry.original_sha256 and self.is_ours(
                self._link_io.read(path).icon
            ):
                # Changed since, but still showing our icon: restore just the icon field.
                self._link_io.set_icon(path, entry.original_icon)
        self.manifest.forget(path)
        return True


def windows_service(paths: AppPaths | None = None) -> IconService:
    """The real thing: the user's shortcut folders, IShellLink and Explorer refresh."""
    return IconService(
        paths or default_app_paths(),
        ShellLinkIO(),
        default_roots(),
        notify=notify_icons_changed,
    )
