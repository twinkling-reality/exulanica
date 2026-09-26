"""A person's model decisions, applied by the purposeful engine at its own choice point.

The purposeful society (``exulanica-society/v2``) takes a model's decision for a person the way it
takes a person's own direct request: as a goal policy for the coming minute, over the seam the
planner already has. A decision is a stored receipt (``exulanica.society-decision/v2``), asked
before the minute by the host for a person whose world's owner chose a model for them and bound to
the exact state and input it was asked over. This module decides, deterministically and without
any model, what each receipt does to the minute, in decision order:

*   A receipt that is not ``accepted`` does nothing to the minute; its disposition is its status
    and its reason the receipt's, and the routine decides that turn.
*   An accepted receipt asked over another state or input is ``stale``.
*   A person a direct request moves this minute is ``superseded``: their own request comes first.
    So is a second receipt for somebody already decided this minute.
*   An accepted choice is checked again against the minute
    (:func:`~exulanica.world.society_decision_contract.recheck_option`), and a place is promised
    to it before the minute, after every direct request's, so two choices, or a choice and a
    request, never share one place. A choice that no longer holds is ``rejected`` with the reason.
*   Anything else is ``applied``: a goal policy the planner reads as a model's, recording the
    model's own reason code.

Each consumed receipt is appended to the minute's events as a ``decision_applied`` event, after
the planner's events and any direct request's, so the history says what every receipt did. A
society that never saw a receipt advances exactly as it always has: with no receipts this adds
no policy and no event.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final

from exulanica.world.society import SOCIETY_NAMESPACE, SocietyEvent, society_state_sha256
from exulanica.world.society_decision_contract import (
    DecisionOption,
    option_goal_policy,
    recheck_option,
)
from exulanica.world.society_decisions import PERSON_DECISION_PROFILE
from exulanica.world.society_planner import input_sha256

__all__ = [
    "DECISION_EVENT_KIND",
    "DecisionDisposition",
    "append_decision_events",
    "model_goal_policies",
]

#: The event kind a consumed receipt is recorded under, the one the social society records too.
DECISION_EVENT_KIND: Final = "decision_applied"
#: The dispositions a consumed receipt may have, the ones migration 0055 binds a transition to.
_DISPOSITIONS: Final = ("applied", "rejected", "unavailable", "stale", "superseded")


@dataclass(frozen=True, slots=True)
class DecisionDisposition:
    """What one receipt did to one minute, and why."""

    decision_seq: int
    request_id: str
    subject_id: str
    disposition: str
    reason: str
    decision_sha256: str


def _checked(receipt: Mapping[str, Any]) -> None:
    if (
        receipt.get("profile") != PERSON_DECISION_PROFILE
        or receipt["document_sha256"] != input_sha256(dict(receipt))
        or receipt["status"] not in ("accepted", "rejected", "unavailable", "stale")
    ):
        raise ValueError("a purposeful society consumes only sealed person decision receipts")


def model_goal_policies(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    directed: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], tuple[DecisionDisposition, ...]]:
    """The minute's goal policies, a direct request's and each applied choice's, and what every
    receipt did.

    ``directed`` is the direct requests' policies for this minute, which are kept as they are and
    come first. ``document`` is the input the minute consumes last.
    """
    policies = {subject: dict(policy) for subject, policy in directed.items()}
    promised = {
        policy["place_node_id"] for policy in directed.values() if "place_node_id" in policy
    }
    prior = society_state_sha256(dict(state))
    applied: set[str] = set()
    sequences = [receipt["decision_seq"] for receipt in receipts]
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        raise ValueError("person decision receipts are consumed once each, in decision order")
    present = {person["id"] for person in state["inhabitants"]}
    dispositions: list[DecisionDisposition] = []
    for receipt in receipts:
        _checked(receipt)
        subject = receipt["subject_id"]
        reason = receipt["reason"]
        if receipt["status"] != "accepted":
            disposition = receipt["status"]
        elif (
            receipt["base_tick"] != state["tick"]
            or receipt["base_state_sha256"] != prior
            or receipt["input_sha256"] != document["document_sha256"]
            or receipt["branch_id"] != state["branch_id"]
            or subject not in present
        ):
            disposition, reason = "stale", "decision_context_changed"
        elif subject in directed:
            disposition, reason = "superseded", "person_asked_directly"
        elif subject in applied:
            disposition, reason = "superseded", "subject_already_decided"
        else:
            option = DecisionOption.from_record(receipt["proposal"]["option"])
            refused, place = recheck_option(state, document, subject, option, promised)
            if refused is not None:
                disposition, reason = "rejected", refused
            else:
                disposition = "applied"
                applied.add(subject)
                policies[subject] = option_goal_policy(option, place)
                if place is not None:
                    promised.add(place)
        dispositions.append(
            DecisionDisposition(
                decision_seq=receipt["decision_seq"],
                request_id=receipt["request_id"],
                subject_id=subject,
                disposition=disposition,
                reason=reason,
                decision_sha256=receipt["document_sha256"],
            )
        )
    return policies, tuple(dispositions)


def append_decision_events(
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    document: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[DecisionDisposition],
    events: tuple[SocietyEvent, ...],
) -> tuple[SocietyEvent, ...]:
    """The minute's events with one ``decision_applied`` event per consumed receipt appended."""
    if len(receipts) != len(dispositions):
        raise ValueError("every consumed person decision has one disposition")
    people = {person["id"]: person for person in next_state["inhabitants"]}
    previous_digest = society_state_sha256(dict(previous_state))
    result = list(events)
    for receipt, disposition in zip(receipts, dispositions, strict=True):
        if disposition.disposition not in _DISPOSITIONS:
            raise ValueError(f"no disposition {disposition.disposition!r}")
        # A person no longer here (sent away before the minute consumed their receipt) is named
        # by id alone: the event still closes what their receipt asked.
        person = people.get(disposition.subject_id)
        who = "Someone no longer here" if person is None else person["display_name"]
        provider = receipt["provider"]
        order = len(result)
        event_document = {
            "summary": (
                f"{who} (simulated): the model's decision was "
                f"{disposition.disposition}; {disposition.reason.replace('_', ' ')}."
            ),
            "synthetic": True,
            "profile": next_state["profile"],
            "branch_id": next_state["branch_id"],
            "subject_id": disposition.subject_id,
            "tick": next_state["tick"],
            "order": order,
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "target": None,
            "reason": disposition.reason,
            "outcome": f"decision_{disposition.disposition}",
            "goal": None if person is None else deepcopy(person["goal"]),
            "action": None if person is None else deepcopy(person["action"]),
            "position_mm": None if person is None else list(person["position_mm"]),
            "motion_path_mm": None if person is None else deepcopy(person["motion_path_mm"]),
            "previous_state_sha256": previous_digest,
            "seed_sha256": previous_state["seed_sha256"],
            "origin": "model",
            "decision_seq": disposition.decision_seq,
            "request_id": disposition.request_id,
            "decision_sha256": disposition.decision_sha256,
            "disposition": disposition.disposition,
            "model": (
                None
                if provider is None
                else {"provider": provider["provider"], "model_id": provider["model_id"]}
            ),
            "chose": None if receipt["proposal"] is None else receipt["proposal"]["label"],
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
                DECISION_EVENT_KIND,
                uuid.UUID(disposition.subject_id),
                None,
                event_document,
            )
        )
    return tuple(result)
