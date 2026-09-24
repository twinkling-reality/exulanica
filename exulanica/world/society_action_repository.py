"""PostgreSQL audit boundary for typed user-directed society actions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.society import (
    SocietyEvent,
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    society_state_sha256,
)
from exulanica.world.society_actions import (
    ActionDisposition,
    ActionIntent,
    build_action_request,
    validate_action_request,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_planner import validate_society_input


class SocietyActionRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str,
        input_authorizer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer

    def _lock(self) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))",
            (str(self.workspace_id),),
        )

    def _authorize(self, document: dict[str, Any]) -> None:
        if self.input_authorizer is None:
            raise UnavailableSocietyInput("current society input authorization is not configured")
        self.input_authorizer(document)

    def _society(self, version_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
        suffix = " for update" if lock else ""
        row = self.connection.execute(
            "select * from world_society where workspace_id=%s and world_id=%s "
            f"and version_id=%s{suffix}",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownSociety("society is unavailable")
        if not society_engine(row["engine_version"]).directed_actions:
            raise ValueError(f"{row['engine_version']} takes no user actions")
        if society_state_sha256(row["state"]) != row["state_sha256"]:
            raise ValueError("stored society state digest mismatch")
        return row

    def _input(self, society_id: uuid.UUID, input_seq: int | None = None) -> dict[str, Any]:
        suffix = "order by input_seq desc limit 1" if input_seq is None else "and input_seq=%s"
        params: tuple[Any, ...] = (self.workspace_id, society_id)
        if input_seq is not None:
            params = (*params, input_seq)
        row = self.connection.execute(
            "select input_seq,document,document_sha256 from world_society_input "
            f"where workspace_id=%s and society_id=%s {suffix}",
            params,
        ).fetchone()
        if row is None:
            raise ValueError("society action input is unavailable")
        document = row["document"]
        validate_society_input(document)
        if (
            document["input_seq"] != row["input_seq"]
            or document["document_sha256"] != row["document_sha256"]
        ):
            raise ValueError("stored society action input binding mismatch")
        return document

    @staticmethod
    def _same_retry(
        document: dict[str, Any],
        *,
        requested_by: uuid.UUID,
        subject_id: uuid.UUID,
        base_tick: int,
        base_state_sha256: str,
        intent: ActionIntent,
    ) -> bool:
        expected_intent = {
            "kind": intent.kind,
            "target_id": intent.target_id,
            **({"affordance": intent.affordance} if intent.kind == "perform" else {}),
        }
        return (
            document["requested_by"] == str(requested_by)
            and document["subject_id"] == str(subject_id)
            and document["base_tick"] == base_tick
            and document["base_state_sha256"] == base_state_sha256
            and document["intent"] == expected_intent
        )

    def _request(self, society_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any] | None:
        row = self.connection.execute(
            "select action_seq,document,document_sha256 from world_society_action_request "
            "where workspace_id=%s and society_id=%s and request_id=%s",
            (self.workspace_id, society_id, request_id),
        ).fetchone()
        if row is None:
            return None
        document = row["document"]
        validate_action_request(document)
        if document["document_sha256"] != row["document_sha256"]:
            raise ValueError("stored action request digest mismatch")
        return document

    def _envelope(self, society_id: uuid.UUID, document: dict[str, Any]) -> dict[str, Any]:
        consumed = self.connection.execute(
            "select tick,disposition from world_society_transition_action "
            "where workspace_id=%s and society_id=%s and action_seq=("
            "select action_seq from world_society_action_request where workspace_id=%s "
            "and society_id=%s and request_id=%s)",
            (
                self.workspace_id,
                society_id,
                self.workspace_id,
                society_id,
                uuid.UUID(document["request_id"]),
            ),
        ).fetchone()
        return {
            "request": document,
            "status": "consumed" if consumed else "pending",
            "consumption": None if consumed is None else dict(consumed),
        }

    def create(
        self,
        version_id: uuid.UUID,
        *,
        request_id: uuid.UUID,
        requested_by: uuid.UUID,
        subject_id: uuid.UUID,
        base_tick: int,
        base_state_sha256: str,
        intent: ActionIntent,
    ) -> dict[str, Any]:
        with self.connection.transaction():
            self._lock()
            society = self._society(version_id, lock=True)
            existing = self._request(society["society_id"], request_id)
            if existing is not None:
                bound_input = self._input(society["society_id"], existing["input_seq"])
                self._authorize(bound_input)
                if not self._same_retry(
                    existing,
                    requested_by=requested_by,
                    subject_id=subject_id,
                    base_tick=base_tick,
                    base_state_sha256=base_state_sha256,
                    intent=intent,
                ):
                    raise StaleSocietyState(
                        "action idempotency key was reused with another request"
                    )
                return self._envelope(society["society_id"], existing)
            if society["current_tick"] != base_tick or society["state_sha256"] != base_state_sha256:
                raise StaleSocietyState("society changed; reload before requesting an action")
            document = self._input(society["society_id"])
            if (
                society["state"]["input_seq"] != document["input_seq"]
                or society["state"]["input_sha256"] != document["document_sha256"]
            ):
                raise StaleSocietyState("advance queued inputs before requesting an action")
            self._authorize(document)
            reserved = self.connection.execute(
                "select request_id from world_society_action_request where workspace_id=%s "
                "and society_id=%s and base_tick=%s and subject_id=%s",
                (self.workspace_id, society["society_id"], base_tick, subject_id),
            ).fetchone()
            if reserved is not None:
                raise StaleSocietyState(
                    "inhabitant already has an action request for this society state"
                )
            request = build_action_request(
                society["state"],
                document,
                request_id=request_id,
                requested_by=requested_by,
                subject_id=subject_id,
                intent=intent,
            )
            action_seq = self.connection.execute(
                "select coalesce(max(action_seq),0)+1 as next_seq "
                "from world_society_action_request where workspace_id=%s and society_id=%s",
                (self.workspace_id, society["society_id"]),
            ).fetchone()["next_seq"]
            self.connection.execute(
                "insert into world_society_action_request(workspace_id,society_id,action_seq,"
                "request_id,requested_by,subject_id,target_id,base_tick,input_seq,document,"
                "document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    society["society_id"],
                    action_seq,
                    request_id,
                    requested_by,
                    subject_id,
                    intent.target_id,
                    base_tick,
                    request["input_seq"],
                    Jsonb(request),
                    request["document_sha256"],
                ),
            )
            return self._envelope(society["society_id"], request)

    def read(self, version_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
        with self.connection.transaction():
            self._lock()
            society = self._society(version_id)
            request = self._request(society["society_id"], request_id)
            if request is None:
                raise UnknownSociety("society action request is unavailable")
            self._authorize(self._input(society["society_id"], request["input_seq"]))
            return self._envelope(society["society_id"], request)

    def history(self, version_id: uuid.UUID, *, limit: int = 64) -> tuple[dict[str, Any], ...]:
        """Return authorized audit envelopes newest first, never hidden request counts."""
        with self.connection.transaction():
            self._lock()
            society = self._society(version_id)
            rows = self.connection.execute(
                "select request_id from world_society_action_request where workspace_id=%s "
                "and society_id=%s order by action_seq desc limit %s",
                (self.workspace_id, society["society_id"], max(1, min(limit, 128))),
            ).fetchall()
            history = []
            for row in rows:
                request = self._request(society["society_id"], row["request_id"])
                assert request is not None
                self._authorize(self._input(society["society_id"], request["input_seq"]))
                history.append(self._envelope(society["society_id"], request))
            return tuple(history)

    def pending_for_step(
        self, version_id: uuid.UUID, *, base_tick: int, base_state_sha256: str
    ) -> tuple[dict[str, Any], ...]:
        """Load exact unconsumed requests while the caller holds the canonical step transaction."""
        self._lock()
        society = self._society(version_id, lock=True)
        if society["current_tick"] != base_tick or society["state_sha256"] != base_state_sha256:
            raise StaleSocietyState("society changed; reload before advancing")
        document = self._input(society["society_id"])
        self._authorize(document)
        rows = self.connection.execute(
            "select action_request.document,action_request.document_sha256 "
            "from world_society_action_request action_request "
            "left join world_society_transition_action consumed "
            "using(workspace_id,society_id,action_seq) "
            "where action_request.workspace_id=%s and action_request.society_id=%s "
            "and consumed.action_seq is null order by action_request.action_seq",
            (self.workspace_id, society["society_id"]),
        ).fetchall()
        requests = []
        for row in rows:
            request = row["document"]
            validate_action_request(request)
            if request["document_sha256"] != row["document_sha256"]:
                raise ValueError("stored action request digest mismatch")
            self._authorize(self._input(society["society_id"], request["input_seq"]))
            requests.append(request)
        return tuple(requests)

    def bind(
        self,
        version_id: uuid.UUID,
        *,
        tick: int,
        dispositions: tuple[ActionDisposition, ...],
        events: tuple[SocietyEvent, ...],
    ) -> None:
        """Bind deterministic dispositions after their transition and audit events are inserted."""
        society = self._society(version_id, lock=True)
        event_ids = {
            event.document.get("action_request_id"): event.event_id
            for event in events
            if event.kind == "user_action_requested"
        }
        for value in dispositions:
            action = self.connection.execute(
                "select action_seq from world_society_action_request where workspace_id=%s "
                "and society_id=%s and request_id=%s",
                (self.workspace_id, society["society_id"], value.request_id),
            ).fetchone()
            if action is None or str(value.request_id) not in event_ids:
                raise ValueError("action disposition is missing its request or audit event")
            self.connection.execute(
                "insert into world_society_transition_action("
                "workspace_id,society_id,tick,action_seq,disposition,event_id) "
                "values(%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    society["society_id"],
                    tick,
                    action["action_seq"],
                    value.disposition,
                    event_ids[str(value.request_id)],
                ),
            )
