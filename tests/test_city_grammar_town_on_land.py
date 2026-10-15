"""A town on its land: the town composer's version 3.

Version 3 lays a level town's recipe on a land document (:func:`on_land`), generating its
specification migrated to the city grammar version that lays a town on its land. These tests hold
what its receipt keeps (the land, its digest and its rules, beside version 2's arrival), that its
records generate again from that receipt and nothing else, that its seeds and tile keys are the
land's own, that a person arrives on the graded footway, and that a receipt whose land, rules or
grammar no longer agree is refused by name. A level town's recipe, seed and receipt are what they
were: the pins in ``test_generated_worlds.py`` and the town society tests hold those.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from functools import cache

import pytest
from exulanica.grammar.grammars.city.descriptor import CITY_LAND_VERSIONS
from exulanica.grammar.grammars.city.generation.massing import BuildingChange
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.landform import LandformRefused, land_recipes, land_rules
from exulanica.world.composers import UnknownWorldComposer, seed_candidate
from exulanica.world.composers import city_grammar_town as town
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_living import town_routine
from exulanica.world.society_walking_surfaces import walking_surfaces_place
from exulanica.world.world_recipes import town_recipe

WORLD = "world:generated:town-on-land"
LANDS = {recipe.key: dict(recipe.land) for recipe in land_recipes()}


@cache
def _made(land: str = "coast"):  # type: ignore[no-untyped-def]
    return compose_generated_world(town.on_land(town_recipe("small_town"), LANDS[land]), WORLD)


def _receipt(**changes: object) -> dict:  # type: ignore[type-arg]
    receipt = copy.deepcopy(_made().receipt)
    receipt.update(changes)
    return receipt


def test_a_level_town_s_recipe_names_no_land():
    reference = town_recipe("small_town").reference()
    assert not {"land", "land_sha256", "land_rules"} & set(reference)


def test_a_town_on_land_keeps_its_land_its_digest_and_its_rules():
    recipe = town.on_land(town_recipe("small_town"), LANDS["coast"])
    receipt = _made().receipt
    assert receipt["composer"] == {"key": town.COMPOSER_KEY, "version": 3}
    assert receipt["grammar"]["grammar_version"] in CITY_LAND_VERSIONS
    assert receipt["specification"]["grammar_version"] == receipt["grammar"]["grammar_version"]
    assert receipt["land"] == recipe.land
    assert receipt["land_sha256"] == recipe.land_sha256
    assert receipt["land_rules"] == land_rules()
    assert receipt["recipe"]["land_sha256"] == recipe.land_sha256
    assert receipt["recipe"]["land_rules"] == land_rules()
    # Version 2's arrival, with its pins.
    assert {"arrival_policy", "arrival_routine"} <= set(receipt)


def test_a_town_on_land_generates_again_from_its_receipt_alone():
    made = _made()
    assert town.records(made.receipt) == tuple(made.records)


def test_a_building_changed_in_a_town_on_land_stands_on_the_same_land():
    made = _made()
    assert town.records_with(made.receipt, {}) == tuple(made.records)
    removed = next(r.identity for r in made.records if isinstance(r, MassingRecord))
    changed = town.records_with(made.receipt, {removed: BuildingChange(removed=True)})
    assert removed not in {r.identity for r in changed if isinstance(r, MassingRecord)}
    terrain = [r for r in made.records if isinstance(r, TerrainRecord)]
    assert [r for r in changed if isinstance(r, TerrainRecord)] == terrain
    assert len({h for patch in terrain for h in patch.height_mm}) > 1, "the land is not level"


def test_a_person_arrives_on_the_graded_footway():
    made = _made()
    arrival = made.receipt["arrival"]
    place = walking_surfaces_place(f"generated:{WORLD}", made.records, routine=town_routine())
    [spot] = [spot for spot in place["spots"] if spot["spot_id"] == arrival["spot_id"]]
    assert arrival["support_z_mm"] == spot["support_z_mm"] > 0, "the coast's town is not level"
    [spawn] = made.candidate.placement["destinations"]
    assert spawn["y_mm"] == arrival["support_z_mm"]


def test_its_seeds_and_tile_keys_are_its_land_s_own():
    level = town_recipe("small_town")
    coast = town.on_land(level, LANDS["coast"])
    upland = town.on_land(level, LANDS["upland"])
    other_rules = dataclasses.replace(coast, land_rules={**coast.land_rules, "version": 0})
    seeds = {seed_candidate(recipe, WORLD, 0) for recipe in (level, coast, upland, other_rules)}
    assert len(seeds) == 4
    receipt = _made().receipt
    assert receipt["seed"] == seed_candidate(coast, WORLD, receipt["candidate"])
    keys = dict(town.tile_inputs(receipt))
    assert set(keys) == {tuple(tile) for tile in receipt["tiles"]}


def test_only_a_level_version_2_town_is_laid_on_land():
    level = town_recipe("small_town")
    with pytest.raises(ValueError, match="lays on land"):
        town.on_land(town.on_land(level, LANDS["coast"]), LANDS["upland"])
    with pytest.raises(ValueError, match="lays on land"):
        town.on_land(dataclasses.replace(level, composer_version=1), LANDS["coast"])
    with pytest.raises(LandformRefused):
        town.on_land(level, {"profile": "exulanica.landform/v1", "ground_mm": "high"})


def test_a_recipe_whose_version_and_land_disagree_is_refused_by_name():
    level = town_recipe("small_town")
    with pytest.raises(UnknownWorldComposer, match="no land"):
        town.compose(dataclasses.replace(level, composer_version=3), WORLD)
    landed = town.on_land(level, LANDS["coast"])
    with pytest.raises(UnknownWorldComposer, match="level ground"):
        town.compose(dataclasses.replace(landed, composer_version=2), WORLD)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"land": {**LANDS["coast"], "ground_mm": 1}}, "generated_world_land_changed"),
        ({"land_sha256": "0" * 64}, "generated_world_land_changed"),
        ({"land_rules": {"version": 0, "catalogs": {}}}, "generated_world_land_rules_changed"),
        ({"composer": {"key": town.COMPOSER_KEY, "version": 2}}, "generated_world_grammar_changed"),
    ],
    ids=["land", "digest", "rules", "level-composer"],
)
def test_a_receipt_whose_land_or_grammar_no_longer_agrees_is_refused_by_name(changes, code):
    receipt = _receipt(**changes)
    for read in (town.records, town.tile_inputs):
        with pytest.raises(InvalidStructuralData, match=code):
            read(receipt)


def test_a_town_on_land_names_the_land_grammar_and_a_level_one_names_no_land():
    landed = _receipt(grammar={**_made().receipt["grammar"], "grammar_version": 5})
    with pytest.raises(InvalidStructuralData, match="generated_world_grammar_changed"):
        town.records(landed)
    level = compose_generated_world(town_recipe("small_town"), WORLD).receipt
    with pytest.raises(InvalidStructuralData, match="generated_world_land_changed"):
        town.tile_inputs({**level, "land": LANDS["coast"]})


def test_the_land_drawn_round_a_town_is_the_land_its_terrain_was_graded_from():
    """The chunks under a town's tiles are its terrain records' heights to the millimetre, so the
    land the browser draws round the town meets its tiles; the ring round them, the backdrop and
    the land's own water come from the same grading, framed by the town's own seed."""
    made = _made()
    land = town.graded_land(made.receipt, made.records)
    documents = land.documents()
    section = land.drawing_section()
    terrain = [r for r in made.records if isinstance(r, TerrainRecord)]
    assert terrain
    for patch in terrain:
        chunk = json.loads(documents["chunks"][f"{patch.tile_x},{patch.tile_y}"]["body"])
        assert tuple(chunk["height_mm"]) == patch.height_mm, (patch.tile_x, patch.tile_y)
    under = {(patch.tile_x, patch.tile_y) for patch in terrain}
    named = {tuple(chunk["chunk"]) for chunk in section["chunks"]}
    assert under < named, "the near land rings the town's tiles"
    assert section["land_sha256"] == made.receipt["land_sha256"]
    assert land.frame.seed == made.receipt["seed"]
    assert {body["kind"] for body in section["water"]} >= {"sea"}, "the coast's town has its sea"
