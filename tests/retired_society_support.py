"""A stored society of a retired engine, for tests that hold what such a society still does.

No request creates a society with an engine the table marks not creatable
(``RetiredSocietyEngine``, ``society_engine_retired``), but a society stored before its engine was
retired still reads, advances, takes directed actions and replays. A test of that behaviour plants
one with the write its creation made (``SocietyRepository._create``), which is exactly the row and
first input a creation of it stored. A decision the social engine's retired proposal route stored
is planted the same way (:func:`plant_retired_decision`): the request it reserved and the receipt
it recorded, as those rows were written.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from exulanica.selection.validation import Session
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_decisions import REQUEST_PROFILE, seal, validate_decision_request
from exulanica.world.society_engines import society_engine
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_social import decision_context
from psycopg.types.json import Jsonb


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


def plant_retired_decision(
    decisions: SocietyDecisionRepository,
    version_id: uuid.UUID,
    *,
    request_id: uuid.UUID,
    subject_id: str,
    result: Mapping[str, Any] | None,
    provider_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A decision the social engine's retired proposal route stored, as a read returns it.

    That route reserved a v1 request over one cast member's context at the society's current
    minute, from the latest input, and recorded its answer in a later transaction, where the
    answer was checked and ``result`` is what it recorded. This writes the same request row and
    records the receipt through the repository's own receipt write; with no ``result``, the
    request alone, one the route reserved and never answered.
    """
    row = decisions._row(version_id)
    document = decisions.society._validated_inputs(row)[-1]
    context = decision_context(row["state"], document, subject_id)
    request = seal(
        {
            "profile": REQUEST_PROFILE,
            "request_id": str(request_id),
            "subject_id": subject_id,
            "branch_id": str(version_id),
            "base_tick": row["current_tick"],
            "base_state_sha256": row["state_sha256"],
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "context": context,
            "context_sha256": society_state_sha256(context),
            "provider_config": None if provider_config is None else dict(provider_config),
        }
    )
    validate_decision_request(request)
    decisions.connection.execute(
        "insert into world_society_decision_request("
        "workspace_id,society_id,request_id,subject_id,"
        "base_tick,input_seq,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            row["workspace_id"],
            row["society_id"],
            request_id,
            uuid.UUID(subject_id),
            row["current_tick"],
            document["input_seq"],
            Jsonb(request),
            request["document_sha256"],
        ),
    )
    if result is None:
        return {"request": request, "decision": None, "status": "in_progress"}
    return decisions._record_receipt(row, request, request_id, dict(result))
