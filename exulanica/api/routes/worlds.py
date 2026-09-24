"""The worlds a workspace holds, each with its kind, and the policy that says how many it may hold.

Every route that reads or changes a world requires a ``world_id``; this is where a caller learns
which ids there are. The list comes from the registry (:mod:`exulanica.world.worlds`), oldest
first, and never from a fixed id. The policy is returned beside it so a client can say how many
worlds of a kind the workspace may create without restating the number.

A world is created by the path that builds it, which is where the count policy is checked: an
authored starter (``POST /world-entries/starter``), or the personal-source world composed from the
account holder's reviewed photographs by ``/worlds/personal-source`` below. That pair is a read
that says whether composing now would make the world, bring it up to date or only need a saved
entry, or why not, and a write that does exactly what the read showed or refuses by name. The rule
for which photographs, and the one writer, are :mod:`exulanica.world.personal_composition`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.graph.personal_sources import personal_composition
from exulanica.world.personal_composition import (
    PersonalComposition,
    PersonalWorldPlan,
    PersonalWorldRefused,
    compose_personal_world,
    personal_world_plan,
)
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.worlds import (
    WorldLimitReached,
    current_world_count_policy,
    workspace_worlds,
)

router = APIRouter(prefix="/worlds", tags=["world"])


class WorldCountPolicyView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    version: int
    sha256: str
    #: The most worlds of each kind one workspace may hold; null where the policy sets no limit.
    limits: dict[str, int | None]


class WorldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    kind: str
    created_at: dt.datetime
    created_by: uuid.UUID | None
    provenance: dict[str, JsonValue]


class WorldsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: WorldCountPolicyView
    worlds: list[WorldView]


@router.get(
    "",
    response_model=WorldsView,
    summary="Every world this workspace holds, with its kind, and how many of each it may hold.",
)
def worlds(connection: ReadOnlyConnection, session: CurrentSession) -> WorldsView:
    policy = current_world_count_policy()
    return WorldsView(
        policy=WorldCountPolicyView(
            policy_id=policy.policy_id,
            version=policy.version,
            sha256=policy.sha256,
            limits=dict(policy.limits),
        ),
        worlds=[
            WorldView(
                world_id=world.world_id,
                kind=world.kind,
                created_at=world.created_at,
                created_by=world.created_by,
                provenance=dict(world.provenance),
            )
            for world in workspace_worlds(connection, session.workspace_id)
        ],
    )


class RefusalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    #: Written for the person who asked; a client shows it as it is.
    detail: str


class PersonalPhotographsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Every photograph the account holder reviewed and may use in a world now.
    reviewed: int
    #: Of those, the ones composing would make source slots.
    composed: int
    #: Reviewed photographs in no live scene group, left out of the composition.
    outside_scene_groups: int


class PersonalWorldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What composing now would do; null when it is refused.
    action: Literal["create_world", "update_world", "save_entry"] | None
    refusal: RefusalView | None
    #: The personal-source world, when the workspace holds exactly one.
    world_id: str | None
    #: The saved world that names that world, when one does.
    saved_entry_id: uuid.UUID | None
    photographs: PersonalPhotographsView
    #: How many regions composing would give the topology, one per scene group.
    regions: int
    #: The digest composing now would register, which the write takes back; null with nothing to
    #: compose.
    topology_digest: str | None
    current_topology_digest: str | None


class ComposePersonalWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology_digest: Annotated[str, Field(min_length=1, max_length=256)]


class ComposedPersonalWorldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create_world", "update_world", "save_entry"]
    #: The world every later request names.
    world_id: str
    topology_digest: str
    style_version_id: uuid.UUID
    saved_entry_id: uuid.UUID | None


def _personal_world_view(
    composition: PersonalComposition, plan: PersonalWorldPlan
) -> PersonalWorldView:
    return PersonalWorldView(
        action=plan.action,
        refusal=None
        if plan.refusal is None
        else RefusalView(code=plan.refusal.code, detail=plan.refusal.detail),
        world_id=plan.world_id,
        saved_entry_id=plan.saved_entry_id,
        photographs=PersonalPhotographsView(
            reviewed=composition.reviewed,
            composed=composition.composed,
            outside_scene_groups=composition.outside_scene_groups,
        ),
        regions=len(composition.region_ids),
        topology_digest=plan.topology_digest,
        current_topology_digest=plan.current_topology_digest,
    )


@router.get(
    "/personal-source",
    response_model=PersonalWorldView,
    summary="Whether a world can be made or brought up to date from your reviewed photographs now.",
)
def personal_source_world(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> PersonalWorldView:
    composition = personal_composition(
        connection, session.workspace_id, reviewed_for=session.actor, store=services.store
    )
    return _personal_world_view(
        composition, personal_world_plan(connection, session.workspace_id, composition)
    )


@router.post(
    "/personal-source",
    response_model=ComposedPersonalWorldView,
    summary="Compose your reviewed photographs into your personal-source world, as last read.",
    responses={409: {"description": "Refused by name; nothing was written."}},
)
def compose_personal_source_world(
    body: ComposePersonalWorldBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> ComposedPersonalWorldView | JSONResponse:
    try:
        with connection.transaction():
            # Held from the read to the write, so the composition compared is the one composed.
            lock_workspace(connection, session.workspace_id)
            composition = personal_composition(
                connection, session.workspace_id, reviewed_for=session.actor, store=services.store
            )
            plan, composed = compose_personal_world(
                connection,
                session.workspace_id,
                composition,
                expected_topology_digest=body.topology_digest,
                actor=session.actor,
            )
    except PersonalWorldRefused as exc:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": exc.detail})
    except WorldLimitReached as exc:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})
    assert plan.action is not None
    return ComposedPersonalWorldView(
        action=plan.action,
        world_id=composed["world_id"],
        topology_digest=composed["topology_digest"],
        style_version_id=composed["style_version_id"],
        saved_entry_id=plan.saved_entry_id,
    )
