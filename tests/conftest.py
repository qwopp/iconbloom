from pathlib import Path

from PIL import Image

SAMPLES_DIR = Path(__file__).parent / "samples"


def sample_names() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*.png"))


def load_sample(name: str) -> Image.Image:
    with Image.open(SAMPLES_DIR / f"{name}.png") as img:
        return img.convert("RGBA")
