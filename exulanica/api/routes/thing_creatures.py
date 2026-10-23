"""A creature from a person's words: ask for one, then read how its draft went.

``POST /things/creatures`` takes the person's words for one creature and answers ``202`` at once
with a draft (``exulanica.creature-draft/v1``) that a worker in this process plays
(:mod:`exulanica.selection.creature_drafts`): it asks the creature drafter, holds the creature to
every check a thing passes, and keeps one that passes in the workspace's own store, its sketch its
first look. ``GET /things/creatures/drafts/{draft_id}`` answers the draft as it goes: ``queued`` and
``running``; ``kept``, naming the kind made and its sketch by digest (served by
:mod:`exulanica.api.routes.thing_store`), the model that drafted it and, once one is asked, its
creature's newest look job (``look_job``, as ``GET /things/creatures/looks/{look_id}`` answers it):
a draft from words alone asks its creature's made look as it keeps it; ``erased``, a kept draft
whose creature the workspace has erased since; ``refused``, with the check's code, the field of the
drafter's form it refused and the code's fixed sentence; ``failed``, with why by code; or
``cancelled``, ended by its workspace's erasure (``workspace_deleted``). Every state carries what
the draft has spent (``spend``), as the durable spending authority recorded its attempts, or null
where no durable authority admits this process's calls and nothing is recorded to read.

``GET /things/creatures/offered`` says whether the workspace may ask, the model a draft asks first,
the most one draft may be charged and to which account (``price``, from the route's bounds and the
manifest's prices: :func:`exulanica.selection.creature_drafts.price_at_most`), how long a draft
usually takes and every code a draft may end with.

The words are sent with every saved name replaced (:func:`exulanica.selection.world_drafting.
sendable`) and are kept only in the draft's job until it ends; the draft keeps nothing of them.
Only the workspaces this installation lists draft creatures (``EXULANICA_CREATURE_WORKSPACES``), at
most one unfinished draft and a bounded number an hour for one requester; only the requester reads
a draft. Asking needs ``world.write`` and ``model.invoke``; reading needs ``world.read``.

``POST /things/creatures/{kind_sha256}/looks`` asks for a made look of a creature the workspace
keeps and answers ``202`` at once with its look job (``exulanica.creature-look/v1``), queued, or
with the one already waiting for that creature; ``GET /things/creatures/looks/{look_id}`` answers it
as it goes: ``queued``; ``staged`` by an operator's run; ``made``, naming the look the creature now
wears by its document's digest (served by :mod:`exulanica.api.routes.thing_store`); ``refused``, by
the fit's code; ``failed`` or ``cancelled``, by why. Nothing here spends: an operator's run makes
the look (:mod:`exulanica.world.creature_look_jobs`). Only the workspaces this installation lists
ask, at most a few unfinished jobs and a bounded number an hour for one requester; any member of the
workspace reads a job, which holds no word, and a creature's erasure takes its jobs with it. The
same permissions as a draft.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Annotated, Any, Final

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.models.manifest import Role, load_manifest
from exulanica.selection import creature_drafts as drafts
from exulanica.selection.world_drafting import sendable
from exulanica.things.lines import LineRefused, check_line
from exulanica.world import creature_look_jobs as look_jobs
from exulanica.world.committed_content import DIGEST
from exulanica.world.thing_store import ThingStore

if TYPE_CHECKING:
    from exulanica.spending.status import SpendingRefusals

__all__ = [
    "DRAFTS_PROFILE",
    "DRAFT_PROFILE",
    "LOOK_PROFILE",
    "OFFER_CODES",
    "OFFER_PROFILE",
    "router",
]

router = APIRouter(prefix="/things", tags=["things"])

DRAFT_PROFILE: Final = "exulanica.creature-draft/v1"
OFFER_PROFILE: Final = "exulanica.creature-offer/v1"
DRAFTS_PROFILE: Final = "exulanica.creature-drafts/v1"
LOOK_PROFILE: Final = "exulanica.creature-look/v1"
#: Why a workspace may not ask for a creature here, by code.
OFFER_CODES: Final = drafts.OFFER_REFUSALS
#: Another requester's draft answers exactly as one that does not exist.
_UNKNOWN: Final = "unknown_reference"
_UNKNOWN_DETAIL: Final = "nothing at this address is available to this credential"
_HEADERS: Final = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

_LOG = logging.getLogger(__name__)


class CreatureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The person's words for one creature, as they typed them.
    words: str
    #: A finished reference request of this requester, made for things; web notes only.
    reference_id: uuid.UUID | None = None


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status, headers=_HEADERS)


def _spending(
    services: Services, connection: Any, workspace_id: uuid.UUID
) -> SpendingRefusals | None:
    """The workspace's spending as the durable authority would answer its next attempt, read once
    on the request's connection under a savepoint, or None where nothing reads it or the read fails
    (admission still refuses the draft's attempt, and the draft fails by its code)."""
    try:
        with connection.transaction():
            return services.spending_refusals(connection, workspace_id)
    except Exception as exc:
        # Never the exception's text, which may carry a connection string.
        _LOG.warning("the spending state could not be read: %s", type(exc).__qualname__)
        return None


def _view(
    connection: Any,
    workspace_id: uuid.UUID,
    draft: drafts.CreatureDraft,
    services: Services,
) -> dict[str, Any]:
    status = draft.status
    kind = look = None
    label = None
    if draft.kind_sha256 is not None:
        held = ThingStore(connection, workspace_id, None).kind_by_digest(draft.kind_sha256)
        if held is not None:
            kind = held.reference()
            look = dict(held.looks[0]) if held.looks else None
            label = held.label
        else:
            # Nothing holds the digest: the creature was erased, or went with its workspace's
            # tombstone, whose purge deletes the kind and writes no erasure. Either way it is gone.
            status = "erased"
    model = None
    if draft.model_id is not None:
        model = {"model_id": draft.model_id, "name": load_manifest().model_name(draft.model_id)}
    view = {
        "profile": DRAFT_PROFILE,
        "draft_id": str(draft.draft_id),
        "status": status,
        "label": label,
        "kind": kind,
        "look": look,
        "model": model,
        # The code's fixed sentence, never one built from the request.
        "refusal": None
        if draft.refusal_code is None
        else {
            "code": draft.refusal_code,
            "field": draft.refusal_field,
            "detail": drafts.refusal_sentence(draft.refusal_code, draft.refusal_field),
        },
        "failure": draft.failure,
        # What its attempts were charged, as the durable authority recorded them; null where
        # none admits this process's calls, so nothing was recorded.
        "spend": None
        if services.spending is None
        else drafts.draft_spend(connection, workspace_id, draft),
        "created_at": draft.created_at.isoformat(),
        "started_at": None if draft.started_at is None else draft.started_at.isoformat(),
        "finished_at": None if draft.finished_at is None else draft.finished_at.isoformat(),
    }
    if kind is not None:
        asked = look_jobs.newest_look(connection, workspace_id, draft.kind_sha256)
        if asked is not None:
            view["look_job"] = _look_view(asked)
    if draft.reference_id is not None:
        view["references"] = {
            "reference_id": str(draft.reference_id),
            **(
                draft.reference_usage
                if draft.reference_usage is not None
                else {"state": "not_attempted" if draft.finished else "pending"}
            ),
        }
    return view


@router.get("/creatures/offered")
def creature_offer(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Whether this workspace may ask for a creature here, why not by code, how long a draft
    usually takes by the creature drafter's measured calls, and every code a draft may end with."""
    # Also the model a draft asks first and the most a draft may be charged, to which account. The
    # workspace's own spending is read once: spending paused or spent is said before anyone types.
    code = services.creature_offer_refusal(
        session.workspace_id, spending=_spending(services, connection, session.workspace_id)
    )
    offered = code is None
    manifest = load_manifest()
    binding = manifest[Role.CREATURE_DRAFTER]
    basis = binding.timeout_basis
    client = services.model_client
    return JSONResponse(
        {
            "profile": OFFER_PROFILE,
            "offered": offered,
            "code": code,
            # The route's first model; a fallback answers only for one withdrawn, and the draft
            # names the model that answered.
            "model": {
                "model_id": binding.primary.model_id,
                "name": manifest.model_name(binding.primary.model_id),
            },
            # With no model client here, no attempt is counted and no price is stated.
            "price": None
            if client is None
            else drafts.price_at_most(
                manifest, client.maximum_wire_attempts(Role.CREATURE_DRAFTER)
            ),
            # From the record the role's timeout rests on: its primary's calls, never a number
            # typed here. A draft is a call and, when a check refuses it, one repair.
            "timing": {
                "record": basis["record"],
                "call_p50_seconds": -(-int(basis["p50_ms"]) // 1000),
                "call_longest_seconds": -(-int(basis["longest_ms"]) // 1000),
                "call_timeout_seconds": binding.timeout_seconds,
            },
            "codes": {
                "refused": list(drafts.refusal_codes()),
                "failed": list(drafts.FAILURE_CODES),
                "cancelled": list(drafts.CANCELLATION_CODES),
            },
        },
        headers=_HEADERS,
    )


@router.get("/creatures/drafts")
def list_creature_drafts(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """The requester's own drafts, newest first: a reload or a second tab finds one still
    running."""
    listed = drafts.list_drafts(connection, session.workspace_id, owner_actor_id=session.actor)
    return JSONResponse(
        {
            "profile": DRAFTS_PROFILE,
            "drafts": [
                _view(connection, session.workspace_id, draft, services) for draft in listed
            ],
        },
        headers=_HEADERS,
    )


@router.post("/creatures", status_code=202)
def draft_creature(
    body: CreatureBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Ask for a creature from the person's words; answers 202 with its draft at once."""
    try:
        check_line(body.words, maximum=drafts.MAX_WORDS_CHARACTERS)
    except LineRefused as refused:
        return _refusal(422, "words_refused", str(refused))
    if not services.serves_creatures_to(session.workspace_id):
        return _refusal(409, "creatures_not_run_here", "creatures are not drafted here")
    sent = sendable(connection, session.workspace_id, body.words)
    if len(sent.text) > drafts.MAX_WORDS_CHARACTERS:
        return _refusal(
            422,
            "words_too_long",
            f"with saved names replaced, the words are at most {drafts.MAX_WORDS_CHARACTERS} "
            "characters",
        )
    try:
        made = drafts.create_draft(
            connection,
            session.workspace_id,
            offered_to=services.creature_workspaces,
            owner_actor_id=session.actor,
            words=body.words,
            sent=sent.text,
            placeholders=sent.placeholders,
            reference_id=body.reference_id,
        )
    except drafts.DraftNotOffered:
        return _refusal(409, "creatures_not_run_here", "creatures are not drafted here")
    except drafts.DraftLimitReached:
        return _refusal(
            429,
            "creature_limit_reached",
            f"at most {drafts.MAX_OPEN_PER_ACTOR} draft open and "
            f"{drafts.MAX_PER_ACTOR_HOUR} an hour for one requester",
        )
    return JSONResponse(
        _view(connection, session.workspace_id, made, services),
        status_code=202,
        headers=_HEADERS,
    )


@router.get("/creatures/drafts/{draft_id}")
def read_creature_draft(
    draft_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """One creature draft: queued, running, kept with its kind and look, erased since, refused with
    the check's code and its fixed sentence, or failed with why."""
    found = drafts.read_draft(
        connection, session.workspace_id, draft_id, owner_actor_id=session.actor
    )
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(_view(connection, session.workspace_id, found, services), headers=_HEADERS)


def _look_view(look: look_jobs.CreatureLook) -> dict[str, Any]:
    return {
        "profile": LOOK_PROFILE,
        "look_id": str(look.look_id),
        "status": look.status,
        "kind_sha256": look.kind_sha256,
        "look_sha256": look.look_sha256,
        "refusal": look.refusal_code,
        "failure": look.failure,
        "cost_usd": None if look.cost_usd is None else str(look.cost_usd),
        "created_at": look.created_at.isoformat(),
        "staged_at": None if look.staged_at is None else look.staged_at.isoformat(),
        "finished_at": None if look.finished_at is None else look.finished_at.isoformat(),
    }


@router.post("/creatures/{kind_sha256}/looks", status_code=202)
def ask_creature_look(
    kind_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Ask for a made look of a creature this workspace keeps; answers 202 with its look job at
    once, or with the one already waiting for that creature."""
    # The creature is looked for first, so a kind this workspace does not keep is answered alike
    # wherever it is asked.
    if not look_jobs.keeps_creature(connection, session.workspace_id, kind_sha256):
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    if session.workspace_id not in services.creature_workspaces:
        return _refusal(409, "creatures_not_run_here", "creature looks are not made here")
    try:
        asked = look_jobs.ask_look(
            connection, session.workspace_id, kind_sha256=kind_sha256, requested_by=session.actor
        )
    except look_jobs.LookNotAsked:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    except look_jobs.LookLimitReached:
        return _refusal(
            429,
            "look_limit_reached",
            f"at most {look_jobs.MAX_OPEN_PER_ACTOR} look jobs open and "
            f"{look_jobs.MAX_PER_ACTOR_HOUR} an hour for one requester",
        )
    return JSONResponse(_look_view(asked), status_code=202, headers=_HEADERS)


@router.get("/creatures/looks/{look_id}")
def read_creature_look(
    look_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    """One look job, for any member of the workspace: queued, staged, made with the look's digest,
    refused with the fit's code, or failed or cancelled with why."""
    found = look_jobs.read_look(connection, session.workspace_id, look_id)
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(_look_view(found), headers=_HEADERS)
