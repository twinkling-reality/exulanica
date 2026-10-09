"""Grants: a world owner's permission for one bridge, and the secrets that open it.

A grant names one world and one bridge the deployment admits, and states its scope: how many
visitors the bridge may bring in (none to four), which of the world's own things it decides for
(none by default), whether things may be carried in and out and whether its visitors may speak, and
when it ends (two hours unless the owner says otherwise, never more than a day). The grant is the
newest of its revisions (``door_grant_revision``, migration 0149), each appended and never changed.
Revoking records the owner's revocation (``door_grant_revocation``), after which nothing is asked or
answered under the grant and nothing revises it; a revocation is a withdrawal of permission, so a
restore from an older backup writes it again (``exulanica/deletion/withdrawals.v2.json``). Every
request asked under a grant records the number of the revision it was asked under.

A grant opens through two kinds of secret (:mod:`exulanica.door.credentials`), each stored as its
digest in ``door_secret``: an invite, which a server bridge redeems once, within fifteen minutes,
with the deployment's bridge credential, for a channel credential; or a channel credential issued
directly to the owner, for a bridge the owner runs or a server bridge declared for the owner's
workspace alone (:meth:`exulanica.door.bridges.Bridge.direct_credentials_for`). At most eight
unexpired invites wait unused per grant, and one channel credential is live: a grant answers to one
program at a time, so a channel credential issued or redeemed ends the grant's earlier one, and the
channel counts only a hello said since the live credential was issued
(:func:`exulanica.door.channel.presence_of`). A receipt therefore names the adapter of the program
that holds the grant, which is the only one that can answer. Every use of a secret checks its
grant: once the grant has ended an invite opens nothing and a channel credential answers nothing,
reading only, until a day after the end, what happened while its bridge was away. An owner may also
end every credential and invite of a grant at once without ending the grant
(:meth:`GrantRepository.revoke_credentials`), as after a credential leaked; each records the time
it was revoked.

Issuing, revoking, every write of a grant's secrets, and a hello and an answer on its channel all
take the grant's lock (:meth:`GrantRepository.lock`), so a credential being ended is never issued
again by a request running beside it, a cap is never passed by two requests at once, and an answer
is never stored under a hello its credential did not say.

Revoking also writes a departure for every visitor the grant brought in that is still in its
society (:mod:`exulanica.door.crossings`), so a grant's end sends its visitors home at the next
minute.

A grant may carry ``world_words``, the words its owner chose for its bridge to show players about
the world (a title for a panel). The door never reads the world's own title, which is the owner's
content and may hold a name.

A grant that names some of the world's own things binds them to the bridge in the version it names,
through the choice record (``SocietyModelChoiceRepository.record_external_choice``), in the grant's
own transaction, so a thing is never decided for by a program whose grant does not exist; revoking
hands them back to their routine the same way (``release_external_choice``), and so does a grant
that runs out, the first time the decision host meets one of its things (:meth:`GrantRepository.
lapse`). A new world version
starts its society again, so a binding is a version's, as a model choice is.

A grant that lets visitors in names the world version they arrive in, which must hold a society of
things (:func:`visitors_society`): issuing refuses one that does not, as every arrival under a grant
stored without one is refused.

The repository runs on a connection scoped to the owner's workspace and is the one writer of the
grant tables. Its idempotency: an issue names an ``idempotency_key``, from which the grant's id is
derived, so a repeated issue answers with the grant it made, its lists in any order, and a key
reused for a different grant is refused.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.door.bridges import Bridge, BridgeDirectory
from exulanica.door.credentials import (
    credential_sha256,
    format_invite_code,
    new_channel_credential,
    new_invite_code,
)
from exulanica.door.protocol import words_fault
from exulanica.door.retention import prune
from exulanica.errors import ExulanicaError
from exulanica.world.crossings import society_of_version
from exulanica.world.placed_things import PLACED_THING_ID_PATTERN
from exulanica.world.society_decision_contract import decision_contract, person_role
from exulanica.world.society_engines import society_engine
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)

__all__ = [
    "GRANTS_PER_DAY_MAXIMUM",
    "GRANT_PROFILE",
    "INVITE_LIFETIME",
    "MINUTES_DEFAULT",
    "MINUTES_MAXIMUM",
    "READING_GRACE",
    "SECRETS_ISSUED_MAXIMUM",
    "SECRETS_WAITING_MAXIMUM",
    "THINGS_MAXIMUM",
    "VISITORS_MAXIMUM",
    "WORLD_WORDS_MAXIMUM",
    "Grant",
    "GrantRefused",
    "GrantRepository",
    "IssuedSecret",
    "Scope",
    "grant_actor",
    "visitors_society",
]

_LOG = logging.getLogger(__name__)

GRANT_PROFILE: Final = "exulanica.door-grant/v1"
VISITORS_MAXIMUM: Final = 4
THINGS_MAXIMUM: Final = 8
MINUTES_DEFAULT: Final = 120
MINUTES_MAXIMUM: Final = 1440
INVITE_LIFETIME: Final = dt.timedelta(minutes=15)
#: How long a channel credential may still read its grant's frames after the grant ends.
READING_GRACE: Final = dt.timedelta(hours=24)
#: Per grant, the most invites waiting unused and unexpired: enough for a server and a spare. A
#: grant has one live channel credential at most.
SECRETS_WAITING_MAXIMUM: Final = 8
#: The most secrets one grant is ever given, invites and channel credentials together. A revoked
#: secret is kept for good (migration 0157), so this bounds what one grant adds to the global
#: secret table, whatever its owner asks.
SECRETS_ISSUED_MAXIMUM: Final = 48
#: The most grants one workspace issues in any 24 hours. A grant is given at most
#: SECRETS_ISSUED_MAXIMUM secrets and a revoked secret is kept for good (migration 0157), so this
#: bounds how fast a workspace's kept door secrets grow: at most 2,400 rows a day at the cap.
GRANTS_PER_DAY_MAXIMUM: Final = 50
#: The most characters in the words an owner gives a grant's bridge to show for the world.
WORLD_WORDS_MAXIMUM: Final = 80
#: Grants' ids, derived from the workspace and the issue's idempotency key.
_GRANT_NAMESPACE: Final = uuid.UUID("6b0c9d2e-3f4a-5b6c-8d7e-9f0a1b2c3d4e")
#: The actor a bridge's writes under a grant are recorded as: one per grant, never an account.
_ACTOR_NAMESPACE: Final = uuid.UUID("2a7e5c19-8b3d-5f40-9c61-d4e8f0a2b6c3")
_KEY: Final = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_GAME_TYPE: Final = re.compile(r"^[A-Za-z0-9_:.-]{1,80}$")
#: A placed thing's id, as a version's things are placed with.
_PLACED_ID: Final = re.compile(PLACED_THING_ID_PATTERN)


class GrantRefused(ExulanicaError):
    """A grant cannot be issued, revoked or opened as asked; ``code`` says why, and
    ``retry_after_s`` when asking again later would be answered."""

    def __init__(self, code: str, detail: str, *, retry_after_s: int | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retry_after_s = retry_after_s


def grant_actor(grant_id: uuid.UUID) -> uuid.UUID:
    """Who a bridge's writes under ``grant_id`` are recorded as."""
    return uuid.uuid5(_ACTOR_NAMESPACE, f"grant:{grant_id}")


def _utc(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat(timespec="microseconds")


def visitors_society(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, version_id: str
) -> dict[str, Any] | None:
    """The society a world version holds where a grant's visitors arrive, by its id and engine, or
    None where the version holds no society or its engine holds no things (the engine table
    decides): the rule a visitors grant is issued under and every arrival under one is taken by."""
    society = society_of_version(connection, workspace_id, world_id, uuid.UUID(version_id))
    if society is None or society_engine(society["engine_version"]).state_family != "things":
        return None
    return society


@dataclass(frozen=True, slots=True)
class Scope:
    """What a grant lets its bridge do in its world."""

    visitors_maximum: int = 0
    kinds: tuple[str, ...] = ()
    things: tuple[str, ...] = ()
    version_id: str | None = None
    gate: str | None = None
    may_carry_in: bool = False
    may_carry_out: bool = False
    may_speak: bool = True
    world_words: str | None = None

    def __post_init__(self) -> None:
        if type(self.visitors_maximum) is not int or not 0 <= self.visitors_maximum <= (
            VISITORS_MAXIMUM
        ):
            raise GrantRefused(
                "invalid_scope", f"a grant brings in 0 to {VISITORS_MAXIMUM} visitors at once"
            )
        if len(self.kinds) > 16 or not all(_GAME_TYPE.match(kind) for kind in self.kinds):
            raise GrantRefused("invalid_scope", "a grant names at most 16 visitor kinds")
        if len(set(self.kinds)) != len(self.kinds) or len(set(self.things)) != len(self.things):
            raise GrantRefused("invalid_scope", "a grant names each kind and thing once")
        if len(self.things) > THINGS_MAXIMUM:
            raise GrantRefused(
                "invalid_scope", f"a grant decides for at most {THINGS_MAXIMUM} named things"
            )
        named = () if self.version_id is None else (self.version_id,)
        for value in (*self.things, *named):
            try:
                if str(uuid.UUID(value)) != value:
                    raise ValueError(value)
            except (TypeError, ValueError, AttributeError) as exc:
                raise GrantRefused("invalid_scope", "a thing is named by its id") from exc
        if self.gate is not None and (
            not isinstance(self.gate, str) or _PLACED_ID.fullmatch(self.gate) is None
        ):
            raise GrantRefused("invalid_scope", "a gate is named by the id it was placed with")
        if bool(self.things) and self.version_id is None:
            raise GrantRefused(
                "invalid_scope", "a grant names the world version its things are bound in"
            )
        if self.visitors_maximum == 0 and not self.things:
            raise GrantRefused(
                "invalid_scope", "a grant lets its bridge bring visitors in or names things"
            )
        if self.visitors_maximum > 0 and not self.kinds:
            raise GrantRefused("invalid_scope", "a grant for visitors names the kinds it admits")
        if self.world_words is not None:
            fault = words_fault(self.world_words, maximum=WORLD_WORDS_MAXIMUM)
            if fault is not None:
                raise GrantRefused("invalid_scope", f"a grant's world words: {fault}")

    def check_issue(self) -> None:
        """The rules a grant is issued under beyond those every stored revision keeps, so a
        revision written before one of them existed is still read as it was written: a grant for
        visitors names the version they arrive in, and a gate is named only for visitors to come
        through. A visitors grant stored without a version takes no arrival
        (``world_not_open_to_visitors``)."""
        if (bool(self.things) or self.visitors_maximum > 0) != (self.version_id is not None):
            raise GrantRefused(
                "invalid_scope",
                "a grant names the version its things are bound in and its visitors arrive in",
            )
        if self.gate is not None and self.visitors_maximum == 0:
            raise GrantRefused("invalid_scope", "a gate is named only for visitors to come through")

    def document(self) -> dict[str, Any]:
        return {
            "visitors_maximum": self.visitors_maximum,
            "kinds": sorted(self.kinds),
            "things": sorted(self.things),
            "version_id": self.version_id,
            "gate": self.gate,
            "may_carry_in": self.may_carry_in,
            "may_carry_out": self.may_carry_out,
            "may_speak": self.may_speak,
            "world_words": self.world_words,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> Scope:
        return cls(
            visitors_maximum=document["visitors_maximum"],
            kinds=tuple(document["kinds"]),
            things=tuple(document["things"]),
            version_id=document["version_id"],
            gate=document["gate"],
            may_carry_in=document["may_carry_in"],
            may_carry_out=document["may_carry_out"],
            may_speak=document["may_speak"],
            world_words=document["world_words"],
        )


@dataclass(frozen=True, slots=True)
class Grant:
    """A grant as its newest revision states it."""

    grant_id: uuid.UUID
    world_id: str
    bridge: str
    grant_seq: int
    state: str
    scope: Scope
    mapping_sha256: tuple[str, ...]
    expires_at: dt.datetime
    issued_at: dt.datetime

    def ended(self, now: dt.datetime) -> str | None:
        """``revoked`` or ``expired`` once the grant no longer stands, else None."""
        if self.state == "revoked":
            return "revoked"
        if now >= self.expires_at:
            return "expired"
        return None

    def view(self) -> dict[str, Any]:
        """The grant as its owner and its bridge read it."""
        return {
            "grant_id": str(self.grant_id),
            "world_id": self.world_id,
            "bridge": self.bridge,
            "grant_seq": self.grant_seq,
            "state": self.state,
            "scope": self.scope.document(),
            "expires_at": _utc(self.expires_at),
            "issued_at": _utc(self.issued_at),
        }


@dataclass(frozen=True, slots=True)
class IssuedSecret:
    """A secret as it is shown once: its text and when it stops opening anything."""

    text: str
    expires_at: dt.datetime


def _revision(
    grant_id: uuid.UUID,
    grant_seq: int,
    *,
    world_id: str,
    bridge: str,
    scope: Scope,
    mapping_sha256: Sequence[str],
    expires_at: dt.datetime,
) -> dict[str, Any]:
    return {
        "profile": GRANT_PROFILE,
        "grant_id": str(grant_id),
        "grant_seq": grant_seq,
        "world_id": world_id,
        "bridge": bridge,
        "scope": scope.document(),
        "mapping_sha256": sorted(mapping_sha256),
        "expires_at": _utc(expires_at),
    }


class GrantRepository:
    """The grant tables of one workspace, on a connection scoped to it."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, actor: uuid.UUID
    ) -> None:
        self._connection = connection
        self._workspace_id = workspace_id
        self._actor = actor

    def now(self) -> dt.datetime:
        row = self._connection.execute("select statement_timestamp() as now").fetchone()
        assert row is not None
        return row["now"]

    def current(self, grant_id: uuid.UUID) -> Grant | None:
        """The grant as its newest revision states it, or None for a grant this workspace has not
        issued."""
        row = self._connection.execute(
            "select g.world_id, g.bridge, g.issued_at, r.grant_seq, r.document, "
            "v.revoked_at is not null as revoked "
            "from door_grant g join door_grant_revision r using (workspace_id, grant_id) "
            "left join door_grant_revocation v using (workspace_id, grant_id) "
            "where g.workspace_id = %s and g.grant_id = %s "
            "order by r.grant_seq desc limit 1",
            (self._workspace_id, grant_id),
        ).fetchone()
        return None if row is None else self._grant(grant_id, row)

    def in_world(self, world_id: str) -> list[Grant]:
        """Every grant issued in one world, newest first, each as it now stands."""
        rows = self._connection.execute(
            "select distinct on (g.grant_id) g.grant_id, g.world_id, g.bridge, g.issued_at, "
            "r.grant_seq, r.document, v.revoked_at is not null as revoked "
            "from door_grant g join door_grant_revision r using (workspace_id, grant_id) "
            "left join door_grant_revocation v using (workspace_id, grant_id) "
            "where g.workspace_id = %s and g.world_id = %s "
            "order by g.grant_id, r.grant_seq desc",
            (self._workspace_id, world_id),
        ).fetchall()
        grants = [self._grant(row["grant_id"], row) for row in rows]
        return sorted(
            grants, key=lambda grant: (grant.issued_at, str(grant.grant_id)), reverse=True
        )

    @staticmethod
    def _grant(grant_id: uuid.UUID, row: dict[str, Any]) -> Grant:
        document = row["document"]
        return Grant(
            grant_id=grant_id,
            world_id=row["world_id"],
            bridge=row["bridge"],
            grant_seq=row["grant_seq"],
            state="revoked" if row["revoked"] else "active",
            scope=Scope.from_document(document["scope"]),
            mapping_sha256=tuple(document["mapping_sha256"]),
            expires_at=dt.datetime.fromisoformat(document["expires_at"]),
            issued_at=row["issued_at"],
        )

    def lock(self, grant_id: uuid.UUID) -> None:
        """Take the grant's lock until the transaction ends. Issuing, revoking, every write of its
        secrets, and a hello and an answer on its channel take it, so none sees another half
        done."""
        self._connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 149001))", (str(grant_id),)
        )

    def _choices(self, world_id: str) -> SocietyModelChoiceRepository:
        return SocietyModelChoiceRepository(self._connection, self._workspace_id, world_id=world_id)

    def _bind(self, world_id: str, grant_id: uuid.UUID, bridge: str, scope: Scope) -> None:
        """Bind the grant's named things to its bridge in the version it names, or refuse."""
        assert scope.version_id is not None
        try:
            self._choices(world_id).record_external_choice(
                uuid.UUID(scope.version_id),
                person_role(),
                request_id=uuid.uuid5(grant_id, "bind"),
                subjects=list(scope.things),
                bridge=bridge,
                grant_id=grant_id,
                chosen_by=self._actor,
                contract=decision_contract(),
            )
        except ModelChoiceRefused as exc:
            raise GrantRefused(exc.code, exc.detail) from exc

    def _release(self, grant: Grant, why: str = "release") -> dict[str, Any] | None:
        """Hand the grant's named things back to their routine in the version they were bound in,
        as one choice keyed by the grant and ``why`` (a revocation's ``release``, a run-out
        grant's ``lapse``, each by its own chooser): the choice recorded, which a repeat answers
        again, or None when the grant decides for nobody now, as after the other one."""
        assert grant.scope.version_id is not None
        try:
            return self._choices(grant.world_id).release_external_choice(
                uuid.UUID(grant.scope.version_id),
                person_role(),
                request_id=uuid.uuid5(grant.grant_id, why),
                grant_id=grant.grant_id,
                chosen_by=self._actor,
                contract=decision_contract(),
            )
        except ModelChoiceRefused as exc:
            # The choice record will not hand the things back (one left the world, or its kind
            # takes no routine): the grant ends all the same, and nothing more is asked under it,
            # so the refusal is said by name and does not stop a revocation or a lapse.
            _LOG.warning("A grant's things were not handed back: %s", exc.code)
            return None

    def issue(
        self,
        *,
        world_id: str,
        bridge: Bridge,
        scope: Scope,
        minutes: int,
        idempotency_key: str,
    ) -> tuple[Grant, bool]:
        """Issue a grant, or answer with the one this key already issued; True when it is new.

        The world must be one this workspace registered and the bridge one the deployment offers
        it; a grant for visitors names a version holding a society of things. The same issue sent
        again answers with the grant it made: the world, the bridge and the scope's document, whose
        lists are sorted, are what is compared, so kinds and things in another order are the same
        grant. A key reused for a different grant is refused.
        """
        if not isinstance(idempotency_key, str) or not _KEY.match(idempotency_key):
            raise GrantRefused("invalid_idempotency_key", "8 to 128 letters, digits or ._:-")
        if type(minutes) is not int or not 1 <= minutes <= MINUTES_MAXIMUM:
            raise GrantRefused("invalid_scope", f"a grant lasts 1 to {MINUTES_MAXIMUM} minutes")
        scope.check_issue()
        if not bridge.offered_to(self._workspace_id):
            raise GrantRefused("bridge_not_offered", "this deployment offers no such bridge here")
        grant_id = uuid.uuid5(_GRANT_NAMESPACE, f"{self._workspace_id}:{idempotency_key}")
        with self._connection.transaction():
            self.lock(grant_id)
            existing = self.current(grant_id)
            if existing is not None:
                if (existing.world_id, existing.bridge, existing.scope.document()) != (
                    world_id,
                    bridge.key,
                    scope.document(),
                ):
                    raise GrantRefused(
                        "idempotency_key_reused", "this key already issued a different grant"
                    )
                return existing, False
            registered = self._connection.execute(
                "select 1 from world_identity where workspace_id = %s and world_id = %s",
                (self._workspace_id, world_id),
            ).fetchone()
            if registered is None:
                raise GrantRefused("unknown_world", "no world with this id is registered here")
            if scope.visitors_maximum > 0 and self._takes_no_visitors(world_id, scope):
                raise GrantRefused(
                    "world_not_open_to_visitors", "this world's version takes no visitors"
                )
            self._within_daily_grants()
            self._connection.execute(
                "insert into door_grant (workspace_id, grant_id, world_id, bridge, issued_by) "
                "values (%s, %s, %s, %s, %s)",
                (self._workspace_id, grant_id, world_id, bridge.key, self._actor),
            )
            now = self.now()
            document = _revision(
                grant_id,
                1,
                world_id=world_id,
                bridge=bridge.key,
                scope=scope,
                mapping_sha256=sorted(bridge.mapping_sha256),
                expires_at=now + dt.timedelta(minutes=minutes),
            )
            self._connection.execute(
                "insert into door_grant_revision (workspace_id, grant_id, grant_seq, document, "
                "document_sha256, recorded_by) values (%s, %s, 1, %s, %s, %s)",
                (
                    self._workspace_id,
                    grant_id,
                    Jsonb(document),
                    sha256_of_canonical(document).hex(),
                    self._actor,
                ),
            )
            if scope.things:
                self._bind(world_id, grant_id, bridge.key, scope)
            issued = self.current(grant_id)
        assert issued is not None
        return issued, True

    def _takes_no_visitors(self, world_id: str, scope: Scope) -> bool:
        """Whether the version a visitors grant names holds no society of things to arrive in."""
        assert scope.version_id is not None  # check_issue
        society = visitors_society(self._connection, self._workspace_id, world_id, scope.version_id)
        return society is None

    def _within_daily_grants(self) -> None:
        """Refuse a new grant past the workspace's daily bound, under the workspace's issuing lock
        (taken after the grant's, and only here), so two issued at once cannot both take the last
        place; answered with when the oldest grant of the day leaves the count."""
        self._connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 149003))",
            (str(self._workspace_id),),
        )
        row = self._connection.execute(
            "select count(*) as issued, "
            "ceil(extract(epoch from min(issued_at) + interval '1 day' - statement_timestamp())) "
            "  as wait "
            "from door_grant where workspace_id = %s "
            "and issued_at > statement_timestamp() - interval '1 day'",
            (self._workspace_id,),
        ).fetchone()
        assert row is not None
        if row["issued"] >= GRANTS_PER_DAY_MAXIMUM:
            raise GrantRefused(
                "too_many_grants",
                f"a workspace issues at most {GRANTS_PER_DAY_MAXIMUM} grants a day",
                retry_after_s=max(1, int(row["wait"])),
            )

    def revoke(self, grant_id: uuid.UUID) -> Grant:
        """End a grant now: nothing more is asked or answered under it, and its invites and
        channel open nothing more but reading what was sent. Revoking twice changes nothing."""
        with self._connection.transaction():
            self.lock(grant_id)
            grant = self.current(grant_id)
            if grant is None:
                raise GrantRefused("unknown_grant", "no grant with this id is issued here")
            if grant.state == "revoked":
                return grant
            self._connection.execute(
                "insert into door_grant_revocation (workspace_id, grant_id, revoked_by) "
                "values (%s, %s, %s)",
                (self._workspace_id, grant_id, self._actor),
            )
            # Every visitor it brought in goes home, in the revocation's own transaction, before
            # its things are handed back: the departures take the society's crossing lock first
            # and its row after, as every crossing written does.
            self._send_home(grant, self._actor)
            if grant.scope.things:
                self._release(grant)
            revoked = self.current(grant_id)
        assert revoked is not None
        return revoked

    def _send_home(self, grant: Grant, actor: uuid.UUID) -> int:
        """A departure for every visitor of ``grant`` still present, because it ended; how many
        were written. A departure the door cannot write is said by name in the log and stops no
        revocation: the grant ends all the same and nobody is asked under it; every minute it is
        asked for, its visitor's receipt names the grant's end, which the society counts among its
        kind's quiet minutes, so those minutes send it home."""
        # Imported here: the crossings read grants, and a grant ends its own visits.
        from exulanica.door.channel import ChannelRefused
        from exulanica.door.crossings import Visits

        try:
            return Visits(self._connection, self._workspace_id, grant, actor).end()
        except ChannelRefused as exc:
            _LOG.warning("A grant's visitors were not sent home: %s", exc.code)
            return 0

    def lapse(self, grant_id: uuid.UUID) -> bool:
        """Hand a grant's named things back to their routine once the grant has run out, as
        revoking does, under the grant's lock and chosen by the grant's own actor: the decision
        host then asks the routine for them and nobody else. True when they are released (a
        repeat answers with the same release); a grant that stands, was revoked or names no thing
        changes nothing."""
        with self._connection.transaction():
            self.lock(grant_id)
            grant = self.current(grant_id)
            if grant is None or not grant.scope.things or grant.ended(self.now()) != "expired":
                return False
            return self._release(grant, "lapse") is not None

    def _standing(self, grant_id: uuid.UUID) -> Grant:
        grant = self.current(grant_id)
        if grant is None:
            raise GrantRefused("unknown_grant", "no grant with this id is issued here")
        if grant.ended(self.now()) is not None:
            raise GrantRefused("grant_ended", "this grant was revoked or has ended")
        return grant

    def _secret(
        self, grant: Grant, *, kind: str, text: str, expires_at: dt.datetime, room: int = 1
    ) -> IssuedSecret:
        """Store one new secret of ``grant``, under the grant's lock the caller holds, while
        ``room`` more fit under :data:`SECRETS_ISSUED_MAXIMUM`: an invite needs room for itself
        and for the channel credential its redemption issues."""
        issued = self._connection.execute(
            "select count(*) as issued from door_secret where workspace_id = %s and grant_id = %s",
            (self._workspace_id, grant.grant_id),
        ).fetchone()
        assert issued is not None
        if issued["issued"] + room > SECRETS_ISSUED_MAXIMUM:
            raise GrantRefused(
                "too_many_secrets",
                f"a grant is given at most {SECRETS_ISSUED_MAXIMUM} invites and credentials",
            )
        self._connection.execute(
            "insert into door_secret (secret_sha256, kind, bridge, workspace_id, grant_id, "
            "expires_at) values (%s, %s, %s, %s, %s, %s)",
            (
                credential_sha256(text),
                kind,
                grant.bridge,
                self._workspace_id,
                grant.grant_id,
                expires_at,
            ),
        )
        prune(self._connection)
        return IssuedSecret(text=text, expires_at=expires_at)

    def _waiting(self, grant: Grant, kind: str) -> int:
        """How many of the grant's secrets of ``kind`` are live: unrevoked and unexpired, and for
        an invite unused."""
        row = self._connection.execute(
            "select count(*) as waiting from door_secret "
            "where workspace_id = %s and grant_id = %s and kind = %s and revoked_at is null "
            "and used_at is null and expires_at > statement_timestamp()",
            (self._workspace_id, grant.grant_id, kind),
        ).fetchone()
        assert row is not None
        return int(row["waiting"])

    def _offered(self, grant: Grant, bridges: BridgeDirectory) -> Bridge:
        """The grant's bridge, while the deployment declares it and offers it here."""
        bridge = bridges.get(grant.bridge)
        if bridge is None or not bridge.offered_to(self._workspace_id):
            raise GrantRefused("bridge_not_offered", "this deployment offers no such bridge here")
        return bridge

    def invite(self, grant_id: uuid.UUID, bridges: BridgeDirectory) -> IssuedSecret:
        """A fresh invite to a standing grant of a server bridge: single use, for fifteen minutes
        or until the grant ends, whichever is sooner, shown once as four groups of four."""
        with self._connection.transaction():
            self.lock(grant_id)
            grant = self._standing(grant_id)
            bridge = self._offered(grant, bridges)
            if not bridge.takes_invites():
                raise GrantRefused(
                    "invites_not_offered", "a program its owner runs is given a credential instead"
                )
            if self._waiting(grant, "invite") >= SECRETS_WAITING_MAXIMUM:
                raise GrantRefused(
                    "too_many_secrets",
                    f"a grant has at most {SECRETS_WAITING_MAXIMUM} invites waiting to be used",
                )
            code = new_invite_code()
            expires_at = min(self.now() + INVITE_LIFETIME, grant.expires_at)
            issued = self._secret(grant, kind="invite", text=code, expires_at=expires_at, room=2)
        return IssuedSecret(text=format_invite_code(issued.text), expires_at=issued.expires_at)

    def direct_channel(self, grant_id: uuid.UUID, bridges: BridgeDirectory) -> IssuedSecret:
        """A channel credential for a standing grant, shown once, given to its owner: for a program
        the owner runs, or a server bridge declared for this workspace alone. It ends the grant's
        earlier channel credential."""
        with self._connection.transaction():
            self.lock(grant_id)
            grant = self._standing(grant_id)
            bridge = self._offered(grant, bridges)
            if not bridge.direct_credentials_for(self._workspace_id):
                raise GrantRefused(
                    "direct_credential_not_offered",
                    "this bridge's grants open only with invites its own server redeems",
                )
            return self._channel(grant)

    def redeemed_channel(self, grant_id: uuid.UUID) -> IssuedSecret:
        """The channel credential a redeemed invite opens, in the redemption's transaction, which
        holds the grant's lock; it ends the grant's earlier channel credential."""
        return self._channel(self._standing(grant_id))

    def _channel(self, grant: Grant) -> IssuedSecret:
        """A new channel credential for ``grant``, ending the live one it had: a grant answers to
        one program at a time. The caller holds the grant's lock."""
        self._connection.execute(
            "update door_secret set revoked_at = statement_timestamp() "
            "where workspace_id = %s and grant_id = %s and kind = 'channel' "
            "and revoked_at is null and expires_at > statement_timestamp()",
            (self._workspace_id, grant.grant_id),
        )
        return self._secret(
            grant,
            kind="channel",
            text=new_channel_credential(),
            expires_at=grant.expires_at + READING_GRACE,
        )

    def revoke_credentials(self, grant_id: uuid.UUID) -> int:
        """End every live invite and channel credential of a grant now, without ending the grant,
        and say how many: each records the time it was revoked, and opens nothing after."""
        with self._connection.transaction():
            self.lock(grant_id)
            grant = self.current(grant_id)
            if grant is None:
                raise GrantRefused("unknown_grant", "no grant with this id is issued here")
            revoked = self._connection.execute(
                "update door_secret set revoked_at = statement_timestamp() "
                "where workspace_id = %s and grant_id = %s and revoked_at is null "
                "and expires_at > statement_timestamp() returning secret_sha256",
                (self._workspace_id, grant_id),
            ).fetchall()
        return len(revoked)
