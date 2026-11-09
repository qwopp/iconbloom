"""Stand-ins for Windows pieces, so shortcut logic is testable on any OS."""

import json
from pathlib import Path

from platform_win.shortcuts import IconLocation, LinkInfo


class FakeLinkIO:
    """Shortcuts stored as small JSON files with a .lnk name.

    Writing rewrites the whole file like IShellLink does, so byte-level
    backup and restore behave as they would on Windows.
    """

    def create(self, path: Path, target: str, icon: IconLocation | None = None) -> None:
        icon = icon or IconLocation()
        data = {"target": target, "args": "", "icon": icon.path, "index": icon.index}
        path.write_text(json.dumps(data), encoding="utf-8")

    def read(self, path: Path) -> LinkInfo:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OSError(f"not a shortcut: {path}") from exc
        return LinkInfo(data["target"], data["args"], IconLocation(data["icon"], data["index"]))

    def set_icon(self, path: Path, icon: IconLocation) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["icon"], data["index"] = icon.path, icon.index
        # Key order changes on purpose: a real save does not keep bytes stable either.
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
