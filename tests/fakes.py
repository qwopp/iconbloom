"""Stand-ins for Windows pieces, so shortcut logic is testable on any OS."""

import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path, PureWindowsPath

from PIL import Image

from app.elevation import ELEVATED_FLAG, WindowsElevator, handle_request
from app.service import IconService
from platform_win.elevate import ElevationDeclinedError
from platform_win.extract import SHARP_MIN, ExtractedIcon
from platform_win.paths import AppPaths
from platform_win.shortcuts import IconLocation, LinkInfo, ScanRoot, Source

SAMPLES_DIR = Path(__file__).parent / "samples"


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


class FakeDesktop:
    """A temp-folder stand-in for the user's shortcut folders, wired to an IconService.

    ``icons`` maps app name to a sample icon; apps not listed get ``default``.
    Apps named in ``unreadable`` fail extraction, like a broken program file.
    """

    def __init__(
        self,
        root: Path,
        icons: Mapping[str, str] | None = None,
        default: str = "multicolor",
        unreadable: Collection[str] = (),
    ) -> None:
        self.desktop = root / "Desktop"
        self.common = root / "Common"
        self.desktop.mkdir()
        self.common.mkdir()
        self.paths = AppPaths(root / "Iconbloom")
        self.link_io = FakeLinkIO()
        self.notified = 0
        self.refreshed: list[Path] = []
        self.roots = [
            ScanRoot(self.desktop, Source.DESKTOP, recursive=False),
            ScanRoot(self.common, Source.ALL_USERS_START_MENU, recursive=True),
        ]
        # Plays Windows' permission prompt: True = the user says No.
        self.decline_permission = False
        self.elevations: list[list[str]] = []
        self._icons = dict(icons or {})
        self._default = default
        self._unreadable = set(unreadable)

    def make(self, name: str, folder: Path | None = None, icon: str = "") -> Path:
        path = (folder or self.desktop) / f"{name}.lnk"
        self.link_io.create(path, rf"C:\Apps\{name}.exe", IconLocation(icon, 1 if icon else 0))
        return path

    def service(self) -> IconService:
        return IconService(
            self.paths,
            self.link_io,
            self.roots,
            extractor=self.extract,
            notify=self._notify,
            elevator=WindowsElevator(self.paths, launch=self._launch_elevated),
        )

    def _launch_elevated(self, arguments: Sequence[str]) -> int:
        """Stand-in for starting the elevated copy: same request file, same checks."""
        self.elevations.append(list(arguments))
        if self.decline_permission:
            raise ElevationDeclinedError
        flag, request = arguments
        assert flag == ELEVATED_FLAG
        admin = IconService(self.paths, self.link_io, roots=[])
        return handle_request(Path(request), admin, [self.common])

    def extract(
        self, icon: IconLocation, target: str, shortcut: Path, *, use_shell: bool = True
    ) -> ExtractedIcon:
        """Stand-in extractor: the sample icon for the app, labelled with where it came from."""
        app = PureWindowsPath(target).stem
        if app in self._unreadable:
            raise OSError(f"{app}: unreadable icon")
        sample = self._icons.get(app, self._default)
        with Image.open(SAMPLES_DIR / f"{sample}.png") as img:
            image = img.convert("RGBA")
        source = icon.path if not use_shell else f"{icon.path} (shell allowed)"
        return ExtractedIcon(image, max(image.size) < SHARP_MIN, source)

    def _notify(self, paths: Sequence[Path]) -> None:
        self.notified += 1
        self.refreshed.extend(paths)
