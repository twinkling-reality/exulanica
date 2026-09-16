"""Streets: a planar graph as records. Record shapes only; no generator.

A street is never "ground minus buildings". It is a node, a segment with a centreline and a
hierarchy class, and a curb graph around it. The kerb height bound, 100 to 180 mm on every
segment, is a gate of the target architecture and is checked here on every record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import (
    require_increasing,
    require_integer,
    require_key,
    require_pairs,
    require_record,
)

__all__ = [
    "CURB_SIDES",
    "KERB_HEIGHT_MAXIMUM_MM",
    "KERB_HEIGHT_MINIMUM_MM",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "CurbEdgeRecord",
    "StreetNodeRecord",
    "StreetSegmentRecord",
    "validate_curb_edge",
    "validate_street_node",
    "validate_street_segment",
]

STAGE_ID: Final = "streets"
STAGE_VERSION: Final = 1
KERB_HEIGHT_MINIMUM_MM: Final = 100
KERB_HEIGHT_MAXIMUM_MM: Final = 180
CURB_SIDES: Final = ("left", "right")


@dataclass(frozen=True, slots=True)
class StreetNodeRecord:
    RECORD_KIND: ClassVar[str] = "city.street_node"
    RECORD_VERSION: ClassVar[int] = 1

    node_ordinal: int
    x_mm: int
    y_mm: int


@dataclass(frozen=True, slots=True)
class StreetSegmentRecord:
    RECORD_KIND: ClassVar[str] = "city.street_segment"
    RECORD_VERSION: ClassVar[int] = 1

    segment_ordinal: int
    start_node: int
    end_node: int
    #: The centreline as integer points. A polyline in a record, not the vertices of a mesh.
    centreline_mm: tuple[tuple[int, int], ...]
    #: A key into the street-hierarchy catalog.
    hierarchy: str
    carriageway_width_mm: int
    kerb_height_mm: int
    gutter_width_mm: int
    footway_width_mm: int
    corner_radius_mm: int
    #: Where crossings sit, measured along the centreline from its start.
    crossing_offsets_mm: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CurbEdgeRecord:
    """One run of kerb along one side of a segment, linked to the run that follows it."""

    RECORD_KIND: ClassVar[str] = "city.curb_edge"
    RECORD_VERSION: ClassVar[int] = 1

    curb_ordinal: int
    segment_ordinal: int
    side: str
    next_curb_ordinal: int


def validate_street_node(candidate: object) -> None:
    record = require_record(candidate, StreetNodeRecord)
    require_integer("node_ordinal", record.node_ordinal, minimum=0)
    require_integer("x_mm", record.x_mm)
    require_integer("y_mm", record.y_mm)


def validate_street_segment(candidate: object) -> None:
    record = require_record(candidate, StreetSegmentRecord)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    require_integer("start_node", record.start_node, minimum=0)
    require_integer("end_node", record.end_node, minimum=0)
    if record.start_node == record.end_node:
        raise InvalidRecordError("a segment joins two different nodes")
    require_pairs("centreline_mm", record.centreline_mm, minimum_count=2)
    require_key("hierarchy", record.hierarchy)
    require_integer("carriageway_width_mm", record.carriageway_width_mm, minimum=1)
    require_integer(
        "kerb_height_mm",
        record.kerb_height_mm,
        minimum=KERB_HEIGHT_MINIMUM_MM,
        maximum=KERB_HEIGHT_MAXIMUM_MM,
    )
    require_integer("gutter_width_mm", record.gutter_width_mm, minimum=0)
    require_integer("footway_width_mm", record.footway_width_mm, minimum=1)
    require_integer("corner_radius_mm", record.corner_radius_mm, minimum=0)
    require_increasing("crossing_offsets_mm", record.crossing_offsets_mm)


def validate_curb_edge(candidate: object) -> None:
    record = require_record(candidate, CurbEdgeRecord)
    require_integer("curb_ordinal", record.curb_ordinal, minimum=0)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    if record.side not in CURB_SIDES:
        raise InvalidRecordError(f"side is one of {CURB_SIDES}, got {record.side!r}")
    require_integer("next_curb_ordinal", record.next_curb_ordinal, minimum=0)
    if record.next_curb_ordinal == record.curb_ordinal:
        raise InvalidRecordError("a curb edge cannot follow itself")


STAGE: Final = skeleton(
    STAGE_ID,
    STAGE_VERSION,
    (StreetNodeRecord, validate_street_node),
    (StreetSegmentRecord, validate_street_segment),
    (CurbEdgeRecord, validate_curb_edge),
)
