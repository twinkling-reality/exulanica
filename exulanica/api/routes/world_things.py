"""Things placed in an authored version by their kind: place, move, remove and undo.

A placed thing names a shipped thing kind by key, version and digest and stands in a region of the
version's source snapshot at its kind's own size (:mod:`exulanica.world.placed_things`). Every edit
names the version state it was made against and runs in
:func:`exulanica.api.world_edit.commit_edit`, like every other authored edit, and answers with the
whole version.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession
from exulanica.api.world_edit import BaseStateBody, EntryBoundEditBody, WriteObjects, commit_edit
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.objects import MAX_YAW_MICRORADIANS, ObjectOrigin, Transform
from exulanica.world.placed_things import UNSCALED_MILLI, ThingPlacement, named_kind

router = APIRouter(prefix="/world", tags=["world"])


class ThingKindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    version: StrictInt = Field(ge=1, le=10_000)
    #: The kind's digest as the caller read it. Left out, the shipped version's digest is stored;
    #: stated, it must be that digest.
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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
    kind: ThingKindBody
    region_id: str = Field(min_length=1, max_length=500)
    pose: ThingPoseBody
    origin_role: Literal["fictional", "personal"]


class MoveThingBody(EntryBoundEditBody):
    pose: ThingPoseBody


@router.post(
    "/versions/{version_id}/things",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Place a thing by its shipped kind against the current version state.",
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
            kind=named_kind(body.kind.kind, body.kind.version, body.kind.sha256),
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
