"""The picker window: shortcuts on the left, styled options for the selected one on the right."""

import logging
import threading
from collections.abc import Callable, Sequence
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
from app.choices import Choice
from app.service import ChangeReport, IconService, Status
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
from engine.themes import DEFAULT_THEME, Theme
from platform_win.shortcuts import ShortcutGroup

log = logging.getLogger(__name__)

APP_ICON = UI_DIR / "iconbloom.png"
PREVIEW_COLUMNS = 4
# Wait this long after the selection moves before rendering, so holding an
# arrow key doesn't queue a full render for every shortcut it passes.
SELECT_DELAY_MS = 80
STATUS_LABELS = {Status.ORIGINAL: "untouched"}


@dataclass(frozen=True)
class Preview:
    label: str
    choice: Choice
    image: QImage


@dataclass(frozen=True)
class PreviewSet:
    group_key: str
    # The original after ops.prepare, reused by Shuffle, theme switches and Apply.
    icon: Image.Image
    original: QImage
    upscaled: bool
    previews: list[Preview]


@dataclass(frozen=True)
class Thumbnail:
    key: str
    image: QImage


@dataclass(frozen=True)
class BatchStep:
    index: int
    name: str


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: IconService,
        *,
        hard_refresh: Callable[[], None],
        update_check: Callable[[], Release | None] = updates.check,
    ) -> None:
        super().__init__()
        self.service = service
        self._hard_refresh = hard_refresh
        self._update_check = update_check
        self.settings = Settings.load(service.paths.settings)
        self._pool = QThreadPool(self)
        self._jobs: set[Job] = set()
        self._groups: dict[str, ShortcutGroup] = {}
        self._items: dict[str, QStandardItem] = {}
        self._preview_token = 0
        self._seed = 0
        self._previews: PreviewSet | None = None
        self._custom: Preview | None = None
        self._cards: list[PreviewCard] = []
        self._chosen: PreviewCard | None = None
        self._theme_names = service.theme_names()
        known = [theme_id for theme_id, _ in self._theme_names]
        self.theme: Theme = service.theme(DEFAULT_THEME if DEFAULT_THEME in known else known[0])

        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        self._select_timer.setInterval(SELECT_DELAY_MS)
        self._select_timer.timeout.connect(self._show_current)

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
        for theme_id, name in self._theme_names:
            self.theme_box.addItem(name, theme_id)
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
        legend = QLabel(
            "   ".join(
                f'<span style="color:{color.name()}">●</span> {STATUS_LABELS.get(status, status)}'
                for status, color in STATUS_COLORS.items()
            )
        )
        legend.setObjectName("legend")
        layout.addWidget(legend)
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
        self.detail_label = QLabel("Looking for your shortcuts…")
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

    def _button(self, text: str, slot: Callable[[], object], role: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", role)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    # ---- shortcuts grid -----------------------------------------------------

    def reload_shortcuts(self) -> None:
        """Rescan shortcut folders in the background and refresh the grid."""
        job = self._start(lambda _report: self.service.scan())
        job.signals.done.connect(self._on_scanned)

    def _on_scanned(self, result: object) -> None:
        if not isinstance(result, list):
            return
        groups: list[ShortcutGroup] = [g for g in result if isinstance(g, ShortcutGroup)]
        log.info("found %d shortcut groups", len(groups))
        current = self.current_group()
        old_groups = self._groups
        # Read thumbnails before clear(), which deletes the old items.
        old_pixmaps = {
            key: item.data(Qt.ItemDataRole.DecorationRole) for key, item in self._items.items()
        }
        self._groups = {g.key: g for g in groups}
        self._items = {}
        self.model.clear()
        stale: list[ShortcutGroup] = []
        for target in groups:
            item = QStandardItem(target.name)
            item.setEditable(False)
            item.setData(target.key, KEY_ROLE)
            self._items[target.key] = item
            self._update_item(target)
            # Keep the thumbnail when the shortcut still shows the same icon.
            previous = old_groups.get(target.key)
            pixmap = old_pixmaps.get(target.key)
            if (
                previous is not None
                and pixmap is not None
                and (previous.primary.info.icon == target.primary.info.icon)
            ):
                item.setData(pixmap, Qt.ItemDataRole.DecorationRole)
            else:
                stale.append(target)
            self.model.appendRow(item)
        self._load_thumbnails(stale)
        if current is not None and current.key in self._items:
            self.grid.setCurrentIndex(self._items[current.key].index())
        elif groups:
            self.select_next_untouched(start=0)
        else:
            self.detail_label.setText("No shortcuts found on your desktop or Start menu.")

    def _update_item(self, target: ShortcutGroup) -> None:
        item = self._items[target.key]
        item.setData(str(self.service.status(target)), STATUS_ROLE)
        item.setData(target.writable, WRITABLE_ROLE)
        item.setToolTip(self._tooltip(target))

    def _load_thumbnails(self, groups: Sequence[ShortcutGroup]) -> None:
        if not groups:
            return

        def work(report: Callable[[object], None]) -> None:
            for target in groups:
                try:
                    image = self.service.current_icon(target)
                except Exception:  # one bad icon must not stop the rest of the grid
                    log.exception("could not load icon for %s", target.name)
                    continue
                image.thumbnail((128, 128))
                report(Thumbnail(target.key, to_qimage(image)))

        self._start(work).signals.progress.connect(self._on_thumbnail)

    def _on_thumbnail(self, payload: object) -> None:
        if not isinstance(payload, Thumbnail):
            return
        item = self._items.get(payload.key)
        if item is not None:
            pixmap = pixmap_at(payload.image, TileDelegate.ICON, self.devicePixelRatioF())
            item.setData(pixmap, Qt.ItemDataRole.DecorationRole)

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
            item = self.model.item((begin + offset) % rows)
            if item is not None and self.service.is_untouched(self._groups[item.data(KEY_ROLE)]):
                self.grid.setCurrentIndex(item.index())
                return True
        return False

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._seed = 0
        self._custom = None
        self._clear_cards()
        if current.isValid():
            self._select_timer.start()

    def _show_current(self) -> None:
        target = self.current_group()
        if target is not None:
            self._show_group(target)

    def _refresh_group(self, target: ShortcutGroup) -> ShortcutGroup:
        updated = self.service.reload(target)
        self._groups[updated.key] = updated
        if updated.key in self._items:
            self._update_item(updated)
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
        self._set_detail(target, upscaled=False)
        self._clear_cards()
        self._render_previews(target)

    def _set_detail(self, target: ShortcutGroup, *, upscaled: bool) -> None:
        notes = [f"{target.primary.source} · {self.service.status(target)}"]
        if not target.writable:
            notes.append("Shared by all users, so it can't be changed without admin rights.")
        if upscaled:
            notes.append("This app only ships a small icon, so styles may look a little soft.")
        self.detail_label.setText("  ".join(notes))

    def _render_previews(self, target: ShortcutGroup) -> None:
        theme, seed = self.theme, self._seed
        # Shuffle and theme switches keep the same original; skip re-extracting it.
        cached = (
            self._previews if self._previews and self._previews.group_key == target.key else None
        )

        def work(_report: Callable[[object], None]) -> PreviewSet:
            if cached is not None:
                icon, upscaled = cached.icon, cached.upscaled
            else:
                extracted = self.service.original_icon(target)
                icon, upscaled = ops.prepare(extracted.image)
                upscaled = upscaled or extracted.upscaled
            previews = [
                Preview(
                    recipe.label,
                    Choice(theme.id, recipe.id, seed),
                    to_qimage(render(recipe, icon, theme, seed=seed)),
                )
                for recipe in analyze.order_recipes(theme.recipes, icon)
            ]
            return PreviewSet(target.key, icon, to_qimage(icon), upscaled, previews)

        self._preview_token += 1
        token = self._preview_token
        job = self._start(work)
        job.signals.done.connect(lambda result: self._on_previews(token, result))
        job.signals.failed.connect(lambda message: self._on_preview_failed(token, message))

    def _on_previews(self, token: int, result: object) -> None:
        current = self.current_group()
        if token != self._preview_token or not isinstance(result, PreviewSet):
            return
        if current is None or current.key != result.group_key:
            return
        self._previews = result
        self.original_label.setPixmap(pixmap_at(result.original, 64, self.devicePixelRatioF()))
        self._set_detail(current, upscaled=result.upscaled)
        self._show_cards()

    def _on_preview_failed(self, token: int, message: str) -> None:
        if token == self._preview_token:
            self.detail_label.setText(f"Couldn't read this app's icon: {message}")

    def _show_cards(self) -> None:
        self._clear_cards()
        if self._previews is None:
            return
        previews = ([self._custom] if self._custom else []) + self._previews.previews
        for i, preview in enumerate(previews):
            card = PreviewCard(preview.choice, preview.label, preview.image)
            card.clicked.connect(self._choose)
            card.activated.connect(self._choose_and_apply)
            card.hovered.connect(self._on_card_hover)
            self.cards_layout.addWidget(card, i // PREVIEW_COLUMNS, i % PREVIEW_COLUMNS)
            self._cards.append(card)
        self._choose(self._cards[0])

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

    def _update_buttons(self) -> None:
        target = self.current_group()
        writable = target is not None and target.writable
        chosen = self._chosen
        self.apply_button.setEnabled(writable and chosen is not None)
        self.all_button.setEnabled(chosen is not None and not chosen.choice.is_custom)
        self.skip_button.setEnabled(target is not None)
        themed = target is not None and self.service.status(target) is Status.THEMED
        self.revert_button.setEnabled(themed)
        self.shuffle_button.setEnabled(target is not None)
        self.own_image_button.setEnabled(writable)

    # ---- actions ------------------------------------------------------------

    def apply_chosen(self) -> None:
        target = self.current_group()
        card = self._chosen
        if target is None or card is None or not target.writable:
            return
        cached = self._previews_for(target)
        prepared = cached.icon if cached else None
        choice = card.choice
        report = self._guard(lambda: self.service.apply(target, choice, prepared=prepared))
        if report is None:
            return
        self._show_skipped(report)
        self._refresh_group(target)
        if not self.select_next_untouched():
            self._show_group(self._groups[target.key])
        self.statusBar().showMessage(f"Applied “{card.label}” to {target.name}", 4000)

    def _previews_for(self, target: ShortcutGroup) -> PreviewSet | None:
        """The rendered previews, if they belong to ``target``."""
        previews = self._previews
        return previews if previews is not None and previews.group_key == target.key else None

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
        self._show_group(self._refresh_group(target))
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
        self._show_group(target)

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
        source = path
        choice = self._guard(lambda: self.service.store_custom_image(source))
        if choice is None:
            return
        full, _ = self.service.render_choice(choice)
        self._custom = Preview("Your image", choice, to_qimage(full))
        self._show_cards()

    def apply_style_to_all(self) -> None:
        card = self._chosen
        if card is None or card.choice.is_custom:
            return
        choice = card.choice
        label = self.theme.recipe(choice.recipe).label
        targets = [g for g in self._groups.values() if self.service.is_untouched(g)]
        answer = QMessageBox.question(
            self,
            "Apply this style to all?",
            f"Use “{label}” on {len(targets)} untouched shortcuts?",
        )
        if answer != QMessageBox.StandardButton.Yes or not targets:
            return
        self._run_batch(
            "Theming shortcuts…",
            targets,
            lambda progress: self.service.apply_many(targets, lambda _g: choice, progress=progress),
            lambda report: f"Applied “{label}” to {len(report.changed)} shortcuts",
        )

    def reapply_all(self) -> None:
        lost = [g for g in self._groups.values() if self.service.status(g) is Status.NEEDS_REAPPLY]
        if not lost:
            self.statusBar().showMessage("Nothing needed reapplying", 5000)
            return
        self._run_batch(
            "Reapplying your icons…",
            lost,
            lambda progress: self.service.reapply(lost, progress=progress),
            lambda report: f"Reapplied {len(report.changed)} icons",
        )

    def _run_batch(
        self,
        title: str,
        targets: Sequence[ShortcutGroup],
        run: Callable[[Callable[[int, ShortcutGroup], bool]], ChangeReport],
        summary: Callable[[ChangeReport], str],
    ) -> None:
        """Run a batch on the thread pool behind a progress dialog with a Stop button."""
        dialog = QProgressDialog(title, "Stop", 0, len(targets), self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        stop = threading.Event()
        dialog.canceled.connect(stop.set)

        def work(report: Callable[[object], None]) -> ChangeReport:
            def step(i: int, target: ShortcutGroup) -> bool:
                report(BatchStep(i, target.name))
                return not stop.is_set()

            return run(step)

        def on_progress(item: object) -> None:
            if isinstance(item, BatchStep):
                dialog.setValue(item.index)
                dialog.setLabelText(f"{title}\n{item.name}")

        def on_done(result: object) -> None:
            dialog.reset()
            if isinstance(result, ChangeReport):
                self._show_skipped(result)
                self.statusBar().showMessage(summary(result), 5000)
            self.reload_shortcuts()

        def on_failed(message: str) -> None:
            dialog.reset()
            QMessageBox.warning(self, "That didn't work", message)
            self.reload_shortcuts()

        job = self._start(work)
        job.signals.progress.connect(on_progress)
        job.signals.done.connect(on_done)
        job.signals.failed.connect(on_failed)
        dialog.show()

    def _show_skipped(self, report: ChangeReport) -> None:
        if report.skipped:
            reasons = "\n".join(f"{p.stem}: {why}" for p, why in report.skipped[:20])
            QMessageBox.information(self, "Some shortcuts were left alone", reasons)

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
        self.theme = self._guard(lambda: self.service.theme(theme_id)) or self.theme
        target = self.current_group()
        if target is not None:
            self._show_group(target)

    def _on_update_toggled(self, enabled: bool) -> None:
        self.settings.check_for_updates = enabled
        self._guard(lambda: self.settings.save(self.service.paths.settings))
        if enabled:
            self.check_for_updates()

    def check_for_updates(self) -> None:
        job = self._start(lambda _report: self._update_check())
        job.signals.done.connect(self._on_update_result)

    def _on_update_result(self, result: object) -> None:
        if isinstance(result, Release):
            self.update_label.setText(
                f'<a href="{result.url}">Iconbloom {result.version} is available</a>'
            )

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

    def _start(self, work: Callable[[Callable[[object], None]], object]) -> Job:
        job = Job(work)
        job.setAutoDelete(False)
        self._jobs.add(job)
        job.signals.done.connect(lambda _result: self._jobs.discard(job))
        job.signals.failed.connect(lambda _message: self._jobs.discard(job))
        self._pool.start(job)
        return job

    def wait_for_jobs(self, msecs: int = 30_000) -> bool:
        return self._pool.waitForDone(msecs)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self._select_timer.stop()
        self._pool.clear()
        self._pool.waitForDone(5_000)
        super().closeEvent(event)
