"""A landscape's walkable surfaces, named, joined and reached: ``exulanica.landscape-surfaces/v1``.

What the walking layer stands people on, from a landscape, its placed volumes as
:func:`~exulanica.grammar.landscape.compose_volumes` realized them under the landscape's seed, and
its land under the land's own seed. In whole numbers:

* **Surfaces.** ``ground`` is the land's walkable dry surface; ``volume:<placement id>/top:<n>`` is
  each placed volume's walkable top (:func:`~exulanica.grammar.volumes.volume_tops`), placements in
  the document's order and each volume's tops in their own. Each states its frame (the world's for
  the ground; the placement's origin and turn for a top), its walkable cells and the range of the
  heights of their corners in the world.
* **Walkable points.** A walkable point of a surface is a corner of one of its walkable cells, at
  that corner's height. A top's points are taken from its sheet into the world as
  :mod:`~exulanica.grammar.landscape.spacing` turns a volume's extent: ``(x, y)`` of the volume's
  frame lies ``(c x - s y) // 2^30`` east and ``(s x + c y) // 2^30`` north of the placement's
  origin (``s`` and ``c`` its yaw by :func:`~exulanica.grammar.volumes.sin_cos` at
  :data:`~exulanica.grammar.volumes.TURN_ONE`, floored once), and its height is raised by the
  origin's. A turned sheet's lattice is not the world's, so its points are compared where they fall
  on the world plan, never by their lattice indices.
* **The ground's cells** are the land's 1 m lattice cells within the land near the world
  (:func:`~exulanica.grammar.landform.near_domain`; beyond it the land is backdrop, never walked)
  whose four corners are dry and whose edges climb at most 1 in 4: the land's own walking rule
  (:mod:`~exulanica.grammar.landform.grading`). A point is dry unless it lies within a water body
  (:func:`~exulanica.grammar.landform.water_bodies`) less than
  :data:`~exulanica.grammar.landform.DRY_ABOVE_WATER_MM` above its level; a shore's sea lies
  everywhere at level 0. Only the ground near a top is realized: over the box on the world lattice
  holding every point within one cell of the top's walkable points, grown by one cell for the cells
  round them. The ground states the walkable cells it realized, not the whole land's.
* **Joins.** Two surfaces join where a walkable point of one and a walkable point of the other lie
  within one lattice cell of each other on the world plan (east and north each at most
  :data:`CELL_MM` apart) and within :data:`STEP_MM` in height, the place contract's step. A top
  joins the ground the same way, the ground's points being those of its walkable cells. A join
  states its two surfaces in their order, the pair of points with the least climb (then the lowest
  points), the climb from the first to the second, and how many pairs of points meet the rule.
* **Reach.** From the arrival (a stated point in a walkable ground cell, or the ground as a whole
  when none is stated) every surface reached through joins is listed, in the surfaces' order, and
  every walkable surface nothing reaches is listed as reached only by flight. The ground is one
  surface: whether two stretches of it are joined across the land is the land's own reach.

Nothing :func:`~exulanica.grammar.landscape.compose_volumes` realized is realized again: tops are
read from their sheets. Points are kept in buckets of a cell on the world plan, so each is compared
only with the points of the nine buckets round it. The document's identity is the SHA-256 of its
canonical JSON.
"""

from __future__ import annotations

import functools
import hashlib
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, TypeAlias

from exulanica.canonical import canonical_json
from exulanica.grammar.landform import (
    DRY_ABOVE_WATER_MM,
    WALK_GRADE_PERMILLE,
    WorldFrame,
    land_heights,
    near_domain,
    water_bodies,
)
from exulanica.grammar.landform.grading import _within as _in_water
from exulanica.grammar.landscape.compose import PlacedVolume
from exulanica.grammar.landscape.document import LandscapeDocument, LandscapeRefused
from exulanica.grammar.volumes import TURN_ONE, VolumeSheet, sin_cos
from exulanica.grammar.volumes.sheets import SHEET_CELL_MM

__all__ = [
    "CELL_MM",
    "GROUND",
    "STEP_MM",
    "SURFACES_PROFILE",
    "LandscapeSurfaces",
    "SurfaceJoin",
    "WalkableSurface",
    "landscape_surfaces",
]

SURFACES_PROFILE: Final = "exulanica.landscape-surfaces/v1"
GROUND: Final = "ground"
#: The lattice every surface's walkable points lie on in its own frame: a sheet's, and the land's.
CELL_MM: Final = SHEET_CELL_MM
#: The most a join climbs: the place contract's kerb step (``society_place.STEP_LIMIT_MM``).
STEP_MM: Final = 180
#: The most an edge of a walkable ground cell climbs: the land's walking grade.
_RISE_MM: Final = CELL_MM * WALK_GRADE_PERMILLE // 1000

Point: TypeAlias = tuple[int, int, int]


@dataclass(frozen=True)
class WalkableSurface:
    """One walkable surface: its name, frame and walkable cells, and its walkable points in the
    world (east, north and up), sorted."""

    surface: str
    at_mm: tuple[int, int, int]
    yaw_mdeg: int
    sheet_sha256: str | None
    cells: int
    points: tuple[Point, ...]

    @property
    def height_mm(self) -> tuple[int, int] | None:
        if not self.points:
            return None
        heights = [up for _, _, up in self.points]
        return min(heights), max(heights)

    def document(self) -> dict[str, Any]:
        heights = self.height_mm
        return {
            "surface": self.surface,
            "sheet_sha256": self.sheet_sha256,
            "at_mm": list(self.at_mm),
            "yaw_mdeg": self.yaw_mdeg,
            "cells": self.cells,
            "height_mm": None if heights is None else list(heights),
        }


@dataclass(frozen=True)
class SurfaceJoin:
    """Two surfaces a person steps between: the pair of points with the least climb, the first on
    the surface listed first, and how many pairs of points meet the rule."""

    surfaces: tuple[str, str]
    from_mm: Point
    to_mm: Point
    pairs: int

    def document(self) -> dict[str, Any]:
        return {
            "surfaces": list(self.surfaces),
            "from_mm": list(self.from_mm),
            "to_mm": list(self.to_mm),
            "climb_mm": self.to_mm[2] - self.from_mm[2],
            "pairs": self.pairs,
        }


@dataclass(frozen=True)
class LandscapeSurfaces:
    landscape_sha256: str
    arrival_mm: tuple[int, int] | None
    surfaces: tuple[WalkableSurface, ...]
    joins: tuple[SurfaceJoin, ...]
    reached: tuple[str, ...]
    flight_only: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "profile": SURFACES_PROFILE,
            "landscape_sha256": self.landscape_sha256,
            "cell_mm": CELL_MM,
            "step_mm": STEP_MM,
            "arrival_mm": None if self.arrival_mm is None else list(self.arrival_mm),
            "surfaces": [surface.document() for surface in self.surfaces],
            "joins": [join.document() for join in self.joins],
            "reached": list(self.reached),
            "flight_only": list(self.flight_only),
        }

    @functools.cached_property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document())).hexdigest()


def _top(volume: PlacedVolume, sheet: VolumeSheet) -> WalkableSurface:
    """A placed volume's top with its walkable points taken into the world."""
    sine, cosine = sin_cos(volume.yaw_mdeg)
    east, north, up = volume.at_mm
    x0, y0 = sheet.origin_mm
    corners: dict[tuple[int, int], int] = {}
    for row, first, last in sheet.walkable:
        for j in (row, row + 1):
            for i in range(first, last + 2):
                corners[(i, j)] = sheet.height_mm[j * sheet.columns + i]
    points = []
    for (i, j), height in corners.items():
        x, y = x0 + i * CELL_MM, y0 + j * CELL_MM
        points.append(
            (
                east + (cosine * x - sine * y) // TURN_ONE,
                north + (sine * x + cosine * y) // TURN_ONE,
                up + height,
            )
        )
    return WalkableSurface(
        surface=f"volume:{volume.id}/{sheet.surface}",
        at_mm=volume.at_mm,
        yaw_mdeg=volume.yaw_mdeg,
        sheet_sha256=sheet.sha256,
        cells=sheet.cells,
        points=tuple(sorted(points)),
    )


class _Ground:
    """The land near the world, realized only where it is asked for."""

    def __init__(self, landscape: LandscapeDocument, land_seed: str) -> None:
        width, depth = landscape.extent_mm
        self.land = landscape.land
        self.frame = WorldFrame(width_mm=width, depth_mm=depth, seed=land_seed)
        self.water = water_bodies(self.land, self.frame)
        self.near = near_domain(self.frame)
        self.cells: set[tuple[int, int]] = set()
        self.points: dict[tuple[int, int], int] = {}

    def _dry(self, x: int, y: int, height: int) -> bool:
        return not any(
            height < body.level_mm + DRY_ABOVE_WATER_MM and _in_water(body, x, y)
            for body in self.water
        )

    def walkable(
        self, low: tuple[int, int], high: tuple[int, int]
    ) -> dict[tuple[int, int], tuple[int, int, int, int]]:
        """The walkable cells between two lattice points, inclusive, within the near land: each by
        its south-west corner, with its corners' heights south-west, south-east, north-west and
        north-east."""
        x0, y0 = max(low[0], self.near[0]), max(low[1], self.near[1])
        x1, y1 = min(high[0], self.near[2]), min(high[1], self.near[3])
        if x1 <= x0 or y1 <= y0:
            return {}
        xs, ys = list(range(x0, x1 + 1, CELL_MM)), list(range(y0, y1 + 1, CELL_MM))
        nx = len(xs)
        heights = land_heights(self.land, self.frame, xs, ys)
        dry = [self._dry(xs[k % nx], ys[k // nx], h) for k, h in enumerate(heights)]
        cells = {}
        for j in range(len(ys) - 1):
            for i in range(nx - 1):
                corners = (j * nx + i, j * nx + i + 1, (j + 1) * nx + i, (j + 1) * nx + i + 1)
                if not all(dry[corner] for corner in corners):
                    continue
                a, b, c, d = (heights[corner] for corner in corners)
                if max(abs(a - b), abs(c - d), abs(a - c), abs(b - d)) <= _RISE_MM:
                    cells[(xs[i], ys[j])] = (a, b, c, d)
        return cells

    def examine(self, points: Sequence[Point]) -> None:
        """Realize the ground near ``points``: every lattice point within a cell of one of them,
        and the cells round those."""
        if not points:
            return
        east = [x for x, _, _ in points]
        north = [y for _, y, _ in points]
        low = (-(-(min(east) - CELL_MM) // CELL_MM) - 1, -(-(min(north) - CELL_MM) // CELL_MM) - 1)
        high = ((max(east) + CELL_MM) // CELL_MM + 1, (max(north) + CELL_MM) // CELL_MM + 1)
        cells = self.walkable(
            (low[0] * CELL_MM, low[1] * CELL_MM), (high[0] * CELL_MM, high[1] * CELL_MM)
        )
        for (x, y), corners in cells.items():
            self.cells.add((x, y))
            for (dx, dy), height in zip(
                ((0, 0), (CELL_MM, 0), (0, CELL_MM), (CELL_MM, CELL_MM)), corners, strict=True
            ):
                self.points[(x + dx, y + dy)] = height

    def surface(self) -> WalkableSurface:
        return WalkableSurface(
            surface=GROUND,
            at_mm=(0, 0, 0),
            yaw_mdeg=0,
            sheet_sha256=None,
            cells=len(self.cells),
            points=tuple(sorted((x, y, height) for (x, y), height in self.points.items())),
        )


def _joins(surfaces: Sequence[WalkableSurface]) -> tuple[SurfaceJoin, ...]:
    buckets: dict[tuple[int, int], list[tuple[int, Point]]] = {}
    for index, surface in enumerate(surfaces):
        for point in surface.points:
            buckets.setdefault((point[0] // CELL_MM, point[1] // CELL_MM), []).append(
                (index, point)
            )
    found: dict[tuple[int, int], tuple[tuple[int, Point, Point], int]] = {}
    for index, surface in enumerate(surfaces):
        for point in surface.points:
            east, north = point[0] // CELL_MM, point[1] // CELL_MM
            for bucket in ((east + de, north + dn) for de in (-1, 0, 1) for dn in (-1, 0, 1)):
                for other, near in buckets.get(bucket, ()):
                    if (
                        other <= index
                        or abs(near[0] - point[0]) > CELL_MM
                        or abs(near[1] - point[1]) > CELL_MM
                        or abs(near[2] - point[2]) > STEP_MM
                    ):
                        continue
                    witness = (abs(near[2] - point[2]), point, near)
                    best, pairs = found.get((index, other), (witness, 0))
                    found[(index, other)] = (min(best, witness), pairs + 1)
    return tuple(
        SurfaceJoin(
            surfaces=(surfaces[first].surface, surfaces[second].surface),
            from_mm=start,
            to_mm=end,
            pairs=pairs,
        )
        for (first, second), ((_, start, end), pairs) in sorted(found.items())
    )


def _reached(names: Sequence[str], joins: Sequence[SurfaceJoin]) -> set[str]:
    neighbours: dict[str, list[str]] = {name: [] for name in names}
    for join in joins:
        one, other = join.surfaces
        neighbours[one].append(other)
        neighbours[other].append(one)
    reached, queue = {GROUND}, deque([GROUND])
    while queue:
        for name in neighbours[queue.popleft()]:
            if name not in reached:
                reached.add(name)
                queue.append(name)
    return reached


def landscape_surfaces(
    landscape: LandscapeDocument,
    placed: Sequence[PlacedVolume],
    land_seed: str,
    arrival_mm: tuple[int, int] | None = None,
) -> LandscapeSurfaces:
    """The landscape's walkable surfaces, their joins and what reaches them from ``arrival_mm``
    (or the ground as a whole), its volumes as ``compose_volumes`` realized them and its land under
    ``land_seed``. An arrival outside a walkable ground cell is refused by name
    (``landscape_arrival_not_ground``)."""
    composed = [(v.id, v.volume_sha256, v.at_mm, v.yaw_mdeg) for v in placed]
    stated = [(p.id, p.volume.sha256, p.at_mm, p.yaw_mdeg) for p in landscape.placements]
    if composed != stated:
        raise ValueError("the placed volumes are not the landscape's, composed in its order")
    ground = _Ground(landscape, land_seed)
    if arrival_mm is not None:
        x, y = arrival_mm[0] // CELL_MM * CELL_MM, arrival_mm[1] // CELL_MM * CELL_MM
        if (x, y) not in ground.walkable((x, y), (x + CELL_MM, y + CELL_MM)):
            raise LandscapeRefused(
                f"the arrival ({arrival_mm[0]}, {arrival_mm[1]}) is not in a walkable ground cell "
                "of the land near the world",
                path="arrival_mm",
                code="landscape_arrival_not_ground",
            )
    tops = [_top(volume, sheet) for volume in placed for sheet in volume.tops]
    for top in tops:
        ground.examine(top.points)
    surfaces = (ground.surface(), *tops)
    joins = _joins(surfaces)
    reached = _reached([surface.surface for surface in surfaces], joins)
    return LandscapeSurfaces(
        landscape_sha256=landscape.sha256,
        arrival_mm=None if arrival_mm is None else (arrival_mm[0], arrival_mm[1]),
        surfaces=surfaces,
        joins=joins,
        reached=tuple(surface.surface for surface in surfaces if surface.surface in reached),
        flight_only=tuple(
            surface.surface for surface in surfaces if surface.surface not in reached
        ),
    )
