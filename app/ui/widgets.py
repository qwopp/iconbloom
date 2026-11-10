"""Small building blocks: image conversion, shortcut tiles, preview cards and the size popup."""

import logging
from typing import override

from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from app.changes import Status
from app.choices import Choice
from app.ui import palette

log = logging.getLogger(__name__)

PREVIEW_PX = 128
STATUS_COLORS = {
    Status.ORIGINAL: QColor("#D9CCE3"),
    Status.THEMED: QColor("#FF7FAF"),
    Status.SKIPPED: QColor("#F3D9A4"),
    Status.NEEDS_REAPPLY: QColor("#FFB067"),
}

KEY_ROLE = Qt.ItemDataRole.UserRole + 1
STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
# Every shortcut in the group is shared by all users, so changing it asks for permission.
SHARED_ROLE = Qt.ItemDataRole.UserRole + 3


def to_qimage(image: Image.Image) -> QImage:
    """Copy a Pillow image into a QImage. Safe to call off the GUI thread."""
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return qimage.copy()  # detach from the Python buffer before it is freed


def pixmap_at(image: QImage, size: int, ratio: float) -> QPixmap:
    """A pixmap that displays at ``size`` logical px, sharp on high-DPI screens."""
    physical = max(1, round(size * ratio))
    scaled = image.scaled(
        physical,
        physical,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap = QPixmap.fromImage(scaled)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class TileDelegate(QStyledItemDelegate):
    """Shortcut tile: icon, name underneath, and a status dot in the corner."""

    ICON = 56
    # Tall enough for a two-line name ("Stardew Valley") without clipping its last line.
    SIZE = QSize(112, 120)

    @override
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return self.SIZE

    @override
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        colors = palette.current()
        background = "tile_selected" if selected else "hover" if hovered else "card"
        painter.setPen(colors.color("accent" if selected else "tile_border"))
        painter.setBrush(colors.color(background))
        painter.drawRoundedRect(rect, 14, 14)

        pixmap = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(pixmap, QPixmap):
            icon_rect = QRect(0, 0, self.ICON, self.ICON)
            icon_rect.moveCenter(QPoint(rect.center().x(), rect.top() + 10 + self.ICON // 2))
            painter.drawPixmap(icon_rect, pixmap)

        painter.setPen(colors.color("text"))
        top = rect.top() + self.ICON + 16
        text_rect = QRect(rect.left() + 6, top, rect.width() - 12, rect.bottom() - top - 2)
        name = str(index.data(Qt.ItemDataRole.DisplayRole))
        elided = painter.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, text_rect.width() * 2 - 10
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, elided
        )

        # Qt hands StrEnum values back as plain strings, so look the color up by value.
        status = index.data(STATUS_ROLE)
        if status in STATUS_COLORS:
            painter.setPen(colors.color("card"))
            painter.setBrush(STATUS_COLORS[Status(status)])
            painter.drawEllipse(QPoint(rect.right() - 12, rect.top() + 12), 6, 6)
        if index.data(SHARED_ROLE):
            _draw_shield(painter, QPoint(rect.left() + 14, rect.top() + 14))
        painter.restore()


def _draw_shield(painter: QPainter, center: QPoint) -> None:
    """Small shield, the Windows sign for "this asks for administrator permission"."""
    x, y = center.x(), center.y()
    shield = QPolygon(
        [
            QPoint(x - 6, y - 7),
            QPoint(x + 6, y - 7),
            QPoint(x + 6, y),
            QPoint(x, y + 7),
            QPoint(x - 6, y),
        ]
    )
    colors = palette.current()
    painter.setPen(QPen(colors.color("icon_muted"), 1.4))
    painter.setBrush(colors.color("shield"))
    painter.drawPolygon(shield)


class SizePopup(QFrame):
    """Floating strip comparing the original and a style at real desktop sizes."""

    # The largest size Windows shows on a standard desktop; smaller ones look the same.
    SIZES = (48,)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setObjectName("sizePopup")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(10)

    def show_for(self, original: QImage, styled: QImage, at: QPoint) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        ratio = self.devicePixelRatioF()
        for caption, image in (("before", original), ("after", styled)):
            column = QVBoxLayout()
            row = QHBoxLayout()
            for size in self.SIZES:
                label = QLabel()
                label.setPixmap(pixmap_at(image, size, ratio))
                label.setFixedSize(size, size)
                row.addWidget(label, alignment=Qt.AlignmentFlag.AlignBottom)
            column.addLayout(row)
            text = QLabel(caption)
            text.setObjectName("popupCaption")
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(text)
            self._layout.addLayout(column)
        self.adjustSize()
        self.move(at)
        self.show()


class PreviewCard(QFrame):
    """One styled option: the 128 px render with its name underneath."""

    clicked = Signal(object)
    activated = Signal(object)
    hovered = Signal(object, bool)

    def __init__(
        self, choice: Choice, label: str, image: QImage, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.choice = choice
        self.label = label
        self.image = image
        self.setObjectName("previewCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)
        picture = QLabel()
        picture.setPixmap(pixmap_at(image, PREVIEW_PX, self.devicePixelRatioF()))
        picture.setFixedSize(PREVIEW_PX, PREVIEW_PX)
        layout.addWidget(picture, alignment=Qt.AlignmentFlag.AlignHCenter)
        caption = QLabel(label)
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

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self)
        super().mouseDoubleClickEvent(event)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        self.hovered.emit(self, True)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        self.hovered.emit(self, False)
        super().leaveEvent(event)
