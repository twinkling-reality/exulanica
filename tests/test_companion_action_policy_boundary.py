"""The Companion's world actions never grant a capability, and never reach the policy plane.

The sibling of ``tests/test_companion_memory_policy_boundary.py``, for the modules that turn an
utterance into world requests. A plan is only as permitted as the caller's grant, and the grant is
read from the session: no request body the planner routes accept has a field that could say
otherwise, and the planner imports neither the interaction-policy plane nor stored conversation,
so neither a sentence nor a remembered preference can author what the system may do.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
from exulanica.api.routes import selection_actions

_ROOT = Path(__file__).resolve().parents[1]

#: The modules that plan world actions, read their outcome, and serve both.
_ACTION_SOURCES = (
    _ROOT / "exulanica" / "selection" / "action_plan.py",
    _ROOT / "exulanica" / "selection" / "action_outcome.py",
    _ROOT / "exulanica" / "api" / "routes" / "selection_actions.py",
)

#: Names a body field would need to carry a grant, an identity or a permission.
_GRANTING_FIELDS = frozenset(
    {"actor", "grant", "held", "permissions", "permitted", "requires", "role", "workspace_id"}
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


@pytest.mark.parametrize("path", _ACTION_SOURCES, ids=lambda p: p.name)
def test_the_action_planner_imports_no_policy_type_and_no_stored_conversation(path):
    imported = _imported_modules(path)
    offenders = sorted(
        name
        for name in imported
        if "interaction" in name.lower() or "companion_memory" in name.lower()
    )
    assert not offenders, (
        f"{path.name} imports {offenders}: a plan's permission is the caller's grant, and "
        "neither the policy plane nor a remembered conversation may reach it."
    )


def _models(annotation: Any) -> Iterator[type]:
    """Every request model an annotation can carry, through lists, unions and ``Annotated``."""
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        yield annotation
        return
    for argument in get_args(annotation):
        yield from _models(argument)


def _fields(model: type) -> set[str]:
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        for nested in _models(field.annotation):
            names |= _fields(nested)
    return names


def test_the_field_walk_reaches_every_typed_action_a_body_carries():
    """Positive control for the check below: a walk that stopped at a union of typed actions would
    pass it with nothing checked inside them."""
    carried = _fields(selection_actions.PrepareRequest)
    assert {"asset_key", "object_id", "speed", "minutes", "region_id"} <= carried


@pytest.mark.parametrize(
    "model",
    [
        selection_actions.ActionRequest,
        selection_actions.PrepareRequest,
        selection_actions.OutcomeRequest,
    ],
    ids=lambda model: model.__name__,
)
def test_no_request_body_has_a_field_that_could_grant_anything(model):
    carried = _fields(model) & _GRANTING_FIELDS
    assert not carried, f"{model.__name__} accepts {sorted(carried)} from the caller"
