"""Every reason code the planner records is in the one set the browser's words are held to.

``REASON_CODES`` in ``exulanica/world/society_planner.py`` states the codes; the browser's
``REASON_WORDS`` has words for exactly those
(``web/packages/app/test/society-words-parity.test.ts``).
This reads the planner's own source for every code it can write: the reason a person is blocked
for, the reason of every event it emits, every ``"reason"`` in an action or goal it builds, and
every code a reason is assigned from. A code written anywhere else, or a code in the set the
planner no longer writes, fails here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from exulanica.world import society_planner
from exulanica.world.society_input_policy import LOCAL_RECORD_REASONS
from exulanica.world.society_planner import REASON_CODES

PLANNER = Path(society_planner.__file__)
#: Names a reason is assigned to before it is recorded.
REASON_NAMES = ("reason", "why")


def _literals(node: ast.AST) -> Iterator[str]:
    """The string constants an expression can evaluate to, through branches and defaults."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.IfExp):
        yield from _literals(node.body)
        yield from _literals(node.orelse)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _literals(value)
    elif isinstance(node, ast.Call):
        # ``held.get(key, "default")``: the default is a code the call may return.
        for argument in node.args[1:]:
            yield from _literals(argument)


def recorded() -> set[str]:
    """Every reason code the planner's source can record."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(PLANNER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "block" and len(node.args) > 1:
                found.update(_literals(node.args[1]))
            if node.func.id == "emit" and len(node.args) > 2:
                found.update(_literals(node.args[2]))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "reason":
                    found.update(_literals(value))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                named = isinstance(target, ast.Name) and target.id in REASON_NAMES
                keyed = (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "reason"
                )
                if named or keyed:
                    found.update(_literals(node.value))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "DRAWN_REASONS"
            and isinstance(node.value, ast.Dict)
        ):
            for value in node.value.values:
                found.update(_literals(value))
    return found


def test_the_scan_finds_codes_the_planner_is_known_to_record():
    """A positive control: a scan that found nothing would pass the equality below vacuously."""
    found = recorded()
    assert {"restore_need", "no_room_at_destination", "stopped_to_talk", "partner_left"} <= found


def test_the_planner_records_exactly_the_stated_reason_codes():
    local = set().union(*LOCAL_RECORD_REASONS.values())
    assert recorded() | local == REASON_CODES
    assert local <= REASON_CODES
