"""Reference requests: notes on what the things in a person's words look like, for one draft.

``POST /worlds/references`` takes a person's description, the drafter it is for (``purpose``) and
an explicit ``"web": true``, and answers ``202`` at once with a request whose steps the page reads
from ``GET /worlds/references/{reference_id}`` while a job plans the searches, sends them, reads
what came back and keeps only notes in a model's own words (:mod:`exulanica.references.worker`).
Nothing a search returned is kept or served: a request serves its notes, its steps, and our own
record of each search (source, outcome, result count, credits, when), never a query result, a web
address or the query text. ``POST .../cancel`` stops a request at its next step.
``GET /worlds/references`` lists the caller's recent requests and the capability to make one, with
the reason when it is unavailable.

Web notes are opt-in for every request, and offered only to the workspaces the installation lists
(``EXULANICA_REFERENCE_WORKSPACES``) while the source is offered to the operator only, and never on
an installation whose profile is ``public``. The description is sent with every saved name
replaced (:func:`exulanica.selection.world_drafting.sendable`); an idempotency key answers with the
request it first made.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.capabilities import (
    AVAILABLE,
    Operation,
    describe,
    installation_facts_of,
    surface,
    unavailable,
)
from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.references import store
from exulanica.references.adapters import ReferenceSourceUnavailable
from exulanica.references.bundle import read_bundle
from exulanica.references.catalogs import load_reference_catalogs
from exulanica.references.drafting import reference_prompts
from exulanica.references.worker import WEB_SOURCE
from exulanica.selection.world_drafting import sendable

__all__ = ["REFERENCE_UNAVAILABLE", "router"]

router = APIRouter(prefix="/worlds", tags=["world"])

#: Why a reference request is not offered, by code, as the capability and a refusal name it.
REFERENCE_UNAVAILABLE: Final = (
    "references_not_configured",
    "references_operator_only",
    "references_not_run_here",
    "reference_budget_unavailable",
)
_LISTED: Final = 20


class ReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Which drafter the notes are for.
    purpose: Literal["world_draft", "kind", "look", "pieces", "things"]
    #: The person's words, as they typed them; saved names are replaced before anything leaves.
    description: str = Field(min_length=1, max_length=1000)
    #: Web notes are asked for on every request, explicitly; nothing else is offered yet.
    web: Literal[True]
    idempotency_key: uuid.UUID | None = None


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status)


def unavailable_because(services: Services, workspace_id: uuid.UUID) -> str | None:
    """Why this workspace may not ask for web notes here, or None when it may."""
    source = load_reference_catalogs().sources[WEB_SOURCE]
    if not services.references_offered_here() or (
        source.availability == "operator_only" and workspace_id not in services.reference_workspaces
    ):
        return "references_operator_only"
    if not services.runs_reference_worker or services.model_client is None:
        return "references_not_run_here"
    if services.spending is None:
        return "reference_budget_unavailable"
    if services.reference_adapter_for is None:
        return "references_not_configured"
    try:
        adapter = services.reference_adapter_for(source)
    except ReferenceSourceUnavailable:
        return "references_not_configured"
    adapter.close()
    return None


def reference_operation(code: str | None) -> Operation:
    """Asking for a reference: available, or unavailable with its code."""
    return Operation(
        endpoint=request_reference,
        availability=AVAILABLE if code is None else unavailable(code),
        subject="workspace",
        idempotency="idempotency_key",
        options=(read_reference, cancel_reference),
    )


def _view(request: store.ReferenceRequest, lookups: list[dict[str, Any]]) -> dict[str, Any]:
    notes: list[dict[str, str]] = []
    missed: list[str] = []
    if request.bundle is not None:
        bundle = read_bundle(request.bundle)
        notes = [
            {"aspect": note.aspect, "text": note.text, "basis": note.basis} for note in bundle.notes
        ]
        missed = list(bundle.missed)
    return {
        "reference_id": str(request.reference_id),
        "purpose": request.purpose,
        "web": request.web,
        "status": request.status,
        "steps": list(request.steps),
        "notes": notes,
        "missed": missed,
        "failure": request.failure,
        "searches": lookups,
        "bundle_sha256": request.bundle_sha256,
        "cancel_requested": request.cancel_requested_at is not None,
        "created_at": request.created_at.isoformat(),
        "finished_at": None if request.finished_at is None else request.finished_at.isoformat(),
    }


def _lookups(connection: Any, workspace_id: uuid.UUID, reference_id: uuid.UUID) -> list[dict]:
    """Our record of each search, without the query text: what a request serves of it."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select source, outcome, result_count, credits, sent_at from reference_lookup "
            "where workspace_id=%s and reference_id=%s order by sent_at, lookup_id",
            (workspace_id, reference_id),
        ).fetchall()
    return [
        {
            "source": row["source"],
            "outcome": row["outcome"],
            "result_count": row["result_count"],
            "credits": row["credits"],
            "sent_at": row["sent_at"].isoformat(),
        }
        for row in rows
    ]


def _request_sha256(body: ReferenceBody) -> str:
    canonical = json.dumps(
        {"purpose": body.purpose, "description": body.description, "web": body.web},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


@router.get("/references")
def list_references(
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    held: HeldPermissions,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """The caller's most recent reference requests, newest first, and whether one may be made."""
    with connection.cursor(row_factory=dict_row) as cursor:
        ids = cursor.execute(
            "select reference_id from reference_request where workspace_id=%s "
            "and owner_actor_id=%s order by created_at desc limit %s",
            (session.workspace_id, session.actor, _LISTED),
        ).fetchall()
    views = []
    for row in ids:
        found = store.read_request(connection, session.workspace_id, row["reference_id"])
        if found is not None:
            views.append(
                _view(found, _lookups(connection, session.workspace_id, found.reference_id))
            )
    operation = reference_operation(unavailable_because(services, session.workspace_id))
    return JSONResponse(
        {
            "references": views,
            "capabilities": [
                describe(operation, surface(request.app), held, installation_facts_of(services))
            ],
        }
    )


@router.post("/references", status_code=202)
def request_reference(
    body: ReferenceBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Ask for notes on what the things in a description look like, for one draft. Answers 202
    with the request at once; an idempotency key answers 200 with the request it first made."""
    code = unavailable_because(services, session.workspace_id)
    if code is not None:
        return _refusal(409, code, "web notes are not offered to this workspace here")
    sent = sendable(connection, session.workspace_id, body.description)
    key = body.idempotency_key
    try:
        made, new = store.create_request(
            connection,
            session.workspace_id,
            offered_to=services.reference_workspaces,
            owner_actor_id=session.actor,
            purpose=body.purpose,
            web=True,
            description=sent.text,
            withheld_words=(),
            prompts_sha256=reference_prompts().sha256,
            request_id=key,
            request_sha256=None if key is None else _request_sha256(body),
        )
    except store.RequestNotOffered:
        return _refusal(409, "references_operator_only", "web notes are not offered here")
    except store.RequestKeyReused:
        return _refusal(
            409, "idempotency_key_reused", "the key names an earlier request with another body"
        )
    return JSONResponse(_view(made, []), status_code=202 if new else 200)


@router.get("/references/{reference_id}")
def read_reference(
    reference_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    """One reference request: its steps as they happen, then its notes, or why it stopped."""
    found = store.read_request(connection, session.workspace_id, reference_id)
    if found is None:
        return _refusal(404, "reference_not_found", "no such reference request")
    return JSONResponse(_view(found, _lookups(connection, session.workspace_id, reference_id)))


@router.post("/references/{reference_id}/cancel")
def cancel_reference(
    reference_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    """Stop a request: a queued one at once, a running one at its next step. A finished one is
    answered as it stands."""
    found = store.request_cancel(connection, session.workspace_id, reference_id)
    if found is None:
        return _refusal(404, "reference_not_found", "no such reference request")
    return JSONResponse(_view(found, _lookups(connection, session.workspace_id, reference_id)))
