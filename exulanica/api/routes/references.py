"""Reference requests: notes on what the things in a person's words look like, for one draft.

``POST /worlds/references`` takes a person's description, the drafter it is for (``purpose``), an
explicit ``"web"`` and, where pictures are offered, up to four of the person's own pictures by
capture id; it answers ``202`` at once with a request whose steps the page reads from
``GET /worlds/references/{reference_id}`` while a job reads each picture, plans the searches, sends
them, reads what came back and keeps only notes in a model's own words
(:mod:`exulanica.references.worker`).
Nothing a search returned is kept or served: a request serves its notes, its steps, and our own
record of each search (source, outcome, result count, credits, when), never a query result, a web
address or the query text. ``POST .../cancel`` stops a request at its next step.
``GET /worlds/references`` lists the caller's recent requests and the capability to make one, with
the reason when it is unavailable, and whether pictures are offered with the uses a person grants
for them.

Web notes are opt-in for every request, and offered only to the workspaces the installation lists
(``EXULANICA_REFERENCE_WORKSPACES``) while the source is offered to the operator only, and never on
an installation whose profile is ``public``. The description is sent with every saved name
replaced (:func:`exulanica.selection.world_drafting.sendable`); an idempotency key answers with the
request it first made.

A person's own pictures are offered only where ``EXULANICA_REFERENCE_PICTURES`` is on as well, and a
request names only pictures a privacy screening permits looking at and a current right for the
picture role covers (:func:`exulanica.api.reference_pictures.picture_refusal`); the job checks both
again before it reads each one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
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
from exulanica.api.reference_pictures import picture_refusal
from exulanica.api.services import Services
from exulanica.ingest.personal_admission import model_right_offers
from exulanica.references import store
from exulanica.references.adapters import ReferenceSourceUnavailable
from exulanica.references.bundle import read_bundle
from exulanica.references.catalogs import web_source
from exulanica.references.drafting import reference_prompts
from exulanica.references.pictures import PICTURE_ROLE
from exulanica.selection.world_drafting import sendable
from exulanica.spending.status import workspace_status

__all__ = ["REFERENCE_UNAVAILABLE", "router"]

router = APIRouter(prefix="/worlds", tags=["world"])
_LOG = logging.getLogger(__name__)

#: Why a reference request is not offered, by code, as the capability and a refusal name it.
REFERENCE_UNAVAILABLE: Final = (
    "references_not_configured",
    "references_operator_only",
    "references_not_run_here",
    "reference_budget_unavailable",
)
_LISTED: Final = 20
#: Another requester's request answers exactly as one that does not exist, and as an id-addressed
#: route answers a credential that may not reach it (exulanica/api/permissions.py).
_UNKNOWN: Final = "unknown_reference"
_UNKNOWN_DETAIL: Final = "nothing at this address is available to this credential"


class ReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Which drafter the notes are for.
    purpose: Literal["world_draft", "kind", "look", "pieces", "things"]
    #: The person's words, as they typed them; saved names are replaced before anything leaves.
    description: str = Field(min_length=1, max_length=1000)
    #: Whether web notes are asked for, explicitly on every request.
    web: bool
    #: The person's own pictures to read, by capture id, where pictures are offered.
    pictures: list[uuid.UUID] | None = Field(
        default=None, min_length=1, max_length=store.MAX_PICTURES
    )
    idempotency_key: uuid.UUID | None = None


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status)


def unavailable_because(
    services: Services, workspace_id: uuid.UUID, *, running: bool, web: bool = True
) -> str | None:
    """Why this workspace may not ask for references here, or None when it may.

    ``running`` is whether the worker's thread is alive in this process. Everything a search could
    be refused by is asked here, before anything is queued: the source and its offer, the worker,
    durable spending and, when ``web`` is asked for, the workspace's own grant for the source and
    its adapter. A request for notes from pictures alone sends no search.
    """
    source = web_source()
    if source is None:
        return "references_not_configured"
    if not services.references_offered_here() or (
        source.availability == "operator_only" and workspace_id not in services.reference_workspaces
    ):
        return "references_operator_only"
    if not services.runs_reference_worker or services.model_client is None or not running:
        return "references_not_run_here"
    if services.spending is None:
        return "reference_budget_unavailable"
    if not web:
        return None
    if not _granted(services, workspace_id, source.key):
        return "reference_budget_unavailable"
    if services.reference_adapter_for is None:
        return "references_not_configured"
    try:
        adapter = services.reference_adapter_for(source)
    except ReferenceSourceUnavailable:
        return "references_not_configured"
    adapter.close()
    return None


def _granted(services: Services, workspace_id: uuid.UUID, provider: str) -> bool:
    """Whether the workspace holds a live grant for ``provider`` with a call left."""
    document = workspace_status(services.database, workspace_id, providers=[provider])
    for entry in document["providers"]:
        if entry["provider"] == provider:
            return (
                entry["grant"]["state"] == "active"
                and entry["authority_state"] == "active"
                and entry["available_calls"] > 0
            )
    return False


def _running(request: Request) -> bool:
    thread = getattr(request.app.state, "reference_thread", None)
    return thread is not None and thread.is_alive()


def _sweep(services: Services, workspace_id: uuid.UUID) -> None:
    """This workspace's reference jobs no worker here will take, ended now, words blanked; its
    searches' query text past its retention, cleared."""
    with services.database.session(workspace_id) as connection:
        if services.serves_references_to(workspace_id):
            store.expire_unclaimed(connection, workspace_id)
        else:
            store.end_unserved(connection, workspace_id)
        cleared = store.try_clear_old_queries(connection, workspace_id)
        if isinstance(cleared, store.ClearFailed):
            _LOG.warning(
                "clearing old reference queries failed; the next sweep tries again",
                extra={"failure": cleared.failure},
            )


def _invalid_description(description: str) -> str | None:
    """A control character (U+0000 included) is refused by name; line breaks and tabs are words."""
    if any(
        unicodedata.category(character) == "Cc" and character not in "\n\t"
        for character in description
    ):
        return "description_control_character"
    return None


def reference_operation(code: str | None) -> Operation:
    """Asking for a reference: available, or unavailable with its code."""
    return Operation(
        endpoint=request_reference,
        availability=AVAILABLE if code is None else unavailable(code),
        subject="workspace",
        idempotency="idempotency_key",
        options=(read_reference,),
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
    fields: dict[str, Any] = {
        "purpose": body.purpose,
        "description": body.description,
        "web": body.web,
    }
    # A request without pictures keeps the digest it had before pictures were offered.
    if body.pictures:
        fields["pictures"] = [str(picture) for picture in body.pictures]
    canonical = json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def pictures_unavailable_because(
    services: Services, workspace_id: uuid.UUID, *, running: bool
) -> str | None:
    """Why this workspace may not name its own pictures here, or None: the one code the list states
    and a request naming a picture is refused with."""
    if not services.pictures_offered_to(workspace_id):
        return "reference_pictures_not_offered"
    return unavailable_because(services, workspace_id, running=running, web=False)


def _pictures(
    services: Services, workspace_id: uuid.UUID, *, running: bool, holds_right: bool
) -> dict[str, Any]:
    """Whether this workspace may name its own pictures here, and the uses a person grants for
    them; the code says why not, for logs and tests. The uses, stop words included, are served
    while pictures are offered and whenever the caller still holds a current picture right, so a
    page can always offer the stop."""
    code = pictures_unavailable_because(services, workspace_id, running=running)
    pictures: dict[str, Any] = {
        "offered": code is None,
        "code": code,
        "maximum": store.MAX_PICTURES,
    }
    if code is None or holds_right:
        pictures["consent"] = {
            "uses": [
                offer.as_record() for offer in model_right_offers(offered_on="reference_pictures")
            ]
        }
    return pictures


def _holds_picture_right(connection: Any, workspace_id: uuid.UUID, actor: uuid.UUID) -> bool:
    """Whether ``actor`` granted a reading right on a picture that is current now."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select exists (select 1 from personal_model_right where workspace_id=%s "
            "and granted_by=%s and model_role=%s and personal_model_right_allows(workspace_id,"
            "right_id,capture_id,model_provider,model_role,model_id,model_revision,destination,"
            "clock_timestamp())) as holds",
            (workspace_id, actor, str(PICTURE_ROLE)),
        ).fetchone()
    return bool(row and row["holds"])


def _picture_refused(
    services: Services, workspace_id: uuid.UUID, requester: uuid.UUID, pictures: list[uuid.UUID]
) -> JSONResponse | None:
    """The refusal of the first named picture ``requester`` may not have read, read as the request
    policy reads rights, or None when every one may be."""
    with services.readonly_database.session(workspace_id) as connection:
        for capture_id in pictures:
            reason, _rendition, _rights = picture_refusal(
                connection, workspace_id, capture_id, requester
            )
            if reason is not None:
                return _refusal(
                    409,
                    "reference_picture_not_admitted",
                    f"picture {capture_id} may not be read for notes ({reason})",
                )
    return None


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
    _sweep(services, session.workspace_id)
    running = _running(request)
    holds_right = _holds_picture_right(connection, session.workspace_id, session.actor)
    operation = reference_operation(
        unavailable_because(services, session.workspace_id, running=running)
    )
    return JSONResponse(
        {
            "references": views,
            "capabilities": [
                describe(operation, surface(request.app), held, installation_facts_of(services))
            ],
            "pictures": _pictures(
                services, session.workspace_id, running=running, holds_right=holds_right
            ),
        }
    )


@router.post("/references", status_code=202)
def request_reference(
    request: Request,
    body: ReferenceBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Ask for notes on what the things in a description and the person's own pictures look like,
    for one draft. Answers 202 with the request at once; an idempotency key answers 200 with the
    request it first made."""
    invalid = _invalid_description(body.description)
    if invalid is not None:
        return _refusal(422, invalid, "a description holds no control character")
    pictures = body.pictures or []
    if not body.web and not pictures:
        return _refusal(422, "nothing_to_look_up", "ask for web notes, name pictures, or both")
    if len(set(pictures)) != len(pictures):
        return _refusal(422, "pictures_repeated", "each picture is named once")
    _sweep(services, session.workspace_id)
    running = _running(request)
    if pictures:
        # The code the list states for pictures, before anything about web notes.
        code = pictures_unavailable_because(services, session.workspace_id, running=running)
        if code is not None:
            return _refusal(409, code, "pictures are not offered to this workspace here")
    code = unavailable_because(services, session.workspace_id, running=running, web=body.web)
    if code is not None:
        return _refusal(409, code, "references are not offered to this workspace here")
    if pictures:
        refused = _picture_refused(services, session.workspace_id, session.actor, pictures)
        if refused is not None:
            return refused
    sent = sendable(connection, session.workspace_id, body.description)
    if len(sent.text) > store.MAX_DESCRIPTION_CHARACTERS:
        return _refusal(
            422,
            "description_too_long",
            f"with its saved names replaced, a description is at most "
            f"{store.MAX_DESCRIPTION_CHARACTERS} characters",
        )
    key = body.idempotency_key
    try:
        made, new = store.create_request(
            connection,
            session.workspace_id,
            offered_to=services.reference_workspaces,
            owner_actor_id=session.actor,
            purpose=body.purpose,
            web=body.web,
            description=sent.text,
            withheld_words=(),
            prompts_sha256=reference_prompts().sha256,
            request_id=key,
            request_sha256=None if key is None else _request_sha256(body),
            pictures=tuple(pictures),
        )
    except store.RequestNotOffered:
        return _refusal(409, "references_operator_only", "web notes are not offered here")
    except store.RequestLimitReached:
        return _refusal(
            429,
            "reference_limit_reached",
            f"at most {store.MAX_OPEN_PER_ACTOR} requests open and "
            f"{store.MAX_PER_ACTOR_HOUR} an hour for one requester",
        )
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
    found = store.read_request(
        connection, session.workspace_id, reference_id, owner_actor_id=session.actor
    )
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(_view(found, _lookups(connection, session.workspace_id, reference_id)))


@router.post("/references/{reference_id}/cancel")
def cancel_reference(
    reference_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    """Stop a request: a queued one at once, a running one at its next step. A finished one is
    answered as it stands."""
    found = store.request_cancel(
        connection, session.workspace_id, reference_id, owner_actor_id=session.actor
    )
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(_view(found, _lookups(connection, session.workspace_id, reference_id)))
