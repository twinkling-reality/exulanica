"""City grammar version 5: a district's street mix and use mix, and every surface dressed.

Version 5 runs the streets stage at its version 4, the massing, premises and vitrine stages at
their version 3 (premises before vitrine) and the material stage at its version 3. These tests hold
what it adds, measured from the records rather than from the generator's own arithmetic: which
streets are high streets and what the other cross streets are, the priority each junction gives,
typologies and shop uses drawn by weight, every ground band and the bare ground dressed; that its
descriptor, catalogs and migration agree with version 4 on everything it does not change; that a
version 5 tile owning a rounded corner whose follower it does not carry is refused by name; and
that the tessellator, which no longer asks a straight join for a follower it never reads, bakes
every corridor tile to the bytes it baked before (issue #85).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

import pytest
from exulanica.grammar import CascadeBinding
from exulanica.grammar.errors import GrammarError, InvalidRecordError
from exulanica.grammar.grammars.city import CITY_GRAMMAR_V5, city_grammar
from exulanica.grammar.grammars.city.catalogs import (
    CATALOG_DIRECTORY,
    entry_fields,
    load_city_catalogs,
)
from exulanica.grammar.grammars.city.descriptor import (
    CITY_MIGRATION_PATHS,
    CITY_V4_SURFACE,
    CITY_V5_SURFACE,
)
from exulanica.grammar.grammars.city.document import (
    TileDocument,
    document_bytes,
    validate_city_document,
)
from exulanica.grammar.grammars.city.facade import FacadeRecord, GroundBayRecord
from exulanica.grammar.grammars.city.generation import streets as generation_streets
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_LOD,
    CORRIDOR_SEED,
    CORRIDOR_TILES,
)
from exulanica.grammar.grammars.city.generation.facade import building_shop_units
from exulanica.grammar.grammars.city.generation.massing import weighted_typologies
from exulanica.grammar.grammars.city.generation.premises import shop_uses
from exulanica.grammar.grammars.city.generation.tiles import (
    city_records,
    generate_city,
    tile_document,
)
from exulanica.grammar.grammars.city.generation.vitrine import fitting_fitouts
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneRecord,
)
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord, StreetSegmentRecord
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.city.vitrine import VitrineRecord
from exulanica.grammar.migration import ParameterMigration

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
TSX = WEB / "node_modules" / ".bin" / "tsx"
CLI = WEB / "packages" / "loom-tess" / "src" / "node" / "cli.ts"

#: A town two tiles long and one deep, as the town specification makes one, with every street mix
#: and use mix value left to each test.
_TOWN = {
    "driving_side": "right",
    "city_extent_x_mm": 256_000,
    "city_extent_y_mm": 128_000,
    "terrain_relief_mm": 0,
    "block_length_mm": 90_000,
    "block_depth_mm": 56_000,
    "storey_band_low": 2,
    "storey_band_high": 4,
    "gutter_width_mm": 300,
    "front_setback_mm": 0,
    "memory_precinct_lots": 0,
}
_IDENTITY = "4f9f1f0e-0000-5000-8000-0000000000a5"
_EVEN = 500
_NEW = (
    "high_street_count",
    "cross_street_hierarchy",
    *(f"typology_weight_{key}_permille" for key in weighted_typologies()),
    *(f"ground_floor_use_weight_{key}_permille" for key in shop_uses()),
)

#: What each corridor tile baked to, container SHA-256, with the tessellator at 731066f8, the tree
#: before it stopped asking a straight join for its follower: the corridor specification at city
#: grammar versions 3 and 4, every tile. Measured by baking each document with that tree's
#: ``loom-tess`` CLI and with this one's: 10 of 10 identical.
_CORRIDOR_CONTAINERS = {
    (3, 0): "e2b09769bed8f8df4d3d7f321e7f52301476519e819139c9ae5666bd4b9eadf8",
    (3, 1): "459fa2e539a2f1c3455c80e40d32970e39611c037279739eb2660cb7dfd08bdb",
    (3, 2): "22b5c2870ce7fb636aabfbe504625b1d6070c1f6be2bcc3f13732cfda2b837e6",
    (3, 3): "613a58371ad84617299197a180f39124376bb7252085538193527eb5ab5db94d",
    (3, 4): "d43709781a896a072a0d5202d86dfd965c52f8c1bf1b243f4037034b4baaed7d",
    (4, 0): "f9fe52ccd2443f4a3b22de8a438797b05239603ab5e7d424f747867541b5ad03",
    (4, 1): "32f1ef0665103d887b534a85cb3fddeff6da06424f55a018bad2e0a9ab6c0dad",
    (4, 2): "8b35700741143970b6591b7e64fb536248e02f4caae9a71c5a9dae8548e7511e",
    (4, 3): "cb2d5fa76208586371aac8f5b310ace4bd748094e5817aebc224e2936f07fe20",
    (4, 4): "fb296e2b8018a7c2db932d952ba29ccc58b74c4ddb0d5ae7233641a9e996f91f",
}


def _mix(**overrides: object) -> dict[str, object]:
    """Version 5's values for the town: one high street, local cross streets and even weights,
    with ``overrides`` in their place."""
    values: dict[str, object] = {
        **_TOWN,
        "high_street_count": 1,
        "cross_street_hierarchy": "local_street",
        **{f"typology_weight_{key}_permille": _EVEN for key in weighted_typologies()},
        **{f"ground_floor_use_weight_{key}_permille": _EVEN for key in shop_uses()},
    }
    values.update(overrides)
    return values


def _generated(values: dict[str, object], version: int = 5) -> tuple[str, tuple[object, ...]]:
    """The first of eight seed candidates that generates, as the town composer tries them."""
    refusals = []
    for candidate in range(8):
        seed = f"{candidate:064x}"
        try:
            generation = generate_city(
                seed=seed,
                subject_identity=_IDENTITY,
                bindings=(CascadeBinding.of("city", values),),
                grammar_version=version,
            )
        except GrammarError as error:
            refusals.append(str(error))
            continue
        return seed, city_records(generation)
    raise AssertionError(f"no candidate generated: {refusals}")


@cache
def _town(key: str) -> tuple[str, tuple[object, ...]]:
    return _generated(json.loads(key))


def _records(**overrides: object) -> tuple[str, tuple[object, ...]]:
    return _town(json.dumps(_mix(**overrides), sort_keys=True))


def _of(records: tuple[object, ...], kind: type) -> list:
    return [record for record in records if isinstance(record, kind)]


def _lines(records: tuple[object, ...]) -> dict[tuple[str, int], set[str]]:
    """Each street line by its axis and position, with the hierarchies its segments state."""
    lines: dict[tuple[str, int], set[str]] = {}
    for segment in _of(records, StreetSegmentRecord):
        (x0, y0, _z0), (_x1, y1, _z1) = segment.centreline_mm[0], segment.centreline_mm[-1]
        key = ("x", y0) if y0 == y1 else ("y", x0)
        lines.setdefault(key, set()).add(segment.hierarchy)
    return lines


# -------------------------------------------------------------------------------------------------
# The descriptor, the catalogs and the migration


def test_version_5_declares_every_version_4_parameter_unchanged_and_fifteen_more():
    v4 = {spec.name: spec for spec in CITY_V4_SURFACE.parameters.parameters}
    v5 = {spec.name: spec for spec in CITY_V5_SURFACE.parameters.parameters}
    assert {name: v5[name] for name in v4} == v4
    assert sorted(set(v5) - set(v4)) == sorted(_NEW)
    assert len(v5) == 108
    for name in _NEW:
        assert v5[name].level == "district"
        assert v5[name].basis


def test_the_weights_are_one_per_terraced_typology_and_one_per_use_a_shop_can_take():
    catalogs = {catalog.catalog_id: catalog for catalog in load_city_catalogs(grammar_version=5)}
    typology = catalogs["typology"]
    terraced = sorted(
        entry.key
        for entry in typology.entries
        if entry_fields(typology, entry.key)["attachment"] == "terraced"
    )
    uses = catalogs["use-class"]
    signed = {
        entry.key for entry in uses.entries if entry_fields(uses, entry.key)["signage"] != "none"
    }
    taken = sorted(
        {
            use
            for key in terraced
            for use in entry_fields(typology, key)["ground_floor_uses"]  # type: ignore[union-attr]
            if use in signed
        }
    )
    assert weighted_typologies() == terraced
    assert shop_uses() == taken
    weights = [
        spec for spec in CITY_V5_SURFACE.parameters.parameters if spec.name.endswith("_permille")
    ]
    assert len(weights) == len(terraced) + len(taken) == 13
    for spec in weights:
        assert (spec.kind, spec.unit, spec.when_unset) == ("integer", "permille", "draw")
        assert (spec.minimum, spec.maximum) == (0, 1000)
    assert {spec.stage for spec in weights if spec.name.startswith("typology_")} == {"massing"}
    assert {spec.stage for spec in weights if spec.name.startswith("ground_floor_")} == {"premises"}


def test_the_cross_street_choices_are_the_hierarchies_ranked_below_the_high_street():
    hierarchy = next(
        catalog
        for catalog in load_city_catalogs(grammar_version=5)
        if catalog.catalog_id == "street-hierarchy"
    )
    rank = {entry.key: entry_fields(hierarchy, entry.key)["rank"] for entry in hierarchy.entries}
    spec = CITY_V5_SURFACE.parameters.get("cross_street_hierarchy")
    assert spec.vocabulary == "street-hierarchy"
    assert spec.options == tuple(
        sorted((key for key in rank if rank[key] > rank["high_street"]), key=rank.__getitem__)
    )
    count = CITY_V5_SURFACE.parameters.get("high_street_count")
    assert (count.minimum, count.maximum, count.stage) == (1, 8, "streets")


def test_version_5_runs_premises_before_vitrine_at_the_stage_versions_it_states():
    stages = [(stage.stage_id, stage.stage_version) for stage in CITY_GRAMMAR_V5.declared_stages]
    v4 = dict((stage.stage_id, stage.stage_version) for stage in city_grammar(4).declared_stages)
    assert [stage_id for stage_id, _version in stages].index("premises") < [
        stage_id for stage_id, _version in stages
    ].index("vitrine")
    moved = {stage_id: version for stage_id, version in stages if v4[stage_id] != version}
    assert moved == {"streets": 4, "massing": 3, "premises": 3, "vitrine": 3, "material": 3}


def test_the_material_edition_5_differs_from_4_in_what_the_tree_pit_soil_dresses_alone():
    v4 = json.loads(CATALOG_DIRECTORY.joinpath("material.v4.json").read_text(encoding="utf-8"))
    v5 = json.loads(CATALOG_DIRECTORY.joinpath("material.v5.json").read_text(encoding="utf-8"))
    assert (v4["catalog_version"], v5["catalog_version"]) == (4, 5)
    before = {entry["key"]: entry for entry in v4["entries"]}
    after = {entry["key"]: entry for entry in v5["entries"]}
    assert before.keys() == after.keys()
    moved = sorted(key for key in before if before[key] != after[key])
    assert moved == ["tree_pit_soil"]
    was, now = before["tree_pit_soil"], after["tree_pit_soil"]
    assert {field for field in was if was[field] != now[field]} == {"surfaces", "reason"}
    assert (was["surfaces"], now["surfaces"]) == (["tree_pit"], ["terrain", "tree_pit"])
    editions = {c.catalog_id: c.catalog_version for c in load_city_catalogs(grammar_version=4)}
    assert editions["material"] == 4
    editions = {c.catalog_id: c.catalog_version for c in load_city_catalogs(grammar_version=5)}
    assert editions["material"] == 5


def test_the_version_5_migration_carries_every_version_4_parameter_and_introduces_fifteen():
    migration = ParameterMigration.read(CITY_MIGRATION_PATHS[5])
    migration.check(CITY_V4_SURFACE, CITY_V5_SURFACE)
    document = json.loads(CITY_MIGRATION_PATHS[5].read_text(encoding="utf-8"))
    assert document["identity_policy"] == "rekeyed"
    assert sorted(row["target"] for row in document["introduced"]) == sorted(_NEW)
    assert document["removed"] == []
    bound = (CascadeBinding.of("city", {"block_length_mm": 90_000, "driving_side": "left"}),)
    assert migration.migrate(CITY_V4_SURFACE, CITY_V5_SURFACE, bound).bindings == bound


def test_the_vocabulary_names_every_street_version_5_can_lay():
    """The street mix moves street names between hierarchies: more high streets, narrow cross
    streets. The widest district the declared ranges admit, with every cross street it can make a
    high street and the rest narrow, still finds a distinct name for each."""
    spans = (
        CITY_V5_SURFACE.parameters.get("city_extent_x_mm").maximum,
        CITY_V5_SURFACE.parameters.get("city_extent_y_mm").maximum,
    )
    length = CITY_V5_SURFACE.parameters.get("block_length_mm").minimum
    depth = CITY_V5_SURFACE.parameters.get("block_depth_mm").minimum
    most = CITY_V5_SURFACE.parameters.get("high_street_count").maximum
    supply = generation_streets.street_names_by_hierarchy()
    for cross in CITY_V5_SURFACE.parameters.get("cross_street_hierarchy").options:
        demand = generation_streets.street_name_demand(
            *spans,
            length,
            depth,
            generation_streets.narrowest_reach("local_street"),
            high_street_count=most,
            cross_hierarchy=cross,
        )
        assert demand["high_street"] == most
        for hierarchy, wanted in demand.items():
            assert wanted <= len(supply[hierarchy]), (hierarchy, wanted)
        union = frozenset().union(*(supply[hierarchy] for hierarchy in demand))
        assert sum(demand.values()) <= len(union)


# -------------------------------------------------------------------------------------------------
# The street mix


def test_high_street_count_makes_the_cross_streets_nearest_the_middle_high_streets():
    """One high street is the street through the middle; the second is the western of the two
    equally near cross streets, the third the eastern one."""
    for count, high_cross in ((1, set()), (2, {83_000}), (3, {83_000, 173_000})):
        _seed, records = _records(high_street_count=count)
        lines = _lines(records)
        assert lines[("x", 64_000)] == {"high_street"}
        assert lines[("x", 8_000)] == lines[("x", 120_000)] == {"local_street"}
        crosses = {position for axis, position in lines if axis == "y"}
        assert crosses == {83_000, 173_000}
        for position in crosses:
            wanted = "high_street" if position in high_cross else "local_street"
            assert lines[("y", position)] == {wanted}, (count, position)


def test_a_count_above_the_streets_the_layout_lays_is_refused_by_name():
    with pytest.raises(GrammarError, match=r"high_street_count is bound to 4, outside \[1, 3\]"):
        generate_city(
            seed="0" * 64,
            subject_identity=_IDENTITY,
            bindings=(CascadeBinding.of("city", _mix(high_street_count=4)),),
            grammar_version=5,
        )


def test_a_high_cross_street_keeps_parking_and_a_narrow_one_carries_traffic_both_ways():
    _seed, records = _records(high_street_count=2, cross_street_hierarchy="narrow_street")
    segments = {record.identity: record for record in _of(records, StreetSegmentRecord)}
    catalog = next(
        c for c in load_city_catalogs(grammar_version=5) if c.catalog_id == "street-hierarchy"
    )
    lanes_of: dict[str, list[LaneRecord]] = {}
    for lane in _of(records, LaneRecord):
        lanes_of.setdefault(lane.segment_identity, []).append(lane)
    seen = Counter()
    for identity, segment in segments.items():
        fields = entry_fields(catalog, segment.hierarchy)
        low, high = fields["speed_limit_minimum_mm_s"], fields["speed_limit_maximum_mm_s"]
        assert low <= segment.speed_limit_mm_s <= high, segment.hierarchy  # type: ignore[operator]
        traffic = [lane for lane in lanes_of[identity] if lane.lane_use == "general"]
        parking = [lane for lane in lanes_of[identity] if lane.lane_use == "parking"]
        assert Counter(lane.direction for lane in traffic) == {"forward": 1, "backward": 1}
        assert len(parking) == (2 if segment.hierarchy == "high_street" else 0)
        seen[segment.hierarchy] += 1
    assert set(seen) == {"high_street", "local_street", "narrow_street"}


def test_every_junction_gives_one_street_priority_the_through_street_then_the_busier():
    """At the crossroads of two high streets the street along x keeps priority; where a cross
    street ends at an outer street, the outer street runs on and keeps it; no junction gives every
    approach priority, which traffic refuses."""
    _seed, records = _records(high_street_count=3, cross_street_hierarchy="narrow_street")
    segments = {record.identity: record for record in _of(records, StreetSegmentRecord)}
    approaches: dict[str, list[JunctionApproachRecord]] = {}
    for approach in _of(records, JunctionApproachRecord):
        approaches.setdefault(approach.junction_identity, []).append(approach)
    junctions = _of(records, JunctionRecord)
    assert junctions
    for junction in junctions:
        rows = approaches[junction.identity]
        priority = {
            segments[row.segment_identity].street_identity
            for row in rows
            if row.control == "priority"
        }
        stop = {
            segments[row.segment_identity].street_identity for row in rows if row.control == "stop"
        }
        assert len(priority) == 1 and len(stop) == 1, junction.identity
        [major] = priority
        legs = [segments[row.segment_identity] for row in rows]
        runs_on = Counter(leg.street_identity for leg in legs)[major] == 2
        assert runs_on, "priority went to a street that ends here"
        along_x = {
            leg.street_identity
            for leg in legs
            if leg.centreline_mm[0][1] == leg.centreline_mm[-1][1]
        }
        if len(legs) == 4 and {leg.hierarchy for leg in legs} == {"high_street"}:
            assert major in along_x


# -------------------------------------------------------------------------------------------------
# The use mix


def test_a_typology_weight_alone_makes_every_lot_that_admits_that_typology_take_it():
    weights = {f"typology_weight_{key}_permille": 0 for key in weighted_typologies()}
    _seed, records = _records(**{**weights, "typology_weight_loft_building_permille": 1000})
    lots = {record.identity: record for record in _of(records, ParcelRecord)}
    buildings = _of(records, MassingRecord)
    loft = entry_fields(
        next(c for c in load_city_catalogs(grammar_version=5) if c.catalog_id == "typology"),
        "loft_building",
    )
    lofts = 0
    for building in buildings:
        frontage = lots[building.parcel_identity].frontages[0].run_length_mm
        fits = loft["frontage_minimum_mm"] <= frontage <= loft["frontage_maximum_mm"]  # type: ignore[operator]
        assert (building.typology == "loft_building") == fits, (building.typology, frontage)
        lofts += building.typology == "loft_building"
    assert lofts > 0


def test_every_weight_zero_draws_evenly_and_refuses_no_lot():
    zero = {name: 0 for name in _NEW if name.endswith("_permille")}
    _seed, records = _records(**zero)
    assert len({building.typology for building in _of(records, MassingRecord)}) > 1


def test_a_use_weight_alone_makes_every_shop_that_can_take_that_use_take_it():
    weights = {f"ground_floor_use_weight_{key}_permille": 0 for key in shop_uses()}
    _seed, records = _records(**{**weights, "ground_floor_use_weight_cafe_permille": 1000})
    typology = next(c for c in load_city_catalogs(grammar_version=5) if c.catalog_id == "typology")
    fitout = next(c for c in load_city_catalogs(grammar_version=5) if c.catalog_id == "fitout")
    buildings = {record.identity: record for record in _of(records, MassingRecord)}
    lots = {record.identity: record for record in _of(records, ParcelRecord)}
    faces = _of(records, FacadeRecord)
    bays = _of(records, GroundBayRecord)
    face_of = {face.identity: face for face in faces}
    cafes = 0
    for shop in (p for p in _of(records, PremisesRecord) if p.sign):
        building = buildings[shop.building_identity]
        own_faces = [face for face in faces if face.building_identity == building.identity]
        own_bays = [
            bay
            for bay in bays
            if face_of[bay.facade_identity].building_identity == building.identity
        ]
        units = building_shop_units(lots[building.parcel_identity], own_faces, own_bays)
        shopfronts = [bay for unit in units for bay in unit if bay.bay_kind == "shopfront"]
        served = (
            {
                use
                for key in fitting_fitouts(shopfronts)
                for use in entry_fields(fitout, key)["use_classes"]
            }  # type: ignore[union-attr]
            if shopfronts
            else {"cafe"}
        )
        admits = "cafe" in entry_fields(typology, building.typology)["ground_floor_uses"]  # type: ignore[operator]
        assert (shop.use_class == "cafe") == (admits and "cafe" in served), shop.identity
        cafes += shop.use_class == "cafe"
    assert cafes > 0


def test_each_window_is_dressed_for_the_use_its_shop_already_has():
    _seed, records = _records(ground_floor_use_weight_bakery_permille=1000)
    use_of_bay = {
        bay: p.use_class for p in _of(records, PremisesRecord) for bay in p.bay_identities
    }
    fitout = next(c for c in load_city_catalogs(grammar_version=5) if c.catalog_id == "fitout")
    vitrines = _of(records, VitrineRecord)
    assert vitrines
    for case in vitrines:
        assert use_of_bay[case.bay_identity] in entry_fields(fitout, case.fitout)["use_classes"]  # type: ignore[operator]


# -------------------------------------------------------------------------------------------------
# Dressing


def test_version_5_dresses_the_bare_ground_and_every_ground_band_where_version_4_did_not():
    for version, dressed in ((4, False), (5, True)):
        values = _mix() if version == 5 else dict(_TOWN)
        _seed, records = _generated(values, version)
        materials = {(m.surface_identity, m.role): m for m in _of(records, SurfaceMaterialRecord)}
        patches = _of(records, TerrainRecord)
        assert patches
        assert all(((p.identity, "terrain") in materials) == dressed for p in patches)
        if dressed:
            assert {materials[(p.identity, "terrain")].material for p in patches} == {
                "tree_pit_soil"
            }
        bands = [face for face in _of(records, FacadeRecord) if face.first_storey == 0]
        party = [face for face in bands if face.exposure == "party_wall"]
        assert party, "a town with no party wall would pass this vacuously"
        assert all(((face.identity, "ground_band") in materials) == dressed for face in party)
        assert all(
            (face.identity, "ground_band") in materials
            for face in bands
            if face.exposure != "party_wall"
        )


# -------------------------------------------------------------------------------------------------
# A rounded corner's follower (#85)


def _document(values: dict[str, object], version: int, tile_x: int) -> TileDocument:
    seed, records = _generated(values, version)
    return tile_document(
        records,
        seed=seed,
        subject_identity=_IDENTITY,
        catalogs=load_city_catalogs(grammar_version=version),
        tile_x=tile_x,
        tile_y=0,
        lod=0,
        grammar_version=version,
    )


def _without_follower(document: TileDocument, *, rounded: bool) -> tuple[TileDocument, str]:
    """The document with the halo follower of one owned curb moved to its external list, and the
    material records that dress it, which belong with it, left out with it."""
    [grammar] = document.grammars
    owned = {record.identity: record for record in grammar.owned}
    halo = {record.identity: record for record in grammar.halo}
    for curb in (record for record in owned.values() if isinstance(record, CurbEdgeRecord)):
        if (curb.corner_radius_mm > 0) != rounded:
            continue
        for follower in curb.next_curb_identity:
            if follower in halo:
                external = dict(grammar.external)
                external[follower] = "city.curb_edge"
                edited = dataclasses.replace(
                    grammar,
                    halo=tuple(
                        record
                        for record in grammar.halo
                        if record.identity != follower
                        and getattr(record, "surface_identity", None) != follower
                    ),
                    external=tuple(sorted(external.items())),
                )
                return dataclasses.replace(document, grammars=(edited,)), curb.identity
    raise AssertionError("no owned curb of that kind has a follower in the halo")


def test_a_version_5_tile_lacking_a_rounded_corner_follower_is_refused_by_name():
    document = _document(_mix(), 5, 1)
    catalogs = load_city_catalogs(grammar_version=5)
    validate_city_document(document, catalogs=catalogs)
    edited, curb = _without_follower(document, rounded=True)
    with pytest.raises(InvalidRecordError, match=rf"\[corner_follower\] curb {curb}"):
        validate_city_document(edited, catalogs=catalogs)


def test_a_straight_join_needs_no_follower_the_tile_does_not_carry():
    """The outer streets' kerbs join straight on at each cross street; the #85 town, two tiles long
    with cross streets 140 m apart, puts one such follower 6 m outside the second tile's margin."""
    document = _document(_mix(block_length_mm=140_000), 5, 1)
    [grammar] = document.grammars
    carried = {record.identity for record in grammar.records()}
    lacking = [
        curb
        for curb in grammar.owned
        if isinstance(curb, CurbEdgeRecord)
        and any(follower not in carried for follower in curb.next_curb_identity)
    ]
    assert lacking and all(curb.corner_radius_mm == 0 for curb in lacking)
    validate_city_document(document, catalogs=load_city_catalogs(grammar_version=5))


# -------------------------------------------------------------------------------------------------
# The tessellator, through its own CLI


def _bake(document: Path) -> str:
    if not TSX.exists():
        pytest.skip(
            f"the web toolchain is not installed ({TSX} is missing); run pnpm install in web/"
        )
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    out = document.with_suffix(".owd")
    result = subprocess.run(
        [str(TSX), str(CLI), "bake", str(document), str(out)],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return hashlib.sha256(out.read_bytes()).hexdigest()


def test_the_tessellator_bakes_every_corridor_tile_to_the_bytes_it_baked_before(tmp_path):
    documents = {}
    for version in (3, 4):
        generation = generate_city(
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            bindings=CORRIDOR_BINDINGS,
            grammar_version=version,
        )
        records = city_records(generation)
        catalogs = load_city_catalogs(grammar_version=version)
        for tile_x, tile_y in CORRIDOR_TILES:
            document = tile_document(
                records,
                seed=CORRIDOR_SEED,
                subject_identity=CORRIDOR_CITY_IDENTITY,
                catalogs=catalogs,
                tile_x=tile_x,
                tile_y=tile_y,
                lod=CORRIDOR_LOD,
                grammar_version=version,
            )
            path = tmp_path / f"corridor-v{version}-{tile_x}-{tile_y}.json"
            path.write_bytes(document_bytes(document))
            documents[(version, tile_x)] = path
    assert documents.keys() == _CORRIDOR_CONTAINERS.keys()
    with ThreadPoolExecutor(max_workers=4) as pool:
        baked = dict(zip(documents, pool.map(_bake, documents.values()), strict=True))
    assert baked == _CORRIDOR_CONTAINERS


def test_the_tessellator_bakes_a_tile_owning_a_straight_join_whose_follower_it_lacks(tmp_path):
    """Issue #85's tile: the second tile of a town two tiles long with cross streets 140 m apart,
    at version 4 as the specification's two-tile rule refused it and at version 5."""
    for version in (4, 5):
        values = (
            _mix(block_length_mm=140_000)
            if version == 5
            else {
                **_TOWN,
                "block_length_mm": 140_000,
            }
        )
        document = _document(values, version, 1)
        path = tmp_path / f"town-v{version}-1-0.json"
        path.write_bytes(document_bytes(document))
        assert len(_bake(path)) == 64
