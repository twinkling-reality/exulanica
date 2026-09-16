"""Vitrine: a lit interior volume behind ground-floor glazing. Record shape only; no generator.

The depth bound, 600 to 1500 mm, is the target architecture's and is checked on every record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import (
    require_identity,
    require_integer,
    require_key,
    require_record,
)

__all__ = [
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "VITRINE_DEPTH_MAXIMUM_MM",
    "VITRINE_DEPTH_MINIMUM_MM",
    "VitrineRecord",
    "validate_vitrine",
]

STAGE_ID: Final = "vitrine"
STAGE_VERSION: Final = 1
VITRINE_DEPTH_MINIMUM_MM: Final = 600
VITRINE_DEPTH_MAXIMUM_MM: Final = 1500


@dataclass(frozen=True, slots=True)
class VitrineRecord:
    RECORD_KIND: ClassVar[str] = "city.vitrine"
    RECORD_VERSION: ClassVar[int] = 1

    building_identity: str
    edge_ordinal: int
    bay_ordinal: int
    depth_mm: int
    #: A key naming the seeded fitout.
    fitout: str


def validate_vitrine(candidate: object) -> None:
    record = require_record(candidate, VitrineRecord)
    require_identity("building_identity", record.building_identity)
    require_integer("edge_ordinal", record.edge_ordinal, minimum=0)
    require_integer("bay_ordinal", record.bay_ordinal, minimum=0)
    require_integer(
        "depth_mm",
        record.depth_mm,
        minimum=VITRINE_DEPTH_MINIMUM_MM,
        maximum=VITRINE_DEPTH_MAXIMUM_MM,
    )
    require_key("fitout", record.fitout)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (VitrineRecord, validate_vitrine))
