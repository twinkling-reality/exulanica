"""A day's protocol changes values only, and leaves every module an existing comparison bound alone.

A comparison over a living town's day is defined under the fourth protocol, whose window is a day
and whose floor is measured on a day's anchors, and the fifth score, the fourth's terms over a day
assembled from its hours. A new protocol version is its catalog's entries: these tests hold that the
fourth states only keys the verdict already reads, so the verdict module, which every binding since
the second names by digest, is unchanged; that the bindings the retained pre-registrations recorded
still hold, and so does the fourth binding a living town's hour registers, as main recorded it
before the day; that an hour's comparison is still defined under the third protocol, its family's
score and the fifth seeds; that a day's binding names the fourth's modules and the two that read a
day; and that the fourth protocol's floor is the one its record derived.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.models.manifest import load_manifest
from exulanica.world.society_catalogs import (
    COMPARISON_VERSIONS,
    DAY_COMPARISON_VERSIONS,
    comparison_catalogs_for_engine,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison_result import (
    binding_holds,
    comparison_result,
    scoring_binding,
)
from exulanica.world.society_comparison_verdict import (
    PROTOCOL_READS,
    ComparisonRefused,
    protocol_values,
)
from exulanica.world.society_living import LIVING_TOWN_PROFILE
from exulanica.world.society_planner import PURPOSEFUL_PROFILE
from exulanica.world.society_score_v4 import NEED_UNIT

from comparison_support import SEEDS, model_arm, seeded_catalogs

ROOT = Path(__file__).resolve().parents[1]
#: The record the fourth protocol's floor was derived from.
FLOOR_RECORD = ROOT / "docs" / "evaluation" / "2026-10-02-living-day-anchors.json"
#: The retained pre-registrations whose bindings name modules by digest.
REGISTERED = (
    "2026-09-26-society-model-comparison-preregistration.json",
    "2026-09-30-town-comparison-preregistration.json",
    "2026-09-30-town-comparison-2-preregistration.json",
)
#: The binding a living town's hour registered on main at 2d8ad511, before a day was defined: no
#: retained record names it, so it is held here, and a change to any module it names is a change
#: to every hour's comparison registered under it.
HOUR_BINDING_ON_MAIN = {
    "catalogs": {
        "sha256": "8afdf2c16d93c2c73fd9812eec191458d6287854084f58bdcaee45b396b6a459",
        "versions": {
            "society-comparison-protocol": 3,
            "society-comparison-seeds": 5,
            "society-person-score": 4,
        },
    },
    "modules": {
        "exulanica.world.society_comparison_claim": (
            "7f3ff0152129e64c501acbf4067514d694e4eb5ef644b48b25b319f73cff000a"
        ),
        "exulanica.world.society_comparison_verdict": (
            "a8ed6e639ad6ad2f3a5e30788a6a0c951396ea102cc9936ab61b05fc1bf44b47"
        ),
        "exulanica.world.society_comparison_verdict_v4": (
            "e0c958479a43120c68956475e9d595725f182b2099f7a90d4085c5102dd8f48a"
        ),
        "exulanica.world.society_score": (
            "561e6242bdb601559215e234a40e29429b9d26967a548e5bfdf166006194c010"
        ),
        "exulanica.world.society_score_v2": (
            "a75bc8f3dae5f61a9202acf5097224aecf807676a7260b3eba88c6e99592b110"
        ),
        "exulanica.world.society_score_v3": (
            "9fd6402972feeec0d5f3174be3ae94fcaddf1b249660578d0255b91727c3cea8"
        ),
        "exulanica.world.society_score_v4": (
            "e78a09cbe34022184d53ba7c9a2d952d0f6497adef2d46e677e5e44d367854da"
        ),
    },
    "profile": "exulanica.society-comparison-binding/v4",
}
#: The replay line the third protocol states for the purposeful engine; a living town's day is
#: read by its own measured line, so the fourth states none of it.
PURPOSEFUL_LINE = {
    "replay_fixed_ms",
    "replay_per_person_us",
    "replay_per_decided_person_us",
    "replay_per_decided_pair_us",
}


def _record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["record"]


def test_the_days_protocol_states_values_the_verdict_already_reads():
    hour = load_comparison_catalogs(versions=COMPARISON_VERSIONS)
    day = load_comparison_catalogs(versions=DAY_COMPARISON_VERSIONS)
    values, hour_values = protocol_values(day), protocol_values(hour)
    assert set(values) <= PROTOCOL_READS
    assert set(values) == set(hour_values) - PURPOSEFUL_LINE
    changed = {key for key in values if values[key] != hour_values[key]}
    assert changed == {"window_ticks", "need_relief_floor_per_person"}
    assert values["window_ticks"] == 1440


def test_the_days_floor_is_the_one_its_record_derived():
    record = _record(FLOOR_RECORD)
    day = load_comparison_catalogs(versions=DAY_COMPARISON_VERSIONS)
    floor = day.protocol["need_relief_floor_per_person"]
    assert floor["value"] == record["derived"]["need_relief_floor_per_person"]
    assert str(FLOOR_RECORD.relative_to(ROOT)) in str(floor["reason"])
    assert record["window_ticks"] == protocol_values(day)["window_ticks"]


@pytest.mark.parametrize("name", REGISTERED)
def test_every_recorded_binding_still_holds(name):
    registered = _record(ROOT / "docs" / "evaluation" / name)["scoring"]
    assert binding_holds(registered)


def test_the_binding_a_living_towns_hour_registers_is_mains_before_the_day():
    hour = comparison_catalogs_for_engine(LIVING_TOWN_PROFILE)
    assert scoring_binding(hour) == HOUR_BINDING_ON_MAIN
    assert binding_holds(HOUR_BINDING_ON_MAIN)


def test_an_hours_comparison_is_defined_under_the_third_protocol_and_its_familys_score():
    assert COMPARISON_VERSIONS == {
        "society-person-score": 3,
        "society-comparison-protocol": 3,
        "society-comparison-seeds": 5,
    }
    assert comparison_catalogs_for_engine(LIVING_TOWN_PROFILE).versions == {
        **COMPARISON_VERSIONS,
        "society-person-score": 4,
    }
    assert comparison_catalogs_for_engine(PURPOSEFUL_PROFILE).versions == COMPARISON_VERSIONS


def test_a_day_is_defined_for_a_living_town_alone():
    assert comparison_catalogs_for_engine(LIVING_TOWN_PROFILE, "day").versions == (
        DAY_COMPARISON_VERSIONS
    )
    with pytest.raises(CatalogError, match="over a day of a purposeful society"):
        comparison_catalogs_for_engine(PURPOSEFUL_PROFILE, "day")
    with pytest.raises(CatalogError, match="no comparison window"):
        comparison_catalogs_for_engine(LIVING_TOWN_PROFILE, "week")


def test_a_days_binding_names_the_fourths_modules_and_the_two_that_read_a_day():
    binding = scoring_binding(comparison_catalogs_for_engine(LIVING_TOWN_PROFILE, "day"))
    assert binding["profile"] == "exulanica.society-comparison-binding/v5"
    assert set(binding["modules"]) == set(HOUR_BINDING_ON_MAIN["modules"]) | {
        "exulanica.world.society_score_v5",
        "exulanica.world.society_comparison_verdict_v5",
    }
    for module, digest in HOUR_BINDING_ON_MAIN["modules"].items():
        assert binding["modules"][module] == digest
    assert binding_holds(binding)
    for module in binding["modules"]:
        changed = {**binding, "modules": {**binding["modules"], module: "0" * 64}}
        assert not binding_holds(changed), module


def _day_terms(urgency: int, variety: int) -> dict:
    """A day's terms over two people, in the fourth score's form."""
    return {
        "ticks": 1440,
        "threshold": 0,
        "people": ["a", "b"],
        "urgency": urgency,
        "choice_points": 40,
        "turns": 0,
        "classes": {"answered": 0, "not_answered": 0, "not_applied": 0, "refused": 0},
        "reasons": {"not_answered": {}, "not_applied": {}, "refused": {}},
        "person_minutes": {"doing": 1440, "waiting": 1440, "walking": 0},
        "minutes_by_activity": {"rest": 1440},
        "activities": {"a": variety - 1, "b": 1},
        "others": [],
        "others_urgency": 0,
        "need_thresholds": {"energy": 700},
        "need_unit": NEED_UNIT,
    }


def _day_comparison(catalogs, terms_by_arm):
    seeds = [hashlib.sha256(seed.encode()).hexdigest() for seed in SEEDS]
    arms = {
        "routine": {
            "role": "one",
            "decider": {"kind": "routine"},
            "provider_config": None,
            "answering": None,
            "description": "Their own routine",
        },
        "wait": {
            "role": "zero",
            "decider": {"kind": "wait"},
            "provider_config": None,
            "answering": None,
            "description": "Waiting where they are",
        },
        "model_a": model_arm("candidate"),
    }
    document = {
        "profile": "exulanica.society-comparison/v2",
        "document_sha256": "f" * 64,
        "phase": "development",
        "seeds": seeds,
        "window_ticks": 1440,
        "population": 2,
        "input": {"input_seq": 1, "document_sha256": "1" * 64},
        "group": {
            "people": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "source": {"kind": "everyone"},
        },
        "others": [],
        "arms": arms,
        "claim": {
            "primary": ["routine", "model_a"],
            "family": [["routine", "model_a"]],
            "control": None,
        },
        "preregistration": None,
        "scoring": scoring_binding(catalogs),
    }
    row = {
        "comparison_id": uuid.uuid4(),
        "created_at": dt.datetime(2026, 10, 2, tzinfo=dt.UTC),
        "document": document,
    }
    runs = [
        {
            "run_id": uuid.uuid4(),
            "arm": arm,
            "seed_digest": seed,
            "status": "completed",
            "outcome": {"terms": terms_by_arm[arm], "calls": None},
        }
        for arm in arms
        for seed in seeds
    ]
    return row, runs


def test_a_days_comparison_is_read_under_the_fifth_score_by_the_fourths_math():
    catalogs = seeded_catalogs(versions=DAY_COMPARISON_VERSIONS)
    terms = {
        "wait": _day_terms(2_000_000, 2),
        "routine": _day_terms(500_000, 9),
        "model_a": _day_terms(800_000, 7),
    }
    row, runs = _day_comparison(catalogs, terms)
    result = comparison_result(row, runs, catalogs, model_name=load_manifest().model_name)
    assert result["score_version"] == 5
    assert result["window_ticks"] == 1440
    assert (result["verdict"]["code"], result["verdict"]["reason"]) == (
        "not_judged",
        "development_seeds",
    )
    # Half need relief, (2,000,000 - 800,000) / (2,000,000 - 500,000), and half variety, (7 - 2) /
    # (9 - 2), as the fourth score anchors them.
    assert result["summaries"]["model_a"]["mean_score"] == "0.7571"
    # A run scored over another window than the protocol's day is refused by name.
    hour = {**terms["model_a"], "ticks": 60}
    row, runs = _day_comparison(catalogs, {**terms, "model_a": hour})
    with pytest.raises(ComparisonRefused, match="day_terms_not_the_window"):
        comparison_result(row, runs, catalogs, model_name=load_manifest().model_name)
