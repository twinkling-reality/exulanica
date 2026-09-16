"""Terrain: a heightfield in millimetres with a slope field. Record shape only; no generator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.records import require_integer, require_record

__all__ = ["STAGE", "STAGE_ID", "STAGE_VERSION", "TerrainRecord", "validate_terrain"]

STAGE_ID: Final = "terrain"
STAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class TerrainRecord:
    """A regular grid. Samples are row-major, ``columns * rows`` of them in both fields."""

    RECORD_KIND: ClassVar[str] = "city.terrain"
    RECORD_VERSION: ClassVar[int] = 1

    origin_x_mm: int
    origin_y_mm: int
    cell_mm: int
    columns: int
    rows: int
    height_mm: tuple[int, ...]
    #: Rise over run at each sample, as a magnitude, in millionths.
    slope_millionths: tuple[int, ...]


def validate_terrain(candidate: object) -> None:
    record = require_record(candidate, TerrainRecord)
    require_integer("origin_x_mm", record.origin_x_mm)
    require_integer("origin_y_mm", record.origin_y_mm)
    require_integer("cell_mm", record.cell_mm, minimum=1)
    require_integer("columns", record.columns, minimum=1)
    require_integer("rows", record.rows, minimum=1)
    samples = record.columns * record.rows
    if len(record.height_mm) != samples or len(record.slope_millionths) != samples:
        raise InvalidRecordError(f"a {record.columns} by {record.rows} grid has {samples} samples")
    for index, height in enumerate(record.height_mm):
        require_integer(f"height_mm[{index}]", height)
    for index, slope in enumerate(record.slope_millionths):
        require_integer(f"slope_millionths[{index}]", slope, minimum=0)


STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, (TerrainRecord, validate_terrain))
