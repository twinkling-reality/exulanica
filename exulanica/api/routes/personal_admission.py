"""Personal authority, detection permission and human review on the ordinary API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.services import Services
from exulanica.errors import BlobNotFoundError, PrivacyAdmissionError
from exulanica.ingest.personal_admission import PersonalBatch, admit_batch
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
        return admit_batch(
            body,
            actor=session.actor,
            pipeline=PhotoIngestPipeline(
                IngestRepository(connection, session.workspace_id), services.store
            ),
        )
    except (ValueError, PrivacyAdmissionError, BlobNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
