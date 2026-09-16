"""Streetlife: kerb-offset placement of street furniture. Record shape only; no generator.

A tree or a lamp is a record, not a renderer loop, because a person can reasonably point at one.
Placement is a rule (a segment, a side, a distance along it and an offset from the kerb) and the
position that rule resolves to. The exclusion tests against frontage, crossings and junction
sightlines need the buildings and the street graph, so they belong to the generator and to the
gate that counts intersections; a record validator cannot see either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.streets import CURB_SIDES
from exulanica.grammar.records import require_integer, require_key, require_record

__all__ = [
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "StreetFurnitureRecord",
    "validate_street_furniture",
]

STAGE_ID: Final = "streetlife"
STAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class StreetFurnitureRecord:
    RECORD_KIND: ClassVar[str] = "city.street_furniture"
    RECORD_VERSION: ClassVar[int] = 1

    item_ordinal: int
    #: A key into a catalog, for example a tree species.
    item_class: str
    segment_ordinal: int
    side: str
    along_mm: int
    kerb_offset_mm: int
    x_mm: int
    y_mm: int


def validate_street_furniture(candidate: object) -> None:
    record = require_record(candidate, StreetFurnitureRecord)
    require_integer("item_ordinal", record.item_ordinal, minimum=0)
    require_key("item_class", record.item_class)
    require_integer("segment_ordinal", record.segment_ordinal, minimum=0)
    if record.side not in CURB_SIDES:
        raise InvalidRecordError(f"side is one of {CURB_SIDES}, got {record.side!r}")
    require_integer("along_mm", record.along_mm, minimum=0)
    require_integer("kerb_offset_mm", record.kerb_offset_mm, minimum=0)
    require_integer("x_mm", record.x_mm)
    require_integer("y_mm", record.y_mm)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (StreetFurnitureRecord, validate_street_furniture))
