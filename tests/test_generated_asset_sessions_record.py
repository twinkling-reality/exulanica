"""The warm sessions' evaluation record holds together without the evidence it was built from.

The evidence is held outside the repository, so these tests do not rebuild the record; the
script's ``--check`` does that where the evidence is present. Here every cost is recomputed from
the instants, milliseconds and rate the record states, with the script's own arithmetic, and the
record must name the script exactly as it is committed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/evaluation/2026-10-09-nebius-generated-asset-warm-sessions.json"
SCRIPT = ROOT / "scripts/record_generated_asset_sessions.py"


def _script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("record_generated_asset_sessions", SCRIPT)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _record() -> dict:
    return json.loads(RECORD.read_bytes())["record"]


def test_the_committed_record_names_the_script_as_committed() -> None:
    record = _record()
    assert record["script"] == SCRIPT.relative_to(ROOT).as_posix()
    assert record["script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert [s["session"] for s in record["sessions"]] == [
        name.removeprefix("session-") for name in _script().SESSIONS
    ]
    assert record["evidence"]["files_sha256"], "the record names no evidence it read"


def test_every_cost_is_its_time_at_the_rate_and_the_totals_add_up() -> None:
    script = _script()
    record = _record()
    rate = record["compute"]["rate_cents_per_hour"]
    for session in record["sessions"]:
        milliseconds = (
            script.nanoseconds(session["container_finished_at"])
            - script.nanoseconds(session["container_started_at"])
        ) // 1_000_000
        assert session["container_milliseconds"] == milliseconds, session["session"]
        assert session["computed_cost_microdollars"] == script.microdollars(rate, milliseconds)
        billed = script.seconds_between(session["billed_from"], session["billed_to"])
        assert session["billed_seconds"] == billed, session["session"]
        assert session["billed_cost_microdollars"] == script.microdollars(rate, billed * 1000)
        held = script.seconds_between(session["upper_bound_from"], session["upper_bound_to"])
        assert session["upper_bound_cost_microdollars"] == script.microdollars(rate, held * 1000)
        assert session["upper_bound_to"] == session["billed_to"], session["session"]
        assert (
            session["upper_bound_cost_microdollars"]
            >= session["billed_cost_microdollars"]
            >= session["computed_cost_microdollars"]
        ), session["session"]
        for line in session["charges"]:
            assert line["cost_microdollars"] == script.microdollars(rate, line["milliseconds"])
    totals = record["totals"]
    sessions = record["sessions"]
    assert totals["computed_cost_microdollars"] == sum(
        s["computed_cost_microdollars"] for s in sessions
    )
    assert totals["billed_cost_microdollars"] == sum(
        s["billed_cost_microdollars"] for s in sessions
    )
    assert totals["upper_bound_cost_microdollars"] == sum(
        s["upper_bound_cost_microdollars"] for s in sessions
    )
    assert totals["pieces_with_receipts"] == sum(len(s["pieces"]) for s in sessions)


def test_a_piece_is_within_exactly_when_it_is_over_nothing() -> None:
    record = _record()
    for session in record["sessions"]:
        requests = {e["request_sha256"]: e["entry"] for e in session["entries"]}
        for piece in session["pieces"]:
            assert piece["within"] is (piece["over"] == []), piece["receipt_sha256"]
            assert piece["entry"] == requests[piece["request_sha256"]]
    assert record["totals"]["pieces_within_every_check"] == sum(
        p["within"] for s in record["sessions"] for p in s["pieces"]
    )
