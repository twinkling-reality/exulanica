"""Environment instances in an authored version: place, move, remove and undo.

An instance pins one exact admitted environment asset or feature. Every edit names the version state
it was made against and runs in :func:`exulanica.api.world_edit.commit_edit`, like every other
authored edit.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request, Response
from pydantic import Field

from exulanica.api.dependencies import CurrentSession
from exulanica.api.world_edit import (
    BaseStateBody,
    EntryBoundEditBody,
    EnvironmentSelectionBody,
    MoveObjectBody,
    SourceAnchorBody,
    TransformBody,
    WriteObjects,
    commit_edit,
)
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world import EnvironmentPlacement, ObjectOrigin

router = APIRouter(prefix="/world", tags=["world"])


class AddEnvironmentBody(EntryBoundEditBody):
    instance_id: str = Field(min_length=1, max_length=200)
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None = None
    selection: EnvironmentSelectionBody
    source_anchor: SourceAnchorBody
    region_id: str = Field(min_length=1, max_length=500)
    transform: TransformBody
    origin_role: Literal["fictional", "personal"]


@router.post(
    "/versions/{version_id}/environment-instances",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Place one exact environment asset or feature against the current version state.",
)
def add_environment_instance(
    version_id: Annotated[uuid.UUID, Path()],
    body: AddEnvironmentBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    placement = EnvironmentPlacement(
        instance_id=body.instance_id,
        admission_id=body.admission_id,
        render_asset_id=body.render_asset_id,
        publication_id=body.publication_id,
        selection=body.selection.domain(),
        source_anchor=body.source_anchor.domain(),
        region_id=body.region_id,
        transform=body.transform.domain(),
        origin=ObjectOrigin("authored", body.origin_role),
    )
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.add_environment(
            version_id,
            placement,
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/environment-instances/{instance_id}/move",
    response_model=AlternateVersionView,
    summary="Move an available, still-authorized environment instance without changing its source.",
)
def move_environment_instance(
    version_id: Annotated[uuid.UUID, Path()],
    instance_id: Annotated[str, Path(max_length=200)],
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
        lambda: repository.move_environment(
            version_id,
            instance_id,
            body.transform.domain(),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/environment-instances/{instance_id}/remove",
    response_model=AlternateVersionView,
    summary="Store a removal, including when the pinned source has since been withdrawn.",
)
def remove_environment_instance(
    version_id: Annotated[uuid.UUID, Path()],
    instance_id: Annotated[str, Path(max_length=200)],
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
        lambda: repository.remove_environment(
            version_id,
            instance_id,
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/environment-instances/undo",
    response_model=AlternateVersionView,
    summary="Undo the newest authored edit from stored history, even after source withdrawal.",
)
def undo_environment_edit(
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
