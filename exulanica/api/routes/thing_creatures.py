"""A creature from a person's words: ask for one, then read how its draft went.

``POST /things/creatures`` takes the person's words for one creature and answers ``202`` at once
with a draft (``exulanica.creature-draft/v1``) that a worker in this process plays
(:mod:`exulanica.selection.creature_drafts`): it asks the creature drafter, holds the creature to
every check a thing passes, and keeps one that passes in the workspace's own store, its sketch its
first look. ``GET /things/creatures/drafts/{draft_id}`` answers the draft as it goes: ``queued`` and
``running``; ``kept``, naming the kind made and its sketch by digest (served by
:mod:`exulanica.api.routes.thing_store`) and the model that drafted it; ``erased``, a kept draft
whose creature the workspace has erased since; ``refused``, with the check's code, the field of the
drafter's form it refused and the code's fixed sentence; ``failed``, with why by code; or
``cancelled``, ended by its workspace's erasure (``workspace_deleted``).

The words are sent with every saved name replaced (:func:`exulanica.selection.world_drafting.
sendable`) and are kept only in the draft's job until it ends; the draft keeps nothing of them.
Only the workspaces this installation lists draft creatures (``EXULANICA_CREATURE_WORKSPACES``), at
most one unfinished draft and a bounded number an hour for one requester; only the requester reads
a draft. Asking needs ``world.write`` and ``model.invoke``; reading needs ``world.read``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends
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
from exulanica.world.thing_store import ThingStore

__all__ = ["DRAFTS_PROFILE", "DRAFT_PROFILE", "OFFER_CODES", "OFFER_PROFILE", "router"]

router = APIRouter(prefix="/things", tags=["things"])

DRAFT_PROFILE: Final = "exulanica.creature-draft/v1"
OFFER_PROFILE: Final = "exulanica.creature-offer/v1"
DRAFTS_PROFILE: Final = "exulanica.creature-drafts/v1"
#: Why a workspace may not ask for a creature here, by code.
OFFER_CODES: Final = drafts.OFFER_REFUSALS
#: Another requester's draft answers exactly as one that does not exist.
_UNKNOWN: Final = "unknown_reference"
_UNKNOWN_DETAIL: Final = "nothing at this address is available to this credential"
_HEADERS: Final = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class CreatureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The person's words for one creature, as they typed them.
    words: str


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status, headers=_HEADERS)


def _view(connection: Any, workspace_id: uuid.UUID, draft: drafts.CreatureDraft) -> dict[str, Any]:
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
    return {
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
        "created_at": draft.created_at.isoformat(),
        "started_at": None if draft.started_at is None else draft.started_at.isoformat(),
        "finished_at": None if draft.finished_at is None else draft.finished_at.isoformat(),
    }


@router.get("/creatures/offered")
def creature_offer(
    session: CurrentSession, services: Annotated[Services, Depends(get_services)]
) -> JSONResponse:
    """Whether this workspace may ask for a creature here, why not by code, how long a draft
    usually takes by the creature drafter's measured calls, and every code a draft may end with."""
    code = services.creature_offer_refusal(session.workspace_id)
    offered = code is None
    binding = load_manifest()[Role.CREATURE_DRAFTER]
    basis = binding.timeout_basis
    return JSONResponse(
        {
            "profile": OFFER_PROFILE,
            "offered": offered,
            "code": code,
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
def list_creature_drafts(connection: ReadOnlyConnection, session: CurrentSession) -> JSONResponse:
    """The requester's own drafts, newest first: a reload or a second tab finds one still
    running."""
    listed = drafts.list_drafts(connection, session.workspace_id, owner_actor_id=session.actor)
    return JSONResponse(
        {
            "profile": DRAFTS_PROFILE,
            "drafts": [_view(connection, session.workspace_id, draft) for draft in listed],
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
        _view(connection, session.workspace_id, made), status_code=202, headers=_HEADERS
    )


@router.get("/creatures/drafts/{draft_id}")
def read_creature_draft(
    draft_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    """One creature draft: queued, running, kept with its kind and look, erased since, refused with
    the check's code and its fixed sentence, or failed with why."""
    found = drafts.read_draft(
        connection, session.workspace_id, draft_id, owner_actor_id=session.actor
    )
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(_view(connection, session.workspace_id, found), headers=_HEADERS)
