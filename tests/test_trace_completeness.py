"""The trace completeness check over a world version's decision records, read through a fake API.

Every record here is synthetic, written in the shapes the models, events and decision routes serve.
"""

from __future__ import annotations

from typing import Any

import pytest
from scripts.trace_completeness import (
    ReadFailed,
    named_requests,
    read_world,
    recorded_path,
    summary_lines,
    trace,
)

VERSION = "version-1"
BEING = "being-1"


def _receipt(
    request_id: str,
    seq: int,
    status: str = "accepted",
    label: str | None = "wait",
    action: str = "wait",
) -> dict[str, Any]:
    proposal = (
        None if label is None else {"label": label, "option": {"action": action, "label": label}}
    )
    return {
        "request_id": request_id,
        "decision_seq": seq,
        "status": status,
        "reason": "validated_choice" if status == "accepted" else "model_timed_out",
        "proposal": proposal,
        "document_sha256": f"digest-{request_id}",
    }


def _record(request_id: str, base_tick: int, receipt: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": "in_progress" if receipt is None else "completed",
        "request": {"request_id": request_id, "subject_id": BEING, "base_tick": base_tick},
        "decision": receipt,
    }


def _event(tick: int, kind: str, order: int = 0, **document: Any) -> dict[str, Any]:
    return {
        "tick": tick,
        "event_kind": kind,
        "subject_id": BEING,
        "document": {"order": order, **document},
    }


def _closing(tick: int, request_id: str, disposition: str = "applied") -> dict[str, Any]:
    return _event(
        tick,
        "decision_applied",
        5,
        request_id=request_id,
        disposition=disposition,
        decision_sha256=f"digest-{request_id}",
        motion_path_mm=[[0, 0]],
    )


def _world() -> dict[str, Any]:
    """Three requests: a walk applied in minute 2 (arrived in 3), a wait in 5, a timeout at 6."""
    events = [
        _event(6, "action_completed", reason="reviewed_duration_elapsed"),
        _closing(5, "wait"),
        _event(
            3,
            "route_progressed",
            reason="arrived_at_access_node",
            motion_path_mm=[[30000, 0], [30000, 20000]],
        ),
        _closing(2, "go"),
        _event(
            2,
            "route_progressed",
            1,
            reason="following_reachable_route",
            motion_path_mm=[[0, 0], [30000, 0]],
        ),
    ]
    return {
        "models": {
            "society_id": "society-1",
            "latest": [
                {
                    "request_id": "timeout",
                    "subject_id": BEING,
                    "base_tick": 6,
                    "consumed_tick": None,
                    "disposition": None,
                }
            ],
            "by_model": [{"decisions": 3}],
            "decisions_read": {"counted": 3, "maximum": 50},
        },
        "events": events,
        "events_complete": True,
        "records": {
            "go": _record("go", 1, _receipt("go", 1, label="rest, 50 m away", action="go")),
            "wait": _record("wait", 4, _receipt("wait", 2)),
            "timeout": _record(
                "timeout", 6, _receipt("timeout", 3, status="unavailable", label=None)
            ),
        },
    }


def test_complete_trace_reports_each_request_and_the_walked_path() -> None:
    report = trace(_world())
    assert report["complete"] is True
    rows = {row["request_id"]: row for row in report["requests"]}
    assert [row["request_id"] for row in report["requests"]] == ["go", "wait", "timeout"]
    walk = rows["go"]
    assert (
        walk["consumed_tick"],
        walk["disposition"],
        walk["decision_applied_event"],
        walk["event_binds_receipt"],
    ) == (2, "applied", True, True)
    assert walk["path"] == {
        "minutes": [
            {"minute": 2, "points": 2, "metres": 30.0},
            {"minute": 3, "points": 2, "metres": 20.0},
        ],
        "metres": 50.0,
        "arrived_at": 3,
        "until": 5,
    }
    # A wait is applied with no walk, and that is not a problem.
    assert rows["wait"]["path"]["metres"] == 0 and rows["wait"]["problems"] == []
    # A timeout no minute has taken up yet is recorded, unconsumed and eventless, and complete.
    assert rows["timeout"] == {
        **rows["timeout"],
        "status": "unavailable",
        "consumed_tick": None,
        "decision_applied_event": False,
        "path": None,
        "problems": [],
    }
    text = "\n".join(summary_lines(report))
    assert "path 50.0 m over 2 minute(s), arrived in minute 3" in text
    assert "not consumed by any minute" in text
    assert text.endswith("Trace complete.")


def test_missing_links_are_reported_by_name() -> None:
    world = _world()
    # A receipt never written, an event whose digest names another receipt, a consumed decision
    # with no event, and a request nothing names but whose sequence number is missing.
    world["records"]["wait"] = _record("wait", 4, None)
    world["records"]["go"]["decision"]["document_sha256"] = "digest-other"
    world["models"]["latest"][0].update(consumed_tick=4, disposition="unavailable")
    world["records"]["timeout"]["decision"]["decision_seq"] = 5
    report = trace(world)
    problems = {row["request_id"]: row["problems"] for row in report["requests"]}
    assert problems == {
        "go": ["event_receipt_digest_mismatch"],
        "wait": ["no_receipt"],
        "timeout": ["consumed_without_event"],
    }
    assert report["checks"]["decision_seq_gaps"] == [2, 3, 4]
    assert report["complete"] is False
    assert summary_lines(report)[-1] == "Trace NOT complete."


def test_applied_go_with_no_recorded_walk_is_a_problem() -> None:
    world = _world()
    world["events"] = [
        event for event in world["events"] if event["event_kind"] != "route_progressed"
    ]
    rows = {row["request_id"]: row for row in trace(world)["requests"]}
    assert rows["go"]["problems"] == ["applied_go_without_movement"]


def test_the_path_stops_at_the_next_applied_decision() -> None:
    events = [
        _closing(2, "go"),
        _event(2, "route_progressed", 1, motion_path_mm=[[0, 0], [10000, 0]]),
        _closing(4, "later"),
        _event(4, "route_progressed", 1, motion_path_mm=[[10000, 0], [40000, 0]]),
    ]
    assert recorded_path(events, BEING, "go", 2)["metres"] == 10.0


def test_reads_only_by_get_and_takes_request_ids_from_the_records() -> None:
    world = _world()
    asked: list[tuple[str, dict[str, str]]] = []

    def get(path: str, query: dict[str, str]) -> Any:
        asked.append((path, dict(query)))
        base = f"/world/versions/{VERSION}"
        if path == f"{base}/society/models":
            return world["models"]
        if path == f"{base}/society/events":
            # Two pages, newest first.
            return (
                {"events": world["events"][:2], "next": "older"}
                if "before" not in query
                else {"events": world["events"][2:], "next": None}
            )
        request_id = path.rsplit("/", 1)[-1]
        if request_id == "wait":
            raise ReadFailed(path, 404)
        return world["records"][request_id]

    read = read_world(get, VERSION)
    assert [query.get("before") for path, query in asked if path.endswith("/events")] == [
        None,
        "older",
    ]
    assert read["events_complete"] is True
    assert named_requests(read["models"], read["events"]) == ["go", "timeout", "wait"]
    assert read["records"]["wait"] == {"read_failed": 404}
    rows = {row["request_id"]: row for row in trace(read)["requests"]}
    assert rows["wait"]["problems"] == ["record_unreadable"]


@pytest.mark.parametrize("counted", [50, 60])
def test_a_windowed_models_read_is_not_compared(counted: int) -> None:
    world = _world()
    world["models"]["decisions_read"] = {"counted": counted, "maximum": 50}
    world["models"]["by_model"] = [{"decisions": counted}]
    checks = trace(world)["checks"]
    assert checks["models_read_counts_all"] is False
    assert checks["models_read_count_matches"] is None
