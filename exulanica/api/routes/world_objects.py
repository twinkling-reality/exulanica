"""Authored objects in an alternate version: add, move, remove, give a behaviour, and undo.

An object names a reviewed asset by content digest, a region-local transform, the origin role the
person chose and optionally one reviewed behaviour with bounded parameters. Every edit names the
version state it was made against and runs in :func:`exulanica.api.world_edit.commit_edit`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request, Response
from pydantic import Field

from exulanica.api.dependencies import CurrentSession
from exulanica.api.world_edit import (
    BaseStateBody,
    BehaviourBody,
    EntryBoundEditBody,
    MoveObjectBody,
    TransformBody,
    WriteObjects,
    commit_edit,
)
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world import AuthoredObject, ObjectOrigin

router = APIRouter(prefix="/world", tags=["world"])


class AddObjectBody(EntryBoundEditBody):
    object_id: str = Field(min_length=1, max_length=200)
    #: By content digest, not by reviewed name. A key is a pointer that could be repointed; the
    #: digest is the bytes, and it is what the version's state digest covers.
    asset_sha256: str = Field(min_length=64, max_length=64)
    region_id: str = Field(min_length=1, max_length=500)
    transform: TransformBody
    #: The person chooses. Product direction is explicit that this surface asks rather than
    #: classifies, so there is no default and no inference from the asset.
    origin_role: Literal["fictional", "personal"]
    behaviour: BehaviourBody | None = None


class SetObjectBehaviourBody(EntryBoundEditBody):
    #: Required, and null means "take the behaviour away". A body that simply omitted it would
    #: otherwise be read as a clear the caller never asked for.
    behaviour: BehaviourBody | None


@router.post(
    "/versions/{version_id}/objects",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Add one authored object against an explicit base version state.",
)
def add_authored_object(
    version_id: Annotated[uuid.UUID, Path()],
    body: AddObjectBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    obj = AuthoredObject(
        object_id=body.object_id,
        asset_sha256=body.asset_sha256,
        region_id=body.region_id,
        transform=body.transform.domain(),
        origin=ObjectOrigin("authored", body.origin_role),
        behaviour=None if body.behaviour is None else body.behaviour.domain(),
    )
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.add_object(
            version_id, obj, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.post(
    "/versions/{version_id}/objects/{object_id}/move",
    response_model=AlternateVersionView,
    summary="Replace one authored object's region-local transform.",
)
def move_authored_object(
    version_id: Annotated[uuid.UUID, Path()],
    object_id: Annotated[str, Path(max_length=200)],
    body: MoveObjectBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.move_object(
            version_id,
            object_id,
            body.transform.domain(),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/objects/{object_id}/remove",
    response_model=AlternateVersionView,
    summary="Store a removal. POST rather than DELETE: this appends history, it destroys nothing.",
)
def remove_authored_object(
    version_id: Annotated[uuid.UUID, Path()],
    object_id: Annotated[str, Path(max_length=200)],
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
        lambda: repository.remove_object(
            version_id, object_id, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.post(
    "/versions/{version_id}/objects/{object_id}/behaviour",
    response_model=AlternateVersionView,
    summary="Give one authored object a reviewed behaviour, replace it, or take it away with null.",
)
def set_authored_object_behaviour(
    version_id: Annotated[uuid.UUID, Path()],
    object_id: Annotated[str, Path(max_length=200)],
    body: SetObjectBehaviourBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.set_object_behaviour(
            version_id,
            object_id,
            None if body.behaviour is None else body.behaviour.domain(),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/objects/undo",
    response_model=AlternateVersionView,
    summary="Reverse the newest object edit, from the document that edit stored.",
)
def undo_authored_edit(
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
