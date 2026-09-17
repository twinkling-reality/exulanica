"""The city v2 fixture tile, written by hand, and the one command that writes its files.

Every value below was chosen by hand for this fixture. The builder computes only what a written
rule derives from those values: identities (``exulanica.grammar.subjects``), facade output
digests, part extents, owners' extents covering what they anchor, a curb's extent covering the
corner its radius owns, the descriptor and catalog pins, and the canonical bytes. The tile carries
everything it names, so its external list is empty. It is a test input, never stage output, and
nothing here is a generator.

The tile is one T-junction at (60 m, 40 m). Market Street, a high street, runs west to east
through it on two segments; Mill Lane, a local street, runs north from it. The junction is
signalised, with six movements, a signal plan of four groups and a signalised crossing on each of
two arms. The north-west block holds a memory precinct lot and a corner lot, on which a
four-storey shophouse stands: a chamfered corner under 1.2 m, a set-back top storey, a light
well, a bakery with three lit vitrines and awnings, a bookshop, flats above, a service door at the
back, plant and a tank on the roof. The streets carry lanes, parking, a loading bay, cycle stands,
paint, a lamp, a bench, three signal poles and a London plane.

Run from the repository root to rewrite the files; ``tests/test_grammar_city_fixture.py`` holds
the committed files to exactly what this produces::

    uv run python tests/fixtures/city-v2/build_fixture.py
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import uuid
from pathlib import Path

from exulanica.grammar.catalogs import catalog_digest
from exulanica.grammar.contract import DeclaredSemantics
from exulanica.grammar.geometry import Extent, edge_run_length, ring_centroid
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES
from exulanica.grammar.grammars.city.catalogs import entry_fields, form_parts, load_city_catalogs
from exulanica.grammar.grammars.city.common import SIDE_CODES, SURFACE_ROLE_CODES, FormPart
from exulanica.grammar.grammars.city.corners import corner_box
from exulanica.grammar.grammars.city.descriptor import CITY_DESCRIPTOR_PATH, CITY_SURFACE
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.document import (
    GrammarRecords,
    TileDocument,
    descriptor_sha256,
    document_bytes,
    record_sort_key,
)
from exulanica.grammar.grammars.city.facade import (
    FACADE_TIER_STRIDE,
    Awning,
    BayLayout,
    EntranceRecord,
    FacadeRecord,
    GroundBayRecord,
    GroundPanel,
    Moulding,
    OpeningGrid,
    facade_output_digest,
)
from exulanica.grammar.grammars.city.massing import MassingRecord, RooftopObjectRecord, Tier
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord, scaled_module_mm
from exulanica.grammar.grammars.city.parcels import Frontage, ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    RoadMarkingRecord,
    SignalGroup,
    SignalHead,
    SignalRecord,
    Stripe,
)
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.city.tile import (
    EMPTY_EDIT_DELTA_DIGEST,
    HALO_RADIUS_MM,
    GrammarPin,
    TileRecord,
)
from exulanica.grammar.grammars.city.vitrine import InteriorBackingRecord, VitrineRecord
from exulanica.grammar.parameters import ParameterBinding
from exulanica.grammar.shapes import describe_shapes
from exulanica.grammar.subjects import subject_identity

HERE = Path(__file__).resolve().parent
DOCUMENT_PATH = HERE / "tile-document.json"
SHAPES_PATH = HERE / "record-shapes.json"

SEED = hashlib.sha256(b"exulanica city vocabulary v2 fixture").hexdigest()
CITY = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/fixture/city-v2"))
#: The traffic lane's signal-plan catalog, assets/catalogs/traffic/signal-plan.v1.json as
#: committed at lane/traffic 22162316: the SHA-256 of its bytes. The city grammar never reads that
#: catalog; the record carries the key and this digest, and traffic resolves durations.
SIGNAL_PLAN_KEY = "fixed_two_phase_60s"
SIGNAL_PLAN_CATALOG_SHA256 = "5a428368b682ddf4147bf84c48ec56e6979bc85fdc920b8eab08279739b1c8be"

CATALOGS = load_city_catalogs()


def identity(kind: str, owner: str, ordinal: int) -> str:
    return subject_identity(
        grammar_id="city",
        root_identity=CITY,
        subject_kind=kind,
        owner_identity=owner,
        ordinal=ordinal,
    )


def catalog(catalog_id: str) -> object:
    return next(item for item in CATALOGS if item.catalog_id == catalog_id)


def entry(catalog_id: str, key: str) -> dict[str, object]:
    return entry_fields(catalog(catalog_id), key)  # type: ignore[arg-type]


def box(*points: tuple[int, int, int]) -> Extent:
    xs, ys, zs = zip(*points, strict=True)
    return Extent(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def turned(dx: int, dy: int, local_x: int, local_y: int) -> tuple[int, int]:
    """A local offset turned by an axis-aligned unit direction. Only axis directions are used."""
    if (dx, dy) == (1, 0):
        return local_x, local_y
    if (dx, dy) == (-1, 0):
        return -local_x, -local_y
    if (dx, dy) == (0, 1):
        return -local_y, local_x
    if (dx, dy) == (0, -1):
        return local_y, -local_x
    raise ValueError("the fixture turns objects by axis directions only")


def parts_extent(
    x: int, y: int, z: int, facing: tuple[int, int], parts: tuple[FormPart, ...]
) -> Extent:
    corners = []
    for part in parts:
        half_x, half_y = (part.size_x_mm + 1) // 2, (part.size_y_mm + 1) // 2
        for sx in (-half_x, half_x):
            for sy in (-half_y, half_y):
                wx, wy = turned(*facing, part.offset_x_mm + sx, part.offset_y_mm + sy)
                for sz in (part.offset_z_mm, part.offset_z_mm + part.size_z_mm):
                    corners.append((x + wx, y + wy, z + sz))
    return box(*corners)


# -------------------------------------------------------------------------------------------
# The district, the network and the block

DISTRICT = identity("district", CITY, 0)
district = DistrictRecord(
    identity=DISTRICT,
    district_ordinal=0,
    boundary_mm=((10_000, 10_000), (120_000, 10_000), (120_000, 120_000), (10_000, 120_000)),
    driving_side="right",
    extent=Extent(10_000, 10_000, -95, 120_000, 120_000, 22_585),
)

NODE_POINTS = {
    "west": (20_000, 40_000, 0),
    "junction": (60_000, 40_000, 0),
    "east": (100_000, 40_000, 0),
    "north": (60_000, 80_000, 0),
}
NODE_ORDINALS = {"west": 0, "junction": 1, "east": 2, "north": 3}
NODES = {name: identity("street_node", CITY, ordinal) for name, ordinal in NODE_ORDINALS.items()}
nodes = [
    StreetNodeRecord(NODES[name], NODE_ORDINALS[name], *NODE_POINTS[name], box(NODE_POINTS[name]))
    for name in NODE_ORDINALS
]

SEGMENTS = {
    name: identity("street_segment", CITY, ordinal)
    for ordinal, name in enumerate(("s0", "s1", "s2"))
}
STREETS = {
    name: identity("street", CITY, ordinal) for ordinal, name in enumerate(("market", "mill"))
}

segments = [
    StreetSegmentRecord(
        identity=SEGMENTS["s0"],
        segment_ordinal=0,
        street_identity=STREETS["market"],
        district_identity=DISTRICT,
        start_node_identity=NODES["west"],
        end_node_identity=NODES["junction"],
        centreline_mm=(NODE_POINTS["west"], NODE_POINTS["junction"]),
        length_mm=40_000,
        hierarchy="high_street",
        carriageway_width_mm=9_500,
        camber_millionths=20_000,
        speed_limit_mm_s=8_333,
        extent=Extent(20_000, 35_250, -95, 60_000, 44_750, 0),
    ),
    StreetSegmentRecord(
        identity=SEGMENTS["s1"],
        segment_ordinal=1,
        street_identity=STREETS["market"],
        district_identity=DISTRICT,
        start_node_identity=NODES["junction"],
        end_node_identity=NODES["east"],
        centreline_mm=(NODE_POINTS["junction"], NODE_POINTS["east"]),
        length_mm=40_000,
        hierarchy="high_street",
        carriageway_width_mm=9_500,
        camber_millionths=20_000,
        speed_limit_mm_s=8_333,
        extent=Extent(60_000, 35_250, -95, 100_000, 44_750, 0),
    ),
    StreetSegmentRecord(
        identity=SEGMENTS["s2"],
        segment_ordinal=2,
        street_identity=STREETS["mill"],
        district_identity=DISTRICT,
        start_node_identity=NODES["junction"],
        end_node_identity=NODES["north"],
        centreline_mm=(NODE_POINTS["junction"], NODE_POINTS["north"]),
        length_mm=40_000,
        hierarchy="local_street",
        carriageway_width_mm=6_500,
        camber_millionths=29_231,
        speed_limit_mm_s=8_333,
        extent=Extent(56_750, 40_000, -95, 63_250, 80_000, 0),
    ),
]
streets = [
    StreetRecord(
        STREETS["market"],
        0,
        "market_street",
        "Market Street",
        (SEGMENTS["s0"], SEGMENTS["s1"]),
        Extent(20_000, 35_250, -95, 100_000, 44_750, 0),
    ),
    StreetRecord(
        STREETS["mill"],
        1,
        "mill_lane",
        "Mill Lane",
        (SEGMENTS["s2"],),
        Extent(56_750, 40_000, -95, 63_250, 80_000, 0),
    ),
]

BLOCK = identity("block", CITY, 0)
BLOCK_RING = ((20_000, 48_950), (53_050, 48_950), (53_050, 80_000), (20_000, 80_000))
block = BlockRecord(
    BLOCK,
    0,
    DISTRICT,
    BLOCK_RING,
    *ring_centroid(BLOCK_RING),
    135,
    Extent(20_000, 48_950, 135, 53_050, 80_000, 135),
)


def curb_id(segment: str, side: str) -> str:
    return identity("curb_edge", SEGMENTS[segment], SIDE_CODES[side])


CURBS = {
    f"{segment}{side[0]}": curb_id(segment, side)
    for segment in SEGMENTS
    for side in ("left", "right")
}


def curb(segment, side, block_ids, line, footway, crossfall, gutter, next_ids, radius, extent):
    return CurbEdgeRecord(
        identity=curb_id(segment, side),
        segment_identity=SEGMENTS[segment],
        side=side,
        block_identity=block_ids,
        kerb_line_mm=line,
        kerb_height_mm=150,
        kerb_width_mm=200,
        gutter_width_mm=gutter,
        footway_width_mm=footway,
        footway_crossfall_millionths=crossfall,
        next_curb_identity=next_ids,
        corner_radius_mm=radius,
        extent=extent,
    )


curbs = [
    curb(
        "s0",
        "left",
        (BLOCK,),
        ((20_000, 44_750, -95), (50_750, 44_750, -95)),
        4_000,
        20_000,
        300,
        (CURBS["s2l"],),
        6_000,
        Extent(20_000, 44_750, -95, 50_750, 48_950, 135),
    ),
    curb(
        "s0",
        "right",
        (),
        ((20_000, 35_250, -95), (60_000, 35_250, -95)),
        4_000,
        20_000,
        300,
        (),
        0,
        Extent(20_000, 31_050, -95, 60_000, 35_250, 135),
    ),
    curb(
        "s1",
        "left",
        (),
        ((69_250, 44_750, -95), (100_000, 44_750, -95)),
        4_000,
        20_000,
        300,
        (),
        0,
        Extent(69_250, 44_750, -95, 100_000, 48_950, 135),
    ),
    curb(
        "s1",
        "right",
        (),
        ((60_000, 35_250, -95), (100_000, 35_250, -95)),
        4_000,
        20_000,
        300,
        (CURBS["s0r"],),
        0,
        Extent(60_000, 31_050, -95, 100_000, 35_250, 135),
    ),
    curb(
        "s2",
        "left",
        (BLOCK,),
        ((56_750, 50_750, -95), (56_750, 80_000, -95)),
        3_500,
        22_858,
        250,
        (),
        0,
        Extent(53_050, 50_750, -95, 56_750, 80_000, 135),
    ),
    curb(
        "s2",
        "right",
        (),
        ((63_250, 50_750, -95), (63_250, 80_000, -95)),
        3_500,
        22_858,
        250,
        (CURBS["s1l"],),
        6_000,
        Extent(63_250, 50_750, -95, 66_950, 80_000, 135),
    ),
]


def corner_covered(record: CurbEdgeRecord) -> CurbEdgeRecord:
    """A curb stating a radius owns its corner, so its extent grows to the corner's box."""
    for next_identity in record.next_curb_identity:
        follower = next(item for item in curbs if item.identity == next_identity)
        box = corner_box(record, follower)
        if box is not None:
            record = dataclasses.replace(record, extent=covering(record.extent, box))
    return record


JUNCTION = identity("junction", NODES["junction"], 0)
SIGNAL = identity("signal", JUNCTION, 0)
CROSSINGS = {
    "s0": identity("crossing", SEGMENTS["s0"], 0),
    "s2": identity("crossing", SEGMENTS["s2"], 0),
}
crossings = [
    CrossingRecord(
        CROSSINGS["s0"],
        SEGMENTS["s0"],
        0,
        "signalised",
        28_000,
        3_000,
        ((48_000, 35_250, -95), (48_000, 44_750, -95)),
        6,
        (SIGNAL,),
        Extent(46_500, 35_250, -95, 49_500, 44_750, 0),
    ),
    CrossingRecord(
        CROSSINGS["s2"],
        SEGMENTS["s2"],
        0,
        "signalised",
        13_000,
        3_000,
        ((56_750, 53_000, -95), (63_250, 53_000, -95)),
        6,
        (SIGNAL,),
        Extent(56_750, 51_500, -95, 63_250, 54_500, 0),
    ),
]


def lane_id(segment: str, index: int) -> str:
    return identity("lane", SEGMENTS[segment], index)


def lane(segment, index, use, direction, width, line, start, end, turns, left, right, extent):
    return LaneRecord(
        lane_id(segment, index),
        SEGMENTS[segment],
        index,
        use,
        direction,
        width,
        line,
        start,
        end,
        turns,
        left,
        right,
        extent,
    )


lanes = [
    lane(
        "s0",
        0,
        "parking",
        "none",
        2_400,
        ((20_000, 43_250, -65), (50_750, 43_250, -65)),
        0,
        30_750,
        (),
        "none",
        "solid",
        Extent(20_000, 42_050, -65, 50_750, 44_450, -65),
    ),
    lane(
        "s0",
        1,
        "general",
        "backward",
        3_250,
        ((56_750, 40_425, -8), (20_000, 40_425, -8)),
        36_750,
        0,
        ("straight",),
        "solid",
        "dashed",
        Extent(20_000, 38_800, -8, 56_750, 42_050, -8),
    ),
    lane(
        "s0",
        2,
        "general",
        "forward",
        3_250,
        ((20_000, 37_175, -56), (46_000, 37_175, -56)),
        0,
        26_000,
        ("left", "straight"),
        "dashed",
        "none",
        Extent(20_000, 35_550, -56, 46_000, 38_800, -56),
    ),
    lane(
        "s1",
        0,
        "parking",
        "none",
        2_400,
        ((69_250, 43_250, -65), (100_000, 43_250, -65)),
        9_250,
        40_000,
        (),
        "none",
        "solid",
        Extent(69_250, 42_050, -65, 100_000, 44_450, -65),
    ),
    lane(
        "s1",
        1,
        "general",
        "backward",
        3_250,
        ((100_000, 40_425, -8), (74_000, 40_425, -8)),
        40_000,
        14_000,
        ("straight", "right"),
        "solid",
        "dashed",
        Extent(74_000, 38_800, -8, 100_000, 42_050, -8),
    ),
    lane(
        "s1",
        2,
        "general",
        "forward",
        3_250,
        ((63_250, 37_175, -56), (100_000, 37_175, -56)),
        3_250,
        40_000,
        ("straight",),
        "dashed",
        "none",
        Extent(63_250, 35_550, -56, 100_000, 38_800, -56),
    ),
    lane(
        "s2",
        0,
        "general",
        "backward",
        3_000,
        ((58_500, 80_000, -43), (58_500, 55_000, -43)),
        40_000,
        15_000,
        ("left", "right"),
        "none",
        "dashed",
        Extent(57_000, 55_000, -43, 60_000, 80_000, -43),
    ),
    lane(
        "s2",
        1,
        "general",
        "forward",
        3_000,
        ((61_500, 44_750, -43), (61_500, 80_000, -43)),
        4_750,
        40_000,
        ("straight",),
        "dashed",
        "none",
        Extent(60_000, 44_750, -43, 63_000, 80_000, -43),
    ),
]
LANES = {(record.segment_identity, record.lane_index): record for record in lanes}


def lane_of(segment: str, index: int) -> LaneRecord:
    return LANES[(SEGMENTS[segment], index)]


connection_specs = [
    (
        ("s0", 2),
        ("s1", 2),
        "straight",
        (lane_of("s0", 2).centreline_mm[-1], lane_of("s1", 2).centreline_mm[0]),
    ),
    (
        ("s1", 1),
        ("s0", 1),
        "straight",
        (lane_of("s1", 1).centreline_mm[-1], lane_of("s0", 1).centreline_mm[0]),
    ),
    (
        ("s0", 2),
        ("s2", 1),
        "left",
        (
            lane_of("s0", 2).centreline_mm[-1],
            (61_500, 37_175, -50),
            lane_of("s2", 1).centreline_mm[0],
        ),
    ),
    (
        ("s1", 1),
        ("s2", 1),
        "right",
        (
            lane_of("s1", 1).centreline_mm[-1],
            (61_500, 40_425, -8),
            lane_of("s2", 1).centreline_mm[0],
        ),
    ),
    (
        ("s2", 0),
        ("s1", 2),
        "left",
        (
            lane_of("s2", 0).centreline_mm[-1],
            (58_500, 37_175, -56),
            lane_of("s1", 2).centreline_mm[0],
        ),
    ),
    (
        ("s2", 0),
        ("s0", 1),
        "right",
        (
            lane_of("s2", 0).centreline_mm[-1],
            (58_500, 40_425, -8),
            lane_of("s0", 1).centreline_mm[0],
        ),
    ),
]
connections = [
    LaneConnectionRecord(
        identity("lane_connection", JUNCTION, ordinal),
        JUNCTION,
        ordinal,
        lane_of(*source).identity,
        lane_of(*target).identity,
        movement,
        path,
        box(*path),
    )
    for ordinal, (source, target, movement, path) in enumerate(connection_specs)
]
CONNECTIONS = [record.identity for record in connections]

junction = JunctionRecord(
    JUNCTION,
    NODES["junction"],
    "signalised",
    (SEGMENTS["s1"], SEGMENTS["s2"], SEGMENTS["s0"]),
    (SIGNAL,),
    Extent(56_750, 35_250, -95, 63_250, 44_750, 0),
)
approaches = [
    JunctionApproachRecord(
        identity("junction_approach", JUNCTION, ordinal),
        JUNCTION,
        SEGMENTS[segment],
        ordinal,
        "signal",
        rank,
    )
    for ordinal, (segment, rank) in enumerate((("s1", 0), ("s2", 1), ("s0", 0)))
]


def furniture_id(curb_key: str, ordinal: int) -> str:
    return identity("street_furniture", CURBS[curb_key], ordinal)


FURNITURE = {
    "bench": furniture_id("s0l", 0),
    "lamp": furniture_id("s0l", 1),
    "walk_s0": furniture_id("s0l", 2),
    "signal_s0": furniture_id("s0r", 0),
    "walk_s2": furniture_id("s2l", 0),
    "stand_a": furniture_id("s2l", 1),
    "stand_b": furniture_id("s2l", 2),
}

signal = SignalRecord(
    identity=SIGNAL,
    controls_identity=JUNCTION,
    plan=SIGNAL_PLAN_KEY,
    plan_catalog_sha256=SIGNAL_PLAN_CATALOG_SHA256,
    offset_ms=0,
    groups=(
        SignalGroup("phase_a", tuple(CONNECTIONS[:4]), ()),
        SignalGroup("phase_b", tuple(CONNECTIONS[4:]), ()),
        SignalGroup("walk_a", (), (CROSSINGS["s0"],)),
        SignalGroup("walk_b", (), (CROSSINGS["s2"],)),
    ),
    heads=(
        SignalHead(FURNITURE["signal_s0"], CONNECTIONS[0]),
        SignalHead(FURNITURE["walk_s0"], CROSSINGS["s0"]),
        SignalHead(FURNITURE["walk_s2"], CROSSINGS["s2"]),
    ),
)

parking = [
    ParkingSpaceRecord(
        identity("parking_space", CURBS["s0l"], 0),
        CURBS["s0l"],
        SEGMENTS["s0"],
        0,
        "general",
        "carriageway",
        1,
        ((30_000, 42_050), (36_000, 42_050), (36_000, 44_450), (30_000, 44_450)),
        (lane_of("s0", 0).identity,),
        lane_of("s0", 1).identity,
        10_000,
        16_000,
        (),
        Extent(30_000, 42_050, -65, 36_000, 44_450, -65),
    ),
    ParkingSpaceRecord(
        identity("parking_space", CURBS["s1l"], 0),
        CURBS["s1l"],
        SEGMENTS["s1"],
        0,
        "loading",
        "carriageway",
        1,
        ((80_000, 42_050), (88_000, 42_050), (88_000, 44_450), (80_000, 44_450)),
        (lane_of("s1", 0).identity,),
        lane_of("s1", 1).identity,
        20_000,
        28_000,
        (),
        Extent(80_000, 42_050, -65, 88_000, 44_450, -65),
    ),
    ParkingSpaceRecord(
        identity("parking_space", CURBS["s2l"], 0),
        CURBS["s2l"],
        SEGMENTS["s2"],
        0,
        "cycle_stand",
        "footway",
        4,
        ((55_150, 59_300), (55_950, 59_300), (55_950, 61_700), (55_150, 61_700)),
        (),
        lane_of("s2", 0).identity,
        19_000,
        22_000,
        (FURNITURE["stand_a"], FURNITURE["stand_b"]),
        Extent(55_150, 59_300, 77, 55_950, 61_700, 77),
    ),
]


def stripe(x0: int, y0: int, x1: int, y1: int, z: int) -> Stripe:
    return Stripe(((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)))


markings = [
    RoadMarkingRecord(
        identity("road_marking", SEGMENTS["s0"], 0),
        SEGMENTS["s0"],
        0,
        "lane_line",
        (stripe(20_000, 38_750, 23_000, 38_850, -24), stripe(30_000, 38_750, 33_000, 38_850, -24)),
        Extent(20_000, 38_750, -24, 33_000, 38_850, -24),
    ),
    RoadMarkingRecord(
        identity("road_marking", lane_of("s0", 2).identity, 0),
        lane_of("s0", 2).identity,
        0,
        "stop_line",
        (stripe(45_700, 35_550, 46_000, 38_800, -56),),
        Extent(45_700, 35_550, -56, 46_000, 38_800, -56),
    ),
    RoadMarkingRecord(
        identity("road_marking", CROSSINGS["s0"], 0),
        CROSSINGS["s0"],
        0,
        "crossing_stripe",
        (stripe(46_500, 35_250, 46_700, 44_750, -95), stripe(49_300, 35_250, 49_500, 44_750, -95)),
        Extent(46_500, 35_250, -95, 49_500, 44_750, -95),
    ),
]

# -------------------------------------------------------------------------------------------
# Lots and the building

PRECINCT = identity("parcel", BLOCK, 0)
CORNER_LOT = identity("parcel", BLOCK, 1)
PRECINCT_RING = ((33_050, 48_950), (41_050, 48_950), (41_050, 66_950), (33_050, 66_950))
CORNER_RING = ((41_050, 48_950), (53_050, 48_950), (53_050, 66_950), (41_050, 66_950))
parcels = [
    ParcelRecord(
        PRECINCT,
        BLOCK,
        0,
        "memory_precinct",
        PRECINCT_RING,
        *ring_centroid(PRECINCT_RING),
        135,
        (Frontage(0, CURBS["s0l"], 8_000),),
        8_000,
        10,
        4_000,
        Extent(33_050, 48_950, 135, 41_050, 66_950, 135),
    ),
    ParcelRecord(
        CORNER_LOT,
        BLOCK,
        1,
        "building",
        CORNER_RING,
        *ring_centroid(CORNER_RING),
        135,
        (Frontage(0, CURBS["s0l"], 12_000), Frontage(1, CURBS["s2l"], 18_000)),
        30_000,
        12,
        6_000,
        Extent(41_050, 48_950, 135, 53_050, 66_950, 135),
    ),
]

BUILDING = identity("building", CORNER_LOT, 0)
BASE = 285
GROUND = 4_500
UPPER = 3_200
FOOTPRINT = (
    (41_050, 48_950),
    (52_250, 48_950),
    (53_050, 49_750),
    (53_050, 62_950),
    (41_050, 62_950),
)
UPPER_RING = ((41_050, 50_950), (53_050, 50_950), (53_050, 62_950), (41_050, 62_950))
LIGHT_WELL = ((41_950, 60_050), (43_950, 60_050), (43_950, 62_050), (41_950, 62_050))
building = MassingRecord(
    identity=BUILDING,
    parcel_identity=CORNER_LOT,
    building_ordinal=0,
    base_elevation_mm=BASE,
    typology="shophouse",
    era="prewar_masonry",
    storeys=4,
    ground_storey_height_mm=GROUND,
    upper_storey_height_mm=UPPER,
    tiers=(Tier(0, 2, FOOTPRINT, (LIGHT_WELL,), 900), Tier(3, 3, UPPER_RING, (LIGHT_WELL,), 900)),
    roof_family="flat_parapet",
    roof_form="flat",
    ridge_mm=(),
    roof_rise_mm=0,
    extent=Extent(41_050, 48_950, 135, 53_050, 62_950, 15_285),
)
ROOF_Z = BASE + GROUND + 3 * UPPER


def rooftop(ordinal: int, kind: str, x: int, y: int, clearance: int) -> RooftopObjectRecord:
    parts = form_parts(entry("rooftop-object", kind)["parts"])
    return RooftopObjectRecord(
        identity("rooftop_object", BUILDING, ordinal),
        BUILDING,
        ordinal,
        kind,
        x,
        y,
        ROOF_Z,
        1,
        0,
        parts,
        clearance,
        parts_extent(x, y, ROOF_Z, (1, 0), parts),
    )


rooftops = [
    rooftop(0, "hvac_unit", 44_550, 53_950, 2_400),
    rooftop(1, "water_tank", 49_550, 55_950, 1_650),
]

# -------------------------------------------------------------------------------------------
# Facades, ground bays, entrances

FACADE_PARAMETERS = {spec.name for spec in CITY_SURFACE.parameters.for_stage("facade")}
FRONT_VALUES = {
    "awning_present": "yes",
    "awning_projection_mm": 1_200,
    "door_width_mm": 1_200,
    "door_height_mm": 2_400,
    "awning_valance_mm": 250,
    "bay_pitch_mm": 2_800,
    "cornice_height_mm": 450,
    "cornice_projection_mm": 350,
    "entrance_recess_mm": 900,
    "fascia_height_mm": 800,
    "head_band_mm": 200,
    "head_projection_mm": 60,
    "head_rise_mm": 250,
    "head_treatment": "arch",
    "opening_height_mm": 1_600,
    "opening_width_mm": 1_200,
    "reveal_depth_mm": 180,
    "sill_height_mm": 900,
    "sill_projection_mm": 60,
    "sill_thickness_mm": 80,
    "stall_riser_height_mm": 600,
    "string_course_height_mm": 150,
    "string_course_projection_mm": 60,
    "threshold_height_mm": 150,
    "transom_height_mm": 500,
}
REAR_VALUES = {
    **FRONT_VALUES,
    "opening_width_mm": 1_000,
    "head_treatment": "lintel",
    "head_rise_mm": 0,
    "bay_pitch_mm": 3_000,
}
#: The two values a scope set rather than the facade stage deriving them.
BOUND = {"cornice_height_mm": "district", "reveal_depth_mm": "building"}
assert set(FRONT_VALUES) == FACADE_PARAMETERS, sorted(FACADE_PARAMETERS ^ set(FRONT_VALUES))


def bindings(values: dict[str, object]) -> tuple[ParameterBinding, ...]:
    return tuple(
        ParameterBinding(name, values[name], BOUND.get(name, "derive")) for name in sorted(values)
    )


def grid(storeys, width, offset, values):
    return OpeningGrid(
        storeys=storeys,
        u_offset_mm=offset,
        width_mm=width,
        height_mm=values["opening_height_mm"],
        sill_height_mm=values["sill_height_mm"],
        reveal_depth_mm=values["reveal_depth_mm"],
        sill_projection_mm=values["sill_projection_mm"],
        sill_thickness_mm=values["sill_thickness_mm"],
        head_treatment=values["head_treatment"],
        head_rise_mm=values["head_rise_mm"],
        head_band_mm=values["head_band_mm"],
        head_projection_mm=values["head_projection_mm"],
    )


LOWER_COURSES = (Moulding(4_500, 4_650, 60), Moulding(7_700, 7_800, 40))
LOWER_CORNICE = (Moulding(10_450, 10_600, 120), Moulding(10_600, 10_900, 350))
UPPER_CORNICE = (Moulding(13_650, 13_800, 120), Moulding(13_800, 14_100, 350))
SEMANTICS = DeclaredSemantics("facade", CITY_GRAMMAR.semantics.admissible_uses)


class Face:
    def __init__(
        self,
        tier,
        edge,
        exposure,
        faces,
        layout,
        openings,
        courses,
        cornice,
        neighbour_top,
        values,
        extent,
    ):
        self.tier, self.edge = tier, edge
        self.identity = identity("facade", BUILDING, tier * FACADE_TIER_STRIDE + edge)
        ring = building.tiers[tier].ring_mm
        self.run = edge_run_length(ring, edge)
        self.start = ring[edge]
        self.end = ring[(edge + 1) % len(ring)]
        self.exposure, self.faces, self.layout = exposure, faces, layout
        self.openings, self.courses, self.cornice = openings, courses, cornice
        self.neighbour_top, self.values, self.extent = neighbour_top, values, extent
        self.bays: list[GroundBayRecord] = []
        self.entrances: list[EntranceRecord] = []

    def record(self) -> FacadeRecord:
        tier = building.tiers[self.tier]
        draft = FacadeRecord(
            building_identity=BUILDING,
            grammar_version=2,
            parameters=bindings(self.values),
            seed=SEED,
            output_digest="0" * 64,
            declared_semantics=SEMANTICS,
            identity=self.identity,
            facade_ordinal=self.tier * FACADE_TIER_STRIDE + self.edge,
            tier_ordinal=self.tier,
            edge_ordinal=self.edge,
            exposure=self.exposure,
            faces_segment_identity=(SEGMENTS[self.faces[0]],) if self.faces else (),
            faces_curb_identity=(CURBS[self.faces[1]],) if self.faces else (),
            run_length_mm=self.run,
            first_storey=tier.first_storey,
            last_storey=tier.last_storey,
            band_top_mm=GROUND if tier.first_storey == 0 else 0,
            bays=self.layout,
            openings=self.openings,
            string_courses=self.courses,
            cornice=self.cornice,
            neighbour_top_mm=self.neighbour_top,
            extent=self.extent,
        )
        digest = facade_output_digest(draft, tuple(self.bays), tuple(self.entrances))
        return dataclasses.replace(draft, output_digest=digest)

    def point(self, u: int) -> tuple[int, int]:
        (x0, y0), (x1, y1) = self.start, self.end
        return x0 + (x1 - x0) * u // self.run, y0 + (y1 - y0) * u // self.run


LOWER_Z = (BASE, BASE + GROUND + 2 * UPPER)
UPPER_Z = (LOWER_Z[1], LOWER_Z[1] + UPPER)
south = Face(
    0,
    0,
    "frontage",
    ("s0", "s0l"),
    BayLayout(4, 2_800, 0, 0),
    (grid((1, 2), 1_200, 800, FRONT_VALUES),),
    LOWER_COURSES,
    LOWER_CORNICE,
    0,
    FRONT_VALUES,
    Extent(41_050, 47_750, LOWER_Z[0], 52_250, 49_850, LOWER_Z[1]),
)
chamfer = Face(
    0,
    1,
    "frontage",
    ("s0", "s0l"),
    BayLayout(0, 0, 1_131, 0),
    (),
    LOWER_COURSES,
    LOWER_CORNICE,
    0,
    FRONT_VALUES,
    Extent(51_900, 48_600, LOWER_Z[0], 53_400, 50_100, LOWER_Z[1]),
)
east = Face(
    0,
    2,
    "frontage",
    ("s2", "s2l"),
    BayLayout(5, 2_640, 0, 0),
    (grid((1, 2), 1_200, 720, FRONT_VALUES),),
    LOWER_COURSES,
    LOWER_CORNICE,
    0,
    FRONT_VALUES,
    Extent(52_150, 49_750, LOWER_Z[0], 54_250, 62_950, LOWER_Z[1]),
)
rear = Face(
    0,
    3,
    "rear",
    (),
    BayLayout(4, 3_000, 0, 0),
    (grid((1, 2), 1_000, 1_000, REAR_VALUES),),
    (),
    (),
    0,
    REAR_VALUES,
    Extent(41_050, 62_770, LOWER_Z[0], 53_050, 63_010, LOWER_Z[1]),
)
party = Face(
    0,
    4,
    "party_wall",
    (),
    BayLayout(0, 0, 14_000, 0),
    (),
    (),
    (),
    0,
    FRONT_VALUES,
    Extent(41_050, 48_950, LOWER_Z[0], 41_050, 62_950, LOWER_Z[1]),
)
top_south = Face(
    1,
    0,
    "frontage",
    ("s0", "s0l"),
    BayLayout(4, 3_000, 0, 0),
    (grid((3,), 1_200, 900, FRONT_VALUES),),
    (),
    UPPER_CORNICE,
    0,
    FRONT_VALUES,
    Extent(41_050, 50_600, UPPER_Z[0], 53_050, 51_130, UPPER_Z[1]),
)
top_east = Face(
    1,
    1,
    "frontage",
    ("s2", "s2l"),
    BayLayout(4, 3_000, 0, 0),
    (grid((3,), 1_200, 900, FRONT_VALUES),),
    (),
    UPPER_CORNICE,
    0,
    FRONT_VALUES,
    Extent(52_870, 50_950, UPPER_Z[0], 53_400, 62_950, UPPER_Z[1]),
)
top_rear = Face(
    1,
    2,
    "rear",
    (),
    BayLayout(4, 3_000, 0, 0),
    (grid((3,), 1_000, 1_000, REAR_VALUES),),
    (),
    (),
    0,
    REAR_VALUES,
    Extent(41_050, 62_770, UPPER_Z[0], 53_050, 63_010, UPPER_Z[1]),
)
top_party = Face(
    1,
    3,
    "party_wall",
    (),
    BayLayout(0, 0, 12_000, 0),
    (),
    (),
    (),
    0,
    FRONT_VALUES,
    Extent(41_050, 50_950, UPPER_Z[0], 41_050, 62_950, UPPER_Z[1]),
)
FACES = (south, chamfer, east, rear, party, top_south, top_east, top_rear, top_party)

SHOP = (
    ("stall_riser", 0, 600, 0),
    ("glazing", 600, 3_200, 0),
    ("transom", 3_200, 3_700, 0),
    ("fascia", 3_700, 4_500, 0),
)
AWNING = (Awning(3_650, 2_900, 1_200, 250),)


def shopfront(u: int, width: int) -> tuple[GroundPanel, ...]:
    return tuple(
        GroundPanel(role, u, u + width, low, high, recess) for role, low, high, recess in SHOP
    )


def bay(face: Face, ordinal: int, kind: str, panels, awning, extent) -> GroundBayRecord:
    record = GroundBayRecord(
        identity("ground_bay", face.identity, ordinal),
        face.identity,
        ordinal,
        kind,
        face.layout.margin_start_mm + ordinal * face.layout.pitch_mm,
        face.layout.pitch_mm,
        panels,
        awning,
        extent,
    )
    face.bays.append(record)
    return record


def entrance(face: Face, ordinal: int, bay_record, centre, width, height, recess, approach, extent):
    x, y = face.point(centre)
    record = EntranceRecord(
        identity("entrance", face.identity, ordinal),
        face.identity,
        bay_record.identity,
        ordinal,
        centre,
        width,
        height,
        recess,
        150,
        x,
        y,
        BASE,
        approach,
        extent,
    )
    face.entrances.append(record)
    return record


BAND_Z = (BASE, BASE + GROUND)
south_bays = [
    bay(
        south,
        0,
        "shopfront",
        shopfront(0, 2_800),
        AWNING,
        Extent(41_050, 47_750, BAND_Z[0], 43_850, 48_950, BAND_Z[1]),
    ),
    bay(
        south,
        1,
        "entrance",
        (
            GroundPanel("wall", 2_800, 3_350, 0, 3_700, 0),
            GroundPanel("door", 3_350, 5_050, 0, 3_200, 900),
            GroundPanel("transom", 3_350, 5_050, 3_200, 3_700, 900),
            GroundPanel("wall", 5_050, 5_600, 0, 3_700, 0),
            GroundPanel("fascia", 2_800, 5_600, 3_700, 4_500, 0),
        ),
        (),
        Extent(43_850, 48_950, BAND_Z[0], 46_650, 49_850, BAND_Z[1]),
    ),
    bay(
        south,
        2,
        "shopfront",
        shopfront(5_600, 2_800),
        AWNING,
        Extent(46_650, 47_750, BAND_Z[0], 49_450, 48_950, BAND_Z[1]),
    ),
    bay(
        south,
        3,
        "shopfront",
        shopfront(8_400, 2_800),
        AWNING,
        Extent(49_450, 47_750, BAND_Z[0], 52_250, 48_950, BAND_Z[1]),
    ),
]
east_bays = [
    bay(
        east,
        0,
        "shopfront",
        shopfront(0, 2_640),
        AWNING,
        Extent(53_050, 49_750, BAND_Z[0], 54_250, 52_390, BAND_Z[1]),
    ),
    bay(
        east,
        1,
        "entrance",
        (
            GroundPanel("wall", 2_640, 3_160, 0, 4_500, 0),
            GroundPanel("door", 3_160, 4_760, 0, 3_200, 600),
            GroundPanel("transom", 3_160, 4_760, 3_200, 3_700, 600),
            GroundPanel("wall", 3_160, 4_760, 3_700, 4_500, 0),
            GroundPanel("wall", 4_760, 5_280, 0, 4_500, 0),
        ),
        (),
        Extent(52_450, 52_390, BAND_Z[0], 53_050, 55_030, BAND_Z[1]),
    ),
    bay(
        east,
        2,
        "shopfront",
        shopfront(5_280, 2_640),
        (),
        Extent(53_050, 55_030, BAND_Z[0], 53_050, 57_670, BAND_Z[1]),
    ),
    bay(
        east,
        3,
        "entrance",
        (
            GroundPanel("wall", 7_920, 8_390, 0, 3_700, 0),
            GroundPanel("door", 8_390, 10_090, 0, 3_200, 900),
            GroundPanel("transom", 8_390, 10_090, 3_200, 3_700, 900),
            GroundPanel("wall", 10_090, 10_560, 0, 3_700, 0),
            GroundPanel("fascia", 7_920, 10_560, 3_700, 4_500, 0),
        ),
        (),
        Extent(52_150, 57_670, BAND_Z[0], 53_050, 60_310, BAND_Z[1]),
    ),
    bay(
        east,
        4,
        "shopfront",
        shopfront(10_560, 2_640),
        (),
        Extent(53_050, 60_310, BAND_Z[0], 53_050, 62_950, BAND_Z[1]),
    ),
]
rear_bays = [
    bay(
        rear,
        ordinal,
        "blank",
        (GroundPanel("wall", 3_000 * ordinal, 3_000 * ordinal + 3_000, 0, 4_500, 0),),
        (),
        Extent(
            53_050 - 3_000 * ordinal - 3_000,
            62_950,
            BAND_Z[0],
            53_050 - 3_000 * ordinal,
            62_950,
            BAND_Z[1],
        ),
    )
    for ordinal in range(3)
] + [
    bay(
        rear,
        3,
        "service",
        (
            GroundPanel("wall", 9_000, 10_000, 0, 4_500, 0),
            GroundPanel("door", 10_000, 11_000, 0, 2_400, 0),
            GroundPanel("wall", 10_000, 11_000, 2_400, 4_500, 0),
            GroundPanel("wall", 11_000, 12_000, 0, 4_500, 0),
        ),
        (),
        Extent(41_050, 62_950, BAND_Z[0], 44_050, 62_950, BAND_Z[1]),
    ),
]
shop_door = entrance(
    south,
    0,
    south_bays[1],
    4_200,
    1_700,
    3_200,
    900,
    (CURBS["s0l"],),
    Extent(44_400, 48_950, 135, 46_100, 49_850, BASE + 3_200),
)
flats_door = entrance(
    east,
    0,
    east_bays[1],
    3_960,
    1_600,
    3_200,
    600,
    (CURBS["s2l"],),
    Extent(52_450, 52_910, 135, 53_050, 54_510, BASE + 3_200),
)
books_door = entrance(
    east,
    1,
    east_bays[3],
    9_240,
    1_700,
    3_200,
    900,
    (CURBS["s2l"],),
    Extent(52_150, 58_140, 135, 53_050, 59_840, BASE + 3_200),
)
service_door = entrance(
    rear,
    0,
    rear_bays[3],
    10_500,
    1_000,
    2_400,
    0,
    (),
    Extent(42_050, 62_950, 135, 43_050, 62_950, BASE + 2_400),
)
facades = [face.record() for face in FACES]
ground_bays = south_bays + east_bays + rear_bays
entrances = [shop_door, flats_door, books_door, service_door]

# -------------------------------------------------------------------------------------------
# Vitrines and premises


def vitrine(bay_record: GroundBayRecord, face: Face, fitout: str, units: int, light: int, extent):
    unit = form_parts(entry("fitout", fitout)["parts"])
    parts = tuple(
        dataclasses.replace(part, offset_x_mm=part.offset_x_mm + 950 * index)
        for index in range(units)
        for part in unit
    )
    return VitrineRecord(
        identity("vitrine", bay_record.identity, 0),
        bay_record.identity,
        face.identity,
        BUILDING,
        bay_record.u_start_mm,
        bay_record.width_mm,
        600,
        2_600,
        900,
        fitout,
        light,
        parts,
        extent,
    )


# One plane behind each face that has openings: the near wall of the rooms behind it. Its band is
# what the face's openings reach, by the rule in `exulanica.grammar.grammars.city.vitrine`.
BACKING_DEPTH_MM = 800
BACKING_LIGHT = 120_000


def backing(face: Face) -> InteriorBackingRecord:
    sills, heads = [], []
    for grid in face.openings:
        for storey in grid.storeys:
            floor = GROUND + (storey - 1) * UPPER
            sill = floor + grid.sill_height_mm
            sills.append(sill)
            heads.append(sill + grid.height_mm + grid.head_rise_mm)
    sill, height = min(sills), max(heads) - min(sills)
    dx, dy = face.end[0] - face.start[0], face.end[1] - face.start[1]
    inward = (-((dy > 0) - (dy < 0)), (dx > 0) - (dx < 0))
    xs = [face.start[0], face.end[0]]
    ys = [face.start[1], face.end[1]]
    xs += [x + inward[0] * BACKING_DEPTH_MM for x in xs]
    ys += [y + inward[1] * BACKING_DEPTH_MM for y in ys]
    return InteriorBackingRecord(
        identity("interior_backing", face.identity, 0),
        face.identity,
        BUILDING,
        0,
        face.run,
        sill,
        height,
        BACKING_DEPTH_MM,
        BACKING_LIGHT,
        Extent(min(xs), min(ys), BASE + sill, max(xs), max(ys), BASE + sill + height),
    )


backings = [backing(face) for face in FACES if face.openings]


VITRINE_Z = (BASE + 600, BASE + 3_200)
vitrines = [
    vitrine(
        south_bays[0],
        south,
        "bakery_counter",
        3,
        700_000,
        Extent(41_050, 48_950, VITRINE_Z[0], 43_850, 49_850, VITRINE_Z[1]),
    ),
    vitrine(
        south_bays[2],
        south,
        "bakery_counter",
        3,
        700_000,
        Extent(46_650, 48_950, VITRINE_Z[0], 49_450, 49_850, VITRINE_Z[1]),
    ),
    vitrine(
        south_bays[3],
        south,
        "bakery_counter",
        3,
        700_000,
        Extent(49_450, 48_950, VITRINE_Z[0], 52_250, 49_850, VITRINE_Z[1]),
    ),
    vitrine(
        east_bays[0],
        east,
        "bakery_counter",
        2,
        700_000,
        Extent(52_150, 49_750, VITRINE_Z[0], 53_050, 52_390, VITRINE_Z[1]),
    ),
    vitrine(
        east_bays[2],
        east,
        "book_shelves",
        2,
        600_000,
        Extent(52_150, 55_030, VITRINE_Z[0], 53_050, 57_670, VITRINE_Z[1]),
    ),
    vitrine(
        east_bays[4],
        east,
        "book_shelves",
        2,
        600_000,
        Extent(52_150, 60_310, VITRINE_Z[0], 53_050, 62_950, VITRINE_Z[1]),
    ),
]

GROUND_EXTENT = Extent(41_050, 48_950, BASE, 53_050, 62_950, BASE + GROUND)
premises = [
    PremisesRecord(
        identity("premises", BUILDING, 0),
        BUILDING,
        0,
        "bakery",
        ("bakery",),
        ("Bakery",),
        0,
        0,
        60_000_000,
        tuple(sorted(item.identity for item in (*south_bays, east_bays[0]))),
        tuple(sorted((shop_door.identity, service_door.identity))),
        GROUND_EXTENT,
    ),
    PremisesRecord(
        identity("premises", BUILDING, 1),
        BUILDING,
        1,
        "bookshop",
        ("books",),
        ("Books",),
        0,
        0,
        40_000_000,
        tuple(sorted(east_bays[index].identity for index in (2, 3, 4))),
        (books_door.identity,),
        GROUND_EXTENT,
    ),
    PremisesRecord(
        identity("premises", BUILDING, 2),
        BUILDING,
        2,
        "residential",
        (),
        (),
        1,
        3,
        420_000_000,
        (east_bays[1].identity,),
        (flats_door.identity,),
        Extent(41_050, 48_950, BASE + GROUND, 53_050, 62_950, ROOF_Z),
    ),
]

# -------------------------------------------------------------------------------------------
# Streetlife


def placed(
    curb_key: str,
    ordinal: int,
    kind: str,
    along: int,
    offset: int,
    x: int,
    y: int,
    z: int,
    facing: tuple[int, int],
) -> StreetFurnitureRecord:
    item = entry("street-furniture", kind)
    parts = form_parts(item["parts"])
    return StreetFurnitureRecord(
        furniture_id(curb_key, ordinal),
        CURBS[curb_key],
        SEGMENTS[curb_key[:2]],
        ordinal,
        kind,
        along,
        offset,
        x,
        y,
        z,
        *facing,
        parts,
        item["exclusion_radius_mm"],
        parts_extent(x, y, z, facing, parts),
    )


furniture = [
    placed("s0l", 0, "bench", 18_000, 1_500, 38_000, 46_250, 81, (1, 0)),
    placed("s0l", 1, "street_lamp", 26_000, 600, 46_000, 45_350, 63, (0, -1)),
    placed("s0l", 2, "pedestrian_signal", 30_000, 600, 50_000, 45_350, 63, (0, -1)),
    placed("s0r", 0, "traffic_signal", 26_500, 600, 46_500, 34_650, 63, (-1, 0)),
    placed("s2l", 0, "pedestrian_signal", 16_000, 600, 56_150, 56_000, 64, (1, 0)),
    placed("s2l", 1, "cycle_stand", 20_000, 1_200, 55_550, 60_000, 77, (0, 1)),
    placed("s2l", 2, "cycle_stand", 21_000, 1_200, 55_550, 61_000, 77, (0, 1)),
]
assert [item.identity for item in furniture] == list(FURNITURE.values())

TREE_PARTS = (
    FormPart("prism", "trunk", 0, 0, 0, 300, 300, 2_500, 1_000_000, 8, 1),
    FormPart("ellipsoid", "canopy", 0, 0, 2_500, 6_000, 6_000, 5_000, 1_000_000, 16, 8),
)
trees = [
    StreetTreeRecord(
        identity("street_tree", CURBS["s0l"], 0),
        CURBS["s0l"],
        SEGMENTS["s0"],
        0,
        "platanus_x_acerifolia",
        22_000,
        900,
        42_000,
        45_650,
        69,
        ((41_400, 45_050), (42_600, 45_050), (42_600, 46_250), (41_400, 46_250)),
        TREE_PARTS,
        1_500,
        parts_extent(42_000, 45_650, 69, (1, 0), TREE_PARTS),
    ),
]

# -------------------------------------------------------------------------------------------
# Materials

FACADE_SURFACES = {
    south.identity: {
        "wall": "brick_running_bond",
        "ground_band": "limestone_ashlar",
        "stall_riser": "limestone_ashlar",
        "fascia": "painted_render",
        "shopfront_frame": "storefront_metal",
        "trim": "limestone_ashlar",
        "awning": "storefront_metal",
    },
    chamfer.identity: {
        "wall": "brick_running_bond",
        "ground_band": "limestone_ashlar",
        "trim": "limestone_ashlar",
    },
    east.identity: {
        "wall": "brick_running_bond",
        "ground_band": "limestone_ashlar",
        "stall_riser": "limestone_ashlar",
        "fascia": "painted_render",
        "shopfront_frame": "storefront_metal",
        "trim": "limestone_ashlar",
        "awning": "storefront_metal",
    },
    rear.identity: {"wall": "brick_running_bond", "ground_band": "brick_running_bond"},
    party.identity: {"wall": "brick_running_bond", "party_wall_scar": "painted_render"},
    top_south.identity: {"wall": "brick_running_bond", "trim": "limestone_ashlar"},
    top_east.identity: {"wall": "brick_running_bond", "trim": "limestone_ashlar"},
    top_rear.identity: {"wall": "brick_running_bond"},
    top_party.identity: {"wall": "brick_running_bond", "party_wall_scar": "painted_render"},
}
WEATHERED = (250_000, 150_000, 400_000)


def material(surface: str, kind: str, role: str, key: str, weathering=(0, 0, 0), bands=(0, 0)):
    values = entry("material", key)
    return SurfaceMaterialRecord(
        identity=identity("surface_material", surface, SURFACE_ROLE_CODES[role]),
        surface_identity=surface,
        surface_kind=kind,
        role=role,
        material=key,
        texture_set_id=values["texture_set_id"],
        repeat_size_millionths=1_000_000,
        uv_rotation_urad=0,
        uv_offset_u_mm=0,
        uv_offset_v_mm=0,
        course_module_mm=scaled_module_mm(values["course_module_mm"], 1_000_000),
        mortar_module_mm=scaled_module_mm(values["mortar_module_mm"], 1_000_000),
        soiling_gradient_millionths=weathering[0],
        base_weathering_millionths=weathering[1],
        reveal_darkening_millionths=weathering[2],
        soil_band_bottom_mm=bands[0],
        soil_band_edge_mm=bands[1],
    )


materials = [
    material(face, "city.facade", role, key, WEATHERED)
    for face, roles in FACADE_SURFACES.items()
    for role, key in roles.items()
]
materials += [
    material(BUILDING, "city.massing", "roof", "cast_concrete"),
    material(BUILDING, "city.massing", "parapet", "limestone_ashlar", WEATHERED),
    material(BUILDING, "city.massing", "wall", "brick_running_bond", WEATHERED),
    material(JUNCTION, "city.junction", "carriageway", "carriageway_asphalt"),
    material(BLOCK, "city.block", "lot", "cast_concrete"),
    *[material(parcel.identity, "city.parcel", "lot", "footway_paving") for parcel in parcels],
    *[
        material(crossing.identity, "city.crossing", "crossing", "carriageway_asphalt")
        for crossing in crossings
    ],
]
for segment in segments:
    materials.append(
        material(segment.identity, "city.street_segment", "carriageway", "carriageway_asphalt")
    )
    materials.append(material(segment.identity, "city.street_segment", "gutter", "kerb_stone"))
for record in curbs:
    materials.append(material(record.identity, "city.curb_edge", "kerb", "kerb_stone"))
    materials.append(material(record.identity, "city.curb_edge", "footway", "footway_paving"))
OBJECT_MATERIALS = {
    "hvac_unit": {"object_primary": "storefront_metal", "object_secondary": "cast_concrete"},
    "water_tank": {"object_primary": "storefront_metal", "object_secondary": "storefront_metal"},
    "street_lamp": {"object_primary": "storefront_metal", "object_secondary": "storefront_metal"},
    "bench": {"object_primary": "cast_concrete", "object_secondary": "storefront_metal"},
    "cycle_stand": {"object_primary": "storefront_metal"},
    "traffic_signal": {
        "object_primary": "storefront_metal",
        "object_secondary": "storefront_metal",
    },
    "pedestrian_signal": {
        "object_primary": "storefront_metal",
        "object_secondary": "storefront_metal",
    },
    "bakery_counter": {"object_primary": "cast_concrete", "object_secondary": "storefront_metal"},
    "book_shelves": {"object_primary": "storefront_metal"},
}
for obj in rooftops:
    for role, key in OBJECT_MATERIALS[obj.object_class].items():
        materials.append(material(obj.identity, "city.rooftop_object", role, key))
for item in furniture:
    for role, key in OBJECT_MATERIALS[item.furniture_class].items():
        materials.append(material(item.identity, "city.street_furniture", role, key))
for item in vitrines:
    for role, key in OBJECT_MATERIALS[item.fitout].items():
        materials.append(material(item.identity, "city.vitrine", role, key))

# -------------------------------------------------------------------------------------------
# Owners' extents cover what they anchor


def covering(*extents: Extent) -> Extent:
    """The smallest extent containing every one given: how an owner's extent covers its parts."""
    return Extent(
        min(extent.min_x_mm for extent in extents),
        min(extent.min_y_mm for extent in extents),
        min(extent.min_z_mm for extent in extents),
        max(extent.max_x_mm for extent in extents),
        max(extent.max_y_mm for extent in extents),
        max(extent.max_z_mm for extent in extents),
    )


curbs = [corner_covered(record) for record in curbs]
segments = [
    dataclasses.replace(
        segment,
        extent=covering(
            segment.extent,
            *(
                item.extent
                for item in (*curbs, *lanes, *crossings, *parking, *furniture, *trees)
                if item.segment_identity == segment.identity
            ),
        ),
    )
    for segment in segments
]
streets = [
    dataclasses.replace(
        street,
        extent=covering(
            *(segment.extent for segment in segments if segment.street_identity == street.identity)
        ),
    )
    for street in streets
]
junction = dataclasses.replace(
    junction, extent=covering(junction.extent, *(item.extent for item in connections))
)
building = dataclasses.replace(
    building,
    extent=covering(
        building.extent,
        *(item.extent for item in (*rooftops, *facades, *premises, *vitrines)),
    ),
)
parcels = [
    dataclasses.replace(parcel, extent=covering(parcel.extent, building.extent))
    if parcel.identity == building.parcel_identity
    else parcel
    for parcel in parcels
]

# -------------------------------------------------------------------------------------------
# Terrain, the tile and the document

SAMPLES = 17
terrain = TerrainRecord(
    identity("terrain", CITY, 0),
    0,
    0,
    0,
    8_000,
    SAMPLES,
    (0,) * (SAMPLES * SAMPLES),
    (0,) * (SAMPLES * SAMPLES),
    "sw_ne",
    Extent(0, 0, 0, 128_000, 128_000, 0),
)

tile = TileRecord(
    city_seed=SEED,
    grammar_versions=(GrammarPin("city", 2, descriptor_sha256(CITY_DESCRIPTOR_PATH)),),
    catalog_digest=catalog_digest(CATALOGS),
    tile_x=0,
    tile_y=0,
    lod=0,
    tile_size_mm=128_000,
    halo_radius_mm=HALO_RADIUS_MM,
    ownership_rule="anchor_floor_division",
    halo_rule="extent_meets_grown_square",
    edit_delta_digest=EMPTY_EDIT_DELTA_DIGEST,
)

OWNED = [
    *nodes,
    *segments,
    block,
    *curbs,
    *crossings,
    *lanes,
    junction,
    *approaches,
    *connections,
    signal,
    *parking,
    *markings,
    *parcels,
    building,
    *rooftops,
    *facades,
    *ground_bays,
    *entrances,
    *materials,
    *furniture,
    *trees,
    *vitrines,
    *backings,
    *premises,
    terrain,
]
HALO = [district, *streets]


def build_document() -> TileDocument:
    return TileDocument(
        tile=tile,
        grammars=(
            GrammarRecords(
                grammar_id="city",
                grammar_version=2,
                descriptor_sha256=descriptor_sha256(CITY_DESCRIPTOR_PATH),
                declared_semantics=CITY_GRAMMAR.semantics,
                subject_identity=CITY,
                owned=tuple(sorted(OWNED, key=record_sort_key)),
                halo=tuple(sorted(HALO, key=record_sort_key)),
                external=(),
            ),
        ),
    )


def shape_table_bytes() -> bytes:
    return (json.dumps(describe_shapes(CITY_SHAPES), indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    DOCUMENT_PATH.write_bytes(document_bytes(build_document()))
    SHAPES_PATH.write_bytes(shape_table_bytes())
    print(DOCUMENT_PATH, len(DOCUMENT_PATH.read_bytes()), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
