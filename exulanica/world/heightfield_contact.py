"""Exact conservative square contact over one immutable heightfield.

The swept convex hull covers every point occupied along a straight movement segment. Closed
triangle clipping, rational height extrema and closed obstruction boxes intentionally refuse
some safe paths rather than accepting an unproved one. Callers must supply complete current
obstructions and source authority; this pure module cannot establish either from a digest.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.world.heightfield_geometry import (
    HeightfieldGeometry,
    Point,
    cell_range,
    cross,
    digest,
    identity,
    integer,
    keys,
    point_contact,
    position,
    ratio,
    require,
)

PROFILE: Final = "exulanica.heightfield-contact/v1"
POLICY: Final = "person-square-680x1800-dry350-slope6248-v1"
MAX_TRIANGLES: Final = 4096
MAX_WORK: Final = 262_144
MAX_OBSTRUCTIONS: Final = 512
MAX_BYTES: Final = 131_072


@dataclass(frozen=True)
class Obstruction:
    obstruction_id: str
    bounds_mm: tuple[int, ...] | None

    def document(self) -> dict:
        if self.bounds_mm is None:
            return {"kind": "unknown", "obstruction_id": self.obstruction_id}
        return {
            "kind": "aabb",
            "obstruction_id": self.obstruction_id,
            "bounds_mm": list(self.bounds_mm),
        }


@dataclass(frozen=True)
class HeightfieldContact:
    geometry: HeightfieldGeometry
    obstructions: tuple[Obstruction, ...]
    canonical_bytes: bytes
    sha256: str

    def document(self) -> dict:
        return {
            "profile": PROFILE,
            "geometry_sha256": self.geometry.sha256,
            "component_id": self.geometry.component_id,
            "policy": POLICY,
            "obstructions": [one.document() for one in self.obstructions],
        }


def read_heightfield_contact(
    document: Any,
    geometry: HeightfieldGeometry,
    expected_sha256: str | None = None,
) -> HeightfieldContact:
    raw = keys(document, "profile geometry_sha256 component_id policy obstructions")
    require(raw["profile"] == PROFILE and raw["policy"] == POLICY, "unknown contact policy")
    require(
        digest(raw["geometry_sha256"]) == geometry.sha256
        and identity(raw["component_id"]) == geometry.component_id,
        "contact source mismatch",
    )
    rows = raw["obstructions"]
    require(type(rows) is list and len(rows) <= MAX_OBSTRUCTIONS, "obstruction count limit")
    obstructions = []
    for row in rows:
        require(type(row) is dict, "obstruction is an object")
        if row.get("kind") == "unknown":
            keys(row, "kind obstruction_id")
            bounds = None
        else:
            keys(row, "kind obstruction_id bounds_mm")
            require(row["kind"] == "aabb", "unknown obstruction shape")
            values = row["bounds_mm"]
            require(type(values) is list and len(values) == 6, "box states six bounds")
            bounds = tuple(integer(v, -512_000, 512_000) for v in values)
            require(all(bounds[i] <= bounds[i + 3] for i in range(3)), "reversed box")
        obstructions.append(Obstruction(identity(row["obstruction_id"]), bounds))
    ids = [row.obstruction_id for row in obstructions]
    require(ids == sorted(set(ids)), "obstructions have unique sorted identities")
    encoded = canonical_json(raw)
    require(len(encoded) <= MAX_BYTES, "contact byte limit")
    sha256 = hashlib.sha256(encoded).hexdigest()
    if expected_sha256 is not None:
        require(digest(expected_sha256) == sha256, "contact digest mismatch")
    return HeightfieldContact(geometry, tuple(obstructions), encoded, sha256)


def _hull(points: list[Point]) -> tuple[Point, ...]:
    points = sorted(set(points))
    halves = []
    for sequence in (points, reversed(points)):
        half = []
        for p in sequence:
            while len(half) >= 2 and cross(half[-2], half[-1], p) <= 0:
                half.pop()
            half.append(p)
        halves.append(half[:-1])
    return tuple(halves[0] + halves[1])


def _clip_edge(polygon: tuple[Point, ...], a: Point, b: Point) -> tuple[Point, ...]:
    """Clip against one closed left half-plane, retaining point and line intersections."""
    if not polygon:
        return ()
    output = []
    previous = polygon[-1]
    previous_side = cross(a, b, previous)
    for current in polygon:
        side = cross(a, b, current)
        if (previous_side >= 0) != (side >= 0):
            t = Fraction(previous_side, previous_side - side)
            output.append(
                (
                    previous[0] + t * (current[0] - previous[0]),
                    previous[1] + t * (current[1] - previous[1]),
                )
            )
        if side >= 0:
            output.append(current)
        previous, previous_side = current, side
    # Clipping can repeat a corner at a boundary. Preserve a degenerate point or segment once.
    distinct = []
    for p in output:
        if not distinct or p != distinct[-1]:
            distinct.append(p)
    if len(distinct) > 1 and distinct[0] == distinct[-1]:
        distinct.pop()
    return tuple(distinct)


def _clip(polygon: tuple[Point, ...], boundary: tuple[Point, ...]) -> tuple[Point, ...]:
    for a, b in zip(boundary, (*boundary[1:], boundary[0]), strict=True):
        polygon = _clip_edge(polygon, a, b)
        if not polygon:
            break
    return polygon


def _box_overlap(polygon: tuple[Point, ...], bounds: tuple[int, ...]) -> bool:
    x0, _, z0, x1, _, z1 = bounds
    if (
        max(p[0] for p in polygon) < x0
        or min(p[0] for p in polygon) > x1
        or max(p[1] for p in polygon) < z0
        or min(p[1] for p in polygon) > z1
    ):
        return False
    # Separate half-planes preserve finite extents even for a zero-width box or point.
    for a, b in (((x0, 1), (x0, 0)), ((x1, 0), (x1, 1)), ((0, z0), (1, z0)), ((1, z1), (0, z1))):
        polygon = _clip_edge(polygon, a, b)
        if not polygon:
            return False
    return True


def _result(
    reason: str | None = None,
    *,
    contact: dict | None = None,
    height_range: tuple[Fraction, Fraction] | None = None,
    triangles: int = 0,
) -> dict:
    return {
        "status": (
            "clear"
            if reason is None
            else "unavailable"
            if reason in ("work_limit", "unknown_obstruction")
            else "blocked"
        ),
        "reason": reason,
        "contact": contact,
        "height_range_mm": None if height_range is None else [ratio(v) for v in height_range],
        "triangles": triangles,
    }


def _query(
    contact: HeightfieldContact,
    start: Any,
    end: Any,
    half_width: int,
    height: int,
    *,
    passive: bool = False,
) -> dict:
    start, end = position(start), position(end)
    if (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2 > 2000**2:
        return _result("segment_limit")
    polygon = _hull(
        [
            (x + dx, z + dz)
            for x, z in (start, end)
            for dx in (-half_width, half_width)
            for dz in (-half_width, half_width)
        ]
    )
    x0, x1 = min(p[0] for p in polygon), max(p[0] for p in polygon)
    z0, z1 = min(p[1] for p in polygon), max(p[1] for p in polygon)
    geometry = contact.geometry
    if (
        x0 < geometry.east_mm[0]
        or x1 > geometry.east_mm[-1]
        or z0 < geometry.south_mm[0]
        or z1 > geometry.south_mm[-1]
    ):
        return _result("outside_domain")
    rows, columns = cell_range(geometry.south_mm, z0, z1), cell_range(geometry.east_mm, x0, x1)
    candidates = len(rows) * len(columns) * 2
    if candidates > MAX_TRIANGLES or candidates * (1 + len(contact.obstructions)) > MAX_WORK:
        return _result("work_limit")
    if any(obstruction.bounds_mm is None for obstruction in contact.obstructions):
        return _result("unknown_obstruction")
    pieces = []
    for row in rows:
        for column in columns:
            for half in (0, 1):
                triangle = geometry.triangle(row, column, half)
                clipped = _clip(polygon, triangle.polygon)
                if clipped:
                    heights = [triangle.height(p) for p in clipped]
                    pieces.append((clipped, min(heights), max(heights), triangle.normal))
    assert pieces, "admitted closed grid did not cover a contained footprint"
    low, high = min(p[1] for p in pieces), max(p[2] for p in pieces)
    common = {
        "contact": point_contact(geometry, end),
        "height_range": (low, high),
        "triangles": len(pieces),
    }
    if low < 350:
        return _result("wet", **common)
    if passive:
        if low != high or low.denominator != 1:
            return _result("not_flat", **common)
    elif any((n[0] ** 2 + n[2] ** 2) * 10000**2 > n[1] ** 2 * 6248**2 for _, _, _, n in pieces):
        return _result("steep", **common)
    # A center-grounded upright body can reach above a lower adjacent terrain piece.
    # Use the whole swept height envelope at every horizontal overlap, never local columns.
    for polygon, _, _, _ in pieces:
        for obstruction in contact.obstructions:
            bounds = obstruction.bounds_mm
            assert bounds is not None
            if low <= bounds[4] and bounds[1] <= high + height and _box_overlap(polygon, bounds):
                return _result("obstructed", **common)
    return _result(**common)


def at(contact: HeightfieldContact, position_mm: Any) -> dict:
    """A stationary person's complete conservative square and vertical envelope."""
    return sweep(contact, position_mm, position_mm)


def sweep(contact: HeightfieldContact, start: Any, end: Any) -> dict:
    """Ground-following navigation only; the caller keeps its accepted pose on refusal."""
    return _query(contact, start, end, 340, 1800)


def passive_patch(
    contact: HeightfieldContact, position_mm: Any, half_width_mm: int, height_mm: int
) -> dict:
    """Prove a complete conservative all-yaw square at one exact integer elevation."""
    half_width = integer(half_width_mm, 1, 256_000)
    height = integer(height_mm, 1, 128_000)
    return _query(contact, position_mm, position_mm, half_width, height, passive=True)
