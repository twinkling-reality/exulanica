"""The durable lease around one exact multi-photograph reconstruction input set."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Final

from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.evidence.blob import BlobId
from exulanica.evidence.scene import scene_id_for, scene_member_digest
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = [
    "MAX_SCENE_CLAIMS",
    "ClaimedSceneJob",
    "SceneJobMember",
    "active_scratch_keys",
    "cancelled_or_lost",
    "claim",
    "complete",
    "enqueue",
    "expire_exhausted",
    "fail",
    "heartbeat",
    "release_checkpointed",
]

MAX_SCENE_CLAIMS: Final = 3
_JOB_NAMESPACE: Final = uuid.UUID("d7af4526-f141-50d4-bc58-aa3786f35833")


def _policy_bytes(policy: dict[str, Any]) -> bytes:
    return canonical_json(policy)


def _build_input_bytes(build_inputs: dict[str, Any]) -> bytes:
    return canonical_json(build_inputs)


@dataclass(frozen=True, slots=True)
class SceneJobMember:
    capture_id: uuid.UUID
    ordinal: int
    blob_id: BlobId
    media_type: str


@dataclass(frozen=True, slots=True)
class ClaimedSceneJob:
    job_id: uuid.UUID
    scene_id: uuid.UUID
    member_digest: bytes
    selection_policy: dict[str, Any]
    selection_policy_digest: bytes
    build_inputs: dict[str, Any]
    build_input_digest: bytes
    privacy_admission_id: uuid.UUID
    privacy_admission_digest: bytes
    members: tuple[SceneJobMember, ...]
    attempts: int
    claim_token: uuid.UUID
    scratch_key: str | None
    reclaimed: bool


def enqueue(
    scope: WorkspaceScope,
    *,
    capture_ids: list[uuid.UUID],
    selection_policy: dict[str, Any],
    privacy_admission_id: uuid.UUID,
    privacy_admission_digest: bytes,
    build_inputs: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, bool]:
    """Queue one exact ordered set, or verify and reuse the identical queued question."""
    if not capture_ids or len(set(capture_ids)) != len(capture_ids):
        raise ValueError("a scene job needs a non-empty, duplicate-free capture list")
    policy_bytes = _policy_bytes(selection_policy)
    policy_digest = hashlib.sha256(policy_bytes).digest()
    inputs = build_inputs or {
        "profile": "exulanica.reconstruction-scene-build-input/manual-v0",
        "point_maps": [],
    }
    build_input_digest = hashlib.sha256(_build_input_bytes(inputs)).digest()
    scene_id = scene_id_for(capture_ids)
    member_digest = scene_member_digest(capture_ids)
    job_id = uuid.uuid5(
        _JOB_NAMESPACE,
        f"{scene_id}:{policy_digest.hex()}:{build_input_digest.hex()}:"
        f"{privacy_admission_digest.hex()}",
    )
    with scope.connection.transaction():
        cursor = scope.connection.execute(
            "insert into reconstruction_scene_job "
            "(job_id, workspace_id, scene_id, member_digest, selection_policy, "
            "selection_policy_digest,build_inputs,build_input_digest,scratch_key,"
            "privacy_admission_id,privacy_admission_digest) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (workspace_id,scene_id,selection_policy_digest,build_input_digest,"
            "privacy_admission_digest) "
            "do nothing",
            (
                job_id,
                scope.workspace_id,
                scene_id,
                member_digest,
                Jsonb(selection_policy),
                policy_digest,
                Jsonb(inputs),
                build_input_digest,
                f"{scope.workspace_id}/{job_id}",
                privacy_admission_id,
                privacy_admission_digest,
            ),
        )
        inserted = cursor.rowcount > 0
        if inserted:
            with scope.connection.cursor() as member_cursor:
                member_cursor.executemany(
                    "insert into reconstruction_scene_job_member "
                    "(workspace_id, job_id, capture_id, ordinal) values (%s, %s, %s, %s)",
                    [
                        (scope.workspace_id, job_id, capture_id, ordinal)
                        for ordinal, capture_id in enumerate(capture_ids)
                    ],
                )

        row = scope.connection.execute(
            "select job_id,member_digest,selection_policy,build_inputs,"
            "privacy_admission_id,privacy_admission_digest "
            "from reconstruction_scene_job where workspace_id=%s and scene_id=%s "
            "and selection_policy_digest=%s and build_input_digest=%s "
            "and privacy_admission_digest=%s",
            (
                scope.workspace_id,
                scene_id,
                policy_digest,
                build_input_digest,
                privacy_admission_digest,
            ),
        ).fetchone()
        members = scope.connection.execute(
            "select capture_id from reconstruction_scene_job_member "
            "where workspace_id = %s and job_id = %s order by ordinal, capture_id",
            (scope.workspace_id, job_id),
        ).fetchall()
        if (
            row is None
            or row["job_id"] != job_id
            or bytes(row["member_digest"]) != member_digest
            or dict(row["selection_policy"]) != selection_policy
            or dict(row["build_inputs"]) != inputs
            or row["privacy_admission_id"] != privacy_admission_id
            or bytes(row["privacy_admission_digest"]) != privacy_admission_digest
            or [member["capture_id"] for member in members] != capture_ids
        ):
            raise ValueError(
                "an existing reconstruction job disagrees with the requested input set"
            )
    return job_id, inserted


def active_scratch_keys(scope: WorkspaceScope) -> frozenset[str]:
    """Scratch protected by queued, held or still-retryable jobs in this workspace."""
    rows = scope.connection.execute(
        "select scratch_key from reconstruction_scene_job where workspace_id=%s "
        "and scratch_key is not null and (status in ('queued','running') "
        "or (status='failed' and attempts < %s))",
        (scope.workspace_id, MAX_SCENE_CLAIMS),
    ).fetchall()
    return frozenset(row["scratch_key"] for row in rows)


def expire_exhausted(scope: WorkspaceScope) -> int:
    """Make a dead final claim terminal so its sensitive scratch can be swept."""
    cursor = scope.connection.execute(
        "update reconstruction_scene_job set status='failed',claim_token=null,"
        "claimed_by=null,lease_expires_at=null,completed_at=coalesce(completed_at,now()),"
        "updated_at=now(),failure_class='claim_exhausted',"
        "failure_message='the final worker lease expired before completion' "
        "where workspace_id=%s and status='running' and lease_expires_at < now() "
        "and attempts >= %s",
        (scope.workspace_id, MAX_SCENE_CLAIMS),
    )
    return cursor.rowcount


def _claimed(scope: WorkspaceScope, row: dict[str, Any], *, reclaimed: bool) -> ClaimedSceneJob:
    members = scope.connection.execute(
        "select m.capture_id, m.ordinal, c.blob_sha256, b.media_type "
        "from reconstruction_scene_job_member m "
        "join capture c on c.workspace_id=m.workspace_id and c.capture_id=m.capture_id "
        "join blob b on b.blob_sha256=c.blob_sha256 "
        "where m.workspace_id=%s and m.job_id=%s order by m.ordinal,m.capture_id",
        (scope.workspace_id, row["job_id"]),
    ).fetchall()
    return ClaimedSceneJob(
        job_id=row["job_id"],
        scene_id=row["scene_id"],
        member_digest=bytes(row["member_digest"]),
        selection_policy=dict(row["selection_policy"]),
        selection_policy_digest=bytes(row["selection_policy_digest"]),
        build_inputs=dict(row["build_inputs"]),
        build_input_digest=bytes(row["build_input_digest"]),
        privacy_admission_id=row["privacy_admission_id"],
        privacy_admission_digest=bytes(row["privacy_admission_digest"]),
        members=tuple(
            SceneJobMember(
                capture_id=member["capture_id"],
                ordinal=int(member["ordinal"]),
                blob_id=BlobId(bytes(member["blob_sha256"])),
                media_type=member["media_type"],
            )
            for member in members
        ),
        attempts=int(row["attempts"]),
        claim_token=row["claim_token"],
        scratch_key=row["scratch_key"],
        reclaimed=reclaimed,
    )


def claim(scope: WorkspaceScope, *, worker: str, lease_seconds: float) -> ClaimedSceneJob | None:
    """Claim expired work first, then queued or retryable work, with a rotated token."""
    scope.connection.execute(
        "update reconstruction_scene_job set status='cancelled',claim_token=null,"
        "claimed_by=null,lease_expires_at=null,completed_at=coalesce(completed_at,now()),"
        "updated_at=now(),failure_class='privacy_withdrawn',"
        "failure_message='the exact privacy admission is no longer eligible' "
        "where workspace_id=%s and status in ('queued','failed') "
        "and not privacy_admission_allows_job(workspace_id,job_id)",
        (scope.workspace_id,),
    )
    reclaimed = True
    row = scope.connection.execute(
        "update reconstruction_scene_job set status='running', attempts=attempts+1, "
        "claim_token=gen_random_uuid(), claimed_by=%s, "
        "lease_expires_at=now()+make_interval(secs => %s), updated_at=now(), "
        "failure_class=null, failure_message=null "
        "where job_id=(select job_id from reconstruction_scene_job "
        "where workspace_id=%s and status='running' and lease_expires_at < now() "
        "and privacy_admission_allows_job(workspace_id,job_id) "
        "and attempts < %s order by available_at,created_at,job_id "
        "for update skip locked limit 1) "
        "returning job_id,scene_id,member_digest,selection_policy,selection_policy_digest,"
        "build_inputs,build_input_digest,privacy_admission_id,privacy_admission_digest,"
        "attempts,claim_token,scratch_key",
        (worker, lease_seconds, scope.workspace_id, MAX_SCENE_CLAIMS),
    ).fetchone()
    if row is None:
        reclaimed = False
        row = scope.connection.execute(
            "update reconstruction_scene_job set status='running', attempts=attempts+1, "
            "claim_token=gen_random_uuid(), claimed_by=%s, "
            "lease_expires_at=now()+make_interval(secs => %s), updated_at=now(), "
            "failure_class=null, failure_message=null "
            "where job_id=(select job_id from reconstruction_scene_job "
            "where workspace_id=%s and status in ('queued','failed') and available_at <= now() "
            "and attempts < %s and not tombstone_blocks_reconstruction_job(workspace_id,job_id) "
            "and privacy_admission_allows_job(workspace_id,job_id) "
            "order by available_at,created_at,job_id for update skip locked limit 1) "
            "returning job_id,scene_id,member_digest,selection_policy,selection_policy_digest,"
            "build_inputs,build_input_digest,privacy_admission_id,privacy_admission_digest,"
            "attempts,claim_token,scratch_key",
            (worker, lease_seconds, scope.workspace_id, MAX_SCENE_CLAIMS),
        ).fetchone()
    return None if row is None else _claimed(scope, row, reclaimed=reclaimed)


def heartbeat(
    scope: WorkspaceScope,
    *,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_seconds: float,
) -> bool:
    cursor = scope.connection.execute(
        "update reconstruction_scene_job set "
        "lease_expires_at=now()+make_interval(secs => %s),updated_at=now() "
        "where workspace_id=%s and job_id=%s and status='running' and claim_token=%s",
        (lease_seconds, scope.workspace_id, job_id, claim_token),
    )
    return cursor.rowcount > 0


def cancelled_or_lost(scope: WorkspaceScope, *, job_id: uuid.UUID, claim_token: uuid.UUID) -> bool:
    row = scope.connection.execute(
        "select status,claim_token,tombstone_blocks_reconstruction_job(workspace_id,job_id) "
        "as blocked,privacy_admission_allows_job(workspace_id,job_id) as privacy_allowed "
        "from reconstruction_scene_job where workspace_id=%s and job_id=%s",
        (scope.workspace_id, job_id),
    ).fetchone()
    return bool(
        row is None
        or row["status"] != "running"
        or row["claim_token"] != claim_token
        or row["blocked"]
        or not row["privacy_allowed"]
    )


def complete(
    scope: WorkspaceScope,
    *,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    scratch_key: str,
    pose_manifest_digest: bytes,
    pose_receipt_artifact_id: uuid.UUID,
    placement_artifact_id: uuid.UUID,
    gate_artifact_id: uuid.UUID,
    rung_assertion_id: uuid.UUID,
) -> bool:
    """Close a held job only after every durable output was accepted in this transaction."""
    cursor = scope.connection.execute(
        "update reconstruction_scene_job set status='succeeded',scratch_key=%s,"
        "pose_manifest_digest=%s,pose_receipt_artifact_id=%s,placement_artifact_id=%s,"
        "gate_artifact_id=%s,rung_assertion_id=%s,"
        "claim_token=null,claimed_by=null,lease_expires_at=null,"
        "completed_at=now(),updated_at=now(),failure_class=null,failure_message=null "
        "where workspace_id=%s and job_id=%s and status='running' and claim_token=%s "
        "and not tombstone_blocks_reconstruction_job(workspace_id,job_id) "
        "and privacy_admission_allows_job(workspace_id,job_id)",
        (
            scratch_key,
            pose_manifest_digest,
            pose_receipt_artifact_id,
            placement_artifact_id,
            gate_artifact_id,
            rung_assertion_id,
            scope.workspace_id,
            job_id,
            claim_token,
        ),
    )
    if cursor.rowcount > 0:
        scope.connection.execute(
            "update reconstruction_scene set current_job_id=%s "
            "where workspace_id=%s and scene_id=(select scene_id "
            "from reconstruction_scene_job where workspace_id=%s and job_id=%s)",
            (job_id, scope.workspace_id, scope.workspace_id, job_id),
        )
    return cursor.rowcount > 0


def fail(
    scope: WorkspaceScope,
    *,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    failure_class: str,
    failure_message: str,
    retry_delay_seconds: float,
) -> bool:
    """Record a retryable failure, becoming terminal after the bounded claim count."""
    cursor = scope.connection.execute(
        "update reconstruction_scene_job set status='failed',available_at=now()+"
        "make_interval(secs => %s),claim_token=null,claimed_by=null,lease_expires_at=null,"
        "completed_at=case when attempts >= %s then now() else null end,updated_at=now(),"
        "failure_class=%s,failure_message=%s "
        "where workspace_id=%s and job_id=%s and status='running' and claim_token=%s",
        (
            retry_delay_seconds,
            MAX_SCENE_CLAIMS,
            failure_class,
            failure_message[:2000],
            scope.workspace_id,
            job_id,
            claim_token,
        ),
    )
    return cursor.rowcount > 0


def release_checkpointed(
    scope: WorkspaceScope,
    *,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    retry_delay_seconds: float,
) -> bool:
    """Release verified durable progress without consuming the failure/reclaim budget."""
    cursor = scope.connection.execute(
        "update reconstruction_scene_job set status='queued',attempts=greatest(0,attempts-1),"
        "available_at=now()+make_interval(secs => %s),claim_token=null,claimed_by=null,"
        "lease_expires_at=null,completed_at=null,updated_at=now(),"
        "failure_class='training_checkpointed',failure_message='training checkpoint is resumable' "
        "where workspace_id=%s and job_id=%s and status='running' and claim_token=%s "
        "and not tombstone_blocks_reconstruction_job(workspace_id,job_id) "
        "and privacy_admission_allows_job(workspace_id,job_id)",
        (retry_delay_seconds, scope.workspace_id, job_id, claim_token),
    )
    return cursor.rowcount > 0
