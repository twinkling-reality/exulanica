"""Typed user requests over canonical society targets, never browser-space movement.

A request is the world owner asking one of a society's people to do one thing at its next minute:
to walk to a target its consumed input lists, or to do the target's activity there
(``exulanica.society-action-request/v1``, ``go_to`` and ``perform``); or, in a society of things
running the hands module, to pick a thing up, put it down, give it or take it
(``exulanica.society-action-request/v2``, intent ``hands``). A v2 request is read beside v1 and
names no input target: its act is checked against the hands acts the being is offered on the
state the minute starts from, over the whole approach distance, and the minute walks the being to
stand within reach as a decider's chosen act does. An applied request comes before the being's
decider's answer for that minute, which is set aside (``person_asked_directly``).
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.society import SOCIETY_NAMESPACE, SocietyEvent, society_state_sha256
from exulanica.world.society_engines import ACTION_ENGINES
from exulanica.world.society_planner import (
    PLACE_INPUTS,
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    ends_on_request,
    held_nodes,
    input_graph,
    routine_of,
    routine_withheld,
    supports,
    validate_society_input,
)

ACTION_REQUEST_PROFILE: Final = "exulanica.society-action-request/v1"
#: A request for a hands act, read beside v1: v1's fields without ``target``.
HANDS_REQUEST_PROFILE: Final = "exulanica.society-action-request/v2"
ACTION_EVENT_KIND: Final = "user_action_requested"
ActionKind = Literal["go_to", "perform", "hands"]
ActionDispositionKind = Literal["applied", "stale", "unavailable", "rejected", "superseded"]
#: The hands acts a person may ask a being for, as the hands module names them.
HANDS_ABILITIES: Final = ("pick_up", "put_down", "give", "take")
#: The acts that hand a thing to, or take it from, another being, who the request names.
_WITH_ANOTHER: Final = frozenset({"give", "take"})


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """What a request asks: ``go_to`` or ``perform`` a target, or a ``hands`` act, whose
    ``target_id`` is the thing and ``with_id`` the other being it is given to or taken from."""

    kind: ActionKind
    target_id: str
    affordance: str | None = None
    ability: str | None = None
    with_id: str | None = None

    def document(self) -> dict[str, Any]:
        """The intent as the request records it."""
        if self.kind == "hands":
            return {
                "kind": "hands",
                "ability": self.ability,
                "thing_id": self.target_id,
                "with_id": self.with_id,
            }
        return {
            "kind": self.kind,
            "target_id": self.target_id,
            **({"affordance": self.affordance} if self.kind == "perform" else {}),
        }


@dataclass(frozen=True, slots=True)
class ActionDisposition:
    request_id: uuid.UUID
    subject_id: uuid.UUID
    disposition: ActionDispositionKind
    reason: str


#: Every name a directed request is refused or found stale by, stated once: the page has words for
#: exactly these (``REFUSAL_WORDS`` in web/packages/app/src/ui/society-directed-action.ts, held to
#: this set by code-words-parity.test.ts), and tests/test_society_action_refusals.py fails when
#: ``_request_reason`` returns a name outside it.
ACTION_REFUSALS: Final = frozenset(
    {
        "action_context_changed",
        "activity_not_offered",
        "canonical_target_changed",
        "destination_full",
        "decided_from_outside",
        "inhabitant_action_in_progress",
        "inhabitant_already_there",
        "target_unreachable",
        "unknown_inhabitant",
        # A hands act: not offered to the being now, its thing or other being gone, no open
        # place within reach of it to walk to, or a thing a visitor here brought, which only that
        # visitor may hand over.
        "act_not_offered",
        "thing_gone",
        "out_of_reach",
        "belongs_to_visitor",
    }
)


class UnknownAffordance(ValueError):
    """A perform request naming an activity at an object the society's recorded routine does not
    offer. Standing and talking happen at no object, so nobody is directed to perform them."""

    code: Final = "unknown_affordance"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _uuid(value: Any, name: str) -> str:
    _require(isinstance(value, str), f"invalid {name}")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    _require(parsed == value, f"invalid {name}")
    return parsed


def _digest(value: Any, name: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"invalid {name}",
    )
    return value


def action_request_sha256(document: dict[str, Any]) -> str:
    return society_state_sha256(
        {key: value for key, value in document.items() if key != "document_sha256"}
    )


def validate_action_request(document: dict[str, Any]) -> None:
    """Validate the immutable request envelope without treating it as current authority: a v1
    request for a target, or a v2 request for a hands act, which names no target."""
    hands = isinstance(document, dict) and document.get("profile") == HANDS_REQUEST_PROFILE
    fields = {
        "profile",
        "request_id",
        "requested_by",
        "subject_id",
        "branch_id",
        "base_tick",
        "base_state_sha256",
        "input_seq",
        "input_sha256",
        "intent",
        "document_sha256",
        *(() if hands else ("target",)),
    }
    _require(
        isinstance(document, dict) and set(document) == fields, "invalid action request fields"
    )
    _require(
        document["profile"] in (ACTION_REQUEST_PROFILE, HANDS_REQUEST_PROFILE),
        "unsupported action request profile",
    )
    for key in ("request_id", "requested_by", "subject_id", "branch_id"):
        _uuid(document[key], key)
    _require(type(document["base_tick"]) is int and document["base_tick"] >= 0, "invalid base tick")
    _require(
        type(document["input_seq"]) is int and document["input_seq"] > 0, "invalid input sequence"
    )
    _digest(document["base_state_sha256"], "base state digest")
    _digest(document["input_sha256"], "input digest")
    _digest(document["document_sha256"], "action request digest")
    intent = document["intent"]
    _require(isinstance(intent, dict), "invalid action intent")
    kind = intent.get("kind")
    if hands:
        _require(
            set(intent) == {"kind", "ability", "thing_id", "with_id"} and kind == "hands",
            "invalid hands intent fields",
        )
        _require(intent["ability"] in HANDS_ABILITIES, "unsupported hands act")
        _require(
            isinstance(intent["thing_id"], str) and 0 < len(intent["thing_id"]) <= 1000,
            "invalid thing ID",
        )
        with_id = intent["with_id"]
        _require(
            (with_id is not None) == (intent["ability"] in _WITH_ANOTHER)
            and (with_id is None or (isinstance(with_id, str) and 0 < len(with_id) <= 1000))
            and with_id != document["subject_id"],
            "a hands act names another being exactly when it gives or takes",
        )
    else:
        if kind == "go_to":
            _require(set(intent) == {"kind", "target_id"}, "invalid go-to intent fields")
        elif kind == "perform":
            _require(
                set(intent) == {"kind", "target_id", "affordance"},
                "invalid perform intent fields",
            )
            _require(
                isinstance(intent["affordance"], str) and 0 < len(intent["affordance"]) <= 1000,
                "invalid requested affordance",
            )
        else:
            raise ValueError("unsupported action intent")
        _require(
            isinstance(intent["target_id"], str) and 0 < len(intent["target_id"]) <= 1000,
            "invalid target ID",
        )
        target = document["target"]
        _require(isinstance(target, dict), "invalid frozen action target")
        _require(target.get("target_id") == intent["target_id"], "action target binding mismatch")
        _require(target.get("version_id") == document["branch_id"], "cross-branch action target")
        _require(target.get("enabled") is True, "action target is not enabled")
        if kind == "perform":
            _require(target.get("affordance") == intent["affordance"], "action affordance changed")
    _require(
        action_request_sha256(document) == document["document_sha256"],
        "action request digest mismatch",
    )


def _people(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {person["id"]: person for person in state["inhabitants"]}


def _target(document: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    return next(
        (target for target in document["targets"] if target["target_id"] == target_id), None
    )


def _reachable(person: dict[str, Any], document: dict[str, Any], target: dict[str, Any]) -> bool:
    nodes = {node["node_id"] for node in document["navigation"]["nodes"]}
    adjacent = {node: [] for node in nodes}
    for edge in document["navigation"]["edges"]:
        adjacent[edge["from_node_id"]].append(edge["to_node_id"])
        adjacent[edge["to_node_id"]].append(edge["from_node_id"])
    location = person["location"]
    start = location["node_id"]
    if location["edge"] is not None:
        start = location["edge"]["to_node_id"]
    if start not in nodes or target["node_id"] not in nodes:
        return False
    pending = [start]
    visited = {start}
    while pending:
        node = pending.pop()
        for neighbor in adjacent[node]:
            if neighbor == target["node_id"]:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    return target["node_id"] in visited


def may_be_directed(person: dict[str, Any], document: dict[str, Any]) -> bool:
    """Whether a direct request may send ``person`` somewhere, under the input it is made against.

    Somebody who came in from outside never is: the program that sent them decides for them.
    Anybody else may be when nobody is doing anything, what they did is over or blocked, or it is a
    stay the request ends (``ends_on_request``: a stay under a routine that draws its stays). A
    walk is left to arrive. The database holds a recorded request to this same rule
    (``society_person_may_be_directed``, migrations 0108 and 0151), and
    tests/test_society_request_rule_parity.py holds the two equal.
    """
    return person.get("came_by") != "crossed" and (
        person["goal"] is None
        or person["action"]["status"] in ("completed", "blocked")
        or ends_on_request(routine_of(document), person)
    )


def _request_reason(
    state: dict[str, Any], document: dict[str, Any], request: dict[str, Any]
) -> tuple[ActionDispositionKind, str]:
    if (
        request["base_tick"] != state["tick"]
        or request["base_state_sha256"] != society_state_sha256(state)
        or request["input_seq"] != document["input_seq"]
        or request["input_sha256"] != document["document_sha256"]
    ):
        return "stale", "action_context_changed"
    if document["availability"] != "available" or document["navigation"]["unavailable_reason"]:
        return "unavailable", document["unavailable_reason"] or document["navigation"][
            "unavailable_reason"
        ]
    person = _people(state).get(request["subject_id"])
    if person is None:
        return "rejected", "unknown_inhabitant"
    if person.get("came_by") == "crossed":
        # Their own program decides for a visitor from outside, never a person's request.
        return "rejected", "decided_from_outside"
    if not may_be_directed(person, document):
        return "rejected", "inhabitant_action_in_progress"
    if request["profile"] == HANDS_REQUEST_PROFILE:
        return _hands_reason(state, document, person, request["intent"])
    if (
        ends_on_request(routine_of(document), person)
        and (person["target"] or {}).get("target_id") == request["intent"]["target_id"]
    ):
        # Asked to go where they already are, doing it now: there is nothing to end, and ending
        # it would only start the same stay again.
        return "rejected", "inhabitant_already_there"
    target = _target(document, request["intent"]["target_id"])
    if target is None or not target["enabled"] or target != request["target"]:
        return "stale", "canonical_target_changed"
    if target["affordance"] in routine_withheld(state, person):
        # A being whose kind does not list the activity never does it, asked or not.
        return "rejected", "activity_not_offered"
    if not _reachable(person, document, target):
        return "rejected", "target_unreachable"
    if document["profile"] in PLACE_INPUTS and all(
        place in held_nodes(state["inhabitants"], person, graph=input_graph(document))
        for place in target["place_node_ids"]
    ):
        # Every place at the destination is taken by somebody else, so there is no room to send
        # this person to; the request says so rather than leaving it standing in a queue.
        return "rejected", "destination_full"
    return "applied", "validated_user_target"


def _hands_reason(
    state: dict[str, Any],
    document: dict[str, Any],
    person: dict[str, Any],
    intent: dict[str, Any],
) -> tuple[ActionDispositionKind, str]:
    """Whether a hands act may be asked of ``person`` on the state the minute starts from: the
    society running the hands module, its thing and the other being here, no thing a visitor here
    brought picked up or taken, and the act among those the being is offered over the whole
    approach distance (walking first where it must). Read when the request is built and again by
    the minute that consumes it."""
    from exulanica.abilities.registry import recorded_row
    from exulanica.world.society_hands import acts_offered

    if recorded_row(state.get("modules", ()), "hands") is None:
        return "rejected", "act_not_offered"
    things = {thing["id"]: thing for thing in state.get("things", ())}
    here = {other["id"] for other in state["inhabitants"]}
    thing = things.get(intent["thing_id"])
    if thing is None or (intent["with_id"] is not None and intent["with_id"] not in here):
        return "rejected", "thing_gone"
    if intent["ability"] in ("pick_up", "take") and thing.get("brought_by") in here:
        # What a visitor brought goes home with it; only the visitor hands it over.
        return "rejected", "belongs_to_visitor"
    asked = (intent["ability"], intent["thing_id"], intent["with_id"])
    if not any(
        (offer.act.ability, offer.act.thing_id, offer.act.other_id) == asked
        for offer in acts_offered(state, document, person)
    ):
        return "rejected", "act_not_offered"
    return "applied", "validated_user_act"


def _hands_option(intent: dict[str, Any]) -> Any:
    """A hands request's act as the option the planner's hands goal policy reads."""
    from exulanica.world.society_decision_contract import DecisionOption

    return DecisionOption(
        label="",
        kind=str(intent["ability"]),
        action="hands",
        target_id=str(intent["thing_id"]),
        activity=None,
        walk_mm=None,
        addressee_id=intent["with_id"],
    )


def applied_hands(
    requests: list[dict[str, Any]], dispositions: tuple[ActionDisposition, ...]
) -> tuple[dict[str, Any], ...]:
    """The minute's applied hands requests, in request order, as its things phase takes them."""
    applied = {str(value.request_id) for value in dispositions if value.disposition == "applied"}
    return tuple(
        request
        for request in requests
        if request["profile"] == HANDS_REQUEST_PROFILE and request["request_id"] in applied
    )


def _promised_place(
    state: dict[str, Any],
    person: dict[str, Any],
    target: dict[str, Any],
    promised: set[str],
    graph: tuple[dict, dict],
) -> str | None:
    """The place a directed person takes: the one it stands at, else the first nobody holds.

    Positions are read against ``graph``, the input the step consumes: somebody an edit left
    standing where a place used to be stands at no place, and holds none against anybody else.
    """
    location = person["location"]
    if (
        location["edge"] is None
        and location["node_id"] in target["place_node_ids"]
        and supports(graph, person)
    ):
        return str(location["node_id"])
    held = held_nodes(state["inhabitants"], person, graph=graph) | promised
    return next((place for place in target["place_node_ids"] if place not in held), None)


def build_action_request(
    state: dict[str, Any],
    document: dict[str, Any],
    *,
    request_id: uuid.UUID,
    requested_by: uuid.UUID,
    subject_id: uuid.UUID,
    intent: ActionIntent,
) -> dict[str, Any]:
    """Resolve IDs to a frozen canonical target; clients never supply space or target records."""
    validate_society_input(document)
    _require(state.get("profile") in ACTION_ENGINES, "this society takes no user actions")
    _require(
        state.get("branch_id") == document["version_id"], "society input belongs to another branch"
    )
    _require(
        state.get("input_seq") == document["input_seq"]
        and state.get("input_sha256") == document["document_sha256"],
        "advance queued inputs before requesting an action",
    )
    common = {
        "request_id": str(request_id),
        "requested_by": str(requested_by),
        "subject_id": str(subject_id),
        "branch_id": state["branch_id"],
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "intent": intent.document(),
    }
    if intent.kind == "hands":
        request = {"profile": HANDS_REQUEST_PROFILE, **common}
        request["document_sha256"] = action_request_sha256(request)
        validate_action_request(request)
        disposition, reason = _request_reason(state, document, request)
        _require(disposition == "applied", reason)
        return request
    if intent.kind == "perform" and intent.affordance not in routine_of(document).affordances:
        raise UnknownAffordance(
            f"the routine this society records offers no activity at an object named "
            f"{intent.affordance!r}"
        )
    target = _target(document, intent.target_id)
    _require(target is not None, "unknown canonical target")
    request = {"profile": ACTION_REQUEST_PROFILE, **common, "target": deepcopy(target)}
    request["document_sha256"] = action_request_sha256(request)
    validate_action_request(request)
    disposition, reason = _request_reason(state, document, request)
    _require(disposition == "applied", reason)
    return request


def action_goal_policies(
    state: dict[str, Any], document: dict[str, Any], requests: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], tuple[ActionDisposition, ...]]:
    """Produce the existing planner seam plus deterministic audit dispositions for one step."""
    validate_society_input(document)
    _require(state.get("profile") in ACTION_ENGINES, "this society takes no user actions")
    policies: dict[str, dict[str, Any]] = {}
    dispositions = []
    # Where an input states places, each applied request is promised its place before the step,
    # in request order, so a person sent somewhere is never beaten to the last place by somebody
    # choosing for themselves in the same minute, and two requests never share one place.
    promised: set[str] = set()
    people = _people(state)
    graph = input_graph(document)
    for request in requests:
        validate_action_request(request)
        _require(request["branch_id"] == state["branch_id"], "action request branch mismatch")
        disposition, reason = _request_reason(state, document, request)
        subject = request["subject_id"]
        if disposition == "applied" and subject in policies:
            disposition, reason = "superseded", "subject_already_directed"
        if request["profile"] == HANDS_REQUEST_PROFILE:
            # The being waits where it stands within reach, or walks to the open node within reach
            # of what the act is for, as a decider's chosen act walks it.
            from exulanica.world.society_model_decisions import hands_goal_policy

            if disposition == "applied":
                policy = hands_goal_policy(
                    state, document, subject, _hands_option(request["intent"]), promised, asked=True
                )
                if isinstance(policy, str):
                    disposition, reason = "rejected", policy
                else:
                    policies[subject] = policy
                    if "place_node_id" in policy:
                        promised.add(policy["place_node_id"])
            dispositions.append(
                ActionDisposition(
                    uuid.UUID(request["request_id"]), uuid.UUID(subject), disposition, reason
                )
            )
            continue
        place = None
        if disposition == "applied" and document["profile"] in PLACE_INPUTS:
            place = _promised_place(state, people[subject], request["target"], promised, graph)
            if place is None:
                disposition, reason = "rejected", "destination_full"
        if disposition == "applied":
            policies[subject] = {
                "allowed_target_ids": [request["target"]["target_id"]],
                "preferred_target_id": request["target"]["target_id"],
            }
            if place is not None:
                policies[subject]["place_node_id"] = place
                promised.add(place)
        dispositions.append(
            ActionDisposition(
                uuid.UUID(request["request_id"]),
                uuid.UUID(subject),
                disposition,
                reason,
            )
        )
    return policies, tuple(dispositions)


def append_action_events(
    previous_state: dict[str, Any],
    next_state: dict[str, Any],
    document: dict[str, Any],
    requests: list[dict[str, Any]],
    dispositions: tuple[ActionDisposition, ...],
    events: tuple[SocietyEvent, ...],
) -> tuple[SocietyEvent, ...]:
    """Append request consumption to the normal deterministic event order."""
    by_request = {str(value.request_id): value for value in dispositions}
    people = _people(next_state)
    result = list(events)
    previous_digest = society_state_sha256(previous_state)
    for request in requests:
        disposition = by_request[request["request_id"]]
        person = people[request["subject_id"]]
        order = len(result)
        event_document = {
            "summary": (
                f"{person['display_name']} (simulated): user action request "
                f"{disposition.disposition}; {disposition.reason.replace('_', ' ')}."
            ),
            "synthetic": True,
            "profile": next_state["profile"],
            "branch_id": next_state["branch_id"],
            "subject_id": person["id"],
            "tick": next_state["tick"],
            "order": order,
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "target": deepcopy(request.get("target")),
            **(
                {"act": {key: request["intent"][key] for key in ("ability", "thing_id", "with_id")}}
                if request["profile"] == HANDS_REQUEST_PROFILE
                else {}
            ),
            "reason": disposition.reason,
            "outcome": "action_request_" + disposition.disposition,
            "goal": deepcopy(person["goal"]),
            "action": deepcopy(person["action"]),
            "position_mm": list(person["position_mm"]),
            "motion_path_mm": deepcopy(person["motion_path_mm"]),
            "previous_state_sha256": previous_digest,
            "seed_sha256": previous_state["seed_sha256"],
            "origin": "user",
            "requested_by": request["requested_by"],
            "action_request_id": request["request_id"],
            "action_request_sha256": request["document_sha256"],
            "disposition": disposition.disposition,
        }
        event_id = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{previous_state['society_id']}:{next_state['tick']}:{order}:"
            f"{society_state_sha256(event_document)}",
        )
        result.append(
            SocietyEvent(
                event_id,
                next_state["tick"],
                ACTION_EVENT_KIND,
                uuid.UUID(person["id"]),
                None,
                event_document,
            )
        )
    return tuple(result)


def advance_directed_purposeful_society(
    state: dict[str, Any],
    seed: str,
    inputs: list[dict[str, Any]],
    requests: list[dict[str, Any]],
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...], tuple[ActionDisposition, ...]]:
    """Reference v2 composition used by shared persistence wiring and exact replay."""
    _require(state.get("profile") == PURPOSEFUL_PROFILE, "reference directed advance requires v2")
    policies, dispositions = action_goal_policies(state, inputs[-1], requests)
    result, events = advance_purposeful_society(state, seed, inputs, goal_policy=policies)
    return (
        result,
        append_action_events(state, result, inputs[-1], requests, dispositions, events),
        dispositions,
    )
