"""Smoke tests for the picker window, driven through pytest-qt against fake shortcuts."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import override

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from app.main import load_style
from app.service import ChangeReport, IconService, Status
from app.settings import Settings
from app.ui.main_window import MainWindow
from app.updates import Release, Updater
from platform_win.shortcuts import Place
from tests.conftest import load_sample
from tests.fakes import FakeDesktop

APPS = {"Arcade": "non_square", "Browser": "multicolor", "Music": "simple_glyph"}
RECIPES = 12


class FakeUpdater(Updater):
    """GitHub stand-in: offers ``release`` and 'downloads' a dummy installer."""

    def __init__(self) -> None:
        super().__init__()
        self.release: Release | None = None
        self.launched: list[Path] = []

    @override
    def check(self, timeout: float = 5.0) -> Release | None:
        return self.release

    @override
    def download(
        self, release: Release, folder: Path, progress: Callable[[int, int], None] | None = None
    ) -> Path:
        if progress is not None:
            progress(5, 10)
        folder.mkdir(parents=True, exist_ok=True)
        installer = folder / release.installer_name
        installer.write_bytes(b"installer")
        return installer

    @override
    def launch(self, installer: Path) -> None:
        self.launched.append(installer)


class Harness:
    def __init__(self, desktop: FakeDesktop, qtbot: QtBot) -> None:
        self.desktop = desktop
        self.qtbot = qtbot
        self.refreshes = 0
        # Text of every information/warning box the window tried to show.
        self.messages: list[str] = []
        self.updater = FakeUpdater()
        self.window = MainWindow(
            desktop.service(), hard_refresh=self._hard_refresh, updater=self.updater
        )

    def _hard_refresh(self) -> None:
        self.refreshes += 1

    @property
    def service(self) -> IconService:
        return self.window.service

    def settle(self) -> None:
        """Wait until every background action has finished and reported back."""
        self.qtbot.waitUntil(lambda: not self.window._jobs, timeout=15_000)
        self.qtbot.wait(20)

    def select(self, *names: str) -> None:
        """Click the first name, then ctrl-click the rest."""
        grid = self.window.grid
        rows = {self.window.model.item(r).text(): r for r in range(self.window.model.rowCount())}
        grid.setCurrentIndex(self.window.model.index(rows[names[0]], 0))
        selection = grid.selectionModel()
        for name in names[1:]:
            selection.select(
                self.window.model.index(rows[name], 0), QItemSelectionModel.SelectionFlag.Select
            )
        self.wait_for_previews()

    def wait_for_previews(self, count: int = RECIPES) -> None:
        self.qtbot.waitUntil(lambda: len(self.window._cards) == count, timeout=15_000)

    def status(self, name: str) -> Status:
        return self.service.status(next(g for g in self.service.scan() if g.name == name))

    def lnk(self, name: str) -> Path:
        return self.desktop.desktop / f"{name}.lnk"

    def path(self, name: str) -> Path:
        mine = self.lnk(name)
        return mine if mine.exists() else self.desktop.common / f"{name}.lnk"


@pytest.fixture
def harness(
    tmp_path: Path, qtbot: QtBot, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Harness]:
    desktop = FakeDesktop(tmp_path, icons=APPS, default="dark")
    # The first-run update question is tested on its own below.
    Settings(asked_about_updates=True).save(desktop.paths.settings)
    for name in APPS:
        desktop.make(name)
    desktop.make("Admin Tool", folder=desktop.common)
    load_style(qapp)
    h = Harness(desktop, qtbot)
    # Shared shortcuts go through the fake permission prompt without asking each time.
    h.window.settings.shared_shortcuts = "include"
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
    assert group.name == "Arcade"  # desktop shortcuts first, the shared Admin Tool last
    assert harness.window.apply_button.isEnabled()
    assert not harness.window.revert_button.isEnabled()


def test_apply_themes_shortcut_and_advances(harness: Harness) -> None:
    before = harness.lnk("Arcade").read_bytes()
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED
    assert harness.lnk("Arcade").read_bytes() != before
    current = harness.window.current_group()
    assert current is not None
    assert current.name == "Browser"


def test_double_click_applies_and_revert_restores(harness: Harness) -> None:
    before = harness.lnk("Arcade").read_bytes()
    card = harness.window._cards[2]
    card.activated.emit(card)
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED

    harness.select("Arcade")
    assert harness.window.revert_button.isEnabled()
    harness.window.revert_current()
    harness.settle()
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
    names = [*APPS, "Admin Tool"]
    originals = {name: harness.path(name).read_bytes() for name in names}
    harness.window.apply_style_to_all()
    harness.settle()
    assert all(harness.status(name) is Status.THEMED for name in names)
    harness.window.revert_all()
    harness.settle()
    assert harness.status("Admin Tool") is Status.ORIGINAL
    for name in APPS:
        assert harness.path(name).read_bytes() == originals[name]


def test_use_own_image(harness: Harness, tmp_path: Path) -> None:
    picture = tmp_path / "bunny.png"
    load_sample("gradient_app").save(picture)
    harness.window.use_own_image(picture)
    harness.wait_for_previews(RECIPES + 1)
    assert harness.window._cards[0].choice.is_custom
    harness.window._choose(harness.window._cards[0])
    assert not harness.window.all_button.isEnabled()
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Arcade") is Status.THEMED


def test_shared_shortcut_is_changed_after_permission(harness: Harness) -> None:
    harness.select("Admin Tool")
    assert harness.window.apply_button.isEnabled()
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Admin Tool") is Status.THEMED
    assert len(harness.desktop.elevations) == 1


def test_shared_shortcut_left_alone_when_declined(harness: Harness) -> None:
    harness.desktop.decline_permission = True
    harness.select("Admin Tool")
    harness.window.apply_chosen()
    harness.settle()
    assert harness.status("Admin Tool") is Status.ORIGINAL
    assert "Left 1 shared shortcut" in harness.window.statusBar().currentMessage()


def test_remembered_skip_never_asks_for_permission(harness: Harness) -> None:
    harness.window.settings.shared_shortcuts = "skip"
    harness.select("Admin Tool")
    harness.window.apply_chosen()
    harness.settle()
    assert harness.desktop.elevations == []
    assert harness.status("Admin Tool") is Status.ORIGINAL


def test_search_and_place_tabs_filter_the_grid(harness: Harness) -> None:
    window = harness.window

    def visible() -> list[str]:
        model = window.model
        return [
            model.item(r).text() for r in range(model.rowCount()) if not window.grid.isRowHidden(r)
        ]

    assert visible() == ["Arcade", "Browser", "Music", "Admin Tool"]
    window.search.setText("mu")
    assert visible() == ["Music"]
    assert window.current_group() is not None
    window.search.setText("nothing like this")
    assert visible() == []
    assert window.empty_label.isVisibleTo(window)
    window.search.clear()
    window._place_buttons[Place.START_MENU].click()
    assert visible() == ["Admin Tool"]
    assert window._place_buttons[Place.DESKTOP].text() == "Desktop (3)"


def test_multi_select_previews_and_applies_to_all(harness: Harness) -> None:
    harness.select("Arcade", "Browser", "Music")
    window = harness.window
    assert window.apply_button.text() == "Apply to 3"
    assert window.selection_strip.isVisibleTo(window)
    harness.qtbot.waitUntil(
        lambda: all(
            window.selection_icons.itemAt(i).widget().pixmap().width() > 0  # type: ignore[union-attr]
            for i in range(3)
        ),
        timeout=15_000,
    )
    window.apply_chosen()
    harness.settle()
    assert all(harness.status(name) is Status.THEMED for name in APPS)
    harness.select("Arcade", "Music")
    window.revert_current()
    harness.settle()
    assert harness.status("Arcade") is Status.ORIGINAL
    assert harness.status("Music") is Status.ORIGINAL
    assert harness.status("Browser") is Status.THEMED


def test_taskbar_change_offers_a_refresh(harness: Harness) -> None:
    report = ChangeReport(dry_run=False, changed=[Path("C:/Users/x/User Pinned/TaskBar/A.lnk")])
    harness.window._show_taskbar_notice(report)
    assert harness.window.notice.isVisibleTo(harness.window)


def test_hover_shows_real_size_popup(harness: Harness) -> None:
    card = harness.window._cards[0]
    card.hovered.emit(card, True)
    assert harness.window._popup.isVisible()
    card.hovered.emit(card, False)
    assert not harness.window._popup.isVisible()


def test_toolbar_actions(harness: Harness, say_yes: None) -> None:
    harness.window.apply_chosen()
    harness.settle()
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

    monkeypatch.setattr(harness.service, "apply_many", broken)
    harness.window.apply_chosen()
    harness.settle()
    assert len(harness.messages) == 1
    assert "disk is full" in harness.messages.pop()
    assert harness.status("Arcade") is Status.ORIGINAL


def test_popup_handles_point(harness: Harness) -> None:
    harness.window._popup.show_for(
        harness.window._cards[0].image, harness.window._cards[1].image, QPoint(10, 10)
    )
    assert harness.window._popup.isVisible()


RELEASE = Release(
    "9.9.9",
    "https://github.com/qwopp/iconbloom/releases/v9.9.9",
    installer_url="https://dl/setup.exe",
    checksums_url="https://dl/sums",
)


def test_first_launch_asks_before_checking_for_updates(
    tmp_path: Path, qtbot: QtBot, qapp: QApplication
) -> None:
    desktop = FakeDesktop(tmp_path)
    desktop.make("Paint")
    updater = FakeUpdater()
    updater.release = RELEASE
    window = MainWindow(desktop.service(), hard_refresh=lambda: None, updater=updater)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(window.notice.isVisible, timeout=5_000)
    assert "new version" in window.notice_label.text()
    window.update_box.setChecked(True)  # what "Yes, check" does
    qtbot.waitUntil(lambda: "ready to install" in window.notice_label.text(), timeout=5_000)
    saved = Settings.load(desktop.paths.settings)
    assert saved.check_for_updates
    assert saved.asked_about_updates
    window.close()


def test_update_downloads_installs_and_closes(harness: Harness) -> None:
    harness.updater.release = RELEASE
    harness.window.update_box.setChecked(True)
    harness.qtbot.waitUntil(
        lambda: "9.9.9 is ready" in harness.window.notice_label.text(), timeout=5_000
    )
    harness.window.install_update()
    harness.qtbot.waitUntil(lambda: bool(harness.updater.launched), timeout=5_000)
    assert harness.updater.launched[0].name == "Iconbloom-Setup-9.9.9.exe"
    assert not harness.window.isVisible()
