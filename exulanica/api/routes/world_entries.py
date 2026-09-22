"""Durable workspace entry points into saved personal-world branch states and styles."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.world import (
    InvalidStructuralData,
    SavedWorldCandidate,
    SavedWorldEntry,
    SavedWorldEntryRepository,
    SourceAttachmentOperationConflict,
    SourceAttachmentSelection,
    StaleSavedWorldEntry,
)
from exulanica.world.saved_entries import SourceRebindRequired
from exulanica.world.source_membership_events import (
    MembershipEventConflict,
    MembershipEventRefused,
)
from exulanica.world.starter import AuthoredStarterScene

router = APIRouter(prefix="/world-entries", tags=["world-entries"])


class AuthoredModuleView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    key: str
    version: int


class AuthoredGroundView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    kind: Literal["flat"]
    half_width_mm: int
    half_depth_mm: int
    elevation_mm: int


class AuthoredSpawnView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    x_mm: int
    y_mm: int
    z_mm: int
    yaw_microradians: int


class AuthoredRegionView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    region_id: str
    origin: Literal["authored"]
    module: AuthoredModuleView
    ground: AuthoredGroundView
    spawn: AuthoredSpawnView


class AuthoredStarterSceneView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    schema_version: Literal[1]
    kind: Literal["authored-starter"]
    region: AuthoredRegionView


class SavedWorldEntryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: uuid.UUID
    world_id: str
    title: str
    source_kind: Literal["personal", "authored"]
    source_snapshot_id: uuid.UUID
    source_snapshot_sha256: str
    authored_scene: AuthoredStarterSceneView | None
    authored_version_id: uuid.UUID
    authored_state_sha256: str
    authored_edit_seq: int
    current_authored_state_sha256: str
    current_authored_edit_seq: int
    style_version_id: uuid.UUID
    revision: int
    availability: Literal["available", "unavailable"]
    unavailable_reason: str | None
    source_attachments: list[SavedWorldSourceAttachmentView]
    previous_source_attachments: list[SavedWorldPreviousSourceAttachmentView]
    created_by: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class CreateSavedWorldEntryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: Annotated[str, Field(min_length=1, max_length=200)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    source_kind: Literal["personal"]
    authored_version_id: uuid.UUID
    style_version_id: uuid.UUID


class CreateStarterWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)] = "My world"


class UpdateSavedWorldEntryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: Annotated[int, Field(ge=1)]
    authored_version_id: uuid.UUID
    expected_authored_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    expected_authored_edit_seq: Annotated[int, Field(ge=0)]
    style_version_id: uuid.UUID
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None


class SourceAttachmentSelectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID


class AttachSavedWorldSourcesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: uuid.UUID
    base_revision: Annotated[int, Field(ge=1)]
    authored_version_id: uuid.UUID
    authored_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    authored_edit_seq: Annotated[int, Field(ge=0)]
    style_version_id: uuid.UUID
    sources: Annotated[list[SourceAttachmentSelectionBody], Field(min_length=1, max_length=200)]


class DetachSelectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: uuid.UUID


class DetachSavedWorldSourcesBody(BaseModel):
    """Detach names current memberships by attachment. The cursor is the resume point read."""

    model_config = ConfigDict(extra="forbid")

    operation_id: uuid.UUID
    base_revision: Annotated[int, Field(ge=1)]
    authored_version_id: uuid.UUID
    authored_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    authored_edit_seq: Annotated[int, Field(ge=0)]
    style_version_id: uuid.UUID
    selections: Annotated[list[DetachSelectionBody], Field(min_length=1, max_length=200)]


class RebindSavedWorldSourcesBody(BaseModel):
    """Rebind names photographs; the server resolves and pins their new review receipts."""

    model_config = ConfigDict(extra="forbid")

    operation_id: uuid.UUID
    base_revision: Annotated[int, Field(ge=1)]
    authored_version_id: uuid.UUID
    authored_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    authored_edit_seq: Annotated[int, Field(ge=0)]
    style_version_id: uuid.UUID
    sources: Annotated[list[SourceAttachmentSelectionBody], Field(min_length=1, max_length=200)]


class SavedWorldSourceAttachmentView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    attachment_id: uuid.UUID
    operation_id: uuid.UUID
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    source_sha256: str
    authorization_id: uuid.UUID
    screening_id: uuid.UUID
    role: Literal["reference"]
    attached_entry_revision: int
    attached_by: uuid.UUID
    attached_at: dt.datetime
    availability: Literal["available", "unavailable"]
    unavailable_reason: Literal[
        "source_unavailable",
        "authorization_expired",
        "screening_expired",
        "viewer_unavailable",
    ] | None
    viewer_sha256: str | None
    evidence_path: str | None


class SavedWorldPreviousSourceAttachmentView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    attachment_id: uuid.UUID
    operation_id: uuid.UUID
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    source_sha256: str
    authorization_id: uuid.UUID
    screening_id: uuid.UUID
    attached_entry_revision: int
    attached_at: dt.datetime
    detach_operation_id: uuid.UUID
    detached_entry_revision: int
    detached_by: uuid.UUID
    detached_at: dt.datetime
    availability: Literal["available", "unavailable"]
    unavailable_reason: Literal["source_unavailable"] | None


class SavedWorldStyleCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    revision: int


class SavedWorldCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    authored_version_id: uuid.UUID
    title: str
    source_invalidated: bool
    styles: list[SavedWorldStyleCandidateView]


def _view(entry: SavedWorldEntry) -> SavedWorldEntryView:
    values = {field: getattr(entry, field) for field in SavedWorldEntryView.model_fields}
    if isinstance(entry.authored_scene, AuthoredStarterScene):
        values["authored_scene"] = AuthoredStarterSceneView.model_validate(entry.authored_scene)
    values["source_attachments"] = [
        SavedWorldSourceAttachmentView.model_validate(attachment)
        for attachment in entry.source_attachments
    ]
    values["previous_source_attachments"] = [
        SavedWorldPreviousSourceAttachmentView.model_validate(attachment)
        for attachment in entry.previous_source_attachments
    ]
    return SavedWorldEntryView(**values)


def _candidate_view(candidate: SavedWorldCandidate) -> SavedWorldCandidateView:
    return SavedWorldCandidateView(
        world_id=candidate.world_id,
        authored_version_id=candidate.authored_version_id,
        title=candidate.title,
        source_invalidated=candidate.source_invalidated,
        styles=[
            SavedWorldStyleCandidateView(version_id=style.version_id, revision=style.revision)
            for style in candidate.styles
        ],
    )


@router.get("", response_model=list[SavedWorldEntryView])
def entries(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> list[SavedWorldEntryView]:
    return [
        _view(entry)
        for entry in SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).entries()
    ]


@router.get("/candidates", response_model=list[SavedWorldCandidateView])
def candidates(
    connection: ReadOnlyConnection, session: CurrentSession
) -> list[SavedWorldCandidateView]:
    return [
        _candidate_view(candidate)
        for candidate in SavedWorldEntryRepository(connection, session.workspace_id).candidates()
    ]


@router.post("/starter", response_model=SavedWorldEntryView)
def create_starter_entry(
    body: CreateStarterWorldBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    try:
        created = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).create_starter(
            title=body.title,
            created_by=session.actor,
        )
    except (InvalidStructuralData, ValueError) as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "saved_world_conflict", "detail": str(exc)},
        )
    return _view(created)


@router.post("", response_model=SavedWorldEntryView, status_code=201)
def create_entry(
    body: CreateSavedWorldEntryBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    try:
        created = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).create(
            world_id=body.world_id,
            title=body.title,
            authored_version_id=body.authored_version_id,
            style_version_id=body.style_version_id,
            created_by=session.actor,
        )
    except (InvalidStructuralData, ValueError) as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "saved_world_conflict", "detail": str(exc)},
        )
    return _view(created)


@router.get("/{entry_id}", response_model=SavedWorldEntryView)
def entry(
    entry_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView:
    return _view(
        SavedWorldEntryRepository(connection, session.workspace_id, services.store).entry(entry_id)
    )


@router.put("/{entry_id}", response_model=SavedWorldEntryView)
def update_entry(
    entry_id: Annotated[uuid.UUID, Path()],
    body: UpdateSavedWorldEntryBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    try:
        updated = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).update(
            entry_id,
            base_revision=body.base_revision,
            authored_version_id=body.authored_version_id,
            expected_authored_state_sha256=body.expected_authored_state_sha256,
            expected_authored_edit_seq=body.expected_authored_edit_seq,
            style_version_id=body.style_version_id,
            title=body.title,
        )
    except StaleSavedWorldEntry as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "stale_saved_world_entry", "detail": str(exc)},
        )
    except (InvalidStructuralData, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_saved_world_entry", "detail": str(exc)},
        )
    return _view(updated)


@router.post("/{entry_id}/source-attachments", response_model=SavedWorldEntryView)
def attach_sources(
    entry_id: Annotated[uuid.UUID, Path()],
    body: AttachSavedWorldSourcesBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    try:
        attached = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).attach_sources(
            entry_id,
            operation_id=body.operation_id,
            base_revision=body.base_revision,
            authored_version_id=body.authored_version_id,
            authored_state_sha256=body.authored_state_sha256,
            authored_edit_seq=body.authored_edit_seq,
            style_version_id=body.style_version_id,
            sources=tuple(
                SourceAttachmentSelection(
                    capture_id=source.capture_id,
                    evidence_span_id=source.evidence_span_id,
                )
                for source in body.sources
            ),
            attached_by=session.actor,
        )
    except SourceAttachmentOperationConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "source_attachment_operation_conflict", "detail": str(exc)},
        )
    except StaleSavedWorldEntry as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "stale_saved_world_entry", "detail": str(exc)},
        )
    except SourceRebindRequired as exc:
        return JSONResponse(
            status_code=422,
            content={"code": "rebind_required", "detail": str(exc)},
        )
    except (InvalidStructuralData, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_source_attachment", "detail": str(exc)},
        )
    return _view(attached)


def _membership_refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, MembershipEventConflict):
        return JSONResponse(
            status_code=409,
            content={"code": "membership_event_operation_conflict", "detail": str(exc)},
        )
    if isinstance(exc, StaleSavedWorldEntry):
        return JSONResponse(
            status_code=409,
            content={"code": "stale_saved_world_entry", "detail": str(exc)},
        )
    if isinstance(exc, MembershipEventRefused):
        return JSONResponse(status_code=422, content={"code": exc.code, "detail": exc.detail})
    return JSONResponse(
        status_code=422, content={"code": "invalid_source_membership", "detail": str(exc)}
    )


@router.post("/{entry_id}/source-detachments", response_model=SavedWorldEntryView)
def detach_sources(
    entry_id: Annotated[uuid.UUID, Path()],
    body: DetachSavedWorldSourcesBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    try:
        detached = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).detach_sources(
            entry_id,
            operation_id=body.operation_id,
            base_revision=body.base_revision,
            authored_version_id=body.authored_version_id,
            authored_state_sha256=body.authored_state_sha256,
            authored_edit_seq=body.authored_edit_seq,
            style_version_id=body.style_version_id,
            attachment_ids=tuple(selection.attachment_id for selection in body.selections),
            detached_by=session.actor,
        )
    except (
        MembershipEventConflict,
        StaleSavedWorldEntry,
        MembershipEventRefused,
        InvalidStructuralData,
        ValueError,
    ) as exc:
        return _membership_refusal(exc)
    return _view(detached)


@router.post("/{entry_id}/source-rebinds", response_model=SavedWorldEntryView)
def rebind_sources(
    entry_id: Annotated[uuid.UUID, Path()],
    body: RebindSavedWorldSourcesBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    try:
        rebound = SavedWorldEntryRepository(
            connection, session.workspace_id, services.store
        ).rebind_sources(
            entry_id,
            operation_id=body.operation_id,
            base_revision=body.base_revision,
            authored_version_id=body.authored_version_id,
            authored_state_sha256=body.authored_state_sha256,
            authored_edit_seq=body.authored_edit_seq,
            style_version_id=body.style_version_id,
            sources=tuple(
                SourceAttachmentSelection(
                    capture_id=source.capture_id,
                    evidence_span_id=source.evidence_span_id,
                )
                for source in body.sources
            ),
            rebound_by=session.actor,
        )
    except (
        MembershipEventConflict,
        StaleSavedWorldEntry,
        MembershipEventRefused,
        InvalidStructuralData,
        ValueError,
    ) as exc:
        return _membership_refusal(exc)
    return _view(rebound)
