"""Personal authority, detection permission and human review on the ordinary API."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
    owns_workspace,
)
from exulanica.api.services import Services
from exulanica.errors import BlobNotFoundError, PrivacyAdmissionError
from exulanica.ingest.model_rights import ModelRightRow, model_right, withdraw_model_right
from exulanica.ingest.personal_admission import HUMAN_ATTESTATION, PersonalBatch, admit_batch
from exulanica.ingest.personal_requests import admission_status, personal_request
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.references.pictures import PICTURE_ROLE
from exulanica.selection.validation import Session

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
        if body.request_id is not None:
            return personal_request(
                connection,
                workspace=session.workspace_id,
                actor=session.actor,
                request_id=uuid.UUID(body.request_id),
                operation="admission",
                body=body.model_dump(mode="json", exclude={"request_id"}),
                captures=[uuid.UUID(member.capture_id) for member in body.members],
                run=lambda: admit_personal(
                    body.model_copy(update={"request_id": None}), connection, session, services
                ),
            )
        return admit_batch(
            body,
            actor=session.actor,
            pipeline=PhotoIngestPipeline(
                IngestRepository(connection, session.workspace_id), services.store
            ),
        )
    except (ValueError, PrivacyAdmissionError, BlobNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def personal_status(connection: ReadOnlyConnection, session: CurrentSession) -> dict[str, Any]:
    return {
        **admission_status(connection, session.workspace_id, session.actor),
        # The words a review sends back exactly, from the one constant it is checked against, so
        # no client keeps a copy of its own.
        "attestation": HUMAN_ATTESTATION,
    }


@router.post("/model-rights/{right_id}/withdraw")
def withdraw_right(
    right_id: Annotated[uuid.UUID, Path()],
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    """End a model right now, and answer with that right. Final, and idempotent: a second
    withdrawal of the same right changes nothing.

    Another workspace's right is answered exactly as an id nobody granted. A picture's reading
    right is stopped only by the person who granted it or an owner of the workspace; anyone else
    is answered as for an id nobody granted. Stopping it ends, in this one transaction, every
    reading right not yet withdrawn that its grantor holds on that picture, so nothing more of it
    is sent whichever of them a request would have used; stopping it again ends only those granted
    at or before its own stop, never a consent given since.
    """
    repository = IngestRepository(connection, session.workspace_id)
    with connection.transaction():
        stopped = model_right(repository, right_id)
        if stopped is None or not _may_stop(request, session, stopped):
            raise HTTPException(status_code=404, detail="no such model right")
        for each in _rights_ended_with(connection, session.workspace_id, stopped):
            right = withdraw_model_right(repository, right_id=each, withdrawn_by=session.actor)
            if each == right_id:
                ended = right
    return {**ended.as_reference(), "state": "ended"}


def _may_stop(request: Request, session: Session, stopped: ModelRightRow) -> bool:
    """Whether this caller may stop this right. A picture's reading right, whose stop ends every
    reading right its grantor holds on the picture, is stopped by its grantor or an owner of the
    workspace (by the membership record) alone; any other right by any caller the route admits."""
    if stopped.identity.role != str(PICTURE_ROLE):
        return True
    return stopped.granted_by == session.actor or owns_workspace(request, session)


def _rights_ended_with(
    connection: Any, workspace_id: uuid.UUID, stopped: ModelRightRow
) -> list[uuid.UUID]:
    """The rights one stop ends, locked in right id order before any is changed: the right itself
    and, for a picture's reading right, every reading right not yet withdrawn that its grantor holds
    on that picture. Locked here, never in the right's own trigger, which runs after the row and
    the privacy-currency lock are already held; FOR NO KEY UPDATE, the lock the withdrawal's own
    UPDATE takes. Whether the stopped right was already stopped is read under that lock: when it
    was, only the rights granted at or before that stop end with it, so a repeated stop never ends a
    consent given after the first."""
    if stopped.identity.role != str(PICTURE_ROLE):
        return [stopped.right_id]
    rows = connection.execute(
        "select right_id, granted_at, withdrawn_at from personal_model_right "
        "where workspace_id=%s and (right_id=%s or (capture_id=%s and model_role=%s "
        "and granted_by=%s and withdrawn_at is null)) order by right_id for no key update",
        (
            workspace_id,
            stopped.right_id,
            stopped.capture_id,
            str(PICTURE_ROLE),
            stopped.granted_by,
        ),
    ).fetchall()
    rows = [row if isinstance(row, dict) else dict(zip(_LOCKED, row, strict=True)) for row in rows]
    (own,) = [row for row in rows if row["right_id"] == stopped.right_id]
    stopped_at = own["withdrawn_at"]
    return [
        row["right_id"]
        for row in rows
        if row["right_id"] == stopped.right_id
        or stopped_at is None
        or row["granted_at"] <= stopped_at
    ]


_LOCKED = ("right_id", "granted_at", "withdrawn_at")
