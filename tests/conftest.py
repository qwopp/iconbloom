import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from app import main
from engine.themes import DEFAULT_THEME, Theme, load_theme
from platform_win import watch
from tests.fakes import SAMPLES_DIR, FakeDesktop

# Fixtures for driving the window (``harness``, ``say_yes``).
pytest_plugins = ["tests.ui_harness"]

# UI tests never open real windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Real-shell tests need IShellLink and friends; elsewhere the fakes cover the logic.
collect_ignore_glob = [] if sys.platform == "win32" else ["win/*"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        help="rewrite tests/goldens/*.png from the current engine output",
    )


@pytest.fixture
def update_goldens(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture(scope="session")
def kawaii() -> Theme:
    return load_theme(DEFAULT_THEME)


@pytest.fixture
def env(tmp_path: Path) -> FakeDesktop:
    return FakeDesktop(tmp_path)


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDesktop]:
    """A fake desktop that app.main's Windows wiring is pointed at."""
    env = FakeDesktop(tmp_path)
    monkeypatch.setattr(main, "default_app_paths", lambda: env.paths)
    monkeypatch.setattr(main, "windows_service", lambda paths: env.service())
    monkeypatch.setattr(watch, "first_copy", object)  # the only copy running
    # setup_logging adds a file handler to the root logger; drop it after the test.
    root = logging.getLogger()
    handlers = list(root.handlers)
    yield env
    for handler in root.handlers[len(handlers) :]:
        handler.close()
        root.removeHandler(handler)
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)


# Golden-tested for every theme besides the default: colorful, a plain glyph,
# a gradient, a tiny icon and a logo on a plain plate (for the cut-out styles).
REPRESENTATIVE_SAMPLES = ("multicolor", "simple_glyph", "gradient_app", "tiny", "plate_glyph")


def sample_names() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*.png"))


def load_sample(name: str) -> Image.Image:
    with Image.open(SAMPLES_DIR / f"{name}.png") as img:
        return img.convert("RGBA")
