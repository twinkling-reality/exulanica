"""Typed user requests over canonical society targets, never browser-space movement."""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.society import SOCIETY_NAMESPACE, SocietyEvent, society_state_sha256
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    validate_society_input,
)
from exulanica.world.society_social import SOCIAL_PROFILE

ACTION_REQUEST_PROFILE: Final = "exulanica.society-action-request/v1"
ACTION_EVENT_KIND: Final = "user_action_requested"
ActionKind = Literal["go_to", "perform"]
ActionDispositionKind = Literal["applied", "stale", "unavailable", "rejected", "superseded"]


@dataclass(frozen=True, slots=True)
class ActionIntent:
    kind: ActionKind
    target_id: str
    affordance: str | None = None


@dataclass(frozen=True, slots=True)
class ActionDisposition:
    request_id: uuid.UUID
    subject_id: uuid.UUID
    disposition: ActionDispositionKind
    reason: str


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
    """Validate the immutable request envelope without treating it as current authority."""
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
        "target",
        "document_sha256",
    }
    _require(
        isinstance(document, dict) and set(document) == fields, "invalid action request fields"
    )
    _require(document["profile"] == ACTION_REQUEST_PROFILE, "unsupported action request profile")
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
    if person["goal"] is not None and person["action"]["status"] not in ("completed", "blocked"):
        return "rejected", "inhabitant_action_in_progress"
    target = _target(document, request["intent"]["target_id"])
    if target is None or not target["enabled"] or target != request["target"]:
        return "stale", "canonical_target_changed"
    if not _reachable(person, document, target):
        return "rejected", "target_unreachable"
    return "applied", "validated_user_target"


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
    _require(
        state.get("profile") in (PURPOSEFUL_PROFILE, SOCIAL_PROFILE), "actions require v2 or v3"
    )
    _require(
        state.get("branch_id") == document["version_id"], "society input belongs to another branch"
    )
    _require(
        state.get("input_seq") == document["input_seq"]
        and state.get("input_sha256") == document["document_sha256"],
        "advance queued inputs before requesting an action",
    )
    target = _target(document, intent.target_id)
    _require(target is not None, "unknown canonical target")
    request = {
        "profile": ACTION_REQUEST_PROFILE,
        "request_id": str(request_id),
        "requested_by": str(requested_by),
        "subject_id": str(subject_id),
        "branch_id": state["branch_id"],
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "intent": {
            "kind": intent.kind,
            "target_id": intent.target_id,
            **({"affordance": intent.affordance} if intent.kind == "perform" else {}),
        },
        "target": deepcopy(target),
    }
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
    _require(
        state.get("profile") in (PURPOSEFUL_PROFILE, SOCIAL_PROFILE), "actions require v2 or v3"
    )
    policies: dict[str, dict[str, Any]] = {}
    dispositions = []
    for request in requests:
        validate_action_request(request)
        _require(request["branch_id"] == state["branch_id"], "action request branch mismatch")
        disposition, reason = _request_reason(state, document, request)
        subject = request["subject_id"]
        if disposition == "applied" and subject in policies:
            disposition, reason = "superseded", "subject_already_directed"
        if disposition == "applied":
            policies[subject] = {
                "allowed_target_ids": [request["target"]["target_id"]],
                "preferred_target_id": request["target"]["target_id"],
            }
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
            "target": deepcopy(request["target"]),
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
