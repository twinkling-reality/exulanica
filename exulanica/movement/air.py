"""The air a flight happens in: a bounded volume, a coarse occupancy grid, and declared perches.

**The volume** is a box over a world's ground: horizontally the area the ground states, or the
one a world with an endless ground is given (the society declares its walking area the same way),
vertically from the ground to the flight module's declared ceiling. Nothing flies outside it.

**The grid** divides the volume into cubes of the module's ``cell_mm``. A cell is solid when any
solid of the world, an object's catalog part turned, scaled and placed, touches it once grown by the
air's clearance: each part's axis-aligned bounds in the region are rounded outward to the
millimetre and grown by the clearance on every side, and every cell those closed bounds meet is
solid. The clearance is half the widest flying kind's span, so a flyer whose point stays in free
cells keeps its whole body out of every part. That is conservative by construction: a crown or a
lamp head blocks a little more air than it fills, and never less. The grid also keeps, for each
solid cell, the objects whose grown parts touch it.

**A perch** is a point a catalog declares on a part's upper surface. Above it runs its column: the
cells from the perch up to its approach point, one approach height above it for a kind. The solid
cells at the foot of the column, the perch's own, are touched by the perch's own object alone and
are passable only to the one flyer landing on, perching at or taking off from it. A column cell any
other object touches refuses the perch (``perch_approach_blocked``), so no landing passes through
another object; every cell above the perch's own must be free, and the approach point must lie
inside the volume and the kind's altitude band, or the perch is not usable by that kind, and the
reason is kept.

Cells are half-open, ``[low, low + cell)`` on each axis, so every point belongs to exactly one.

Pure integers: no float reaches a cell, a bound or a digest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Final, Literal

from exulanica.canonical import canonical_json
from exulanica.movement.fixed import ONE, Vector, ceil_div, tdiv, turn, turned

__all__ = [
    "AIR_VOLUME_PROFILE",
    "AirVolume",
    "Cell",
    "Column",
    "Occupancy",
    "PartBox",
    "PerchSite",
    "Placement",
    "Solid",
    "build_occupancy",
    "placed_point",
    "segment_meets_cell",
    "swept_cells",
]

Cell = tuple[int, int, int]
AreaSource = Literal["ground", "declared"]
#: The profile of a flight volume's document, the space the flight module's row declares.
AIR_VOLUME_PROFILE: Final = "exulanica.air-volume/v1"
_SCALE_ONE: Final = 1000


@dataclass(frozen=True, slots=True)
class AirVolume:
    """The box a flight happens in, in the region's frame: ``x`` east, ``y`` up, ``z`` south."""

    source: AreaSource
    min_x_mm: int
    max_x_mm: int
    min_z_mm: int
    max_z_mm: int
    ground_mm: int
    ceiling_mm: int
    cell_mm: int

    def __post_init__(self) -> None:
        for low, high in (
            (self.min_x_mm, self.max_x_mm),
            (self.min_z_mm, self.max_z_mm),
            (self.ground_mm, self.ceiling_mm),
        ):
            if not low < high or (high - low) % self.cell_mm:
                raise ValueError("a flight volume spans a positive whole number of cells")

    @property
    def shape(self) -> tuple[int, int, int]:
        cell = self.cell_mm
        return (
            (self.max_x_mm - self.min_x_mm) // cell,
            (self.ceiling_mm - self.ground_mm) // cell,
            (self.max_z_mm - self.min_z_mm) // cell,
        )

    def contains(self, point: Sequence[int]) -> bool:
        """Whether a point lies inside the closed volume."""
        x, y, z = point
        return (
            self.min_x_mm <= x <= self.max_x_mm
            and self.ground_mm <= y <= self.ceiling_mm
            and self.min_z_mm <= z <= self.max_z_mm
        )

    def cell_of(self, point: Sequence[int]) -> Cell | None:
        """The half-open cell holding a point, or None outside the grid."""
        x, y, z = point
        nx, ny, nz = self.shape
        cell = self.cell_mm
        ix = (x - self.min_x_mm) // cell
        iy = (y - self.ground_mm) // cell
        iz = (z - self.min_z_mm) // cell
        if 0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz:
            return (ix, iy, iz)
        return None

    def cell_bounds(self, cell: Cell) -> tuple[Vector, Vector]:
        """A cell's half-open bounds: ``low`` included, ``high`` excluded, on every axis."""
        ix, iy, iz = cell
        size = self.cell_mm
        low = (self.min_x_mm + ix * size, self.ground_mm + iy * size, self.min_z_mm + iz * size)
        return low, (low[0] + size, low[1] + size, low[2] + size)

    def document(self) -> dict[str, Any]:
        return {
            "profile": AIR_VOLUME_PROFILE,
            "source": self.source,
            "min_mm": [self.min_x_mm, self.ground_mm, self.min_z_mm],
            "max_mm": [self.max_x_mm, self.ceiling_mm, self.max_z_mm],
            "cell_mm": self.cell_mm,
        }


@dataclass(frozen=True, slots=True)
class Placement:
    """Where an object stands in the region: millimetres, a yaw in microradians, a scale in
    thousandths, as a placed object's transform states it."""

    x_mm: int
    y_mm: int
    z_mm: int
    yaw_microradians: int
    scale_milli: int


@dataclass(frozen=True, slots=True)
class PartBox:
    """A part's bounds in its kind's own frame: ``+x`` across, ``+y`` its front, ``+z`` up."""

    min_x_mm: int
    max_x_mm: int
    min_y_mm: int
    max_y_mm: int
    min_z_mm: int
    max_z_mm: int


@dataclass(frozen=True, slots=True)
class Solid:
    """One part of one placed object, as the grid reads it.

    ``travel_mm`` is how far the object moves along its region's axes from where it was placed
    and back (a bounded path): the part is solid over the whole of that travel.
    """

    object_id: str
    box: PartBox
    placement: Placement
    travel_mm: Vector = (0, 0, 0)


def _region_offset(px: int, py: int, placement: Placement) -> tuple[int, int]:
    """A part-frame plan point as numerators over ``1000 * ONE`` of its turned region offset.

    The kind's front ``+y`` faces the region's ``-z`` (``exulanica.world.object_glb``), so a part
    point ``(x, y)`` is the region offset ``(x, -y)`` before its scale and turn.
    """
    cosine, sine = turn(placement.yaw_microradians)
    return turned(px * placement.scale_milli, -py * placement.scale_milli, cosine, sine)


def placed_point(point: Sequence[int], placement: Placement) -> Vector:
    """A part-frame point ``(x, y, z)`` in the region, each coordinate truncated toward zero from
    its exact value about the placement, and its height rounded up so it never sinks into what it
    stands on."""
    px, py, pz = point
    dx, dz = _region_offset(px, py, placement)
    denominator = _SCALE_ONE * ONE
    return (
        placement.x_mm + tdiv(dx, denominator),
        placement.y_mm + ceil_div(pz * placement.scale_milli, _SCALE_ONE),
        placement.z_mm + tdiv(dz, denominator),
    )


def _solid_bounds(solid: Solid) -> tuple[Vector, Vector]:
    """A solid's closed region bounds, every corner rounded outward to the millimetre, over the
    whole of its travel: a box moved along a straight line sweeps the box spanning both ends."""
    low, high = _placed_bounds(solid.box, solid.placement)
    tx, ty, tz = solid.travel_mm
    return (
        (min(low[0], low[0] + tx), min(low[1], low[1] + ty), min(low[2], low[2] + tz)),
        (max(high[0], high[0] + tx), max(high[1], high[1] + ty), max(high[2], high[2] + tz)),
    )


def _placed_bounds(box: PartBox, placement: Placement) -> tuple[Vector, Vector]:
    """A part box's closed region bounds where it was placed, rounded outward."""
    denominator = _SCALE_ONE * ONE
    xs, zs = [], []
    for px in (box.min_x_mm, box.max_x_mm):
        for py in (box.min_y_mm, box.max_y_mm):
            dx, dz = _region_offset(px, py, placement)
            xs.append(dx)
            zs.append(dz)
    return (
        (
            placement.x_mm + min(xs) // denominator,
            placement.y_mm + box.min_z_mm * placement.scale_milli // _SCALE_ONE,
            placement.z_mm + min(zs) // denominator,
        ),
        (
            placement.x_mm + ceil_div(max(xs), denominator),
            placement.y_mm + ceil_div(box.max_z_mm * placement.scale_milli, _SCALE_ONE),
            placement.z_mm + ceil_div(max(zs), denominator),
        ),
    )


def _closed_range(low: int, high: int, origin: int, cell: int, count: int) -> range:
    """The half-open cells a closed interval ``[low, high]`` meets, clipped to the grid."""
    first = max(0, (low - origin) // cell)
    last = min(count - 1, (high - origin) // cell)
    return range(first, last + 1)


def swept_cells(volume: AirVolume, start: Sequence[int], end: Sequence[int]) -> Iterator[Cell]:
    """Every cell the closed box spanning a move's two ends meets: a superset of the cells the
    straight move passes through, so a move whose cells are all passable passes nothing else."""
    nx, ny, nz = volume.shape
    cell = volume.cell_mm
    for ix in _closed_range(
        min(start[0], end[0]), max(start[0], end[0]), volume.min_x_mm, cell, nx
    ):
        for iy in _closed_range(
            min(start[1], end[1]), max(start[1], end[1]), volume.ground_mm, cell, ny
        ):
            for iz in _closed_range(
                min(start[2], end[2]), max(start[2], end[2]), volume.min_z_mm, cell, nz
            ):
                yield (ix, iy, iz)


def segment_meets_cell(
    volume: AirVolume, start: Sequence[int], end: Sequence[int], cell: Cell
) -> bool:
    """Whether some point of the straight segment from ``start`` to ``end`` lies in ``cell``.

    Exact: on each axis the parameters ``t`` in ``[0, 1]`` at which the segment lies inside the
    cell's half-open slab form an interval, computed with exact fractions and its open or closed
    ends kept; the segment meets the cell when the three intervals share a point.
    """
    low, high = volume.cell_bounds(cell)
    first, first_open = Fraction(0), False
    last, last_open = Fraction(1), False
    for axis in range(3):
        origin, delta = start[axis], end[axis] - start[axis]
        if delta == 0:
            if not low[axis] <= origin < high[axis]:
                return False
            continue
        enter = Fraction(low[axis] - origin, delta)
        leave = Fraction(high[axis] - origin, delta)
        if delta > 0:
            # low <= origin + t*delta < high: t in [enter, leave)
            lower, lower_open, upper, upper_open = enter, False, leave, True
        else:
            # dividing by a negative delta turns both bounds: t in (leave, enter]
            lower, lower_open, upper, upper_open = leave, True, enter, False
        if lower > first or (lower == first and lower_open):
            first, first_open = lower, lower_open
        if upper < last or (upper == last and upper_open):
            last, last_open = upper, upper_open
    if first < last:
        return True
    return first == last and not first_open and not last_open


@dataclass(frozen=True, slots=True)
class Column:
    """A perch's column for one kind: where a flyer turns to land, and the perch's own cells."""

    approach_mm: Vector
    #: The solid cells at the foot of the column, passable only to the flyer using this perch.
    own_cells: tuple[Cell, ...]
    #: Every cell from the perch's to the approach point's, in order upward.
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class PerchSite:
    """A declared perch placed in the region, and, for each kind, its column or why not."""

    perch_id: str
    object_id: str
    point_mm: Vector
    span_mm: int
    columns: Mapping[str, Column]
    #: For each kind that cannot use this perch, the reason: ``perch_too_narrow``,
    #: ``perch_out_of_reach`` or ``perch_approach_blocked``.
    refused: Mapping[str, str]

    def document(self) -> dict[str, Any]:
        return {
            "perch_id": self.perch_id,
            "object_id": self.object_id,
            "point_mm": list(self.point_mm),
            "span_mm": self.span_mm,
            "columns": {
                kind: {
                    "approach_mm": list(column.approach_mm),
                    "own_cells": [list(cell) for cell in column.own_cells],
                }
                for kind, column in sorted(self.columns.items())
            },
            "refused": dict(sorted(self.refused.items())),
        }


@dataclass(frozen=True, slots=True)
class Occupancy:
    """The grid: one byte a cell, 1 where a grown solid touches it, the objects touching each
    solid cell, and its digest."""

    volume: AirVolume
    solid: bytes
    sha256: str
    #: How far every part was grown on every side before its cells were marked, in millimetres.
    clearance_mm: int = 0
    #: For each solid cell's index, the objects whose grown parts touch it.
    owners: Mapping[int, frozenset[str]] = field(default_factory=dict)

    def index(self, cell: Cell) -> int:
        _nx, ny, nz = self.volume.shape
        ix, iy, iz = cell
        return (ix * ny + iy) * nz + iz

    def is_solid(self, cell: Cell) -> bool:
        return self.solid[self.index(cell)] == 1

    def solid_cells(self) -> int:
        return sum(self.solid)


def build_occupancy(
    volume: AirVolume, solids: Sequence[Solid], *, clearance_mm: int = 0
) -> Occupancy:
    """Every cell any solid touches once grown by ``clearance_mm`` on every side, the objects
    touching each, and the grid's digest over the volume, the clearance and the cells."""
    if clearance_mm < 0:
        raise ValueError("a clearance is not negative")
    nx, ny, nz = volume.shape
    cells = bytearray(nx * ny * nz)
    owners: dict[int, set[str]] = {}
    cell = volume.cell_mm
    grow = clearance_mm
    for solid in solids:
        low, high = _solid_bounds(solid)
        for ix in _closed_range(low[0] - grow, high[0] + grow, volume.min_x_mm, cell, nx):
            for iy in _closed_range(low[1] - grow, high[1] + grow, volume.ground_mm, cell, ny):
                for iz in _closed_range(low[2] - grow, high[2] + grow, volume.min_z_mm, cell, nz):
                    index = (ix * ny + iy) * nz + iz
                    cells[index] = 1
                    owners.setdefault(index, set()).add(solid.object_id)
    header = canonical_json({"volume": volume.document(), "clearance_mm": clearance_mm})
    digest = hashlib.sha256(header + b"\n" + bytes(cells)).hexdigest()
    return Occupancy(
        volume,
        bytes(cells),
        digest,
        clearance_mm,
        MappingProxyType({index: frozenset(ids) for index, ids in owners.items()}),
    )


def perch_column(
    occupancy: Occupancy,
    point: Vector,
    *,
    object_id: str,
    approach_height_mm: int,
    min_altitude_mm: int,
    max_altitude_mm: int,
) -> Column | str:
    """A perch's column for a kind, or the reason the kind cannot use the perch.

    ``object_id`` is the object the perch stands on: the solid cells at the column's foot must be
    touched by it alone, and a column cell any other object touches refuses the perch.
    """
    volume = occupancy.volume
    approach = (point[0], point[1] + approach_height_mm, point[2])
    height = approach[1] - volume.ground_mm
    foot = volume.cell_of(point)
    top = volume.cell_of(approach)
    if (
        foot is None
        or top is None
        or not volume.contains(approach)
        or not min_altitude_mm <= height <= max_altitude_mm
    ):
        return "perch_out_of_reach"
    cells = tuple((foot[0], iy, foot[2]) for iy in range(foot[1], top[1] + 1))
    own: list[Cell] = []
    for cell in cells:
        if not occupancy.is_solid(cell):
            break
        if occupancy.owners.get(occupancy.index(cell)) != frozenset({object_id}):
            return "perch_approach_blocked"
        own.append(cell)
    if any(occupancy.is_solid(cell) for cell in cells[len(own) :]) or len(own) == len(cells):
        return "perch_approach_blocked"
    return Column(approach, tuple(own), cells)
