"""A land chunk as exact heightfield geometry, so the existing contact predicates apply to it.

A chunk (``exulanica.grammar.landform``) is 129 samples a side, 1 m apart, rows from its
south-west corner, each cell split along its south-west to north-east diagonal. The exact sheet
(``exulanica.heightfield-geometry/v1``) is east, up and south, rows from north to south, each cell
split ``a-c-b,b-c-d``: the same diagonal. So a chunk is one sheet in its own frame, east from its
west edge and south from minus 128 m at its north edge to 0 at its south edge, with its rows in
the other order. Heights and topology are unchanged, so exact contact on the sheet is exact
contact on the land.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Final

from exulanica.grammar.landform import CHUNK_MM, LandChunk
from exulanica.world.heightfield_geometry import DIAGONAL, FRAME
from exulanica.world.heightfield_geometry import PROFILE as GEOMETRY_PROFILE

__all__ = ["GENERATOR_ID", "GENERATOR_VERSION", "chunk_geometry", "chunk_height_at", "chunk_local"]

GENERATOR_ID: Final = "exulanica.landform"
GENERATOR_VERSION: Final = 1


def chunk_geometry(chunk: LandChunk) -> dict[str, Any]:
    """The chunk as an ``exulanica.heightfield-geometry/v1`` document in its own frame."""
    n, cell = chunk.samples_per_side, chunk.cell_mm
    rows = [chunk.height_mm[(n - 1 - j) * n : (n - j) * n] for j in range(n)]
    return {
        "profile": GEOMETRY_PROFILE,
        "component_id": f"landform:chunk:{chunk.chunk_x}:{chunk.chunk_y}",
        "frame": FRAME,
        "east_mm": [k * cell for k in range(n)],
        "south_mm": [-CHUNK_MM + k * cell for k in range(n)],
        "height_mm": [h for row in rows for h in row],
        "diagonal": DIAGONAL,
        "provenance": {
            "kind": "generated",
            "source_sha256": chunk.sha256,
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "input_sha256": chunk.sha256,
        },
    }


def chunk_local(chunk: LandChunk, east_mm: int, north_mm: int) -> list[int]:
    """A world point (east and north of the world's south-west corner) in the chunk's frame."""
    return [east_mm - chunk.chunk_x * CHUNK_MM, chunk.chunk_y * CHUNK_MM - north_mm]


def chunk_height_at(chunk: LandChunk, east_mm: int, north_mm: int) -> Fraction | None:
    """The exact height of the land at a world point of the chunk: the plane of the triangle it lies
    in, each cell split along its south-west to north-east diagonal. None outside the chunk."""
    n, cell = chunk.samples_per_side, chunk.cell_mm
    gx = Fraction(east_mm - chunk.chunk_x * CHUNK_MM, cell)
    gy = Fraction(north_mm - chunk.chunk_y * CHUNK_MM, cell)
    if not (0 <= gx <= n - 1 and 0 <= gy <= n - 1):
        return None
    i, j = min(n - 2, math.floor(gx)), min(n - 2, math.floor(gy))
    fx, fy = gx - i, gy - j
    h = chunk.height_mm
    h00, h10 = h[j * n + i], h[j * n + i + 1]
    h01, h11 = h[(j + 1) * n + i], h[(j + 1) * n + i + 1]
    if fx >= fy:
        return h00 + (h10 - h00) * fx + (h11 - h10) * fy
    return h00 + (h11 - h01) * fx + (h01 - h00) * fy
