"""Swept contact checked by independent half-plane vertex enumeration and adversarial geometry."""

from __future__ import annotations

import copy
import itertools
import json
import math
from fractions import Fraction

import pytest
from exulanica.world.heightfield_contact import (
    POLICY,
    PROFILE,
    at,
    passive_patch,
    read_heightfield_contact,
    sweep,
)
from exulanica.world.heightfield_geometry import (
    HeightfieldInvalid,
    point_contact,
    read_heightfield_geometry,
)

from test_heightfield_geometry import FIXTURES, oracle_height, oracle_point, terrain, triangles


def contact_document(geometry, obstructions=()):
    return {
        "profile": PROFILE,
        "geometry_sha256": geometry.sha256,
        "component_id": geometry.component_id,
        "policy": POLICY,
        "obstructions": list(obstructions),
    }


def surface(document=None, obstructions=()):
    geometry = read_heightfield_geometry(terrain() if document is None else document)
    return read_heightfield_contact(contact_document(geometry, obstructions), geometry)


def box(bounds, identity="obstacle:test"):
    return {"kind": "aabb", "obstruction_id": identity, "bounds_mm": list(bounds)}


def _line(a, b):
    # Ax+Bz+C >= 0, distinct from the production polygon clipping representation.
    A, B = a[1] - b[1], b[0] - a[0]
    C = -(A * a[0] + B * a[1])
    divisor = math.gcd(A, B, C)
    return tuple(v // divisor for v in (A, B, C))


def _evaluate(line, point):
    return line[0] * point[0] + line[1] * point[1] + line[2]


def _supporting_halfplanes(points):
    lines = set()
    for a, b in itertools.permutations(set(points), 2):
        line = _line(a, b)
        if all(_evaluate(line, p) >= 0 for p in points):
            lines.add(line)
    return sorted(lines)


def _intersection_vertices(lines):
    """Enumerate intersections of all boundary-line pairs, retaining every feasible vertex.

    This uses neither polygon clipping nor the production triangle planes. Degenerate closed
    segments and points also have feasible boundary intersections and therefore remain visible.
    """
    vertices = set()
    for first, second in itertools.combinations(lines, 2):
        a, b, c = first
        d, e, f = second
        determinant = a * e - b * d
        if not determinant:
            continue
        point = (Fraction(b * f - c * e, determinant), Fraction(c * d - a * f, determinant))
        if all(_evaluate(line, point) >= 0 for line in lines):
            vertices.add(point)
    return vertices


def _wire_ratio(value):
    value = Fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def oracle_sweep(
    document, start, end, *, half_width=340, height=1800, passive=False, obstructions=()
):
    answer = {
        "status": "clear",
        "reason": None,
        "contact": None,
        "height_range_mm": None,
        "triangles": 0,
    }

    def refuse(reason):
        answer.update(
            status="unavailable" if reason in ("work_limit", "unknown_obstruction") else "blocked",
            reason=reason,
        )
        return answer

    if sum((a - b) ** 2 for a, b in zip(start, end, strict=True)) > 2000**2:
        return refuse("segment_limit")
    corners = [
        (x + dx, z + dz)
        for x, z in (start, end)
        for dx in (-half_width, half_width)
        for dz in (-half_width, half_width)
    ]
    xmin, xmax = min(x for x, _ in corners), max(x for x, _ in corners)
    zmin, zmax = min(z for _, z in corners), max(z for _, z in corners)
    east, south = document["east_mm"], document["south_mm"]
    if xmin < east[0] or xmax > east[-1] or zmin < south[0] or zmax > south[-1]:
        return refuse("outside_domain")
    columns = sum(a <= xmax and b >= xmin for a, b in itertools.pairwise(east))
    rows = sum(a <= zmax and b >= zmin for a, b in itertools.pairwise(south))
    candidates = rows * columns * 2
    if candidates > 4096 or candidates * (1 + len(obstructions)) > 262144:
        return refuse("work_limit")
    if any(o["kind"] == "unknown" for o in obstructions):
        return refuse("unknown_obstruction")
    hull_lines = _supporting_halfplanes(corners)
    pieces = []
    for _, triangle in triangles(document):
        triangle_lines = _supporting_halfplanes([(v[0], v[2]) for v in triangle])
        lines = hull_lines + triangle_lines
        vertices = _intersection_vertices(lines)
        if vertices:
            heights = [oracle_height(triangle, p) for p in vertices]
            origin = oracle_height(triangle, (0, 0))
            gradient = [oracle_height(triangle, p) - origin for p in ((1, 0), (0, 1))]
            pieces.append((lines, min(heights), max(heights), sum(g * g for g in gradient)))
    low, high = min(p[1] for p in pieces), max(p[2] for p in pieces)
    answer.update(
        contact=oracle_point(document, end),
        height_range_mm=[_wire_ratio(low), _wire_ratio(high)],
        triangles=len(pieces),
    )
    if low < 350:
        return refuse("wet")
    if passive:
        if low != high or low.denominator != 1:
            return refuse("not_flat")
    elif any(piece[3] > Fraction(6248, 10000) ** 2 for piece in pieces):
        return refuse("steep")
    for lines, _, _, _ in pieces:
        for obstruction in obstructions:
            x0, y0, z0, x1, y1, z1 = obstruction["bounds_mm"]
            if y1 < low or y0 > high + height:
                continue
            rect = [(1, 0, -x0), (-1, 0, x1), (0, 1, -z0), (0, -1, z1)]
            if _intersection_vertices(lines + rect):
                return refuse("obstructed")
    return answer


def test_full_sweeps_match_independent_halfplane_oracle_on_nonuniform_non_lagoon_surface():
    east, south = [-2000, -1250, -250, 500, 1750], [-2000, -1000, 250, 1000, 2000]
    # A reproducible valley/ridge with uneven cells and rational contacts, independent
    # of the prototype.
    heights = [900 + abs(x) // 8 + z // 10 for z in south for x in east]
    document = terrain(east, south, heights)
    obstacles = [box([-100, 2000, -100, 150, 2200, 100])]
    for obstructions in ([], obstacles):
        contact = surface(document, obstructions)
        for start, end in [((-900, -1200), (500, 0)), ((0, 0), (0, 0)), ((-500, 300), (800, 1000))]:
            assert sweep(contact, start, end) == oracle_sweep(
                document, start, end, obstructions=obstructions
            )


@pytest.mark.parametrize(("height", "reason"), [(0, "wet"), (800, "steep")])
def test_corner_sliver_missed_by_centre_and_four_axis_samples_is_refused(height, reason):
    axis = list(range(-1000, 1001, 250))
    document = terrain(axis)
    document["height_mm"][5 * len(axis) + 5] = height
    contact = surface(document)
    for point in [(0, 0), (-340, 0), (340, 0), (0, -340), (0, 340)]:
        sample = point_contact(contact.geometry, point)
        assert sample["height_mm"] == {"numerator": "500", "denominator": "1"}
        assert sample["normal"] == ["0", "1", "0"]
    result = at(contact, [0, 0])
    assert result["reason"] == reason
    assert result == oracle_sweep(document, [0, 0], [0, 0])


@pytest.mark.parametrize("bounds", [[-10, 500, -10, 10, 900, 10], [-10, 2000, -10, 10, 2100, 10]])
def test_diagonal_barrier_and_midway_headroom_refuse_between_valid_endpoints(bounds):
    contact = surface(obstructions=[box(bounds)])
    start, end = [-700, -700], [700, 700]
    assert at(contact, start)["status"] == at(contact, end)["status"] == "clear"
    before = copy.deepcopy(start)
    assert sweep(contact, start, end)["reason"] == "obstructed"
    assert start == before
    assert sweep(contact, start, end) == oracle_sweep(
        contact.geometry.document(), start, end, obstructions=[box(bounds)]
    )


@pytest.mark.parametrize(
    ("bounds", "blocked"),
    [
        ([340, 500, 0, 350, 600, 10], True),
        ([341, 500, 0, 350, 600, 10], False),
        ([0, 2300, 0, 10, 2301, 10], True),
        ([0, 2301, 0, 10, 2301, 10], False),
        ([0, 499, 0, 10, 499, 10], False),
        ([0, 499, 0, 10, 500, 10], True),
        ([340, 2300, 340, 340, 2300, 340], True),
        ([340, 2300, 341, 340, 2300, 341], False),
        ([0, 500, 1000, 0, 600, 1100], False),
    ],
)
def test_closed_obstacle_tangency_including_finite_zero_area_proxies(bounds, blocked):
    result = at(surface(obstructions=[box(bounds)]), [0, 0])
    assert (result["reason"] == "obstructed") is blocked


def test_complete_footprint_and_segment_limit_are_exact_and_precede_geometry_work():
    contact = surface()
    assert at(contact, [1660, 0])["status"] == "clear"
    assert at(contact, [1661, 0])["reason"] == "outside_domain"
    assert sweep(contact, [-1000, 0], [1000, 0])["status"] == "clear"
    assert sweep(contact, [-1000, 0], [1000, 1])["reason"] == "segment_limit"
    assert at(contact, [1800, 1800])["triangles"] == 0


def test_exact_slope_threshold_and_full_flat_patch_are_separate_proofs():
    axis = [-1250, 0, 1250]
    document = terrain(axis, heights=[2000 + (x + 1250) * 781 // 1250 for _ in axis for x in axis])
    contact = surface(document)
    assert at(contact, [0, 0])["status"] == "clear"
    assert passive_patch(contact, [0, 0], 340, 500)["reason"] == "not_flat"
    document["height_mm"][5] += 1
    assert at(surface(document), [0, 0])["reason"] == "steep"
    flat = surface()
    assert passive_patch(flat, [0, 0], 700, 1800)["status"] == "clear"
    assert passive_patch(flat, [1500, 0], 501, 100)["reason"] == "outside_domain"


def test_closed_boundary_steep_triangle_is_conservative_for_navigation_but_flat_patch_is_exact():
    axis = [-1250, -340, 660, 1660]
    # The square ends on x=-340; its entire occupied area is flat, steep terrain just outside.
    document = terrain(axis, heights=[500, 500, 1500, 1500] * len(axis))
    contact = surface(document)
    centre = [-680, 0]
    assert at(contact, centre)["reason"] == "steep"
    assert passive_patch(contact, centre, 340, 500)["status"] == "clear"
    assert passive_patch(contact, centre, 341, 500)["reason"] == "not_flat"


def test_work_and_unknown_geometry_are_unavailable_and_bounded_before_clipping(monkeypatch):
    from exulanica.world import heightfield_contact as implementation

    axis = list(range(-32000, 32001, 250))
    document = terrain(axis)
    unknown = [{"kind": "unknown", "obstruction_id": "mesh:unknown"}]
    contact = surface(document, unknown)

    def expensive(*_):
        raise AssertionError("preflight must not clip")

    monkeypatch.setattr(implementation, "_clip", expensive)
    assert passive_patch(contact, [0, 0], 6000, 100)["reason"] == "work_limit"
    assert at(contact, [0, 0])["reason"] == "unknown_obstruction"
    obstacles = [
        box([10000, 10000, 10000, 11000, 11000, 11000], f"obstacle:{n:03}") for n in range(80)
    ]
    assert passive_patch(surface(document, obstacles), [0, 0], 5250, 100)["reason"] == "work_limit"


def test_contact_authority_binding_and_input_shapes_refuse_without_coercion():
    geometry = read_heightfield_geometry(terrain())
    document = contact_document(geometry)
    contact = read_heightfield_contact(document, geometry)
    assert read_heightfield_contact(document, geometry, contact.sha256).sha256 == contact.sha256
    for changes in [
        {"component_id": "terrain:elsewhere"},
        {"geometry_sha256": "0" * 64},
        {"policy": "easier"},
        {"extra": 1},
        {"obstructions": [box([1, 0, 0, 0, 1, 1])]},
        {"obstructions": [box([0, False, 0, 1, 1, 1])]},
        {"obstructions": [box([0, 0, 0, 1, 1, 1])] * 513},
        {"obstructions": [box([0, 0, 0, 1, 1, 1])] * 2},
        {"obstructions": [{"kind": "mesh", "obstruction_id": "mesh:test"}]},
    ]:
        with pytest.raises(HeightfieldInvalid):
            read_heightfield_contact({**document, **changes}, geometry)
    with pytest.raises(HeightfieldInvalid, match="digest mismatch"):
        read_heightfield_contact(document, geometry, "0" * 64)
    for point in ([True, 0], [0, 1.1], [0], [512001, 0]):
        with pytest.raises(HeightfieldInvalid):
            at(contact, point)
    for size in (0, True, 256001):
        with pytest.raises(HeightfieldInvalid):
            passive_patch(contact, [0, 0], size, 100)


def test_shared_contact_vectors_match_independent_exact_oracle():
    for case in json.loads(FIXTURES.read_text())["cases"]:
        geometry = read_heightfield_geometry(case["geometry"], case["geometry_sha256"])
        contact = read_heightfield_contact(case["contact"], geometry, case["contact_sha256"])
        for query in case["sweeps"]:
            expected = oracle_sweep(
                case["geometry"],
                query["start"],
                query["end"],
                obstructions=case["contact"]["obstructions"],
            )
            assert query["expected"] == expected
            assert sweep(contact, query["start"], query["end"]) == expected
        for query in case["patches"]:
            expected = oracle_sweep(
                case["geometry"],
                query["position"],
                query["position"],
                half_width=query["half_width_mm"],
                height=query["height_mm"],
                passive=True,
                obstructions=case["contact"]["obstructions"],
            )
            assert query["expected"] == expected
            assert (
                passive_patch(
                    contact, query["position"], query["half_width_mm"], query["height_mm"]
                )
                == expected
            )


def test_slope_headroom_covers_upright_person_above_lower_adjacent_terrain_piece():
    axis = [0, 1000, 2000]
    document = terrain(axis, heights=[1000 + x // 2 for _ in axis for x in axis])
    obstacle = box([950, 3350, 990, 960, 3360, 1010])
    contact = surface(document, [obstacle])
    point = [1250, 1000]
    # The centered foot is at 1625, so its upright 1800mm body reaches 3425. The roof
    # overlaps that body despite lying above the lower adjacent piece's own 3300mm top.
    assert point_contact(contact.geometry, point)["height_mm"] == {
        "numerator": "1625",
        "denominator": "1",
    }
    result = at(contact, point)
    assert result["reason"] == "obstructed"
    assert result == oracle_sweep(document, point, point, obstructions=[obstacle])
