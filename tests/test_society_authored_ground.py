"""The saved-world projection itself: what it reads, what it refuses and what it never invents."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, replace

import pytest
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.assets import reviewed_assets
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.objects import (
    AuthoredObject,
    ElementOverride,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
)
from exulanica.world.photo_point_maps import (
    PLACEABLE_RUNG,
    POINT_MAP_CONTAINER,
    PointMapInstance,
    PointMapModel,
    PointMapSourceBinding,
)
from exulanica.world.society_authored_ground import (
    DECLARED_HALF_EXTENT_MM,
    GROUND_PROFILE,
    LATTICE_MM,
    SocietyGround,
    WalkableArea,
    authored_ground_from_snapshot,
    build_authored_ground_society_input,
    ground_navigation,
)
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.society_input_policy import AUTHORED_GROUND_INPUT, UNREACHABLE
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    input_sha256,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.starter import (
    AUTHORED_GROUND_V1_HALF_WIDTH_MM,
    AUTHORED_GROUND_V1_MODULE_VERSION,
    AUTHORED_GROUND_V1_STREAMING_KEY,
    AUTHORED_SPAWN_X_MM,
    AUTHORED_SPAWN_Z_MM,
    _authored_starter_candidate,
    authored_starter_candidate,
)

SNAPSHOT = uuid.UUID("3f8a2c14-0b6e-4f41-9a1a-0d0d5c5f0001")
VERSION = uuid.UUID("3f8a2c14-0b6e-4f41-9a1a-0d0d5c5f0002")
WORLD = "world:authored:3f8a2c14-0b6e-4f41-9a1a-0d0d5c5f0003"
REGISTRY = reviewed_affordance_registry()
PLATE = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-plate")
PILLAR = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-pillar")


def bounded(half_width_mm: int = 12_000, half_depth_mm: int | None = None) -> WalkableArea:
    """The area a bounded ground states, read from the ground."""
    depth = half_width_mm if half_depth_mm is None else half_depth_mm
    return WalkableArea("ground", 0, 0, half_width_mm, depth)


def ground(**changes) -> SocietyGround:
    base = SocietyGround(
        world_id=WORLD,
        snapshot_id=SNAPSHOT,
        snapshot_sha256="b" * 64,
        region_id="region:starter",
        element_id="element:starter-ground",
        module_key="region.authored-ground",
        module_version=1,
        ground_kind="flat",
        elevation_mm=0,
        area=bounded(),
        arrival_x_mm=AUTHORED_SPAWN_X_MM,
        arrival_z_mm=AUTHORED_SPAWN_Z_MM,
    )
    return replace(base, **changes)


def endless() -> SocietyGround:
    """A ground module that states no edge, and the area the society declares on it."""
    return ground(
        module_version=2,
        ground_kind="endless",
        area=WalkableArea("declared", 0, 0, DECLARED_HALF_EXTENT_MM, DECLARED_HALF_EXTENT_MM),
    )


def version(
    *objects: AuthoredObject, overrides=(), invalidated=False, point_maps=()
) -> AlternateVersion:
    return AlternateVersion(
        version_id=VERSION,
        world_id=WORLD,
        source_snapshot_id=SNAPSHOT,
        parent_version_id=None,
        title="A world of my own",
        style_version_id=None,
        # The state token covers every part of the authored delta, placed estimates included,
        # exactly as the object repository computes it.
        state_sha256=delta_sha256(
            objects=objects,
            element_overrides=overrides,
            environment_instances=(),
            point_map_instances=point_maps,
        ),
        edit_seq=len(objects) + len(point_maps),
        source_invalidated=invalidated,
        created_by=uuid.uuid4(),
        created_at="2026-09-22T00:00:00+00:00",
        objects=objects,
        element_overrides=tuple(overrides),
        point_map_instances=tuple(point_maps),
    )


def estimate(instance_id: str, x_mm: int, z_mm: int) -> PointMapInstance:
    """A placed depth estimate from the account holder's own photograph, bound to its right."""
    return PointMapInstance(
        instance_id=instance_id,
        source=PointMapSourceBinding(
            entry_id=uuid.UUID(int=1),
            attachment_id=uuid.UUID(int=2),
            capture_id=uuid.UUID(int=3),
            source_sha256="1" * 64,
            authorization_id=uuid.UUID(int=4),
            authorization_evidence_sha256="2" * 64,
            screening_id=uuid.UUID(int=5),
            screening_receipt_sha256="3" * 64,
            right_id=uuid.UUID(int=6),
            right_receipt_sha256="4" * 64,
            model=PointMapModel("nvidia", "depth", "fixture-depth", None, "self-hosted"),
            artifact_id=uuid.UUID(int=7),
            point_map_sha256="5" * 64,
            byte_size=1024,
            container=POINT_MAP_CONTAINER,
            stage_version=1,
            rung=PLACEABLE_RUNG,
            declared_metric=False,
            declared_fov_y_microdegrees=60_000_000,
        ),
        region_id="region:starter",
        transform=Transform(x_mm=x_mm, y_mm=0, z_mm=z_mm, yaw_microradians=0, scale_milli=1000),
        origin=ObjectOrigin("authored", "personal"),
    )


def placed(object_id, asset, x_mm, z_mm, *, y_mm=0, region="region:starter", behaviour=None):
    return AuthoredObject(
        object_id=object_id,
        asset_sha256=asset.content_sha256,
        region_id=region,
        transform=Transform(x_mm=x_mm, y_mm=y_mm, z_mm=z_mm, yaw_microradians=0, scale_milli=1000),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=behaviour,
    )


def compose(area, world_version, *, input_seq=1, refs=()):
    return build_authored_ground_society_input(
        ground=area,
        version=world_version,
        input_seq=input_seq,
        dependency_refs=refs,
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=REGISTRY,
        segment_blocked=segment_blocked,
    )


def test_the_lattice_stays_a_clearance_inside_the_declared_ground():
    navigation = ground_navigation(ground())
    positions = [node["position_mm"] for node in navigation["nodes"]]
    limit = 12_000 - CLEARANCE_MM
    assert positions and all(abs(x) <= limit and abs(z) <= limit for x, z in positions)
    assert len(positions) == len({tuple(p) for p in positions})
    # One more step on either axis would leave the ground, which is what makes this the whole
    # walkable area rather than an arbitrary part of it.
    assert max(x for x, _ in positions) + LATTICE_MM > limit
    assert navigation["unavailable_reason"] is None


def test_an_area_smaller_than_the_clearance_says_so_rather_than_shrinking():
    narrow = ground(area=bounded(200))
    navigation = ground_navigation(narrow)
    assert navigation["nodes"] == [] and navigation["edges"] == []
    assert navigation["unavailable_reason"] == "walkable_area_smaller_than_clearance"
    document = compose(narrow, version(placed("object:cushion", PLATE, 0, 0)))
    assert document["availability"] == "unavailable"
    assert document["unavailable_reason"] == "walkable_area_smaller_than_clearance"
    assert document["targets"] == [] and document["unavailable_affordances"] == []
    assert document["navigation"]["nodes"] == []


def test_a_saved_world_states_the_ground_it_was_composed_from_and_no_geography():
    document = compose(ground(), version(placed("object:cushion", PLATE, 3_000, 5_000)))
    validate_society_input(document)
    assert document["profile"] == AUTHORED_GROUND_INPUT
    assert document["district_id"] == "authored:region:starter"
    assert document["base_artifact_sha256"] == "b" * 64
    assert document["district_document_sha256"] == ground().document_sha256
    assert set(document["frame"]) == {
        "name",
        "axis_order",
        "horizontal_unit",
        "altitude_reference",
    }
    assert ground().document()["profile"] == GROUND_PROFILE
    # A ground of another size is a different area, so its digest is a different digest and a
    # stored input composed against the old one cannot pass for one composed against the new.
    assert ground(area=bounded(24_000)).document_sha256 != ground().document_sha256


def test_the_same_world_composes_to_the_same_bytes_twice():
    world = version(placed("object:cushion", PLATE, 3_000, 5_000))
    assert compose(ground(), world) == compose(ground(), world)


@pytest.mark.parametrize(
    ("obj", "reason"),
    [
        (placed("object:hovering", PLATE, 0, 0, y_mm=500), "unsupported_object_transform"),
        (
            placed("object:elsewhere", PLATE, 0, 0, region="region:other"),
            "unregistered_object_region",
        ),
        (
            placed("object:animated", PLATE, 0, 0, behaviour=ObjectBehaviour("spin", 1, {})),
            "unsupported_active_behaviour",
        ),
    ],
)
def test_an_object_the_projection_cannot_place_makes_the_world_unavailable(obj, reason):
    document = compose(ground(), version(obj))
    assert document["availability"] == "unavailable"
    assert document["unavailable_reason"] == f"{reason}:{obj.object_id}"
    assert document["navigation"]["nodes"] == [] and document["targets"] == []


def test_an_object_out_of_reach_loses_its_own_activity_and_nothing_else():
    # A cushion in the strip between the last lattice row and the ground's edge: still in the
    # world, still drawn, and with no place to stand that can reach it.
    document = compose(
        ground(),
        version(
            placed("object:cushion", PLATE, 3_000, 5_000),
            placed("object:cornered", PLATE, 11_500, 11_500),
        ),
    )
    assert document["availability"] == "available"
    assert [t["object_id"] for t in document["targets"]] == ["object:cushion"]
    [unreachable] = document["unavailable_affordances"]
    assert unreachable["object_id"] == "object:cornered"
    assert unreachable["reason"] == UNREACHABLE
    assert unreachable["affordance"] == "rest" and "node_id" not in unreachable


def test_a_version_of_another_snapshot_or_an_invalidated_source_composes_nothing():
    drifted = compose(ground(snapshot_id=uuid.uuid4()), version(placed("o:a", PLATE, 0, 0)))
    assert drifted["unavailable_reason"] == "authored_ground_snapshot_mismatch"
    invalidated = compose(ground(), version(placed("o:a", PLATE, 0, 0), invalidated=True))
    assert invalidated["unavailable_reason"] == "authored_source_invalidated"
    overridden = compose(
        ground(),
        version(placed("o:a", PLATE, 0, 0), overrides=(ElementOverride("element:x", True),)),
    )
    assert overridden["unavailable_reason"] == "unsupported_structural_overrides"
    for document in (drifted, invalidated, overridden):
        assert document["navigation"]["nodes"] == []
        assert document["targets"] == [] and document["unavailable_affordances"] == []


def test_a_solid_object_takes_away_the_place_it_stands_in():
    on_a_node = compose(ground(), version(placed("object:post", PILLAR, 4_000, 4_000)))
    empty = ground_navigation(ground())
    assert len(on_a_node["navigation"]["nodes"]) == len(empty["nodes"]) - 1
    assert "ground:+00004000:+00004000" not in {
        node["node_id"] for node in on_a_node["navigation"]["nodes"]
    }
    # Nobody can stand within reach of it any more, so its own activity is the one that goes.
    assert on_a_node["targets"] == []
    assert [row["object_id"] for row in on_a_node["unavailable_affordances"]] == ["object:post"]


def test_a_composed_world_refuses_a_district_shaped_claim():
    document = compose(ground(), version(placed("object:cushion", PLATE, 3_000, 5_000)))
    document["frame"]["name"] = "flatiron-local-mm"
    with pytest.raises(ValueError, match="unsupported frame"):
        validate_society_input(document)


def test_a_world_holding_a_placed_photo_estimate_composes_and_the_estimate_is_not_ground():
    cushion = placed("object:cushion", PLATE, 3_000, 5_000)
    # Placed right where the cushion's access node is, so if the estimate were read as an
    # obstacle or as somewhere to stand, the lattice or the target would move.
    with_estimate = version(cushion, point_maps=(estimate("point-map:kitchen", 2_000, 4_000),))
    without = version(cushion)
    # The estimate really is part of the state token, so this test cannot pass by the estimate
    # being dropped before the digest is taken.
    assert with_estimate.state_sha256 != without.state_sha256
    document = compose(ground(), with_estimate)
    assert document["availability"] == "available"
    assert document["authored_state"]["delta_sha256"] == with_estimate.state_sha256
    # A depth estimate is personal evidence placed in the world. It is drawn; it is not a floor,
    # a wall or an activity, so the society's area and targets are exactly what they were.
    reference = compose(ground(), without)
    assert document["navigation"] == reference["navigation"]
    assert document["targets"] == reference["targets"]


def _read(candidate) -> SocietyGround:
    return authored_ground_from_snapshot(
        world_id=WORLD,
        snapshot_id=SNAPSHOT,
        snapshot_sha256="b" * 64,
        composer_key=candidate.composer_key,
        composer_version=candidate.composer_version,
        topology=candidate.topology,
        placement=candidate.placement,
    )


def _v1_candidate():
    """A starter written before the ground module stopped stating an edge."""
    return _authored_starter_candidate(
        WORLD,
        module_version=AUTHORED_GROUND_V1_MODULE_VERSION,
        streaming_key=AUTHORED_GROUND_V1_STREAMING_KEY,
    )


def test_a_bounded_ground_is_read_and_an_endless_one_is_declared_for():
    old = _read(_v1_candidate())
    new = _read(authored_starter_candidate(WORLD))
    assert (old.ground_kind, old.area.source) == ("flat", "ground")
    assert old.area.half_width_mm == AUTHORED_GROUND_V1_HALF_WIDTH_MM
    assert (new.ground_kind, new.area.source) == ("endless", "declared")
    assert new.area.half_width_mm == DECLARED_HALF_EXTENT_MM
    # An endless ground's descriptor carries no ground extent. The only extent in it is the
    # society's, and it says the society declared it.
    descriptor = new.document()
    assert "half_width_mm" not in descriptor and "half_depth_mm" not in descriptor
    assert descriptor["ground_kind"] == "endless"
    assert descriptor["walkable_area"]["source"] == "declared"
    assert old.document_sha256 != new.document_sha256


def test_an_old_and_a_new_starter_give_a_society_the_same_lattice():
    cushion = version(placed("object:cushion", PLATE, 3_000, 5_000))
    old = compose(_read(_v1_candidate()), cushion)
    new = compose(_read(authored_starter_candidate(WORLD)), cushion)
    for document in (old, new):
        assert len(document["navigation"]["nodes"]) == 121
        assert len(document["navigation"]["edges"]) == 220
        [target] = document["targets"]
        node = next(n for n in document["navigation"]["nodes"] if n["node_id"] == target["node_id"])
        # 1,000 mm east and 1,000 mm south: 1,414 mm, inside the 1,500 mm reviewed reach.
        dx, dz = node["position_mm"][0] - 3_000, node["position_mm"][1] - 5_000
        assert dx * dx + dz * dz == 2_000_000
    assert old["navigation"]["nodes"] == new["navigation"]["nodes"]
    assert old["targets"] == new["targets"]
    assert old["navigation"]["walkable_area"]["source"] == "ground"
    assert new["navigation"]["walkable_area"]["source"] == "declared"


def test_an_object_beyond_a_declared_area_is_unreachable_and_nothing_else_changes():
    # Forty metres out on an endless plane: in the world and drawn, outside the society's area.
    far = placed("object:far-cushion", PLATE, 40_000, 0)
    near = placed("object:cushion", PLATE, 3_000, 5_000)
    document = compose(endless(), version(near, far))
    assert document["availability"] == "available"
    assert [t["object_id"] for t in document["targets"]] == ["object:cushion"]
    [unreachable] = document["unavailable_affordances"]
    assert (unreachable["object_id"], unreachable["reason"]) == ("object:far-cushion", UNREACHABLE)
    assert len(document["navigation"]["nodes"]) == 121


def test_a_stored_input_cannot_route_outside_the_area_it_states():
    document = compose(endless(), version(placed("object:cushion", PLATE, 3_000, 5_000)))
    widened = copy.deepcopy(document)
    widened["navigation"]["walkable_area"]["half_width_mm"] = 6_000
    widened["document_sha256"] = input_sha256(widened)
    with pytest.raises(ValueError, match="outside the stated walkable area"):
        validate_society_input(widened)
    # And an edit may change what is in the area, never where the area is.
    moved = copy.deepcopy(document)
    moved["input_seq"] = 2
    moved["navigation"]["walkable_area"]["centre_mm"] = [2_000, 0]
    moved["navigation"]["walkable_area"]["half_width_mm"] = 14_000
    moved["document_sha256"] = input_sha256(moved)
    validate_society_input(moved)
    with pytest.raises(ValueError, match="immutable walkable_area"):
        validate_input_successor(document, moved)


def test_a_ground_kind_with_no_rule_is_refused_not_guessed_at(monkeypatch):
    import exulanica.world.starter as starter

    @dataclass(frozen=True)
    class TerracedGround:
        kind: str
        elevation_mm: int

    real = starter.authored_starter_scene

    def scene_with_an_unknown_ground(**kwargs):
        scene = real(**kwargs)
        region = replace(scene.region, ground=TerracedGround("terraced", 0))
        return replace(scene, region=region)

    monkeypatch.setattr(starter, "authored_starter_scene", scene_with_an_unknown_ground)
    with pytest.raises(InvalidStructuralData, match="no rule for an authored ground"):
        _read(authored_starter_candidate(WORLD))
