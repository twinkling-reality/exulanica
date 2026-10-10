"""A town's homes follow the floor its premises records state, and a town keeps the routine it was
made under.

What holds each claim, none of it the code under test:

* the catalogs' own JSON (the floor area a dwelling takes, the residents a dwelling houses, the
  people a new town starts with) and the premises records' own floor areas, with the spread
  worked here by exact fractions;
* a spread of ten people worked by hand;
* the routine a receipt pins, read back from the receipt, and the people a town had under it.
"""

from __future__ import annotations

import dataclasses
import json
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.world import society_catalogs
from exulanica.world.arrival_worlds import load_arrival_worlds
from exulanica.world.composers import composer_module
from exulanica.world.generated_worlds import compose_generated_world, compose_specified_world
from exulanica.world.society_city_place import _people_living
from exulanica.world.society_living import town_routine, town_routine_of
from exulanica.world.society_walking_surfaces import place_residents, walking_surfaces_place
from exulanica.world.specification_samples import compute_sample
from exulanica.world.town_people import people_frame
from exulanica.world.world_recipes import town_recipe

from living_town_support import per_town_routine

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "assets" / "catalogs" / "society"


def _entries(name: str) -> dict[str, dict[str, Any]]:
    stated = json.loads((CATALOGS / name).read_text(encoding="utf-8"))
    return {entry["key"]: entry for entry in stated["entries"]}


@per_town_routine
def _composed(recipe: str) -> Any:
    return compose_generated_world(town_recipe(recipe), f"world:generated:floor-area-{recipe}")


def _homes(place: dict[str, Any]) -> dict[str, int]:
    """Each premises of homes of a place with how many people live there, by record identity."""
    return {
        dest["subject_id"].split(":", 1)[1]: dest["resident_capacity"]
        for dest in place["destinations"]
        if dest["use_class"] == "residential"
    }


def _spread(holds: dict[str, int], budget: int) -> dict[str, int]:
    """``budget`` people over homes in proportion to what each holds, by largest remainder with
    ties in identity order, in exact fractions."""
    total = sum(holds.values())
    if budget >= total:
        return dict(holds)
    exact = {key: Fraction(places * budget, total) for key, places in holds.items()}
    living = {key: int(share) for key, share in exact.items()}
    left = budget - sum(living.values())
    by_remainder = sorted(holds, key=lambda key: (-(exact[key] - living[key]), key))
    for key in by_remainder[:left]:
        living[key] += 1
    return living


@pytest.mark.parametrize("recipe", ["small_town", "market_town"])
def test_a_new_town_s_people_follow_the_floor_its_homes_records_state(recipe: str):
    uses = _entries("society-use-class.v3.json")
    policy = _entries("society-policy.v3.json")
    dwelling = uses["residential"]["dwelling_floor_area_mm2"]
    residents = uses["residential"]["resident_capacity"]
    budget = policy["town_people_default"]["value"]
    assert (dwelling, residents, budget) == (50_000_000, 2, 128)
    composed = _composed(recipe)
    # A new town's receipt pins the routine it was made under: the one a new town is made under.
    assert composed.receipt["arrival_routine"] == town_routine().binding()
    assert composed.receipt["arrival_routine"]["catalog_versions"]["society-use-class"] == 3
    place = walking_surfaces_place("place:floor-area", composed.records, town_routine())
    lived = _homes(place)
    records = {
        record.identity: record
        for record in composed.records
        if isinstance(record, PremisesRecord) and record.identity in lived
    }
    assert set(records) == set(lived)
    holds = {
        identity: max(1, record.floor_area_mm2 // dwelling) * residents
        for identity, record in records.items()
    }
    # The homes hold several times the people a town starts with, so the budget is what binds.
    assert sum(holds.values()) > 3 * budget
    assert lived == _spread(holds, budget)
    assert place_residents(place) == budget
    # More floor is never fewer people, and the tallest homes house more than the smallest.
    by_floor = sorted(records, key=lambda identity: records[identity].floor_area_mm2)
    assert all(lived[a] <= lived[b] + 1 for a, b in pairwise(by_floor))
    assert lived[by_floor[-1]] > lived[by_floor[0]]
    # What a society of things is given of the town is the same people.
    assert people_frame(place, town_routine())["population"] == budget


def test_ten_people_over_three_homes_by_hand():
    routine = town_routine()
    dwelling = routine.use_classes["residential"].dwelling_floor_area_mm2

    def home(identity: str, dwellings_and_a_bit: int) -> SimpleNamespace:
        return SimpleNamespace(
            identity=identity, use_class="residential", floor_area_mm2=dwellings_and_a_bit
        )

    homes = [
        # Five dwellings and most of a sixth: ten people.
        home("a", 5 * dwelling + dwelling - 1),
        # Three dwellings: six people.
        home("b", 3 * dwelling),
        # Less floor than one dwelling takes is still one dwelling: two people.
        home("c", dwelling // 2),
        # Nobody lives at a shop.
        SimpleNamespace(identity="shop", use_class="bakery", floor_area_mm2=9 * dwelling),
    ]

    def living(budget: int | None) -> dict[str, int]:
        policy = {k: v for k, v in routine.policy.items() if k != "town_people_default"}
        if budget is not None:
            policy["town_people_default"] = budget
        return _people_living(homes, dataclasses.replace(routine, policy=policy))

    full = {"a": 10, "b": 6, "c": 2}
    assert living(None) == full
    assert living(18) == full and living(500) == full
    # Nine of eighteen places: exactly half of each.
    assert living(9) == {"a": 5, "b": 3, "c": 1}
    # Ten: 5.56, 3.33 and 1.11; the tenth goes to the largest remainder.
    assert living(10) == {"a": 6, "b": 3, "c": 1}
    # Three: 1.67, 1.00 and 0.33; a and c tie nowhere, a has the largest remainder.
    assert living(3) == {"a": 2, "b": 1, "c": 0}
    # One: 0.56, 0.33, 0.11.
    assert living(1) == {"a": 1, "b": 0, "c": 0}


def test_two_homes_alike_share_an_odd_person_in_identity_order():
    routine = town_routine()
    dwelling = routine.use_classes["residential"].dwelling_floor_area_mm2
    homes = [
        SimpleNamespace(identity=name, use_class="residential", floor_area_mm2=2 * dwelling)
        for name in ("z", "m", "b")
    ]
    policy = {**routine.policy, "town_people_default": 4}
    assert _people_living(homes, dataclasses.replace(routine, policy=policy)) == {
        "b": 2,
        "m": 1,
        "z": 1,
    }


def test_a_town_made_before_keeps_the_routine_its_receipt_pins_and_its_people(monkeypatch):
    before = dict(society_catalogs.TOWN_ROUTINE_VERSIONS_BEFORE_FLOOR_AREA)
    with monkeypatch.context() as earlier:
        # A town made when towns were made under the earlier routine.
        earlier.setattr(society_catalogs, "TOWN_ROUTINE_VERSIONS", before)
        made = compose_generated_world(town_recipe("small_town"), "world:generated:made-before")
    receipt = json.loads(json.dumps(made.receipt))
    assert receipt["arrival_routine"]["catalog_versions"] == before
    # Peopled today, when a new town is made under another routine.
    assert town_routine().binding()["catalog_versions"] != before
    routine = town_routine_of(receipt)
    assert routine.binding() == receipt["arrival_routine"]
    place = walking_surfaces_place("place:made-before", made.records, routine)
    lived = _homes(place)
    # Two people a home, whatever its floor, as that routine's use class states.
    assert set(lived.values()) == {
        _entries("society-use-class.v2.json")["residential"]["resident_capacity"]
    }
    assert place_residents(place) == 2 * len(lived)
    assert people_frame(place, routine)["population"] == 2 * len(lived)
    # The same records under today's routine would be other people: the control.
    assert place_residents(walking_surfaces_place("p", made.records, town_routine())) != 2 * len(
        lived
    )


@pytest.mark.parametrize("world", load_arrival_worlds({}), ids=lambda world: world.key)
def test_an_arrival_town_is_the_same_town_under_either_routine_with_other_people(
    world, monkeypatch
):
    """A new guest's copy of an arrival world is composed in their workspace, so it is made under
    the routine a new town is made under. Its streets and buildings are the ones it had: the same
    seed and candidate, the same records and the same input digest for every tile, so nothing is
    baked again. Its people are the routine's: two a home before, the policy's number now."""
    made = {}
    for name, versions in (
        ("before", dict(society_catalogs.TOWN_ROUTINE_VERSIONS_BEFORE_FLOOR_AREA)),
        ("now", dict(society_catalogs.TOWN_ROUTINE_VERSIONS)),
    ):
        with monkeypatch.context() as under:
            under.setattr(society_catalogs, "TOWN_ROUTINE_VERSIONS", versions)
            made[name] = compose_specified_world(world.recipe, world.values, world.world_id)
    before, now = made["before"].receipt, made["now"].receipt
    assert before["arrival_routine"] != now["arrival_routine"]
    for key in ("seed", "candidate", "refused_candidates", "tiles", "output_digest", "grammar"):
        assert before[key] == now[key], key
    composer = composer_module(now["composer"]["key"], now["composer"]["version"])
    assert composer.tile_inputs(before) == composer.tile_inputs(now)
    assert len(composer.tile_inputs(now)) == len(now["tiles"]) > 0
    people = {
        name: place_residents(
            walking_surfaces_place("p", made[name].records, town_routine_of(made[name].receipt))
        )
        for name in made
    }
    homes = sum(
        1
        for dest in walking_surfaces_place("p", made["before"].records, town_routine_of(before))[
            "destinations"
        ]
        if dest["resident_capacity"]
    )
    assert people["before"] == 2 * homes
    assert people["now"] == _entries("society-policy.v3.json")["town_people_default"]["value"]


def test_a_receipt_from_before_receipts_pinned_a_routine_names_the_earlier_one():
    routine = town_routine_of({"composer": {"key": "city-grammar-town", "version": 1}})
    assert routine.binding()["catalog_versions"] == dict(
        society_catalogs.TOWN_ROUTINE_VERSIONS_BEFORE_FLOOR_AREA
    )


def test_a_receipt_whose_routine_these_catalogs_do_not_hold_is_refused():
    pinned = dict(town_routine().binding())
    pinned["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="names a living routine these catalogs differ from"):
        town_routine_of({"arrival_routine": pinned})


def test_the_people_a_draft_shows_are_the_people_the_town_starts_with(monkeypatch):
    """What a person is shown before a town is made counts the people under the routine the town
    is made under: today's, and for a town made as towns were made before, that one's."""
    world_id = "world:sample:floor-area"
    today = compute_sample("small_town", {}, world_id)
    assert today["status"] == "sampled"
    assert today["people"] == _entries("society-policy.v3.json")["town_people_default"]["value"]
    with monkeypatch.context() as earlier:
        earlier.setattr(
            society_catalogs,
            "TOWN_ROUTINE_VERSIONS",
            dict(society_catalogs.TOWN_ROUTINE_VERSIONS_BEFORE_FLOOR_AREA),
        )
        before = compute_sample("small_town", {}, world_id)
    homes = next(row["count"] for row in before["premises"] if row["key"] == "residential")
    # Two a premises of homes that has a door, as that routine's use class states: never more
    # than two for each premises of homes the records state.
    assert 0 < before["people"] <= 2 * homes and before["people"] % 2 == 0
    assert before["people"] != today["people"]


def _use_class(key: str, **changes: Any) -> dict[str, Any]:
    stated = dict(_entries("society-use-class.v3.json")[key])
    stated.update(changes)
    return {name: value for name, value in stated.items() if name not in ("key", "licence")}


@pytest.mark.parametrize(
    ("key", "changes"),
    [
        # A home that states no floor area for a dwelling.
        ("residential", {"dwelling_floor_area_mm2": 0}),
        # A shop that states one.
        ("bakery", {"dwelling_floor_area_mm2": 50_000_000}),
    ],
)
def test_exactly_a_home_states_the_floor_area_a_dwelling_takes(key: str, changes: dict[str, Any]):
    check = society_catalogs.SCHEMAS[("society-use-class", 3)].entry_check
    assert check is not None
    check(key, _use_class(key))
    with pytest.raises(CatalogError, match="exactly a home states the floor area"):
        check(key, _use_class(key, **changes))
