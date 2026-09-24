"""The rehearsal's step list is well formed and covers every gate of the first demonstration.

``scripts/rehearsal/`` runs the demonstration in the real application from a step list that is data
(``steps.json``). These tests hold that data to the document that states the gates
(``docs/product-direction.md``), to the two registries of code that perform its steps (the browser
driver's ``HANDLERS`` and the orchestrator's ``ORCHESTRATED``), and to the schema of the result
document a run writes. Each rule is also broken on a copy, so a check that would pass on anything
cannot hide behind a green run.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "scripts" / "rehearsal"
sys.path.insert(0, str(REHEARSAL))

import resultdoc  # noqa: E402
import steplist  # noqa: E402


def _rehearse() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rehearsal_rehearse", REHEARSAL / "rehearse.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REHEARSE = _rehearse()
STEPS = steplist.load()
GATES = steplist.read_gates(STEPS["gate_sources"])
DIRECTION = ROOT / "docs" / "product-direction.md"


def _problems_with(mutate) -> list[str]:
    broken = copy.deepcopy(STEPS)
    mutate(broken)
    return steplist.problems(broken, GATES)


def _step(steps: dict[str, Any], step_id: str) -> dict[str, Any]:
    return next(step for step in steps["steps"] if step["id"] == step_id)


def _direction_copy(tmp_path: Path, old: str, new: str) -> Path:
    text = DIRECTION.read_text(encoding="utf-8")
    assert old in text, f"the break check's anchor {old!r} is no longer in {DIRECTION.name}"
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / DIRECTION.name).write_text(text.replace(old, new, 1), encoding="utf-8")
    return tmp_path


def test_the_step_list_is_well_formed():
    assert steplist.problems(STEPS, GATES) == []


def test_every_gate_the_owning_document_states_is_read_and_served():
    # Both declared sources yield gates, so coverage cannot pass on an empty gate list.
    assert {gate.source for gate in GATES} == {source["key"] for source in STEPS["gate_sources"]}
    served = {gate for step in STEPS["steps"] for gate in step["gates"]}
    assert [gate.key for gate in GATES if gate.key not in served] == []


def test_a_delivery_gate_with_no_step_fails(tmp_path):
    root = _direction_copy(
        tmp_path,
        "5. **Release rehearsal:**",
        "5. **Unrehearsed gate:** a gate no step serves.\n6. **Release rehearsal:**",
    )
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    found = steplist.problems(STEPS, gates)
    assert any(
        "gate 'delivery:Unrehearsed gate'" in problem and "has no step" in problem
        for problem in found
    )


def test_a_milestone_deliverable_with_no_step_fails(tmp_path):
    root = _direction_copy(
        tmp_path,
        "| Inspection |",
        "| Unrehearsed deliverable | A deliverable no step serves. |\n| Inspection |",
    )
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    assert any(
        "gate 'milestone:Unrehearsed deliverable'" in problem
        for problem in steplist.problems(STEPS, gates)
    )


def test_a_renamed_gate_leaves_its_steps_naming_a_gate_the_document_does_not_state(tmp_path):
    root = _direction_copy(tmp_path, "**Persistence:**", "**Durability:**")
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    found = steplist.problems(STEPS, gates)
    unstated = "'delivery:Persistence', which the owning document does not state"
    assert any(unstated in problem for problem in found)
    assert any("gate 'delivery:Durability'" in p and "has no step" in p for p in found)


def test_the_gate_reader_refuses_a_missing_or_empty_section(tmp_path):
    missing = _direction_copy(tmp_path / "missing", "## First milestone", "## First release")
    with pytest.raises(steplist.StepListError, match="has no section '## First milestone'"):
        steplist.read_gates(STEPS["gate_sources"], missing)
    empty = _direction_copy(
        tmp_path / "empty", "1. **Usable environment:**", "1. Usable environment:"
    )
    text = (empty / "docs" / DIRECTION.name).read_text(encoding="utf-8")
    for name in ("Meaningful action", "Persistence", "Independent use", "Release rehearsal"):
        text = text.replace(f"**{name}:**", f"{name}:")
    (empty / "docs" / DIRECTION.name).write_text(text, encoding="utf-8")
    with pytest.raises(steplist.StepListError, match="states no gate in the numbered form"):
        steplist.read_gates(STEPS["gate_sources"], empty)


def test_the_about_panel_is_read_after_the_starter_and_nothing_waits_on_it():
    """What About this place says and offers is its own step, so a wrong panel fails it alone.

    Nearly every later step requires the starter step, so an observable inside it would leave them
    all unreachable when the panel is wrong. The About step comes straight after the starter,
    names what a starter must never claim and which views it must never offer, names sections
    every world offers so an empty read cannot pass, and no step requires it.
    """
    ids = [step["id"] for step in STEPS["steps"]]
    about = _step(STEPS, "read-about-this-place")
    parameters = about["parameters"]
    assert ids.index("read-about-this-place") == ids.index("enter-owned-starter") + 1
    assert about["requires"] == ["enter-owned-starter"]
    assert [o["id"] for o in about["expect"]["page"]] == [
        "about-states-the-world",
        "starter-offers-no-district-views",
    ]
    assert parameters["never_says"] and parameters["never_says_reason"].strip()
    assert parameters["never_offers"] and parameters["never_offers_reason"].strip()
    assert parameters["offers"] and parameters["offers_reason"].strip()
    assert not set(parameters["offers"]) & set(parameters["never_offers"])
    waiting = [s["id"] for s in STEPS["steps"] if "read-about-this-place" in s.get("requires", [])]
    assert waiting == []
    assert len([s for s in STEPS["steps"] if "enter-owned-starter" in s.get("requires", [])]) > 1


def test_every_step_names_its_observable_result():
    for step in STEPS["steps"]:
        declared = [o for observables in step["expect"].values() for o in observables]
        assert declared, step["id"]
        assert all(o["says"].strip() for o in declared), step["id"]


def test_a_step_that_names_no_observable_result_is_not_well_formed():
    found = _problems_with(lambda s: _step(s, "name-world").update(expect={}))
    assert "name-world: names no observable result (expect is empty)" in found
    found = _problems_with(lambda s: _step(s, "name-world").update(expect={"page": []}))
    assert "name-world: names no observable result" in found
    found = _problems_with(lambda s: _step(s, "name-world")["expect"]["page"][0].update(says="  "))
    assert any("does not say what it expects" in p for p in found)
    found = _problems_with(
        lambda s: _step(s, "name-world")["expect"].update(screen=[{"id": "x", "says": "y"}])
    )
    assert "name-world: expect has an unknown kind 'screen'" in found


def test_a_step_serving_no_gate_or_an_unstated_gate_is_not_well_formed():
    found = _problems_with(lambda s: _step(s, "name-world").update(gates=[]))
    assert "name-world: serves no gate" in found
    found = _problems_with(lambda s: _step(s, "name-world")["gates"].append("delivery:Speed"))
    assert any("'delivery:Speed', which the owning document does not state" in p for p in found)


def test_a_step_may_require_only_an_earlier_step():
    found = _problems_with(lambda s: _step(s, "access-gate")["requires"].append("name-world"))
    assert "access-gate: requires 'name-world', which is not an earlier step" in found


def test_a_step_the_product_cannot_attempt_says_why_and_runs_in_no_session():
    unavailable = [step for step in STEPS["steps"] if "not_available" in step]
    assert unavailable, "the positive control needs at least one declared step"
    for step in unavailable:
        assert step["not_available"].strip() and "session" not in step
    identifier = unavailable[0]["id"]
    found = _problems_with(lambda s: _step(s, identifier).update(not_available=" "))
    assert f"{identifier}: not_available must say why" in found
    found = _problems_with(lambda s: _step(s, identifier).update(session="arrival"))
    assert f"{identifier}: a step the product cannot attempt runs in no session" in found


def test_hosted_model_steps_are_estimated_within_the_decision_threshold():
    hosted = [step for step in STEPS["steps"] if step.get("hosted_model")]
    assert hosted and all(step["spend_estimate_source"].strip() for step in hosted)
    assert steplist.spend_estimate(STEPS) <= steplist.Decimal(STEPS["spend"]["ask_before_usd"])
    found = _problems_with(lambda s: _step(s, hosted[0]["id"]).update(spend_estimate_usd="0.75"))
    assert any("that needs a decision before a run" in p for p in found)
    found = _problems_with(lambda s: _step(s, hosted[0]["id"]).pop("spend_estimate_usd"))
    assert f"{hosted[0]['id']}: a hosted-model step needs spend_estimate_usd" in found


def test_every_runnable_step_has_exactly_one_handler():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    listed = subprocess.run(
        [node, str(REHEARSAL / "session.mjs"), "--list-handlers"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    browser_handlers = set(json.loads(listed.stdout))
    runners = {session["id"]: session["runner"] for session in STEPS["sessions"]}
    runnable = [step for step in STEPS["steps"] if "not_available" not in step]
    assert browser_handlers == {s["id"] for s in runnable if runners[s["session"]] == "browser"}
    assert set(REHEARSE.ORCHESTRATED) == {
        s["id"] for s in runnable if runners[s["session"]] == "orchestrator"
    }
    unavailable = {step["id"] for step in STEPS["steps"] if "not_available" in step}
    assert not unavailable & (browser_handlers | set(REHEARSE.ORCHESTRATED))


def test_every_session_preparation_is_registered():
    named = {session["prepare"] for session in STEPS["sessions"] if session.get("prepare")}
    assert named and named <= set(REHEARSE.PREPARATIONS)


def _passing(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "passed",
        "reason": None,
        "observations": [
            {"id": observable["id"], "ok": True, "observed": None}
            for observables in step["expect"].values()
            for observable in observables
        ],
        "evidence": {},
    }


def _run_block() -> dict[str, Any]:
    return {
        "started_at": "2026-09-23T00:00:00+00:00",
        "finished_at": "2026-09-23T00:10:00+00:00",
        "rehearsal_tree": {"head": "0" * 40, "diff_head_sha256": "0" * 64},
        "application_tree": None,
        "steps_sha256": steplist.digest(),
    }


def test_a_result_reports_every_step_once_and_the_first_failure_of_each_gate():
    runnable = [step for step in STEPS["steps"] if "not_available" not in step]
    outcomes = {step["id"]: _passing(step) for step in runnable}
    outcomes["place-reviewed-object"] = {
        "status": "failed",
        "reason": "did not hold: object-listed",
        "observations": [{"id": "object-listed", "ok": False, "observed": []}],
        "evidence": {},
    }
    # A reported pass that checked less than the step list declares.
    outcomes["name-world"]["observations"].pop()
    # A reported pass that checked something the step list does not declare.
    outcomes["explore-walk"]["observations"].append({"id": "extra-check", "ok": True})
    del outcomes["returning-user-reopens"]
    unreached = {"returning-user-reopens": "the page session ended before this step"}

    document = resultdoc.assemble(STEPS, GATES, outcomes, unreached, _run_block())
    schema = json.loads((REHEARSAL / "result.schema.json").read_text())
    jsonschema.validate(document, schema)

    assert [step["id"] for step in document["steps"]] == [step["id"] for step in STEPS["steps"]]
    by_id = {step["id"]: step for step in document["steps"]}
    assert by_id["name-world"]["status"] == "failed"
    assert by_id["name-world"]["reason"].startswith("declared but not checked: title-after-reload")
    assert by_id["explore-walk"]["status"] == "failed"
    undeclared = "checked but not declared in the step list: extra-check"
    assert undeclared in by_id["explore-walk"]["reason"]
    assert by_id["returning-user-reopens"]["status"] == "not_reachable"
    for step in STEPS["steps"]:
        if "not_available" in step:
            assert by_id[step["id"]]["status"] == "not_available"
            assert by_id[step["id"]]["reason"] == step["not_available"]
    assert sum(document["summary"].values()) == len(STEPS["steps"])

    gates = {gate["gate"]: gate for gate in document["gates"]}
    assert set(gates) == {gate.key for gate in GATES}
    creation = gates["milestone:Durable creation"]
    assert creation["status"] == "failed"
    assert creation["first_failure"] == {
        "step": "place-reviewed-object",
        "reason": "did not hold: object-listed",
        "owner_area": _step(STEPS, "place-reviewed-object")["owner_area"],
    }
    # World entry's first failed step in step order is name-world, ahead of the unreached return.
    assert gates["milestone:World entry"]["first_failure"]["step"] == "name-world"
    assert gates["delivery:Independent use"] == gates["delivery:Independent use"] | {
        "status": "passed",
        "first_failure": None,
    }


def test_a_failed_step_fails_its_gate_whatever_comes_before_it():
    # A gate whose declared not-available step comes ahead of a step that runs and fails must still
    # report the failure. The step list is reordered on a copy so that order exists whatever the
    # step list holds.
    steps = copy.deepcopy(STEPS)
    moved = _step(steps, "observe-a-person-and-footage")
    steps["steps"].remove(moved)
    steps["steps"].insert([s["id"] for s in steps["steps"]].index("access-gate"), moved)
    runnable = [step for step in steps["steps"] if "not_available" not in step]
    outcomes = {step["id"]: _passing(step) for step in runnable}
    outcomes["access-gate"] = {
        "status": "failed",
        "reason": "did not hold: gate-shown",
        "observations": [],
        "evidence": {},
    }
    document = resultdoc.assemble(steps, GATES, outcomes, {}, _run_block())
    release = next(g for g in document["gates"] if g["gate"] == "delivery:Release rehearsal")
    order = [s["status"] for s in release["steps"]]
    assert order.index("not_available") < order.index("failed")
    assert release["status"] == "failed"
    assert release["first_failure"]["step"] == "access-gate"
    personal = next(g for g in document["gates"] if g["gate"] == "milestone:Personal-media path")
    assert personal["status"] == "not_available" and personal["first_failure"] is None


def test_the_model_rights_are_given_in_the_drawer_by_one_hosted_step():
    """The rights a grounded answer needs are ticked in the photo drawer, not posted by a route.

    One step gives them, after the first in-app admission and before the place is confirmed, which
    requires it; it is the photos session's hosted step, carrying the job wait the model work needs,
    and it checks both what the page shows and what the server recorded.
    """
    ids = [step["id"] for step in STEPS["steps"]]
    rights = _step(STEPS, "grant-model-rights-in-app")
    assert not [i for i in ids if i.startswith("grant-model-rights") and i != rights["id"]]
    assert "not_available" not in rights and rights["session"] == "photos"
    assert rights["requires"] == ["authorize-admission-in-app"]
    assert _step(STEPS, "confirm-proposed-place")["requires"] == ["grant-model-rights-in-app"]
    assert rights["hosted_model"] is True and rights["spend_estimate_source"].strip()
    parameters = rights["parameters"]
    assert parameters["roles"] and parameters["roles_reason"].strip()
    assert parameters["job_wait_seconds"] > 0 and parameters["job_wait_reason"].strip()
    photos = next(s for s in STEPS["sessions"] if s["id"] == "photos")
    assert photos["budget_seconds"] > parameters["job_wait_seconds"]
    assert {kind: [o["id"] for o in found] for kind, found in rights["expect"].items()} == {
        "page": ["rights-offered", "rights-listed"],
        "api": ["rights-recorded", "vision-ran", "place-proposed"],
    }


def test_a_runner_may_not_report_a_step_as_not_available():
    runnable = next(step for step in STEPS["steps"] if "not_available" not in step)
    outcome = {"status": "not_available", "reason": "said so", "observations": [], "evidence": {}}
    document = resultdoc.assemble(STEPS, GATES, {runnable["id"]: outcome}, {}, _run_block())
    reported = next(step for step in document["steps"] if step["id"] == runnable["id"])
    assert reported["status"] == "failed"
    assert "which a runner may not report" in reported["reason"]
