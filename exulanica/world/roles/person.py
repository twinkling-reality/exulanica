"""The person role's adapter: a person in a purposeful society deciding what to do next.

The person's contract lives in :mod:`exulanica.world.society_decision_contract` (what a person may
be offered, what they see, how a choice is checked again) and its minute in
:mod:`exulanica.world.society_model_decisions` (what each receipt does to the planner's goal
policies, and the event it appends). This module binds them to the names the generic decision path
calls, and declares the role key it serves; its registry entry states the rest as data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.decision_roles import DecisionContract, DecisionRole, decision_roles
from exulanica.world.role_decisions import written_messages
from exulanica.world.society_decision_contract import (
    ACTION_FIELDS,
    PERSON_REASONS,
    DecisionOption,
    at_choice_point,
    choice_options,
    observed_context,
    situation,
)
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies

__all__ = [
    "IDLE_KIND",
    "KINDS",
    "REASONS",
    "ROLE",
    "apply",
    "context",
    "due",
    "events",
    "messages",
    "option_from_record",
    "options",
    "person_role",
    "subjects",
]

#: The role this module serves: the key every stored call record of a person's decision carries.
ROLE: Final = "society_decision"
KINDS: Final = ACTION_FIELDS
#: Waiting a minute changes nothing: it is offered only beside something else.
IDLE_KIND: Final = "wait"
REASONS: Final = PERSON_REASONS


def person_role() -> DecisionRole:
    """The person role, as the production registry states it."""
    return decision_roles().role(ROLE)


def subjects(state: Mapping[str, Any]) -> list[str]:
    """Everybody the role may decide for: the society's people, as its state names them."""
    return [person["id"] for person in state["inhabitants"]]


def due(state: Mapping[str, Any], subject_id: str) -> bool:
    person = next(p for p in state["inhabitants"] if p["id"] == subject_id)
    return at_choice_point(person)


def options(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    contract: DecisionContract,
    *,
    seed: str,
) -> tuple[DecisionOption, ...]:
    return choice_options(state, source, subject_id, contract, seed=seed)


def context(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    options: Sequence[DecisionOption],
) -> dict[str, Any]:
    return observed_context(state, source, subject_id, options, profile=role.context_profile)


def option_from_record(record: Mapping[str, Any]) -> DecisionOption:
    return DecisionOption.from_record(record)


def messages(
    role: DecisionRole, context: Mapping[str, Any], mechanism: AnsweringMechanism
) -> list[dict[str, str]]:
    return written_messages(role, situation(context), context, mechanism)


def apply(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    seam: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], tuple[Any, ...]]:
    return model_goal_policies(state, source, receipts, seam, profile=role.receipt_profile)


def events(
    role: DecisionRole,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[Any],
    events: tuple[Any, ...],
) -> tuple[Any, ...]:
    return append_decision_events(
        previous_state, next_state, source, receipts, dispositions, events
    )
