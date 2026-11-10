"""The Iconbloom window: assembles the panels and turns button presses into changes."""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import override

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.changes import ChangeReport, Status
from app.service import IconService
from app.settings import Settings
from app.ui import UI_DIR, palette
from app.ui.change_runner import ChangeRunner
from app.ui.controls import count, guarded, make_button, without_arguments
from app.ui.jobs import JobRunner
from app.ui.notice import NoticeBar
from app.ui.shortcut_list import ShortcutList
from app.ui.style_picker import StylePicker
from app.ui.update_flow import UpdateFlow
from app.updates import Updater
from engine.themes import DEFAULT_THEME

APP_ICON = UI_DIR / "iconbloom.png"
# Wait this long after the selection moves before rendering, so holding an
# arrow key doesn't queue a full render for every icon it passes.
SELECT_DELAY_MS = 80
STATUS_MESSAGE_MS = 5000


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: IconService,
        *,
        hard_refresh: Callable[[], None],
        updater: Updater | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.settings = Settings.load(service.paths.settings)
        self.jobs = JobRunner(self)
        self._hard_refresh = hard_refresh
        self._theme_names = service.styles.theme_names()
        known = [theme_id for theme_id, _ in self._theme_names]
        theme = service.styles.theme(DEFAULT_THEME if DEFAULT_THEME in known else known[0])

        self.setWindowTitle("Iconbloom")
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1180, 760)
        self.notice = NoticeBar()
        self.shortcuts = ShortcutList(service, self.jobs)
        self.picker = StylePicker(service, self.jobs, theme)
        self.changes = ChangeRunner(
            self,
            self.jobs,
            self.notice,
            self.statusBar(),
            self.settings,
            service.paths,
            refresh_icons=self.refresh_icons,
            reload=self.shortcuts.reload,
        )
        self.updates = UpdateFlow(
            self,
            self.jobs,
            self.notice,
            updater or Updater(),
            service.paths.root / "updates",
            close_app=self.close,
        )
        self._build(theme.id)
        self._connect()
        self.set_dark_mode(self._wants_dark_mode(), save=False)

        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        self._select_timer.setInterval(SELECT_DELAY_MS)
        self._select_timer.timeout.connect(self._show_current)
        QTimer.singleShot(0, self.shortcuts.reload)
        if self.settings.check_for_updates:
            QTimer.singleShot(0, self.updates.check)

    # ---- layout -------------------------------------------------------------

    def _build(self, theme_id: str) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 18)
        outer.setSpacing(12)
        outer.addLayout(self._build_top_bar(theme_id))
        outer.addWidget(self.notice)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.shortcuts)
        splitter.addWidget(self.picker)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self._build_status_bar()

    def _build_top_bar(self, theme_id: str) -> QHBoxLayout:
        bar = QHBoxLayout()
        title = QLabel("Iconbloom")
        title.setObjectName("title")
        bar.addWidget(title)
        bar.addSpacing(16)
        bar.addWidget(QLabel("Theme"))
        self.theme_box = QComboBox()
        for known_id, name in self._theme_names:
            self.theme_box.addItem(name, known_id)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(theme_id)))
        self.theme_box.setToolTip("The look every style is drawn in")
        bar.addWidget(self.theme_box)
        bar.addStretch(1)
        bar.addWidget(self._build_more_menu())
        bar.addWidget(
            make_button(
                "Revert all",
                "danger",
                "Put every icon and taskbar setting Iconbloom changed back to the original",
                self.revert_all,
            )
        )
        return bar

    def _build_more_menu(self) -> QToolButton:
        self.more_menu = QMenu(self)
        self.more_menu.setToolTipsVisible(True)
        for text, slot, tip in (
            (
                "Reapply my icons",
                self.reapply_all,
                "Put your chosen styles back on icons that an app update reset",
            ),
            (
                "Refresh Windows icons…",
                self.refresh_icons,
                "Clear Windows' icon cache and restart Explorer, for icons that look stale",
            ),
            (
                "Delete unused icon files",
                self.clean_up,
                "Remove icons Iconbloom made earlier that nothing uses any more",
            ),
        ):
            action = self.more_menu.addAction(text)
            action.setToolTip(tip)
            action.triggered.connect(without_arguments(slot))
        self.more_menu.addSeparator()
        self.dark_mode_action = self.more_menu.addAction("Dark mode")
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.setToolTip("Switch Iconbloom's window between light and dark")
        self.dark_mode_action.toggled.connect(self.set_dark_mode)
        more = QToolButton()
        more.setObjectName("more")
        more.setText("More")
        more.setToolTip("Less common actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setMenu(self.more_menu)
        return more

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.update_box = QCheckBox("Check for updates")
        self.update_box.setToolTip(
            "Ask GitHub for a newer version when Iconbloom starts. It's the only time "
            "Iconbloom uses the internet, and nothing is installed unless you click Update now."
        )
        self.update_box.setChecked(self.settings.check_for_updates)
        self.update_box.toggled.connect(self._on_update_toggled)
        bar.addPermanentWidget(self.update_box)
        bar.addPermanentWidget(QLabel(f"v{__version__}"))

    def _connect(self) -> None:
        self.theme_box.currentIndexChanged.connect(self._on_theme_changed)
        self.shortcuts.current_changed.connect(self._on_current_changed)
        self.shortcuts.selection_changed.connect(self._update_actions)
        self.shortcuts.scanned.connect(self._on_scanned)
        self.picker.chosen_changed.connect(self._update_actions)
        self.picker.activated.connect(self.apply_chosen)
        picker = self.picker
        picker.own_image_button.clicked.connect(without_arguments(self.use_own_image))
        picker.revert_button.clicked.connect(without_arguments(self.revert_selected))
        picker.all_button.clicked.connect(without_arguments(self.apply_style_to_all))
        picker.skip_button.clicked.connect(without_arguments(self.skip_selected))
        picker.apply_button.clicked.connect(without_arguments(self.apply_chosen))
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.applicationStateChanged.connect(self._on_app_state_changed)

    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        # Coming back to the window after installing or deleting something: show it.
        # A change in progress reloads the list itself when it finishes.
        if state is Qt.ApplicationState.ApplicationActive and not self.changes.running:
            self.shortcuts.rescan()

    # ---- following the selection --------------------------------------------

    def _on_current_changed(self) -> None:
        self.picker.reset()
        if self.shortcuts.current_group() is not None:
            self._select_timer.start()

    def _show_current(self) -> None:
        target = self.shortcuts.current_group()
        if target is not None:
            self.picker.show_group(target)

    def _on_scanned(self, found: int) -> None:
        if not found:
            self.picker.show_message("No icons found on your desktop or Start menu.")

    def _update_actions(self) -> None:
        self.picker.update_actions(self.shortcuts.selected_groups())

    def _on_theme_changed(self) -> None:
        theme_id = self.theme_box.currentData()
        if isinstance(theme_id, str):
            theme = guarded(self, lambda: self.service.styles.theme(theme_id))
            if theme is not None:
                self.picker.set_theme(theme)

    # ---- actions ------------------------------------------------------------

    def apply_chosen(self) -> None:
        card = self.picker.chosen
        targets = self.shortcuts.selected_groups()
        if card is None or not targets:
            return
        include_shared = self.changes.ask_about_shared(targets)
        if include_shared is None:
            return
        prepared = {
            t.key: icon for t in targets if (icon := self.picker.prepared_icon(t)) is not None
        }
        choice = card.choice

        def done(report: ChangeReport) -> None:
            if len(targets) == 1:
                # Stay on the icon just styled, with its style still picked.
                self.picker.update_group(self.shortcuts.refresh_group(targets[0]))
                self._update_actions()
            else:
                self.shortcuts.reload()
            if report.changed:
                self._say(f"Applied “{card.label}” to {count(report.changed, 'icon')}")

        self.changes.run(
            "Applying your style…",
            targets,
            lambda progress: self.service.apply_many(
                targets,
                lambda _g: choice,
                include_shared=include_shared,
                prepared=prepared,
                progress=progress,
            ),
            done,
        )

    def skip_selected(self) -> None:
        targets = self.shortcuts.selected_groups()
        for target in targets:
            self.service.skip(target)
            self.shortcuts.refresh_group(target)
        if targets:
            self.shortcuts.select_next_untouched()

    def revert_selected(self) -> None:
        targets = [
            g for g in self.shortcuts.selected_groups() if self.service.status(g) is Status.THEMED
        ]
        if not targets:
            return

        def done(_report: ChangeReport) -> None:
            for target in targets:
                self.shortcuts.refresh_group(target)
            current = self.shortcuts.current_group()
            if current is not None:
                self.picker.show_group(current)
            names = targets[0].name if len(targets) == 1 else count(targets, "icon")
            self._say(f"{names}: back to the original icon")

        self.changes.run(
            "Putting the original back…",
            targets,
            lambda _progress: _merged(self.service.revert(t) for t in targets),
            done,
        )

    def revert_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Revert everything?",
            "Put every icon and taskbar setting Iconbloom changed back to the original?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.changes.run(
            "Putting every original back…",
            [],
            lambda _progress: self.service.revert_all(),
            lambda report: self._say(_reverted(report)),
            reload=True,
        )

    def use_own_image(self, path: Path | None = None) -> None:
        """Style a picture of the user's own; while one is in use, the same button goes
        back to the app's icon."""
        target = self.shortcuts.current_group()
        if target is None:
            return
        if path is None and self.service.own_image(target) is not None:
            self.picker.use_custom_image(target, None)
            return
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Use my own image", str(Path.home()), "Images (*.png *.ico *.bmp)"
            )
            if not chosen:
                return
            path = Path(chosen)
        source = path
        choice = guarded(self, lambda: self.service.styles.store_custom_image(source))
        if choice is not None and choice.custom_image is not None:
            self.picker.use_custom_image(target, choice.custom_image)

    def apply_style_to_all(self) -> None:
        card = self.picker.chosen
        if card is None or card.choice.uses_own_image:
            return
        choice = card.choice
        targets = [g for g in self.shortcuts.groups if self.service.is_untouched(g)]
        answer = QMessageBox.question(
            self,
            "Apply this style to all?",
            f"Use “{card.label}” on {count(targets, 'untouched icon')}?",
        )
        if answer != QMessageBox.StandardButton.Yes or not targets:
            return
        include_shared = self.changes.ask_about_shared(targets)
        if include_shared is None:
            return
        self.changes.run(
            "Styling your icons…",
            targets,
            lambda progress: self.service.apply_many(
                targets, lambda _g: choice, include_shared=include_shared, progress=progress
            ),
            lambda report: self._say(f"Applied “{card.label}” to {count(report.changed, 'icon')}"),
            reload=True,
        )

    def reapply_all(self) -> None:
        lost = [g for g in self.shortcuts.groups if self.service.status(g) is Status.NEEDS_REAPPLY]
        if not lost:
            self._say("Nothing needed reapplying")
            return
        include_shared = self.changes.ask_about_shared(lost)
        if include_shared is None:
            return
        self.changes.run(
            "Reapplying your icons…",
            lost,
            lambda progress: self.service.reapply(
                lost, include_shared=include_shared, progress=progress
            ),
            lambda report: self._say(f"Reapplied {count(report.changed, 'icon')}"),
            reload=True,
        )

    def refresh_icons(self) -> None:
        answer = QMessageBox.question(
            self,
            "Refresh icons?",
            "If some icons still look old, Windows can clear its icon cache and redraw "
            "them all. This restarts Explorer, so the taskbar disappears for a few "
            "seconds.\n\nContinue?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            guarded(self, self._hard_refresh)

    def clean_up(self) -> None:
        report = guarded(self, self.service.cleanup)
        if report is not None:
            self._say(f"Removed {count(report.removed, 'unused icon file')}")

    def _on_update_toggled(self, enabled: bool) -> None:
        self.settings.check_for_updates = enabled
        self.settings.update_check_chosen = True
        guarded(self, lambda: self.settings.save(self.service.paths.settings))
        if enabled:
            self.updates.check()

    def _wants_dark_mode(self) -> bool:
        chosen = self.settings.dark_mode
        return palette.windows_prefers_dark() if chosen is None else chosen

    def set_dark_mode(self, dark: bool, save: bool = True) -> None:
        """Restyle the whole window; ``save`` remembers it as the user's choice."""
        app = QApplication.instance()
        if isinstance(app, QApplication):
            palette.apply(app, palette.DARK if dark else palette.LIGHT)
        self.shortcuts.grid.viewport().update()
        with QSignalBlocker(self.dark_mode_action):
            self.dark_mode_action.setChecked(dark)
        if save:
            self.settings.dark_mode = dark
            guarded(self, lambda: self.settings.save(self.service.paths.settings))

    def _say(self, message: str) -> None:
        self.statusBar().showMessage(message, STATUS_MESSAGE_MS)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self._select_timer.stop()
        self.jobs.shutdown()
        super().closeEvent(event)


def _reverted(report: ChangeReport) -> str:
    message = f"Reverted {count(report.changed, 'icon')}"
    return message + " and the taskbar" if report.taskbar else message


def _merged(reports: Iterable[ChangeReport]) -> ChangeReport:
    merged = ChangeReport(dry_run=False)
    for report in reports:
        merged.extend(report)
    return merged
