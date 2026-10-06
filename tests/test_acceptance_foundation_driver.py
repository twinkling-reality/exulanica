"""The foundation acceptance driver in ``scripts/acceptance/foundation.py``, without a server.

These hold the driver's own rules: a row is passed, failed or blocked and never skipped, a blocked
prerequisite outranks any outcome, the driver is an independent client that imports nothing from
``exulanica``, its evidence dumps depend on the data alone, and its isolation comparison ignores an
echoed identifier but nothing else. Running it against a stack is the acceptance run itself.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "acceptance" / "foundation.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_foundation", DRIVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses resolve their own module by name while the class is made.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRIVE = _load()


def test_a_row_is_passed_failed_or_blocked_and_never_skipped():
    assert DRIVE.STATES == ("passed", "failed", "blocked")

    clean = DRIVE.Row("X1", "check", "expected").close()
    failed = DRIVE.Row("X2", "check", "expected")
    failed.expect(False, "an outcome was not observed")
    blocked = DRIVE.Row("X3", "check", "expected")
    blocked.expect(False, "an outcome was not observed")
    blocked.blocked_by.append("a prerequisite is absent")

    assert clean.status == "passed"
    assert failed.close().status == "failed"
    assert blocked.close().status == "blocked"
    assert blocked.document()["failures"] == ["an outcome was not observed"]


def test_a_row_that_was_never_closed_cannot_be_written_as_a_result():
    row = DRIVE.Row("X4", "check", "expected")
    row.status = "skipped"
    with pytest.raises(AssertionError):
        row.document()


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
    assert "exulanica_client" in imported


def test_every_placed_object_stands_on_the_ground_but_the_floating_control(monkeypatch):
    for name, (_, height, _) in DRIVE.PLACES.items():
        assert (height != 0) == (name == "bench_floating"), name
    body = DRIVE.placement("cc0.bench", "bench", "bench", "a" * 64)
    assert body["placement"]["transform"]["y_mm"] == 0
    assert body["placement"]["region_id"] == DRIVE.STARTER_REGION


def test_evidence_dumps_pin_the_restrict_key_so_the_digest_is_the_datas(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    def run(command, **_):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"data", stderr=b"")

    monkeypatch.setattr(DRIVE.subprocess, "run", run)
    (tmp_path / "blob").write_bytes(b"x")
    stack = DRIVE.Stack(
        tmp_path,
        {
            "database": {
                "postgres_bin": "/bin",
                "owner_url_for_evidence_reads": "postgresql://h/d",
            },
            "data_dir": str(tmp_path),
        },
    )

    first, second = stack.evidence_digest(), stack.evidence_digest()

    assert first == second
    assert f"--restrict-key={DRIVE.EVIDENCE_RESTRICT_KEY}" in commands[0]
    assert "--data-only" in commands[0]


def test_an_echoed_identifier_is_no_difference_but_anything_else_is():
    foreign = {"entry_id": "e-1", "authored_version_id": "v-1", "world_id": "w-1"}
    invented = {"entry_id": "e-2", "authored_version_id": "v-2", "world_id": "w-2"}

    assert DRIVE.without_identities(
        {"code": "unknown_reference", "detail": "no entry e-1"}, foreign
    ) == DRIVE.without_identities({"code": "unknown_reference", "detail": "no entry e-2"}, invented)
    assert DRIVE.without_identities(
        {"code": "unknown_reference", "detail": "entry e-1 is withdrawn"}, foreign
    ) != DRIVE.without_identities({"code": "unknown_reference", "detail": "no entry e-2"}, invented)


def test_the_driver_names_the_code_it_started_with_and_says_when_that_changed():
    source = DRIVER.read_text(encoding="utf-8")

    assert hashlib.sha256(DRIVER.read_bytes()).hexdigest() == DRIVE.DRIVER_SHA256_AT_START
    assert source.count('"driver_sha256": DRIVER_SHA256_AT_START') == source.count(
        '"driver_changed_during_run":'
    )


def test_the_companion_plans_drafts_fill_the_form_the_product_builds():
    """Each world-edit draft the Companion rows script names only the fields the product's form
    offers, so a scripted reply is refused for the reason its row means and never for its shape
    (A-55: the old slots were refused on every draft)."""
    import json

    from exulanica.selection import action_plan as plan

    from test_companion_action_plan import _world

    step = plan._world_edit_form(_world()).model_json_schema()["$defs"]["WorldEditStep"]
    offered = set(step["properties"])
    drafts = [
        json.loads(rule["content"])
        for rule in json.loads(DRIVE.COMPANION_PLAN.read_text())["rules"]
        if rule["match"]["contains"].startswith("The request:")
    ]

    assert drafts
    for draft in drafts:
        for drafted in draft["steps"]:
            assert set(drafted) <= offered, drafted
            assert drafted["operation"] in plan.WorldEditOperation._value2member_map_


def test_a_confirmation_of_a_plan_with_no_step_is_answered_and_sends_nothing():
    class Refusing:
        def call(self, *arguments, **keywords):
            raise AssertionError("a step that is not there was sent")

    assert DRIVE.confirm(Refusing(), "F1", {}, {}) == (0, {})


class _Recorder:
    """A client that keeps each request body and answers 200 with nothing."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def call(self, step, method, path, query=None, body=None):
        self.bodies.append(body)
        return 200, {}


def test_the_outcome_read_sends_each_confirmed_steps_own_answer():
    """A-61: an accepted edit answers with the edit_seq and state_sha256 at the top of its body, a
    refusal with its problem code; a step not sent goes back as it came."""
    accepted = DRIVE.edit_answer(201, {"edit_seq": 4, "state_sha256": "a" * 64, "edits": []})
    refused = DRIVE.edit_answer(409, {"code": "stale_saved_world_entry", "edit_seq": 9})
    assert accepted == {"status": 201, "edit_seq": 4, "state_sha256": "a" * 64}
    assert refused == {"status": 409, "code": "stale_saved_world_entry"}
    client = _Recorder()
    entry = {"world_id": "w", "authored_version_id": "v"}
    plan = {"plan_sha256": "p", "steps": [{"operation": "one"}, {"operation": "two"}]}
    DRIVE.outcome(client, "F1", entry, plan, [accepted])
    DRIVE.outcome(client, "F1", entry, plan)
    sent, bare = (body["steps"] for body in client.bodies)
    assert sent == [{"operation": "one", "answer": accepted}, {"operation": "two"}]
    assert bare == plan["steps"]
