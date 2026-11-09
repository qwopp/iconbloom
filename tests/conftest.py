import sys
from pathlib import Path

import pytest
from PIL import Image

from engine.themes import Theme, load_theme

SAMPLES_DIR = Path(__file__).parent / "samples"

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
    return load_theme("kawaii_pink")


def sample_names() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*.png"))


def load_sample(name: str) -> Image.Image:
    with Image.open(SAMPLES_DIR / f"{name}.png") as img:
        return img.convert("RGBA")
