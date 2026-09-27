"""The flight checker's re-judgment and the flight worker record, held to what they bind.

``docs/evaluation/2026-09-26-flight-independent-check.json`` judges record B's seeds again with the
independent checker and compares the windows this flight serves with record B's.
``docs/evaluation/2026-09-26-flight-worker.json`` answers its pre-registration on held-out seeds and
times the server beside a cold flight read; ``2026-09-26-flight-worker-v2.json`` times it again,
after the route's encoding and the measuring script changed, and ``-v3`` once more, after the
server froze what its startup made. These tests hold each to the bytes of
every file it binds, each judged record to its pre-registration, and the search bound's reason to
the record that times it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.movement.flight import FLIGHT_MODULE
from scripts.measure_flight_bounds import seeds

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "docs" / "evaluation"
RECORD_B = EVALUATION / "2026-09-25-flight-bounds-v2.json"
CHECK = EVALUATION / "2026-09-26-flight-independent-check.json"
WORKER = EVALUATION / "2026-09-26-flight-worker.json"
WORKER_PREREGISTRATION = EVALUATION / "2026-09-26-flight-worker-preregistration.json"
TIMING = EVALUATION / "2026-09-26-flight-worker-v2.json"
TIMING_PREREGISTRATION = EVALUATION / "2026-09-26-flight-worker-v2-preregistration.json"
FROZEN = EVALUATION / "2026-09-26-flight-worker-v3.json"
FROZEN_PREREGISTRATION = EVALUATION / "2026-09-26-flight-worker-v3-preregistration.json"
ERRATUM = EVALUATION / "2026-09-26-flight-worker-erratum.json"


def _envelope(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bound(record: dict, name: str) -> dict:
    return json.loads((ROOT / record["bound_artifacts"][name]["path"]).read_bytes())


def test_every_file_each_record_binds_is_the_file_it_measured():
    for path in (
        CHECK,
        WORKER,
        WORKER_PREREGISTRATION,
        TIMING,
        TIMING_PREREGISTRATION,
        FROZEN,
        FROZEN_PREREGISTRATION,
        ERRATUM,
    ):
        envelope = _envelope(path)
        assert envelope["record_sha256"] == _sha256(canonical_json(envelope["record"])), path
        record = envelope["record"]
        entries = record.get("bound_artifacts") or {
            entry["path"]: entry for entry in record["artifacts"]["files"]
        }
        assert entries, f"{path.name} binds nothing"
        for name, entry in sorted(entries.items()):
            data = (ROOT / entry["path"]).read_bytes()
            assert (len(data), _sha256(data)) == (entry["byte_size"], entry["sha256"]), name


def test_the_re_judgment_is_of_record_b_s_seeds_and_windows():
    record = _envelope(CHECK)["record"]
    envelope_b = _envelope(RECORD_B)
    assert record["answers"] == {
        "path": f"docs/evaluation/{RECORD_B.name}",
        "record_sha256": envelope_b["record_sha256"],
    }
    run = _bound(record, "runs/judged-2-worker.json")
    run_b = _bound(envelope_b["record"], "runs/judged-bounds.json")
    assert run["seeds"] == run_b["seeds"] == {"kind": "judged-2", "values": seeds("judged-2")}
    for name, world in run["worlds"].items():
        recorded = {row["seed"]: row["windows_sha256"] for row in run_b["worlds"][name]["runs"]}
        served = {row["seed"]: row["windows_sha256"] for row in world["runs"]}
        assert served == recorded, name
    assert {row["id"]: row["outcome"] for row in record["judged"]} == {
        "no-violation": "passed",
        "every-flyer-home": "passed",
        "record-b-windows": "passed",
    }


def test_the_worker_record_answers_its_preregistration_on_seeds_nobody_ran_before_it():
    record = _envelope(WORKER)["record"]
    envelope = _envelope(WORKER_PREREGISTRATION)
    preregistration = envelope["record"]
    assert record["preregistration"] == {
        "path": f"docs/evaluation/{WORKER_PREREGISTRATION.name}",
        "record_sha256": envelope["record_sha256"],
    }
    bound = {
        Path(entry["path"]).name: entry["sha256"] for entry in preregistration["artifacts"]["files"]
    }
    assert {name: entry["sha256"] for name, entry in record["scripts"].items()} == bound
    assert [row["id"] for row in record["judged"]] == [
        row["id"] for row in preregistration["judged"]
    ]
    held_out = seeds("judged-3")
    assert preregistration["seeds"]["judged"] == held_out
    assert not set(held_out) & (
        set(seeds("judged")) | set(seeds("judged-2")) | set(seeds("development"))
    )
    run = _bound(record, "runs/judged-bounds.json")
    assert run["seeds"] == {"kind": "judged-3", "values": held_out}
    assert preregistration["written_at"] < run["started_at"]


def test_the_search_bound_s_reason_names_the_record_that_times_it():
    assert f"docs/evaluation/{WORKER.name}" in FLIGHT_MODULE.parameter("route_cells").reason
    record = _envelope(WORKER)["record"]
    costs = record["reported"]["worker-costs"]["capped_search"]
    assert costs["route_cells"] == FLIGHT_MODULE.value("route_cells")
    assert costs["bounded_process_us"]["max"] < costs["unbounded_process_us"]["values"][0]


@pytest.mark.parametrize(
    ("record_path", "preregistration_path", "answered"),
    [(TIMING, TIMING_PREREGISTRATION, WORKER), (FROZEN, FROZEN_PREREGISTRATION, TIMING)],
    ids=["second", "third"],
)
def test_each_later_timing_answers_its_preregistration_after_the_one_before_was_judged(
    record_path, preregistration_path, answered
):
    record = _envelope(record_path)["record"]
    envelope = _envelope(preregistration_path)
    preregistration = envelope["record"]
    assert record["preregistration"] == {
        "path": f"docs/evaluation/{preregistration_path.name}",
        "record_sha256": envelope["record_sha256"],
    }
    assert preregistration["answers"] == {
        "path": f"docs/evaluation/{answered.name}",
        "record_sha256": _envelope(answered)["record_sha256"],
    }
    bound = {
        Path(entry["path"]).name: entry["sha256"] for entry in preregistration["artifacts"]["files"]
    }
    assert {name: entry["sha256"] for name, entry in record["scripts"].items()} == bound
    assert [row["id"] for row in record["judged"]] == [
        row["id"] for row in preregistration["judged"]
    ]
    written = datetime.strptime(preregistration["written_at"], "%Y-%m-%dT%H:%M:%S%z")
    assert written < datetime.strptime(record["first_timed_run_at"], "%Y-%m-%dT%H:%M:%S%z")
    assert _envelope(answered)["record"]["verdict"].startswith("FAILED")


def test_the_freeze_s_comment_names_the_record_that_times_it():
    source = (ROOT / "exulanica" / "api" / "app.py").read_text(encoding="utf-8")
    assert f"docs/evaluation/{FROZEN.name}" in source
    memory = _envelope(FROZEN)["record"]["startup_memory_kib"]
    assert len(memory["with-freeze"]) == len(memory["without-freeze"]) == 3


def test_the_erratum_corrects_the_three_timing_records_as_they_stand():
    erratum = _envelope(ERRATUM)["record"]
    assert [row["path"] for row in erratum["corrects"]] == [
        f"docs/evaluation/{path.name}" for path in (WORKER, TIMING, FROZEN)
    ]
    for row in erratum["corrects"]:
        assert row["record_sha256"] == _envelope(ROOT / row["path"])["record_sha256"]
    assert erratum["runs"] and all(
        run["mean_idle_tenths_percent"] >= 500 for run in erratum["runs"]
    )
