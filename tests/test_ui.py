"""Smoke tests for the picker window, driven through pytest-qt against fake shortcuts."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from app.main import load_style
from app.service import IconService, Status
from app.ui.main_window import MainWindow
from app.updates import Release
from tests.conftest import load_sample
from tests.fakes import FakeDesktop

APPS = {"Arcade": "non_square", "Browser": "multicolor", "Music": "simple_glyph"}
RECIPES = 12


class Harness:
    def __init__(self, desktop: FakeDesktop, qtbot: QtBot) -> None:
        self.desktop = desktop
        self.qtbot = qtbot
        self.refreshes = 0
        # Text of every information/warning box the window tried to show.
        self.messages: list[str] = []
        self.release: Release | None = None
        self.window = MainWindow(
            desktop.service(), hard_refresh=self._hard_refresh, update_check=lambda: self.release
        )

    def _hard_refresh(self) -> None:
        self.refreshes += 1

    @property
    def service(self) -> IconService:
        return self.window.service

    def wait_for_previews(self, count: int = RECIPES) -> None:
        self.qtbot.waitUntil(lambda: len(self.window._cards) == count, timeout=15_000)

    def status(self, name: str) -> Status:
        return self.service.status(next(g for g in self.service.scan() if g.name == name))

    def lnk(self, name: str) -> Path:
        return self.desktop.desktop / f"{name}.lnk"


@pytest.fixture
def harness(
    tmp_path: Path, qtbot: QtBot, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Harness]:
    desktop = FakeDesktop(tmp_path, icons=APPS, default="dark")
    for name in APPS:
        desktop.make(name)
    desktop.make("Admin Tool", folder=desktop.common)
    load_style(qapp)
    h = Harness(desktop, qtbot)
    # Modal boxes would block a headless run forever; record them instead.
    for kind in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, kind, lambda parent, title, text: h.messages.append(text))
    qtbot.addWidget(h.window)
    h.window.show()
    qtbot.waitUntil(lambda: h.window.model.rowCount() == len(APPS) + 1, timeout=10_000)
    h.wait_for_previews()
    yield h
    h.window.close()
    assert h.messages == [], f"unexpected dialogs: {h.messages}"


@pytest.fixture
def say_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )


def test_launch_selects_first_untouched_and_shows_previews(harness: Harness) -> None:
    group = harness.window.current_group()
    assert group is not None
    assert group.name == "Arcade"  # the read-only Admin Tool is skipped
    assert harness.window.apply_button.isEnabled()
    assert not harness.window.revert_button.isEnabled()


def test_apply_themes_shortcut_and_advances(harness: Harness) -> None:
    before = harness.lnk("Arcade").read_bytes()
    harness.window.apply_chosen()
    assert harness.status("Arcade") is Status.THEMED
    assert harness.lnk("Arcade").read_bytes() != before
    current = harness.window.current_group()
    assert current is not None
    assert current.name == "Browser"


def test_double_click_applies_and_revert_restores(harness: Harness) -> None:
    before = harness.lnk("Arcade").read_bytes()
    card = harness.window._cards[2]
    card.activated.emit(card)
    assert harness.status("Arcade") is Status.THEMED

    arcade = harness.window.model.index(1, 0)
    harness.window.grid.setCurrentIndex(arcade)
    harness.wait_for_previews()
    assert harness.window.revert_button.isEnabled()
    harness.window.revert_current()
    assert harness.lnk("Arcade").read_bytes() == before
    assert harness.status("Arcade") is Status.ORIGINAL


def test_skip_marks_and_advances(harness: Harness) -> None:
    harness.window.skip_current()
    assert harness.status("Arcade") is Status.SKIPPED
    current = harness.window.current_group()
    assert current is not None
    assert current.name == "Browser"


def test_shuffle_rerolls_previews(harness: Harness) -> None:
    first = [card.image.copy() for card in harness.window._cards]
    harness.window.shuffle()
    harness.wait_for_previews()
    second = [card.image for card in harness.window._cards]
    assert any(a != b for a, b in zip(first, second, strict=True))


def test_revert_all_after_applying_everything(harness: Harness, say_yes: None) -> None:
    originals = {name: harness.lnk(name).read_bytes() for name in APPS}
    harness.window.apply_style_to_all()
    harness.qtbot.waitUntil(
        lambda: all(harness.status(name) is Status.THEMED for name in APPS), timeout=15_000
    )
    harness.window.revert_all()
    assert {name: harness.lnk(name).read_bytes() for name in APPS} == originals


def test_use_own_image(harness: Harness, tmp_path: Path) -> None:
    picture = tmp_path / "bunny.png"
    load_sample("gradient_app").save(picture)
    harness.window.use_own_image(picture)
    harness.wait_for_previews(RECIPES + 1)
    assert harness.window._cards[0].choice.is_custom
    harness.window._choose(harness.window._cards[0])
    assert not harness.window.all_button.isEnabled()
    harness.window.apply_chosen()
    assert harness.status("Arcade") is Status.THEMED


def test_read_only_shortcut_cannot_be_applied(harness: Harness) -> None:
    harness.window.grid.setCurrentIndex(harness.window.model.index(0, 0))
    harness.wait_for_previews()
    assert not harness.window.apply_button.isEnabled()
    assert not harness.window.own_image_button.isEnabled()


def test_hover_shows_real_size_popup(harness: Harness) -> None:
    card = harness.window._cards[0]
    card.hovered.emit(card, True)
    assert harness.window._popup.isVisible()
    card.hovered.emit(card, False)
    assert not harness.window._popup.isVisible()


def test_toolbar_actions(harness: Harness, say_yes: None) -> None:
    harness.window.apply_chosen()
    harness.window.reapply_all()
    assert "Nothing needed reapplying" in harness.window.statusBar().currentMessage()
    harness.window.clean_up()
    harness.window.refresh_icons()
    assert harness.refreshes == 1
    harness.window.theme_box.setCurrentIndex(0)
    harness.wait_for_previews()


def test_errors_become_a_dialog(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk is full")

    monkeypatch.setattr(harness.service, "apply", broken)
    harness.window.apply_chosen()
    assert len(harness.messages) == 1
    assert "disk is full" in harness.messages.pop()
    assert harness.status("Arcade") is Status.ORIGINAL


def test_popup_handles_point(harness: Harness) -> None:
    harness.window._popup.show_for(
        harness.window._cards[0].image, harness.window._cards[1].image, QPoint(10, 10)
    )
    assert harness.window._popup.isVisible()


def test_update_check_is_opt_in(harness: Harness) -> None:
    harness.release = Release("9.9.9", "https://github.com/qwopp/iconbloom/releases/v9.9.9")
    assert not harness.window.update_box.isChecked()
    harness.window.update_box.setChecked(True)
    harness.qtbot.waitUntil(lambda: "9.9.9" in harness.window.update_label.text(), timeout=5_000)
    assert harness.window.service.paths.settings.exists()
