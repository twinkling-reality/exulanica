"""Durable authorization and fail-closed privacy receipts for reconstruction."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine.artifacts import CaptureArtifactRow, exact_for_captures
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = [
    "PrivacyAdmissionRow",
    "PrivacyScreeningRow",
    "ReconstructionAuthorizationRow",
    "admit",
    "authorization",
    "current_inputs",
    "insert_authorization",
    "insert_screening",
    "latest_screening",
    "mask_is_current",
    "screening",
    "screening_allows",
    "screening_allows_observation",
    "screening_masks",
    "selected_masks",
]


@dataclass(frozen=True, slots=True)
class ReconstructionAuthorizationRow:
    authorization_id: uuid.UUID
    capture_id: uuid.UUID
    source_sha256: bytes
    corpus_class: str
    authorization_scope: dict[str, Any]
    evidence_digest: bytes
    valid_until: dt.datetime | None


@dataclass(frozen=True, slots=True)
class PrivacyScreeningRow:
    screening_id: uuid.UUID
    authorization_id: uuid.UUID
    capture_id: uuid.UUID
    source_sha256: bytes
    corpus_class: str
    eligibility_state: str
    authorization_scope: dict[str, Any]
    policy_version: str
    policy_params_digest: bytes
    receipt_digest: bytes
    screened_at: dt.datetime
    valid_until: dt.datetime | None


@dataclass(frozen=True, slots=True)
class PrivacyAdmissionRow:
    admission_id: uuid.UUID
    scene_id: uuid.UUID
    member_digest: bytes
    corpus_class: str
    eligibility_state: str
    blocking_reasons: tuple[str, ...]
    policy_version: str
    policy_params_digest: bytes
    authorization_scope: dict[str, Any]
    admission_digest: bytes
    valid_until: dt.datetime | None


def insert_authorization(
    scope: WorkspaceScope,
    *,
    authorization_id: uuid.UUID,
    capture_id: uuid.UUID,
    source_sha256: BlobId,
    corpus_class: str,
    purpose: str,
    authorization_scope: dict[str, Any],
    authorization_evidence: dict[str, Any],
    authorization_record: dict[str, Any],
    authorization_canonical: bytes,
    evidence_digest: bytes,
    synthetic_manifest_digest: bytes | None,
    authorized_by: uuid.UUID,
    authorized_at: dt.datetime,
    valid_until: dt.datetime | None,
) -> ReconstructionAuthorizationRow:
    """Insert an immutable exact-source authorization, or return its identical row."""
    scope.connection.execute(
        "insert into capture_reconstruction_authorization "
        "(authorization_id,workspace_id,capture_id,source_sha256,corpus_class,purpose,"
        "authorization_scope,authorization_evidence,authorization_record,"
        "authorization_canonical,evidence_digest,synthetic_manifest_digest,authorized_by,"
        "authorized_at,valid_until) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "on conflict (authorization_id) do nothing",
        (
            authorization_id,
            scope.workspace_id,
            capture_id,
            source_sha256.digest,
            corpus_class,
            purpose,
            Jsonb(authorization_scope),
            Jsonb(authorization_evidence),
            Jsonb(authorization_record),
            authorization_canonical,
            evidence_digest,
            synthetic_manifest_digest,
            authorized_by,
            authorized_at,
            valid_until,
        ),
    )
    row = authorization(scope, authorization_id)
    if row is None or row != ReconstructionAuthorizationRow(
        authorization_id=authorization_id,
        capture_id=capture_id,
        source_sha256=source_sha256.digest,
        corpus_class=corpus_class,
        authorization_scope=authorization_scope,
        evidence_digest=evidence_digest,
        valid_until=valid_until,
    ):
        raise ValueError("an existing reconstruction authorization disagrees with this record")
    return row


def authorization(
    scope: WorkspaceScope, authorization_id: uuid.UUID
) -> ReconstructionAuthorizationRow | None:
    row = scope.connection.execute(
        "select authorization_id,capture_id,source_sha256,corpus_class,"
        "authorization_scope,evidence_digest,valid_until "
        "from capture_reconstruction_authorization "
        "where workspace_id=%s and authorization_id=%s",
        (scope.workspace_id, authorization_id),
    ).fetchone()
    if row is None:
        return None
    return ReconstructionAuthorizationRow(
        authorization_id=row["authorization_id"],
        capture_id=row["capture_id"],
        source_sha256=bytes(row["source_sha256"]),
        corpus_class=row["corpus_class"],
        authorization_scope=dict(row["authorization_scope"]),
        evidence_digest=bytes(row["evidence_digest"]),
        valid_until=row["valid_until"],
    )


def insert_screening(
    scope: WorkspaceScope,
    *,
    screening_id: uuid.UUID,
    authorization_id: uuid.UUID,
    capture_id: uuid.UUID,
    source_sha256: BlobId,
    screening_method: str,
    human_review_required: bool,
    reviewed_by: uuid.UUID | None,
    sensitive_regions: list[dict[str, Any]],
    eligibility_state: str,
    blocking_reasons: list[str],
    policy_version: str,
    policy_params_digest: bytes,
    authorization_scope: dict[str, Any],
    screened_at: dt.datetime,
    valid_until: dt.datetime | None,
    receipt_record: dict[str, Any],
    receipt_canonical: bytes,
    receipt_digest: bytes,
) -> PrivacyScreeningRow:
    """Insert one immutable screening result. Masking is intentionally not accepted yet."""
    scope.connection.execute(
        "insert into reconstruction_privacy_screening "
        "(screening_id,workspace_id,authorization_id,capture_id,source_sha256,"
        "screening_method,model_id,model_revision,human_review_required,reviewed_by,"
        "sensitive_regions,mask_artifacts,eligibility_state,blocking_reasons,"
        "policy_version,policy_params_digest,authorization_scope,screened_at,valid_until,"
        "receipt_record,receipt_canonical,receipt_digest) "
        "values (%s,%s,%s,%s,%s,%s,null,null,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "on conflict (screening_id) do nothing",
        (
            screening_id,
            scope.workspace_id,
            authorization_id,
            capture_id,
            source_sha256.digest,
            screening_method,
            human_review_required,
            reviewed_by,
            Jsonb(sensitive_regions),
            Jsonb(receipt_record.get("mask_artifacts", [])),
            eligibility_state,
            Jsonb(blocking_reasons),
            policy_version,
            policy_params_digest,
            Jsonb(authorization_scope),
            screened_at,
            valid_until,
            Jsonb(receipt_record),
            receipt_canonical,
            receipt_digest,
        ),
    )
    row = screening(scope, screening_id)
    if row is None or row.receipt_digest != receipt_digest:
        raise ValueError("an existing privacy screening disagrees with this receipt")
    return row


def screening(scope: WorkspaceScope, screening_id: uuid.UUID) -> PrivacyScreeningRow | None:
    row = scope.connection.execute(
        "select s.screening_id,s.authorization_id,s.capture_id,s.source_sha256,"
        "a.corpus_class,s.eligibility_state,s.authorization_scope,s.policy_version,"
        "s.policy_params_digest,s.receipt_digest,s.screened_at,s.valid_until "
        "from reconstruction_privacy_screening s "
        "join capture_reconstruction_authorization a "
        "on a.workspace_id=s.workspace_id and a.authorization_id=s.authorization_id "
        "where s.workspace_id=%s and s.screening_id=%s",
        (scope.workspace_id, screening_id),
    ).fetchone()
    if row is None:
        return None
    return PrivacyScreeningRow(
        screening_id=row["screening_id"],
        authorization_id=row["authorization_id"],
        capture_id=row["capture_id"],
        source_sha256=bytes(row["source_sha256"]),
        corpus_class=row["corpus_class"],
        eligibility_state=row["eligibility_state"],
        authorization_scope=dict(row["authorization_scope"]),
        policy_version=row["policy_version"],
        policy_params_digest=bytes(row["policy_params_digest"]),
        receipt_digest=bytes(row["receipt_digest"]),
        screened_at=row["screened_at"],
        valid_until=row["valid_until"],
    )


def screening_allows(scope: WorkspaceScope, capture_id: uuid.UUID, screening_id: uuid.UUID) -> bool:
    row = scope.connection.execute(
        "select privacy_screening_allows_capture(%s,%s,%s) as allowed",
        (scope.workspace_id, capture_id, screening_id),
    ).fetchone()
    assert row is not None
    return bool(row["allowed"])


def screening_allows_observation(
    scope: WorkspaceScope, capture_id: uuid.UUID, screening_id: uuid.UUID
) -> bool:
    """Whether this receipt permits showing the photograph to a detector.

    A different question from :func:`screening_allows`, and a different SQL function, so a caller
    cannot reach geometry with a receipt that only ever permitted looking.
    """
    row = scope.connection.execute(
        "select privacy_screening_allows_observation(%s,%s,%s) as allowed",
        (scope.workspace_id, capture_id, screening_id),
    ).fetchone()
    assert row is not None
    return bool(row["allowed"])


def latest_screening(scope: WorkspaceScope, capture_id: uuid.UUID) -> PrivacyScreeningRow | None:
    row = scope.connection.execute(
        "select s.screening_id from reconstruction_privacy_screening s "
        "where s.workspace_id=%s and s.capture_id=%s "
        "and privacy_screening_allows_capture(s.workspace_id,s.capture_id,s.screening_id) "
        "order by s.screened_at desc,s.screening_id desc limit 1",
        (scope.workspace_id, capture_id),
    ).fetchone()
    return None if row is None else screening(scope, row["screening_id"])


def admit(
    scope: WorkspaceScope,
    *,
    admission_id: uuid.UUID,
    scene_id: uuid.UUID,
    member_digest: bytes,
    corpus_class: str,
    eligibility_state: str,
    blocking_reasons: list[str],
    policy_version: str,
    policy_params_digest: bytes,
    authorization_scope: dict[str, Any],
    admitted_at: dt.datetime,
    valid_until: dt.datetime | None,
    admission_record: dict[str, Any],
    admission_canonical: bytes,
    admission_digest: bytes,
    members: list[tuple[uuid.UUID, BlobId, uuid.UUID | None, uuid.UUID | None]],
) -> PrivacyAdmissionRow:
    """Persist one decision over the exact ordered member set in one transaction."""
    with scope.connection.transaction():
        scope.connection.execute(
            "insert into reconstruction_privacy_admission "
            "(admission_id,workspace_id,scene_id,member_digest,corpus_class,"
            "eligibility_state,blocking_reasons,policy_version,policy_params_digest,"
            "authorization_scope,admitted_at,valid_until,admission_record,"
            "admission_canonical,admission_digest) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (admission_id) do nothing",
            (
                admission_id,
                scope.workspace_id,
                scene_id,
                member_digest,
                corpus_class,
                eligibility_state,
                Jsonb(blocking_reasons),
                policy_version,
                policy_params_digest,
                Jsonb(authorization_scope),
                admitted_at,
                valid_until,
                Jsonb(admission_record),
                admission_canonical,
                admission_digest,
            ),
        )
        with scope.connection.cursor() as cursor:
            cursor.executemany(
                "insert into reconstruction_privacy_admission_member "
                "(workspace_id,admission_id,capture_id,ordinal,source_sha256,"
                "authorization_id,screening_id) values (%s,%s,%s,%s,%s,%s,%s) "
                "on conflict (workspace_id,admission_id,capture_id) do nothing",
                [
                    (
                        scope.workspace_id,
                        admission_id,
                        capture_id,
                        ordinal,
                        source_sha256.digest,
                        authorization_id,
                        screening_id,
                    )
                    for ordinal, (
                        capture_id,
                        source_sha256,
                        authorization_id,
                        screening_id,
                    ) in enumerate(members)
                ],
            )
        row = scope.connection.execute(
            "select admission_id,scene_id,member_digest,corpus_class,eligibility_state,"
            "blocking_reasons,policy_version,policy_params_digest,authorization_scope,"
            "admission_digest,valid_until from reconstruction_privacy_admission "
            "where workspace_id=%s and admission_id=%s",
            (scope.workspace_id, admission_id),
        ).fetchone()
        stored_members = scope.connection.execute(
            "select capture_id,source_sha256,authorization_id,screening_id "
            "from reconstruction_privacy_admission_member "
            "where workspace_id=%s and admission_id=%s order by ordinal",
            (scope.workspace_id, admission_id),
        ).fetchall()
        expected = [
            (capture_id, source.digest, authorization_id, screening_id)
            for capture_id, source, authorization_id, screening_id in members
        ]
        actual = [
            (
                item["capture_id"],
                bytes(item["source_sha256"]),
                item["authorization_id"],
                item["screening_id"],
            )
            for item in stored_members
        ]
        if row is None or bytes(row["admission_digest"]) != admission_digest or actual != expected:
            raise ValueError("an existing privacy admission disagrees with this exact set")
    return PrivacyAdmissionRow(
        admission_id=row["admission_id"],
        scene_id=row["scene_id"],
        member_digest=bytes(row["member_digest"]),
        corpus_class=row["corpus_class"],
        eligibility_state=row["eligibility_state"],
        blocking_reasons=tuple(row["blocking_reasons"]),
        policy_version=row["policy_version"],
        policy_params_digest=bytes(row["policy_params_digest"]),
        authorization_scope=dict(row["authorization_scope"]),
        admission_digest=bytes(row["admission_digest"]),
        valid_until=row["valid_until"],
    )


def current_inputs(scope: WorkspaceScope, capture_id: uuid.UUID) -> dict[str, Any] | None:
    """One current snapshot, evaluated after taking the shared privacy lock."""
    row = scope.connection.execute(
        "select current_privacy_inputs(%s,%s) as inputs", (scope.workspace_id, capture_id)
    ).fetchone()
    return row["inputs"] if row else None


def mask_is_current(
    scope: WorkspaceScope, capture_id: uuid.UUID, artifact_id: uuid.UUID | None = None
) -> bool:
    """Match the real producer digest, optionally for one exact declared artifact."""
    row = scope.connection.execute(
        "select current_privacy_mask(%s,%s,%s) as allowed",
        (scope.workspace_id, capture_id, artifact_id),
    ).fetchone()
    return bool(row and row["allowed"])


def screening_masks(
    scope: WorkspaceScope, capture_id: uuid.UUID, inputs: dict[str, Any] | None
) -> list[dict[str, str]]:
    """Bind a reviewed snapshot to an exact mask, never label an old output with new inputs."""
    if not inputs or not any(
        r["state"] in ("unknown", "present", "withdrawn") for r in inputs["regions"]
    ):
        return []
    row = scope.connection.execute(
        "select artifact_id,encode(content_sha256,'hex') as digest from artifact "
        "where workspace_id=%s and kind='masked_source' "
        "and privacy_mask_matches(%s,%s,artifact_id,%s) order by artifact_id limit 1",
        (scope.workspace_id, scope.workspace_id, capture_id, Jsonb(inputs)),
    ).fetchone()
    return (
        [{"artifact_id": str(row["artifact_id"]), "content_sha256": row["digest"]}] if row else []
    )


def selected_masks(
    scope: WorkspaceScope, capture_ids: list[uuid.UUID]
) -> dict[uuid.UUID, CaptureArtifactRow]:
    """Select exact current masks only for members that currently require them."""
    wanted = {}
    for capture_id in capture_ids:
        inputs = current_inputs(scope, capture_id)
        if inputs is None:
            raise PrivacyAdmissionError("a scene member is no longer available")
        required = any(
            row["state"] in ("unknown", "present", "withdrawn") for row in inputs["regions"]
        )
        if not required:
            continue
        masks = screening_masks(scope, capture_id, inputs)
        if not masks:
            raise PrivacyAdmissionError("a required current masked source is missing; rebuild")
        wanted[capture_id] = uuid.UUID(masks[0]["artifact_id"])
    rows = exact_for_captures(scope, artifact_ids_by_capture=wanted, kind="masked_source")
    if set(rows) != set(wanted):
        raise PrivacyAdmissionError("a required current masked source is no longer available")
    return rows
