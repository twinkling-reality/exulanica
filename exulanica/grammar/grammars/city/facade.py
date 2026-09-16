"""Facade: the durable procedural record per building per edge. Record shape only; no generator.

``docs/world-memory-model.md`` section 5.1 has required this record since before this package
existed: "the admitted building identity, grammar version, parameters, seed, output digest, and
declared semantics". :data:`FACADE_RECORD_FIELDS` names those six, and :class:`FacadeRecord`
carries all six plus the edge it describes. A facade may later emit thousands of openings
without storing any of them; this record is what stands behind them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.contract import DeclaredSemantics
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import (
    require_hex64,
    require_identity,
    require_integer,
    require_key,
    require_record,
)
from exulanica.grammar.seed import require_seed

__all__ = [
    "FACADE_RECORD_FIELDS",
    "STAGE",
    "STAGE_ID",
    "STAGE_VERSION",
    "FacadeRecord",
    "validate_facade",
]

STAGE_ID: Final = "facade"
STAGE_VERSION: Final = 1

#: The six fields section 5.1 requires, in its order.
FACADE_RECORD_FIELDS: Final = (
    "building_identity",
    "grammar_version",
    "parameters",
    "seed",
    "output_digest",
    "declared_semantics",
)


@dataclass(frozen=True, slots=True)
class FacadeRecord:
    RECORD_KIND: ClassVar[str] = "city.facade"
    RECORD_VERSION: ClassVar[int] = 1

    building_identity: str
    grammar_version: int
    #: ``(name, value)`` pairs, sorted by name, each value an int or a key.
    parameters: tuple[tuple[str, int | str], ...]
    seed: str
    output_digest: str
    declared_semantics: DeclaredSemantics
    #: Which footprint edge of the building this facade faces out from.
    edge_ordinal: int


def validate_facade(candidate: object) -> None:
    record = require_record(candidate, FacadeRecord)
    require_identity("building_identity", record.building_identity)
    require_integer("grammar_version", record.grammar_version, minimum=1)
    if not isinstance(record.parameters, tuple):
        raise InvalidRecordError("parameters is a tuple of (name, value) pairs")
    names = []
    for index, pair in enumerate(record.parameters):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise InvalidRecordError(f"parameters[{index}] is a (name, value) pair")
        name, value = pair
        names.append(require_key(f"parameters[{index}] name", name))
        if type(value) is str:
            require_key(f"parameters[{index}] value", value)
        else:
            require_integer(f"parameters[{index}] value", value)
    if names != sorted(set(names)):
        raise InvalidRecordError("parameters are sorted by name and name each parameter once")
    require_seed(record.seed)
    require_hex64("output_digest", record.output_digest)
    if type(record.declared_semantics) is not DeclaredSemantics:
        raise InvalidRecordError("declared_semantics is a DeclaredSemantics")
    require_integer("edge_ordinal", record.edge_ordinal, minimum=0)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (FacadeRecord, validate_facade))
