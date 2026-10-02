"""The third score of a person in a world: half need relief, half variety, read from states alone.

The second score did not separate two models whose people's hours differed widely, since choices
made while rested neither earn nor cost need. The third weighs how many different kinds of thing
each person of the group did beside it, anchored as need relief is. These tests hold the terms, the
catalog's declaration, the served result's integer terms and reasons, the protocol read as data and
the binding the third score registers.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import shutil
import uuid
from fractions import Fraction
from typing import Any

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world import society_score_v3
from exulanica.world.society_catalogs import (
    COMPARISON_VERSIONS,
    DAY_COMPARISON_VERSIONS,
    ROUTINE_DIRECTORY,
    _versions_present,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison_result import (
    BINDING_PROFILES,
    DEFINITION_PROFILES,
    binding_holds,
    comparison_result,
    listing_document,
    scoring_binding,
)
from exulanica.world.society_comparison_verdict import (
    PROTOCOL_READS,
    ComparisonRefused,
    protocol_value,
    protocol_values,
)
from exulanica.world.society_score import ScoreRefused
from exulanica.world.society_score_v2 import RunTerms

from comparison_support import SECOND_SCORE_VERSIONS, model_arm, seeded_catalogs

CATALOGS = seeded_catalogs()
SECOND = seeded_catalogs(versions=SECOND_SCORE_VERSIONS)
NAME = load_manifest().model_name
FLOOR = int(CATALOGS.protocol["need_relief_floor_per_person"]["value"])  # type: ignore[call-overload]
HELD = [hashlib.sha256(f"held-v3-{index}".encode()).hexdigest() for index in range(4)]


def _run(urgency: int, kinds: tuple[int, int], *, answered: int = 0, turns: int = 0) -> RunTerms:
    return RunTerms.from_document(_terms(urgency, kinds, answered=answered, turns=turns))


def _terms(
    urgency: int,
    kinds: tuple[int, int],
    *,
    answered: int = 0,
    turns: int = 0,
    timed_out: int = 0,
) -> dict[str, Any]:
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
            "not_answered": timed_out,
            "not_applied": turns - answered - timed_out,
        },
        "reasons": {
            "not_answered": {"model_timed_out": timed_out} if timed_out else {},
            "not_applied": {"stale": turns - answered - timed_out}
            if turns - answered - timed_out
            else {},
            "refused": {},
        },
        "person_minutes": {"doing": 60, "waiting": 60, "walking": 0},
        "minutes_by_activity": {"rest": 60},
        "activities": {"a": kinds[0], "b": kinds[1]},
        "others": [],
        "others_urgency": 0,
    }


SCORE = society_score_v3.person_score(CATALOGS.score)
WAIT = _run(20_000, (0, 0))
ROUTINE = _run(10_000, (3, 3))


def test_the_committed_catalog_weighs_need_relief_and_variety_half_each():
    assert CATALOGS.versions["society-person-score"] == society_score_v3.CATALOG_VERSION
    assert SCORE.weights == {"need_relief": 500, "variety": 500}


def test_the_anchors_score_zero_and_one_and_each_term_is_apart():
    for run, expected in ((WAIT, 0), (ROUTINE, 1)):
        found = society_score_v3.seed_score(
            run, waiting=WAIT, routine=ROUTINE, score=SCORE, floor_per_person=FLOOR
        )
        assert (found.need_relief, found.variety, found.score) == (expected, expected, expected)


def test_equal_need_relief_is_told_apart_by_variety():
    # The second score's blind spot: both runs spare the group exactly the routine's need, and
    # one of them had its people do one kind of thing each, the other four.
    sitting = society_score_v3.seed_score(
        _run(10_000, (1, 1)), waiting=WAIT, routine=ROUTINE, score=SCORE, floor_per_person=FLOOR
    )
    varied = society_score_v3.seed_score(
        _run(10_000, (4, 4)), waiting=WAIT, routine=ROUTINE, score=SCORE, floor_per_person=FLOOR
    )
    assert sitting.need_relief == varied.need_relief == 1
    assert (sitting.variety, varied.variety) == (Fraction(1, 3), Fraction(4, 3))
    assert (sitting.score, varied.score) == (Fraction(2, 3), Fraction(7, 6))


def test_a_seed_below_the_floor_or_with_no_variety_to_spare_is_excluded_by_name():
    short = _run(20_000 - 2 * FLOOR + 1, (3, 3))
    below = society_score_v3.seed_score(
        _run(15_000, (2, 2)), waiting=WAIT, routine=short, score=SCORE, floor_per_person=FLOOR
    )
    assert (below.excluded, below.score) == ("need_below_floor", None)
    flat = society_score_v3.seed_score(
        _run(15_000, (2, 2)),
        waiting=WAIT,
        routine=_run(10_000, (0, 0)),
        score=SCORE,
        floor_per_person=FLOOR,
    )
    assert (flat.excluded, flat.score) == (society_score_v3.NO_VARIETY, None)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda e: e.pop("variety"), "score_terms_not_computed"),
        (lambda e: e["variety"].update(weight_milli=400), "score_weights_not_whole"),
        (lambda e: e["variety"].update(reads="events"), "score_terms_not_computed"),
    ],
    ids=["no-variety", "weights-not-whole", "variety-reads-events"],
)
def test_a_catalog_declaring_another_score_is_refused_by_name(change, code):
    entries = {key: dict(entry) for key, entry in CATALOGS.score.items()}
    change(entries)
    with pytest.raises(ScoreRefused, match=code):
        society_score_v3.person_score(entries)


# -- the served result, end to end -----------------------------------------------------------------


def _held_out(catalogs) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A held-out comparison of two models and a control over four seeds, in which every model
    spares the group exactly the routine's need, as the second judged comparison's models did, and
    the second model's people each did three kinds of thing where the first's did one."""
    kinds = {
        "wait": (0, 0),
        "routine": (3, 3),
        "model_a": (1, 1),
        "model_a_again": (1, 1),
        "model_b": (3, 3),
    }
    urgency = {"wait": 20_000}
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
        "document_sha256": "d" * 64,
        "phase": "held_out",
        "seeds": HELD,
        "window_ticks": 60,
        "population": 2,
        "group": {
            "people": [{"id": p, "name": p} for p in ("a", "b")],
            "source": {"kind": "named"},
        },
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
    asks = {"model_a": 50, "model_b": 50, "model_a_again": 50}
    runs = [
        {
            "run_id": uuid.uuid4(),
            "arm": arm,
            "seed_digest": seed,
            "status": "completed",
            "outcome": {
                "terms": _terms(
                    urgency.get(arm, 10_000),
                    kinds[arm],
                    answered=asks.get(arm, 0) - (3 if arm in asks else 0),
                    turns=asks.get(arm, 0),
                    timed_out=2 if arm in asks else 0,
                ),
                "calls": None,
            },
        }
        for arm in arms
        for seed in HELD
    ]
    row = {
        "comparison_id": uuid.uuid4(),
        "created_at": dt.datetime(2026, 9, 30, tzinfo=dt.UTC),
        "document": definition,
    }
    return row, runs


def _with_held(catalogs):
    seeds = {
        f"held_{i}": {"phase": "held_out", "seed_digest": d, "reason": "A test seed."}
        for i, d in enumerate(HELD)
    }
    return dataclasses.replace(catalogs, seeds={**catalogs.seeds, **seeds})


def test_the_third_score_judges_a_difference_the_second_cannot_see():
    # The positive control: the same outcomes read under the second score, whose need relief is
    # all the models' alike, find no difference.
    second = _with_held(SECOND)
    row, runs = _held_out(second)
    assert comparison_result(row, runs, second, model_name=NAME)["verdict"]["code"] == (
        "no_measured_difference"
    )
    third = _with_held(CATALOGS)
    row, runs = _held_out(third)
    result = comparison_result(row, runs, third, model_name=NAME)
    assert result["score_version"] == 3
    assert (result["verdict"]["code"], result["verdict"]["higher"]) == ("different", "model_b")
    # The control pair ran the same model and did the same; the verdict's bound is theirs.
    assert result["control"] == ["model_a", "model_a_again"]
    assert result["control_bound"] == "0.0000"
    seed = result["seeds"][0]["runs"]
    assert seed["model_b"]["parts"] == {"need_relief": "1.0000", "variety": "1.0000"}
    assert seed["model_a"]["parts"] == {"need_relief": "1.0000", "variety": "0.3333"}
    assert seed["model_a"]["score"] == "0.6667"


def test_the_served_result_keeps_each_runs_integer_terms_and_reasons_by_class():
    third = _with_held(CATALOGS)
    row, runs = _held_out(third)
    run = comparison_result(row, runs, third, model_name=NAME)["seeds"][0]["runs"]["model_a"]
    assert run["terms"]["urgency"] == 10_000
    assert run["terms"]["variety"] == 2
    assert run["terms"]["people"] == 2
    assert run["terms"]["classes"] == {
        "answered": 47,
        "refused": 0,
        "not_answered": 2,
        "not_applied": 1,
    }
    # A turn given no answer in time is kept apart from one whose answer was not applied.
    assert run["reliability"]["reasons_by_class"] == {
        "not_answered": {"model_timed_out": 2},
        "not_applied": {"stale": 1},
        "refused": {},
    }


# -- the protocol, read as data ------------------------------------------------------------------


def test_each_protocol_version_states_only_values_a_reader_reads():
    day = DAY_COMPARISON_VERSIONS["society-comparison-protocol"]
    for version in _versions_present("society-comparison-protocol"):
        catalogs = load_comparison_catalogs(
            versions={**COMPARISON_VERSIONS, "society-comparison-protocol": version}
        )
        assert set(protocol_values(catalogs)) <= PROTOCOL_READS
        # Every version an hour's comparison has been defined under runs an hour; the day's, a day.
        assert protocol_value(catalogs, "window_ticks") == (1440 if version == day else 60)


def test_a_value_the_protocol_does_not_state_or_a_key_no_reader_reads_is_refused_by_name():
    first = load_comparison_catalogs(
        versions={**COMPARISON_VERSIONS, "society-comparison-protocol": 1}
    )
    with pytest.raises(ComparisonRefused, match=r"protocol_keys.*states no pair_replay_budget_ms"):
        protocol_value(first, "pair_replay_budget_ms")
    misspelt = dataclasses.replace(
        CATALOGS,
        protocol={**CATALOGS.protocol, "window_tick": CATALOGS.protocol["window_ticks"]},
    )
    with pytest.raises(ComparisonRefused, match=r"protocol_keys.*unread"):
        protocol_values(misspelt)


def test_a_protocol_version_is_claimed_by_its_file_alone(tmp_path):
    for path in ROUTINE_DIRECTORY.glob("society-comparison-protocol.v*.json"):
        shutil.copy(path, tmp_path / path.name)
    document = json.loads((tmp_path / "society-comparison-protocol.v3.json").read_text())
    document["catalog_version"] = 9
    (tmp_path / "society-comparison-protocol.v9.json").write_text(json.dumps(document))
    assert _versions_present("society-comparison-protocol", tmp_path) == (1, 2, 3, 4, 9)


# -- the binding ---------------------------------------------------------------------------------


def test_the_third_binding_names_the_third_score_beside_every_module_the_second_names():
    binding = scoring_binding()
    assert binding["profile"] == BINDING_PROFILES[3]
    second = scoring_binding(load_comparison_catalogs(versions=SECOND_SCORE_VERSIONS))
    assert set(binding["modules"]) == {*second["modules"], "exulanica.world.society_score_v3"}
    assert binding_holds(binding)
    changed = {**binding, "modules": {**binding["modules"]}}
    changed["modules"]["exulanica.world.society_score_v3"] = "0" * 64
    assert not binding_holds(changed)


def test_the_listing_names_the_score_a_comparison_recorded():
    # Two scores share the definition's second version; the listing reads the one it recorded.
    for catalogs, version in ((_with_held(SECOND), 2), (_with_held(CATALOGS), 3)):
        row, _runs = _held_out(catalogs)
        listed = listing_document([row], {}, model_name=NAME, starts={})["comparisons"][0]
        assert listed["score_version"] == version
