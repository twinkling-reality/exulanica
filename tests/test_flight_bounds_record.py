"""The flight bounds records: each answers its pre-registration, and the module answers them.

``docs/evaluation/2026-09-25-flight-bounds.json`` is the first registration's result: its run said
every rule passed, and the corrected check of the same windows found flyers late home among the
crowded crowns, so it failed, and it says why. ``docs/evaluation/2026-09-25-flight-bounds-v2.json``
judges the flight that answers it, on seeds nobody ran before its registration. These tests hold
each record to the pre-registration it answers and to the bytes of every file it binds, and the
registry's ``max_flyers`` to the second record's frame time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.movement.flight import FLIGHT_MODULE
from scripts.measure_flight_bounds import seeds

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "docs" / "evaluation"
FIRST = EVALUATION / "2026-09-25-flight-bounds.json"
SECOND = EVALUATION / "2026-09-25-flight-bounds-v2.json"
RECORDS = {
    "first": (FIRST, EVALUATION / "2026-09-25-flight-bounds-preregistration.json"),
    "second": (SECOND, EVALUATION / "2026-09-25-flight-bounds-v2-preregistration.json"),
}


def _envelope(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("which", sorted(RECORDS), ids=sorted(RECORDS))
def test_each_record_answers_its_preregistration_with_the_scripts_it_bound(which):
    record_path, preregistration_path = RECORDS[which]
    record = _envelope(record_path)["record"]
    preregistration = _envelope(preregistration_path)
    assert record["preregistration"] == {
        "path": f"docs/evaluation/{preregistration_path.name}",
        "record_sha256": preregistration["record_sha256"],
    }
    bound = {
        Path(entry["path"]).name: entry["sha256"]
        for entry in preregistration["record"]["artifacts"]["files"]
    }
    assert {name: entry["sha256"] for name, entry in record["scripts"].items()} == bound
    assert [row["id"] for row in record["judged"]] == [
        row["id"] for row in preregistration["record"]["judged"]
    ]


@pytest.mark.parametrize("which", sorted(RECORDS), ids=sorted(RECORDS))
def test_every_file_each_record_binds_is_the_file_it_measured(which):
    envelope = _envelope(RECORDS[which][0])
    assert envelope["record_sha256"] == _sha256(canonical_json(envelope["record"]))
    record = envelope["record"]
    assert record["bound_artifacts"], "the record binds nothing"
    for name, entry in sorted(record["bound_artifacts"].items()):
        data = (ROOT / entry["path"]).read_bytes()
        assert (len(data), _sha256(data)) == (entry["byte_size"], entry["sha256"]), name
    for name, entry in record["scripts"].items():
        assert _sha256((ROOT / entry["path"]).read_bytes()) == entry["sha256"], name


def test_the_first_registration_failed_and_says_why():
    record = _envelope(FIRST)["record"]
    outcomes = {row["id"]: row["outcome"] for row in record["judged"]}
    assert outcomes == {
        "no-violation": "failed",
        "every-flyer-home": "failed",
        "exact-replay": "passed",
        "twenty-four-flyers-in-a-frame": "passed",
    }
    assert record["verdict"].startswith("FAILED")
    assert record["first_run"]["verdict_then"] == "PASSED" and record["checker_defects"]
    crowded = record["found"]["crowded_crowns"]
    assert crowded["not_home_at_an_episode_end"] > 0
    assert crowded["windows_equal_to_the_first_run"] == crowded["seeds"]
    run = json.loads((ROOT / record["bound_artifacts"]["runs/first-run.json"]["path"]).read_bytes())
    assert run["seeds"] == {"kind": "judged", "values": seeds("judged")}


def test_the_second_registration_was_judged_on_seeds_nobody_ran_before_it():
    record = _envelope(SECOND)["record"]
    preregistration = _envelope(RECORDS["second"][1])["record"]
    held_out = seeds("judged-2")
    assert preregistration["seeds"]["judged"] == held_out
    assert not set(held_out) & (set(seeds("judged")) | set(seeds("development")))
    bound = record["bound_artifacts"]["runs/judged-bounds.json"]["path"]
    run = json.loads((ROOT / bound).read_bytes())
    assert run["seeds"] == {"kind": "judged-2", "values": held_out}
    assert preregistration["written_at"] < run["started_at"]


def test_max_flyers_is_the_largest_population_the_second_record_measured_within_a_frame():
    record = _envelope(SECOND)["record"]
    max_flyers = FLIGHT_MODULE.value("max_flyers")
    assert record["max_flyers"] == {
        "declared": max_flyers,
        "largest_population_measured_within_a_frame": max_flyers,
    }
    [frame] = [row for row in record["judged"] if row["id"] == "twenty-four-flyers-in-a-frame"]
    assert frame["outcome"] == "passed"
    assert frame["measured"]["flyers"] == max_flyers
    assert frame["measured"]["work_p95_us"] < frame["measured"]["budget_us"]
    assert f"docs/evaluation/{SECOND.name}" in FLIGHT_MODULE.parameter("max_flyers").reason
