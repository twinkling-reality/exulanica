"""The living-square measurement reads a minute the way its docstring says, and judges fairly.

``scripts/measure_living_square.py`` is the instrument a before-and-after record rests on. These
check what it counts on minutes built by hand: walking, using an object, another activity and
waiting are exclusive; a stay's dwell runs from the minute its action appears to the minute it
completes; a person with a partner is measured against that partner; and a target the summary
cannot answer fails rather than passing. A result is written only for an after arm that started
measuring after its targets were registered.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from scripts import measure_living_square as measure


def person(ordinal: int, **changes) -> dict:
    base = {
        "id": f"person-{ordinal}",
        "ordinal": ordinal,
        "position_mm": [0, 0],
        "motion_path_mm": [[0, 0]],
        "goal": None,
        "target": None,
        "action": {
            "kind": "idle",
            "status": "active",
            "target_id": None,
            "remaining_ticks": 0,
            "reason": "awaiting_goal",
        },
    }
    return {**base, **changes}


BENCH = {"target_id": "t-bench", "object_id": "bench-1", "affordance": "rest"}


def resting(ordinal: int, status: str = "active", remaining: int = 3) -> dict:
    return person(
        ordinal,
        target=BENCH,
        action={
            "kind": "rest",
            "status": status,
            "target_id": "t-bench",
            "remaining_ticks": remaining,
            "reason": "arrived_at_access_node",
        },
    )


def talking(ordinal: int, partner: int, x_mm: int) -> dict:
    return person(
        ordinal,
        position_mm=[x_mm, 0],
        motion_path_mm=[[x_mm, 0]],
        goal={"kind": "talk", "target_id": None, "partner_id": f"person-{partner}"},
        action={
            "kind": "talk",
            "status": "active",
            "target_id": None,
            "remaining_ticks": 2,
            "reason": "talking",
        },
    )


def test_a_minute_is_exactly_one_of_walking_using_another_activity_or_waiting():
    assert measure.minute_of(person(0, motion_path_mm=[[0, 0], [10, 0]])) == ("walking", None)
    assert measure.minute_of(resting(0)) == ("using", "bench-1")
    assert measure.minute_of(resting(0, status="completed")) == ("using", "bench-1")
    assert measure.minute_of(talking(0, 1, 0)) == ("talk", None)
    assert measure.minute_of(person(0)) == ("waiting", None)
    blocked = resting(0)
    blocked["action"] = {**blocked["action"], "kind": "idle", "status": "blocked"}
    assert measure.minute_of(blocked) == ("waiting", None)


def test_a_stay_runs_from_the_minute_it_appears_to_the_minute_it_completes():
    stays: list = []
    held: dict = {}
    objects = {"bench-1": "bench"}
    measure._follow(resting(0, remaining=3), 5, objects, held, stays)
    measure._follow(resting(0, remaining=2), 6, objects, held, stays)
    measure._follow(resting(0, status="completed", remaining=0), 8, objects, held, stays)
    assert stays == [
        {
            "person": 0,
            "kind": "rest",
            "target_id": "t-bench",
            "object_id": "bench-1",
            "object_kind": "bench",
            "started": 5,
            "planned": 3,
            "outcome": "completed",
            "minutes": 3,
        }
    ]
    # Something else before it completes interrupts it, and it has no dwell.
    measure._follow(resting(1), 9, objects, held, stays)
    measure._follow(person(1), 10, objects, held, stays)
    assert stays[-1]["outcome"] == "interrupted" and "minutes" not in stays[-1]


def test_a_person_with_a_partner_is_measured_against_that_partner():
    rows: list = []
    measure._partners([talking(0, 1, 0), talking(1, 0, 2000), person(2)], rows)
    assert rows == [["talk", "talk", 2000], ["talk", "talk", 2000]]
    summary = measure._with_a_partner([*rows, ["talk", "walking", 4000]])
    assert summary["talk"]["person_minutes"] == 3
    assert summary["talk"]["partner_doing_the_same"] == 2
    assert summary["talk"]["partner_by_category"] == {"talk": 2, "walking": 1}
    assert summary["talk"]["apart_mm_when_both"]["max"] == 2000


def test_a_target_the_summary_cannot_answer_fails():
    summary = {
        "share_of_person_minutes_milli": {"walking": 400},
        "with_a_partner": {"talk": {"person_minutes": 10, "partner_doing_the_same": 9}},
    }
    within = {"id": "w", "metric": ["share_of_person_minutes_milli", "walking"], "rule": "within"}
    assert measure.judge({**within, "bounds": [100, 250]}, summary)["passed"] is False
    assert measure.judge({**within, "bounds": [100, 450]}, summary)["passed"] is True
    # A share nobody spent a minute on is 0; any other absent value fails as None.
    talk = {"id": "t", "metric": ["share_of_person_minutes_milli", "talk"], "rule": "at_least"}
    assert measure.judge({**talk, "bound": 1}, summary) == {"id": "t", "value": 0, "passed": False}
    dwell = {"id": "d", "metric": ["dwell_minutes_by_object_kind", "bench"], "rule": "at_least"}
    unanswered = {"id": "d", "value": None, "passed": False}
    assert measure.judge({**dwell, "bound": 1}, summary) == unanswered
    together = {
        "id": "p",
        "metric": ["with_a_partner", "talk", "partner_doing_the_same"],
        "of": ["with_a_partner", "talk", "person_minutes"],
        "rule": "share_at_least",
    }
    assert measure.judge({**together, "bound": 900}, summary)["value"] == 900
    assert measure.judge({**together, "bound": 901}, summary)["passed"] is False
    with pytest.raises(SystemExit, match="no rule named"):
        measure.judge({**within, "rule": "roughly"}, summary)


def test_the_viewer_faces_the_way_a_person_arriving_faces():
    # A camera at yaw 0 looks along -z; the page states that as half a turn.
    assert measure.viewer_facing({"x_mm": 0, "z_mm": 4000, "yaw_microradians": 0}) == {
        "x_mm": 0,
        "z_mm": 4000,
        "yaw_microradians": 3_141_593,
    }


def _registered(tmp_path, monkeypatch, *, written_at: str, started_at: str) -> tuple:
    """A targets record and an after arm in a scratch evaluation directory, bound to one script."""
    evaluation = tmp_path / "docs" / "evaluation"
    evaluation.mkdir(parents=True)
    monkeypatch.setattr(measure, "ROOT", tmp_path)
    monkeypatch.setattr(measure, "EVALUATION", evaluation)
    script = b"the measuring script, as it ran"
    digest = hashlib.sha256(script).hexdigest()
    targets = {
        "profile": f"{measure.PROFILE}/targets",
        "written_at": written_at,
        "measured_with_sha256": digest,
        "seeds": {"judged": ["7a" * 32], "development": []},
        "targets": [],
        "before": {"tree": {}, "summary": {}},
    }
    (evaluation / "2026-09-25-living-square-targets.json").write_text(
        json.dumps(measure._envelope(targets)), encoding="utf-8"
    )
    after = tmp_path / "after.json"
    after.write_text(
        json.dumps(
            {
                "profile": measure.PROFILE,
                "measured_with_sha256": digest,
                "started_at": started_at,
                "measured_at": started_at,
                "inputs": {"seeds": ["7a" * 32]},
                "tree": {},
                "summary": {},
            }
        ),
        encoding="utf-8",
    )
    return after, script


def test_an_after_arm_that_started_before_its_targets_were_registered_is_refused(
    tmp_path, monkeypatch
):
    after, script = _registered(
        tmp_path,
        monkeypatch,
        written_at="2026-09-25T14:54:47+00:00",
        started_at="2026-09-25T14:54:46+00:00",
    )
    with pytest.raises(SystemExit, match="before its targets were registered"):
        measure.write(after, script)


def test_an_after_arm_started_after_its_targets_were_registered_is_judged(tmp_path, monkeypatch):
    """A positive control for the refusal above: the same arm a second later is written."""
    after, script = _registered(
        tmp_path,
        monkeypatch,
        written_at="2026-09-25T14:54:47+00:00",
        started_at="2026-09-25T14:54:48+00:00",
    )
    record = json.loads(measure.write(after, script).read_text(encoding="utf-8"))["record"]
    assert record["passed"] is True and record["judged"] == []
