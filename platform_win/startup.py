"""Running Iconbloom at sign-in, to put back icons app updates reset (opt-in).

It's one value in the user's own Run key, the same place Windows' Startup apps
settings page lists and can turn off. No administrator permission is needed.
"""

import sys

from platform_win.taskbar import REG_SZ, UserRegistry, WindowsUserRegistry

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Iconbloom"
FIX_ICONS_FLAG = "--fix-icons"


class SignInRun:
    def __init__(self, registry: UserRegistry, command: str) -> None:
        self._registry = registry
        self._command = command

    def is_on(self) -> bool:
        return self._registry.read(RUN_KEY, VALUE_NAME) is not None

    def set(self, on: bool) -> None:
        if on:
            self._registry.write(RUN_KEY, VALUE_NAME, (REG_SZ, self._command))
        else:
            self._registry.delete(RUN_KEY, VALUE_NAME)


def windows_sign_in_run() -> SignInRun | None:
    """None when running from source: only the built app has an exe to start."""
    if not getattr(sys, "frozen", False):
        return None
    return SignInRun(WindowsUserRegistry(), f'"{sys.executable}" {FIX_ICONS_FLAG}')
