"""Shortcuts every user shares that an update reset: offered from the sign-in copy in a
small corner notice, and only changed after Put back and Windows' permission prompt."""

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from app import main
from app.changes import shared_reset_message
from app.choices import Choice
from app.service import IconService
from app.settings import Settings
from app.ui.shared_notice import SharedResetNotice
from platform_win import watch
from platform_win.shortcuts import IconLocation
from platform_win.startup import FIX_ICONS_FLAG
from tests.fakes import FakeDesktop

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


def _button(notice: SharedResetNotice, text: str) -> QPushButton:
    return next(b for b in notice.findChildren(QPushButton) if b.text() == text)


def test_put_back_asks_permission_and_fixes_them(env: FakeDesktop, qtbot: QtBot) -> None:
    service, shared = _reset_chrome(env)
    prompts = len(env.elevations)
    notice = main.shared_reset_notice(service)
    assert notice is not None
    qtbot.addWidget(notice)
    notice.show_in_corner()
    assert "Chrome's icon" in notice.bar.label.text()
    _button(notice, "Put back").click()
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
    _button(notice, "Not now").click()
    assert len(env.elevations) == prompts
    assert not service.is_ours(env.link_io.read(shared).icon)
    assert not notice.isVisible()


def test_no_notice_once_nothing_shared_is_reset(env: FakeDesktop) -> None:
    env.make("Paint")
    assert main.shared_reset_notice(env.service()) is None


class QuietThenStop:
    """Two more passes (nothing changed, just the clock), then a stop."""

    def __init__(self) -> None:
        self._wakes = [watch.Wake.QUIET, watch.Wake.QUIET]

    def wait(self, seconds: float) -> watch.Wake:
        return self._wakes.pop(0) if self._wakes else watch.Wake.STOP


@pytest.fixture
def keeping(env: FakeDesktop, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """app.main's --fix-icons on the fake desktop with the option on; returns the offers."""
    offers: list[str] = []
    monkeypatch.setattr(main, "windows_service", lambda paths: env.service())
    monkeypatch.setattr(watch, "first_copy", object)
    monkeypatch.setattr(watch, "windows_folder_watch", lambda folders: QuietThenStop())
    monkeypatch.setattr(main, "start_offer", lambda: offers.append("offer"))
    monkeypatch.setattr(main, "setup_logging", lambda folder: None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() replaces it
    env.sign_in.set(True)
    return offers


def test_the_sign_in_copy_offers_a_shared_reset_once(
    env: FakeDesktop, keeping: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "default_app_paths", lambda: env.paths)
    _reset_chrome(env)
    assert main.main([FIX_ICONS_FLAG]) == 0
    assert keeping == ["offer"]  # three passes, one offer


def test_no_offer_when_shared_shortcuts_are_skipped(
    env: FakeDesktop, keeping: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "default_app_paths", lambda: env.paths)
    _reset_chrome(env)
    Settings(shared_shortcuts="skip").save(env.paths.settings)
    assert main.main([FIX_ICONS_FLAG]) == 0
    assert keeping == []


def test_own_resets_are_put_back_without_an_offer(
    env: FakeDesktop, keeping: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "default_app_paths", lambda: env.paths)
    lnk = env.make("Paint")
    service = env.service()
    service.apply(next(g for g in service.scan() if g.name == "Paint"), CHOICE)
    env.link_io.set_icon(lnk, IconLocation(r"C:\Apps\Paint.exe", 0))
    assert main.main([FIX_ICONS_FLAG]) == 0
    assert service.is_ours(env.link_io.read(lnk).icon)
    assert keeping == []
