"""Drive the real window offscreen against a fake desktop, for the UI tests.

Loaded as a pytest plugin (see conftest.py), so its fixtures work in every UI test.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import override

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from pytestqt.qtbot import QtBot

from app.main import load_style
from app.service import IconService, Status
from app.ui.main_window import MainWindow
from app.updates import Release, Updater
from tests.fakes import FakeDesktop

APPS = {"Arcade": "non_square", "Browser": "multicolor", "Music": "simple_glyph"}
RECIPES = 12


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
        self.qtbot.waitUntil(lambda: not self.window.jobs.busy, timeout=15_000)
        self.qtbot.wait(20)

    def select(self, *names: str) -> None:
        """Click the first name, then ctrl-click the rest."""
        grid = self.window.shortcuts.grid
        rows = {
            self.window.shortcuts.model.item(r).text(): r
            for r in range(self.window.shortcuts.model.rowCount())
        }
        grid.setCurrentIndex(self.window.shortcuts.model.index(rows[names[0]], 0))
        selection = grid.selectionModel()
        for name in names[1:]:
            selection.select(
                self.window.shortcuts.model.index(rows[name], 0),
                QItemSelectionModel.SelectionFlag.Select,
            )
        self.wait_for_previews()

    def strip_pictures(self) -> list[bool]:
        """For each icon in the multi-select strip: has its preview been drawn yet?"""
        icons = self.window.picker.selection_icons
        drawn: list[bool] = []
        for i in range(icons.count()):
            item = icons.itemAt(i)
            label = item.widget() if item is not None else None
            drawn.append(isinstance(label, QLabel) and not label.pixmap().isNull())
        return drawn

    def wait_for_previews(self, count: int = RECIPES) -> None:
        self.qtbot.waitUntil(lambda: len(self.window.picker.cards) == count, timeout=15_000)

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
    qtbot.waitUntil(lambda: h.window.shortcuts.model.rowCount() == len(APPS) + 1, timeout=10_000)
    h.wait_for_previews()
    yield h
    h.window.close()
    assert h.messages == [], f"unexpected dialogs: {h.messages}"


@pytest.fixture
def say_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )


RELEASE = Release(
    "9.9.9",
    "https://github.com/qwopp/iconbloom/releases/v9.9.9",
    installer_url="https://dl/setup.exe",
    checksums_url="https://dl/sums",
)


def open_window(desktop: FakeDesktop, updater: FakeUpdater, qtbot: QtBot) -> MainWindow:
    window = MainWindow(desktop.service(), hard_refresh=lambda: None, updater=updater)
    qtbot.addWidget(window)
    window.show()
    return window
