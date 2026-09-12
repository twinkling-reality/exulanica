"""Persist normalized image receipts beside their workspace-owned artifact."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.reconstruction.source_lineage import verify_decoded_record


def record_decoded(scope: WorkspaceScope, artifact_id: uuid.UUID, record: dict[str, Any]) -> None:
    verify_decoded_record(
        record, source_sha256=record["source_sha256"], output_sha256=record["output_sha256"]
    )
    canonical = canonical_json(record)
    scope.connection.execute(
        "insert into decoded_source (workspace_id,artifact_id,source_sha256,output_sha256,"
        "receipt_record,receipt_canonical,receipt_sha256) values (%s,%s,%s,%s,%s,%s,%s) "
        "on conflict (workspace_id,artifact_id) do nothing",
        (
            scope.workspace_id,
            artifact_id,
            bytes.fromhex(record["source_sha256"]),
            bytes.fromhex(record["output_sha256"]),
            Jsonb(record),
            canonical,
            hashlib.sha256(canonical).digest(),
        ),
    )
    row = scope.connection.execute(
        "select receipt_canonical from decoded_source where workspace_id=%s and artifact_id=%s",
        (scope.workspace_id, artifact_id),
    ).fetchone()
    if row is None or bytes(row["receipt_canonical"]) != canonical:
        raise ValueError("stored decoded source receipt disagrees")
