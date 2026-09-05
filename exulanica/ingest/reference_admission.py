"""Admit an explicitly human-reviewed benchmark set through existing receipt and job writers."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from exulanica.canonical import sha256_of_canonical
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest import derivative_queue
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.privacy import authorize_benchmark_capture, record_human_screening
from exulanica.ingest.repository import IngestRepository

HUMAN_ATTESTATION = (
    "I personally inspected every exact photograph in this inventory and found no visible "
    "people or sensitive person regions."
)


def admit_reviewed_benchmark(
    repository: IngestRepository,
    *,
    actor: uuid.UUID,
    members: list[tuple[uuid.UUID, str]],
    source_manifest_sha256: str,
    source_manifest: dict[str, Any],
    official_source_url: str,
    retrieval_date: str,
    license_document_sha256: str,
    permitted_use: str,
    reviewed_by_name: str,
    reviewed_at: dt.datetime,
    attestation: str,
) -> dict[str, Any]:
    """Atomically bind real human review to exact captures and enqueue the normal derivatives.

    The caller's authenticated actor owns the review; a request cannot name another
    actor or workspace. This function never supplies an attestation on their behalf.
    """
    if attestation != HUMAN_ATTESTATION or not reviewed_by_name.strip():
        raise PrivacyAdmissionError("an explicit named human exact-byte review is required")
    try:
        split = source_manifest["evaluation_split"]
        train, heldout = split["training_sha256"], split["heldout_sha256"]
        digests = {digest for _, digest in members}
        valid_manifest = (
            source_manifest.get("profile") == "exulanica.reference-inputs/v1"
            and source_manifest.get("corpus_class") == "benchmark"
            and sha256_of_canonical(source_manifest).hex() == source_manifest_sha256
            and source_manifest["official_source_url"] == official_source_url
            and source_manifest["retrieval_date"] == retrieval_date
            and source_manifest["license"]["document_sha256"] == license_document_sha256
            and len(source_manifest["files"]) == len(members)
            and {item["sha256"] for item in source_manifest["files"]}
            == {digest for _, digest in members}
            and len({digest for _, digest in members}) == len(members)
            and isinstance(train, list)
            and isinstance(heldout, list)
            and bool(train)
            and bool(heldout)
            and len(set(train)) == len(train)
            and len(set(heldout)) == len(heldout)
            and not set(train) & set(heldout)
            and set(train) | set(heldout) == digests
        )
    except (KeyError, TypeError, ValueError):
        valid_manifest = False
    if not valid_manifest:
        raise PrivacyAdmissionError(
            "review must cover the complete digest-verified source manifest"
        )
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise PrivacyAdmissionError("human review needs an offset-aware timestamp")
    if reviewed_at > dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5):
        raise PrivacyAdmissionError("human review cannot be in the future")
    if not members or len({capture for capture, _ in members}) != len(members):
        raise PrivacyAdmissionError("review requires a unique non-empty capture inventory")
    for capture_id, expected in members:
        capture = repository.capture(capture_id)
        if capture is None or capture.deleted_at is not None or capture.blob_id.hex != expected:
            raise PrivacyAdmissionError("review does not match an available exact capture")
    scope = {
        "purpose": "retained reconstruction reference and visual evaluation",
        "source_manifest_sha256": source_manifest_sha256,
        "source_manifest": source_manifest,
        "retention": "source photographs, reconstructed assets and visual evidence",
        "reviewed_by_name": reviewed_by_name.strip(),
        "human_attestation": attestation,
    }
    receipts = []
    for capture_id, _ in members:
        authorization = authorize_benchmark_capture(
            repository,
            capture_id=capture_id,
            actor=actor,
            official_source_url=official_source_url,
            retrieval_date=retrieval_date,
            license_document_sha256=license_document_sha256,
            permitted_use=permitted_use,
            authorization_scope=scope,
            purpose="retained reconstruction reference and visual evaluation",
            authorized_at=reviewed_at,
        )
        screening = record_human_screening(
            repository,
            authorization_id=authorization.authorization_id,
            reviewed_by=actor,
            sensitive_regions=[],
            screened_at=reviewed_at,
        )
        receipts.append(
            {
                "capture_id": str(capture_id),
                "authorization_id": str(authorization.authorization_id),
                "screening_id": str(screening.screening_id),
                "screening_sha256": screening.receipt_digest.hex(),
            }
        )
    batch = IntakeBatch.open(repository, label="reviewed reconstruction reference")
    batch.declare_size(len(members))
    job_id = derivative_queue.enqueue(
        repository.connection,
        repository.workspace_id,
        batch_id=batch.batch_id,
        capture_ids=[capture for capture, _ in members],
    )
    return {"batch_id": str(batch.batch_id), "queued_job_id": str(job_id), "receipts": receipts}
