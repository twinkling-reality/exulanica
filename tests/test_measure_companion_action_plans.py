"""The P1 harness in ``scripts/measure_companion_action_plans.py``, without a server.

These hold what the harness decides by itself, since it imports nothing from the product: the
body it sends for each page context, how it reads an answer in the set's terms, when it stops, and
that the frozen set and the scripted plan it writes for checking itself fit each other. Running it
against a stack is the measurement.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "measure_companion_action_plans.py"
SET = ROOT / "docs" / "evaluation" / "2026-10-02-companion-action-plans-set.json"
CONTROL_STEP = "POST /world/versions/{version_id}/society/control/steps"
CONTROL = "PUT /world/versions/{version_id}/society/control"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_measure_action_plans", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _load()

FIXTURES = {
    name: {
        "entry_id": f"entry-{name}",
        "world_id": f"world-{name}",
        "version_id": f"00000000-0000-4000-8000-00000000000{index}",
        "state_sha256": str(index) * 64,
        "region_id": "region:starter",
        "regions": ["region:starter"],
        "objects": {} if name == "bare" else {n: f"p1-{n}" for n, _, _ in H.SQUARE_OBJECTS},
        "token_file": H.FIXTURE_TOKENS[name],
    }
    for index, name in enumerate(H.FIXTURE_TOKENS, start=1)
}
NAMES = {f"p1-{n}": n for n, _, _ in H.SQUARE_OBJECTS}


def _item(**fields):
    return {
        "fixture": "square",
        "context": "full",
        "utterance": "words",
        "appearance_basis": None,
        "expected": None,
        "planted": [],
        **fields,
    }


def test_the_harness_imports_nothing_from_the_product():
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
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


def test_the_frozen_set_reproduces_its_digest_and_a_changed_one_is_refused(tmp_path):
    record, file_sha = H.load_set(SET)

    assert file_sha == hashlib.sha256(SET.read_bytes()).hexdigest()
    assert len(record["records"]) == 78
    assert len({r["id"] for r in record["records"]}) == 78
    document = json.loads(SET.read_text())
    document["record"]["records"][0]["utterance"] = "Put two benches here."
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(document))
    with pytest.raises(SystemExit, match="record_sha256"):
        H.load_set(changed)


def test_the_split_comes_only_from_the_prefix_the_set_preregistered():
    prefix = "a" * 64
    records = [{"id": f"r-{i}", "utterance": f"words {i}"} for i in range(40)]
    assignment = [[r["id"], H.split_of(prefix, r["utterance"])] for r in records]
    rule = {
        "prefix_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
        "assignment_sha256": hashlib.sha256(
            json.dumps(assignment, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    drawn = H.splits({"split": rule, "records": records}, prefix)

    assert set(drawn.values()) == {"development", "held_out"}
    assert drawn != {r["id"]: H.split_of("", r["utterance"]) for r in records}
    with pytest.raises(SystemExit, match="prefix_sha256"):
        H.splits({"split": rule, "records": records}, "b" * 64)


def test_each_page_context_sends_exactly_what_it_names():
    full = H.request_body(_item(), FIXTURES)
    assert full["origin_role"] == "fictional"
    assert full["context"]["placement"] == {"region_id": "region:starter", "transform": H.POINTED}
    assert full["context"]["viewer"]["region_id"] == "region:starter"
    assert "selected_object_id" not in full["context"]
    assert "appearance_basis" not in full

    assert "placement" not in H.request_body(_item(context="no-placement"), FIXTURES)["context"]
    assert "viewer" not in H.request_body(_item(context="no-viewer"), FIXTURES)["context"]
    assert "origin_role" not in H.request_body(_item(context="no-role"), FIXTURES)
    selected = H.request_body(_item(context="full+selected:bench-2"), FIXTURES)
    assert selected["context"]["selected_object_id"] == "p1-bench-2"
    playing = H.request_body(
        _item(fixture="square-playing", appearance_basis="authored_design"), FIXTURES
    )
    assert playing["version_id"] == FIXTURES["square-people"]["version_id"]
    assert playing["appearance_basis"] == "authored_design"
    with pytest.raises(ValueError):
        H.request_body(_item(context="half"), FIXTURES)


def _plan(kind, steps=(), **fields):
    return {
        "outcome": "plan",
        "kind": kind,
        "steps": list(steps),
        "clarification": None,
        "refusal": None,
        **fields,
    }


def test_a_world_edit_is_read_by_operation_and_the_objects_fixture_name():
    plan = _plan(
        "world_edit",
        [
            {
                "operation": "x",
                "action": {
                    "operation": "move_object",
                    "asset_key": None,
                    "object_id": "p1-bench-1",
                    "arrangement_key": None,
                    "arrangement_version": None,
                },
            }
        ],
    )
    seen = H.observe(plan, NAMES)

    assert seen["steps"] == [{"operation": "move_object", "object": "bench-1"}]
    right = {
        "outcome": "plan",
        "kind": "world_edit",
        "steps": [{"operation": "move_object", "object": "bench-1"}],
    }
    wrong = {**right, "steps": [{"operation": "move_object", "object": "bench-2"}]}
    assert H.compare(right, seen)["exact"] is True
    assert H.compare(wrong, seen) == {
        "scored": True,
        "parts": {"outcome": True, "kind": True, "steps": False},
        "exact": False,
    }
    stranger = H.observe(
        _plan(
            "world_edit",
            [
                {
                    "operation": "x",
                    "action": {"operation": "remove_object", "object_id": "p1-elsewhere"},
                }
            ],
        ),
        NAMES,
    )
    assert stranger["steps"] == [{"operation": "remove_object", "object": "unlisted:p1-elsewhere"}]


def test_simulation_is_read_by_its_action_and_an_advance_by_its_minutes():
    def step(operation, action, **slots):
        return {"operation": operation, "action": {"operation": action, **slots}}

    paused_advance = _plan(
        "simulation", [step(CONTROL_STEP, "advance", minutes=3, minute=m) for m in (1, 2, 3)]
    )
    playing_advance = _plan(
        "simulation",
        [
            step(CONTROL, "pause", speed=1),
            step(CONTROL_STEP, "advance", minute=1),
            step(CONTROL_STEP, "advance", minute=2),
            step(CONTROL, "play", speed=1),
        ],
    )
    speed = _plan("simulation", [step(CONTROL, "set_speed", speed=4)])
    wanted = {
        "outcome": "plan",
        "kind": "simulation",
        "simulation": {"operation": "advance", "speed": None, "minutes": 3},
    }

    assert H.observe(paused_advance, NAMES)["simulation"] == wanted["simulation"]
    assert H.observe(playing_advance, NAMES)["simulation"]["minutes"] == 2
    assert H.compare(wanted, H.observe(paused_advance, NAMES))["exact"] is True
    assert H.compare(wanted, H.observe(playing_advance, NAMES))["exact"] is False
    four = {
        "outcome": "plan",
        "kind": "simulation",
        "simulation": {"operation": "set_speed", "speed": 4, "minutes": None},
    }
    two = {**four, "simulation": {**four["simulation"], "speed": 2}}
    assert H.compare(four, H.observe(speed, NAMES))["exact"] is True
    assert H.compare(two, H.observe(speed, NAMES))["exact"] is False


def test_clarifications_and_refusals_compare_as_sets_in_the_sets_terms():
    clarify = {
        "outcome": "clarify",
        "kind": "world_edit",
        "steps": [],
        "refusal": None,
        "clarification": {
            "code": "object_ambiguous",
            "candidates": [
                {"value": "p1-bench-2", "title": "Bench", "selected": False},
                {"value": "p1-bench-1", "title": "Bench", "selected": False},
            ],
        },
    }
    expected = {
        "outcome": "clarify",
        "kind": "world_edit",
        "clarification": {"code": "object_ambiguous", "candidates": ["bench-1", "bench-2"]},
    }
    assert H.compare(expected, H.observe(clarify, NAMES))["exact"] is True
    narrower = {
        **expected,
        "clarification": {"code": "object_ambiguous", "candidates": ["bench-1"]},
    }
    assert H.compare(narrower, H.observe(clarify, NAMES))["exact"] is False

    refused = {
        "outcome": "refused",
        "kind": "appearance",
        "steps": [],
        "clarification": None,
        "refusal": {"code": "no_evidence", "alternatives": ["authored_design"]},
    }
    no_evidence = {
        "outcome": "refused",
        "kind": "appearance",
        "refusal": {"code": "no_evidence", "alternatives": ["authored_design"]},
    }
    assert H.compare(no_evidence, H.observe(refused, NAMES))["exact"] is True
    bare = {**no_evidence, "refusal": {"code": "no_evidence", "alternatives": []}}
    assert H.compare(bare, H.observe(refused, NAMES))["exact"] is False


def test_an_appearance_plan_is_scored_on_its_first_step_alone():
    plan = _plan(
        "appearance",
        [
            {
                "operation": "POST /world/styles/previews",
                "action": {"operation": "propose_appearance"},
            },
            {
                "operation": "POST /world/styles/previews/{preview_id}/apply",
                "action": {"operation": "apply_appearance"},
            },
        ],
    )
    expected = {
        "outcome": "plan",
        "kind": "appearance",
        "steps": [{"operation": "propose_appearance"}],
    }

    assert H.compare(expected, H.observe(plan, NAMES))["exact"] is True
    assert H.compare(None, H.observe(plan, NAMES)) == {"scored": False}


def test_a_planted_value_is_found_in_what_a_step_would_send_and_nowhere_else():
    planted = ["planted-region-3e7"]
    in_body = _plan(
        "simulation",
        [
            {
                "operation": "x",
                "action": {},
                "bind": {},
                "query": {},
                "body": {"region_id": "planted-region-3e7"},
            }
        ],
    )
    in_preview = _plan(
        "world_edit",
        [
            {
                "operation": "x",
                "action": {},
                "body": {},
                "preview": {"body": {"note": "planted-region-3e7"}},
            }
        ],
    )
    in_clarification = {
        "outcome": "clarify",
        "steps": [],
        "clarification": {"actions": [{"region_id": "planted-region-3e7"}]},
    }
    in_refusal_words = {
        "outcome": "refused",
        "steps": [],
        "refusal": {"detail": "planted-region-3e7"},
    }

    assert H.planted_found(in_body, planted) == planted
    assert H.planted_found(in_preview, planted) == planted
    assert H.planted_found(in_clarification, planted) == planted
    assert H.planted_found(in_refusal_words, planted) == []
    assert H.planted_found(in_body, []) == []


def test_the_budget_stops_at_the_ceiling_and_before_a_request_that_could_pass_it():
    budget = H.Budget(Decimal("0.25"))
    budget.add(Decimal("0.10"))
    assert budget.stop_before_next() is None
    budget.add(Decimal("0.10"))
    assert "would pass the ceiling" in budget.stop_before_next()
    exact = H.Budget(Decimal("0.25"), spent=Decimal("0.25"))
    assert "reached" in exact.stop_before_next()

    known = [
        {"usd": "0.0004", "cost_basis": "known", "outcome": "completed"},
        {"usd": None, "cost_basis": "not_sent", "outcome": "failed"},
    ]
    assert H.cost_of(known) == (Decimal("0.0004"), True)
    assert H.cost_of([{"usd": None, "cost_basis": "unknown"}]) == (Decimal(0), False)


def test_provider_errors_stop_a_pass_past_ten_percent():
    assert H.provider_error(200, [{"outcome": "completed"}]) is False
    assert H.provider_error(200, [{"outcome": "timed_out"}]) is True
    assert H.provider_error(503, []) is True
    assert H.errors_stop(7, 78) is None
    assert H.errors_stop(8, 78) is not None


def test_the_floor_is_the_question_share_of_the_scored_requests():
    record, _ = H.load_set(SET)
    every = {r["id"] for r in record["records"]}
    floor = H.floor_score(record["records"], every)

    assert floor["exact"] == sum(r["stratum"] == "question" for r in record["records"])
    assert floor["scored"] == sum(r["expected"] is not None for r in record["records"])


def test_every_expectation_names_what_its_fixture_holds():
    record, _ = H.load_set(SET)
    catalogs = sorted((ROOT / "assets" / "catalogs" / "world-objects").glob("world-object.v*.json"))
    newest = json.loads(catalogs[-1].read_text())
    kinds = {entry["asset_key"] for entry in newest["entries"]}
    for item in record["records"]:
        fixture = FIXTURES[H.FIXTURE_OF[item["fixture"]]]
        H.parse_context(item["context"])
        _, selected = H.parse_context(item["context"])
        assert selected is None or selected in fixture["objects"], item["id"]
        expected = item["expected"]
        if expected is None:
            assert item["stratum"] == "injection" and item["planted"], item["id"]
            continue
        for step in expected.get("steps", []):
            assert step.get("asset_key") in (None, *kinds), item["id"]
            assert step.get("object") in (None, *fixture["objects"]), item["id"]
        clarification = expected.get("clarification") or {}
        if clarification.get("code") == "object_ambiguous":
            assert set(clarification["candidates"]) <= set(fixture["objects"]), item["id"]
        if clarification.get("code") == "asset_ambiguous":
            assert set(clarification["candidates"]) <= kinds, item["id"]


def test_the_scripted_plan_answers_every_request_and_fills_only_the_offered_slots(
    tmp_path, monkeypatch
):
    # The authored draft is read from the candidate by a child interpreter; its own test is the
    # scripted check against a stack, where the style lifecycle takes it or refuses it.
    monkeypatch.setattr(H, "authored_draft", lambda worktree: {"profile": "stand-in"})
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps(FIXTURES))
    for answers in ("expected", "question"):
        out = tmp_path / f"{answers}.json"
        H.main(
            [
                "scripted-plan",
                "--set",
                str(SET),
                "--fixtures",
                str(fixtures),
                "--worktree",
                str(ROOT),
                "--answers",
                answers,
                "--out",
                str(out),
            ]
        )
        plan = json.loads(out.read_text())
        record, _ = H.load_set(SET)
        classifier = [r for r in plan["rules"] if "The sentence:" in r["match"]["contains"]]
        assert len(classifier) == len({r["utterance"] for r in record["records"]})
        if answers == "question":
            assert {json.loads(r["content"])["kind"] for r in plan["rules"]} == {"question"}
            continue
        for rule in plan["rules"]:
            draft = json.loads(rule["content"])
            for step in draft.get("steps", []):
                assert {"operation", "kinds", "arrangements"} <= set(step)
        bare = [
            r
            for r in record["records"]
            if r["fixture"] == "bare" and (r["expected"] or {}).get("kind") == "world_edit"
        ]
        for item in bare:
            wanted = H.escaped(f'The request:\n"""{item["utterance"]}"""')
            (rule,) = [r for r in plan["rules"] if r["match"]["contains"] == wanted]
            assert all("objects" not in s for s in json.loads(rule["content"])["steps"])


def test_the_drafters_object_labels_put_the_selected_object_first_then_newest():
    square = FIXTURES["square"]

    assert H.object_labels(square, None) == {
        "bench-2": "object-1",
        "bench-1": "object-2",
        "lamp": "object-3",
        "stall": "object-4",
    }
    assert H.object_labels(square, "lamp") == {
        "lamp": "object-1",
        "bench-2": "object-2",
        "bench-1": "object-3",
        "stall": "object-4",
    }
    assert H.object_labels(FIXTURES["bare"], None) == {}
