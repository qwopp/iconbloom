"""The picker window: shortcuts on the left, styled options for the selected one on the right."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import override

from PIL import Image
from PySide6.QtCore import QModelIndex, QPoint, Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QImage, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import __version__, updates
from app.choices import CUSTOM_RECIPE, Choice
from app.service import IconService, Status
from app.settings import Settings
from app.ui import UI_DIR
from app.ui.widgets import (
    KEY_ROLE,
    STATUS_COLORS,
    STATUS_ROLE,
    WRITABLE_ROLE,
    Job,
    PreviewCard,
    SizePopup,
    TileDelegate,
    pixmap_at,
    to_qimage,
)
from app.updates import Release
from engine import analyze, ops
from engine.recipes import render
from engine.themes import THEMES_DIR, Theme, list_themes, load_theme
from platform_win.shortcuts import ShortcutGroup

log = logging.getLogger(__name__)

APP_ICON = UI_DIR / "iconbloom.png"
PREVIEW_COLUMNS = 4
DEFAULT_THEME = "kawaii_pink"


@dataclass(frozen=True)
class Preview:
    key: str
    label: str
    choice: Choice
    full: Image.Image
    image: QImage


@dataclass(frozen=True)
class PreviewSet:
    group_key: str
    # The prepared original, kept for the simplified small-size render on apply.
    icon: Image.Image
    original: QImage
    upscaled: bool
    previews: list[Preview]


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: IconService,
        *,
        hard_refresh: Callable[[], None],
        themes_dir: Path = THEMES_DIR,
        update_check: Callable[[], Release | None] = updates.check,
    ) -> None:
        super().__init__()
        self.service = service
        self._hard_refresh = hard_refresh
        self._themes_dir = themes_dir
        self._update_check = update_check
        self.settings = Settings.load(service.paths.settings)
        self._pool = QThreadPool(self)
        self._groups: dict[str, ShortcutGroup] = {}
        self._token = 0
        self._seed = 0
        self._previews: PreviewSet | None = None
        self._cards: list[PreviewCard] = []
        self._chosen: PreviewCard | None = None
        self._custom: Preview | None = None
        self._jobs: set[Job] = set()
        self.theme = self._load_initial_theme()

        self.setWindowTitle("Iconbloom")
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1180, 760)
        self._popup = SizePopup(self)
        self._build()
        self._build_status_bar()
        QTimer.singleShot(0, self.reload_shortcuts)
        if self.settings.check_for_updates:
            QTimer.singleShot(0, self.check_for_updates)

    # ---- layout -------------------------------------------------------------

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 18)
        outer.setSpacing(12)
        outer.addLayout(self._build_top_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_grid())
        splitter.addWidget(self._build_preview_pane())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        title = QLabel("Iconbloom")
        title.setObjectName("title")
        bar.addWidget(title)
        bar.addSpacing(16)
        bar.addWidget(QLabel("Theme"))
        self.theme_box = QComboBox()
        for theme_id in list_themes(self._themes_dir):
            self.theme_box.addItem(load_theme(theme_id, self._themes_dir).name, theme_id)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self.theme.id)))
        self.theme_box.currentIndexChanged.connect(self._on_theme_changed)
        bar.addWidget(self.theme_box)
        bar.addStretch(1)
        self.reapply_button = self._button("Reapply my icons", self.reapply_all, "secondary")
        self.reapply_button.setToolTip("Re-theme shortcuts that an app update reset")
        bar.addWidget(self.reapply_button)
        bar.addWidget(self._button("Refresh icons", self.refresh_icons, "secondary"))
        bar.addWidget(self._button("Clean up", self.clean_up, "secondary"))
        bar.addWidget(self._button("Revert all", self.revert_all, "danger"))
        return bar

    def _build_grid(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel("Your shortcuts")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        self.model = QStandardItemModel(self)
        self.grid = QListView()
        self.grid.setObjectName("grid")
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setGridSize(TileDelegate.SIZE)
        self.grid.setSpacing(4)
        self.grid.setMouseTracking(True)
        self.grid.setItemDelegate(TileDelegate(self.grid))
        self.grid.setModel(self.model)
        self.grid.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self.grid, 1)
        self.legend = QLabel(
            "   ".join(
                f'<span style="color:{STATUS_COLORS[status].name()}">\u25cf</span> {label}'
                for status, label in (
                    (Status.THEMED, "themed"),
                    (Status.ORIGINAL, "untouched"),
                    (Status.SKIPPED, "skipped"),
                    (Status.NEEDS_REAPPLY, "needs reapply"),
                )
            )
        )
        self.legend.setObjectName("legend")
        layout.addWidget(self.legend)
        return panel

    def _build_preview_pane(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.original_label = QLabel()
        self.original_label.setFixedSize(64, 64)
        header.addWidget(self.original_label)
        names = QVBoxLayout()
        self.name_label = QLabel("Pick a shortcut")
        self.name_label.setObjectName("heading")
        self.detail_label = QLabel("Click any icon on the left to see cute versions of it.")
        self.detail_label.setObjectName("detail")
        self.detail_label.setWordWrap(True)
        names.addWidget(self.name_label)
        names.addWidget(self.detail_label)
        header.addLayout(names, 1)
        self.shuffle_button = self._button("Shuffle", self.shuffle, "secondary")
        self.shuffle_button.setToolTip("Re-roll accessories, blush and shades")
        self.own_image_button = self._button("Use my own image…", self.use_own_image, "secondary")
        header.addWidget(self.shuffle_button)
        header.addWidget(self.own_image_button)
        layout.addLayout(header)

        self.cards_host = QWidget()
        self.cards_layout = QGridLayout(self.cards_host)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setObjectName("previewScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.cards_host)
        layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.revert_button = self._button("Revert", self.revert_current, "secondary")
        self.all_button = self._button("Apply style to all", self.apply_style_to_all, "secondary")
        self.all_button.setToolTip("Use the selected style on every untouched shortcut")
        self.skip_button = self._button("Skip", self.skip_current, "secondary")
        self.apply_button = self._button("Apply", self.apply_chosen, "primary")
        actions.addWidget(self.revert_button)
        actions.addWidget(self.all_button)
        actions.addStretch(1)
        actions.addWidget(self.skip_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self._update_buttons()
        return panel

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.update_label = QLabel()
        self.update_label.setOpenExternalLinks(True)
        bar.addPermanentWidget(self.update_label)
        self.update_box = QCheckBox("Check for updates")
        self.update_box.setToolTip(
            "Ask GitHub for a newer version when Iconbloom starts. Off by default; "
            "it's the only time Iconbloom uses the internet, and it never downloads anything."
        )
        self.update_box.setChecked(self.settings.check_for_updates)
        self.update_box.toggled.connect(self._on_update_toggled)
        bar.addPermanentWidget(self.update_box)
        bar.addPermanentWidget(QLabel(f"v{__version__}"))

    def _on_update_toggled(self, enabled: bool) -> None:
        self.settings.check_for_updates = enabled
        self._guard(lambda: self.settings.save(self.service.paths.settings))
        if enabled:
            self.check_for_updates()

    def check_for_updates(self) -> None:
        job = self._start(lambda _report: self._update_check(), token=-2)
        job.signals.done.connect(self._on_update_result)

    def _on_update_result(self, _token: int, result: object) -> None:
        if isinstance(result, Release):
            self.update_label.setText(
                f'<a href="{result.url}">Iconbloom {result.version} is available</a>'
            )

    def _button(self, text: str, slot: Callable[[], object], role: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", role)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    # ---- shortcuts grid -----------------------------------------------------

    def reload_shortcuts(self) -> None:
        groups = self.service.scan()
        self._groups = {g.key: g for g in groups}
        self.model.clear()
        for target in groups:
            item = QStandardItem(target.name)
            item.setEditable(False)
            item.setData(target.key, KEY_ROLE)
            item.setData(str(self.service.status(target)), STATUS_ROLE)
            item.setData(target.writable, WRITABLE_ROLE)
            item.setToolTip(self._tooltip(target))
            self.model.appendRow(item)
        self._load_thumbnails(groups)
        if groups and not self.grid.currentIndex().isValid():
            self.select_next_untouched(start=0)

    def _load_thumbnails(self, groups: list[ShortcutGroup]) -> None:
        def work(report: Callable[[object], None]) -> None:
            for target in groups:
                try:
                    image = self.service.current_icon(target)
                except Exception:  # one bad icon must not stop the rest of the grid
                    log.exception("could not load icon for %s", target.name)
                    continue
                image.thumbnail((128, 128))
                report((target.key, to_qimage(image)))

        job = self._start(work, token=-1)
        job.signals.progress.connect(self._on_thumbnail)

    def _on_thumbnail(self, _token: int, payload: object) -> None:
        if not isinstance(payload, tuple):
            return
        key, image = payload  # pyright: ignore[reportUnknownVariableType]
        item = self._item(str(key))  # pyright: ignore[reportUnknownArgumentType]
        if item is not None and isinstance(image, QImage):
            item.setData(
                pixmap_at(image, TileDelegate.ICON, self.devicePixelRatioF()),
                Qt.ItemDataRole.DecorationRole,
            )

    def _item(self, key: str) -> QStandardItem | None:
        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            if item is not None and item.data(KEY_ROLE) == key:
                return item
        return None

    def current_group(self) -> ShortcutGroup | None:
        index = self.grid.currentIndex()
        if not index.isValid():
            return None
        return self._groups.get(str(index.data(KEY_ROLE)))

    def select_next_untouched(self, start: int | None = None) -> bool:
        """Move to the next shortcut that is writable and not yet themed or skipped."""
        rows = self.model.rowCount()
        begin = self.grid.currentIndex().row() + 1 if start is None else start
        for offset in range(rows):
            row = (begin + offset) % rows
            item = self.model.item(row)
            if item is None:
                continue
            if item.data(WRITABLE_ROLE) and item.data(STATUS_ROLE) == Status.ORIGINAL:
                self.grid.setCurrentIndex(self.model.indexFromItem(item))
                return True
        return False

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._seed = 0
        self._custom = None
        if current.isValid():
            self._show_group(self._groups[str(current.data(KEY_ROLE))])

    def _refresh_group(self, target: ShortcutGroup) -> ShortcutGroup:
        updated = self.service.reload(target)
        self._groups[updated.key] = updated
        item = self._item(updated.key)
        if item is not None:
            item.setData(str(self.service.status(updated)), STATUS_ROLE)
            item.setToolTip(self._tooltip(updated))
        self._load_thumbnails([updated])
        return updated

    def _tooltip(self, target: ShortcutGroup) -> str:
        lines = [target.name, target.primary.info.target or "(Store or advertised app)"]
        lines += [f"{s.source}: {s.path}" for s in target.shortcuts]
        if not target.writable:
            lines.append("Read-only: this shortcut is shared by all users and needs admin rights.")
        return "\n".join(lines)

    # ---- previews -----------------------------------------------------------

    def _show_group(self, target: ShortcutGroup) -> None:
        self.name_label.setText(target.name)
        status = self.service.status(target)
        notes = [f"{target.primary.source} · {status}"]
        if not target.writable:
            notes.append("Shared by all users, so it can't be changed without admin rights.")
        self.detail_label.setText("  ".join(notes))
        self._clear_cards()
        self._render_previews(target)

    def _render_previews(self, target: ShortcutGroup) -> None:
        theme, seed = self.theme, self._seed

        def work(_report: Callable[[object], None]) -> PreviewSet:
            extracted = self.service.original_icon(target)
            icon, upscaled = ops.prepare(extracted.image)
            previews = [
                Preview(
                    key=recipe.id,
                    label=recipe.label,
                    choice=Choice(theme.id, recipe.id, seed),
                    full=(full := render(recipe, icon, theme, seed=seed)),
                    image=to_qimage(full),
                )
                for recipe in analyze.order_recipes(theme.recipes, icon)
            ]
            upscaled = upscaled or extracted.upscaled
            return PreviewSet(target.key, icon, to_qimage(icon), upscaled, previews)

        self._token += 1
        job = self._start(work, token=self._token)
        job.signals.done.connect(self._on_previews)
        job.signals.failed.connect(self._on_preview_failed)

    def _on_previews(self, token: int, result: object) -> None:
        current = self.current_group()
        if token != self._token or not isinstance(result, PreviewSet):
            return
        if current is None or current.key != result.group_key:
            return
        self._previews = result
        self.original_label.setPixmap(pixmap_at(result.original, 64, self.devicePixelRatioF()))
        if result.upscaled:
            self.detail_label.setText(
                self.detail_label.text()
                + "  This app only ships a small icon, so styles may look a little soft."
            )
        self._clear_cards()
        previews = ([self._custom] if self._custom else []) + result.previews
        for i, preview in enumerate(previews):
            card = PreviewCard(preview.key, preview.label, preview.image)
            card.clicked.connect(self._choose)
            card.activated.connect(self._choose_and_apply)
            card.hovered.connect(self._on_card_hover)
            self.cards_layout.addWidget(card, i // PREVIEW_COLUMNS, i % PREVIEW_COLUMNS)
            self._cards.append(card)
        if self._cards:
            self._choose(self._cards[0])

    def _on_preview_failed(self, token: int, message: str) -> None:
        if token == self._token:
            self.detail_label.setText(f"Couldn't read this app's icon: {message}")

    def _clear_cards(self) -> None:
        self._popup.hide()
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._chosen = None
        self._update_buttons()

    def _choose(self, card: object) -> None:
        if not isinstance(card, PreviewCard):
            return
        for other in self._cards:
            other.set_selected(other is card)
        self._chosen = card
        self._update_buttons()

    def _choose_and_apply(self, card: object) -> None:
        self._choose(card)
        self.apply_chosen()

    def _on_card_hover(self, card: object, entered: bool) -> None:
        if not entered or not isinstance(card, PreviewCard) or self._previews is None:
            self._popup.hide()
            return
        at = card.mapToGlobal(QPoint(card.width() + 6, 0))
        self._popup.show_for(self._previews.original, card.image, at)

    def _preview_for(self, card: PreviewCard) -> Preview | None:
        if self._custom is not None and card.key == self._custom.key:
            return self._custom
        if self._previews is None:
            return None
        return next((p for p in self._previews.previews if p.key == card.key), None)

    def _update_buttons(self) -> None:
        target = self.current_group()
        writable = target is not None and target.writable
        has_choice = self._chosen is not None
        self.apply_button.setEnabled(writable and has_choice)
        self.all_button.setEnabled(
            has_choice and (self._chosen is None or self._chosen.key != "custom")
        )
        self.skip_button.setEnabled(target is not None)
        self.revert_button.setEnabled(
            target is not None and self.service.status(target) is Status.THEMED
        )
        self.shuffle_button.setEnabled(target is not None)
        self.own_image_button.setEnabled(writable)

    # ---- actions ------------------------------------------------------------

    def apply_chosen(self) -> None:
        target = self.current_group()
        card = self._chosen
        if target is None or card is None or not target.writable:
            return
        preview = self._preview_for(card)
        if preview is None:
            return
        simple = self._simplified(preview)
        report = self._guard(
            lambda: self.service.apply(target, preview.full, simple, preview.choice)
        )
        if report is None:
            return
        if report.skipped:
            reasons = "\n".join(f"{p.name}: {why}" for p, why in report.skipped)
            QMessageBox.information(self, "Some shortcuts were left alone", reasons)
        self._refresh_group(target)
        if not self.select_next_untouched():
            self._show_group(self._groups[target.key])
        self.statusBar().showMessage(f"Applied “{preview.label}” to {target.name}", 4000)

    def _simplified(self, preview: Preview) -> Image.Image:
        if preview.choice.recipe == CUSTOM_RECIPE:
            return preview.full
        if self._previews is None:
            return preview.full
        recipe = self.theme.recipe(preview.choice.recipe)
        return render(
            recipe, self._previews.icon, self.theme, seed=preview.choice.seed, simplified=True
        )

    def skip_current(self) -> None:
        target = self.current_group()
        if target is None:
            return
        self.service.skip(target)
        self._refresh_group(target)
        self.select_next_untouched()

    def revert_current(self) -> None:
        target = self.current_group()
        if target is None:
            return
        if self._guard(lambda: self.service.revert(target)) is None:
            return
        updated = self._refresh_group(target)
        self._show_group(updated)
        self.statusBar().showMessage(f"{target.name} is back to its original icon", 4000)

    def revert_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Revert all icons?",
            "Put every shortcut Iconbloom changed back to its original icon?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        report = self._guard(self.service.revert_all)
        if report is not None:
            self.reload_shortcuts()
            self.statusBar().showMessage(f"Reverted {len(report.changed)} shortcuts", 5000)

    def shuffle(self) -> None:
        target = self.current_group()
        if target is None:
            return
        self._seed += 1
        self._clear_cards()
        self._render_previews(target)

    def use_own_image(self, path: Path | None = None) -> None:
        target = self.current_group()
        if target is None or not target.writable:
            return
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Use my own image", str(Path.home()), "Images (*.png *.ico *.bmp)"
            )
            if not chosen:
                return
            path = Path(chosen)
        name = self._guard(lambda: self.service.store_custom_image(path))
        if name is None:
            return
        choice = Choice("", CUSTOM_RECIPE, custom_image=name)
        full, _ = self.service.render_choice(choice, Image.new("RGBA", (1, 1)))
        self._custom = Preview("custom", "Your image", choice, full, to_qimage(full))
        if self._previews is not None:
            self._on_previews(self._token, self._previews)

    def apply_style_to_all(self) -> None:
        card = self._chosen
        if card is None or card.key == "custom":
            return
        recipe = self.theme.recipe(card.key)
        targets = [
            g
            for g in self._groups.values()
            if g.writable and self.service.status(g) is Status.ORIGINAL
        ]
        answer = QMessageBox.question(
            self,
            "Apply this style to all?",
            f"Use “{recipe.label}” on {len(targets)} untouched shortcuts?",
        )
        if answer != QMessageBox.StandardButton.Yes or not targets:
            return
        choice = Choice(self.theme.id, recipe.id, self._seed)
        progress = QProgressDialog("Theming shortcuts…", "Stop", 0, len(targets), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        done = 0
        for i, target in enumerate(targets):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            progress.setLabelText(f"Theming {target.name}…")
            try:
                original = self.service.original_icon(target).image
                full, simple = self.service.render_choice(choice, original)
                self.service.apply(target, full, simple, choice)
                done += 1
            except Exception:  # skip the one icon, keep going; details are in the log
                log.exception("apply-to-all failed for %s", target.name)
        progress.setValue(len(targets))
        self.reload_shortcuts()
        self.statusBar().showMessage(f"Applied “{recipe.label}” to {done} shortcuts", 5000)

    def reapply_all(self) -> None:
        report = self._guard(lambda: self.service.reapply(list(self._groups.values())))
        if report is not None:
            self.reload_shortcuts()
            count = len(report.changed)
            message = f"Reapplied {count} icons" if count else "Nothing needed reapplying"
            self.statusBar().showMessage(message, 5000)

    def refresh_icons(self) -> None:
        answer = QMessageBox.question(
            self,
            "Refresh icons?",
            "If some icons still look old, Windows can rebuild its icon cache. "
            "This restarts Explorer, so the taskbar disappears for a few seconds.\n\nContinue?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._guard(self._hard_refresh)

    def clean_up(self) -> None:
        report = self._guard(self.service.cleanup)
        if report is not None:
            self.statusBar().showMessage(f"Removed {len(report.removed)} unused icon files", 5000)

    def _on_theme_changed(self) -> None:
        theme_id = self.theme_box.currentData()
        if not isinstance(theme_id, str):
            return
        self.theme = self._guard(lambda: load_theme(theme_id, self._themes_dir)) or self.theme
        target = self.current_group()
        if target is not None:
            self._show_group(target)

    def _load_initial_theme(self) -> Theme:
        available = list_themes(self._themes_dir)
        theme_id = DEFAULT_THEME if DEFAULT_THEME in available else available[0]
        return load_theme(theme_id, self._themes_dir)

    # ---- plumbing -----------------------------------------------------------

    def _guard[T](self, action: Callable[[], T]) -> T | None:
        """Run an action, turning failures into a friendly dialog and a log entry."""
        try:
            return action()
        except Exception as exc:  # every failure reaches the user, never a silent crash
            log.exception("action failed")
            QMessageBox.warning(
                self,
                "That didn't work",
                f"{exc}\n\nNothing else was changed. Details are in the log file.",
            )
            return None

    def _start(self, work: Callable[[Callable[[object], None]], object], token: int) -> Job:
        job = Job(token, work)
        job.setAutoDelete(False)
        self._jobs.add(job)
        job.signals.done.connect(lambda *_: self._jobs.discard(job))
        job.signals.failed.connect(lambda *_: self._jobs.discard(job))
        self._pool.start(job)
        return job

    def wait_for_jobs(self, msecs: int = 30_000) -> bool:
        return self._pool.waitForDone(msecs)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self._pool.clear()
        self._pool.waitForDone(5_000)
        super().closeEvent(event)
