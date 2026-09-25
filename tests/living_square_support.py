"""The small square in a starter world, composed and advanced in memory, for society tests.

A person standing where a starter world puts them asks for the small square; its objects stand
where the arrangement's own layout puts them (``exulanica.world.arrangements.lay_out``), and the
society composes the world as the runtime does, under the newest saved-world profile. Nothing here
reads a database: the planner is driven minute by minute exactly as a step drives it.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.arrangements import arrangement_catalog, lay_out
from exulanica.world.assets import reviewed_assets
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import (
    AUTHORED_GROUND_POPULATION,
    LATTICE_MM,
    StandingPolicy,
    build_authored_ground_society_input_v2,
    build_authored_ground_society_input_v3,
)
from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.society_planner import advance_purposeful_society, initial_purposeful_society
from exulanica.world.starter import AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Z_MM
from scripts.measure_living_world_pace import seeds

import test_society_authored_ground as authored

#: The seeds the living-square record judges: the living-world pace record's twelve, the browser's
#: own first, read from the script that states them.
JUDGED_SEEDS = tuple(seeds())
#: Seeds for developing and testing the routine, disjoint from the judged ones, so the judged
#: measurement is taken once on seeds the routine was never tuned on.
DEVELOPMENT_SEEDS = tuple(
    hashlib.sha256(f"exulanica.living-square/v1/development/{index}".encode()).hexdigest()
    for index in range(12)
)
#: A person standing where a starter world puts them, facing its centre (-z): half a turn.
FACING_THE_CENTRE = 3_141_593
REGISTRY = reviewed_affordance_registry()
POLICY = load_routine_model().policy
STANDING = StandingPolicy(POLICY["standing_spacing_mm"], POLICY["standing_radius_mm"])
SOCIETY = uuid.uuid5(authored.VERSION, "exulanica-society/v1")


def square_objects() -> tuple[AuthoredObject, ...]:
    """The small square's objects as apply adds them, in front of the arrival point."""
    square = arrangement_catalog().by_key()["small_square"]
    layout = lay_out(
        square,
        viewer_x_mm=AUTHORED_SPAWN_X_MM,
        viewer_z_mm=AUTHORED_SPAWN_Z_MM,
        viewer_yaw_microradians=FACING_THE_CENTRE,
        spacing_mm=LATTICE_MM,
    )
    assets = {asset.asset_key: asset for asset in reviewed_assets()}
    # Named as apply names them in a starter whose first edit they are (``apply_arrangement``), so
    # a run here and a run through the routes choose among the same targets in the same order.
    return tuple(
        AuthoredObject(
            object_id=f"{square.key}-1-{index}-{placed.placement.kind.key}",
            asset_sha256=assets[placed.placement.kind.asset_key].content_sha256,
            region_id="region:starter",
            transform=Transform(
                placed.centre[0], 0, placed.centre[1], placed.yaw_microradians, 1000
            ),
            origin=ObjectOrigin("authored", "fictional"),
        )
        for index, placed in enumerate(layout.objects, 1)
    )


def version(objects: tuple[AuthoredObject, ...], edit_seq: int | None = None) -> AlternateVersion:
    """The version holding ``objects``, at ``edit_seq`` edits, one per object unless stated."""
    return AlternateVersion(
        version_id=authored.VERSION,
        world_id=authored.WORLD,
        source_snapshot_id=authored.SNAPSHOT,
        parent_version_id=None,
        title="A small square",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=objects, element_overrides=(), environment_instances=(), point_map_instances=()
        ),
        edit_seq=len(objects) if edit_seq is None else edit_seq,
        source_invalidated=False,
        created_by=uuid.UUID(int=1),
        created_at="2026-09-25T00:00:00+00:00",
        objects=objects,
        element_overrides=(),
        environment_instances=(),
    )


def compose(
    objects: tuple[AuthoredObject, ...],
    *,
    input_seq: int = 1,
    v2: bool = False,
    edit_seq: int | None = None,
) -> dict:
    """A saved world's input over the starter's endless ground, as the runtime composes it.

    ``edit_seq`` is how many edits the version has had, one per object unless an edit moved one.
    """
    build = build_authored_ground_society_input_v2 if v2 else build_authored_ground_society_input_v3
    return build(
        ground=authored.endless(),
        version=version(objects, edit_seq),
        input_seq=input_seq,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=REGISTRY,
        segment_blocked=segment_blocked,
        standing=STANDING,
    )


def run(seed: str, ticks: int, document: dict | None = None) -> list[dict[str, Any]]:
    """Every state of a square society from genesis through ``ticks`` minutes."""
    document = compose(square_objects()) if document is None else document
    state = initial_purposeful_society(
        SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
    )
    states = [state]
    for _ in range(ticks):
        state, _events = advance_purposeful_society(state, seed, [document])
        states.append(state)
    return states


def digest(state: dict) -> str:
    return society_state_sha256(state)
