"""Opening a grant: the two lookups that run before any workspace is known.

A bridge presents one of two secrets, and neither request names a workspace:

*   **A channel credential**, on every channel request. Anything not shaped as the door writes one
    is refused before the database is asked. Its digest is looked up in ``door_secret`` (migration
    0149), which names the workspace and grant it opens; the request then runs in that workspace
    under row-level security like any other. A credential that was revoked, is past its end, or
    belongs to a bridge the deployment no longer declares or no longer offers to that workspace
    opens nothing.
*   **The deployment's bridge credential with an invite code**, to redeem the invite once for a
    channel credential. Only a bridge run by a server has one. The bridge credential is matched
    against the deployment's declared bridges (:mod:`exulanica.door.bridges`); the invite is looked
    up by its digest, used in the same statement that checks it is unused, unrevoked and unexpired,
    under its grant's lock, and only then is a channel credential issued, ending the grant's earlier
    one (a grant answers to one program at a time).

``door_secret`` carries no row-level security because it must be read before any workspace is
known, which is why it holds nothing but digests and identifiers. Both lookups read it on a
connection that declares no workspace (:meth:`exulanica.db.session.Database.unscoped`), in one
statement whether or not a row matches.

**One refusal for every failure.** A channel credential that is absent, malformed, unknown, revoked
or past its end is refused as :class:`ChannelNotAccepted`, and an invite that is malformed, unknown,
already used, revoked, expired, another bridge's, for a workspace the bridge is no longer offered to
or for a grant that has ended as :class:`InviteNotRedeemable`, each with one code and one sentence,
so a caller learns nothing about which guess came closer.

**A workspace that is closed opens nothing.** Where the deployment has accounts, a credential or an
invite opens a grant only while its workspace is open: its owner's account and membership stand and
the workspace is not disabled (``open_to``, which the application reads through its account role on
every request, as a browser session is checked). A disabled workspace's doors close at the next
request, and its societies stop playing, so nothing is asked there either.

**A lockout that locks out only the guesser.** A server bridge forwards codes that many people type,
so it names who typed each one with ``requester``, a digest it derives and never a name. Every
failed redemption is recorded against its bridge and requester; a requester with ten failures in the
last minute is refused before its code is read, and those refusals are not recorded, so the lockout
ends a minute after the last real failure and another requester of the same bridge is never held up.
Redemption prunes the door's global tables as it goes (:mod:`exulanica.door.retention`).
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.db.session import Database
from exulanica.door.bridges import Bridge, BridgeDirectory
from exulanica.door.credentials import (
    CHANNEL_CREDENTIAL_FORM,
    credential_sha256,
    normalise_invite_code,
)
from exulanica.door.grants import (
    Grant,
    GrantRefused,
    GrantRepository,
    IssuedSecret,
    grant_actor,
)
from exulanica.door.retention import prune
from exulanica.errors import ExulanicaError

__all__ = [
    "REDEMPTION_FAILURES_PER_MINUTE",
    "REQUESTER_FORM",
    "ChannelNotAccepted",
    "ChannelSession",
    "InviteNotRedeemable",
    "Redeemed",
    "TooManyRedemptions",
    "open_channel",
    "redeem_invite",
]

#: Failed redemptions one requester of a bridge may make in a minute before its next is refused
#: unread.
REDEMPTION_FAILURES_PER_MINUTE: Final = 10
#: A requester as a bridge names one: a SHA-256 digest it derives for whoever typed the code.
REQUESTER_FORM: Final = re.compile(r"[0-9a-f]{64}")


class ChannelNotAccepted(ExulanicaError):
    """The presented channel credential opens no grant."""


class InviteNotRedeemable(ExulanicaError):
    """The invite opens nothing for this bridge."""

    code: Final = "invite_not_redeemable"


class TooManyRedemptions(ExulanicaError):
    """This requester failed too many redemptions in the last minute."""

    code: Final = "too_many_redemptions"
    retry_after_s: Final = 60


@dataclass(frozen=True, slots=True)
class ChannelSession:
    """Who is asking on a channel: one bridge, under one grant, in one workspace, with the channel
    credential it presented (as its digest)."""

    workspace_id: uuid.UUID
    grant_id: uuid.UUID
    bridge: str
    credential_sha256: str

    @property
    def actor(self) -> uuid.UUID:
        return grant_actor(self.grant_id)


@dataclass(frozen=True, slots=True)
class Redeemed:
    """What a redeemed invite opened: the grant as it stands and its new channel credential."""

    grant: Grant
    channel: IssuedSecret


def _row(connection: psycopg.Connection, digest: str) -> tuple[dict[str, Any] | None, dt.datetime]:
    """The secret with this digest, or None, and the statement's time: one statement either way."""
    row = connection.execute(
        "select n.now, s.kind, s.bridge, s.workspace_id, s.grant_id, s.expires_at, s.used_at, "
        "s.revoked_at from (select statement_timestamp() as now) n "
        "left join door_secret s on s.secret_sha256 = %s",
        (digest,),
    ).fetchone()
    assert row is not None
    return (None if row["kind"] is None else row), row["now"]


def open_channel(
    database: Database,
    bridges: BridgeDirectory,
    presented: str | None,
    open_to: Callable[[uuid.UUID], bool] | None = None,
) -> ChannelSession:
    """The channel a credential opens, or :class:`ChannelNotAccepted`. ``open_to`` says whether a
    workspace is open, where the deployment has accounts."""
    if not presented or CHANNEL_CREDENTIAL_FORM.fullmatch(presented) is None:
        raise ChannelNotAccepted("no channel credential opens a grant here")
    digest = credential_sha256(presented)
    with database.unscoped() as connection:
        row, now = _row(connection, digest)
    if (
        row is None
        or row["kind"] != "channel"
        or row["revoked_at"] is not None
        or now >= row["expires_at"]
    ):
        raise ChannelNotAccepted("no channel credential opens a grant here")
    bridge = bridges.get(row["bridge"])
    if bridge is None or not bridge.offered_to(row["workspace_id"]):
        raise ChannelNotAccepted("no channel credential opens a grant here")
    if open_to is not None and not open_to(row["workspace_id"]):
        raise ChannelNotAccepted("no channel credential opens a grant here")
    return ChannelSession(
        workspace_id=row["workspace_id"],
        grant_id=row["grant_id"],
        bridge=row["bridge"],
        credential_sha256=digest,
    )


def _refuse(connection: psycopg.Connection, bridge: Bridge, requester: str) -> None:
    connection.execute(
        "insert into door_redemption_refusal (bridge, requester_sha256) values (%s, %s)",
        (bridge.key, requester),
    )


def redeem_invite(
    database: Database,
    bridge: Bridge,
    typed: str,
    requester: str,
    open_to: Callable[[uuid.UUID], bool] | None = None,
) -> Redeemed:
    """Redeem one invite for a channel credential, as ``bridge``, whose own credential the caller
    already matched (:meth:`~exulanica.door.bridges.BridgeDirectory.for_credential`), for the
    requester the bridge names, while the invite's workspace is open (``open_to``, where the
    deployment has accounts).

    Raises :class:`TooManyRedemptions` for a requester past its failures, and
    :class:`InviteNotRedeemable` for every other failure.
    """
    if not bridge.takes_invites() or REQUESTER_FORM.fullmatch(requester) is None:
        raise InviteNotRedeemable("this invite opens nothing for this bridge")
    canonical = normalise_invite_code(typed)
    refusal: Exception | None = None
    with database.unscoped() as connection:
        failures = connection.execute(
            "select count(*) as failures from door_redemption_refusal "
            "where bridge = %s and requester_sha256 = %s "
            "and refused_at > statement_timestamp() - interval '1 minute'",
            (bridge.key, requester),
        ).fetchone()
        assert failures is not None
        if failures["failures"] >= REDEMPTION_FAILURES_PER_MINUTE:
            refusal = TooManyRedemptions(
                "this requester failed too many redemptions in the last minute"
            )
        else:
            row, now = _row(connection, credential_sha256(canonical or ""))
            if (
                canonical is None
                or row is None
                or row["kind"] != "invite"
                or row["bridge"] != bridge.key
                or row["used_at"] is not None
                or row["revoked_at"] is not None
                or now >= row["expires_at"]
                or not bridge.offered_to(row["workspace_id"])
            ):
                _refuse(connection, bridge, requester)
                refusal = InviteNotRedeemable("this invite opens nothing for this bridge")
            prune(connection)
    # The account database is read with no connection of this one held open.
    if refusal is None and open_to is not None and not open_to(row["workspace_id"]):
        with database.unscoped() as connection:
            _refuse(connection, bridge, requester)
        refusal = InviteNotRedeemable("this invite opens nothing for this bridge")
    # Raised only once the connection has committed the refusal it recorded.
    if refusal is not None:
        raise refusal
    assert canonical is not None
    workspace_id = row["workspace_id"]
    grant_id = row["grant_id"]
    try:
        with database.session(workspace_id) as connection, connection.transaction():
            grants = GrantRepository(connection, workspace_id, grant_actor(grant_id))
            grants.lock(grant_id)
            used = connection.execute(
                "update door_secret set used_at = statement_timestamp() "
                "where secret_sha256 = %s and kind = 'invite' and used_at is null "
                "and revoked_at is null and expires_at > statement_timestamp() "
                "returning grant_id",
                (credential_sha256(canonical),),
            ).fetchone()
            if used is None:
                raise InviteNotRedeemable("this invite opens nothing for this bridge")
            channel = grants.redeemed_channel(grant_id)
            grant = grants.current(grant_id)
            assert grant is not None
    except (InviteNotRedeemable, GrantRefused) as exc:
        if isinstance(exc, GrantRefused) and exc.code == "too_many_secrets":
            # A good invite whose grant has been given every secret it may be, since direct
            # credentials took the room it was issued with: said so by name, and not counted
            # against the requester, who presented what the owner gave.
            raise
        with database.unscoped() as connection:
            _refuse(connection, bridge, requester)
        raise InviteNotRedeemable("this invite opens nothing for this bridge") from exc
    return Redeemed(grant=grant, channel=channel)
