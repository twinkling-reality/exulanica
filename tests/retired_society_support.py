"""A stored society of a retired engine, for tests that hold what such a society still does.

No request creates a society with an engine the table marks not creatable
(``RetiredSocietyEngine``, ``society_engine_retired``), but a society stored before its engine was
retired still reads, advances, takes directed actions and replays. A test of that behaviour plants
one with the write its creation made (``SocietyRepository._create``), which is exactly the row and
first input a creation of it stored.
"""

from __future__ import annotations

import uuid
from typing import Any

from exulanica.selection.validation import Session
from exulanica.world.society_engines import society_engine
from exulanica.world.society_repository import SocietyRepository


def plant_retired_society(
    repository: SocietyRepository,
    version_id: uuid.UUID,
    *,
    place_id: uuid.UUID,
    region_id: str,
    seed: str,
    actor: uuid.UUID,
    profile: str,
    initial_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The society a creation of a now retired engine stored, as its snapshot."""
    assert not society_engine(profile).creatable, f"{profile} is created through create()"
    return repository._create(
        version_id,
        place_id=place_id,
        region_id=region_id,
        seed=seed,
        actor=actor,
        profile=profile,
        initial_input=initial_input,
    )


def create_or_plant(repository: SocietyRepository, version_id: uuid.UUID, **kwargs: Any) -> Any:
    """Create a society with a creatable engine, or plant a stored one of a retired engine."""
    if society_engine(kwargs.get("profile")).creatable:
        return repository.create(version_id, **kwargs)
    return plant_retired_society(repository, version_id, **kwargs)


def plant_in_saved_world(services: Any, world: dict[str, Any], profile: str) -> dict[str, Any]:
    """A stored society of a retired engine in a saved world, planted where bringing people in
    made it: the place and first input the server derives, and the world's own seed."""
    binding = world["binding"]
    workspace = world["workspace"]
    actor = world["session"].actor
    runtime = services.society_runtime
    session = Session(workspace_id=workspace, actor=actor)
    with services.database.session(workspace) as connection, connection.transaction():
        place_id = runtime.saved_world_place(connection, session, binding.version_id)
        document = runtime.initial_input(
            connection, session, binding.version_id, place_id, binding.region_id
        )
        repository = SocietyRepository(
            connection,
            workspace,
            world_id=binding.world_id,
            input_authorizer=lambda doc: runtime.authorize(connection, session, doc),
        )
        return plant_retired_society(
            repository,
            binding.version_id,
            place_id=place_id,
            region_id=binding.region_id,
            seed=services.society_seed(workspace, binding.world_id),
            actor=actor,
            profile=profile,
            initial_input=document,
        )
