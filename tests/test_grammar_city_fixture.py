"""The hand-written city v2 fixture tile: its committed bytes, its validation, and what it refuses.

``tests/fixtures/city-v2`` is what the tessellator (lane tess) reads. Its two files are pinned here
twice: equal to what ``build_fixture.py`` writes today, and equal to a SHA-256 written into this
file, so a fixture that moves under a lane building on it cannot move silently.

The document validates completely, and the report counts what the corridor is gated on. Then each
mutation below breaks exactly one thing, and the named document check (the bracketed name in the
refusal) is the one that refuses it. A mutation refused by some earlier, unrelated check would
prove nothing about the check it names, so every case names the check it expects.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.errors import InvalidRecordError, UnresolvedReferenceError
from exulanica.grammar.geometry import Extent, ring_centroid
from exulanica.grammar.grammars.city import CITY_SHAPES
from exulanica.grammar.grammars.city.catalogs import entry_fields, load_city_catalogs
from exulanica.grammar.grammars.city.descriptor import CITY_V1_DESCRIPTOR_PATH
from exulanica.grammar.grammars.city.document import (
    RELATION_FIELDS,
    TILE_DOCUMENT_PROFILE,
    TileDocument,
    document_bytes,
    read_tile_document,
    record_sort_key,
    validate_city_document,
)
from exulanica.grammar.grammars.city.streets import BlockRecord
from exulanica.grammar.grammars.city.tile import (
    HALO,
    HALO_RULES,
    OUTSIDE_TILE,
    OWNED,
    halo_square,
    membership,
)
from exulanica.grammar.shapes import describe_shapes
from exulanica.grammar.textures import read_texture_manifest

from city_v2_fixture import builder

FIXTURE = builder()
DOCUMENT_SHA256 = "9da6beb4bda8f9314baaaf9edd4d8385c5f05521a337ff9be805ddc59ecf9a31"
DOCUMENT_BYTES = 124_717
SHAPES_SHA256 = "14d981dba098f6fcbf11cc21da44340674f61a009f81a937ba425564d37ec7e9"
SHAPES_BYTES = 59_825

#: Every city record kind but the tile record, which is the envelope rather than a record in it.
_RECORD_KINDS = sorted(shape.kind for shape in CITY_SHAPES if shape.kind != "city.tile")


def _validate(document: TileDocument, catalogs: Any = None):
    return validate_city_document(
        document, catalogs=FIXTURE.CATALOGS if catalogs is None else catalogs
    )


# -------------------------------------------------------------------------------------------
# The committed files


def test_the_committed_document_is_exactly_what_the_builder_writes():
    committed = FIXTURE.DOCUMENT_PATH.read_bytes()
    assert committed == document_bytes(FIXTURE.build_document())
    assert (len(committed), hashlib.sha256(committed).hexdigest()) == (
        DOCUMENT_BYTES,
        DOCUMENT_SHA256,
    )


def test_the_committed_shape_table_is_exactly_the_city_shapes():
    committed = FIXTURE.SHAPES_PATH.read_bytes()
    assert committed == FIXTURE.shape_table_bytes()
    assert json.loads(committed) == describe_shapes(CITY_SHAPES)
    assert (len(committed), hashlib.sha256(committed).hexdigest()) == (SHAPES_BYTES, SHAPES_SHA256)


def test_importing_the_builder_writes_nothing():
    """The builder writes only from ``main``; the tests import it under another module name."""
    assert FIXTURE.__name__ != "__main__"
    assert FIXTURE.DOCUMENT_PATH.read_bytes() == document_bytes(FIXTURE.build_document())


# -------------------------------------------------------------------------------------------
# Reading and validating


def test_the_committed_bytes_read_back_to_the_built_document():
    read = read_tile_document(FIXTURE.DOCUMENT_PATH.read_bytes())
    assert read == FIXTURE.build_document()
    assert read.payload()["profile"] == TILE_DOCUMENT_PROFILE


def test_the_fixture_validates_completely_and_reports_the_gate_figures():
    report = _validate(read_tile_document(FIXTURE.DOCUMENT_PATH.read_bytes()))
    figures = report.as_dict()
    assert sorted(figures["record_counts"]) == _RECORD_KINDS
    assert len(_RECORD_KINDS) == 26
    assert figures["record_counts"]["city.surface_material"] == 81
    assert figures["record_counts"]["city.facade"] == 9
    assert {
        name: value
        for name, value in figures.items()
        if name not in ("record_counts", "unavailable_surfaces")
    } == {
        "buildings": 1,
        "buildings_with_every_facade": 1,
        "frontage_faces_with_bays": 4,
        "frontage_faces_in_pitch_band": 4,
        "edges_over_threshold_without_bays": 0,
        "kerb_height_range_mm": [150, 150],
        "objects_inside_footprints": 0,
        "materials": 81,
        "materials_with_texture_set": 81,
        "facades": 9,
        "facades_with_section_5_1_fields": 9,
    }
    unavailable = Counter(entry.rsplit(":", 1)[1] for entry in figures["unavailable_surfaces"])
    assert unavailable == {"glazing": 6, "transom": 9, "door": 4, "marking": 3, "tree": 1}


def test_the_fixture_uses_only_real_catalog_keys_and_published_texture_sets():
    published = read_texture_manifest()
    materials = next(catalog for catalog in FIXTURE.CATALOGS if catalog.catalog_id == "material")
    for record in FIXTURE.materials:
        assert record.texture_set_id in published
        assert entry_fields(materials, record.material)["texture_set_id"] == record.texture_set_id


@pytest.mark.parametrize(
    "text,message",
    [
        ("pretty", "exactly its canonical JSON"),
        ("profile", "profile is"),
        ("unsorted", "sorted by kind, version and identity"),
        ("both", "both owned and halo"),
        ("grammar", "city v2 records only"),
    ],
)
def test_a_document_outside_its_envelope_is_refused_when_read(text, message):
    payload = FIXTURE.build_document().payload()
    entry = payload["grammars"][0]
    if text == "pretty":
        data = json.dumps(payload, indent=1, sort_keys=True).encode()
    else:
        if text == "profile":
            payload["profile"] = "exulanica.tile-document/v1"
        elif text == "unsorted":
            entry["owned"] = list(reversed(entry["owned"]))
        elif text == "both":
            entry["halo"] = sorted(
                [*entry["halo"], entry["owned"][0]],
                key=lambda item: (item["kind"], item["version"], item["fields"]["identity"]),
            )
        else:
            entry["grammar_version"] = 1
            payload["tile"]["fields"]["grammar_versions"][0]["grammar_version"] = 1
        data = canonical_json(payload)
    with pytest.raises(InvalidRecordError, match=message):
        read_tile_document(data)


# -------------------------------------------------------------------------------------------
# Mutations, each refused by the check it names


def _document(
    *,
    replace: dict[str, object] | None = None,
    remove: frozenset[str] = frozenset(),
    to_halo: frozenset[str] = frozenset(),
    to_owned: frozenset[str] = frozenset(),
    tile: dict[str, object] | None = None,
    grammar: dict[str, object] | None = None,
    add_halo: tuple[object, ...] = (),
    add_owned: tuple[object, ...] = (),
) -> TileDocument:
    """The fixture document with records replaced (by identity), removed, moved or added."""
    document = FIXTURE.build_document()
    entry = document.grammars[0]
    replacements = replace or {}
    owned, halo = [], []
    for listed, records in (("owned", entry.owned), ("halo", entry.halo)):
        for record in records:
            identity = record.identity  # type: ignore[attr-defined]
            if identity in remove:
                continue
            record = replacements.get(identity, record)
            moved = (listed == "owned" and identity in to_halo) or (
                listed == "halo" and identity in to_owned
            )
            (halo if (listed == "halo") != moved else owned).append(record)
    halo.extend(add_halo)
    owned.extend(add_owned)
    entry = dataclasses.replace(
        entry,
        owned=tuple(sorted(owned, key=record_sort_key)),
        halo=tuple(sorted(halo, key=record_sort_key)),
        **(grammar or {}),
    )
    return TileDocument(dataclasses.replace(document.tile, **(tile or {})), (entry,))


def _placed_at(record: Any, x: int, y: int) -> Any:
    facing = (record.facing_dx_mm, record.facing_dy_mm)
    extent = FIXTURE.parts_extent(x, y, record.z_mm, facing, record.parts)
    return dataclasses.replace(record, x_mm=x, y_mm=y, extent=extent)


def _stop_line_moved() -> TileDocument:
    lane = FIXTURE.lanes[2]
    return _document(replace={lane.identity: dataclasses.replace(lane, end_offset_mm=27_000)})


def _stop_point_moved() -> TileDocument:
    lane = FIXTURE.lanes[2]
    line = (lane.centreline_mm[0], (46_100, 37_175, -56))
    extent = dataclasses.replace(lane.extent, max_x_mm=46_100)
    return _document(
        replace={lane.identity: dataclasses.replace(lane, centreline_mm=line, extent=extent)}
    )


def _identity_wrong() -> TileDocument:
    marking = FIXTURE.markings[0]
    wrong = "00000000-0000-5000-8000-000000000000"
    return _document(replace={marking.identity: dataclasses.replace(marking, identity=wrong)})


def _key_unknown() -> TileDocument:
    building = FIXTURE.building
    return _document(replace={building.identity: dataclasses.replace(building, typology="castle")})


def _era_foreign_to_typology() -> TileDocument:
    building = FIXTURE.building
    return _document(replace={building.identity: dataclasses.replace(building, era="postwar")})


def _texture_set_other() -> TileDocument:
    wall = FIXTURE.materials[0]
    asphalt = next(item for item in FIXTURE.materials if item.material == "carriageway_asphalt")
    assert asphalt.texture_set_id != wall.texture_set_id
    changed = dataclasses.replace(wall, texture_set_id=asphalt.texture_set_id)
    return _document(replace={wall.identity: changed})


def _facade_removed_alone() -> TileDocument:
    return _document(remove=frozenset({FIXTURE.facades[-1].identity}))


def _bench_in_building() -> TileDocument:
    bench = FIXTURE.furniture[0]
    return _document(replace={bench.identity: _placed_at(bench, 45_000, 55_000)})


def _stand_outside_its_space() -> TileDocument:
    stand = FIXTURE.furniture[5]
    assert stand.furniture_class == "cycle_stand"
    return _document(replace={stand.identity: _placed_at(stand, 55_550, 59_000)})


def _building_listed_as_halo() -> TileDocument:
    return _document(to_halo=frozenset({FIXTURE.building.identity}))


def _district_listed_as_owned() -> TileDocument:
    return _document(to_owned=frozenset({FIXTURE.district.identity}))


def _far_block(min_x: int) -> BlockRecord:
    """A long block anchored well beyond the grown square, reaching back toward the tile."""
    ring = ((min_x, 0), (900_000, 0), (900_000, 10_000), (min_x, 10_000))
    return BlockRecord(
        FIXTURE.identity("block", FIXTURE.CITY, 1),
        1,
        FIXTURE.DISTRICT,
        ring,
        *ring_centroid(ring),
        0,
        Extent(min_x, 0, 0, 900_000, 10_000, 0),
    )


def _halo_block_that_misses_the_grown_square() -> TileDocument:
    return _document(add_halo=(_far_block(192_000),))


def _district_far_away() -> TileDocument:
    district = FIXTURE.district
    ring = ((500_000, 500_000), (600_000, 500_000), (600_000, 600_000), (500_000, 600_000))
    moved = dataclasses.replace(
        district,
        boundary_mm=ring,
        extent=Extent(500_000, 500_000, -95, 600_000, 600_000, 22_585),
    )
    return _document(replace={district.identity: moved})


def _material_listed_apart_from_its_surface() -> TileDocument:
    return _document(to_halo=frozenset({FIXTURE.materials[0].identity}))


def _descriptor_pinned_elsewhere() -> TileDocument:
    [pin] = FIXTURE.tile.grammar_versions
    other = "1" * 64
    return _document(
        tile={"grammar_versions": (dataclasses.replace(pin, descriptor_sha256=other),)},
        grammar={"descriptor_sha256": other},
    )


def _tile_pin_alone_moved() -> TileDocument:
    [pin] = FIXTURE.tile.grammar_versions
    return _document(
        tile={"grammar_versions": (dataclasses.replace(pin, descriptor_sha256="1" * 64),)}
    )


def _catalog_pinned_elsewhere() -> TileDocument:
    return _document(tile={"catalog_digest": "2" * 64})


def _facade_seed_other() -> TileDocument:
    face = FIXTURE.facades[0]
    return _document(replace={face.identity: dataclasses.replace(face, seed="3" * 64)})


def _footway_narrowed() -> TileDocument:
    curb = FIXTURE.curbs[0]
    return _document(replace={curb.identity: dataclasses.replace(curb, footway_width_mm=3_900)})


def _camber_steepened() -> TileDocument:
    segment = FIXTURE.segments[0]
    return _document(
        replace={segment.identity: dataclasses.replace(segment, camber_millionths=21_000)}
    )


def _crossing_too_wide() -> TileDocument:
    crossing = FIXTURE.crossings[0]
    signalised = entry_fields(
        next(catalog for catalog in FIXTURE.CATALOGS if catalog.catalog_id == "crossing-type"),
        "signalised",
    )
    width = signalised["width_maximum_mm"] + 1  # type: ignore[operator]
    return _document(replace={crossing.identity: dataclasses.replace(crossing, width_mm=width)})


def _kerb_below_the_gate() -> TileDocument:
    curb = FIXTURE.curbs[0]
    return _document(replace={curb.identity: dataclasses.replace(curb, kerb_height_mm=99)})


def _vitrine_not_behind_glass() -> TileDocument:
    vitrine = FIXTURE.vitrines[0]
    return _document(replace={vitrine.identity: dataclasses.replace(vitrine, sill_mm=500)})


def _sign_of_another_use() -> TileDocument:
    shop = FIXTURE.premises[0]
    changed = dataclasses.replace(shop, sign=("books",), sign_text=("Books",))
    return _document(replace={shop.identity: changed})


_MUTATIONS: list[tuple[str, Callable[[], TileDocument], str]] = [
    ("a stop line moved into a crossing", _stop_line_moved, r"\[stop_line\]"),
    ("a stop line point moved off its connection", _stop_point_moved, r"\[connection_path\]"),
    ("an identity its rule does not derive", _identity_wrong, "is not the identity its rule"),
    ("a catalog key that does not exist", _key_unknown, "'castle' is not a key of typology"),
    ("an era its typology does not have", _era_foreign_to_typology, r"\[typology\]"),
    ("a material naming another set", _texture_set_other, r"\[material_texture\]"),
    ("a facade removed from under its materials", _facade_removed_alone, "which no record states"),
    ("a bench inside the building", _bench_in_building, r"\[footprint_intersection\]"),
    ("a cycle stand outside its space", _stand_outside_its_space, r"\[cycle_parking\]"),
    ("an owned building listed as halo", _building_listed_as_halo, r"\[membership\]"),
    ("a district listed as owned", _district_listed_as_owned, r"\[membership\]"),
    (
        "a halo block whose extent misses the grown square",
        _halo_block_that_misses_the_grown_square,
        r"\[membership\]",
    ),
    ("a district whose extent misses the grown square", _district_far_away, r"\[membership\]"),
    (
        "a material listed halo while its surface is owned",
        _material_listed_apart_from_its_surface,
        r"\[membership\]",
    ),
    ("both descriptor pins moved", _descriptor_pinned_elsewhere, r"\[descriptor_pin\]"),
    ("the tile's descriptor pin alone moved", _tile_pin_alone_moved, "exactly the tile's grammar"),
    ("a catalog digest pinned elsewhere", _catalog_pinned_elsewhere, r"\[catalog_pin\]"),
    ("a facade stating another seed", _facade_seed_other, r"\[seed\]"),
    ("a footway that stops short of the frontage", _footway_narrowed, r"\[frontage_line\]"),
    ("a camber the kerb line does not fall by", _camber_steepened, r"\[camber\]"),
    ("a crossing wider than its type", _crossing_too_wide, r"\[crossing_width\]"),
    ("a kerb below the 100 mm gate", _kerb_below_the_gate, "below its minimum 100"),
    ("a vitrine partly behind a stall riser", _vitrine_not_behind_glass, r"\[vitrine\]"),
    ("a sign of another use class", _sign_of_another_use, r"\[premises_sign\]"),
]


@pytest.mark.parametrize(
    "make,expected",
    [(make, expected) for _, make, expected in _MUTATIONS],
    ids=[what for what, _, _ in _MUTATIONS],
)
def test_each_mutation_is_refused_by_the_check_it_names(make, expected):
    with pytest.raises(InvalidRecordError, match=expected):
        _validate(make())


def test_a_mutation_is_also_refused_after_a_round_trip_through_bytes():
    for _what, make, expected in _MUTATIONS:
        document = make()
        with pytest.raises(InvalidRecordError, match=expected):
            _validate(read_tile_document(document_bytes(document)))


def test_the_unmutated_document_built_through_the_mutation_helper_validates():
    """The helper itself changes nothing, so every refusal above is the mutation's."""
    assert _document() == FIXTURE.build_document()
    _validate(_document())


def test_a_facade_removed_with_its_surfaces_leaves_the_building_without_every_facade():
    face = FIXTURE.facades[-1]
    dressing = {
        item.identity for item in FIXTURE.materials if item.surface_identity == face.identity
    }
    report = _validate(_document(remove=frozenset({face.identity, *dressing})))
    assert (report.buildings, report.buildings_with_every_facade) == (1, 0)


def test_a_stripped_texture_set_refuses_the_catalogs_that_name_it():
    published = dict(read_texture_manifest())
    used = FIXTURE.materials[0].texture_set_id
    del published[used]
    with pytest.raises(UnresolvedReferenceError, match=used):
        load_city_catalogs(texture_sets=published)


def test_a_document_is_refused_against_another_descriptor():
    with pytest.raises(InvalidRecordError, match=r"\[descriptor_pin\]"):
        validate_city_document(
            FIXTURE.build_document(),
            catalogs=FIXTURE.CATALOGS,
            descriptor_path=CITY_V1_DESCRIPTOR_PATH,
        )


# -------------------------------------------------------------------------------------------
# Tile membership


def test_the_halo_rule_is_extent_based():
    assert HALO_RULES == ("extent_meets_grown_square",)
    assert FIXTURE.tile.halo_rule == "extent_meets_grown_square"
    assert halo_square(FIXTURE.tile) == (-64_000, -64_000, 192_000, 192_000)


@pytest.mark.parametrize(
    "anchor,extent,expected",
    [
        ((0, 0), Extent(0, 0, 0, 0, 0, 0), OWNED),
        ((127_999, 127_999), Extent(-900_000, 0, 0, 127_999, 127_999, 0), OWNED),
        ((128_000, 0), Extent(128_000, 0, 0, 128_000, 0, 0), HALO),
        ((-1, 0), Extent(-1, 0, 0, -1, 0, 0), HALO),
        # Anchored far outside the grown square, and still crossing the tile.
        ((540_000, 5_000), Extent(180_000, 0, 0, 900_000, 10_000, 0), HALO),
        ((540_000, 5_000), Extent(-900_000, 60_000, 0, 900_000, 60_000, 0), HALO),
        (None, Extent(-10, -10, 0, 10, 10, 0), HALO),
        # The grown square's north and east edges belong to the next tiles' squares.
        ((500_000, 0), Extent(192_000, 0, 0, 900_000, 0, 0), OUTSIDE_TILE),
        ((0, 500_000), Extent(0, 192_000, 0, 0, 900_000, 0), OUTSIDE_TILE),
        ((-500_000, 0), Extent(-900_000, 0, 0, -64_001, 0, 0), OUTSIDE_TILE),
        ((-500_000, 0), Extent(-900_000, 0, 0, -64_000, 0, 0), HALO),
        (None, Extent(-900_000, -900_000, 0, -64_001, 900_000, 0), OUTSIDE_TILE),
    ],
)
def test_membership_reads_the_anchor_for_ownership_and_the_extent_for_the_halo(
    anchor, extent, expected
):
    assert membership(FIXTURE.tile, anchor, extent) == expected


def test_a_block_anchored_beyond_the_grown_square_that_reaches_the_tile_is_carried_as_halo():
    block = _far_block(191_999)
    assert block.centroid_x_mm > 192_000
    report = _validate(_document(add_halo=(block,)))
    assert report.record_counts["city.block"] == 2
    with pytest.raises(InvalidRecordError, match=r"\[membership\]"):
        _validate(_document(add_owned=(block,)))


def test_every_record_kind_without_an_extent_names_the_record_it_relates_to():
    without = {
        shape.record_type
        for shape in CITY_SHAPES
        if not shape.extent_field and shape.kind != "city.tile"
    }
    assert without == set(RELATION_FIELDS)
    for record_type, field in RELATION_FIELDS.items():
        shape = next(item for item in CITY_SHAPES if item.record_type is record_type)
        assert shape.field(field).kind == "identity"
