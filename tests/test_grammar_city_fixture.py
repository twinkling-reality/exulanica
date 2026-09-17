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
from exulanica.grammar.grammars.city.corners import corner_box, strip_box
from exulanica.grammar.grammars.city.descriptor import CITY_V1_DESCRIPTOR_PATH
from exulanica.grammar.grammars.city.document import (
    ANCHOR_OWNER_FIELDS,
    ANCHORLESS_KINDS,
    OWN_ANCHOR_KINDS,
    RELATION_FIELDS,
    TILE_DOCUMENT_PROFILE,
    TileDocument,
    document_bytes,
    read_tile_document,
    record_sort_key,
    select_tile,
    validate_city_document,
)
from exulanica.grammar.grammars.city.facade import (
    EntranceRecord,
    GroundBayRecord,
    facade_output_digest,
)
from exulanica.grammar.grammars.city.streets import BlockRecord, StreetSegmentRecord
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
DOCUMENT_SHA256 = "9ecd7b7009287459cce30db3718e83f980ae814b8fefc14212a153d1c70124ef"
DOCUMENT_BYTES = 132_669
SHAPES_SHA256 = "dc74683ac4d76e5d621c40313b469d302250c2337702d8c5da17e4dd6462cd65"
SHAPES_BYTES = 61_882

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
    assert len(_RECORD_KINDS) == 27
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


def _bench_outside_its_segment() -> TileDocument:
    bench = FIXTURE.furniture[0]
    return _document(replace={bench.identity: _placed_at(bench, 45_000, 55_000)})


def _bench_in_building() -> TileDocument:
    bench = _placed_at(FIXTURE.furniture[0], 45_000, 55_000)
    segment = FIXTURE.segments[0]
    widened = dataclasses.replace(segment, extent=FIXTURE.covering(segment.extent, bench.extent))
    return _document(replace={bench.identity: bench, segment.identity: widened})


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


def _junction_centred_beyond_the_tile() -> TileDocument:
    junction = FIXTURE.junction
    stretched = dataclasses.replace(junction.extent, max_x_mm=400_000)
    return _document(replace={junction.identity: dataclasses.replace(junction, extent=stretched)})


def _building_external() -> TileDocument:
    return _document(
        remove=frozenset({FIXTURE.BUILDING}),
        grammar={"external": ((FIXTURE.BUILDING, "city.massing"),)},
    )


def _facade_external_under_its_materials() -> TileDocument:
    face = FIXTURE.facades[-1]
    return _document(
        remove=frozenset({face.identity}), grammar={"external": ((face.identity, "city.facade"),)}
    )


# A segment crossing the tile northward from the north node to a node 400 m out, on a street the
# tile does not carry: the case external references exist for.
FAR_NODE = FIXTURE.identity("street_node", FIXTURE.CITY, 4)
NORTH_STREET = FIXTURE.identity("street", FIXTURE.CITY, 2)
OTHER_IDENTITY = "00000000-0000-5000-8000-000000000000"


def _crossing_segment() -> StreetSegmentRecord:
    return StreetSegmentRecord(
        identity=FIXTURE.identity("street_segment", FIXTURE.CITY, 3),
        segment_ordinal=3,
        street_identity=NORTH_STREET,
        district_identity=FIXTURE.DISTRICT,
        start_node_identity=FIXTURE.NODES["north"],
        end_node_identity=FAR_NODE,
        centreline_mm=(FIXTURE.NODE_POINTS["north"], (60_000, 400_000, 0)),
        length_mm=320_000,
        hierarchy="local_street",
        carriageway_width_mm=6_500,
        camber_millionths=29_231,
        speed_limit_mm_s=8_333,
        extent=Extent(56_750, 80_000, -95, 63_250, 400_000, 0),
    )


def _crossing_external() -> list[tuple[str, str]]:
    return sorted([(FAR_NODE, "city.street_node"), (NORTH_STREET, "city.street")])


def _crossing_document(external: list[tuple[str, str]] | None = None) -> TileDocument:
    listed = _crossing_external() if external is None else external
    return _document(add_halo=(_crossing_segment(),), grammar={"external": tuple(listed)})


def _far_node_not_listed() -> TileDocument:
    return _crossing_document([(NORTH_STREET, "city.street")])


def _far_node_listed_as_a_block() -> TileDocument:
    return _crossing_document(sorted([(FAR_NODE, "city.block"), (NORTH_STREET, "city.street")]))


def _external_nobody_names() -> TileDocument:
    return _crossing_document(sorted([*_crossing_external(), (OTHER_IDENTITY, "city.street_node")]))


def _external_also_carried() -> TileDocument:
    carried = (FIXTURE.NODES["north"], "city.street_node")
    return _crossing_document(sorted([*_crossing_external(), carried]))


def _external_out_of_order() -> TileDocument:
    return _crossing_document(list(reversed(_crossing_external())))


def _external_twice() -> TileDocument:
    first, second = _crossing_external()
    return _crossing_document([first, first, second])


def _external_tile_kind() -> TileDocument:
    return _crossing_document(sorted([(FAR_NODE, "city.tile"), (NORTH_STREET, "city.street")]))


def _external_unknown_kind() -> TileDocument:
    return _crossing_document(sorted([(FAR_NODE, "city.hedge"), (NORTH_STREET, "city.street")]))


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


def _corner_radius(curb_index: int, radius: int) -> TileDocument:
    curb = FIXTURE.curbs[curb_index]
    return _document(replace={curb.identity: dataclasses.replace(curb, corner_radius_mm=radius)})


def _corner_tangent_point_moved(offset_mm: int) -> TileDocument:
    """Mill Lane's west kerb starts ``offset_mm`` north of where the corner arc from Market Street
    ends. Market Street's north kerb owns that corner, so its extent, and its segment's, grow to
    the corner's new box."""
    owner, curb = FIXTURE.curbs[0], FIXTURE.curbs[4]
    (x, y, z), *rest = curb.kerb_line_mm
    moved = dataclasses.replace(curb, kerb_line_mm=((x, y + offset_mm, z), *rest))
    grown = _grown_to_corner(owner, moved)
    segment = next(item for item in FIXTURE.segments if item.identity == owner.segment_identity)
    segment = dataclasses.replace(segment, extent=FIXTURE.covering(segment.extent, grown.extent))
    return _document(
        replace={curb.identity: moved, owner.identity: grown, segment.identity: segment}
    )


def _grown_to_corner(owner: Any, follower: Any) -> Any:
    try:
        box = corner_box(owner, follower)
    except InvalidRecordError:
        return owner
    if box is None:
        return owner
    return dataclasses.replace(owner, extent=FIXTURE.covering(owner.extent, box))


def _corner_left_outside_its_owner() -> TileDocument:
    """Market Street's north kerb keeps only its straight part's extent, not its corner's."""
    curb = FIXTURE.curbs[0]
    return _document(replace={curb.identity: dataclasses.replace(curb, extent=strip_box(curb))})


def _straight_part_outside_its_curb() -> TileDocument:
    """Market Street's south kerb's extent stops 1 mm short of its footway's back edge."""
    curb = FIXTURE.curbs[1]
    shrunk = dataclasses.replace(curb.extent, min_y_mm=curb.extent.min_y_mm + 1)
    return _document(replace={curb.identity: dataclasses.replace(curb, extent=shrunk)})


def _frontage_corner_off_the_block() -> TileDocument:
    """Mill Lane's west footway narrows by 100 mm, so the corner Market Street's north kerb owns
    meets the frontage 100 mm east of the block's corner."""
    curb = FIXTURE.curbs[4]
    narrowed = dataclasses.replace(curb, footway_width_mm=curb.footway_width_mm - 100)
    return _document(replace={curb.identity: narrowed})


def _awning_at_head_height() -> TileDocument:
    """The first shopfront's awning hangs to 1800 mm above the building's base."""
    face = FIXTURE.facades[0]
    bay = FIXTURE.south_bays[0]
    [awning] = bay.awning
    lowered = dataclasses.replace(bay, awning=(dataclasses.replace(awning, front_z_mm=2_050),))
    bays = tuple(lowered if item.identity == bay.identity else item for item in FIXTURE.south_bays)
    entrances = tuple(item for item in FIXTURE.entrances if item.facade_identity == face.identity)
    redigested = dataclasses.replace(
        face, output_digest=facade_output_digest(face, bays, entrances)
    )
    return _document(replace={bay.identity: lowered, face.identity: redigested})


def _string_course_at_head_height() -> TileDocument:
    """The south face's lower string course drops to 1800 mm above the base."""
    face = FIXTURE.facades[0]
    first, *rest = face.string_courses
    lowered = dataclasses.replace(first, z_bottom_mm=1_800, z_top_mm=1_950)
    return _document(
        replace={face.identity: dataclasses.replace(face, string_courses=(lowered, *rest))}
    )


def _canopy_at_head_height() -> TileDocument:
    """The London plane's canopy starts 1000 mm above its trunk base, over the footway."""
    [tree] = FIXTURE.trees
    trunk, canopy = tree.parts
    lowered = dataclasses.replace(canopy, offset_z_mm=1_000)
    return _document(replace={tree.identity: dataclasses.replace(tree, parts=(trunk, lowered))})


def _junction_fill_below_its_extent() -> TileDocument:
    """The junction's extent stops 1 mm above the kerb lines its fill reaches down to."""
    junction = FIXTURE.junction
    raised = dataclasses.replace(junction.extent, min_z_mm=junction.extent.min_z_mm + 1)
    return _document(replace={junction.identity: dataclasses.replace(junction, extent=raised)})


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
    ("a facade removed from under its materials", _facade_removed_alone, r"\[references\]"),
    ("a bench moved outside its segment's extent", _bench_outside_its_segment, r"\[owner_extent\]"),
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
    (
        "a junction whose extent centre leaves the tile",
        _junction_centred_beyond_the_tile,
        r"\[membership\]",
    ),
    ("a building external under its facades", _building_external, r"\[anchor_owner\]"),
    (
        "a facade external under its materials",
        _facade_external_under_its_materials,
        r"\[anchor_owner\]",
    ),
    ("a far node neither carried nor external", _far_node_not_listed, r"\[references\]"),
    ("a far node listed as a block", _far_node_listed_as_a_block, r"\[reference_kind\]"),
    ("an external entry nothing names", _external_nobody_names, r"\[external_unnamed\]"),
    ("an identity both carried and external", _external_also_carried, r"\[external_carried\]"),
    ("external entries out of order", _external_out_of_order, r"\[external_order\]"),
    ("an external entry listed twice", _external_twice, r"\[external_order\]"),
    ("an external tile record", _external_tile_kind, r"\[external_kind\]"),
    ("an external entry of no kind", _external_unknown_kind, r"\[external_kind\]"),
    ("both descriptor pins moved", _descriptor_pinned_elsewhere, r"\[descriptor_pin\]"),
    ("the tile's descriptor pin alone moved", _tile_pin_alone_moved, "exactly the tile's grammar"),
    ("a catalog digest pinned elsewhere", _catalog_pinned_elsewhere, r"\[catalog_pin\]"),
    ("a facade stating another seed", _facade_seed_other, r"\[seed\]"),
    ("a footway that stops short of the frontage", _footway_narrowed, r"\[frontage_line\]"),
    ("a camber the kerb line does not fall by", _camber_steepened, r"\[camber\]"),
    (
        "a corner radius its tangent points do not fit",
        lambda: _corner_radius(0, 5_000),
        r"\[corner_radius\]",
    ),
    (
        "no corner radius where the kerbs do not meet",
        lambda: _corner_radius(0, 0),
        r"\[corner_radius\]",
    ),
    (
        "a corner radius where the kerb runs straight on",
        lambda: _corner_radius(3, 3_000),
        r"\[corner_radius\]",
    ),
    (
        "a tangent point 3 mm off its arc",
        lambda: _corner_tangent_point_moved(3),
        r"\[corner_radius\]",
    ),
    (
        "a corner outside the extent of the curb that owns it",
        _corner_left_outside_its_owner,
        r"\[corner_extent\]",
    ),
    (
        "a frontage corner that is not the block's corner",
        _frontage_corner_off_the_block,
        r"\[corner_extent\]",
    ),
    (
        "a straight footway outside its curb's extent",
        _straight_part_outside_its_curb,
        r"\[curb_extent\]",
    ),
    (
        "a junction fill outside the junction's extent",
        _junction_fill_below_its_extent,
        r"\[junction_extent\]",
    ),
    ("an awning hanging at head height", _awning_at_head_height, r"\[facade_clearance\]"),
    (
        "a string course projecting at head height",
        _string_course_at_head_height,
        r"\[facade_clearance\]",
    ),
    ("a tree canopy at head height", _canopy_at_head_height, r"\[canopy_clearance\]"),
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


# -------------------------------------------------------------------------------------------
# External references


def test_a_segment_crossing_the_tile_with_a_far_node_and_an_external_street_validates():
    document = _crossing_document()
    report = _validate(document)
    assert report.record_counts["city.street_segment"] == 4
    [entry] = document.grammars
    assert _crossing_segment().identity in {record.identity for record in entry.halo}
    assert dict(entry.external) == {FAR_NODE: "city.street_node", NORTH_STREET: "city.street"}
    again = read_tile_document(document_bytes(document))
    assert again == document
    _validate(again)


def test_the_committed_fixture_carries_everything_it_names():
    [entry] = FIXTURE.build_document().grammars
    assert entry.external == ()
    assert document_bytes(FIXTURE.build_document()).count(b'"external":[]') == 1


def test_every_record_kind_has_exactly_one_anchor_rule():
    kinds = {shape.record_type for shape in CITY_SHAPES if shape.kind != "city.tile"}
    rules = [
        set(OWN_ANCHOR_KINDS),
        set(ANCHOR_OWNER_FIELDS),
        set(RELATION_FIELDS),
        set(ANCHORLESS_KINDS),
    ]
    assert set().union(*rules) == kinds
    assert sum(len(rule) for rule in rules) == len(kinds)
    for record_type, field in ANCHOR_OWNER_FIELDS.items():
        shape = next(item for item in CITY_SHAPES if item.record_type is record_type)
        assert shape.field(field).kind == "identity"
        assert shape.extent_field == "extent"


_NEIGHBOURHOOD = [(tile_x, tile_y) for tile_y in (-1, 0, 1) for tile_x in (-1, 0, 1)]


def _city_records() -> tuple[object, ...]:
    return FIXTURE.build_document().grammars[0].records()


def test_selecting_the_fixture_tile_from_its_records_gives_the_committed_document():
    assert select_tile(FIXTURE.tile, _city_records(), subject_identity=FIXTURE.CITY) == (
        FIXTURE.build_document()
    )


@pytest.mark.parametrize("tile_x,tile_y", _NEIGHBOURHOOD)
def test_the_same_city_seen_from_each_neighbouring_tile_validates(tile_x, tile_y):
    """Halo owners with partial parts, far references and external streets, all by the rules."""
    tile = dataclasses.replace(FIXTURE.tile, tile_x=tile_x, tile_y=tile_y)
    document = select_tile(tile, _city_records(), subject_identity=FIXTURE.CITY)
    _validate(document)
    _validate(read_tile_document(document_bytes(document)))


def test_every_anchored_record_is_owned_by_exactly_one_tile_of_the_neighbourhood():
    owners: dict[str, list[tuple[int, int]]] = {}
    carried: set[str] = set()
    for tile_x, tile_y in _NEIGHBOURHOOD:
        tile = dataclasses.replace(FIXTURE.tile, tile_x=tile_x, tile_y=tile_y)
        [entry] = select_tile(tile, _city_records(), subject_identity=FIXTURE.CITY).grammars
        for record in entry.owned:
            owners.setdefault(record.identity, []).append((tile_x, tile_y))
        carried |= {record.identity for record in entry.records()}
        if (tile_x, tile_y) == (0, 1):
            assert entry.halo and entry.external
    anchorless = {FIXTURE.district.identity, *(street.identity for street in FIXTURE.streets)}
    everything = {record.identity for record in _city_records()}
    assert set(owners) == everything - anchorless
    assert all(places == [(0, 0)] for places in owners.values())
    assert carried == everything


def _halo_facade_missing_a_bay() -> TileDocument:
    """Tile (-1, 0) carries the building as halo; one ground bay of its south face is left out.

    Carried bays of a halo face are only those whose own extents reach the grown square, so a halo
    face may lack a part, and the part becomes an external reference of the records that name it.
    """
    tile = dataclasses.replace(FIXTURE.tile, tile_x=-1)
    [entry] = select_tile(tile, _city_records(), subject_identity=FIXTURE.CITY).grammars
    bay = FIXTURE.south_bays[0]
    halo = tuple(record for record in entry.halo if record.identity != bay.identity)
    assert len(halo) == len(entry.halo) - 1
    external = tuple(sorted((*entry.external, (bay.identity, "city.ground_bay"))))
    return TileDocument(tile, (dataclasses.replace(entry, halo=halo, external=external),))


def test_a_halo_facade_lacking_a_ground_bay_validates_by_the_owned_only_rules():
    document = _halo_facade_missing_a_bay()
    [entry] = document.grammars
    south = FIXTURE.facades[0]
    assert south.identity in {record.identity for record in entry.halo}
    assert not entry.owned
    carried_bays = tuple(
        record
        for record in entry.halo
        if type(record) is GroundBayRecord and record.facade_identity == south.identity
    )
    carried_entrances = tuple(
        record
        for record in entry.halo
        if type(record) is EntranceRecord and record.facade_identity == south.identity
    )
    assert len(carried_bays) == south.bays.count - 1
    # The face's stated digest covers all four bays, so a digest over what this tile carries
    # differs: only the rule that checks the digest on an owned face lets the document stand.
    assert facade_output_digest(south, carried_bays, carried_entrances) != south.output_digest
    _validate(document)
    _validate(read_tile_document(document_bytes(document)))


def test_the_same_facade_owned_and_lacking_a_ground_bay_is_refused():
    bay = FIXTURE.south_bays[0]
    document = _document(
        remove=frozenset({bay.identity}),
        grammar={"external": ((bay.identity, "city.ground_bay"),)},
    )
    with pytest.raises(InvalidRecordError, match=r"\[ground_bays\]"):
        _validate(document)


# -------------------------------------------------------------------------------------------
# Corner arcs


def test_the_fixture_corners_are_the_ones_the_check_reads():
    """Market Street's north kerb turns into Mill Lane's west kerb, and Mill Lane's east kerb into
    Market Street's north kerb east of the junction, each on a 6 m arc; the south kerb runs
    straight on."""
    curbs = FIXTURE.curbs
    assert (curbs[0].next_curb_identity, curbs[0].corner_radius_mm) == ((curbs[4].identity,), 6_000)
    assert (curbs[5].next_curb_identity, curbs[5].corner_radius_mm) == ((curbs[2].identity,), 6_000)
    assert (curbs[3].next_curb_identity, curbs[3].corner_radius_mm) == ((curbs[1].identity,), 0)
    assert curbs[3].kerb_line_mm[0] == curbs[1].kerb_line_mm[-1]


def test_a_tangent_point_within_the_stated_rounding_of_its_arc_is_accepted():
    _validate(_corner_tangent_point_moved(2))
    with pytest.raises(InvalidRecordError, match=r"\[corner_radius\]"):
        _validate(_corner_tangent_point_moved(3))
