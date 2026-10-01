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
typically cost is a measurement, not a bound: a shipped catalog binds its source records and
their per-person-hour figures (:data:`TYPICAL_CATALOG`), served beside the most as that source's
figure (:func:`typical_per_person_hour`). How many of a
minute's asks one run can have answered is derived from the same record's answer times and the
decision contract (:func:`answers_per_minute`): a large group leaves the rest of a busy minute to
their routine, which the plan says rather than refuses.

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
from decimal import ROUND_CEILING, Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.api.decision_host import ask_bound_usd
from exulanica.api.society_comparison_runner import ComparisonArm, SocietyComparisonRunner
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import Manifest
from exulanica.models.spending import SpendingRefused
from exulanica.models.usage import USD_QUANTUM
from exulanica.world.decision_roles import DecisionContract, DecisionRole
from exulanica.world.society_catalogs import ComparisonCatalogs
from exulanica.world.society_comparison_repository import seed_digest
from exulanica.world.society_comparison_result import (
    GROUP_SOURCES,
    MINUTES_PER_HOUR,
    definition_role,
    protocol_value,
)

__all__ = [
    "EVERYBODY",
    "MODELS_MOST",
    "PHASE",
    "ROUTINE_ARM",
    "START_REFUSALS",
    "TYPICAL_FALLBACK",
    "TYPICAL_NAVIGATION",
    "TYPICAL_RECORD",
    "TYPICAL_RECORDS",
    "WAIT_ARM",
    "ComparisonCost",
    "ComparisonSelection",
    "StartRefused",
    "TypicalFigures",
    "answers_per_minute",
    "asked_providers",
    "comparison_body",
    "comparison_cost",
    "definition_body",
    "development_seeds",
    "development_seeds_in",
    "figures_for",
    "stopped_host_usd",
    "typical_figures",
    "typical_latency_ms",
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
#: The measurements a comparison's typical cost and answer times are read from, by the kind of
#: ground its society stands on (its input's navigation profile), each with the name of its
#: reader: the judged group comparison, whose model arms each decided for four people of the
#: starter world's small square for the protocol's hour over twelve held-out seeds, and one
#: development comparison of four people of a generated town, whose people are asked more often.
TYPICAL_CATALOG: Final = (
    _ROOT / "assets/catalogs/society-comparison-cost/society-comparison-typical-cost.v1.json"
)
_TYPICAL_DOCUMENT: Final = json.loads(TYPICAL_CATALOG.read_text(encoding="utf-8"))
if (
    _TYPICAL_DOCUMENT.get("catalog_id") != "society-comparison-typical-cost"
    or _TYPICAL_DOCUMENT.get("catalog_version") != 1
):
    raise ValueError("invalid comparison typical-cost catalog")
#: The shipped catalog owns each ground's source and extraction form.
TYPICAL_RECORDS: Final = {
    entry["navigation"]: (entry["source"], entry["extraction"])
    for entry in _TYPICAL_DOCUMENT["entries"]
}
TYPICAL_NAVIGATION: Final = _TYPICAL_DOCUMENT["default_navigation"]
TYPICAL_RECORD: Final = TYPICAL_RECORDS[TYPICAL_NAVIGATION][0]
TYPICAL_FALLBACK: Final = (
    "assets/catalogs/society-comparison-cost/society-comparison-typical-cost.v1.json"
    "#conservative-unmeasured"
)

#: Every way a start is refused, by the code it is answered with and its status. The plan route
#: answers the same codes in its body, and the page has words for each (``START_REFUSAL_WORDS`` in
#: web/packages/app/src/ui/society-comparison-start.ts, held to this mapping by a parity test).
START_REFUSALS: Final = {
    # This server: the seed catalog it defines comparisons under commits no development seed's text.
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
    # The society: its engine takes no comparison or hosts no such role; it holds more people, or
    # a model would decide for more of them, than one run's read may take by the protocol
    # (exulanica/world/society_comparison_reading.py).
    "engine_takes_no_comparison": 409,
    "role_not_hosted": 409,
    "population_over_comparison_bound": 409,
    "decided_over_comparison_bound": 409,
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
    # The input it freezes: a sequence the society holds no input at.
    "input_not_in_society": 422,
    # The bound: above the most the comparison can cost, or more than this server's model budget
    # has left beside the part its decision contract keeps for other work.
    "bound_out_of_range": 422,
    "bound_over_budget": 409,
    "calls_over_budget": 409,
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


def development_seeds(catalogs: ComparisonCatalogs) -> tuple[str, ...]:
    """The development seeds the seed catalog commits the text of, in its order: from its third
    version every development seed, so a comparison needs no file of seeds beside the server. A
    held-out seed's text is never committed (the catalog's schema refuses one)."""
    return tuple(
        str(entry["seed"])
        for entry in catalogs.seeds.values()
        if entry["phase"] == PHASE and "seed" in entry
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


def _judged_comparison(record: Mapping[str, Any]) -> tuple[dict[str, Decimal], dict[str, int]]:
    """A judged comparison's figures: each model's arms' recorded spend per simulated hour,
    averaged over its arms and divided by the group's people, and the slowest of its arms' 95th
    percentile answer times."""
    size = int(record["group"]["size"])
    spent: dict[str, list[Decimal]] = {}
    slowest: dict[str, int] = {}
    for arm in record["arms"]:
        if arm["decider"]["kind"] != "model":
            continue
        model_id = arm["decider"]["model_id"]
        summary = record["summaries"][arm["key"]]
        if summary["cost_usd_per_hour"] is not None:
            spent.setdefault(model_id, []).append(Decimal(summary["cost_usd_per_hour"]))
        if summary["latency_ms"]["p95"] is not None:
            slowest[model_id] = max(slowest.get(model_id, 0), int(summary["latency_ms"]["p95"]))
    per_person_hour = {
        model_id: (sum(costs, Decimal(0)) / len(costs) / size).quantize(USD_QUANTUM)
        for model_id, costs in sorted(spent.items())
    }
    return per_person_hour, dict(sorted(slowest.items()))


def _town_comparison_cost(record: Mapping[str, Any]) -> tuple[dict[str, Decimal], dict[str, int]]:
    """A town's measured figures (``scripts/record_town_comparison_cost.py``): each model's cost
    per person-hour and 95th percentile answer time, as the record states them."""
    models = record["models"]
    return (
        {
            model_id: Decimal(held["typical_usd_per_person_hour"])
            for model_id, held in models.items()
        },
        {
            model_id: int(held["latency_ms"]["p95"])
            for model_id, held in models.items()
            if held["latency_ms"]["p95"] is not None
        },
    )


#: How each form of measurement is read, by the name :data:`TYPICAL_RECORDS` gives it.
_TYPICAL_READERS: Final = {
    "judged_comparison": _judged_comparison,
    "town_comparison_cost": _town_comparison_cost,
}


@dataclass(frozen=True, slots=True)
class TypicalFigures:
    """What one person typically cost for a simulated hour under each model, and how long each
    model took to answer, as one measurement recorded them."""

    record: str
    per_person_hour: Mapping[str, Decimal]
    latency_p95_ms: Mapping[str, int]


@cache
def typical_figures(navigation: str | None = TYPICAL_NAVIGATION) -> TypicalFigures | None:
    """The typical figures measured on the kind of ground ``navigation`` names, or None where no
    measurement states it, or ``navigation`` is None (a
    society whose engine takes no inputs stands on no ground a measurement names)."""
    entry = TYPICAL_RECORDS.get(navigation)
    if entry is None:
        return None
    path, form = entry
    found = next(
        (row for row in _TYPICAL_DOCUMENT["entries"] if row["navigation"] == navigation), None
    )
    if found is None or found["source"] != path or found["extraction"] != form:
        raise ValueError("typical-cost catalog source binding changed")
    models = found["models"]
    per_person_hour = {
        model_id: Decimal(value["usd_per_person_hour"]) for model_id, value in models.items()
    }
    latency = {
        model_id: int(value["latency_p95_ms"])
        for model_id, value in models.items()
        if value["latency_p95_ms"] is not None
    }
    return TypicalFigures(path, per_person_hour, latency)


def _conservative_figures() -> TypicalFigures:
    cost: dict[str, Decimal] = {}
    latency: dict[str, int] = {}
    for navigation in TYPICAL_RECORDS:
        measured = typical_figures(navigation)
        if measured is None:
            continue
        for model, value in measured.per_person_hour.items():
            cost[model] = max(cost.get(model, value), value)
        for model, value in measured.latency_p95_ms.items():
            latency[model] = max(latency.get(model, value), value)
    return TypicalFigures(TYPICAL_FALLBACK, cost, latency)


def figures_for(
    navigation: str | None, model_ids: Sequence[str]
) -> tuple[TypicalFigures | None, bool]:
    """The figures a plan of ``model_ids`` over a society on ``navigation``'s ground reads, and
    whether they were measured on that ground: its own measurement where it states every model,
    otherwise the small square's, which does not match any other ground."""
    own = None if navigation is None else typical_figures(navigation)
    if own is not None and all(model_id in own.per_person_hour for model_id in model_ids):
        return own, True
    return _conservative_figures(), False


def typical_latency_ms(navigation: str | None = TYPICAL_NAVIGATION) -> dict[str, int]:
    """How long each model a measurement ran took to answer one of a group's people, by model id:
    its 95th percentile answer time on ``navigation``'s ground, else on the small square. A model
    neither measured has no figure."""
    merged = dict(_conservative_figures().latency_p95_ms)
    merged.update((typical_figures(navigation) or _NONE).latency_p95_ms)
    return dict(sorted(merged.items()))


def answers_per_minute(
    contract: DecisionContract, model_id: str, navigation: str | None = TYPICAL_NAVIGATION
) -> int | None:
    """How many asks one run's minute can have answered by ``model_id``: the contract's concurrent
    calls, each answering one ask after another at the model's measured answer time on the
    society's ground (:func:`typical_latency_ms`), within the one deadline the minute's asks share.
    Asks past it are left to the routine. None for a model with no measured answer time."""
    latency = typical_latency_ms(navigation).get(model_id)
    if latency is None or latency < 1:
        return None
    return contract.value("concurrent_calls_maximum") * (
        contract.value("decision_deadline_ms") // latency
    )


def typical_per_person_hour(navigation: str | None = TYPICAL_NAVIGATION) -> dict[str, Decimal]:
    """What one of a group's people cost for a simulated hour under each model, by model id: as
    measured on ``navigation``'s ground where it was, else on the small square. A model neither
    measured has no figure."""
    merged = dict(_conservative_figures().per_person_hour)
    merged.update((typical_figures(navigation) or _NONE).per_person_hour)
    return dict(sorted(merged.items()))


def dearest_per_person_hour() -> dict[str, Decimal]:
    """Each model's dearest figure per person-hour over every ground a measurement names."""
    dearest: dict[str, Decimal] = {}
    for navigation in TYPICAL_RECORDS:
        for model_id, figure in (typical_figures(navigation) or _NONE).per_person_hour.items():
            dearest[model_id] = max(figure, dearest.get(model_id, figure))
    return dict(sorted(dearest.items()))


#: No measurement: no figures.
_NONE: Final = TypicalFigures(record="", per_person_hour={}, latency_p95_ms={})


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
    #: The most the asks of the runs played at once can hold reserved together: the protocol's
    #: runs at once, the dearest of the runs counted, each asking at most the contract's concurrent
    #: calls at once, each held at its model's bound until its usage is recorded
    #: (``BoundedBudget``).
    held_usd: Decimal

    #: Whether the typical figure was measured on the kind of ground this society stands on.
    typical_matches: bool
    #: The measurement the typical figure was read from.
    typical_record: str

    @property
    def suggested_usd(self) -> Decimal | None:
        """The least bound that lets a comparison spending the typical figure finish: that spend
        and room for the most its runs can hold reserved at once, since a run asks a minute only
        while what it would hold still fits. Derived, never measured; it promises a finish only
        where the typical figure was measured on this society's kind of ground
        (:attr:`typical_matches`), and it is None where the typical figure is unknown."""
        return None if self.typical_usd is None else self.typical_usd + self.held_usd

    def document(self) -> dict[str, Any]:
        suggested = self.suggested_usd
        return {
            "runs": self.runs,
            "asks_most": self.asks,
            "calls_most": self.calls,
            "most_usd": format(self.most_usd, "f"),
            "typical_usd": None if self.typical_usd is None else format(self.typical_usd, "f"),
            "typical_record": self.typical_record,
            "held_usd": format(self.held_usd, "f"),
            "suggested_usd": None if suggested is None else format(suggested, "f"),
            "typical_matches": self.typical_matches,
        }


def spending_plan_refusal(refused: SpendingRefused) -> dict[str, Any]:
    """A plan's statement of the refusal a start of it would be answered with where the durable
    spending authority refuses a provider it would ask: the 429 problem's code and detail, with the
    authority's ``spending`` member (``Services.allowance_refusal``)."""
    return {
        "code": "budget_exceeded",
        "detail": str(refused),
        "spending": refused.problem_member(),
    }


def asked_providers(body: Mapping[str, Any]) -> tuple[str, ...]:
    """Every provider a comparison ``body`` asks, each once and sorted: each model arm's, and in
    every arm the provider of the model an owner chose for somebody outside the group."""
    return tuple(
        sorted(
            {
                str(held["provider_config"]["provider"])
                for held in [*body["arms"].values(), *body["others"]]
                if held.get("provider_config") is not None
            }
        )
    )


def comparison_cost(
    body: Mapping[str, Any],
    population: int,
    role: DecisionRole,
    budget: BudgetGuard,
    manifest: Manifest,
    *,
    at_once: int,
    navigation_profile: str | None,
    runs_left: Sequence[tuple[str, str]] | None = None,
    dearest_elsewhere: bool = False,
) -> ComparisonCost:
    """What the comparison ``body`` states can cost at most, over a society of ``population``
    people, asking ``role``: every run's asks at their bound. ``at_once`` is how many runs are
    played at the same time (the protocol's ``runs_at_once``); ``navigation_profile`` is the kind
    of ground the society stands on, which says whether the typical figure was measured there
    (None where no reader is shown it). ``runs_left`` names the runs to
    count, by arm and seed digest; left out, every run the body plans. With
    ``dearest_elsewhere``, where the society's own ground has no figure for every model it asks,
    each model is taken at the dearest figure any ground has for it rather than the small
    square's, which a town's people are asked more often than: what a host admits a seed by."""
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
    figures, matches = figures_for(
        navigation_profile, sorted({model_id for pairs in asked.values() for model_id, _ in pairs})
    )
    typical = dict((figures or _NONE).per_person_hour)
    if dearest_elsewhere and not matches:
        typical = dearest_per_person_hour()
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
    # What each run counted can hold reserved at once: its minute's asks, at most the contract's
    # concurrent calls of them, each at the dearest bound among the models its arm asks. Runs are
    # counted one by one, so two seeds of one arm played at the same time hold twice.
    concurrent = contract.value("concurrent_calls_maximum")
    held_by_arm = {
        key: min(concurrent, sum(subjects for _model, subjects in pairs))
        * max((bounds[model_id] for model_id, _ in pairs), default=Decimal(0))
        for key, pairs in asked.items()
    }
    held_by_run = sorted((held_by_arm[key] for key, _digest in runs), reverse=True)
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
        held_usd=sum(held_by_run[: max(1, at_once)], Decimal(0)).quantize(
            USD_QUANTUM, rounding=ROUND_CEILING
        ),
        typical_matches=matches,
        typical_record=TYPICAL_RECORD if figures is None else figures.record,
    )


#: What prices asks where the caller has no budget of its own: estimating reads the manifest's
#: prices, never a ceiling.
_PRICES: Final = BudgetGuard(ceiling_usd=Decimal(0), max_calls=0)


def stopped_host_usd(
    definition: Mapping[str, Any],
    catalogs: ComparisonCatalogs,
    budget: BudgetGuard | None,
    manifest: Manifest,
    open_runs: Sequence[Mapping[str, Any]],
) -> Decimal:
    """The most a host whose lease ran out may have spent and never recorded: one minute of each
    open run it may have been playing, the protocol's ``runs_at_once`` at a time, at the most a
    minute of any of them can cost. What a claim that takes the start over presumes, and what a
    cancellation of such a start presumes."""
    if not open_runs:
        return Decimal(0)
    at_once = protocol_value(catalogs, "runs_at_once")
    cost = comparison_cost(
        definition,
        int(definition["population"]),
        definition_role(definition),
        budget if budget is not None else _PRICES,
        manifest,
        at_once=at_once,
        navigation_profile=None,
        runs_left=[(run["arm"], run["seed_digest"]) for run in open_runs],
    )
    in_flight = min(at_once, len(open_runs))
    return (in_flight * cost.minute_usd).quantize(USD_QUANTUM, rounding=ROUND_CEILING)
