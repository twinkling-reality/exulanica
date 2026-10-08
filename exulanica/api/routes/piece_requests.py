"""Piece requests: asking a GPU for new pieces of a world's look.

``POST /world/piece-requests`` names a world, a committed look (a style pack version, by its id,
version and manifest digest) the pieces are made in, and up to 16 shipped thing kinds. Each kind
becomes one request (:mod:`exulanica.generation.requests`): its words come from catalogs alone, so
a request holds no text a person typed. The answer is ``202`` with the requests, what they will
take in items, seconds and US dollars, and whether a generation session is running, at once; an
idempotency key answers ``200`` with the requests its first answer held, and an ask for pieces
already waiting for the same world answers ``200`` with them. A deleted workspace answers ``410``.
Asking is the consent to the world's look taking each passed piece in as it arrives; the world
never waits on one.

The GPU runs on a session the operator starts (Nebius AI Cloud, the operator's account). Until a
session takes a request it waits as ``requested``; a guest may ask only while a session is running.
Nothing is spent here: the request states its worst case, the workspace's ``nebius_ai_cloud_gpu``
allowance must cover it, and the worker that queues it admits, dispatches and settles it from what
the GPU measured.

``GET /world/piece-requests?world_id=`` lists a world's requests, newest first;
``GET /world/piece-requests/{piece_request_id}`` reads one; ``DELETE`` cancels one no session has
taken.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from typing import Annotated, Any, Final

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.generation import store
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    PieceAskRefused,
    estimate,
    generation_catalogs,
    plan_requests,
)
from exulanica.models.spending import SpendingRefused
from exulanica.spending.status import admission_refusal, read_workspace_status
from exulanica.world.style_pack_library import style_pack_library

__all__ = ["router"]

router = APIRouter(prefix="/world", tags=["world"])

#: Another workspace's request answers exactly as one that does not exist.
_UNKNOWN: Final = "unknown_piece_request"
_UNKNOWN_DETAIL: Final = "nothing at this address is available to this credential"
#: Whether a generation session is running: none can be until the worker that starts and follows
#: one lands, so every answer says so.
_SESSION_OFF: Final = {
    "state": "off",
    "detail": "the piece maker is off; requests wait until the operator starts it",
}


class KindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    version: int = Field(ge=1)


class LookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$")
    version: int = Field(ge=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PieceAskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The world whose look takes the pieces in.
    world_id: Annotated[str, Field(min_length=1, max_length=200)]
    #: The committed look the pieces are made in.
    look: LookBody
    #: Up to 64 are read, so an ask naming more than an ask may hold is refused by name.
    kinds: list[KindBody] = Field(min_length=1, max_length=64)
    idempotency_key: uuid.UUID | None = None


def _refusal(
    status: int, code: str, detail: str, extensions: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail, **(extensions or {})}, status_code=status)


def _ask_sha256(body: PieceAskBody) -> str:
    canonical = json.dumps(
        body.model_dump(mode="json", exclude={"idempotency_key"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _is_guest(request: Request, services: Services) -> bool:
    """Whether the caller is a guest's browser session (a bearer token is never a guest's)."""
    if request.headers.get("authorization") is not None or services.accounts is None:
        return False
    return services.accounts.browser_session(request).role == "guest"


def _weigher(services: Services, workspace_id: uuid.UUID) -> store.Weigh:
    """Weigh an ask's new requests against the workspace's GPU allowance, inside the store's
    transaction and under its lock: admission's own answer first (its reason and scope), then the
    money left once every open request's worst case is set aside."""
    witnessed = services.spending is not None and services.spending.witness is not None

    def weigh(connection: Any, worst_case: Decimal, held: Decimal) -> None:
        document = read_workspace_status(connection, workspace_id, providers=[GPU_PROVIDER])
        entry = next(item for item in document["providers"] if item["provider"] == GPU_PROVIDER)
        refused = admission_refusal(entry, witness_configured=witnessed)
        if refused is None and Decimal(entry["available_usd"]) - held < worst_case:
            refused = SpendingRefused(
                "spending_limit_reached",
                scope="workspace",
                detail="usd",
                limit=entry["grant"]["ceiling_usd"],
                committed=str(Decimal(entry["committed_usd"]) + held),
                requested=str(worst_case),
            )
        if refused is not None:
            raise store.PieceAllowanceRefused(refused)

    return weigh


def _answer(
    records: list[store.PieceRequestRecord], extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "piece_requests": [record.document() for record in records],
        "session": dict(_SESSION_OFF),
        **(extra or {}),
    }


@router.post("/piece-requests", status_code=202)
def ask_for_pieces(
    request: Request,
    body: PieceAskBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Ask for new pieces of a world's look for some thing kinds. Answers 202 with the requests and
    their estimate; an idempotency key, or an ask already waiting, answers 200."""
    look = LookReference(body.look.pack_id, body.look.version, body.look.manifest_sha256)
    kinds = [(kind.key, kind.version) for kind in body.kinds]
    try:
        planned = plan_requests(kinds, look, library=style_pack_library())
    except PieceAskRefused as refused:
        return _refusal(422, refused.code, refused.detail)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    worst_cases = [compute.worst_case_usd(plan.variants) for plan in planned]
    if _is_guest(request, services):
        return _refusal(
            409,
            "generation_session_off",
            "a visitor's pieces are made only while the piece maker is running",
        )
    key = body.idempotency_key
    # Under the workspace's lock the store answers a key's earlier ask first, then weighs only the
    # requests it would make, beside what the workspace's open requests can still cost.
    try:
        records, made = store.create_piece_requests(
            connection,
            session.workspace_id,
            requested_by=session.actor,
            world_id=body.world_id,
            look=look,
            planned=planned,
            worst_cases=worst_cases,
            request_id=key,
            ask_sha256=None if key is None else _ask_sha256(body),
            weigh=_weigher(services, session.workspace_id),
        )
    except store.PieceAllowanceRefused as refused:
        member = {"spending": refused.refusal.problem_member()}
        return _refusal(429, "budget_exceeded", str(refused.refusal), member)
    except psycopg.errors.ForeignKeyViolation:
        return _refusal(404, "unknown_world", _UNKNOWN_DETAIL)
    except store.PieceQuotaExceeded as limit:
        return _refusal(429, "piece_quota_exceeded", str(limit))
    except store.PieceAskKeyReused:
        return _refusal(
            409, "idempotency_key_reused", "the key names an earlier ask with another body"
        )
    return JSONResponse(
        _answer(records, {"estimate": estimate(planned, compute).document()}),
        status_code=202 if made else 200,
    )


@router.get("/piece-requests")
def list_piece_requests(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: Annotated[str, Query(min_length=1, max_length=200)],
) -> JSONResponse:
    """A world's piece requests, newest first, and whether the piece maker is running."""
    return JSONResponse(
        _answer(store.list_piece_requests(connection, session.workspace_id, world_id))
    )


@router.get("/piece-requests/{piece_request_id}")
def read_piece_request(
    piece_request_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    """One piece request and where it stands."""
    found = store.read_piece_request(connection, session.workspace_id, piece_request_id)
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(found.document())


@router.delete("/piece-requests/{piece_request_id}")
def cancel_piece_request(
    piece_request_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    """Cancel a request no session has taken. One taken or ended is answered 409 with its state."""
    try:
        found = store.cancel_piece_request(connection, session.workspace_id, piece_request_id)
    except store.PieceRequestNotCancellable as taken:
        return _refusal(409, "piece_request_not_cancellable", str(taken), {"state": taken.state})
    if found is None:
        return _refusal(404, _UNKNOWN, _UNKNOWN_DETAIL)
    return JSONResponse(found.document())
