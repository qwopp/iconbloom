import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from engine.themes import DEFAULT_THEME, Theme, load_theme
from tests.fakes import SAMPLES_DIR, FakeDesktop

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


def sample_names() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*.png"))


def load_sample(name: str) -> Image.Image:
    with Image.open(SAMPLES_DIR / f"{name}.png") as img:
        return img.convert("RGBA")
