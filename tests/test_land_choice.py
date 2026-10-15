"""The land a place made from a sentence stands on: the recipe catalog, every recipe taking a site's
layout, and the choice from the person's words, the setting and the default, with no model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.api.instance_settings import (
    WORLDS_ON_LAND_ENV,
    SocietySettingRefused,
    _explicitly_enabled,
)
from exulanica.grammar.landform import WorldFrame, land_recipes, read_land_document, water_bodies
from exulanica.world.composers import site_plan
from exulanica.world.kinds.document import read_kind
from exulanica.world.land_choice import choose_land, said_by_land
from exulanica.world.world_settings import setting_parts

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"


def _recipe(key: str):  # type: ignore[no-untyped-def]
    return next(recipe for recipe in land_recipes() if recipe.key == key)


def test_the_recipes_are_the_catalog_s_with_one_default_and_settings_that_exist() -> None:
    recipes = land_recipes()
    assert [recipe.key for recipe in recipes] == [
        "coast",
        "valley",
        "upland",
        "hillside",
        "rolling",
    ]
    assert [recipe.key for recipe in recipes if recipe.default] == ["rolling"]
    grounds = {part["key"] for part in setting_parts().listed() if part["axis"] == "ground"}
    named = [ground for recipe in recipes for ground in recipe.for_ground]
    assert set(named) == grounds and len(named) == len(grounds), "each ground part brings one land"
    for recipe in recipes:
        assert read_land_document(recipe.land).sha256 == recipe.land_sha256


def test_recipe_version_2_s_coast_pours_a_cascade_into_the_sea_and_version_1_reads_as_it_was():
    first, second = land_recipes(1), land_recipes()
    assert [recipe.key for recipe in first] == [recipe.key for recipe in second]
    assert [new.key for old, new in zip(first, second, strict=True) if old != new] == ["coast"]
    assert "cascade" not in {feature["kind"] for feature in first[0].land["features"]}
    coast = read_land_document(dict(_recipe("coast").land))
    for width, depth in ((16_000, 20_000), (256_000, 256_000)):
        water = water_bodies(coast, WorldFrame(width_mm=width, depth_mm=depth, seed="c" * 64))
        falls = [body for body in water if body.kind == "fall"]
        assert falls and falls[-1].bottom_mm == 0, "it falls into the sea in front of any site"


@pytest.mark.parametrize("key", ["coast", "valley", "upland", "hillside", "rolling"])
def test_every_recipe_takes_a_site_s_layout(key: str) -> None:
    """A recipe is land a place can be laid out on: each fixture kind is made on it."""
    for name in ("farm", "site"):
        kind = read_kind(json.loads((FIXTURES / f"fixture-{name}.json").read_text("utf-8")))
        world = site_plan.compose_kind(
            kind,
            kind.values(kind.presets[0][0]),
            f"world:generated:recipe-{key}",
            place_id="place:recipe",
            land=dict(_recipe(key).land),
        )
        assert world.receipt["land_sha256"] == _recipe(key).land_sha256


@pytest.mark.parametrize(
    ("words", "ground", "recipe", "chosen_by", "said"),
    [
        ("a quiet garden by the sea", None, "coast", "words", ["sea"]),
        ("a village in a valley under the mountains", None, "valley", "words", ["valley"]),
        ("a Hillside cafe", "sea", "hillside", "words", ["Hillside"]),
        ("a valley farm on the coast", None, "coast", "words", ["coast"]),
        ("a garden with no sea in sight", None, "rolling", "default", []),
        ("a farm far from the mountains", None, "rolling", "default", []),
        ("a town without a beach", "snowfield", "upland", "setting", []),
        ("a calm garden", "sea", "coast", "setting", []),
        ("a calm garden", "wheat_fields", "rolling", "setting", []),
        ("a calm garden", None, "rolling", "default", []),
    ],
)
def test_words_then_the_setting_then_the_default_choose_the_land(
    words: str, ground: str | None, recipe: str, chosen_by: str, said: list[str]
) -> None:
    chosen = choose_land(words, ground)
    assert (chosen.recipe.key, chosen.chosen_by) == (recipe, chosen_by)
    assert [words[start:end] for start, end in chosen.spans] == said


def test_a_saved_name_in_the_sentence_never_chooses_land() -> None:
    sent = "lunch at [place A] by the hills"
    name = (sent.index("["), sent.index("]") + 1)
    assert choose_land(sent, None, names=[name]).recipe.key == "hillside"
    named = "the [Sea View] cafe"
    assert choose_land(named, None, names=[(4, 14)]).recipe.key == "rolling"


def test_the_land_answers_only_a_phrase_that_names_it_alone() -> None:
    assert said_by_land("in a valley", _recipe("valley"))
    assert said_by_land("by the sea", _recipe("coast"))
    assert not said_by_land("sea with flying boats", _recipe("coast"))
    assert not said_by_land("in a valley", _recipe("coast"))
    assert not said_by_land("on the", _recipe("coast"))


def test_land_is_off_unless_the_installation_says_on_and_other_values_are_refused() -> None:
    read = lambda value: _explicitly_enabled(  # noqa: E731
        value, "worlds_on_land_not_boolean", WORLDS_ON_LAND_ENV
    )
    assert (read(None), read(""), read("off"), read("on"), read("true")) == (
        False,
        False,
        False,
        True,
        True,
    )
    with pytest.raises(SocietySettingRefused) as caught:
        read("hills")
    assert caught.value.code == "worlds_on_land_not_boolean"
