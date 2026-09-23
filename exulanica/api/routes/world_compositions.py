"""Composition preview and apply.

Transport for ``exulanica.world.composition_preview``. The bodies carry references and intent
only: a version by path and world, the base state the caller read, a source by identity and a
placement. Everything that decides readiness is resolved on the server, so no field here can make a
preview ready. Apply runs inside :func:`exulanica.api.world_edit.commit_edit` like every other
authored edit: the same transaction, the same saved-entry lock and advance, and the same durable
write.

A photo point map has a pair of routes of its own over the same resolver. Resolving one reads the
photograph's admission state, and a permission is declared per route in
``exulanica.api.permissions`` and checked before the body is read, so the kind cannot share a route
with kinds that need only ``world.write``. The generic pair refuses it for every caller.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from exulanica.api.dependencies import CurrentSession
from exulanica.api.world_edit import (
    BehaviourBody,
    EnvironmentSelectionBody,
    SavedEntryAdvanceBody,
    SourceAnchorBody,
    TransformBody,
    WriteObjects,
    commit_edit,
)
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world import (
    CompositionPlacement,
    CompositionRequest,
    EnvironmentAdmissionSource,
    PhotoPointMapSource,
    ReviewedAssetSource,
    SourceAttachmentSource,
    WorldObjectRepository,
    apply_composition,
    preview_composition,
)

router = APIRouter(prefix="/world", tags=["world"])


class ReviewedAssetSourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reviewed_asset"]
    #: The registry's own key rule (migration 0042), so a key the catalog could never hold is a
    #: 422 here rather than a string the database is asked to compare.
    asset_key: str = Field(min_length=1, max_length=200, pattern=r"^[a-z][a-z0-9.-]*$")

    def domain(self) -> ReviewedAssetSource:
        return ReviewedAssetSource(self.asset_key)


class EnvironmentAdmissionSourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["environment_admission"]
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None = None
    selection: EnvironmentSelectionBody

    @model_validator(mode="after")
    def publication_matches_selection(self) -> EnvironmentAdmissionSourceBody:
        if (self.selection.kind == "feature") != (self.publication_id is not None):
            raise ValueError(
                "a feature selection names its publication and a whole asset names none"
            )
        return self

    def domain(self) -> EnvironmentAdmissionSource:
        return EnvironmentAdmissionSource(
            self.admission_id, self.render_asset_id, self.publication_id, self.selection.domain()
        )


class SourceAttachmentSourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source_attachment"]
    entry_id: uuid.UUID
    attachment_id: uuid.UUID

    def domain(self) -> SourceAttachmentSource:
        return SourceAttachmentSource(self.entry_id, self.attachment_id)


class PhotoPointMapSourceBody(BaseModel):
    """The depth estimate reached through this world's current membership of a photograph.

    The same two identifiers ``source_attachment`` carries, deliberately: the reference is how the
    server finds the photograph, the review it was added under and the world that may use it. What
    differs is what is asked for, and that is the ``kind``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["photo_point_map"]
    entry_id: uuid.UUID
    attachment_id: uuid.UUID

    def domain(self) -> PhotoPointMapSource:
        return PhotoPointMapSource(self.entry_id, self.attachment_id)


CompositionSourceBody = Annotated[
    ReviewedAssetSourceBody
    | EnvironmentAdmissionSourceBody
    | SourceAttachmentSourceBody
    | PhotoPointMapSourceBody,
    Field(discriminator="kind"),
]


class CompositionPlacementBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1, max_length=200)
    region_id: str = Field(min_length=1, max_length=500)
    transform: TransformBody
    #: Chosen by the person, never inferred, exactly as on POST .../objects. A photo point map
    #: takes only ``personal``, which the resolver refuses rather than this transport: the reason
    #: is about what the thing IS, and a person who sent the wrong one should read that sentence.
    origin_role: Literal["fictional", "personal"]
    behaviour: BehaviourBody | None = None
    source_anchor: SourceAnchorBody | None = None

    def domain(self) -> CompositionPlacement:
        return CompositionPlacement(
            subject_id=self.subject_id,
            region_id=self.region_id,
            transform=self.transform.domain(),
            origin_role=self.origin_role,
            behaviour=None if self.behaviour is None else self.behaviour.domain(),
            source_anchor=None if self.source_anchor is None else self.source_anchor.domain(),
        )


class CompositionPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: CompositionSourceBody
    placement: CompositionPlacementBody | None = None

    @model_validator(mode="after")
    def placement_fits_source(self) -> CompositionPreviewBody:
        """Refuse a field the source kind would ignore, rather than accept it and drop it."""
        if self.placement is None:
            return self
        kind = self.source.kind
        if self.placement.behaviour is not None and kind != "reviewed_asset":
            raise ValueError("only a reviewed asset placement takes a behaviour")
        if (self.placement.source_anchor is not None) != (kind == "environment_admission"):
            raise ValueError("an environment placement, and only one, takes a source_anchor")
        return self

    def domain(self) -> CompositionRequest:
        return CompositionRequest(
            base_state_sha256=self.base_state_sha256,
            source=self.source.domain(),
            placement=None if self.placement is None else self.placement.domain(),
        )


class CompositionApplyBody(CompositionPreviewBody):
    placement: CompositionPlacementBody
    saved_entry: SavedEntryAdvanceBody | None = None


class PhotoPointMapPreviewBody(CompositionPreviewBody):
    """The composition body with its source fixed to the one kind these routes take."""

    source: PhotoPointMapSourceBody


class PhotoPointMapApplyBody(CompositionApplyBody):
    source: PhotoPointMapSourceBody


#: Where a photo point map is composed, under this router's prefix.
_PHOTO_POINT_MAP_COMPOSITIONS: Final = "/versions/{version_id}/compositions/photo-point-maps"

#: The generic routes' answer to a photo point map, the same for every caller and every version.
#: Deciding by the caller's grant here would be a permission read from a body, and it is not a
#: ``blocked_reason`` because nothing was resolved.
PHOTO_POINT_MAP_ROUTE_REQUIRED: Final = "photo_point_map_route_required"


def _photo_point_map_route_required() -> JSONResponse:
    routes = " and ".join(
        f"POST {router.prefix}{_PHOTO_POINT_MAP_COMPOSITIONS}/{action}"
        for action in ("preview", "apply")
    )
    return JSONResponse(
        status_code=422,
        content={
            "code": PHOTO_POINT_MAP_ROUTE_REQUIRED,
            "detail": f"a photo_point_map source is composed through {routes}",
        },
    )


@router.post(
    "/versions/{version_id}/compositions/preview",
    response_model=dict[str, object],
    summary="The server's verdict on one composition into one authored version. Writes nothing.",
)
def composition_preview_route(
    version_id: Annotated[uuid.UUID, Path()],
    body: CompositionPreviewBody,
    repository: WriteObjects,
) -> dict[str, object] | JSONResponse:
    if body.source.kind == "photo_point_map":
        return _photo_point_map_route_required()
    return _preview(repository, version_id, body)


@router.post(
    "/versions/{version_id}/compositions/apply",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Perform exactly the resolved composition, or refuse with its blocked reason.",
)
def composition_apply_route(
    version_id: Annotated[uuid.UUID, Path()],
    body: CompositionApplyBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    if body.source.kind == "photo_point_map":
        return _photo_point_map_route_required()
    return _apply(request, repository, version_id, body, actor=session.actor)


@router.post(
    f"{_PHOTO_POINT_MAP_COMPOSITIONS}/preview",
    response_model=dict[str, object],
    summary="The server's verdict on placing a 3D estimate from a photograph. Writes nothing.",
)
def photo_point_map_preview_route(
    version_id: Annotated[uuid.UUID, Path()],
    body: PhotoPointMapPreviewBody,
    repository: WriteObjects,
) -> dict[str, object]:
    return _preview(repository, version_id, body)


@router.post(
    f"{_PHOTO_POINT_MAP_COMPOSITIONS}/apply",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Place exactly the resolved estimate, or refuse with its blocked reason.",
)
def photo_point_map_apply_route(
    version_id: Annotated[uuid.UUID, Path()],
    body: PhotoPointMapApplyBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _apply(request, repository, version_id, body, actor=session.actor)


def _preview(
    repository: WorldObjectRepository, version_id: uuid.UUID, body: CompositionPreviewBody
) -> dict[str, object]:
    # The write-scoped connection, read only: apply resolves on this same connection role, so the
    # two cannot see different rows.
    return preview_composition(repository, version_id, body.domain()).document()


def _apply(
    request: Request,
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    body: CompositionApplyBody,
    *,
    actor: uuid.UUID,
) -> Response | AlternateVersionView:
    composition = body.domain()
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: apply_composition(repository, version_id, composition, actor=actor),
    )
