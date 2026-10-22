"""Grading: what a layout does to the land so it can stand on it and walk it.

A grammar lays out its world on the land and then grades it here, on the 1 m lattice of the
realized near land, in a fixed order:

1. **Pads with a stated level** are set flat. They pin what follows.
2. **Corridors** (paths, streets) are graded along their length, in order: the profile is the land's
   own, brought within the corridor's grade by the midpoint of its largest and smallest
   grade-limited envelopes (so it cuts and fills by the least it must), then held to every level
   already fixed under its centre line (a pad, or a corridor it crosses, which keeps the crossing).
   A corridor is level across, except where it crosses a corridor graded before it. A **ramp** (a
   corridor with stated end levels) is the straight line between them instead, over its length;
   the layout has already said where it stands, and cells fixed before it keep their levels.
3. **Pads with a door** are set flat at the height of the ground at their door after the corridors;
   a pad with neither a level nor a door takes the land's height at its middle.
4. **Banks**: every cell not fixed above is held between the cones of the fixed cells at the bank
   grade, so no bank is steeper. Where two fixed cells are closer than their difference allows, the
   cones cross and a retaining wall takes the difference; walls are listed with their height.
   Under a plan with an **ease** grade, a bank's first cell off the level ground it leaves (its
   crest) and the land's first cell past it (its toe) step no steeper than the ease, the bank
   grade between them, so a bank reads as a slope rounding into the ground above and below it
   rather than a face cut straight off the edge; the bank grade's cones still bound every cell, so
   no wall stands where none did, and land more than two cells beyond the bank keeps its shape.
   Where the plan asks for them, every lattice edge whose samples differ by more than the bank
   grade over one cell, one of them fixed, is a retaining wall's: a seam where two pads, or a pad
   and a corridor, meet at levels a bank cannot join. Edges along one lattice line rising to the
   same side join into one run, listed on the line of its low side. No height moves.
   Where the plan lets a terrace hold a wall and a bank would cut or fill a cell past the bound, the
   pad whose cone set that cell stands in a retaining wall instead: its cones start that much above
   and below its level, raised by the excess up to the most a wall holds, and the banks are graded
   again, so the land behind the wall keeps more of its own shape. A plan within the bound grades as
   though no wall could be held; a corridor never holds one.
5. **Ponds** are carved as ellipses inscribed in their rectangles, below a level that is the
   lowest ground on the ring just outside them less a freeboard, so the water holds.

Before any of them, a layout whose pads or corridors would cross a cascade's pools or falls is
refused (``landform_cascade_crossed``): a layout stands beside a cascade.

Then the checks, each refused by name with the figure: cut and fill within their bound; every
water body holds (its dry neighbours stand at or above its level; a cascade's falls are its drops
and are not held); every door reachable from the entry over ground walked within the walking grade,
never through a wall or water; the near bound.

Pure and integer: the same land and plan grade to the same heights.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.landform.document import LandformRefused
from exulanica.grammar.landform.noise import ONE
from exulanica.grammar.landform.realize import (
    CELL_MM,
    NEAR_BOUND_MM,
    NearLand,
    WaterBody,
)

__all__ = [
    "BANK_GRADE_PERMILLE",
    "CUT_FILL_MOST_MM",
    "DRY_ABOVE_WATER_MM",
    "WALK_GRADE_PERMILLE",
    "Basin",
    "Corridor",
    "GradedLand",
    "GradingPlan",
    "Pad",
    "RetainingWall",
    "Wall",
    "grade_land",
    "within_water",
]

#: The steepest a bank is cut or filled: 1 in 2, the usual stable grassed bank.
BANK_GRADE_PERMILLE: Final = 500
#: The deepest a pad, corridor or bank may cut into or fill above the land.
CUT_FILL_MOST_MM: Final = 8_000
#: The steepest open ground a person walks: 1 in 4.
WALK_GRADE_PERMILLE: Final = 250
#: Ground less than this above a water's level is water's edge, not walked (the exact contact's
#: dry rule, ``heightfield_contact.py``).
DRY_ABOVE_WATER_MM: Final = 350
_FAR: Final = 1 << 60


@dataclass(frozen=True, slots=True)
class Corridor:
    """A path or a street: a rectangle graded along ``axis`` (``x`` east or ``y`` north). With
    ``levels_mm`` it is a ramp: its levels at its low and high ends along ``axis``, stated."""

    id: str
    rect_mm: tuple[int, int, int, int]
    axis: str
    grade_permille: int
    levels_mm: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class Pad:
    """Level ground for a building, a seat, a plaza or a whole yard: a stated level, or its door's
    height. A pad that holds water lets a pond be carved into it (a yard's own pond)."""

    id: str
    rect_mm: tuple[int, int, int, int]
    level_mm: int | None = None
    door_mm: tuple[int, int] | None = None
    water_allowed: bool = False


@dataclass(frozen=True, slots=True)
class Basin:
    """A pond a layout places: carved as the ellipse inscribed in its rectangle."""

    id: str
    rect_mm: tuple[int, int, int, int]
    depth_mm: int
    shelf_mm: int
    freeboard_mm: int


@dataclass(frozen=True, slots=True)
class Wall:
    x_mm: int
    y_mm: int
    height_mm: int


@dataclass(frozen=True, slots=True)
class RetainingWall:
    """A retaining wall where two levels meet over one lattice cell: a run along x or y on the
    lattice line of its low side, from ``from_mm`` to ``to_mm`` (lattice points, the first before
    the second along the run), the land rising one cell toward ``high`` (a main side)."""

    from_mm: tuple[int, int]
    to_mm: tuple[int, int]
    high: str

    def document(self) -> dict[str, Any]:
        return {"from_mm": list(self.from_mm), "to_mm": list(self.to_mm), "high": self.high}


@dataclass(frozen=True, slots=True)
class GradingPlan:
    corridors: tuple[Corridor, ...] = ()
    pads: tuple[Pad, ...] = ()
    basins: tuple[Basin, ...] = ()
    entry_mm: tuple[int, int] = (0, 0)
    bank_grade_permille: int = BANK_GRADE_PERMILLE
    #: The steepest a bank's first cell off its level ground and the land's first cell past it step;
    #: 0 eases none, and the bank stands straight at its grade from edge to land, as it always did.
    bank_ease_permille: int = 0
    cut_fill_most_mm: int = CUT_FILL_MOST_MM
    walk_grade_permille: int = WALK_GRADE_PERMILLE
    retaining_walls: bool = False
    #: The most a pad's retaining wall holds where its bank would cut or fill past the bound; 0
    #: holds none, and the layout is refused there as it always was.
    held_most_mm: int = 0


@dataclass(frozen=True)
class GradedLand:
    near: NearLand
    pads: tuple[tuple[str, int], ...]
    water: tuple[WaterBody, ...]
    walls: tuple[Wall, ...]
    report: Mapping[str, int] = field(default_factory=dict)
    #: The retaining walls where levels meet, sorted by axis (runs along x first), line and start;
    #: None when the plan asked for none.
    retaining: tuple[RetainingWall, ...] | None = None


class _Work:
    def __init__(self, near: NearLand) -> None:
        self.near = near
        self.h = list(near.heights)
        self.locked = [False] * len(self.h)
        self.owner = [""] * len(self.h)

    def cells(self, rect: tuple[int, int, int, int]) -> list[int]:
        x0, y0, x1, y1 = rect
        n = self.near
        i0 = max(0, -(-(x0 - n.x0) // CELL_MM))
        i1 = min(n.nx - 1, (x1 - n.x0) // CELL_MM)
        j0 = max(0, -(-(y0 - n.y0) // CELL_MM))
        j1 = min(n.ny - 1, (y1 - n.y0) // CELL_MM)
        return [j * n.nx + i for j in range(j0, j1 + 1) for i in range(i0, i1 + 1)]

    def cell(self, x: int, y: int) -> int:
        n = self.near
        i, j = (x - n.x0) // CELL_MM, (y - n.y0) // CELL_MM
        if not (0 <= i < n.nx and 0 <= j < n.ny):
            raise LandformRefused(f"({x}, {y}) lies outside the land being graded")
        return j * n.nx + i

    def place(self, index: int) -> tuple[int, int]:
        n = self.near
        return n.x0 + index % n.nx * CELL_MM, n.y0 + index // n.nx * CELL_MM

    def fix(self, index: int, level: int, owner: str) -> None:
        self.h[index] = level
        self.locked[index] = True
        self.owner[index] = owner


def _pad(work: _Work, pad: Pad, level: int, *, keep_fixed: bool = False) -> int:
    """Set a pad's cells level. Set after the corridors (``keep_fixed``), it keeps every cell a
    corridor has already fixed, so a yard meeting its path never moves the path."""
    for index in work.cells(pad.rect_mm):
        if keep_fixed and work.locked[index]:
            continue
        work.fix(index, level, pad.id)
    return level


def _lipschitz_midpoint(values: list[int], step: int) -> list[int]:
    upper, lower = list(values), list(values)
    for k in range(1, len(values)):
        upper[k] = max(upper[k], upper[k - 1] - step)
        lower[k] = min(lower[k], lower[k - 1] + step)
    for k in range(len(values) - 2, -1, -1):
        upper[k] = max(upper[k], upper[k + 1] - step)
        lower[k] = min(lower[k], lower[k + 1] + step)
    return [(u + low) // 2 for u, low in zip(upper, lower, strict=True)]


def _corridor(work: _Work, corridor: Corridor) -> int:
    x0, y0, x1, y1 = corridor.rect_mm
    along_y = corridor.axis == "y"
    if corridor.axis not in ("x", "y"):
        raise LandformRefused(f"corridor {corridor.id} runs along x or y")
    centre = (x0 + x1) // 2 // CELL_MM * CELL_MM if along_y else (y0 + y1) // 2 // CELL_MM * CELL_MM
    low, high = (y0, y1) if along_y else (x0, x1)
    stations = list(range(-(-low // CELL_MM) * CELL_MM, high + 1, CELL_MM))
    stations = [s for s in stations if _inside(work, (centre, s) if along_y else (s, centre))]
    if not stations:
        return 0
    middle = [work.cell(centre, s) if along_y else work.cell(s, centre) for s in stations]
    step = corridor.grade_permille * CELL_MM // 1000
    pins: list[tuple[int, int, str]]
    if corridor.levels_mm is not None:
        first, last = corridor.levels_mm
        profile = [first + (last - first) * (s - low) // max(1, high - low) for s in stations]
        pins = []
    else:
        profile = _lipschitz_midpoint([work.h[i] for i in middle], step)
        pins = [(k, work.h[i], work.owner[i]) for k, i in enumerate(middle) if work.locked[i]]
    if pins:
        floor = [-_FAR] * len(stations)
        ceiling = [_FAR] * len(stations)
        for k, level, _owner in pins:
            floor[k], ceiling[k] = max(floor[k], level), min(ceiling[k], level)
        for k in range(1, len(stations)):
            floor[k] = max(floor[k], floor[k - 1] - step)
            ceiling[k] = min(ceiling[k], ceiling[k - 1] + step)
        for k in range(len(stations) - 2, -1, -1):
            floor[k] = max(floor[k], floor[k + 1] - step)
            ceiling[k] = min(ceiling[k], ceiling[k + 1] + step)
        for k in range(len(stations)):
            if floor[k] > ceiling[k]:
                (ka, la, oa), (kb, lb, ob) = _conflict(pins, step)
                raise LandformRefused(
                    f"corridor {corridor.id} cannot join {oa} at {la} mm and {ob} at {lb} mm "
                    f"{abs(stations[kb] - stations[ka])} mm apart within its grade of "
                    f"{corridor.grade_permille} per mille",
                    code="landform_corridor_too_steep",
                )
        profile = [max(f, min(c, p)) for f, c, p in zip(floor, ceiling, profile, strict=True)]
    steepest = 0
    for k, station in enumerate(stations):
        if k:
            steepest = max(steepest, abs(profile[k] - profile[k - 1]) * 1000 // CELL_MM)
        rect = (x0, station, x1, station) if along_y else (station, y0, station, y1)
        for index in work.cells(rect):
            if not work.locked[index]:
                work.fix(index, profile[k], corridor.id)
    return steepest


def _inside(work: _Work, point: tuple[int, int]) -> bool:
    x0, y0, x1, y1 = work.near.domain_mm
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1


def _conflict(pins: list[tuple[int, int, str]], step: int) -> tuple:
    worst = None
    for a in pins:
        for b in pins:
            excess = abs(a[1] - b[1]) - step * abs(a[0] - b[0])
            if excess > 0 and (worst is None or excess > worst[0]):
                worst = (excess, a, b)
    assert worst is not None
    return worst[1], worst[2]


def _cones(
    work: _Work, held: Mapping[str, int], step: int, first: int, *, settle: bool
) -> tuple[list[int], list[int], list[str], list[str]]:
    """The lowest and highest each free cell may stand, and the fixed cell that sets each: cones
    down and up from every fixed cell, ``first`` (with its diagonal) for the step off the fixed cell
    and ``step`` for every step after. One forward and one backward sweep holds a cone of one grade;
    ``settle`` sweeps again until nothing moves, for a cone whose first step differs."""
    n = work.near
    nx, ny = n.nx, n.ny
    size = len(work.h)
    low = [work.h[i] - held.get(work.owner[i], 0) if work.locked[i] else -_FAR for i in range(size)]
    high = [work.h[i] + held.get(work.owner[i], 0) if work.locked[i] else _FAR for i in range(size)]
    low_owner = list(work.owner)
    high_owner = list(work.owner)
    diagonal, first_diagonal = step * 1414 // 1000, first * 1414 // 1000
    forward = ((0, -1, False), (-1, -1, True), (-1, 0, False), (-1, 1, True))
    backward = ((0, 1, False), (1, 1, True), (1, 0, False), (1, -1, True))
    moved = True
    while moved:
        moved = False
        for neighbours, rows in ((forward, range(ny)), (backward, range(ny - 1, -1, -1))):
            columns = range(nx) if neighbours is forward else range(nx - 1, -1, -1)
            for r in rows:
                for c in columns:
                    i = r * nx + c
                    if work.locked[i]:
                        continue
                    for dr, dc, across in neighbours:
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < ny and 0 <= cc < nx:
                            k = rr * nx + cc
                            if work.locked[k]:
                                cost = first_diagonal if across else first
                            else:
                                cost = diagonal if across else step
                            if low[k] - cost > low[i]:
                                low[i], low_owner[i] = low[k] - cost, low_owner[k]
                                moved = True
                            if high[k] + cost < high[i]:
                                high[i], high_owner[i] = high[k] + cost, high_owner[k]
                                moved = True
        moved = moved and settle
    return low, high, low_owner, high_owner


def _banks(
    work: _Work, grade: int, held: Mapping[str, int] | None = None, ease: int = 0
) -> list[Wall]:
    """Grade every free cell between the cones of the fixed cells at the bank grade, listing a wall
    where they cross. With an ``ease`` grade, a bank's first cell off the level ground it leaves and
    the land's first cell past it step no steeper than the ease: the bank grade's cones still bound
    every cell, so no wall stands where none did."""
    step = grade * CELL_MM // 1000
    held = held or {}
    low, high, low_owner, high_owner = _cones(work, held, step, step, settle=False)
    walls = []
    if ease:
        eased_low, eased_high, _, _ = _cones(work, held, step, ease * CELL_MM // 1000, settle=True)
        natural = list(work.h)
        side = [0] * len(work.h)
    for i in range(len(work.h)):
        if work.locked[i] or low[i] == -_FAR:
            continue
        if low[i] > high[i]:
            x, y = work.place(i)
            walls.append(Wall(x, y, low[i] - high[i]))
            work.h[i] = (low[i] + high[i]) // 2
            work.owner[i] = low_owner[i]
        elif ease and eased_low[i] <= eased_high[i] and natural[i] < eased_low[i]:
            # A fill bank, its crest eased: up to the eased cone, within the bank grade's cones.
            work.h[i] = max(low[i], min(high[i], eased_low[i]))
            work.owner[i] = low_owner[i]
            side[i] = 1
        elif ease and eased_low[i] <= eased_high[i] and natural[i] > eased_high[i]:
            work.h[i] = min(high[i], max(low[i], eased_high[i]))
            work.owner[i] = high_owner[i]
            side[i] = -1
        else:
            clamped = max(low[i], min(high[i], work.h[i]))
            if clamped != work.h[i]:
                work.owner[i] = low_owner[i] if clamped == low[i] else high_owner[i]
            work.h[i] = clamped
    if ease:
        _toe(work, side, low, high, ease * CELL_MM // 1000)
        _corners(work, side, low, high, step)
    return walls


def _toe(work: _Work, side: list[int], low: list[int], high: list[int], ease: int) -> None:
    """The land's first two rings of cells past an eased bank, on the bank's side only (raised
    beside a fill, lowered beside a cut), each brought within the ease step of the bank or ring
    cells beside it, never past the lowest fill (or highest cut) cell beside it, and within the bank
    grade's cones. Two rings, since round a corner of the
    bank's octagon a cell one ring out still meets the land a step too steep. Land further out
    keeps its own shape."""
    n = work.near
    nx, ny = n.nx, n.ny
    across = ease * 1414 // 1000
    for _ring in range(2):
        settled = list(work.h)
        moved: list[tuple[int, int, str, int]] = []
        for r in range(ny):
            for c in range(nx):
                i = r * nx + c
                if work.locked[i] or side[i] or low[i] > high[i]:
                    continue
                want, owner, way = settled[i], work.owner[i], 0
                # Never above a fill cell beside it nor below a cut cell: it meets the bank's foot.
                under, over = _FAR, -_FAR
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        rr, cc = r + dr, c + dc
                        if (dr or dc) and 0 <= rr < ny and 0 <= cc < nx:
                            k = rr * nx + cc
                            cost = across if dr and dc else ease
                            if side[k] == 1:
                                under = min(under, settled[k])
                                if settled[k] - cost > want:
                                    want, owner, way = settled[k] - cost, work.owner[k], 1
                            elif side[k] == -1:
                                over = max(over, settled[k])
                                if settled[k] + cost < want:
                                    want, owner, way = settled[k] + cost, work.owner[k], -1
                if way == 1:
                    want = max(settled[i], min(want, under))
                elif way == -1:
                    want = min(settled[i], max(want, over))
                want = max(low[i], min(high[i], want))
                if want != work.h[i]:
                    moved.append((i, want, owner, way))
        for i, want, owner, way in moved:
            work.h[i], work.owner[i], side[i] = want, owner, way


def _corners(work: _Work, side: list[int], low: list[int], high: list[int], step: int) -> None:
    """A bank's corners eased like its edges: where a lattice triangle leans past the bank grade
    and its highest corner is a fill bank cell (its lowest a cut bank cell), that cell comes down
    (or up) until the triangle leans no steeper, never past the bank grade's cones. Round a bank's
    corner the bank grade's cones step a cell's two sides at once, so a triangle there leans up to
    half as steep again as the bank. Each lattice cell is split along its south-west to north-east
    diagonal, so a triangle's right angle is its south-east or north-west corner. A triangle within
    a hundredth of the grade is left: whole millimetres put a bank's own edge a hair past it, and
    easing those would shave every cell along it."""
    n = work.near
    nx, ny = n.nx, n.ny
    h = work.h
    limit = step * step
    near = step * 101 // 100
    past = near * near
    # Each cell's two triangles: the right angle, then its legs' ends, as (row, column) steps.
    shapes = (((0, 1), (0, 0), (1, 1)), ((1, 0), (0, 0), (1, 1)))
    # Each pass only lowers fill cells and raises cut cells, in whole millimetres within their
    # cones, so the passes end.
    moved = True
    while moved:
        moved = False
        for r in range(ny - 1):
            for c in range(nx - 1):
                for shape in shapes:
                    v, a, b = ((r + dr) * nx + c + dc for dr, dc in shape)
                    da, db = h[a] - h[v], h[b] - h[v]
                    if da * da + db * db <= past:
                        continue
                    for way in (1, -1):
                        # The corner farthest out on the bank's side, if a bank cell of that side.
                        t = max((v, a, b), key=lambda k: way * h[k])
                        if work.locked[t] or side[t] != way:
                            continue
                        eased = _eased_corner(h, v, a, b, t, limit, way)
                        if eased is None:
                            continue
                        eased = max(low[t], eased) if way == 1 else min(high[t], eased)
                        if eased != h[t]:
                            h[t] = eased
                            moved = True
                        break


def _eased_corner(h: list[int], v: int, a: int, b: int, t: int, limit: int, way: int) -> int | None:
    """The height of corner ``t`` of the right triangle ``v`` (its right angle), ``a``, ``b`` at
    which the triangle leans exactly the bank grade (``limit`` its step squared), on the side
    ``way`` of the other two; None where moving ``t`` alone cannot bring it within the grade."""
    if t == v:
        p, q = h[a], h[b]
        root = 2 * limit - (p - q) * (p - q)
        if root < 0:
            return None
        middle = (p + q + way * integer_sqrt(root)) * way
        return (middle // 2) * way if way == 1 else -(middle // 2)
    other = b if t == a else a
    leg = h[other] - h[v]
    rest = limit - leg * leg
    if rest < 0:
        return None
    return h[v] + way * integer_sqrt(rest)


def _held_banks(work: _Work, plan: GradingPlan) -> list[Wall]:
    """The banks, with each pad whose bank would cut or fill a free cell past the bound held in a
    retaining wall: its cones start the wall's height above and below its level, raised by the
    excess up to :attr:`GradingPlan.held_most_mm`, and the banks graded again from the fixed cells,
    until no pad that set an offending cell can hold more. A plan whose banks stay within the bound
    is graded once, as though no wall could be held."""
    pads = {pad.id for pad in plan.pads}
    heights, owners = list(work.h), list(work.owner)
    held: dict[str, int] = {}
    while True:
        walls = _banks(work, plan.bank_grade_permille, held, plan.bank_ease_permille)
        over: dict[str, int] = {}
        for index, (graded, natural) in enumerate(zip(work.h, work.near.heights, strict=True)):
            excess = abs(graded - natural) - plan.cut_fill_most_mm
            owner = work.owner[index]
            if excess > 0 and not work.locked[index] and owner in pads:
                over[owner] = max(over.get(owner, 0), excess)
        grown = False
        for owner, excess in sorted(over.items()):
            wanted = min(plan.held_most_mm, held.get(owner, 0) + excess)
            if wanted > held.get(owner, 0):
                held[owner] = wanted
                grown = True
        if not grown:
            return walls
        work.h, work.owner = list(heights), list(owners)


def _retaining(work: _Work, grade: int) -> tuple[RetainingWall, ...]:
    """Every run of lattice edges where a fixed sample meets a neighbour more than a bank's step
    above or below it, on the line of the edges' low samples, rising toward their high ones. A run
    joins two lattice points at least: a lone edge makes none."""
    n = work.near
    step = grade * CELL_MM // 1000
    h = work.h
    edges: set[tuple[int, int]] = set()
    for a, fixed in enumerate(work.locked):
        if not fixed:
            continue
        r, c = divmod(a, n.nx)
        for rr, cc in ((r, c + 1), (r, c - 1), (r + 1, c), (r - 1, c)):
            if 0 <= rr < n.ny and 0 <= cc < n.nx:
                b = rr * n.nx + cc
                if abs(h[b] - h[a]) > step:
                    edges.add((a, b) if h[a] < h[b] else (b, a))
    lines: dict[tuple[str, int, str], list[int]] = {}
    for low, high in edges:
        (lx, ly), (hx, hy) = work.place(low), work.place(high)
        if hy == ly:
            lines.setdefault(("y", lx, "east" if hx > lx else "west"), []).append(ly)
        else:
            lines.setdefault(("x", ly, "north" if hy > ly else "south"), []).append(lx)
    runs = []
    for (axis, line, side), stations in lines.items():
        stations.sort()
        first = 0
        for k in range(1, len(stations) + 1):
            if k < len(stations) and stations[k] - stations[k - 1] == CELL_MM:
                continue
            if k - 1 > first:
                start, end = stations[first], stations[k - 1]
                runs.append((axis, line, start, end, side))
            first = k
    return tuple(
        RetainingWall(
            from_mm=(start, line) if axis == "x" else (line, start),
            to_mm=(end, line) if axis == "x" else (line, end),
            high=side,
        )
        for axis, line, start, end, side in sorted(runs)
    )


def _ellipse(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return (x0 + x1) // 2, (y0 + y1) // 2, max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2)


def _reach(x: int, y: int, ellipse: tuple[int, int, int, int]) -> int:
    """How far out a point lies on the ellipse's scale: ONE on its rim."""
    cx, cy, a, b = ellipse
    u, v = (x - cx) * ONE // a, (y - cy) * ONE // b
    return integer_sqrt(u * u + v * v)


def _pond(work: _Work, basin: Basin, pads: Sequence[Pad] = ()) -> WaterBody:
    ellipse = _ellipse(basin.rect_mm)
    cx, cy, a, b = ellipse
    short = min(a, b)
    rim_out = ONE + 2 * CELL_MM * ONE // short
    grown = (cx - a - 2 * CELL_MM, cy - b - 2 * CELL_MM, cx + a + 2 * CELL_MM, cy + b + 2 * CELL_MM)
    inside, rim = [], []
    for index in work.cells(grown):
        x, y = work.place(index)
        reach = _reach(x, y, ellipse)
        if reach < ONE:
            inside.append((index, reach))
        elif reach < rim_out:
            rim.append(work.h[index])
    holding = {pad.id for pad in pads if pad.water_allowed}
    locked = [i for i, _ in inside if work.locked[i] and work.owner[i] not in holding]
    if locked:
        x, y = work.place(locked[0])
        raise LandformRefused(
            f"pond {basin.id} would be carved over {work.owner[locked[0]]} at ({x}, {y})",
            code="landform_basin_over_locked",
        )
    if not rim:
        raise LandformRefused(f"pond {basin.id} has no ground round it to hold it")
    level = min(rim) - basin.freeboard_mm
    for index, reach in inside:
        inward = (ONE - reach) * short // ONE
        if inward < basin.shelf_mm:
            target = (
                level
                + basin.freeboard_mm
                - (basin.freeboard_mm + 400) * inward // max(1, basin.shelf_mm)
            )
        else:
            t = min(ONE, (inward - basin.shelf_mm) * ONE // max(1, short - basin.shelf_mm))
            target = level - 400 - (basin.depth_mm - 400) * min(ONE, 2 * t) // ONE
        work.h[index] = min(work.h[index], target)
        work.owner[index] = basin.id
    return WaterBody(id=basin.id, kind="pond", level_mm=level, rect_mm=basin.rect_mm)


def _within(body: WaterBody, x: int, y: int) -> bool:
    if body.kind == "sea":
        return True
    if body.kind == "fall":
        return False
    if body.kind == "pool":
        x0, y0, x1, y1 = body.rect_mm
        return x0 <= x <= x1 and y0 <= y <= y1
    if body.kind == "lake":
        cx, cy = body.centre_mm
        return (x - cx) * (x - cx) + (y - cy) * (y - cy) < body.radius_mm * body.radius_mm
    return _reach(x, y, _ellipse(body.rect_mm)) < ONE


def within_water(body: WaterBody, x_mm: int, y_mm: int) -> bool:
    """Whether a point lies within a body of water's outline, the one the grading holds its water
    to: anywhere for the sea, nowhere on a fall's sheet, a pool's rectangle, a lake's circle and a
    pond's ellipse inscribed in its rectangle. The water there is where the land under the point
    lies below the body's level."""
    return _within(body, x_mm, y_mm)


def _water_holds(work: _Work, bodies: Sequence[WaterBody]) -> None:
    n = work.near
    for body in bodies:
        if body.kind in ("sea", "fall"):
            continue
        for index in range(len(work.h)):
            x, y = work.place(index)
            if work.h[index] >= body.level_mm or not _within(body, x, y):
                continue
            for dx, dy in ((CELL_MM, 0), (-CELL_MM, 0), (0, CELL_MM), (0, -CELL_MM)):
                if not _inside(work, (x + dx, y + dy)):
                    continue
                k = work.cell(x + dx, y + dy)
                if work.h[k] < body.level_mm and not _within(body, x + dx, y + dy):
                    raise LandformRefused(
                        f"{body.kind} {body.id} would spill at ({x + dx}, {y + dy}): the ground "
                        f"there is {work.h[k]} mm, below its level of {body.level_mm} mm",
                        code="landform_water_spills",
                    )
    del n


def _reachable(
    work: _Work, plan: GradingPlan, bodies: Sequence[WaterBody], walls: Sequence[Wall]
) -> None:
    doors = [(pad.id, pad.door_mm) for pad in plan.pads if pad.door_mm is not None]
    if not doors:
        return
    n = work.near
    blocked = {work.cell(wall.x_mm, wall.y_mm) for wall in walls}
    for index in range(len(work.h)):
        x, y = work.place(index)
        for body in bodies:
            if work.h[index] < body.level_mm + DRY_ABOVE_WATER_MM and _within(body, x, y):
                blocked.add(index)
    rise = plan.walk_grade_permille * CELL_MM // 1000
    start = work.cell(*plan.entry_mm)
    seen = {start}
    queue = deque([start])
    while queue:
        i = queue.popleft()
        r, c = divmod(i, n.nx)
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < n.ny and 0 <= cc < n.nx:
                k = rr * n.nx + cc
                if k not in seen and k not in blocked and abs(work.h[k] - work.h[i]) <= rise:
                    seen.add(k)
                    queue.append(k)
    for pad_id, door in doors:
        if work.cell(*door) not in seen:
            raise LandformRefused(
                f"the door of {pad_id} at ({door[0]}, {door[1]}) cannot be reached from the entry "
                f"over ground walked at {plan.walk_grade_permille} per mille or less",
                code="landform_unreachable",
            )


def _clear_of_cascades(plan: GradingPlan, water: Sequence[WaterBody]) -> None:
    """Refuse a layout whose terraces or paths would cross a cascade's pools or falls."""
    for owner, (x0, y0, x1, y1) in (
        *((pad.id, pad.rect_mm) for pad in plan.pads),
        *((corridor.id, corridor.rect_mm) for corridor in plan.corridors),
    ):
        for body in water:
            if body.kind not in ("pool", "fall"):
                continue
            bx0, by0, bx1, by1 = body.rect_mm
            if x0 <= bx1 and bx0 <= x1 and y0 <= by1 and by0 <= y1:
                raise LandformRefused(
                    f"{owner} would cross {body.kind} {body.id}; a layout stands beside a cascade",
                    code="landform_cascade_crossed",
                )


def grade_land(near: NearLand, plan: GradingPlan, water: Sequence[WaterBody] = ()) -> GradedLand:
    """Grade realized near land for a layout, or refuse it by name. ``water`` is the land's own
    water (a sea, lakes, a cascade's pools and falls), held to the same check as the ponds the plan
    carves; a layout crossing a cascade is refused."""
    _clear_of_cascades(plan, water)
    work = _Work(near)
    levels: dict[str, int] = {}
    for pad in plan.pads:
        if pad.level_mm is not None:
            levels[pad.id] = _pad(work, pad, pad.level_mm)
    steepest = 0
    for corridor in plan.corridors:
        steepest = max(steepest, _corridor(work, corridor))
    for pad in plan.pads:
        if pad.level_mm is not None:
            continue
        if pad.door_mm is not None:
            level = work.h[work.cell(*pad.door_mm)]
        else:
            x0, y0, x1, y1 = pad.rect_mm
            middle = ((x0 + x1) // 2 // CELL_MM * CELL_MM, (y0 + y1) // 2 // CELL_MM * CELL_MM)
            level = work.h[work.cell(*middle)]
        levels[pad.id] = _pad(work, pad, level, keep_fixed=True)
    walls = _held_banks(work, plan)
    retaining = _retaining(work, plan.bank_grade_permille) if plan.retaining_walls else None
    cut = fill = 0
    for index, (graded, natural) in enumerate(zip(work.h, near.heights, strict=True)):
        change = graded - natural
        cut, fill = max(cut, -change), max(fill, change)
        if abs(change) > plan.cut_fill_most_mm:
            x, y = work.place(index)
            raise LandformRefused(
                f"{work.owner[index]} would {'cut' if change < 0 else 'fill'} {abs(change)} mm "
                f"at ({x}, {y}); the bound is {plan.cut_fill_most_mm} mm",
                code="landform_cut_too_deep",
            )
    ponds = [_pond(work, basin, plan.pads) for basin in plan.basins]
    bodies = [*water, *ponds]
    _water_holds(work, bodies)
    _reachable(work, plan, bodies, walls)
    if min(work.h) < -NEAR_BOUND_MM or max(work.h) > NEAR_BOUND_MM:
        raise LandformRefused(
            f"graded land reaches {min(work.h)} to {max(work.h)} mm; the near bound is "
            f"{NEAR_BOUND_MM} mm",
            code="landform_near_out_of_bounds",
        )
    graded = NearLand(near.x0, near.y0, near.nx, near.ny, tuple(work.h))
    return GradedLand(
        near=graded,
        pads=tuple((pad.id, levels[pad.id]) for pad in plan.pads),
        water=tuple(ponds),
        walls=tuple(walls),
        report={
            "max_cut_mm": cut,
            "max_fill_mm": fill,
            "max_corridor_grade_permille": steepest,
            "walls": len(walls),
        },
        retaining=retaining,
    )
