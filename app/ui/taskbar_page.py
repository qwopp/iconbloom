"""The Taskbar page: give the taskbar the theme's look, with a live picture of the result.

Every control only redraws the picture; Windows changes when Apply is pressed.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import override

from PIL import Image
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.taskbar import TaskbarChoice, TaskbarService
from app.ui.controls import make_button
from app.ui.jobs import JobRunner
from app.ui.widgets import to_qimage
from engine.taskbar import BarSpec, Look, SearchMode, gradient_wallpaper, looks, render_preview
from engine.themes import Theme

log = logging.getLogger(__name__)

PREVIEW = QSize(1060, 200)
PREVIEW_SCALE = 1.0
CARD = QSize(250, 80)
CARD_SCALE = 0.5
_WALLPAPER = (1920, 1080)
SEARCH_LABELS = {
    SearchMode.HIDDEN: "Hidden",
    SearchMode.ICON: "Icon",
    SearchMode.BOX: "Search box",
    SearchMode.BUTTON: "Search button",
}
DARK_QUESTION = (
    "Windows only colors the taskbar in dark mode, so this also switches Windows to dark "
    "mode. Your apps stay as they are, and Revert puts it back.\n\nContinue?"
)
ACCENT_NOTE = "Also used as Windows' accent color in Start and Settings. Revert puts it back."
DARK_NOTE = "Windows only colors the taskbar in dark mode, so Apply switches Windows to dark."

# Loads the icons to pin in the picture, off the UI thread.
type IconLoader = Callable[[], Sequence[Image.Image]]


class LookCard(QFrame):
    """One look: a small picture of the taskbar in it, and its name."""

    clicked = Signal(object)

    def __init__(self, look: Look, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.look = look
        self.setObjectName("previewCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)
        self.picture = QLabel()
        self.picture.setFixedSize(CARD)
        layout.addWidget(self.picture)
        caption = QLabel(look.label)
        caption.setObjectName("cardCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(caption)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)


class TaskbarPage(QWidget):
    # A short message for the status bar.
    said = Signal(str)

    def __init__(
        self,
        service: TaskbarService,
        jobs: JobRunner,
        theme: Theme,
        load_icons: IconLoader,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._service = service
        self._jobs = jobs
        self._theme = theme
        self._load_icons = load_icons
        self._icons: list[Image.Image] = []
        self._wallpapers: dict[str, Image.Image] = {}
        self._current = service.current()
        self._windows_light = service.windows_is_light()
        self._look: Look | None = None
        self.cards: list[LookCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        self.preview = QLabel()
        self.preview.setObjectName("taskbarPreview")
        self.preview.setFixedSize(PREVIEW)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.heading = QLabel()
        self.heading.setObjectName("heading")
        layout.addWidget(self.heading)
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(12)
        layout.addLayout(self._cards_row)
        layout.addLayout(self._build_options())
        self.note = QLabel()
        self.note.setObjectName("detail")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch(1)
        layout.addLayout(self._build_actions())
        self.set_theme(theme)

    def _build_options(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.frosted = QCheckBox("Frosted glass")
        self.frosted.setToolTip("Windows' transparency effect: the wallpaper softly shows through")
        grid.addWidget(self._label("Effect"), 0, 0)
        grid.addWidget(self.frosted, 0, 1)

        self.centered = self._tab("Centered")
        self.left = self._tab("Left")
        alignment = QButtonGroup(self)
        alignment.addButton(self.centered)
        alignment.addButton(self.left)
        self.small = QCheckBox("Smaller buttons")
        layout_row = QHBoxLayout()
        layout_row.setSpacing(6)
        for widget in (self.centered, self.left):
            layout_row.addWidget(widget)
        layout_row.addSpacing(12)
        layout_row.addWidget(self.small)
        layout_row.addStretch(1)
        grid.addWidget(self._label("Layout"), 1, 0)
        grid.addLayout(layout_row, 1, 1)

        self.search = QComboBox()
        for mode in self._service.search_modes():
            self.search.addItem(SEARCH_LABELS[mode], mode.value)
        self.task_view = QCheckBox("Task view")
        self.auto_hide = QCheckBox("Hide automatically")
        show_row = QHBoxLayout()
        show_row.setSpacing(12)
        show_row.addWidget(QLabel("Search"))
        show_row.addWidget(self.search)
        show_row.addWidget(self.task_view)
        show_row.addWidget(self.auto_hide)
        show_row.addStretch(1)
        grid.addWidget(self._label("Show"), 2, 0)
        grid.addLayout(show_row, 2, 1)
        grid.setColumnStretch(1, 1)

        if not self._service.win11:
            self.centered.hide()
            self.left.hide()
        for box in (self.frosted, self.small, self.task_view, self.auto_hide):
            box.toggled.connect(self._changed)
        self.centered.toggled.connect(self._changed)
        self.search.currentIndexChanged.connect(self._changed)
        return grid

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.revert_button = make_button(
            "Revert", "secondary", "Put the taskbar back the way it was", self.revert
        )
        self.apply_button = make_button(
            "Apply", "primary", "Give your taskbar this look", self.apply
        )
        row.addWidget(self.revert_button)
        row.addStretch(1)
        row.addWidget(self.apply_button)
        return row

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("detail")
        return label

    def _tab(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("tab")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    # ---- state --------------------------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        """Show this theme's looks, keeping the same kind of look picked."""
        self._theme = theme
        self.heading.setText(f"Looks for {theme.name}")
        picked = self._look.id if self._look is not None else None
        while self._cards_row.count():
            item = self._cards_row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.cards = []
        for look in looks(theme.palette):
            card = LookCard(look)
            card.setToolTip(ACCENT_NOTE if look.color is not None else "Windows' own color")
            card.clicked.connect(self._on_card)
            self._cards_row.addWidget(card)
            self.cards.append(card)
        self._cards_row.addStretch(1)
        self._pick(next((c.look for c in self.cards if c.look.id == picked), None))

    def refresh(self) -> None:
        """Read the taskbar as it is now, and reload the icons in the picture."""
        self._current = self._service.current()
        self._windows_light = self._service.windows_is_light()
        self._show(self._current)
        self._pick(next((c.look for c in self.cards if c.look.color == self._current.color), None))
        self._jobs.start(
            lambda _progress: list(self._load_icons()),
            on_done=self._on_icons,
            on_failed=lambda message: log.warning("taskbar icons: %s", message),
        )

    def wanted(self) -> BarSpec:
        """The taskbar the controls describe."""
        color = self._look.color if self._look is not None else self._current.color
        return replace(
            self._current,
            color=color,
            transparency=self.frosted.isChecked(),
            centered=self.centered.isChecked(),
            small=self.small.isChecked(),
            search=SearchMode(str(self.search.currentData())),
            task_view=self.task_view.isChecked(),
            auto_hide=self.auto_hide.isChecked(),
            light=self._windows_light and color is None,
        )

    def _show(self, bar: BarSpec) -> None:
        widgets = (self.frosted, self.centered, self.left, self.small, self.search)
        for widget in (*widgets, self.task_view, self.auto_hide):
            widget.blockSignals(True)
        self.frosted.setChecked(bar.transparency)
        (self.centered if bar.centered else self.left).setChecked(True)
        self.small.setChecked(bar.small)
        self.search.setCurrentIndex(max(0, self.search.findData(bar.search.value)))
        self.task_view.setChecked(bar.task_view)
        self.auto_hide.setChecked(bar.auto_hide)
        for widget in (*widgets, self.task_view, self.auto_hide):
            widget.blockSignals(False)

    def _pick(self, look: Look | None) -> None:
        self._look = look
        for card in self.cards:
            card.set_selected(card.look == look)
        self._changed()

    def _on_card(self, card: LookCard) -> None:
        self._pick(card.look)

    def _on_icons(self, icons: object) -> None:
        if isinstance(icons, list):
            self._icons = [i for i in icons if isinstance(i, Image.Image)]  # pyright: ignore[reportUnknownVariableType]
        self._draw()

    def _changed(self, *_args: object) -> None:
        wanted = self.wanted()
        self.apply_button.setEnabled(_differs(wanted, self._current))
        self.revert_button.setEnabled(self._service.is_changed)
        if wanted.color is not None and self._windows_light:
            self.note.setText(DARK_NOTE)
        elif wanted.color is not None and wanted.color != self._current.color:
            self.note.setText(ACCENT_NOTE)
        else:
            self.note.setText("")
        self._draw()

    def _draw(self) -> None:
        wanted = self.wanted()
        ratio = self.devicePixelRatioF()
        self.preview.setPixmap(self._picture(wanted, PREVIEW, PREVIEW_SCALE, ratio))
        for card in self.cards:
            bar = replace(wanted, color=card.look.color, light=False, auto_hide=False)
            if card.look.color is None:
                bar = replace(bar, light=self._windows_light)
            card.picture.setPixmap(self._picture(bar, CARD, CARD_SCALE, ratio))

    def _picture(self, bar: BarSpec, size: QSize, scale: float, ratio: float) -> QPixmap:
        physical = (round(size.width() * ratio), round(size.height() * ratio))
        image: QImage = to_qimage(
            render_preview(self._wallpaper(), physical, bar, self._icons, scale=scale * ratio)
        )
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    def _wallpaper(self) -> Image.Image:
        if self._theme.id not in self._wallpapers:
            self._wallpapers[self._theme.id] = gradient_wallpaper(_WALLPAPER, self._theme.palette)
        return self._wallpapers[self._theme.id]

    # ---- actions ------------------------------------------------------------------

    def apply(self) -> None:
        wanted = self.wanted()
        if self._service.needs_dark_windows(wanted):
            answer = QMessageBox.question(self, "Switch Windows to dark mode?", DARK_QUESTION)
            if answer != QMessageBox.StandardButton.Yes:
                return
        choice = TaskbarChoice(self._theme.id, self._look.id if self._look else "")
        self._run(
            lambda: self._service.apply(wanted, choice),
            lambda names: "Taskbar updated" if names else "The taskbar already looks like this",
        )

    def revert(self) -> None:
        self._run(
            self._service.revert,
            lambda names: "Taskbar back the way it was" if names else "Nothing to put back",
        )

    def _run(self, action: Callable[[], list[str]], message: Callable[[list[str]], str]) -> None:
        self.apply_button.setEnabled(False)
        self.revert_button.setEnabled(False)

        def done(names: object) -> None:
            self.refresh()
            self.said.emit(message(names if isinstance(names, list) else []))  # pyright: ignore[reportUnknownArgumentType]

        def failed(error: str) -> None:
            QMessageBox.warning(
                self,
                "That didn't work",
                f"{error}\n\nAnything already changed can be put back with Revert.",
            )
            self.refresh()

        self._jobs.start(lambda _progress: action(), on_done=done, on_failed=failed)


def _differs(wanted: BarSpec, current: BarSpec) -> bool:
    """Whether applying would change anything a person can see."""
    return replace(wanted, light=current.light) != current
