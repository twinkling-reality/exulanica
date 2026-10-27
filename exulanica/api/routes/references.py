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
an installation whose profile is ``public``, unless the installation offers them to every workspace
(``EXULANICA_NOTES_AND_CREATURES=everyone``), guests included, each request paid from the
workspace's own allowance for the source and for its model calls. The description is sent with
every saved name replaced (:func:`exulanica.selection.world_drafting.sendable`); an idempotency key
answers with the request it first made.

A person's own pictures are offered only where ``EXULANICA_REFERENCE_PICTURES`` is on as well, and a
request names only pictures a privacy screening permits looking at and a current right for the
picture role covers (:func:`exulanica.api.reference_pictures.picture_refusal`); the job checks both
again before it reads each one.

A picture search (``web_pictures``, for a creature) is offered only where
``EXULANICA_REFERENCE_WEB_PICTURES`` is on as well: the person's words, at most eight, are its one
search, and the pictures it finds are served to its requester alone from
``GET /worlds/references/{reference_id}/pictures`` while this process holds them (thirty minutes),
with ``Cache-Control: no-store``; the page shows each from its own website. Nothing of them is
written anywhere. ``POST .../pictures/{n}/keep`` keeps the one the person picks, with their answer
to whether they may use it: fetched once (:mod:`exulanica.references.picture_fetch`) and kept apart
from their own photographs (:mod:`exulanica.world.kept_web_pictures`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
import uuid
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Path, Request
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
from exulanica.api.permissions import Permission
from exulanica.api.reference_pictures import picture_refusal
from exulanica.api.services import Services
from exulanica.api.world_draft_offer import notes_maximum_usd
from exulanica.ingest.personal_admission import model_right_offers
from exulanica.models.usage import usd_string
from exulanica.references import store
from exulanica.references.adapters import ReferenceSourceUnavailable
from exulanica.references.boundary import MAX_QUERY_CHARACTERS, MAX_QUERY_WORDS
from exulanica.references.bundle import read_bundle
from exulanica.references.catalogs import web_source
from exulanica.references.drafting import prompts_for_request
from exulanica.references.held_pictures import held_pictures
from exulanica.references.picture_fetch import PictureFetchRefused
from exulanica.references.pictures import PICTURE_ROLE
from exulanica.selection.world_drafting import sendable
from exulanica.spending.status import workspace_status
from exulanica.world.kept_web_pictures import (
    KeptPictureRefused,
    KeptWebPictures,
    keep_held_picture,
)

__all__ = [
    "NOTES_PRICE_UNAVAILABLE",
    "REFERENCE_UNAVAILABLE",
    "notes_figures",
    "notes_offer",
    "router",
]

router = APIRouter(prefix="/worlds", tags=["world"])
_LOG = logging.getLogger(__name__)

#: Why a reference request is not offered, by code, as the capability and a refusal name it.
REFERENCE_UNAVAILABLE: Final = (
    "references_not_configured",
    "references_operator_only",
    "references_not_run_here",
    "reference_budget_unavailable",
)
#: Web notes are offered and permitted, but no current rate prices their model calls, so no most
#: can be said before anything is sent: they are not offered.
NOTES_PRICE_UNAVAILABLE: Final = "references_price_unavailable"
_LISTED: Final = 20
#: Another requester's request answers exactly as one that does not exist, and as an id-addressed
#: route answers a credential that may not reach it (exulanica/api/permissions.py).
_UNKNOWN: Final = "unknown_reference"
_UNKNOWN_DETAIL: Final = "nothing at this address is available to this credential"
#: What a held picture's answer may not be: kept by a cache anywhere on its way.
_NOT_STORED: Final = {"Cache-Control": "no-store"}


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
    #: Whether to search the web for pictures of the creature the words describe; a web search.
    web_pictures: bool = False
    idempotency_key: uuid.UUID | None = None


class KeepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Whether the person may use the picture for their own world, in their own answer.
    answer: Literal["made_or_permitted", "licence_allows", "private_world_only"]
    #: The licence that allows it, where the answer says one does.
    licence: str | None = Field(default=None, min_length=1, max_length=200)


#: A fetch refusal that is the website's doing, not the picture's: answered as a bad gateway.
_UPSTREAM: Final = frozenset({"picture_unreachable", "picture_timed_out"})


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
        source.availability == "operator_only" and not services.reference_listed(workspace_id)
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


def notes_offer(
    request: Request,
    services: Services,
    workspace_id: uuid.UUID,
    held: frozenset[Permission],
    *,
    purpose: str,
) -> dict[str, Any]:
    """Web notes a draft of ``purpose`` may be asked with here, as this person would meet them now.

    ``offered`` where this workspace may ask for web notes here and this person may (a guest holds
    ``references.request`` only where web notes are offered to everyone); else ``code`` names why,
    as the references read names it, ``references_not_permitted``, or
    :data:`NOTES_PRICE_UNAVAILABLE` where no current rate prices their model calls.
    ``searches_at_most`` is the planner's limit in the words a new request of ``purpose`` is
    planned with; ``maximum_usd`` the most their two model calls may add at current rates
    (:func:`exulanica.api.world_draft_offer.notes_maximum_usd`), null where not offered.
    """
    searches = prompts_for_request(purpose).subjects_maximum
    if Permission.REFERENCES_REQUEST not in held:
        code: str | None = "references_not_permitted"
    else:
        code = unavailable_because(services, workspace_id, running=_running(request), web=True)
    most = None if code is not None else notes_maximum_usd(services.model_client)
    if code is None and most is None:
        code = NOTES_PRICE_UNAVAILABLE
    return {
        "offered": code is None,
        "code": code,
        "searches_at_most": searches,
        "maximum_usd": None if most is None else usd_string(Decimal(most)),
    }


def notes_figures(
    connection: Any,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    reference_id: uuid.UUID,
    *,
    purpose: str,
) -> tuple[int | None, str | None]:
    """How many searches ``actor``'s own notes request for a draft of ``purpose`` sent and what its
    model calls spent, as its bundle records them; none for a request without a bundle, another
    person's, or one made for another kind of draft, whose spend is not that draft's."""
    found = store.read_request(connection, workspace_id, reference_id, owner_actor_id=actor)
    if found is None or found.purpose != purpose or found.bundle is None:
        return None, None
    bundle = read_bundle(found.bundle)
    spent = sum((Decimal(call.usd) for call in bundle.model_calls), Decimal(0))
    return len(bundle.lookups), usd_string(spent)


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
    if body.web_pictures:
        fields["web_pictures"] = True
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


def web_pictures_unavailable_because(
    services: Services, workspace_id: uuid.UUID, *, running: bool
) -> str | None:
    """Why this workspace may not search the web for pictures here, or None: the one code the
    list states and a picture search is refused with. Picture searches are offered where they are
    turned on, references are served to the workspace, and the installation is not public."""
    profile = services.installation.profile if services.installation is not None else None
    if (
        not services.reference_web_pictures
        or (profile is not None and profile.id == "public")
        or not services.serves_references_to(workspace_id)
    ):
        return "web_pictures_not_offered"
    return unavailable_because(services, workspace_id, running=running, web=True)


def _web_pictures(services: Services, workspace_id: uuid.UUID, *, running: bool) -> dict[str, Any]:
    """Whether this workspace may search the web for pictures here, and how many words a search
    holds; the code says why not."""
    code = web_pictures_unavailable_because(services, workspace_id, running=running)
    return {"offered": code is None, "code": code, "words": MAX_QUERY_WORDS}


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
            "web_pictures": _web_pictures(services, session.workspace_id, running=running),
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
    if body.web_pictures and not body.web:
        return _refusal(422, "web_pictures_need_web", "a picture search is a web search")
    if body.web_pictures and body.purpose != "things":
        return _refusal(422, "web_pictures_for_things", "a picture search is for a creature")
    pictures = body.pictures or []
    if not body.web and not pictures:
        return _refusal(422, "nothing_to_look_up", "ask for web notes, name pictures, or both")
    if len(set(pictures)) != len(pictures):
        return _refusal(422, "pictures_repeated", "each picture is named once")
    _sweep(services, session.workspace_id)
    running = _running(request)
    if body.web_pictures:
        code = web_pictures_unavailable_because(services, session.workspace_id, running=running)
        if code is not None:
            return _refusal(409, code, "picture searches are not offered to this workspace here")
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
    if body.web_pictures and (
        len(sent.text.split()) > MAX_QUERY_WORDS or len(sent.text) > MAX_QUERY_CHARACTERS
    ):
        return _refusal(
            422,
            "web_pictures_words",
            f"a picture search is at most {MAX_QUERY_WORDS} words and "
            f"{MAX_QUERY_CHARACTERS} characters",
        )
    key = body.idempotency_key
    try:
        made, new = store.create_request(
            connection,
            session.workspace_id,
            # The one workspace this request is for, where a worker here takes its jobs.
            offered_to=(
                (session.workspace_id,)
                if services.serves_references_to(session.workspace_id)
                else ()
            ),
            owner_actor_id=session.actor,
            purpose=body.purpose,
            web=body.web,
            description=sent.text,
            withheld_words=(),
            prompts_sha256=prompts_for_request(body.purpose, pictures=bool(body.pictures)).sha256,
            request_id=key,
            request_sha256=None if key is None else _request_sha256(body),
            pictures=tuple(pictures),
            web_pictures=body.web_pictures,
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


@router.get("/references/{reference_id}/pictures")
def read_reference_pictures(
    reference_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    """The pictures a picture search found, for its requester only, while this process holds
    them: each its address, its website and its words, for the page to show from the website.
    Never stored, so never cached either."""
    found = store.read_request(
        connection, session.workspace_id, reference_id, owner_actor_id=session.actor
    )
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    held = held_pictures().read(session.workspace_id, reference_id)
    if held is None:
        return JSONResponse(
            {
                "code": "pictures_not_held",
                "detail": "no pictures are held for this request in this process",
            },
            status_code=404,
            headers=_NOT_STORED,
        )
    return JSONResponse(
        {
            "reference_id": str(reference_id),
            "pictures": [
                {
                    "n": n,
                    "address": picture.address,
                    "website": picture.website,
                    "description": picture.description,
                }
                for n, picture in enumerate(held.pictures)
            ],
            "seconds_left": held.seconds_left,
        },
        headers=_NOT_STORED,
    )


@router.post("/references/{reference_id}/pictures/{n}/keep", status_code=201)
def keep_reference_picture(
    reference_id: uuid.UUID,
    n: Annotated[int, Path(ge=0, le=7)],
    body: KeepBody,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Keep the picture a search found at position ``n``, with the person's answer: fetched once,
    written again with no metadata, and kept apart from their own photographs. Only the request's
    requester keeps one, while this process holds the search's pictures."""
    found = store.read_request(
        connection, session.workspace_id, reference_id, owner_actor_id=session.actor
    )
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    code = web_pictures_unavailable_because(
        services, session.workspace_id, running=_running(request)
    )
    if code is not None:
        return _refusal(409, code, "picture searches are not offered to this workspace here")
    held = held_pictures().read(session.workspace_id, reference_id)
    if held is None:
        return _refusal(404, "pictures_not_held", "no pictures are held for this request")
    if n >= len(held.pictures):
        return _refusal(404, "picture_unknown", "the search found no picture at this place")
    stores = services.content_stores
    if stores is None:
        return _refusal(503, "web_picture_store_unavailable", "this server keeps no pictures")
    try:
        with services.database.session(session.workspace_id) as keeping:
            kept = keep_held_picture(
                KeptWebPictures(
                    keeping,
                    session.workspace_id,
                    stores.web_pictures.for_workspace(session.workspace_id),
                ),
                held.pictures[n],
                answer=body.answer,
                answered_by=session.actor,
                reference_id=reference_id,
                licence=body.licence,
            )
    except PictureFetchRefused as refused:
        return _refusal(502 if refused.code in _UPSTREAM else 422, refused.code, str(refused))
    except KeptPictureRefused as refused:
        status = 409 if refused.code in ("workspace_erased", "restore_sealed") else 422
        return _refusal(status, refused.code, refused.detail)
    return JSONResponse(kept_picture_view(kept), status_code=201)


def kept_picture_view(kept: Any) -> dict[str, Any]:
    """A kept picture as the routes answer it: where it came from, what was kept and the answer."""
    return {
        "picture_id": str(kept.picture_id),
        "address": kept.address,
        "website": kept.website,
        "media_type": kept.media_type,
        "byte_size": kept.byte_size,
        "width": kept.width,
        "height": kept.height,
        "answer": kept.answer,
        "licence": kept.licence,
        "reference_id": None if kept.reference_id is None else str(kept.reference_id),
        "kept_at": kept.kept_at.isoformat(),
    }


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
    if found.status == "cancelled" or (
        found.cancel_requested_at is not None and found.finished_at is None
    ):
        # A stopped search's pictures go with it; a finished one keeps them for their time.
        held_pictures().forget(session.workspace_id, reference_id)
    return JSONResponse(_view(found, _lookups(connection, session.workspace_id, reference_id)))
