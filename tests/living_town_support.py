"""A generated town's society input, composed without a database, for the living town's tests.

The same path the runtime composes a town's input by (``society_runtime._authored_compose``): the
recipe's composer generates the world for an identity, the world's ground is read from its
snapshot, the records make the city place under a living routine, and the input is built over
it. Pure: no connection, no store and no model.
"""

from __future__ import annotations

import functools
import uuid
from typing import Any

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_living import current_routine, town_routine
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.world_recipes import town_recipe

#: The seed a town's society is made with in these tests: any lowercase SHA-256 text.
SEED = "5" * 64


def version_of(world_id: str, snapshot_id: uuid.UUID) -> AlternateVersion:
    """An authored version of the world with no edits, as a new generated world's first one."""
    empty = AlternateVersion(
        version_id=uuid.uuid5(uuid.NAMESPACE_URL, world_id),
        world_id=world_id,
        source_snapshot_id=snapshot_id,
        parent_version_id=None,
        title="town",
        style_version_id=None,
        state_sha256="0" * 64,
        edit_seq=0,
        source_invalidated=False,
        created_by=uuid.UUID(int=0),
        created_at="2026-09-29T00:00:00+00:00",
    )
    return AlternateVersion(
        **{
            **{field: getattr(empty, field) for field in empty.__slots__},
            "state_sha256": version_delta_sha256(empty),
        }
    )


@functools.cache
def town_input(
    recipe: str = "small_town",
    values: tuple[tuple[str, int], ...] = (),
    index: int = 0,
    *,
    living: bool = True,
) -> dict[str, Any]:
    """The first input of a society over one generated town: walking-surfaces-v2, carrying its
    living place, or with ``living`` false the walking-surfaces-v1 input the purposeful society
    reads. Cached per process; callers copy before changing it."""
    world_id = f"world:generated:living-town-{recipe}-{index}"
    composed = compose_generated_world(town_recipe(recipe, dict(values) or None), world_id)
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = town_routine() if living else current_routine()
    policy = routine.policy
    return build_walking_surfaces_input(
        ground=ground,
        version=version_of(world_id, snapshot_id),
        place=walking_surfaces_place(ground.place_id, composed.records, routine),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        living=routine if living else None,
    )
