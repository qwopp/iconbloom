import os
from pathlib import Path

import pytest

from platform_win.item_io import ShellLinkIO

SYSTEM32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
NOTEPAD = SYSTEM32 / "notepad.exe"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/win/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.windows)


@pytest.fixture
def shell_io() -> ShellLinkIO:
    return ShellLinkIO()
