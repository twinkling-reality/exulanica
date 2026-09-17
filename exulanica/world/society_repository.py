"""PostgreSQL authority for deterministic synthetic societies and historical inputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.society import (
    SOCIETY_ENGINE_VERSION,
    SOCIETY_POPULATION,
    SOCIETY_TICK_SECONDS,
    SocietyEvent,
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    event_document_sha256,
    society_state_sha256,
)
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_actions import (
    action_goal_policies,
    append_action_events,
    validate_action_request,
)
from exulanica.world.society_decisions import validate_decision_receipt
from exulanica.world.society_legacy import advance_society, initial_society
from exulanica.world.society_living import (
    LIVING_PROFILE,
    advance_living_society,
    current_routine,
    initial_living_society,
    living_places,
    routine_for,
)
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.society_social import (
    SOCIAL_PROFILE,
    advance_social_society,
    initial_social_society,
)

#: Profiles that consume authorized district inputs and record transition receipts.
INPUT_PROFILES = (PURPOSEFUL_PROFILE, SOCIAL_PROFILE, LIVING_PROFILE)


class SocietyRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str = DEFAULT_WORLD_ID,
        input_authorizer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer

    def _lock(self) -> None:
        # Same ordering as authored edits and structural invalidation.
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,880024))", (str(self.workspace_id),)
        )

    def _authorize(self, document: dict[str, Any]) -> None:
        if self.input_authorizer is None:
            raise UnavailableSocietyInput("current society input authorization is not configured")
        self.input_authorizer(document)

    def create(
        self,
        version_id: uuid.UUID,
        *,
        place_id: uuid.UUID,
        region_id: str,
        seed: str,
        actor: uuid.UUID,
        profile: str = SOCIETY_ENGINE_VERSION,
        initial_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connection.transaction():
            self._lock()
            version = self.connection.execute(
                "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
                "and version_id=%s for update",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            if version is None:
                raise UnknownSociety("world version is unavailable")
            existing = self._row(version_id, lock=True)
            if existing is not None:
                if existing["engine_version"] != profile:
                    raise StaleSocietyState(
                        "society profile is immutable; create another authored version"
                    )
                return self.snapshot(version_id)
            society_id = uuid.uuid5(version_id, "exulanica-society/v1")
            if profile == SOCIETY_ENGINE_VERSION:
                if initial_input is not None:
                    raise ValueError("v1 cannot consume district inputs")
                state = initial_society(society_id, seed)
            elif profile in INPUT_PROFILES:
                if initial_input is None:
                    raise UnavailableSocietyInput("v2 requires a server-authorized initial input")
                self._validate_scope(version_id, initial_input)
                self._authorize(initial_input)
                if profile == LIVING_PROFILE:
                    routine = current_routine()
                    [place] = living_places([initial_input], routine)
                    state = initial_living_society(
                        society_id, seed, place, routine, branch_id=str(version_id)
                    )
                else:
                    initializer = (
                        initial_social_society
                        if profile == SOCIAL_PROFILE
                        else initial_purposeful_society
                    )
                    state = initializer(society_id, seed, initial_input)
            else:
                raise ValueError("unsupported society engine version")
            population = (
                state["population"]["size"] if profile == LIVING_PROFILE else SOCIETY_POPULATION
            )
            row = self.connection.execute(
                "insert into world_society(workspace_id,society_id,world_id,version_id,place_id,"
                "region_id,engine_version,seed,population_size,tick_seconds,"
                "state,state_sha256,created_by) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (
                    self.workspace_id,
                    society_id,
                    self.world_id,
                    version_id,
                    place_id,
                    region_id,
                    profile,
                    seed,
                    population,
                    SOCIETY_TICK_SECONDS,
                    Jsonb(state),
                    society_state_sha256(state),
                    actor,
                ),
            ).fetchone()
            if initial_input is not None:
                self._insert_input(row, initial_input)
            return self._snapshot(row)

    def _validate_scope(self, version_id: uuid.UUID, document: dict[str, Any]) -> None:
        validate_society_input(document)
        if document["version_id"] != str(version_id) or document["world_id"] != self.world_id:
            raise ValueError("society input belongs to another world or branch")

    def _insert_input(self, row: dict, document: dict[str, Any]) -> None:
        self.connection.execute(
            "insert into "
            "world_society_input(workspace_id,society_id,input_seq,document,document_sha256) "
            "values(%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                row["society_id"],
                document["input_seq"],
                Jsonb(document),
                document["document_sha256"],
            ),
        )

    def record_input(self, version_id: uuid.UUID, document: dict[str, Any]) -> dict[str, Any]:
        """Internal authored-edit hook; call in the edit transaction, never from arbitrary JSON."""
        with self.connection.transaction():
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if row["engine_version"] not in INPUT_PROFILES:
                raise ValueError("legacy society cannot consume authored inputs")
            self._validate_scope(version_id, document)
            self._authorize(document)
            last = self.connection.execute(
                "select document from world_society_input where workspace_id=%s and society_id=%s "
                "order by input_seq desc limit 1",
                (self.workspace_id, row["society_id"]),
            ).fetchone()["document"]
            if document == last:
                return document
            if document["input_seq"] != last["input_seq"] + 1:
                raise StaleSocietyState("society input sequence changed; reload before recording")
            validate_input_successor(last, document)
            self._insert_input(row, document)
            return document

    def _input_rows(self, row: dict) -> list[dict]:
        return self.connection.execute(
            "select input_seq,document,document_sha256 from world_society_input "
            "where workspace_id=%s and society_id=%s order by input_seq",
            (self.workspace_id, row["society_id"]),
        ).fetchall()

    def _validated_inputs(self, row: dict) -> list[dict]:
        rows = self._input_rows(row)
        if not rows or rows[0]["input_seq"] != 1:
            raise ValueError("missing society genesis input")
        documents = []
        for value in rows:
            document = value["document"]
            self._validate_scope(row["version_id"], document)
            if (
                document["input_seq"] != value["input_seq"]
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored input binding mismatch")
            if documents:
                validate_input_successor(documents[-1], document)
            documents.append(document)
        return documents

    def snapshot(self, version_id: uuid.UUID) -> dict[str, Any]:
        self._lock()
        row = self._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        if row["engine_version"] in INPUT_PROFILES:
            # A historical snapshot is not a current rights grant. Authorizer checks dependencies
            # of the current state plus queued input. Historical replay checks every input below.
            documents = self._validated_inputs(row)
            current = documents[row["state"]["input_seq"] - 1]
            self._authorize(current)
            if documents[-1] != current:
                self._authorize(documents[-1])
            if row["engine_version"] == SOCIAL_PROFILE:
                for agent in row["state"]["social"]["agents"].values():
                    for memory in [*agent["observations"], *agent["beliefs"].values()]:
                        self._authorize(documents[memory["input_seq"] - 1])
        return self._snapshot(row)

    def _decisions(self, row: dict) -> list[dict]:
        rows = self.connection.execute(
            "select d.document,d.document_sha256,r.document as request "
            "from world_society_decision d "
            "join world_society_decision_request r using(workspace_id,society_id,request_id) "
            "where d.workspace_id=%s and d.society_id=%s order by d.decision_seq",
            (self.workspace_id, row["society_id"]),
        ).fetchall()
        documents = []
        for sequence, value in enumerate(rows, 1):
            document = value["document"]
            validate_decision_receipt(document, value["request"])
            if (
                document["decision_seq"] != sequence
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored decision sequence or digest mismatch")
            documents.append(document)
        return documents

    def _actions(self, row: dict, documents: list[dict]) -> list[dict]:
        rows = self.connection.execute(
            "select request.action_seq,request.document,request.document_sha256,"
            "binding.tick,binding.disposition,binding.event_id "
            "from world_society_action_request request "
            "left join world_society_transition_action binding "
            "using(workspace_id,society_id,action_seq) "
            "where request.workspace_id=%s and request.society_id=%s "
            "order by request.action_seq",
            (self.workspace_id, row["society_id"]),
        ).fetchall()
        actions = []
        for expected_sequence, value in enumerate(rows, 1):
            document = value["document"]
            validate_action_request(document)
            input_seq = document["input_seq"]
            if (
                value["action_seq"] != expected_sequence
                or document["document_sha256"] != value["document_sha256"]
                or document["branch_id"] != str(row["version_id"])
                or input_seq > len(documents)
                or document["input_sha256"] != documents[input_seq - 1]["document_sha256"]
            ):
                raise ValueError("stored society action sequence, scope or digest mismatch")
            actions.append(dict(value))
        return actions

    def advance(
        self, version_id: uuid.UUID, *, base_tick: int, base_state_sha256: str
    ) -> dict[str, Any]:
        with self.connection.transaction():
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
                raise StaleSocietyState("society changed; reload before advancing")
            if society_state_sha256(row["state"]) != row["state_sha256"]:
                raise ValueError("stored society state digest mismatch")
            if row["engine_version"] == SOCIETY_ENGINE_VERSION:
                state, events = advance_society(row["state"], row["seed"])
            elif row["engine_version"] == LIVING_PROFILE:
                documents = self._validated_inputs(row)
                inputs = documents[row["state"]["input_seq"] - 1 :]
                self._authorize(inputs[-1])
                routine = routine_for(row["state"])
                state, events = advance_living_society(
                    row["state"], row["seed"], living_places(inputs, routine), routine
                )
            elif row["engine_version"] in (PURPOSEFUL_PROFILE, SOCIAL_PROFILE):
                documents = self._validated_inputs(row)
                inputs = documents[row["state"]["input_seq"] - 1 :]
                # The latest authorized unavailable input must be able to pause the engine
                # even when earlier dependencies are now withdrawn. Historical replay/reads
                # still authorize every materialized input separately.
                self._authorize(inputs[-1])
                action_repository = SocietyActionRepository(
                    self.connection,
                    self.workspace_id,
                    world_id=self.world_id,
                    input_authorizer=self.input_authorizer,
                )
                requests = action_repository.pending_for_step(
                    version_id,
                    base_tick=base_tick,
                    base_state_sha256=base_state_sha256,
                )
                goal_policy, action_dispositions = action_goal_policies(
                    row["state"], inputs[-1], list(requests)
                )
                if row["engine_version"] == SOCIAL_PROFILE:
                    if inputs[-1]["availability"] == "available":
                        self.snapshot(version_id)
                        for document in inputs:
                            self._authorize(document)
                    decisions = self._decisions(row)
                    queued = [
                        d
                        for d in decisions
                        if d["decision_seq"] > row["state"]["social"]["last_decision_seq"]
                    ]
                    state, events, processed = advance_social_society(
                        row["state"],
                        row["seed"],
                        inputs,
                        queued,
                        external_goal_policy=goal_policy,
                    )
                else:
                    state, events = advance_purposeful_society(
                        row["state"], row["seed"], inputs, goal_policy=goal_policy
                    )
                events = append_action_events(
                    row["state"],
                    state,
                    inputs[-1],
                    list(requests),
                    action_dispositions,
                    events,
                )
            else:
                raise ValueError("unsupported society engine version")
            digest = society_state_sha256(state)
            self.connection.execute(
                "update world_society set current_tick=%s,state=%s,state_sha256=%s "
                "where workspace_id=%s and society_id=%s",
                (state["tick"], Jsonb(state), digest, self.workspace_id, row["society_id"]),
            )
            for event in events:
                self.connection.execute(
                    "insert into "
                    "world_society_event(workspace_id,society_id,event_id,tick,event_kind,"
                    "subject_id,object_id,place_id,document,document_sha256) "
                    "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        row["society_id"],
                        event.event_id,
                        event.tick,
                        event.kind,
                        event.subject_id,
                        event.object_id,
                        row["place_id"],
                        Jsonb(event.document),
                        event_document_sha256(event),
                    ),
                )
            if row["engine_version"] in INPUT_PROFILES:
                self.connection.execute(
                    "insert into "
                    "world_society_transition(workspace_id,society_id,tick,from_input_seq,"
                    "to_input_seq,previous_state_sha256,state_sha256,event_ids,events_sha256) "
                    "values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        row["society_id"],
                        state["tick"],
                        row["state"]["input_seq"],
                        state["input_seq"],
                        row["state_sha256"],
                        digest,
                        Jsonb([str(e.event_id) for e in events]),
                        society_state_sha256(ordered_events_document(events)),
                    ),
                )
                if row["engine_version"] == SOCIAL_PROFILE:
                    for sequence, disposition in processed:
                        self.connection.execute(
                            "insert into world_society_transition_decision("
                            "workspace_id,society_id,tick,decision_seq,disposition) "
                            "values(%s,%s,%s,%s,%s)",
                            (
                                self.workspace_id,
                                row["society_id"],
                                state["tick"],
                                sequence,
                                disposition,
                            ),
                        )
                if row["engine_version"] != LIVING_PROFILE:
                    action_repository.bind(
                        version_id,
                        tick=state["tick"],
                        dispositions=action_dispositions,
                        events=events,
                    )
            return self.snapshot(version_id)

    def events(self, version_id: uuid.UUID, *, limit: int = 256) -> tuple[dict[str, Any], ...]:
        self.snapshot(version_id)  # Current authorization applies to event materialization too.
        row = self._row(version_id)
        rows = self.connection.execute(
            "select "
            "event_id,tick,event_kind,subject_id,object_id,place_id,document,document_sha256,"
            "recorded_at from world_society_event where workspace_id=%s and society_id=%s "
            "order by tick desc, (document->>'order')::integer nulls last,event_id limit %s",
            (self.workspace_id, row["society_id"], max(1, min(limit, 256))),
        ).fetchall()
        if row["engine_version"] in INPUT_PROFILES:
            documents = self._validated_inputs(row)
            for seq in {value["document"]["input_seq"] for value in rows}:
                self._authorize(documents[seq - 1])
        return tuple(dict(value) for value in rows)

    def replay(self, version_id: uuid.UUID) -> dict[str, Any]:
        # Hold the same lock as advances so state, inputs, and transitions cannot straddle a tick.
        with self.connection.transaction():
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            expected_events: list[SocietyEvent] = []
            if row["engine_version"] == SOCIETY_ENGINE_VERSION:
                state = initial_society(
                    row["society_id"], row["seed"], population=row["population_size"]
                )
                for _ in range(row["current_tick"]):
                    state, events = advance_society(state, row["seed"])
                    expected_events.extend(events)
            elif row["engine_version"] == LIVING_PROFILE:
                state, expected_events = self._replay_living(row)
            elif row["engine_version"] in (PURPOSEFUL_PROFILE, SOCIAL_PROFILE):
                documents = self._validated_inputs(row)
                for document in documents:
                    self._authorize(document)
                actions = self._actions(row, documents)
                initializer = (
                    initial_social_society
                    if row["engine_version"] == SOCIAL_PROFILE
                    else initial_purposeful_society
                )
                state = initializer(
                    row["society_id"], row["seed"], documents[0], population=row["population_size"]
                )
                transitions = self.connection.execute(
                    "select * from world_society_transition where workspace_id=%s and "
                    "society_id=%s order by tick",
                    (self.workspace_id, row["society_id"]),
                ).fetchall()
                if len(transitions) != row["current_tick"]:
                    raise ValueError("missing or extra society transition")
                for transition in transitions:
                    previous_state = state
                    if (
                        transition["tick"] != state["tick"] + 1
                        or transition["from_input_seq"] != state["input_seq"]
                        or transition["to_input_seq"] < transition["from_input_seq"]
                        or transition["to_input_seq"] > len(documents)
                        or transition["previous_state_sha256"] != society_state_sha256(state)
                    ):
                        raise ValueError("society transition lineage mismatch")
                    inputs = documents[
                        transition["from_input_seq"] - 1 : transition["to_input_seq"]
                    ]
                    transition_actions = [
                        value
                        for value in actions
                        if value["document"]["base_tick"] == state["tick"]
                    ]
                    if any(value["tick"] != transition["tick"] for value in transition_actions):
                        raise ValueError("society action transition binding mismatch")
                    requests = [value["document"] for value in transition_actions]
                    goal_policy, action_dispositions = action_goal_policies(
                        state, inputs[-1], requests
                    )
                    if row["engine_version"] == SOCIAL_PROFILE:
                        bindings = self.connection.execute(
                            "select decision_seq,disposition "
                            "from world_society_transition_decision where "
                            "workspace_id=%s and society_id=%s and tick=%s order by decision_seq",
                            (self.workspace_id, row["society_id"], transition["tick"]),
                        ).fetchall()
                        decisions = {d["decision_seq"]: d for d in self._decisions(row)}
                        state, events, processed = advance_social_society(
                            state,
                            row["seed"],
                            inputs,
                            [decisions[b["decision_seq"]] for b in bindings],
                            external_goal_policy=goal_policy,
                        )
                        if processed != [(b["decision_seq"], b["disposition"]) for b in bindings]:
                            raise ValueError("social decision disposition replay mismatch")
                    else:
                        state, events = advance_purposeful_society(
                            state, row["seed"], inputs, goal_policy=goal_policy
                        )
                    events = append_action_events(
                        previous_state,
                        state,
                        inputs[-1],
                        requests,
                        action_dispositions,
                        events,
                    )
                    action_events = [
                        event for event in events if event.kind == "user_action_requested"
                    ]
                    for binding, disposition, event in zip(
                        transition_actions, action_dispositions, action_events, strict=True
                    ):
                        if (
                            binding["disposition"] != disposition.disposition
                            or binding["event_id"] != event.event_id
                            or binding["document"]["request_id"] != str(disposition.request_id)
                        ):
                            raise ValueError("society action disposition replay mismatch")
                    if (
                        transition["state_sha256"] != society_state_sha256(state)
                        or transition["event_ids"] != [str(e.event_id) for e in events]
                        or transition["events_sha256"]
                        != society_state_sha256(ordered_events_document(events))
                    ):
                        raise ValueError("society transition replay mismatch")
                    expected_events.extend(events)
                for action in actions:
                    if action["tick"] is None and (
                        action["document"]["base_tick"] != state["tick"]
                        or action["document"]["base_state_sha256"] != society_state_sha256(state)
                    ):
                        raise ValueError("pending society action is not bound to current state")
            else:
                raise ValueError("unsupported society engine version")
            self._verify_events(row, expected_events)
            if society_state_sha256(state) != row["state_sha256"] or state != row["state"]:
                raise ValueError("stored society state does not match deterministic replay")
            return self._snapshot(row) | {"replay_verified": True}

    def _replay_living(self, row: dict[str, Any]) -> tuple[dict[str, Any], list[SocietyEvent]]:
        """Regenerate a v4 society from genesis over every retained input and transition."""
        documents = self._validated_inputs(row)
        for document in documents:
            self._authorize(document)
        if self.connection.execute(
            "select 1 from world_society_action_request where workspace_id=%s and society_id=%s",
            (self.workspace_id, row["society_id"]),
        ).fetchone():
            raise ValueError("living society has user action requests it cannot consume")
        routine = routine_for(row["state"])
        held: dict = {}
        [genesis] = living_places(documents[:1], routine, held)
        state = initial_living_society(
            row["society_id"],
            row["seed"],
            genesis,
            routine,
            branch_id=str(row["version_id"]),
            population=row["state"]["population"]["requested"],
        )
        if state["population"]["size"] != row["population_size"]:
            raise ValueError("living society population does not match its genesis")
        transitions = self.connection.execute(
            "select * from world_society_transition where workspace_id=%s and "
            "society_id=%s order by tick",
            (self.workspace_id, row["society_id"]),
        ).fetchall()
        if len(transitions) != row["current_tick"]:
            raise ValueError("missing or extra society transition")
        expected: list[SocietyEvent] = []
        for transition in transitions:
            if (
                transition["tick"] != state["tick"] + 1
                or transition["from_input_seq"] != state["input_seq"]
                or transition["to_input_seq"] < transition["from_input_seq"]
                or transition["to_input_seq"] > len(documents)
                or transition["previous_state_sha256"] != society_state_sha256(state)
            ):
                raise ValueError("society transition lineage mismatch")
            inputs = documents[transition["from_input_seq"] - 1 : transition["to_input_seq"]]
            state, events = advance_living_society(
                state, row["seed"], living_places(inputs, routine, held), routine
            )
            if (
                transition["state_sha256"] != society_state_sha256(state)
                or transition["event_ids"] != [str(e.event_id) for e in events]
                or transition["events_sha256"]
                != society_state_sha256(ordered_events_document(events))
            ):
                raise ValueError("society transition replay mismatch")
            expected.extend(events)
        return state, expected

    def _verify_events(self, row: dict[str, Any], events: list[SocietyEvent]) -> None:
        stored = self.connection.execute(
            "select "
            "event_id,tick,event_kind,subject_id,object_id,place_id,document,document_sha256 "
            "from world_society_event where workspace_id=%s and society_id=%s",
            (self.workspace_id, row["society_id"]),
        ).fetchall()
        expected = {
            event.event_id: {
                "event_id": event.event_id,
                "tick": event.tick,
                "event_kind": event.kind,
                "subject_id": event.subject_id,
                "object_id": event.object_id,
                "place_id": row["place_id"],
                "document": event.document,
                "document_sha256": event_document_sha256(event),
            }
            for event in events
        }
        if {value["event_id"]: dict(value) for value in stored} != expected:
            raise ValueError("stored society events do not match deterministic replay")

    def _row(self, version_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if lock else ""
        return self.connection.execute(
            "select * from world_society where workspace_id=%s and world_id=%s "
            f"and version_id=%s{suffix}",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()

    @staticmethod
    def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            "profile": row["engine_version"],
            "society_id": row["society_id"],
            "world_id": row["world_id"],
            "version_id": row["version_id"],
            "place_id": row["place_id"],
            "region_id": row["region_id"],
            "seed": row["seed"],
            "population_size": row["population_size"],
            "tick_seconds": row["tick_seconds"],
            "current_tick": row["current_tick"],
            "state": row["state"],
            "state_sha256": row["state_sha256"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }
        if row["engine_version"] in INPUT_PROFILES:
            snapshot.update(
                {key: row["state"][key] for key in ("branch_id", "input_seq", "input_sha256")}
            )
        return snapshot
