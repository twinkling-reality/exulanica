"""A volume's field: the signed distance to its surface at any point, in whole millimetres.

Negative inside the mass, positive outside, zero on its surface, in the volume's own frame (x
east, y north, z up). One pure integer function of a volume document and a seed, so a field is the
same in every process and every replay, and a realized mesh or walkable sheet built on it is too.

**Order.** Solid parts in the document's order, each joined to what comes before it: an ``add`` by
a smooth union, a ``carve`` by a smooth subtraction, each with its blend (the polynomial smooth
minimum: no join where two values are a blend apart, a fillet nearer). Then erosion (fractal value
noise on the volume's own axes times the erosion's amplitude), then strata, then caps in order (a
smooth intersection with the half-space below each level), so a capped top stays level whatever
the weathering below it, then the top land, the same way below its surface.

**Top land.** A volume that states a top land (:class:`~exulanica.grammar.volumes.document.TopLand`)
is capped by the land's surface as a cap is by its level: ``smooth_max(value, z - surface, blend)``,
after the caps. The land is realized once per field (:class:`TopLandSurface`) by the land realizer
(:func:`~exulanica.grammar.landform.realize_region`) on the land's own lattice,
:data:`TOP_LAND_CELL_MM` apart, over its square in the square's own frame (its south-west corner
the land's origin, the square's side the land's extent, the land's datum the volume's level 0), its
frame's seed drawn from the volume's id alone, so the same document has the same top under every
seed and wherever it is placed. Between lattice points the surface is the floor of the bilinear
blend of the four round it, in whole numbers; outside the square it is the height of the square's
nearest edge point, a flat level. A land the realizer refuses is refused here by its path under
``top_land.land``. The surface is the land's height above each point, not a distance to it; it
only ever raises a value, as a cap does, so it changes no bound below.

**Strata.** Beds are a triangle wave across each bed's thickness: a bed stands out at its middle and
is cut back at its joins. Stated plainly they are level beds of the period's thickness, every one
standing out by the amplitude. A volume may vary them (:class:`_Beds`): beds alternate thicker and
thinner by a drawn amount within the spread; each steps out by a drawn share of the amplitude (the
relief) and is set proud or recessed within what is left; each stands proud on one drawn side and
recessed on the other (the offset, toward that side from the volume's own vertical axis); and the
bedding planes lean by a tilt toward a bearing. Each bed is drawn from the seed and its index, bed 0
lying on the volume's own level 0, and its whole contribution stays within the amplitude. The
relief and the offset fade to nothing over the lowest quarter of the volume's height (its extent),
so the narrow foot of an island or a stack is never pinched to a neck by a recessed bed.

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
:data:`EXACT_MM` plus the erosion's and the strata's amplitudes, twice every cap's and the top
land's blend and twice every part's blend, which is enough that a smooth join, weathering or a cap
can never carry a skipped part's difference down to the surface: every value within
:data:`EXACT_MM` of a surface is the value the whole field (every part at every point, weathered
everywhere) gives, and every sign is the whole field's sign everywhere. Farther away a value is
only a bound on the distance (noise is not a distance either; a reader marching the field states a
step factor from the erosion's amplitude over its wavelength).

**Extent and looks.** Every solid point lies inside :attr:`VolumeField.extent`: each added part's
own bounds grown by a quarter of every blend (the most a chain of smooth unions lowers a value),
the erosion's and the strata's amplitudes, no higher than the lowest cap, and no higher than the
top land's highest realized height (a smooth maximum is at least each of its values, and the
bilinear surface never rises above the lattice heights round it). Outside it is air,
which is where a realizer may stop looking. :meth:`VolumeField.look_at` names the look of the
added part nearest a point, the volume's own look where the part states none.

Nothing here opens a database, a store or evidence.
"""

from __future__ import annotations

import bisect
import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Final, TypeAlias

from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.landform import CELL_MM as LAND_CELL_MM
from exulanica.grammar.landform import LandformRefused, NearLand, WorldFrame, realize_region
from exulanica.grammar.volumes.document import (
    PROFILE,
    PartValue,
    TopLand,
    VolumeDocument,
    VolumeRefused,
    number,
    point,
)
from exulanica.grammar.volumes.noise3 import HALF, Noise3
from exulanica.grammar.volumes.rules import SERVED_VOLUME_RULES, rules_reading
from exulanica.grammar.volumes.turns import TURN_ONE, Turn, sin_cos, turn_matrix

__all__ = [
    "EXACT_MM",
    "FAR_MM",
    "SHAPES",
    "TOP_LAND_CELL_MM",
    "TopLandSurface",
    "VolumeField",
    "realize_top_land",
    "smooth_max",
    "smooth_min",
    "top_land_frame",
]

#: Within this distance of a surface every value is the whole field's value.
EXACT_MM: Final = 4_000
#: The value where no part reaches: outside the mass, farther than any part.
FAR_MM: Final = 1 << 62
#: Fixed-point one for positions along a limb or a column's slant.
_FINE: Final = 1 << 24
#: Slack for a turned bounds' corners, floored once by the turn.
_TURN_SLACK_MM: Final = 4
#: The lattice a top land is realized on: the land's own.
TOP_LAND_CELL_MM: Final = LAND_CELL_MM

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


class _Beds:
    """A volume's varied beds: each bed's base, thickness, relief, shift and side, drawn once per
    bed index from the volume's seed, found by height and drawn further whenever a height lies past
    the beds drawn so far."""

    __slots__ = (
        "_bases",
        "_beds",
        "_first",
        "_key",
        "_least",
        "_offset",
        "_relief",
        "_spread",
        "bedding",
        "period",
    )

    def __init__(self, key: bytes, strata: Mapping[str, int | str]) -> None:
        self._key = key
        self.period = number(strata["period_mm"])
        self.bedding = number(strata["amplitude_mm"])
        self._spread = number(strata["spread_mm"])
        self._least = max(1, self._spread // 4)
        self._relief = number(strata["relief_permille"])
        self._offset = self.bedding * number(strata["offset_permille"]) // 1000
        self._first = 0
        self._bases = [0]
        self._beds = [self._draw(0)]

    def _draw(self, index: int) -> tuple[int, int, int, int, int]:
        """Bed ``index``'s thickness, step-out, shift, and its side's cosine and sine."""
        digest = hashlib.sha256(self._key + index.to_bytes(8, "big", signed=True)).digest()
        a, b, c, d = (int.from_bytes(digest[at : at + 8], "big") for at in (0, 8, 16, 24))
        thickness = self.period
        if self._spread:
            amount = self._least + a % (self._spread - self._least + 1)
            thickness += amount if index % 2 == 0 else -amount
        scale = self.bedding * (1000 - b % (self._relief + 1)) // 1000
        room = self.bedding - scale
        sine, cosine = sin_cos(d % 360_000)
        return thickness, scale, c % (2 * room + 1) - room, cosine, sine

    def value(self, height: int, x: int, y: int, share: int) -> int:
        """The beds' contribution at ``height`` across the bedding, at ``(x, y)``, their variation
        of step-out and side kept to ``share`` per thousand."""
        bases, beds = self._bases, self._beds
        while height < bases[0]:
            self._first -= 1
            bed = self._draw(self._first)
            bases.insert(0, bases[0] - bed[0])
            beds.insert(0, bed)
        while height >= bases[-1] + beds[-1][0]:
            bases.append(bases[-1] + beds[-1][0])
            beds.append(self._draw(self._first + len(beds)))
        at = bisect.bisect_right(bases, height) - 1
        thickness, scale, shift, cosine, sine = beds[at]
        offset = self._offset
        if share < 1000:
            scale = self.bedding - (self.bedding - scale) * share // 1000
            shift = shift * share // 1000
            offset = offset * share // 1000
        rest = height - bases[at]
        value = (abs(2 * rest - thickness) * 2 * HALF // thickness - HALF) * scale // HALF + shift
        if offset:
            across = integer_sqrt(x * x + y * y)
            if across:
                value -= offset * (x * cosine + y * sine) // (TURN_ONE * across)
        return max(-self.bedding, min(self.bedding, value))


def top_land_frame(top: TopLand, volume_id: str) -> WorldFrame:
    """The frame a volume's top land is realized in: its square, its seed drawn from the volume's
    id alone."""
    seed = hashlib.sha256(PROFILE.encode() + b"\x1ftop_land\x1f" + volume_id.encode())
    return WorldFrame(width_mm=top.side_mm, depth_mm=top.side_mm, seed=seed.hexdigest())


def realize_top_land(top: TopLand, volume_id: str) -> NearLand:
    """A volume's natural top: its land realized over its square on the land's own lattice, in the
    square's frame (its south-west corner the land's origin), or a refusal by its path under
    ``top_land.land``. The one realization a top land's surface and anything laid out on it read."""
    side = top.side_mm
    try:
        return realize_region(top.land, top_land_frame(top, volume_id), 0, 0, side, side)
    except LandformRefused as refused:
        inner = f"top_land.land.{refused.path}" if refused.path else "top_land.land"
        raise VolumeRefused(f"{volume_id}: {refused.detail}", path=inner) from refused


class TopLandSurface:
    """A top land's surface: its heights realized once on its square's lattice, read between them
    by the floor of their bilinear blend and outside the square at its nearest edge point."""

    __slots__ = ("_count", "_half", "_heights", "blend", "highest", "lowest")

    def __init__(self, top: TopLand, volume_id: str) -> None:
        side = top.side_mm
        near = realize_top_land(top, volume_id)
        self._half = side // 2
        self._count = near.nx
        self._heights = near.heights
        self.blend = top.blend_mm
        #: The highest and lowest realized heights: the surface lies between them everywhere.
        self.highest = max(near.heights)
        self.lowest = min(near.heights)

    def height(self, x: int, y: int) -> int:
        """The surface's height above ``(x, y)`` of the volume's frame."""
        cell, count, side = TOP_LAND_CELL_MM, self._count, 2 * self._half
        u = min(side, max(0, x + self._half))
        v = min(side, max(0, y + self._half))
        i, j = min(u // cell, count - 2), min(v // cell, count - 2)
        fx, fy = u - i * cell, v - j * cell
        at = j * count + i
        heights = self._heights
        return (
            heights[at] * (cell - fx) * (cell - fy)
            + heights[at + 1] * fx * (cell - fy)
            + heights[at + count] * (cell - fx) * fy
            + heights[at + count + 1] * fx * fy
        ) // (cell * cell)


#: The strata values that vary the beds; a volume stating none of them has level, even beds.
_VARIED: Final = ("spread_mm", "relief_permille", "offset_permille", "tilt_mdeg")


class VolumeField:
    """One volume's field under one seed and one version of the volume rules (the newest that
    reads the catalogs its document was read against, unless a world's rules name another).
    ``whole`` evaluates every part at every point and weathers every point: slower, and the
    reference the culled field is held to."""

    __slots__ = (
        "_beds",
        "_caps",
        "_erosion",
        "_erosion_gate",
        "_floor",
        "_noise",
        "_quarter",
        "_strata",
        "_strata_gate",
        "_top",
        "_up",
        "_whole",
        "bounds",
        "document",
        "extent",
        "rules",
        "seed",
        "slope_permille",
        "solids",
        "weathering_mm",
    )

    def __init__(
        self,
        document: VolumeDocument,
        seed: bytes,
        *,
        whole: bool = False,
        rules: int | None = None,
    ) -> None:
        named = rules_reading(document.catalog_version) if rules is None else rules
        if SERVED_VOLUME_RULES.get(named) != document.catalog_version:
            raise VolumeRefused(
                f"{document.id} was read against volume catalog version "
                f"{document.catalog_version}, which volume rules version {named} does not read",
                code="volume_rules_changed",
            )
        #: The volume rules this field is evaluated by, named by every chunk and top made of it.
        self.rules = named
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
        varied = any(number(strata.get(name, 0)) for name in _VARIED)
        self._beds = (
            _Beds(
                hashlib.sha256(
                    PROFILE.encode() + b"\x1fstrata\x1f" + seed + b"\x1f" + document.id.encode()
                ).digest(),
                strata,
            )
            if bedding and varied
            else None
        )
        sin_tilt, cos_tilt = sin_cos(number(strata.get("tilt_mdeg", 0)))
        sin_toward, cos_toward = sin_cos(number(strata.get("toward_mdeg", 0)))
        #: The bedding's up: leaned by its tilt toward its bearing, at :data:`TURN_ONE`.
        self._up = (
            sin_tilt * sin_toward // TURN_ONE,
            sin_tilt * cos_toward // TURN_ONE,
            cos_tilt,
        )
        caps = [part for part in document.parts if part.op == "cap"]
        self._caps = tuple(
            (number(part.values["height_mm"]), number(part.values["blend_mm"])) for part in caps
        )
        #: The top land's surface, realized once for this field, or None.
        self._top = (
            TopLandSurface(document.top_land, document.id)
            if document.top_land is not None
            else None
        )
        capping = 2 * sum(blend for _, blend in self._caps)
        if self._top is not None:
            capping += 2 * self._top.blend
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
        if self._top is not None:
            high = (high[0], high[1], min(high[2], self._top.highest))
        #: Every solid point lies inside this box; outside it is air.
        self.extent: tuple[Point, Point] = (low, high)
        #: Varied beds keep their variation out of the lowest quarter of the volume's height.
        self._floor = low[2]
        self._quarter = max(1, (high[2] - low[2]) // 4)

    def _finish(
        self,
        value: int,
        x: int,
        y: int,
        z: int,
        noise: Callable[[], int],
        surface: int | None = None,
    ) -> int:
        whole = self._whole
        if self._erosion and (whole or value < self._erosion_gate):
            value += noise() * self._erosion // HALF
        bedding, period = self._strata
        if bedding and (whole or value < self._strata_gate):
            beds = self._beds
            if beds is None:
                rest = z % period
                value += (abs(2 * rest - period) * 2 * HALF // period - HALF) * bedding // HALF
            else:
                up_x, up_y, up_z = self._up
                share = min(1000, max(0, (z - self._floor) * 1000 // self._quarter))
                value += beds.value((up_x * x + up_y * y + up_z * z) // TURN_ONE, x, y, share)
        for height, blend in self._caps:
            value = smooth_max(value, z - height, blend)
        top = self._top
        if top is not None:
            if surface is None:
                surface = top.height(x, y)
            value = smooth_max(value, z - surface, top.blend)
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
        return self._finish(self.bare(x, y, z), x, y, z, partial(self._noise.point, x, y, z))

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
        top = self._top
        surfaces: list[int | None] = (
            [None] * (nx * ny) if top is None else [top.height(x, y) for y in ys for x in xs]
        )
        index = 0
        for k in range(nz):
            z, wz = zs[k], az[k]
            for j in range(ny):
                y, wy = ys[j], ay[j]
                row = j * nx
                for i in range(nx):
                    values[index] = self._finish(
                        values[index],
                        xs[i],
                        y,
                        z,
                        partial(noise.sample, ax[i], wy, wz),
                        surfaces[row + i],
                    )
                    index += 1
        return values
