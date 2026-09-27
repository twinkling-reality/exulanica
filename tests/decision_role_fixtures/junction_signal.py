"""The adapter of a traffic signal at a two-way junction, and the toy engine it runs in.

A signal lets one way go at a time. Once a way has gone for its shortest green, the signal is at a
choice point: keep the lights, or let the other way go. Cars arrive each minute by a draw from the
seed, and the way that goes lets some through.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.decision_roles import DecisionContract, DecisionRole
from exulanica.world.role_decisions import DecisionDisposition, written_messages
from exulanica.world.society import society_state_sha256

ROLE: Final = "junction_signal"
KINDS: Final = {"green": frozenset({"direction", "waiting"}), "hold": frozenset()}
IDLE_KIND: Final = "hold"
#: A choice to let a way go that no longer holds when the minute runs: that way already goes.
REASONS: Final = frozenset({"way_already_goes"})
#: The junction's two ways; minutes a way goes before the signal may switch; cars that pass on
#: green each minute; the most cars that arrive on one way in a minute, less one.
WAYS: Final = ("east-west", "north-south")
SHORTEST_GREEN: Final = 2
PASSING: Final = 2
ARRIVALS: Final = 3


@dataclass(frozen=True, slots=True)
class SignalOption:
    label: str
    kind: str
    action: str
    way: str | None
    waiting: int | None

    def as_record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "action": self.action,
            "way": self.way,
            "waiting": self.waiting,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> SignalOption:
        if set(record) != {"label", "kind", "action", "way", "waiting"}:
            raise ValueError("a recorded signal option states exactly its fields")
        return cls(**record)


def genesis(branch_id: uuid.UUID, signals: int) -> dict[str, Any]:
    """A junction's signals at minute 0, each letting the first way go, nobody waiting."""
    return {
        "branch_id": str(branch_id),
        "tick": 0,
        "signals": [
            {
                "id": str(uuid.uuid5(branch_id, f"signal:{index}")),
                "way": WAYS[0],
                "since": 0,
                "waiting": dict.fromkeys(WAYS, 0),
            }
            for index in range(signals)
        ],
    }


def source(branch_id: uuid.UUID) -> dict[str, Any]:
    """The junction's one input: its signals do not move, so it states only what it is."""
    document: dict[str, Any] = {"input_seq": 1, "branch_id": str(branch_id), "ways": list(WAYS)}
    document["document_sha256"] = society_state_sha256(document)
    return document


def _signal(state: Mapping[str, Any], subject_id: str) -> Mapping[str, Any]:
    return next(signal for signal in state["signals"] if signal["id"] == subject_id)


def step(state: Mapping[str, Any], seed: str, sources: Sequence[Any], seam: Mapping[str, str]):
    """One minute: each switch the seam holds, then arrivals drawn from the seed, then passing."""
    tick = state["tick"] + 1
    signals = []
    for signal in state["signals"]:
        way, since = (
            (seam[signal["id"]], tick) if signal["id"] in seam else (signal["way"], signal["since"])
        )
        waiting = {
            name: count
            + int(
                hashlib.sha256(f"{seed}:{signal['id']}:{tick}:{name}".encode()).hexdigest()[:8], 16
            )
            % ARRIVALS
            for name, count in signal["waiting"].items()
        }
        waiting[way] = max(0, waiting[way] - PASSING)
        signals.append({"id": signal["id"], "way": way, "since": since, "waiting": waiting})
    return {"branch_id": state["branch_id"], "tick": tick, "signals": signals}, ()


def subjects(state: Mapping[str, Any]) -> list[str]:
    return [signal["id"] for signal in state["signals"]]


def due(state: Mapping[str, Any], subject_id: str) -> bool:
    return state["tick"] - _signal(state, subject_id)["since"] >= SHORTEST_GREEN


def options(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    contract: DecisionContract,
    *,
    seed: str,
) -> tuple[SignalOption, ...]:
    signal = _signal(state, subject_id)
    turns = [
        SignalOption(
            contract.words["green"].format(direction=way, waiting=signal["waiting"][way]),
            "green",
            contract.action_keys["green"],
            way,
            signal["waiting"][way],
        )
        for way in WAYS
        if way != signal["way"]
    ]
    return (
        *turns,
        SignalOption(contract.words["hold"], "hold", contract.action_keys["hold"], None, None),
    )


def context(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    options: Sequence[SignalOption],
) -> dict[str, Any]:
    signal = _signal(state, subject_id)
    return {
        "profile": role.context_profile,
        "subject_id": subject_id,
        "branch_id": state["branch_id"],
        "tick": state["tick"],
        "way": signal["way"],
        "held_minutes": state["tick"] - signal["since"],
        "waiting": dict(signal["waiting"]),
        "options": [option.as_record() for option in options],
    }


def option_from_record(record: Mapping[str, Any]) -> SignalOption:
    return SignalOption.from_record(record)


def messages(
    role: DecisionRole, context: Mapping[str, Any], mechanism: AnsweringMechanism
) -> list[dict[str, str]]:
    waiting = ", ".join(f"{way} {count}" for way, count in sorted(context["waiting"].items()))
    return written_messages(
        role,
        [
            f"It is minute {context['tick']}. The {context['way']} traffic has gone for "
            f"{context['held_minutes']} minutes.",
            f"Waiting: {waiting}.",
        ],
        context,
        mechanism,
    )


def apply(
    role: DecisionRole,
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    seam: Mapping[str, str],
):
    """Each receipt in decision order: stale over another state, a second for one signal, a way
    that already goes, or a switch the minute makes."""
    switches, done, prior = dict(seam), [], society_state_sha256(dict(state))
    for receipt in receipts:
        disposition, reason = receipt["status"], receipt["reason"]
        if receipt["status"] == "accepted":
            option = SignalOption.from_record(receipt["proposal"]["option"])
            if (receipt["base_state_sha256"], receipt["input_sha256"]) != (
                prior,
                source["document_sha256"],
            ):
                disposition, reason = "stale", "decision_context_changed"
            elif receipt["subject_id"] in switches:
                disposition, reason = "superseded", "subject_already_decided"
            elif (
                option.kind == "green"
                and option.way == _signal(state, receipt["subject_id"])["way"]
            ):
                disposition, reason = "rejected", "way_already_goes"
            else:
                disposition = "applied"
                if option.kind == "green":
                    switches[receipt["subject_id"]] = str(option.way)
        done.append(
            DecisionDisposition(
                receipt["decision_seq"],
                receipt["request_id"],
                receipt["subject_id"],
                disposition,
                reason,
                receipt["document_sha256"],
            )
        )
    return switches, tuple(done)


def events(
    role: DecisionRole,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[DecisionDisposition],
    events: tuple[Any, ...],
):
    return (
        *events,
        *(
            {
                "tick": next_state["tick"],
                "subject_id": d.subject_id,
                "disposition": d.disposition,
                "reason": d.reason,
            }
            for d in dispositions
        ),
    )
