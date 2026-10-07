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

**Reading.** Frames are projected from what the grant's tables and the decision tables hold
(:mod:`exulanica.door.protocol`): the grant as it stands, each ask's request with the role's words,
each answered ask's recorded outcome, and the grant's end. A cheap head read says whether anything
is new before any frame is built, which is what a held poll repeats.

**Answering.** An answer names one ask of this grant and one of the labels its request offered. It
is stored as the bridge sent it, with the adapter version, mapping and declaration the grant's
presence names at that moment, and nothing else happens: the decision host makes the receipt, and
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
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import CanonicalisationError, sha256_of_canonical
from exulanica.door.bridges import Bridge, BridgeDirectory
from exulanica.door.grants import Grant, GrantRepository
from exulanica.door.mapping import MappingRefused, check_mapping, check_plain, check_reads
from exulanica.door.protocol import (
    DECLARED_CHARACTERS_MAXIMUM,
    DECLARED_MIND_MAXIMUM,
    FRAME_PROFILE,
    FRAMES_PER_POLL,
    LINE_CHARACTERS_MAXIMUM,
    QUIET_SECONDS,
    Cursor,
    answer_sha256,
    asked_frame,
    declared_fault,
    grant_ended_frame,
    grant_frame,
    outcome_frame,
    words_fault,
)
from exulanica.door.secrets import ChannelSession
from exulanica.errors import ExulanicaError
from exulanica.world.deciders import ADAPTER_VERSION
from exulanica.world.decision_roles import decision_roles

__all__ = [
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
    """A channel request the door will not act on: ``code`` and ``status`` say how it answers."""

    def __init__(self, code: str, status: int, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.status = status
        self.detail = detail


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


def presence_of(
    connection: psycopg.Connection, workspace_id: uuid.UUID, grant_id: uuid.UUID
) -> Presence | None:
    row = connection.execute(
        "select p.adapter_version, p.mapping_sha256, p.declared_sha256, d.document as declared, "
        "p.hello_at, p.polled_at from door_presence p left join door_declaration d "
        "  on d.workspace_id = p.workspace_id and d.declared_sha256 = p.declared_sha256 "
        "where p.workspace_id = %s and p.grant_id = %s",
        (workspace_id, grant_id),
    ).fetchone()
    return None if row is None else Presence(**row)


@dataclass(frozen=True, slots=True)
class Head:
    """What a cheap read of the channel finds: whether anything after a cursor is waiting."""

    asks: int
    outcomes: int
    grant_seq: int
    ended: str | None

    def news(self, cursor: Cursor) -> bool:
        return (
            self.asks > cursor.ask
            or self.outcomes > 0
            or self.grant_seq > cursor.grant
            or (self.ended is not None and not cursor.ended)
        )


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
        return {
            "profile": FRAME_PROFILE,
            "grant": grant.view(),
            "hold_seconds": bridge.hold_seconds,
            # From here on: asks made before this hello are not sent again; the grant is.
            "cursor": Cursor(ask=head.asks, outcome=head.asks).encode(),
        }

    def open_poll(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor] | None:
        """A poll's first read, checking the grant as every poll does: under a standing grant it
        records the poll; once the grant has ended it records nothing, and once the bridge has read
        that end (``cursor.ended``) it is refused. Then whatever is new after ``cursor``, or None.
        """
        self.bridge()
        grant = self.grant()
        ended = grant.ended(self._grants.now())
        if ended is not None and cursor.ended:
            raise ChannelRefused("grant_ended", 410, "this grant was revoked or has ended")
        if ended is None:
            polled = self._connection.execute(
                "update door_presence set polled_at = greatest(polled_at, statement_timestamp()) "
                "where workspace_id = %(w)s and grant_id = %(g)s returning grant_id",
                self._ids,
            ).fetchone()
        else:
            polled = self._connection.execute(
                "select grant_id from door_presence "
                "where workspace_id = %(w)s and grant_id = %(g)s",
                self._ids,
            ).fetchone()
        if polled is None:
            raise ChannelRefused("hello_first", 409, "say hello on this channel before polling")
        return self.read(cursor)

    def read(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor] | None:
        """What is new after ``cursor`` and the cursor after it, or None when the head says nothing
        is: the one read a held poll repeats."""
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
        )

    def frames(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor]:
        """Everything after ``cursor``, at most :data:`FRAMES_PER_POLL` frames, and the cursor
        after them: the grant if it changed, outcomes in ask order, open asks, then its end."""
        grant = self.grant()
        now = self._grants.now()
        frames: list[dict[str, Any]] = []
        position = {
            "ask": cursor.ask,
            "outcome": cursor.outcome,
            "grant": cursor.grant,
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
            "d.document->>'reason' as reason "
            "from door_ask a left join world_society_decision d "
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
            },
        ).fetchall()
        for row in outcomes:
            if row["status"] is None:
                break  # outcomes are reported in ask order, so the first still open stops them
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
            for row in asks:
                position["ask"] = row["ask_seq"]
                if row["recorded"] is not None:
                    continue  # answered already, or closed: its outcome follows, not the ask
                request = row["request"]
                role = registry.for_request(request["profile"])
                if role is None:
                    raise LookupError("an ask names a request no registered role writes")
                frames.append(
                    asked_frame(
                        ask_seq=row["ask_seq"],
                        request=request,
                        instruction=role.instruction,
                        choice_description=role.choice_description,
                        deadline_ms=request["provider_config"]["deadline_ms"],
                    )
                )
        ended = grant.ended(now)
        if ended is not None and not cursor.ended and len(frames) < FRAMES_PER_POLL:
            frames.append(
                grant_ended_frame(
                    grant_id=str(grant.grant_id), grant_seq=grant.grant_seq, reason=ended
                )
            )
            position["ended"] = True
        return frames, Cursor(**position)

    def answer(self, body: Mapping[str, Any]) -> str:
        """Store a bridge's answer to one open ask of this standing grant, with who answered as its
        presence names them now, and return its digest."""
        request_id = body["request_id"]
        self._standing()
        presence = presence_of(self._connection, self._session.workspace_id, self._session.grant_id)
        if presence is None:
            raise ChannelRefused("hello_first", 409, "say hello on this channel before answering")
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
                raise ChannelRefused("line_refused", 422, f"a line {fault}")
        document = {key: body[key] for key in ("request_id", "request_sha256", "label")}
        if line is not None:
            document["line"] = line
        digest = answer_sha256(document)
        try:
            with self._connection.transaction():
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
        except psycopg.errors.UniqueViolation as exc:
            raise ChannelRefused(
                "answer_already_given", 409, "this ask was answered already"
            ) from exc
        except psycopg.errors.CheckViolation as exc:
            # The grant ended between the read above and the insert, which 0149 checks under the
            # lock revoking takes.
            raise ChannelRefused("grant_ended", 410, "this grant was revoked or has ended") from exc
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
            raise ChannelRefused("declared_refused", 422, f"a declared {key} {fault}")
    return {key: declared[key] for key in sorted(declared)}
