"""The banner across the top of the window, for things worth knowing right now."""

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from app.ui.controls import make_button

# (button text, what it does, hover text)
type NoticeAction = tuple[str, Callable[[], object], str]


class NoticeBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        self._actions = QHBoxLayout()
        row.addLayout(self._actions)
        close = QToolButton()
        close.setObjectName("closeNotice")
        close.setText("✕")
        close.setToolTip("Dismiss")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        self.hide()

    def show_message(self, text: str, actions: Sequence[NoticeAction] = ()) -> None:
        """Show ``text`` with buttons; the first is the main one, and any button closes it."""
        while self._actions.count():
            item = self._actions.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for i, (text_, action, tip) in enumerate(actions):
            button = make_button(text_, "primary" if i == 0 else "secondary", tip, action)
            button.clicked.connect(self.hide)
            self._actions.addWidget(button)
        self.label.setText(text)
        self.show()
