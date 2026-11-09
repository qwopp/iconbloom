"""Run changes to icons in the background, and tell the user what happened."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QMessageBox, QProgressDialog, QStatusBar, QWidget

from app.changes import DECLINED_REASON, SHARED_REASON, ChangeReport
from app.settings import Settings
from app.ui.controls import count, guarded
from app.ui.jobs import JobRunner
from app.ui.notice import NoticeBar
from platform_win.paths import AppPaths
from platform_win.refresh import is_pinned
from platform_win.shortcuts import ShortcutGroup, Source

# A change to run: given a progress callback (False from it means "stop"), returns its report.
type Change = Callable[[Callable[[int, ShortcutGroup], bool]], ChangeReport]

# Show the progress dialog only for changes that take longer than this.
PROGRESS_DELAY_MS = 400
SKIPPED_SHOWN = 20


@dataclass(frozen=True)
class BatchStep:
    index: int
    name: str


class ChangeRunner:
    def __init__(
        self,
        parent: QWidget,
        jobs: JobRunner,
        notice: NoticeBar,
        status_bar: QStatusBar,
        settings: Settings,
        paths: AppPaths,
        *,
        refresh_icons: Callable[[], None],
        reload: Callable[[], None],
        include_shared: Callable[[Sequence[ShortcutGroup]], None],
    ) -> None:
        self._parent = parent
        self._jobs = jobs
        self._notice = notice
        self._status = status_bar
        self._settings = settings
        self._paths = paths
        self._refresh_icons = refresh_icons
        self._reload = reload
        self._include_shared = include_shared
        self._running = 0

    @property
    def running(self) -> bool:
        return bool(self._running)

    def run(
        self,
        title: str,
        targets: Sequence[ShortcutGroup],
        change: Change,
        on_done: Callable[[ChangeReport], None],
        *,
        reload: bool = False,
    ) -> None:
        """Run a change on the thread pool, so a permission prompt never freezes the window.

        A progress dialog with a Stop button appears if it takes more than a moment.
        """
        dialog = QProgressDialog(title, "Stop", 0, max(len(targets), 1), self._parent)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(PROGRESS_DELAY_MS)
        stop = threading.Event()
        dialog.canceled.connect(stop.set)
        self._running += 1

        def work(report: Callable[[object], None]) -> ChangeReport:
            def step(i: int, target: ShortcutGroup) -> bool:
                report(BatchStep(i, target.name))
                return not stop.is_set()

            return change(step)

        def on_progress(item: object) -> None:
            if isinstance(item, BatchStep):
                dialog.setValue(item.index)
                dialog.setLabelText(f"{title}\n{item.name}")

        def finished(result: object) -> None:
            self._running -= 1
            dialog.reset()
            if isinstance(result, ChangeReport):
                self._show_skipped(result)
                self.show_taskbar_notice(result, targets)
                on_done(result)
            if reload:
                self._reload()

        def failed(message: str) -> None:
            self._running -= 1
            dialog.reset()
            QMessageBox.warning(self._parent, "That didn't work", message)
            self._reload()

        self._jobs.start(work, on_done=finished, on_failed=failed, on_progress=on_progress)

    def ask_about_shared(self, targets: Sequence[ShortcutGroup]) -> bool | None:
        """Whether to include shortcuts every user shares; None means cancel."""
        shared = [t for t in targets if t.shared_shortcuts]
        if not shared:
            return False
        remembered = self._settings.shared_shortcuts
        if remembered in ("include", "skip"):
            return remembered == "include"
        which = shared[0].name if len(shared) == 1 else f"{len(shared)} of these apps"
        box = QMessageBox(self._parent)
        box.setWindowTitle("Shared shortcuts")
        box.setIcon(QMessageBox.Icon.Question)
        text = (
            f"{which} also {'has' if len(shared) == 1 else 'have'} a shortcut that every user "
            "on this PC shares. Windows will ask for administrator permission to change it."
        )
        if any(shared_start_menu(t) for t in shared):
            text += (
                "\n\nThe taskbar takes its icons from the Start menu, so with “Only mine” "
                "it keeps showing the old icon."
            )
        box.setText(text)
        include = box.addButton("Change those too", QMessageBox.ButtonRole.AcceptRole)
        mine = None
        if any(t.own_shortcuts for t in targets):
            mine = box.addButton("Only mine", QMessageBox.ButtonRole.RejectRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        remember = QCheckBox("Remember my answer")
        box.setCheckBox(remember)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked not in (include, mine):
            return None
        answer = clicked is include
        if remember.isChecked():
            self._settings.shared_shortcuts = "include" if answer else "skip"
            guarded(self._parent, lambda: self._settings.save(self._paths.settings))
        return answer

    def show_taskbar_notice(
        self, report: ChangeReport, targets: Sequence[ShortcutGroup] = ()
    ) -> None:
        left_out = taskbar_left_out(targets, report)
        if left_out:
            which = f"{left_out[0].name}'s" if len(left_out) == 1 else f"{len(left_out)} apps'"
            self._notice.show_message(
                f"Windows draws {which} taskbar icon from a Start menu shortcut every user "
                "shares, which was left as it was, so the taskbar keeps the old icon.",
                [
                    (
                        "Change it too",
                        lambda: self._include_shared(left_out),
                        "Windows will ask for administrator permission",
                    )
                ],
            )
        elif any(is_pinned(p) for p in report.changed):
            self._notice.show_message(
                "Windows keeps its own copy of taskbar icons, so they can take a moment to "
                "update. If one still looks old, refresh Windows' icons.",
                [
                    (
                        "Refresh icons",
                        self._refresh_icons,
                        "Rebuild Windows' icon cache and restart Explorer",
                    )
                ],
            )

    def _show_skipped(self, report: ChangeReport) -> None:
        # Skipping shared shortcuts was the user's own choice; no need to repeat it.
        problems = [(p, why) for p, why in report.skipped if why != SHARED_REASON]
        declined = [p for p, why in problems if why == DECLINED_REASON]
        problems = [(p, why) for p, why in problems if why != DECLINED_REASON]
        if declined:
            self._status.showMessage(
                f"Left {count(declined, 'shared shortcut')} as they were", 5000
            )
        if problems:
            reasons = "\n".join(f"{p.stem}: {why}" for p, why in problems[:SKIPPED_SHOWN])
            QMessageBox.information(self._parent, "Some items were left alone", reasons)


def shared_start_menu(target: ShortcutGroup) -> tuple[Path, ...]:
    """The group's Start menu shortcuts every user shares, which the taskbar draws it from."""
    return tuple(s.path for s in target.shared_shortcuts if s.source is Source.ALL_USERS_START_MENU)


def taskbar_left_out(targets: Sequence[ShortcutGroup], report: ChangeReport) -> list[ShortcutGroup]:
    """Groups that got styled while their shared Start menu shortcut was left alone."""
    left = {p for p, why in report.skipped if why in (SHARED_REASON, DECLINED_REASON)}
    changed = set(report.changed)
    return [
        t
        for t in targets
        if any(s.path in changed for s in t.own_shortcuts)
        and any(p in left for p in shared_start_menu(t))
    ]
