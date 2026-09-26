"""PostgreSQL authority for deterministic synthetic societies and historical inputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world import society_authored_ground
from exulanica.world.society import (
    SOCIETY_ENGINE_VERSION,
    SOCIETY_POPULATION,
    SOCIETY_TICK_SECONDS,
    SocietyEvent,
    StaleSocietyState,
    UnavailableSocietyInput,
    UnknownSociety,
    event_document_sha256,
    inputs_ahead,
    society_state_sha256,
)
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_actions import (
    action_goal_policies,
    append_action_events,
    validate_action_request,
)
from exulanica.world.society_decisions import validate_decision_receipt
from exulanica.world.society_engines import (
    DEFAULT_ENGINE,
    INPUT_ENGINES,
    UnknownSocietyEngine,
    society_engine,
)
from exulanica.world.society_input_policy import is_authored_ground
from exulanica.world.society_legacy import advance_society, initial_society
from exulanica.world.society_living import (
    LIVING_PROFILE,
    advance_living_society,
    current_routine,
    initial_living_society,
    living_places,
    routine_for,
)
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.society_presence import (
    PresenceRefused,
    change_presence,
    presence_request,
    validate_presence_request,
)
from exulanica.world.society_social import (
    SOCIAL_PROFILE,
    advance_social_society,
    initial_social_society,
)

#: Profiles that consume authorized inputs and record transition receipts, from the engine table.
INPUT_PROFILES = INPUT_ENGINES


def consumed_places(document: dict[str, Any]) -> dict[str, Any]:
    """Where inhabitants can go, as the input a society's current state consumed states it.

    Read from the one input the state names, already authorized with it, and copied rather than
    derived: the targets an inhabitant can be directed to, each object activity the input says no
    inhabitant can reach, and the area the society walks. A queued input that no step has consumed
    yet is not described here, because nothing in the society has acted on it.
    """
    navigation = document["navigation"]
    return {
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "availability": document["availability"],
        "unavailable_reason": document["unavailable_reason"],
        "walkable_area": navigation.get("walkable_area"),
        "clearance_mm": navigation["clearance_mm"],
        "targets": [dict(target) for target in document["targets"]],
        "unavailable_affordances": [
            dict(record) for record in document.get("unavailable_affordances", [])
        ],
    }


class SocietyRepository:
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
        profile: str = DEFAULT_ENGINE,
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
            # An engine the table does not state is refused by name before anything is written.
            engine = society_engine(profile)
            if not engine.takes_inputs:
                if initial_input is not None:
                    raise ValueError(f"{profile} cannot consume district inputs")
                state = initial_society(
                    society_id,
                    seed,
                    minimum_population=engine.population_minimum,
                    maximum_population=engine.population_maximum,
                )
            else:
                if initial_input is None:
                    raise UnavailableSocietyInput(
                        f"{profile} requires a server-authorized initial input"
                    )
                if is_authored_ground(initial_input["profile"]) and not engine.saved_world:
                    # The living society reads streets, occupancy and stated surface heights out
                    # of its place. A saved world's ground states a flat rectangle and none of
                    # those, so this refuses rather than publishing a place of empty answers.
                    raise ValueError(f"{profile} has no place contract for an authored ground")
                self._validate_scope(version_id, initial_input)
                self._authorize(initial_input)
                # A saved world's own ground holds a handful of people; a district, its full
                # population. Read at the moment of creation, so a measurement can set another.
                population = (
                    society_authored_ground.AUTHORED_GROUND_POPULATION
                    if is_authored_ground(initial_input["profile"])
                    else SOCIETY_POPULATION
                )
                if profile == LIVING_PROFILE:
                    routine = current_routine()
                    [place] = living_places([initial_input], routine)
                    state = initial_living_society(
                        society_id, seed, place, routine, branch_id=str(version_id)
                    )
                elif profile == SOCIAL_PROFILE:
                    state = initial_social_society(
                        society_id, seed, initial_input, population=population
                    )
                elif profile == PURPOSEFUL_PROFILE:
                    state = initial_purposeful_society(
                        society_id, seed, initial_input, population=population
                    )
                else:
                    raise UnknownSocietyEngine(f"no genesis is implemented for {profile}")
            population = (
                state["population"]["size"]
                if profile == LIVING_PROFILE
                else len(state["inhabitants"])
            )
            if not engine.holds(population):
                raise ValueError(
                    f"{profile} holds {engine.population_minimum} to "
                    f"{engine.population_maximum} inhabitants, not {population}"
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

    def _chain(self, row: dict) -> int:
        """The newest input sequence, after checking the stored inputs run from one with no gap."""
        found = self.connection.execute(
            "select count(*) as n,min(input_seq) as low,max(input_seq) as high "
            "from world_society_input where workspace_id=%s and society_id=%s",
            (self.workspace_id, row["society_id"]),
        ).fetchone()
        if not found["n"] or found["low"] != 1:
            raise ValueError("missing society genesis input")
        if found["high"] != found["n"]:
            raise ValueError("society input chain has a gap")
        return int(found["high"])

    def _inputs(self, row: dict, sequences: Iterable[int]) -> dict[int, dict]:
        """The stored inputs with these sequence numbers, each held to its own row and validated.

        Every input was validated against the one before it when it was recorded, the table takes
        no update or delete, and replay checks the whole chain again from the first input. So a
        read loads and validates the inputs it shows or consumes, never the history behind them;
        what the history adds to a read is the one count ``_chain`` makes over its rows.
        """
        wanted = sorted(set(sequences))
        rows = self.connection.execute(
            "select input_seq,document,document_sha256 from world_society_input "
            "where workspace_id=%s and society_id=%s and input_seq=any(%s) order by input_seq",
            (self.workspace_id, row["society_id"], wanted),
        ).fetchall()
        if [value["input_seq"] for value in rows] != wanted:
            raise ValueError("a stored society input is missing")
        documents = {}
        for value in rows:
            document = value["document"]
            self._validate_scope(row["version_id"], document)
            if (
                document["input_seq"] != value["input_seq"]
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored input binding mismatch")
            documents[value["input_seq"]] = document
        return documents

    def _pending_inputs(self, row: dict) -> list[dict]:
        """The input the state consumed and every input queued after it, in order.

        What a step consumes. The engine checks each queued input against the one before it.
        """
        first = row["state"]["input_seq"]
        documents = self._inputs(row, range(first, self._chain(row) + 1))
        return [documents[sequence] for sequence in sorted(documents)]

    @staticmethod
    def _memories(row: dict) -> list[int]:
        """The inputs a social society's people remember, by sequence: what they observed and
        what they believe was each learned from one."""
        if row["engine_version"] != SOCIAL_PROFILE:
            return []
        return [
            memory["input_seq"]
            for agent in row["state"]["social"]["agents"].values()
            for memory in [*agent["observations"], *agent["beliefs"].values()]
        ]

    def named_inputs(self, row: dict) -> tuple[dict, ...]:
        """Every input a society's state names or its next minute consumes, to announce first.

        The input the state consumed, each queued after it and each its people remember: what a
        minute, the state read after it and a change of presence authorize, all in one transaction,
        so each is announced before the first takes the asset read lock
        (:func:`~exulanica.world.society.inputs_ahead`). A caller that reads the state and then
        runs minutes in one transaction, as a playback round does, announces these before the read.
        """
        if row["engine_version"] not in INPUT_PROFILES:
            return ()
        first = row["state"]["input_seq"]
        documents = self._inputs(row, [*range(first, self._chain(row) + 1), *self._memories(row)])
        return tuple(documents[sequence] for sequence in sorted(documents))

    def _validated_inputs(self, row: dict) -> list[dict]:
        """Every stored input from the first, each checked against the one before it: replay's."""
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

    def snapshot(self, version_id: uuid.UUID, *, places: bool = False) -> dict[str, Any]:
        """The current state; ``places`` adds, for a society with inputs, where inhabitants go."""
        self._lock()
        row = self._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        current = None
        if row["engine_version"] in INPUT_PROFILES:
            # A historical snapshot is not a current rights grant. Authorizer checks dependencies
            # of the current state plus queued input. Historical replay checks every input below.
            consumed, latest = row["state"]["input_seq"], self._chain(row)
            memories = self._memories(row)
            documents = self._inputs(row, [consumed, latest, *memories])
            current = documents[consumed]
            with inputs_ahead(self.connection, documents.values()):
                self._authorize(current)
                if latest != consumed:
                    self._authorize(documents[latest])
                for sequence in memories:
                    self._authorize(documents[sequence])
        snapshot = self._snapshot(row)
        if places and current is not None:
            snapshot["places"] = consumed_places(current)
        return snapshot

    def _decisions(self, row: dict, *, after: int = 0) -> list[dict]:
        """The stored receipts after ``after``, in decision order, each held to its request."""
        rows = self.connection.execute(
            "select d.document,d.document_sha256,r.document as request "
            "from world_society_decision d "
            "join world_society_decision_request r using(workspace_id,society_id,request_id) "
            "where d.workspace_id=%s and d.society_id=%s and d.decision_seq>%s "
            "order by d.decision_seq",
            (self.workspace_id, row["society_id"], after),
        ).fetchall()
        documents = []
        for sequence, value in enumerate(rows, after + 1):
            document = value["document"]
            validate_decision_receipt(document, value["request"])
            if (
                document["decision_seq"] != sequence
                or document["document_sha256"] != value["document_sha256"]
            ):
                raise ValueError("stored decision sequence or digest mismatch")
            documents.append(document)
        return documents

    def _consumed_decisions(self, row: dict) -> int:
        """The last receipt a committed minute consumed; every later one is queued."""
        return int(
            self.connection.execute(
                "select coalesce(max(decision_seq),0) as seq "
                "from world_society_transition_decision where workspace_id=%s and society_id=%s",
                (self.workspace_id, row["society_id"]),
            ).fetchone()["seq"]
        )

    def _bindings(self, row: dict) -> dict[int, list[dict]]:
        """The receipts each committed minute consumed, with what each did, by minute and in
        decision order: one read for a whole replay."""
        by_tick: dict[int, list[dict]] = {}
        for binding in self.connection.execute(
            "select tick,decision_seq,disposition from world_society_transition_decision "
            "where workspace_id=%s and society_id=%s order by decision_seq",
            (self.workspace_id, row["society_id"]),
        ).fetchall():
            by_tick.setdefault(binding["tick"], []).append(binding)
        return by_tick

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
        with self.connection.transaction(), ExitStack() as ahead:
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
                raise StaleSocietyState("society changed; reload before advancing")
            if society_state_sha256(row["state"]) != row["state_sha256"]:
                raise ValueError("stored society state digest mismatch")
            ahead.enter_context(inputs_ahead(self.connection, self.named_inputs(row)))
            if row["engine_version"] == SOCIETY_ENGINE_VERSION:
                state, events = advance_society(row["state"], row["seed"])
            elif row["engine_version"] == LIVING_PROFILE:
                inputs = self._pending_inputs(row)
                self._authorize(inputs[-1])
                routine = routine_for(row["state"])
                state, events = advance_living_society(
                    row["state"], row["seed"], living_places(inputs, routine), routine
                )
            elif row["engine_version"] in (PURPOSEFUL_PROFILE, SOCIAL_PROFILE):
                inputs = self._pending_inputs(row)
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
                    # A person's model decisions are receipts asked before this minute; with
                    # none, the policies are the direct requests' alone and nothing is added.
                    receipts = self._decisions(row, after=self._consumed_decisions(row))
                    policies, decided = model_goal_policies(
                        row["state"], inputs[-1], receipts, goal_policy
                    )
                    state, events = advance_purposeful_society(
                        row["state"], row["seed"], inputs, goal_policy=policies
                    )
                    processed = [(d.decision_seq, d.disposition) for d in decided]
                events = append_action_events(
                    row["state"],
                    state,
                    inputs[-1],
                    list(requests),
                    action_dispositions,
                    events,
                )
                if row["engine_version"] == PURPOSEFUL_PROFILE:
                    events = append_decision_events(
                        row["state"], state, inputs[-1], receipts, decided, events
                    )
            else:
                raise UnknownSocietyEngine(f"unsupported society engine {row['engine_version']!r}")
            self._record(row, state, events)
            if row["engine_version"] in INPUT_PROFILES:
                if row["engine_version"] in (PURPOSEFUL_PROFILE, SOCIAL_PROFILE):
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

    def _record(self, row: dict, state: dict[str, Any], events: tuple[SocietyEvent, ...]) -> None:
        """Commit one minute: the new state, its events and, for an input engine, its receipt."""
        digest = society_state_sha256(state)
        self.connection.execute(
            "update world_society set current_tick=%s,state=%s,state_sha256=%s "
            "where workspace_id=%s and world_id=%s and society_id=%s",
            (
                state["tick"],
                Jsonb(state),
                digest,
                self.workspace_id,
                self.world_id,
                row["society_id"],
            ),
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

    def change_presence(
        self,
        version_id: uuid.UUID,
        *,
        wanted: str,
        request_id: uuid.UUID,
        requested_by: uuid.UUID,
        base_tick: int,
        base_state_sha256: str,
    ) -> dict[str, Any]:
        """Send everyone away, or bring them back: one recorded minute, bound to this request.

        The person asks; this decides, under the same lock and compare-and-swap as a step. An
        exact retry of a recorded request returns the society as it is; a request against a state
        that has moved on is stale; one the state cannot honour is refused by name.
        """
        with self.connection.transaction(), ExitStack() as ahead:
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if not society_engine(row["engine_version"]).presence:
                raise PresenceRefused(
                    "engine_keeps_its_people",
                    f"the people of an {row['engine_version']} society are not sent away",
                )
            recorded = self.connection.execute(
                "select document from world_society_presence where workspace_id=%s "
                "and society_id=%s and request_id=%s",
                (self.workspace_id, row["society_id"], request_id),
            ).fetchone()
            if recorded is not None:
                document = recorded["document"]
                if (
                    document["presence"] != wanted
                    or document["base_tick"] != base_tick
                    or document["base_state_sha256"] != base_state_sha256
                    or document["requested_by"] != str(requested_by)
                ):
                    raise StaleSocietyState("this request id was used for another request")
                return self.snapshot(version_id)
            if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
                raise StaleSocietyState("society changed; reload before asking")
            if society_state_sha256(row["state"]) != row["state_sha256"]:
                raise ValueError("stored society state digest mismatch")
            waiting = self.connection.execute(
                "select 1 from world_society_action_request request "
                "left join world_society_transition_action consumed "
                "using(workspace_id,society_id,action_seq) "
                "where request.workspace_id=%s and request.society_id=%s "
                "and consumed.action_seq is null limit 1",
                (self.workspace_id, row["society_id"]),
            ).fetchone()
            if waiting is not None:
                # A directed request is consumed by the next ordinary minute; this minute would
                # pass it by and leave it bound to a state that no longer exists.
                raise PresenceRefused("a_request_is_waiting")
            deciding = self.connection.execute(
                "select 1 from world_society_decision_request request "
                "left join world_society_decision receipt "
                "using(workspace_id,society_id,request_id) "
                "left join world_society_transition_decision consumed "
                "on consumed.workspace_id=receipt.workspace_id "
                "and consumed.society_id=receipt.society_id "
                "and consumed.decision_seq=receipt.decision_seq "
                "where request.workspace_id=%s and request.society_id=%s "
                "and (request.base_tick=%s "
                "or (receipt.decision_seq is not null and consumed.decision_seq is null)) limit 1",
                (self.workspace_id, row["society_id"], row["current_tick"]),
            ).fetchone()
            if deciding is not None:
                # A model's decision is being asked for this minute, or answered and not yet
                # consumed: like a directed request, the next ordinary minute takes it.
                raise PresenceRefused("a_request_is_waiting")
            inputs = self._pending_inputs(row)
            # The state read after this minute names the same inputs: all are read first.
            ahead.enter_context(inputs_ahead(self.connection, self.named_inputs(row)))
            self._authorize(inputs[-1])
            request = presence_request(
                row["state"],
                request_id=request_id,
                requested_by=requested_by,
                wanted=wanted,  # type: ignore[arg-type]
            )
            state, events = change_presence(
                row["state"], row["seed"], inputs, request, population=row["population_size"]
            )
            self._record(row, state, events)
            self.connection.execute(
                "insert into world_society_presence(workspace_id,society_id,tick,request_id,"
                "requested_by,presence,document,document_sha256) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    row["society_id"],
                    state["tick"],
                    request_id,
                    requested_by,
                    wanted,
                    Jsonb(request),
                    request["document_sha256"],
                ),
            )
            return self.snapshot(version_id)

    def _presences(self, row: dict) -> dict[int, dict[str, Any]]:
        """Every recorded presence request, by the tick of the minute it took."""
        rows = self.connection.execute(
            "select tick,document,document_sha256 from world_society_presence "
            "where workspace_id=%s and society_id=%s order by tick",
            (self.workspace_id, row["society_id"]),
        ).fetchall()
        requests = {}
        for value in rows:
            document = value["document"]
            validate_presence_request(document)
            if (
                document["document_sha256"] != value["document_sha256"]
                or document["base_tick"] + 1 != value["tick"]
                or document["branch_id"] != str(row["version_id"])
            ):
                raise ValueError("stored presence request binding mismatch")
            requests[value["tick"]] = document
        return requests

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
            shown = {value["document"]["input_seq"] for value in rows}
            documents = self._inputs(row, shown)
            for sequence in sorted(shown):
                self._authorize(documents[sequence])
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
                with inputs_ahead(self.connection, documents):
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
                presences = self._presences(row)
                # Replayed from what was stored and bound, never asked again.
                person_decisions, person_bindings = (
                    ({d["decision_seq"]: d for d in self._decisions(row)}, self._bindings(row))
                    if row["engine_version"] == PURPOSEFUL_PROFILE
                    else ({}, {})
                )
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
                    presence_request_document = presences.get(transition["tick"])
                    if presence_request_document is not None:
                        # A minute somebody sent everyone away or brought them back: regenerated
                        # from the stored request and inputs, and it consumed no directed request.
                        if transition_actions:
                            raise ValueError("a presence minute cannot consume a directed request")
                        state, events = change_presence(
                            state,
                            row["seed"],
                            inputs,
                            presence_request_document,
                            population=row["population_size"],
                        )
                        if (
                            transition["state_sha256"] != society_state_sha256(state)
                            or transition["event_ids"] != [str(e.event_id) for e in events]
                            or transition["events_sha256"]
                            != society_state_sha256(ordered_events_document(events))
                        ):
                            raise ValueError("society transition replay mismatch")
                        expected_events.extend(events)
                        continue
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
                        bindings = person_bindings.get(transition["tick"], [])
                        receipts = [person_decisions[b["decision_seq"]] for b in bindings]
                        policies, decided = model_goal_policies(
                            state, inputs[-1], receipts, goal_policy
                        )
                        if [(d.decision_seq, d.disposition) for d in decided] != [
                            (b["decision_seq"], b["disposition"]) for b in bindings
                        ]:
                            raise ValueError("person decision disposition replay mismatch")
                        state, events = advance_purposeful_society(
                            state, row["seed"], inputs, goal_policy=policies
                        )
                    events = append_action_events(
                        previous_state,
                        state,
                        inputs[-1],
                        requests,
                        action_dispositions,
                        events,
                    )
                    if row["engine_version"] == PURPOSEFUL_PROFILE:
                        events = append_decision_events(
                            previous_state, state, inputs[-1], receipts, decided, events
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
                raise UnknownSocietyEngine(f"unsupported society engine {row['engine_version']!r}")
            self._verify_events(row, expected_events)
            if society_state_sha256(state) != row["state_sha256"] or state != row["state"]:
                raise ValueError("stored society state does not match deterministic replay")
            return self._snapshot(row) | {"replay_verified": True}

    def _replay_living(self, row: dict[str, Any]) -> tuple[dict[str, Any], list[SocietyEvent]]:
        """Regenerate a v4 society from genesis over every retained input and transition."""
        documents = self._validated_inputs(row)
        with inputs_ahead(self.connection, documents):
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
