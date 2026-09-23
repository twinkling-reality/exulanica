"""One ordinary object never empties a saved world's society.

The second saved-world composition (``exulanica.society-composition/authored-ground-v2``) decides
every object on its own. A turned or scaled object is used as it stands; an object that moves
blocks everywhere its motion covers and offers nothing; an object off the ground plane blocks its
footprint and offers nothing; an environment placement is named as unread; an override that keeps
the ground where it is changes nothing. In every case the rest of the world stays usable, which
the first composition did not allow, and each accepting test runs at a value other than the
default: yaw, scale, height, behaviour, placement or override.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import replace

import pytest
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.assets import reviewed_assets
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.environment_instances import (
    EnvironmentInstance,
    EnvironmentSelection,
    EnvironmentSourceBinding,
    SourceAnchor,
)
from exulanica.world.objects import (
    AuthoredObject,
    ElementOverride,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
)
from exulanica.world.society_authored_ground import (
    StandingPolicy,
    _UsableObject,
    build_authored_ground_society_input,
    build_authored_ground_society_input_v2,
    convex_ring,
    destination_places,
)
from exulanica.world.society_composition import footprint_ring
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_INPUT,
    AUTHORED_GROUND_INPUT_V2,
    MOVES,
    NO_AUTHORED_FRAME,
    OFF_GROUND,
    UNSUPPORTED_BEHAVIOUR,
)
from exulanica.world.society_living import current_routine
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    input_sha256,
    validate_input_successor,
    validate_society_input,
)

import test_society_authored_ground as authored

CUBE = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-cube")
PILLAR, PLATE = authored.PILLAR, authored.PLATE
POLICY = current_routine().policy
STANDING = StandingPolicy(POLICY["standing_spacing_mm"], POLICY["standing_radius_mm"])
FACING_THE_PERSON = 3_141_593
MOTION = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"travel_mm": 4_000, "period_milliseconds": 4_000, "axis": "x", "easing": "smooth"},
)


def thing(object_id, asset, x_mm, z_mm, *, y_mm=0, yaw=0, scale=1000, behaviour=None):
    return AuthoredObject(
        object_id=object_id,
        asset_sha256=asset.content_sha256,
        region_id="region:starter",
        transform=Transform(x_mm, y_mm, z_mm, yaw, scale),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=behaviour,
    )


def placement(instance_id: str) -> EnvironmentInstance:
    source = EnvironmentSourceBinding(
        admission_id=uuid.UUID(int=10),
        render_asset_id=uuid.UUID(int=11),
        publication_id=None,
        source_sha256="1" * 64,
        source_receipt_sha256="2" * 64,
        render_sha256="3" * 64,
        render_receipt_sha256="4" * 64,
        index_sha256=None,
        index_receipt_sha256=None,
        publication_receipt_sha256=None,
        place_id=uuid.UUID(int=12),
        frame={"name": "grid", "axis_order": ["east", "north", "height"]},
        bounds={
            "kind": "bbox",
            "frame_name": "grid",
            "coordinate_scale": 1000,
            "coordinates": [0, 0, 0, 10, 10, 10],
        },
        anchor=SourceAnchor("grid", 1000, (5, 5, 0)),
        selection=EnvironmentSelection("whole_asset"),
    )
    return EnvironmentInstance(
        instance_id=instance_id,
        source=source,
        region_id="region:starter",
        transform=Transform(-6_000, 0, -6_000, 260_000, 1_120),
        origin=ObjectOrigin("authored", "fictional"),
    )


def world(*objects, overrides=(), placements=()) -> AlternateVersion:
    """A saved world holding a reachable cushion plus whatever the case adds."""
    held = (thing("object:cushion", PLATE, 3_000, 5_000), *objects)
    return AlternateVersion(
        version_id=authored.VERSION,
        world_id=authored.WORLD,
        source_snapshot_id=authored.SNAPSHOT,
        parent_version_id=None,
        title="A world of my own",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=held,
            element_overrides=overrides,
            environment_instances=placements,
            point_map_instances=(),
        ),
        edit_seq=len(held) + len(placements) + len(overrides),
        source_invalidated=False,
        created_by=uuid.uuid4(),
        created_at="2026-09-23T00:00:00+00:00",
        objects=held,
        element_overrides=tuple(overrides),
        environment_instances=tuple(placements),
    )


def second(area, version, *, input_seq=1):
    return build_authored_ground_society_input_v2(
        ground=area,
        version=version,
        input_seq=input_seq,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=authored.REGISTRY,
        segment_blocked=segment_blocked,
        standing=STANDING,
    )


def first(area, version):
    return build_authored_ground_society_input(
        ground=area,
        version=version,
        input_seq=1,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=authored.REGISTRY,
        segment_blocked=segment_blocked,
    )


GROUNDS = pytest.mark.parametrize(
    "area", [authored.ground(), authored.endless()], ids=["bounded", "endless"]
)
IDENTITY = ElementOverride("element:starter-ground", False, Transform(0, 0, 0, 0, 1000))
CASES = {
    # case: (world, what the first composition said, the object's own outcome in the second)
    "turned": (
        world(thing("object:post", PILLAR, -4_000, 1_000, yaw=FACING_THE_PERSON)),
        None,
        "used",
    ),
    "scaled": (
        world(thing("object:post", PILLAR, -4_000, 1_000, scale=2_000)),
        "unsupported_object_transform:object:post",
        "used",
    ),
    "raised": (
        world(thing("object:lifted", CUBE, 4_000, -4_000, y_mm=500)),
        "unsupported_object_transform:object:lifted",
        OFF_GROUND,
    ),
    "moving": (
        world(thing("object:slider", CUBE, -8_000, -8_000, behaviour=MOTION)),
        "unsupported_active_behaviour:object:slider",
        MOVES,
    ),
    "unruled behaviour on a plate": (
        world(
            thing("object:spinner", PLATE, -3_000, 5_000, behaviour=ObjectBehaviour("spin", 1, {}))
        ),
        "unsupported_active_behaviour:object:spinner",
        UNSUPPORTED_BEHAVIOUR,
    ),
    "environment placement": (
        world(placements=(placement("environment:corner-building"),)),
        "unsupported_environment_composition",
        "unread",
    ),
    "ground override that keeps the ground": (
        world(overrides=(IDENTITY,)),
        "unsupported_structural_overrides",
        None,
    ),
}


@GROUNDS
@pytest.mark.parametrize("case", sorted(CASES))
def test_one_ordinary_object_leaves_the_rest_of_the_world_usable(area, case):
    version, before, outcome = CASES[case]
    # The positive control: the first composition, on the same world, is what this replaces.
    old = first(area, version)
    assert old["profile"] == AUTHORED_GROUND_INPUT
    assert old["unavailable_reason"] == before
    document = second(area, version)
    validate_society_input(document)
    assert document["profile"] == AUTHORED_GROUND_INPUT_V2
    assert document["availability"] == "available", document["unavailable_reason"]
    targets = {t["object_id"]: t for t in document["targets"]}
    # The cushion is somewhere to rest in every case, with its places.
    assert targets["object:cushion"]["affordance"] == "rest"
    assert len(targets["object:cushion"]["place_node_ids"]) == 2
    records = {r["object_id"]: r["reason"] for r in document["unavailable_affordances"]}
    added = {o.object_id for o in version.objects} - {"object:cushion"}
    if outcome == "used":
        assert added <= set(targets) and not records
    elif outcome == "unread":
        assert document["unread_placements"] == [
            {"instance_id": "environment:corner-building", "reason": NO_AUTHORED_FRAME}
        ]
        assert not records and set(targets) == {"object:cushion"}
    elif outcome is None:
        assert not records and set(targets) == {"object:cushion"}
    else:
        assert records == {object_id: outcome for object_id in added}
        assert set(targets) == {"object:cushion"}


@GROUNDS
def test_an_environment_placement_changes_nothing_but_the_list_that_names_it(area):
    plain = second(area, world())
    placed = second(area, world(placements=(placement("environment:corner-building"),)))
    for key in ("targets", "unavailable_affordances"):
        assert placed[key] == plain[key]
    assert placed["navigation"] == plain["navigation"]
    assert plain["unread_placements"] == []
    # A removed placement is not in the world, so it is not named either.
    removed = replace(placement("environment:corner-building"), removed=True)
    assert second(area, world(placements=(removed,)))["unread_placements"] == []


@pytest.mark.parametrize(
    "override",
    [
        ElementOverride("element:starter-ground", True, None),
        ElementOverride("element:starter-ground", False, Transform(1_000, 0, 0, 0, 1000)),
        ElementOverride("element:starter-ground", False, Transform(0, 250, 0, 0, 1000)),
    ],
    ids=["hidden", "moved", "raised"],
)
def test_an_override_that_hides_or_moves_the_ground_is_named(override):
    document = second(authored.endless(), world(overrides=(override,)))
    assert document["availability"] == "unavailable"
    assert document["unavailable_reason"] == "unsupported_ground_override:element:starter-ground"
    assert document["targets"] == [] and document["unread_placements"] == []
    assert document["unavailable_affordances"] == [] and document["navigation"]["nodes"] == []


def test_the_ground_element_placement_is_the_one_the_snapshot_states():
    from exulanica.world.starter import authored_starter_candidate

    candidate = authored_starter_candidate(authored.WORLD)
    [element] = candidate.placement["elements"]
    stated = Transform(
        element["x_mm"],
        element["y_mm"],
        element["z_mm"],
        element["yaw_microradians"],
        element["scale_milli"],
    )
    assert stated == authored.endless().element_transform() == IDENTITY.transform


@pytest.mark.parametrize(
    ("obj", "reason"),
    [
        (
            thing("object:spinning-post", PILLAR, 0, 0, behaviour=ObjectBehaviour("spin", 1, {})),
            "unsupported_active_behaviour",
        ),
        (
            thing(
                "object:bad-path",
                CUBE,
                0,
                0,
                behaviour=ObjectBehaviour("motion.bounded-path", 1, {"travel_mm": 100}),
            ),
            "unsupported_active_behaviour",
        ),
        (thing("object:elsewhere", PLATE, 0, 0), "unregistered_object_region"),
    ],
    ids=["unruled-behaviour-that-blocks", "unreadable-path", "another-region"],
)
def test_what_the_society_cannot_bound_still_refuses_by_name(obj, reason):
    if reason == "unregistered_object_region":
        obj = replace(obj, region_id="region:other")
    document = second(authored.endless(), world(obj))
    assert document["availability"] == "unavailable"
    assert document["unavailable_reason"] == f"{reason}:{obj.object_id}"
    assert document["navigation"]["nodes"] == [] and document["targets"] == []


def _pruned(document):
    lattice = {e["edge_id"] for e in authored.ground_navigation(authored.endless())["edges"]}
    return lattice - {e["edge_id"] for e in document["navigation"]["edges"]}


def test_a_scaled_object_blocks_its_scaled_footprint_and_nothing_more():
    # A pillar five times its size covers a 1,250 mm square. Unscaled, it stands a metre from
    # every lattice line and takes nothing away; scaled, the lattice edges that come within a
    # clearance of it are exactly those a 625 mm half extent footprint takes away.
    post = thing("object:post", PILLAR, -3_000, 1_000, scale=5_000)
    document = second(authored.endless(), world(post))
    ring = footprint_ring((-3_000, 1_000), (625, 625), 0)
    nodes = {
        n["node_id"]: n["position_mm"]
        for n in authored.ground_navigation(authored.endless())["nodes"]
    }
    expected = {
        e["edge_id"]
        for e in authored.ground_navigation(authored.endless())["edges"]
        if segment_blocked(
            tuple(nodes[e["from_node_id"]]), tuple(nodes[e["to_node_id"]]), ring, CLEARANCE_MM
        )
    }
    assert expected and _pruned(document) == expected
    unit = second(
        authored.endless(),
        world(replace(post, transform=replace(post.transform, scale_milli=1000))),
    )
    assert _pruned(unit) == set()


def test_a_moving_object_blocks_everywhere_its_motion_covers():
    still = second(authored.endless(), world(thing("object:slider", CUBE, -8_000, -8_000)))
    moving = second(
        authored.endless(), world(thing("object:slider", CUBE, -8_000, -8_000, behaviour=MOTION))
    )
    # The path runs four metres east of where the cube was placed, so edges near the far end are
    # pruned only while it moves, and every edge the still cube prunes stays pruned.
    assert _pruned(still) < _pruned(moving)
    sweep = convex_ring(
        [
            *footprint_ring((-8_000, -8_000), (250, 250), 0)[:-1],
            *footprint_ring((-4_000, -8_000), (250, 250), 0)[:-1],
        ]
    )
    assert sweep == [
        (-8_250, -8_250),
        (-3_750, -8_250),
        (-3_750, -7_750),
        (-8_250, -7_750),
        (-8_250, -8_250),
    ]
    nodes = {
        n["node_id"]: n["position_mm"]
        for n in authored.ground_navigation(authored.endless())["nodes"]
    }
    expected = {
        e["edge_id"]
        for e in authored.ground_navigation(authored.endless())["edges"]
        if segment_blocked(
            tuple(nodes[e["from_node_id"]]), tuple(nodes[e["to_node_id"]]), sweep, CLEARANCE_MM
        )
    }
    assert _pruned(moving) == expected


def test_a_raised_object_still_blocks_where_it_stands():
    grounded = second(authored.endless(), world(thing("object:lifted", CUBE, 4_000, -4_000)))
    lifted = second(
        authored.endless(), world(thing("object:lifted", CUBE, 4_000, -4_000, y_mm=500))
    )
    assert _pruned(lifted) == _pruned(grounded) != set()


@GROUNDS
def test_an_ordinary_world_prunes_exactly_what_the_first_composition_pruned(area):
    version = world(
        thing("object:post", PILLAR, -4_000, 1_000),
        thing("object:block", CUBE, 5_000, -3_000),
    )
    old, new = first(area, version), second(area, version)
    lattice_edges = {
        e["edge_id"] for e in new["navigation"]["edges"] if "place:" not in e["edge_id"]
    }
    assert lattice_edges == {e["edge_id"] for e in old["navigation"]["edges"]}
    assert [n for n in new["navigation"]["nodes"] if not n["node_id"].startswith("place:")] == (
        old["navigation"]["nodes"]
    )


def test_places_keep_a_standing_spacing_from_every_other_place():
    # Two cushions side by side: the second one's places that would stand inside the first one's
    # are dropped, and the rest are kept a standing spacing apart.
    version = world(thing("object:second", PLATE, 4_000, 5_000))
    document = second(authored.endless(), version)
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    places = [nodes[p] for t in document["targets"] for p in t["place_node_ids"]]
    assert len(places) == 3
    for index, a in enumerate(places):
        for b in places[index + 1 :]:
            assert math.dist(a, b) >= STANDING.spacing_mm


def test_a_bigger_plate_seats_more_people_and_a_block_seats_one_at_each_face():
    plate = next(r for r in authored.REGISTRY.values() if r["asset_key"] == "cc0.marker-plate")
    cube = next(r for r in authored.REGISTRY.values() if r["asset_key"] == "cc0.marker-cube")
    one = _UsableObject(thing("object:a", PLATE, 0, 0), plate, (0, 0), (500, 500))
    three = _UsableObject(
        thing("object:b", PLATE, 0, 0, scale=2_000), plate, (0, 0), (1_000, 1_000)
    )
    block = _UsableObject(thing("object:c", CUBE, 0, 0), cube, (0, 0), (250, 250))
    assert destination_places(one, STANDING, CLEARANCE_MM) == [(-350, 0), (350, 0)]
    assert destination_places(three, STANDING, CLEARANCE_MM) == [(-700, 0), (0, 0), (700, 0)]
    out = 250 + CLEARANCE_MM + STANDING.radius_mm
    assert destination_places(block, STANDING, CLEARANCE_MM) == [
        (0, -out),
        (out, 0),
        (0, out),
        (-out, 0),
    ]


def _tampered(document, change):
    changed = change(document)
    changed["document_sha256"] = input_sha256(changed)
    return changed


def test_an_input_cannot_seat_two_people_inside_one_another():
    document = second(authored.endless(), world())
    target = document["targets"][0]

    def squeeze(value):
        value = {**value, "navigation": {**value["navigation"]}}
        nodes = [dict(n) for n in value["navigation"]["nodes"]]
        for node in nodes:
            if node["node_id"] == target["place_node_ids"][1]:
                first_place = next(n for n in nodes if n["node_id"] == target["place_node_ids"][0])
                node["position_mm"] = [
                    first_place["position_mm"][0] + 300,
                    first_place["position_mm"][1],
                ]
        value["navigation"]["nodes"] = nodes
        value["navigation"]["edges"] = [
            e
            for e in value["navigation"]["edges"]
            if target["place_node_ids"][1] not in e["edge_id"]
        ]
        return value

    with pytest.raises(ValueError, match="standing spacing"):
        validate_society_input(_tampered(document, squeeze))


@pytest.mark.parametrize(("reason", "accepted"), [(OFF_GROUND, True), ("because_i_said_so", False)])
def test_a_local_record_carries_only_a_reason_its_profile_knows(reason, accepted):
    moving = thing("object:slider", CUBE, -8_000, -8_000, behaviour=MOTION)
    document = second(authored.endless(), world(moving))

    def relabel(value):
        records = [dict(r, reason=reason) for r in value["unavailable_affordances"]]
        return {**value, "unavailable_affordances": records}

    changed = _tampered(document, relabel)
    if accepted:
        validate_society_input(changed)
    else:
        with pytest.raises(ValueError, match="reason mismatch"):
            validate_society_input(changed)


def test_the_first_profile_never_learned_the_second_profile_reasons():
    document = first(authored.endless(), world())

    def claim(value):
        records = [
            {
                "target_id": f"authored:{value['version_id']}:object:slider:visit",
                "subject_id": f"authored:{value['version_id']}:object:slider",
                "object_id": "object:slider",
                "version_id": value["version_id"],
                "affordance": "visit",
                "reason": MOVES,
            }
        ]
        return {**value, "unavailable_affordances": records}

    with pytest.raises(ValueError, match="reason mismatch"):
        validate_society_input(_tampered(document, claim))


def test_a_society_moves_forward_to_the_second_profile_and_never_back():
    version = world()
    old = first(authored.endless(), version)
    new = second(authored.endless(), version, input_seq=2)
    validate_input_successor(old, new)
    older = first(authored.endless(), version)
    older = _tampered(older, lambda value: {**value, "input_seq": 3})
    with pytest.raises(ValueError, match="moved backwards"):
        validate_input_successor(new, older)
