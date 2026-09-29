"""The least bound that lets a comparison finish is derived, served by the plan, and suggested.

A run's asks are each held at their model's bound until what they cost is known, and a run asks a
minute only while what it would hold still fits what is left of the bound, so a bound near the
typical spend stops the runs part way. The plan therefore serves, beside the most and the typical
figure, the most the runs played at once can hold reserved together and the least bound that lets a
comparison spending the typical figure finish: that spend and that room. Display only: nothing here
changes what a bound enforces. The figures are derived again here, apart from the code that serves
them, from the contract, each model's bound and the protocol's runs at once.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from exulanica.api.decision_host import ask_bound_usd
from exulanica.api.society_comparison_start import (
    TYPICAL_NAVIGATION,
    TYPICAL_RECORDS,
    comparison_cost,
    typical_per_person_hour,
)
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import load_manifest
from exulanica.world.society_decision_contract import person_role

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest()
ROLE = person_role()
#: Prices a model's asks with no ceiling, as the plan route does where no client asks.
ESTIMATOR = BudgetGuard(ceiling_usd=Decimal(0), max_calls=0)
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
QWEN = "Qwen/Qwen3-235B-A22B-Instruct-2507"
#: The kind of ground a generated town's people walk, where the typical figure was not measured.
TOWN = "city-walking-surfaces/v1"


def _arm(model_id: str | None) -> dict:
    return {"provider_config": None if model_id is None else {"model_id": model_id}}


def _body(first: str, second: str, group: int, *, others: int = 0) -> dict:
    return {
        "window_ticks": 60,
        "seeds": ["0" * 64],
        "group": {"people": [f"p{i}" for i in range(group)]},
        "others": [{"provider_config": {"model_id": QWEN}}] * others,
        "arms": {
            "routine": _arm(None),
            "wait": _arm(None),
            "model_a": _arm(first),
            "model_b": _arm(second),
            "model_a_again": _arm(first),
        },
    }


def _bound(model_id: str) -> Decimal:
    spec = next(spec for spec in MANIFEST.offered_models(ROLE.chosen) if spec.model_id == model_id)
    return ask_bound_usd(ROLE, ESTIMATOR, spec, ROLE.contract())


def test_the_finishing_bound_is_the_typical_spend_and_what_runs_at_once_can_hold():
    concurrent = ROLE.contract().value("concurrent_calls_maximum")
    cost = comparison_cost(
        _body(NANO, LIGHTNING, 4),
        48,
        ROLE,
        ESTIMATOR,
        MANIFEST,
        at_once=2,
        navigation_profile=TYPICAL_NAVIGATION,
    )
    # Each model arm holds at most its four people's asks at once; the two dearest runs held
    # together are one Nano and one Lightning run, or two Nano runs, whichever holds more.
    held = sorted([4 * _bound(NANO), 4 * _bound(LIGHTNING), 4 * _bound(NANO)], reverse=True)
    assert cost.held_usd == (held[0] + held[1]).quantize(Decimal("0.00000001"))
    typical = typical_per_person_hour()
    assert cost.typical_usd == ((2 * typical[NANO] + typical[LIGHTNING]) * 4).quantize(
        Decimal("0.00000001")
    )
    assert cost.suggested_usd == cost.typical_usd + cost.held_usd
    assert cost.suggested_usd < cost.most_usd
    assert cost.typical_matches is True
    served = cost.document()
    assert served["suggested_usd"] == format(cost.suggested_usd, "f")
    assert served["held_usd"] == format(cost.held_usd, "f")
    # A group larger than the contract's concurrent calls holds only that many asks at once, and
    # somebody outside it asked of a dearer model makes every arm hold at that model's bound.
    wide = comparison_cost(
        _body(NANO, LIGHTNING, 20, others=1),
        48,
        ROLE,
        ESTIMATOR,
        MANIFEST,
        at_once=2,
        navigation_profile=TOWN,
    )
    assert wide.held_usd == (2 * concurrent * _bound(QWEN)).quantize(Decimal("0.00000001"))


def test_one_run_at_once_holds_only_the_dearest_run():
    cost = comparison_cost(
        _body(QWEN, NANO, 4), 48, ROLE, ESTIMATOR, MANIFEST, at_once=1, navigation_profile=TOWN
    )
    assert cost.held_usd == (4 * _bound(QWEN)).quantize(Decimal("0.00000001"))


def test_a_comparison_with_no_typical_figure_suggests_no_finishing_bound():
    unmeasured = "deepseek-ai/DeepSeek-V4-Flash-0731"
    assert unmeasured not in typical_per_person_hour()
    cost = comparison_cost(
        _body(unmeasured, NANO, 4),
        48,
        ROLE,
        ESTIMATOR,
        MANIFEST,
        at_once=2,
        navigation_profile=TOWN,
    )
    assert cost.typical_usd is None and cost.suggested_usd is None
    assert cost.document()["suggested_usd"] is None


def test_a_society_is_planned_with_its_own_grounds_figures_or_promised_nothing():
    """The square's measurement ran on the starter world's lattice, and a town's on its walking
    surfaces, where people are asked more often: a town comparison of models its record measured
    reads the town's figures and may promise a finish; one asking a model only the square measured
    reads the square's and promises nothing."""
    from exulanica.world.society_grounds import society_ground_for_navigation

    assert society_ground_for_navigation(TYPICAL_NAVIGATION).key == "authored_starter"
    square = ROOT / "docs/evaluation/2026-09-26-society-group-comparison-preregistration.json"
    assert "starter world" in square.read_text(encoding="utf-8")
    town_record, _reader = TYPICAL_RECORDS[TOWN]
    measured = json.loads((ROOT / town_record).read_text(encoding="utf-8"))["record"]
    assert measured["navigation_profile"] == TOWN
    town = comparison_cost(
        _body(NANO, LIGHTNING, 4), 48, ROLE, ESTIMATOR, MANIFEST, at_once=2, navigation_profile=TOWN
    )
    assert (town.typical_matches, town.typical_record) == (True, town_record)
    per_hour = {
        model: Decimal(held["typical_usd_per_person_hour"])
        for model, held in measured["models"].items()
    }
    assert town.typical_usd == ((2 * per_hour[NANO] + per_hour[LIGHTNING]) * 4).quantize(
        Decimal("0.00000001")
    )
    assert per_hour[NANO] > typical_per_person_hour()[NANO]
    unmeasured = comparison_cost(
        _body(QWEN, NANO, 4), 48, ROLE, ESTIMATOR, MANIFEST, at_once=2, navigation_profile=TOWN
    )
    assert unmeasured.typical_matches is False
    assert unmeasured.typical_record == TYPICAL_RECORDS[TYPICAL_NAVIGATION][0]
    assert unmeasured.document()["typical_matches"] is False
