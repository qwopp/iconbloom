"""Shortcuts every user shares that an update reset: offered from the sign-in copy in a
small corner notice, and only changed after Put back and Windows' permission prompt."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from app import main
from app.changes import shared_reset_message
from app.choices import Choice
from app.service import IconService
from app.settings import Settings
from platform_win import watch
from platform_win.startup import FIX_ICONS_FLAG
from platform_win.watch import Wake
from tests.fakes import FakeDesktop, ScriptedWatch
from tests.ui_harness import button

CHOICE = Choice("kawaii_pink", "sticker")


def test_the_message_names_the_apps() -> None:
    one = shared_reset_message(["Google Chrome"])
    assert "Google Chrome's icon" in one
    assert "every user on this PC shares" in one
    three = shared_reset_message(["Google Chrome", "Google Play Games", "Roblox"])
    assert "Google Chrome, Google Play Games and Roblox" in three
    assert "Putting them back" in three


def _reset_chrome(env: FakeDesktop) -> tuple[IconService, Path]:
    """Chrome installed for all users, styled with permission, then reset by its update."""
    shared = env.make("Chrome", folder=env.common)
    env.pin(shared)
    service = env.service()
    group = next(g for g in service.scan() if g.name == "Chrome")
    service.apply(group, CHOICE, include_shared=True)
    env.link_io.create(shared, r"C:\Apps\Chrome.exe")
    return service, shared


def test_put_back_asks_permission_and_fixes_them(env: FakeDesktop, qtbot: QtBot) -> None:
    service, shared = _reset_chrome(env)
    prompts = len(env.elevations)
    notice = main.shared_reset_notice(service)
    assert notice is not None
    qtbot.addWidget(notice)
    notice.show_in_corner()
    assert "Chrome's icon" in notice.bar.label.text()
    button(notice, "Put back").click()
    assert len(env.elevations) == prompts + 1
    assert service.is_ours(env.link_io.read(shared).icon)
    assert not notice.isVisible()


def test_not_now_changes_nothing(env: FakeDesktop, qtbot: QtBot) -> None:
    service, shared = _reset_chrome(env)
    prompts = len(env.elevations)
    notice = main.shared_reset_notice(service)
    assert notice is not None
    qtbot.addWidget(notice)
    notice.show_in_corner()
    button(notice, "Not now").click()
    assert len(env.elevations) == prompts
    assert not service.is_ours(env.link_io.read(shared).icon)
    assert not notice.isVisible()


def test_no_notice_once_nothing_shared_is_reset(env: FakeDesktop) -> None:
    env.make("Paint")
    assert main.shared_reset_notice(env.service()) is None


@pytest.fixture
def keeping(desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """app.main's --fix-icons with the option on, for three passes; returns the offers."""
    offers: list[str] = []
    monkeypatch.setattr(
        watch, "WindowsFolderWatch", lambda folders: ScriptedWatch([Wake.QUIET, Wake.QUIET])
    )
    monkeypatch.setattr(main, "start_detached", offers.append)
    desktop.sign_in.set(True)
    return offers


def test_the_sign_in_copy_offers_a_shared_reset_once(
    desktop: FakeDesktop, keeping: list[str]
) -> None:
    _reset_chrome(desktop)
    assert main.main([FIX_ICONS_FLAG]) == 0
    assert keeping == [main.OFFER_SHARED_FLAG]  # three passes, one offer


def test_no_offer_when_shared_shortcuts_are_skipped(
    desktop: FakeDesktop, keeping: list[str]
) -> None:
    _reset_chrome(desktop)
    Settings(shared_shortcuts="skip").save(desktop.paths.settings)
    assert main.main([FIX_ICONS_FLAG]) == 0
    assert keeping == []


def test_own_resets_are_put_back_without_an_offer(desktop: FakeDesktop, keeping: list[str]) -> None:
    service, lnk = desktop.styled_then_reset()
    assert main.main([FIX_ICONS_FLAG]) == 0
    assert service.is_ours(desktop.link_io.read(lnk).icon)
    assert keeping == []
