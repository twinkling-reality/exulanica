"""The worlds a workspace holds, each with its kind, and the policy that says how many it may hold.

Every route that reads or changes a world requires a ``world_id``; this is where a caller learns
which ids there are. The list comes from the registry (:mod:`exulanica.world.worlds`), oldest
first, and never from a fixed id. The policy is returned beside it so a client can say how many
worlds of a kind the workspace may create without restating the number.

A world is created by the path that builds it, which is where the count policy is checked: an
authored starter (``POST /world-entries/starter``), or the personal-source world composed from the
account holder's reviewed photographs by ``/worlds/personal-source`` below. That pair is a read
that says whether composing now would make the world, bring it up to date, only need a saved
entry, or add newly reviewed photographs to the made world, with a preview of what adding them
does, or why none of these, and a write that does exactly what the read showed or refuses by name.
The rules for which photographs and which regions, and the one writer, are
:mod:`exulanica.world.personal_composition`.
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
from exulanica.graph.personal_sources import personal_sources
from exulanica.world.personal_composition import (
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


PersonalWorldAction = Literal["create_world", "update_world", "save_entry", "add_photographs"]


class StaysBehindView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The kind of row, by the subject the edit-kind registry names.
    kind: str
    #: Why it stays only in the previous version.
    reason: str
    count: int


class PersonalWorldAdditionCountsView(BaseModel):
    """What adding the photographs does, in counts; the sentences say the same in words."""

    model_config = ConfigDict(extra="forbid")

    photographs_added: int
    photographs_joining_places: int
    #: Places already in the world that take in photographs.
    places_growing: int
    new_places: int
    photographs_in_new_places: int
    #: Newly reviewed photographs no live scene group holds.
    left_out_in_no_place: int
    #: Newly reviewed photographs whose place holds photographs of several places of the world.
    left_out_between_places: int
    #: Photographs the world was made with that it no longer shows, kept in their places.
    kept_not_allowed: int
    #: Photographs the world was made with that no live scene group holds, kept where placed.
    kept_in_no_place: int
    #: Rows carried into the new version that are drawn, by subject.
    carried: dict[str, int]
    #: Removals carried as removals.
    carried_removals: int
    #: Places whose appearance the saved world sets, which carries with the saved appearance.
    region_appearances: int
    avatar_revisions: int
    stays_behind: list[StaysBehindView]
    #: Whether the version's inhabitants, away, and their history stay in the previous version.
    society_staying: bool
    #: Changes Take back still reaches after adding, which is all of them or none.
    changes_carried: int


class PersonalWorldPreviewView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The SHA-256 of this preview with every base it was read from; the write takes it back.
    preview_sha256: str
    #: Written for the person who asked; a client shows them as they are, in order.
    sentences: list[str]
    counts: PersonalWorldAdditionCountsView


class PersonalWorldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What composing now would do; null when it is refused.
    action: PersonalWorldAction | None
    refusal: RefusalView | None
    #: The personal-source world, when the workspace holds exactly one.
    world_id: str | None
    #: The saved world that names that world, when one does.
    saved_entry_id: uuid.UUID | None
    photographs: PersonalPhotographsView
    #: How many regions the topology would have, one per place.
    regions: int
    #: The digest composing now would register, which the write takes back; null with nothing to
    #: compose.
    topology_digest: str | None
    current_topology_digest: str | None
    #: What adding the photographs does, for ``add_photographs`` only.
    preview: PersonalWorldPreviewView | None


class ComposePersonalWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology_digest: Annotated[str, Field(min_length=1, max_length=256)]
    #: The preview the person confirmed; required to add photographs, refused for anything else.
    preview_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")] | None = None


class ComposedPersonalWorldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: PersonalWorldAction
    #: The world every later request names.
    world_id: str
    topology_digest: str
    style_version_id: uuid.UUID
    saved_entry_id: uuid.UUID | None


def _personal_world_view(plan: PersonalWorldPlan) -> PersonalWorldView:
    composition = plan.composition
    preview = plan.preview
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
        preview=None
        if preview is None
        else PersonalWorldPreviewView(
            preview_sha256=preview.sha256,
            sentences=list(preview.sentences),
            counts=PersonalWorldAdditionCountsView.model_validate(preview.counts),
        ),
    )


@router.get(
    "/personal-source",
    response_model=PersonalWorldView,
    summary="Whether a world can be made, or photographs added to it, from your reviewed "
    "photographs now; writes nothing.",
)
def personal_source_world(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> PersonalWorldView:
    sources = personal_sources(
        connection, session.workspace_id, reviewed_for=session.actor, store=services.store
    )
    return _personal_world_view(
        personal_world_plan(connection, session.workspace_id, sources, store=services.store)
    )


@router.post(
    "/personal-source",
    response_model=ComposedPersonalWorldView,
    summary="Compose your reviewed photographs into your personal-source world, or add them to "
    "it, as last read.",
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
            sources = personal_sources(
                connection, session.workspace_id, reviewed_for=session.actor, store=services.store
            )
            plan, composed = compose_personal_world(
                connection,
                session.workspace_id,
                sources,
                expected_topology_digest=body.topology_digest,
                expected_preview_sha256=body.preview_sha256,
                actor=session.actor,
                store=services.store,
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
