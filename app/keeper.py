"""Keeping the person's styles on their icons for as long as they're signed in.

Started at sign-in (``Iconbloom.exe --fix-icons``), it puts back what app updates reset,
then sleeps until a shortcut folder changes and does it again: Chrome and Roblox update
while the PC is on, and Google's updater also runs right after sign-in.
"""

import logging
import time
from collections.abc import Callable

from platform_win.backup import BackupCorruptError
from platform_win.watch import FolderWatch, Wake

log = logging.getLogger(__name__)

# An installer writes several shortcuts in a row; put them back once it's done.
SETTLE_SECONDS = 10.0
# A file being written to the desktop for a long time still gets a pass now and then.
MOST_SETTLING_SECONDS = 120.0
# A pass now and then even with no change seen, in case Windows dropped a notification.
CHECK_EVERY_SECONDS = 3600.0


def keep_icons(
    fix: Callable[[], None],
    watch: FolderWatch,
    still_on: Callable[[], bool],
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run ``fix`` now and after every change, until stopped or switched off.

    ``still_on`` is asked before each pass, so turning the option off in Windows'
    Startup apps page also ends this copy. A failing pass is logged and the next
    change tries again; a damaged backup ends it, as nothing may change until it's fixed.
    """
    while True:
        _safely(fix)
        if not still_on() or _drain(watch) is Wake.STOP:
            break
        wake = watch.wait(CHECK_EVERY_SECONDS)
        if wake is Wake.CHANGED:
            wake = _settle(watch, clock)
        if wake is Wake.STOP or not still_on():
            break
    log.info("stopped keeping icons")


def _drain(watch: FolderWatch) -> Wake:
    """Forget the changes a pass just made itself, so they don't bring on another one.
    (A pass starts once the folders are quiet, so little else can be among them.)"""
    while (wake := watch.wait(0)) is Wake.CHANGED:
        pass
    return wake


def _settle(watch: FolderWatch, clock: Callable[[], float]) -> Wake:
    """Wait until the folders have been quiet for a while (or a stop comes)."""
    deadline = clock() + MOST_SETTLING_SECONDS
    while clock() < deadline:
        wake = watch.wait(min(SETTLE_SECONDS, deadline - clock()))
        if wake is not Wake.CHANGED:
            return wake
    return Wake.QUIET


def _safely(fix: Callable[[], None]) -> None:
    try:
        fix()
    except BackupCorruptError:
        raise
    except Exception:
        log.exception("putting icons back failed; trying again at the next change")
