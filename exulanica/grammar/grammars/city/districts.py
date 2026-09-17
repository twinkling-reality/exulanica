"""Districts: the coarse scopes a city is divided into. Record shape only; no generator.

A district is the second level of the parameter cascade, so it is a record with an identity: a
binding that restyles a district names this identity. It comes before the streets because street
and building parameters both cascade through it, and it states the one road rule every street in
it shares, the side of the road traffic drives on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, extent_contains_ring
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import DRIVING_SIDES, extent_field

__all__ = ["SHAPE", "STAGE", "STAGE_ID", "STAGE_VERSION", "DistrictRecord"]

STAGE_ID: Final = "districts"
STAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class DistrictRecord:
    RECORD_KIND: ClassVar[str] = "city.district"
    RECORD_VERSION: ClassVar[int] = 1

    identity: str
    district_ordinal: int
    boundary_mm: tuple[tuple[int, int], ...]
    #: ``right`` or ``left``: the side of the carriageway traffic keeps to.
    driving_side: str
    extent: Extent


def _boundary_in_extent(record: DistrictRecord) -> None:
    if not extent_contains_ring(record.extent, record.boundary_mm):
        raise InvalidRecordError("a district's boundary lies inside its extent")


SHAPE: Final = shapes.RecordShape(
    DistrictRecord,
    (
        shapes.identity("identity"),
        shapes.integer("district_ordinal", 0),
        shapes.ring("boundary_mm"),
        shapes.choice("driving_side", DRIVING_SIDES),
        extent_field(),
    ),
    rules=(shapes.RecordRule("district_boundary_in_extent", _boundary_in_extent),),
    identity=shapes.IdentityRule("district", ordinal_field="district_ordinal"),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
