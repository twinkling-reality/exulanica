"""Every kind of event a society engine names is one the store admits.

The event table admits a fixed list of kinds (``world_society_event_event_kind_check``, a
migration's CHECK). An engine that names a kind outside it writes a minute the store refuses, which
only a stored minute meets: the living town's first "waited" kind failed a playing town's minute
with a 500 while every engine test passed. This reads, from each engine module's source, every event
kind it names as text (the kind an ``emit`` helper is called with, the kind a ``SocietyEvent`` is
built with and each ``*_EVENT_KIND`` constant), and holds them to the live schema's list.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_MODULES = sorted((ROOT / "exulanica" / "world").glob("society*.py"))
ADMITTED = re.compile(r"'([a-z_]+)'::text")


def _kind(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def named_kinds(paths: list[Path]) -> dict[str, set[str]]:
    """Each event kind named as text in these modules, with the modules naming it."""
    found: dict[str, set[str]] = {}

    def note(kind: str | None, path: Path) -> None:
        if kind is not None:
            found.setdefault(kind, set()).add(path.name)

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "emit" and len(node.args) >= 2:
                    note(_kind(node.args[1]), path)
                if node.func.id == "SocietyEvent" and len(node.args) >= 3:
                    note(_kind(node.args[2]), path)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith("_EVENT_KIND"):
                        note(_kind(node.value), path)
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id.endswith("_EVENT_KIND")
                and node.value is not None
            ):
                note(_kind(node.value), path)
    return found


def test_the_scan_sees_the_kinds_engines_name(tmp_path):
    # The positive control: the living engine's kinds and a role's decision kind are found, and a
    # planted module's kind is too, so an empty scan cannot pass for a clean one.
    found = named_kinds(ENGINE_MODULES)
    assert {"goal_selected", "route_progressed", "action_completed", "decision_applied"} <= set(
        found
    )
    planted = tmp_path / "society_planted.py"
    planted.write_text(
        'WAITED_EVENT_KIND = "waited"\n'
        "def advance(person):\n"
        '    emit(person, "napped", "tired", "slept", {})\n',
        encoding="utf-8",
    )
    assert {"waited", "napped"} <= set(named_kinds([planted]))


@pytest.mark.postgres
def test_every_kind_an_engine_names_is_admitted_by_the_store(repository):
    body = repository.connection.execute(
        "select pg_get_constraintdef(oid) as body from pg_constraint "
        "where conname='world_society_event_event_kind_check'"
    ).fetchone()["body"]
    admitted = set(ADMITTED.findall(body))
    assert "goal_selected" in admitted, body
    refused = {
        kind: sorted(modules)
        for kind, modules in named_kinds(ENGINE_MODULES).items()
        if kind not in admitted
    }
    assert not refused, f"event kinds the store refuses: {refused}"
