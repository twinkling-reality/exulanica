"""The foundation acceptance driver in ``scripts/acceptance/foundation.py``, without a server.

These hold the driver's own rules: a row is passed, failed or blocked and never skipped, a blocked
prerequisite outranks any outcome, the driver is an independent client that imports nothing from
``exulanica``, its evidence dumps depend on the data alone, and its isolation comparison ignores an
echoed identifier but nothing else. Running it against a stack is the acceptance run itself.
"""

from __future__ import annotations

import ast
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
