"""What a change did: the report every action returns, and each item's status."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from platform_win.shortcuts import ShortcutGroup


class Status(StrEnum):
    ORIGINAL = "original"
    THEMED = "themed"
    SKIPPED = "skipped"
    # A style was chosen, but the item lost it (usually an app update).
    NEEDS_REAPPLY = "needs reapply"


SHARED_REASON = "shared by every user on this PC; needs administrator permission"
DECLINED_REASON = "you declined Windows' permission prompt"


class ShortcutStateError(Exception):
    """An item is in a state Iconbloom won't change without a person deciding."""


@dataclass
class ChangeReport:
    """What a command changed, or with dry_run, what it would change."""

    dry_run: bool
    changed: list[Path] = field(default_factory=list[Path])
    written: list[Path] = field(default_factory=list[Path])
    removed: list[Path] = field(default_factory=list[Path])
    skipped: list[tuple[Path, str]] = field(default_factory=list[tuple[Path, str]])
    # New shortcuts made for Store apps, which the person still has to pin themselves.
    created: list[Path] = field(default_factory=list[Path])
    # Taskbar settings put back or changed, by name ("taskbar color", "alignment"...).
    taskbar: list[str] = field(default_factory=list[str])

    def extend(self, other: "ChangeReport") -> None:
        self.changed += other.changed
        self.written += other.written
        self.removed += other.removed
        self.skipped += other.skipped
        self.created += other.created
        self.taskbar += other.taskbar


# Called before each group in a batch; returning False stops the batch.
type Progress = Callable[[int, ShortcutGroup], bool]
