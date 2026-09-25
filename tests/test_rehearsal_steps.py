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
    # Every declared source yields gates, so coverage cannot pass on an empty gate list.
    assert {gate.source for gate in GATES} == {source["key"] for source in STEPS["gate_sources"]}
    served = {gate for step in STEPS["steps"] for gate in step["gates"]}
    unserved = STEPS["unserved_gates"]
    assert [gate.key for gate in GATES if gate.key not in served and gate.key not in unserved] == []
    # A gate said to have no step has none, and says why; one served in part has steps.
    assert not served & set(unserved) and all(reason.strip() for reason in unserved.values())
    assert set(STEPS["gates_in_part"]) <= served


def test_a_gate_said_to_have_no_step_or_served_in_part_is_held_to_the_document():
    unserved = next(iter(STEPS["unserved_gates"]))
    found = _problems_with(lambda s: s["unserved_gates"].pop(unserved))
    assert any(f"gate {unserved!r}" in p and "has no step" in p for p in found)
    found = _problems_with(lambda s: s["unserved_gates"].update({unserved: " "}))
    assert f"unserved_gates gives no reason for {unserved!r}" in found
    found = _problems_with(lambda s: s["unserved_gates"].update({"delivery:Speed": "slow"}))
    unstated = "unserved_gates names 'delivery:Speed', which the owning document does not state"
    assert unstated in found
    found = _problems_with(lambda s: s["unserved_gates"].update({"foundation:Inspection": "none"}))
    assert "gate 'foundation:Inspection' is said to have no step, and steps serve it" in found
    found = _problems_with(lambda s: s["gates_in_part"].update({unserved: "some"}))
    assert f"gate {unserved!r} is said to be served in part, and no step serves it" in found


def test_the_foundation_deliverables_are_read_from_their_own_level_three_section():
    """The saved-world foundation's table sits inside the first milestone's section; each source
    reads only its own table, so neither takes the other's rows."""
    by_source = {
        source: [gate.name for gate in GATES if gate.source == source]
        for source in ("milestone", "foundation")
    }
    assert by_source["foundation"] and by_source["milestone"]
    assert not set(by_source["foundation"]) & set(by_source["milestone"])
    assert "Deliverable" not in by_source["milestone"] + by_source["foundation"]
    assert "World entry" in by_source["foundation"]


def test_a_delivery_gate_with_no_step_fails(tmp_path):
    root = _direction_copy(
        tmp_path,
        "6. **Release rehearsal:**",
        "6. **Unrehearsed gate:** a gate no step serves.\n7. **Release rehearsal:**",
    )
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    found = steplist.problems(STEPS, gates)
    assert any(
        "gate 'delivery:Unrehearsed gate'" in problem and "has no step" in problem
        for problem in found
    )


def test_a_milestone_deliverable_with_no_step_fails(tmp_path):
    root = _direction_copy(
        tmp_path / "milestone",
        "| A model per group |",
        "| Unrehearsed deliverable | A deliverable no step serves. |\n| A model per group |",
    )
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    assert any(
        "gate 'milestone:Unrehearsed deliverable'" in problem
        for problem in steplist.problems(STEPS, gates)
    )
    root = _direction_copy(
        tmp_path / "foundation",
        "| Inspection |",
        "| Unrehearsed deliverable | A deliverable no step serves. |\n| Inspection |",
    )
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    assert any(
        "gate 'foundation:Unrehearsed deliverable'" in problem
        for problem in steplist.problems(STEPS, gates)
    )


def test_a_renamed_gate_leaves_its_steps_naming_a_gate_the_document_does_not_state(tmp_path):
    root = _direction_copy(tmp_path, "**Persistence and replay:**", "**Durability:**")
    gates = steplist.read_gates(STEPS["gate_sources"], root)
    found = steplist.problems(STEPS, gates)
    unstated = "'delivery:Persistence and replay', which the owning document does not state"
    assert any(unstated in problem for problem in found)
    assert any("gate 'delivery:Durability'" in p and "has no step" in p for p in found)


def test_the_gate_reader_refuses_a_missing_or_empty_section(tmp_path):
    missing = _direction_copy(tmp_path / "missing", "## First milestone", "## First release")
    with pytest.raises(steplist.StepListError, match="has no section '## First milestone'"):
        steplist.read_gates(STEPS["gate_sources"], missing)
    below = _direction_copy(
        tmp_path / "below", "### Saved-world foundation", "#### Saved-world foundation"
    )
    with pytest.raises(steplist.StepListError, match="has no section '### Saved-world foundation'"):
        steplist.read_gates(STEPS["gate_sources"], below)
    empty = _direction_copy(tmp_path / "empty", "1. **Usable world:**", "1. Usable world:")
    text = (empty / "docs" / DIRECTION.name).read_text(encoding="utf-8")
    names = (
        "Models in their roles",
        "Swap and compare",
        "Persistence and replay",
        "Independent use",
        "Release rehearsal",
    )
    for name in names:
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
    creation = gates["foundation:Durable creation"]
    assert creation["status"] == "failed"
    assert creation["first_failure"] == {
        "step": "place-reviewed-object",
        "reason": "did not hold: object-listed",
        "owner_area": _step(STEPS, "place-reviewed-object")["owner_area"],
    }
    # World entry's first failed step in step order is name-world, ahead of the unreached return.
    assert gates["foundation:World entry"]["first_failure"]["step"] == "name-world"
    assert gates["foundation:Developer proof"] == gates["foundation:Developer proof"] | {
        "status": "not_reachable",
        "first_failure": None,
    }
    # A gate no step serves is reported with the step list's reason, never left out.
    for key, reason in STEPS["unserved_gates"].items():
        assert gates[key] | {"status": "not_served", "reason": reason, "steps": []} == gates[key]


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
    personal = next(g for g in document["gates"] if g["gate"] == "foundation:Personal-media path")
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


def _all_passing(steps: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["id"]: _passing(step) for step in steps["steps"] if "not_available" not in step}


def test_the_stand_in_review_is_stated_once_and_every_gate_resting_on_it_is_qualified():
    """The human review is the rehearsal driver's stand-in, said once, and never a plain pass.

    The step list states the stand-in once, and the step that records the review gives it. Every
    step that rests on it through what it requires carries its statement in the result, and every
    gate one of those steps serves reports ``passed_on_stand_in`` with the stand-in's qualification
    where it would otherwise pass. A gate no such step serves still passes plainly.
    """
    stand_in = STEPS["stand_ins"]["human-review"]
    assert "rehearsal driver" in stand_in["reviewer_name"]
    assert "not a person's review" in stand_in["reviewer_name"]
    assert "stands in for a person's review" in stand_in["statement"]
    givers = [step["id"] for step in STEPS["steps"] if step.get("stand_in") == "human-review"]
    assert givers[0] == "review-photographs-in-app"
    resting = steplist.stand_ins_of(STEPS)
    for identifier in (
        "wait-for-depth-and-grouping",
        "make-world-from-photographs",
        "ask-grounded-question",
        "companion-proposes-appearance-change",
        "return-to-made-world",
    ):
        assert resting[identifier] == ["human-review"], identifier
    assert resting["name-world"] == [] and resting["confirm-proposed-place"] == []

    document = resultdoc.assemble(STEPS, GATES, _all_passing(STEPS), {}, _run_block())
    jsonschema.validate(document, json.loads((REHEARSAL / "result.schema.json").read_text()))
    by_id = {step["id"]: step for step in document["steps"]}
    assert by_id["make-world-from-photographs"]["stand_ins"] == [
        {"key": "human-review", "statement": stand_in["statement"]}
    ]
    assert by_id["name-world"]["stand_ins"] == []
    gates = {gate["gate"]: gate for gate in document["gates"]}
    companion = gates["foundation:Companion interaction"]
    assert companion["status"] == "passed_on_stand_in"
    assert companion["qualification"] == [stand_in["gate_qualification"]]
    assert gates["foundation:Durable creation"]["status"] == "passed"
    assert gates["foundation:Durable creation"]["qualification"] == []
    # A gate its steps serve in part never passes plainly, and says what they leave out.
    for key, gap in STEPS["gates_in_part"].items():
        assert gates[key]["status"] == "passed_in_part"
        assert gates[key]["qualification"][0] == f"In part: {gap}"
    # A gate that fails or cannot be reached keeps that status and names the stand-in, and its
    # qualification, which speaks of a pass, is empty.
    assert gates["foundation:Personal-media path"]["status"] == "not_available"
    assert gates["foundation:Personal-media path"]["stand_ins"] == ["human-review"]
    assert gates["foundation:Personal-media path"]["qualification"] == []


def test_a_stand_in_no_step_gives_or_a_step_giving_an_unstated_one_is_not_well_formed():
    found = _problems_with(lambda s: _step(s, "review-photographs-in-app").pop("stand_in"))
    assert "stand-in 'human-review' is stated and no step gives it" not in found  # the addition
    found = _problems_with(lambda s: [step.pop("stand_in", None) for step in s["steps"]])
    assert "stand-in 'human-review' is stated and no step gives it" in found
    found = _problems_with(lambda s: _step(s, "review-photographs-in-app").update(stand_in="x"))
    assert "review-photographs-in-app: gives the stand-in 'x', which is not stated" in found
    found = _problems_with(lambda s: s["stand_ins"]["human-review"].update(reviewer_name=" "))
    assert "stand-in 'human-review' does not state its reviewer_name" in found


def test_a_result_that_drops_the_stand_in_from_a_passing_gate_is_refused_by_the_schema():
    document = resultdoc.assemble(STEPS, GATES, _all_passing(STEPS), {}, _run_block())
    schema = json.loads((REHEARSAL / "result.schema.json").read_text())
    gate = "foundation:Companion interaction"
    companion = next(g for g in document["gates"] if g["gate"] == gate)
    # Its status and its qualification both dropped: only the stand-in list is left to say it.
    companion["status"] = "passed"
    companion["qualification"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)


def test_the_personal_path_reviews_waits_makes_and_the_companion_moves_into_the_made_world():
    """Review, the depth and grouping wait and making the world come in order in the photos session;
    every Companion step rests on the made world; the return reopens it, reviews one more photograph
    and adds it to the made world on a confirmed preview."""
    ids = [step["id"] for step in STEPS["steps"]]
    path = [
        "review-photographs-in-app",
        "wait-for-depth-and-grouping",
        "make-world-from-photographs",
    ]
    assert (
        ids[ids.index("confirm-proposed-place") + 1 : ids.index("confirm-proposed-place") + 4]
        == path
    )
    assert all(_step(STEPS, i)["session"] == "photos" for i in path)
    for earlier, later in zip(["confirm-proposed-place", *path], path, strict=False):
        assert earlier in _step(STEPS, later)["requires"], later
    closure: dict[str, set[str]] = {}
    for step in STEPS["steps"]:
        closure[step["id"]] = set(step.get("requires", []))
        for required in step.get("requires", []):
            closure[step["id"]] |= closure[required]
    companion = [s["id"] for s in STEPS["steps"] if s.get("session") == "companion"]
    assert companion and all("make-world-from-photographs" in closure[i] for i in companion)
    returning = [s["id"] for s in STEPS["steps"] if s.get("session") == "return"]
    assert returning == [
        "returning-user-reopens",
        "return-to-made-world",
        "made-world-takes-new-photograph",
    ]
    addition = _step(STEPS, "made-world-takes-new-photograph")
    assert addition["stand_in"] == "human-review"
    assert addition["requires"] == ["return-to-made-world"]
    parameters = addition["parameters"]
    assert parameters["action"] == "add_photographs"
    assert parameters["buttons"]["add_photographs"].strip() and parameters["confirm"].strip()
    assert parameters["refusal_after"] == "personal_world_current"
    assert "refusal" not in parameters
    assert {kind: [o["id"] for o in found] for kind, found in addition["expect"].items()} == {
        "api": [
            "new-photograph-reviewed",
            "offer-reads-preview",
            "cancel-writes-nothing",
            "confirmed-with-preview",
            "world-advanced",
        ],
        "page": ["preview-before-write", "reopened-with-edits", "current-after-confirm"],
    }
    make = _step(STEPS, "make-world-from-photographs")
    assert {o["id"] for o in make["expect"]["api"]} == {
        "offer-read",
        "composed-as-read",
        "entry-saved",
    }
    assert {o["id"] for o in make["expect"]["page"]} == {
        "offer-shown",
        "world-opens",
        "list-offers-refusal",
    }


def test_the_companion_session_allows_each_utterance_every_deadline_the_page_waits_for_it():
    """The Companion budget is derived from the page's own deadlines, read from its source.

    Each hosted Companion step is one utterance; the page waits for its appearance classification
    and then for its answer, each as long as its constant in the application's source says. The
    session's allowance must cover all of them in turn, and the driver reads the same constants
    at run time (``rehearse.page_deadlines``), so the two cannot drift apart unnoticed.
    """
    deadlines = REHEARSE.page_deadlines(ROOT, STEPS["runtime"]["answer_deadlines"])
    assert set(deadlines) == set(STEPS["runtime"]["answer_deadlines"]["constants"])
    assert all(ms > 0 for ms in deadlines.values())
    session = next(s for s in STEPS["sessions"] if s["id"] == "companion")
    utterances = [
        s for s in STEPS["steps"] if s.get("session") == "companion" and s.get("hosted_model")
    ]
    assert len(utterances) == 3
    assert session["budget_seconds"] * 1000 >= len(utterances) * sum(deadlines.values())
    for name, ms in deadlines.items():
        assert f"{name} {ms // 1000} s" in session["budget_reason"], name
    missing = copy.deepcopy(STEPS["runtime"]["answer_deadlines"])
    missing["constants"] = ["NO_SUCH_TIMEOUT_MS"]
    with pytest.raises(REHEARSE.Refused, match="states no plain integer NO_SUCH_TIMEOUT_MS"):
        REHEARSE.page_deadlines(ROOT, missing)


def test_no_scene_job_exists_for_the_rehearsal_photographs_as_the_scene_step_states():
    """The scene-geometry statement rests on the photographs' capture times, read from the data.

    Grouped with the grouping stage's own parameters, the photos session's drawings fall into
    groups too small for the pose policy, which is why no scene job exists and the scene worker
    has nothing to claim. A drawing moved into one group with the others makes a group the
    policy selects, so the check can fail.
    """
    import datetime as dt

    from exulanica.ingest.scene_selection import SceneGroupPosePolicy
    from exulanica.ingest.scenes import group_captures
    from exulanica.ingest.stages import stage

    params = stage("scene_group").params

    def groups(inputs: list[dict[str, Any]]) -> list[Any]:
        captures = sorted(
            (
                {
                    "capture_id": index,
                    "utc_instant": dt.datetime.strptime(
                        f"{p['captured']} {p['utc_offset']}", "%Y:%m:%d %H:%M:%S %z"
                    ).isoformat(),
                }
                for index, p in enumerate(inputs)
            ),
            key=lambda capture: capture["utc_instant"],
        )
        found, ungrouped = group_captures(
            captures,
            max_time_gap_s=int(params["max_time_gap_s"]),
            max_distance_m=int(params["max_distance_m"]),
        )
        assert ungrouped == 0
        return found

    policy = SceneGroupPosePolicy()
    photos = next(s for s in STEPS["sessions"] if s["id"] == "photos")["inputs"]["photographs"]
    assert all(policy.selection_record(group) is None for group in groups(photos))
    together = [dict(p, captured=photos[0]["captured"]) for p in photos]
    assert any(policy.selection_record(group) is not None for group in groups(together))
    statement = _step(STEPS, "reconstruct-scene-geometry")["not_available"]
    assert "at least three photographs" in statement
    assert policy.minimum_member_count == 3


def test_the_derivative_worker_is_the_production_command_with_its_depth_model():
    """The worker the rehearsal starts is main's console script, configured as its code reads."""
    import tomllib

    from exulanica.ingest import worker_command

    worker = STEPS["runtime"]["derivative_worker"]
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts[worker["command"]] == "exulanica.ingest.worker_command:main"
    environment = worker["environment"]
    assert environment[worker_command.DEPTH_MODEL_ENV] == "moge"
    assert worker_command.DEPTH_DEVICE_ENV in environment
    assert worker["startup_seconds"] > 0 and worker["stop_seconds"] > 0


#: The steps whose handlers wait for derivative jobs (waitForJobs in handlers.mjs), each with its
#: own bound: a step without one waited for nothing and read the jobs before they ended.
JOB_WAITING_STEPS = (
    "grant-model-rights-in-app",
    "wait-for-depth-and-grouping",
    "photo-jobs-end-cleanly",
    "made-world-takes-new-photograph",
)


def test_every_wait_the_steps_declare_has_a_bound_and_a_reason():
    handlers = (REHEARSAL / "handlers.mjs").read_text()
    assert handlers.count("await waitForJobs(ctx,") == len(JOB_WAITING_STEPS)
    for identifier in JOB_WAITING_STEPS:
        parameters = _step(STEPS, identifier)["parameters"]
        assert parameters["job_wait_seconds"] > 0, identifier
        assert parameters["job_wait_reason"].strip(), identifier
    for step in STEPS["steps"]:
        for name, value in step.get("parameters", {}).items():
            if name.endswith(("_seconds", "_ms", "_milliseconds")):
                stem = name.rsplit("_", 1)[0]
                assert isinstance(value, int) and value > 0, (step["id"], name)
                assert step["parameters"].get(f"{stem}_reason", "").strip(), (step["id"], name)


def _instruments() -> set[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    listed = subprocess.run(
        [node, str(REHEARSAL / "session.mjs"), "--list-instruments"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return set(json.loads(listed.stdout))


def test_every_instrument_a_session_names_is_registered_and_says_why():
    named = {
        (session["id"], name)
        for session in STEPS["sessions"]
        for name in session.get("instruments", [])
    }
    assert named, "the positive control needs a session that names an instrument"
    registered = _instruments()
    assert {name for _, name in named} <= registered
    for session in STEPS["sessions"]:
        if session.get("instruments"):
            assert session["runner"] == "browser" and session["instruments_reason"].strip()
    assert "no-such-instrument" not in registered


#: The living world, in the order a person meets it, each step requiring the one it builds on.
LIVING = {
    "furnish-small-square": ["enter-owned-starter"],
    "bring-in-inhabitants": ["furnish-small-square"],
    "play-and-watch-walking": ["bring-in-inhabitants"],
    "inspect-an-inhabitant": ["play-and-watch-walking"],
    "object-in-use": ["play-and-watch-walking"],
    "pause-playback": ["play-and-watch-walking"],
}


def test_the_living_session_furnishes_brings_people_in_plays_inspects_and_pauses():
    """The living world is one browser session in the starter, played by the host it launches.

    Its steps come in the order a person meets them, each requiring the one it builds on, and
    each says why it serves the gates it names, since no gate of the first demonstration names a
    living world. The session measures walking with its instrument, and the launcher is asked to
    play the run's workspace, which is what lets People nearby offer Play at all.
    """
    living = [s for s in STEPS["steps"] if s.get("session") == "living"]
    assert {s["id"]: s["requires"] for s in living} == LIVING
    assert [s["id"] for s in living] == list(LIVING)
    for step in living:
        assert step["gates"] == ["milestone:A world to run", "delivery:Usable world"], step["id"]
        assert step["gates_reason"].strip(), step["id"]
    # They show part of both gates, never all of either: a town is not a starter with a square.
    assert {"milestone:A world to run", "delivery:Usable world"} <= set(STEPS["gates_in_part"])
    session = next(s for s in STEPS["sessions"] if s["id"] == "living")
    assert session["instruments"] == ["walker-positions"]
    ids = [s["id"] for s in STEPS["sessions"]]
    assert ids.index("appearance") < ids.index("living") < ids.index("photos")
    watch = _step(STEPS, "play-and-watch-walking")["parameters"]
    assert watch["walking_floor_m_per_s"] > 0 and watch["walking_floor_reason"].strip()
    # The pace bound lies between W2's two measured arms, 2.8 m/s walking on and 13.9 m/s rushing.
    assert "13.9" in watch["pace_reason"] and "2.8" in watch["pace_reason"]
    assert 2.8 < watch["pace_p95_at_most_m_per_s"] < 13.9
    assert STEPS["runtime"]["society_playback"]["launcher_flags"] == ["--society-playback"]
    # The session's allowance holds its bounds: the watch and the wait for someone at the square.
    in_use = _step(STEPS, "object-in-use")["parameters"]["in_use_wait_seconds"]
    assert session["budget_seconds"] > watch["sample_seconds"] + in_use


def test_the_first_use_square_is_taken_back_and_nothing_waits_on_it():
    """The card's square can only be pressed while the starter is empty, so it comes straight after
    the About panel, takes the square back one change at a time, and no step requires it: the
    creation steps start from a world with no object either way."""
    ids = [step["id"] for step in STEPS["steps"]]
    card = _step(STEPS, "start-with-small-square")
    assert ids.index("start-with-small-square") == ids.index("read-about-this-place") + 1
    assert card["session"] == "arrival" and card["requires"] == ["enter-owned-starter"]
    assert card["undo_reason"].strip() and card["gates_reason"].strip()
    card_id = card["id"]
    assert [s["id"] for s in STEPS["steps"] if card_id in s.get("requires", [])] == []
    assert "undone-newest-first" in {o["id"] for o in card["expect"]["api"]}
