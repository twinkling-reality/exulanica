"""One run of a comparison: the same hour of a saved world, its people decided by one arm.

A comparison asks what a world's people do in one simulated hour when a model decides for them,
beside the same hour decided by their own routine and by nobody at all. Every run of it starts
from the same place: the genesis of the world's own purposeful society (``exulanica-society/v2``)
over its first input, with a seed, and its later inputs, up to the one the comparison froze,
consumed in the first minute as a step consumes queued inputs. The people are the society's own,
by identity, all of them; the seed decides where they start, how tired they are and every draw of
the routine.

A run's arm names who decides for its people:

*   ``routine``: nothing is asked; the planner decides, as it does for everybody by default.
*   ``wait``: at every choice point each person waits a minute, under the goal policy a model's
    chosen wait applies: the score's zero anchor.
*   ``model``: at every choice point each person with something to choose is asked of the arm's
    model through the decision contract, as the host's playback asks a person whose world's owner
    chose a model for them: the options the rules of the workspace leave unchanged, judged once a
    minute, then one request each (:func:`~exulanica.world.society_decisions.person_request`), and
    each answer a receipt the engine applies or refuses at its own choice point.

The minutes run back to back: nothing waits for a playback interval, and a minute waits only for
its slowest answer. Asking is not done here. :func:`play` takes an :class:`Asking` port; the
host's runner asks models through it, and :func:`replay` answers from what a run stored, with no
client at all, then holds every rebuilt request and receipt to the stored bytes and every minute's
state to its recorded digest. A replay that differs anywhere is refused by name
(:class:`ReplayMismatch`), never shown.

Nothing here reads or writes a database or the live society: a run is its own, and the world it
ran over is unchanged by it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from exulanica.world.society import SocietyEvent, society_state_sha256
from exulanica.world.society_decision_contract import (
    DecisionContract,
    DecisionOption,
    at_choice_point,
    choice_options,
    option_goal_policy,
)
from exulanica.world.society_decisions import (
    person_request,
    receipt_for,
    validate_decision_receipt,
)
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
)

__all__ = [
    "DECIDER_KINDS",
    "Asking",
    "PlayedRun",
    "ReplayMismatch",
    "RunPlan",
    "play",
    "replay",
    "request_id",
]

#: Who decides for the people of a run: their routine, nobody (they wait), or a model.
DECIDER_KINDS: Final = ("routine", "wait", "model")


class ReplayMismatch(ValueError):
    """A stored run does not replay to what it recorded."""

    code: Final = "run_replay_mismatch"

    def __init__(self, detail: str, *, minute: int | None = None) -> None:
        where = "" if minute is None else f" at minute {minute}"
        super().__init__(f"run_replay_mismatch{where}: {detail}")
        self.minute = minute


class Asking(Protocol):
    """What a run asks of the world outside it, minute by minute."""

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[DecisionOption]]
    ) -> Mapping[str, frozenset[str]]:
        """For each person due at ``tick``, with the options they have, the labels that may be
        offered to them. Asked once a minute, for every person due in it."""
        ...

    def answers(self, requests: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]:
        """One result per request, in the same order: ``{status, reason, proposal, provider}``,
        as a receipt records it."""
        ...


@dataclass(frozen=True, slots=True)
class RunPlan:
    """Everything one run depends on, all of it recorded with the comparison it belongs to."""

    run_id: uuid.UUID
    society_id: uuid.UUID
    seed: str
    population: int
    #: The world's society inputs from the first through the one the comparison froze.
    inputs: tuple[dict[str, Any], ...]
    ticks: int
    #: The arm's decider, for every person of the run.
    decider: Mapping[str, Any]
    #: What a model arm's requests record about the model they ask; None for the anchors.
    provider_config: Mapping[str, Any] | None
    contract: DecisionContract

    def __post_init__(self) -> None:
        if not self.inputs or self.inputs[0]["input_seq"] != 1:
            raise ValueError("a run starts from the society's first input")
        if [doc["input_seq"] for doc in self.inputs] != list(range(1, len(self.inputs) + 1)):
            raise ValueError("a run consumes the society's inputs in order, none left out")
        if self.ticks < 1:
            raise ValueError("a run takes at least one minute")
        kind = self.decider.get("kind")
        if kind not in DECIDER_KINDS:
            raise ValueError(f"no decider {kind!r}")
        if (kind == "model") != (self.provider_config is not None):
            raise ValueError("exactly a model arm records what its requests ask")


def request_id(run_id: uuid.UUID, subject_id: str, tick: int) -> uuid.UUID:
    """The request a person is asked with in one run's minute: one per person, run and minute."""
    return uuid.uuid5(run_id, f"person-decision:{subject_id}:{tick}")


@dataclass(slots=True)
class PlayedRun:
    """What a run did: the genesis, every minute's state after it, its events, requests and
    receipts."""

    start: dict[str, Any]
    states: list[dict[str, Any]] = field(default_factory=list)
    events: list[SocietyEvent] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def minute_digests(self) -> list[str]:
        return [society_state_sha256(state) for state in self.states]

    @property
    def events_sha256(self) -> str:
        return society_state_sha256(ordered_events_document(tuple(self.events)))

    @property
    def receipts_sha256(self) -> str:
        return society_state_sha256([receipt["document_sha256"] for receipt in self.receipts])


def genesis(plan: RunPlan) -> dict[str, Any]:
    """The run's first state: the society's genesis over its first input with the run's seed."""
    return initial_purposeful_society(
        plan.society_id,
        plan.seed,
        plan.inputs[0],
        population=plan.population,
        engine_profile=PURPOSEFUL_PROFILE,
    )


def _wait_policy(contract: DecisionContract) -> dict[str, Any]:
    """The goal policy a model's chosen wait applies, from the contract's own wait option."""
    return option_goal_policy(
        DecisionOption(
            label=contract.words["wait"],
            kind="wait",
            action=contract.action_keys["wait"],
            target_id=None,
            activity=None,
            walk_mm=None,
        ),
        None,
    )


def _only(labels: frozenset[str]) -> Callable[[Sequence[DecisionOption]], list[DecisionOption]]:
    def offered(options: Sequence[DecisionOption]) -> list[DecisionOption]:
        return [option for option in options if option.label in labels]

    return offered


def play(
    plan: RunPlan,
    asking: Asking,
    *,
    on_minute: Callable[[int, Sequence[dict[str, Any]], Sequence[dict[str, Any]]], None]
    | None = None,
) -> PlayedRun:
    """Play ``plan`` minute by minute, asking ``asking`` for a model arm's people.

    ``on_minute(tick, requests, receipts)`` is called after each minute's answers are receipted
    and before the minute advances, so a caller can store what it paid for as it goes.
    """
    state = genesis(plan)
    played = PlayedRun(start=state)
    latest = plan.inputs[-1]
    kind = plan.decider["kind"]
    waiting = _wait_policy(plan.contract)
    sequence = 0
    for minute in range(1, plan.ticks + 1):
        consumed = list(plan.inputs) if minute == 1 else [latest]
        people = sorted(
            (person for person in state["inhabitants"] if at_choice_point(person)),
            key=lambda person: person["id"],
        )
        directed: dict[str, dict[str, Any]] = {}
        requests: list[dict[str, Any]] = []
        if kind == "wait":
            directed = {person["id"]: dict(waiting) for person in people}
        elif kind == "model":
            due = {
                person["id"]: options
                for person in people
                if (
                    options := choice_options(
                        state, latest, person["id"], plan.contract, seed=plan.seed
                    )
                )
            }
            kept = asking.offerable(state["tick"], due) if due else {}
            for subject in sorted(due):
                request, _status = person_request(
                    state,
                    latest,
                    subject,
                    request_id=request_id(plan.run_id, subject, state["tick"]),
                    contract=plan.contract,
                    seed=plan.seed,
                    provider_config=dict(plan.provider_config or {}),
                    offer=_only(kept.get(subject, frozenset())),
                )
                if request is not None:
                    requests.append(request)
        results = list(asking.answers(requests)) if requests else []
        if len(results) != len(requests):
            raise ValueError("every request of a minute gets exactly one result")
        receipts = []
        for request, result in zip(requests, results, strict=True):
            sequence += 1
            receipt = receipt_for(request, sequence, dict(result))
            validate_decision_receipt(receipt, request)
            receipts.append(receipt)
        if on_minute is not None:
            on_minute(state["tick"] + 1, requests, receipts)
        policies, decided = model_goal_policies(state, latest, receipts, directed)
        after, events = advance_purposeful_society(state, plan.seed, consumed, goal_policy=policies)
        events = append_decision_events(state, after, latest, receipts, decided, events)
        played.states.append(after)
        played.events.extend(events)
        played.requests.extend(requests)
        played.receipts.extend(receipts)
        state = after
    return played


@dataclass(frozen=True, slots=True)
class _Stored:
    """Answers from what a run stored: the options each stored request offered, and its receipt."""

    requests: Mapping[tuple[str, int], dict[str, Any]]
    receipts: Mapping[str, dict[str, Any]]
    used: set[str]

    def offerable(
        self, tick: int, due: Mapping[str, Sequence[DecisionOption]]
    ) -> dict[str, frozenset[str]]:
        # A person the run asked was offered exactly the options their stored request records;
        # one it did not ask was offered too few, and is offered none again.
        return {
            subject: frozenset(
                option["label"]
                for option in self.requests.get((subject, tick), {"context": {"options": []}})[
                    "context"
                ]["options"]
            )
            for subject in due
        }

    def answers(self, requests: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for request in requests:
            minute = request["base_tick"] + 1
            stored = self.requests.get((request["subject_id"], request["base_tick"]))
            receipt = self.receipts.get(request["request_id"])
            if stored is None or receipt is None:
                raise ReplayMismatch("a rebuilt request has no stored answer", minute=minute)
            if stored != request or receipt["request_sha256"] != request["document_sha256"]:
                raise ReplayMismatch("a rebuilt request is not the one stored", minute=minute)
            self.used.add(request["request_id"])
            results.append(
                {key: receipt[key] for key in ("status", "reason", "proposal", "provider")}
            )
        return results


def replay(
    plan: RunPlan,
    stored: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    minute_digests: Sequence[str],
) -> PlayedRun:
    """Play ``plan`` again from the requests and receipts it stored, asking nothing, and hold it
    to its record.

    ``stored`` is every request the run recorded with its receipt, in decision order, and
    ``minute_digests`` the state digest it recorded after each minute. A rebuilt request that is
    not the stored one, a receipt that is not rebuilt to the same bytes, a stored receipt no minute
    asks for, or a minute that ends in another state: each is a :class:`ReplayMismatch`.
    """
    requests = {(str(r["subject_id"]), int(r["base_tick"])): dict(r) for r, _ in stored}
    receipts = {str(receipt["request_id"]): dict(receipt) for _, receipt in stored}
    if len(requests) != len(stored) or len(receipts) != len(stored):
        raise ReplayMismatch("a person is asked twice in one minute, or a request answered twice")
    answering = _Stored(requests, receipts, set())
    played = play(plan, answering)
    if len(played.states) != len(minute_digests):
        raise ReplayMismatch("the run recorded another number of minutes")
    for minute, (found, recorded) in enumerate(
        zip(played.minute_digests, minute_digests, strict=True), 1
    ):
        if found != recorded:
            raise ReplayMismatch("the minute ends in another state", minute=minute)
    if [dict(receipt) for _, receipt in stored] != played.receipts:
        raise ReplayMismatch("a stored receipt is not the one its request rebuilds")
    if answering.used != set(receipts):
        raise ReplayMismatch("a stored receipt answers no request the run asks")
    return played
