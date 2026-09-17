"""What the network compiler reads: the city's road records, resolved for traffic.

A :class:`RoadInput` is derived data, never a record shape and never a second source of truth.
The one function that builds it from city records is
:func:`exulanica.traffic.city_roads.road_input_from_city`; the compiler reads nothing else. Every
item keeps the identity of the city record it came from, and the compiler, the simulation's
events and its receipts name records by those identities.

What the conversion has already settled, so the compiler never repeats it:

* plan geometry only: every point is ``(x, y)`` in integer millimetres, the city frame's plan;
* the vehicle classes a lane carries (from ``lane-use-access``) and a parking space admits (from
  ``parking-kind-access``); a lane that carries no traffic is not an input at all;
* a lane's direction as ``forward`` or ``backward`` along its segment;
* a signal's offset in whole seconds, and its plan checked against the signal-plan bytes traffic
  holds;
* a crossing's control, ``signalised`` exactly when a signal releases it, else
  ``marked_priority``, and its centre point on the segment centreline at its offset;
* a parking space's access stretch as positions along its access lane, measured the way the
  compiler measures a path: from the lane's first point, with ceiling piece lengths.

Everything is sorted by identity, so an input does not depend on the order records arrived in.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ApproachInput",
    "ConnectionInput",
    "CrossingInput",
    "JunctionInput",
    "LaneInput",
    "NodeInput",
    "ParkingInput",
    "RoadInput",
    "SegmentInput",
    "SignalGroupInput",
    "SignalInput",
]

Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class NodeInput:
    identity: str
    ordinal: int
    point: Point


@dataclass(frozen=True, slots=True)
class SegmentInput:
    identity: str
    ordinal: int
    start_node: str
    end_node: str
    centreline: tuple[Point, ...]
    speed_limit_mm_per_s: int


@dataclass(frozen=True, slots=True)
class LaneInput:
    identity: str
    segment: str
    lane_index: int
    #: ``forward`` runs with the segment, start node to end node; ``backward`` against it.
    direction: str
    width_mm: int
    #: In the direction of travel. The last point is the stop line of a lane that ends at a
    #: junction.
    centreline: tuple[Point, ...]
    classes: tuple[str, ...]
    #: The movements allowed where the lane ends, in the city's order.
    turns: tuple[str, ...]
    lane_use: str


@dataclass(frozen=True, slots=True)
class JunctionInput:
    identity: str
    node: str
    #: The city's junction-control key, which is a right-of-way policy key.
    policy: str


@dataclass(frozen=True, slots=True)
class ApproachInput:
    identity: str
    junction: str
    segment: str
    ordinal: int
    control: str
    rank: int


@dataclass(frozen=True, slots=True)
class ConnectionInput:
    identity: str
    junction: str
    ordinal: int
    from_lane: str
    to_lane: str
    turn: str
    path: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class SignalGroupInput:
    group: str
    connections: tuple[str, ...]
    crossings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignalInput:
    identity: str
    junction: str
    plan: str
    offset_s: int
    groups: tuple[SignalGroupInput, ...]


@dataclass(frozen=True, slots=True)
class CrossingInput:
    identity: str
    segment: str
    ordinal: int
    offset_mm: int
    width_mm: int
    line: tuple[Point, Point]
    #: The point on the segment centreline at ``offset_mm``, by the city's run-length rule.
    centre: Point
    control: str
    #: The signal that releases it, or empty.
    signal: str


@dataclass(frozen=True, slots=True)
class ParkingInput:
    identity: str
    segment: str
    kind: str
    placement: str
    capacity: int
    footprint: tuple[Point, ...]
    classes: tuple[str, ...]
    access_lane: str
    #: Positions along the access lane, low before high, whatever the lane's direction.
    access_start_mm: int
    access_end_mm: int


@dataclass(frozen=True, slots=True)
class RoadInput:
    #: The admitted identity of the city the records belong to.
    city: str
    driving_side: str
    nodes: tuple[NodeInput, ...]
    segments: tuple[SegmentInput, ...]
    lanes: tuple[LaneInput, ...]
    junctions: tuple[JunctionInput, ...]
    approaches: tuple[ApproachInput, ...]
    connections: tuple[ConnectionInput, ...]
    signals: tuple[SignalInput, ...]
    crossings: tuple[CrossingInput, ...]
    spaces: tuple[ParkingInput, ...]
