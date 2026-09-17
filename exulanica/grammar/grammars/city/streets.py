"""Streets: a planar graph, its blocks, its kerbs and its crossings, as records. No generator.

A street is never "ground minus buildings". The stage states the network and, because blocks are
the faces of that network, the blocks too; the parcels stage then subdivides them. Traffic
records (lanes, junctions, signals, parking and markings) belong to the same stage and are
declared in :mod:`~exulanica.grammar.grammars.city.roads`.

**Geometry is written once, by the generator.**

* A segment's ``centreline_mm`` runs from its start node to its end node, with ``z`` on each
  point; it is the carriageway's crown line, and the carriageway is centred on it.
* A curb edge's ``kerb_line_mm`` is the foot of the kerb face, at gutter level, digitised in the
  segment's direction, from the tangent point where one corner arc ends to the tangent point where
  the next begins. The carriageway surface runs between the two kerb lines of its segment; a
  junction fills the rest with fillet arcs of each curb's ``corner_radius_mm`` (the tessellator's
  own arc rule). The kerb face rises ``kerb_height_mm`` from the kerb line, the kerb top is
  ``kerb_width_mm`` wide, and the footway then runs ``footway_width_mm`` to the frontage line.
* **Footway width is the source; the frontage line is derived and checked.** A block's ring is
  the frontage line, and the document check holds each straight kerb piece to lie
  ``kerb_width_mm + footway_width_mm`` from it, to within the rounding of one integer normal.
* **Profiles.** The carriageway surface is planar across each strip between the crown line and a
  kerb line, so ``camber_millionths`` is stated and checked as the fall from crown to kerb line
  over half the carriageway width, floored. The gutter is the ``gutter_width_mm`` strip of the
  carriageway next to the kerb and follows that same plane; it differs only in material. The
  footway rises away from the kerb: at distance ``w`` from the kerb top's back edge its surface
  is ``kerb top + w * footway_crossfall_millionths // 10**6``.
* A crossing's ``line_mm`` runs kerb line to kerb line through the crossing's centre, and the
  crossing is the band ``width_mm`` wide around it, along the street.

The kerb height bound, 100 to 180 mm, is a gate of the target architecture and is checked on
every curb record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import (
    Extent,
    extent_contains_point,
    extent_contains_ring,
    polyline_run_length,
    ring_centroid,
)
from exulanica.grammar.grammars.city import roads
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import SIDE_CODES, SIDES, extent_field

__all__ = [
    "BLOCK_SHAPE",
    "CROSSING_SHAPE",
    "CURB_SHAPE",
    "CURB_SIDES",
    "KERB_HEIGHT_MAXIMUM_MM",
    "KERB_HEIGHT_MINIMUM_MM",
    "NODE_SHAPE",
    "SEGMENT_SHAPE",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "STREET_SHAPE",
    "BlockRecord",
    "CrossingRecord",
    "CurbEdgeRecord",
    "StreetNodeRecord",
    "StreetRecord",
    "StreetSegmentRecord",
]

STAGE_ID: Final = "streets"
STAGE_VERSION: Final = 2
KERB_HEIGHT_MINIMUM_MM: Final = 100
KERB_HEIGHT_MAXIMUM_MM: Final = 180
CURB_SIDES: Final = SIDES
#: The fastest posted limit a record may state: 200 km/h, floored to millimetres per second.
SPEED_LIMIT_MAXIMUM_MM_S: Final = 55_555


def _points_in_extent(name: str, extent: Extent, points: tuple[tuple[int, ...], ...]) -> None:
    for index, point in enumerate(points):
        if not extent_contains_point(extent, *point):
            raise InvalidRecordError(f"{name}[{index}] lies outside the record's extent")


@dataclass(frozen=True, slots=True)
class StreetNodeRecord:
    RECORD_KIND: ClassVar[str] = "city.street_node"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    node_ordinal: int
    x_mm: int
    y_mm: int
    z_mm: int
    #: Exactly the node's point.
    extent: Extent


def _node_extent(record: StreetNodeRecord) -> None:
    point = Extent(record.x_mm, record.y_mm, record.z_mm, record.x_mm, record.y_mm, record.z_mm)
    if record.extent != point:
        raise InvalidRecordError("a street node's extent is exactly its point")


NODE_SHAPE: Final = shapes.RecordShape(
    StreetNodeRecord,
    (
        shapes.identity("identity"),
        shapes.integer("node_ordinal", 0),
        shapes.integer("x_mm"),
        shapes.integer("y_mm"),
        shapes.integer("z_mm"),
        extent_field(),
    ),
    rules=(shapes.RecordRule("node_extent_is_point", _node_extent),),
    identity=shapes.IdentityRule("street_node", ordinal_field="node_ordinal"),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class StreetRecord:
    """A named street: the segments that carry one name, in order along it.

    The name is presentation, never identity: a key into the street-name catalog, whose entries
    are authored generic names, and the entry's text.
    """

    RECORD_KIND: ClassVar[str] = "city.street"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    street_ordinal: int
    name: str
    name_text: str
    segment_identities: tuple[str, ...]
    extent: Extent


STREET_SHAPE: Final = shapes.RecordShape(
    StreetRecord,
    (
        shapes.identity("identity"),
        shapes.integer("street_ordinal", 0),
        shapes.key("name", "street-name"),
        shapes.text("name_text"),
        shapes.identities("segment_identities", "city.street_segment", count_minimum=1),
        extent_field(),
    ),
    identity=shapes.IdentityRule("street", ordinal_field="street_ordinal"),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class StreetSegmentRecord:
    RECORD_KIND: ClassVar[str] = "city.street_segment"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    segment_ordinal: int
    street_identity: str
    district_identity: str
    start_node_identity: str
    end_node_identity: str
    #: The crown line, start node to end node, ``(x, y, z)``. Points of a record, not of a mesh.
    centreline_mm: tuple[tuple[int, int, int], ...]
    #: The plan length: the sum of each piece's integer run length.
    length_mm: int
    #: A key into the street-hierarchy catalog. A label: no geometry follows from it.
    hierarchy: str
    #: Kerb line to kerb line: both gutters and every lane, centred on the centreline.
    carriageway_width_mm: int
    camber_millionths: int
    speed_limit_mm_s: int
    extent: Extent


def _segment_geometry(record: StreetSegmentRecord) -> None:
    if record.start_node_identity == record.end_node_identity:
        raise InvalidRecordError("a segment joins two different nodes")
    if record.length_mm != polyline_run_length(record.centreline_mm):
        raise InvalidRecordError("length_mm is the sum of the centreline's integer run lengths")
    _points_in_extent("centreline_mm", record.extent, record.centreline_mm)


SEGMENT_SHAPE: Final = shapes.RecordShape(
    StreetSegmentRecord,
    (
        shapes.identity("identity"),
        shapes.integer("segment_ordinal", 0),
        shapes.identity("street_identity", "city.street"),
        shapes.identity("district_identity", "city.district"),
        shapes.identity("start_node_identity", "city.street_node"),
        shapes.identity("end_node_identity", "city.street_node"),
        shapes.points("centreline_mm", 3, count_minimum=2),
        shapes.integer("length_mm", 1),
        shapes.key("hierarchy", "street-hierarchy"),
        shapes.integer("carriageway_width_mm", 1),
        shapes.integer("camber_millionths", 0, 100_000),
        shapes.integer("speed_limit_mm_s", 1, SPEED_LIMIT_MAXIMUM_MM_S),
        extent_field(),
    ),
    rules=(shapes.RecordRule("segment_geometry", _segment_geometry),),
    identity=shapes.IdentityRule("street_segment", ordinal_field="segment_ordinal"),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class BlockRecord:
    """A face of the street graph: the frontage line round it, and its own ground level."""

    RECORD_KIND: ClassVar[str] = "city.block"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    block_ordinal: int
    district_identity: str
    #: The frontage line, where every footway round the block ends.
    boundary_mm: tuple[tuple[int, int], ...]
    #: :func:`exulanica.grammar.geometry.ring_centroid` of the boundary. The block's anchor.
    centroid_x_mm: int
    centroid_y_mm: int
    #: The level of any part of the block no parcel covers.
    grade_elevation_mm: int
    extent: Extent


def _block_geometry(record: BlockRecord) -> None:
    if (record.centroid_x_mm, record.centroid_y_mm) != ring_centroid(record.boundary_mm):
        raise InvalidRecordError("a block's centroid is the ring centroid of its boundary")
    if not extent_contains_ring(record.extent, record.boundary_mm):
        raise InvalidRecordError("a block's boundary lies inside its extent")


BLOCK_SHAPE: Final = shapes.RecordShape(
    BlockRecord,
    (
        shapes.identity("identity"),
        shapes.integer("block_ordinal", 0),
        shapes.identity("district_identity", "city.district"),
        shapes.ring("boundary_mm"),
        shapes.integer("centroid_x_mm"),
        shapes.integer("centroid_y_mm"),
        shapes.integer("grade_elevation_mm"),
        extent_field(),
    ),
    rules=(shapes.RecordRule("block_geometry", _block_geometry),),
    identity=shapes.IdentityRule("block", ordinal_field="block_ordinal"),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class CurbEdgeRecord:
    """One side of one segment: its kerb, gutter and footway, and the curb that follows it.

    ``next_curb_identity`` names the curb reached by going counter-clockwise round the face this
    curb bounds, and ``corner_radius_mm`` is the fillet between them, 0 where the kerb runs
    straight on; with no next curb (the edge of what was generated) the radius is 0.

    **The corner's tangent points agree with its radius.** Walking counter-clockwise round the face
    takes a left curb's kerb line from its first point to its last and a right curb's from its
    last to its first. The corner runs from ``P``, where this curb's walk ends, to ``Q``, where the
    next curb's begins, leaving along the walk's last piece and joining the next curb's first. With
    radius 0, ``P`` is ``Q``. Otherwise the two pieces turn (left, or right for a concave corner),
    and the arc's centre found from each tangent point agrees within 2 mm on each axis, each centre
    being the tangent point plus the radius along the piece's unit normal toward the turn, every
    component floored, with the piece's length taken as ``isqrt((dx * dx + dy * dy) * 10**12)``
    millionths of a millimetre. The tile document check ``[corner_radius]`` holds it wherever both
    curbs are carried.
    """

    RECORD_KIND: ClassVar[str] = "city.curb_edge"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    segment_identity: str
    side: str
    block_identity: tuple[str, ...]
    kerb_line_mm: tuple[tuple[int, int, int], ...]
    kerb_height_mm: int
    kerb_width_mm: int
    gutter_width_mm: int
    footway_width_mm: int
    footway_crossfall_millionths: int
    next_curb_identity: tuple[str, ...]
    corner_radius_mm: int
    extent: Extent


def _curb_geometry(record: CurbEdgeRecord) -> None:
    if not record.next_curb_identity and record.corner_radius_mm:
        raise InvalidRecordError("a curb with no next curb has no corner radius")
    if record.next_curb_identity == (record.identity,):
        raise InvalidRecordError("a curb edge cannot follow itself")
    _points_in_extent("kerb_line_mm", record.extent, record.kerb_line_mm)


CURB_SHAPE: Final = shapes.RecordShape(
    CurbEdgeRecord,
    (
        shapes.identity("identity"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.choice("side", SIDES),
        shapes.optional_identity("block_identity", "city.block"),
        shapes.points("kerb_line_mm", 3, count_minimum=2),
        shapes.integer("kerb_height_mm", KERB_HEIGHT_MINIMUM_MM, KERB_HEIGHT_MAXIMUM_MM),
        shapes.integer("kerb_width_mm", 100, 600),
        shapes.integer("gutter_width_mm", 0, 900),
        shapes.integer("footway_width_mm", 1_000, 12_000),
        shapes.integer("footway_crossfall_millionths", 0, 50_000),
        shapes.optional_identity("next_curb_identity", "city.curb_edge"),
        shapes.integer("corner_radius_mm", 0, 50_000),
        extent_field(),
    ),
    rules=(shapes.RecordRule("curb_geometry", _curb_geometry),),
    identity=shapes.IdentityRule(
        "curb_edge",
        owner_field="segment_identity",
        ordinal_field="side",
        ordinal_codes=SIDE_CODES,
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class CrossingRecord:
    RECORD_KIND: ClassVar[str] = "city.crossing"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    segment_identity: str
    crossing_ordinal: int
    #: A key into the crossing-type catalog. A label: the band and line below are the geometry.
    crossing_type: str
    #: The crossing's centre, along the centreline from the start node.
    offset_mm: int
    width_mm: int
    line_mm: tuple[tuple[int, int, int], ...]
    #: The kerb's upstand where the crossing meets it: 0 is flush.
    kerb_upstand_mm: int
    signal_identity: tuple[str, ...]
    extent: Extent


def _crossing_geometry(record: CrossingRecord) -> None:
    _points_in_extent("line_mm", record.extent, record.line_mm)


CROSSING_SHAPE: Final = shapes.RecordShape(
    CrossingRecord,
    (
        shapes.identity("identity"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.integer("crossing_ordinal", 0),
        shapes.key("crossing_type", "crossing-type"),
        shapes.integer("offset_mm", 0),
        shapes.integer("width_mm", 1_500, 10_000),
        shapes.points("line_mm", 3, count_minimum=2, count_maximum=2),
        shapes.integer("kerb_upstand_mm", 0, KERB_HEIGHT_MAXIMUM_MM),
        shapes.optional_identity("signal_identity", "city.signal"),
        extent_field(),
    ),
    rules=(shapes.RecordRule("crossing_geometry", _crossing_geometry),),
    identity=shapes.IdentityRule(
        "crossing", owner_field="segment_identity", ordinal_field="crossing_ordinal"
    ),
    extent_field="extent",
)

STAGE: Final = skeleton(
    STAGE_ID,
    STAGE_VERSION,
    NODE_SHAPE,
    STREET_SHAPE,
    SEGMENT_SHAPE,
    BLOCK_SHAPE,
    CURB_SHAPE,
    CROSSING_SHAPE,
    *roads.SHAPES,
)
