"""Things placed in an authored version by their kind: place, move, remove and undo, and the look
each thing of a version wears.

A placed thing names a shipped thing kind by key, version and digest, or a kind its workspace keeps
(a creature drafted from a person's words) by the digest of the kind's document alone, and stands
in a region of the version's source snapshot at its kind's own size
(:mod:`exulanica.world.placed_things`). A thing whose workspace kind is gone (no longer held, or
erased after it was placed) is moved nowhere (410 ``thing_kind_erased``) and is removed as any
thing is. Every edit names the version state it was made against and runs in
:func:`exulanica.api.world_edit.commit_edit`, like every other authored edit, and answers with the
whole version. ``GET .../thing-looks`` answers the latest look chosen for each thing of the
version (:mod:`exulanica.world.thing_looks`), never cached.

``GET .../society/things/{thing_id}`` answers one thing or being of the version's society of
things as its card (``exulanica.thing-card/v1``, :mod:`exulanica.api.thing_card`), by the id the
society gives it, which is never an author's placed id (the move and remove routes above take
those); ``POST .../society/things/{thing_id}/look`` records the world's owner's choice of a look
made for its body and answers the card again, its minute and state digest those of the same
read, so a reader sees that only the look changed. Both answer 424 by name where the society's
input names something no longer available, as the society read does.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.routes.society_models import _society
from exulanica.api.thing_card import choose_look, thing_card
from exulanica.api.world_edit import (
    BaseStateBody,
    EntryBoundEditBody,
    ReadObjects,
    WriteObjects,
    commit_edit,
)
from exulanica.api.world_scope import WorldId
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.objects import MAX_YAW_MICRORADIANS, ObjectOrigin, Transform
from exulanica.world.placed_things import (
    UNSCALED_MILLI,
    ThingPlacement,
    named_kind,
    workspace_kind_reference,
)
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.thing_looks import ThingLookRefused, look_choices

router = APIRouter(prefix="/world", tags=["world"])


class ThingKindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    version: StrictInt = Field(ge=1, le=10_000)
    #: The kind's digest as the caller read it. Left out, the shipped version's digest is stored;
    #: stated, it must be that digest.
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class WorkspaceKindBody(BaseModel):
    """A kind the placing workspace keeps, by the SHA-256 of its document alone, never by a key a
    person's words made."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["workspace"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ThingPoseBody(BaseModel):
    """Where a thing stands, region-local: no scale, since a thing stands at its kind's size."""

    model_config = ConfigDict(extra="forbid")

    x_mm: StrictInt
    y_mm: StrictInt
    z_mm: StrictInt
    yaw_microradians: StrictInt = Field(ge=0, le=MAX_YAW_MICRORADIANS)

    def domain(self) -> Transform:
        return Transform(self.x_mm, self.y_mm, self.z_mm, self.yaw_microradians, UNSCALED_MILLI)


class AddThingBody(EntryBoundEditBody):
    thing_id: str = Field(min_length=1, max_length=200)
    kind: ThingKindBody | WorkspaceKindBody
    region_id: str = Field(min_length=1, max_length=500)
    pose: ThingPoseBody
    origin_role: Literal["fictional", "personal"]


class MoveThingBody(EntryBoundEditBody):
    pose: ThingPoseBody


@router.post(
    "/versions/{version_id}/things",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Place a thing by its kind, shipped or its workspace's own, against the current state.",
)
def add_thing(
    version_id: Annotated[uuid.UUID, Path()],
    body: AddThingBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    def place() -> AlternateVersion:
        placement = ThingPlacement(
            thing_id=body.thing_id,
            kind=(
                workspace_kind_reference(body.kind.sha256)
                if isinstance(body.kind, WorkspaceKindBody)
                else named_kind(body.kind.kind, body.kind.version, body.kind.sha256)
            ),
            region_id=body.region_id,
            transform=body.pose.domain(),
            origin=ObjectOrigin("authored", body.origin_role),
        )
        return repository.add_thing(
            version_id, placement, base_state_sha256=body.base_state_sha256, actor=session.actor
        )

    return commit_edit(request, repository, version_id, body, place)


@router.post(
    "/versions/{version_id}/things/{thing_id}/move",
    response_model=AlternateVersionView,
    summary="Move a placed thing to another pose in its region, its kind unchanged.",
)
def move_thing(
    version_id: Annotated[uuid.UUID, Path()],
    thing_id: Annotated[str, Path(max_length=200)],
    body: MoveThingBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.move_thing(
            version_id,
            thing_id,
            body.pose.domain(),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/things/{thing_id}/remove",
    response_model=AlternateVersionView,
    summary="Store the removal of a placed thing.",
)
def remove_thing(
    version_id: Annotated[uuid.UUID, Path()],
    thing_id: Annotated[str, Path(max_length=200)],
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.remove_thing(
            version_id, thing_id, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.post(
    "/versions/{version_id}/things/undo",
    response_model=AlternateVersionView,
    summary="Undo the newest authored edit from stored history.",
)
def undo_thing_edit(
    version_id: Annotated[uuid.UUID, Path()],
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.undo(
            version_id, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.get(
    "/versions/{version_id}/thing-looks",
    summary="The look each thing of a version wears: the latest choice per thing.",
)
def thing_looks(version_id: Annotated[uuid.UUID, Path()], repository: ReadObjects) -> JSONResponse:
    return JSONResponse(
        content=look_choices(
            repository.connection, repository.workspace_id, repository.world_id, version_id
        ),
        headers={"Cache-Control": "private, no-store"},
    )


class LookChoiceBody(BaseModel):
    """A shipped look, by key, version and digest, for the thing to wear."""

    model_config = ConfigDict(extra="forbid")

    look: str = Field(pattern=r"^[a-z][a-z0-9-]{0,47}$")
    version: StrictInt = Field(ge=1, le=10_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkspaceLookBody(BaseModel):
    """A look the workspace keeps, by the digest of its document alone."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["workspace"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ThingLookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    look: LookChoiceBody | WorkspaceLookBody


def _unavailable(exc: UnavailableSocietyInput) -> JSONResponse:
    return JSONResponse(
        status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
    )


@router.get(
    "/versions/{version_id}/society/things/{thing_id}",
    summary="One thing or being of the version's society of things, as its card shows it.",
)
def thing_card_read(
    version_id: Annotated[uuid.UUID, Path()],
    thing_id: Annotated[uuid.UUID, Path()],
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> JSONResponse:
    society = _society(connection, session, request, world_id)
    try:
        card = thing_card(
            connection,
            get_services(request),
            society,
            workspace_id=session.workspace_id,
            world_id=world_id,
            version_id=version_id,
            thing_id=thing_id,
            reader=session.actor,
        )
    except UnavailableSocietyInput as exc:
        return _unavailable(exc)
    return JSONResponse(content=card, headers={"Cache-Control": "private, no-store"})


@router.post(
    "/versions/{version_id}/society/things/{thing_id}/look",
    summary="The world's owner chooses a shipped look for a thing; answers its card.",
)
def thing_look_choose(
    version_id: Annotated[uuid.UUID, Path()],
    thing_id: Annotated[uuid.UUID, Path()],
    body: ThingLookBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> JSONResponse:
    society = _society(connection, session, request, world_id)
    try:
        with connection.transaction():
            card = choose_look(
                connection,
                get_services(request),
                society,
                workspace_id=session.workspace_id,
                world_id=world_id,
                version_id=version_id,
                thing_id=thing_id,
                look=body.look.model_dump(),
                actor=session.actor,
            )
    except ThingLookRefused as exc:
        return JSONResponse(status_code=422, content={"code": exc.code, "detail": exc.detail})
    except UnavailableSocietyInput as exc:
        return _unavailable(exc)
    return JSONResponse(content=card, headers={"Cache-Control": "private, no-store"})
