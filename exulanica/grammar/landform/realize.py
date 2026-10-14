"""Realizing a land document: one pure integer function of the document and the world's seed.

``H(x, y)`` is the land's height in millimetres above the datum (the sea's level) at a point east
and north of the world's south-west corner. Features apply in a fixed order: the additive ones sum
(tilt, rise, valley, undulation, range), then the shaping ones carve or hold the result, terraces
(level benches joined by banks), then shores, then basins last, so a basin's water is set by the rim
it ends with. Each recipe is
bounded to the land it was written for and fades out beyond it, so no periodic term ever repeats
across a far slope.

**Near land** is the world's extent plus one ring of chunks, sampled every metre in chunks on the
city's 128 m tile grid: chunk ``(i, j)`` covers east ``i * 128 m`` to ``(i + 1) * 128 m`` and north
the same, 129 samples a side, neighbours sharing their edge samples. A chunk has the city's
``TerrainRecord`` shape (rows from the south-west, the exact slope field), and every near height
is held to the exact sheet's 64 m (``exulanica.heightfield-geometry/v1``).

**The backdrop** is the same function on a coarse grid out to the horizon: 16 m apart across the
near land, growing outward by 15 percent a step to 96 m. It is drawn only, never walked, and not
held to the near bound. Samples on the near land's edge are the near samples there, so the two
meet. A range must rise beyond the near land; one whose foot reaches it is refused.

Placement words resolve against the world's extent: a side's line lies ``distance_mm`` beyond the
world's edge on that side (negative reaches in), ``offset_mm`` along it from its middle; ``centre``
is the world's middle, offset east and north.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.landform.document import LandDocument, LandFeature, LandformRefused
from exulanica.grammar.landform.noise import ONE, fbm_grid, smooth

__all__ = [
    "BACKDROP_PROFILE",
    "BACKDROP_REACH_MM",
    "CELL_MM",
    "CHUNK_MM",
    "CHUNK_PROFILE",
    "NEAR_BOUND_MM",
    "SAMPLES_PER_SIDE",
    "Backdrop",
    "LandChunk",
    "NearLand",
    "WaterBody",
    "WorldFrame",
    "height_at",
    "land_heights",
    "near_chunks",
    "near_domain",
    "read_land_chunk",
    "realize_backdrop",
    "realize_chunk",
    "realize_near",
    "realize_region",
    "water_bodies",
]

#: The city grammar's tile (``TILE_SIZE_MM``), so a town's terrain stage writes land as it is.
CHUNK_MM: Final = 128_000
#: The city's slope unit: rise per run in millionths.
MILLIONTHS: Final = 1_000_000
CELL_MM: Final = 1_000
SAMPLES_PER_SIDE: Final = CHUNK_MM // CELL_MM + 1
#: The exact sheet's height bound (``heightfield_geometry.read_heightfield_geometry``).
NEAR_BOUND_MM: Final = 64_000
BACKDROP_REACH_MM: Final = 8_000_000
BACKDROP_NEAR_STEP_MM: Final = 16_000
BACKDROP_FAR_STEP_MM: Final = 96_000
BACKDROP_GROWTH_PERMILLE: Final = 1_150
CHUNK_PROFILE: Final = "exulanica.landform-chunk/v1"
BACKDROP_PROFILE: Final = "exulanica.landform-backdrop/v1"
#: How far a shore's water's edge wanders along its length, as a wavelength.
SHORE_WANDER_PERIOD_MM: Final = 90_000
#: The width of the ring outside a basin whose lowest sample sets its water's level.
BASIN_RIM_MM: Final = 2 * CELL_MM
#: 1 / sqrt(2) in fixed point, for the four diagonal sides.
_R2: Final = 46_341
_SIDES: Final = {
    "north": (0, 1), "north_east": (1, 1), "east": (1, 0), "south_east": (1, -1),
    "south": (0, -1), "south_west": (-1, -1), "west": (-1, 0), "north_west": (-1, 1),
    "centre": (0, 0),
}  # fmt: skip
_SHAPING_ORDER: Final = ("terraces", "shore", "basin")


@dataclass(frozen=True, slots=True)
class WorldFrame:
    """The world's extent from its south-west corner, and its seed (hexadecimal text)."""

    width_mm: int
    depth_mm: int
    seed: str

    @property
    def centre(self) -> tuple[int, int]:
        return self.width_mm // 2, self.depth_mm // 2

    def half_along(self, side: str) -> int:
        dx, dy = _SIDES[side]
        if dx and dy:
            return (self.width_mm // 2 + self.depth_mm // 2) * _R2 // ONE
        return self.width_mm // 2 if dx else self.depth_mm // 2 if dy else 0


def _along(side: str, x: int, y: int, centre: tuple[int, int]) -> int:
    dx, dy = _SIDES[side]
    px, py = x - centre[0], y - centre[1]
    if dx and dy:
        return (px * dx + py * dy) * _R2 // ONE
    return px * dx + py * dy


def _across(side: str, x: int, y: int, centre: tuple[int, int]) -> int:
    dx, dy = _SIDES[side]
    if not (dx or dy):
        dx, dy = 0, 1
    px, py = x - centre[0], y - centre[1]
    if dx and dy:
        return (-px * dy + py * dx) * _R2 // ONE
    return -px * dy + py * dx


def _seed(frame: WorldFrame, feature: LandFeature) -> bytes:
    return hashlib.sha256(f"{frame.seed}:{feature.id}".encode()).digest()[:16]


def _point_of(frame: WorldFrame, feature: LandFeature) -> tuple[int, int]:
    """A placed feature's middle: on its side's line, offset along it; or the world's centre."""
    v = feature.values
    side, distance, offset = str(v["side"]), int(v["distance_mm"]), int(v.get("offset_mm", 0))
    cx, cy = frame.centre
    if side == "centre":
        return cx + offset, cy + distance
    dx, dy = _SIDES[side]
    reach = frame.half_along(side) + distance
    if dx and dy:
        ux, uy = dx * _R2, dy * _R2  # unit along, fixed point
        return (
            cx + (ux * reach - uy * offset) // ONE,
            cy + (uy * reach + ux * offset) // ONE,
        )
    return cx + dx * reach - dy * offset, cy + dy * reach + dx * offset


class _Grid:
    """The samples a contribution is computed over: axes and their row-major points."""

    def __init__(self, xs: Sequence[int], ys: Sequence[int]) -> None:
        self.xs, self.ys = list(xs), list(ys)
        self.points = [(x, y) for y in self.ys for x in self.xs]


# ---------------------------------------------------------------------------- additive features


def _tilt(frame: WorldFrame, f: LandFeature, grid: _Grid) -> list[int]:
    side, reach = str(f.values["side"]), int(f.values["reach_mm"])
    grade, c = int(f.values["grade_permille"]), frame.centre
    return [max(-reach, min(reach, _along(side, x, y, c))) * grade // 1000 for x, y in grid.points]


def _rise(frame: WorldFrame, f: LandFeature, grid: _Grid) -> list[int]:
    v, c = f.values, frame.centre
    side = str(v["side"])
    half_w, half_d = int(v["width_mm"]) // 2, int(v["depth_mm"]) // 2
    if side == "centre":
        mx, my = _point_of(frame, f)
        envelope = []
        for x, y in grid.points:
            p, q = (x - mx) * ONE // half_w, (y - my) * ONE // half_d
            d2 = p * p + q * q
            envelope.append(smooth(ONE - d2 // ONE) if d2 < ONE * ONE else 0)
    else:
        reach = frame.half_along(side) + int(v["distance_mm"]) + half_d
        offset = int(v["offset_mm"])
        envelope = []
        for x, y in grid.points:
            u = _along(side, x, y, c) - reach
            w = _across(side, x, y, c) - offset
            p, q = w * ONE // half_w, u * ONE // half_d
            d2 = p * p + q * q
            envelope.append(smooth(ONE - d2 // ONE) if d2 < ONE * ONE else 0)
    if not any(envelope):
        return envelope
    rough = int(v["roughness_permille"])
    if rough:
        wavelength = max(8_000, min(half_w, half_d) // 2)
        noise = fbm_grid(_seed(frame, f), grid.xs, grid.ys, wavelength, 5, ridged=True)
        envelope = [
            e * (1000 - rough + rough * n // 32_768) // 1000
            for e, n in zip(envelope, noise, strict=True)
        ]
    height = int(v["height_mm"])
    return [height * e // ONE for e in envelope]


def _valley(frame: WorldFrame, f: LandFeature, grid: _Grid) -> list[int]:
    v, c = f.values, frame.centre
    side, offset = str(v["side"]), int(v["offset_mm"])
    half, floor, depth = int(v["width_mm"]) // 2, int(v["floor_mm"]) // 2, int(v["depth_mm"])
    out = []
    for x, y in grid.points:
        d = abs(_across(side, x, y, c) - offset)
        if d <= floor:
            out.append(-depth)
        elif d >= half:
            out.append(0)
        else:
            out.append(-depth * smooth(ONE - (d - floor) * ONE // max(1, half - floor)) // ONE)
    return out


def _undulation(frame: WorldFrame, f: LandFeature, grid: _Grid) -> list[int]:
    amplitude, wavelength = int(f.values["amplitude_mm"]), int(f.values["wavelength_mm"])
    noise = fbm_grid(_seed(frame, f), grid.xs, grid.ys, wavelength, 4)
    return [n * amplitude // 32_768 for n in noise]


def _range(frame: WorldFrame, f: LandFeature, grid: _Grid) -> list[int]:
    v, c = f.values, frame.centre
    side, band = str(v["side"]), int(v["band_mm"])
    distance, width, offset = int(v["distance_mm"]), int(v["width_mm"]), int(v["offset_mm"])
    envelope = []
    for x, y in grid.points:
        u = _along(side, x, y, c) - distance
        if u <= -band:
            envelope.append(0)
            continue
        rise = smooth((u + band) * ONE // band) if u < 0 else ONE
        if width:
            w = abs(_across(side, x, y, c) - offset)
            half, fade = width // 2, max(1, width // 4)
            if w >= half + fade:
                rise = 0
            elif w > half:
                rise = rise * smooth((half + fade - w) * ONE // fade) // ONE
        envelope.append(rise)
    if not any(envelope):
        return envelope
    noise = fbm_grid(_seed(frame, f), grid.xs, grid.ys, int(v["wavelength_mm"]), 6, ridged=True)
    rugged, height = int(v["ruggedness_permille"]), int(v["height_mm"])
    out = []
    for e, n in zip(envelope, noise, strict=True):
        lift = max(0, min(1100, 300 + n * 700 // 32_768))
        lift = lift * rugged // 1000 + (1000 - rugged) * 6 // 10
        out.append(height * e // ONE * lift // 1000)
    return out


_ADDITIVE: Final = {
    "tilt": _tilt, "rise": _rise, "valley": _valley, "undulation": _undulation, "range": _range,
}  # fmt: skip

# ---------------------------------------------------------------------------- shaping features


def _terraces(
    frame: WorldFrame, land: LandDocument, f: LandFeature, grid: _Grid, h: list[int]
) -> None:
    """Steps cut into a slope: within each tier of natural rise the lower part is held level, a
    bench, and the upper part (``riser_share_permille`` of the tier) is a bank climbing the whole
    tier, so a bank is no steeper than the slope beneath divided by its share. A function of each
    point's own height: the backdrop and the near land agree wherever they meet."""
    v, c = f.values, frame.centre
    side = str(v["side"])
    start = frame.half_along(side) + int(v["distance_mm"])
    depth, half, fade = int(v["depth_mm"]), int(v["width_mm"]) // 2, int(v["fade_mm"])
    tier, base, offset = int(v["tier_height_mm"]), land.ground_mm, int(v["offset_mm"])
    bench = tier - tier * int(v["riser_share_permille"]) // 1000
    for k, (x, y) in enumerate(grid.points):
        u = _along(side, x, y, c) - start
        w = abs(_across(side, x, y, c) - offset)
        if u < -fade or u > depth + fade or w > half + fade or h[k] <= base:
            continue
        step, part = divmod(h[k] - base, tier)
        held = base + step * tier + max(0, part - bench) * tier // (tier - bench)
        weight = ONE
        for edge in (u + fade, depth + fade - u, half + fade - w):
            if edge < 2 * fade:
                weight = min(weight, smooth(edge * ONE // (2 * fade)))
        h[k] += (held - h[k]) * weight // ONE


def _shore(
    frame: WorldFrame, land: LandDocument, f: LandFeature, grid: _Grid, h: list[int]
) -> None:
    v, c = f.values, frame.centre
    side = str(v["side"])
    line = frame.half_along(side) + int(v["distance_mm"])
    beach, top = int(v["beach_mm"]), int(v["beach_top_mm"])
    depth, grade = int(v["sea_depth_mm"]), int(v["coast_grade_permille"])
    wander_mm = int(v["wander_mm"])
    wander = (
        fbm_grid(_seed(frame, f), grid.xs, grid.ys, SHORE_WANDER_PERIOD_MM, 3)
        if wander_mm
        else [0] * len(grid.points)
    )
    shelf = 20_000
    for k, (x, y) in enumerate(grid.points):
        s = _along(side, x, y, c) - line - wander[k] * wander_mm // 32_768  # positive seaward
        if s <= -beach:
            limit = top + (-s - beach) * grade // 1000
        elif s <= 0:
            limit = 300 + (top - 300) * (-s) // max(1, beach)
        elif s <= shelf:
            limit = 300 - 2_300 * s // shelf
        else:
            limit = -2_000 - min(depth - 2_000, (s - shelf) * depth // 120_000)
        if h[k] > limit:
            h[k] = limit


_LEVELS: dict[tuple[str, WorldFrame, str], int] = {}


def _basin_level(frame: WorldFrame, land: LandDocument, f: LandFeature) -> int:
    """The lowest sample on the ring just outside a basin, before it is carved, less a freeboard.

    Kept per land, world and basin for the process: a basin's level is asked for every grid that
    reaches it, and an earlier basin's again inside a later one's."""
    key = (land.sha256, frame, f.id)
    if key not in _LEVELS:
        if len(_LEVELS) > 4096:
            _LEVELS.clear()
        _LEVELS[key] = _ring_level(frame, land, f)
    return _LEVELS[key]


def _ring_level(frame: WorldFrame, land: LandDocument, f: LandFeature) -> int:
    cx, cy = _point_of(frame, f)
    r, outer = int(f.values["radius_mm"]), int(f.values["radius_mm"]) + BASIN_RIM_MM
    lowest: int | None = None
    y_low = -(-(cy - outer) // CELL_MM) * CELL_MM
    for y in range(y_low, cy + outer + 1, CELL_MM):
        row = [
            x
            for x in range(-(-(cx - outer) // CELL_MM) * CELL_MM, cx + outer + 1, CELL_MM)
            if r * r <= (x - cx) * (x - cx) + (y - cy) * (y - cy) < outer * outer
        ]
        if not row:
            continue
        heights = _heights(land, frame, row, [y], until=f.id)
        low = min(heights)
        lowest = low if lowest is None else min(lowest, low)
    assert lowest is not None
    return lowest - int(f.values["freeboard_mm"])


def _basin(
    frame: WorldFrame, land: LandDocument, f: LandFeature, grid: _Grid, h: list[int]
) -> None:
    cx, cy = _point_of(frame, f)
    r = int(f.values["radius_mm"])
    level = _basin_level(frame, land, f)
    freeboard, depth, shelf = (
        int(f.values["freeboard_mm"]), int(f.values["depth_mm"]), int(f.values["shelf_mm"]),
    )  # fmt: skip
    for k, (x, y) in enumerate(grid.points):
        d2 = (x - cx) * (x - cx) + (y - cy) * (y - cy)
        if d2 >= r * r:
            continue
        inward = r - integer_sqrt(d2)
        if inward < shelf:
            target = level + freeboard - (freeboard + 400) * inward // max(1, shelf)
        else:
            t = min(ONE, (inward - shelf) * ONE // max(1, r - shelf))
            target = level - 400 - (depth - 400) * smooth(2 * t) // ONE
        if h[k] > target:
            h[k] = target


_SHAPING: Final = {"terraces": _terraces, "shore": _shore, "basin": _basin}


def _ordered(land: LandDocument) -> list[LandFeature]:
    additive = [f for f in land.features if f.kind in _ADDITIVE]
    shaping = sorted(
        (f for f in land.features if f.kind in _SHAPING),
        key=lambda f: _SHAPING_ORDER.index(f.kind),
    )
    return additive + shaping


def _heights(
    land: LandDocument, frame: WorldFrame, xs: Sequence[int], ys: Sequence[int], *, until: str = ""
) -> list[int]:
    grid = _Grid(xs, ys)
    h = [land.ground_mm] * len(grid.points)
    for feature in _ordered(land):
        if feature.id == until:
            break
        if feature.kind in _ADDITIVE:
            for k, value in enumerate(_ADDITIVE[feature.kind](frame, feature, grid)):
                h[k] += value
        else:
            _SHAPING[feature.kind](frame, land, feature, grid, h)
    return h


def land_heights(
    land: LandDocument, frame: WorldFrame, xs: Sequence[int], ys: Sequence[int]
) -> tuple[int, ...]:
    """``H`` at every (x, y) of the grid, rows of ``ys``, row-major. Integers only."""
    return tuple(_heights(land, frame, xs, ys))


def height_at(land: LandDocument, frame: WorldFrame, x_mm: int, y_mm: int) -> int:
    return _heights(land, frame, [x_mm], [y_mm])[0]


# ---------------------------------------------------------------------------- water


@dataclass(frozen=True, slots=True)
class WaterBody:
    """Water over the land: the sea at the datum on a side, a lake in a basin, or a pond a layout
    grades. ``centre_mm`` and ``radius_mm`` place a lake; ``rect_mm`` a pond; a sea states its
    side."""

    id: str
    kind: str
    level_mm: int
    side: str = ""
    centre_mm: tuple[int, int] = (0, 0)
    radius_mm: int = 0
    rect_mm: tuple[int, int, int, int] = (0, 0, 0, 0)

    def document(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "kind": self.kind, "level_mm": self.level_mm}
        if self.kind == "sea":
            out["side"] = self.side
        elif self.kind == "lake":
            out["centre_mm"], out["radius_mm"] = list(self.centre_mm), self.radius_mm
        else:
            out["rect_mm"] = list(self.rect_mm)
        return out


def water_bodies(land: LandDocument, frame: WorldFrame) -> tuple[WaterBody, ...]:
    out = []
    for f in _ordered(land):
        if f.kind == "shore":
            out.append(WaterBody(id=f.id, kind="sea", level_mm=0, side=str(f.values["side"])))
        elif f.kind == "basin" and f.values["water"] == "fill":
            out.append(
                WaterBody(
                    id=f.id,
                    kind="lake",
                    level_mm=_basin_level(frame, land, f),
                    centre_mm=_point_of(frame, f),
                    radius_mm=int(f.values["radius_mm"]),
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------- near land


def near_chunks(frame: WorldFrame) -> tuple[tuple[int, int], ...]:
    """The chunks the world's extent touches and one ring round them, rows from the south-west."""
    x_last = -(-frame.width_mm // CHUNK_MM) - 1
    y_last = -(-frame.depth_mm // CHUNK_MM) - 1
    return tuple((x, y) for y in range(-1, y_last + 2) for x in range(-1, x_last + 2))


def near_domain(frame: WorldFrame) -> tuple[int, int, int, int]:
    chunks = near_chunks(frame)
    xs = [x for x, _ in chunks]
    ys = [y for _, y in chunks]
    return (
        min(xs) * CHUNK_MM,
        min(ys) * CHUNK_MM,
        (max(xs) + 1) * CHUNK_MM,
        (max(ys) + 1) * CHUNK_MM,
    )


def _check_ranges(land: LandDocument, frame: WorldFrame) -> None:
    x0, y0, x1, y1 = near_domain(frame)
    c = frame.centre
    for f in land.features:
        if f.kind != "range":
            continue
        side = str(f.values["side"])
        foot = int(f.values["distance_mm"]) - int(f.values["band_mm"])
        near = max(_along(side, x, y, c) for x in (x0, x1) for y in (y0, y1))
        if foot < near:
            raise LandformRefused(
                f"range {f.id} would begin to rise {foot} mm from the world's middle, inside the "
                f"walkable land, which reaches {near} mm toward {side}; a range is drawn only",
                path=f"features[{land.features.index(f)}]",
                code="landform_range_too_near",
            )


def _check_basins(land: LandDocument, frame: WorldFrame) -> None:
    basins = [f for f in land.features if f.kind == "basin"]
    for k, a in enumerate(basins):
        for b in basins[k + 1 :]:
            (ax, ay), (bx, by) = _point_of(frame, a), _point_of(frame, b)
            reach = int(a.values["radius_mm"]) + int(b.values["radius_mm"]) + 2 * BASIN_RIM_MM
            if (ax - bx) * (ax - bx) + (ay - by) * (ay - by) < reach * reach:
                raise LandformRefused(
                    f"basins {a.id} and {b.id} overlap or share a rim; one would spill the other",
                    code="landform_basins_overlap",
                )


@dataclass(frozen=True)
class NearLand:
    """Heights on the 1 m lattice over a rectangle, rows from the south, row-major."""

    x0: int
    y0: int
    nx: int
    ny: int
    heights: tuple[int, ...]

    @property
    def domain_mm(self) -> tuple[int, int, int, int]:
        return (
            self.x0,
            self.y0,
            self.x0 + (self.nx - 1) * CELL_MM,
            self.y0 + (self.ny - 1) * CELL_MM,
        )

    def index(self, x: int, y: int) -> int:
        i, j = (x - self.x0) // CELL_MM, (y - self.y0) // CELL_MM
        if (
            (x - self.x0) % CELL_MM
            or (y - self.y0) % CELL_MM
            or not (0 <= i < self.nx and 0 <= j < self.ny)
        ):
            raise KeyError((x, y))
        return j * self.nx + i

    def at(self, x: int, y: int) -> int:
        return self.heights[self.index(x, y)]

    def samples(self) -> Iterator[tuple[int, int, int]]:
        for j in range(self.ny):
            y = self.y0 + j * CELL_MM
            for i in range(self.nx):
                yield self.x0 + i * CELL_MM, y, self.heights[j * self.nx + i]

    def chunk(self, chunk_x: int, chunk_y: int) -> LandChunk:
        n = SAMPLES_PER_SIDE
        i0, j0 = (
            (chunk_x * CHUNK_MM - self.x0) // CELL_MM,
            (chunk_y * CHUNK_MM - self.y0) // CELL_MM,
        )
        if i0 < 0 or j0 < 0 or i0 + n > self.nx or j0 + n > self.ny:
            raise KeyError((chunk_x, chunk_y))
        rows = (
            self.heights[(j0 + j) * self.nx + i0 : (j0 + j) * self.nx + i0 + n] for j in range(n)
        )
        return LandChunk(chunk_x, chunk_y, CELL_MM, n, tuple(h for row in rows for h in row))

    def chunks(self) -> tuple[LandChunk, ...]:
        x0, y0, x1, y1 = self.domain_mm
        return tuple(
            self.chunk(cx, cy)
            for cy in range(-(-y0 // CHUNK_MM), (y1 - CHUNK_MM) // CHUNK_MM + 1)
            for cx in range(-(-x0 // CHUNK_MM), (x1 - CHUNK_MM) // CHUNK_MM + 1)
        )


def _bounded(heights: Sequence[int], where: str) -> None:
    low, high = min(heights), max(heights)
    if low < -NEAR_BOUND_MM or high > NEAR_BOUND_MM:
        raise LandformRefused(
            f"the land reaches {low} to {high} mm in {where}; near land lies "
            f"within {NEAR_BOUND_MM} mm of the sea's level either way",
            code="landform_near_out_of_bounds",
        )


def _realized(
    land: LandDocument, frame: WorldFrame, x0: int, y0: int, x1: int, y1: int, where: str
) -> NearLand:
    if any(v % CELL_MM for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
        raise LandformRefused("a region's corners lie on the 1 m lattice, south-west first")
    _check_ranges(land, frame)
    _check_basins(land, frame)
    xs = list(range(x0, x1 + 1, CELL_MM))
    ys = list(range(y0, y1 + 1, CELL_MM))
    heights = _heights(land, frame, xs, ys)
    _bounded(heights, where)
    return NearLand(x0, y0, len(xs), len(ys), tuple(heights))


def realize_region(
    land: LandDocument, frame: WorldFrame, x0: int, y0: int, x1: int, y1: int
) -> NearLand:
    """Near land over any rectangle on the 1 m lattice (corners inclusive)."""
    return _realized(land, frame, x0, y0, x1, y1, f"the region ({x0}, {y0}) to ({x1}, {y1})")


def realize_near(land: LandDocument, frame: WorldFrame) -> NearLand:
    """The world's walkable land: its extent and one ring of chunks round it."""
    return _realized(land, frame, *near_domain(frame), "the land near the world")


def realize_chunk(land: LandDocument, frame: WorldFrame, chunk_x: int, chunk_y: int) -> LandChunk:
    x0, y0 = chunk_x * CHUNK_MM, chunk_y * CHUNK_MM
    near = _realized(
        land, frame, x0, y0, x0 + CHUNK_MM, y0 + CHUNK_MM, f"chunk ({chunk_x}, {chunk_y})"
    )
    return near.chunk(chunk_x, chunk_y)


# ---------------------------------------------------------------------------- chunks


@dataclass(frozen=True)
class LandChunk:
    """One chunk of near land in the city's terrain shape: rows from the south-west, 1 m apart."""

    chunk_x: int
    chunk_y: int
    cell_mm: int
    samples_per_side: int
    height_mm: tuple[int, ...]

    def document(self) -> dict[str, Any]:
        return {
            "profile": CHUNK_PROFILE,
            "chunk": [self.chunk_x, self.chunk_y],
            "cell_mm": self.cell_mm,
            "samples_per_side": self.samples_per_side,
            "height_mm": list(self.height_mm),
        }

    @functools.cached_property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document())).hexdigest()

    def slope_millionths(self) -> tuple[int, ...]:
        """The city's exact slope rule (``city/terrain.py``), sample by sample."""
        side, h = self.samples_per_side, self.height_mm
        out = []
        for row in range(side):
            for column in range(side):
                here = h[row * side + column]
                across = column + 1 if column + 1 < side else column - 1
                up = row + 1 if row + 1 < side else row - 1
                rise = max(abs(h[row * side + across] - here), abs(h[up * side + column] - here))
                out.append(rise * MILLIONTHS // self.cell_mm)
        return tuple(out)


def read_land_chunk(raw: object, expected_sha256: str | None = None) -> LandChunk:
    if not isinstance(raw, dict) or set(raw) != {
        "profile", "chunk", "cell_mm", "samples_per_side", "height_mm",
    }:  # fmt: skip
        raise LandformRefused(
            "a land chunk has exactly profile, chunk, cell_mm, samples_per_side, height_mm"
        )
    if raw["profile"] != CHUNK_PROFILE:
        raise LandformRefused(f"profile is {CHUNK_PROFILE}", path="profile")
    chunk = raw["chunk"]
    if not (isinstance(chunk, list) and len(chunk) == 2 and all(type(v) is int for v in chunk)):
        raise LandformRefused("chunk is two whole numbers", path="chunk")
    if raw["cell_mm"] != CELL_MM or raw["samples_per_side"] != SAMPLES_PER_SIDE:
        raise LandformRefused(
            f"a v1 chunk is {SAMPLES_PER_SIDE} samples a side, {CELL_MM} mm apart", path="cell_mm"
        )
    heights = raw["height_mm"]
    if not (
        isinstance(heights, list)
        and len(heights) == SAMPLES_PER_SIDE * SAMPLES_PER_SIDE
        and all(type(h) is int and -NEAR_BOUND_MM <= h <= NEAR_BOUND_MM for h in heights)
    ):
        raise LandformRefused(
            "height_mm is every sample, a whole number within the near bound", path="height_mm"
        )
    out = LandChunk(chunk[0], chunk[1], CELL_MM, SAMPLES_PER_SIDE, tuple(heights))
    if expected_sha256 is not None and out.sha256 != expected_sha256:
        raise LandformRefused(
            "the chunk is not the one its digest names", code="landform_digest_mismatch"
        )
    return out


# ---------------------------------------------------------------------------- backdrop


def _axis(low: int, high: int, near_low: int, near_high: int) -> list[int]:
    inner = list(range(near_low, near_high + 1, BACKDROP_NEAR_STEP_MM))
    upward, step, value = [], BACKDROP_NEAR_STEP_MM, near_high
    while value < high:
        step = min(BACKDROP_FAR_STEP_MM, step * BACKDROP_GROWTH_PERMILLE // 1000)
        value = min(high, value + step)
        upward.append(value)
    downward, step, value = [], BACKDROP_NEAR_STEP_MM, near_low
    while value > low:
        step = min(BACKDROP_FAR_STEP_MM, step * BACKDROP_GROWTH_PERMILLE // 1000)
        value = max(low, value - step)
        downward.append(value)
    return downward[::-1] + inner + upward


@dataclass(frozen=True)
class Backdrop:
    """The land drawn to the horizon: heights on a coarse grid, and the near land it lies under."""

    near_mm: tuple[int, int, int, int]
    x_mm: tuple[int, ...]
    y_mm: tuple[int, ...]
    height_mm: tuple[int, ...]
    water: tuple[WaterBody, ...]

    def height(self, x_mm: int, y_mm: int) -> int:
        return self.height_mm[self.y_mm.index(y_mm) * len(self.x_mm) + self.x_mm.index(x_mm)]

    def document(self) -> dict[str, Any]:
        return {
            "profile": BACKDROP_PROFILE,
            "near_mm": list(self.near_mm),
            "x_mm": list(self.x_mm),
            "y_mm": list(self.y_mm),
            "height_mm": list(self.height_mm),
            "water": [body.document() for body in self.water],
        }

    @functools.cached_property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document())).hexdigest()


def realize_backdrop(
    land: LandDocument, frame: WorldFrame, reach_mm: int = BACKDROP_REACH_MM
) -> Backdrop:
    _check_ranges(land, frame)
    _check_basins(land, frame)
    near = near_domain(frame)
    cx, cy = frame.centre
    xs = _axis(cx - reach_mm, cx + reach_mm, near[0], near[2])
    ys = _axis(cy - reach_mm, cy + reach_mm, near[1], near[3])
    return Backdrop(
        near_mm=near,
        x_mm=tuple(xs),
        y_mm=tuple(ys),
        height_mm=tuple(_heights(land, frame, xs, ys)),
        water=water_bodies(land, frame),
    )
