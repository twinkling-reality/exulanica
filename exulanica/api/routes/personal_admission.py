"""Personal authority, detection permission and human review on the ordinary API."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.errors import BlobNotFoundError, PrivacyAdmissionError
from exulanica.ingest.model_rights import withdraw_model_right
from exulanica.ingest.personal_admission import PersonalBatch, admit_batch
from exulanica.ingest.personal_requests import admission_status, personal_request
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository

router = APIRouter(prefix="/personal-admission", tags=["personal-admission"])


@router.post("", status_code=202)
def admit_personal(
    body: PersonalBatch,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, Any]:
    """Record receipts for the exact captures returned by upload, then queue observation."""
    try:
        if body.request_id is not None:
            return personal_request(
                connection,
                workspace=session.workspace_id,
                actor=session.actor,
                request_id=uuid.UUID(body.request_id),
                operation="admission",
                body=body.model_dump(mode="json", exclude={"request_id"}),
                captures=[uuid.UUID(member.capture_id) for member in body.members],
                run=lambda: admit_personal(
                    body.model_copy(update={"request_id": None}), connection, session, services
                ),
            )
        return admit_batch(
            body,
            actor=session.actor,
            pipeline=PhotoIngestPipeline(
                IngestRepository(connection, session.workspace_id), services.store
            ),
        )
    except (ValueError, PrivacyAdmissionError, BlobNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def personal_status(connection: ReadOnlyConnection, session: CurrentSession) -> dict[str, Any]:
    return admission_status(connection, session.workspace_id, session.actor)


@router.post("/model-rights/{right_id}/withdraw")
def withdraw_right(
    right_id: Annotated[uuid.UUID, Path()],
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    """End one model right now. Final, and idempotent: a second withdrawal changes nothing.

    Another workspace's right is answered exactly as an id nobody granted.
    """
    try:
        right = withdraw_model_right(
            IngestRepository(connection, session.workspace_id),
            right_id=right_id,
            withdrawn_by=session.actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="no such model right") from exc
    return {**right.as_reference(), "state": "ended"}
