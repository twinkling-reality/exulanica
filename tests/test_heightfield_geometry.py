"""Exact geometry admission and a barycentric oracle independent of the plane reader."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from fractions import Fraction
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.heightfield_geometry import (
    DIAGONAL,
    FRAME,
    PROFILE,
    HeightfieldInvalid,
    point_contact,
    read_heightfield_geometry,
)

FIXTURES = Path(__file__).parent / "fixtures" / "heightfield" / "conformance.json"


def terrain(east=(-2000, -1000, 0, 1000, 2000), south=None, heights=None):
    south = east if south is None else south
    return {
        "profile": PROFILE,
        "component_id": "terrain:test",
        "frame": FRAME,
        "east_mm": list(east),
        "south_mm": list(south),
        "height_mm": [500] * (len(east) * len(south)) if heights is None else list(heights),
        "diagonal": DIAGONAL,
        "provenance": {
            "kind": "authored",
            "source_sha256": "1" * 64,
            "generator_id": "fixture:terrace",
            "generator_version": 1,
            "input_sha256": "2" * 64,
        },
    }


def triangles(document):
    east, south, heights = (document[k] for k in ("east_mm", "south_mm", "height_mm"))
    for row in range(len(south) - 1):
        for col in range(len(east) - 1):
            a, b, c, d = [
                (east[i], heights[j * len(east) + i], south[j])
                for j, i in ((row, col), (row, col + 1), (row + 1, col), (row + 1, col + 1))
            ]
            yield (row, col, 0), (a, c, b)
            yield (row, col, 1), (b, c, d)


def barycentric(vertices, point):
    """Solve the projected triangle's independent two-by-two linear system."""
    a, b, c = vertices
    ux, uz = b[0] - a[0], b[2] - a[2]
    vx, vz = c[0] - a[0], c[2] - a[2]
    px, pz = point[0] - a[0], point[1] - a[2]
    determinant = ux * vz - uz * vx
    u = Fraction(px * vz - pz * vx, determinant)
    v = Fraction(ux * pz - uz * px, determinant)
    return (1 - u - v, u, v)


def oracle_height(vertices, point):
    return sum(w * v[1] for w, v in zip(barycentric(vertices, point), vertices, strict=True))


def oracle_point(document, point):
    for selector, vertices in triangles(document):
        weights = barycentric(vertices, point)
        if min(weights) < 0:
            continue
        height = oracle_height(vertices, point)
        # Independent gradient from evaluations at unit-axis displacements, then common scaling.
        origin = oracle_height(vertices, (0, 0))
        gx = oracle_height(vertices, (1, 0)) - origin
        gz = oracle_height(vertices, (0, 1)) - origin
        scale = math.lcm(gx.denominator, gz.denominator)
        n = [-int(gx * scale), scale, -int(gz * scale)]
        divisor = math.gcd(*n)
        return {
            "geometry_sha256": hashlib.sha256(canonical_json(document)).hexdigest(),
            "component_id": document["component_id"],
            "triangle": list(selector),
            "height_mm": {
                "numerator": str(height.numerator),
                "denominator": str(height.denominator),
            },
            "normal": [str(v // divisor) for v in n],
        }
    return None


def test_nonuniform_grid_negative_heights_and_all_boundary_ties_match_independent_oracle():
    east, south = [-1500, -1150, -250, 250, 1600], [-2100, -1350, -700, 300, 1800]
    rng = random.Random(806)
    document = terrain(east, south, [rng.randrange(-64000, 64001) for _ in range(25)])
    geometry = read_heightfield_geometry(document)
    points = [(x, z) for x in east for z in south]
    points += [
        (rng.randrange(east[0], east[-1] + 1), rng.randrange(south[0], south[-1] + 1))
        for _ in range(80)
    ]
    points += [(-1501, 0), (1601, 0), (0, -2101), (0, 1801)]
    for point in points:
        assert point_contact(geometry, point) == oracle_point(document, point), point


def test_numeric_selector_order_at_multidigit_axis_and_diagonal_ties():
    axis = list(range(0, 3251, 250))
    geometry = read_heightfield_geometry(terrain(axis))
    assert point_contact(geometry, [2500, 2500])["triangle"] == [9, 9, 1]
    assert point_contact(geometry, [2625, 2625])["triangle"] == [10, 10, 0]
    assert point_contact(geometry, [0, 0])["triangle"] == [0, 0, 0]
    assert point_contact(geometry, [3250, 3250])["triangle"] == [12, 12, 1]


def test_integer_realization_and_provenance_are_immutable_digest_inputs():
    document = terrain()
    geometry = read_heightfield_geometry(document)
    original = geometry.document()
    assert geometry.canonical_bytes == canonical_json(original)
    assert read_heightfield_geometry(original, geometry.sha256).sha256 == geometry.sha256
    document["height_mm"][0] = -123
    document["provenance"]["generator_version"] = 2
    copy_out = geometry.document()
    copy_out["east_mm"].clear()
    assert geometry.document() == original
    with pytest.raises(HeightfieldInvalid, match="digest mismatch"):
        read_heightfield_geometry(document, geometry.sha256)
    changed = copy.deepcopy(original)
    changed["provenance"]["input_sha256"] = "3" * 64
    assert read_heightfield_geometry(changed).sha256 != geometry.sha256


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(extra=1),
        lambda d: d.update(profile="unknown"),
        lambda d: d.update(diagonal="a-b-d,a-d-c"),
        lambda d: d.update(component_id=""),
        lambda d: d.update(component_id="terrain:🍃"),
        lambda d: d.update(frame="north-up"),
        lambda d: d["east_mm"].__setitem__(0, True),
        lambda d: d["east_mm"].__setitem__(0, -256001),
        lambda d: d["east_mm"].__setitem__(1, -1751),
        lambda d: d["east_mm"].reverse(),
        lambda d: d.update(east_mm=[0]),
        lambda d: d.update(east_mm=list(range(0, 258 * 250, 250))),
        lambda d: d["height_mm"].pop(),
        lambda d: d["height_mm"].__setitem__(0, 64001),
        lambda d: d["height_mm"].__setitem__(0, 1.5),
        lambda d: d["height_mm"].__setitem__(0, False),
        lambda d: d["provenance"].update(kind="model-was-good"),
        lambda d: d["provenance"].update(generator_version=True),
        lambda d: d["provenance"].update(source_sha256="A" * 64),
        lambda d: d["provenance"].update(generator_id="g" * 129),
    ],
)
def test_closed_bounded_admission_refuses_malformed_geometry(edit):
    document = terrain()
    edit(document)
    with pytest.raises(HeightfieldInvalid):
        read_heightfield_geometry(document)


def test_shared_points_have_reviewed_exact_oracle_values():
    for case in json.loads(FIXTURES.read_text())["cases"]:
        geometry = read_heightfield_geometry(case["geometry"], case["geometry_sha256"])
        for point in case["points"]:
            assert point["expected"] == oracle_point(case["geometry"], point["position"])
            assert point_contact(geometry, point["position"]) == point["expected"]
