"""Durable workspace entry points into saved personal-world branch states and styles."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.arrival_source import (
    authorized_arrival_descriptor,
    authorized_retained_scene,
)
from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.errors import BlobNotFoundError, IntegrityError, TombstonedError
from exulanica.graph.payload import ReconstructionSceneRow
from exulanica.graph.scene_geometry import read_scene_geometry
from exulanica.world import (
    InvalidStructuralData,
    SavedWorldCandidate,
    SavedWorldEntry,
    SavedWorldEntryRepository,
    SourceAttachmentOperationConflict,
    SourceAttachmentSelection,
    StaleSavedWorldEntry,
)
from exulanica.world.arrival_selection import ArrivalDescriptor, RetainedScenePin
from exulanica.world.saved_entries import SourceRebindRequired, WorldTakesNoPhotographs
from exulanica.world.source_membership_events import (
    MembershipEventConflict,
    MembershipEventRefused,
)
from exulanica.world.starter import AuthoredStarterScene
from exulanica.world.worlds import WorldsReadOnly, require_world_registration

router = APIRouter(prefix="/world-entries", tags=["world-entries"])
#: What a creation this workspace cannot make is answered with, whatever its reason.
SAVED_WORLD_CONFLICT: Final = "saved_world_conflict"


class AuthoredModuleView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    key: str
    version: int


class BoundedAuthoredGroundView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    kind: Literal["flat"]
    half_width_mm: int
    half_depth_mm: int
    elevation_mm: int


class EndlessAuthoredGroundView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    kind: Literal["endless"]
    elevation_mm: int


# Two shapes rather than one with optional extents. An endless ground has no horizontal extent, so
# the wire shape it is serialised into has nowhere to put one, and a reader cannot mistake an
# absent extent for an unread one.
AuthoredGroundView = Annotated[
    BoundedAuthoredGroundView | EndlessAuthoredGroundView, Field(discriminator="kind")
]


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


class DeclaredFloorView(BaseModel):
    """The floor every region of a world that states no ground has: a square of this half extent
    about the region origin, at this height in the region's frame, in millimetres."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    half_extent_mm: int
    elevation_mm: int


class GeneratedTileView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    tile_x: int
    tile_y: int
    tile_inputs_digest: str
    #: The stored bake the page reads through this world's version, once one is stored.
    baked_tile_id: uuid.UUID | None
    #: ``baked`` when its bytes are served, ``baking`` while none is stored, ``failed`` when a
    #: stored bake was found nondeterministic and is never served.
    state: Literal["baked", "baking", "failed"]


class GeneratedGroundView(BaseModel):
    """What the page draws of a world generated from a recipe: its tiles, the one region its
    people live in and where a person arrives, in that region's frame (east, height, south)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    recipe_key: str
    recipe_label: str
    region_id: str
    arrival_mm: tuple[int, int, int]
    #: The way a person arriving faces, a plan vector east then south: toward the nearest street.
    arrival_facing_mm: tuple[int, int]
    tiles: list[GeneratedTileView]


class SavedWorldEntryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: uuid.UUID
    world_id: str
    title: str
    source_kind: Literal["personal", "authored", "generated"]
    source_snapshot_id: uuid.UUID
    source_snapshot_sha256: str
    authored_scene: AuthoredStarterSceneView | None
    #: Set for a world whose regions have the declared floor its people stand on; the app draws it.
    declared_floor: DeclaredFloorView | None
    #: Set for a world generated from a recipe: the baked tiles the app draws, its region and where
    #: a person arrives.
    generated_ground: GeneratedGroundView | None = None
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
    #: Whether photographs may be added to this world, by its kind: false for a world generated
    #: from a recipe, which adding photographs to is refused by name.
    takes_photographs: bool
    #: Present only for a society whose v4 genesis pinned this exact authorized first frame.
    arrival: ArrivalDescriptor | None = None
    arrival_unavailable_reason: Literal["arrival_source_unavailable"] | None = None
    arrival_scene: ReconstructionSceneRow | None = None


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
    unavailable_reason: (
        Literal[
            "source_unavailable",
            "authorization_expired",
            "screening_expired",
            "viewer_unavailable",
        ]
        | None
    )
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
    values = {
        field: getattr(entry, field)
        for field in SavedWorldEntryView.model_fields
        if hasattr(entry, field)
    }
    if isinstance(entry.authored_scene, AuthoredStarterScene):
        values["authored_scene"] = AuthoredStarterSceneView.model_validate(entry.authored_scene)
    if entry.declared_floor is not None:
        values["declared_floor"] = DeclaredFloorView.model_validate(entry.declared_floor)
    if entry.generated_ground is not None:
        values["generated_ground"] = GeneratedGroundView.model_validate(entry.generated_ground)
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
        require_world_registration(connection)
    except WorldsReadOnly as exc:
        return JSONResponse(status_code=403, content={"code": exc.code, "detail": str(exc)})
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
            content={"code": SAVED_WORLD_CONFLICT, "detail": str(exc)},
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
            content={"code": SAVED_WORLD_CONFLICT, "detail": str(exc)},
        )
    return _view(created)


@router.get("/{entry_id}", response_model=SavedWorldEntryView)
def entry(
    entry_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView:
    saved = SavedWorldEntryRepository(connection, session.workspace_id, services.store).entry(
        entry_id
    )
    view = _view(saved)
    if saved.source_kind != "personal":
        return view
    row = connection.execute(
        "select i.document from world_society s join world_society_input i "
        "on i.workspace_id=s.workspace_id and i.society_id=s.society_id and i.input_seq=1 "
        "where s.workspace_id=%s and s.world_id=%s and s.version_id=%s",
        (session.workspace_id, saved.world_id, saved.authored_version_id),
    ).fetchone()
    if (
        row is None
        or row["document"].get("profile") != "exulanica.society-input/authored-ground-v4"
    ):
        return view
    try:
        descriptor = ArrivalDescriptor.model_validate(row["document"]["arrival"])
        available = authorized_arrival_descriptor(
            connection, session.workspace_id, descriptor, services.store
        )
    except (KeyError, ValueError):
        available = False
    scene = None
    if available and isinstance(descriptor.source, RetainedScenePin):
        scene = authorized_retained_scene(
            connection, session.workspace_id, descriptor.source, services.store
        )
        if scene is None:
            available = False
        elif scene.trained_geometry is not None and scene.trained_geometry.reference is not None:
            scene = scene.model_copy(deep=True)
            trained_copy = scene.trained_geometry
            assert trained_copy is not None and trained_copy.reference is not None
            trained_copy.reference.href = (
                f"/world-entries/{entry_id}/arrival/scene-geometry/{trained_copy.artifact_id}"
            )
        if available and not authorized_arrival_descriptor(
            connection, session.workspace_id, descriptor, services.store
        ):
            available = False
    return view.model_copy(
        update={
            "arrival": descriptor if available else None,
            "arrival_unavailable_reason": None if available else "arrival_source_unavailable",
            "arrival_scene": scene if available else None,
        }
    )


@router.get("/{entry_id}/arrival/scene-geometry/{artifact_id}")
def arrival_scene_geometry(
    entry_id: Annotated[uuid.UUID, Path()],
    artifact_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    """Serve only the trained artifact of this entry's currently authorized v4 build."""
    saved = SavedWorldEntryRepository(connection, session.workspace_id, services.store).entry(
        entry_id
    )
    row = connection.execute(
        "select i.document from world_society s join world_society_input i "
        "on i.workspace_id=s.workspace_id and i.society_id=s.society_id and i.input_seq=1 "
        "where s.workspace_id=%s and s.world_id=%s and s.version_id=%s",
        (session.workspace_id, saved.world_id, saved.authored_version_id),
    ).fetchone()
    if (
        row is None
        or row["document"].get("profile") != "exulanica.society-input/authored-ground-v4"
    ):
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no arrival build"}
        )
    descriptor = ArrivalDescriptor.model_validate(row["document"]["arrival"])
    pin = descriptor.source
    if not isinstance(pin, RetainedScenePin) or not authorized_arrival_descriptor(
        connection, session.workspace_id, descriptor, services.store
    ):
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no arrival build"}
        )
    scene = authorized_retained_scene(connection, session.workspace_id, pin, services.store)
    if (
        scene is None
        or scene.trained_geometry is None
        or scene.trained_geometry.artifact_id != artifact_id
    ):
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no arrival artifact"}
        )
    try:
        found = read_scene_geometry(
            connection,
            session.workspace_id,
            artifact_id,
            services.store,
            retained_job_id=pin.job_id,
        )
    except (BlobNotFoundError, IntegrityError, TombstonedError, ValueError):
        found = None
    if found is None or found.content_sha256 != scene.trained_geometry.content_sha256:
        return JSONResponse(
            status_code=404,
            content={"code": "unknown_reference", "detail": "arrival artifact unavailable"},
        )
    if not authorized_arrival_descriptor(
        connection, session.workspace_id, descriptor, services.store
    ):
        return JSONResponse(
            status_code=404,
            content={"code": "unknown_reference", "detail": "arrival artifact unavailable"},
        )
    return Response(
        content=found.payload,
        media_type="application/octet-stream",
        headers={
            "ETag": f'"{found.content_sha256}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "none",
        },
    )


@router.put("/{entry_id}", response_model=SavedWorldEntryView)
def update_entry(
    entry_id: Annotated[uuid.UUID, Path()],
    body: UpdateSavedWorldEntryBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    entries = SavedWorldEntryRepository(connection, session.workspace_id, services.store)
    try:
        entries.update(
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
    # Read after the write's own transaction has committed: the read checks viewer images.
    return _view(entries.entry(entry_id))


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
    except WorldTakesNoPhotographs as exc:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})
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
