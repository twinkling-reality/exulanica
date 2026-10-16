"""A stored society replayed from its inputs and records.

A part of :class:`~exulanica.world.society_repository.SocietyRepository` (its methods read the
repository's connection and workspace and reach its lock, authorization and stored rows through
``self``): a society's minutes run again from its recorded inputs, the living minutes among them,
and the stored events, bindings, actions and presences checked against what the replay makes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from exulanica.world.crossings import crossing_stream
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import (
    append_role_events,
    apply_receipts,
    consumed_receipts,
)
from exulanica.world.society import (
    SocietyEvent,
    UnknownSociety,
    event_document_sha256,
    inputs_ahead,
    society_state_sha256,
)
from exulanica.world.society_actions import (
    action_goal_policies,
    append_action_events,
    applied_hands,
    validate_action_request,
)
from exulanica.world.society_engines import (
    UnknownSocietyEngine,
    society_engine,
)
from exulanica.world.society_legacy import advance_society, initial_society
from exulanica.world.society_living import (
    initial_living_society,
    living_places,
    routine_for,
)
from exulanica.world.society_living_decisions import LivingSeam, living_step
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
)
from exulanica.world.society_presence import (
    change_presence,
    validate_presence_request,
)
from exulanica.world.society_social import (
    SOCIAL_PROFILE,
    advance_social_society,
    initial_social_society,
)
from exulanica.world.society_things import advance_things, initial_things_society

#: Profiles that consume authorized inputs and record transition receipts, from the engine table.


class SocietyReplay:
    """The replay of :class:`~exulanica.world.society_repository.SocietyRepository`."""

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
                            decisions=consumed_receipts(receipts, decided),
                            asked=applied_hands(requests, action_dispositions),
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
