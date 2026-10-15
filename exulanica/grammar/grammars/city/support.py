"""How high a support record's drawn surface stands under a box in plan.

A clearance above a support (a canopy over a footway, a street or the bare ground) is a clearance
above the surface where the box stands, not above the support's highest point anywhere: on land a
street's crown, a curb's footway and the terrain climb along their length, and their highest point
may lie a block away from the box. :func:`support_top_under` reads the surface under the box:

* terrain: its highest sample of every cell the box meets;
* a segment: its highest crown point over the box's run along each piece of its centreline;
* a curb: the same over its kerb line, plus its kerb and its footway's rise;
* every other support kind: :func:`~exulanica.grammar.grammars.city.document.support_top_mm`.

Where a support stands level (every version before land) each reading equals its highest point,
so a level town's clearances read as they always have. Pure and integer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Any

from exulanica.grammar.grammars.city.corners import footway_rise_mm
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord, StreetSegmentRecord
from exulanica.grammar.grammars.city.terrain import TerrainRecord

__all__ = ["line_top_under", "support_top_under"]


def line_top_under(
    line: Sequence[tuple[int, int, int]], low_x: int, low_y: int, high_x: int, high_y: int
) -> int | None:
    """The highest point of ``line`` over the box's run along each of its pieces, or ``None`` when
    no piece runs within the box's run. A piece runs along x or y; heights between its two points
    are interpolated, so the highest is at an end of the run."""
    best: int | None = None
    for (x0, y0, z0), (x1, y1, z1) in pairwise(line):
        along_x = x0 != x1
        t0, t1 = (x0, x1) if along_x else (y0, y1)
        low, high = (low_x, high_x) if along_x else (low_y, high_y)
        start, end = max(min(t0, t1), low), min(max(t0, t1), high)
        if start > end:
            continue
        for t in (start, end):
            z = z0 if t1 == t0 else z0 + (z1 - z0) * (t - t0) // (t1 - t0)
            best = z if best is None else max(best, z)
    return best


def _terrain_top(record: TerrainRecord, low_x: int, low_y: int, high_x: int, high_y: int) -> int:
    cell, side = record.cell_mm, record.samples_per_side
    x0, y0 = record.extent.min_x_mm, record.extent.min_y_mm
    columns = range(max(0, (low_x - x0) // cell), min(side - 1, -(-(high_x - x0) // cell)) + 1)
    rows = range(max(0, (low_y - y0) // cell), min(side - 1, -(-(high_y - y0) // cell)) + 1)
    heights = [record.height_mm[row * side + column] for row in rows for column in columns]
    return max(heights) if heights else max(record.height_mm)


def support_top_under(
    record: Any,
    low_x: int,
    low_y: int,
    high_x: int,
    high_y: int,
    everywhere: Callable[[Any], int],
) -> int:
    """How high ``record``'s support surface stands under the box, read as the module says;
    ``everywhere`` is the support's highest point anywhere, for the kinds that stand level."""
    if type(record) is TerrainRecord:
        return _terrain_top(record, low_x, low_y, high_x, high_y)
    if type(record) is StreetSegmentRecord:
        top = line_top_under(record.centreline_mm, low_x, low_y, high_x, high_y)
        return everywhere(record) if top is None else top
    if type(record) is CurbEdgeRecord:
        top = line_top_under(record.kerb_line_mm, low_x, low_y, high_x, high_y)
        if top is None:
            return everywhere(record)
        return top + record.kerb_height_mm + footway_rise_mm(record)
    return everywhere(record)
