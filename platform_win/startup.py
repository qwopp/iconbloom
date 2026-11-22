"""Running Iconbloom at sign-in, to keep putting back icons app updates reset (opt-in).

It's one value in the user's own Run key, the same place Windows' Startup apps
settings page lists and can turn off. No administrator permission is needed.
"""

import subprocess
import sys
from collections.abc import Callable

from platform_win.taskbar import REG_SZ, UserRegistry, WindowsUserRegistry

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Where Settings > Apps > Startup and Task Manager record an entry they switched off.
STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = "Iconbloom"
FIX_ICONS_FLAG = "--fix-icons"


class SignInRun:
    """The Run value, plus starting or stopping this session's copy when it's switched."""

    def __init__(
        self,
        registry: UserRegistry,
        command: str,
        name: str = VALUE_NAME,
        *,
        start: Callable[[], None],
        stop: Callable[[], None],
    ) -> None:
        self._registry = registry
        self._command = command
        self._name = name
        self._start = start
        self._stop = stop

    def is_on(self) -> bool:
        if self._registry.read(RUN_KEY, self._name) is None:
            return False
        return not self._switched_off_by_windows()

    def set(self, on: bool) -> None:
        # Either way the Startup apps page's own switch goes: on means really on.
        self._registry.delete(STARTUP_APPROVED_KEY, self._name)
        if on:
            self._registry.write(RUN_KEY, self._name, (REG_SZ, self._command))
            self._start()
        else:
            self._registry.delete(RUN_KEY, self._name)
            self._stop()

    def run_now(self) -> None:
        """Start this session's copy if the option is on (it exits if one already runs)."""
        if self.is_on():
            self._start()

    def _switched_off_by_windows(self) -> bool:
        # The first byte is 2 (or 6) while on and 3 (or 7) once switched off.
        value = self._registry.read(STARTUP_APPROVED_KEY, self._name)
        if value is None or not isinstance(value[1], bytes) or not value[1]:
            return False
        return bool(value[1][0] & 1)


def start_detached(*arguments: str) -> None:
    """Start another copy of the built app that outlives this one."""
    subprocess.Popen(
        [sys.executable, *arguments],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def windows_sign_in_run() -> SignInRun | None:
    """None when running from source: only the built app has an exe to start."""
    if not getattr(sys, "frozen", False):
        return None
    from platform_win.watch import ask_keeper_to_stop, is_running

    def start() -> None:
        if not is_running():  # opening the window shouldn't start a copy that just exits
            start_detached(FIX_ICONS_FLAG)

    return SignInRun(
        WindowsUserRegistry(),
        f'"{sys.executable}" {FIX_ICONS_FLAG}',
        start=start,
        stop=ask_keeper_to_stop,
    )
