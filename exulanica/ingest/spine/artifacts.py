"""What a stage produced, under the identity key that says it is the same output.

``idempotency_key`` is what the output should be, computed before the stage runs.
``content_sha256`` is what it turned out to be. They are separate columns because a
deterministic stage that disagrees with itself is a fact worth recording rather than absorbing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from exulanica.db.guards import terminal_if_tombstoned
from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = [
    "ArtifactRow",
    "CaptureArtifactRow",
    "current_for_captures",
    "exact_for_captures",
    "find",
    "insert",
    "insert_scene",
    "mark_needs_repair",
]


@dataclass(frozen=True, slots=True)
class ArtifactRow:
    artifact_id: uuid.UUID
    kind: str
    stage_key: str
    stage_version: int
    idempotency_key: str
    content_sha256: bytes | None
    storage_key: str | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class CaptureArtifactRow:
    capture_id: uuid.UUID
    artifact_id: uuid.UUID
    content_sha256: bytes
    storage_key: str
    byte_size: int
    privacy_screening_id: uuid.UUID | None


def current_for_captures(
    scope: WorkspaceScope, *, capture_ids: list[uuid.UUID], kind: str
) -> dict[uuid.UUID, CaptureArtifactRow]:
    """The current complete artifact of ``kind`` for each requested live capture that has one."""
    if not capture_ids:
        return {}
    rows = scope.connection.execute(
        "select distinct on (c.capture_id) c.capture_id,a.artifact_id,a.content_sha256,"
        "a.storage_key,a.byte_size,a.privacy_screening_id from capture c join artifact a "
        "on a.workspace_id=c.workspace_id and a.source_blob_sha256=c.blob_sha256 "
        "where c.workspace_id=%s and c.capture_id=any(%s::uuid[]) and c.deleted_at is null "
        "and a.kind=%s and a.superseded_by is null and a.purged_at is null "
        "and a.content_sha256 is not null and a.storage_key is not null "
        "and a.byte_size is not null "
        "and (a.kind <> 'point_map' or (a.privacy_screening_id is not null and "
        "privacy_screening_allows_capture(c.workspace_id,c.capture_id,"
        "a.privacy_screening_id))) "
        "and not tombstone_blocks_capture(c.workspace_id,c.capture_id) "
        "order by c.capture_id,a.stage_version desc,a.created_at desc,a.artifact_id",
        (scope.workspace_id, capture_ids, kind),
    ).fetchall()
    return {
        row["capture_id"]: CaptureArtifactRow(
            capture_id=row["capture_id"],
            artifact_id=row["artifact_id"],
            content_sha256=bytes(row["content_sha256"]),
            storage_key=row["storage_key"],
            byte_size=int(row["byte_size"]),
            privacy_screening_id=row["privacy_screening_id"],
        )
        for row in rows
    }


def exact_for_captures(
    scope: WorkspaceScope,
    *,
    artifact_ids_by_capture: dict[uuid.UUID, uuid.UUID],
    kind: str,
) -> dict[uuid.UUID, CaptureArtifactRow]:
    """Resolve exact immutable build inputs, including artifacts later superseded.

    A queued scene names artifact ids and content hashes. Re-resolving the current artifact at
    execution time would change the build after it was admitted, so this query accepts only the
    named row and still applies the live-capture, purge and tombstone boundaries.
    """
    if not artifact_ids_by_capture:
        return {}
    capture_ids = list(artifact_ids_by_capture)
    artifact_ids = list(artifact_ids_by_capture.values())
    rows = scope.connection.execute(
        "select c.capture_id,a.artifact_id,a.content_sha256,a.storage_key,a.byte_size,"
        "a.privacy_screening_id "
        "from capture c join artifact a on a.workspace_id=c.workspace_id "
        "and a.source_blob_sha256=c.blob_sha256 where c.workspace_id=%s "
        "and c.capture_id=any(%s::uuid[]) and a.artifact_id=any(%s::uuid[]) "
        "and c.deleted_at is null and a.kind=%s and a.purged_at is null "
        "and a.content_sha256 is not null and a.storage_key is not null "
        "and a.byte_size is not null "
        "and (a.kind <> 'point_map' or (a.privacy_screening_id is not null and "
        "privacy_screening_allows_capture(c.workspace_id,c.capture_id,"
        "a.privacy_screening_id))) "
        "and not tombstone_blocks_capture(c.workspace_id,c.capture_id)",
        (scope.workspace_id, capture_ids, artifact_ids, kind),
    ).fetchall()
    return {
        row["capture_id"]: CaptureArtifactRow(
            capture_id=row["capture_id"],
            artifact_id=row["artifact_id"],
            content_sha256=bytes(row["content_sha256"]),
            storage_key=row["storage_key"],
            byte_size=int(row["byte_size"]),
            privacy_screening_id=row["privacy_screening_id"],
        )
        for row in rows
        if artifact_ids_by_capture.get(row["capture_id"]) == row["artifact_id"]
    }


def find(scope: WorkspaceScope, idempotency_key: str) -> ArtifactRow | None:
    """The live artifact under this identity key, or None. Purged rows are not live."""
    row = scope.connection.execute(
        "select artifact_id, kind, stage_key, stage_version, idempotency_key, "
        "content_sha256, storage_key, byte_size from artifact "
        "where workspace_id = %s and idempotency_key = %s and purged_at is null",
        (scope.workspace_id, idempotency_key),
    ).fetchone()
    if row is None:
        return None
    return ArtifactRow(
        artifact_id=row["artifact_id"],
        kind=row["kind"],
        stage_key=row["stage_key"],
        stage_version=row["stage_version"],
        idempotency_key=row["idempotency_key"],
        content_sha256=bytes(row["content_sha256"]) if row["content_sha256"] else None,
        storage_key=row["storage_key"],
        byte_size=row["byte_size"],
    )


def insert(
    scope: WorkspaceScope,
    *,
    artifact_id: uuid.UUID,
    kind: str,
    source_blob: BlobId,
    stage_key: str,
    stage_version: int,
    params_digest: bytes,
    input_digest: bytes,
    idempotency_key: str,
    content_sha256: bytes,
    storage_key: str,
    byte_size: int,
    produced_by_event: uuid.UUID | None,
    privacy_screening_id: uuid.UUID | None = None,
    read_source_sha256: bytes | None = None,
) -> bool:
    """Insert a derivative. Returns False when another worker already produced it.

    Never an update. A new ``stage_version`` produces a new row and marks the old one superseded,
    so old citations, old anchor resolutions and old Assembly Replays stay intact.
    """
    # TERMINAL, like every other write the tombstone guards cover. Migration 0011 refuses a
    # derivative of tombstoned bytes, and without this translation the refusal surfaces as an
    # ordinary integrity error: the run is recorded as FAILED, and a failed run is one a worker
    # retries, which is an unbounded loop against a photograph the user deleted.
    with terminal_if_tombstoned():
        cursor = scope.connection.execute(
            "insert into artifact (artifact_id, workspace_id, kind, source_blob_sha256, "
            "stage_key, stage_version, params_digest, input_digest, idempotency_key, "
            "content_sha256, storage_key, byte_size, produced_by_event, privacy_screening_id, "
            "read_source_sha256) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (workspace_id, idempotency_key) do nothing",
            (
                artifact_id,
                scope.workspace_id,
                kind,
                source_blob.digest,
                stage_key,
                stage_version,
                params_digest,
                input_digest,
                idempotency_key,
                content_sha256,
                storage_key,
                byte_size,
                produced_by_event,
                privacy_screening_id,
                read_source_sha256,
            ),
        )
    return cursor.rowcount > 0


def insert_scene(
    scope: WorkspaceScope,
    *,
    artifact_id: uuid.UUID,
    kind: str,
    scene_id: uuid.UUID,
    stage_key: str,
    stage_version: int,
    params_digest: bytes,
    input_digest: bytes,
    idempotency_key: str,
    content_sha256: bytes,
    storage_key: str,
    byte_size: int,
    produced_by_event: uuid.UUID | None,
) -> bool:
    """Insert a derivative whose subject is a complete reconstruction scene.

    Scene artifacts use the same immutable identity and content fields as single-photograph
    artifacts. Their subject is ``scene_id`` and ``source_blob_sha256`` remains NULL. The
    database constraint in migration 0024 makes the two subject forms exclusive, and its
    tombstone trigger refuses this insert when deletion reaches any scene member.
    """
    with terminal_if_tombstoned():
        cursor = scope.connection.execute(
            "insert into artifact (artifact_id, workspace_id, kind, scene_id, stage_key, "
            "stage_version, params_digest, input_digest, idempotency_key, content_sha256, "
            "storage_key, byte_size, produced_by_event) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (workspace_id, idempotency_key) do nothing",
            (
                artifact_id,
                scope.workspace_id,
                kind,
                scene_id,
                stage_key,
                stage_version,
                params_digest,
                input_digest,
                idempotency_key,
                content_sha256,
                storage_key,
                byte_size,
                produced_by_event,
            ),
        )
    return cursor.rowcount > 0


def mark_needs_repair(scope: WorkspaceScope, artifact_id: uuid.UUID) -> None:
    """Flag an artifact whose bytes are gone and cannot be reproduced.

    Set when a recompute of a stage declared deterministic does not reproduce the stored content
    hash *and* the stored bytes are absent. The row is not rewritten to point at the new bytes:
    the identity key names the old content, and quietly redefining what it names would make every
    citation and replay that used it wrong without saying so.
    """
    scope.connection.execute(
        "update artifact set needs_repair = true where workspace_id = %s and artifact_id = %s",
        (scope.workspace_id, artifact_id),
    )
