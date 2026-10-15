"""A volume's surface as meshes by chunk: ``exulanica.volume-chunk/v1``.

The field (:mod:`exulanica.grammar.volumes.field`) is sampled on a grid of cubes 32 m a side in the
volume's own frame, at one of four cells (:data:`LEVELS`, a level of detail each), and meshed by
surface nets, in whole numbers throughout:

* A point is solid where the field is at most zero.
* Each cube cell whose corners are not all solid or all air holds one vertex: the floor of the mean
  of the points where its edges cross the surface, each crossing found along its edge by the floor
  of linear interpolation between the edge's two values, kept a millimetre inside the edge (where
  the field is exactly zero at a corner, every cell round it would otherwise share one vertex).
* Each grid edge whose ends differ holds one quad of the four cells around it, turned so it faces
  from the solid end to the air end, split into two triangles on a fixed diagonal. An edge belongs
  to the chunk holding its lower end, so neighbouring chunks never both draw it, and the vertices
  they share are computed from the same samples, so they meet without a seam.
* A vertex's normal is the gradient over its cell's corners, scaled to :data:`NORMAL_ONE`; its look
  is the look of the added part nearest it.

A chunk is a pure function of the volume document, the seed and the volume rules, and its document
names them by :func:`input_sha256`; its identity is the SHA-256 of its canonical JSON, so a realized
chunk is kept and served by digest and never realized twice.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.volumes.document import VolumeRefused
from exulanica.grammar.volumes.field import VolumeField
from exulanica.grammar.volumes.rules import VOLUME_RULES_VERSION

__all__ = [
    "CHUNK_MM",
    "CHUNK_PROFILE",
    "LEVELS",
    "LOOKS",
    "NORMAL_ONE",
    "VolumeChunk",
    "input_sha256",
    "read_volume_chunk",
    "realize_chunk",
    "realize_volume",
    "volume_chunks",
]

CHUNK_PROFILE: Final = "exulanica.volume-chunk/v1"
#: A chunk's side.
CHUNK_MM: Final = 32_000
#: The cells a chunk is realized at, finest first: a level of detail each.
LEVELS: Final = (500, 1_000, 2_000, 4_000)
#: A normal's length.
NORMAL_ONE: Final = 32_767
#: The looks a vertex may name: the volume catalog's face looks.
LOOKS: Final = ("rock", "wall")
#: Each axis and the two that turn about it counterclockwise (x: y then z, and so on).
_AXES: Final = ((0, 1, 2), (1, 2, 0), (2, 0, 1))
_KEYS: Final = frozenset(
    {
        "profile",
        "input_sha256",
        "volume_sha256",
        "rules_version",
        "chunk",
        "cell_mm",
        "positions_mm",
        "normals",
        "looks",
        "vertex_looks",
        "triangles",
    }
)


def input_sha256(field: VolumeField) -> str:
    """What a realization of this field is a function of: the volume document, the seed and the
    volume rules, as one digest."""
    return hashlib.sha256(
        canonical_json(
            {
                "volume_sha256": field.document.sha256,
                "seed": field.seed.hex(),
                "volume_rules": VOLUME_RULES_VERSION,
            }
        )
    ).hexdigest()


@dataclass(frozen=True)
class VolumeChunk:
    """One chunk of a volume's surface at one cell: vertices, normals, looks and triangles."""

    input_sha256: str
    volume_sha256: str
    chunk: tuple[int, int, int]
    cell_mm: int
    positions_mm: tuple[int, ...]
    normals: tuple[int, ...]
    looks: tuple[str, ...]
    vertex_looks: tuple[int, ...]
    triangles: tuple[int, ...]

    def document(self) -> dict[str, Any]:
        return {
            "profile": CHUNK_PROFILE,
            "input_sha256": self.input_sha256,
            "volume_sha256": self.volume_sha256,
            "rules_version": VOLUME_RULES_VERSION,
            "chunk": list(self.chunk),
            "cell_mm": self.cell_mm,
            "positions_mm": list(self.positions_mm),
            "normals": list(self.normals),
            "looks": list(self.looks),
            "vertex_looks": list(self.vertex_looks),
            "triangles": list(self.triangles),
        }

    @functools.cached_property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document())).hexdigest()

    @property
    def vertex_count(self) -> int:
        return len(self.positions_mm) // 3


def volume_chunks(field: VolumeField, cell_mm: int) -> tuple[tuple[int, int, int], ...]:
    """Every chunk a vertex of the volume's surface can lie in at ``cell_mm``: those reaching
    within one cell of its extent, ordered by height, then north, then east."""
    low, high = field.extent
    spans = [
        range((low[axis] - cell_mm) // CHUNK_MM, (high[axis] + cell_mm) // CHUNK_MM + 1)
        for axis in range(3)
    ]
    return tuple((i, j, k) for k in spans[2] for j in spans[1] for i in spans[0])


def _crossing(a: int, b: int, cell: int) -> int:
    """How far along an edge of ``cell`` from the end valued ``a`` the surface crosses it, kept a
    millimetre inside the edge so a crossing is never a corner two cells share."""
    return max(1, min(cell - 1, cell * a // (a - b)))


def realize_chunk(field: VolumeField, chunk: tuple[int, int, int], cell_mm: int) -> VolumeChunk:
    """The chunk ``chunk`` of the field's surface at ``cell_mm``; empty where no surface lies."""
    if cell_mm not in LEVELS:
        raise VolumeRefused(f"a chunk is realized at a cell of {LEVELS} mm, not {cell_mm}")
    n = CHUNK_MM // cell_mm
    side = n + 3  # one sample beyond each face, so every cell an owned edge touches is sampled
    origin = tuple(chunk[axis] * CHUNK_MM - cell_mm for axis in range(3))
    values = field.grid((origin[0], origin[1], origin[2]), cell_mm, (side, side, side))

    def value(i: int, j: int, k: int) -> int:
        return values[((k + 1) * side + (j + 1)) * side + (i + 1)]

    # The owned edges whose ends differ, and the quads of cells around them.
    quads: list[tuple[tuple[int, int, int], ...]] = []
    for k in range(n):
        for j in range(n):
            for i in range(n):
                here = value(i, j, k) <= 0
                point = (i, j, k)
                for axis, u, v in _AXES:
                    ahead = list(point)
                    ahead[axis] += 1
                    if (value(*ahead) <= 0) == here:
                        continue
                    ring = []
                    for du, dv in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
                        corner = list(point)
                        corner[u] += du
                        corner[v] += dv
                        ring.append((corner[0], corner[1], corner[2]))
                    quads.append(tuple(ring) if here else tuple(reversed(ring)))
    cells = sorted({cell for quad in quads for cell in quad}, key=lambda c: (c[2], c[1], c[0]))
    index = {cell: number for number, cell in enumerate(cells)}
    positions: list[int] = []
    normals: list[int] = []
    vertex_looks: list[int] = []
    for i, j, k in cells:
        corners = [value(i + di, j + dj, k + dk) for dk in (0, 1) for dj in (0, 1) for di in (0, 1)]
        total, count = [0, 0, 0], 0
        for (a, b), (start, axis) in _cell_edges(corners):
            if (a <= 0) != (b <= 0):
                place = [start[0] * cell_mm, start[1] * cell_mm, start[2] * cell_mm]
                place[axis] += _crossing(a, b, cell_mm)
                for axis_index in range(3):
                    total[axis_index] += place[axis_index]
                count += 1
        position = tuple(
            origin[axis] + cell_mm + (i, j, k)[axis] * cell_mm + total[axis] // count
            for axis in range(3)
        )
        positions.extend(position)
        normals.extend(_normal(corners))
        vertex_looks.append(LOOKS.index(field.look_at(*position)))
    triangles: list[int] = []
    for quad in quads:
        a, b, c, d = (index[cell] for cell in quad)
        triangles.extend((a, b, c, a, c, d))
    return VolumeChunk(
        input_sha256=input_sha256(field),
        volume_sha256=field.document.sha256,
        chunk=chunk,
        cell_mm=cell_mm,
        positions_mm=tuple(positions),
        normals=tuple(normals),
        looks=LOOKS,
        vertex_looks=tuple(vertex_looks),
        triangles=tuple(triangles),
    )


def _cell_edges(
    corners: list[int],
) -> Iterator[tuple[tuple[int, int], tuple[tuple[int, int, int], int]]]:
    """A cell's twelve edges: their two values and their lower corner and axis, corners indexed
    x fastest, then y, then z."""
    for dk in (0, 1):
        for dj in (0, 1):
            low = (dk * 2 + dj) * 2
            yield (corners[low], corners[low + 1]), ((0, dj, dk), 0)
    for dk in (0, 1):
        for di in (0, 1):
            low = dk * 4 + di
            yield (corners[low], corners[low + 2]), ((di, 0, dk), 1)
    for dj in (0, 1):
        for di in (0, 1):
            low = dj * 2 + di
            yield (corners[low], corners[low + 4]), ((di, dj, 0), 2)


def _normal(corners: list[int]) -> tuple[int, int, int]:
    gx = sum(corners[low + 1] - corners[low] for low in (0, 2, 4, 6))
    gy = sum(corners[low + 2] - corners[low] for low in (0, 1, 4, 5))
    gz = sum(corners[low + 4] - corners[low] for low in (0, 1, 2, 3))
    length = integer_sqrt(gx * gx + gy * gy + gz * gz)
    if length == 0:
        return (0, 0, NORMAL_ONE)
    return (gx * NORMAL_ONE // length, gy * NORMAL_ONE // length, gz * NORMAL_ONE // length)


def realize_volume(field: VolumeField, cell_mm: int) -> tuple[VolumeChunk, ...]:
    """Every chunk of the volume's surface at ``cell_mm`` that holds any of it, in
    :func:`volume_chunks` order."""
    chunks = (realize_chunk(field, chunk, cell_mm) for chunk in volume_chunks(field, cell_mm))
    return tuple(chunk for chunk in chunks if chunk.triangles)


def _whole_numbers(
    raw: object, path: str, low: int, high: int, *, triples: bool
) -> tuple[int, ...]:
    if not isinstance(raw, list) or (triples and len(raw) % 3):
        raise VolumeRefused(
            f"{path} is a list of whole numbers{' in threes' if triples else ''}", path=path
        )
    for index, item in enumerate(raw):
        if type(item) is not int or not low <= item <= high:
            raise VolumeRefused(
                f"{path}[{index}] is a whole number from {low} to {high}, got {item!r}", path=path
            )
    return tuple(raw)


def read_volume_chunk(raw: object, expected_sha256: str | None = None) -> VolumeChunk:
    """Admit a chunk document, or refuse it by path; with ``expected_sha256``, only the chunk that
    digest names."""
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise VolumeRefused(f"a volume chunk has exactly {sorted(_KEYS)}")
    if raw["profile"] != CHUNK_PROFILE:
        raise VolumeRefused(f"profile is {CHUNK_PROFILE}", path="profile")
    for name in ("input_sha256", "volume_sha256"):
        digest = raw[name]
        if not (
            isinstance(digest, str)
            and len(digest) == 64
            and all(ch in "0123456789abcdef" for ch in digest)
        ):
            raise VolumeRefused(f"{name} is a SHA-256 in lowercase hex", path=name)
    if raw["rules_version"] != VOLUME_RULES_VERSION:
        raise VolumeRefused(
            f"this server reads chunks of volume rules version {VOLUME_RULES_VERSION}",
            path="rules_version",
            code="volume_rules_changed",
        )
    chunk = _whole_numbers(raw["chunk"], "chunk", -(1 << 20), 1 << 20, triples=True)
    if len(chunk) != 3:
        raise VolumeRefused("chunk is three whole numbers", path="chunk")
    cell = raw["cell_mm"]
    if type(cell) is not int or cell not in LEVELS:
        raise VolumeRefused(f"cell_mm is one of {LEVELS}", path="cell_mm")
    if raw["looks"] != list(LOOKS):
        raise VolumeRefused(f"looks are {list(LOOKS)}", path="looks")
    low = [chunk[axis] * CHUNK_MM - cell for axis in range(3)]
    reach = CHUNK_MM + 2 * cell
    positions = _whole_numbers(
        raw["positions_mm"], "positions_mm", min(low), max(low) + reach, triples=True
    )
    for number in range(len(positions) // 3):
        point = positions[3 * number : 3 * number + 3]
        if any(not low[axis] <= point[axis] <= low[axis] + reach for axis in range(3)):
            raise VolumeRefused(
                f"vertex {number} lies outside its chunk and one cell round it", path="positions_mm"
            )
    count = len(positions) // 3
    normals = _whole_numbers(raw["normals"], "normals", -NORMAL_ONE, NORMAL_ONE, triples=True)
    looks = _whole_numbers(raw["vertex_looks"], "vertex_looks", 0, len(LOOKS) - 1, triples=False)
    if len(normals) != 3 * count or len(looks) != count:
        raise VolumeRefused("every vertex has one normal and one look", path="normals")
    triangles = _whole_numbers(raw["triangles"], "triangles", 0, max(count - 1, 0), triples=True)
    if triangles and not count:
        raise VolumeRefused("triangles name vertices the chunk does not have", path="triangles")
    out = VolumeChunk(
        input_sha256=raw["input_sha256"],
        volume_sha256=raw["volume_sha256"],
        chunk=(chunk[0], chunk[1], chunk[2]),
        cell_mm=cell,
        positions_mm=positions,
        normals=normals,
        looks=LOOKS,
        vertex_looks=looks,
        triangles=triangles,
    )
    if expected_sha256 is not None and out.sha256 != expected_sha256:
        raise VolumeRefused(
            "the chunk is not the one its digest names", code="volume_digest_mismatch"
        )
    return out
