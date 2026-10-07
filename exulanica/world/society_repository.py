"""PostgreSQL authority for deterministic synthetic societies and historical inputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.crossings import CROSSINGS_PER_MINUTE, BoundCrossing, crossing_stream
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import append_role_events, apply_receipts
from exulanica.world.society import (
    SOCIETY_POPULATION,
    SOCIETY_TICK_SECONDS,
    SocietyEvent,
    SocietyLivesElsewhere,
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
    creatable_engine,
    society_engine,
)
from exulanica.world.society_grounds import society_population
from exulanica.world.society_input_policy import LIVING_INPUTS, THING_INPUTS, is_authored_ground
from exulanica.world.society_legacy import advance_society, initial_society
from exulanica.world.society_living import (
    initial_living_society,
    input_routine,
    living_places,
    routine_for,
)
from exulanica.world.society_living_decisions import LivingSeam, living_step
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    SocietyStartRefused,
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
from exulanica.world.society_things import advance_things, initial_things_society
from exulanica.world.world_clock_repository import WorldClockRepository

#: Profiles that consume authorized inputs and record transition receipts, from the engine table.
INPUT_PROFILES = INPUT_ENGINES
#: The most events one read returns: the read's own bound, a page of a society's history.
EVENTS_READ_MAXIMUM = 256


class InvalidEventCursor(ValueError):
    """A cursor that names no event of this society, or is not one this repository wrote."""

    code = "invalid_event_cursor"


def event_cursor(event: dict[str, Any]) -> str:
    """Where a page of events ends, as the next page names it: the last event's tick, its order
    within the tick (empty where it states none) and its id. Opaque to a client."""
    order = event["document"].get("order")
    return f"{event['tick']}:{'' if order is None else order}:{event['event_id']}"


def _cursor_parts(cursor: str) -> tuple[int, int | None, uuid.UUID]:
    try:
        tick, order, event_id = cursor.split(":", 2)
        return int(tick), None if order == "" else int(order), uuid.UUID(event_id)
    except ValueError as exc:
        raise InvalidEventCursor("this is not a cursor an events read gave") from exc


def consumed_places(document: dict[str, Any]) -> dict[str, Any]:
    """Where inhabitants can go, as the input a society's current state consumed states it.

    Read from the one input the state names, already authorized with it, and copied rather than
    derived: the targets an inhabitant can be directed to, each object activity the input says no
    inhabitant can reach, and the area the society walks. A queued input that no step has consumed
    yet is not described here, because nothing in the society has acted on it.
    """
    navigation = document["navigation"]
    living = document.get("living")
    place = living.get("place") if isinstance(living, dict) else None
    words = place.get("words") if isinstance(place, dict) else None
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
        **(
            {
                "living_destinations": [
                    {
                        "destination_id": destination["destination_id"],
                        "use_class": destination["use_class"],
                        "label": destination["label"],
                    }
                    for destination in document["living"]["place"]["destinations"]
                    if destination["enabled"]
                ]
            }
            if "living" in document
            else {}
        ),
        # What is said of where a site world's people are and walk, keyed by the society ground
        # the catalog states its words for; a town's place states none, and serves none.
        **(
            {
                "place_words": {
                    "ground": _ground_key(navigation["profile"]),
                    "here": words["here"],
                    "around": words["around"],
                }
            }
            if isinstance(words, dict)
            else {}
        ),
    }


def _ground_key(navigation_profile: str) -> str:
    from exulanica.world.society_grounds import society_ground_for_navigation

    return society_ground_for_navigation(navigation_profile).key


def _consumed(receipts: list[Any], decided: Any) -> list[tuple[Any, Any]]:
    """Each receipt a minute consumed with what the minute did with it, in decision order."""
    by_request = {str(disposition.request_id): disposition for disposition in decided}
    return [
        (receipt, by_request[str(receipt["request_id"])])
        for receipt in receipts
        if str(receipt["request_id"]) in by_request
    ]


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
        """Create this version's society, or read back the one it holds with the same engine.

        An engine the table does not state, or states as retired, is refused by name before
        anything is read or written (:func:`~exulanica.world.society_engines.creatable_engine`).
        """
        creatable_engine(profile)
        return self._create(
            version_id,
            place_id=place_id,
            region_id=region_id,
            seed=seed,
            actor=actor,
            profile=profile,
            initial_input=initial_input,
        )

    def held(
        self, version_id: uuid.UUID, *, profile: str, region_id: str | None
    ) -> dict[str, Any] | None:
        """This version's society where it already holds one, read back with nothing composed.

        None where it holds none, so a caller composes the first input only for a society it
        will create. Another engine is refused as :meth:`create` refuses it, and another region by
        name (:class:`~exulanica.world.society.SocietyLivesElsewhere`); a creation that names no
        region reads back the one there is.
        """
        row = self._row(version_id)
        if row is None:
            return None
        if row["engine_version"] != profile:
            raise StaleSocietyState("society profile is immutable; create another authored version")
        if region_id is not None and row["region_id"] != region_id:
            raise SocietyLivesElsewhere(
                "this version's society lives in another region; one version holds one society"
            )
        return self.snapshot(version_id)

    def _create(
        self,
        version_id: uuid.UUID,
        *,
        place_id: uuid.UUID,
        region_id: str,
        seed: str,
        actor: uuid.UUID,
        profile: str,
        initial_input: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """The write a society's creation makes, for any engine the table states.

        :meth:`create` is the only caller that makes a society; a retired engine's genesis stays
        here because it is the write a stored society of that engine was made by, which a test
        repeats to hold such a society (``tests/retired_society_support.py``).
        """
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
                    profile=profile,
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
                if engine.state_family == "living" and engine.saved_world != (
                    initial_input["profile"] in LIVING_INPUTS
                ):
                    # A living engine that stands on a saved world walks the living place a
                    # town's input carries; one that does not reads a district's input. Any other
                    # pairing is refused by name, whichever engine a caller names.
                    raise SocietyStartRefused("engine_not_for_this_ground")
                self._validate_scope(version_id, initial_input)
                self._authorize(initial_input)
                # A saved world's own ground holds the population its entry in the society ground
                # catalog states or derives by its rule, found by the navigation profile its
                # input records; a district, its full population.
                population = (
                    society_population(initial_input)
                    if is_authored_ground(initial_input["profile"])
                    else SOCIETY_POPULATION
                )
                if engine.state_family == "living":
                    routine = input_routine(initial_input)
                    [place] = living_places([initial_input], routine)
                    state = initial_living_society(
                        society_id,
                        seed,
                        place,
                        routine,
                        branch_id=str(version_id),
                        # A town's people are its homes' residents, bounded by its ground's rule;
                        # a district's population is sized to its place.
                        population=(
                            population if is_authored_ground(initial_input["profile"]) else None
                        ),
                        profile=profile,
                    )
                elif engine.state_family == "things":
                    # A society of things reads the things composition and no other.
                    if initial_input["profile"] not in THING_INPUTS:
                        raise SocietyStartRefused("engine_not_for_this_ground")
                    state = initial_things_society(
                        society_id, seed, initial_input, population=population
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
            if engine.state_family == "living":
                population = state["population"]["size"]
            elif engine.state_family == "things":
                # The people its ground's population brings: the beings its author placed are its
                # things, which every replay places again from the first input.
                population = sum(
                    1 for person in state["inhabitants"] if person["came_by"] == "populated"
                )
            else:
                population = len(state["inhabitants"])
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
        self,
        version_id: uuid.UUID,
        *,
        base_tick: int,
        base_state_sha256: str,
        base_clock_revision: int | None = None,
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
            # A coupled world's minute waits while its society leads sealed traffic by the clock's
            # lead; a legacy world has no clock row and runs as it always has.
            clocks = WorldClockRepository(self.connection, self.workspace_id, self.world_id)
            clocks.check_revision(version_id, base_clock_revision)
            clock = clocks.before_minute(version_id, row["current_tick"])
            ahead.enter_context(inputs_ahead(self.connection, self.named_inputs(row)))
            engine = society_engine(row["engine_version"])
            places = None
            crossed: tuple[BoundCrossing, ...] = ()
            if engine.state_family == "legacy":
                state, events = advance_society(row["state"], row["seed"])
            elif engine.state_family == "living":
                inputs = self._pending_inputs(row)
                self._authorize(inputs[-1])
                routine = routine_for(row["state"])
                # The choices of every role this engine hosts are receipts asked before this
                # minute, applied through the living seam; with none, the rule decides for all.
                roles = decision_roles().hosted_by(row["engine_version"])
                receipts = (
                    self._decisions(row, after=self._consumed_decisions(row))
                    if engine.owner_model_choice
                    else []
                )
                places = living_places(inputs, routine)
                seam, decided = apply_receipts(
                    roles,
                    row["state"],
                    inputs[-1],
                    receipts,
                    LivingSeam(row["seed"], places, routine),
                )
                state, events = living_step(row["state"], row["seed"], seam)
                events = append_role_events(
                    roles, row["state"], state, inputs[-1], receipts, decided, events
                )
                processed = [(d.decision_seq, d.disposition) for d in decided]
            elif engine.state_family in ("purposeful", "things"):
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
                    # The model decisions of every role this engine hosts are receipts asked
                    # before this minute; with none, the policies are the direct requests' alone
                    # and nothing is added.
                    roles = decision_roles().hosted_by(row["engine_version"])
                    receipts = self._decisions(row, after=self._consumed_decisions(row))
                    policies, decided = apply_receipts(
                        roles, row["state"], inputs[-1], receipts, goal_policy
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
                if engine.owner_model_choice:
                    events = append_role_events(
                        roles, row["state"], state, inputs[-1], receipts, decided, events
                    )
                if engine.state_family == "things":
                    # Placed beings as the latest input places them, then the crossings the door
                    # handed over and no minute has consumed, in the order it wrote them, at most
                    # a minute's worth: the rest wait for later minutes.
                    stream = crossing_stream()
                    pending = (
                        ()
                        if stream is None
                        else tuple(
                            stream.pending(
                                self.connection,
                                self.workspace_id,
                                row["society_id"],
                                state["tick"],
                                limit=CROSSINGS_PER_MINUTE,
                            )
                        )[:CROSSINGS_PER_MINUTE]
                    )
                    state, events, crossed = advance_things(
                        row["state"],
                        state,
                        row["seed"],
                        inputs[-1],
                        events,
                        pending,
                        decisions=_consumed(receipts, decided),
                    )
            else:
                raise UnknownSocietyEngine(f"unsupported society engine {row['engine_version']!r}")
            digest = self._record(row, state, events)
            if clock is not None:
                clocks.after_minute(
                    clock,
                    before=row["state"],
                    after=state,
                    previous_state_sha256=row["state_sha256"],
                    state_sha256=digest,
                    events=[event.document for event in events],
                    places=None if places is None else [place.document for place in places],
                )
            if engine.takes_inputs:
                if engine.model_decisions:
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
                if engine.directed_actions:
                    action_repository.bind(
                        version_id,
                        tick=state["tick"],
                        dispositions=action_dispositions,
                        events=events,
                    )
            if crossed:
                # Each crossing bound once, to the event this minute recorded for it.
                stream = crossing_stream()
                assert stream is not None
                stream.bind(
                    self.connection, self.workspace_id, row["society_id"], state["tick"], crossed
                )
            return self.snapshot(version_id)

    def _record(self, row: dict, state: dict[str, Any], events: tuple[SocietyEvent, ...]) -> str:
        """Commit one minute: the new state, its events and, for an input engine, its receipt.
        Answers the new state's digest."""
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
        return digest

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
            # A presence minute is a minute of a coupled world's clock like any other.
            clocks = WorldClockRepository(self.connection, self.workspace_id, self.world_id)
            clock = clocks.before_minute(version_id, row["current_tick"])
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
            digest = self._record(row, state, events)
            if clock is not None:
                clocks.after_minute(
                    clock,
                    before=row["state"],
                    after=state,
                    previous_state_sha256=row["state_sha256"],
                    state_sha256=digest,
                    events=[event.document for event in events],
                    places=None,
                )
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

    def input_provenance(self, version_id: uuid.UUID, input_seq: int) -> dict[str, Any]:
        """One stored input's identity and the authored state it followed, never the input itself.

        Authorized as :meth:`events` authorizes the inputs it shows: the society's current rights
        first (:meth:`snapshot`), then this input's own. ``authored_state`` is the input's own
        record of the version's ``edit_seq`` and state digest (``delta_sha256``), which names the
        edit it followed in the version's history, or None for an input that records none. A
        society that takes no inputs, or a sequence its chain does not hold, is
        :class:`UnknownSociety`.
        """
        self.snapshot(version_id)
        row = self._row(version_id)
        if row is None or row["engine_version"] not in INPUT_PROFILES:
            raise UnknownSociety("society input is unavailable")
        if not 1 <= input_seq <= self._chain(row):
            raise UnknownSociety("society input is unavailable")
        document = self._inputs(row, [input_seq])[input_seq]
        self._authorize(document)
        authored = document.get("authored_state")
        return {
            "version_id": str(version_id),
            "society_id": str(row["society_id"]),
            "input_seq": input_seq,
            "input_sha256": document["document_sha256"],
            "input_profile": document["profile"],
            "authored_state": None
            if authored is None
            else {"edit_seq": authored["edit_seq"], "delta_sha256": authored["delta_sha256"]},
        }

    def events(self, version_id: uuid.UUID, *, limit: int = 256) -> tuple[dict[str, Any], ...]:
        return self.events_page(version_id, limit=limit)[0]

    def events_page(
        self, version_id: uuid.UUID, *, limit: int = EVENTS_READ_MAXIMUM, before: str | None = None
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        """A page of the society's events, newest first, and the cursor that reads on from it.

        The order is the one every events read has: tick, newest first, then the order the
        engine gave events within a tick, then id. ``before`` is a cursor a previous page gave
        (:func:`event_cursor`); the page holds the events after it in that order. The cursor that
        comes back is None when no older event is left. The inputs of the events a page shows are
        authorized before it is answered, as the first page's are.
        """
        self.snapshot(version_id)  # Current authorization applies to event materialization too.
        row = self._row(version_id)
        bound = max(1, min(limit, EVENTS_READ_MAXIMUM))
        after = ""
        values: dict[str, Any] = {
            "workspace": self.workspace_id,
            "society": row["society_id"],
            "rows": bound + 1,
        }
        if before is not None:
            tick, order, event_id = _cursor_parts(before)
            named = self.connection.execute(
                "select 1 from world_society_event where workspace_id=%s and society_id=%s "
                "and event_id=%s and tick=%s "
                "and (document->>'order')::integer is not distinct from %s::integer",
                (self.workspace_id, row["society_id"], event_id, tick, order),
            ).fetchone()
            if named is None:
                raise InvalidEventCursor("the cursor names no event of this society")
            values |= {"tick": tick, "order": order, "event": event_id}
            after = (
                " and (tick<%(tick)s or (tick=%(tick)s and ("
                "(%(order)s::integer is not null and ((document->>'order')::integer>%(order)s "
                "or document->>'order' is null or ((document->>'order')::integer=%(order)s "
                "and event_id>%(event)s))) "
                "or (%(order)s::integer is null and document->>'order' is null "
                "and event_id>%(event)s))))"
            )
        rows = self.connection.execute(
            "select "
            "event_id,tick,event_kind,subject_id,object_id,place_id,document,document_sha256,"
            "recorded_at from world_society_event "
            "where workspace_id=%(workspace)s and society_id=%(society)s"
            + after
            + " order by tick desc, (document->>'order')::integer nulls last,event_id "
            "limit %(rows)s",
            values,
        ).fetchall()
        page, more = rows[:bound], len(rows) > bound
        if row["engine_version"] in INPUT_PROFILES:
            shown = {value["document"]["input_seq"] for value in page}
            documents = self._inputs(row, shown)
            for sequence in sorted(shown):
                self._authorize(documents[sequence])
        events = tuple(dict(value) for value in page)
        return events, event_cursor(events[-1]) if more else None

    def replay(self, version_id: uuid.UUID) -> dict[str, Any]:
        # Hold the same lock as advances so state, inputs, and transitions cannot straddle a tick.
        with self.connection.transaction():
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            expected_events: list[SocietyEvent] = []
            engine = society_engine(row["engine_version"])
            if engine.state_family == "legacy":
                state = initial_society(
                    row["society_id"], row["seed"], population=row["population_size"]
                )
                for _ in range(row["current_tick"]):
                    state, events = advance_society(state, row["seed"])
                    expected_events.extend(events)
            elif engine.state_family == "living":
                state, expected_events = self._replay_living(row)
            elif engine.state_family in ("purposeful", "things"):
                documents = self._validated_inputs(row)
                with inputs_ahead(self.connection, documents):
                    for document in documents:
                        self._authorize(document)
                actions = self._actions(row, documents)
                initializer = (
                    initial_social_society
                    if row["engine_version"] == SOCIAL_PROFILE
                    else initial_things_society
                    if engine.state_family == "things"
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
                # The crossings each minute consumed, as the door bound them, by minute.
                consumed: dict[int, list[Any]] = {}
                stream = crossing_stream()
                if engine.state_family == "things" and stream is None:
                    took = self.connection.execute(
                        "select 1 from world_society_event where workspace_id=%s "
                        "and society_id=%s and document->'thing' ? 'crossing_id' limit 1",
                        (self.workspace_id, row["society_id"]),
                    ).fetchone()
                    if took is not None:
                        raise ValueError(
                            "a society that took crossings replays only with its door's stream "
                            "registered"
                        )
                if engine.state_family == "things" and stream is not None:
                    for taken in stream.consumed(
                        self.connection, self.workspace_id, row["society_id"]
                    ):
                        consumed.setdefault(taken.tick, []).append(taken)
                # Replayed from what was stored and bound, never asked again.
                roles = decision_roles().hosted_by(row["engine_version"])
                role_decisions, role_bindings = (
                    ({d["decision_seq"]: d for d in self._decisions(row)}, self._bindings(row))
                    if engine.owner_model_choice
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
                        bindings = role_bindings.get(transition["tick"], [])
                        receipts = [role_decisions[b["decision_seq"]] for b in bindings]
                        policies, decided = apply_receipts(
                            roles, state, inputs[-1], receipts, goal_policy
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
                    if engine.owner_model_choice:
                        events = append_role_events(
                            roles, previous_state, state, inputs[-1], receipts, decided, events
                        )
                    if engine.state_family == "things":
                        taken = consumed.pop(transition["tick"], [])
                        state, events, crossed = advance_things(
                            previous_state,
                            state,
                            row["seed"],
                            inputs[-1],
                            events,
                            [each.crossing for each in taken],
                            decisions=_consumed(receipts, decided),
                        )
                        if list(crossed) != [each.bound for each in taken]:
                            raise ValueError("society crossing replay mismatch")
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
                if consumed:
                    raise ValueError("a crossing is bound to a minute the society never ran")
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

    def replay_living_minutes(
        self,
        version_id: uuid.UUID,
        observe: Callable[[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict]], None],
    ) -> dict[str, Any]:
        """Replay a living society as :meth:`replay` does, under the same lock, handing ``observe``
        each regenerated minute: the state before it, the state after it, its event documents and
        the place documents it read. Asks no model. Answers the replayed state's digest."""
        with self.connection.transaction():
            self._lock()
            row = self._row(version_id, lock=True)
            if row is None:
                raise UnknownSociety("society is unavailable")
            if society_engine(row["engine_version"]).state_family != "living":
                raise ValueError("only a living society's minutes are replayed with their places")
            state, _events = self._replay_living(row, observe)
            digest = society_state_sha256(state)
            if digest != row["state_sha256"]:
                raise ValueError("society replay final state mismatch")
            return {"tick": state["tick"], "state_sha256": digest}

    def _replay_living(
        self,
        row: dict[str, Any],
        observe: Callable[[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict]], None]
        | None = None,
    ) -> tuple[dict[str, Any], list[SocietyEvent]]:
        """Regenerate a living society from genesis over every retained input, transition and,
        for an engine whose owner may choose models, every receipt each minute consumed: asked
        again of nothing, and held to the dispositions the minutes recorded."""
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
            profile=row["engine_version"],
        )
        engine = society_engine(row["engine_version"])
        roles = decision_roles().hosted_by(row["engine_version"])
        role_decisions, role_bindings = (
            ({d["decision_seq"]: d for d in self._decisions(row)}, self._bindings(row))
            if engine.owner_model_choice
            else ({}, {})
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
            bindings = role_bindings.get(transition["tick"], [])
            receipts = [role_decisions[b["decision_seq"]] for b in bindings]
            previous_state = state
            places = living_places(inputs, routine, held)
            seam, decided = apply_receipts(
                roles,
                state,
                inputs[-1],
                receipts,
                LivingSeam(row["seed"], places, routine),
            )
            if [(d.decision_seq, d.disposition) for d in decided] != [
                (b["decision_seq"], b["disposition"]) for b in bindings
            ]:
                raise ValueError("person decision disposition replay mismatch")
            state, events = living_step(state, row["seed"], seam)
            events = append_role_events(
                roles, previous_state, state, inputs[-1], receipts, decided, events
            )
            if (
                transition["state_sha256"] != society_state_sha256(state)
                or transition["event_ids"] != [str(e.event_id) for e in events]
                or transition["events_sha256"]
                != society_state_sha256(ordered_events_document(events))
            ):
                raise ValueError("society transition replay mismatch")
            if observe is not None:
                observe(
                    previous_state,
                    state,
                    [event.document for event in events],
                    [place.document for place in places],
                )
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
        """The society as stored, seed included. A route serves it through
        :func:`~exulanica.world.society.served_snapshot`, which never carries the seed."""
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
