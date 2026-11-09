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
    assert Choice("t", "r").file_tag == "t_r"
    assert Choice("t", "r", seed=2).file_tag == "t_r_s2"
    assert Choice("", "custom", custom_image="abc.png").file_tag == "custom_abc"
    styled = Choice("t", "r", 2, custom_image="abc.png")
    assert styled.uses_own_image
    assert not styled.as_is
    assert Choice.custom("abc.png").as_is
    assert styled.file_tag == "custom_abc_t_r_s2"


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
