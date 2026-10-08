"""The person role's adapter: a person in a purposeful or a living society deciding what to do next.

The person's contract lives in :mod:`exulanica.world.society_decision_contract` (what a person may
be offered, what they see, how a choice is checked again) and its minute in
:mod:`exulanica.world.society_model_decisions` (what each receipt does to the planner's goal
policies, and the event it appends). A person in a living society (the living town) is offered the
living engine's own answer set and applied through its choice seam, in
:mod:`exulanica.world.society_living_decisions`. This module binds them to the names the generic
decision path calls, by the state family the engine table states for the state's engine, refusing
any other family by name, and declares the role key it serves; its registry entry states the rest
as data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.decision_roles import (
    DecisionContract,
    DecisionRole,
    RoleRefused,
    decision_roles,
)
from exulanica.world.role_decisions import written_messages
from exulanica.world.society_decision_contract import (
    ACTION_FIELDS,
    LINE_KINDS,
    NAMED_FIELDS,
    PERSON_REASONS,
    POLICY_KEYS_FROM,
    POLICY_RANGES,
    DecisionOption,
    at_choice_point,
    choice_options,
    observed_context,
    situation,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_living_decisions import (
    apply_living_receipts,
    living_context,
    living_decision_events,
    living_due,
    living_messages,
    living_options,
)
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies

__all__ = [
    "FAMILIES",
    "IDLE_KIND",
    "IDLE_KINDS",
    "KINDS",
    "LINE_KINDS",
    "NAMED_KINDS",
    "POLICY_KEYS_FROM",
    "POLICY_RANGES",
    "REASONS",
    "ROLE",
    "apply",
    "context",
    "due",
    "due_from_outside",
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
#: The placeholders a kind's words may name instead: the being by the name the page shows.
NAMED_KINDS: Final = NAMED_FIELDS
#: Waiting a minute changes nothing: it is offered only beside something else.
IDLE_KIND: Final = "wait"
#: What changes nothing, first preferred first: going on with what is under way, where it is
#: offered (to a society of things' people asked while something is under way), else waiting.
IDLE_KINDS: Final = ("carry_on", IDLE_KIND)
REASONS: Final = PERSON_REASONS


#: The state families whose people this role decides for: a society of things' people are
#: purposeful people beside its things, asked the purposeful contract's questions.
FAMILIES: Final = ("purposeful", "living", "things")


def person_role() -> DecisionRole:
    """The person role, as the production registry states it."""
    return decision_roles().role(ROLE)


def _living(profile: object) -> bool:
    """Whether a state of ``profile``'s engine is a living society's, by the engine table; a
    family this role does not decide for is refused by name."""
    family = society_engine(profile).state_family
    if family not in FAMILIES:
        raise RoleRefused(
            "person_family_unsupported",
            f"a person decides in a {' or '.join(FAMILIES)} society, not a {family} one",
        )
    return family == "living"


def subjects(state: Mapping[str, Any]) -> list[str]:
    """Everybody the role may decide for: the society's people, as its state names them."""
    return [person["id"] for person in state["inhabitants"]]


def _addressed(state: Mapping[str, Any], person: Mapping[str, Any]) -> bool:
    """Whether a line was said to ``person`` in the minute that made ``state``."""
    return any(
        heard["to"] == person["id"] and heard["tick"] == state["tick"]
        for heard in person.get("heard", ())
    )


def due(state: Mapping[str, Any], subject_id: str) -> bool:
    """Whether a model chosen for this person is asked before the coming minute: at the routine's
    own choice point, and in a society of things also the minute after a line was said to them,
    whatever is under way."""
    if _living(state["profile"]):
        return living_due(state, subject_id)
    person = next(p for p in state["inhabitants"] if p["id"] == subject_id)
    if at_choice_point(person):
        return True
    return society_engine(state["profile"]).state_family == "things" and _addressed(state, person)


def due_from_outside(state: Mapping[str, Any], subject_id: str) -> bool:
    """Whether an outside program deciding for this person is asked before the coming minute:
    whenever a model would be, and in a society of things every minute, so a program whose
    player acts at any moment is asked at the next one, with going on offered."""
    if society_engine(state["profile"]).state_family == "things":
        return True
    return due(state, subject_id)


def options(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    contract: DecisionContract,
    *,
    seed: str,
) -> tuple[DecisionOption, ...]:
    if _living(state["profile"]):
        return living_options(state, source, subject_id, contract, seed=seed)
    return choice_options(state, source, subject_id, contract, seed=seed)


def context(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    options: Sequence[DecisionOption],
) -> dict[str, Any]:
    if _living(state["profile"]):
        return living_context(state, source, subject_id, options, profile=role.context_profile)
    return observed_context(state, source, subject_id, options, profile=role.context_profile)


def option_from_record(record: Mapping[str, Any]) -> DecisionOption:
    return DecisionOption.from_record(record)


def messages(
    role: DecisionRole, context: Mapping[str, Any], mechanism: AnsweringMechanism
) -> list[dict[str, str]]:
    # A living person's context names its engine; a purposeful person's never did, and every
    # stored one reads as it was asked.
    if "engine" in context and _living(context["engine"]):
        return living_messages(role, context, mechanism)
    return written_messages(role, situation(context), context, mechanism)


def apply(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    seam: Any,
) -> tuple[Any, tuple[Any, ...]]:
    if _living(state["profile"]):
        return apply_living_receipts(state, source, receipts, seam, profile=role.receipt_profile)
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
    if _living(next_state["profile"]):
        return living_decision_events(
            previous_state, next_state, source, receipts, dispositions, events
        )
    return append_decision_events(
        previous_state, next_state, source, receipts, dispositions, events
    )
