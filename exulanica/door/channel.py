"""A grant's channel: what its bridge says hello with, what it reads and what it answers.

Everything here runs on a connection scoped to the grant's workspace, for a bridge whose channel
credential has already opened the grant (:func:`exulanica.door.secrets.open_channel`).

**Hello.** A bridge presents its adapter's version, its mapping file and the game fields it reads,
and the program behind it may declare a name and a maker. The grant must stand; the version must be
one the deployment admits for the bridge and the mapping one whose digest the deployment pins; the
mapping must meet its profile and account for every field read (:mod:`exulanica.door.mapping`). The
mapping and the declaration are kept in the workspace by their digests, so every record that names
one can be read back with it, and the grant's presence records the version, the mapping and the
declaration, which every later answer names. Declared words are for a person reading a card: they
never enter a society record or any model's context.

**Presence.** A grant answers to one program at a time: it has one live channel credential, and a
hello counts only if it was said since that credential was issued (:func:`presence_of`), so a hello
an earlier program said never names who answers now. A hello whose adapter version or mapping the
deployment no longer admits counts for nothing either: unpinning one closes every channel that said
hello with it, which must say hello again before it polls or answers, and is not asked meanwhile.
A hello and an answer take the grant's lock and check that their credential is still the live one,
so neither lands beside the issue of the next.

**Reading.** Frames are projected from what the grant's tables and the decision tables hold
(:mod:`exulanica.door.protocol`): the grant as it stands, each ask's request with the role's words,
each answered ask's recorded outcome, and the grant's end. A cheap head read says whether anything
is new before any frame is built, which is what a held poll repeats.

**Answering.** An answer names one ask of this grant and one of the labels its request offered. It
is stored as the bridge sent it, with the adapter version, mapping and declaration its own hello
named, and nothing else happens: the decision host makes the receipt, and
applies the workspace's rules to any line, when it records it. Migration 0149 ties the stored answer
to its ask by all four of the ask's names and refuses it under a grant that has ended, under the
lock revoking takes. An answer to an ask the host already recorded is too late, and a second answer
to one ask is refused; neither changes anything.

Requests and receipts are read from migration 0055's tables by request id, the one place the door
reads the society plane.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import CanonicalisationError, canonical_json, sha256_of_canonical
from exulanica.door.bridges import Bridge, BridgeDirectory
from exulanica.door.grants import Grant, GrantRepository
from exulanica.door.mapping import (
    MappingRefused,
    check_mapping,
    check_plain,
    check_reads,
    mapped_fields,
)
from exulanica.door.protocol import (
    ASKED_BYTES_MAXIMUM,
    DECLARED_CHARACTERS_MAXIMUM,
    DECLARED_MIND_MAXIMUM,
    FRAME_PROFILE,
    FRAMES_PER_POLL,
    LINE_CHARACTERS_MAXIMUM,
    QUIET_SECONDS,
    Cursor,
    answer_sha256,
    arrival_refused_frame,
    arrived_frame,
    asked_frame,
    declared_fault,
    departed_frame,
    grant_ended_frame,
    grant_frame,
    outcome_frame,
    words_fault,
)
from exulanica.door.secrets import ChannelSession
from exulanica.errors import ExulanicaError
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.deciders import ADAPTER_VERSION
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_decision_repository import UNANSWERED_WINDOW_TICKS

__all__ = [
    "UNANSWERED_WINDOW",
    "ChannelRefused",
    "ChannelRepository",
    "Head",
    "Presence",
    "presence_of",
    "presence_window",
]


def presence_window(bridge: Bridge) -> dt.timedelta:
    """A grant whose bridge polled within this window is connected: one of its held polls, then the
    quiet allowance before its next."""
    return dt.timedelta(seconds=bridge.hold_seconds + QUIET_SECONDS)


def declared_sha256(declared: Mapping[str, str]) -> str:
    """The digest a declaration is kept and named by."""
    return sha256_of_canonical(dict(declared)).hex()


class ChannelRefused(ExulanicaError):
    """A channel request the door will not act on: ``code`` and ``status`` say how it answers, and
    ``retry_after_s`` when asking again later would be answered."""

    def __init__(
        self, code: str, status: int, detail: str, *, retry_after_s: int | None = None
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.status = status
        self.detail = detail
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class Presence:
    """What a grant's bridge last said hello with, and when it last polled."""

    adapter_version: str
    mapping_sha256: str
    declared_sha256: str | None
    declared: Mapping[str, str] | None
    hello_at: dt.datetime
    polled_at: dt.datetime

    def connected(self, now: dt.datetime, window: dt.timedelta) -> bool:
        return now - self.polled_at <= window

    def admitted_by(self, bridge: Bridge) -> bool:
        """Whether the deployment still admits the adapter version and the mapping this hello
        named: one it unpinned closes the channel until the bridge says hello again."""
        return (
            self.adapter_version in bridge.adapter_versions
            and self.mapping_sha256 in bridge.mapping_sha256
        )


def presence_of(
    connection: psycopg.Connection, workspace_id: uuid.UUID, grant_id: uuid.UUID
) -> Presence | None:
    """What the program holding the grant's live channel credential said hello with, and when it
    last polled; None when it has said no hello since that credential was issued, or the grant has
    no live channel credential."""
    row = connection.execute(
        "select p.adapter_version, p.mapping_sha256, p.declared_sha256, d.document as declared, "
        "p.hello_at, p.polled_at from door_presence p left join door_declaration d "
        "  on d.workspace_id = p.workspace_id and d.declared_sha256 = p.declared_sha256 "
        "where p.workspace_id = %(w)s and p.grant_id = %(g)s and p.hello_at >= ("
        "  select max(s.created_at) from door_secret s "
        "   where s.workspace_id = %(w)s and s.grant_id = %(g)s and s.kind = 'channel' "
        "     and s.revoked_at is null and s.expires_at > statement_timestamp())",
        {"w": workspace_id, "g": grant_id},
    ).fetchone()
    return None if row is None else Presence(**row)


#: How long after an ask its request may still gain a receipt, beyond its own deadline: the minutes
#: in which the host closes a request that a stopped process left unanswered (a playing world's
#: minute is a minute). Past it no receipt will come, so the ask's outcome is passed over and
#: nothing after it, the grant's end included, waits for it.
UNANSWERED_WINDOW: Final = dt.timedelta(minutes=UNANSWERED_WINDOW_TICKS)
#: This grant's arrivals the society took. A society's minute takes crossings in the order the door
#: wrote them, so their ``crossing_seq`` is the order they were taken in, and a cursor holds the
#: last one it was told of.
_ARRIVALS_TAKEN: Final = (
    "from door_crossing c join door_crossing_binding b "
    "  on b.workspace_id = c.workspace_id and b.society_id = c.society_id "
    " and b.crossing_id = c.crossing_id "
    "where c.workspace_id = %(w)s and c.grant_id = %(g)s and c.kind = 'arrival' "
)
#: The departures the society recorded of this grant's visitors, in the order it recorded them:
#: those the door wrote and those the society decided by its own rules.
_DEPARTURES: Final = (
    "from world_society_event e join door_crossing c "
    "  on c.workspace_id = e.workspace_id and c.society_id = e.society_id "
    " and c.thing_id = e.subject_id and c.kind = 'arrival' "
    "where e.workspace_id = %(w)s and c.grant_id = %(g)s and e.event_kind = 'thing_departed' "
)


@dataclass(frozen=True, slots=True)
class Head:
    """What a cheap read of the channel finds: whether anything after a cursor is waiting."""

    asks: int
    outcomes: int
    grant_seq: int
    ended: str | None
    crossed: int = 0
    departed: int = 0
    arrived: int = 0
    pending: int = 0

    def news(self, cursor: Cursor) -> bool:
        return (
            self.asks > cursor.ask
            or self.outcomes > 0
            or self.grant_seq > cursor.grant
            or self.crossed > cursor.crossed
            or self.departed > cursor.departed
            or (self.ended is not None and not cursor.ended and self.settled(cursor.departed))
        )

    def settled(self, departed: int) -> bool:
        """Whether every visitor of the grant has left and the bridge was told each departure, so
        the grant's end may be told: nothing still waits for a minute, and every arrival that
        arrived has departed."""
        return self.pending == 0 and departed >= self.arrived


class ChannelRepository:
    """One grant's channel, on a connection scoped to its workspace."""

    def __init__(
        self,
        connection: psycopg.Connection,
        session: ChannelSession,
        bridges: BridgeDirectory,
    ) -> None:
        self._connection = connection
        self._session = session
        self._bridges = bridges
        self._grants = GrantRepository(connection, session.workspace_id, session.actor)

    @property
    def _ids(self) -> dict[str, uuid.UUID]:
        return {"w": self._session.workspace_id, "g": self._session.grant_id}

    def bridge(self) -> Bridge:
        """The bridge this channel's credential opened, while the deployment still declares it and
        offers it to this workspace; the credential lookup refuses the rest before this runs."""
        bridge = self._bridges.get(self._session.bridge)
        if bridge is None or not bridge.offered_to(self._session.workspace_id):
            raise ChannelRefused("unauthenticated", 401, "no door credential opens anything here")
        return bridge

    def grant(self) -> Grant:
        grant = self._grants.current(self._session.grant_id)
        if grant is None:
            # A credential exists only for a grant that does; a missing one is a defect.
            raise LookupError("a channel credential opened a grant this workspace does not hold")
        return grant

    def _standing(self) -> Grant:
        grant = self.grant()
        if grant.ended(self._grants.now()) is not None:
            raise ChannelRefused("grant_ended", 410, "this grant was revoked or has ended")
        return grant

    def _live(self) -> None:
        """Take the grant's lock and refuse a credential ended since it was presented, by a newer
        one of the grant or by its owner, so a hello or an answer never lands beside the issue of
        the next credential."""
        self._grants.lock(self._session.grant_id)
        row = self._connection.execute(
            "select 1 from door_secret where secret_sha256 = %s and kind = 'channel' "
            "and revoked_at is null and expires_at > statement_timestamp()",
            (self._session.credential_sha256,),
        ).fetchone()
        if row is None:
            raise ChannelRefused("unauthenticated", 401, "no door credential opens anything here")

    def _presence(self, bridge: Bridge, doing: str) -> Presence:
        """This channel's own hello, while the deployment admits what it named, or a refusal that
        asks the bridge to say hello first. A credential ended since its request was accepted is
        refused as unauthenticated instead: the newer credential that ended it is what makes its
        hello no longer count, and a poll's first read takes no lock that would keep the two
        apart. Read after the hello, so it sees an end that took the hello away."""
        presence = presence_of(self._connection, self._session.workspace_id, self._session.grant_id)
        if presence is None or not presence.admitted_by(bridge):
            live = self._connection.execute(
                "select 1 from door_secret where secret_sha256 = %s and kind = 'channel' "
                "and revoked_at is null and expires_at > statement_timestamp()",
                (self._session.credential_sha256,),
            ).fetchone()
            if live is None:
                raise ChannelRefused(
                    "unauthenticated", 401, "no door credential opens anything here"
                )
            raise ChannelRefused("hello_first", 409, f"say hello on this channel before {doing}")
        return presence

    def hello(
        self,
        *,
        adapter_version: str,
        mapping: Mapping[str, Any],
        reads: list[str],
        declared: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Admit the adapter, its mapping and the program's declaration for this standing grant, or
        refuse by name."""
        bridge = self.bridge()
        grant = self._standing()
        if not ADAPTER_VERSION.fullmatch(adapter_version) or (
            adapter_version not in bridge.adapter_versions
        ):
            raise ChannelRefused(
                "adapter_version_not_admitted", 422, "this adapter version is not admitted"
            )
        try:
            check_plain(mapping)
            digest = sha256_of_canonical(dict(mapping)).hex()
        except (MappingRefused, CanonicalisationError) as exc:
            raise ChannelRefused("mapping_refused", 422, str(exc)) from exc
        if digest not in bridge.mapping_sha256:
            raise ChannelRefused(
                "mapping_not_admitted", 422, "this mapping is not one the deployment pins"
            )
        try:
            checked = check_mapping(dict(mapping))
            check_reads(checked, reads)
        except MappingRefused as exc:
            raise ChannelRefused("mapping_refused", 422, str(exc)) from exc
        declaration = None if declared is None else _declaration(declared)
        declared_digest = None if declaration is None else declared_sha256(declaration)
        with self._connection.transaction():
            self._live()
            self._connection.execute(
                "insert into door_mapping (workspace_id, mapping_sha256, document) "
                "values (%(w)s, %(m)s, %(d)s) on conflict do nothing",
                {**self._ids, "m": digest, "d": Jsonb(checked)},
            )
            if declaration is not None:
                self._connection.execute(
                    "insert into door_declaration (workspace_id, declared_sha256, document) "
                    "values (%(w)s, %(h)s, %(d)s) on conflict do nothing",
                    {**self._ids, "h": declared_digest, "d": Jsonb(declaration)},
                )
            self._connection.execute(
                "insert into door_presence (workspace_id, grant_id, adapter_version, "
                "mapping_sha256, declared_sha256) values (%(w)s, %(g)s, %(v)s, %(m)s, %(h)s) "
                "on conflict (workspace_id, grant_id) do update set "
                "adapter_version = excluded.adapter_version, "
                "mapping_sha256 = excluded.mapping_sha256, "
                "declared_sha256 = excluded.declared_sha256, "
                "hello_at = statement_timestamp(), polled_at = statement_timestamp()",
                {**self._ids, "v": adapter_version, "m": digest, "h": declared_digest},
            )
            head = self.head(Cursor())
            departed = self._delivered_before()
        return {
            "profile": FRAME_PROFILE,
            "grant": grant.view(),
            "hold_seconds": bridge.hold_seconds,
            # From here on: asks made before this hello are not sent again; the grant is, what
            # became of each of its arrivals, and every departure from the first whose delivery
            # the bridge has not reported, so a bridge that restarted delivers what its visitors
            # carried home.
            "cursor": Cursor(ask=head.asks, outcome=head.asks, departed=departed).encode(),
        }

    def open_poll(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor] | None:
        """A poll's first read, checking the grant as every poll does: under a standing grant it
        records the poll; once the grant has ended it records nothing, and once the bridge has read
        that end (``cursor.ended``) it is refused. Then whatever is new after ``cursor``, or None.
        """
        bridge = self.bridge()
        grant = self.grant()
        ended = grant.ended(self._grants.now())
        if ended is not None and cursor.ended:
            raise ChannelRefused("grant_ended", 410, "this grant was revoked or has ended")
        if ended is None:
            # Once the grant has ended a bridge only reads what was sent, its end included, so a
            # hello the deployment no longer admits does not keep it from reading the end.
            self._presence(bridge, "polling")
            self._connection.execute(
                "update door_presence set polled_at = greatest(polled_at, statement_timestamp()) "
                "where workspace_id = %(w)s and grant_id = %(g)s",
                self._ids,
            )
        return self.read(cursor)

    def read(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor] | None:
        """What is new after ``cursor`` and the cursor after it, or None when the head says nothing
        is: the one read a held poll repeats, which refuses a credential ended since the poll
        began, by a newer one of the grant or by its owner."""
        live = self._connection.execute(
            "select 1 from door_secret where secret_sha256 = %s and kind = 'channel' "
            "and revoked_at is null and expires_at > statement_timestamp()",
            (self._session.credential_sha256,),
        ).fetchone()
        if live is None:
            raise ChannelRefused("unauthenticated", 401, "no door credential opens anything here")
        if not self.head(cursor).news(cursor):
            return None
        return self.frames(cursor)

    def head(self, cursor: Cursor) -> Head:
        """One read: how many asks the grant has, how many outcomes wait after the cursor, and
        the grant's newest revision and whether it has ended."""
        row = self._connection.execute(
            "select "
            "(select coalesce(max(ask_seq), 0) from door_ask "
            " where workspace_id = %(w)s and grant_id = %(g)s) as asks, "
            "(select count(*) from door_ask a join world_society_decision d "
            "   on d.workspace_id = a.workspace_id and d.society_id = a.society_id "
            "  and d.request_id = a.request_id "
            " where a.workspace_id = %(w)s and a.grant_id = %(g)s "
            "   and a.ask_seq > %(outcome)s and a.ask_seq <= %(ask)s) as outcomes, "
            "(select r.document from door_grant_revision r "
            " where r.workspace_id = %(w)s and r.grant_id = %(g)s "
            " order by r.grant_seq desc limit 1) as revision, "
            "exists (select 1 from door_grant_revocation v "
            " where v.workspace_id = %(w)s and v.grant_id = %(g)s) as revoked, "
            "(select coalesce(max(c.crossing_seq), 0) " + _ARRIVALS_TAKEN + ") as crossed, "
            "(select count(*) " + _ARRIVALS_TAKEN + " and b.disposition = 'arrived') as arrived, "
            "(select count(*) " + _DEPARTURES + ") as departed, "
            "(select count(*) from door_crossing c left join door_crossing_binding b "
            "   on b.workspace_id = c.workspace_id and b.society_id = c.society_id "
            "  and b.crossing_id = c.crossing_id "
            " where c.workspace_id = %(w)s and c.grant_id = %(g)s and b.crossing_id is null) "
            "  as pending, "
            "statement_timestamp() as now",
            {**self._ids, "outcome": cursor.outcome, "ask": cursor.ask},
        ).fetchone()
        assert row is not None and row["revision"] is not None
        revision = row["revision"]
        ended = None
        if row["revoked"]:
            ended = "revoked"
        elif row["now"] >= dt.datetime.fromisoformat(revision["expires_at"]):
            ended = "expired"
        return Head(
            asks=row["asks"],
            outcomes=row["outcomes"],
            grant_seq=revision["grant_seq"],
            ended=ended,
            crossed=row["crossed"],
            departed=row["departed"],
            arrived=row["arrived"],
            pending=row["pending"],
        )

    def frames(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor]:
        """Everything after ``cursor``, at most :data:`FRAMES_PER_POLL` frames, and the cursor
        after them: the grant if it changed, outcomes in ask order, open asks, what became of its
        visitors' arrivals, their departures, then its end, once every ask was read, every outcome
        reported, every visitor departed and each departure read, so the end is the last thing a
        bridge reads."""
        grant = self.grant()
        now = self._grants.now()
        frames: list[dict[str, Any]] = []
        position = {
            "ask": cursor.ask,
            "outcome": cursor.outcome,
            "grant": cursor.grant,
            "crossed": cursor.crossed,
            "departed": cursor.departed,
            "ended": cursor.ended,
        }
        if grant.grant_seq > cursor.grant:
            view = grant.view()
            frames.append(
                grant_frame(
                    grant_seq=grant.grant_seq,
                    scope={**view["scope"], "expires_at": view["expires_at"]},
                )
            )
            position["grant"] = grant.grant_seq
        outcomes = self._connection.execute(
            "select a.ask_seq, a.request_id, d.document->>'status' as status, "
            "d.document->>'reason' as reason, "
            # An ask no receipt can close any more: past its deadline and the unanswered window.
            "(d.request_id is null and a.recorded_at < statement_timestamp() - %(window)s "
            "  - make_interval(secs => coalesce("
            "      (r.document->'provider_config'->>'deadline_ms')::numeric, 0) / 1000)) as passed "
            "from door_ask a join world_society_decision_request r "
            "  on r.workspace_id = a.workspace_id and r.society_id = a.society_id "
            " and r.request_id = a.request_id "
            "left join world_society_decision d "
            "  on d.workspace_id = a.workspace_id and d.society_id = a.society_id "
            " and d.request_id = a.request_id "
            "where a.workspace_id = %(w)s and a.grant_id = %(g)s "
            "  and a.ask_seq > %(outcome)s and a.ask_seq <= %(ask)s "
            "order by a.ask_seq limit %(limit)s",
            {
                **self._ids,
                "outcome": cursor.outcome,
                "ask": cursor.ask,
                "limit": FRAMES_PER_POLL,
                "window": UNANSWERED_WINDOW,
            },
        ).fetchall()
        for row in outcomes:
            if row["status"] is None:
                if not row["passed"]:
                    break  # in ask order, an ask that may still be decided stops the outcomes
                # No receipt will ever close it, so nothing can be told of it truthfully: it is
                # passed over, and the outcomes after it, and the grant's end, wait for it no more.
                position["outcome"] = row["ask_seq"]
                continue
            frames.append(
                outcome_frame(
                    ask_seq=row["ask_seq"],
                    request_id=str(row["request_id"]),
                    status=row["status"],
                    reason=row["reason"],
                )
            )
            position["outcome"] = row["ask_seq"]
        room = FRAMES_PER_POLL - len(frames)
        if room > 0:
            asks = self._connection.execute(
                "select a.ask_seq, r.document as request, d.request_id as recorded "
                "from door_ask a join world_society_decision_request r "
                "  on r.workspace_id = a.workspace_id and r.society_id = a.society_id "
                " and r.request_id = a.request_id "
                "left join world_society_decision d "
                "  on d.workspace_id = a.workspace_id and d.society_id = a.society_id "
                " and d.request_id = a.request_id "
                "where a.workspace_id = %(w)s and a.grant_id = %(g)s and a.ask_seq > %(ask)s "
                "order by a.ask_seq limit %(limit)s",
                {**self._ids, "ask": cursor.ask, "limit": room},
            ).fetchall()
            registry = decision_roles()
            asked_bytes = 0
            for row in asks:
                if row["recorded"] is not None:
                    position["ask"] = row["ask_seq"]
                    continue  # answered already, or closed: its outcome follows, not the ask
                request = row["request"]
                role = registry.for_request(request["profile"])
                if role is None:
                    raise LookupError("an ask names a request no registered role writes")
                frame = asked_frame(
                    ask_seq=row["ask_seq"],
                    request=request,
                    instruction=role.instruction,
                    choice_description=role.choice_description,
                    deadline_ms=request["provider_config"]["deadline_ms"],
                    messages=role.adapter.messages(
                        role, request["context"], AnsweringMechanism.TOOL_CALL
                    ),
                    act=role.choice(request["context"]).tool(),
                    idle_label=role.idle_label(request["context"]),
                )
                size = len(canonical_json(frame))
                if asked_bytes and asked_bytes + size > ASKED_BYTES_MAXIMUM:
                    break  # the next poll reads on from this ask
                asked_bytes += size
                frames.append(frame)
                position["ask"] = row["ask_seq"]
        room = FRAMES_PER_POLL - len(frames)
        if room > 0:
            for row in self._connection.execute(
                "select c.crossing_seq, c.document, c.game_items, b.disposition, b.reason "
                + _ARRIVALS_TAKEN
                + "and c.crossing_seq > %(after)s order by c.crossing_seq limit %(room)s",
                {**self._ids, "after": cursor.crossed, "room": room},
            ).fetchall():
                position["crossed"] = row["crossing_seq"]
                document = row["document"]
                if row["disposition"] == "arrived":
                    frames.append(
                        arrived_frame(
                            arrival_id=document["arrival_id"],
                            thing_id=document["thing_id"],
                            carried=row["game_items"],
                        )
                    )
                else:
                    frames.append(
                        arrival_refused_frame(
                            arrival_id=document["arrival_id"], reason=row["reason"]
                        )
                    )
        room = FRAMES_PER_POLL - len(frames)
        if room > 0:
            departed = self.departures(after=cursor.departed, limit=room)
            frames.extend(departed)
            position["departed"] += len(departed)
        ended = grant.ended(now)
        # The end goes last. A poll that read any ask carries no end, since that ask's outcome is
        # yet to be told (the outcome rule below), and a poll with no room left read none; so the
        # end comes only in a poll that read every ask there is and told every outcome.
        if (
            ended is not None
            and not cursor.ended
            and len(frames) < FRAMES_PER_POLL
            and position["outcome"] >= position["ask"]
            and self.head(Cursor()).settled(position["departed"])
        ):
            frames.append(
                grant_ended_frame(
                    grant_id=str(grant.grant_id), grant_seq=grant.grant_seq, reason=ended
                )
            )
            position["ended"] = True
        return frames, Cursor(**position)

    def departures(self, *, after: int, limit: int) -> list[dict[str, Any]]:
        """The departed frames of this grant's visitors after the first ``after``, at most
        ``limit``. A thing a visitor brought in goes home as the game item it came in as; a thing
        of the world it holds becomes the one item the mapping lets travel out for its kind only
        under a grant that lets things be carried out, and otherwise none."""
        rows = self._connection.execute(
            "select e.event_id, e.subject_id, e.document, c.game_items "
            + _DEPARTURES
            + "order by e.tick, (e.document->>'order')::int offset %(after)s limit %(limit)s",
            {**self._ids, "after": after, "limit": limit},
        ).fetchall()
        if not rows:
            return []
        outbound = self._outbound() if self.grant().scope.may_carry_out else {}
        frames = []
        for row in rows:
            details = row["document"]["thing"]
            came_as = {held["thing_id"]: held["game_item"] for held in row["game_items"] or []}
            frames.append(
                departed_frame(
                    departure_id=details.get("crossing_id") or str(row["event_id"]),
                    thing_id=str(row["subject_id"]),
                    why=row["document"]["reason"],
                    carried=[
                        {
                            "thing_id": held["id"],
                            "kind": held["kind"],
                            "game_item": came_as.get(held["id"])
                            or outbound.get(held["kind"]["kind"]),
                        }
                        for held in details.get("carried", [])
                    ],
                )
            )
        return frames

    def _delivered_before(self) -> int:
        """How many of this grant's departures come before the first one that carried something
        home and whose delivery the bridge has not reported: a hello's cursor starts there, so no
        such departure is ever skipped."""
        row = self._connection.execute(
            "with d as (select row_number() over "
            "  (order by e.tick, (e.document->>'order')::int) as n, e.event_id, e.document "
            + _DEPARTURES
            + ") select coalesce((select min(d.n) - 1 from d "
            "  where jsonb_array_length(coalesce(d.document->'thing'->'carried', '[]')) > 0 "
            "    and not exists (select 1 from door_delivery x where x.workspace_id = %(w)s "
            "      and x.departure_id "
            "        = coalesce((d.document->'thing'->>'crossing_id')::uuid, d.event_id))), "
            " (select count(*) from d)) as before",
            self._ids,
        ).fetchone()
        assert row is not None
        return int(row["before"])

    def _outbound(self) -> dict[str, str]:
        """The game item each thing kind travels out as, by the mapping of the bridge's hello."""
        presence = presence_of(self._connection, self._session.workspace_id, self._session.grant_id)
        if presence is None:
            return {}
        row = self._connection.execute(
            "select document from door_mapping where workspace_id = %(w)s "
            "and mapping_sha256 = %(m)s",
            {**self._ids, "m": presence.mapping_sha256},
        ).fetchone()
        if row is None:
            return {}
        return {
            item["kind"]["key"]: item["game_item"]
            for item in row["document"]["items"]
            if item["ways"] in ("out", "both")
        }

    def arrive(self, body: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """Write one arrival of a visitor of this standing grant, or answer with the one its
        arrival id wrote; True when it is new. The mapping is the one the bridge's own hello named;
        the arrival's manifest accounts for every game field it maps (each field the adapter said it
        reads is one of them)."""
        from exulanica.door.crossings import Visits

        with self._connection.transaction():
            self._live()
            grant = self._standing()
            presence = self._presence(self.bridge(), "sending a visitor")
            mapping = self._mapping(presence.mapping_sha256)
            visits = Visits(
                self._connection, self._session.workspace_id, grant, self._session.actor
            )
            return visits.arrive(
                arrival_id=body["arrival_id"],
                game_type=body["game_type"],
                look_key=body["look_key"],
                carried=body["carried"],
                presence=presence,
                mapping=mapping,
                reads=sorted(mapped_fields(mapping)),
            )

    def delivered(self, departure_id: uuid.UUID, body: Mapping[str, Any]) -> bool:
        """Record the bridge's report that its game delivered, or could not deliver, what one of
        this grant's departed visitors carried home; True when it is new. A report may follow the
        grant's end, and a second report of one departure changes nothing."""
        with self._connection.transaction():
            row = self._connection.execute(
                "select e.subject_id, e.document from world_society_event e join door_crossing c "
                "  on c.workspace_id = e.workspace_id and c.society_id = e.society_id "
                " and c.thing_id = e.subject_id and c.kind = 'arrival' "
                "where e.workspace_id = %(w)s and c.grant_id = %(g)s "
                "  and e.event_kind = 'thing_departed' "
                "  and coalesce((e.document->'thing'->>'crossing_id')::uuid, e.event_id) = %(d)s",
                {**self._ids, "d": departure_id},
            ).fetchone()
            if row is None:
                raise ChannelRefused(
                    "unknown_reference", 404, "nothing at this address is open to this channel"
                )
            carried = {held["id"] for held in row["document"]["thing"].get("carried", [])}
            named = [entry["thing_id"] for entry in (*body["delivered"], *body["not_delivered"])]
            if len(set(named)) != len(named) or set(named) != carried:
                raise ChannelRefused(
                    "delivery_not_this_departure",
                    422,
                    "a report names each thing the visitor carried home once",
                )
            document = {
                "departure_id": str(departure_id),
                "delivered": [dict(entry) for entry in body["delivered"]],
                "not_delivered": [dict(entry) for entry in body["not_delivered"]],
            }
            written = self._connection.execute(
                "insert into door_delivery (workspace_id, grant_id, departure_id, thing_id, "
                "document, document_sha256) values (%(w)s, %(g)s, %(d)s, %(t)s, %(doc)s, %(h)s) "
                "on conflict (workspace_id, departure_id) do nothing returning departure_id",
                {
                    **self._ids,
                    "d": departure_id,
                    "t": row["subject_id"],
                    "doc": Jsonb(document),
                    "h": sha256_of_canonical(document).hex(),
                },
            ).fetchone()
        return written is not None

    def gone(self, thing_id: uuid.UUID) -> bool:
        """Record that the person behind one of this grant's visitors left the game: the visitor
        is not asked again. True when it is new."""
        from exulanica.door.crossings import Visits

        with self._connection.transaction():
            self._live()
            grant = self.grant()
            visits = Visits(
                self._connection, self._session.workspace_id, grant, self._session.actor
            )
            if thing_id not in visits.present():
                raise ChannelRefused(
                    "unknown_reference", 404, "nothing at this address is open to this channel"
                )
            written = self._connection.execute(
                "insert into door_visitor_gone (workspace_id, grant_id, thing_id) "
                "values (%(w)s, %(g)s, %(t)s) on conflict do nothing returning thing_id",
                {**self._ids, "t": thing_id},
            ).fetchone()
        return written is not None

    def _mapping(self, mapping_sha256: str) -> dict[str, Any]:
        row = self._connection.execute(
            "select document from door_mapping where workspace_id = %(w)s "
            "and mapping_sha256 = %(m)s",
            {**self._ids, "m": mapping_sha256},
        ).fetchone()
        assert row is not None  # a presence names a mapping its hello stored
        return row["document"]

    def answer(self, body: Mapping[str, Any]) -> str:
        """Store a bridge's answer to one open ask of this standing grant, with who answered as its
        own hello named them, and return its digest."""
        try:
            with self._connection.transaction():
                return self._answer(body)
        except psycopg.errors.UniqueViolation as exc:
            raise ChannelRefused(
                "answer_already_given", 409, "this ask was answered already"
            ) from exc
        except psycopg.errors.CheckViolation as exc:
            # The grant reached its end between the read below and the insert, which 0149 checks
            # again under the lock revoking takes.
            raise ChannelRefused("grant_ended", 410, "this grant was revoked or has ended") from exc

    def _answer(self, body: Mapping[str, Any]) -> str:
        request_id = body["request_id"]
        self._live()
        self._standing()
        presence = self._presence(self.bridge(), "answering")
        row = self._connection.execute(
            "select a.ask_seq, r.document as request, d.request_id as recorded, "
            "w.request_id as answered "
            "from door_ask a join world_society_decision_request r "
            "  on r.workspace_id = a.workspace_id and r.society_id = a.society_id "
            " and r.request_id = a.request_id "
            "left join world_society_decision d "
            "  on d.workspace_id = a.workspace_id and d.society_id = a.society_id "
            " and d.request_id = a.request_id "
            "left join door_answer w "
            "  on w.workspace_id = a.workspace_id and w.request_id = a.request_id "
            "where a.workspace_id = %(w)s and a.grant_id = %(g)s and a.request_id = %(r)s",
            {**self._ids, "r": request_id},
        ).fetchone()
        if row is None:
            raise ChannelRefused(
                "unknown_reference", 404, "nothing at this address is open to this channel"
            )
        request = row["request"]
        if row["answered"] is not None:
            raise ChannelRefused("answer_already_given", 409, "this ask was answered already")
        if row["recorded"] is not None:
            raise ChannelRefused("answer_too_late", 409, "this ask's turn has been decided")
        if body["request_sha256"] != request["document_sha256"]:
            raise ChannelRefused(
                "answer_not_for_this_request", 422, "the request digest is not this ask's"
            )
        role = decision_roles().for_request(request["profile"])
        if role is None:
            raise LookupError("an ask names a request no registered role writes")
        offered = {
            role.adapter.option_from_record(option).label: option
            for option in request["context"]["options"]
        }
        option = offered.get(body["label"])
        if option is None:
            raise ChannelRefused("answer_not_offered", 422, "that label is not one offered")
        line = body.get("line")
        if line is not None and "line_characters_maximum" not in option:
            raise ChannelRefused("line_not_offered", 422, "that option says nothing")
        if "line_characters_maximum" in option and line is None:
            raise ChannelRefused("line_missing", 422, "that option says a line")
        if line is not None:
            fault = words_fault(line, maximum=LINE_CHARACTERS_MAXIMUM)
            if fault is not None:
                raise ChannelRefused("line_refused", 422, fault)
        document = {key: body[key] for key in ("request_id", "request_sha256", "label")}
        if line is not None:
            document["line"] = line
        digest = answer_sha256(document)
        self._connection.execute(
            "insert into door_answer (workspace_id, request_id, grant_id, ask_seq, "
            "adapter_version, mapping_sha256, declared_sha256, document, answer_sha256) "
            "values (%(w)s, %(r)s, %(g)s, %(s)s, %(v)s, %(m)s, %(c)s, %(d)s, %(h)s)",
            {
                **self._ids,
                "r": request_id,
                "s": row["ask_seq"],
                "v": presence.adapter_version,
                "m": presence.mapping_sha256,
                "c": presence.declared_sha256,
                "d": Jsonb(document),
                "h": digest,
            },
        )
        return digest


def _declaration(declared: Mapping[str, str]) -> dict[str, str]:
    """A program's declared name and maker, and the mind it says it thinks with if it says, each
    held to :func:`~exulanica.door.protocol.declared_fault`, or a refusal by name."""
    if not isinstance(declared, Mapping) or not {"name", "maker"} <= set(declared) <= {
        "name",
        "maker",
        "mind",
    }:
        raise ChannelRefused(
            "declared_refused", 422, "a declaration states a name and a maker, and may state a mind"
        )
    for key in sorted(declared):
        fault = declared_fault(
            declared[key],
            maximum=DECLARED_MIND_MAXIMUM if key == "mind" else DECLARED_CHARACTERS_MAXIMUM,
            slash=key == "mind",
        )
        if fault is not None:
            raise ChannelRefused("declared_refused", 422, f"the declared {key}: {fault}")
    return {key: declared[key] for key in sorted(declared)}
