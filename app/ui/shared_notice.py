"""The small corner notice the sign-in copy shows when updates reset shortcuts every user
shares. It never changes anything by itself: Put back brings up the permission prompt."""

from collections.abc import Callable, Sequence
from typing import override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.changes import shared_reset_message
from app.ui.notice import NoticeBar

MARGIN = 16
WIDTH = 460


class SharedResetNotice(QWidget):
    """Closes once any of its buttons (or ✕) is clicked."""

    def __init__(self, names: Sequence[str], put_back: Callable[[], object]) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Iconbloom")
        self.setFixedWidth(WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bar = NoticeBar(self)
        layout.addWidget(self.bar)
        self.bar.show_message(
            f"Iconbloom: {shared_reset_message(names)}",
            [
                ("Put back", put_back, "Show Windows' permission prompt and put them back"),
                ("Not now", lambda: None, "Leave them; Iconbloom offers again next time"),
            ],
        )
        self.bar.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.bar and event.type() == QEvent.Type.Hide:
            self.close()
        return super().eventFilter(watched, event)

    def show_in_corner(self) -> None:
        """Above the taskbar's clock, where Windows shows its own notifications."""
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - MARGIN, screen.bottom() - self.height() - MARGIN)
        self.show()
