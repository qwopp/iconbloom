"""What a change did: the report every action returns, and each item's status."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from platform_win.shortcuts import ShortcutGroup

# Exit code of the CLI and --revert-all when some items could not be changed.
SKIPPED_EXIT = 3


class Status(StrEnum):
    ORIGINAL = "original"
    THEMED = "themed"
    SKIPPED = "skipped"
    # A style was chosen, but the item lost it (usually an app update).
    NEEDS_REAPPLY = "needs reapply"


# Statuses Revert can undo: a style is on the icons, or was and an update took part of it.
REVERTIBLE = frozenset({Status.THEMED, Status.NEEDS_REAPPLY})


SHARED_REASON = "shared by every user on this PC; needs administrator permission"
DECLINED_REASON = "you declined Windows' permission prompt"


def join_names(names: Sequence[str]) -> str:
    """'Chrome', 'Chrome and Roblox', 'Chrome, Discord and Roblox'."""
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)


def shared_reset_message(names: Sequence[str]) -> str:
    """What to say when updates reset shortcuts only a permission prompt can put back."""
    if len(names) == 1:
        return (
            f"An app update reset {names[0]}'s icon, a shortcut every user on this PC "
            "shares. Putting it back needs administrator permission."
        )
    return (
        f"App updates reset the icons of {join_names(names)}, shortcuts every user on this "
        "PC shares. Putting them back needs administrator permission."
    )


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
