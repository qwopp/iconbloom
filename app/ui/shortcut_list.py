"""The left panel: every icon Iconbloom found, with search, place tabs and status dots."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QItemSelection, QModelIndex, Qt, Signal
from PySide6.QtGui import QImage, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.changes import Status
from app.service import IconService
from app.ui.jobs import JobRunner
from app.ui.widgets import (
    KEY_ROLE,
    SHARED_ROLE,
    STATUS_COLORS,
    STATUS_ROLE,
    TileDelegate,
    pixmap_at,
    to_qimage,
)
from platform_win.shortcuts import ItemKind, Place, ShortcutGroup

log = logging.getLogger(__name__)

STATUS_LABELS = {Status.ORIGINAL: "untouched"}
THUMBNAIL_PX = 128


@dataclass(frozen=True)
class Thumbnail:
    key: str
    image: QImage


class ShortcutList(QWidget):
    """Shows the scanned groups; the window reacts to its signals."""

    # The highlighted tile changed (it drives the style picker).
    current_changed = Signal()
    # The set of selected tiles changed (multi-select with Ctrl/Shift).
    selection_changed = Signal()
    # A scan finished, with this many groups.
    scanned = Signal(int)

    def __init__(self, service: IconService, jobs: JobRunner, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self._service = service
        self._jobs = jobs
        self._scans_running = 0
        self._groups: dict[str, ShortcutGroup] = {}
        self._items: dict[str, QStandardItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel("Your icons")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search apps, folders and more")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
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
        self.grid.selectionModel().currentChanged.connect(self._on_current_changed)
        self.grid.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.grid, 1)

        self.empty_label = QLabel("No icons match.")
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

    def _build_place_tabs(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        tabs = QButtonGroup(self)
        tabs.setExclusive(True)
        self.place_buttons: dict[Place | None, QPushButton] = {}
        for place in (None, *Place):
            button = QPushButton(str(place) if place else "All")
            button.setObjectName("tab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(place is None)
            tabs.addButton(button)
            self.place_buttons[place] = button
            button.clicked.connect(self.apply_filter)
            row.addWidget(button)
        row.addStretch(1)
        return row

    # ---- contents -----------------------------------------------------------

    @property
    def groups(self) -> list[ShortcutGroup]:
        return list(self._groups.values())

    def reload(self) -> None:
        """Rescan in the background and refresh the grid."""
        self._start_scan(self._on_scanned)

    def rescan(self) -> None:
        """Pick up shortcuts added, removed or changed outside the app.

        The grid is only rebuilt when the scan found a difference: rebuilding it for
        nothing would drop a multi-selection and the scroll position every time the
        user switches back to the window.
        """
        if self._scans_running:
            return
        self._start_scan(self._on_rescanned)

    def _start_scan(self, on_done: Callable[[object], None]) -> None:
        self._scans_running += 1

        def finished(result: object) -> None:
            self._scans_running -= 1
            on_done(result)

        def failed(_message: str) -> None:
            self._scans_running -= 1

        self._jobs.start(lambda _report: self._service.scan(), on_done=finished, on_failed=failed)

    def _on_rescanned(self, result: object) -> None:
        if result != self.groups:
            self._on_scanned(result)

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
            self._describe(target)
            # Keep the thumbnail when the item still shows the same icon.
            previous = old_groups.get(target.key)
            pixmap = old_pixmaps.get(target.key)
            if pixmap is not None and previous is not None and _same_icon(previous, target):
                item.setData(pixmap, Qt.ItemDataRole.DecorationRole)
            else:
                stale.append(target)
            self.model.appendRow(item)
        self._load_thumbnails(stale)
        self.apply_filter()
        if current is not None and current.key in self._items:
            self.grid.setCurrentIndex(self._items[current.key].index())
        elif groups:
            self.select_next_untouched(start=0)
        self.scanned.emit(len(groups))

    def refresh_group(self, target: ShortcutGroup) -> ShortcutGroup:
        """Re-read one group after a change and update its tile."""
        updated = self._service.reload(target)
        self._groups[updated.key] = updated
        if updated.key in self._items:
            self._describe(updated)
        self._load_thumbnails([updated])
        return updated

    def group(self, key: str) -> ShortcutGroup:
        return self._groups[key]

    def _describe(self, target: ShortcutGroup) -> None:
        item = self._items[target.key]
        item.setData(str(self._service.status(target)), STATUS_ROLE)
        item.setData(not target.own_shortcuts, SHARED_ROLE)
        item.setToolTip(_tooltip(target))

    def _load_thumbnails(self, groups: Sequence[ShortcutGroup]) -> None:
        if not groups:
            return

        def work(report: Callable[[object], None]) -> None:
            for target in groups:
                try:
                    image = self._service.current_icon(target)
                except Exception:  # one bad icon must not stop the rest of the grid
                    log.exception("could not load icon for %s", target.name)
                    continue
                image.thumbnail((THUMBNAIL_PX, THUMBNAIL_PX))
                report(Thumbnail(target.key, to_qimage(image)))

        self._jobs.start(work, on_progress=self._on_thumbnail)

    def _on_thumbnail(self, payload: object) -> None:
        if not isinstance(payload, Thumbnail):
            return
        item = self._items.get(payload.key)
        if item is not None:
            pixmap = pixmap_at(payload.image, TileDelegate.ICON, self.devicePixelRatioF())
            item.setData(pixmap, Qt.ItemDataRole.DecorationRole)

    # ---- filtering ----------------------------------------------------------

    def apply_filter(self) -> None:
        query = self.search.text().strip().casefold()
        place = next((p for p, b in self.place_buttons.items() if b.isChecked()), None)
        counts: dict[Place | None, int] = dict.fromkeys(self.place_buttons, 0)
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
        for key, button in self.place_buttons.items():
            button.setText(f"{key or 'All'} ({counts[key]})")
        self.empty_label.setVisible(visible == 0 and self.model.rowCount() > 0)
        current = self.grid.currentIndex()
        hidden = current.isValid() and self.grid.isRowHidden(current.row())
        if hidden and not self.select_next_untouched(start=0):
            self._select_first_visible()

    def _select_first_visible(self) -> None:
        for row in range(self.model.rowCount()):
            if not self.grid.isRowHidden(row):
                self.grid.setCurrentIndex(self.model.index(row, 0))
                return

    # ---- selection ----------------------------------------------------------

    def current_group(self) -> ShortcutGroup | None:
        index = self.grid.currentIndex()
        if not index.isValid():
            return None
        return self._groups.get(str(index.data(KEY_ROLE)))

    def selected_groups(self) -> list[ShortcutGroup]:
        """Every selected tile, in grid order; just the current one if none are."""
        rows = sorted(i.row() for i in self.grid.selectionModel().selectedIndexes())
        chosen = [self._groups[self.model.item(r).data(KEY_ROLE)] for r in rows]
        current = self.current_group()
        if not chosen and current is not None:
            chosen = [current]
        return chosen

    def select(self, key: str) -> None:
        if key in self._items:
            self.grid.setCurrentIndex(self._items[key].index())

    def select_next_untouched(self, start: int | None = None) -> bool:
        """Move to the next visible tile that isn't styled or skipped yet."""
        rows = self.model.rowCount()
        begin = self.grid.currentIndex().row() + 1 if start is None else start
        for offset in range(rows):
            row = (begin + offset) % rows
            item = self.model.item(row)
            if self.grid.isRowHidden(row) or item is None:
                continue
            if self._service.is_untouched(self._groups[item.data(KEY_ROLE)]):
                self.grid.setCurrentIndex(item.index())
                return True
        return False

    def _on_current_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self.current_changed.emit()

    def _on_selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        self.selection_changed.emit()


def _same_icon(before: ShortcutGroup, after: ShortcutGroup) -> bool:
    return before.primary.info.icon == after.primary.info.icon


def _tooltip(target: ShortcutGroup) -> str:
    primary = target.primary
    if primary.info.store_app_id is not None:
        opens = "Store app"
    elif primary.kind is ItemKind.SHORTCUT:
        opens = primary.info.target or "(Store or advertised app)"
    else:
        opens = primary.info.target or str(primary.kind)
    lines = [target.name, opens]
    lines += [
        f"{s.source}: {s.path}"
        for s in target.shortcuts
        if s.kind not in (ItemKind.WINDOWS_ICON, ItemKind.STORE_APP)  # no real path to show
    ]
    if target.shared_shortcuts:
        lines.append("Shared by every user: Windows asks for permission to change it.")
    return "\n".join(lines)
