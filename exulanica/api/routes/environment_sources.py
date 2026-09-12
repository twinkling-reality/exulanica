"""Authenticated admission and operation-scoped reads of environment resources."""

from __future__ import annotations

import uuid
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
    EnvironmentFeatureKind,
    EnvironmentOperation,
    EnvironmentOperationDenied,
    EnvironmentPayloadTooLarge,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    FeatureIndexPublication,
    SourceAdmission,
    SourceDigestMismatch,
    UnknownEnvironmentResource,
)
from exulanica.errors import BlobNotFoundError

router = APIRouter(prefix="/environment-resources", tags=["environment-resources"])


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


@router.post("/sources", status_code=201)
def admit_source(
    body: SourceAdmission,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    root = services.environment_admission_root
    local_path = body.local_path.resolve()
    if root is None:
        return _problem(503, "admission_unavailable", "the local environment inbox is disabled")
    workspace_root = root.resolve() / str(session.workspace_id)
    if not local_path.is_relative_to(workspace_root) or not local_path.is_file():
        return _problem(404, "unknown_reference", "no such environment admission input")
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
