"""A saved world's objects stand at whatever yaw the person placed them at, and a society uses them.

Placing an object in front of yourself turns it to face you, so almost nothing a person places is
at yaw zero. The saved-world projection takes an object at any yaw: its centre and reach do not
turn, and a blocking object's footprint turns with it. A district projection keeps refusing a
turned object, as its pinned inputs were composed.
"""

from __future__ import annotations

import math

import pytest
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.assets import reviewed_assets
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society_composition import composed_objects, footprint_ring
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_COMPOSITION,
    LEGACY_COMPOSITION,
    LOCAL_COMPOSITION,
)
from exulanica.world.society_planner import CLEARANCE_MM

import test_society_authored_ground as authored

CUBE = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-cube")
#: What "Place before me" stores for a person standing at the spawn, looking the way it faces.
FACING_THE_PERSON = 3_141_593
QUARTER_TURN = 785_398  # 45 degrees in microradians, where a turned square differs the most


def turned(object_id, asset, x_mm, z_mm, yaw_microradians):
    return AuthoredObject(
        object_id=object_id,
        asset_sha256=asset.content_sha256,
        region_id="region:starter",
        transform=Transform(
            x_mm=x_mm, y_mm=0, z_mm=z_mm, yaw_microradians=yaw_microradians, scale_milli=1000
        ),
        origin=ObjectOrigin("authored", "fictional"),
    )


@pytest.mark.parametrize(
    "area", [authored.ground(), authored.endless()], ids=["bounded", "endless"]
)
def test_a_plate_placed_facing_the_person_is_somewhere_to_rest(area):
    document = authored.compose(
        area, authored.version(turned("object:cushion", authored.PLATE, 0, 500, FACING_THE_PERSON))
    )
    assert document["availability"] == "available", document["unavailable_reason"]
    [target] = document["targets"]
    assert (target["object_id"], target["affordance"]) == ("object:cushion", "rest")
    # A plate does not block walking, so turning it changes nothing about where anybody walks.
    plain = authored.compose(
        area, authored.version(authored.placed("object:cushion", authored.PLATE, 0, 500))
    )
    assert document["navigation"]["edges"] == plain["navigation"]["edges"]
    assert document["navigation"]["nodes"] == plain["navigation"]["nodes"]


UNTURNED = authored.version(
    authored.placed("object:cushion", authored.PLATE, 3_000, 5_000),
    authored.placed("object:post", authored.PILLAR, -4_000, 1_000),
)


@pytest.mark.parametrize(
    "area", [authored.ground(), authored.endless()], ids=["bounded", "endless"]
)
def test_taking_turned_objects_changes_nothing_for_an_unturned_world(area, monkeypatch):
    import exulanica.world.society_composition as composition

    taken = authored.compose(area, UNTURNED)
    # The rule that refused every turn, put back for one composition of the same world.
    monkeypatch.setattr(composition, "AUTHORED_GROUND_COMPOSITION", "the rule before turns")
    refused = authored.compose(area, UNTURNED)
    assert refused == taken
    # And the old rule is really what ran: a turned object is refused under it.
    turned_world = authored.version(turned("object:post", authored.PILLAR, 0, 0, QUARTER_TURN))
    assert authored.compose(area, turned_world)["unavailable_reason"] == (
        "unsupported_object_transform:object:post"
    )


#: Composed under the registry of every world object catalog kind. Under its three marker rows
#: alone these are ab14b4b0... and d09bbf68..., the digests before the catalog held furniture, and
#: tests/test_society_object_catalog.py holds that.
@pytest.mark.parametrize(
    ("area", "digest"),
    [
        (authored.ground(), "205099b240299d9833241d67789e1524de051648f1afe1c9cb518595013c7956"),
        (authored.endless(), "b496b4d0eb430ffbe9b9d6640230c97c050a1398513aca1990238831be48ea5a"),
    ],
    ids=["bounded", "endless"],
)
def test_an_unturned_world_composes_to_its_pinned_bytes(area, digest):
    assert authored.compose(area, UNTURNED)["document_sha256"] == digest


def _inside(point, polygon):
    """Point in a convex counter- or clockwise polygon, in floating point."""
    signs = set()
    for (ax, az), (bx, bz) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        cross = (bx - ax) * (point[1] - az) - (bz - az) * (point[0] - ax)
        if cross:
            signs.add(cross > 0)
    return len(signs) <= 1


def _point_segment(p, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / (dx * dx + dz * dz)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dz)


def _distance_to_square(a, b, square):
    """Shortest distance from segment ab to a convex polygon, zero when they touch."""
    if _inside(a, square) or _inside(b, square):
        return 0.0
    edges = list(zip(square, square[1:] + square[:1], strict=True))
    return min(
        min(
            _point_segment(a, c, d),
            _point_segment(b, c, d),
            _point_segment(c, a, b),
            _point_segment(d, a, b),
        )
        for c, d in edges
    )


def _exact_square(center, half, yaw_microradians):
    theta = yaw_microradians / 1_000_000
    c, s = math.cos(theta), math.sin(theta)
    return [
        (center[0] + dx * c + dz * s, center[1] - dx * s + dz * c)
        for dx, dz in ((-half, -half), (half, -half), (half, half), (-half, half))
    ]


def test_a_turned_cube_prunes_exactly_the_edges_its_turned_footprint_comes_near():
    center, half = (1_000, 760), 250
    empty = authored.compose(authored.endless(), authored.version())
    all_edges = {edge["edge_id"]: edge for edge in empty["navigation"]["edges"]}
    positions = {node["node_id"]: node["position_mm"] for node in empty["navigation"]["nodes"]}

    def pruned(yaw):
        world = authored.version(turned("object:cube", CUBE, *center, yaw))
        document = authored.compose(authored.endless(), world)
        assert document["availability"] == "available", document["unavailable_reason"]
        return set(all_edges) - {edge["edge_id"] for edge in document["navigation"]["edges"]}

    def expected(yaw):
        # Worked out here in floating point from the exact turned square, not from the ring the
        # projection rounds, and every edge is far enough from the clearance for rounding to
        # decide nothing.
        square = _exact_square(center, half, yaw)
        near = set()
        for edge_id, edge in all_edges.items():
            a, b = positions[edge["from_node_id"]], positions[edge["to_node_id"]]
            distance = _distance_to_square(a, b, square)
            assert abs(distance - CLEARANCE_MM) > 1, (edge_id, distance)
            if distance < CLEARANCE_MM:
                near.add(edge_id)
        return near

    beside = "ground:+00000000:+00000000|ground:+00002000:+00000000"
    # Unturned, the cube's near face is 510 mm from that edge; turned an eighth, its corner is
    # 406 mm from it. The rotation is what prunes it.
    assert beside not in pruned(0) and pruned(0) == expected(0)
    assert beside in pruned(QUARTER_TURN) and pruned(QUARTER_TURN) == expected(QUARTER_TURN)
    assert pruned(FACING_THE_PERSON) == expected(FACING_THE_PERSON)


def test_the_turned_ring_is_the_rectangle_unturned_and_only_ever_grows():
    assert footprint_ring((1_000, 760), (250, 250), 0) == [
        (750, 510),
        (1_250, 510),
        (1_250, 1_010),
        (750, 1_010),
        (750, 510),
    ]
    for yaw in (1, QUARTER_TURN, 1_570_796, FACING_THE_PERSON, 4_712_389, 6_283_185):
        ring = footprint_ring((1_000, 760), (250, 250), yaw)
        exact = _exact_square((1_000, 760), 250, yaw)
        for (x, z), (ex, ez) in zip(ring, exact, strict=False):
            assert abs(x - ex) < 1 and abs(z - ez) < 1
            # Outward on each axis: never closer to the centre than the exact corner.
            assert abs(x - 1_000) >= abs(ex - 1_000) and abs(z - 760) >= abs(ez - 760)


@pytest.mark.parametrize("profile", [LEGACY_COMPOSITION, LOCAL_COMPOSITION])
def test_a_district_projection_still_refuses_a_turned_object(profile):
    world = authored.version(turned("object:post", authored.PILLAR, 0, 0, FACING_THE_PERSON))
    _, _, reason = composed_objects(
        world,
        authored.REGISTRY,
        region_id="region:starter",
        translation_mm=(0, 0, 0),
        composition_profile=profile,
    )
    assert reason == "unsupported_object_transform:object:post"
    _, _, reason = composed_objects(
        world,
        authored.REGISTRY,
        region_id="region:starter",
        translation_mm=(0, 0, 0),
        composition_profile=AUTHORED_GROUND_COMPOSITION,
    )
    assert reason is None


def test_segment_blocking_reads_the_turned_ring_the_projection_builds():
    # The same predicate the projection prunes with, over the same ring it builds.
    ring = footprint_ring((1_000, 760), (250, 250), QUARTER_TURN)
    assert segment_blocked((0, 0), (2_000, 0), ring, CLEARANCE_MM)
    assert not segment_blocked(
        (0, 0), (2_000, 0), footprint_ring((1_000, 760), (250, 250), 0), CLEARANCE_MM
    )
