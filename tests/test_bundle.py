"""The packaged app must be able to load every theme from the files it ships."""

import shutil
from pathlib import Path

import pytest

from engine.themes import list_themes, load_theme
from scripts.bundle import theme_files

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bundled_themes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    bundle = tmp_path_factory.mktemp("bundle")
    for source, dest in theme_files(ROOT):
        (bundle / dest).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, bundle / dest / source.name)
    return bundle / "themes"


def test_bundle_has_every_theme(bundled_themes: Path) -> None:
    assert list_themes(bundled_themes) == list_themes()


@pytest.mark.parametrize("theme_id", list_themes())
def test_every_theme_loads_from_the_bundle(bundled_themes: Path, theme_id: str) -> None:
    shipped = load_theme(theme_id, bundled_themes)
    assert shipped.recipes == load_theme(theme_id).recipes
    assert set(shipped.assets) == set(load_theme(theme_id).assets)


def test_bundle_leaves_out_sources() -> None:
    assert all(source.suffix in {".json", ".png"} for source, _ in theme_files(ROOT))
