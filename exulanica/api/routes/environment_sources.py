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
    EnvironmentOperation,
    EnvironmentOperationDenied,
    EnvironmentPayloadTooLarge,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
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
