"""What a comparison's records say, as the routes serve them, with no database.

``exulanica/world/society_comparison_result.py`` checks a definition before it is stored, reads a
comparison's scores from its runs' outcomes, and gives the server's verdict. These tests hold the
refusals a definition meets, the order the verdict's cases take (a comparison with a run missing is
incomplete before anything else; development seeds, scoring code other than the registered code
and too few scored seeds are each not judged, by name), and how a value is written.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import uuid
from fractions import Fraction
from typing import Any

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world.society_comparison_result import (
    ComparisonRefused,
    check_definition_body,
    comparison_result,
    decimal_text,
    scoring_binding,
)

from comparison_support import SEEDS, development_body, model_arm, seeded_catalogs

CATALOGS = seeded_catalogs()
#: The rule every served document names a model by.
NAME = load_manifest().model_name
DIGESTS = [hashlib.sha256(seed.encode()).hexdigest() for seed in SEEDS]
MORE = [hashlib.sha256(f"more-{index}".encode()).hexdigest() for index in range(4)]


def _catalogs_with(*digests: str, phase: str = "held_out"):
    seeds = {
        f"seed_{index}": {"phase": phase, "seed_digest": digest, "reason": "A test seed."}
        for index, digest in enumerate(digests)
    }
    return dataclasses.replace(CATALOGS, seeds={**CATALOGS.seeds, **seeds})


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda b: b.update(seeds=[hashlib.sha256(b"elsewhere").hexdigest()]),
            "seeds_not_committed",
        ),
        (lambda b: b.update(seeds=[DIGESTS[0], DIGESTS[0]]), "seeds_not_committed"),
        (lambda b: b.update(window_ticks=30), "window_not_the_protocol"),
        (lambda b: b["arms"].pop("wait"), "arms_not_anchored"),
        (lambda b: b["arms"].pop("model_a"), "no_candidate"),
        (lambda b: b["arms"]["routine"].update(decider={"kind": "wait"}), "arm_decider"),
        (
            lambda b: b["arms"]["model_a"]["provider_config"].update(model_id="another/model"),
            "arm_provider",
        ),
        (
            lambda b: b["arms"].update(
                again={
                    **model_arm("control"),
                    "decider": {"kind": "model", "provider": "p", "model_id": "m"},
                }
            ),
            "arm_provider",
        ),
        (lambda b: b["claim"].update(primary=["routine", "wait"]), "claim_arms"),
        (lambda b: b.update(phase="held_out"), "seeds_not_committed"),
    ],
    ids=[
        "seed-not-committed",
        "seed-twice",
        "window",
        "no-zero",
        "no-candidate",
        "anchor-decider",
        "config-model",
        "control-config",
        "primary-not-in-family",
        "held-out-seeds",
    ],
)
def test_a_definition_this_code_cannot_run_or_judge_is_refused_by_name(change, code):
    body = copy.deepcopy(development_body(CATALOGS))
    check_definition_body(body, CATALOGS)  # the positive control: the body as made is accepted
    change(body)
    with pytest.raises(ComparisonRefused, match=code):
        check_definition_body(body, CATALOGS)


def test_a_held_out_comparison_registers_a_claim_with_a_control_before_it_runs():
    catalogs = _catalogs_with(*MORE)
    body = copy.deepcopy(development_body(catalogs))
    body.update(phase="held_out", seeds=MORE)
    with pytest.raises(ComparisonRefused, match="claim_not_registered"):
        check_definition_body({**body, "claim": None}, catalogs)
    with pytest.raises(ComparisonRefused, match="claim_not_registered"):
        check_definition_body(body, catalogs)
    body["arms"]["model_a_again"] = model_arm("control")
    body["claim"]["control"] = ["model_a", "model_a_again"]
    with pytest.raises(ComparisonRefused, match="claim_not_registered"):
        check_definition_body(body, catalogs)
    body["preregistration"] = {"record": "a registered record", "record_sha256": "0" * 64}
    check_definition_body(body, catalogs)


# -- the verdict ----------------------------------------------------------------------------------


def _terms(urgency: int, *, turns: int = 0) -> dict[str, Any]:
    return {
        "ticks": 60,
        "threshold": 750,
        "people": ["a", "b"],
        "urgency": urgency,
        "turns": turns,
        "applied": turns,
        "counted": {"turns_refused": 0, "turns_unanswered": 0},
        "not_applied_reasons": {},
        "person_minutes": {"doing": 60, "waiting": 60, "walking": 0},
        "activities": {"a": 1, "b": 1},
    }


def _comparison(phase: str, seeds: list[str], urgencies: dict[str, list[int]], **definition):
    """A comparison's row and runs, each arm's urgency on each seed given, every run completed."""
    arms = {
        "routine": {
            "role": "one",
            "decider": {"kind": "routine"},
            "provider_config": None,
            "description": "Their own routine",
        },
        "wait": {
            "role": "zero",
            "decider": {"kind": "wait"},
            "provider_config": None,
            "description": "Waiting where they are",
        },
        "model_a": model_arm("candidate"),
        "model_b": {**model_arm("candidate"), "description": "Another model"},
        "model_a_again": model_arm("control"),
    }
    document = {
        "document_sha256": "d" * 64,
        "phase": phase,
        "seeds": seeds,
        "window_ticks": 60,
        "population": 2,
        "arms": arms,
        "claim": {
            "primary": ["model_a", "model_b"],
            "family": [["model_a", "model_b"], ["routine", "model_a"], ["routine", "model_b"]],
            "control": ["model_a", "model_a_again"],
        },
        "preregistration": None
        if phase == "development"
        else {"record": "r", "record_sha256": "0" * 64},
        "scoring": scoring_binding(CATALOGS),
        **definition,
    }
    row = {
        "comparison_id": uuid.uuid4(),
        "created_at": dt.datetime(2026, 9, 26, tzinfo=dt.UTC),
        "document": document,
    }
    runs = [
        {
            "run_id": uuid.uuid4(),
            "arm": arm,
            "seed_digest": seed,
            "status": "completed",
            "outcome": {"terms": _terms(urgencies[arm][index]), "calls": None},
        }
        for arm in arms
        for index, seed in enumerate(seeds)
    ]
    return row, runs


#: Waiting leaves 20,000 above the threshold on every seed and the routine 10,000; model_b spares
#: more than model_a on every seed, and model_a's repeat is model_a to the minute.
CLEAR = {
    "wait": [20_000] * 4,
    "routine": [10_000] * 4,
    "model_a": [16_000, 15_000, 17_000, 16_500],
    "model_a_again": [16_000, 15_000, 17_000, 16_500],
    "model_b": [11_000, 10_500, 12_000, 11_200],
}


def test_a_registration_belongs_to_a_held_out_comparison_and_is_refused_by_name_elsewhere():
    """0113 holds that a definition names a pre-registration exactly when it is held out, as an
    object; each side of that rule is refused here by name before it is a database error."""
    registered = {"record": "a registered record", "record_sha256": "a" * 64}
    development = copy.deepcopy(development_body(CATALOGS))
    check_definition_body(development, CATALOGS)  # the positive control
    with pytest.raises(ComparisonRefused, match="preregistration_not_held_out"):
        check_definition_body({**development, "preregistration": registered}, CATALOGS)
    catalogs = _catalogs_with(*MORE)
    held = copy.deepcopy(development_body(catalogs))
    held.update(phase="held_out", seeds=MORE, preregistration=registered)
    held["arms"]["model_a_again"] = model_arm("control")
    held["claim"]["control"] = ["model_a", "model_a_again"]
    check_definition_body(held, catalogs)  # the positive control
    with pytest.raises(ComparisonRefused, match="claim_not_registered"):
        check_definition_body({**held, "preregistration": "a registered record"}, catalogs)


def test_a_held_out_comparison_scored_under_its_own_code_is_judged():
    row, runs = _comparison("held_out", MORE, CLEAR)
    result = comparison_result(row, runs, _catalogs_with(*MORE), model_name=NAME)
    assert result["verdict"] == {"code": "different", "higher": "model_b", "reason": None}
    assert result["summaries"]["routine"]["mean_score"] == "1.0000"
    assert result["summaries"]["wait"]["mean_score"] == "0.0000"
    assert result["control_bound"] == "0.0000"


def test_a_model_arm_is_named_by_the_manifest_and_an_anchor_names_no_model():
    row, runs = _comparison("held_out", MORE, CLEAR)
    arms = comparison_result(row, runs, _catalogs_with(*MORE), model_name=NAME)["arms"]
    deciders = {arm["key"]: arm["decider"] for arm in arms}
    for key in ("model_a", "model_a_again", "model_b"):
        assert deciders[key]["name"] == NAME(deciders[key]["model_id"])
        assert deciders[key]["name"] != deciders[key]["model_id"]
    assert deciders["routine"] == {"kind": "routine"}
    assert deciders["wait"] == {"kind": "wait"}


def test_a_run_missing_makes_a_comparison_incomplete_before_anything_else():
    row, runs = _comparison("development", MORE, CLEAR)
    runs[3]["status"] = None
    result = comparison_result(
        row, runs, _catalogs_with(*MORE, phase="development"), model_name=NAME
    )
    assert result["verdict"] == {"code": "incomplete", "higher": None, "reason": None}


def test_development_seeds_are_never_judged_and_their_differences_still_shown():
    row, runs = _comparison("development", MORE, CLEAR)
    result = comparison_result(
        row, runs, _catalogs_with(*MORE, phase="development"), model_name=NAME
    )
    assert result["verdict"] == {
        "code": "not_judged",
        "higher": None,
        "reason": "development_seeds",
    }
    assert len(result["differences"]) == 3


def test_a_comparison_read_under_other_scoring_code_is_not_judged():
    other = {**scoring_binding(CATALOGS), "scorer_sha256": "0" * 64}
    row, runs = _comparison("held_out", MORE, CLEAR, scoring=other)
    result = comparison_result(row, runs, _catalogs_with(*MORE), model_name=NAME)
    assert result["verdict"]["code"] == "not_judged"
    assert result["verdict"]["reason"] == "scored_under_other_code"


def test_seeds_under_the_floor_leave_too_few_to_judge_and_are_named():
    barely = {**CLEAR, "wait": [20_000, 10_100, 10_100, 10_100]}
    row, runs = _comparison("held_out", MORE, barely)
    result = comparison_result(row, runs, _catalogs_with(*MORE), model_name=NAME)
    assert [seed["excluded"] for seed in result["seeds"]] == [
        None,
        "need_below_floor",
        "need_below_floor",
        "need_below_floor",
    ]
    assert result["verdict"] == {
        "code": "not_judged",
        "higher": None,
        "reason": "too_few_seeds_scored",
    }


def test_a_value_is_written_exactly_to_four_places_half_to_even():
    assert decimal_text(Fraction(-1, 4)) == "-0.2500"
    assert decimal_text(Fraction(5, 4)) == "1.2500"
    assert decimal_text(Fraction(1, 80000)) == "0.0000"
    assert decimal_text(Fraction(3, 80000)) == "0.0000"
    assert decimal_text(Fraction(5, 80000)) == "0.0001"
    assert decimal_text(Fraction(0)) == "0.0000"
    assert decimal_text(Fraction(-1, 3)) == "-0.3333"
