"""Version 3 of the standpoint join's records hold what they bind, and bind each other.

The pre-registration was written before the held-out split was measured and the outcome after; the
outcome may name only the sources, parameters and scripts the pre-registration froze.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json, sha256_of_canonical

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "evaluation"
PREREGISTRATION = RECORDS / "2026-09-25-standpoint-join-v3-preregistration.json"
OUTCOME = RECORDS / "2026-09-25-standpoint-join-v3-outcome.json"
#: The held-out split's definition as it was planned, before version 2's held-out measurement.
HELD_OUT_SPLIT_SHA256 = "a30544381a8ac69a2caa21ec9fdf7fb08327263d8eccc7c0514ceac7e014a8fd"


def _record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["record"]


def _bindings(record: dict) -> list[dict]:
    found = [*record["bound_artifacts"].values(), *record.get("scripts", {}).values()]
    found += list(record.get("splits", {}).get("development", {}).get("definitions", {}).values())
    return found


def test_every_file_either_record_binds_is_the_file_it_bound():
    for path in (PREREGISTRATION, OUTCOME):
        bindings = _bindings(_record(path))
        assert bindings, path
        for binding in bindings:
            data = (ROOT / binding["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == binding["sha256"], binding["path"]


def test_the_outcome_measured_what_the_preregistration_froze():
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    outcome = _record(OUTCOME)
    assert outcome["preregistration"] == {
        "path": PREREGISTRATION.relative_to(ROOT).as_posix(),
        "record_sha256": preregistration["record_sha256"],
    }
    frozen = preregistration["record"]["method"]
    for key in ("params_path", "params_sha256", "stage_version", "sources_sha256"):
        assert outcome["method"][key] == frozen[key], key
    params = json.loads((ROOT / frozen["params_path"]).read_text(encoding="utf-8"))
    assert sha256_of_canonical(params).hex() == frozen["params_sha256"]
    split = preregistration["record"]["splits"]["held_out"]["definition"]
    assert split["sha256"] == HELD_OUT_SPLIT_SHA256


def test_the_outcome_says_passed_only_where_every_judged_gate_passed():
    outcome = _record(OUTCOME)
    for arm in ("exif", "exif-perturbed"):
        judged = outcome["held_out"][arm]["judged"]
        never = ("moved_never_joined", "changed_never_joined")
        assert judged["never_passed"] == all(judged["verdicts"][name] for name in never)
        assert judged["passed"] == all(judged["verdicts"].values())
        assert len(judged["verdicts"]) > len(never)


def test_the_preregistration_written_before_the_measurement_is_the_one_the_run_started_under():
    """The bound script copies were redacted for publication after the run; the record written
    before it is the redacted one with its earlier bindings back, and the run printed its digest."""
    record = _record(PREREGISTRATION)
    redaction = record["redaction"]
    before = {key: value for key, value in record.items() if key != "redaction"}
    before["scripts"] = redaction["scripts_as_bound_before_the_measurement"]
    digest = hashlib.sha256(canonical_json(before)).hexdigest()
    assert digest == redaction["record_sha256_before_the_measurement"]
    run_log = _record(OUTCOME)["bound_artifacts"]["held-out/run.log.txt"]["path"]
    assert f"pre-registration {digest}" in (ROOT / run_log).read_text(encoding="utf-8")
