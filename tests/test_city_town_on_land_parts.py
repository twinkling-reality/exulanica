"""A town on its land is not refused for one door or one tree its slope makes unfit.

City grammar version 6 stands each lot level at the highest its footway reaches along its frontage,
so a shop door at the low end of a long frontage on a climbing street would stand more than an
entrance's step above the footway under it, and a street tree beside a lot standing above its
footway would need a trunk clear higher than the street's range to hang its crown over that lot.
Each of these refused the whole town candidate, so whether a town stood on its land turned on its
land's noise. Version 6 lays such a door out as a shopfront, the shop entered by its next door along
the face, and lets no tree stand where its crown would not clear the ground, as where one would
crowd another. Each test is on a fixed seed that reaches its rule, and says so if it no longer does.
"""

from __future__ import annotations

import hashlib
from functools import cache

import pytest
from exulanica.grammar import generate
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.grammars.city import city_grammar_with
from exulanica.grammar.grammars.city.descriptor import (
    CITY_MIGRATION_PATHS,
    CITY_SURFACES,
    CITY_V5_SURFACE,
    CITY_V6_SURFACE,
)
from exulanica.grammar.grammars.city.facade import (
    ENTRANCE_SHAPE,
    EntranceRecord,
    FacadeRecord,
    GroundBayRecord,
)
from exulanica.grammar.grammars.city.generation import facade as facade_stage
from exulanica.grammar.grammars.city.generation import streetlife as streetlife_stage
from exulanica.grammar.grammars.city.generation.facade import building_shop_units
from exulanica.grammar.grammars.city.generation.tiles import city_records
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.streetlife import StreetTreeRecord
from exulanica.grammar.grammars.specified import derived_identity
from exulanica.grammar.landform import land_recipes, read_land_document
from exulanica.grammar.migration import ParameterMigration
from exulanica.world.world_recipes import read_specification, town_recipe

ROLLING = read_land_document(dict(next(r.land for r in land_recipes() if r.key == "rolling")))
#: A small town on rolling land whose first shop door at a frontage's low end would step 710 mm.
DOOR_SEED = hashlib.sha256(b"town-parts-rolling-7").hexdigest()
#: A small town on rolling land with a street tree whose crown would hang over a raised lot.
TREE_SEED = hashlib.sha256(b"town-parts-rolling-16").hexdigest()
#: The most an entrance's threshold steps above the footway under it, from its own shape.
STEP_MOST_MM = next(f.maximum for f in ENTRANCE_SHAPE.fields if f.name == "step_height_mm")


def _bindings():  # type: ignore[no-untyped-def]
    spec = read_specification(town_recipe("small_town").specification)
    migration = ParameterMigration.read(CITY_MIGRATION_PATHS[6])
    return migration.migrate(CITY_V5_SURFACE, CITY_V6_SURFACE, spec.bindings).bindings


def _generate(seed: str) -> tuple[object, ...]:
    return tuple(
        city_records(
            generate(
                city_grammar_with(6, land=ROLLING),
                seed=seed,
                subject_identity=derived_identity(seed),
                bindings=_bindings(),
            )
        )
    )


@cache
def _town(seed: str) -> tuple[object, ...]:
    return _generate(seed)


def _of(records, kind):  # type: ignore[no-untyped-def]
    return [record for record in records if isinstance(record, kind)]


def test_a_shop_door_the_slope_makes_too_high_is_a_window_and_the_town_stands():
    records = _town(DOOR_SEED)
    assert all(e.step_height_mm <= STEP_MOST_MM for e in _of(records, EntranceRecord))
    lots = {lot.identity: lot for lot in _of(records, ParcelRecord)}
    faces = _of(records, FacadeRecord)
    bays = _of(records, GroundBayRecord)
    opened_by_a_later_door = 0
    for building in _of(records, MassingRecord):
        own = [face for face in faces if face.building_identity == building.identity]
        identities = {face.identity for face in own}
        units = building_shop_units(
            lots[building.parcel_identity],
            own,
            [b for b in bays if b.facade_identity in identities],
        )
        for unit in units:
            # Every shop keeps a door, and a shop may begin with the window its door became.
            assert any(bay.bay_kind == "entrance" for bay in unit)
            opened_by_a_later_door += unit[0].bay_kind == "shopfront"
    assert opened_by_a_later_door > 0, (
        "no shop door here is a window: the seed no longer reaches it"
    )
    for shop in _of(records, PremisesRecord):
        assert shop.entrance_identities


def test_without_the_window_the_same_town_is_refused_for_its_door(monkeypatch):
    # The seed reaches the rule: with every shop door kept, the town is refused by its step.
    monkeypatch.setattr(facade_stage, "_shop_doors_within_a_step", lambda kinds, *_: kinds)
    with pytest.raises(InvalidRecordError, match="step_height_mm"):
        _generate(DOOR_SEED)


def test_a_street_tree_whose_crown_would_not_clear_the_ground_is_not_planted():
    # The town stands and keeps its other trees, each clear to a height within the street's range.
    spec = CITY_SURFACES[6].parameters.get("tree_trunk_clear_height_mm")
    trees = _of(_town(TREE_SEED), StreetTreeRecord)
    assert trees
    for tree in trees:
        crown = next(part for part in tree.parts if part.shape == "ellipsoid")
        assert spec.minimum <= crown.offset_z_mm <= spec.maximum


def test_without_the_skip_the_same_town_is_refused_for_its_tree(monkeypatch):
    monkeypatch.setattr(streetlife_stage, "admits", lambda *_args, **_narrowing: True)
    with pytest.raises(InvalidParameterError, match="tree_trunk_clear_height_mm"):
        _generate(TREE_SEED)
