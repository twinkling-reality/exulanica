"""Conservative 2D geometry for declared district simulation envelopes (millimetres)."""

from __future__ import annotations

import itertools
from math import isqrt

Point = tuple[int, int]
Ring = list[Point]
Polygon = list[Ring]


def squared_distance(a: Point, b: Point) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def length_mm(a: Point, b: Point) -> int:
    squared = squared_distance(a, b)
    root = isqrt(squared)
    return root if root * root == squared else root + 1


def point_in_ring(p: Point, ring: Ring) -> bool:
    inside = False
    for a, b in itertools.pairwise(ring):
        if (a[1] > p[1]) != (b[1] > p[1]):
            # Compare the ray intersection without floating-point division.
            lhs = (p[0] - a[0]) * (b[1] - a[1])
            rhs = (b[0] - a[0]) * (p[1] - a[1])
            if (lhs < rhs) if b[1] > a[1] else (lhs > rhs):
                inside = not inside
    return inside


def point_near_segment(p: Point, a: Point, b: Point, radius: int) -> bool:
    dx, dz = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dz * dz
    dot = (p[0] - a[0]) * dx + (p[1] - a[1]) * dz
    if dot <= 0:
        return squared_distance(p, a) <= radius * radius
    if dot >= den:
        return squared_distance(p, b) <= radius * radius
    cross = (p[0] - a[0]) * dz - (p[1] - a[1]) * dx
    return cross * cross <= radius * radius * den


def _cross(a: Point, b: Point, c: Point) -> int:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_near(a: Point, b: Point, c: Point, d: Point, radius: int) -> bool:
    if max(a[0], b[0]) + radius < min(c[0], d[0]) or max(c[0], d[0]) + radius < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) + radius < min(c[1], d[1]) or max(c[1], d[1]) + radius < min(a[1], b[1]):
        return False
    if _cross(a, b, c) * _cross(a, b, d) <= 0 and _cross(c, d, a) * _cross(c, d, b) <= 0:
        return True
    return (
        point_near_segment(a, c, d, radius)
        or point_near_segment(b, c, d, radius)
        or point_near_segment(c, a, b, radius)
        or point_near_segment(d, a, b, radius)
    )


def inside_polygon(p: Point, polygon: Polygon) -> bool:
    return point_in_ring(p, polygon[0]) and not any(point_in_ring(p, r) for r in polygon[1:])


def segment_inside(a: Point, b: Point, polygon: Polygon, radius: int) -> bool:
    return (
        inside_polygon(a, polygon)
        and inside_polygon(b, polygon)
        and not any(
            segments_near(a, b, c, d, radius)
            for ring in polygon
            for c, d in itertools.pairwise(ring)
        )
    )


def segment_blocked(a: Point, b: Point, exterior: Ring, radius: int) -> bool:
    # Match existing navigation: building courtyard holes are conservatively blocked.
    return (
        point_in_ring(a, exterior)
        or point_in_ring(b, exterior)
        or any(segments_near(a, b, c, d, radius) for c, d in itertools.pairwise(exterior))
    )


class DistrictGeometry:
    def __init__(self, base: dict) -> None:
        self.bounds = [v * 10 for v in base["bounds_cm"]]
        self.buildings = [
            (
                b["id"],
                [v * 10 for v in b["bbox_cm"]],
                [[(x * 10, z * 10) for x, z in p[0]] for p in b["polygons"]],
            )
            for b in base["buildings"]
        ]
        self.sidewalks = [
            (
                s["id"],
                [v * 10 for v in s["bbox_cm"]],
                [[[(x * 10, z * 10) for x, z in r] for r in p] for p in s["polygons"]],
            )
            for s in base["sidewalks"]
        ]

    def supports(self, a: Point, b: Point, radius: int = 450) -> list[str]:
        w, n, e, s = self.bounds
        if any(
            not (w + radius < p[0] < e - radius and n + radius < p[1] < s - radius) for p in (a, b)
        ):
            return []
        lo_x, lo_z = min(a[0], b[0]) - radius, min(a[1], b[1]) - radius
        hi_x, hi_z = max(a[0], b[0]) + radius, max(a[1], b[1]) + radius
        for _, box, exteriors in self.buildings:
            if box[2] < lo_x or box[0] > hi_x or box[3] < lo_z or box[1] > hi_z:
                continue
            if any(segment_blocked(a, b, ring, radius) for ring in exteriors):
                return []
        return [
            identity
            for identity, box, polygons in self.sidewalks
            if box[0] <= lo_x
            and box[1] <= lo_z
            and box[2] >= hi_x
            and box[3] >= hi_z
            and any(segment_inside(a, b, polygon, radius) for polygon in polygons)
        ]
