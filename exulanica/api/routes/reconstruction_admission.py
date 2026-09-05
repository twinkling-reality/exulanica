"""Authenticated exact-byte benchmark review; no synthetic or personal-media shortcut."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.reference_admission import admit_reviewed_benchmark
from exulanica.ingest.repository import IngestRepository

router = APIRouter(prefix="/operations", tags=["operations"])
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ReviewedMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_id: uuid.UUID
    source_sha256: Digest


class BenchmarkReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[ReviewedMember] = Field(min_length=1, max_length=500)
    source_manifest_sha256: Digest
    source_manifest: dict[str, Any]
    official_source_url: HttpUrl
    retrieval_date: dt.date
    license_document_sha256: Digest
    permitted_use: str = Field(min_length=1, max_length=2000)
    reviewed_by_name: str = Field(min_length=1, max_length=200)
    reviewed_at: AwareDatetime
    attestation: str = Field(min_length=1, max_length=1000)


@router.post("/reconstruction-admission", status_code=202)
def admit_benchmark(
    body: BenchmarkReview,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    try:
        with connection.transaction():
            return admit_reviewed_benchmark(
                IngestRepository(connection, session.workspace_id),
                actor=session.actor,
                members=[(item.capture_id, item.source_sha256) for item in body.members],
                source_manifest_sha256=body.source_manifest_sha256,
                source_manifest=body.source_manifest,
                official_source_url=str(body.official_source_url),
                retrieval_date=body.retrieval_date.isoformat(),
                license_document_sha256=body.license_document_sha256,
                permitted_use=body.permitted_use,
                reviewed_by_name=body.reviewed_by_name,
                reviewed_at=body.reviewed_at,
                attestation=body.attestation,
            )
    except PrivacyAdmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
