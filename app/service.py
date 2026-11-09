"""Apply, revert and reapply themed icons: the one place shortcuts get changed.

The UI and the CLI both go through ``IconService``. Every change follows the
same order, so a crash at any step leaves a recoverable state:

1. write the generated .ico file
2. record the shortcut's original in the backup manifest (saved to disk)
3. point the shortcut at the new .ico
4. note the shortcut's new hash in the manifest, and the choice in choices.json
"""

import hashlib
import io
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PIL import Image

from app.choices import Choice, ChoiceStore
from app.elevation import Action, ElevatedItem, ElevatedResult, Elevator, WindowsElevator
from engine import ops
from engine.ico import build_ico
from engine.recipes import render
from engine.themes import THEMES_DIR, Theme, list_themes, load_theme, theme_name
from platform_win.backup import BackupManifest, state_hash
from platform_win.elevate import ElevationDeclinedError, is_inside
from platform_win.extract import ExtractedIcon, ExtractionError, extract_icon, read_icon_file
from platform_win.fileio import atomic_write
from platform_win.item_io import windows_item_io
from platform_win.paths import AppPaths, default_app_paths
from platform_win.refresh import notify_icons_changed
from platform_win.shell_icons import WINDOWS_ICONS
from platform_win.shortcuts import (
    SHARED_SOURCES,
    IconLocation,
    ItemIO,
    ScanRoot,
    Shortcut,
    ShortcutGroup,
    WindowsIcon,
    default_roots,
    normalize_path,
    scan,
    variant_path,
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


SHARED_REASON = "shared by every user on this PC; needs administrator permission"
DECLINED_REASON = "you declined Windows' permission prompt"


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
        io: ItemIO,
        roots: Sequence[ScanRoot],
        *,
        windows_icons: Sequence[WindowsIcon] = (),
        extractor: Extractor = extract_icon,
        notify: Callable[[Sequence[Path]], None] = lambda _paths: None,
        themes_dir: Path = THEMES_DIR,
        elevator: Elevator | None = None,
    ) -> None:
        self.paths = paths.ensure()
        self._io = io
        self._roots = roots
        self._windows_icons = windows_icons
        self._extract = extractor
        self._notify = notify
        self._themes_dir = themes_dir
        self._elevator = elevator
        self._shared_folders = [r.path for r in roots if r.source in SHARED_SOURCES]
        self._themes: dict[str, Theme] = {}
        self._icons_prefix = normalize_path(str(self.paths.icons)).rstrip("\\") + "\\"
        # Raises BackupCorruptError on a damaged manifest, before anything can change.
        self.manifest = BackupManifest(paths.manifest, paths.originals)
        self.choices = ChoiceStore(paths.choices)

    def scan(self) -> list[ShortcutGroup]:
        return scan(self._roots, self._io, self._windows_icons)

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
            Shortcut(s.path, s.source, self._io.read(s.path), s.label)
            for s in target.shortcuts
            if self._io.exists(s.path)
        )
        return ShortcutGroup(target.key, fresh or target.shortcuts)

    def is_ours(self, icon: IconLocation) -> bool:
        return bool(icon.path) and normalize_path(icon.path).startswith(self._icons_prefix)

    def status(self, target: ShortcutGroup) -> Status:
        chosen = self.choices.get(target.key) is not None
        if any(self.is_ours(s.info.icon) for s in target.shortcuts):
            # Some of the group lost the style (an update recreated one shortcut, say).
            own = target.own_shortcuts
            if chosen and not all(self.is_ours(s.info.icon) for s in own):
                return Status.NEEDS_REAPPLY
            return Status.THEMED
        if self.choices.is_skipped(target.key):
            return Status.SKIPPED
        if chosen:
            return Status.NEEDS_REAPPLY
        return Status.ORIGINAL

    def is_untouched(self, target: ShortcutGroup) -> bool:
        """Hasn't been themed or skipped yet."""
        return self.status(target) is Status.ORIGINAL

    def original_icon(self, target: ShortcutGroup) -> ExtractedIcon:
        """The item's own icon, even when it currently shows a styled one.

        While styled, Windows would hand back our icon, so the original comes
        from the picture saved at apply time, or failing that from the
        recorded icon location.
        """
        primary = target.primary
        icon = primary.info.icon
        if not self.is_ours(icon):
            return self._extract(icon, primary.info.target, primary.path)
        saved = self._saved_original_path(target)
        if saved.is_file():
            with Image.open(saved) as img:
                return ExtractedIcon(img.convert("RGBA"), upscaled=False, source="saved original")
        entry = self.manifest.get(primary.path)
        icon = entry.original_icon if entry is not None else IconLocation()
        return self._extract(icon, primary.info.target, primary.path, use_shell=False)

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
        include_shared: bool = False,
        prepared: Image.Image | None = None,
        dry_run: bool = False,
    ) -> ChangeReport:
        """Theme a group's shortcuts with ``choice``.

        Shortcuts in folders every user shares are only changed when
        ``include_shared`` is set, through one Windows permission prompt.
        ``prepared`` is the original icon after ``ops.prepare``, when the
        caller already has it; otherwise it is extracted here.
        """
        return self.apply_many(
            [target],
            lambda _g: choice,
            include_shared=include_shared,
            prepared={target.key: prepared} if prepared is not None else None,
            dry_run=dry_run,
            catch=False,
        )

    def apply_many(
        self,
        targets: Sequence[ShortcutGroup],
        choice_for: Callable[[ShortcutGroup], Choice | None],
        *,
        include_shared: bool = False,
        dry_run: bool = False,
        progress: Progress | None = None,
        prepared: Mapping[str, Image.Image] | None = None,
        catch: bool = True,
    ) -> ChangeReport:
        """Theme many groups, with at most one permission prompt and one Explorer refresh.

        With ``catch``, a failure on one group is recorded in ``skipped`` and
        the batch goes on.
        """
        report = ChangeReport(dry_run)
        shared: list[ElevatedItem] = []
        chosen: dict[Path, tuple[ShortcutGroup, Choice]] = {}
        for i, target in enumerate(targets):
            if progress is not None and not progress(i, target):
                break
            choice = choice_for(target)
            if choice is None:
                continue
            if not target.own_shortcuts and not include_shared:
                report.skipped += [(s.path, SHARED_REASON) for s in target.shortcuts]
                continue
            try:
                icon_file = self._themed_icon(
                    target, choice, (prepared or {}).get(target.key), dry_run=dry_run
                )
            except Exception as exc:
                if not catch:
                    raise
                log.exception("could not theme %s", target.name)
                report.skipped.append((target.primary.path, str(exc)))
                continue
            report.written.append(icon_file)
            for shortcut in target.own_shortcuts:
                try:
                    self._apply_one(shortcut.path, icon_file, dry_run=dry_run)
                except ShortcutStateError as exc:
                    report.skipped.append((shortcut.path, str(exc)))
                    continue
                report.changed.append(shortcut.path)
                chosen[shortcut.path] = (target, choice)
            for shortcut in target.shared_shortcuts:
                if include_shared:
                    shared.append(ElevatedItem(shortcut.path, icon_file))
                    chosen[shortcut.path] = (target, choice)
                else:
                    report.skipped.append((shortcut.path, SHARED_REASON))
        if shared:
            report.extend(self._elevated("apply", shared, dry_run=dry_run))
        if not dry_run:
            for path in report.changed:
                target, choice = chosen[path]
                self.choices.set(target.key, choice)
            if report.changed:
                self._notify(report.changed)
                log.info("applied styles to %d shortcuts", len(report.changed))
        return report

    def reapply(
        self,
        groups: Sequence[ShortcutGroup],
        *,
        include_shared: bool = False,
        dry_run: bool = False,
        progress: Progress | None = None,
    ) -> ChangeReport:
        """Re-theme every shortcut that lost its chosen icon, e.g. after an app update."""
        lost = [g for g in groups if self.status(g) is Status.NEEDS_REAPPLY]
        return self.apply_many(
            lost,
            lambda g: self.choices.get(g.key),
            include_shared=include_shared,
            dry_run=dry_run,
            progress=progress,
        )

    def revert(self, target: ShortcutGroup, *, dry_run: bool = False) -> ChangeReport:
        report = self._revert_paths([s.path for s in target.shortcuts], dry_run=dry_run)
        if not dry_run:
            self.choices.clear(target.key)
        return report

    def revert_all(self, *, dry_run: bool = False) -> ChangeReport:
        report = self._revert_paths([Path(e.shortcut) for e in self.manifest], dry_run=dry_run)
        if not dry_run:
            self.choices.clear_all()
        return report

    def _revert_paths(self, paths: Sequence[Path], *, dry_run: bool) -> ChangeReport:
        report = ChangeReport(dry_run)
        shared: list[ElevatedItem] = []
        for path in paths:
            if self.manifest.get(path) is None:
                continue
            if self.is_shared(path) and self._io.exists(path):
                shared.append(ElevatedItem(path))
            elif self._revert_one(path, dry_run=dry_run):
                report.changed.append(path)
        if shared:
            report.extend(self._elevated("revert", shared, dry_run=dry_run))
        if not dry_run and report.changed:
            self._notify(report.changed)
            log.info("reverted %d shortcuts", len(report.changed))
        return report

    def is_shared(self, path: Path) -> bool:
        """In a folder every user shares, so changing it needs administrator permission."""
        return is_inside(path, self._shared_folders)

    def _elevated(
        self, action: Action, items: Sequence[ElevatedItem], *, dry_run: bool
    ) -> ChangeReport:
        report = ChangeReport(dry_run)
        if dry_run:
            report.changed += [i.shortcut for i in items]
            return report
        if self._elevator is None:
            report.skipped += [(i.shortcut, SHARED_REASON) for i in items]
            return report
        try:
            result = self._elevator(action, items)
        except ElevationDeclinedError:
            report.skipped += [
                (i.shortcut, "you declined Windows' permission prompt") for i in items
            ]
            return report
        finally:
            # The elevated copy wrote to backup.json; pick up its entries.
            self.manifest.reload()
        report.changed += result.changed
        report.skipped += result.skipped
        return report

    def apply_files(self, items: Sequence[tuple[Path, Path]]) -> ElevatedResult:
        """Inside the elevated copy: point already-checked shortcuts at icon files."""
        result = ElevatedResult()
        for shortcut, icon_file in items:
            try:
                self._apply_one(shortcut, icon_file, dry_run=False)
            except (ShortcutStateError, OSError) as exc:
                result.skipped.append((shortcut, str(exc)))
            else:
                result.changed.append(shortcut)
        return result

    def restore_icon_fields(self, shortcuts: Sequence[Path]) -> ElevatedResult:
        """Inside the elevated copy: put back the recorded icon, never whole files."""
        result = ElevatedResult()
        for shortcut in shortcuts:
            entry = self.manifest.get(shortcut)
            if entry is None:
                continue
            if entry.original_icon_path.startswith("\\\\"):
                # Network icon paths would make every user's PC reach out to that server.
                result.skipped.append((shortcut, "original icon is on a network path"))
                continue
            try:
                self._revert_one(shortcut, dry_run=False, whole_file=False)
            except OSError as exc:
                result.skipped.append((shortcut, str(exc)))
            else:
                result.changed.append(shortcut)
        return result

    def skip(self, target: ShortcutGroup) -> None:
        self.choices.skip(target.key)

    def cleanup(self, *, dry_run: bool = False) -> ChangeReport:
        """Delete generated .ico files that no shortcut points at any more."""
        report = ChangeReport(dry_run)
        in_use = {
            normalize_path(e.applied_icon) for e in self.manifest if e.applied_icon is not None
        }
        for path in sorted(self.paths.icons.glob("*.ico")):
            # A variant ("x.full.ico") is in use when its main icon ("x.ico") is.
            main = path.with_name(path.name.split(".", 1)[0] + path.suffix)
            if normalize_path(str(main)) not in in_use:
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
        current = self._io.read(path)
        entry = self.manifest.get(path)
        ours = self.is_ours(current.icon)
        if entry is None and ours:
            raise ShortcutStateError(
                "already uses an Iconbloom icon but has no backup entry; revert it by hand first"
            )
        if dry_run:
            return
        state = self._io.snapshot(path)
        if entry is None:
            self.manifest.record_original(path, current.icon, state)
        elif not ours and state_hash(state) not in (entry.original_sha256, entry.applied_sha256):
            # Rewritten by something else (an app update): that is the new original.
            self.manifest.rerecord_original(path, current.icon, state)
        self._io.set_icon(path, IconLocation(str(icon_file), 0))
        self.manifest.mark_applied(path, icon_file, self._io.snapshot(path))

    def _themed_icon(
        self, target: ShortcutGroup, choice: Choice, prepared: Image.Image | None, *, dry_run: bool
    ) -> Path:
        """Render ``choice`` for a group and write its .ico (and any variants); returns the file."""
        if not choice.is_custom and prepared is None:
            prepared, _ = ops.prepare(self.original_icon(target).image)
        full, simple = self.render_choice(choice, prepared)
        icon_file = self.paths.icons / f"{target.slug}_{choice.file_tag}.ico"
        if dry_run:
            return icon_file
        if self.status(target) is not Status.THEMED:
            self._save_original(target, prepared)
        atomic_write(icon_file, build_ico(full, simple))
        primary = target.primary.path
        for name, location in self._io.variants(primary).items():
            source = None
            if not choice.is_custom:
                extracted = self._extract(location, "", primary, use_shell=False)
                source, _ = ops.prepare(extracted.image)
            variant_full, variant_simple = self.render_choice(choice, source)
            atomic_write(variant_path(icon_file, name), build_ico(variant_full, variant_simple))
        return icon_file

    def _save_original(self, target: ShortcutGroup, prepared: Image.Image | None) -> None:
        """Keep a picture of the item's own icon, since Windows reports ours once it's styled."""
        if prepared is None:
            try:
                prepared, _ = ops.prepare(self.original_icon(target).image)
            except (ExtractionError, OSError, ValueError):
                log.warning("could not save the original icon of %s", target.name)
                return
        buffer = io.BytesIO()
        prepared.save(buffer, format="PNG")
        atomic_write(self._saved_original_path(target), buffer.getvalue())

    def _saved_original_path(self, target: ShortcutGroup) -> Path:
        return self.paths.original_icons / f"{target.slug}.png"

    def _revert_one(self, path: Path, *, dry_run: bool, whole_file: bool = True) -> bool:
        entry = self.manifest.get(path)
        if entry is None:
            return False
        if dry_run:
            return True
        if self._io.exists(path):
            current = state_hash(self._io.snapshot(path))
            original = self.manifest.original_state(entry)
            if whole_file and current == entry.applied_sha256 and original is not None:
                # Nothing else touched the item since we did: restore it exactly.
                self._io.restore(path, original.data)
            elif current != entry.original_sha256 and self.is_ours(self._io.read(path).icon):
                # Changed since, but still showing our icon: restore just the icon.
                self._io.set_icon(path, entry.original_icon)
        self.manifest.forget(path)
        return True


def windows_service(paths: AppPaths | None = None) -> IconService:
    """The real thing: the user's shortcut folders, IShellLink and Explorer refresh."""
    paths = paths or default_app_paths()
    return IconService(
        paths,
        windows_item_io(),
        default_roots(),
        windows_icons=WINDOWS_ICONS,
        notify=notify_icons_changed,
        elevator=WindowsElevator(paths),
    )
