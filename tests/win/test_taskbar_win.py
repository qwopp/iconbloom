"""The taskbar's Windows pieces on a real registry, without touching the real taskbar.

Values are written only under a throwaway HKCU key; the taskbar itself is only read.
"""

import contextlib
import uuid
import winreg
from collections.abc import Iterator

import pytest

from platform_win import taskbar as tb


@pytest.fixture
def scratch_key() -> Iterator[str]:
    key = rf"Software\Iconbloom-tests\{uuid.uuid4()}"
    yield key
    for path in (key, r"Software\Iconbloom-tests"):
        # The parent stays if another run still uses it.
        with contextlib.suppress(OSError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


@pytest.mark.parametrize(
    "value",
    [(tb.REG_DWORD, 0xFFC3B700), (tb.REG_BINARY, bytes(range(32))), (tb.REG_SZ, "0")],
)
def test_registry_round_trip(scratch_key: str, value: tb.RegValue) -> None:
    registry = tb.WindowsUserRegistry()
    registry.write(scratch_key, "Value", value)
    assert registry.read(scratch_key, "Value") == value
    assert tb.decode(tb.encode(value)) == value
    registry.delete(scratch_key, "Value")
    assert registry.read(scratch_key, "Value") is None
    registry.delete(scratch_key, "Value")  # deleting what is absent is fine


def test_reads_the_real_taskbar() -> None:
    io = tb.windows_taskbar_io()
    assert isinstance(io.read(), tb.TaskbarState)
    snapshot = io.snapshot()
    assert isinstance(snapshot[tb.AUTO_HIDE], bool)
    assert io.plan(io.read()) == {}  # what it reads, it would leave alone


def test_broadcast_returns() -> None:
    tb.broadcast_setting_change("TraySettings")
