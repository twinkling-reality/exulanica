"""The beings acceptance driver in ``scripts/acceptance/beings_rows.py``, without a server.

These hold what the driver reads and builds by itself, since it imports nothing from the product:
the scripted plans its Companion rows are served by are forms the product's own drafter vocabulary
takes, and the arrival world it reads names a scene the scene catalog ships. Running it against a
stack is the acceptance run itself.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from exulanica.selection.action_plan import DRAFT_OPERATIONS, MAX_CANDIDATES, MAX_STEPS

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "acceptance" / "beings_rows.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_beings_rows", DRIVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRIVE = _load()


def test_the_driver_imports_nothing_from_the_product():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "exulanica" not in imported


@pytest.mark.parametrize("plan_file", [DRIVE.THINGS_PLAN, DRIVE.OFFER_PLAN])
def test_each_companion_utterance_is_answered_by_one_classifier_and_one_drafter_rule(plan_file):
    plan = json.loads(plan_file.read_text())
    lines = list(plan["utterances"].values())
    # A rule matches by a substring that ends at the utterance's end, so no utterance may begin
    # another: the longer one would take the shorter one's rule.
    assert not [(a, b) for a in lines for b in lines if a != b and b.startswith(a)]
    for line in lines:
        matching = [r for r in plan["rules"] if r["match"]["contains"].endswith(line)]
        asked = sorted(r["match"]["contains"].split(":")[0] for r in matching)
        assert asked == ["The request", "The sentence"], line


@pytest.mark.parametrize("plan_file", [DRIVE.THINGS_PLAN, DRIVE.OFFER_PLAN])
def test_each_drafted_form_is_one_the_products_drafter_vocabulary_takes(plan_file):
    plan = json.loads(plan_file.read_text())
    drafted = {
        key: json.loads(rule["content"])["steps"]
        for key, line in plan["utterances"].items()
        for rule in plan["rules"]
        if rule["match"]["contains"] == 'The request:\\n\\"\\"\\"' + line
    }
    assert sorted(drafted) == sorted(plan["utterances"])
    for steps in drafted.values():
        for step in steps:
            assert list(step) == ["operation", "options"], "options are a step's last field"
            assert step["operation"] in DRAFT_OPERATIONS
            assert len(step["options"]) <= MAX_CANDIDATES
    if plan_file == DRIVE.THINGS_PLAN:
        # CP1's plan fits the bound, and its over-long answer is one step past it.
        assert len(drafted["evening"]) == 6 <= MAX_STEPS == DRIVE.PLAN_STEPS_MAXIMUM
        assert len(drafted["nine"]) == MAX_STEPS + 1


def test_an_answer_is_recorded_by_its_status_code_and_string_detail():
    assert DRIVE.answered(409, {"code": "being_played", "detail": "somebody else plays it"}) == [
        409,
        "being_played",
        "somebody else plays it",
    ]
    # A validation answer's detail is a list, and an empty answer has neither.
    assert DRIVE.answered(422, {"detail": [{"loc": ["body"]}]}) == [422, None, None]
    assert DRIVE.answered(204, None) == [204, None, None]


def test_the_arrival_world_it_reads_names_a_scene_whose_beings_the_scene_places():
    world, scene = DRIVE.arrival_world(ROOT)

    assert scene is not None and scene["scene"] == world["scene"]["scene"]
    placed = {thing["thing_id"] for thing in scene["things"]}
    assert {mind["thing_id"] for mind in scene["minds"]} <= placed
    assert scene["engine"] == DRIVE.D.THINGS_ENGINE


def test_a_plan_that_is_not_one_says_its_outcome_refusal_question_and_steps():
    plan = {
        "outcome": "refused",
        "refusal": {"code": "not_drafted"},
        "clarification": None,
        "steps": [{"state": "blocked", "code": "act_not_offered"}],
    }

    assert DRIVE.why_not(plan) == ["refused", "not_drafted", None, [["blocked", "act_not_offered"]]]


def _made(tick: int, doing: int, beings: int = 10) -> dict:
    """A society of things as the creation route answers it: ``doing`` of its beings stand, the
    rest are idle."""
    people = [{"action": {"kind": "stand" if n < doing else "idle"}} for n in range(beings)]
    return {"current_tick": tick, "state": {"inhabitants": people}}


def test_a_society_of_things_made_again_is_read_at_a_minute_the_opening_policy_yields():
    # The policy in force, read from its file: half the beings doing something, a least of minutes
    # before the seconds may stop the opening, and a most.
    policy = json.loads((ROOT / DRIVE.OPENING_POLICY).read_text(encoding="utf-8"))
    values = policy["values"]
    assert (policy["version"], values["active_share_milli"]) == (2, 500)
    least, most = values["minutes_minimum"], values["minutes_maximum"]
    assert 1 < least < most
    read = DRIVE.opened_as_the_policy_says
    # What the row expected before a society of things opened awake is now refused: minute 0 with
    # every being idle is a society the server did not open.
    assert read(_made(0, 0), policy) == (False, "minute 0 with 0 of 10 beings doing something")
    # Born idle, it is first read at minute 1 with nearly everyone doing something.
    assert read(_made(1, 129, 130), policy) == (
        True,
        "minute 1 with 129 of 130 beings doing something",
    )
    # Exactly half is the share; one fewer is not, short of the least minutes.
    assert read(_made(1, 5), policy)[0] is True
    assert read(_made(1, 4), policy)[0] is False
    assert read(_made(least - 1, 4), policy)[0] is False
    # A society already doing something when made is not advanced at all.
    assert read(_made(0, 5), policy)[0] is True
    # Short of the share it may stand only where the opening ran out of budget: at or past the
    # least minutes (the seconds stopped it) and never past the most.
    assert read(_made(least, 4), policy)[0] is True
    assert read(_made(most, 0), policy)[0] is True
    assert read(_made(most + 1, 10), policy)[0] is False
    # An answer that is no society, or holds nobody, is not one the policy yields.
    assert read(None, policy)[0] is False
    assert read({"current_tick": 1, "state": {"inhabitants": []}}, policy)[0] is False
    assert read({"current_tick": True, "state": _made(1, 9)["state"]}, policy)[0] is False
