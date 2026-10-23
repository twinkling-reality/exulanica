"""The land a place made from a sentence stands on: the recipe catalog, every recipe taking a site's
layout, and the choice from the person's words, the setting and the default, with no model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.api.instance_settings import SocietySettingRefused, _worlds_on_land
from exulanica.grammar.landform import (
    CELL_MM,
    WorldFrame,
    height_at,
    land_recipes,
    read_land_document,
    water_bodies,
)
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


def test_recipe_version_3_s_coast_meets_the_sea_nearer_and_version_2_reads_as_it_was():
    """Version 3 differs from version 2 in the coast alone: its shore begins 25 m from the place
    rather than 70 m, so in a town's frame and a site's the land meets the sea within 45 m of the
    place's sea-facing edge, and its falls still end in the sea; its cascade follows the land, so
    its last fall pours off the shore and no pool stands over the sea."""
    second, third = land_recipes(2), land_recipes(3)
    assert [recipe.key for recipe in second] == [recipe.key for recipe in third]
    assert [new.key for old, new in zip(second, third, strict=True) if old != new] == ["coast"]

    def shore(recipe):  # type: ignore[no-untyped-def]
        return next(f for f in recipe.land["features"] if f["kind"] == "shore")

    assert (shore(second[0])["distance_mm"], shore(third[0])["distance_mm"]) == (70_000, 25_000)
    coast = read_land_document(dict(third[0].land))
    for width, depth in ((256_000, 128_000), (96_000, 72_000)):
        frame = WorldFrame(width_mm=width, depth_mm=depth, seed="c" * 64)
        wet = next(
            d for d in range(0, 200_001, 5_000) if height_at(coast, frame, width // 2, -d) <= 0
        )
        assert wet <= 45_000, (width, depth, wet)
        falls = [body for body in water_bodies(coast, frame) if body.kind == "fall"]
        assert falls and falls[-1].bottom_mm == 0
    land = dict(third[0].land)
    before = read_land_document(
        {**land, "features": [f for f in land["features"] if f["kind"] != "cascade"]}
    )
    for width, depth in ((16_000, 20_000), (96_000, 72_000), (256_000, 128_000)):
        for n in range(4):
            frame = WorldFrame(width_mm=width, depth_mm=depth, seed=f"{n:x}" * 64)
            bodies = [body for body in water_bodies(coast, frame) if body.id.startswith("falls")]
            pools = [body for body in bodies if body.kind == "pool"]
            last = [body for body in bodies if body.kind == "fall"][-1]
            x = (pools[0].rect_mm[0] + pools[0].rect_mm[2]) // 2
            # The last fall pours off the shore: the land there, before the cascade, is the sea's,
            # and a cell landward it is dry.
            y = last.rect_mm[1]
            assert height_at(before, frame, x, y) <= 0 < height_at(before, frame, x, y + CELL_MM)
            for pool in pools:
                over = range(pool.rect_mm[1], pool.rect_mm[3] + 1, CELL_MM)
                assert all(height_at(before, frame, x, y) > 0 for y in over), (frame, pool.id)


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


def test_land_is_on_unless_the_installation_says_off_and_other_values_are_refused() -> None:
    assert (
        _worlds_on_land(None),
        _worlds_on_land(""),
        _worlds_on_land("  "),
        _worlds_on_land("on"),
        _worlds_on_land("true"),
        _worlds_on_land("off"),
        _worlds_on_land("0"),
    ) == (True, True, True, True, True, False, False)
    for value in ("hills", "maybe"):
        with pytest.raises(SocietySettingRefused) as caught:
            _worlds_on_land(value)
        assert caught.value.code == "worlds_on_land_not_boolean"


def test_a_server_that_states_nothing_makes_worlds_on_land(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from exulanica.api.services import build_services

    monkeypatch.setattr(
        "exulanica.api.services.load_account_runtime", lambda _: SimpleNamespace(guest=None)
    )
    environ = {"EXULANICA_DATABASE_URL": "postgresql://unused", "EXULANICA_DATA_DIR": str(tmp_path)}
    assert build_services(environ).worlds_on_land is True
    assert build_services({**environ, "EXULANICA_WORLDS_ON_LAND": ""}).worlds_on_land is True
    assert build_services({**environ, "EXULANICA_WORLDS_ON_LAND": "off"}).worlds_on_land is False
    with pytest.raises(SocietySettingRefused):
        build_services({**environ, "EXULANICA_WORLDS_ON_LAND": "hills"})
