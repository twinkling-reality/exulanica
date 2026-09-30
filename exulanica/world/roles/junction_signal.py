"""The junction signal role's adapter, with traffic-owned observations and actions.

A society engine does not host this role. The traffic controller uses the generic decision
request and receipt path with a sealed traffic observation; the traffic step remains the authority
on whether a recorded keep can extend its green. The adapter never calls a model or changes a
signal by itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.decision_roles import DecisionContract, DecisionRole, RoleRefused
from exulanica.world.role_decisions import written_messages

__all__ = [
    "IDLE_KIND",
    "KINDS",
    "REASONS",
    "ROLE",
    "SignalOption",
    "apply",
    "context",
    "due",
    "events",
    "messages",
    "option_from_record",
    "options",
    "subjects",
]

ROLE: Final = "junction_signal"
KINDS: Final = {"switch": frozenset(), "keep": frozenset()}
IDLE_KIND: Final = "switch"
REASONS: Final = frozenset(
    {"green_not_eligible", "phase_changed", "point_stale", "signal_no_longer_in_world"}
)


@dataclass(frozen=True, slots=True)
class SignalOption:
    label: str
    kind: str
    action_key: str

    def as_record(self) -> dict[str, str]:
        return {"label": self.label, "kind": self.kind, "action_key": self.action_key}


def subjects(state: Mapping[str, Any]) -> tuple[str, ...]:
    """Signals this traffic continuation carries, in stable identity order."""
    return tuple(sorted(state.get("signals", ())))


def due(state: Mapping[str, Any], subject_id: str) -> bool:
    """Only the point the worker derived from the step is due."""
    return subject_id in state.get("choice_points", ())


def options(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    contract: DecisionContract,
    *,
    seed: str,
) -> tuple[SignalOption, ...]:
    if source.get("signal_id") != subject_id or not due(state, subject_id):
        return ()
    observation = source.get("observation")
    if not isinstance(observation, Mapping) or observation.get("near_vehicle_count", 0) <= 0:
        return ()
    return tuple(
        SignalOption(contract.words[kind], kind, contract.action_keys[kind])
        for kind in ("switch", "keep")
    )


def context(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    options: Sequence[SignalOption],
) -> dict[str, Any]:
    return {
        "profile": role.context_profile,
        "subject_id": subject_id,
        "branch_id": state["branch_id"],
        "tick": state["tick"],
        "world_id": source["world_id"],
        "roads_version": source["roads_version"],
        "episode": source["episode"],
        "segment": source["segment"],
        "choice_generation": source["choice_generation"],
        "choice_second": source["choice_second"],
        "state_sha256": source["state_sha256"],
        "observation": dict(source["observation"]),
        "options": [option.as_record() for option in options],
    }


def option_from_record(record: Mapping[str, Any]) -> SignalOption:
    if (
        set(record) != {"label", "kind", "action_key"}
        or record["kind"] not in KINDS
        or not isinstance(record["label"], str)
        or not isinstance(record["action_key"], str)
    ):
        raise ValueError("a signal option states its label, kind and action key")
    return SignalOption(record["label"], record["kind"], record["action_key"])


def messages(
    role: DecisionRole, context: Mapping[str, Any], mechanism: AnsweringMechanism
) -> list[dict[str, str]]:
    observation = context["observation"]
    situation = [
        f"Active street vehicles near: {observation['active_near']}.",
        f"Other street vehicles near: {observation['other_near']}.",
        f"Active street longest wait: {observation['active_wait_seconds']} seconds.",
        f"Other street longest wait: {observation['other_wait_seconds']} seconds.",
        f"Green elapsed: {observation['green_elapsed_seconds']} seconds.",
    ]
    return written_messages(role, situation, context, mechanism)


def apply(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    seam: Any,
) -> tuple[Any, tuple[Any, ...]]:
    raise RoleRefused("signal_engine_only", "the traffic step applies signal receipts")


def events(
    role: DecisionRole,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[Any],
    events: tuple[Any, ...],
) -> tuple[Any, ...]:
    raise RoleRefused("signal_engine_only", "the traffic step records signal events")
