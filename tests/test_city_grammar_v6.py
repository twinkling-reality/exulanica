"""City grammar version 6: a town laid on its land.

Version 6 runs the districts stage at its version 2 (the city's extent from its parameters), the
streets stage on the land (each junction level at its node's level, each street a ramp between its
mouths), the parcels stage at its version 3 (each lot at the highest its footway reaches along its
frontage), the terrain stage on the land after the parcels (graded for them, at a 1 m cell), the
facade stage at its version 3 (each door's step read at its footway) and street life at its
version 4. These tests hold what it adds, measured from the records and from the town's walking
place rather than from the generator's own arithmetic; that its figures are their sources'; that
it is generated only with its land and named by no request; and that a version 3 to 5 facade
validates exactly as before.
"""

from __future__ import annotations

import dataclasses
from functools import cache
from pathlib import Path

import pytest
from exulanica.grammar import generate
from exulanica.grammar.errors import GrammarError, InvalidRecordError, UnregisteredGrammarError
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.grammars.city import CITY_GRAMMARS, city_grammar, city_grammar_with
from exulanica.grammar.grammars.city import facade as facade_records
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.grammar.grammars.city.descriptor import (
    CITY_GENERATING_VERSIONS,
    CITY_LAND_VERSIONS,
    CITY_MIGRATION_PATHS,
    CITY_SURFACES,
    CITY_V5_SURFACE,
    CITY_V6_SURFACE,
)
from exulanica.grammar.grammars.city.document import (
    document_bytes,
    read_tile_document,
    validate_city_document,
)
from exulanica.grammar.grammars.city.facade import (
    ENTRANCE_SHAPE,
    FACADE_SHAPE,
    EntranceRecord,
    FacadeRecord,
)
from exulanica.grammar.grammars.city.generation.tiles import (
    check_city_reference_closure,
    city_records,
    tile_document,
)
from exulanica.grammar.grammars.city.land import (
    door_of,
    footway_surface_at,
    frontage_top,
    street_profiles,
    town_land_plan,
)
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.streets import (
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.specified import GENERATED_LOD, derived_identity, specification
from exulanica.grammar.landform import (
    BANK_GRADE_PERMILLE,
    CUT_FILL_MOST_MM,
    land_recipes,
    level_land,
    read_land_document,
)
from exulanica.grammar.migration import ParameterMigration
from exulanica.grammar.shapes import validate_record
from exulanica.world.composers import seed_candidate
from exulanica.world.society_city_place import _Kerb
from exulanica.world.society_living import town_routine
from exulanica.world.society_place import STEP_LIMIT_MM
from exulanica.world.society_walking_surfaces import place_residents, walking_surfaces_place
from exulanica.world.world_recipes import read_specification, town_recipe

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "city-v2" / "tile-document.json"
WORLD = "world:generated:city-grammar-v6"
#: The figures version 6 declares fixed, each with the source a test holds it to.
GRADING_FIGURES = (
    "bank_grade_permille",
    "cut_fill_most_mm",
    "footway_station_spacing_mm",
    "walking_step_mm",
)
LANDS = {"level": level_land()} | {
    recipe.key: read_land_document(dict(recipe.land)) for recipe in land_recipes()
}


def _bindings():  # type: ignore[no-untyped-def]
    spec = read_specification(town_recipe("small_town").specification)
    migration = ParameterMigration.read(CITY_MIGRATION_PATHS[6])
    return migration.migrate(CITY_V5_SURFACE, CITY_V6_SURFACE, spec.bindings).bindings


@cache
def _town(land: str) -> tuple[str, tuple[object, ...]]:
    """The small town on ``land``: the first of its recipe's candidates the land admits, as a
    composer tries them."""
    recipe = town_recipe("small_town")
    refusals = []
    for candidate in range(recipe.candidates):
        seed = seed_candidate(recipe, WORLD, candidate)
        try:
            generation = generate(
                city_grammar_with(6, land=LANDS[land]),
                seed=seed,
                subject_identity=derived_identity(seed),
                bindings=_bindings(),
            )
        except InvalidRecordError as refusal:
            refusals.append(str(refusal))
            continue
        return seed, tuple(city_records(generation))
    raise AssertionError(f"no candidate stands on {land}: {refusals}")


def _of(records, kind):  # type: ignore[no-untyped-def]
    return [record for record in records if isinstance(record, kind)]


@cache
def _place(land: str):  # type: ignore[no-untyped-def]
    _seed, records = _town(land)
    return walking_surfaces_place(f"generated:city-v6-{land}", records, routine=town_routine())


def _carried(document):  # type: ignore[no-untyped-def]
    return [record for entry in document.grammars for record in (*entry.owned, *entry.halo)]


def _terrain_at(records, x: int, y: int) -> int:  # type: ignore[no-untyped-def]
    tile_x, tile_y = x // TILE_SIZE_MM, y // TILE_SIZE_MM
    [patch] = [r for r in _of(records, TerrainRecord) if (r.tile_x, r.tile_y) == (tile_x, tile_y)]
    i = (x - tile_x * TILE_SIZE_MM) // patch.cell_mm
    j = (y - tile_y * TILE_SIZE_MM) // patch.cell_mm
    return patch.height_mm[j * patch.samples_per_side + i]


# ---------------------------------------------------------------------------------------------
# The descriptor: what version 6 declares, and where each figure comes from


def test_version_6_declares_version_5s_parameters_less_relief_and_four_grading_figures():
    was = {spec.name: spec for spec in CITY_V5_SURFACE.parameters.parameters}
    now = {spec.name: spec for spec in CITY_V6_SURFACE.parameters.parameters}
    assert set(was) - set(now) == {"terrain_relief_mm"}
    assert set(now) - set(was) == set(GRADING_FIGURES)
    assert len(now) == 111
    changed = sorted(name for name in set(was) & set(now) if was[name] != now[name])
    assert changed == [
        "city_extent_x_mm",
        "city_extent_y_mm",
        "terrain_cell_mm",
        "threshold_height_mm",
    ]
    for name in ("city_extent_x_mm", "city_extent_y_mm"):
        # The districts stage reads the extent now, since the terrain runs after the parcels.
        assert (was[name].stage, now[name].stage) == ("terrain", "districts")
        assert dataclasses.replace(now[name], stage="terrain", basis=was[name].basis) == was[name]
    cell = now["terrain_cell_mm"]
    assert dataclasses.replace(cell, basis=was["terrain_cell_mm"].basis) == was["terrain_cell_mm"]
    threshold = now["threshold_height_mm"]
    assert (was["threshold_height_mm"].maximum, threshold.maximum) == (180, 600)


def test_the_grading_figures_and_the_threshold_bound_equal_their_sources():
    specs = CITY_V6_SURFACE.parameters
    fixed = {name: (specs.get(name).minimum, specs.get(name).maximum) for name in GRADING_FIGURES}
    station = town_routine().policy["footway_station_spacing_mm"]
    assert fixed == {
        "bank_grade_permille": (BANK_GRADE_PERMILLE, BANK_GRADE_PERMILLE),
        "cut_fill_most_mm": (CUT_FILL_MOST_MM, CUT_FILL_MOST_MM),
        "footway_station_spacing_mm": (station, station),
        "walking_step_mm": (STEP_LIMIT_MM, STEP_LIMIT_MM),
    }
    [step] = [field for field in ENTRANCE_SHAPE.fields if field.name == "step_height_mm"]
    assert specs.get("threshold_height_mm").maximum == step.maximum


def test_the_version_6_migration_carries_every_version_5_binding_but_the_relief():
    spec = read_specification(town_recipe("small_town").specification)
    migration = ParameterMigration.read(CITY_MIGRATION_PATHS[6])
    migrated = migration.migrate(CITY_V5_SURFACE, CITY_V6_SURFACE, spec.bindings)
    bound = {name for binding in spec.bindings for name, _value in binding.values}
    carried = {name for binding in migrated.bindings for name, _value in binding.values}
    assert carried == bound - {"terrain_relief_mm"}
    assert [(dropped.name, dropped.value) for dropped in migrated.dropped] == [
        ("terrain_relief_mm", 0)
    ]


# ---------------------------------------------------------------------------------------------
# Generated only with its land: no request names it


def test_version_6_is_generated_and_read_but_never_registered_or_requested():
    assert 6 in CITY_GENERATING_VERSIONS and CITY_LAND_VERSIONS == (6,)
    assert 6 not in CITY_GRAMMARS
    with pytest.raises(UnregisteredGrammarError):
        specification("city", 6, ())
    # What reads a version 6 tile is given version 6 on level land.
    assert city_grammar(6).key.grammar_version == 6


@pytest.mark.parametrize("version", sorted(CITY_GRAMMARS))
def test_a_level_version_refuses_land_by_name(version):
    with pytest.raises(GrammarError, match="stands on level ground"):
        city_grammar_with(version, land=LANDS["coast"])
    assert city_grammar_with(version) is CITY_GRAMMARS[version]


def test_land_too_steep_for_a_town_is_refused_by_name():
    steep = read_land_document(
        {
            "profile": "exulanica.landform/v1",
            "ground_mm": 20000,
            "features": [{"id": "tilt", "kind": "tilt", "side": "east", "grade_permille": 120}],
        }
    )
    seed = seed_candidate(town_recipe("small_town"), WORLD, 0)
    with pytest.raises(InvalidRecordError, match=r"\[landform_"):
        generate(
            city_grammar_with(6, land=steep),
            seed=seed,
            subject_identity=derived_identity(seed),
            bindings=_bindings(),
        )


# ---------------------------------------------------------------------------------------------
# A town on its land


@pytest.mark.parametrize("land", ["level", "coast", "upland"])
def test_a_town_on_its_land_validates_closes_and_is_walked_as_on_level_land(land):
    seed, records = _town(land)
    catalogs = load_city_catalogs(grammar_version=6)
    tiles = sorted({(r.tile_x, r.tile_y) for r in _of(records, TerrainRecord)})
    documents = []
    for tile_x, tile_y in tiles:
        document = tile_document(
            list(records),
            seed=seed,
            subject_identity=derived_identity(seed),
            catalogs=catalogs,
            tile_x=tile_x,
            tile_y=tile_y,
            lod=GENERATED_LOD,
            grammar_version=6,
        )
        validate_city_document(document, catalogs=catalogs)
        documents.append(document)
    check_city_reference_closure(documents)
    place = _place(land)
    # The land adds nothing the walking place cannot read: no corner, door or footway refused.
    assert place["unsupported"] == _place("level")["unsupported"]
    assert place_residents(place) == place_residents(_place("level")) > 0
    if land != "level":
        heights = {node.z_mm for node in _of(records, StreetNodeRecord)}
        assert len(heights) > 1, "the land is not level"


@pytest.mark.parametrize("land", ["coast", "upland"])
def test_junctions_stand_level_and_streets_climb_only_between_their_mouths(land):
    _seed, records = _town(land)
    nodes = {node.identity: node for node in _of(records, StreetNodeRecord)}
    profiles = street_profiles(records)
    climbing = 0
    for segment in _of(records, StreetSegmentRecord):
        profile = profiles[segment.identity]
        axis = profile.axis
        for x, y, z in segment.centreline_mm:
            assert z == profile.at((x, y)[axis]), segment.identity
        for key in (segment.start_node_identity, segment.end_node_identity):
            node = nodes[key]
            assert profile.at((node.x_mm, node.y_mm)[axis]) == node.z_mm
        rise = abs(profile.high_level_mm - profile.low_level_mm)
        if rise:
            climbing += 1
            # Within one step over each footway station, less the rounding margin.
            station = town_routine().policy["footway_station_spacing_mm"]
            assert rise * station < STEP_LIMIT_MM * (profile.high_mm - profile.low_mm)
    assert climbing, "no street climbs"


@pytest.mark.parametrize("land", ["coast", "upland"])
def test_every_lot_stands_at_its_frontage_top_and_every_door_states_the_footway_under_it(land):
    _seed, records = _town(land)
    curbs = {curb.identity: curb for curb in _of(records, CurbEdgeRecord)}
    for lot in _of(records, ParcelRecord):
        ring, edge = lot.boundary_mm, lot.frontages[0].edge_ordinal
        frontage = (ring[edge], ring[(edge + 1) % len(ring)])
        assert lot.grade_elevation_mm == frontage_top(
            curbs[lot.frontages[0].curb_identity], frontage
        )
    steps = []
    for entrance in _of(records, EntranceRecord):
        if not entrance.approach_curb_identity:
            continue
        curb = curbs[entrance.approach_curb_identity[0]]
        under = footway_surface_at(curb, (entrance.threshold_x_mm, entrance.threshold_y_mm))
        assert entrance.step_height_mm == entrance.threshold_z_mm - under >= 0
        steps.append(entrance.step_height_mm)
    assert max(steps) > 0, "every door meets a level footway"


@pytest.mark.parametrize("land", ["coast", "upland"])
def test_the_footway_is_read_as_the_walking_place_reads_it_on_climbing_kerbs(land):
    _seed, records = _town(land)
    segments = {segment.identity: segment for segment in _of(records, StreetSegmentRecord)}
    checked = 0
    for curb in _of(records, CurbEdgeRecord):
        line = curb.kerb_line_mm
        if len({z for *_xy, z in line}) == 1:
            continue
        kerb = _Kerb(curb, segments[curb.segment_identity])
        (ax, ay, _az), (bx, by, _bz) = line[0], line[-1]
        length = integer_sqrt((bx - ax) * (bx - ax) + (by - ay) * (by - ay))
        sign = 1 if curb.side == "left" else -1
        normal = (sign * -(by - ay), sign * (bx - ax))
        reach = curb.kerb_width_mm + curb.footway_width_mm
        for fraction in range(9):
            on = (ax + (bx - ax) * fraction // 8, ay + (by - ay) * fraction // 8)
            for out in (curb.kerb_width_mm // 2, reach // 2, reach, reach + 500):
                point = (on[0] + normal[0] * out // length, on[1] + normal[1] * out // length)
                squared, along = kerb.project(point)
                walked = kerb.surface_z(along, integer_sqrt(squared))
                assert footway_surface_at(curb, point) == walked, (curb.identity, point)
                checked += 1
    assert checked, "no kerb climbs"


@pytest.mark.parametrize("land", ["coast", "upland"])
def test_no_junction_holds_level_ground_where_a_street_has_begun_to_climb(land):
    """A junction's level pads reach across their street only as far as the mouths of the
    streets leaving it the other way: where a street is wider on one side than its crossing
    street's kerbs reach, a pad beyond that mouth would hold ground level that the crossing
    street's ramp has already raised, a lip no walk crosses."""
    _seed, records = _town(land)
    plan = town_land_plan(
        records, bank_grade_permille=BANK_GRADE_PERMILLE, cut_fill_most_mm=CUT_FILL_MOST_MM
    )
    junctions = [pad for pad in plan.pads if pad.id.startswith("junction")]
    assert junctions and plan.corridors
    for pad in junctions:
        x0, y0, x1, y1 = pad.rect_mm
        for ramp in plan.corridors:
            rx0, ry0, rx1, ry1 = ramp.rect_mm
            inside = max(x0, rx0) < min(x1, rx1) and max(y0, ry0) < min(y1, ry1)
            assert not inside, (pad.id, ramp.id)


@pytest.mark.parametrize("land", ["coast", "upland"])
def test_the_terrain_is_graded_at_a_metre_and_level_under_every_lot(land):
    _seed, records = _town(land)
    assert {patch.cell_mm for patch in _of(records, TerrainRecord)} == {1000}
    for lot in _of(records, ParcelRecord):
        xs = [x for x, _y in lot.boundary_mm]
        ys = [y for _x, y in lot.boundary_mm]
        # Strictly inside: a sample on a boundary is shared with the lot or street beside it.
        heights = {
            _terrain_at(records, x, y)
            for x in range(min(xs) // 1000 * 1000 + 1000, max(xs), 1000)
            for y in range(min(ys) // 1000 * 1000 + 1000, max(ys), 1000)
        }
        assert heights == {lot.grade_elevation_mm}, lot.identity
        assert door_of(lot)


# ---------------------------------------------------------------------------------------------
# The facade record reads the parameters of the version that wrote it


def test_every_version_a_facade_may_carry_names_a_parameter_surface():
    [field] = [field for field in FACADE_SHAPE.fields if field.name == "grammar_version"]
    assert set(range(field.minimum, field.maximum + 1)) <= set(CITY_SURFACES)


def test_a_stored_version_3_facade_validates_as_it_did_and_reads_back_to_its_bytes():
    data = FIXTURE.read_bytes()
    document = read_tile_document(data)
    facades = [record for record in _carried(document) if isinstance(record, FacadeRecord)]
    assert facades and {facade.grammar_version for facade in facades} == {3}
    for facade in facades:
        assert validate_record(facade, FACADE_SHAPE) is facade
    validate_city_document(document, catalogs=load_city_catalogs(grammar_version=3))
    assert document_bytes(document) == data


def test_a_facade_of_a_version_with_no_parameter_surface_is_refused_by_name(monkeypatch):
    facade = next(
        record
        for record in _carried(read_tile_document(FIXTURE.read_bytes()))
        if isinstance(record, FacadeRecord)
    )
    known = {version: CITY_SURFACES[version] for version in CITY_SURFACES if version != 3}
    monkeypatch.setattr(facade_records, "CITY_SURFACES", known)
    with pytest.raises(InvalidRecordError, match="no city grammar version 3 is known"):
        validate_record(facade, FACADE_SHAPE)


def test_a_door_above_one_step_is_a_version_6_facade_and_no_earlier_one():
    _seed, records = _town("upland")
    facades = _of(records, FacadeRecord)
    high = [
        facade
        for facade in facades
        if any(
            binding.name == "threshold_height_mm" and binding.value > STEP_LIMIT_MM
            for binding in facade.parameters
        )
    ]
    if not high:
        pytest.skip("this town on upland stands no door more than one step above its footway")
    for facade in high:
        assert validate_record(facade, FACADE_SHAPE) is facade
        with pytest.raises(GrammarError, match="threshold_height_mm"):
            validate_record(dataclasses.replace(facade, grammar_version=5), FACADE_SHAPE)
