"""A volume's field: the signed distance to its surface at any point, in whole millimetres.

Negative inside the mass, positive outside, zero on its surface, in the volume's own frame (x
east, y north, z up). One pure integer function of a volume document and a seed, so a field is the
same in every process and every replay, and a realized mesh or walkable sheet built on it is too.

**Order.** Solid parts in the document's order, each joined to what comes before it: an ``add`` by
a smooth union, a ``carve`` by a smooth subtraction, each with its blend (the polynomial smooth
minimum: no join where two values are a blend apart, a fillet nearer). Then erosion (fractal value
noise on the volume's own axes times the erosion's amplitude), then strata (a triangle wave in
height, level beds), then caps in order (a smooth intersection with the half-space below each
level), so a capped top stays level whatever the weathering below it.

**Shapes.** In a part's own frame, standing on its base at its point: a sphere about its point; a
box on its base, centred across; a capsule from its point to ``to_mm``, its radius tapering along
it; a column, the capped cone of its base and top radii, rims rounded; an arch, a passage along
the part's north with straight sides to its spring and a round head, its floor on its base. Lengths
that halve (a box's sides, a column's height) are taken in doubled units so nothing is lost to a
halving; square roots are exact floors (:func:`~exulanica.grammar.geometry.integer_sqrt`). A turned
part takes a point into its own frame by the transpose of its turn
(:func:`~exulanica.grammar.volumes.turns.turn_matrix`).

**Exactness and culling.** A part is evaluated only for points inside its bounds grown by twice its
blend and a margin, and weathering only where the unweathered value is below a gate. The margin is
:data:`EXACT_MM` plus the erosion's and the strata's amplitudes, twice every cap's blend and twice
every part's blend, which is enough that a smooth join, weathering or a cap can never carry a
skipped part's difference down to the surface: every value within :data:`EXACT_MM` of a surface is
the value the whole field (every part at every point, weathered everywhere) gives, and every sign
is the whole field's sign everywhere. Farther away a value is only a bound on the distance (noise
is not a distance either; a reader marching the field states a step factor from the erosion's
amplitude over its wavelength).

**Extent and looks.** Every solid point lies inside :attr:`VolumeField.extent`: each added part's
own bounds grown by a quarter of every blend (the most a chain of smooth unions lowers a value),
the erosion's and the strata's amplitudes, and no higher than the lowest cap. Outside it is air,
which is where a realizer may stop looking. :meth:`VolumeField.look_at` names the look of the
added part nearest a point, the volume's own look where the part states none.

Nothing here opens a database, a store or evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Final, TypeAlias

from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.volumes.document import (
    PROFILE,
    PartValue,
    VolumeDocument,
    VolumeRefused,
    number,
    point,
)
from exulanica.grammar.volumes.noise3 import HALF, Noise3
from exulanica.grammar.volumes.turns import TURN_ONE, Turn, turn_matrix

__all__ = ["EXACT_MM", "FAR_MM", "SHAPES", "VolumeField", "smooth_max", "smooth_min"]

#: Within this distance of a surface every value is the whole field's value.
EXACT_MM: Final = 4_000
#: The value where no part reaches: outside the mass, farther than any part.
FAR_MM: Final = 1 << 62
#: Fixed-point one for positions along a limb or a column's slant.
_FINE: Final = 1 << 24
#: Slack for a turned bounds' corners, floored once by the turn.
_TURN_SLACK_MM: Final = 4

Point: TypeAlias = tuple[int, int, int]
Distance: TypeAlias = Callable[[int, int, int], int]


def smooth_min(a: int, b: int, blend: int) -> int:
    """The polynomial smooth minimum: ``min(a, b)`` where they differ by the blend or more."""
    low = a if a < b else b
    if blend <= 0:
        return low
    h = blend - abs(a - b)
    if h <= 0:
        return low
    return low - h * h // (4 * blend)


def smooth_max(a: int, b: int, blend: int) -> int:
    return -smooth_min(-a, -b, blend)


def _length(point: Point) -> int:
    return integer_sqrt(point[0] * point[0] + point[1] * point[1] + point[2] * point[2])


def _sphere(values: Mapping[str, PartValue]) -> tuple[Distance, Point, Point]:
    radius = number(values["radius_mm"])

    def distance(x: int, y: int, z: int) -> int:
        return integer_sqrt(x * x + y * y + z * z) - radius

    return distance, (-radius, -radius, -radius), (radius, radius, radius)


def _box(values: Mapping[str, PartValue]) -> tuple[Distance, Point, Point]:
    sx, sy, sz = point(values["size_mm"])
    rounding = number(values["round_mm"])
    ex, ey, ez = sx - 2 * rounding, sy - 2 * rounding, sz - 2 * rounding

    def distance(x: int, y: int, z: int) -> int:
        qx, qy, qz = abs(2 * x) - ex, abs(2 * y) - ey, abs(2 * z - sz) - ez
        ox, oy, oz = max(qx, 0), max(qy, 0), max(qz, 0)
        inside = min(max(qx, qy, qz), 0)
        return (integer_sqrt(ox * ox + oy * oy + oz * oz) + inside) // 2 - rounding

    hx, hy = (sx + 1) // 2, (sy + 1) // 2
    return distance, (-hx, -hy, 0), (hx, hy, sz)


def _capsule(values: Mapping[str, PartValue]) -> tuple[Distance, Point, Point]:
    bx, by, bz = point(values["to_mm"])
    near, far = number(values["radius_mm"]), number(values["to_radius_mm"])
    length2 = bx * bx + by * by + bz * bz

    def distance(x: int, y: int, z: int) -> int:
        t = (x * bx + y * by + z * bz) * _FINE // length2
        t = 0 if t < 0 else _FINE if t > _FINE else t
        cx, cy, cz = x - bx * t // _FINE, y - by * t // _FINE, z - bz * t // _FINE
        return integer_sqrt(cx * cx + cy * cy + cz * cz) - (near + (far - near) * t // _FINE)

    r = max(near, far)
    return (
        distance,
        (min(0, bx) - r, min(0, by) - r, min(0, bz) - r),
        (max(0, bx) + r, max(0, by) + r, max(0, bz) + r),
    )


def _column(values: Mapping[str, PartValue]) -> tuple[Distance, Point, Point]:
    height = number(values["height_mm"])
    base, top = number(values["base_radius_mm"]), number(values["top_radius_mm"])
    rounding = number(values["round_mm"])
    # Doubled units: the core's half height, its radii, and the slant from base rim to top rim.
    half = height - 2 * rounding
    a, b = 2 * (base - rounding), 2 * (top - rounding)
    kx, ky = b - a, 2 * half
    k2 = kx * kx + ky * ky

    def distance(x: int, y: int, z: int) -> int:
        qx = integer_sqrt(4 * (x * x + y * y))
        qy = 2 * z - height
        cax = qx - min(qx, a if qy < 0 else b)
        cay = abs(qy) - half
        t = ((b - qx) * kx + (half - qy) * ky) * _FINE // k2
        t = 0 if t < 0 else _FINE if t > _FINE else t
        cbx = qx - b + kx * t // _FINE
        cby = qy - half + ky * t // _FINE
        nearest = integer_sqrt(min(cax * cax + cay * cay, cbx * cbx + cby * cby))
        return (-nearest if cbx < 0 and cay < 0 else nearest) // 2 - rounding

    r = max(base, top)
    return distance, (-r, -r, 0), (r, r, height)


def _arch(values: Mapping[str, PartValue]) -> tuple[Distance, Point, Point]:
    width, spring, depth = (
        number(values["width_mm"]),
        number(values["spring_mm"]),
        number(values["depth_mm"]),
    )

    def distance(x: int, y: int, z: int) -> int:
        across, along = abs(2 * x), abs(2 * y) - depth
        # The straight-sided passage from its floor to its spring.
        sx, sz = across - width, abs(2 * z - spring) - spring
        ox, oy, oz = max(sx, 0), max(along, 0), max(sz, 0)
        sides = integer_sqrt(ox * ox + oy * oy + oz * oz) + min(max(sx, along, sz), 0)
        # The round head: a level cylinder along north at the spring, above the spring only.
        rx = integer_sqrt(across * across + (2 * z - 2 * spring) * (2 * z - 2 * spring)) - width
        ox, oy = max(rx, 0), max(along, 0)
        head = integer_sqrt(ox * ox + oy * oy) + min(max(rx, along), 0)
        head = max(head, 2 * spring - 2 * z)
        return min(sides, head) // 2

    hx, hy = (width + 1) // 2, (depth + 1) // 2
    return distance, (-hx, -hy, 0), (hx, hy, spring + hx)


_SHAPES: Final[Mapping[str, Callable[[Mapping[str, PartValue]], tuple[Distance, Point, Point]]]] = {
    "sphere": _sphere,
    "box": _box,
    "capsule": _capsule,
    "column": _column,
    "arch": _arch,
}
#: Every shape this field evaluates: the solid shapes and the cap.
SHAPES: Final = frozenset(_SHAPES) | {"cap"}


@dataclass(frozen=True, slots=True)
class _Solid:
    carves: bool
    at: Point
    turn: Turn | None
    blend: int
    #: Where the part is evaluated: its bounds grown by the culling margin.
    low: Point
    high: Point
    distance: Distance
    #: Where an added part's solid can lie: its bounds grown by what can lower a value.
    reach: tuple[Point, Point]
    look: str

    def holds(self, x: int, y: int, z: int) -> bool:
        low, high = self.low, self.high
        return low[0] <= x <= high[0] and low[1] <= y <= high[1] and low[2] <= z <= high[2]

    def value(self, x: int, y: int, z: int) -> int:
        dx, dy, dz = x - self.at[0], y - self.at[1], z - self.at[2]
        m = self.turn
        if m is None:
            return self.distance(dx, dy, dz)
        return self.distance(
            (m[0][0] * dx + m[1][0] * dy + m[2][0] * dz) // TURN_ONE,
            (m[0][1] * dx + m[1][1] * dy + m[2][1] * dz) // TURN_ONE,
            (m[0][2] * dx + m[1][2] * dy + m[2][2] * dz) // TURN_ONE,
        )

    def join(self, current: int, own: int) -> int:
        if self.carves:
            return smooth_max(current, -own, self.blend)
        return smooth_min(current, own, self.blend)


def _turned_bounds(
    low: Point, high: Point, turn: Turn | None, at: Point, grow: int
) -> tuple[Point, Point]:
    corners: list[Point] = [
        (x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])
    ]
    if turn is not None:
        corners = [
            (
                (turn[0][0] * x + turn[0][1] * y + turn[0][2] * z) // TURN_ONE,
                (turn[1][0] * x + turn[1][1] * y + turn[1][2] * z) // TURN_ONE,
                (turn[2][0] * x + turn[2][1] * y + turn[2][2] * z) // TURN_ONE,
            )
            for x, y, z in corners
        ]
        grow += _TURN_SLACK_MM
    return _box_of(corners, at, grow)


def _box_of(corners: Sequence[Point], at: Point, grow: int) -> tuple[Point, Point]:
    """The least box holding ``corners`` moved by ``at``, grown by ``grow`` on every side."""
    low_x, high_x = _extent(corner[0] for corner in corners)
    low_y, high_y = _extent(corner[1] for corner in corners)
    low_z, high_z = _extent(corner[2] for corner in corners)
    return (
        (low_x + at[0] - grow, low_y + at[1] - grow, low_z + at[2] - grow),
        (high_x + at[0] + grow, high_y + at[1] + grow, high_z + at[2] + grow),
    )


def _extent(values: Iterable[int]) -> tuple[int, int]:
    listed = list(values)
    return min(listed), max(listed)


def _span(start: int, cell: int, count: int, low: int, high: int) -> range:
    """The indices of a grid axis whose coordinates lie in [low, high]."""
    first = max(0, -((start - low) // cell))
    last = min(count, (high - start) // cell + 1)
    return range(first, last)


class VolumeField:
    """One volume's field under one seed. ``whole`` evaluates every part at every point and
    weathers every point: slower, and the reference the culled field is held to."""

    __slots__ = (
        "_caps",
        "_erosion",
        "_erosion_gate",
        "_noise",
        "_strata",
        "_strata_gate",
        "_whole",
        "bounds",
        "document",
        "extent",
        "seed",
        "slope_permille",
        "solids",
        "weathering_mm",
    )

    def __init__(self, document: VolumeDocument, seed: bytes, *, whole: bool = False) -> None:
        self.document = document
        self.seed = seed
        self._whole = whole
        erosion, strata = document.erosion, document.strata
        amplitude = number(erosion["amplitude_mm"])
        bedding = number(strata["amplitude_mm"])
        self._erosion = amplitude
        self._strata = (bedding, number(strata["period_mm"]))
        self._noise = Noise3(
            hashlib.sha256(
                PROFILE.encode() + b"\x1f" + seed + b"\x1f" + document.id.encode()
            ).digest(),
            number(erosion["wavelength_mm"]),
            number(erosion["octaves"]),
            ridged=erosion["ridged"] == "yes",
        )
        caps = [part for part in document.parts if part.op == "cap"]
        self._caps = tuple(
            (number(part.values["height_mm"]), number(part.values["blend_mm"])) for part in caps
        )
        capping = 2 * sum(blend for _, blend in self._caps)
        self._strata_gate = EXACT_MM + bedding + capping
        self._erosion_gate = self._strata_gate + amplitude
        solid_parts = [part for part in document.parts if part.op != "cap"]
        blends = sum(number(part.values["blend_mm"]) for part in solid_parts)
        margin = self._erosion_gate + 2 * blends
        reach = blends // 4 + 1 + amplitude + bedding
        #: The most weathering lowers a value.
        self.weathering_mm = amplitude + bedding
        #: The steepest the parts' joined value changes, per thousand: one, and a tapered limb
        #: steeper by its taper over its length.
        self.slope_permille = 1000 + max(
            (
                abs(number(part.values["to_radius_mm"]) - number(part.values["radius_mm"]))
                * 1000
                // max(1, _length(point(part.values["to_mm"])))
                + 1
                for part in solid_parts
                if part.shape == "capsule"
            ),
            default=0,
        )
        solids = []
        for part in solid_parts:
            make = _SHAPES.get(part.shape)
            if make is None:
                raise VolumeRefused(
                    f"{part.id}: no field evaluates a {part.shape}", path=f"parts.{part.id}.shape"
                )
            distance, low, high = make(part.values)
            at = point(part.values["at_mm"])
            turn = turn_matrix(
                number(part.values["yaw_mdeg"]),
                number(part.values["tilt_mdeg"]),
                number(part.values["toward_mdeg"]),
            )
            blend = number(part.values["blend_mm"])
            grown_low, grown_high = _turned_bounds(low, high, turn, at, 2 * blend + margin)
            look = str(part.values["look"])
            solids.append(
                _Solid(
                    carves=part.op == "carve",
                    at=at,
                    turn=turn,
                    blend=blend,
                    low=grown_low,
                    high=grown_high,
                    distance=distance,
                    reach=_turned_bounds(low, high, turn, at, reach),
                    look=document.look if look == "volume" else look,
                )
            )
        self.solids: tuple[_Solid, ...] = tuple(solids)
        adds = [solid for solid in solids if not solid.carves]
        #: Outside these bounds every value is positive and no surface lies.
        self.bounds: tuple[Point, Point] = (
            _box_of([solid.low for solid in adds], (0, 0, 0), 0)[0],
            _box_of([solid.high for solid in adds], (0, 0, 0), 0)[1],
        )
        low, high = (
            _box_of([solid.reach[0] for solid in adds], (0, 0, 0), 0)[0],
            _box_of([solid.reach[1] for solid in adds], (0, 0, 0), 0)[1],
        )
        if self._caps:
            high = (high[0], high[1], min(high[2], min(height for height, _ in self._caps)))
        #: Every solid point lies inside this box; outside it is air.
        self.extent: tuple[Point, Point] = (low, high)

    def _finish(self, value: int, z: int, noise: Callable[[], int]) -> int:
        whole = self._whole
        if self._erosion and (whole or value < self._erosion_gate):
            value += noise() * self._erosion // HALF
        bedding, period = self._strata
        if bedding and (whole or value < self._strata_gate):
            rest = z % period
            value += (abs(2 * rest - period) * 2 * HALF // period - HALF) * bedding // HALF
        for height, blend in self._caps:
            value = smooth_max(value, z - height, blend)
        return value

    def bare(self, x: int, y: int, z: int) -> int:
        """The parts alone at one point, joined, before weathering and caps."""
        value = FAR_MM
        whole = self._whole
        for solid in self.solids:
            if whole or solid.holds(x, y, z):
                value = solid.join(value, solid.value(x, y, z))
        return value

    def distance(self, x: int, y: int, z: int) -> int:
        """The field at one point of the volume's frame."""
        return self._finish(self.bare(x, y, z), z, partial(self._noise.point, x, y, z))

    def air_reach(self, x: int, y: int, z: int) -> int:
        """How far round the point every point is certainly air, or zero or less where that is not
        certain. The parts' joined value changes no faster than :attr:`slope_permille` per metre
        (a smooth join or carve no faster than its parts), weathering lowers it by at most the
        erosion's and the strata's amplitudes, and caps only raise it; past the erosion gate a
        value is only a bound, so it counts as the gate."""
        bound = min(self.bare(x, y, z), self._erosion_gate) - self.weathering_mm
        return bound * 1000 // self.slope_permille

    def look_at(self, x: int, y: int, z: int) -> str:
        """The look of the added part nearest the point (the first of equals)."""
        nearest, look = FAR_MM, self.document.look
        for solid in self.solids:
            if not solid.carves:
                value = solid.value(x, y, z)
                if value < nearest:
                    nearest, look = value, solid.look
        return look

    def grid(self, origin: Point, cell: int, counts: Sequence[int]) -> list[int]:
        """The field at every point ``origin + cell * (i, j, k)`` of a grid ``counts`` points a
        side, x fastest, then y, then z: the same values :meth:`distance` gives point by point."""
        x0, y0, z0 = origin
        nx, ny, nz = counts
        xs = [x0 + cell * i for i in range(nx)]
        ys = [y0 + cell * j for j in range(ny)]
        zs = [z0 + cell * k for k in range(nz)]
        values = [FAR_MM] * (nx * ny * nz)
        for solid in self.solids:
            if self._whole:
                spans = (range(nx), range(ny), range(nz))
            else:
                spans = (
                    _span(x0, cell, nx, solid.low[0], solid.high[0]),
                    _span(y0, cell, ny, solid.low[1], solid.high[1]),
                    _span(z0, cell, nz, solid.low[2], solid.high[2]),
                )
            for k in spans[2]:
                z = zs[k]
                for j in spans[1]:
                    y = ys[j]
                    row = (k * ny + j) * nx
                    for i in spans[0]:
                        x = xs[i]
                        values[row + i] = solid.join(values[row + i], solid.value(x, y, z))
        noise = self._noise
        ax, ay, az = noise.axis(xs), noise.axis(ys), noise.axis(zs)
        index = 0
        for k in range(nz):
            z, wz = zs[k], az[k]
            for j in range(ny):
                wy = ay[j]
                for i in range(nx):
                    values[index] = self._finish(
                        values[index], z, partial(noise.sample, ax[i], wy, wz)
                    )
                    index += 1
        return values
