"""A person sending their world's inhabitants away, and bringing them back, as recorded history.

Sending the inhabitants away is one simulated minute in which each of them leaves: an ordinary
transition, with one ``departed`` event each, after which the state holds nobody and says why and
since when. Bringing them back is another minute, in which the same people (the same identities
and names, derived from the society's seed as at genesis) arrive at spread starting places over the
world as it is then, with one ``arrived`` event each. Neither erases anything: the states before
the departure, their events and their transitions stay where they were, so replaying to any
minute before it shows them, and the return is a new arrival, never an undo of the departure.

The request is the person's; the server decides. It binds the exact state it was made against,
names the person who asked, and is refused by name when there is nobody to send away or when they
are already here. Replay regenerates both minutes from the stored request and the stored inputs.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from itertools import pairwise
from typing import Any, Final, Literal

from exulanica.world.society import SOCIETY_NAMESPACE, SocietyEvent, society_state_sha256
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    arriving_inhabitants,
    validate_input_successor,
    validate_society_input,
)

PRESENCE_REQUEST_PROFILE: Final = "exulanica.society-presence/v1"
AWAY: Final = "away"
HERE: Final = "here"
Presence = Literal["away", "here"]
#: What a request may ask for, and what the state then says.
PRESENCES: Final = (AWAY, HERE)


class PresenceRefused(ValueError):
    """A request the state cannot honour, with the name a caller can act on and why."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def presence(state: dict[str, Any]) -> Presence:
    """Whether the inhabitants are here. A state no request has changed has its people here."""
    held = state.get("presence")
    if held is None:
        return HERE
    status = held.get("status") if isinstance(held, dict) else None
    if status not in PRESENCES:
        raise ValueError("invalid society presence")
    return status  # type: ignore[return-value]


def presence_request_sha256(document: dict[str, Any]) -> str:
    return society_state_sha256({k: v for k, v in document.items() if k != "document_sha256"})


def presence_request(
    state: dict[str, Any],
    *,
    request_id: uuid.UUID,
    requested_by: uuid.UUID,
    wanted: Presence,
) -> dict[str, Any]:
    """The request as the server records it: bound to the exact state it was made against."""
    if wanted not in PRESENCES:
        raise ValueError("a presence request asks for away or here")
    document = {
        "profile": PRESENCE_REQUEST_PROFILE,
        "request_id": str(request_id),
        "requested_by": str(requested_by),
        "branch_id": state["branch_id"],
        "presence": wanted,
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
    }
    document["document_sha256"] = presence_request_sha256(document)
    validate_presence_request(document)
    return document


def validate_presence_request(document: Any) -> None:
    fields = {
        "profile",
        "request_id",
        "requested_by",
        "branch_id",
        "presence",
        "base_tick",
        "base_state_sha256",
        "document_sha256",
    }
    if (
        not isinstance(document, dict)
        or set(document) != fields
        or document["profile"] != PRESENCE_REQUEST_PROFILE
        or document["presence"] not in PRESENCES
        or type(document["base_tick"]) is not int
        or document["base_tick"] < 0
        or any(
            not isinstance(document[key], str) or str(uuid.UUID(document[key])) != document[key]
            for key in ("request_id", "requested_by", "branch_id")
        )
        or document["document_sha256"] != presence_request_sha256(document)
    ):
        raise ValueError("invalid society presence request")


def refusal(state: dict[str, Any], wanted: Presence) -> str | None:
    """Why this state cannot take this request, by name, or None when it can."""
    if wanted == AWAY and (presence(state) == AWAY or not state["inhabitants"]):
        return "nobody_to_send_away"
    if wanted == HERE and presence(state) == HERE:
        return "already_here"
    return None


def change_presence(
    state: dict[str, Any],
    seed: str,
    inputs: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    population: int,
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...]]:
    """Take the one minute a presence request asks for, consuming every queued input first.

    ``population`` is the society's own, as its row records it: the people who come back are the
    people who were created, however many of them had left.
    """
    validate_presence_request(request)
    if state["profile"] != PURPOSEFUL_PROFILE or state["seed_sha256"] != seed:
        raise ValueError("presence changes apply to a purposeful society's own lineage")
    if (
        request["branch_id"] != state["branch_id"]
        or request["base_tick"] != state["tick"]
        or request["base_state_sha256"] != society_state_sha256(state)
    ):
        raise ValueError("presence request is not bound to this state")
    reason = refusal(state, request["presence"])
    if reason is not None:
        raise PresenceRefused(reason)
    if not inputs:
        raise ValueError("historical current input is required")
    validate_society_input(inputs[0])
    if (
        inputs[0]["input_seq"] != state["input_seq"]
        or inputs[0]["document_sha256"] != state["input_sha256"]
    ):
        raise ValueError("current input binding mismatch")
    for prior, current in pairwise(inputs):
        validate_input_successor(prior, current)
    document = inputs[-1]
    result = deepcopy(state)
    tick = state["tick"] + 1
    result["tick"] = tick
    previous_digest = society_state_sha256(state)
    events: list[SocietyEvent] = []
    if request["presence"] == AWAY:
        leaving, kind, why, outcome = result["inhabitants"], "departed", "sent_away", "departed"
    else:
        try:
            leaving = arriving_inhabitants(
                uuid.UUID(state["society_id"]), seed, document, population=population
            )
        except ValueError as exc:
            raise PresenceRefused("nowhere_to_arrive", str(exc)) from exc
        kind, why, outcome = "arrived", "brought_back", "arrived"
    for person in leaving:
        order = len(events)
        summary = (
            f"{person['display_name']} (simulated) left: the world's owner sent everyone away."
            if kind == "departed"
            else f"{person['display_name']} (simulated) arrived: the world's owner brought "
            "everyone back."
        )
        event_document = {
            "summary": summary,
            "synthetic": True,
            "profile": PURPOSEFUL_PROFILE,
            "branch_id": result["branch_id"],
            "subject_id": person["id"],
            "tick": tick,
            "order": order,
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "target": None,
            "reason": why,
            "outcome": outcome,
            "goal": deepcopy(person["goal"]),
            "action": deepcopy(person["action"]),
            "position_mm": list(person["position_mm"]),
            "motion_path_mm": [list(person["position_mm"])],
            "previous_state_sha256": previous_digest,
            "seed_sha256": seed,
            "presence_request_id": request["request_id"],
            "presence_request_sha256": request["document_sha256"],
        }
        identity = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{state['society_id']}:{tick}:{order}:{society_state_sha256(event_document)}",
        )
        events.append(
            SocietyEvent(identity, tick, kind, uuid.UUID(person["id"]), None, event_document)
        )
        if kind == "arrived":
            person["memory"] = [str(identity)]
            person["explanation"] = {"summary": summary, "event_ids": [str(identity)]}
    result["inhabitants"] = [] if kind == "departed" else leaving
    result["presence"] = {
        "status": request["presence"],
        "since_tick": tick,
        "request_id": request["request_id"],
        "request_sha256": request["document_sha256"],
    }
    result["input_seq"] = document["input_seq"]
    result["input_sha256"] = document["document_sha256"]
    return result, tuple(events)
