"""The streets stage's traffic records: lanes, junctions, signals, parking and markings.

These are record shapes, written with the traffic lane's requirements, and no generator. The
traffic simulation reads them; it never imports this package's generators, and this package never
imports traffic. Where a traffic catalog decides something (a right-of-way policy, a signal plan's
durations, which vehicle classes a lane or a bay admits) the record carries the city's own key and
traffic maps it:

* ``junction.control`` is a key of the city's junction-control catalog, and traffic's
  right-of-way policies are keyed by the same keys;
* ``lane.lane_use`` and ``parking_space.parking_kind`` are city keys that traffic maps to vehicle
  classes;
* ``signal.plan`` is a key of traffic's signal-plan catalog, and ``plan_catalog_sha256`` is the
  SHA-256 of that catalog file's bytes as the generator read it. Durations are never in a city
  record: traffic resolves them at simulation time from the plan it can prove it holds.

**Lanes are geometry written once.** A lane's ``centreline_mm`` is digitised in its direction of
travel (with the segment for a lane that carries no traffic), and ``start_offset_mm`` and
``end_offset_mm`` are the offsets, along the segment's centreline from its start node, of the
lane's first and last points. For a lane flowing into a junction the last point is its stop line.
A connection's ``path_mm`` starts exactly at its from-lane's last point and ends exactly at its
to-lane's first point. ``lane_index`` counts every lane of a segment from left to right looking
from the start node, lanes that carry no traffic included.

**Approaches.** Each junction states, for each segment it joins, the approach's control
(``signal``, ``stop``, ``yield`` or ``priority``) and its rank; the rank is constant for every
movement from that approach, and turn yielding is traffic's policy, not a record field.

**Parking.** A ``carriageway`` space is a bay of a parking lane, with an explicit footprint and the
stretch of the access lane a vehicle stops in to enter or leave. A ``footway`` space (cycle
parking) is a footprint inside its curb's footway that lists the stands it uses; each stand is
drawn and excluded once, as street furniture, and the space itself draws nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, extent_contains_point, require_ring
from exulanica.grammar.grammars.city.common import (
    APPROACH_CONTROLS,
    MOVEMENTS,
    extent_field,
)

__all__ = [
    "APPROACH_SHAPE",
    "CONNECTION_SHAPE",
    "JUNCTION_SHAPE",
    "LANE_DIRECTIONS",
    "LANE_MARKINGS",
    "LANE_SHAPE",
    "MARKING_KINDS",
    "MARKING_SHAPE",
    "PARKING_PLACEMENTS",
    "PARKING_SHAPE",
    "SHAPES",
    "SIGNAL_SHAPE",
    "JunctionApproachRecord",
    "JunctionRecord",
    "LaneConnectionRecord",
    "LaneRecord",
    "ParkingSpaceRecord",
    "RoadMarkingRecord",
    "SignalGroup",
    "SignalHead",
    "SignalRecord",
    "Stripe",
]

LANE_DIRECTIONS: Final = ("forward", "backward", "none")
LANE_MARKINGS: Final = ("none", "dashed", "solid", "double_solid")
PARKING_PLACEMENTS: Final = ("carriageway", "footway")
MARKING_KINDS: Final = (
    "lane_line",
    "centre_line",
    "edge_line",
    "stop_line",
    "crossing_stripe",
    "bay_line",
)


def _points_in_extent(name: str, extent: Extent, points: tuple[tuple[int, ...], ...]) -> None:
    for index, point in enumerate(points):
        if not extent_contains_point(extent, *point):
            raise InvalidRecordError(f"{name}[{index}] lies outside the record's extent")


@dataclass(frozen=True, slots=True)
class LaneRecord:
    RECORD_KIND: ClassVar[str] = "city.lane"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    segment_identity: str
    lane_index: int
    #: A key into the lane-use catalog, which says whether the lane carries traffic.
    lane_use: str
    direction: str
    width_mm: int
    centreline_mm: tuple[tuple[int, int, int], ...]
    start_offset_mm: int
    end_offset_mm: int
    #: The movements allowed where the lane ends, in the order of ``MOVEMENTS``.
    turns: tuple[str, ...]
    left_marking: str
    right_marking: str
    extent: Extent


def _lane_rules(record: LaneRecord) -> None:
    if record.direction == "backward":
        if record.start_offset_mm <= record.end_offset_mm:
            raise InvalidRecordError("a backward lane starts further along the segment")
    elif record.start_offset_mm >= record.end_offset_mm:
        raise InvalidRecordError("a forward lane, or one with no traffic, runs with the segment")
    if (record.direction == "none") != (not record.turns):
        raise InvalidRecordError("a lane lists turns exactly when it carries traffic")
    _points_in_extent("centreline_mm", record.extent, record.centreline_mm)


LANE_SHAPE: Final = shapes.RecordShape(
    LaneRecord,
    (
        shapes.identity("identity"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.integer("lane_index", 0, 64),
        shapes.key("lane_use", "lane-use"),
        shapes.choice("direction", LANE_DIRECTIONS),
        shapes.integer("width_mm", 1_000, 6_000),
        shapes.points("centreline_mm", 3, count_minimum=2),
        shapes.integer("start_offset_mm", 0),
        shapes.integer("end_offset_mm", 0),
        shapes.choices("turns", MOVEMENTS),
        shapes.choice("left_marking", LANE_MARKINGS),
        shapes.choice("right_marking", LANE_MARKINGS),
        extent_field(),
    ),
    rules=(shapes.RecordRule("lane_direction_and_turns", _lane_rules),),
    identity=shapes.IdentityRule(
        "lane", owner_field="segment_identity", ordinal_field="lane_index"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class JunctionRecord:
    RECORD_KIND: ClassVar[str] = "city.junction"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    node_identity: str
    #: A key into the junction-control catalog; traffic's right-of-way policy has the same key.
    control: str
    #: Every segment meeting the node, counter-clockwise from +x by each one's first piece.
    segment_identities: tuple[str, ...]
    signal_identity: tuple[str, ...]
    extent: Extent


JUNCTION_SHAPE: Final = shapes.RecordShape(
    JunctionRecord,
    (
        shapes.identity("identity"),
        shapes.identity("node_identity", "city.street_node"),
        shapes.key("control", "junction-control"),
        shapes.identities("segment_identities", "city.street_segment", count_minimum=1),
        shapes.optional_identity("signal_identity", "city.signal"),
        extent_field(),
    ),
    identity=shapes.IdentityRule("junction", owner_field="node_identity"),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class JunctionApproachRecord:
    """How one segment enters a junction: its control, its rank (0 is the major road) and the turn
    it must admit.

    ``turning_radius_mm`` is the tightest turn a vehicle leaving this approach may need: the widest
    of the turning radii the lane-use catalog states for this segment's lane uses. The catalog takes
    those from traffic's vehicle classes and names that catalog by digest in each entry's reason;
    the city grammar never reads it. 0 means nothing drives out of this approach.
    """

    RECORD_KIND: ClassVar[str] = "city.junction_approach"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    junction_identity: str
    segment_identity: str
    #: The segment's index in its junction's counter-clockwise list.
    approach_ordinal: int
    control: str
    priority_rank: int
    turning_radius_mm: int


APPROACH_SHAPE: Final = shapes.RecordShape(
    JunctionApproachRecord,
    (
        shapes.identity("identity"),
        shapes.identity("junction_identity", "city.junction"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.integer("approach_ordinal", 0, 64),
        shapes.choice("control", APPROACH_CONTROLS),
        shapes.integer("priority_rank", 0, 16),
        shapes.integer("turning_radius_mm", 0, 30_000),
    ),
    identity=shapes.IdentityRule(
        "junction_approach", owner_field="junction_identity", ordinal_field="approach_ordinal"
    ),
)


@dataclass(frozen=True, slots=True)
class LaneConnectionRecord:
    RECORD_KIND: ClassVar[str] = "city.lane_connection"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    junction_identity: str
    connection_ordinal: int
    from_lane_identity: str
    to_lane_identity: str
    movement: str
    path_mm: tuple[tuple[int, int, int], ...]
    extent: Extent


def _connection_rules(record: LaneConnectionRecord) -> None:
    if record.from_lane_identity == record.to_lane_identity:
        raise InvalidRecordError("a connection joins two different lanes")
    _points_in_extent("path_mm", record.extent, record.path_mm)


CONNECTION_SHAPE: Final = shapes.RecordShape(
    LaneConnectionRecord,
    (
        shapes.identity("identity"),
        shapes.identity("junction_identity", "city.junction"),
        shapes.integer("connection_ordinal", 0),
        shapes.identity("from_lane_identity", "city.lane"),
        shapes.identity("to_lane_identity", "city.lane"),
        shapes.choice("movement", MOVEMENTS),
        shapes.points("path_mm", 3, count_minimum=2),
        extent_field(),
    ),
    rules=(shapes.RecordRule("connection_path", _connection_rules),),
    identity=shapes.IdentityRule(
        "lane_connection", owner_field="junction_identity", ordinal_field="connection_ordinal"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class SignalGroup:
    """One group of a signal plan: the movements and crossings it releases together.

    A pedestrian group lists crossings only.
    """

    group: str
    connection_identities: tuple[str, ...]
    crossing_identities: tuple[str, ...]


def _group_not_empty(group: SignalGroup) -> None:
    if not group.connection_identities and not group.crossing_identities:
        raise InvalidRecordError(f"signal group {group.group} releases something")


SIGNAL_GROUP_SHAPE: Final = shapes.RecordShape(
    SignalGroup,
    (
        shapes.key("group"),
        shapes.identities("connection_identities", "city.lane_connection"),
        shapes.identities("crossing_identities", "city.crossing"),
    ),
    rules=(shapes.RecordRule("signal_group_not_empty", _group_not_empty),),
)


@dataclass(frozen=True, slots=True)
class SignalHead:
    """A signal head: the street furniture record that draws it, and what it shows the way to."""

    furniture_identity: str
    serves_identity: str


SIGNAL_HEAD_SHAPE: Final = shapes.RecordShape(
    SignalHead,
    (
        shapes.identity("furniture_identity", "city.street_furniture"),
        shapes.identity("serves_identity", "city.lane_connection", "city.crossing"),
    ),
)


@dataclass(frozen=True, slots=True)
class SignalRecord:
    RECORD_KIND: ClassVar[str] = "city.signal"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    #: The junction, or the mid-block crossing, this signal controls.
    controls_identity: str
    #: A key of traffic's signal-plan catalog. Not resolvable here, by design.
    plan: str
    #: SHA-256 of the signal-plan catalog file's bytes the generator read.
    plan_catalog_sha256: str
    offset_ms: int
    groups: tuple[SignalGroup, ...]
    heads: tuple[SignalHead, ...]


def _signal_rules(record: SignalRecord) -> None:
    names = [group.group for group in record.groups]
    if len(set(names)) != len(names):
        raise InvalidRecordError("a signal names each plan group once")
    released = [
        identity
        for group in record.groups
        for identity in (*group.connection_identities, *group.crossing_identities)
    ]
    if len(set(released)) != len(released):
        raise InvalidRecordError("a movement or crossing belongs to one group of a signal")


SIGNAL_SHAPE: Final = shapes.RecordShape(
    SignalRecord,
    (
        shapes.identity("identity"),
        shapes.identity("controls_identity", "city.junction", "city.crossing"),
        shapes.key("plan"),
        shapes.hex64("plan_catalog_sha256"),
        shapes.integer("offset_ms", 0, 3_600_000),
        shapes.records("groups", SIGNAL_GROUP_SHAPE, count_minimum=1),
        shapes.records("heads", SIGNAL_HEAD_SHAPE, count_minimum=1),
    ),
    rules=(shapes.RecordRule("signal_groups_distinct", _signal_rules),),
    identity=shapes.IdentityRule("signal", owner_field="controls_identity"),
)


@dataclass(frozen=True, slots=True)
class ParkingSpaceRecord:
    RECORD_KIND: ClassVar[str] = "city.parking_space"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    curb_identity: str
    segment_identity: str
    space_ordinal: int
    #: A key into the parking-kind catalog. A label: ``placement`` and the footprint are geometry.
    parking_kind: str
    placement: str
    #: Vehicles the space holds: 1 for a bay, the bicycles for a cycle stand group.
    capacity: int
    footprint_mm: tuple[tuple[int, int], ...]
    #: The parking lane a carriageway bay belongs to; empty on the footway.
    lane_identity: tuple[str, ...]
    #: The traffic lane a vehicle stops in to enter or leave, and the stretch of it, along the
    #: segment's centreline.
    access_lane_identity: str
    access_start_mm: int
    access_end_mm: int
    #: The stands a footway space uses; empty on the carriageway.
    furniture_identities: tuple[str, ...]
    extent: Extent


def _parking_rules(record: ParkingSpaceRecord) -> None:
    if record.access_start_mm >= record.access_end_mm:
        raise InvalidRecordError("an access stretch starts before it ends")
    if record.placement == "carriageway":
        if len(record.lane_identity) != 1 or record.furniture_identities:
            raise InvalidRecordError("a carriageway space names its parking lane and no stands")
        if record.capacity != 1:
            raise InvalidRecordError("a carriageway bay holds one vehicle")
    elif record.lane_identity or not record.furniture_identities:
        raise InvalidRecordError("a footway space names no lane and at least one stand")
    if len(record.footprint_mm) != 4:
        raise InvalidRecordError("a parking footprint has four corners")
    for x, y in record.footprint_mm:
        if not extent_contains_point(record.extent, x, y):
            raise InvalidRecordError("a parking footprint lies inside its extent")


PARKING_SHAPE: Final = shapes.RecordShape(
    ParkingSpaceRecord,
    (
        shapes.identity("identity"),
        shapes.identity("curb_identity", "city.curb_edge"),
        shapes.identity("segment_identity", "city.street_segment"),
        shapes.integer("space_ordinal", 0),
        shapes.key("parking_kind", "parking-kind"),
        shapes.choice("placement", PARKING_PLACEMENTS),
        shapes.integer("capacity", 1, 256),
        shapes.ring("footprint_mm", count_minimum=4, count_maximum=4),
        shapes.optional_identity("lane_identity", "city.lane"),
        shapes.identity("access_lane_identity", "city.lane"),
        shapes.integer("access_start_mm", 0),
        shapes.integer("access_end_mm", 0),
        shapes.identities("furniture_identities", "city.street_furniture"),
        extent_field(),
    ),
    rules=(shapes.RecordRule("parking_placement", _parking_rules),),
    identity=shapes.IdentityRule(
        "parking_space", owner_field="curb_identity", ordinal_field="space_ordinal"
    ),
    extent_field="extent",
)


@dataclass(frozen=True, slots=True)
class Stripe:
    """One painted rectangle: four ``(x, y, z)`` corners, counter-clockwise in plan."""

    corners: tuple[tuple[int, int, int], ...]


def _stripe_quad(stripe: Stripe) -> None:
    require_ring("stripe corners", tuple((x, y) for x, y, _z in stripe.corners), minimum_count=4)


STRIPE_SHAPE: Final = shapes.RecordShape(
    Stripe,
    (shapes.points("corners", 3, count_minimum=4, count_maximum=4),),
    rules=(shapes.RecordRule("stripe_is_a_plan_quad", _stripe_quad),),
)


@dataclass(frozen=True, slots=True)
class RoadMarkingRecord:
    """Paint, as explicit rectangles. No published texture set is road paint yet, so a marking
    has no material record in this version and draws as unavailable."""

    RECORD_KIND: ClassVar[str] = "city.road_marking"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    #: The segment, junction, crossing, lane or parking space the paint marks.
    marks_identity: str
    marking_ordinal: int
    marking: str
    stripes: tuple[Stripe, ...]
    extent: Extent


def _marking_extent(record: RoadMarkingRecord) -> None:
    for stripe in record.stripes:
        _points_in_extent("stripe corners", record.extent, stripe.corners)


MARKING_SHAPE: Final = shapes.RecordShape(
    RoadMarkingRecord,
    (
        shapes.identity("identity"),
        shapes.identity(
            "marks_identity",
            "city.street_segment",
            "city.junction",
            "city.crossing",
            "city.lane",
            "city.parking_space",
        ),
        shapes.integer("marking_ordinal", 0),
        shapes.choice("marking", MARKING_KINDS),
        shapes.records("stripes", STRIPE_SHAPE, count_minimum=1),
        extent_field(),
    ),
    rules=(shapes.RecordRule("marking_in_extent", _marking_extent),),
    identity=shapes.IdentityRule(
        "road_marking", owner_field="marks_identity", ordinal_field="marking_ordinal"
    ),
    extent_field="extent",
)

SHAPES: Final = (
    LANE_SHAPE,
    JUNCTION_SHAPE,
    APPROACH_SHAPE,
    CONNECTION_SHAPE,
    SIGNAL_SHAPE,
    PARKING_SHAPE,
    MARKING_SHAPE,
)
