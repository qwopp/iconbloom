"""Apply and revert taskbar looks: the one place the taskbar's settings get changed.

Same order as icons, so a crash at any step leaves something to restore from:

1. record the settings as they are in taskbar.json (saved to disk)
2. write the new settings
3. note them as applied, with the look the user picked

Revert puts back only settings still as Iconbloom left them; one the user changed in
Windows' Settings since is theirs to keep.
"""

import logging
from dataclasses import dataclass

from engine.taskbar import BarSpec, SearchMode, accent_shades
from platform_win.backup import TaskbarBackup
from platform_win.taskbar import (
    Search,
    TaskbarIO,
    TaskbarState,
    adopt_outside_changes,
    labels,
    revert_plan,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskbarChoice:
    """The look picked on the Taskbar page, so the page can show it again."""

    theme: str
    look: str


class TaskbarService:
    def __init__(self, io: TaskbarIO, backup: TaskbarBackup) -> None:
        self._io = io
        self._backup = backup

    @property
    def win11(self) -> bool:
        return self._io.win11

    def search_modes(self) -> tuple[SearchMode, ...]:
        return tuple(SearchMode[mode.name] for mode in self._io.search_modes())

    def current(self) -> BarSpec:
        state = self._io.read()
        return BarSpec(
            color=state.accent,
            transparency=state.transparency,
            centered=state.centered,
            small=state.small,
            search=SearchMode[state.search.name],
            task_view=state.task_view,
            auto_hide=state.auto_hide,
            win11=self._io.win11,
            light=state.light_windows and state.accent is None,
        )

    def needs_dark_windows(self, wanted: BarSpec) -> bool:
        """Windows only colors the taskbar in dark mode, so applying ``wanted`` switches it."""
        return wanted.color is not None and self._io.read().light_windows

    @property
    def is_changed(self) -> bool:
        return self._backup.original is not None

    def applied_choice(self) -> TaskbarChoice | None:
        choice = self._backup.choice or {}
        theme, look = choice.get("theme"), choice.get("look")
        if isinstance(theme, str) and isinstance(look, str):
            return TaskbarChoice(theme, look)
        return None

    def apply(self, wanted: BarSpec, choice: TaskbarChoice, *, dry_run: bool = False) -> list[str]:
        """Make the taskbar look like ``wanted``; returns the names of the settings changed."""
        state = TaskbarState(
            accent=wanted.color,
            transparency=wanted.transparency,
            centered=wanted.centered,
            small=wanted.small,
            search=Search[wanted.search.name],
            task_view=wanted.task_view,
            auto_hide=wanted.auto_hide,
        )
        shades = accent_shades(wanted.color) if wanted.color is not None else ()
        planned = self._io.plan(state, shades)
        if dry_run:
            return labels(list(planned))
        original = adopt_outside_changes(
            self._backup.original, self._backup.applied, self._io.snapshot()
        )
        self._backup.save(original, self._backup.applied, self._backup.choice)
        self._io.write(planned)
        self._backup.save(
            original, self._io.snapshot(), {"theme": choice.theme, "look": choice.look}
        )
        log.info("taskbar: applied %s/%s, changed %s", choice.theme, choice.look, list(planned))
        return labels(list(planned))

    def revert(self, *, dry_run: bool = False) -> list[str]:
        """Put back every setting Iconbloom changed; returns the names of those it did."""
        original = self._backup.original
        if original is None:
            return []
        plan = revert_plan(original, self._backup.applied, self._io.snapshot())
        if dry_run:
            return labels(list(plan))
        if plan:
            self._io.restore(plan)
        self._backup.forget()
        log.info("taskbar: reverted %s", list(plan))
        return labels(list(plan))
