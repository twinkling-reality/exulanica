"""City grammar version 4: stop lines before crossings and kerbside parking lanes, beside version 3.

Version 4 runs the streets stage at its version 3 and every other stage as version 3 does. These
tests hold four things: version 3 generates exactly what it generated before version 4 existed;
version 4's stop lines stand back from the crossings they approach and its high streets keep a
parking lane against each kerb, each measured from the records rather than from the generator's
own arithmetic; the two versions' descriptors, catalogs and migration agree on everything version
4 does not change; and a document is read and checked at the version it pins.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import defaultdict
from functools import cache
from hashlib import sha256
from pathlib import Path

import pytest
from exulanica.grammar import CascadeBinding, generate
from exulanica.grammar.catalogs import catalog_digest
from exulanica.grammar.errors import CatalogError, GrammarError, InvalidRecordError
from exulanica.grammar.grammars.city import CITY_GRAMMAR_V4, city_grammar
from exulanica.grammar.grammars.city.catalogs import (
    CATALOG_DIRECTORY,
    entry_fields,
    load_city_catalogs,
)
from exulanica.grammar.grammars.city.descriptor import (
    CITY_MIGRATION_PATHS,
    CITY_SURFACE,
    CITY_V4_DESCRIPTOR_PATH,
    CITY_V4_SURFACE,
)
from exulanica.grammar.grammars.city.document import (
    TileDocument,
    descriptor_sha256,
    document_bytes,
    read_tile_document,
    validate_city_document,
)
from exulanica.grammar.grammars.city.facade import FacadeRecord
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_LOD,
    CORRIDOR_SEED,
    CORRIDOR_TILES,
)
from exulanica.grammar.grammars.city.generation.streets import DIMENSION_MODULE_MM
from exulanica.grammar.grammars.city.generation.tiles import (
    check_city_reference_closure,
    city_records,
    generate_city,
    tile_document,
)
from exulanica.grammar.grammars.city.roads import JunctionRecord, LaneRecord
from exulanica.grammar.grammars.city.streets import CrossingRecord, StreetSegmentRecord
from exulanica.grammar.migration import ParameterMigration
from exulanica.traffic.catalogs import CATALOG_DIRECTORY as TRAFFIC_CATALOG_DIRECTORY
from exulanica.traffic.catalogs import load_traffic_catalogs

ROOT = Path(__file__).resolve().parents[1]

#: What the corridor specification generated at version 3 on the tree version 4 was added to
#: (3bf3ce4b): the generation's output digest, the catalog digest and each tile document's SHA-256.
#: Version 4 must move none of them.
V3_OUTPUT_DIGEST = "dc1690236d69ca72bffbba7ca200980657339866e246190ef510c101d0da14d8"
V3_CATALOG_DIGEST = "a4c9ac1be3df9c05bd5104373bc5eae64eef9f3184f0eea049d2f005eb61f9ea"
V3_TILE_DOCUMENTS = {
    (0, 0): "172538ffb707d2e2cf09d41b4ade9aa080f43aca18932f804465d24efaa0e80f",
    (1, 0): "48e3643945076cf026aa4a8b16d5fefd4af8328aa51857ab7f73825e3c85933e",
    (2, 0): "1115cff049f2b6c7d2c347ff2b86eaff6694ba526728671ed6a3ed8f9c725a1a",
    (3, 0): "16baf55687e3aa6d0d6a87f00804687e31e1d7d21c083e90fcac50a2114bba91",
    (4, 0): "6fdbd1da273b2b57c4f2d9fe5dba0a04ee34d5f0766b887c83697f0f8149b54c",
}
#: MUTCD 2009 Section 3B.16's 4 feet, rounded up to the streets stage's 50 mm module, and the most
#: version 4's descriptor admits.
SETBACK_RANGE_MM = (1_250, 3_000)
_NEW_PARAMETERS = {"parking_lane_width_mm", "stop_line_setback_mm"}


@cache
def _corridor(version: int) -> tuple[tuple[object, ...], str, dict[tuple[int, int], TileDocument]]:
    generation = generate_city(
        seed=CORRIDOR_SEED,
        subject_identity=CORRIDOR_CITY_IDENTITY,
        bindings=CORRIDOR_BINDINGS,
        grammar_version=version,
    )
    records = city_records(generation)
    catalogs = load_city_catalogs(grammar_version=version)
    documents = {
        (tile_x, tile_y): tile_document(
            records,
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            catalogs=catalogs,
            tile_x=tile_x,
            tile_y=tile_y,
            lod=CORRIDOR_LOD,
            grammar_version=version,
        )
        for tile_x, tile_y in CORRIDOR_TILES
    }
    return records, generation.receipt.output_digest, documents


def _of(records: tuple[object, ...], kind: type) -> list:
    return [record for record in records if type(record) is kind]


def _stop_line_gaps(records: tuple[object, ...]) -> list[int]:
    """For every traffic lane flowing into a junction whose leg carries a crossing at that end,
    how far its stop line stands before the crossing's near edge, measured along the segment.

    Derived from the records alone: a lane's end offset, its direction, the segment's end nodes,
    the junctions' nodes, and the crossings' offsets and widths. Negative is a stop line past the
    crossing's near edge, inside or beyond the crossing.
    """
    segments = {record.identity: record for record in _of(records, StreetSegmentRecord)}
    junction_nodes = {record.node_identity for record in _of(records, JunctionRecord)}
    crossings = defaultdict(list)
    for crossing in _of(records, CrossingRecord):
        crossings[crossing.segment_identity].append(crossing)
    gaps = []
    for lane in _of(records, LaneRecord):
        if lane.direction == "none":
            continue
        segment = segments[lane.segment_identity]
        forward = lane.direction == "forward"
        end_node = segment.end_node_identity if forward else segment.start_node_identity
        if end_node not in junction_nodes or not crossings[segment.identity]:
            continue
        # The crossing nearest the node the lane flows into.
        crossing = (max if forward else min)(
            crossings[segment.identity], key=lambda item: item.offset_mm
        )
        if forward:
            gaps.append(crossing.offset_mm - crossing.width_mm // 2 - lane.end_offset_mm)
        else:
            gaps.append(lane.end_offset_mm - (crossing.offset_mm + crossing.width_mm // 2))
    return gaps


# -------------------------------------------------------------------------------------------
# Version 3 is what it was


def test_version_3_generates_exactly_what_it_generated_before_version_4():
    """THE BREAK CHECK FOR EVERYTHING BELOW: version 4 shares every stage but one with version 3,
    and a change meant for version 4 that reached version 3 moves one of these digests."""
    records, output_digest, documents = _corridor(3)
    assert output_digest == V3_OUTPUT_DIGEST
    assert len(records) == 6566
    assert catalog_digest(load_city_catalogs()) == V3_CATALOG_DIGEST
    assert catalog_digest(load_city_catalogs(grammar_version=3)) == V3_CATALOG_DIGEST
    assert {
        key: hashlib.sha256(document_bytes(document)).hexdigest()
        for key, document in documents.items()
    } == V3_TILE_DOCUMENTS


def test_a_caller_naming_no_version_generates_version_3():
    generation = generate_city(
        seed=CORRIDOR_SEED, subject_identity=CORRIDOR_CITY_IDENTITY, bindings=CORRIDOR_BINDINGS
    )
    assert (generation.receipt.grammar_version, generation.receipt.output_digest) == (
        3,
        V3_OUTPUT_DIGEST,
    )


# -------------------------------------------------------------------------------------------
# What version 4 lays


def test_version_4_stop_lines_stand_before_the_crossing_they_approach():
    """Version 3 ends an approaching lane at the junction side of its crossing, so every gap there
    is minus a crossing's width; version 4 stands every one back by the district's setback."""
    v3_gaps = _stop_line_gaps(_corridor(3)[0])
    assert v3_gaps and all(gap < 0 for gap in v3_gaps), "the control: version 3's lines are past"
    v4_gaps = _stop_line_gaps(_corridor(4)[0])
    assert len(v4_gaps) == len(v3_gaps)
    [setback] = set(v4_gaps)
    assert SETBACK_RANGE_MM[0] <= setback <= SETBACK_RANGE_MM[1]
    assert setback % 50 == 0


def test_version_4_high_streets_keep_a_parking_lane_against_each_kerb_and_local_streets_none():
    parking = entry_fields(
        next(c for c in load_city_catalogs(grammar_version=4) if c.catalog_id == "lane-use"),
        "parking",
    )
    records = _corridor(4)[0]
    v3_segments = {
        record.segment_ordinal: record for record in _of(_corridor(3)[0], StreetSegmentRecord)
    }
    lanes_by_segment = defaultdict(list)
    for lane in _of(records, LaneRecord):
        lanes_by_segment[lane.segment_identity].append(lane)
    crossings = defaultdict(list)
    for crossing in _of(records, CrossingRecord):
        crossings[crossing.segment_identity].append(crossing)
    widths = set()
    high_streets = 0
    for segment in _of(records, StreetSegmentRecord):
        lanes = sorted(lanes_by_segment[segment.identity], key=lambda lane: lane.lane_index)
        uses = [lane.lane_use for lane in lanes]
        before = v3_segments[segment.segment_ordinal]
        if segment.hierarchy == "high_street":
            high_streets += 1
            assert uses[0] == uses[-1] == "parking" and "parking" not in uses[1:-1], uses
            kerbside = [lanes[0], lanes[-1]]
            for lane in kerbside:
                assert (lane.direction, lane.turns) == ("none", ())
                assert parking["width_minimum_mm"] <= lane.width_mm <= parking["width_maximum_mm"]
                assert (
                    lane.width_mm >= CITY_V4_SURFACE.parameters.get("parking_lane_width_mm").minimum
                )
                widths.add(lane.width_mm)
                # Nothing stands on a crossing: the lane runs between them.
                for crossing in crossings[segment.identity]:
                    low = crossing.offset_mm - crossing.width_mm // 2
                    high = low + crossing.width_mm
                    assert lane.end_offset_mm <= low or lane.start_offset_mm >= high
            assert segment.carriageway_width_mm == before.carriageway_width_mm + sum(
                lane.width_mm for lane in kerbside
            )
        else:
            assert "parking" not in uses
            assert segment.carriageway_width_mm == before.carriageway_width_mm
    assert high_streets and len(widths) == 1, "one parking lane width runs through the district"


def test_a_parking_lane_is_at_least_as_wide_as_the_widest_class_a_general_bay_admits():
    """The descriptor states the minimum from traffic's vehicle classes and names that catalog by
    the digest of its bytes; a change to either fails here, as a turning radius's does."""
    catalogs = load_traffic_catalogs()
    widest = max(
        catalogs.vehicle_class(key).width_mm for key in catalogs.parking_kind("general").classes
    )
    module = DIMENSION_MODULE_MM
    spec = CITY_V4_SURFACE.parameters.get("parking_lane_width_mm")
    assert spec.minimum == -(-widest // module) * module == 2_150
    [row] = [
        row
        for row in json.loads(CITY_V4_DESCRIPTOR_PATH.read_text(encoding="utf-8"))["parameters"]
        if row["name"] == "parking_lane_width_mm"
    ]
    vehicle_file = TRAFFIC_CATALOG_DIRECTORY / "vehicle-class.v1.json"
    stated = (
        f"{vehicle_file.relative_to(ROOT)}, sha256 {sha256(vehicle_file.read_bytes()).hexdigest()}"
    )
    assert stated in row["basis"]


def test_every_version_4_corridor_tile_validates_and_the_city_is_closed():
    catalogs = load_city_catalogs(grammar_version=4)
    documents = _corridor(4)[2]
    for document in documents.values():
        validate_city_document(document, catalogs=catalogs)
    check_city_reference_closure(list(documents.values()))


def test_a_kerb_run_too_short_for_its_crossing_and_a_stop_line_before_it_is_refused_by_name():
    """A small city version 3 lays is refused by version 4 where no stop line can stand 4 feet
    before its crossing, rather than drawn with the line on the crossing."""
    values = {
        "driving_side": "right",
        "city_extent_x_mm": 256_000,
        "city_extent_y_mm": 128_000,
        "terrain_relief_mm": 0,
        "block_length_mm": 60_000,
        "block_depth_mm": 42_000,
        "gutter_width_mm": 300,
        "front_setback_mm": 0,
        "memory_precinct_lots": 1,
    }
    seed = hashlib.sha256(b"city grammar version 4 short kerb run").hexdigest()
    identity = "5b3a3e59-4bd2-5b53-9a39-6a0f5a2b8c11"
    bindings = (CascadeBinding.of("city", values),)
    generate(city_grammar(3), seed=seed, subject_identity=identity, bindings=bindings)
    with pytest.raises(InvalidRecordError, match="has no length between its kerb run's ends"):
        generate(CITY_GRAMMAR_V4, seed=seed, subject_identity=identity, bindings=bindings)


# -------------------------------------------------------------------------------------------
# What the two versions share


def test_version_4_declares_every_version_3_parameter_unchanged_and_two_more():
    v3 = {spec.name: spec for spec in CITY_SURFACE.parameters.parameters}
    v4 = {spec.name: spec for spec in CITY_V4_SURFACE.parameters.parameters}
    assert set(v4) - set(v3) == _NEW_PARAMETERS
    assert set(v3) <= set(v4)
    assert all(v4[name] == spec for name, spec in v3.items())
    for name in _NEW_PARAMETERS:
        assert (v4[name].stage, v4[name].level, v4[name].when_unset) == (
            "streets",
            "district",
            "derive",
        )
    assert (v4["stop_line_setback_mm"].minimum, v4["stop_line_setback_mm"].maximum) == (
        SETBACK_RANGE_MM
    )
    stages = {stage.stage_id: stage.stage_version for stage in CITY_GRAMMAR_V4.declared_stages}
    v3_stages = {stage.stage_id: stage.stage_version for stage in city_grammar(3).declared_stages}
    assert {key for key in stages if stages[key] != v3_stages[key]} == {"streets"}
    assert (v3_stages["streets"], stages["streets"]) == (2, 3)


def test_the_two_catalog_sets_differ_in_the_street_hierarchy_edition_alone():
    v3 = {catalog.catalog_id: catalog for catalog in load_city_catalogs(grammar_version=3)}
    v4 = {catalog.catalog_id: catalog for catalog in load_city_catalogs(grammar_version=4)}
    assert set(v3) == set(v4)
    assert [key for key in v3 if v3[key].payload() != v4[key].payload()] == ["street-hierarchy"]
    was, now = v3["street-hierarchy"], v4["street-hierarchy"]
    assert (was.catalog_version, now.catalog_version) == (2, 3)
    assert was.keys() == now.keys()
    for key in was.keys():  # noqa: SIM118 - a Catalog's keys() is its own method, not a dict's
        before, after = entry_fields(was, key), entry_fields(now, key)
        assert set(after) - set(before) == {"kerbside_parking"}
        # Every field edition 2 states, edition 3 states with the same value; its reason grows.
        assert {name: value for name, value in after.items() if name != "reason"} == {
            **{name: value for name, value in before.items() if name != "reason"},
            "kerbside_parking": after["kerbside_parking"],
        }
        assert str(after["reason"]).startswith(str(before["reason"]))
    kept = {key: entry_fields(now, key)["kerbside_parking"] for key in now.keys()}  # noqa: SIM118
    assert kept == {
        "avenue": "none",
        "high_street": "both_sides",
        "local_street": "none",
        "narrow_street": "none",
    }


def test_the_version_4_migration_carries_every_version_3_parameter_and_introduces_two():
    migration = ParameterMigration.read(CITY_MIGRATION_PATHS[4])
    migration.check(CITY_SURFACE, CITY_V4_SURFACE)
    assert (migration.source_version, migration.target_version) == (3, 4)
    names = sorted(CITY_SURFACE.parameters.names())
    assert (
        sorted(
            [entry.source for entry in migration.carried]
            + [entry.source for entry in migration.mapped]
        )
        == names
    )
    assert all(entry.source == entry.target for entry in migration.carried + migration.mapped)
    assert all((entry.multiply, entry.add) == (1, 0) for entry in migration.carried)
    assert {entry.target for entry in migration.introduced} == _NEW_PARAMETERS
    assert migration.removed == ()
    # Lane ordinals and the lots of a narrower block name other subjects at version 4.
    assert migration.identity_policy == "rekeyed"
    bound = (CascadeBinding.of("city", {"block_depth_mm": 56_000, "driving_side": "right"}),)
    assert migration.migrate(CITY_SURFACE, CITY_V4_SURFACE, bound).bindings == bound


# -------------------------------------------------------------------------------------------
# A document is read at the version it pins


def test_a_version_4_tile_pins_version_4_and_is_read_and_checked_there():
    document = _corridor(4)[2][(2, 0)]
    [pin] = document.tile.grammar_versions
    assert (pin.grammar_version, pin.descriptor_sha256) == (
        4,
        descriptor_sha256(CITY_V4_DESCRIPTOR_PATH),
    )
    catalogs = load_city_catalogs(grammar_version=4)
    assert document.tile.catalog_digest == catalog_digest(catalogs)
    assert read_tile_document(document_bytes(document)) == document
    with pytest.raises(InvalidRecordError, match="catalog_pin"):
        validate_city_document(document, catalogs=load_city_catalogs(grammar_version=3))


def test_a_facade_states_the_version_that_generated_it_and_is_held_to_its_tile():
    for version in (3, 4):
        facades = _of(_corridor(version)[0], FacadeRecord)
        assert facades and {facade.grammar_version for facade in facades} == {version}
    document = _corridor(4)[2][(2, 0)]
    [grammar] = document.grammars
    first = next(i for i, record in enumerate(grammar.owned) if type(record) is FacadeRecord)
    owned = list(grammar.owned)
    owned[first] = dataclasses.replace(owned[first], grammar_version=3)
    edited = dataclasses.replace(
        document, grammars=(dataclasses.replace(grammar, owned=tuple(owned)),)
    )
    with pytest.raises(InvalidRecordError, match="facade_version"):
        validate_city_document(edited, catalogs=load_city_catalogs(grammar_version=4))


def test_a_version_the_city_does_not_generate_is_refused_by_name():
    for version in (2, 5):
        with pytest.raises(GrammarError, match=f"version {version} is not one"):
            city_grammar(version)
        with pytest.raises(CatalogError, match=f"version {version} reads no catalog set"):
            load_city_catalogs(grammar_version=version)


def test_a_catalog_file_no_version_reads_is_still_refused(tmp_path):
    """Another version's edition may stand beside a set; a file no version reads may not."""
    directory = tmp_path / "catalogs"
    directory.mkdir()
    for path in CATALOG_DIRECTORY.glob("*.json"):
        (directory / path.name).write_bytes(path.read_bytes())
    for version in (3, 4):
        load_city_catalogs(directory, grammar_version=version)
    (directory / "street-hierarchy.v9.json").write_bytes(
        (CATALOG_DIRECTORY / "street-hierarchy.v3.json").read_bytes()
    )
    with pytest.raises(CatalogError, match=r"street-hierarchy\.v9\.json"):
        load_city_catalogs(directory, grammar_version=4)
