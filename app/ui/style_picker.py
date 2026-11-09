"""The right panel: the styled versions of the selected icon, and the buttons that act on them."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PIL import Image
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.changes import Status
from app.choices import Choice
from app.service import IconService
from app.ui.controls import count, make_button
from app.ui.jobs import JobRunner
from app.ui.widgets import PreviewCard, SizePopup, pixmap_at, to_qimage
from engine import analyze, ops
from engine.recipes import render
from engine.themes import Theme
from platform_win.shortcuts import ItemKind, Place, ShortcutGroup

log = logging.getLogger(__name__)

PREVIEW_COLUMNS = 4
ORIGINAL_PX = 64
SELECTION_ICON = 48


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
class StripIcon:
    key: str
    image: QImage


class StylePicker(QWidget):
    # The highlighted style changed.
    chosen_changed = Signal()
    # A style was double-clicked: apply it straight away.
    activated = Signal()

    def __init__(
        self, service: IconService, jobs: JobRunner, theme: Theme, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.setObjectName("card")
        self._service = service
        self._jobs = jobs
        self._theme = theme
        self._target: ShortcutGroup | None = None
        self._seed = 0
        self._token = 0
        self._strip_token = 0
        self._previews: PreviewSet | None = None
        self._custom: Preview | None = None
        self._cards: list[PreviewCard] = []
        self._chosen: PreviewCard | None = None
        self.popup = SizePopup(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_cards(), 1)
        layout.addWidget(self._build_selection_strip())
        layout.addLayout(self._build_actions())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        self.original_label = QLabel()
        self.original_label.setFixedSize(ORIGINAL_PX, ORIGINAL_PX)
        header.addWidget(self.original_label)
        names = QVBoxLayout()
        self.name_label = QLabel("Pick an icon")
        self.name_label.setObjectName("heading")
        self.detail_label = QLabel("Looking for your icons…")
        self.detail_label.setObjectName("detail")
        self.detail_label.setWordWrap(True)
        names.addWidget(self.name_label)
        names.addWidget(self.detail_label)
        header.addLayout(names, 1)
        self.shuffle_button = make_button(
            "Shuffle", "secondary", "Try different shades, positions and decorations", self.shuffle
        )
        self.own_image_button = make_button(
            "Use my own image…",
            "secondary",
            "Use a picture of your own (PNG, ICO or BMP) as this icon",
        )
        header.addWidget(self.shuffle_button)
        header.addWidget(self.own_image_button)
        return header

    def _build_cards(self) -> QScrollArea:
        host = QWidget()
        self._cards_layout = QGridLayout(host)
        self._cards_layout.setSpacing(12)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setObjectName("previewScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        return scroll

    def _build_selection_strip(self) -> QFrame:
        """With several icons selected, the chosen style drawn on each of them."""
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
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        column.addWidget(scroll)
        self.selection_strip.hide()
        return self.selection_strip

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self.revert_button = make_button(
            "Revert", "secondary", "Put the original icon back for the selected icons"
        )
        self.all_button = make_button(
            "Apply style to all",
            "secondary",
            "Use the selected style on every icon you haven't styled or skipped yet",
        )
        self.skip_button = make_button(
            "Skip", "secondary", "Leave this one as it is and go to the next"
        )
        self.apply_button = make_button(
            "Apply", "primary", "Use the selected style (or double-click a style)"
        )
        actions.addWidget(self.revert_button)
        actions.addWidget(self.all_button)
        actions.addStretch(1)
        actions.addWidget(self.skip_button)
        actions.addWidget(self.apply_button)
        return actions

    # ---- state the window asks about ----------------------------------------

    @property
    def cards(self) -> list[PreviewCard]:
        return list(self._cards)

    @property
    def chosen(self) -> PreviewCard | None:
        return self._chosen

    def prepared_icon(self, target: ShortcutGroup) -> Image.Image | None:
        """The prepared original of ``target``, if its previews are showing."""
        previews = self._previews
        return previews.icon if previews and previews.group_key == target.key else None

    # ---- showing a group ----------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        if self._target is not None:
            self.show_group(self._target)

    def reset(self) -> None:
        """A different icon was picked: back to the default look, no custom image."""
        self._seed = 0
        self._custom = None
        self._clear_cards()

    def show_message(self, text: str) -> None:
        self.detail_label.setText(text)

    def show_group(self, target: ShortcutGroup) -> None:
        self._target = target
        self.name_label.setText(target.name)
        self._set_detail(target, upscaled=False)
        self._clear_cards()
        self._render_previews(target)

    def shuffle(self) -> None:
        if self._target is not None:
            self._seed += 1
            self.show_group(self._target)

    def add_custom(self, choice: Choice) -> None:
        """Offer the user's own image first among the styles."""
        full, _ = self._service.styles.render(choice)
        self._custom = Preview("Your image", choice, to_qimage(full))
        self._show_cards()

    def _set_detail(self, target: ShortcutGroup, *, upscaled: bool) -> None:
        # Say where the style lands, so a missing taskbar pin is no surprise.
        where = ", ".join(place for place in Place if place in target.places)
        kind = target.primary.kind
        prefix = "" if kind is ItemKind.SHORTCUT else f"{kind} · "
        notes = [f"{prefix}{where} · {self._service.status(target)}"]
        if target.shared_shortcuts:
            notes.append("Shared by every user on this PC: Windows will ask for permission.")
        if upscaled:
            notes.append("This app only ships a small icon, so styles may look a little soft.")
        self.detail_label.setText("  ".join(notes))

    def _render_previews(self, target: ShortcutGroup) -> None:
        theme, seed, service = self._theme, self._seed, self._service
        # Shuffle and theme switches keep the same original; skip re-extracting it.
        cached = (
            self._previews if self._previews and self._previews.group_key == target.key else None
        )

        def work(_report: Callable[[object], None]) -> PreviewSet:
            if cached is not None:
                icon, upscaled = cached.icon, cached.upscaled
            else:
                extracted = service.original_icon(target)
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

        self._token += 1
        token = self._token
        self._jobs.start(
            work,
            on_done=lambda result: self._on_previews(token, result),
            on_failed=lambda message: self._on_preview_failed(token, message),
        )

    def _on_previews(self, token: int, result: object) -> None:
        target = self._target
        if token != self._token or not isinstance(result, PreviewSet):
            return
        if target is None or target.key != result.group_key:
            return
        self._previews = result
        ratio = self.devicePixelRatioF()
        self.original_label.setPixmap(pixmap_at(result.original, ORIGINAL_PX, ratio))
        self._set_detail(target, upscaled=result.upscaled)
        self._show_cards()

    def _on_preview_failed(self, token: int, message: str) -> None:
        if token == self._token:
            self.detail_label.setText(f"Couldn't read this app's icon: {message}")

    # ---- cards --------------------------------------------------------------

    def _show_cards(self) -> None:
        self._clear_cards()
        if self._previews is None:
            return
        previews = ([self._custom] if self._custom else []) + self._previews.previews
        for i, preview in enumerate(previews):
            card = PreviewCard(preview.choice, preview.label, preview.image)
            card.clicked.connect(self.choose)
            card.activated.connect(self._choose_and_activate)
            card.hovered.connect(self._on_card_hover)
            self._cards_layout.addWidget(card, i // PREVIEW_COLUMNS, i % PREVIEW_COLUMNS)
            self._cards.append(card)
        self.choose(self._cards[0])

    def _clear_cards(self) -> None:
        self.popup.hide()
        for card in self._cards:
            # Out of the layout and hidden now; deleteLater() alone would leave the old
            # cards painted until the event loop gets round to deleting them.
            self._cards_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards.clear()
        self._chosen = None
        self.chosen_changed.emit()

    def choose(self, card: object) -> None:
        if not isinstance(card, PreviewCard):
            return
        for other in self._cards:
            other.set_selected(other is card)
        self._chosen = card
        self.chosen_changed.emit()

    def _choose_and_activate(self, card: object) -> None:
        self.choose(card)
        self.activated.emit()

    def _on_card_hover(self, card: object, entered: bool) -> None:
        if not entered or not isinstance(card, PreviewCard) or self._previews is None:
            self.popup.hide()
            return
        at = card.mapToGlobal(QPoint(card.width() + 6, 0))
        self.popup.show_for(self._previews.original, card.image, at)

    # ---- buttons and the multi-select strip ---------------------------------

    def update_actions(self, selected: Sequence[ShortcutGroup]) -> None:
        chosen = self._chosen
        has_target = self._target is not None
        self.apply_button.setEnabled(bool(selected) and chosen is not None)
        self.apply_button.setText(f"Apply to {len(selected)}" if len(selected) > 1 else "Apply")
        self.all_button.setEnabled(chosen is not None and not chosen.choice.is_custom)
        self.skip_button.setEnabled(bool(selected))
        styled = any(self._service.status(g) is Status.THEMED for g in selected)
        self.revert_button.setEnabled(styled)
        self.shuffle_button.setEnabled(has_target)
        self.own_image_button.setEnabled(has_target)
        self._update_strip(selected)

    def _update_strip(self, selected: Sequence[ShortcutGroup]) -> None:
        card = self._chosen
        if len(selected) < 2 or card is None:
            self.selection_strip.hide()
            return
        self.selection_label.setText(f"“{card.label}” on {count(selected, 'selected icon')}:")
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
        service = self._service
        self._strip_token += 1
        token = self._strip_token

        def work(report: Callable[[object], None]) -> None:
            for target in selected:
                if token != self._strip_token:
                    return  # the selection or style changed; stop drawing this one
                try:
                    if choice.is_custom:
                        image, _ = service.styles.render(choice)
                    else:
                        icon, _ = ops.prepare(service.original_icon(target).image)
                        theme = service.styles.theme(choice.theme)
                        image = render(theme.recipe(choice.recipe), icon, theme, seed=choice.seed)
                except Exception:  # one unreadable icon leaves an empty slot, nothing more
                    log.exception("could not preview %s", target.name)
                    continue
                report(StripIcon(target.key, to_qimage(image)))

        def on_icon(payload: object) -> None:
            if token == self._strip_token and isinstance(payload, StripIcon):
                label = slots.get(payload.key)
                if label is not None:
                    ratio = self.devicePixelRatioF()
                    label.setPixmap(pixmap_at(payload.image, SELECTION_ICON, ratio))

        self._jobs.start(work, on_progress=on_icon)
