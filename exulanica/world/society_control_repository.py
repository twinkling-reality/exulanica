"""Explicit playback state and fenced, bounded automatic calls to the existing society engine."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.db.session import set_workspace
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.society import (
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    society_state_sha256,
)
from exulanica.world.society_controls import (
    CONTROL_PROFILE,
    EVENT_PROFILE,
    LEASE_SECONDS,
    MAX_CATCHUP_TICKS,
    MAX_CLAIM_ATTEMPTS,
    ControlClaim,
    LeaseLost,
    ticks_due,
    utc,
    validate_settings,
)
from exulanica.world.society_repository import SocietyRepository

#: Profiles an explicitly enabled playback worker may advance.
PLAYABLE_PROFILES = ("exulanica-society/v2", "exulanica-society/v3", "exulanica-society/v4")


class SocietyControlRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str = DEFAULT_WORLD_ID,
        input_authorizer: Callable[[uuid.UUID, dict], None] | None = None,
        base_tick_interval_ms: int = 1000,
    ) -> None:
        validate_settings("paused", 1, base_tick_interval_ms)
        self.connection, self.workspace_id = connection, workspace_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer
        self.base_tick_interval_ms = base_tick_interval_ms
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    def _society(self, actor: uuid.UUID | None = None) -> SocietyRepository:
        return SocietyRepository(
            self.connection,
            self.workspace_id,
            world_id=self.world_id,
            input_authorizer=(
                None
                if self.input_authorizer is None or actor is None
                else lambda doc: self.input_authorizer(actor, doc)
            ),
        )

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
        if society["engine_version"] not in PLAYABLE_PROFILES:
            raise ValueError("legacy_society_not_playable")
        repo = self._society(actor)
        repo.snapshot(society["version_id"])
        latest = repo._validated_inputs(society)[-1]
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
            "play_ineligible_reason": (
                "legacy_society_not_playable"
                if society["engine_version"] == "exulanica-society/v1"
                else None
            ),
            "play_eligible": society["engine_version"] in PLAYABLE_PROFILES,
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
        self, version_id: uuid.UUID, *, actor: uuid.UUID, base_revision: int, mode: str, speed: int
    ) -> dict:
        validate_settings(mode, speed, self.base_tick_interval_ms)
        if type(base_revision) is not int or base_revision < 0:
            raise ValueError("base_revision must be a nonnegative integer")
        with self.connection.transaction():
            society = self._scope(version_id)
            prior = self._control(society["society_id"])
            if base_revision != (0 if prior is None else prior["revision"]):
                raise StaleSocietyState("playback controls changed; reload before saving")
            if mode == "playing":
                self._ready(society, actor)
            due = (
                None
                if mode == "paused"
                else self._now() + dt.timedelta(milliseconds=self.base_tick_interval_ms // speed)
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
            after = self._society(actor).advance(
                version_id, base_tick=base_tick, base_state_sha256=base_state_sha256
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

    def _in_world(self, world_id: str) -> SocietyControlRepository:
        """This repository's connection and authority, scoped to another world of the workspace."""
        if world_id == self.world_id:
            return self
        return SocietyControlRepository(
            self.connection,
            self.workspace_id,
            world_id=world_id,
            input_authorizer=self.input_authorizer,
            base_tick_interval_ms=self.base_tick_interval_ms,
        )

    def claim(self) -> ControlClaim | None:
        """Lease the oldest due playing society in this workspace, whichever world holds it.

        Playback is fair across a workspace, not across one of its worlds: the default world and
        every saved world a person made compete for the same one claim per round, by due time
        and then society identity. The claim names the world it was taken in, and ``execute``
        runs it only there.
        """
        with self.connection.transaction():
            locked = self.connection.execute(
                "select pg_try_advisory_xact_lock(hashtextextended(%s,880024)) as held",
                (str(self.workspace_id),),
            ).fetchone()["held"]
            if not locked:
                return None
            row = self.connection.execute(
                "select c.*,s.version_id,s.world_id from world_society_control c join "
                "world_society s using(workspace_id,society_id) "
                "where c.workspace_id=%s and "
                "c.mode='playing' and c.next_due_at<=clock_timestamp() "
                "and (c.lease_token is null or c.lease_expires_at<=clock_timestamp()) "
                "order by c.next_due_at,c.society_id for update of c skip locked limit 1",
                (self.workspace_id,),
            ).fetchone()
            if row is None:
                return None
            scoped = self._in_world(row["world_id"])
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
            now = self._now()
            self.connection.execute(
                "update world_society_control set lease_token=%s,"
                "claimed_at=%s,lease_expires_at=%s,"
                "claim_attempts=claim_attempts+1 where workspace_id=%s and "
                "society_id=%s",
                (
                    token,
                    now,
                    now + dt.timedelta(seconds=LEASE_SECONDS),
                    self.workspace_id,
                    row["society_id"],
                ),
            )
            self._event(
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
                workspace_id=self.workspace_id,
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

    def execute(self, claim: ControlClaim) -> dict:
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
            count = min(MAX_CATCHUP_TICKS, due)
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
                    self._ready(society, claim.actor)
                    current = society
                    for _ in range(count):
                        self._check_lease(control, claim)
                        after = self._society(claim.actor).advance(
                            claim.version_id,
                            base_tick=current["current_tick"],
                            base_state_sha256=current["state_sha256"],
                        )
                        current = {
                            **current,
                            "current_tick": after["current_tick"],
                            "state_sha256": after["state_sha256"],
                        }
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
