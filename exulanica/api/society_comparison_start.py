"""A comparison's one definition path, what it can cost, and its start from the application.

Two callers define a comparison, both here: the local command
(``python -m exulanica.orchestration.compare``) and a world's owner in the application, through
``POST /world/versions/{version_id}/society/comparisons``. A :class:`ComparisonSelection` names what
is compared: the group of the society's people every arm decides for (everybody, the people one of
the owner's choices named, or people named), one or two models the manifest offers the runner's
decision role, whether the first runs a second time as the control, and how many development
seeds. :func:`definition_body` resolves the group and everybody else from the world's records and
states the body the runner defines (:func:`comparison_body`); the repository holds the body to the
world's records again when it stores it.

What a comparison can cost at most is derived, never stated (:func:`comparison_cost`). A run asks
each subject a model decides for at most once a minute, since a request is identified by its run,
subject and minute and migration 0113 keeps one per subject and minute; so a run's asks are at most
the protocol's window times the subjects a model decides for in it, the arm's group under a model
arm and, in every arm, anybody outside the group whose owner chose a model. Each ask costs at most
its bound (:func:`~exulanica.api.decision_host.ask_bound_usd`): every answer the contract allows, at
the manifest's prices, for the longest situation and answer the contract allows. What comparisons
typically cost is a measurement, not a bound: the judged group comparison's recorded spend per
simulated hour of each model's arms (:data:`TYPICAL_RECORD`), divided by its group's people, is
served beside the most as that record's figure (:func:`typical_per_person_hour`).

A comparison started from the application is recorded with the bound its owner stated, at most
the most it can cost, and a host's comparison worker plays it under that bound
(:mod:`exulanica.api.society_comparison_worker`). Every refusal of a start is named
(:data:`START_REFUSALS`), and the plan route answers what a start would, writing nothing.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.api.decision_host import ask_bound_usd
from exulanica.api.society_comparison_runner import ComparisonArm, SocietyComparisonRunner
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import Manifest
from exulanica.models.usage import USD_QUANTUM
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.society_catalogs import ComparisonCatalogs
from exulanica.world.society_comparison_repository import seed_digest
from exulanica.world.society_comparison_result import (
    GROUP_SOURCES,
    MINUTES_PER_HOUR,
    protocol_value,
)

__all__ = [
    "EVERYBODY",
    "MODELS_MOST",
    "PHASE",
    "ROUTINE_ARM",
    "START_REFUSALS",
    "TYPICAL_RECORD",
    "WAIT_ARM",
    "ComparisonCost",
    "ComparisonSelection",
    "StartRefused",
    "comparison_body",
    "comparison_cost",
    "definition_body",
    "development_seeds_in",
    "typical_per_person_hour",
]

#: The phase a comparison defined here runs on: development seeds, looked at freely and never
#: judged. A judged comparison is pre-registered, and its record is written by the measurement
#: that registered it.
PHASE: Final = "development"
#: The anchor arms every comparison runs, by key.
ROUTINE_ARM: Final = "routine"
WAIT_ARM: Final = "wait"
#: A group of everybody, as a definition states it: nobody named, nobody outside it.
EVERYBODY: Final = {"people": None, "source": {"kind": "everyone"}}
#: The most models one comparison compares: its claim registers one primary difference, between
#: the two models, or, with one, between it and the routine (:func:`comparison_body`).
MODELS_MOST: Final = 2
_ROOT: Final = Path(__file__).resolve().parents[2]
#: The measurement a comparison's typical cost is read from: the judged group comparison, whose
#: model arms each decided for four of a saved world's people for the protocol's hour over twelve
#: held-out seeds, with every call's recorded cost.
TYPICAL_RECORD: Final = "docs/evaluation/2026-09-26-society-group-comparison.json"

#: Every way a start is refused, by the code it is answered with and its status. The plan route
#: answers the same codes in its body, and the page has words for each (``START_REFUSAL_WORDS`` in
#: web/packages/app/src/ui/society-comparison-start.ts, held to this mapping by a parity test).
START_REFUSALS: Final = {
    # This server: it holds no development seed to run a comparison on (EXULANICA_COMPARISON_SEEDS).
    "comparisons_not_set_up": 409,
    # Nothing plays the comparisons started here (EXULANICA_COMPARISON_WORKER is off).
    "comparisons_not_played": 409,
    # This server does not ask models for this workspace (EXULANICA_SOCIETY_CONTROL_WORKSPACES).
    "comparisons_not_run_here": 409,
    # This server holds no key for the models' service.
    "provider_credential_absent": 409,
    # The world: it plays another comparison started from the application.
    "comparison_running": 409,
    # The id: it already names another comparison of the workspace.
    "comparison_conflict": 409,
    # The society: its engine takes no comparison, hosts no such role, or holds more people than
    # the protocol's population_maximum.
    "engine_takes_no_comparison": 409,
    "role_not_hosted": 409,
    "population_over_comparison_bound": 409,
    # The selection.
    "role_not_registered": 422,
    "model_not_offered": 422,
    "model_named_twice": 422,
    "model_not_askable_here": 409,
    "owner_choice_not_askable": 409,
    "choice_unknown": 422,
    "group_empty": 422,
    "group_person_unknown": 422,
    "seeds_out_of_range": 422,
    # The bound: above the most the comparison can cost, or more than this server's model budget
    # has left beside the part its decision contract keeps for other work.
    "bound_out_of_range": 422,
    "bound_over_budget": 409,
}


class StartRefused(ValueError):
    """A comparison that cannot be started, by a code of ``START_REFUSALS``."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in START_REFUSALS:
            raise ValueError(f"a start is refused only by a stated code, not {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    @property
    def status(self) -> int:
        return START_REFUSALS[self.code]


@dataclass(frozen=True, slots=True)
class ComparisonSelection:
    """What a comparison compares: its models, whether the first runs again as the control, the
    group its arms decide for, and how many development seeds it runs."""

    models: tuple[ComparisonArm, ...]
    control: bool
    #: Where the group comes from, one of ``GROUP_SOURCES``.
    group: str
    seed_count: int
    #: The owner's choice whose people are the group, for an ``owner_choice`` group.
    choice_seq: int | None = None
    #: The people of a ``named`` group, by subject id.
    people: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.group not in GROUP_SOURCES:
            raise ValueError(f"no group source {self.group!r}")
        if (self.group == "owner_choice") != (self.choice_seq is not None):
            raise ValueError("exactly an owner's choice group names a choice")
        if (self.group == "named") != (self.people is not None):
            raise ValueError("exactly a named group names people")
        if not 1 <= len(self.models) <= MODELS_MOST:
            raise ValueError(f"a comparison compares one to {MODELS_MOST} models")


def comparison_body(
    runner: SocietyComparisonRunner,
    models: Sequence[ComparisonArm],
    seeds: Sequence[str],
    *,
    control: bool,
    phase: str = PHASE,
    preregistration: dict[str, str] | None = None,
    group: Mapping[str, Any] | None = None,
    others: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """A definition's body: the group every arm decides for, what decides for everybody else
    (:meth:`~exulanica.api.society_comparison_runner.SocietyComparisonRunner.others_for`), the
    anchors, one arm per model, the control, and the claim."""
    catalogs = runner.catalogs
    arms: dict[str, dict[str, Any]] = {
        ROUTINE_ARM: {
            "role": "one",
            "decider": {"kind": "routine"},
            "provider_config": None,
            "answering": None,
            "description": "Their own routine",
        },
        WAIT_ARM: {
            "role": "zero",
            "decider": {"kind": "wait"},
            "provider_config": None,
            "answering": None,
            "description": "Waiting where they are",
        },
    }
    keys = []
    for index, model in enumerate(models):
        key = f"model_{chr(ord('a') + index)}"
        arms[key] = runner.model_arm(model, "candidate")
        keys.append(key)
    control_pair = None
    if control:
        arms[f"{keys[0]}_again"] = runner.model_arm(models[0], "control")
        control_pair = [keys[0], f"{keys[0]}_again"]
    family = [[ROUTINE_ARM, key] for key in keys]
    primary = family[0]
    if len(keys) >= 2:
        primary = [keys[0], keys[1]]
        family = [primary, *family]
    return {
        "window_ticks": protocol_value(catalogs, "window_ticks"),
        "phase": phase,
        "seeds": [seed_digest(seed) for seed in seeds],
        "group": dict(EVERYBODY if group is None else group),
        "others": [dict(other) for other in others],
        "arms": arms,
        "claim": {"primary": primary, "family": family, "control": control_pair},
        "preregistration": preregistration,
    }


def definition_body(
    runner: SocietyComparisonRunner,
    version_id: uuid.UUID,
    selection: ComparisonSelection,
    seeds: Sequence[str],
    *,
    connection: Any = None,
) -> dict[str, Any]:
    """The body of the comparison ``selection`` names over the version's society as it stands:
    its group from the world's records (an owner's choice by its sequence and digest), everybody
    else keeping what the owner's latest choice for them names, and ``seeds``, each of which the
    catalog commits to the development phase."""
    group: dict[str, Any] | None = None
    if selection.group == "owner_choice":
        assert selection.choice_seq is not None
        group = runner.group_of_choice(version_id, selection.choice_seq, connection=connection)
    elif selection.group == "named":
        assert selection.people is not None
        group = {"people": sorted(set(selection.people)), "source": {"kind": "named"}}
    others = runner.others_for(
        version_id, None if group is None else group["people"], connection=connection
    )
    return comparison_body(
        runner,
        list(selection.models),
        seeds,
        control=selection.control,
        group=group,
        others=others,
    )


def development_seeds_in(text: str, catalogs: ComparisonCatalogs) -> tuple[str, ...]:
    """The development seeds ``text`` holds, one per line, in the order the seed catalog commits
    them: a line is a seed only when the SHA-256 of its text is one the catalog commits to the
    development phase, so a held-out seed in the same text is never taken. Nothing prints one."""
    held = {seed_digest(line.strip()): line.strip() for line in text.splitlines() if line.strip()}
    return tuple(
        held[str(entry["seed_digest"])]
        for entry in catalogs.seeds.values()
        if entry["phase"] == PHASE and str(entry["seed_digest"]) in held
    )


@cache
def typical_per_person_hour() -> dict[str, Decimal]:
    """What one of a group's people cost for a simulated hour under each model the judged group
    comparison measured, by model id: each of that model's arms' recorded spend per simulated
    hour, averaged over its arms and divided by the group's people. A model it did not run has no
    figure, and neither has any model where the record is not beside this code."""
    path = _ROOT / TYPICAL_RECORD
    if not path.is_file():
        return {}
    record = json.loads(path.read_text(encoding="utf-8"))["record"]
    size = int(record["group"]["size"])
    spent: dict[str, list[Decimal]] = {}
    for arm in record["arms"]:
        cost = record["summaries"][arm["key"]]["cost_usd_per_hour"]
        if arm["decider"]["kind"] == "model" and cost is not None:
            spent.setdefault(arm["decider"]["model_id"], []).append(Decimal(cost))
    return {
        model_id: (sum(costs, Decimal(0)) / len(costs) / size).quantize(USD_QUANTUM)
        for model_id, costs in sorted(spent.items())
    }


@dataclass(frozen=True, slots=True)
class ComparisonCost:
    """What a comparison can cost at most, and what one like it typically costs."""

    runs: int
    #: The most asks its runs can make, and the calls they can take, each ask answered as often as
    #: the contract allows.
    asks: int
    calls: int
    #: The most they can cost: every ask at its bound.
    most_usd: Decimal
    #: The most one minute of any one of its runs can cost: what a run a host stopped part way
    #: may have spent on asks it never recorded.
    minute_usd: Decimal
    #: What they would cost at the measured figures (:func:`typical_per_person_hour`), or None
    #: when a model it asks has no figure.
    typical_usd: Decimal | None

    def document(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "asks_most": self.asks,
            "calls_most": self.calls,
            "most_usd": format(self.most_usd, "f"),
            "typical_usd": None if self.typical_usd is None else format(self.typical_usd, "f"),
            "typical_record": TYPICAL_RECORD,
        }


def comparison_cost(
    body: Mapping[str, Any],
    population: int,
    role: DecisionRole,
    budget: BudgetGuard,
    manifest: Manifest,
    *,
    runs_left: Sequence[tuple[str, str]] | None = None,
) -> ComparisonCost:
    """What the comparison ``body`` states can cost at most, over a society of ``population``
    people, asking ``role``: every run's asks at their bound. ``runs_left`` names the runs to
    count, by arm and seed digest; left out, every run the body plans."""
    contract = role.contract()
    window = int(body["window_ticks"])
    people = population if body["group"]["people"] is None else len(body["group"]["people"])
    others = [
        str(other["provider_config"]["model_id"])
        for other in body["others"]
        if other["provider_config"] is not None
    ]
    # Who a model asks in one run of each arm: the arm's model for the group, and in every arm the
    # model each owner chose for somebody outside it.
    asked = {
        key: [
            *(
                [(str(arm["provider_config"]["model_id"]), people)]
                if arm["provider_config"] is not None
                else []
            ),
            *((model_id, 1) for model_id in others),
        ]
        for key, arm in body["arms"].items()
    }
    runs = (
        [(key, digest) for digest in body["seeds"] for key in body["arms"]]
        if runs_left is None
        else list(runs_left)
    )
    offered = {
        spec.model_id: ask_bound_usd(role, budget, spec, contract)
        for spec in manifest.offered_models(role.chosen)
    }
    # A model the manifest no longer offers is asked nothing (the run stops by name before it
    # asks), and is counted at the dearest bound of the models it offers, so nothing it asked
    # before it was withdrawn is counted short.
    dearest = max(offered.values(), default=Decimal(0))
    bounds = {
        model_id: offered.get(model_id, dearest)
        for model_id in {model_id for pairs in asked.values() for model_id, _ in pairs}
    }
    typical = typical_per_person_hour()
    asks = 0
    most = Decimal(0)
    per_hour = Decimal(0)
    measured = True
    for key, _digest in runs:
        for model_id, subjects in asked[key]:
            asks += window * subjects
            most += window * subjects * bounds[model_id]
            if model_id in typical:
                per_hour += typical[model_id] * subjects
            else:
                measured = False
    return ComparisonCost(
        runs=len(runs),
        asks=asks,
        calls=asks * contract.value("answer_attempts_maximum"),
        most_usd=most,
        minute_usd=max(
            (
                sum((subjects * bounds[model_id] for model_id, subjects in pairs), Decimal(0))
                for pairs in asked.values()
            ),
            default=Decimal(0),
        ),
        typical_usd=(per_hour * window / MINUTES_PER_HOUR).quantize(USD_QUANTUM)
        if measured
        else None,
    )
