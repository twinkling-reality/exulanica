"""Arrangement preview and apply.

Transport for :mod:`exulanica.world.arrangements`. The bodies carry references and intent only: a
version by path and world, the base state the caller read, an arrangement by key and version, where
the person stands and which way they face, and the role they give what they add. Where the objects
go is resolved on the server, so no field here can place one. Apply runs inside
:func:`exulanica.api.world_edit.commit_edit` like every other authored edit: the same transaction,
the same saved-entry lock and advance, and each object an ordinary edit in the version's history.

A refusal is ``409 arrangement_refused`` with the reason code as its detail, the shape a composition
refusal has: clients keep only a problem's code and detail.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession
from exulanica.api.world_edit import SavedEntryAdvanceBody, WriteObjects, commit_edit
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world.arrangements import (
    AppliedArrangement,
    ArrangementRefused,
    ArrangementRequest,
    apply_arrangement,
    preview_arrangement,
)
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.objects import MAX_YAW_MICRORADIANS

router = APIRouter(prefix="/world", tags=["world"])

#: The bound on a position a body may state, in millimetres: the bound the society holds an
#: object's transform to (``exulanica.world.society_authored_ground``).
_POSITION_BOUND_MM = 10**9


class ViewerBody(BaseModel):
    """Where the person stands in the world's authored region, and the yaw of their facing."""

    model_config = ConfigDict(extra="forbid")

    x_mm: StrictInt = Field(ge=-_POSITION_BOUND_MM, le=_POSITION_BOUND_MM)
    z_mm: StrictInt = Field(ge=-_POSITION_BOUND_MM, le=_POSITION_BOUND_MM)
    #: The yaw an object placed facing the person would take, as POST .../objects states it.
    yaw_microradians: StrictInt = Field(ge=0, le=MAX_YAW_MICRORADIANS)


class ArrangementPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arrangement_key: str = Field(min_length=1, max_length=200, pattern=r"^[a-z][a-z0-9_]*$")
    arrangement_version: StrictInt = Field(ge=1)
    viewer: ViewerBody
    #: Chosen by the person, never inferred, exactly as on POST .../objects, for every object.
    origin_role: Literal["fictional", "personal"]

    def domain(self) -> ArrangementRequest:
        return ArrangementRequest(
            base_state_sha256=self.base_state_sha256,
            key=self.arrangement_key,
            version=self.arrangement_version,
            viewer_x_mm=self.viewer.x_mm,
            viewer_z_mm=self.viewer.z_mm,
            viewer_yaw_microradians=self.viewer.yaw_microradians,
            origin_role=self.origin_role,
        )


class ArrangementApplyBody(ArrangementPreviewBody):
    saved_entry: SavedEntryAdvanceBody | None = None


class ArrangementView(BaseModel):
    key: str
    version: int
    title: str
    summary: str


class ArrangementApplyView(BaseModel):
    """What apply added, named by the arrangement it came from, and the version it left."""

    arrangement: ArrangementView
    #: Each object added, in the order it was added: undo takes them back newest first.
    added_object_ids: list[str]
    version: AlternateVersionView


def _refused(exc: ArrangementRefused) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"code": "arrangement_refused", "detail": exc.reason}
    )


@router.post(
    "/versions/{version_id}/arrangements/preview",
    response_model=dict[str, object],
    summary="Where an arrangement's objects would stand in one authored version. Writes nothing.",
)
def arrangement_preview_route(
    version_id: Annotated[uuid.UUID, Path()],
    body: ArrangementPreviewBody,
    repository: WriteObjects,
) -> dict[str, object]:
    # The write-scoped connection, read only: apply resolves on this same connection role, so the
    # two cannot see different rows.
    return preview_arrangement(repository, version_id, body.domain()).document()


@router.post(
    "/versions/{version_id}/arrangements/apply",
    response_model=ArrangementApplyView,
    status_code=201,
    summary="Add exactly the resolved objects as ordinary edits, or refuse with the reason.",
)
def arrangement_apply_route(
    version_id: Annotated[uuid.UUID, Path()],
    body: ArrangementApplyBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | ArrangementApplyView:
    applied: list[AppliedArrangement] = []

    def operation() -> AlternateVersion:
        result = apply_arrangement(repository, version_id, body.domain(), actor=session.actor)
        applied.append(result)
        return result.version

    try:
        answer = commit_edit(request, repository, version_id, body, operation)
    except ArrangementRefused as exc:
        return _refused(exc)
    if isinstance(answer, Response):
        return answer
    (result,) = applied
    return ArrangementApplyView(
        arrangement=ArrangementView(**result.arrangement.document()),
        added_object_ids=list(result.object_ids),
        version=answer,
    )
