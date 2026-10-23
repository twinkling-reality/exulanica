"""Explicit playback state and fenced, bounded automatic calls to the existing society engine."""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.db.session import set_workspace
from exulanica.world.decision_measures import measures
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society import (
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    inputs_ahead,
    society_state_sha256,
)
from exulanica.world.society_controls import (
    CONTROL_PROFILE,
    DEFAULT_BASE_TICK_INTERVAL_MS,
    EVENT_PROFILE,
    LEASE_SECONDS,
    MAX_CATCHUP_TICKS,
    MAX_CLAIM_ATTEMPTS,
    ControlClaim,
    LeaseLost,
    playing_due_at,
    ticks_due,
    utc,
    validate_settings,
)
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import PLAYABLE_ENGINES, society_engine
from exulanica.world.society_repository import SocietyInputBehind, SocietyRepository
from exulanica.world.society_sessions import (
    INVALID_SOCIETY_STATE,
    LEASE_RECOVERY_LIMIT,
    PAUSED_BY_PERSON,
    SESSION_CLOSED,
    SESSION_CLOSED_WORDS,
    SESSION_DEADLINE,
    SESSION_DECISIONS_READ,
    SESSION_KINDS,
    SESSION_LIMIT_REASONS,
    SESSION_MAXIMA,
    SESSION_OPENED,
    SOURCE_UNAVAILABLE,
    STOPPED_BY_PERSON,
    SessionRefused,
    closed_words,
    limit_reached,
    model_decisions,
    session_bounds,
    session_limits,
    session_used,
    sessions_from,
)
from exulanica.world.world_clock import lead_room
from exulanica.world.world_clock_repository import ClockLeadExhausted, WorldClockRepository

_LOG = logging.getLogger(__name__)

#: Profiles an explicitly enabled playback worker may advance.
#: The engines the playback worker may play, from the engine table.
PLAYABLE_PROFILES = PLAYABLE_ENGINES


class _RoundInputs:
    """Every society input a playback round asks to authorize, authorized once, at the round's end.

    A round runs its minutes holding the workspace lock, so nothing that changes the society's
    state, inputs or decisions can commit while it runs; what can is a guarded write that changes
    whether an input is permitted (``docs/asset-read-currency.md``). So the minutes are computed
    and written first, and every input they read is authorized afterwards, in the round's own
    transaction, through the runtime's ``authorize``: the stored bytes of all of them are read,
    then the global asset read lock is taken and held until the round commits, and under it only
    rows are read. An input asked for twice is authorized once; two different documents under one
    digest are refused, before the lock.
    """

    def __init__(self) -> None:
        self._asked: list[tuple[uuid.UUID, dict]] = []

    def record(self, actor: uuid.UUID, document: dict) -> None:
        self._asked.append((actor, document))

    def authorize(
        self, connection: psycopg.Connection, authorizer: Callable[[uuid.UUID, dict], None]
    ) -> None:
        once: dict[str, tuple[uuid.UUID, dict]] = {}
        for actor, document in self._asked:
            digest = document.get("document_sha256") if isinstance(document, dict) else None
            if not isinstance(digest, str):
                # Authorized as it was asked for, which refuses it by name.
                once[f"unnamed:{len(once)}"] = (actor, document)
                continue
            first = once.setdefault(digest, (actor, document))[1]
            if first is not document and first != document:
                raise ValueError("a round read two different society inputs under one digest")
        with inputs_ahead(connection, [document for _, document in once.values()]):
            for actor, document in once.values():
                authorizer(actor, document)


def _verified_receipt(row: dict) -> dict:
    """A stored playback receipt, its digest checked against the row and its own contents."""
    doc = row["document"]
    digest = society_state_sha256({k: v for k, v in doc.items() if k != "document_sha256"})
    if digest != row["document_sha256"] or digest != doc["document_sha256"]:
        raise ValueError("control receipt digest mismatch")
    return doc


def open_session_receipt(
    connection: psycopg.Connection, workspace_id: uuid.UUID, society_id: uuid.UUID
) -> dict | None:
    """The society's open living session's opening receipt, or None while none is open: its newest
    session receipt, where that one opened a session. Read on a connection scoped to the
    workspace; the host reads it before each minute to know whether it may ask a model."""
    row = (
        connection.cursor(row_factory=dict_row)
        .execute(
            "select document,document_sha256 from world_society_control_event "
            "where workspace_id=%s and society_id=%s and document->>'kind' in (%s,%s) "
            "order by event_seq desc limit 1",
            (workspace_id, society_id, *SESSION_KINDS),
        )
        .fetchone()
    )
    if row is None:
        return None
    doc = _verified_receipt(row)
    return doc if doc["kind"] == SESSION_OPENED else None


def open_sessions_past_deadline(
    connection: psycopg.Connection, workspace_id: uuid.UUID, now: dt.datetime
) -> list[dict]:
    """Every society of the workspace whose open living session is past its wall deadline, by its
    world and version (``world_id``, ``version_id``), for the playback worker's reaper."""
    rows = (
        connection.cursor(row_factory=dict_row)
        .execute(
            "select distinct on (e.society_id) e.society_id, s.version_id, s.world_id, "
            "e.document, e.document_sha256 from world_society_control_event e "
            "join world_society s using (workspace_id, society_id) "
            "where e.workspace_id=%s and e.document->>'kind' in (%s,%s) "
            "order by e.society_id, e.event_seq desc",
            (workspace_id, *SESSION_KINDS),
        )
        .fetchall()
    )
    found = []
    for row in rows:
        doc = _verified_receipt(row)
        if doc["kind"] == SESSION_OPENED and now >= dt.datetime.fromisoformat(doc["ends_by"]):
            found.append({"world_id": row["world_id"], "version_id": row["version_id"]})
    return found


def _refuse_untold(_version_id: uuid.UUID) -> None:
    """What a round composes with when its worker could not tell the society of an erased kind:
    nothing. The minute is refused as one whose input is unavailable, which pauses the society
    with the reason a person already reads for a source that cannot be read."""
    raise UnavailableSocietyInput(
        "a creature this society runs was erased and the input that sends it away could not be "
        "composed"
    )


class SocietyControlRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str,
        input_authorizer: Callable[[uuid.UUID, dict], None] | None = None,
        input_refresher: Callable[[uuid.UUID, uuid.UUID], None] | None = None,
        base_tick_interval_ms: int = DEFAULT_BASE_TICK_INTERVAL_MS,
    ) -> None:
        validate_settings("paused", 1, base_tick_interval_ms)
        self.connection, self.workspace_id = connection, workspace_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer
        #: What composes a version's next input for an actor where the society's is behind an
        #: erasure (:meth:`SocietyRepository.tell_of_erased_kinds`): a manual step is given it. A
        #: playback round is not: composing reads stored bytes and takes the asset read lock,
        #: which a round takes only once its minutes are computed, so the worker asks before the
        #: round, in a transaction of its own.
        self.input_refresher = input_refresher
        self.base_tick_interval_ms = base_tick_interval_ms
        #: The inputs the running playback round has asked to authorize (:meth:`execute`).
        self._round: _RoundInputs | None = None
        #: Whether the running round's society could not be told of an erased kind before it
        #: (:meth:`execute`'s ``untold``).
        self._untold = False
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    def _society(self, actor: uuid.UUID | None = None) -> SocietyRepository:
        authorizer = self.input_authorizer
        refresher = self.input_refresher
        round_inputs = self._round
        return SocietyRepository(
            self.connection,
            self.workspace_id,
            world_id=self.world_id,
            input_authorizer=(
                None
                if authorizer is None or actor is None
                else (lambda doc: authorizer(actor, doc))
                if round_inputs is None
                else (lambda doc: round_inputs.record(actor, doc))
            ),
            input_refresher=(
                _refuse_untold
                if self._untold
                else None
                if refresher is None or actor is None or round_inputs is not None
                else (lambda version: refresher(actor, version))
            ),
        )

    @contextmanager
    def _authorizing_at_the_end(self) -> Iterator[_RoundInputs]:
        """While a round computes its minutes, authorizations are recorded, not run."""
        self._round = _RoundInputs()
        try:
            yield self._round
        finally:
            self._round = None
            self._untold = False

    def _scope(self, version_id: uuid.UUID) -> dict:
        self._society()._lock()
        row = self._society()._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        return row

    def _now(self) -> dt.datetime:
        return self.connection.execute("select clock_timestamp() as now").fetchone()["now"]

    def _control(self, society_id: uuid.UUID, *, lock: bool = True) -> dict | None:
        return self.connection.execute(
            "select * from world_society_control where workspace_id=%s and "
            "society_id=%s" + (" for update" if lock else ""),
            (self.workspace_id, society_id),
        ).fetchone()

    def _ready(self, society: dict, actor: uuid.UUID) -> None:
        engine = society_engine(society["engine_version"])
        if not engine.playback:
            raise ValueError(engine.playback_refusal)
        repo = self._society(actor)
        # The minutes this round runs next, in this transaction, authorize every input queued after
        # the one consumed, and this read takes the asset read lock first: all are announced to it.
        with inputs_ahead(self.connection, repo.named_inputs(society)):
            repo.snapshot(society["version_id"])
        latest = repo._pending_inputs(society)[-1]
        if latest["availability"] != "available" or latest["navigation"]["unavailable_reason"]:
            raise UnavailableSocietyInput("society input is unavailable for playback")

    def _event(self, society: dict, kind: str, details: dict) -> dict:
        row = self._control(society["society_id"])
        sequence = row["last_event_seq"] + 1
        document = {
            "profile": EVENT_PROFILE,
            "society_id": str(society["society_id"]),
            "branch_id": str(society["version_id"]),
            "event_seq": sequence,
            "kind": kind,
            "revision": row["revision"],
            "actor_id": str(row["changed_by"]),
            "recorded_at": utc(self._now()),
            **details,
        }
        document["document_sha256"] = society_state_sha256(document)
        self.connection.execute(
            "insert into world_society_control_event(workspace_id,society_id,"
            "event_seq,document,document_sha256) values(%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                society["society_id"],
                sequence,
                Jsonb(document),
                document["document_sha256"],
            ),
        )
        self.connection.execute(
            "update world_society_control set last_event_seq=%s where "
            "workspace_id=%s and society_id=%s",
            (sequence, self.workspace_id, society["society_id"]),
        )
        return document

    _verified = staticmethod(_verified_receipt)

    def _session_receipts(self, society_id: uuid.UUID) -> list[dict]:
        """The society's session receipts, oldest first, each digest checked."""
        rows = self.connection.execute(
            "select document,document_sha256 from world_society_control_event "
            "where workspace_id=%s and society_id=%s and document->>'kind' in (%s,%s) "
            "order by event_seq desc",
            (self.workspace_id, society_id, *SESSION_KINDS),
        ).fetchall()
        return [self._verified(row) for row in reversed(rows)]

    def _open_session(self, society_id: uuid.UUID) -> dict | None:
        """The society's open session's opening receipt, or None while none is open."""
        return open_session_receipt(self.connection, self.workspace_id, society_id)

    def _close_session(
        self, society: dict, opened: dict, *, reason: str, closed_by: uuid.UUID | None
    ) -> dict:
        """Close the open session: where the society stands now, why, and who (None: the system).

        A close is how a session's spending stops, so it is never refused: a reason without words
        (``SESSION_CLOSED_WORDS``) still closes the session, and the missing words are logged."""
        if reason not in SESSION_CLOSED_WORDS:
            _LOG.warning("A living session closed for a reason with no words: %s", reason)
        now = self._society()._row(society["version_id"])
        return self._event(
            society,
            SESSION_CLOSED,
            {
                "session_id": opened["session_id"],
                "reason": reason,
                "closed_by": None if closed_by is None else str(closed_by),
                "end_tick": now["current_tick"],
                "end_state_sha256": now["state_sha256"],
                "closed_at": utc(self._now()),
            },
        )

    def _last_execution(self, society_id: uuid.UUID) -> dict | None:
        row = self.connection.execute(
            "select document,document_sha256 from world_society_control_event "
            "where workspace_id=%s and society_id=%s and document->>'kind'='advanced' "
            "order by event_seq desc limit 1",
            (self.workspace_id, society_id),
        ).fetchone()
        if row is None:
            return None
        doc = row["document"]
        digest = society_state_sha256({k: v for k, v in doc.items() if k != "document_sha256"})
        if digest != row["document_sha256"] or digest != doc["document_sha256"]:
            raise ValueError("control receipt digest mismatch")
        return {
            "event_seq": doc["event_seq"],
            "receipt_sha256": digest,
            "executed_ticks": doc["executed_ticks"],
            "execution_duration_ms": doc["execution_duration_ms"],
            "completed_at": doc["completed_at"],
        }

    def _last_minute_at(self, society_id: uuid.UUID) -> dt.datetime | None:
        """When the society's last minute was advanced through its control, or None where none was.

        The time its newest ``advanced`` or ``manual_step`` receipt states, whichever receipt is
        newer. An automatic batch's is ``completed_at``: the clock ``execute`` read once the
        batch's minutes had run, in the transaction that committed them, and the time it added the
        interval to for the next deadline. A manual step's is ``recorded_at``: the clock read as
        the step's receipt was written, in the transaction that committed its minute. Receipts are
        written in sequence under the workspace lock, so the newest of the two kinds is the last
        minute. The control row keeps no such time across a pause. Read in the caller's
        transaction, under that lock; the walk back from the newest receipt passes only the
        receipts written since that minute.
        """
        row = self.connection.execute(
            "select document,document_sha256 from world_society_control_event "
            "where workspace_id=%s and society_id=%s "
            "and document->>'kind' in ('advanced','manual_step') "
            "order by event_seq desc limit 1",
            (self.workspace_id, society_id),
        ).fetchone()
        if row is None:
            return None
        doc = row["document"]
        digest = society_state_sha256({k: v for k, v in doc.items() if k != "document_sha256"})
        if digest != row["document_sha256"] or digest != doc["document_sha256"]:
            raise ValueError("control receipt digest mismatch")
        return dt.datetime.fromisoformat(
            doc["completed_at"] if doc["kind"] == "advanced" else doc["recorded_at"]
        )

    def _public(self, society: dict, control: dict | None) -> dict:
        c = control or {
            "revision": 0,
            "mode": "paused",
            "speed": 1,
            "base_tick_interval_ms": self.base_tick_interval_ms,
            "next_due_at": None,
            "reason": None,
            "lease_expires_at": None,
            "last_event_seq": 0,
        }
        return {
            "profile": CONTROL_PROFILE,
            "society_id": str(society["society_id"]),
            "branch_id": str(society["version_id"]),
            "persisted": control is not None,
            "revision": c["revision"],
            "mode": c["mode"],
            "speed": c["speed"],
            "base_tick_interval_ms": c["base_tick_interval_ms"],
            "tick_interval_ms": c["base_tick_interval_ms"] // c["speed"],
            "interval_semantics": "minimum_wait_after_batch_completion",
            "last_batch_execution": self._last_execution(society["society_id"]),
            "simulated_seconds_per_tick": society["tick_seconds"],
            "max_catchup_ticks": MAX_CATCHUP_TICKS,
            "next_due_at": utc(c["next_due_at"]),
            "reason": c["reason"],
            "lease_expires_at": utc(c["lease_expires_at"]),
            "last_event_seq": c["last_event_seq"],
            "current_tick": society["current_tick"],
            "state_sha256": society["state_sha256"],
            "play_ineligible_reason": society_engine(society["engine_version"]).playback_refusal,
            "play_eligible": society_engine(society["engine_version"]).playback,
        }

    def read(self, version_id: uuid.UUID, *, lock: bool = True) -> dict:
        """Saved controls and defaults, without initialization. ``lock=False`` permits
        composition in a read-only transaction; subsequent writes revalidate their bases.
        """
        with self.connection.transaction():
            society = self._scope(version_id)
            return self._public(society, self._control(society["society_id"], lock=lock))

    def events(self, version_id: uuid.UUID, *, limit: int = 64) -> list[dict]:
        with self.connection.transaction():
            society = self._scope(version_id)
            rows = self.connection.execute(
                "select document,document_sha256 from "
                "world_society_control_event where workspace_id=%s and "
                "society_id=%s order by event_seq desc limit %s",
                (self.workspace_id, society["society_id"], max(1, min(limit, 128))),
            ).fetchall()
            for row in rows:
                doc = row["document"]
                if (
                    doc["document_sha256"] != row["document_sha256"]
                    or society_state_sha256(
                        {k: v for k, v in doc.items() if k != "document_sha256"}
                    )
                    != doc["document_sha256"]
                ):
                    raise ValueError("control receipt digest mismatch")
            return [row["document"] for row in rows]

    def sessions(self, version_id: uuid.UUID) -> list[dict]:
        """Every living session of the society, newest first."""
        with self.connection.transaction():
            society = self._scope(version_id)
            return sessions_from(self._session_receipts(society["society_id"]))

    def session(self, version_id: uuid.UUID, session_id: uuid.UUID) -> dict:
        """One living session of the society; refused ``session_unknown`` where it has none."""
        for one in self.sessions(version_id):
            if one["session_id"] == str(session_id):
                return one
        raise SessionRefused("session_unknown", "this society has no such session")

    def session_now(self, version_id: uuid.UUID) -> dict | None:
        """The society's latest living session as its control read states it, open or the last to
        close, with what it has used of each limit; None for a society that never had one."""
        with self.connection.transaction():
            society = self._scope(version_id)
            found = sessions_from(self._session_receipts(society["society_id"]))
            if not found:
                return None
            view = found[0]
            used = session_used(self.connection, self.workspace_id, society, view, self._now())
            opened, closed = view["opened"], view["closed"]
            return {
                "session_id": view["session_id"],
                "state": view["state"],
                "limits": opened["limits"],
                "used": used,
                "start_tick": opened["start_tick"],
                "opened_at": opened["opened_at"],
                "ends_by": opened["ends_by"],
                "end_tick": None if closed is None else closed["end_tick"],
                "closed_at": None if closed is None else closed["closed_at"],
                "closed_reason": None if closed is None else closed["reason"],
                "closed_reason_words": None if closed is None else closed_words(closed["reason"]),
            }

    def session_read(
        self, version_id: uuid.UUID, session_id: uuid.UUID, *, actor: uuid.UUID
    ) -> dict:
        """One living session with what it came to: what it used of each limit, its bounds by
        provider, its decisions in decision order (each with its request id, for stepping through
        a being's choices) and the measures of its model decisions overall and per model, from
        the decisions asked for its minutes alone. Reading the decisions authorizes the society's
        inputs for ``actor``, as the models read does. Refused ``session_unknown`` where the
        society has no such session."""
        with self.connection.transaction():
            society = self._scope(version_id)
            view = next(
                (
                    one
                    for one in sessions_from(self._session_receipts(society["society_id"]))
                    if one["session_id"] == str(session_id)
                ),
                None,
            )
            if view is None:
                raise SessionRefused("session_unknown", "this society has no such session")
            now = self._now()
            bounds = session_bounds(self.connection, self.workspace_id, view["session_id"], now)
            used = session_used(self.connection, self.workspace_id, society, view, now, bounds)
            closed = view["closed"]
            ticks = (view["opened"]["start_tick"], None if closed is None else closed["end_tick"])
            reader = self._society(actor)
            snapshot = reader.snapshot(version_id)
            decisions = SocietyDecisionRepository(reader)
            rows = sorted(
                (
                    {**row, "role": role.key}
                    for role in decision_roles()
                    for row in decisions.role_decisions(
                        role,
                        version_id,
                        latest=SESSION_DECISIONS_READ,
                        authorized=snapshot,
                        ticks=ticks,
                    )
                ),
                key=lambda row: row["decision_seq"],
            )[-SESSION_DECISIONS_READ:]
            asked = [row for row in rows if row["decider"]["kind"] == "model"]
            by_model: dict[tuple[str, str], list[dict]] = {}
            for row in asked:
                by_model.setdefault((row["provider"], row["model_id"]), []).append(row)
            return {
                **view,
                "used": used,
                "bounds": bounds,
                "decisions": [
                    {
                        "request_id": row["request_id"],
                        "decision_seq": row["decision_seq"],
                        "role": row["role"],
                        "subject_id": row["subject_id"],
                        "decider": row["decider"]["kind"],
                        "base_tick": row["base_tick"],
                        "consumed_tick": row["consumed_tick"],
                        # How its ask ended, so a timeout or an unavailable model shows without
                        # reading each receipt.
                        "status": row["status"],
                        "reason": row["reason"],
                    }
                    for row in rows
                ],
                # Every decision of the session (``total``), of which the latest ``maximum`` are
                # held (``counted``): the list is complete exactly when the two are equal.
                "decisions_read": {
                    "counted": len(rows),
                    "maximum": SESSION_DECISIONS_READ,
                    "total": model_decisions(
                        self.connection, self.workspace_id, society["society_id"], *ticks
                    )["total"],
                },
                "measures": measures(asked),
                "by_model": [
                    {"provider": provider, "model_id": model_id, "measures": measures(group)}
                    for (provider, model_id), group in sorted(by_model.items())
                ],
            }

    def open_session(
        self,
        version_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        request_id: uuid.UUID,
        base_revision: int,
        base_tick: int,
        base_state_sha256: str,
        limits: dict,
        speed: int = 1,
        base_clock_revision: int | None = None,
        reason: str = "opened_by_person",
    ) -> dict:
        """Open a living session on the society and play it, in one transaction.

        The caller states the control revision it read, and another is refused as stale. A paused
        society opens at the tick and state digest the caller read, and another is refused as
        stale; a society playing without a session opens at the minute it is at, recorded as the
        session's start, since its minute moves between a read and a write. Either way no pause is
        written: the session takes over the world's time. The same ``request_id`` answers the
        session it opened, whatever has happened since; with other limits it is refused
        ``session_request_reused``. While a session is open another is refused
        ``session_already_open``. Opening writes a ``configured`` receipt (playing) and then a
        ``session_opened`` one, which records ``reason``: ``opened_by_person`` for a session
        opened by its route, ``guest_pressed_play`` for one a guest's Play opened
        (:meth:`play_with_session`).
        """
        stated = session_limits(limits)
        with self.connection.transaction():
            society = self._scope(version_id)
            receipts = self._session_receipts(society["society_id"])
            same = [
                one
                for one in receipts
                if one["kind"] == SESSION_OPENED and one["request_id"] == str(request_id)
            ]
            if same:
                if same[0]["limits"] != stated:
                    raise SessionRefused(
                        "session_request_reused", "this request opened a session with other limits"
                    )
                return self.session(version_id, uuid.UUID(same[0]["session_id"]))
            if self._open_session(society["society_id"]) is not None:
                raise SessionRefused("session_already_open", "a session is open; stop it first")
            control = self._control(society["society_id"])
            playing = control is not None and control["mode"] == "playing"
            if not playing and (
                society["current_tick"] != base_tick or society["state_sha256"] != base_state_sha256
            ):
                raise StaleSocietyState("society changed; reload before opening a session")
            # Configuring below cancels a minute in flight, so a playing society starts at this one.
            start_tick, start_sha256 = (
                (society["current_tick"], society["state_sha256"])
                if playing
                else (base_tick, base_state_sha256)
            )
            self.configure(
                version_id,
                actor=actor,
                base_revision=base_revision,
                mode="playing",
                speed=speed,
                base_clock_revision=base_clock_revision,
            )
            session_id = uuid.uuid4()
            now = self._now()
            self._event(
                society,
                SESSION_OPENED,
                {
                    "session_id": str(session_id),
                    "request_id": str(request_id),
                    "reason": reason,
                    "opened_by": str(actor),
                    "limits": stated,
                    "start_tick": start_tick,
                    "start_state_sha256": start_sha256,
                    "opened_at": utc(now),
                    "ends_by": utc(now + dt.timedelta(seconds=stated["wall_seconds"])),
                },
            )
            return self.session(version_id, session_id)

    def play_with_session(
        self,
        version_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        base_revision: int,
        speed: int,
        base_clock_revision: int | None = None,
    ) -> dict:
        """Play the society, opening a living session for it where none is open: what a guest's
        Play does, so the models its owner chose are asked within the guest's grant.

        A paused society gets a session at its current tick and digest, limited by
        ``SESSION_MAXIMA`` (the grant's own figures bound what it may spend, as every session's
        bound is held to its grant), opened by ``actor`` for ``guest_pressed_play``. The same Play
        sent again opens the same session. A society already playing, or one with a session open,
        is configured as Play configures it. Answers the control.
        """
        with self.connection.transaction():
            society = self._scope(version_id)
            control = self._control(society["society_id"])
            playing = control is not None and control["mode"] == "playing"
            if playing or self._open_session(society["society_id"]) is not None:
                return self.configure(
                    version_id,
                    actor=actor,
                    base_revision=base_revision,
                    mode="playing",
                    speed=speed,
                    base_clock_revision=base_clock_revision,
                )
            if base_revision != (0 if control is None else control["revision"]):
                raise StaleSocietyState("playback controls changed; reload before saving")
            self.open_session(
                version_id,
                actor=actor,
                request_id=uuid.uuid5(
                    society["society_id"], f"guest_pressed_play:{base_revision}:{actor}"
                ),
                base_revision=base_revision,
                base_tick=society["current_tick"],
                base_state_sha256=society["state_sha256"],
                limits={**SESSION_MAXIMA, "usd": str(SESSION_MAXIMA["usd"])},
                speed=speed,
                base_clock_revision=base_clock_revision,
                reason="guest_pressed_play",
            )
            return self.read(version_id)

    def _pause_for_session(self, society: dict, opened: dict, reason: str) -> dict:
        """Pause the society because its open session reached a limit, and close the session
        with that reason and no person: the system closed it."""
        self.connection.execute(
            "update world_society_control set mode='paused',"
            "revision=revision+1,reason=%s,next_due_at=null,lease_token=null,"
            "claimed_at=null,lease_expires_at=null where workspace_id=%s and "
            "society_id=%s",
            (reason, self.workspace_id, society["society_id"]),
        )
        return self._close_session(society, opened, reason=reason, closed_by=None)

    def session_limit(self, claim: ControlClaim, now: dt.datetime | None = None) -> str | None:
        """The limit the claimed society's open session has reached, or None while it has
        reached none or none is open (``limit_reached``)."""
        with self.connection.transaction():
            society = self._scope(claim.version_id)
            opened = self._open_session(society["society_id"])
            if opened is None:
                return None
            return limit_reached(
                self.connection,
                self.workspace_id,
                society,
                opened,
                self._now() if now is None else now,
            )

    def close_session_at_limit(self, claim: ControlClaim, reason: str) -> dict:
        """Close the claimed society's open session at a limit it reached, under the claim's
        lease: the society pauses with ``reason`` and runs no minute. A claim that lost its lease
        changes nothing (:class:`LeaseLost`)."""
        if reason not in SESSION_LIMIT_REASONS:
            raise ValueError(f"no session limit {reason!r}")
        with self.connection.transaction():
            society = self._scope(claim.version_id)
            self._check_lease(self._control(society["society_id"]), claim)
            opened = self._open_session(society["society_id"])
            if opened is not None:
                self._pause_for_session(society, opened, reason)
            return self.read(claim.version_id)

    def close_session_past_deadline(self, version_id: uuid.UUID) -> bool:
        """Close the society's open session if its wall deadline has passed: the reaper's close
        for a world whose minutes are no longer claimed. True when this closed one."""
        with self.connection.transaction():
            society = self._scope(version_id)
            opened = self._open_session(society["society_id"])
            if opened is None or self._now() < dt.datetime.fromisoformat(opened["ends_by"]):
                return False
            self._pause_for_session(society, opened, SESSION_DEADLINE)
            return True

    def stop_session(
        self, version_id: uuid.UUID, *, actor: uuid.UUID, session_id: uuid.UUID
    ) -> dict:
        """Stop a living session: pause the society and close it (``stopped_by_person``).

        A session that already closed is answered as it closed, and nothing is written; one the
        society never had is refused ``session_unknown``.
        """
        with self.connection.transaction():
            society = self._scope(version_id)
            found = self.session(version_id, session_id)
            if found["state"] == "closed":
                return found
            control = self._control(society["society_id"])
            self.configure(
                version_id,
                actor=actor,
                base_revision=control["revision"],
                mode="paused",
                speed=control["speed"],
                closing_reason=STOPPED_BY_PERSON,
            )
            return self.session(version_id, session_id)

    def configure(
        self,
        version_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        base_revision: int,
        mode: str,
        speed: int,
        base_clock_revision: int | None = None,
        closing_reason: str = PAUSED_BY_PERSON,
    ) -> dict:
        """Play or pause the society, at a speed. Pausing closes its open living session, by
        ``closing_reason``, in the same transaction."""
        validate_settings(mode, speed, self.base_tick_interval_ms)
        if type(base_revision) is not int or base_revision < 0:
            raise ValueError("base_revision must be a nonnegative integer")
        with self.connection.transaction():
            society = self._scope(version_id)
            WorldClockRepository(self.connection, self.workspace_id, self.world_id).check_revision(
                version_id, base_clock_revision
            )
            prior = self._control(society["society_id"])
            if base_revision != (0 if prior is None else prior["revision"]):
                raise StaleSocietyState("playback controls changed; reload before saving")
            if mode == "playing":
                self._ready(society, actor)
            due = (
                None
                if mode == "paused"
                else playing_due_at(
                    self._now(),
                    self._last_minute_at(society["society_id"]),
                    self.base_tick_interval_ms // speed,
                )
            )
            self.connection.execute(
                "insert into world_society_control(workspace_id,society_id,"
                "revision,mode,speed,base_tick_interval_ms,next_due_at,"
                "changed_by) values(%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict(workspace_id,society_id) do update set "
                "revision=excluded.revision,mode=excluded.mode,"
                "speed=excluded.speed,"
                "base_tick_interval_ms=excluded.base_tick_interval_ms,"
                "next_due_at=excluded.next_due_at,"
                "changed_by=excluded.changed_by,reason=null,lease_token=null,"
                "claimed_at=null,lease_expires_at=null,claim_attempts=0",
                (
                    self.workspace_id,
                    society["society_id"],
                    base_revision + 1,
                    mode,
                    speed,
                    self.base_tick_interval_ms,
                    due,
                    actor,
                ),
            )
            self._event(
                society,
                "configured",
                {
                    "mode": mode,
                    "speed": speed,
                    "base_tick_interval_ms": self.base_tick_interval_ms,
                    "simulated_seconds_per_tick": society["tick_seconds"],
                    "next_due_at": utc(due),
                    "cancelled_claim_id": None
                    if prior is None or prior["lease_token"] is None
                    else str(prior["lease_token"]),
                },
            )
            if mode == "paused":
                opened = self._open_session(society["society_id"])
                if opened is not None:
                    self._close_session(society, opened, reason=closing_reason, closed_by=actor)
            return self.read(version_id)

    def manual_step(
        self,
        version_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        base_revision: int,
        base_tick: int,
        base_state_sha256: str,
        base_clock_revision: int | None = None,
    ) -> dict:
        if type(base_revision) is not int or base_revision < 0:
            raise ValueError("base_revision must be a nonnegative integer")
        with self.connection.transaction():
            society = self._scope(version_id)
            control = self._control(society["society_id"])
            if base_revision != (0 if control is None else control["revision"]):
                raise StaleSocietyState("playback controls changed; reload before stepping")
            if control is not None and control["mode"] != "paused":
                raise ValueError("pause_before_manual_step")
            if control is None:
                self.configure(version_id, actor=actor, base_revision=0, mode="paused", speed=1)
            # A being a person plays takes its person's answer first (SocietyRepository.advance).
            after = self._society(actor).advance(
                version_id,
                base_tick=base_tick,
                base_state_sha256=base_state_sha256,
                base_clock_revision=base_clock_revision,
                actor=actor,
            )
            receipt = self._event(
                society,
                "manual_step",
                {
                    "requested_by": str(actor),
                    "tick_from": base_tick,
                    "tick_to": after["current_tick"],
                    "previous_state_sha256": base_state_sha256,
                    "state_sha256": after["state_sha256"],
                },
            )
            return {"control": self.read(version_id), "society": after, "receipt": receipt}

    @classmethod
    def claim_in_workspace(
        cls,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        input_authorizer: Callable[[uuid.UUID, dict], None] | None = None,
        base_tick_interval_ms: int = DEFAULT_BASE_TICK_INTERVAL_MS,
    ) -> ControlClaim | None:
        """Lease the oldest due playing society in this workspace, whichever world holds it.

        Playback is fair across a workspace, not across one of its worlds: every world the
        workspace holds competes for the same one claim per round, by due time and then society
        identity. So the claim names no world. It names the world it was taken in, and
        ``execute`` on that world's repository runs it only there.
        """
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)
        with connection.transaction():
            locked = connection.execute(
                "select pg_try_advisory_xact_lock(hashtextextended(%s,880024)) as held",
                (str(workspace_id),),
            ).fetchone()["held"]
            if not locked:
                return None
            # A coupled world whose society already leads its sealed traffic by the clock's lead
            # waits: claiming it would run no minute (world/world_clock.py).
            row = connection.execute(
                "select c.*,s.version_id,s.world_id from world_society_control c join "
                "world_society s using(workspace_id,society_id) "
                "left join world_clock k on k.workspace_id=c.workspace_id "
                "and k.society_id=c.society_id "
                "where c.workspace_id=%s and "
                "c.mode='playing' and c.next_due_at<=clock_timestamp() "
                "and (c.lease_token is null or c.lease_expires_at<=clock_timestamp()) "
                "and (k.society_id is null or k.traffic_state is null "
                "or k.traffic_state='unavailable' "
                "or k.society_tick-k.traffic_sealed_through_tick<k.lead_ticks) "
                "order by c.next_due_at,c.society_id for update of c skip locked limit 1",
                (workspace_id,),
            ).fetchone()
            if row is None:
                return None
            scoped = cls(
                connection,
                workspace_id,
                world_id=row["world_id"],
                input_authorizer=input_authorizer,
                base_tick_interval_ms=base_tick_interval_ms,
            )
            society = scoped._scope(row["version_id"])
            if row["claim_attempts"] >= MAX_CLAIM_ATTEMPTS:
                scoped._pause_error(
                    society,
                    LEASE_RECOVERY_LIMIT,
                    "lease_recovery_exhausted",
                    {"abandoned_claim_id": str(row["lease_token"])},
                )
                return None
            token = uuid.uuid4()
            now = scoped._now()
            scoped.connection.execute(
                "update world_society_control set lease_token=%s,"
                "claimed_at=%s,lease_expires_at=%s,"
                "claim_attempts=claim_attempts+1 where workspace_id=%s and "
                "society_id=%s",
                (
                    token,
                    now,
                    now + dt.timedelta(seconds=LEASE_SECONDS),
                    workspace_id,
                    row["society_id"],
                ),
            )
            scoped._event(
                society,
                "claimed" if row["lease_token"] is None else "reclaimed",
                {
                    "claim_id": str(token),
                    "previous_claim_id": None
                    if row["lease_token"] is None
                    else str(row["lease_token"]),
                    "attempt": row["claim_attempts"] + 1,
                    "lease_seconds": LEASE_SECONDS,
                    "due_at": utc(row["next_due_at"]),
                },
            )
            return ControlClaim(
                workspace_id=workspace_id,
                world_id=row["world_id"],
                society_id=row["society_id"],
                version_id=row["version_id"],
                token=token,
                revision=row["revision"],
                actor=row["changed_by"],
            )

    def _pause_error(self, society: dict, reason: str, kind: str, details: dict) -> dict:
        self.connection.execute(
            "update world_society_control set mode='paused',"
            "revision=revision+1,reason=%s,next_due_at=null,lease_token=null,"
            "claimed_at=null,lease_expires_at=null where workspace_id=%s and "
            "society_id=%s",
            (reason, self.workspace_id, society["society_id"]),
        )
        receipt = self._event(society, kind, {"reason": reason, **details})
        # A pause the system makes closes the open living session, by the pause's own reason.
        opened = self._open_session(society["society_id"])
        if opened is not None:
            self._close_session(society, opened, reason=reason, closed_by=None)
        return receipt

    def _check_lease(self, row: dict | None, claim: ControlClaim) -> None:
        if (
            row is None
            or row["mode"] != "playing"
            or row["revision"] != claim.revision
            or row["lease_token"] != claim.token
            or row["lease_expires_at"] <= self._now()
        ):
            raise LeaseLost("playback lease expired or was replaced")

    def execute(
        self, claim: ControlClaim, *, max_ticks: int | None = None, untold: bool = False
    ) -> dict:
        """Run a claimed batch: the minutes due, at most ``MAX_CATCHUP_TICKS``, or ``max_ticks``.

        A world that runs people by models is advanced one minute per claim (``max_ticks=1``), so
        each minute's choice points are asked before it; the minutes skipped are recorded. The
        inputs the minutes read are authorized after the minutes are computed and before the
        batch commits (:class:`_RoundInputs`), so the asset read lock is held from that
        authorization to the commit and not while the engine runs. An input refused then rolls
        the minutes back and pauses the society, with the receipt a refusal before them writes.

        ``untold`` says the worker tried to tell this society of an erased kind before the round
        and the input could not be composed. The first minute then refuses as an unavailable
        input does, so the society pauses with that reason and is not left standing still; a
        society the erasure no longer concerns runs as ever, since only a minute that is behind
        asks.
        """
        if max_ticks is not None and not 1 <= max_ticks <= MAX_CATCHUP_TICKS:
            raise ValueError(f"a claim runs 1 to {MAX_CATCHUP_TICKS} minutes, not {max_ticks}")
        if claim.workspace_id != self.workspace_id:
            raise LeaseLost("playback claim belongs to another workspace")
        if claim.world_id != self.world_id:
            raise LeaseLost("playback claim belongs to another world")
        with self.connection.transaction():
            society = self._scope(claim.version_id)
            control = self._control(society["society_id"])
            if society["society_id"] != claim.society_id:
                raise LeaseLost("playback claim belongs to another society")
            self._check_lease(control, claim)
            started = self._now()
            interval = control["base_tick_interval_ms"] // control["speed"]
            due = ticks_due(started, control["next_due_at"], interval)
            count = min(MAX_CATCHUP_TICKS if max_ticks is None else max_ticks, due)
            # A coupled world runs no further ahead of its sealed traffic than its clock's lead;
            # the minutes past it are discarded with the rest of the debt.
            clock = self.connection.execute(
                "select lead_ticks,traffic_state,traffic_sealed_through_tick from world_clock "
                "where workspace_id=%s and world_id=%s and society_id=%s",
                (self.workspace_id, self.world_id, claim.society_id),
            ).fetchone()
            if clock is not None and clock["traffic_state"] in ("running", "blocked"):
                count = min(
                    count,
                    lead_room(
                        clock["lead_ticks"],
                        society["current_tick"],
                        clock["traffic_sealed_through_tick"],
                    ),
                )
            before_tick = society["current_tick"]
            before_hash = society["state_sha256"]
            details = {
                "claim_id": str(claim.token),
                "started_at": utc(started),
                "due_at": utc(control["next_due_at"]),
                "due_ticks": due,
                "base_tick_interval_ms": control["base_tick_interval_ms"],
                "speed": control["speed"],
                "simulated_seconds_per_tick": society["tick_seconds"],
                "tick_from": before_tick,
                "previous_state_sha256": before_hash,
            }
            self._untold = untold
            try:
                with self.connection.transaction():
                    with self._authorizing_at_the_end() as round_inputs:
                        self._ready(society, claim.actor)
                        current = society
                        executed = 0
                        for _ in range(count):
                            self._check_lease(control, claim)
                            try:
                                after = self._society(claim.actor).advance(
                                    claim.version_id,
                                    base_tick=current["current_tick"],
                                    base_state_sha256=current["state_sha256"],
                                    actor=claim.actor,
                                )
                            except SocietyInputBehind:
                                # A kind the society runs was erased after the worker asked,
                                # before this round. The round composes nothing, so it stops at
                                # the minutes computed and does not pause: the next round is told
                                # first, and the erased creature is not run meanwhile.
                                break
                            except ClockLeadExhausted:
                                # The count above keeps inside the lead, so this is a guard: stop
                                # at the minutes committed rather than pause a world that only
                                # waits.
                                break
                            executed += 1
                            current = {
                                **current,
                                "current_tick": after["current_tick"],
                                "state_sha256": after["state_sha256"],
                            }
                    count = executed
                    # Every input the minutes read is authorized now, once: their bytes are read,
                    # then the asset read lock is taken and held until this round commits. A
                    # refusal rolls the minutes back and pauses the society below.
                    if self.input_authorizer is not None:
                        round_inputs.authorize(self.connection, self.input_authorizer)
                    self._check_lease(control, claim)
            except (UnavailableSocietyInput, ValueError) as exc:
                self._check_lease(control, claim)
                reason = (
                    SOURCE_UNAVAILABLE
                    if isinstance(exc, UnavailableSocietyInput)
                    else INVALID_SOCIETY_STATE
                )
                receipt = self._pause_error(
                    society,
                    reason,
                    "paused_due_to_error",
                    {
                        **details,
                        "executed_ticks": 0,
                        "skipped_due_ticks": due,
                        "tick_to": before_tick,
                        "state_sha256": before_hash,
                    },
                )
                self._check_lease(control, claim)
                return {"control": self.read(claim.version_id), "receipt": receipt}
            completed = self._now()
            next_due = completed + dt.timedelta(milliseconds=interval)
            self.connection.execute(
                "update world_society_control set next_due_at=%s,"
                "lease_token=null,claimed_at=null,lease_expires_at=null,"
                "claim_attempts=0,reason=null where workspace_id=%s and "
                "society_id=%s and lease_token=%s",
                (next_due, self.workspace_id, claim.society_id, claim.token),
            )
            transitions = self.connection.execute(
                "select tick,from_input_seq,to_input_seq,"
                "previous_state_sha256,state_sha256,events_sha256 from "
                "world_society_transition where workspace_id=%s and "
                "society_id=%s and tick>%s and tick<=%s order by tick",
                (self.workspace_id, claim.society_id, before_tick, current["current_tick"]),
            ).fetchall()
            receipt = self._event(
                society,
                "advanced",
                {
                    **details,
                    "completed_at": utc(completed),
                    "execution_duration_ms": (completed - started) // dt.timedelta(milliseconds=1),
                    "executed_ticks": count,
                    "skipped_due_ticks": max(0, due - count),
                    "tick_to": current["current_tick"],
                    "state_sha256": current["state_sha256"],
                    "next_due_at": utc(next_due),
                    "transitions": transitions,
                },
            )
            self._check_lease(control, claim)
            return {"control": self.read(claim.version_id), "receipt": receipt}
