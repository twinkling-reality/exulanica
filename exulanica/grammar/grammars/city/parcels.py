"""Parcels: subdivided street-graph faces, each with frontage. Record shape only; no generator.

A reserved memory precinct is a lot like any other, with a kerb, a frontage, a threshold and a
street address, so the city is coherent whether or not anything ever docks there and no hole is
ever cut into a block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import require_integer, require_pairs, require_record

__all__ = ["LOT_CLASSES", "STAGE", "STAGE_ID", "STAGE_VERSION", "ParcelRecord", "validate_parcel"]

STAGE_ID: Final = "parcels"
STAGE_VERSION: Final = 1
LOT_CLASSES: Final = ("building", "memory_precinct")


@dataclass(frozen=True, slots=True)
class ParcelRecord:
    RECORD_KIND: ClassVar[str] = "city.parcel"
    RECORD_VERSION: ClassVar[int] = 1

    parcel_ordinal: int
    block_ordinal: int
    lot_class: str
    #: The lot boundary as an integer ring, not closed by repetition.
    boundary_mm: tuple[tuple[int, int], ...]
    frontage_segment_ordinal: int
    frontage_mm: int
    address_number: int
    threshold_offset_mm: int


def validate_parcel(candidate: object) -> None:
    record = require_record(candidate, ParcelRecord)
    require_integer("parcel_ordinal", record.parcel_ordinal, minimum=0)
    require_integer("block_ordinal", record.block_ordinal, minimum=0)
    if record.lot_class not in LOT_CLASSES:
        raise InvalidRecordError(f"lot_class is one of {LOT_CLASSES}, got {record.lot_class!r}")
    require_pairs("boundary_mm", record.boundary_mm, minimum_count=3)
    if record.boundary_mm[0] == record.boundary_mm[-1]:
        raise InvalidRecordError("boundary_mm is not closed by repeating its first point")
    require_integer("frontage_segment_ordinal", record.frontage_segment_ordinal, minimum=0)
    require_integer("frontage_mm", record.frontage_mm, minimum=1)
    require_integer("address_number", record.address_number, minimum=1)
    require_integer("threshold_offset_mm", record.threshold_offset_mm, minimum=0)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (ParcelRecord, validate_parcel))
