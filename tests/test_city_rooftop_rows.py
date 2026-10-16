"""A rooftop row on city grammar version 6 keeps no object beyond a rooftop record's bound.

The massing stage places a flat roof's plant and tanks in a row along its top tier's middle line,
and a rooftop record states the clearance its object keeps from the tier's edges, at most 10 m. On
a tier deep and long enough, an object in the middle of the row keeps more than that from every
edge, and the record check refused the whole town candidate. Version 6, the version that lays a
town on its land, stands such a row nearer the south edge, where it keeps exactly the bound; a row
that keeps within it stands where it stood, and every earlier version places every row as before.
"""

from __future__ import annotations

import hashlib
from functools import cache

from exulanica.grammar import generate
from exulanica.grammar.grammars.city import city_grammar_with
from exulanica.grammar.grammars.city.catalogs import form_parts
from exulanica.grammar.grammars.city.descriptor import (
    CITY_MIGRATION_PATHS,
    CITY_V5_SURFACE,
    CITY_V6_SURFACE,
)
from exulanica.grammar.grammars.city.generation.massing import _place_row, parts_extent
from exulanica.grammar.grammars.city.generation.stage import entry
from exulanica.grammar.grammars.city.generation.tiles import city_records
from exulanica.grammar.grammars.city.massing import (
    ROOFTOP_SHAPE,
    MassingRecord,
    RooftopObjectRecord,
)
from exulanica.grammar.grammars.specified import derived_identity
from exulanica.grammar.landform import level_land
from exulanica.grammar.migration import ParameterMigration
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.world_recipes import read_specification, town_recipe

#: The most clearance a rooftop record states, from its own shape.
BOUND_MM = next(field.maximum for field in ROOFTOP_SHAPE.fields if field.name == "clearance_mm")
#: Eight plant units then four tanks: as many as a roof's row is ever asked for.
ROW = ["hvac_unit"] * 8 + ["water_tank"] * 4
#: A small town whose version 6 generation, on level land, has a flat roof deep and long enough that
#: its row's middle keeps more than the bound from every edge (found by search, and fixed so the
#: test never varies per run).
DEEP_ROOF_SEED = hashlib.sha256(b"rooftop-row-small_town-2").hexdigest()
#: A level small town (version 5) whose first candidate is refused for such a roof.
LEVEL_WORLD = "world:generated:town-land-sweep-5"


def _square(side_mm: int) -> tuple[tuple[int, int], ...]:
    return ((0, 0), (side_mm, 0), (side_mm, side_mm), (0, side_mm))


def _clearance(key: str) -> int:
    return entry("rooftop-object", key)["clearance_minimum_mm"]


def test_a_row_that_keeps_within_the_bound_stands_on_its_tiers_middle_line():
    ring = _square(15_000)
    placed, count = _place_row(ring, ROW, BOUND_MM)
    assert (placed, count) == _place_row(ring, ROW)
    assert {y for _key, _x, y, _kept in placed} == {7_500}


def test_a_row_on_a_tier_too_deep_and_long_keeps_no_object_beyond_the_bound():
    ring = _square(40_000)
    middle, count = _place_row(ring, ROW)
    assert max(kept for *_, kept in middle) > BOUND_MM  # what the record check refused
    placed, held_count = _place_row(ring, ROW, BOUND_MM)
    assert held_count == count
    # The same objects at the same places along the row, on one line nearer the south edge.
    assert [(key, x) for key, x, _y, _kept in placed] == [(key, x) for key, x, _y, _kept in middle]
    [line] = {y for _key, _x, y, _kept in placed}
    assert line < 20_000
    for key, _x, _y, kept in placed:
        assert _clearance(key) <= kept <= BOUND_MM
    # The class reaching least far south keeps exactly the bound from the south edge.
    reach = max(
        parts_extent(0, 0, 0, form_parts(entry("rooftop-object", key)["parts"])).min_y_mm
        for key in ROW
    )
    assert line + reach == BOUND_MM


@cache
def _deep_roof_town() -> tuple[object, ...]:
    spec = read_specification(town_recipe("small_town").specification)
    bindings = (
        ParameterMigration.read(CITY_MIGRATION_PATHS[6])
        .migrate(CITY_V5_SURFACE, CITY_V6_SURFACE, spec.bindings)
        .bindings
    )
    return tuple(
        city_records(
            generate(
                city_grammar_with(6, land=level_land()),
                seed=DEEP_ROOF_SEED,
                subject_identity=derived_identity(DEEP_ROOF_SEED),
                bindings=bindings,
            )
        )
    )


def test_a_version_6_town_with_a_deep_roof_stands_with_its_row_moved_south():
    records = _deep_roof_town()
    buildings = {r.identity: r for r in records if isinstance(r, MassingRecord)}
    rows: dict[str, set[int]] = {}
    moved = 0
    for obj in records:
        if not isinstance(obj, RooftopObjectRecord):
            continue
        assert _clearance(obj.object_class) <= obj.clearance_mm <= BOUND_MM
        ring = buildings[obj.building_identity].tiers[-1].ring_mm
        middle = (min(y for _x, y in ring) + max(y for _x, y in ring)) // 2
        rows.setdefault(obj.building_identity, set()).add(obj.y_mm)
        moved += obj.y_mm < middle
    assert moved > 0, "no row on this town's roofs was moved: the seed no longer reaches the rule"
    # A moved row stays one straight row.
    assert all(len(lines) == 1 for lines in rows.values())


def test_a_level_towns_deep_roof_is_refused_as_before():
    made = compose_generated_world(town_recipe("small_town"), LEVEL_WORLD)
    assert made.receipt["candidate"] == 1
    [refused] = made.receipt["refused_candidates"]
    assert refused["candidate"] == 0
    assert "city.rooftop_object.clearance_mm" in refused["refusal"]
