"""A rehearsal record keeps large request and response bodies by digest, and nothing reads them.

``scripts/rehearsal/resultdoc.py`` keeps every body in a step's evidence up to
``RECORDED_BODY_BYTES`` whole and a larger one as its SHA-256 and size. These tests hold the rule to
its bound in both directions, and show that the step statuses and the gate table a run reports are
the same whatever the evidence's bodies hold: no gate reads a body the record keeps by digest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "scripts" / "rehearsal"
sys.path.insert(0, str(REHEARSAL))

import resultdoc  # noqa: E402
import steplist  # noqa: E402

STEPS = steplist.load()
GATES = steplist.read_gates(STEPS["gate_sources"])
BOUND = resultdoc.RECORDED_BODY_BYTES


def _body_of(size: int) -> str:
    """A JSON string body whose text as JSON writes it is exactly ``size`` bytes."""
    return "x" * size


def _outcome(step: dict[str, Any], body: object, *, ok: bool = True) -> dict[str, Any]:
    exchange = {"method": "GET", "path": "/api/world-entries", "status": 200}
    return {
        "status": "passed" if ok else "failed",
        "reason": None if ok else "did not hold",
        "observations": [
            {"id": observable["id"], "ok": ok, "observed": {"read": "what the check saw"}}
            for observables in step["expect"].values()
            for observable in observables
        ],
        "evidence": {
            "api": [exchange | {"request_body": None, "response_body": body}],
            "network": [exchange | {"request_body": body, "response_body": body}],
        },
    }


def _run() -> dict[str, Any]:
    return {
        "started_at": "2026-09-29T00:00:00+00:00",
        "finished_at": "2026-09-29T00:10:00+00:00",
        "rehearsal_tree": {"head": "0" * 40, "diff_head_sha256": "0" * 64},
        "application_tree": None,
        "steps_sha256": steplist.digest(),
    }


def _assembled(body: object, failing: str | None = None) -> dict[str, Any]:
    outcomes = {
        step["id"]: _outcome(step, body, ok=step["id"] != failing)
        for step in STEPS["steps"]
        if "not_available" not in step
    }
    return resultdoc.assemble(STEPS, GATES, outcomes, {}, _run())


def test_a_body_at_the_bound_is_kept_whole_and_one_byte_more_is_kept_by_digest():
    at_bound = _body_of(BOUND - 2)  # the two quotes JSON writes around a string
    assert len(json.dumps(at_bound).encode()) == BOUND
    assert resultdoc.recorded_body(at_bound) == at_bound

    over = {"text": "y" * BOUND}
    text = json.dumps(over, sort_keys=True).encode()
    assert resultdoc.recorded_body(over) == {
        "recorded_by_digest": {"sha256": hashlib.sha256(text).hexdigest(), "bytes": len(text)}
    }
    assert resultdoc.recorded_body(None) is None


def test_every_body_in_a_steps_evidence_is_bounded_and_its_observations_are_kept_whole():
    big = {"inhabitants": [{"id": index, "position_mm": [index, 0, index]} for index in range(900)]}
    document = _assembled(big)
    jsonschema.validate(document, json.loads((REHEARSAL / "result.schema.json").read_text()))
    for step in document["steps"]:
        for exchange in step["evidence"].get("api", []) + step["evidence"].get("network", []):
            for field in resultdoc.BODY_FIELDS:
                value = exchange.get(field)
                if value is not None:
                    assert len(json.dumps(value).encode()) <= BOUND, (step["id"], field)
        for observation in step["observations"]:
            assert observation["observed"] == {"read": "what the check saw"}
    recorded = document["steps"][1]["evidence"]["network"][0]["response_body"]
    assert recorded["recorded_by_digest"]["bytes"] > BOUND


def test_no_step_status_or_gate_reads_a_body_the_record_keeps_by_digest():
    # The same outcomes with every body large, small, or absent give the same statuses and the
    # same gate table, for a passing run and for one with a failed step.
    for failing in (None, "place-reviewed-object"):
        tables = []
        for body in ({"text": "z" * (BOUND * 10)}, {"text": "small"}, None):
            document = _assembled(copy.deepcopy(body), failing)
            tables.append(
                (
                    [
                        (step["id"], step["status"], step.get("reason"))
                        for step in document["steps"]
                    ],
                    document["gates"],
                    document["summary"],
                )
            )
        assert tables[0] == tables[1] == tables[2]
    # The positive control: the failing run's table differs from the passing one's, so the
    # comparison above can tell two tables apart.
    assert _assembled(None)["gates"] != _assembled(None, "place-reviewed-object")["gates"]
