"""No model is asked while the traffic controller holds a connection, a transaction or a lock.

A signal's point is reserved in a transaction that commits and closes; the model is asked with no
connection held; the answer is recorded in a transaction of its own; a minute is sealed in another.
An ask made inside one of those blocks would hold the version row, the clock row or the workspace
edit lock for as long as a model takes to answer, and every edit, society minute and seal of the
workspace would wait on it. Held structurally: every call that asks a model in the controller's
module lies outside every ``with`` block that opens a session or a transaction.
"""

from __future__ import annotations

import ast
from pathlib import Path

import exulanica.api.traffic_signal_controller as controller_module

#: The names under which the controller's module reaches a model.
ASKS = frozenset({"ask", "ask_person"})
#: What opens a connection, a transaction or a lock.
HOLDS = frozenset({"session", "transaction", "unscoped", "_lock_version", "_lock_edits"})


def _called(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _asks_inside_holding_blocks(source: str) -> tuple[list[int], list[int]]:
    tree = ast.parse(source)
    asks: list[int] = []
    inside: list[int] = []

    def visit(node: ast.AST, holding: bool) -> None:
        if _called(node) in ASKS:
            asks.append(node.lineno)
            if holding:
                inside.append(node.lineno)
        opens = isinstance(node, ast.With | ast.AsyncWith) and any(
            _called(item.context_expr) in HOLDS for item in node.items
        )
        for child in ast.iter_child_nodes(node):
            visit(child, holding or opens)

    visit(tree, False)
    return asks, inside


def test_the_controller_asks_a_model_outside_every_session_transaction_and_lock():
    source = Path(controller_module.__file__).read_text(encoding="utf-8")
    asks, inside = _asks_inside_holding_blocks(source)
    assert asks, "the controller asks a model somewhere; the guard looked at nothing"
    assert inside == [], f"asks inside a session or transaction at lines {inside}"


def test_the_guard_sees_an_ask_inside_a_session():
    """The control: the same reading finds an ask placed inside a session block."""
    planted = (
        "def answer(self):\n"
        "    with self.database.session(workspace) as connection:\n"
        "        with connection.transaction():\n"
        "            return ask(client, request, contract, ends_at)\n"
    )
    assert _asks_inside_holding_blocks(planted) == ([4], [4])
