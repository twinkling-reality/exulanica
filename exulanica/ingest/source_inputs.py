"""Freeze and verify normalized inputs for queued scene work without conflating masks."""

from __future__ import annotations

import uuid
from typing import Any

from exulanica.epistemics.source_images import normalized_image
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.reconstruction_jobs import ClaimedSceneJob


def decoded_source_declarations(
    repository: IngestRepository, capture_ids: list[uuid.UUID]
) -> list[dict[str, Any]]:
    declarations = []
    for capture_id in capture_ids:
        capture = repository.capture(capture_id)
        if capture is None or capture.deleted_at is not None:
            raise PrivacyAdmissionError("scene source is absent or deleted")
        row = repository.connection.execute(
            "select media_type from blob where blob_sha256=%s", (capture.blob_id.digest,)
        ).fetchone()
        if row["media_type"] not in {"image/heif", "image/heic"}:
            continue
        source = normalized_image(
            repository.connection, repository.workspace_id, capture.blob_id.digest
        )
        if source is None or source.decoded is None:
            raise PrivacyAdmissionError("HEIF requires a current recorded decoded source")
        artifact = repository.connection.execute(
            "select decoded_source_current(%s,%s) as artifact_id",
            (repository.workspace_id, capture.blob_id.digest),
        ).fetchone()
        declarations.append(
            {
                "capture_ref": str(capture_id),
                "artifact_ref": str(artifact["artifact_id"]),
                "content_sha256": source.sha256.hex(),
                "media_type": source.media_type,
                "receipt": source.decoded,
            }
        )
    return declarations


def verify_decoded_sources(
    repository: IngestRepository, claimed: ClaimedSceneJob
) -> dict[uuid.UUID, tuple[BlobId, str]]:
    declared = claimed.build_inputs.get("decoded_sources", [])
    current = decoded_source_declarations(
        repository, [member.capture_id for member in claimed.members]
    )
    if declared != current:
        raise PrivacyAdmissionError(
            "decoded source declaration is stale or forged; rebuild and re-admit"
        )
    return {
        uuid.UUID(item["capture_ref"]): (
            BlobId.from_hex(item["content_sha256"]),
            item["media_type"],
        )
        for item in declared
    }


def training_decoded_lineage(declarations: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"capture_ref": item["capture_ref"], "receipt": item["receipt"]}
        for item in sorted(declarations, key=lambda value: value["capture_ref"])
    )
