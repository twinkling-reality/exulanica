"""Alternate world versions: list, create, open the first one, and read one.

A version refers to its source snapshot and stores its own additions, removals, transforms and
appearance, so the source reconstruction is never rewritten by what a person authors on top of it.
The edits themselves are :mod:`~exulanica.api.routes.world_objects`,
:mod:`~exulanica.api.routes.world_environments` and :mod:`~exulanica.api.routes.world_compositions`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final, Literal

import psycopg
from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.world_edit import ReadObjects, WriteObjects, object_problem
from exulanica.api.world_scope import WorldId
from exulanica.api.world_version_document import (
    AlternateVersionView,
    alternate_version_view,
    rendered_version,
)
from exulanica.world.bootstrap import bootstrap_world
from exulanica.world.edit_kinds import EditSubject
from exulanica.world.object_repository import StayReason

router = APIRouter(prefix="/world", tags=["world"])


class BootstrapWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_topology_digest: str = Field(min_length=1, max_length=256)
    title: str = Field(default="My alternate world", min_length=1, max_length=200)


class BootstrapWorldView(BaseModel):
    snapshot: Literal["applied", "reused"]
    snapshot_id: uuid.UUID
    regions: list[str]
    version: Literal["created", "reused"]
    version_id: uuid.UUID
    state_sha256: str


class LeftBehindView(BaseModel):
    """One of the parent's rows a branch did not copy, and why, as carrying it would say."""

    model_config = ConfigDict(extra="forbid")

    subject: EditSubject
    subject_id: str
    removed: bool
    reason: StayReason


class BranchedVersionView(AlternateVersionView):
    """The version a branch made, and each of its parent's rows it left out.

    A branch's rows are new placements, so a row whose source may no longer be written into a
    version (a withdrawn environment source, an ended depth right, a deleted photograph) stays in
    the parent only, and is named here. Empty for a version made from a snapshot.
    """

    left_behind: list[LeftBehindView]


#: What stops a branch because another write was in flight, with nothing written: a deadlock with a
#: search or training right's stop, which takes the asset read lock before its tombstone takes the
#: workspace lock (the branch takes them the other way round), or a serialization refusal. The
#: same request can be sent again; the code is the one the place-name decision routes answer.
_BUSY: Final = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)


class CreateVersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    source_snapshot_id: uuid.UUID | None = None
    parent_version_id: uuid.UUID | None = None
    style_version_id: uuid.UUID | None = None


@router.get(
    "/versions",
    response_model=list[AlternateVersionView],
    summary="Every alternate world version in this workspace, newest first.",
)
def alternate_versions(repository: ReadObjects, request: Request) -> list[AlternateVersionView]:
    store = get_services(request).store
    assets = {asset.content_sha256: asset for asset in repository.reviewed_assets(store)}
    return [alternate_version_view(version, assets) for version in repository.versions()]


@router.post(
    "/versions",
    response_model=BranchedVersionView,
    status_code=201,
    summary="Create an alternate version from a source snapshot or from another version.",
)
def create_alternate_version(
    body: CreateVersionBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | BranchedVersionView:
    try:
        branched = repository.branch_version(
            source_snapshot_id=body.source_snapshot_id,
            parent_version_id=body.parent_version_id,
            title=body.title,
            style_version_id=body.style_version_id,
            created_by=session.actor,
        )
    except _BUSY:
        return JSONResponse(
            status_code=409,
            content={
                "code": "busy",
                "detail": "another change was being written at that moment; try again",
            },
        )
    except Exception as exc:
        problem = object_problem(exc)
        if problem is None:
            raise
        return problem
    view = rendered_version(repository, branched.version, get_services(request).store)
    return BranchedVersionView(
        **dict(view),
        left_behind=[
            LeftBehindView(
                subject=part.subject,
                subject_id=part.subject_id,
                removed=part.removed,
                reason=part.reason,
            )
            for part in branched.left_behind
            if part.reason is not None
        ],
    )


@router.post(
    "/versions/bootstrap",
    response_model=BootstrapWorldView,
    summary="Open the first snapshot and alternate from the current composed sources.",
)
def bootstrap_alternate_version(
    body: BootstrapWorldBody,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response | BootstrapWorldView:
    try:
        return BootstrapWorldView(
            **bootstrap_world(
                connection,
                workspace_id=session.workspace_id,
                actor=session.actor,
                world_id=world_id,
                base_topology_digest=body.base_topology_digest,
                title=body.title,
            )
        )
    except Exception as exc:
        problem = object_problem(exc)
        if problem is None:
            raise
        return problem


@router.get(
    "/versions/{version_id}",
    response_model=AlternateVersionView,
    summary="One alternate version with its objects, overrides and edit history.",
)
def alternate_version(
    version_id: Annotated[uuid.UUID, Path()],
    repository: ReadObjects,
    request: Request,
) -> AlternateVersionView:
    return rendered_version(
        repository,
        repository.version(version_id, with_availability=False),
        get_services(request).store,
    )
