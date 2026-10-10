"""Explicit playback state and fenced, bounded automatic calls to the existing society engine."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.db.session import set_workspace
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
from exulanica.world.society_engines import PLAYABLE_ENGINES, society_engine
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.world_clock import lead_room
from exulanica.world.world_clock_repository import ClockLeadExhausted, WorldClockRepository

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


class SocietyControlRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str,
        input_authorizer: Callable[[uuid.UUID, dict], None] | None = None,
        base_tick_interval_ms: int = DEFAULT_BASE_TICK_INTERVAL_MS,
    ) -> None:
        validate_settings("paused", 1, base_tick_interval_ms)
        self.connection, self.workspace_id = connection, workspace_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer
        self.base_tick_interval_ms = base_tick_interval_ms
        #: The inputs the running playback round has asked to authorize (:meth:`execute`).
        self._round: _RoundInputs | None = None
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    def _society(self, actor: uuid.UUID | None = None) -> SocietyRepository:
        authorizer = self.input_authorizer
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
        )

    @contextmanager
    def _authorizing_at_the_end(self) -> Iterator[_RoundInputs]:
        """While a round computes its minutes, authorizations are recorded, not run."""
        self._round = _RoundInputs()
        try:
            yield self._round
        finally:
            self._round = None

    def _scope(self, version_id: uuid.UUID) -> dict:
        self._society()._lock()
        row = self._society()._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        return row

    def _now(self) -> dt.datetime:
        return self.connection.execute("select clock_timestamp() as now").fetchone()["now"]

    def _control(self, society_id: uuid.UUID) -> dict | None:
        return self.connection.execute(
            "select * from world_society_control where workspace_id=%s and "
            "society_id=%s for update",
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

    def read(self, version_id: uuid.UUID) -> dict:
        with self.connection.transaction():
            society = self._scope(version_id)
            return self._public(society, self._control(society["society_id"]))

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

    def configure(
        self,
        version_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        base_revision: int,
        mode: str,
        speed: int,
        base_clock_revision: int | None = None,
    ) -> dict:
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
                    "lease_recovery_limit",
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
        return self._event(society, kind, {"reason": reason, **details})

    def _check_lease(self, row: dict | None, claim: ControlClaim) -> None:
        if (
            row is None
            or row["mode"] != "playing"
            or row["revision"] != claim.revision
            or row["lease_token"] != claim.token
            or row["lease_expires_at"] <= self._now()
        ):
            raise LeaseLost("playback lease expired or was replaced")

    def execute(self, claim: ControlClaim, *, max_ticks: int | None = None) -> dict:
        """Run a claimed batch: the minutes due, at most ``MAX_CATCHUP_TICKS``, or ``max_ticks``.

        A world that runs people by models is advanced one minute per claim (``max_ticks=1``), so
        each minute's choice points are asked before it; the minutes skipped are recorded. The
        inputs the minutes read are authorized after the minutes are computed and before the
        batch commits (:class:`_RoundInputs`), so the asset read lock is held from that
        authorization to the commit and not while the engine runs. An input refused then rolls
        the minutes back and pauses the society, with the receipt a refusal before them writes.
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
                    "source_unavailable"
                    if isinstance(exc, UnavailableSocietyInput)
                    else "invalid_society_state"
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
