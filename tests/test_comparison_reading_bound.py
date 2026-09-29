"""The most people a comparison runs, and the most of them a model decides for, are derived from
the protocol's replay line, never stated, and a comparison beyond either is refused by name.

The third protocol version states the pair's budget and a measured line; the bounds here are
derived again from the catalog file's own numbers, apart from the module that reads them. The
first two versions state ``population_maximum`` and bound nothing else. Changing the verdict
module's protocol table moves the second binding's digest, so a held-out comparison registered
under it reads as scored under other code, while a development comparison reads exactly as before.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.society_comparison_start import START_REFUSALS
from exulanica.world.society_catalogs import COMPARISON_VERSIONS, load_comparison_catalogs
from exulanica.world.society_comparison_reading import (
    PAIR_RUNS,
    READING_REFUSALS,
    decided_maximum,
    decided_people,
    population_maximum,
    reading_refusal,
)
from exulanica.world.society_comparison_result import binding_holds, comparison_result
from exulanica.world.society_grounds import society_grounds

import test_society_comparison_binding as binding_tests

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_V3 = ROOT / "assets/catalogs/society/society-comparison-protocol.v3.json"
GROUP_PREREGISTRATION = (
    ROOT / "docs/evaluation/2026-09-26-society-group-comparison-preregistration.json"
)


def _line() -> dict[str, int]:
    """The third protocol's numbers, read from its file."""
    entries = json.loads(PROTOCOL_V3.read_text(encoding="utf-8"))["entries"]
    return {entry["key"]: entry["value"] for entry in entries}


def _derived(population: int | None = None) -> int:
    """The bound derived by hand: one run's share of the pair's budget, less the fixed cost, over
    what a person costs, and, for a population, what is left over what a decided person costs in a
    society of that many."""
    line = _line()
    run_us = line["pair_replay_budget_ms"] * 1000 // 2
    room = run_us - line["replay_fixed_ms"] * 1000
    if population is None:
        return room // line["replay_per_person_us"]
    left = room - line["replay_per_person_us"] * population
    decided = line["replay_per_decided_person_us"] + line["replay_per_decided_pair_us"] * population
    return max(0, min(population, left // decided))


def _with(catalogs, **values: int):
    protocol = {key: dict(entry) for key, entry in catalogs.protocol.items()}
    for key, value in values.items():
        protocol[key]["value"] = value
    return dataclasses.replace(catalogs, protocol=protocol)


def _body(group: list[str] | None, *, others_asked: int = 0) -> dict[str, Any]:
    model = {"provider_config": {"model_id": "a/one"}}
    return {
        "group": {"people": group},
        "others": [{"provider_config": {"model_id": "b/one"}}] * others_asked
        + [{"provider_config": None}],
        "arms": {
            "routine": {"provider_config": None},
            "wait": {"provider_config": None},
            "model_a": model,
            "model_a_again": model,
        },
    }


def test_a_new_comparison_is_defined_under_the_protocol_that_derives_its_bounds():
    assert COMPARISON_VERSIONS["society-comparison-protocol"] == 3
    assert PAIR_RUNS == 2


@pytest.mark.parametrize("population", [8, 30, 42, 58, 128])
def test_the_committed_bounds_are_the_ones_the_line_derives(population):
    catalogs = load_comparison_catalogs()
    assert population_maximum(catalogs) == _derived()
    assert decided_maximum(catalogs, population) == _derived(population)


def test_the_bound_that_applies_to_a_town_is_the_protocols():
    """A generated town's ground holds at most its figure, the tick budget; the most people a
    comparison runs is derived lower, so of the two it is the comparison's that bounds a town's
    comparison, and the documents say so."""
    towns = [ground for ground in society_grounds() if ground.population_rule == "residents"]
    assert towns, "a generated town's ground states its figure"
    most = population_maximum(load_comparison_catalogs())
    assert all(most < ground.population for ground in towns)
    assert f"at most {most} people" in (ROOT / "docs/society-experiments.md").read_text("utf-8")


def test_an_earlier_protocol_states_its_maximum_and_bounds_nothing_else():
    earlier = load_comparison_catalogs(
        versions={**COMPARISON_VERSIONS, "society-comparison-protocol": 2}
    )
    assert population_maximum(earlier) == 8
    assert decided_maximum(earlier, 8) == 8
    assert reading_refusal(earlier, 9) == (
        "population_over_comparison_bound",
        "9 people; a comparison runs at most 8",
    )


def test_who_a_model_decides_for_counts_the_group_and_everybody_else_asked():
    assert decided_people(_body(None), 40) == {
        "routine": 0,
        "wait": 0,
        "model_a": 40,
        "model_a_again": 40,
    }
    assert decided_people(_body(["p1", "p2", "p3"], others_asked=2), 40) == {
        "routine": 2,
        "wait": 2,
        "model_a": 5,
        "model_a_again": 5,
    }


def test_a_comparison_beyond_either_bound_is_refused_by_name():
    line = {
        "pair_replay_budget_ms": 10_000,
        "replay_fixed_ms": 1_000,
        "replay_per_person_us": 50_000,
        "replay_per_decided_person_us": 60_000,
        "replay_per_decided_pair_us": 1_000,
    }
    catalogs = _with(load_comparison_catalogs(), **line)
    # 4,000 ms left for people: at most 80 nobody decides for; at 40 people, 2,000 ms left and a
    # decided person costs 60 + 40 x 1 = 100 ms, so a model decides for at most 20 of them.
    assert population_maximum(catalogs) == 80
    assert decided_maximum(catalogs, 40) == 20
    assert reading_refusal(catalogs, 81)[0] == "population_over_comparison_bound"
    assert reading_refusal(catalogs, 40, _body([f"p{i}" for i in range(20)])) is None
    refused = reading_refusal(catalogs, 40, _body([f"p{i}" for i in range(19)], others_asked=2))
    assert refused is not None and refused[0] == "decided_over_comparison_bound"
    assert reading_refusal(catalogs, 40, _body(None))[0] == "decided_over_comparison_bound"


def test_every_reading_refusal_is_a_start_refusal():
    assert set(READING_REFUSALS) <= set(START_REFUSALS)


def test_the_second_binding_moved_so_only_a_held_out_comparison_reads_under_other_code():
    """The group comparison registered the second binding before the protocol's third version was
    added to the verdict module's table, so that binding no longer holds. A comparison read under
    a binding that does not hold is not judged by that name only when it ran on held-out seeds; one
    on development seeds reads by that reason first, exactly as before."""
    registered = json.loads(GROUP_PREREGISTRATION.read_text(encoding="utf-8"))["record"]["scoring"]
    assert not binding_holds(registered)
    stale = {**binding_tests._record(binding_tests.FIRST_PREREGISTRATION)["scoring"]}
    stale["claim_sha256"] = "0" * 64
    for phase, reason in (
        ("held_out", "scored_under_other_code"),
        ("development", "development_seeds"),
    ):
        row, runs = binding_tests._first_version(stale, binding_tests._held_out_first_seeds())
        row["document"]["phase"] = phase
        result = comparison_result(row, runs, model_name=binding_tests.NAME)
        assert (result["verdict"]["code"], result["verdict"]["reason"]) == ("not_judged", reason)


#: The protocol's replay keys, which one module reads.
REPLAY_KEYS = (
    "pair_replay_budget_ms",
    "replay_fixed_ms",
    "replay_per_person_us",
    "replay_per_decided_person_us",
    "replay_per_decided_pair_us",
)


def test_the_bounds_are_derived_in_one_place():
    """Only the reading module reads the replay line, and the verdict module's table names its
    keys; nothing else in the product or the page names them or restates a bound."""
    readers = {
        ROOT / "exulanica/world/society_comparison_reading.py",
        ROOT / "exulanica/world/society_comparison_verdict.py",
    }
    sources = [
        *ROOT.joinpath("exulanica").rglob("*.py"),
        *ROOT.joinpath("web/packages").glob("*/src/**/*.ts"),
    ]
    naming = sorted(
        str(path.relative_to(ROOT))
        for path in sources
        if path not in readers
        and any(key in path.read_text(encoding="utf-8") for key in REPLAY_KEYS)
    )
    assert naming == []
    # And the reading module is what the start and the repository refuse by.
    for module in (
        "exulanica/api/routes/society_comparisons.py",
        "exulanica/world/society_comparison_repository.py",
    ):
        text = (ROOT / module).read_text(encoding="utf-8")
        assert "reading_refusal(" in text and 'population_maximum"' not in text, module
