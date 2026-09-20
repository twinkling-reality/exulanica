"""Durable workspace entry points into saved personal-world branch states and styles."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.world import (
    InvalidStructuralData,
    SavedWorldCandidate,
    SavedWorldEntry,
    SavedWorldEntryRepository,
    StaleSavedWorldEntry,
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
def entries(connection: ReadOnlyConnection, session: CurrentSession) -> list[SavedWorldEntryView]:
    return [
        _view(entry)
        for entry in SavedWorldEntryRepository(connection, session.workspace_id).entries()
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
) -> SavedWorldEntryView | JSONResponse:
    try:
        created = SavedWorldEntryRepository(connection, session.workspace_id).create_starter(
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
) -> SavedWorldEntryView | JSONResponse:
    try:
        created = SavedWorldEntryRepository(connection, session.workspace_id).create(
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
) -> SavedWorldEntryView:
    return _view(SavedWorldEntryRepository(connection, session.workspace_id).entry(entry_id))


@router.put("/{entry_id}", response_model=SavedWorldEntryView)
def update_entry(
    entry_id: Annotated[uuid.UUID, Path()],
    body: UpdateSavedWorldEntryBody,
    connection: ScopedConnection,
    session: CurrentSession,
) -> SavedWorldEntryView | JSONResponse:
    try:
        updated = SavedWorldEntryRepository(connection, session.workspace_id).update(
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
