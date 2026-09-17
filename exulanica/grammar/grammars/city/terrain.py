"""Terrain: one heightfield patch per tile, for support and grading. Record shape only.

A patch covers exactly one tile square, ``[tile_x * 128000, (tile_x + 1) * 128000]`` on each
axis, with samples on both edges, so neighbouring patches share their edge samples. Samples are
row-major from the south-west corner: row ``j`` is ``y = tile_y * 128000 + j * cell_mm`` and
column ``i`` is ``x = tile_x * 128000 + i * cell_mm``. Each cell is split into two triangles along
the diagonal from its south-west sample to its north-east sample (``triangulation`` states it),
and elevation inside a triangle is planar.

**Terrain is support and grading, not a surface of its own wherever something else covers it.**
Where a street, a block or a lot covers the ground in plan, that surface is drawn and the terrain
is not. Terrain has no admissible material in this version: no published texture set is soil,
grass or gravel, so exposed terrain draws as unavailable.

**The slope field is exact.** At sample ``(i, j)`` it is
``max(|h(i+1, j) - h(i, j)|, |h(i, j+1) - h(i, j)|) * 10**6 // cell_mm``, taking the previous
sample instead of the next on the last column and the last row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city._skeleton import skeleton
from exulanica.grammar.grammars.city.common import (
    MILLIONTHS,
    TILE_SIZE_MM,
    extent_field,
    tile_ordinal,
)

__all__ = ["SHAPE", "STAGE", "STAGE_ID", "STAGE_VERSION", "TRIANGULATIONS", "TerrainRecord"]

STAGE_ID: Final = "terrain"
STAGE_VERSION: Final = 2
TRIANGULATIONS: Final = ("sw_ne",)


@dataclass(frozen=True, slots=True)
class TerrainRecord:
    RECORD_KIND: ClassVar[str] = "city.terrain"
    RECORD_VERSION: ClassVar[int] = 2

    identity: str
    tile_ordinal: int
    tile_x: int
    tile_y: int
    cell_mm: int
    samples_per_side: int
    #: Row-major from the south-west corner, ``samples_per_side`` squared of them.
    height_mm: tuple[int, ...]
    slope_millionths: tuple[int, ...]
    triangulation: str
    extent: Extent


def _grid(record: TerrainRecord) -> None:
    if record.tile_ordinal != tile_ordinal(record.tile_x, record.tile_y):
        raise InvalidRecordError("tile_ordinal is the fold-and-pair of tile_x and tile_y")
    if TILE_SIZE_MM % record.cell_mm:
        raise InvalidRecordError(f"cell_mm divides the {TILE_SIZE_MM} mm tile")
    side = TILE_SIZE_MM // record.cell_mm + 1
    if record.samples_per_side != side:
        raise InvalidRecordError(f"a {record.cell_mm} mm cell gives {side} samples per side")
    if len(record.height_mm) != side * side or len(record.slope_millionths) != side * side:
        raise InvalidRecordError(f"the grid holds {side * side} samples in each field")


def _slope(record: TerrainRecord) -> None:
    side = record.samples_per_side
    heights = record.height_mm
    for row in range(side):
        for column in range(side):
            here = heights[row * side + column]
            across = column + 1 if column + 1 < side else column - 1
            up = row + 1 if row + 1 < side else row - 1
            rise = max(
                abs(heights[row * side + across] - here), abs(heights[up * side + column] - here)
            )
            if record.slope_millionths[row * side + column] != rise * MILLIONTHS // record.cell_mm:
                raise InvalidRecordError(f"slope at sample ({column}, {row}) is not the exact rule")


def _extent(record: TerrainRecord) -> None:
    low_x = record.tile_x * TILE_SIZE_MM
    low_y = record.tile_y * TILE_SIZE_MM
    expected = Extent(
        low_x,
        low_y,
        min(record.height_mm),
        low_x + TILE_SIZE_MM,
        low_y + TILE_SIZE_MM,
        max(record.height_mm),
    )
    if record.extent != expected:
        raise InvalidRecordError(f"a terrain patch's extent is exactly its tile, {expected}")


SHAPE: Final = shapes.RecordShape(
    TerrainRecord,
    (
        shapes.identity("identity"),
        shapes.integer("tile_ordinal", 0),
        shapes.integer("tile_x"),
        shapes.integer("tile_y"),
        shapes.integer("cell_mm", 500, TILE_SIZE_MM),
        shapes.integer("samples_per_side", 2),
        shapes.integers("height_mm", count_minimum=4),
        shapes.integers("slope_millionths", 0, count_minimum=4),
        shapes.choice("triangulation", TRIANGULATIONS),
        extent_field(),
    ),
    rules=(
        shapes.RecordRule("terrain_grid_matches_tile", _grid),
        shapes.RecordRule("terrain_slope_exact", _slope),
        shapes.RecordRule("terrain_extent_is_tile", _extent),
    ),
    identity=shapes.IdentityRule("terrain", ordinal_field="tile_ordinal"),
    extent_field="extent",
)

STAGE: Final = skeleton(STAGE_ID, STAGE_VERSION, SHAPE)
