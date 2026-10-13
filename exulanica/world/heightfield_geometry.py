"""Bounded immutable integer terrain, with exact upward planes and point contact.

A realization owns one semantic component. Its grid topology is implicit and its retained
integer coordinates, rather than a generator or renderer, determine contact. This module
establishes geometry identity only; source authorization belongs to the calling authority.
"""

from __future__ import annotations

import hashlib
import math
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import canonical_json

PROFILE: Final = "exulanica.heightfield-geometry/v1"
FRAME: Final = "region-local-east-up-south-mm"
DIAGONAL: Final = "a-c-b,b-c-d"
MAX_BYTES: Final = 1_048_576
MAX_AXIS: Final = 257
_ID = re.compile(r"[a-z][a-z0-9_.:-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{64}")
Point = tuple[int | Fraction, int | Fraction]


class HeightfieldInvalid(ValueError):
    """A realization or query does not satisfy its closed bounded contract."""


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise HeightfieldInvalid(detail)


def keys(raw: Any, fields: str) -> dict:
    require(type(raw) is dict and set(raw) == set(fields.split()), f"expected fields: {fields}")
    return raw


def integer(raw: Any, low: int, high: int) -> int:
    require(type(raw) is int and low <= raw <= high, f"expected integer in [{low},{high}]")
    return raw


def identity(raw: Any) -> str:
    require(type(raw) is str and len(raw) <= 128 and _ID.fullmatch(raw) is not None, "invalid id")
    return raw


def digest(raw: Any) -> str:
    require(
        type(raw) is str and len(raw) == 64 and _SHA.fullmatch(raw) is not None, "invalid digest"
    )
    return raw


def position(raw: Any) -> tuple[int, int]:
    require(type(raw) in (list, tuple) and len(raw) == 2, "position states east and south")
    return integer(raw[0], -512_000, 512_000), integer(raw[1], -512_000, 512_000)


def ratio(value: int | Fraction) -> dict[str, str]:
    value = Fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def cross(a: Point, b: Point, p: Point) -> int | Fraction:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def cell_range(axis: tuple[int, ...], low: int, high: int) -> range:
    """Every closed cell touching the interval, including both sides of an interior axis."""
    return range(
        max(0, bisect_left(axis, low) - 1), min(len(axis) - 2, bisect_right(axis, high) - 1) + 1
    )


@dataclass(frozen=True)
class Triangle:
    selector: tuple[int, int, int]
    vertices: tuple[tuple[int, int, int], ...]
    normal: tuple[int, int, int]

    @property
    def polygon(self) -> tuple[Point, ...]:
        # Upward 3D winding is clockwise in east/south. Clipping uses counterclockwise edges.
        return tuple((p[0], p[2]) for p in reversed(self.vertices))

    def height(self, point: Point) -> Fraction:
        x, y, z = self.vertices[0]
        east, up, south = self.normal
        return Fraction(y) - (east * (point[0] - x) + south * (point[1] - z)) / Fraction(up)


@dataclass(frozen=True)
class HeightfieldGeometry:
    component_id: str
    east_mm: tuple[int, ...]
    south_mm: tuple[int, ...]
    height_mm: tuple[int, ...]
    # kind, source digest, generator id, generator version, input digest
    provenance: tuple[str, str, str, int, str]
    canonical_bytes: bytes
    sha256: str

    def document(self) -> dict:
        kind, source, generator, version, inputs = self.provenance
        return {
            "profile": PROFILE,
            "component_id": self.component_id,
            "frame": FRAME,
            "east_mm": list(self.east_mm),
            "south_mm": list(self.south_mm),
            "height_mm": list(self.height_mm),
            "diagonal": DIAGONAL,
            "provenance": {
                "kind": kind,
                "source_sha256": source,
                "generator_id": generator,
                "generator_version": version,
                "input_sha256": inputs,
            },
        }

    def triangle(self, row: int, column: int, half: int) -> Triangle:
        integer(row, 0, len(self.south_mm) - 2)
        integer(column, 0, len(self.east_mm) - 2)
        integer(half, 0, 1)
        width = len(self.east_mm)

        def vertex(j: int, i: int) -> tuple[int, int, int]:
            return self.east_mm[i], self.height_mm[j * width + i], self.south_mm[j]

        a, b, c, d = (
            vertex(row, column),
            vertex(row, column + 1),
            vertex(row + 1, column),
            vertex(row + 1, column + 1),
        )
        vertices = (a, c, b) if half == 0 else (b, c, d)
        p, q, r = vertices
        u, v = tuple(q[i] - p[i] for i in range(3)), tuple(r[i] - p[i] for i in range(3))
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        common = math.gcd(*n)
        return Triangle((row, column, half), vertices, tuple(value // common for value in n))


def read_heightfield_geometry(
    document: Any, expected_sha256: str | None = None
) -> HeightfieldGeometry:
    raw = keys(
        document, "profile component_id frame east_mm south_mm height_mm diagonal provenance"
    )
    require(
        raw["profile"] == PROFILE and raw["frame"] == FRAME and raw["diagonal"] == DIAGONAL,
        "unknown geometry profile, frame or topology",
    )
    component = identity(raw["component_id"])
    axes = []
    for name in ("east_mm", "south_mm"):
        axis = raw[name]
        require(type(axis) is list and 2 <= len(axis) <= MAX_AXIS, "invalid axis length")
        values = tuple(integer(v, -256_000, 256_000) for v in axis)
        require(all(250 <= b - a <= 2000 for a, b in pairwise(values)), "invalid axis spacing")
        axes.append(values)
    heights = raw["height_mm"]
    require(
        type(heights) is list and len(heights) == len(axes[0]) * len(axes[1]),
        "height array must cover the row-major grid",
    )
    heights = tuple(integer(v, -64_000, 64_000) for v in heights)
    p = keys(raw["provenance"], "kind source_sha256 generator_id generator_version input_sha256")
    require(p["kind"] in ("authored", "generated"), "unknown provenance kind")
    provenance = (
        p["kind"],
        digest(p["source_sha256"]),
        identity(p["generator_id"]),
        integer(p["generator_version"], 1, 2_147_483_647),
        digest(p["input_sha256"]),
    )
    encoded = canonical_json(raw)
    require(len(encoded) <= MAX_BYTES, "geometry byte limit")
    sha256 = hashlib.sha256(encoded).hexdigest()
    if expected_sha256 is not None:
        require(digest(expected_sha256) == sha256, "geometry digest mismatch")
    return HeightfieldGeometry(component, *axes, heights, provenance, encoded, sha256)


def point_contact(geometry: HeightfieldGeometry, at: Any) -> dict | None:
    x, z = position(at)
    if not (
        geometry.east_mm[0] <= x <= geometry.east_mm[-1]
        and geometry.south_mm[0] <= z <= geometry.south_mm[-1]
    ):
        return None
    for row in cell_range(geometry.south_mm, z, z):
        for column in cell_range(geometry.east_mm, x, x):
            for half in (0, 1):
                triangle = geometry.triangle(row, column, half)
                polygon = triangle.polygon
                if all(
                    cross(a, b, (x, z)) >= 0
                    for a, b in zip(polygon, (*polygon[1:], polygon[0]), strict=True)
                ):
                    return {
                        "geometry_sha256": geometry.sha256,
                        "component_id": geometry.component_id,
                        "triangle": list(triangle.selector),
                        "height_mm": ratio(triangle.height((x, z))),
                        "normal": [str(n) for n in triangle.normal],
                    }
    raise AssertionError("admitted closed grid did not cover an interior point")
