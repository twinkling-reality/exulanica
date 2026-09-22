"""Authenticated admission and operation-scoped reads of environment resources."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.environment import (
    DeclaredPlaceFrame,
    DerivedEnvironmentAsset,
    DuplicateEnvironmentSource,
    EnvironmentAdmissionRefused,
    EnvironmentFeatureKind,
    EnvironmentOperation,
    EnvironmentOperationDenied,
    EnvironmentPayloadTooLarge,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    FeatureIndexPublication,
    InvalidEnvironmentFeatureFilter,
    PlaceFrameConflict,
    SourceAdmission,
    SourceDigestMismatch,
    UnknownEnvironmentResource,
)
from exulanica.errors import BlobNotFoundError

router = APIRouter(prefix="/environment-resources", tags=["environment-resources"])


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _inbox_file(
    services: Services, session: CurrentSession, declared: Path
) -> tuple[Path | None, Response | None]:
    """Resolve a declared local path inside this workspace's own admission inbox.

    A path outside the inbox and a path that names nothing answer identically, because the
    difference between them is a fact about this machine's filesystem that a caller admitting
    somebody else's workspace has no business learning.
    """
    root = services.environment_admission_root
    if root is None:
        return None, _problem(
            503, "admission_unavailable", "the local environment inbox is disabled"
        )
    local_path = declared.resolve()
    workspace_root = root.resolve() / str(session.workspace_id)
    if not local_path.is_relative_to(workspace_root) or not local_path.is_file():
        return None, _problem(404, "unknown_reference", "no such environment admission input")
    return local_path, None


@router.post("/places", status_code=201)
def declare_place(
    body: DeclaredPlaceFrame,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    """Create a place whose frame a provider documented, so a source can be admitted to it.

    The frame this records is **declared, never measured**: the response says so in
    ``frame_authority`` and the receipt repeats it, because a reader that could not tell a
    declaration from a recovered frame would be told a measurement had been made where none was.
    Creating a place grants no right to any source; rights are resolved per admission.
    """
    try:
        declared = EnvironmentRepository(
            connection, session.workspace_id, services.store
        ).declare_place_frame(body, actor=session.actor)
        return JSONResponse(status_code=201, content=declared.document())
    except PlaceFrameConflict as exc:
        return _problem(409, "place_frame_conflict", str(exc))
    except EnvironmentAdmissionRefused as exc:
        return _problem(409, "place_frame_refused", str(exc))


@router.get("/places/{place_id}")
def declared_place(
    place_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    """What a place declared about its frame, for a reader holding only its identifier.

    Registered before the ``{kind}/{resource_id}`` reads below, so ``places`` resolves here
    rather than as a resource kind. A caller that reached a place through a Selection row or a
    composed instance can ask this what kind of frame it has, which is the only way the
    declared-never-measured distinction survives past the request that created the place.
    """
    repository = EnvironmentRepository(connection, session.workspace_id, services.store)
    try:
        return JSONResponse(
            content=repository.declared_place(place_id).document(),
            headers={"Cache-Control": "private, no-store"},
        )
    except UnknownEnvironmentResource as exc:
        return _problem(404, "unknown_reference", str(exc))


@router.post("/sources", status_code=201)
def admit_source(
    body: SourceAdmission,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    local_path, refusal = _inbox_file(services, session, body.local_path)
    if local_path is None:
        assert refusal is not None
        return refusal
    try:
        resource = EnvironmentRepository(
            connection, session.workspace_id, services.store
        ).admit_source(body.model_copy(update={"local_path": local_path}), actor=session.actor)
        return JSONResponse(status_code=201, content=resource.document())
    except UnknownEnvironmentResource:
        return _problem(404, "unknown_reference", "no such environment admission input")
    except EnvironmentPayloadTooLarge as exc:
        return _problem(413, "payload_too_large", str(exc))
    except SourceDigestMismatch as exc:
        return _problem(409, "source_digest_mismatch", str(exc))
    except DuplicateEnvironmentSource as exc:
        return _problem(409, "source_already_admitted", str(exc))
    except EnvironmentAdmissionRefused as exc:
        return _problem(409, "admission_refused", str(exc))


@router.post("/assets", status_code=201)
def register_derived_asset(
    body: DerivedEnvironmentAsset,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    """Register derived bytes against an admitted source, so a feature index can name them.

    The admission stays authoritative. A withdrawn source, or one whose rights do not permit
    what the derivation declares, refuses here exactly as it refuses everywhere else, and the
    derived row can never widen its source's rights.
    """
    local_path, refusal = _inbox_file(services, session, body.local_path)
    if local_path is None:
        assert refusal is not None
        return refusal
    try:
        resource = EnvironmentRepository(
            connection, session.workspace_id, services.store
        ).register_derived(body.model_copy(update={"local_path": local_path}), actor=session.actor)
        return JSONResponse(status_code=201, content=resource.document())
    except UnknownEnvironmentResource as exc:
        return _problem(404, "unknown_reference", str(exc))
    except EnvironmentResourceWithdrawn as exc:
        return _problem(410, "withdrawn", str(exc))
    except EnvironmentOperationDenied as exc:
        return _problem(403, "operation_denied", str(exc))
    except EnvironmentPayloadTooLarge as exc:
        return _problem(413, "payload_too_large", str(exc))
    except SourceDigestMismatch as exc:
        return _problem(409, "source_digest_mismatch", str(exc))
    except DuplicateEnvironmentSource as exc:
        return _problem(409, "asset_already_registered", str(exc))
    except EnvironmentAdmissionRefused as exc:
        return _problem(409, "admission_refused", str(exc))


@router.post("/sources/{admission_id}/feature-indexes", status_code=201)
def publish_feature_index(
    admission_id: uuid.UUID,
    body: FeatureIndexPublication,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    repository = EnvironmentRepository(connection, session.workspace_id, services.store)
    try:
        published = repository.publish_feature_index(admission_id, body, actor=session.actor)
        return JSONResponse(status_code=201, content=published.document())
    except UnknownEnvironmentResource as exc:
        return _problem(404, "unknown_reference", str(exc))
    except EnvironmentResourceWithdrawn as exc:
        return _problem(410, "withdrawn", str(exc))
    except EnvironmentOperationDenied as exc:
        return _problem(403, "operation_denied", str(exc))


@router.get("/sources/{admission_id}/features")
def features(
    admission_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    feature_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")] = None,
    kind: Annotated[EnvironmentFeatureKind | None, Query()] = None,
    bbox: Annotated[list[int] | None, Query(min_length=4, max_length=6)] = None,
    label: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> Response:
    if bbox is not None:
        if len(bbox) not in (4, 6):
            return _problem(422, "invalid_filter", "bbox requires four or six integers")
        dimensions = len(bbox) // 2
        if any(bbox[index] > bbox[index + dimensions] for index in range(dimensions)):
            return _problem(422, "invalid_filter", "bbox minimum must not exceed its maximum")
    repository = EnvironmentRepository(connection, session.workspace_id, services.store)
    try:
        catalog = repository.read_features(
            admission_id,
            feature_id=feature_id,
            kind=kind,
            bbox=None if bbox is None else tuple(bbox),
            label=label,
        )
        return JSONResponse(
            content=catalog.document(),
            headers={"Cache-Control": "private, no-store"},
        )
    except (UnknownEnvironmentResource, BlobNotFoundError) as exc:
        return _problem(404, "unknown_reference", str(exc))
    except EnvironmentResourceWithdrawn as exc:
        return _problem(410, "withdrawn", str(exc))
    except EnvironmentOperationDenied as exc:
        return _problem(403, "operation_denied", str(exc))
    except InvalidEnvironmentFeatureFilter as exc:
        return _problem(422, "invalid_filter", str(exc))


@router.get("/{kind}/{resource_id}")
def metadata(
    kind: Literal["source", "asset"],
    resource_id: uuid.UUID,
    operation: Annotated[EnvironmentOperation, Query()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    repository = EnvironmentRepository(connection, session.workspace_id, services.store)
    try:
        return JSONResponse(
            content=repository.read_metadata(kind, resource_id, operation).document(),
            headers={"Cache-Control": "private, no-store"},
        )
    except UnknownEnvironmentResource as exc:
        return _problem(404, "unknown_reference", str(exc))
    except EnvironmentResourceWithdrawn as exc:
        return _problem(410, "withdrawn", str(exc))
    except EnvironmentOperationDenied as exc:
        return _problem(403, "operation_denied", str(exc))


@router.get("/{kind}/{resource_id}/bytes")
def resource_bytes(
    kind: Literal["source", "asset"],
    resource_id: uuid.UUID,
    operation: Annotated[EnvironmentOperation, Query()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    repository = EnvironmentRepository(connection, session.workspace_id, services.store)
    try:
        authorized = repository.read_bytes(kind, resource_id, operation)
        return Response(
            content=authorized.data,
            media_type=authorized.media_type,
            headers={"Cache-Control": "private, no-store"},
        )
    except (UnknownEnvironmentResource, BlobNotFoundError) as exc:
        return _problem(404, "unknown_reference", str(exc))
    except EnvironmentResourceWithdrawn as exc:
        return _problem(410, "withdrawn", str(exc))
    except EnvironmentOperationDenied as exc:
        return _problem(403, "operation_denied", str(exc))
