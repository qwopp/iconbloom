"""The picker window: shortcuts on the left, styled options for the selected one on the right."""

import logging
import threading
from collections.abc import Callable, Iterable, Sequence, Sized
from dataclasses import dataclass
from pathlib import Path
from typing import override

from PIL import Image
from PySide6.QtCore import QModelIndex, QPoint, Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QImage, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import __version__, updates
from app.choices import Choice
from app.service import DECLINED_REASON, SHARED_REASON, ChangeReport, IconService, Status
from app.settings import Settings
from app.ui import UI_DIR
from app.ui.widgets import (
    KEY_ROLE,
    SHARED_ROLE,
    STATUS_COLORS,
    STATUS_ROLE,
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
from platform_win.refresh import touches_taskbar
from platform_win.shortcuts import Place, ShortcutGroup

log = logging.getLogger(__name__)

APP_ICON = UI_DIR / "iconbloom.png"
PREVIEW_COLUMNS = 4
SELECTION_ICON = 48
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
        self.theme_box.setToolTip("The look every style is drawn in")
        bar.addWidget(self.theme_box)
        bar.addStretch(1)
        bar.addWidget(self._build_more_menu())
        bar.addWidget(
            self._button(
                "Revert all",
                self.revert_all,
                "danger",
                "Put every icon Iconbloom changed back to the original",
            )
        )
        return bar

    def _build_more_menu(self) -> QToolButton:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for text, slot, tip in (
            (
                "Reapply my icons",
                self.reapply_all,
                "Put your chosen styles back on shortcuts that an app update reset",
            ),
            (
                "Refresh Windows icons\u2026",
                self.refresh_icons,
                "Rebuild Windows' icon cache and restart Explorer, for icons that look stale",
            ),
            (
                "Delete unused icon files",
                self.clean_up,
                "Remove icons Iconbloom made earlier that no shortcut uses any more",
            ),
        ):
            action = menu.addAction(text)
            action.setToolTip(tip)
            action.triggered.connect(slot)
        more = QToolButton()
        more.setObjectName("more")
        more.setText("More")
        more.setToolTip("Less common actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setMenu(menu)
        return more

    def _build_grid(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel("Your shortcuts")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search shortcuts")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)
        layout.addLayout(self._build_place_tabs())
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
        self.grid.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.grid.setToolTip("")
        self.grid.selectionModel().currentChanged.connect(self._on_current_changed)
        self.grid.selectionModel().selectionChanged.connect(self._update_buttons)
        layout.addWidget(self.grid, 1)
        self.empty_label = QLabel("No shortcuts match.")
        self.empty_label.setObjectName("detail")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)
        legend = QLabel(
            "   ".join(
                f'<span style="color:{color.name()}">●</span> {STATUS_LABELS.get(status, status)}'
                for status, color in STATUS_COLORS.items()
            )
        )
        legend.setObjectName("legend")
        layout.addWidget(legend)
        return panel

    def _build_place_tabs(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.place_tabs = QButtonGroup(self)
        self.place_tabs.setExclusive(True)
        self._place_buttons: dict[Place | None, QPushButton] = {}
        for place in (None, *Place):
            button = QPushButton(str(place) if place else "All")
            button.setObjectName("tab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(place is None)
            self.place_tabs.addButton(button)
            self._place_buttons[place] = button
            button.clicked.connect(self._apply_filter)
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_preview_pane(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_notice())

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
        self.shuffle_button = self._button(
            "Shuffle", self.shuffle, "secondary", "Try different shades, positions and decorations"
        )
        self.own_image_button = self._button(
            "Use my own image\u2026",
            self.use_own_image,
            "secondary",
            "Use a picture of your own (PNG, ICO or BMP) as this shortcut's icon",
        )
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

        layout.addWidget(self._build_selection_strip())

        actions = QHBoxLayout()
        self.revert_button = self._button(
            "Revert", self.revert_current, "secondary", "Put this shortcut's original icon back"
        )
        self.all_button = self._button(
            "Apply style to all",
            self.apply_style_to_all,
            "secondary",
            "Use the selected style on every shortcut you haven't styled or skipped yet",
        )
        self.skip_button = self._button(
            "Skip", self.skip_current, "secondary", "Leave this one as it is and go to the next"
        )
        self.apply_button = self._button(
            "Apply",
            self.apply_chosen,
            "primary",
            "Use the selected style for this shortcut (or double-click a style)",
        )
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

    def _build_selection_strip(self) -> QFrame:
        """With several shortcuts selected, the chosen style drawn on each of them."""
        self.selection_strip = QFrame()
        self.selection_strip.setObjectName("selectionStrip")
        column = QVBoxLayout(self.selection_strip)
        column.setContentsMargins(12, 8, 12, 8)
        self.selection_label = QLabel()
        self.selection_label.setObjectName("detail")
        column.addWidget(self.selection_label)
        self.selection_icons = QHBoxLayout()
        self.selection_icons.setSpacing(8)
        self.selection_icons.setAlignment(Qt.AlignmentFlag.AlignLeft)
        host = QWidget()
        host.setLayout(self.selection_icons)
        scroll = QScrollArea()
        scroll.setObjectName("previewScroll")
        scroll.setWidget(host)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(SELECTION_ICON + 22)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        column.addWidget(scroll)
        self.selection_strip.hide()
        self._strip_token = 0
        return self.selection_strip

    def _update_selection_strip(self) -> None:
        selected = self.selected_groups()
        card = self._chosen
        if len(selected) < 2 or card is None:
            self.selection_strip.hide()
            return
        self.selection_label.setText(
            f"\u201c{card.label}\u201d on {_count(selected, 'selected shortcut')}:"
        )
        while self.selection_icons.count():
            item = self.selection_icons.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        slots: dict[str, QLabel] = {}
        for target in selected:
            label = QLabel()
            label.setFixedSize(SELECTION_ICON, SELECTION_ICON)
            label.setToolTip(target.name)
            self.selection_icons.addWidget(label)
            slots[target.key] = label
        self.selection_strip.show()

        choice = card.choice
        self._strip_token += 1
        token = self._strip_token

        def work(report: Callable[[object], None]) -> None:
            for target in selected:
                if token != self._strip_token:
                    return  # the selection or style changed; stop drawing this one
                try:
                    if choice.is_custom:
                        image, _ = self.service.render_choice(choice)
                    else:
                        icon, _ = ops.prepare(self.service.original_icon(target).image)
                        theme = self.service.theme(choice.theme)
                        image = render(theme.recipe(choice.recipe), icon, theme, seed=choice.seed)
                except Exception:  # one unreadable icon leaves an empty slot, nothing more
                    log.exception("could not preview %s", target.name)
                    continue
                report(Thumbnail(target.key, to_qimage(image)))

        def on_icon(payload: object) -> None:
            if token == self._strip_token and isinstance(payload, Thumbnail):
                label = slots.get(payload.key)
                if label is not None:
                    label.setPixmap(
                        pixmap_at(payload.image, SELECTION_ICON, self.devicePixelRatioF())
                    )

        self._start(work).signals.progress.connect(on_icon)

    def _build_notice(self) -> QFrame:
        """Banner for things worth knowing right after an action, like taskbar caching."""
        self.notice = QFrame()
        self.notice.setObjectName("notice")
        row = QHBoxLayout(self.notice)
        row.setContentsMargins(12, 8, 8, 8)
        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        row.addWidget(self.notice_label, 1)
        row.addWidget(
            self._button(
                "Refresh icons",
                self.refresh_icons,
                "secondary",
                "Rebuild Windows' icon cache and restart Explorer",
            )
        )
        close = QToolButton()
        close.setObjectName("closeNotice")
        close.setText("\u2715")
        close.setToolTip("Dismiss")
        close.clicked.connect(self.notice.hide)
        row.addWidget(close)
        self.notice.hide()
        return self.notice

    def _show_taskbar_notice(self, report: ChangeReport) -> None:
        if any(touches_taskbar(p) for p in report.changed):
            self.notice_label.setText(
                "Windows keeps its own copy of taskbar icons, so they can take a moment to "
                "update. If one still looks old, refresh Windows' icons."
            )
            self.notice.show()

    def _button(
        self, text: str, slot: Callable[[], object], role: str, tip: str = ""
    ) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", role)
        button.setToolTip(tip)
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
        self._apply_filter()
        if current is not None and current.key in self._items:
            self.grid.setCurrentIndex(self._items[current.key].index())
        elif groups:
            self.select_next_untouched(start=0)
        else:
            self.detail_label.setText("No shortcuts found on your desktop or Start menu.")

    def _apply_filter(self) -> None:
        query = self.search.text().strip().casefold()
        place = next((p for p, b in self._place_buttons.items() if b.isChecked()), None)
        counts: dict[Place | None, int] = dict.fromkeys(self._place_buttons, 0)
        visible = 0
        for row in range(self.model.rowCount()):
            target = self._groups[self.model.item(row).data(KEY_ROLE)]
            matches = query in target.name.casefold()
            if matches:
                counts[None] += 1
                for found in target.places:
                    counts[found] += 1
            shown = matches and (place is None or place in target.places)
            self.grid.setRowHidden(row, not shown)
            visible += shown
        for key, button in self._place_buttons.items():
            button.setText(f"{key or 'All'} ({counts[key]})")
        self.empty_label.setVisible(visible == 0 and self.model.rowCount() > 0)
        current = self.grid.currentIndex()
        hidden = current.isValid() and self.grid.isRowHidden(current.row())
        if hidden and not self.select_next_untouched(start=0):
            self._select_first_visible()

    def _select_first_visible(self) -> bool:
        for row in range(self.model.rowCount()):
            if not self.grid.isRowHidden(row):
                self.grid.setCurrentIndex(self.model.index(row, 0))
                return True
        return False

    def _update_item(self, target: ShortcutGroup) -> None:
        item = self._items[target.key]
        item.setData(str(self.service.status(target)), STATUS_ROLE)
        item.setData(not target.own_shortcuts, SHARED_ROLE)
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
        """Move to the next visible shortcut that isn't themed or skipped yet."""
        rows = self.model.rowCount()
        begin = self.grid.currentIndex().row() + 1 if start is None else start
        for offset in range(rows):
            row = (begin + offset) % rows
            item = self.model.item(row)
            if self.grid.isRowHidden(row) or item is None:
                continue
            if self.service.is_untouched(self._groups[item.data(KEY_ROLE)]):
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
        if target.shared_shortcuts:
            lines.append("Shared by every user: Windows asks for permission to change it.")
        return "\n".join(lines)

    # ---- previews -----------------------------------------------------------

    def _show_group(self, target: ShortcutGroup) -> None:
        self.name_label.setText(target.name)
        self._set_detail(target, upscaled=False)
        self._clear_cards()
        self._render_previews(target)

    def _set_detail(self, target: ShortcutGroup, *, upscaled: bool) -> None:
        notes = [f"{target.primary.source} · {self.service.status(target)}"]
        if target.shared_shortcuts:
            notes.append("Shared by every user on this PC: Windows will ask for permission.")
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
        selected = self.selected_groups()
        chosen = self._chosen
        self.apply_button.setEnabled(bool(selected) and chosen is not None)
        self.apply_button.setText(f"Apply to {len(selected)}" if len(selected) > 1 else "Apply")
        self.all_button.setEnabled(chosen is not None and not chosen.choice.is_custom)
        self.skip_button.setEnabled(bool(selected))
        themed = any(self.service.status(g) is Status.THEMED for g in selected)
        self.revert_button.setEnabled(themed)
        self.shuffle_button.setEnabled(target is not None)
        self.own_image_button.setEnabled(target is not None)
        self._update_selection_strip()

    # ---- actions ------------------------------------------------------------

    def selected_groups(self) -> list[ShortcutGroup]:
        """Every selected shortcut, in grid order; just the current one if none are."""
        rows = sorted(i.row() for i in self.grid.selectionModel().selectedIndexes())
        chosen = [self._groups[self.model.item(r).data(KEY_ROLE)] for r in rows]
        current = self.current_group()
        if not chosen and current is not None:
            chosen = [current]
        return chosen

    def apply_chosen(self) -> None:
        card = self._chosen
        targets = self.selected_groups()
        if card is None or not targets:
            return
        include_shared = self._ask_about_shared(targets)
        if include_shared is None:
            return
        current = self.current_group()
        cached = self._previews_for(current) if current else None
        prepared = {cached.group_key: cached.icon} if cached else None
        choice = card.choice
        single = len(targets) == 1

        def done(report: ChangeReport) -> None:
            if single:
                self._refresh_group(targets[0])
                if report.changed and not self.select_next_untouched():
                    self._show_group(self._groups[targets[0].key])
            else:
                self.reload_shortcuts()
            if report.changed:
                self.statusBar().showMessage(
                    f"Applied \u201c{card.label}\u201d to {_count(report.changed, 'shortcut')}",
                    4000,
                )

        self._run_action(
            "Applying your style\u2026",
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

    def _previews_for(self, target: ShortcutGroup) -> PreviewSet | None:
        """The rendered previews, if they belong to ``target``."""
        previews = self._previews
        return previews if previews is not None and previews.group_key == target.key else None

    def skip_current(self) -> None:
        targets = self.selected_groups()
        for target in targets:
            self.service.skip(target)
            self._refresh_group(target)
        if targets:
            self.select_next_untouched()

    def revert_current(self) -> None:
        targets = [g for g in self.selected_groups() if self.service.status(g) is Status.THEMED]
        if not targets:
            return

        def done(_report: ChangeReport) -> None:
            for target in targets:
                self._refresh_group(target)
            current = self.current_group()
            if current is not None:
                self._show_group(current)
            names = targets[0].name if len(targets) == 1 else _count(targets, "shortcut")
            self.statusBar().showMessage(f"{names}: back to the original icon", 4000)

        self._run_action(
            "Putting the original back\u2026",
            targets,
            lambda _progress: _merge(self.service.revert(t) for t in targets),
            done,
        )

    def revert_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Revert all icons?",
            "Put every shortcut Iconbloom changed back to its original icon?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_action(
            "Putting every original back\u2026",
            [],
            lambda _progress: self.service.revert_all(),
            lambda report: self.statusBar().showMessage(
                f"Reverted {_count(report.changed, 'shortcut')}", 5000
            ),
            reload=True,
        )

    def shuffle(self) -> None:
        target = self.current_group()
        if target is None:
            return
        self._seed += 1
        self._show_group(target)

    def use_own_image(self, path: Path | None = None) -> None:
        if self.current_group() is None:
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
        targets = [g for g in self._groups.values() if self.service.is_untouched(g)]
        answer = QMessageBox.question(
            self,
            "Apply this style to all?",
            f"Use \u201c{card.label}\u201d on {_count(targets, 'untouched shortcut')}?",
        )
        if answer != QMessageBox.StandardButton.Yes or not targets:
            return
        include_shared = self._ask_about_shared(targets)
        if include_shared is None:
            return
        self._run_action(
            "Styling your shortcuts\u2026",
            targets,
            lambda progress: self.service.apply_many(
                targets, lambda _g: choice, include_shared=include_shared, progress=progress
            ),
            lambda report: self.statusBar().showMessage(
                f"Applied \u201c{card.label}\u201d to {_count(report.changed, 'shortcut')}", 5000
            ),
            reload=True,
        )

    def reapply_all(self) -> None:
        lost = [g for g in self._groups.values() if self.service.status(g) is Status.NEEDS_REAPPLY]
        if not lost:
            self.statusBar().showMessage("Nothing needed reapplying", 5000)
            return
        include_shared = self._ask_about_shared(lost)
        if include_shared is None:
            return
        self._run_action(
            "Reapplying your icons\u2026",
            lost,
            lambda progress: self.service.reapply(
                lost, include_shared=include_shared, progress=progress
            ),
            lambda report: self.statusBar().showMessage(
                f"Reapplied {_count(report.changed, 'icon')}", 5000
            ),
            reload=True,
        )

    def _ask_about_shared(self, targets: Sequence[ShortcutGroup]) -> bool | None:
        """Whether to include shortcuts every user shares; None means cancel."""
        shared = [t for t in targets if t.shared_shortcuts]
        if not shared:
            return False
        remembered = self.settings.shared_shortcuts
        if remembered in ("include", "skip"):
            return remembered == "include"
        which = shared[0].name if len(shared) == 1 else f"{len(shared)} of these apps"
        box = QMessageBox(self)
        box.setWindowTitle("Shared shortcuts")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"{which} also {'has' if len(shared) == 1 else 'have'} a shortcut that every user "
            "on this PC shares. Windows will ask for administrator permission to change it."
        )
        include = box.addButton("Change those too", QMessageBox.ButtonRole.AcceptRole)
        mine = None
        if any(t.own_shortcuts for t in targets):
            mine = box.addButton("Only mine", QMessageBox.ButtonRole.RejectRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        remember = QCheckBox("Remember my answer")
        box.setCheckBox(remember)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (include, mine) or clicked is None:
            return None
        answer = clicked is include
        if remember.isChecked():
            self.settings.shared_shortcuts = "include" if answer else "skip"
            self._guard(lambda: self.settings.save(self.service.paths.settings))
        return answer

    def _run_action(
        self,
        title: str,
        targets: Sequence[ShortcutGroup],
        run: Callable[[Callable[[int, ShortcutGroup], bool]], ChangeReport],
        on_done: Callable[[ChangeReport], None],
        *,
        reload: bool = False,
    ) -> None:
        """Run a change on the thread pool, so a permission prompt never freezes the window.

        A progress dialog with a Stop button appears if it takes more than a moment.
        """
        dialog = QProgressDialog(title, "Stop", 0, max(len(targets), 1), self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(400)
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

        def finished(result: object) -> None:
            dialog.reset()
            if isinstance(result, ChangeReport):
                self._show_skipped(result)
                self._show_taskbar_notice(result)
                on_done(result)
            if reload:
                self.reload_shortcuts()

        def failed(message: str) -> None:
            dialog.reset()
            QMessageBox.warning(self, "That didn't work", message)
            self.reload_shortcuts()

        job = self._start(work)
        job.signals.progress.connect(on_progress)
        job.signals.done.connect(finished)
        job.signals.failed.connect(failed)

    def _show_skipped(self, report: ChangeReport) -> None:
        # Skipping shared shortcuts was the user's own choice; no need to repeat it.
        problems = [(p, why) for p, why in report.skipped if why != SHARED_REASON]
        declined = [p for p, why in problems if why == DECLINED_REASON]
        problems = [(p, why) for p, why in problems if why != DECLINED_REASON]
        if declined:
            self.statusBar().showMessage(
                f"Left {_count(declined, 'shared shortcut')} as they were", 5000
            )
        if problems:
            reasons = "\n".join(f"{p.stem}: {why}" for p, why in problems[:20])
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


def _count(items: Sized, noun: str) -> str:
    """'1 shortcut', '3 shortcuts'."""
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


def _merge(reports: Iterable[ChangeReport]) -> ChangeReport:
    merged = ChangeReport(dry_run=False)
    for report in reports:
        merged.extend(report)
    return merged
