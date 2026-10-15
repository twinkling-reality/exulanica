"""A made town's buildings changed by a person: removed, taller or lower, by the grammar's stages.

The town is the small town recipe composed for a fixed world id, so its seed and records are the
same on every run. Expected figures are read from the records the grammar makes, never retyped.
"""

from __future__ import annotations

import pytest
from exulanica.grammar.errors import GrammarError
from exulanica.grammar.grammars.city import city_grammar, city_grammar_with
from exulanica.grammar.grammars.city.document import document_bytes
from exulanica.grammar.grammars.city.facade import FacadeRecord
from exulanica.grammar.grammars.city.generation import massing as massing_stage
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.landform import level_land
from exulanica.grammar.records import canonical_record
from exulanica.world.composers.city_grammar_town import (
    compose,
    records,
    records_with,
    tile_documents,
)
from exulanica.world.site_parts import PartChange, PartChangeRefused
from exulanica.world.town_parts import (
    building_changes,
    people_of_building,
    premises_taken,
    storeys_refusal,
    town_buildings,
)
from exulanica.world.world_recipes import town_recipe

WORLD = "world:generated:00000000-0000-4000-8000-00000000c1a5"


@pytest.fixture(scope="module", name="town")
def _town():  # type: ignore[no-untyped-def]
    return compose(town_recipe("small_town"), WORLD)


def _by_identity(found):  # type: ignore[no-untyped-def]
    return {getattr(r, "identity", None): canonical_record(r) for r in found}


def _touch(a, b) -> bool:  # type: ignore[no-untyped-def]
    return (
        a.min_x_mm <= b.max_x_mm
        and b.min_x_mm <= a.max_x_mm
        and a.min_y_mm <= b.max_y_mm
        and b.min_y_mm <= a.max_y_mm
    )


def _buildings(found):  # type: ignore[no-untyped-def]
    return {r.identity: r for r in found if isinstance(r, MassingRecord)}


def _owner(record, facades):  # type: ignore[no-untyped-def]
    """The building a record follows from, where it names one directly or through its facade."""
    owner = getattr(record, "building_identity", None)
    if owner is None and getattr(record, "facade_identity", None) in facades:
        owner = facades[record.facade_identity]
    return owner


def _changed_owners(before, after):  # type: ignore[no-untyped-def]
    old, new = _by_identity(before), _by_identity(after)
    facades = {
        r.identity: r.building_identity for r in (*before, *after) if isinstance(r, FacadeRecord)
    }
    changed = (set(old) ^ set(new)) | {i for i in set(old) & set(new) if old[i] != new[i]}
    every = {getattr(r, "identity", None): r for r in (*before, *after)}
    return {_owner(every[i], facades) for i in changed} - {None}


def _with_a_party_wall(found):  # type: ignore[no-untyped-def]
    """A building with a neighbour across a party wall."""
    for record in found:
        if isinstance(record, FacadeRecord) and record.exposure == "party_wall":
            return _buildings(found)[record.building_identity]
    raise AssertionError("the small town has no party wall")


def test_no_change_regenerates_the_town_byte_for_byte(town):
    made = records(town.receipt)
    assert made == tuple(town.records)
    assert records_with(town.receipt, {}) == made
    assert city_grammar_with(5, {}) is city_grammar(5)
    # A change naming no building of this town runs the changed stage and changes nothing.
    stranger = {"00000000-0000-5000-8000-000000000000": BuildingChange(removed=True)}
    assert records_with(town.receipt, stranger) == made
    # Every tile document, the bytes a bake is made from, is the same.
    assert [document_bytes(d) for d in tile_documents(town.receipt, made)] == [
        document_bytes(d)
        for d in tile_documents(town.receipt, records_with(town.receipt, stranger))
    ]


def test_a_town_on_its_land_takes_building_changes_by_the_same_massing_stage():
    changes = {"00000000-0000-5000-8000-000000000000": BuildingChange(storeys=3)}
    on_land = city_grammar_with(6, land=level_land())
    changed = city_grammar_with(6, changes, land=level_land())
    assert [s.stage_id for s in changed.stages] == [s.stage_id for s in on_land.stages]
    massing = [s for s in changed.stages if s.stage_id == massing_stage.STAGE_V3.stage_id]
    assert [s.stage_id for s in on_land.stages if s is massing_stage.STAGE_V3] == [
        massing_stage.STAGE_V3.stage_id
    ]
    assert len(massing) == 1 and massing[0] is not massing_stage.STAGE_V3
    assert city_grammar_with(6, {}) is city_grammar(6)
    with pytest.raises(GrammarError):
        city_grammar_with(5, changes, land=level_land())


def test_a_removed_building_leaves_its_lot_and_only_its_neighbours_follow(town):
    made = records(town.receipt)
    building = _with_a_party_wall(made)
    removed = records_with(town.receipt, {building.identity: BuildingChange(removed=True)})
    assert removed != made
    assert building.identity not in _buildings(removed)
    assert building.parcel_identity in {r.identity for r in removed if isinstance(r, ParcelRecord)}
    assert not [
        r
        for r in removed
        if isinstance(r, PremisesRecord) and r.building_identity == building.identity
    ]
    neighbours = {
        other.identity
        for other in _buildings(made).values()
        if other.identity != building.identity and _touch(other.extent, building.extent)
    }
    owners = _changed_owners(made, removed)
    assert building.identity in owners
    assert owners - {building.identity} <= neighbours
    # A neighbour's party wall toward it is no longer one.
    walls = lambda found: {  # noqa: E731
        (r.building_identity, r.tier_ordinal, r.edge_ordinal): r.exposure
        for r in found
        if isinstance(r, FacadeRecord) and r.building_identity in neighbours
    }
    before, after = walls(made), walls(removed)
    assert any(before[k] == "party_wall" and after.get(k) != "party_wall" for k in before)
    # The changed records are whole tile documents: references close and every document reads.
    assert tile_documents(town.receipt, removed)


def _ranged(made, receipt):  # type: ignore[no-untyped-def]
    """A building whose lot allows more than one storey count, with that range."""
    for building in _buildings(made).values():
        counts = []
        for storeys in range(1, building.storeys + 4):
            try:
                records_with(receipt, {building.identity: BuildingChange(storeys=storeys)})
            except BuildingStoreysRefused:
                continue
            counts.append(storeys)
        if len(counts) > 1:
            return building, counts
    raise AssertionError("no building of the small town has a range of storeys")


def test_a_building_taller_or_lower_follows_its_premises_and_its_neighbours_walls(town):
    made = records(town.receipt)
    building, counts = _ranged(made, town.receipt)
    other = counts[0] if counts[0] != building.storeys else counts[-1]
    changed = records_with(town.receipt, {building.identity: BuildingChange(storeys=other)})
    assert _buildings(changed)[building.identity].storeys == other
    area = lambda found: sum(  # noqa: E731
        r.floor_area_mm2
        for r in found
        if isinstance(r, PremisesRecord) and r.building_identity == building.identity
    )
    assert area(changed) != area(made)
    neighbours = {
        o.identity
        for o in _buildings(made).values()
        if o.identity != building.identity and _touch(o.extent, building.extent)
    }
    assert _changed_owners(made, changed) - {building.identity} <= neighbours
    assert tile_documents(town.receipt, changed)


def test_a_storey_count_outside_the_lot_s_range_is_refused_in_words(town):
    made = records(town.receipt)
    building, counts = _ranged(made, town.receipt)
    with pytest.raises(BuildingStoreysRefused) as refused:
        records_with(town.receipt, {building.identity: BuildingChange(storeys=counts[-1] + 1)})
    assert (refused.value.fewest, refused.value.most) == (counts[0], counts[-1])
    said = storeys_refusal(refused.value)
    assert said.code == "part_storeys_refused"
    label = town_buildings(made)[0].label  # a label is the typology catalog's own words
    assert label
    assert str(said).startswith("Not taller: a ")
    assert str(said).endswith(f"has at most {counts[-1]} storeys.")


def test_the_buildings_name_their_premises_and_a_removal_takes_them(town):
    made = records(town.receipt)
    building = _with_a_party_wall(made)
    listed = {b.identity: b for b in town_buildings(made)}
    held = listed[building.identity].premises
    assert held
    removed = records_with(town.receipt, {building.identity: BuildingChange(removed=True)})
    assert premises_taken(made, removed, building.identity) == held
    unchanged = records_with(town.receipt, {})
    assert premises_taken(made, unchanged, building.identity) == ()


def test_people_are_found_by_the_premises_either_engine_names():
    state = {
        "people": {
            "premises": [{"subject_id": "city.premises:p1"}, {"subject_id": "city.premises:p2"}]
        },
        "inhabitants": [
            {
                "display_name": "Ada Lane 1",
                "resident": {
                    "home": {"premises": 0, "household": 0},
                    "job": None,
                    "role": {"key": "r", "label": "r"},
                },
            },
            {
                "display_name": "Bo Cole 2",
                "home": {"destination_id": "premises:p9"},
                "work": {
                    "destination_id": "premises:p1",
                    "shift_start_minute": 0,
                    "shift_minutes": 60,
                },
                "role": {"key": "r", "label": "r"},
            },
        ],
    }
    assert people_of_building(state, ("p1",)) == [("Ada Lane 1", "lives"), ("Bo Cole 2", "works")]
    assert people_of_building(state, ("p3",)) == []


def test_a_town_building_is_not_moved():
    with pytest.raises(PartChangeRefused) as refused:
        building_changes([PartChange("b", False, (1, 2), 0)])
    assert refused.value.code == "part_not_changeable"
    assert building_changes([PartChange("b", True), PartChange("c", False, storeys=3)]) == {
        "b": BuildingChange(removed=True),
        "c": BuildingChange(storeys=3),
    }
