"""A comparison is judged only under the code and catalogs it registered, each under its own.

The first judged comparison registered the first binding: the three first-version catalogs and the
first scorer and claim modules, by digest (its pre-registration's ``scoring``). A second-version
comparison registers the second: its catalogs and every module its score and verdict are read by,
the verdict's assembly among them (``exulanica/world/society_comparison_verdict.py``). These tests
hold that the first judged comparison still reads as judged under its own binding, from the
committed records, that a second-version comparison stops being judged when any module it bound
changes, the verdict's assembly included, that a binding this code cannot read is refused by name,
and the rule by which a verdict says two arms' answered shares differ.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world import society_comparison_claim, society_score
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison_result import (
    DEFINITION_PROFILES,
    ComparisonRefused,
    binding_holds,
    comparison_result,
    scoring_binding,
)
from exulanica.world.society_comparison_verdict import _answered_differ

from comparison_support import (
    FIRST_PREREGISTRATION,
    FIRST_VERSIONS,
    SECOND_SCORE_VERSIONS,
    model_arm,
)

ROOT = Path(__file__).resolve().parents[1]
FIRST_RECORD = ROOT / "docs" / "evaluation" / "2026-09-26-society-model-comparison.json"
NAME = load_manifest().model_name


def _record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["record"]


def _terms(urgency: int) -> dict[str, Any]:
    return {
        "ticks": 60,
        "threshold": 750,
        "people": ["a", "b"],
        "urgency": urgency,
        "turns": 0,
        "applied": 0,
        "counted": {"turns_refused": 0, "turns_unanswered": 0},
        "not_applied_reasons": {},
        "person_minutes": {"doing": 60, "waiting": 60, "walking": 0},
        "activities": {"a": 1, "b": 1},
    }


#: Waiting leaves 20,000 above the threshold and the routine 10,000 on every seed; the second
#: model spares more than the first on every seed; the control is the first model to the minute.
URGENCY = {
    "wait": [20_000] * 4,
    "routine": [10_000] * 4,
    "model_a": [16_000, 15_000, 17_000, 16_500],
    "model_a_again": [16_000, 15_000, 17_000, 16_500],
    "model_b": [11_000, 10_500, 12_000, 11_200],
}


def _first_version(scoring: dict[str, Any], seeds: list[str]):
    """A held-out first-version comparison as the first judged comparison's definition stated it:
    its profile, its registered binding and a pre-registration; every run completed."""
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
        "profile": DEFINITION_PROFILES[1],
        "document_sha256": "e" * 64,
        "phase": "held_out",
        "seeds": seeds,
        "window_ticks": 60,
        "population": 2,
        "arms": arms,
        "claim": {
            "primary": ["model_a", "model_b"],
            "family": [["model_a", "model_b"], ["routine", "model_a"], ["routine", "model_b"]],
            "control": ["model_a", "model_a_again"],
        },
        "preregistration": {
            "record": str(FIRST_PREREGISTRATION.relative_to(ROOT)),
            "record_sha256": "0" * 64,
        },
        "scoring": scoring,
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
            "outcome": {"terms": _terms(URGENCY[arm][index]), "calls": None},
        }
        for arm in arms
        for index, seed in enumerate(seeds)
    ]
    return row, runs


def _held_out_first_seeds() -> list[str]:
    first = load_comparison_catalogs(versions=FIRST_VERSIONS)
    return [str(e["seed_digest"]) for e in first.seeds.values() if e["phase"] == "held_out"][:4]


def test_the_first_judged_comparison_still_reads_as_judged_under_its_own_binding():
    registered = _record(FIRST_PREREGISTRATION)["scoring"]
    # Its binding is the first binding computed now: the same catalogs, scorer and claim, byte
    # for byte, and the judged record's own tree names the same two modules.
    assert scoring_binding(load_comparison_catalogs(versions=FIRST_VERSIONS)) == registered
    assert binding_holds(registered)
    tree = _record(FIRST_RECORD)["tree"]["files_sha256"]
    for module in (society_score, society_comparison_claim):
        relative = str(Path(str(module.__file__)).resolve().relative_to(ROOT))
        assert tree[relative] == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    # And a first-version comparison registered under it reads as judged, read under the
    # committed catalogs at the versions it recorded.
    row, runs = _first_version(registered, _held_out_first_seeds())
    result = comparison_result(row, runs, model_name=NAME)
    assert result["score_version"] == 1
    assert result["verdict"]["reason"] is None
    assert result["verdict"]["code"] == "different"
    assert result["verdict"]["higher"] == "model_b"


def test_a_second_version_binding_holds_every_module_its_score_and_verdict_are_read_by():
    binding = scoring_binding(load_comparison_catalogs(versions=SECOND_SCORE_VERSIONS))
    assert set(binding["modules"]) == {
        "exulanica.world.society_score",
        "exulanica.world.society_score_v2",
        "exulanica.world.society_comparison_claim",
        "exulanica.world.society_comparison_verdict",
    }
    assert binding_holds(binding)
    for module in binding["modules"]:
        changed = {**binding, "modules": {**binding["modules"], module: "0" * 64}}
        assert not binding_holds(changed), module


def test_a_first_version_comparison_read_under_another_verdict_rule_is_still_its_own():
    """The first binding never named the verdict's assembly, so the assembly moving to its own
    module leaves a first-version comparison judged; the second binding names it."""
    registered = _record(FIRST_PREREGISTRATION)["scoring"]
    assert "modules" not in registered
    assert set(registered) == {"catalogs", "scorer_sha256", "claim_sha256"}


def test_a_comparison_read_under_other_code_is_not_judged_by_name():
    registered = _record(FIRST_PREREGISTRATION)["scoring"]
    other = {**registered, "claim_sha256": "0" * 64}
    row, runs = _first_version(other, _held_out_first_seeds())
    result = comparison_result(row, runs, model_name=NAME)
    assert (result["verdict"]["code"], result["verdict"]["reason"]) == (
        "not_judged",
        "scored_under_other_code",
    )


def test_a_binding_this_code_cannot_read_is_refused_by_name():
    with pytest.raises(ComparisonRefused, match="binding_unknown"):
        binding_holds({"profile": "exulanica.society-comparison-binding/v9", "catalogs": {}})
    registered = _record(FIRST_PREREGISTRATION)["scoring"]
    with pytest.raises(ComparisonRefused, match="binding_unknown"):
        binding_holds({**registered, "verdict_sha256": "0" * 64})


@pytest.mark.parametrize(
    ("shares", "expected"),
    [
        # The primary pair's answered shares differ by more than the control pair's: material.
        ({"a": Fraction(95, 100), "b": Fraction(80, 100), "again": Fraction(94, 100)}, True),
        # No more than the same model varies between two runs: not material.
        ({"a": Fraction(95, 100), "b": Fraction(90, 100), "again": Fraction(80, 100)}, False),
        # The control varied not at all: any difference counts, and none is none.
        ({"a": Fraction(1), "b": Fraction(99, 100), "again": Fraction(1)}, True),
        ({"a": Fraction(1), "b": Fraction(1), "again": Fraction(1)}, False),
        # An arm whose model was never asked has no answered share to compare.
        ({"a": None, "b": Fraction(1), "again": Fraction(1)}, None),
    ],
    ids=["beyond-control", "within-control", "any-over-a-still-control", "same", "unasked"],
)
def test_two_arms_answered_shares_differ_materially_beyond_the_control_pairs(shares, expected):
    assert _answered_differ(shares, ("a", "b"), ("a", "again")) is expected
    assert _answered_differ(shares, ("a", "b"), None) is None
