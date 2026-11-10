import json
from dataclasses import asdict
from pathlib import Path

from app.choices import Choice, ChoiceStore


def test_choices_persist(tmp_path: Path) -> None:
    store = ChoiceStore(tmp_path / "choices.json")
    store.set("app", Choice("kawaii_pink", "tile_bow", seed=3))
    store.skip("other")
    reloaded = ChoiceStore(tmp_path / "choices.json")
    assert reloaded.get("app") == Choice("kawaii_pink", "tile_bow", seed=3)
    assert reloaded.is_skipped("other")
    assert reloaded.items() == [("app", Choice("kawaii_pink", "tile_bow", seed=3))]


def test_setting_a_choice_unskips(tmp_path: Path) -> None:
    store = ChoiceStore(tmp_path / "choices.json")
    store.skip("app")
    store.set("app", Choice("kawaii_pink", "sticker"))
    assert not store.is_skipped("app")


def test_clear_and_clear_all(tmp_path: Path) -> None:
    store = ChoiceStore(tmp_path / "choices.json")
    store.set("a", Choice("t", "r"))
    store.set("b", Choice("t", "r"))
    store.clear("a")
    store.clear("missing")
    assert store.get("a") is None
    store.clear_all()
    assert store.items() == []


def test_file_tags_differ_per_look() -> None:
    assert Choice("t", "r").file_tag == "t-r"
    assert Choice("t", "r", seed=2).file_tag == "t-r-s2"
    assert Choice("", "custom", custom_image="abc.png").file_tag == "custom-abc"
    styled = Choice("t", "r", 2, custom_image="abc.png")
    assert styled.uses_own_image
    assert not styled.as_is
    assert Choice.custom("abc.png").as_is
    assert styled.file_tag == "custom-abc-t-r-s2"


def test_styled_own_image_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "choices.json"
    choice = Choice("kawaii_pink", "cutout", custom_image="abc.png")
    ChoiceStore(path).set("app", choice)
    assert ChoiceStore(path).get("app") == choice


def test_unreadable_file_is_set_aside(tmp_path: Path) -> None:
    path = tmp_path / "choices.json"
    path.write_text("{oops", encoding="utf-8")
    store = ChoiceStore(path)
    assert store.items() == []
    assert len(list(tmp_path.glob("choices.json.unreadable-*"))) == 1
    store.set("a", Choice("t", "r"))
    assert ChoiceStore(path).get("a") is not None


def test_own_images_persist_until_forgotten(tmp_path: Path) -> None:
    path = tmp_path / "choices.json"
    store = ChoiceStore(path)
    store.set_image("app", "abc.png")
    assert ChoiceStore(path).image("app") == "abc.png"
    store.set_image("app", None)
    store.set_image("missing", None)
    assert ChoiceStore(path).image("app") is None


def test_reverting_keeps_own_images(tmp_path: Path) -> None:
    store = ChoiceStore(tmp_path / "choices.json")
    store.set("a", Choice("t", "r", custom_image="abc.png"))
    store.set_image("a", "abc.png")
    store.set_image("b", "def.png")
    store.clear("a")
    store.clear_all()
    assert (store.image("a"), store.image("b")) == ("abc.png", "def.png")


def test_older_files_take_own_images_from_applied_choices(tmp_path: Path) -> None:
    path = tmp_path / "choices.json"
    styled = Choice("kawaii_pink", "cutout", custom_image="abc.png")
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "choices": {"cat": asdict(styled), "plain": asdict(Choice("t", "r"))},
                "skipped": [],
            }
        ),
        encoding="utf-8",
    )
    store = ChoiceStore(path)
    assert store.image("cat") == "abc.png"
    assert store.image("plain") is None
    # Once saved with images, going back to the app's icon sticks.
    store.set_image("cat", None)
    assert ChoiceStore(path).image("cat") is None


def test_file_tags_never_collide() -> None:
    """Ids may contain "_", so the parts are joined with "-"."""
    assert Choice("mint", "matcha_tint").file_tag != Choice("mint_matcha", "tint").file_tag
    assert Choice("t", "r_s5").file_tag != Choice("t", "r", seed=5).file_tag
