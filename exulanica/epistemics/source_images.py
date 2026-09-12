"""Persisted image selection and normalized lineage shared by readers and producers."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from exulanica.canonical import canonical_json
from exulanica.reconstruction.source_lineage import verify_decoded_receipt


@dataclass(frozen=True, slots=True)
class SelectedImage:
    sha256: bytes
    media_type: str
    kind: str
    decoded: dict[str, Any] | None = None


def image_digest(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    original_digest: bytes,
    at: dt.datetime,
    *,
    original: bool = False,
) -> bytes | None:
    row = connection.execute(
        "select asset_image_source(%s,%s,%s,%s) as digest",
        (workspace, original_digest, at, original),
    ).fetchone()
    return bytes(row["digest"]) if row["digest"] is not None else None


def decoded_receipt_for(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    original: bytes,
    output: bytes,
    *,
    current: bool = False,
    artifact_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    rows = connection.execute(
        "select d.receipt_record,d.receipt_canonical,d.receipt_sha256 "
        "from decoded_source d join artifact a on a.artifact_id=d.artifact_id "
        "where d.workspace_id=%s and a.workspace_id=d.workspace_id and d.source_sha256=%s "
        "and d.output_sha256=%s and a.kind='decoded_source' "
        "and a.source_blob_sha256=d.source_sha256 "
        "and a.content_sha256=d.output_sha256 and a.purged_at is null and not a.needs_repair "
        "and a.storage_key is not null and (%s::uuid is null or d.artifact_id=%s) "
        "and (%s=false or "
        "d.artifact_id=decoded_source_current(d.workspace_id,d.source_sha256))",
        (workspace, original, output, artifact_id, artifact_id, current),
    ).fetchall()
    receipts = []
    for row in rows:
        record = row["receipt_record"]
        if canonical_json(record) != bytes(row["receipt_canonical"]):
            raise ValueError("decoded source stored canonical bytes disagree")
        envelope = {"record": record, "record_sha256": bytes(row["receipt_sha256"]).hex()}
        verify_decoded_receipt(envelope, source_sha256=original.hex(), output_sha256=output.hex())
        if envelope not in receipts:
            receipts.append(envelope)
    if len(receipts) > 1:
        raise ValueError("decoded source provenance is ambiguous")
    return receipts[0] if receipts else None


def normalized_image(
    connection: psycopg.Connection, workspace: uuid.UUID, original: bytes
) -> SelectedImage | None:
    row = connection.execute(
        "select output_sha256 from decoded_source where workspace_id=%s "
        "and artifact_id=decoded_source_current(%s,%s)",
        (workspace, workspace, original),
    ).fetchone()
    if row is None:
        return None
    digest = bytes(row["output_sha256"])
    receipt = decoded_receipt_for(connection, workspace, original, digest, current=True)
    return SelectedImage(digest, "image/png", "decoded", receipt) if receipt else None


def selected_image(
    connection: psycopg.Connection, workspace: uuid.UUID, original: bytes, at: dt.datetime
) -> SelectedImage | None:
    digest = image_digest(connection, workspace, original, at)
    if digest is None:
        return None
    if digest == original:
        row = connection.execute(
            "select media_type from blob where blob_sha256=%s", (original,)
        ).fetchone()
        return SelectedImage(digest, row["media_type"], "original") if row else None
    normalized = normalized_image(connection, workspace, original)
    if normalized is not None and normalized.sha256 == digest:
        return normalized
    # SQL only returns another digest through a current privacy mask. Keep its predecessor
    # distinct from the original, and never describe a normalized PNG as a JPEG mask.
    row = connection.execute(
        "select read_source_sha256 from artifact where workspace_id=%s "
        "and source_blob_sha256=%s and content_sha256=%s and kind='masked_source' "
        "and purged_at is null and not needs_repair order by artifact_id limit 1",
        (workspace, original, digest),
    ).fetchone()
    if row is None:
        return None
    predecessor = row["read_source_sha256"]
    receipt = (
        None
        if predecessor is None
        else decoded_receipt_for(connection, workspace, original, bytes(predecessor), current=True)
    )
    if predecessor is not None and receipt is None:
        return None
    return SelectedImage(digest, "image/jpeg", "masked", receipt)


def decoded_for_artifact(
    connection: psycopg.Connection, workspace: uuid.UUID, artifact_id: uuid.UUID
) -> dict[str, Any] | None:
    """Read the exact historical decoder input recorded by a producer, never today's selection."""
    rows = connection.execute(
        "select d.artifact_id,d.source_sha256,d.output_sha256 from artifact a "
        "join pipeline_event e on e.event_id=a.produced_by_event "
        "join pipeline_run er on er.run_id=e.run_id and er.workspace_id=a.workspace_id "
        "join decoded_source d on d.workspace_id=a.workspace_id "
        "and d.artifact_id=any(e.input_artifact_ids) "
        "where a.workspace_id=%s and a.artifact_id=%s and d.source_sha256=a.source_blob_sha256",
        (workspace, artifact_id),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("artifact binds multiple decoded predecessors")
    if not rows:
        return None
    row = rows[0]
    return decoded_receipt_for(
        connection,
        workspace,
        bytes(row["source_sha256"]),
        bytes(row["output_sha256"]),
        artifact_id=row["artifact_id"],
    )
