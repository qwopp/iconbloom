from pathlib import Path

from PIL import Image

from engine import sheet
from engine.themes import Theme
from tests.conftest import SAMPLES_DIR


def test_sheet_cli_renders_grid(tmp_path: Path, kawaii: Theme) -> None:
    out = tmp_path / "sheet.png"
    icons = tmp_path / "icons"
    icons.mkdir()
    for name in ("multicolor", "tiny"):
        (icons / f"{name}.png").write_bytes((SAMPLES_DIR / f"{name}.png").read_bytes())
    assert sheet.main([str(icons), "-o", str(out), "--seed", "2"]) == 0
    with Image.open(out) as img:
        columns = len(kawaii.recipes) + 1  # plus the original
        assert img.width == sheet.ROW_LABEL_W + columns * (sheet.CELL + sheet.GAP) + sheet.GAP
        assert (
            img.height == sheet.LABEL_H + 2 * (sheet.CELL + sheet.SMALL_H + sheet.GAP) + sheet.GAP
        )


def test_sheet_cli_fails_on_empty_folder(tmp_path: Path) -> None:
    assert sheet.main([str(tmp_path), "-o", str(tmp_path / "x.png")]) == 1
