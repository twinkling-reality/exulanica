"""Atomic personal-operation replay, scoped to an authenticated actor and workspace.

Old clients may omit request_id and retain their previous non-idempotent behavior. New clients
keep a UUID per explicit operation, including after a lost response. A reused UUID with a
changed operation/body refuses. Receipts retain only hashes and existing receipt identities,
indefinitely like the underlying append-only consent audit. Deletion does not remove that stub;
current access checks suppress its delivery. Returned receipt IDs are history, not permission.
No bytes, outlines, names, authority prose or model content are copied into this table.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.privacy import require_privacy_screening
from exulanica.ingest.repository import IngestRepository


def subject_captures(
    connection: psycopg.Connection, workspace: uuid.UUID, subject: uuid.UUID
) -> list[uuid.UUID]:
    return [
        row["capture_id"]
        for row in connection.execute(
            "select distinct capture_id from person_region_current "
            "where workspace_id=%s and subject_id=%s and action<>'deleted' order by capture_id",
            (workspace, subject),
        ).fetchall()
    ]


def require_current_access(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    captures: Sequence[uuid.UUID],
    subjects: Sequence[uuid.UUID],
) -> None:
    for capture in captures:
        if not connection.execute(
            "select asset_capture_live(%s,%s,clock_timestamp()) as allowed",
            (workspace, capture),
        ).fetchone()["allowed"]:
            raise PrivacyAdmissionError("a request source is no longer available in this workspace")
    for subject in subjects:
        row = connection.execute(
            "select 1 from person_subject where workspace_id=%s and subject_id=%s "
            "and not person_subject_is_withdrawn(workspace_id,subject_id) "
            "and (entity_id is null or not "
            "asset_tombstone_entity(workspace_id,entity_id,clock_timestamp()))",
            (workspace, subject),
        ).fetchone()
        if row is None:
            raise PrivacyAdmissionError("a request person is no longer available in this workspace")


def _references(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "capture_id",
        "subject_id",
        "consent_id",
        "actor_role",
        "recorded",
        "linked",
        "batch_id",
        "queued_job_id",
    }
    refs = {key: value for key, value in result.items() if key in allowed}
    if "receipts" in result:
        refs["receipts"] = [
            {key: item[key] for key in ("capture_id", "authorization_id", "screening_id")}
            for item in result["receipts"]
        ]
    return refs


def receipt_response(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    request_id: uuid.UUID,
    refs: dict[str, Any],
) -> dict[str, Any]:
    response = {**refs, "request_id": str(request_id), "receipt_only": True}
    if "receipts" in refs:
        repository = IngestRepository(connection, workspace)
        receipts = []
        for item in refs["receipts"]:
            try:
                require_privacy_screening(
                    repository, uuid.UUID(item["capture_id"]), uuid.UUID(item["screening_id"])
                )
                state = "eligible"
            except PrivacyAdmissionError:
                state = "blocked-or-stale"
            receipts.append({**item, "eligibility_state": state})
        response["receipts"] = receipts
    return response


def personal_request(
    connection: psycopg.Connection,
    *,
    workspace: uuid.UUID,
    actor: uuid.UUID,
    request_id: uuid.UUID,
    operation: str,
    body: dict[str, Any],
    captures: Sequence[uuid.UUID] | Callable[[], Sequence[uuid.UUID]],
    subjects: Sequence[uuid.UUID] = (),
    run: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    digest = sha256_of_canonical(
        {
            "workspace_id": str(workspace),
            "actor_id": str(actor),
            "operation": operation,
            "body": body,
        }
    )
    with connection.transaction():
        # The existing workspace lock precedes operation and receipt writes. Identical concurrent
        # requests serialize here; there is no independent lock order or pre-transaction cache.
        connection.execute("select privacy_currency_lock(%s)", (workspace,))
        captures = captures() if callable(captures) else captures
        for capture in sorted(set(captures)):
            connection.execute("select current_privacy_inputs(%s,%s)", (workspace, capture))
        prior = connection.execute(
            "select * from personal_request_receipt "
            "where workspace_id=%s and actor_id=%s and request_id=%s",
            (workspace, actor, request_id),
        ).fetchone()
        if prior is not None:
            if prior["operation"] != operation or bytes(prior["request_sha256"]) != digest:
                raise PrivacyAdmissionError(
                    "request_id already names a different personal operation"
                )
            require_current_access(
                connection, workspace, prior["capture_ids"], prior["subject_ids"]
            )
            return receipt_response(connection, workspace, request_id, prior["response_refs"])
        require_current_access(connection, workspace, captures, subjects)
        result = run()
        refs = _references(result)
        bound_subjects = set(subjects)
        if refs.get("subject_id"):
            bound_subjects.add(uuid.UUID(refs["subject_id"]))
        connection.execute(
            "insert into personal_request_receipt "
            "(workspace_id,actor_id,request_id,operation,request_sha256,"
            "capture_ids,subject_ids,response_refs) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace,
                actor,
                request_id,
                operation,
                digest,
                sorted(set(captures)),
                sorted(bound_subjects),
                Jsonb(refs),
            ),
        )
        return receipt_response(connection, workspace, request_id, refs)


def admission_status(
    connection: psycopg.Connection, workspace: uuid.UUID, actor: uuid.UUID
) -> dict[str, Any]:
    """Current source metadata and this actor's operation identities, never original delivery."""
    with connection.transaction():
        connection.execute("select privacy_currency_lock(%s)", (workspace,))
        rows = connection.execute(
            "select c.capture_id,c.blob_sha256,b.byte_size,b.media_type,a.authorization_id,"
            "a.purpose,a.authorization_evidence,a.authorized_at,a.valid_until "
            "from capture c join blob b on b.blob_sha256=c.blob_sha256 "
            "left join lateral (select * from capture_reconstruction_authorization a "
            "where a.workspace_id=c.workspace_id and a.capture_id=c.capture_id "
            "and a.authorized_by=%s and a.corpus_class='personal' "
            "order by a.authorized_at desc,a.authorization_id limit 1) a on true "
            "where c.workspace_id=%s and b.media_type like 'image/%%' "
            "and asset_capture_live(c.workspace_id,c.capture_id,clock_timestamp()) "
            "and b.purged_at is null and b.storage_key is not null order by c.capture_id",
            (actor, workspace),
        ).fetchall()
        sources = []
        for row in rows:
            authority = None
            if row["authorization_id"]:
                authority = {
                    "authorization_id": str(row["authorization_id"]),
                    "purpose": row["purpose"],
                    "account_authority_basis": row["authorization_evidence"][
                        "account_authority_basis"
                    ],
                    "authorized_at": row["authorized_at"].isoformat(),
                    "valid_until": row["valid_until"].isoformat() if row["valid_until"] else None,
                }
            sources.append(
                {
                    "capture_id": str(row["capture_id"]),
                    "sha256": bytes(row["blob_sha256"]).hex(),
                    "bytes": row["byte_size"],
                    "media_type": row["media_type"],
                    "authority": authority,
                }
            )
        requests = []
        for row in connection.execute(
            "select * from personal_request_receipt where workspace_id=%s and actor_id=%s "
            "order by recorded_at,request_id",
            (workspace, actor),
        ).fetchall():
            try:
                require_current_access(
                    connection, workspace, row["capture_ids"], row["subject_ids"]
                )
            except PrivacyAdmissionError:
                continue
            requests.append(
                {
                    "operation": row["operation"],
                    **receipt_response(
                        connection, workspace, row["request_id"], row["response_refs"]
                    ),
                }
            )
        return {
            "sources": sources,
            "requests": requests,
            "notice": "Receipt identities are history, not current consent "
            "or original-byte delivery permission.",
        }
