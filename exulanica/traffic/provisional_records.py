"""PROVISIONAL road record shapes, until the city vocabulary lane lands them in the grammar.

These classes are the road records the orchestrator approved on 2026-09-16 (traffic proposal 1),
kept here only so the traffic compiler can be built and tested before the city vocabulary lane
writes the real ones into ``exulanica/grammar/grammars/city/streets.py``. They are not a second
source of truth: when the grammar classes exist, this module is deleted and the compiler reads
those. Nothing outside ``exulanica.traffic`` and its tests may import it.

One spelling already follows the city vocabulary rather than the proposal: a movement is
``straight``, not ``through``.

Node and segment records are the grammar's own, imported unchanged. Everything else follows the
grammar's record rules: frozen, integers and strings and tuples only, a kind and a version.
Per-record checks here are shape checks; references between records and all geometry are
checked by :func:`exulanica.traffic.network.compile_network`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.streets import (
    CURB_SIDES,
    StreetNodeRecord,
    StreetSegmentRecord,
    validate_street_node,
    validate_street_segment,
)
from exulanica.grammar.records import (
    require_identity,
    require_increasing,
    require_integer,
    require_key,
    require_pairs,
    require_record,
)
from exulanica.traffic.catalogs import TURNS
from exulanica.traffic.errors import UnsupportedNetworkError

__all__ = [
    "APPROACH_CONTROLS",
    "CROSSING_CONTROLS",
    "DRIVING_SIDES",
    "PARKING_LAYOUTS",
    "RECORD_VALIDATORS",
    "STREET_IDENTITY_NAMESPACE",
    "TRAVEL_DIRECTIONS",
    "CarriagewayLaneRecord",
    "CrossingRecord",
    "JunctionApproachRecord",
    "JunctionRecord",
    "LaneConnectorRecord",
    "ParkingSpaceRecord",
    "RoadRulesRecord",
    "SignalControllerRecord",
    "SignalGroupRecord",
    "StreetNodeRecord",
    "StreetSegmentRecord",
    "street_record_identity",
    "validate_record",
]

DRIVING_SIDES: Final = ("right", "left")
TRAVEL_DIRECTIONS: Final = ("with_segment", "against_segment")
APPROACH_CONTROLS: Final = ("signal", "stop", "yield", "priority")
CROSSING_CONTROLS: Final = ("marked_priority", "signalised")
PARKING_LAYOUTS: Final = ("parallel", "cycle_stand")

STREET_IDENTITY_NAMESPACE: Final = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://exulanica.invalid/grammar/city/streets"
)


def street_record_identity(scope: str, kind: str, *parts: int | str) -> str:
    """The approved proposal-1 identity: uuid5 over ``[scope, kind, *parts]`` in canonical JSON."""
    require_identity("scope", scope)
    require_key("kind", kind)
    for part in parts:
        if type(part) not in (int, str):
            raise UnsupportedNetworkError(f"an identity part is an int or a str, got {part!r}")
    return str(
        uuid.uuid5(STREET_IDENTITY_NAMESPACE, canonical_json([scope, kind, *parts]).decode())
    )


@dataclass(frozen=True, slots=True)
class RoadRulesRecord:
    RECORD_KIND: ClassVar[str] = "city.road_rules"
    RECORD_VERSION: ClassVar[int] = 1

    driving_side: str


@dataclass(frozen=True, slots=True)
class CarriagewayLaneRecord:
    RECORD_KIND: ClassVar[str] = "city.carriageway_lane"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    lane_ordinal: int
    segment_ordinal: int
    direction: str
    lane_index: int
    centreline_mm: tuple[tuple[int, int], ...]
    width_mm: int
    permitted_classes: tuple[str, ...]
    permitted_turns: tuple[str, ...]
    speed_limit_mm_per_h: int


@dataclass(frozen=True, slots=True)
class JunctionRecord:
    RECORD_KIND: ClassVar[str] = "city.junction"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    junction_ordinal: int
    node_ordinal: int
    policy: str


@dataclass(frozen=True, slots=True)
class JunctionApproachRecord:
    RECORD_KIND: ClassVar[str] = "city.junction_approach"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    approach_ordinal: int
    junction_ordinal: int
    segment_ordinal: int
    control: str
    priority_rank: int


@dataclass(frozen=True, slots=True)
class LaneConnectorRecord:
    RECORD_KIND: ClassVar[str] = "city.lane_connector"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    connector_ordinal: int
    junction_ordinal: int
    from_lane_ordinal: int
    to_lane_ordinal: int
    turn: str
    path_mm: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class SignalControllerRecord:
    RECORD_KIND: ClassVar[str] = "city.signal_controller"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    controller_ordinal: int
    junction_ordinal: int
    plan: str
    offset_s: int


@dataclass(frozen=True, slots=True)
class SignalGroupRecord:
    RECORD_KIND: ClassVar[str] = "city.signal_group"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    controller_ordinal: int
    group: str
    connector_ordinals: tuple[int, ...]
    crossing_ordinals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CrossingRecord:
    RECORD_KIND: ClassVar[str] = "city.crossing"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    crossing_ordinal: int
    segment_ordinal: int
    offset_index: int
    control: str
    line_mm: tuple[tuple[int, int], ...]
    width_mm: int


@dataclass(frozen=True, slots=True)
class ParkingSpaceRecord:
    RECORD_KIND: ClassVar[str] = "city.parking_space"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    space_ordinal: int
    segment_ordinal: int
    side: str
    space_index: int
    layout: str
    footprint_mm: tuple[tuple[int, int], ...]
    access_lane_ordinal: int
    access_start_mm: int
    access_end_mm: int
    permitted_classes: tuple[str, ...]


def _choice(name: str, value: object, options: tuple[str, ...]) -> None:
    if value not in options:
        raise UnsupportedNetworkError(f"{name} is one of {options}, got {value!r}")


def _sorted_keys(name: str, value: object, *, order: tuple[str, ...] | None = None) -> None:
    if not isinstance(value, tuple) or not value:
        raise UnsupportedNetworkError(f"{name} is a non-empty tuple of keys")
    for index, item in enumerate(value):
        if order is None:
            require_key(f"{name}[{index}]", item)
        else:
            _choice(f"{name}[{index}]", item, order)
    ranked = sorted(value, key=order.index) if order is not None else sorted(value)
    if list(value) != ranked or len(set(value)) != len(value):
        raise UnsupportedNetworkError(f"{name} is unique and in canonical order")


def _road_rules(candidate: object) -> None:
    record = require_record(candidate, RoadRulesRecord)
    _choice("driving_side", record.driving_side, DRIVING_SIDES)


def _lane(candidate: object) -> None:
    record = require_record(candidate, CarriagewayLaneRecord)
    require_identity("identity", record.identity)
    require_integer("lane_ordinal", record.lane_ordinal, minimum=0)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    _choice("direction", record.direction, TRAVEL_DIRECTIONS)
    require_integer("lane_index", record.lane_index, minimum=0)
    require_pairs("centreline_mm", record.centreline_mm, minimum_count=2)
    require_integer("width_mm", record.width_mm, minimum=1)
    _sorted_keys("permitted_classes", record.permitted_classes)
    _sorted_keys("permitted_turns", record.permitted_turns, order=TURNS)
    require_integer("speed_limit_mm_per_h", record.speed_limit_mm_per_h, minimum=1)


def _junction(candidate: object) -> None:
    record = require_record(candidate, JunctionRecord)
    require_identity("identity", record.identity)
    require_integer("junction_ordinal", record.junction_ordinal, minimum=0)
    require_integer("node_ordinal", record.node_ordinal, minimum=0)
    require_key("policy", record.policy)


def _approach(candidate: object) -> None:
    record = require_record(candidate, JunctionApproachRecord)
    require_identity("identity", record.identity)
    require_integer("approach_ordinal", record.approach_ordinal, minimum=0)
    require_integer("junction_ordinal", record.junction_ordinal, minimum=0)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    _choice("control", record.control, APPROACH_CONTROLS)
    require_integer("priority_rank", record.priority_rank, minimum=0)


def _connector(candidate: object) -> None:
    record = require_record(candidate, LaneConnectorRecord)
    require_identity("identity", record.identity)
    require_integer("connector_ordinal", record.connector_ordinal, minimum=0)
    require_integer("junction_ordinal", record.junction_ordinal, minimum=0)
    require_integer("from_lane_ordinal", record.from_lane_ordinal, minimum=0)
    require_integer("to_lane_ordinal", record.to_lane_ordinal, minimum=0)
    _choice("turn", record.turn, TURNS)
    require_pairs("path_mm", record.path_mm, minimum_count=2)


def _controller(candidate: object) -> None:
    record = require_record(candidate, SignalControllerRecord)
    require_identity("identity", record.identity)
    require_integer("controller_ordinal", record.controller_ordinal, minimum=0)
    require_integer("junction_ordinal", record.junction_ordinal, minimum=0)
    require_key("plan", record.plan)
    require_integer("offset_s", record.offset_s, minimum=0)


def _group(candidate: object) -> None:
    record = require_record(candidate, SignalGroupRecord)
    require_identity("identity", record.identity)
    require_integer("controller_ordinal", record.controller_ordinal, minimum=0)
    require_key("group", record.group)
    require_increasing("connector_ordinals", record.connector_ordinals)
    require_increasing("crossing_ordinals", record.crossing_ordinals)
    if not record.connector_ordinals and not record.crossing_ordinals:
        raise UnsupportedNetworkError("a signal group governs at least one connector or crossing")


def _crossing(candidate: object) -> None:
    record = require_record(candidate, CrossingRecord)
    require_identity("identity", record.identity)
    require_integer("crossing_ordinal", record.crossing_ordinal, minimum=0)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    require_integer("offset_index", record.offset_index, minimum=0)
    _choice("control", record.control, CROSSING_CONTROLS)
    require_pairs("line_mm", record.line_mm, minimum_count=2)
    if len(record.line_mm) != 2 or record.line_mm[0] == record.line_mm[1]:
        raise UnsupportedNetworkError("line_mm is exactly two different points")
    require_integer("width_mm", record.width_mm, minimum=1)


def _parking(candidate: object) -> None:
    record = require_record(candidate, ParkingSpaceRecord)
    require_identity("identity", record.identity)
    require_integer("space_ordinal", record.space_ordinal, minimum=0)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    _choice("side", record.side, CURB_SIDES)
    require_integer("space_index", record.space_index, minimum=0)
    _choice("layout", record.layout, PARKING_LAYOUTS)
    require_pairs("footprint_mm", record.footprint_mm, minimum_count=4)
    if len(record.footprint_mm) != 4:
        raise UnsupportedNetworkError("footprint_mm is exactly four points")
    require_integer("access_lane_ordinal", record.access_lane_ordinal, minimum=0)
    require_integer("access_start_mm", record.access_start_mm, minimum=0)
    require_integer("access_end_mm", record.access_end_mm, minimum=record.access_start_mm + 1)
    _sorted_keys("permitted_classes", record.permitted_classes)


RECORD_VALIDATORS: Final[dict[type, Callable[[object], None]]] = {
    StreetNodeRecord: validate_street_node,
    StreetSegmentRecord: validate_street_segment,
    RoadRulesRecord: _road_rules,
    CarriagewayLaneRecord: _lane,
    JunctionRecord: _junction,
    JunctionApproachRecord: _approach,
    LaneConnectorRecord: _connector,
    SignalControllerRecord: _controller,
    SignalGroupRecord: _group,
    CrossingRecord: _crossing,
    ParkingSpaceRecord: _parking,
}


def validate_record(candidate: object) -> None:
    validator = RECORD_VALIDATORS.get(type(candidate))
    if validator is None:
        raise UnsupportedNetworkError(f"traffic reads no record type {type(candidate).__name__}")
    validator(candidate)
