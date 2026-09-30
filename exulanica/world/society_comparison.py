"""One run of a comparison: the same hour of a saved world, its people decided by one arm.

A comparison asks what a world's people do in one simulated hour when a model decides for them,
beside the same hour decided by their own routine and by nobody at all. Every run of it starts
from the same place: the genesis of the world's own purposeful society (``exulanica-society/v2``)
over its first input, with a seed, and its later inputs, up to the one the comparison froze,
consumed in the first minute as a step consumes queued inputs. The people are the society's own,
by identity, all of them; the seed decides where they start, how tired they are and every draw of
the routine.

A run's arm names who decides for the people its comparison scores, its group, which is
everybody unless the comparison names one:

*   ``routine``: nothing is asked; the planner decides, as it does for everybody by default.
*   ``wait``: at every choice point each person waits a minute, under the goal policy a model's
    chosen wait applies: the score's zero anchor.
*   ``model``: at every choice point each person with something to choose is asked of the arm's
    model through the decision contract, as the host's playback asks a person whose world's owner
    chose a model for them: the options the rules of the workspace leave unchanged, judged once a
    minute, then one request each (:func:`~exulanica.world.society_decisions.person_request`), and
    each answer a receipt the engine applies or refuses at its own choice point.

Everybody outside the group keeps the decider the comparison froze for them, the same in every
arm: the model their world's owner chose, asked the same way, or their routine. So two arms differ
only in who decides for the group.

The minutes run back to back: nothing waits for a playback interval, and a minute waits only for
its slowest answer. They are the one minute loop every decision role runs by
(:func:`~exulanica.world.role_decisions.play_minutes`), under the person role, with each arm's
deciders as the loop's own hooks. Asking is not done here. :func:`play` takes an :class:`Asking`
port; the host's runner asks models through it, and :func:`replay` answers from what a run stored,
with no client at all, then holds every rebuilt request and receipt to the stored bytes and every
minute's state to its recorded digest. A replay that differs anywhere is refused by name
(:class:`ReplayMismatch`), never shown.

Nothing here reads or writes a database or the live society: a run is its own, and the world it
ran over is unchanged by it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from typing import Any, Final

from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.role_decisions import (
    Asking,
    PlayedMinutes,
    ReplayMismatch,
    play_minutes,
    replay_minutes,
)
from exulanica.world.society import SocietyEvent, society_state_sha256
from exulanica.world.society_choice import WAIT_KEY
from exulanica.world.society_decision_contract import (
    DecisionContract,
    DecisionOption,
    input_memo,
    option_goal_policy,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_living import initial_living_society, input_routine, living_places
from exulanica.world.society_living_decisions import LivingSeam, living_seam, living_step
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
)

__all__ = [
    "DECIDER_KINDS",
    "OTHER_DECIDER_KINDS",
    "ROUTINE",
    "Asking",
    "PlayedRun",
    "ReplayMismatch",
    "RunPlan",
    "plan_role",
    "play",
    "replay",
    "request_id",
]

#: Who decides for the people of a run: their routine, nobody (they wait), or a model.
DECIDER_KINDS: Final = ("routine", "wait", "model")
#: Who decides for a person outside a comparison's group: what their world's owner chose, a model
#: or their routine.
OTHER_DECIDER_KINDS: Final = ("routine", "model")
#: The routine's decider, for a person nobody chose a model for.
ROUTINE: Final = {"kind": "routine"}


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
    #: The arm's decider, for every person of its group.
    decider: Mapping[str, Any]
    #: What a model arm's requests record about the model they ask; None for the anchors.
    provider_config: Mapping[str, Any] | None
    contract: DecisionContract
    #: The people the arm decides for, or None for everybody.
    group: frozenset[str] | None = None
    #: Everybody outside the group whose decider the comparison froze, by subject id: a model their
    #: world's owner chose (``{"decider": ..., "provider_config": ...}``) or their routine. Anybody
    #: outside the group and not named here follows their routine.
    others: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: The engine of the stored society. Existing comparison definitions belong to v2.
    engine_profile: str = PURPOSEFUL_PROFILE

    def __post_init__(self) -> None:
        if not self.inputs or self.inputs[0]["input_seq"] != 1:
            raise ValueError("a run starts from the society's first input")
        if [doc["input_seq"] for doc in self.inputs] != list(range(1, len(self.inputs) + 1)):
            raise ValueError("a run consumes the society's inputs in order, none left out")
        if self.ticks < 1:
            raise ValueError("a run takes at least one minute")
        if society_engine(self.engine_profile).state_family not in RUN_FAMILIES:
            raise ValueError("comparison_engine_family_unsupported")
        _check_decider(self.decider, self.provider_config, kinds=DECIDER_KINDS, who="arm")
        if self.group is not None and not self.group:
            raise ValueError("a group holds at least one person")
        for subject, held in self.others.items():
            if self.group is None or subject in self.group:
                raise ValueError("a person outside the group is not also in it")
            # Nobody outside the group waits: an owner chooses a model or the routine.
            _check_decider(
                held["decider"], held["provider_config"], kinds=OTHER_DECIDER_KINDS, who="person"
            )

    def decider_for(self, subject_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
        """Who decides for one person of this run, and what their requests record."""
        if self.group is None or subject_id in self.group:
            return self.decider, self.provider_config
        held = self.others.get(subject_id)
        if held is None:
            return ROUTINE, None
        return held["decider"], held["provider_config"]


def _check_decider(
    decider: Mapping[str, Any],
    config: Mapping[str, Any] | None,
    *,
    kinds: Sequence[str],
    who: str,
) -> None:
    kind = decider.get("kind")
    if kind not in kinds:
        raise ValueError(f"no decider {kind!r}")
    if (kind == "model") != (config is not None):
        raise ValueError(f"exactly a model {who} records what its requests ask")


def plan_role(plan: RunPlan) -> DecisionRole:
    """The decision role a run asks: the registered role whose contract is the one the run is
    asked under (:meth:`~exulanica.world.decision_roles.RoleRegistry.for_contract`), so a run
    names its role by the contract its comparison recorded rather than assuming a person."""
    return decision_roles().for_contract(plan.contract.binding())


def request_id(run_id: uuid.UUID, subject_id: str, tick: int) -> uuid.UUID:
    """The request a person is asked with in one run's minute: one per person, run and minute."""
    return uuid.uuid5(run_id, f"person-decision:{subject_id}:{tick}")


@dataclass(slots=True)
class PlayedRun:
    """What a run did: the genesis, every minute's state after it, its events, requests and
    receipts, and how many minutes each person began at the routine's choice point."""

    start: dict[str, Any]
    states: list[dict[str, Any]] = field(default_factory=list)
    events: list[SocietyEvent] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    choice_points: Counter[str] = field(default_factory=Counter)

    @property
    def minute_digests(self) -> list[str]:
        return [society_state_sha256(state) for state in self.states]

    @property
    def events_sha256(self) -> str:
        return society_state_sha256(ordered_events_document(tuple(self.events)))

    @property
    def receipts_sha256(self) -> str:
        return society_state_sha256([receipt["document_sha256"] for receipt in self.receipts])


def _purposeful_genesis(plan: RunPlan) -> dict[str, Any]:
    return initial_purposeful_society(
        plan.society_id,
        plan.seed,
        plan.inputs[0],
        population=plan.population,
        engine_profile=plan.engine_profile,
    )


def _living_genesis(plan: RunPlan) -> dict[str, Any]:
    source = plan.inputs[0]
    routine = input_routine(source)
    [place] = living_places([source], routine)
    return initial_living_society(
        plan.society_id,
        _run_seed(plan),
        place,
        routine,
        branch_id=str(source["version_id"]),
        population=plan.population,
        profile=plan.engine_profile,
    )


@dataclass(frozen=True, slots=True)
class _RunFamily:
    genesis: Callable[[RunPlan], dict[str, Any]]
    seam: Callable[
        [Mapping[str, Any], str, Sequence[dict[str, Any]], Sequence[str], RunPlan, dict[str, Any]],
        Any,
    ]
    step: Callable[
        [Mapping[str, Any], str, list[Mapping[str, Any]], Any], tuple[Any, tuple[Any, ...]]
    ]
    memo: Callable[[int], Any]


def _purposeful_seam(
    _state: Mapping[str, Any],
    _seed: str,
    _sources: Sequence[dict[str, Any]],
    due: Sequence[str],
    plan: RunPlan,
    waiting: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        subject: dict(waiting) for subject in due if plan.decider_for(subject)[0]["kind"] == "wait"
    }


def _living_wait_seam(
    state: Mapping[str, Any],
    seed: str,
    sources: Sequence[dict[str, Any]],
    due: Sequence[str],
    plan: RunPlan,
    _waiting: dict[str, Any],
) -> LivingSeam:
    base = living_seam(state, seed, sources)
    ordinals = {person["id"]: person["ordinal"] for person in state["inhabitants"]}
    held = tuple(subject for subject in due if plan.decider_for(subject)[0]["kind"] == "wait")
    return replace(
        base, chosen={ordinals[subject]: WAIT_KEY for subject in held}, acting_first=held
    )


def _purposeful_step(
    state: Mapping[str, Any],
    seed: str,
    consumed: list[Mapping[str, Any]],
    policies: Any,
) -> tuple[Any, tuple[Any, ...]]:
    return advance_purposeful_society(
        dict(state), seed, [dict(document) for document in consumed], goal_policy=policies
    )


def _living_step(
    state: Mapping[str, Any],
    seed: str,
    _consumed: list[Mapping[str, Any]],
    seam: LivingSeam,
) -> tuple[Any, tuple[Any, ...]]:
    return living_step(dict(state), seed, seam)


RUN_FAMILIES: Final = {
    "purposeful": _RunFamily(_purposeful_genesis, _purposeful_seam, _purposeful_step, input_memo),
    "living": _RunFamily(
        _living_genesis, _living_wait_seam, _living_step, lambda _n: nullcontext()
    ),
}


def _family(plan: RunPlan) -> _RunFamily:
    return RUN_FAMILIES[society_engine(plan.engine_profile).state_family]


def _run_seed(plan: RunPlan) -> str:
    """The living engine's SHA-256 seed; purposeful runs retain their historical seed text."""
    return (
        hashlib.sha256(plan.seed.encode("utf-8")).hexdigest()
        if society_engine(plan.engine_profile).state_family == "living"
        else plan.seed
    )


def genesis(plan: RunPlan) -> dict[str, Any]:
    """The stored society engine family's genesis over its first input and the run's seed."""
    return _family(plan).genesis(plan)


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


def _minutes(
    plan: RunPlan,
    asking: Asking,
    *,
    start: dict[str, Any],
    on_minute: Callable[[int, Sequence[dict[str, Any]], Sequence[dict[str, Any]]], None]
    | None = None,
) -> PlayedMinutes:
    """``plan``'s minutes, by the one loop every role runs by, under the role the run's contract
    names (:func:`plan_role`): the arm's model asked for its people, its waiting anchor as the
    seam each minute begins from, the routine for the rest."""
    role = plan_role(plan)
    waiting = _wait_policy(plan.contract)
    family = _family(plan)
    seed = _run_seed(plan)

    def config_for(subject: str) -> Mapping[str, Any] | None:
        decider, config = plan.decider_for(subject)
        return config if decider["kind"] == "model" else None

    def seam(state: Mapping[str, Any], due: Sequence[str]) -> Any:
        sources = plan.inputs if state["tick"] == 0 else plan.inputs[-1:]
        return family.seam(state, seed, sources, due, plan, waiting)

    # Every minute's options read the run's frozen inputs, so each input's graph and standing
    # exclusions are built once for the run rather than for every person due in every minute.
    with family.memo(len(plan.inputs)):
        return play_minutes(
            [role],
            role,
            start=start,
            sources=plan.inputs,
            seed=seed,
            ticks=plan.ticks,
            step=family.step,
            config_for=config_for,
            request_id_for=lambda subject, tick: request_id(plan.run_id, subject, tick),
            asking=asking,
            seam=seam,
            contract=plan.contract,
            on_minute=on_minute,
        )


def _run(start: dict[str, Any], minutes: PlayedMinutes) -> PlayedRun:
    return PlayedRun(
        start=start,
        states=minutes.states,
        events=minutes.events,
        requests=minutes.requests,
        receipts=minutes.receipts,
        choice_points=minutes.choice_points,
    )


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
    start = genesis(plan)
    if plan.group is not None and not plan.group <= {p["id"] for p in start["inhabitants"]}:
        raise ValueError("group_person_not_in_run: every person of a group is one of the run's")
    return _run(start, _minutes(plan, asking, start=start, on_minute=on_minute))


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
    start = genesis(plan)
    minutes = replay_minutes(
        stored,
        minute_digests=minute_digests,
        play=lambda asking: _minutes(plan, asking, start=start),
    )
    return _run(start, minutes)
