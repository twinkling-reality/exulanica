"""A made town's building stood taller adds homes to the town and takes none from its neighbours;
the new homes stand empty and nobody moves house (``exulanica/world/society_city_place.py``,
``exulanica/world/society_walking_surfaces.py``).

Pure, on the small town composed under a fixed identity. What holds each claim, none of it the
code under the rule:

* the town as made, read as it always is (no ``made_records``), whose homes
  ``tests/test_town_homes_by_floor_area.py`` holds to the catalogs and the records' floor areas;
* the catalogs' own JSON (the floor area a dwelling takes, the residents it houses, the people a
  new town starts with) and the changed premises records' own floor areas, with the made town's
  density worked here by exact fractions.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.world.composers import composer_module
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_city_place import town_homes
from exulanica.world.society_living import town_routine_of
from exulanica.world.society_walking_surfaces import (
    place_residents,
    town_head_count,
    walking_surfaces_place,
)
from exulanica.world.town_parts import premises_of, premises_taken, town_buildings
from exulanica.world.town_people import people_frame
from exulanica.world.world_recipes import town_recipe

from living_town_support import per_town_routine

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "assets" / "catalogs" / "society"
IDENTITY = "world:generated:00000000-0000-4000-8000-000000000003"
PLACE = "place:homes-after-change"


def _entries(name: str) -> dict[str, dict[str, Any]]:
    stated = json.loads((CATALOGS / name).read_text(encoding="utf-8"))
    return {entry["key"]: entry for entry in stated["entries"]}


@per_town_routine
def _made() -> Any:
    return compose_generated_world(town_recipe("small_town"), IDENTITY)


def _routine():
    return town_routine_of(_made().receipt)


def _with(changes: dict[str, BuildingChange]) -> tuple[object, ...]:
    receipt = _made().receipt
    composer = receipt["composer"]
    return composer_module(composer["key"], composer["version"]).records_with(receipt, changes)


def _homes(place: dict[str, Any]) -> dict[str, int]:
    """Each premises of homes of a place with how many people live there, by record identity."""
    return {
        dest["subject_id"].split(":", 1)[1]: dest["resident_capacity"]
        for dest in place["destinations"]
        if dest["use_class"] == "residential"
    }


def _floors(records) -> dict[str, int]:
    return {r.identity: r.floor_area_mm2 for r in records if isinstance(r, PremisesRecord)}


def _density(made_place: dict[str, Any]) -> Fraction:
    """The made town's people over the places its homes hold, from the catalogs' JSON."""
    uses = _entries("society-use-class.v3.json")
    dwelling = uses["residential"]["dwelling_floor_area_mm2"]
    residents = uses["residential"]["resident_capacity"]
    budget = _entries("society-policy.v3.json")["town_people_default"]["value"]
    floors = _floors(_made().records)
    places = sum(max(1, floors[i] // dwelling) * residents for i in _homes(made_place))
    assert place_residents(made_place) == budget
    return Fraction(budget, places)


def _held(floor_area: int) -> int:
    uses = _entries("society-use-class.v3.json")
    dwelling = uses["residential"]["dwelling_floor_area_mm2"]
    return max(1, floor_area // dwelling) * uses["residential"]["resident_capacity"]


def _half_up(value: Fraction) -> int:
    return int(value + Fraction(1, 2))


def _a_home_building(storeys: int) -> tuple[Any, tuple[object, ...]]:
    """The first building of the made town that houses people and that its lot lets stand
    ``storeys`` from its own count, with the records that change makes."""
    lived = _homes(walking_surfaces_place(PLACE, _made().records, _routine()))
    for building in town_buildings(_made().records):
        if not any(lived.get(premises) for premises in building.premises):
            continue
        try:
            change = {building.identity: BuildingChange(storeys=building.storeys + storeys)}
            return building, _with(change)
        except BuildingStoreysRefused:
            continue
    raise AssertionError(f"no lived-in building of the town stands {storeys:+d} storeys")


def test_a_taller_building_adds_homes_and_takes_none_from_its_neighbours():
    routine = _routine()
    made = walking_surfaces_place(PLACE, _made().records, routine)
    building, taller = _a_home_building(+1)
    after = walking_surfaces_place(PLACE, taller, routine, made_records=_made().records)
    # Read as before the rule: the budget shares the town's people out again, so the taller
    # building's gain is taken from its neighbours. The control.
    shared = _homes(walking_surfaces_place(PLACE, taller, routine))
    before, now = _homes(made), _homes(after)
    assert sum(shared.values()) == sum(before.values())
    assert any(before[i] > shared[i] for i in before if i not in building.premises)
    # Every premises the change leaves alone houses exactly the people it housed as made.
    floors, made_floors = _floors(taller), _floors(_made().records)
    untouched = {i for i in before if floors.get(i) == made_floors[i]}
    assert untouched and {i: now[i] for i in untouched} == {i: before[i] for i in untouched}
    # The taller premises house their new floor's places at the made town's density, never fewer.
    density = _density(made)
    grown = set(now) - untouched
    assert grown and grown <= set(building.premises)
    for identity in grown:
        assert floors[identity] > made_floors[identity]
        expected = max(before[identity], _half_up(_held(floors[identity]) * density))
        assert now[identity] == expected > before[identity]
    # The town gains those homes; its head count stays the made town's, so the new homes stand
    # empty and nobody moves house.
    added = sum(now[i] - before[i] for i in grown)
    assert place_residents(after) == place_residents(made) + added
    assert town_head_count(after, _made().records, routine) == place_residents(made)
    count = town_head_count(after, _made().records, routine)
    frame = people_frame(after, routine, population=count)
    assert frame["population"] == place_residents(made)
    assert sum(row["homes"] for row in frame["premises"]) == place_residents(made) + added


def test_a_removed_building_s_homes_are_gone_and_nobody_else_gains():
    routine = _routine()
    made = walking_surfaces_place(PLACE, _made().records, routine)
    before = _homes(made)
    [building] = [
        b
        for b in town_buildings(_made().records)
        if any(before.get(premises) for premises in b.premises)
    ][:1]
    removed = _with({building.identity: BuildingChange(removed=True)})
    after = walking_surfaces_place(PLACE, removed, routine, made_records=_made().records)
    now = _homes(after)
    gone = {i for i in before if i in building.premises}
    assert gone and not gone & set(now)
    assert now == {i: before[i] for i in before if i not in gone}
    housed_there = sum(before[i] for i in gone)
    assert place_residents(after) == place_residents(made) - housed_there
    # The head count is the made town's at most the homes left: every home left is lived in.
    assert town_head_count(after, _made().records, routine) == place_residents(after)


def test_a_lower_building_never_houses_more_than_it_did():
    routine = _routine()
    made = walking_surfaces_place(PLACE, _made().records, routine)
    building, lower = _a_home_building(-1)
    after = walking_surfaces_place(PLACE, lower, routine, made_records=_made().records)
    before, now = _homes(made), _homes(after)
    floors, made_floors = _floors(lower), _floors(_made().records)
    density = _density(made)
    for identity in before:
        if floors[identity] == made_floors[identity]:
            assert now[identity] == before[identity]
        else:
            assert identity in building.premises and floors[identity] < made_floors[identity]
            expected = min(before[identity], _half_up(_held(floors[identity]) * density))
            assert now[identity] == expected <= before[identity]
    assert town_head_count(after, _made().records, routine) == min(
        place_residents(made), place_residents(after)
    )


def test_changes_that_leave_every_premises_alone_read_the_town_as_made():
    """Read with itself as the town as made, the town is the same place document, byte for byte,
    as it is read with none: every premises houses the people it housed as made."""
    routine = _routine()
    records = _made().records
    made = walking_surfaces_place(PLACE, records, routine)
    again = walking_surfaces_place(PLACE, records, routine, made_records=records)
    assert canonical_json(again) == canonical_json(made)
    assert town_head_count(made, None, routine) is None
    assert town_head_count(again, records, routine) == place_residents(made)


def test_town_homes_are_the_homes_the_changed_town_s_place_gives_each_premises():
    """What a lowering is refused by (``world_parts``): the homes each premises holds as the
    changes leave the town, read from the place the society reads."""
    routine, made = _routine(), _made().records
    made_homes = _homes(walking_surfaces_place(PLACE, made, routine))
    for building in town_buildings(made):
        try:
            lower = _with({building.identity: BuildingChange(storeys=building.storeys - 1)})
        except BuildingStoreysRefused:
            continue
        kept = set(premises_of(lower, building.identity)) - set(
            premises_taken(made, lower, building.identity)
        )
        homes = town_homes(lower, made, routine)
        if any(homes.get(i, 0) < made_homes.get(i, 0) for i in kept):
            break
    else:
        raise AssertionError("no lowering of the town keeps a premises that loses homes")
    place = walking_surfaces_place(PLACE, lower, routine, made_records=made)
    assert homes == {i: n for i, n in _homes(place).items() if n}
    # A lower building never houses more than it did, and its neighbours house what they did.
    assert all(homes.get(i, 0) <= made_homes.get(i, 0) for i in kept)
    others = set(made_homes) - set(premises_of(made, building.identity))
    assert {i: homes.get(i, 0) for i in others} == {i: made_homes[i] for i in others}
