"""Premises: a unit, its use class and its sign. Record shape only; no generator.

The sign is a key into the signage lexicon, not a string written here, so every sign a city
shows traces to a reviewed, licensed catalog entry.
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

__all__ = ["STAGE", "STAGE_ID", "STAGE_VERSION", "PremisesRecord", "validate_premises"]

STAGE_ID: Final = "premises"
STAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class PremisesRecord:
    RECORD_KIND: ClassVar[str] = "city.premises"
    RECORD_VERSION: ClassVar[int] = 1

    building_identity: str
    unit_ordinal: int
    use_class: str
    #: A key into the signage-lexicon catalog.
    sign: str


def validate_premises(candidate: object) -> None:
    record = require_record(candidate, PremisesRecord)
    require_identity("building_identity", record.building_identity)
    require_integer("unit_ordinal", record.unit_ordinal, minimum=0)
    require_key("use_class", record.use_class)
    require_key("sign", record.sign)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (PremisesRecord, validate_premises))
