"""Massing: typology, era, storeys and the roofscape of one building. Record shape only.

Typology, era and roof family are keys into catalogs, never free text and never a Python table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import (
    require_identity,
    require_increasing,
    require_integer,
    require_key,
    require_record,
)

__all__ = ["STAGE", "STAGE_ID", "STAGE_VERSION", "MassingRecord", "validate_massing"]

STAGE_ID: Final = "massing"
STAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class MassingRecord:
    RECORD_KIND: ClassVar[str] = "city.massing"
    RECORD_VERSION: ClassVar[int] = 1

    building_identity: str
    parcel_ordinal: int
    typology: str
    era: str
    storeys: int
    ground_storey_height_mm: int
    upper_storey_height_mm: int
    #: ``(storey, depth_mm)``: the facade steps back by ``depth_mm`` from that storey upward.
    setbacks: tuple[tuple[int, int], ...]
    #: Footprint edge ordinals that are shared with a neighbour.
    party_wall_edges: tuple[int, ...]
    light_well_count: int
    roof_family: str
    parapet_height_mm: int
    rooftop_plant_count: int
    rooftop_tank_count: int


def validate_massing(candidate: object) -> None:
    record = require_record(candidate, MassingRecord)
    require_identity("building_identity", record.building_identity)
    require_integer("parcel_ordinal", record.parcel_ordinal, minimum=0)
    require_key("typology", record.typology)
    require_key("era", record.era)
    require_integer("storeys", record.storeys, minimum=1)
    require_integer("ground_storey_height_mm", record.ground_storey_height_mm, minimum=1)
    require_integer("upper_storey_height_mm", record.upper_storey_height_mm, minimum=1)
    if not isinstance(record.setbacks, tuple):
        raise InvalidRecordError("setbacks is a tuple of (storey, depth_mm) pairs")
    previous = 0
    for index, setback in enumerate(record.setbacks):
        if not isinstance(setback, tuple) or len(setback) != 2:
            raise InvalidRecordError(f"setbacks[{index}] is a (storey, depth_mm) pair")
        storey, depth = setback
        require_integer(
            f"setbacks[{index}] storey", storey, minimum=previous + 1, maximum=record.storeys - 1
        )
        require_integer(f"setbacks[{index}] depth_mm", depth, minimum=1)
        previous = storey
    require_increasing("party_wall_edges", record.party_wall_edges)
    require_integer("light_well_count", record.light_well_count, minimum=0)
    require_key("roof_family", record.roof_family)
    require_integer("parapet_height_mm", record.parapet_height_mm, minimum=0)
    require_integer("rooftop_plant_count", record.rooftop_plant_count, minimum=0)
    require_integer("rooftop_tank_count", record.rooftop_tank_count, minimum=0)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (MassingRecord, validate_massing))
