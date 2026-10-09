"""A workspace's own things over HTTP: the looks and kinds it holds, each by its digest.

The shipped library (:mod:`exulanica.api.routes.things`) serves what every workspace reads alike.
These routes serve what one workspace holds in its own store (:mod:`exulanica.world.thing_store`):
a creature's sketch, a sculpted look, a traveller's own look, a drafted kind. Each reads the
requester's own workspace under row-level security, on a short read-only connection closed before
any byte is sent, so another workspace's thing, a withdrawn look and an absent one all answer 404
``unknown_reference`` alike, and a renderer falls back to the kind's first look.

*   ``GET /things/looks/{look_sha256}`` answers the look document the workspace holds at that
    digest, with its origin for the card, never cached.
*   ``GET /things/looks/{look_sha256}/container`` answers that look's container, read from the
    workspace's ``looks`` namespace and verified against the digest the look names, as
    ``model/gltf-binary``. It is addressed by the look's digest, never the container's, so only a
    held look's own container is ever served. A browser keeps it, tagged with the look's digest,
    but asks again before each use (``no-cache``): a revalidation naming that tag is answered 304
    with no body while the look is held, and 404 once it is withdrawn, so a withdrawal reaches
    every cache.
*   ``GET /things/kinds/{kind_sha256}`` answers the kind the workspace holds at that digest, read
    again with its looks and its plan resolved in the store, never cached.
*   ``GET /things/plans/{plan_sha256}`` answers the drafted body plan the workspace holds at that
    digest, read again, never cached: what a page draws a held kind's figure on, since the shipped
    library holds only the shipped plans.
*   ``DELETE /things/kinds/{kind_sha256}`` erases a creature the workspace drafted from a
    person's words, whole and at once (:meth:`ThingStore.erase_creature`): its kind and, with its
    drafted plan, the plan, its recipe and every look drawn on it, whose containers the purge
    worker then destroys. Answered 204; a kind the workspace does not hold answers 404
    ``unknown_reference``, as a read does. It needs ``world.write`` and ``deletion.write``, and
    only the person who drafted the creature or an owner of the workspace erases it: an owner by
    the membership record (a browser session held in the ``owner`` role), anyone else only a
    creature their own actor drafted, so a guest, or a bearer token, which holds no membership,
    erases only its own; anyone else's ask is 403 ``kind_not_yours``. A row the database refuses
    is 409 ``kind_changed``, an installation sealed for a restore 409 ``restore_sealed``, and a
    workspace another transaction holds 409 ``busy`` with ``Retry-After``, as every route answers
    it.

Each read needs a session (``world.read``), as the library does.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response

from exulanica.api.account_repository import AccountRejected, AccountUnavailable
from exulanica.api.authorisation import TokenNotAccepted
from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlySessions,
    ScopedConnection,
    get_services,
)
from exulanica.api.routes.tiles import _revalidates
from exulanica.canonical import canonical_json
from exulanica.evidence.blob import BlobId
from exulanica.selection.validation import Session
from exulanica.world.committed_content import DIGEST
from exulanica.world.thing_store import ThingStore, ThingStoreRefused

__all__ = ["router"]

router = APIRouter(prefix="/things", tags=["things"])

_DOCUMENT_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
_GLB = "model/gltf-binary"


def _absent() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"code": "unknown_reference", "detail": "this workspace holds no such thing"},
        headers=_DOCUMENT_HEADERS,
    )


def _document(document: Any) -> Response:
    """A document's canonical bytes, as the shipped library serves its own."""
    return Response(
        content=canonical_json(dict(document)),
        media_type="application/json",
        headers=_DOCUMENT_HEADERS,
    )


@router.get(
    "/looks/{look_sha256}",
    summary="A look this workspace holds, by the SHA-256 of its document.",
)
def held_look(
    look_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    sessions: ReadOnlySessions,
    session: CurrentSession,
) -> Any:
    with sessions() as connection:
        kept = ThingStore(connection, session.workspace_id, None).look_by_digest(look_sha256)
    if kept is None:
        return _absent()
    return _document(kept.look.document)


@router.get(
    "/looks/{look_sha256}/container",
    summary="The container of a look this workspace holds, by the SHA-256 of the look.",
    responses={200: {"content": {_GLB: {}}}},
)
def held_look_container(
    look_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    request: Request,
    sessions: ReadOnlySessions,
    session: CurrentSession,
) -> Any:
    with sessions() as connection:
        kept = ThingStore(connection, session.workspace_id, None).look_by_digest(look_sha256)
    if kept is None:
        return _absent()
    headers = {
        "ETag": f'"{look_sha256}"',
        "Cache-Control": "private, no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    if _revalidates(request.headers.get("if-none-match"), look_sha256):
        return Response(status_code=304, headers=headers)
    stores = get_services(request).content_stores
    if stores is None:
        return JSONResponse(
            status_code=503,
            content={"code": "look_store_unavailable", "detail": "this server holds no looks"},
            headers=_DOCUMENT_HEADERS,
        )
    looks = stores.looks.for_workspace(session.workspace_id)
    # ``get`` reads the whole object and verifies it hashes to its key.
    data = looks.get(BlobId.from_hex(kept.container_sha256))
    return Response(content=data, media_type=_GLB, headers=headers)


@router.get(
    "/kinds/{kind_sha256}",
    summary="A thing kind this workspace holds, by the SHA-256 of its document.",
)
def held_kind(
    kind_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    sessions: ReadOnlySessions,
    session: CurrentSession,
) -> Any:
    with sessions() as connection:
        held = ThingStore(connection, session.workspace_id, None).kind_by_digest(kind_sha256)
    if held is None:
        return _absent()
    return _document(held.document)


@router.get(
    "/plans/{plan_sha256}",
    summary="A body plan this workspace holds, by the SHA-256 of its document.",
)
def held_plan(
    plan_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    sessions: ReadOnlySessions,
    session: CurrentSession,
) -> Any:
    with sessions() as connection:
        document = ThingStore(connection, session.workspace_id, None).plan_document_by_digest(
            plan_sha256
        )
    if document is None:
        return _absent()
    return _document(document)


@router.delete(
    "/kinds/{kind_sha256}",
    summary="Erase a creature this workspace drafted, whole, by the SHA-256 of its kind.",
    status_code=204,
)
def erase_kind(
    kind_sha256: Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")],
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
) -> Response:
    try:
        ThingStore(connection, session.workspace_id, None).erase_creature(
            kind_sha256, erased_by=session.actor, by_owner=_owns_workspace(request, session)
        )
    except ThingStoreRefused as refused:
        if refused.code == "kind_unknown":
            return _absent()
        return JSONResponse(
            status_code=403 if refused.code == "kind_not_yours" else 409,
            content={"code": refused.code, "detail": refused.detail},
            headers=_DOCUMENT_HEADERS,
        )
    return Response(status_code=204)


def _owns_workspace(request: Request, session: Session) -> bool:
    """Whether the caller owns this workspace by its membership record (0058's ``owner``): a
    browser session held in that role for this workspace. A bearer token is the operator's grant
    to a program and holds no membership, so it answers no; it erases only what its actor drafted.
    The account tables are the account role's alone, so the account runtime reads the role."""
    accounts = get_services(request).accounts
    if accounts is None or request.headers.get("authorization") is not None:
        return False
    try:
        account = accounts.browser_session(request)
    except (AccountRejected, AccountUnavailable, TokenNotAccepted):
        return False
    return account.role == "owner" and account.session.workspace_id == session.workspace_id
