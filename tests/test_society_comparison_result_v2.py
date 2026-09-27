"""A second-version comparison's outcomes and served result, from runs played on the small square.

Runs of a group comparison are played through the real engine with a scripted model, their
outcomes built as the runner builds them (:func:`run_outcome`), and the comparison read as the
route reads it (:func:`comparison_result`). These tests hold what the served result promises the
page: the group and everybody else by name and decider, a score over the group alone, what each
arm's model answered beside every score it carries (counts, shares of its own turns and rates over
the routine run's choice points), the routine's choice points as the rates' one denominator, and
the verdict carrying whether two arms' answered shares differ.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import uuid
from typing import Any

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world.society_comparison import RunPlan, play
from exulanica.world.society_comparison_repository import seed_digest
from exulanica.world.society_comparison_result import (
    DEFINITION_PROFILES,
    RESULT_PROFILE,
    RUN_PROFILES,
    ComparisonRefused,
    check_definition_body,
    comparison_result,
    run_outcome,
    scoring_binding,
)
from exulanica.world.society_decision_contract import decision_contract

import living_square_support as square
from comparison_support import (
    FIRST_VERSIONS,
    SEEDS,
    development_body,
    model_arm,
    seeded_catalogs,
)

CATALOGS = seeded_catalogs()
CONTRACT = decision_contract()
DOCUMENT = square.compose(square.square_objects())
NAME = load_manifest().model_name
TICKS = int(CATALOGS.protocol["window_ticks"]["value"])  # type: ignore[call-overload]


class _Chooser:
    """A scripted model: the first offered action of the kind it is told."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def offerable(self, tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            option = next(o for o in request["context"]["options"] if o["kind"] == self.kind)
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


def _people() -> list[dict[str, Any]]:
    start = play(
        _plan_for(
            {"role": "one", "decider": {"kind": "routine"}, "provider_config": None}, SEEDS[0], None
        ),
        _Chooser("target"),
    ).start
    return [{"id": p["id"], "name": p["display_name"]} for p in start["inhabitants"]]


def _plan_for(arm: dict[str, Any], seed: str, group: frozenset[str] | None) -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"result-v2:{arm['role']}:{seed}:{id(arm)}"),
        society_id=square.SOCIETY,
        seed=seed,
        population=8,
        inputs=(DOCUMENT,),
        ticks=TICKS,
        decider=arm["decider"],
        provider_config=arm["provider_config"],
        contract=CONTRACT,
        group=group,
    )


@pytest.fixture(scope="module")
def compared():
    people = sorted(_people(), key=lambda person: person["id"])
    group = people[:4]
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
        "model_a_again": model_arm("control"),
    }
    definition = {
        "profile": DEFINITION_PROFILES[2],
        "document_sha256": "f" * 64,
        "phase": "development",
        "seeds": [seed_digest(seed) for seed in SEEDS],
        "window_ticks": TICKS,
        "population": 8,
        "group": {"people": group, "source": {"kind": "named"}},
        "others": [
            {
                "id": p["id"],
                "name": p["name"],
                "decider": {"kind": "routine"},
                "provider_config": None,
                "choice": None,
            }
            for p in people[4:]
        ],
        "arms": arms,
        "claim": {
            "primary": ["routine", "model_a"],
            "family": [["routine", "model_a"]],
            "control": ["model_a", "model_a_again"],
        },
        "preregistration": None,
        "scoring": scoring_binding(CATALOGS),
    }
    members = frozenset(person["id"] for person in group)
    runs = []
    choosers = {"model_a": "target", "model_a_again": "wait"}
    for seed in SEEDS:
        for key, arm in arms.items():
            plan = _plan_for(arm, seed, members)
            played = play(plan, _Chooser(choosers.get(key, "target")))
            calls = None
            if arm["decider"]["kind"] == "model":
                calls = {
                    "asked": len(played.receipts),
                    "first_answers_refused": 0,
                    "cost_usd": "0.00100000",
                    "cost_known": True,
                    "latencies_ms": [900] * len(played.receipts),
                }
            outcome = run_outcome(plan, definition, key, seed_digest(seed), played, calls, CATALOGS)
            runs.append(
                {
                    "run_id": uuid.uuid4(),
                    "arm": key,
                    "seed_digest": seed_digest(seed),
                    "status": "completed",
                    "outcome": outcome,
                }
            )
    row = {
        "comparison_id": uuid.uuid4(),
        "created_at": dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        "document": definition,
    }
    return definition, runs, comparison_result(row, runs, CATALOGS, model_name=NAME)


def test_an_outcome_records_the_groups_terms_and_the_routines_choice_points(compared):
    definition, runs, _result = compared
    group = {person["id"] for person in definition["group"]["people"]}
    for run in runs:
        terms = run["outcome"]["terms"]
        assert run["outcome"]["profile"] == RUN_PROFILES[2]
        assert set(terms["people"]) == group
        assert set(terms["others"]) == {other["id"] for other in definition["others"]}
        assert terms["choice_points"] > 0
    routine = [run for run in runs if run["arm"] == "routine"]
    assert all(run["outcome"]["terms"]["turns"] == 0 for run in routine)


def test_the_served_result_names_the_group_and_everybody_elses_decider(compared):
    definition, _runs, result = compared
    assert result["profile"] == RESULT_PROFILE
    assert result["score_version"] == 2
    assert result["group"]["people"] == definition["group"]["people"]
    assert result["group"]["size"] == 4
    assert [other["decider"] for other in result["others"]] == [{"kind": "routine"}] * 4
    model = next(arm for arm in result["arms"] if arm["key"] == "model_a")["decider"]
    assert model["name"] == NAME(model["model_id"])


def test_every_score_is_served_with_what_its_arms_model_answered(compared):
    _definition, runs, result = compared
    routine_points = {
        run["seed_digest"]: run["outcome"]["terms"]["choice_points"]
        for run in runs
        if run["arm"] == "routine"
    }
    for seed in result["seeds"]:
        for key, run in seed["runs"].items():
            reliability = run["reliability"]
            # The positive control: a model arm's run was asked and its turns counted.
            assert reliability is not None
            if key.startswith("model_"):
                assert reliability["turns"] > 0
                assert (
                    reliability["answered"]
                    + reliability["refused"]
                    + reliability["left_to_routine"]
                    == reliability["turns"]
                )
                assert set(reliability["shares"]) == {"answered", "refused", "left_to_routine"}
                # The rates' one denominator: the routine run's choice points on the same seed.
                assert reliability["routine_choice_points"] == routine_points[seed["seed_digest"]]
                assert set(reliability["per_routine_choice"]) == set(reliability["shares"])
            else:
                assert reliability["turns"] == 0 and reliability["shares"] is None
    for key, summary in result["summaries"].items():
        if summary["mean_score"] is not None and key.startswith("model_"):
            assert summary["reliability"]["shares"] is not None


def test_the_verdict_says_whether_two_arms_answered_shares_differ(compared):
    _definition, _runs, result = compared
    verdict = result["verdict"]
    assert (verdict["code"], verdict["reason"]) == ("not_judged", "development_seeds")
    # The primary pair holds the routine, which asks nobody: no answered share to compare.
    assert verdict["answered_shares_differ"] is None


# -- the verdict end to end, from synthetic second-version outcomes -------------------------------

HELD = [hashlib.sha256(f"held-v2-{index}".encode()).hexdigest() for index in range(4)]


def _terms(urgency: int, answered: int, turns: int) -> dict[str, Any]:
    return {
        "ticks": 60,
        "threshold": 750,
        "people": ["a", "b"],
        "urgency": urgency,
        "choice_points": 40,
        "turns": turns,
        "classes": {
            "answered": answered,
            "refused": 0,
            "not_answered": turns - answered,
            "not_applied": 0,
        },
        "reasons": {
            "not_answered": {"model_timed_out": turns - answered} if turns > answered else {},
            "not_applied": {},
            "refused": {},
        },
        "person_minutes": {"doing": 60, "waiting": 60, "walking": 0},
        "minutes_by_activity": {"rest": 60},
        "activities": {"a": 1, "b": 1},
        "others": [],
        "others_urgency": 0,
    }


def _held_out(answered: dict[str, int], catalogs, *, people=("a", "b"), wait=None):
    """A held-out second-version comparison of two models and a control over four seeds, each arm's
    model answering ``answered[arm]`` of 100 turns on every seed."""
    urgency = {
        "wait": wait or [20_000] * 4,
        "routine": [10_000] * 4,
        "model_a": [16_000, 15_000, 17_000, 16_500],
        "model_a_again": [16_000, 15_000, 17_000, 16_500],
        "model_b": [11_000, 10_500, 12_000, 11_200],
    }
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
    definition = {
        "profile": DEFINITION_PROFILES[2],
        "document_sha256": "c" * 64,
        "phase": "held_out",
        "seeds": HELD,
        "window_ticks": 60,
        "population": 2,
        "group": {"people": [{"id": p, "name": p} for p in people], "source": {"kind": "named"}},
        "others": [],
        "arms": arms,
        "claim": {
            "primary": ["model_a", "model_b"],
            "family": [["model_a", "model_b"], ["routine", "model_a"], ["routine", "model_b"]],
            "control": ["model_a", "model_a_again"],
        },
        "preregistration": {"record": "r", "record_sha256": "0" * 64},
        "scoring": scoring_binding(catalogs),
    }
    runs = [
        {
            "run_id": uuid.uuid4(),
            "arm": arm,
            "seed_digest": seed,
            "status": "completed",
            "outcome": {
                "terms": _terms(
                    urgency[arm][index], answered.get(arm, 0), 100 if arm in answered else 0
                ),
                "calls": None,
            },
        }
        for arm in arms
        for index, seed in enumerate(HELD)
    ]
    row = {
        "comparison_id": uuid.uuid4(),
        "created_at": dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        "document": definition,
    }
    return row, runs


def _with_held(catalogs):
    seeds = {
        f"held_{i}": {"phase": "held_out", "seed_digest": d, "reason": "A test seed."}
        for i, d in enumerate(HELD)
    }
    return dataclasses.replace(catalogs, seeds={**catalogs.seeds, **seeds})


@pytest.mark.parametrize(
    ("answered", "differ"),
    [
        ({"model_a": 90, "model_b": 50, "model_a_again": 89}, True),
        ({"model_a": 90, "model_b": 88, "model_a_again": 80}, False),
    ],
    ids=["apart", "within-control"],
)
def test_a_judged_verdict_says_whether_answered_shares_differ_end_to_end(answered, differ):
    catalogs = _with_held(CATALOGS)
    row, runs = _held_out(answered, catalogs)
    result = comparison_result(row, runs, catalogs, model_name=NAME)
    # The positive control: the comparison is judged, and the anchors score 0 and 1.
    assert result["verdict"]["code"] == "different"
    assert result["verdict"]["reason"] is None
    assert result["summaries"]["routine"]["mean_score"] == "1.0000"
    assert result["summaries"]["wait"]["mean_score"] == "0.0000"
    assert result["verdict"]["answered_shares_differ"] is differ
    shares = {
        arm: result["summaries"][arm]["reliability"]["shares"]["answered"] for arm in answered
    }
    assert shares == {arm: f"{count / 100:.4f}" for arm, count in answered.items()}


def test_a_seed_whose_anchors_spare_the_group_less_than_its_floor_is_excluded_by_name():
    catalogs = _with_held(CATALOGS)
    floor = 2 * int(catalogs.protocol["need_relief_floor_per_person"]["value"])  # type: ignore[call-overload]
    # The routine spares the group of two one short of their floor on the first seed, exactly
    # their floor on the second.
    row, runs = _held_out(
        {"model_a": 90, "model_b": 90, "model_a_again": 90},
        catalogs,
        wait=[10_000 + floor - 1, 10_000 + floor, 20_000, 20_000],
    )
    result = comparison_result(row, runs, catalogs, model_name=NAME)
    assert [seed["excluded"] for seed in result["seeds"]] == ["need_below_floor", None, None, None]
    assert {run["score"] for run in result["seeds"][0]["runs"].values()} == {None}
    assert result["seeds"][1]["runs"]["routine"]["score"] == "1.0000"


def test_an_outcome_that_scored_other_people_than_the_group_is_refused_by_name():
    catalogs = _with_held(CATALOGS)
    row, runs = _held_out(
        {"model_a": 90, "model_b": 90, "model_a_again": 90}, catalogs, people=("a", "c")
    )
    with pytest.raises(ComparisonRefused, match="scored_people_not_the_group"):
        comparison_result(row, runs, catalogs, model_name=NAME)


def _group_body(phase: str, catalogs, *, outside_model: bool):
    body = copy.deepcopy(development_body(catalogs))
    body["phase"] = phase
    body["group"] = {"people": ["a"], "source": {"kind": "named"}}
    arm = model_arm("candidate")
    body["others"] = [
        {
            "id": "b",
            "decider": arm["decider"] if outside_model else {"kind": "routine"},
            "provider_config": {**arm["provider_config"], "choice_seq": 1}
            if outside_model
            else None,
            "choice": {"choice_seq": 1, "document_sha256": "d" * 64} if outside_model else None,
        }
    ]
    if phase == "held_out":
        body["seeds"] = HELD
        body["arms"]["model_a_again"] = model_arm("control")
        body["claim"]["control"] = ["model_a", "model_a_again"]
        body["preregistration"] = {"record": "r", "record_sha256": "0" * 64}
    return body


def test_a_held_out_definition_keeps_everybody_outside_its_group_on_their_routine():
    catalogs = _with_held(CATALOGS)
    # The positive controls: a development comparison may have a model outside its group, and a
    # held-out one may have its outside people on their routine.
    check_definition_body(_group_body("development", catalogs, outside_model=True), catalogs)
    check_definition_body(_group_body("held_out", catalogs, outside_model=False), catalogs)
    with pytest.raises(ComparisonRefused, match="held_out_others_not_routine"):
        check_definition_body(_group_body("held_out", catalogs, outside_model=True), catalogs)


def test_a_definition_is_refused_catalogs_of_another_score_version():
    first = seeded_catalogs(versions=FIRST_VERSIONS)
    body = copy.deepcopy(development_body(first))
    with pytest.raises(ComparisonRefused, match="catalogs_not_the_definition_version"):
        check_definition_body(body, first)
