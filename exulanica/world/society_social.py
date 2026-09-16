"""Bounded synthetic observations, hearsay and decisions over deterministic v2 movement."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from exulanica.world.society import (
    SOCIETY_NAMESPACE,
    SOCIETY_POPULATION,
    SocietyEvent,
    society_state_sha256,
)
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    _graph,
    _paths,
    advance_purposeful_society,
    initial_purposeful_society,
    input_sha256,
    validate_society_input,
)

SOCIAL_PROFILE = "exulanica-society/v3"
SOCIAL_STATE_PROFILE = "exulanica.social-state/v1"
CONTEXT_PROFILE = "exulanica.society-decision-context/v1"
OBSERVATION_DISTANCE_MM = 4000
COMMUNICATION_DISTANCE_MM = 8000
MEMORY_LIMIT = 16
CAST_SIZE = 3


def initial_social_society(
    society_id: uuid.UUID, seed: str, document: dict, *, population: int = SOCIETY_POPULATION
) -> dict:
    state = initial_purposeful_society(society_id, seed, document, population=population)
    cast = [p["id"] for p in state["inhabitants"][:CAST_SIZE]]
    state["profile"] = SOCIAL_PROFILE
    state["social"] = {
        "profile": SOCIAL_STATE_PROFILE,
        "cast_ids": cast,
        "last_decision_seq": 0,
        "agents": {
            key: {"observations": [], "beliefs": {}, "communication_ids": []} for key in cast
        },
    }
    return state


def validate_social_state(state: dict) -> None:
    social = state.get("social", {})
    if state.get("profile") != SOCIAL_PROFILE or social.get("profile") != SOCIAL_STATE_PROFILE:
        raise ValueError("unsupported social state")
    cast = social.get("cast_ids", [])
    if cast != [p["id"] for p in state["inhabitants"][:CAST_SIZE]] or set(social["agents"]) != set(
        cast
    ):
        raise ValueError("social cast identity mismatch")
    if type(social["last_decision_seq"]) is not int or social["last_decision_seq"] < 0:
        raise ValueError("invalid social decision cursor")
    for agent in social["agents"].values():
        if set(agent) != {"observations", "beliefs", "communication_ids"}:
            raise ValueError("invalid social agent fields")
        if any(len(agent[key]) > MEMORY_LIMIT for key in agent):
            raise ValueError("social memory exceeds bound")


def _agent(state: dict, subject_id: str) -> tuple[dict, dict]:
    validate_social_state(state)
    if subject_id not in state["social"]["agents"]:
        raise ValueError("subject is not in the bounded social cast")
    return next(p for p in state["inhabitants"] if p["id"] == subject_id), state["social"][
        "agents"
    ][subject_id]


def decision_context(state: dict, document: dict, subject_id: str) -> dict:
    """Only this agent's records; remembered claims do not imply current world truth."""
    person, agent = _agent(state, subject_id)
    validate_society_input(document)
    if (
        document["input_seq"] != state["input_seq"]
        or document["document_sha256"] != state["input_sha256"]
    ):
        raise ValueError("advance queued inputs before requesting a social decision")
    return {
        "profile": CONTEXT_PROFILE,
        "subject_id": subject_id,
        "branch_id": state["branch_id"],
        "tick": state["tick"],
        "position_mm": list(person["position_mm"]),
        "can_choose_goal": person["goal"] is None
        or person["action"]["status"] in ("completed", "blocked"),
        "own_beliefs": [deepcopy(agent["beliefs"][key]) for key in sorted(agent["beliefs"])],
        "own_observations": deepcopy(agent["observations"][-8:]),
        "current_goal": deepcopy(person["goal"]),
        "allowed_actions": ["choose_goal", "wait"],
    }


def validate_proposal(context: dict, document: dict, proposal: Any) -> str | None:
    if not isinstance(proposal, dict) or set(proposal) != {"kind", "target_id"}:
        return "invalid_proposal_fields"
    if not context["can_choose_goal"]:
        return "action_in_progress"
    if proposal["kind"] == "wait":
        return None if proposal["target_id"] is None else "wait_has_target"
    if proposal["kind"] != "choose_goal" or not isinstance(proposal["target_id"], str):
        return "unsupported_proposal"
    belief = next(
        (
            b
            for b in context["own_beliefs"]
            if b["target"]["target_id"] == proposal["target_id"] and b["available"]
        ),
        None,
    )
    if belief is None:
        return "target_not_known_to_agent"
    target = next(
        (
            t
            for t in document["targets"]
            if t["target_id"] == proposal["target_id"] and t["enabled"]
        ),
        None,
    )
    if target is None or target != belief["target"]:
        return "remembered_affordance_changed"
    nodes, adjacent, _ = _graph(document)
    starts = [key for key, node in nodes.items() if node["position_mm"] == context["position_mm"]]
    if not starts or target["node_id"] not in _paths(starts[0], adjacent):
        return "known_target_unreachable"
    return None


def _trim_beliefs(agent: dict) -> None:
    ordered = sorted(agent["beliefs"], key=lambda key: (agent["beliefs"][key]["learned_tick"], key))
    for key in ordered[:-MEMORY_LIMIT]:
        del agent["beliefs"][key]


def advance_social_society(
    state: dict,
    seed: str,
    inputs: list[dict],
    decisions: list[dict] | None = None,
    *,
    external_goal_policy: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict, tuple[SocietyEvent, ...], list[tuple[int, str]]]:
    validate_social_state(state)
    prior_hash = society_state_sha256(state)
    social = deepcopy(state["social"])
    people = {p["id"]: p for p in state["inhabitants"]}
    tick = state["tick"] + 1
    specs: list[tuple[str, str, str, dict, dict]] = []
    policies = {}
    processed = []
    latest = inputs[-1]
    for key in social["cast_ids"]:
        policies[key] = {"allowed_target_ids": []}
    applied = set()
    for receipt in decisions or []:
        if receipt["document_sha256"] != input_sha256(receipt):
            raise ValueError("social decision digest mismatch")
        if receipt["decision_seq"] != social["last_decision_seq"] + 1:
            raise ValueError("social decision sequence gap")
        social["last_decision_seq"] = receipt["decision_seq"]
        subject = receipt["subject_id"]
        if subject not in social["agents"] or receipt["branch_id"] != state["branch_id"]:
            raise ValueError("social decision scope mismatch")
        disposition = receipt["status"]
        reason = receipt["reason"]
        if disposition == "accepted":
            if (
                receipt["base_tick"] != state["tick"]
                or receipt["base_state_sha256"] != prior_hash
                or receipt["input_sha256"] != latest["document_sha256"]
            ):
                disposition, reason = "stale", "decision_context_changed"
            elif subject in applied:
                disposition, reason = "superseded", "subject_already_decided"
            else:
                context = decision_context(state, inputs[0], subject)
                if society_state_sha256(context) != receipt["context_sha256"]:
                    raise ValueError("decision agent context mismatch")
                rejection = validate_proposal(context, latest, receipt["proposal"])
                if rejection:
                    disposition, reason = "rejected", rejection
                else:
                    disposition, reason = "applied", "validated_remembered_choice"
                    applied.add(subject)
                    proposal = receipt["proposal"]
                    policies[subject].update(
                        preferred_target_id=proposal["target_id"], wait=proposal["kind"] == "wait"
                    )
        processed.append((receipt["decision_seq"], disposition))
        specs.append(
            (
                subject,
                "decision_applied",
                reason,
                latest,
                {
                    "decision_seq": receipt["decision_seq"],
                    "request_id": receipt["request_id"],
                    "decision_sha256": receipt["document_sha256"],
                    "disposition": disposition,
                },
            )
        )

    # Only stopped agents at existing graph nodes observe or communicate. These are proximity
    # observations along the reviewed graph, not claims of recovered line-of-sight perception.
    visible_inputs = (
        inputs
        if latest["availability"] == "available" and not latest["navigation"]["unavailable_reason"]
        else []
    )
    for doc in visible_inputs:
        if doc["availability"] != "available" or doc["navigation"]["unavailable_reason"]:
            continue
        nodes, adjacent, _ = _graph(doc)
        authored = {t["target_id"]: t for t in doc["targets"] if t["origin"] == "authored"}
        for key in social["cast_ids"]:
            person, agent = people[key], social["agents"][key]
            node = person["location"]["node_id"]
            if person["location"]["edge"] is not None or node not in nodes:
                continue
            paths = _paths(node, adjacent)
            candidates = dict(authored)
            for name, belief in agent["beliefs"].items():
                candidates.setdefault(name, belief["target"])
            for name, target in sorted(candidates.items()):
                old = agent["beliefs"].get(name)
                if (
                    target["node_id"] not in paths
                    or paths[target["node_id"]][0] > OBSERVATION_DISTANCE_MM
                ):
                    # A local witness can notice a vacated remembered location without
                    # learning the object's new, distant location from global input.
                    if (
                        old is None
                        or old["target"]["node_id"] not in paths
                        or paths[old["target"]["node_id"]][0] > OBSERVATION_DISTANCE_MM
                    ):
                        continue
                    target = old["target"]
                available = name in authored and authored[name] == target and target["enabled"]
                if (
                    old
                    and old["origin"] == "observation"
                    and old["target"] == target
                    and old["available"] == available
                ):
                    continue
                fact = {
                    "fact_id": str(
                        uuid.uuid5(
                            SOCIETY_NAMESPACE,
                            f"{state['society_id']}:{key}:{tick}:{doc['input_seq']}:{name}:{available}:{society_state_sha256(target)}",
                        )
                    ),
                    "observer_id": key,
                    "observed_tick": tick,
                    "input_seq": doc["input_seq"],
                    "input_sha256": doc["document_sha256"],
                    "target": deepcopy(target),
                    "available": available,
                }
                agent["observations"] = [*agent["observations"], fact][-MEMORY_LIMIT:]
                agent["beliefs"][name] = {
                    "origin": "observation",
                    "source_subject_id": key,
                    "source_fact_id": fact["fact_id"],
                    "communication_id": None,
                    "input_seq": fact["input_seq"],
                    "input_sha256": fact["input_sha256"],
                    "learned_tick": tick,
                    "target": deepcopy(target),
                    "available": available,
                }
                _trim_beliefs(agent)
                specs.append(
                    (key, "observed", "local_affordance_observation", doc, {"observation": fact})
                )

    if latest["availability"] == "available" and not latest["navigation"]["unavailable_reason"]:
        nodes, adjacent, _ = _graph(latest)
        senders = deepcopy(social["agents"])
        for sender in social["cast_ids"]:
            person = people[sender]
            if person["location"]["edge"] is not None or person["location"]["node_id"] not in nodes:
                continue
            paths = _paths(person["location"]["node_id"], adjacent)
            sent = False
            for receiver in social["cast_ids"]:
                other = people[receiver]
                node = other["location"]["node_id"]
                if (
                    sender == receiver
                    or other["location"]["edge"] is not None
                    or node not in paths
                    or paths[node][0] > COMMUNICATION_DISTANCE_MM
                ):
                    continue
                for name, belief in sorted(senders[sender]["beliefs"].items()):
                    old = social["agents"][receiver]["beliefs"].get(name)
                    if belief["learned_tick"] >= tick or (
                        old and old["source_fact_id"] == belief["source_fact_id"]
                    ):
                        continue
                    # A direct observation is not silently overwritten by older hearsay.
                    if old and old["input_seq"] >= belief["input_seq"]:
                        continue
                    communication_id = str(
                        uuid.uuid5(
                            SOCIETY_NAMESPACE,
                            f"{state['society_id']}:{tick}:{sender}:{receiver}:{belief['source_fact_id']}",
                        )
                    )
                    learned = {
                        **deepcopy(belief),
                        "origin": "communication",
                        "source_subject_id": sender,
                        "communication_id": communication_id,
                        "learned_tick": tick,
                    }
                    target_agent = social["agents"][receiver]
                    target_agent["beliefs"][name] = learned
                    _trim_beliefs(target_agent)
                    for agent_id in (sender, receiver):
                        agent = social["agents"][agent_id]
                        agent["communication_ids"] = [
                            *agent["communication_ids"],
                            communication_id,
                        ][-MEMORY_LIMIT:]
                    specs.append(
                        (
                            receiver,
                            "communicated",
                            "learned_from_nearby_inhabitant",
                            latest,
                            {
                                "communication_id": communication_id,
                                "sender_id": sender,
                                "receiver_id": receiver,
                                "belief": learned,
                                "dialogue": None,
                            },
                        )
                    )
                    sent = True
                    break
                if sent:
                    break

    if latest["availability"] != "available" or latest["navigation"]["unavailable_reason"]:
        # Do not materialize remembered source claims through an authorized unavailable pause.
        social["agents"] = {
            key: {"observations": [], "beliefs": {}, "communication_ids": []}
            for key in social["cast_ids"]
        }
    for key, policy in policies.items():
        known = social["agents"][key]["beliefs"]
        policy["allowed_target_ids"] = [
            t["target_id"]
            for t in latest["targets"]
            if t["origin"] == "district"
            or (
                t["target_id"] in known
                and known[t["target_id"]]["available"]
                and known[t["target_id"]]["target"] == t
            )
        ]
    people_by_id = {person["id"]: person for person in state["inhabitants"]}
    current_targets = {
        target["target_id"]: target for target in latest["targets"] if target["enabled"] is True
    }
    for subject, policy in (external_goal_policy or {}).items():
        if subject not in people_by_id or set(policy) != {
            "allowed_target_ids",
            "preferred_target_id",
        }:
            raise ValueError("invalid external society goal policy")
        allowed = policy["allowed_target_ids"]
        preferred = policy["preferred_target_id"]
        if (
            not isinstance(allowed, list)
            or len(allowed) != 1
            or not isinstance(preferred, str)
            or allowed[0] != preferred
            or preferred not in current_targets
        ):
            raise ValueError("external society goal policy must select one enabled current target")
        # This seam chooses only a canonical target. The v2 engine below remains authoritative
        # for availability, graph, route, current-action and movement preconditions.
        policies[subject] = deepcopy(policy)
    navigation_state = deepcopy(state)
    navigation_state.pop("social")
    navigation_state["profile"] = PURPOSEFUL_PROFILE
    result, movements = advance_purposeful_society(
        navigation_state, seed, inputs, goal_policy=policies
    )
    result["profile"] = SOCIAL_PROFILE
    result["social"] = social
    events = []
    ids = {}
    result_people = {p["id"]: p for p in result["inhabitants"]}
    for subject, kind, reason, doc, details in specs:
        person = (
            result_people[subject]
            if latest["availability"] != "available" or latest["navigation"]["unavailable_reason"]
            else people[subject]
        )
        document = {
            "summary": f"{person['display_name']} (simulated): {reason.replace('_', ' ')}.",
            "synthetic": True,
            "profile": SOCIAL_PROFILE,
            "branch_id": state["branch_id"],
            "subject_id": subject,
            "tick": tick,
            "order": len(events),
            "input_seq": doc["input_seq"],
            "input_sha256": doc["document_sha256"],
            "target": None,
            "reason": reason,
            "outcome": kind,
            "goal": deepcopy(person["goal"]),
            "action": deepcopy(person["action"]),
            "position_mm": list(person["position_mm"]),
            "motion_path_mm": [list(person["position_mm"])],
            "previous_state_sha256": prior_hash,
            "seed_sha256": seed,
            **details,
        }
        event_id = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{state['society_id']}:{tick}:{len(events)}:{society_state_sha256(document)}",
        )
        events.append(SocietyEvent(event_id, tick, kind, uuid.UUID(subject), None, document))
    for event in movements:
        document = deepcopy(event.document)
        document.update(profile=SOCIAL_PROFILE, previous_state_sha256=prior_hash, order=len(events))
        event_id = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{state['society_id']}:{tick}:{len(events)}:{society_state_sha256(document)}",
        )
        ids[str(event.event_id)] = str(event_id)
        events.append(
            SocietyEvent(event_id, tick, event.kind, event.subject_id, event.object_id, document)
        )
    for person in result_people.values():
        person["memory"] = [ids.get(key, key) for key in person["memory"]]
        own = [e for e in events if str(e.subject_id) == person["id"]]
        if own:
            person["memory"] = list(
                dict.fromkeys([*person["memory"], *(str(e.event_id) for e in own)])
            )[-16:]
            person["explanation"] = {
                "summary": own[-1].document["summary"],
                "event_ids": [str(own[-1].event_id)],
            }
    validate_social_state(result)
    return result, tuple(events), processed
