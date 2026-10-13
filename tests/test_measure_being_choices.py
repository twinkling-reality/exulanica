"""The measures of a model-run being's choices, from synthetic stored records.

One being is asked six times: three waits in a row, a walk to a bench that a path records, an
answer the engine refused when the minute came, and a call that timed out and that no minute
consumed (as the pilot's tenth did). It said two lines, the second a repeat. Expected values are
counted from those records by hand. The reader is tested for reading by GET alone and keeping the
bearer out of every URL.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_being_choices.py"
_SPEC = importlib.util.spec_from_file_location("measure_being_choices", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)

DUCK = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def _option(kind: str, label: str) -> dict:
    return {"kind": kind, "label": label, "action": kind, "target_id": None, "activity": None}


WAIT = _option("wait", "wait here a minute")
BENCH = {**_option("target", "resting on a bench, 8 m away"), "action": "go"}
STAND = _option("stand", "stand a while nearby")


def _record(seq, tick, option, *, status="accepted", consumed=True, cost="0.0001", context=None):
    request_id = f"r{seq}"
    request = {
        "request_id": request_id,
        "subject_id": DUCK,
        "base_tick": tick,
        "context": context or {"options": [WAIT, BENCH], "tick": tick},
        "provider_config": {"prompt_version": "society-person-choice/v6", "model_id": "nano"},
    }
    receipt = {
        "decision_seq": seq,
        "status": status,
        "reason": "validated_choice" if status == "accepted" else "provider_timeout",
        "proposal": None if option is None else {"label": option["label"], "option": option},
        "provider": {"calls": [{"attempt": 1}], "cost_usd": cost, "cost_known": cost is not None},
        "document_sha256": f"d{seq}",
    }
    return request_id, {"request": request, "decision": receipt}


def _applied(seq, tick, disposition="applied", subject=DUCK):
    return {
        "event_kind": "decision_applied",
        "subject_id": subject,
        "tick": tick,
        "document": {
            "request_id": f"r{seq}",
            "disposition": disposition,
            "decision_sha256": f"d{seq}",
            "order": 0,
        },
    }


def _route(tick, path, reason="following_reachable_route"):
    return {
        "event_kind": "route_progressed",
        "subject_id": DUCK,
        "tick": tick,
        "document": {"motion_path_mm": path, "reason": reason, "order": 1},
    }


def _said(tick, line):
    return {
        "event_kind": "said",
        "subject_id": DUCK,
        "tick": tick,
        "document": {"thing": {"line": line}, "order": 2},
    }


def _world():
    records = dict(
        [
            _record(1, 3, WAIT),
            _record(2, 4, WAIT),
            _record(3, 5, WAIT),
            _record(4, 6, BENCH, cost=None),
            _record(5, 9, STAND, context={"options": [WAIT, STAND], "tick": 9, "pad": "x" * 100}),
            _record(6, 10, None, status="unavailable", cost=None),
        ]
    )
    events = [
        _applied(1, 4),
        _applied(2, 5),
        _applied(3, 6),
        _applied(4, 7),
        _route(7, [[0, 0], [3000, 4000]]),
        _route(8, [[3000, 4000], [3000, 7000]], reason="arrived_at_access_node"),
        _applied(5, 10, disposition="rejected"),
        _said(5, "Quack."),
        _said(8, "Quack."),
    ]
    models = {
        "society_id": "s",
        # The timed-out request is the being's latest: no minute consumed it.
        "latest": [
            {"request_id": "r6", "subject_id": DUCK, "base_tick": 10, "consumed_tick": None}
        ],
        "by_model": [{"decisions": 6}],
        "decisions_read": {"counted": 6, "maximum": 50},
    }
    return {"models": models, "events": events, "events_complete": True, "records": records}


def test_one_being_s_choices_are_measured_from_its_records():
    result = tool.measures(_world())
    assert result["trace_complete"] is True
    [duck] = result["beings"]
    assert duck["subject_id"] == DUCK
    assert (duck["asks"], duck["accepted"], duck["applied"]) == (6, 5, 4)
    assert (duck["refused"], duck["not_taken_up"], duck["no_answer"], duck["not_consumed"]) == (
        1,
        0,
        1,
        0,
    )
    # wait, wait, wait, bench, stand: the three waits are the longest run, by label and by kind.
    assert (duck["longest_identical_labels"], duck["longest_identical_kinds"]) == (3, 3)
    assert (duck["distinct_labels"], duck["distinct_kinds"]) == (3, 3)
    assert duck["wait_share"] == 0.6
    # The walk: 5 m, then 3 m to the bench, recorded until the next applied decision (none).
    assert (duck["applied_moves"], duck["metres_moved"]) == (1, 8.0)
    assert (duck["lines_said"], duck["lines_repeated"]) == (2, 1)
    assert duck["context_bytes_maximum"] > duck["context_bytes_median"] > 0
    assert duck["prompt_versions"] == ["society-person-choice/v6"]
    assert duck["models"] == ["nano"]
    assert duck["calls"] == 6
    # Four accepted answers state a known cost of 0.0001; the walk's cost is unknown.
    assert duck["cost_known_usd"] == "0.0004"
    assert duck["cost_unknown_answers"] == 1
    assert duck["cost_per_accepted_usd"] == "0.00010000"
    [timeout] = [ask for ask in duck["in_order"] if ask["request_id"] == "r6"]
    assert (timeout["taken"], timeout["consumed_at"], timeout["chose"]) == ("no_answer", None, None)


def test_a_subject_named_alone_is_measured_alone():
    assert tool.measures(_world(), OTHER)["beings"] == []
    assert [b["subject_id"] for b in tool.measures(_world(), DUCK)["beings"]] == [DUCK]


def test_the_reader_only_gets_and_keeps_the_bearer_out_of_every_url(monkeypatch):
    seen = []

    class Answer:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            import io
            import json

            return io.BytesIO(json.dumps(self.body).encode())

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        seen.append((request.get_method(), request.full_url, request.get_header("Authorization")))
        if request.full_url.split("?")[0].endswith("/society/models"):
            return Answer({"latest": []})
        if "/society/events" in request.full_url:
            return Answer({"events": [], "next": None})
        return Answer({})

    monkeypatch.setattr(tool.trace_completeness.urllib.request, "urlopen", urlopen)
    get = tool.trace_completeness.http_get("http://127.0.0.1:20051", "secret-bearer", "w")
    tool.trace_completeness.read_world(get, "v")
    assert seen and all(method == "GET" for method, _url, _auth in seen)
    assert all("secret-bearer" not in url for _method, url, _auth in seen)
    assert all(auth == "Bearer secret-bearer" for _method, _url, auth in seen)


def test_an_api_off_this_machine_is_refused():
    assert tool._loopback("http://127.0.0.1:20051") == "http://127.0.0.1:20051"
    with pytest.raises(SystemExit, match="not on this machine"):
        tool._loopback("https://81-85-4-184.sslip.io")
