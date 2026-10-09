"""The names a directed request or a presence request is refused by are each stated once.

``ACTION_REFUSALS`` (exulanica/world/society_actions.py) and ``PRESENCE_REFUSALS``
(exulanica/world/society_presence.py) are the sets the page holds its words to. These read the
server's own source for every name it can refuse by, so a refusal written anywhere else, or a name
in a set that nothing refuses by, fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import exulanica
import pytest
from exulanica.world import society_actions, society_model_decisions
from exulanica.world.society_actions import ACTION_REFUSALS
from exulanica.world.society_presence import PRESENCE_REFUSALS, PresenceRefused

PACKAGE = Path(exulanica.__file__).resolve().parent


def _request_reasons(source: str) -> set[str]:
    """The names ``_request_reason`` and ``_hands_reason`` (a hands act's own rule) return with a
    rejected or stale disposition."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name in ("_request_reason", "_hands_reason"):
            for returned in ast.walk(node):
                if (
                    isinstance(returned, ast.Return)
                    and isinstance(returned.value, ast.Tuple)
                    and len(returned.value.elts) == 2
                    and all(isinstance(e, ast.Constant) for e in returned.value.elts)
                    and returned.value.elts[0].value in ("rejected", "stale")
                ):
                    found.add(returned.value.elts[1].value)
    return found


def _presence_refusals() -> set[str]:
    """Every name a ``PresenceRefused`` is raised with anywhere in the package, or returned by
    ``refusal``, which the raise passes on."""
    found: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "PresenceRefused"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found.add(node.args[0].value)
            if (
                path.name == "society_presence.py"
                and isinstance(node, ast.FunctionDef)
                and (node.name == "refusal")
            ):
                for returned in ast.walk(node):
                    value = returned.value if isinstance(returned, ast.Return) else None
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        found.add(value.value)
    return found


def _policy_reasons(source: str) -> set[str]:
    """The names ``hands_goal_policy`` returns where an applied hands act no longer holds, which
    the minute records as a hands request's refusal."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "hands_goal_policy":
            for returned in ast.walk(node):
                if (
                    isinstance(returned, ast.Return)
                    and isinstance(returned.value, ast.Constant)
                    and isinstance(returned.value.value, str)
                ):
                    found.add(returned.value.value)
    return found


def test_a_directed_request_is_refused_by_exactly_the_stated_names():
    found = _request_reasons(Path(society_actions.__file__).read_text(encoding="utf-8"))
    found |= _policy_reasons(Path(society_model_decisions.__file__).read_text(encoding="utf-8"))
    # A positive control: names the function is known to return are found by the same reading.
    assert {"inhabitant_already_there", "canonical_target_changed", "act_not_offered"} <= found
    assert {"thing_gone", "out_of_reach"} <= found
    assert found == ACTION_REFUSALS


def test_a_presence_request_is_refused_by_exactly_the_stated_names():
    found = _presence_refusals()
    assert {"already_here", "engine_keeps_its_people"} <= found
    assert found == PRESENCE_REFUSALS


def test_a_presence_refusal_by_a_name_nobody_stated_is_refused_itself():
    with pytest.raises(ValueError, match="is not a presence refusal"):
        PresenceRefused("gone_fishing")
