"""Helpers every panel uses: buttons, error dialogs and friendly counts."""

import logging
from collections.abc import Callable, Sized

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

log = logging.getLogger(__name__)


def make_button(
    text: str, role: str, tip: str = "", slot: Callable[[], object] | None = None
) -> QPushButton:
    """A styled button; ``role`` (primary, secondary, danger) picks its look."""
    button = QPushButton(text)
    button.setProperty("role", role)
    button.setToolTip(tip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        button.clicked.connect(without_arguments(slot))
    return button


def without_arguments(slot: Callable[[], object]) -> Callable[..., None]:
    """Call ``slot`` with no arguments, whatever the signal sends.

    Qt passes a button's "checked" flag to its clicked handler, and an action
    with an optional parameter would take that flag as its argument.
    """

    def call(*_ignored: object) -> None:
        slot()

    return call


def guarded[T](parent: QWidget, action: Callable[[], T]) -> T | None:
    """Run an action, turning failures into a friendly dialog and a log entry."""
    try:
        return action()
    except Exception as exc:  # every failure reaches the user, never a silent crash
        log.exception("action failed")
        QMessageBox.warning(
            parent,
            "That didn't work",
            f"{exc}\n\nNothing else was changed. Details are in the log file.",
        )
        return None


def count(items: Sized, noun: str) -> str:
    """'1 shortcut', '3 shortcuts'."""
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"
