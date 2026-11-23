"""Waiting, at no cost, for the user's shortcut folders to change.

The sign-in run stays open while the person is signed in and sleeps here until an app
update rewrites a shortcut. Windows wakes it through change notifications, so it uses
no CPU in between. A named event asks it to stop (turning the option off, Revert all,
the installer), and a named mutex keeps it to one copy per sign-in session.
"""

# pywin32's stubs leave most parameters and results untyped (some are wrong: they say
# IShellLink.GetIconLocation returns None), so strict mode's unknown-type checks stay off
# in the modules that call it. Every other strict check still applies.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Protocol

# "Local\" keeps both to this sign-in session, so other users' copies are left alone.
STOP_EVENT = "Local\\Iconbloom.StopKeepingIcons"
ONE_KEEPER = "Local\\Iconbloom.KeepingIcons"
# The corner notice about reset shared shortcuts, also one at a time.
ONE_OFFER = "Local\\Iconbloom.OfferingSharedResets"

# What counts as a change: a shortcut created, deleted, renamed or rewritten.
_FILE_NAME = 0x1
_DIR_NAME = 0x2
_LAST_WRITE = 0x10
_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x2
_SYNCHRONIZE = 0x100000


class Wake(StrEnum):
    CHANGED = "changed"
    QUIET = "quiet"  # the time ran out with nothing changed
    STOP = "stop"


class FolderWatch(Protocol):
    def wait(self, seconds: float) -> Wake: ...


class WindowsFolderWatch:
    """Change notifications on whole folder trees, plus the stop event."""

    def __init__(self, folders: Sequence[Path], stop_event: str = STOP_EVENT) -> None:
        import win32event
        import win32file

        self._stop = win32event.CreateEvent(None, True, False, stop_event)
        win32event.ResetEvent(self._stop)  # a stop meant for an earlier copy doesn't count
        self._changes = [
            win32file.FindFirstChangeNotification(
                str(folder), True, _FILE_NAME | _DIR_NAME | _LAST_WRITE
            )
            for folder in folders
            if folder.is_dir()
        ]

    def wait(self, seconds: float) -> Wake:
        import win32event
        import win32file

        handles = [self._stop, *self._changes]
        result = win32event.WaitForMultipleObjects(handles, False, int(seconds * 1000))
        if result == win32event.WAIT_TIMEOUT:
            return Wake.QUIET
        index = result - win32event.WAIT_OBJECT_0
        if index == 0:
            return Wake.STOP
        win32file.FindNextChangeNotification(handles[index])
        return Wake.CHANGED


def first_copy(name: str = ONE_KEEPER) -> object | None:
    """This session's mutex ``name``, or None when another copy already holds it.
    Keep the returned handle for as long as this copy runs. It's held as owner, so
    setup can wait on it to learn the keeper has really exited."""
    import pywintypes
    import win32api
    import win32event

    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.bInheritHandle = False  # pywin32's default is True
    handle = win32event.CreateMutex(attributes, True, name)
    if win32api.GetLastError() == _ERROR_ALREADY_EXISTS:
        handle.Close()
        return None
    return handle


def is_running(name: str = ONE_KEEPER) -> bool:
    """Whether a copy holds ``name``: cheaper to ask than starting one that would exit."""
    import pywintypes
    import win32api
    import win32event

    try:
        handle = win32event.OpenMutex(_SYNCHRONIZE, False, name)
    except pywintypes.error:
        return False
    win32api.CloseHandle(handle)
    return True


def ask_keeper_to_stop(stop_event: str = STOP_EVENT) -> None:
    """Wake the running copy, if there is one, and have it exit."""
    import pywintypes
    import win32api
    import win32event

    try:
        handle = win32event.OpenEvent(_EVENT_MODIFY_STATE, False, stop_event)
    except pywintypes.error:
        return  # none running
    try:
        win32event.SetEvent(handle)
    finally:
        win32api.CloseHandle(handle)
