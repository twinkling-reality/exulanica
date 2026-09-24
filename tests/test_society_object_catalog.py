"""The society's reviewed affordances, read from the world object catalog.

What inhabitants do with a kind is stated once, in ``assets/catalogs/world-objects``. These tests
hold the registry to that statement, hold the three markers to the rows and compositions they had
before the catalog held anything else, and exercise the two uses the markers never had: a kind
that states where its occupants stand, and a kind nobody uses that still stands in the way.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.assets import reviewed_assets
from exulanica.world.object_catalog import NO_ACTIVITY, world_object_catalog
from exulanica.world.objects import MAX_SCALE_MILLI, MAX_YAW_MICRORADIANS
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import (
    _place_targets,
    _scaled,
    _UsableObject,
    destination_places,
)
from exulanica.world.society_composition import (
    PLACES_FIELD,
    REVIEWED_REACH_MM,
    clearance_test,
    footprint_ring,
    reviewed_affordance_registry,
    reviewed_assignment,
    validate_recorded_registry,
    validate_reviewed_affordances,
)
from exulanica.world.society_planner import CLEARANCE_MM

import test_society_authored_ground as authored
import test_society_destination_room as room
import test_society_turned_objects as turned
from test_society_saved_world_objects import FACING_THE_PERSON, STANDING, second, thing, world

ASSETS = {asset.asset_key: asset for asset in reviewed_assets()}
KINDS = world_object_catalog().by_asset_key()
REGISTRY = reviewed_affordance_registry()

#: The rows the society held for the three markers before the catalog held anything else, as the
#: hand-written table stated them: (affordance, footprint half extents, blocks walking).
MARKER_ROWS = {
    "cc0.marker-cube": ("visit", [250, 250], True),
    "cc0.marker-pillar": ("visit", [125, 125], True),
    "cc0.marker-plate": ("rest", [500, 500], False),
}
#: Compositions pinned before the catalog held anything but the markers (the digests
#: tests/test_society_turned_objects.py and tests/test_society_destination_room.py pinned then).
MARKER_ONLY_PINS = {
    "bounded": "ab14b4b091cb2584692196601aa94ce0e690772173aa9dc31683274fb4e1fdb1",
    "endless": "d09bbf680089e03b625df491016a2a50d34d5e05f2aed7655220376426d8fb17",
    "rest": "faca5b8b6784b633b4626fc1f6f6a8dc13c99024497f620be727b53d79cd4190",
}


def _row(asset_key: str) -> dict:
    return REGISTRY[ASSETS[asset_key].content_sha256]


def test_every_catalog_kind_is_a_registry_row_and_nothing_else_is():
    assert {row["asset_key"] for row in REGISTRY.values()} == set(KINDS)
    for digest, row in REGISTRY.items():
        assert ASSETS[row["asset_key"]].content_sha256 == digest
        assert row == reviewed_assignment(KINDS[row["asset_key"]], REVIEWED_REACH_MM)


def test_the_markers_keep_their_rows_byte_for_byte():
    for key, (affordance, footprint, blocks) in MARKER_ROWS.items():
        assert _row(key) == {
            "asset_key": key,
            "affordance": affordance,
            "duration_ticks": {"visit": 1, "rest": 3}[affordance],
            "footprint_half_extents_mm": footprint,
            "blocks_navigation": blocks,
            "reach_mm": REVIEWED_REACH_MM,
        }


def test_a_world_of_markers_composes_as_it_did_before_the_catalog():
    """Under the three marker rows alone, the pinned compositions come back byte for byte.

    The registry gained rows, so its digest, which every composed input records, moved and the
    full-registry pins moved with it. Nothing else did: this is the positive control for that.
    """
    markers_only = {d: r for d, r in REGISTRY.items() if r["asset_key"] in MARKER_ROWS}
    held = authored.REGISTRY
    try:
        authored.REGISTRY = markers_only
        assert (
            authored.compose(authored.ground(), turned.UNTURNED)["document_sha256"]
            == MARKER_ONLY_PINS["bounded"]
        )
        assert (
            authored.compose(authored.endless(), turned.UNTURNED)["document_sha256"]
            == MARKER_ONLY_PINS["endless"]
        )
        document = room.first(authored.endless(), room.ONE_PLATE)
        states, _ = room.run(document, room.SEEDS[0], 12)
        assert society_state_sha256(states[-1]) == MARKER_ONLY_PINS["rest"]
    finally:
        authored.REGISTRY = held


def test_a_stated_place_is_the_catalog_place_with_its_front_toward_minus_z():
    bench = _row("cc0.bench")
    stated = KINDS["cc0.bench"].use.places
    assert stated is not None
    assert bench[PLACES_FIELD] == [[x, -y] for x, y in stated]
    assert all(z < 0 for _, z in bench[PLACES_FIELD])


def test_a_kind_nobody_uses_is_an_obstacle_row():
    lamp = _row("cc0.lamp-post")
    assert lamp == {
        "asset_key": "cc0.lamp-post",
        "affordance": NO_ACTIVITY,
        "footprint_half_extents_mm": list(KINDS["cc0.lamp-post"].use.footprint_half_extents_mm),
        "blocks_navigation": True,
    }
    validate_recorded_registry({ASSETS["cc0.lamp-post"].content_sha256: lamp})


def _usable(asset_key: str, *, yaw: int = 0, scale: int = 1000) -> _UsableObject:
    row = _row(asset_key)
    hx, hz = row["footprint_half_extents_mm"]
    return _UsableObject(
        thing("object:it", ASSETS[asset_key], 0, 0, yaw=yaw, scale=scale),
        row,
        (0, 0),
        (hx * scale // 1000, hz * scale // 1000),
    )


def test_a_kind_with_stated_places_seats_exactly_those_turned_and_scaled_with_it():
    places = _row("cc0.bench")[PLACES_FIELD]
    assert destination_places(_usable("cc0.bench"), STANDING, CLEARANCE_MM) == [
        (x, z) for x, z in places
    ]
    # Turned half a turn, the front faces the other way: every place is behind the old front.
    turned_places = destination_places(
        _usable("cc0.bench", yaw=FACING_THE_PERSON), STANDING, CLEARANCE_MM
    )
    assert [z > 0 for _, z in turned_places] == [True] * len(places)
    # Twice the size, the places stand twice as far out.
    doubled = destination_places(_usable("cc0.bench", scale=2_000), STANDING, CLEARANCE_MM)
    assert doubled == [(2 * x, 2 * z) for x, z in places]


#: Every 997 microradians round the whole turn (a prime step, so it falls into step with no
#: symmetry of a footprint), and the yaw at which a bench once lost its middle place.
SWEEP = (*range(0, MAX_YAW_MICRORADIANS + 1, 997), 47_856)


def _kept(asset_key: str, yaw: int, scale: int) -> int:
    """How many of a kind's places the society keeps where the ground and the lattice reach them.

    The object stands alone on open ground, with a lattice node at each of its places, so what
    decides is the society's own rule for one object (``_place_targets``): a place clear of the
    object's turned footprint and a standing spacing from every place kept before it.
    """
    row = _row(asset_key)
    obj = thing("object:it", ASSETS[asset_key], 0, 0, yaw=yaw, scale=scale)
    half = _scaled(row["footprint_half_extents_mm"], scale)
    usable = _UsableObject(obj, row, (0, 0), half)
    clear = clearance_test(
        [(obj.object_id, footprint_ring((0, 0), half, yaw))],
        clearance_mm=CLEARANCE_MM,
        supports=lambda *_: True,
        segment_blocked=segment_blocked,
    )
    nodes = [
        {"node_id": f"lattice:{index}", "position_mm": list(point)}
        for index, point in enumerate(destination_places(usable, STANDING, CLEARANCE_MM))
    ]
    nav = {
        "clearance_mm": CLEARANCE_MM,
        "nodes": nodes,
        "edges": [
            {"from_node_id": a["node_id"], "to_node_id": b["node_id"]}
            for a, b in zip(nodes, [*nodes[1:], nodes[0]], strict=True)
        ],
    }
    targets, _ = _place_targets(nav, [usable], clear, version_id=uuid.uuid4(), standing=STANDING)
    return len(targets[0]["place_node_ids"]) if targets else 0


@pytest.mark.parametrize("scale", [1000, MAX_SCALE_MILLI])
def test_every_stated_place_is_kept_at_every_yaw_from_the_kind_s_own_size_up(scale):
    """At its catalog size and at the largest scale an object takes, turned any way."""
    lost: dict[str, list[tuple[int, int]]] = {}
    for kind in KINDS.values():
        if not kind.use.places:
            continue
        for yaw in SWEEP:
            kept = _kept(kind.asset_key, yaw, scale)
            if kept != len(kind.use.places):
                lost.setdefault(kind.key, []).append((yaw, kept))
    # How many yaws cost each kind a place, and the first three (yaw, places kept).
    assert {key: (len(found), found[:3]) for key, found in lost.items()} == {}


def test_a_bench_in_a_saved_world_offers_rest_at_its_three_places():
    bench = thing("object:bench", ASSETS["cc0.bench"], -5_000, 3_000)
    document = second(authored.endless(), world(bench))
    assert document["availability"] == "available"
    target = next(t for t in document["targets"] if t["object_id"] == "object:bench")
    assert target["affordance"] == "rest"
    assert len(target["place_node_ids"]) == 3
    nodes = {n["node_id"]: n for n in document["navigation"]["nodes"]}
    positions = [tuple(nodes[node_id]["position_mm"]) for node_id in target["place_node_ids"]]
    assert positions == [(-5_000 + x, 3_000 + z) for x, z in _row("cc0.bench")[PLACES_FIELD]]


def test_a_bench_turned_where_it_once_lost_a_place_seats_three_in_a_saved_world():
    """The society's whole composition, at the yaw where two places once came within 699.8 mm."""
    bench = thing("object:bench", ASSETS["cc0.bench"], -5_000, 3_000, yaw=47_856)
    document = second(authored.endless(), world(bench))
    assert document["availability"] == "available"
    target = next(t for t in document["targets"] if t["object_id"] == "object:bench")
    assert len(target["place_node_ids"]) == 3


def test_a_lamp_post_blocks_walking_and_offers_nothing_to_do():
    lamp = thing("object:lamp", ASSETS["cc0.lamp-post"], 0, 0)
    alone = second(authored.endless(), world())
    with_lamp = second(authored.endless(), world(lamp))
    assert with_lamp["availability"] == "available"
    assert all(t["object_id"] != "object:lamp" for t in with_lamp["targets"])
    assert all(r["object_id"] != "object:lamp" for r in with_lamp["unavailable_affordances"])
    # The lattice node the post stands on is gone: the post is in the way.
    before = {n["node_id"] for n in alone["navigation"]["nodes"]}
    after = {n["node_id"] for n in with_lamp["navigation"]["nodes"]}
    assert after < before


BENCH = ASSETS["cc0.bench"].content_sha256
LAMP = ASSETS["cc0.lamp-post"].content_sha256
MALFORMED = {
    "places that are not pairs": (BENCH, {PLACES_FIELD: [[0]]}),
    "no places at all": (BENCH, {PLACES_FIELD: []}),
    "a place beyond the bound": (BENCH, {PLACES_FIELD: [[0, 10_001]]}),
    "an obstacle with a reach": (LAMP, {"reach_mm": REVIEWED_REACH_MM}),
    "an obstacle that names an activity": (LAMP, {"affordance": "rest"}),
}


def test_a_recorded_registry_takes_every_row_shape_the_catalog_makes():
    validate_recorded_registry(REGISTRY)


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_a_recorded_registry_refuses_a_malformed_row(case):
    digest, change = MALFORMED[case]
    with pytest.raises(ValueError, match="recorded society affordance"):
        validate_recorded_registry({digest: {**REGISTRY[digest], **change}})


def test_a_recorded_activity_row_states_its_duration():
    row = {key: value for key, value in REGISTRY[BENCH].items() if key != "duration_ticks"}
    with pytest.raises(ValueError, match="recorded society affordance"):
        validate_recorded_registry({BENCH: row})


def test_a_row_the_catalog_does_not_state_is_unreviewed():
    validate_reviewed_affordances(REGISTRY)
    bench = BENCH
    moved = copy.deepcopy(REGISTRY)
    moved[bench][PLACES_FIELD][0][0] += 1
    with pytest.raises(ValueError, match="unreviewed society"):
        validate_reviewed_affordances(moved)
    unplaced = copy.deepcopy(REGISTRY)
    del unplaced[bench][PLACES_FIELD]
    with pytest.raises(ValueError, match="unreviewed society"):
        validate_reviewed_affordances(unplaced)
    swapped = copy.deepcopy(REGISTRY)
    swapped[bench] = {**swapped[bench], "asset_key": "cc0.cafe-table"}
    with pytest.raises(ValueError, match="unreviewed society"):
        validate_reviewed_affordances(swapped)


#: The least a turned blocking corner may come to a whole millimetre: a thousand times the most one
#: unit in the last place of a cosine and of a sine moves a corner of these sizes (under 1e-12 mm),
#: so the outward rounding ``footprint_ring`` makes never depends on a machine's arithmetic.
TURNED_CORNER_MARGIN_MM = 1e-9


def test_no_turned_blocking_corner_comes_near_a_whole_millimetre():
    """Every blocking footprint the catalog states, every nonzero microradian yaw, every corner."""
    np = pytest.importorskip(
        "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
    )
    from exulanica.world.objects import MAX_YAW_MICRORADIANS

    theta = np.arange(1, MAX_YAW_MICRORADIANS + 1, dtype=np.float64) / 1_000_000
    c, s = np.cos(theta), np.sin(theta)
    blocking = [kind for kind in KINDS.values() if kind.use.blocks_navigation]
    assert len(blocking) > 3
    for kind in blocking:
        hx, hz = kind.use.footprint_half_extents_mm
        for dx in (-hx, hx):
            for dz in (-hz, hz):
                for value in (dx * c + dz * s, -dx * s + dz * c):
                    least = float(np.min(np.abs(value - np.round(value))))
                    assert least > TURNED_CORNER_MARGIN_MM, (kind.key, dx, dz, least)
