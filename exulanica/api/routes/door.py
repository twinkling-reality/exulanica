"""The door for outside programs: grants for a world's owner, and a channel for a bridge.

A world's owner lets a bridge the deployment admits decide for some of the world's things, or bring
visitors in, by issuing a grant (``POST /door/grants``); named things are bound in the version the
body names, through the choice record, in the grant's own transaction. The owner revokes a grant;
ends its credentials without ending it (``POST /door/grants/{grant_id}/credentials/revoke``); and
opens it either with an invite
a server bridge redeems (``POST /door/grants/{grant_id}/invites``) or with a channel credential
shown once (``.../channel-credentials``), for a program the owner runs or a server bridge declared
for the owner's workspace alone. These owner routes need ``world.write`` and ``door.grant``; the
reads need ``world.read``.

A bridge redeems an invite with its deployment credential (``POST /door/invites/redeem``) and then
acts on its grant's channel with the channel credential it received: it says hello with its
adapter's version and mapping (``POST /door/channel/hello``), reads frames by long-poll
(``GET /door/channel/frames``) and answers asks (``POST /door/channel/answers``). Its credential
reaches nothing else, and no account's credential reaches these (:class:`exulanica.api.permissions.
Channel`). Every body is bounded before it is read (:data:`BODY_LIMITS`).

**The long-poll holds nothing while it waits.** A held poll is a socket and a place in the streams
admission class. Each read opens a short connection in a poller thread from a limiter every held
poll in the process shares, runs one cheap head read, and builds frames only when the head says
something is new; between reads it is an awaited sleep. Within this process an ask the decision
host writes wakes its grant's poll at once (:mod:`exulanica.door.notices`); otherwise the head is
read once a second. One poll is held per grant, a second poll for the same grant ending the first
with nothing to send; a workspace and a bridge each hold at most their share of the process's
polls, and a full bridge or process gives a workspace holding fewer the place of the oldest poll of
the workspace holding the most (:class:`exulanica.door.notices.HeldPolls`); a poll whose client went
away ends at its next read. Every poll checks its grant: once the
bridge has read that the grant ended, its polls and hellos are refused.

The route validates and delegates: grants, secrets, the channel and the protocol are
:mod:`exulanica.door`'s.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Final, TypeVar

import anyio
import anyio.to_thread
import psycopg
from anyio.lowlevel import RunVar
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import (
    CurrentBridge,
    CurrentChannel,
    CurrentSession,
    ScopedConnection,
    get_services,
)
from exulanica.api.routes.society_models import CHOICE_CONFLICTS
from exulanica.api.world_scope import WorldId
from exulanica.door.bridges import BridgeDirectory
from exulanica.door.channel import (
    ChannelRefused,
    ChannelRepository,
    presence_of,
    presence_window,
)
from exulanica.door.grants import (
    MINUTES_DEFAULT,
    MINUTES_MAXIMUM,
    THINGS_MAXIMUM,
    VISITORS_MAXIMUM,
    WORLD_WORDS_MAXIMUM,
    Grant,
    GrantRefused,
    GrantRepository,
    Scope,
)
from exulanica.door.protocol import (
    ANSWER_BODY_BYTES,
    DECLARED_MIND_MAXIMUM,
    FRAME_PROFILE,
    HELLO_BODY_BYTES,
    HOLD_SECONDS_DEFAULT,
    LINE_CHARACTERS_MAXIMUM,
    OWNER_BODY_BYTES,
    READS_MAXIMUM,
    REDEEM_BODY_BYTES,
    Cursor,
    InvalidCursor,
)
from exulanica.door.runtime import DoorRuntime
from exulanica.door.secrets import (
    ChannelSession,
    InviteNotRedeemable,
    TooManyRedemptions,
    redeem_invite,
)

router = APIRouter(prefix="/door", tags=["door"])

__all__ = ["BODY_LIMITS", "router"]

_T = TypeVar("_T")

#: Each door route's own body limit (:mod:`exulanica.api.body_limit`), refused before the body is
#: read or parsed: the server-wide limit is sized for photographs, and a door body is a small
#: document. Routes with no body are bounded by the owners' limit.
BODY_LIMITS: Final = (
    ("POST", "/door/grants", OWNER_BODY_BYTES),
    ("POST", "/door/grants/{grant_id}/revoke", OWNER_BODY_BYTES),
    ("POST", "/door/grants/{grant_id}/invites", OWNER_BODY_BYTES),
    ("POST", "/door/grants/{grant_id}/channel-credentials", OWNER_BODY_BYTES),
    ("POST", "/door/grants/{grant_id}/credentials/revoke", OWNER_BODY_BYTES),
    ("POST", "/door/invites/redeem", REDEEM_BODY_BYTES),
    ("POST", "/door/channel/hello", HELLO_BODY_BYTES),
    ("POST", "/door/channel/answers", ANSWER_BODY_BYTES),
)
#: How a grant refusal answers, by its code. A refusal of the choice record that binds a grant's
#: named things answers as the choices route answers it: CHOICE_CONFLICTS 409, any other 422.
_GRANT_STATUS: Final = {
    "invalid_scope": 422,
    "invalid_idempotency_key": 422,
    "bridge_not_offered": 422,
    "invites_not_offered": 422,
    "direct_credential_not_offered": 422,
    "unknown_world": 404,
    "idempotency_key_reused": 409,
    "unknown_grant": 404,
    "grant_ended": 409,
    "too_many_secrets": 409,
    **dict.fromkeys(CHOICE_CONFLICTS, 409),
}
#: The poller threads every held poll in one process reads with, and so the most connections the
#: process's held polls use at once.
DOOR_POLLERS: Final = 4
#: How often a held poll reads its head when nothing in this process woke it, and how often it
#: checks for that wake-up between reads.
_HEAD_EVERY_SECONDS: Final = 1.0
_WAKE_EVERY_SECONDS: Final = 0.05
#: A poll read's statement timeout: the reads are indexed and take milliseconds.
_POLL_TIMEOUT_MS: Final = 5000
_POLLERS: RunVar[anyio.CapacityLimiter] = RunVar("exulanica_door_pollers")


def _problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    """The one failure shape this package answers with, as every route module writes it."""
    return JSONResponse(status_code=status, content={**extra, "code": code, "detail": detail})


def _door(request: Request) -> DoorRuntime | None:
    return get_services(request).door


def _unavailable() -> JSONResponse:
    return _problem(503, "door_unavailable", "this server admits no outside programs")


def _refused(exc: GrantRefused) -> JSONResponse:
    if exc.code in ("unknown_grant",):
        return _problem(404, "unknown_reference", "nothing at this address is available")
    return _problem(_GRANT_STATUS.get(exc.code, 422), exc.code, exc.detail)


def _shown_once(issued: Any) -> dict[str, Any]:
    return {
        "credential": issued.text,
        "expires_at": issued.expires_at.isoformat(timespec="microseconds"),
        "shown": "once",
    }


# -- what an owner sends ---------------------------------------------------------------------


class IssueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)
    bridge: str = Field(min_length=1, max_length=32)
    visitors_maximum: int = Field(default=0, ge=0, le=VISITORS_MAXIMUM)
    kinds: list[str] = Field(default_factory=list, max_length=16)
    things: list[uuid.UUID] = Field(default_factory=list, max_length=THINGS_MAXIMUM)
    #: The world version the named things are bound in; a version's society is its own.
    version_id: uuid.UUID | None = None
    gate: uuid.UUID | None = None
    may_carry_in: bool = False
    may_carry_out: bool = False
    may_speak: bool = True
    #: The words the bridge may show players for the world, chosen here; never the world's title.
    world_words: str | None = Field(default=None, max_length=WORLD_WORDS_MAXIMUM)
    minutes: int = Field(default=MINUTES_DEFAULT, ge=1, le=MINUTES_MAXIMUM)
    channel_credential: bool = False


def _grant_view(
    grant: Grant,
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    bridges: BridgeDirectory | None,
) -> dict:
    presence = presence_of(connection, workspace_id, grant.grant_id)
    row = connection.execute("select statement_timestamp() as now").fetchone()
    assert row is not None
    now = row["now"]
    bridge = None if bridges is None else bridges.get(grant.bridge)
    return {
        **grant.view(),
        "ended": grant.ended(now),
        "bridge_label": None if bridge is None else bridge.label,
        "run_by": None if bridge is None else bridge.run_by,
        "ai": None if bridge is None else bridge.ai,
        "connected": presence is not None
        and bridge is not None
        and presence.admitted_by(bridge)
        and presence.connected(now, presence_window(bridge)),
        "adapter_version": None if presence is None else presence.adapter_version,
        # The program's own words about itself, as it last said hello: for a person reading a card.
        "declared": None if presence is None or presence.declared is None else presence.declared,
    }


def _bridges_of(request: Request) -> BridgeDirectory | None:
    door = _door(request)
    return None if door is None else door.bridges


@router.get("/bridges")
def bridges(request: Request, session: CurrentSession) -> Any:
    """The bridges this deployment offers this workspace, in words, and who runs each."""
    door = _door(request)
    offered = () if door is None else door.bridges.offered_to(session.workspace_id)
    return {
        "bridges": [
            {
                "bridge": bridge.key,
                "label": bridge.label,
                "game": bridge.game,
                "run_by": bridge.run_by,
                "ai": bridge.ai,
            }
            for bridge in offered
        ]
    }


@router.post("/grants")
def issue_grant(
    request: Request,
    body: IssueBody,
    session: CurrentSession,
    connection: ScopedConnection,
    world_id: WorldId,
) -> Any:
    """Issue a grant in one world for one bridge, or answer with the one this key issued."""
    door = _door(request)
    if door is None:
        return _unavailable()
    bridge = door.bridges.get(body.bridge)
    if bridge is None or not bridge.offered_to(session.workspace_id):
        return _problem(422, "bridge_not_offered", "this deployment offers no such bridge here")
    if body.channel_credential and not bridge.direct_credentials_for(session.workspace_id):
        # Refused before anything is issued, so an owner is never left with a grant they asked to
        # open another way.
        return _problem(
            422,
            "direct_credential_not_offered",
            "this bridge's grants open only with invites its own server redeems",
        )
    try:
        scope = Scope(
            visitors_maximum=body.visitors_maximum,
            kinds=tuple(body.kinds),
            things=tuple(str(thing) for thing in body.things),
            version_id=None if body.version_id is None else str(body.version_id),
            gate=None if body.gate is None else str(body.gate),
            may_carry_in=body.may_carry_in,
            may_carry_out=body.may_carry_out,
            may_speak=body.may_speak,
            world_words=body.world_words,
        )
        grants = GrantRepository(connection, session.workspace_id, session.actor)
        grant, issued = grants.issue(
            world_id=world_id,
            bridge=bridge,
            scope=scope,
            minutes=body.minutes,
            idempotency_key=body.idempotency_key,
        )
        credential = (
            grants.direct_channel(grant.grant_id, door.bridges)
            if issued and body.channel_credential
            else None
        )
    except GrantRefused as exc:
        return _refused(exc)
    content: dict[str, Any] = {
        "grant": _grant_view(grant, connection, session.workspace_id, door.bridges)
    }
    if credential is not None:
        content["channel_credential"] = _shown_once(credential)
    return JSONResponse(status_code=201 if issued else 200, content=content)


@router.get("/grants")
def world_grants(
    request: Request, session: CurrentSession, connection: ScopedConnection, world_id: WorldId
) -> Any:
    """Every grant issued in one world, newest first, each as it stands now."""
    grants = GrantRepository(connection, session.workspace_id, session.actor)
    directory = _bridges_of(request)
    return {
        "grants": [
            _grant_view(grant, connection, session.workspace_id, directory)
            for grant in grants.in_world(world_id)
        ]
    }


@router.get("/grants/{grant_id}")
def one_grant(
    request: Request, grant_id: uuid.UUID, session: CurrentSession, connection: ScopedConnection
) -> Any:
    grant = GrantRepository(connection, session.workspace_id, session.actor).current(grant_id)
    if grant is None:
        return _problem(404, "unknown_reference", "nothing at this address is available")
    return {"grant": _grant_view(grant, connection, session.workspace_id, _bridges_of(request))}


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(
    request: Request, grant_id: uuid.UUID, session: CurrentSession, connection: ScopedConnection
) -> Any:
    """End a grant now. Revoking twice changes nothing."""
    door = _door(request)
    if door is None:
        return _unavailable()
    try:
        grant = GrantRepository(connection, session.workspace_id, session.actor).revoke(grant_id)
    except GrantRefused as exc:
        return _refused(exc)
    return {"grant": _grant_view(grant, connection, session.workspace_id, door.bridges)}


@router.post("/grants/{grant_id}/credentials/revoke")
def revoke_credentials(
    request: Request, grant_id: uuid.UUID, session: CurrentSession, connection: ScopedConnection
) -> Any:
    """End every live invite and channel credential of a grant now, without ending the grant: after
    a credential leaked, the owner ends them all and gives the bridge a new one."""
    door = _door(request)
    if door is None:
        return _unavailable()
    grants = GrantRepository(connection, session.workspace_id, session.actor)
    try:
        revoked = grants.revoke_credentials(grant_id)
    except GrantRefused as exc:
        return _refused(exc)
    grant = grants.current(grant_id)
    assert grant is not None
    return {
        "revoked": revoked,
        "grant": _grant_view(grant, connection, session.workspace_id, door.bridges),
    }


@router.post("/grants/{grant_id}/invites")
def invite(
    request: Request, grant_id: uuid.UUID, session: CurrentSession, connection: ScopedConnection
) -> Any:
    """A one-use invite to a standing grant of a server bridge, shown once, for a player of its
    bridge to use."""
    door = _door(request)
    if door is None:
        return _unavailable()
    try:
        issued = GrantRepository(connection, session.workspace_id, session.actor).invite(
            grant_id, door.bridges
        )
    except GrantRefused as exc:
        return _refused(exc)
    return JSONResponse(
        status_code=201,
        content={
            "code": issued.text,
            "expires_at": issued.expires_at.isoformat(timespec="microseconds"),
            "shown": "once",
        },
    )


@router.post("/grants/{grant_id}/channel-credentials")
def channel_credential(
    request: Request, grant_id: uuid.UUID, session: CurrentSession, connection: ScopedConnection
) -> Any:
    """A channel credential for a standing grant, shown once: for a program its owner runs, or a
    server bridge declared for this workspace alone."""
    door = _door(request)
    if door is None:
        return _unavailable()
    try:
        issued = GrantRepository(connection, session.workspace_id, session.actor).direct_channel(
            grant_id, door.bridges
        )
    except GrantRefused as exc:
        return _refused(exc)
    return JSONResponse(status_code=201, content=_shown_once(issued))


# -- what a bridge sends ---------------------------------------------------------------------


class RedeemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    #: Who typed the code at the bridge, as a digest the bridge derives, never a name: one
    #: requester's failed codes lock out that requester alone.
    requester: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeclaredBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=DECLARED_MIND_MAXIMUM)
    maker: str = Field(min_length=1, max_length=DECLARED_MIND_MAXIMUM)
    mind: str | None = Field(default=None, min_length=1, max_length=DECLARED_MIND_MAXIMUM)


class HelloBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_version: str = Field(min_length=1, max_length=32)
    mapping: dict[str, Any]
    reads: list[str] = Field(min_length=1, max_length=READS_MAXIMUM)
    #: What the program behind the bridge says it is: words for a card, never for a model.
    declared: DeclaredBody | None = None


class ChannelAnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: str = Field(min_length=1, max_length=120)
    #: Bounded loosely here so the line's own rule answers by name (``line_refused``).
    line: str | None = Field(default=None, max_length=4 * LINE_CHARACTERS_MAXIMUM)


def _channel_problem(exc: ChannelRefused) -> JSONResponse:
    return _problem(exc.status, exc.code, exc.detail)


def _on_channel(
    request: Request, channel: ChannelSession, work: Callable[[ChannelRepository], _T]
) -> _T:
    services = get_services(request)
    door = services.door
    assert door is not None  # a channel credential resolved only with a door
    with services.database.session(channel.workspace_id) as connection:
        connection.execute(
            "select set_config('statement_timeout', %s, false)", (f"{_POLL_TIMEOUT_MS}ms",)
        )
        return work(ChannelRepository(connection, channel, door.bridges))


@router.post("/invites/redeem")
def redeem(request: Request, body: RedeemBody, bridge: CurrentBridge) -> Any:
    """Redeem one invite, as the bridge whose credential is presented, for a channel credential."""
    services = get_services(request)
    open_to = None if services.door is None else services.door.open_to
    try:
        redeemed = redeem_invite(services.database, bridge, body.code, body.requester, open_to)
    except TooManyRedemptions:
        return _problem(
            429,
            TooManyRedemptions.code,
            "this requester failed too many redemptions in the last minute",
            retry_after_s=TooManyRedemptions.retry_after_s,
        )
    except InviteNotRedeemable:
        return _problem(404, InviteNotRedeemable.code, "this invite opens nothing for this bridge")
    return JSONResponse(
        status_code=201,
        content={"grant": redeemed.grant.view(), **_shown_once(redeemed.channel)},
    )


@router.post("/channel/hello")
def hello(request: Request, body: HelloBody, channel: CurrentChannel) -> Any:
    """Present the adapter, its mapping and the program's own words for this grant."""
    door = _door(request)
    assert door is not None  # a channel credential resolved only with a door
    if not door.hellos.admit(channel.grant_id):
        return _problem(
            429,
            "too_many_hellos",
            "this channel said hello too often in the last minute",
            retry_after_s=60,
        )
    declared = None if body.declared is None else body.declared.model_dump(exclude_none=True)
    try:
        return _on_channel(
            request,
            channel,
            lambda repository: repository.hello(
                adapter_version=body.adapter_version,
                mapping=body.mapping,
                reads=body.reads,
                declared=declared,
            ),
        )
    except ChannelRefused as exc:
        return _channel_problem(exc)


@router.post("/channel/answers")
def answer(request: Request, body: ChannelAnswerBody, channel: CurrentChannel) -> Any:
    """Answer one open ask of this grant with one of the labels it offered."""
    payload = {
        "request_id": str(body.request_id),
        "request_sha256": body.request_sha256,
        "label": body.label,
        "line": body.line,
    }
    try:
        digest = _on_channel(request, channel, lambda repository: repository.answer(payload))
    except ChannelRefused as exc:
        return _channel_problem(exc)
    door = _door(request)
    if door is not None:
        door.notices.answered(body.request_id)
    return JSONResponse(status_code=202, content={"received": True, "answer_sha256": digest})


async def _in_thread(work: Callable[[], _T]) -> _T:
    try:
        limiter = _POLLERS.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(DOOR_POLLERS)
        _POLLERS.set(limiter)
    return await anyio.to_thread.run_sync(work, limiter=limiter)


def _frames(found: tuple[list[dict], Cursor]) -> dict[str, Any]:
    sent, after_them = found
    return {"profile": FRAME_PROFILE, "frames": sent, "cursor": after_them.encode()}


@router.get("/channel/frames")
async def frames(
    request: Request,
    channel: CurrentChannel,
    after: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    """What was sent to this grant after the cursor, held up to the bridge's hold for something."""
    door = _door(request)
    assert door is not None  # a channel credential resolved only with a door
    try:
        cursor = Cursor.decode(after)
    except InvalidCursor:
        return _problem(422, InvalidCursor.code, "this cursor was not written by this door")
    bridge = door.bridges.get(channel.bridge)
    hold_seconds = HOLD_SECONDS_DEFAULT if bridge is None else bridge.hold_seconds
    token = door.polls.hold(channel.grant_id, channel.workspace_id, channel.bridge)
    if token is None:
        return _problem(
            503, "door_busy", "this server holds as many polls as it can", retry_after_ms=1000
        )
    try:
        try:
            first = await _in_thread(
                lambda: _on_channel(request, channel, lambda r: r.open_poll(cursor))
            )
        except ChannelRefused as exc:
            return _channel_problem(exc)
        if first is not None and (first[0] or first[1] != cursor):
            return _frames(first)
        ends = time.monotonic() + hold_seconds
        woken = door.notices.asks(channel.grant_id)
        next_head = time.monotonic() + _HEAD_EVERY_SECONDS
        while True:
            now = time.monotonic()
            asks = door.notices.asks(channel.grant_id)
            if now >= next_head or asks != woken:
                woken = asks
                next_head = now + _HEAD_EVERY_SECONDS
                if await request.is_disconnected():
                    return {"profile": FRAME_PROFILE, "frames": [], "cursor": cursor.encode()}
                try:
                    found = await _in_thread(
                        lambda: _on_channel(request, channel, lambda r: r.read(cursor))
                    )
                except ChannelRefused as exc:
                    return _channel_problem(exc)
                if found is not None and (found[0] or found[1] != cursor):
                    return _frames(found)
            if now >= ends or not door.polls.holds(channel.grant_id, token):
                return {"profile": FRAME_PROFILE, "frames": [], "cursor": cursor.encode()}
            await anyio.sleep(_WAKE_EVERY_SECONDS)
    finally:
        door.polls.release(channel.grant_id, token)
