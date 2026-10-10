"""Walking at each body's own pace: the second version of the walking module.

The first version (:mod:`exulanica.movement.walking`) spends one budget for every walker of a
society. This one spends each walker's own: the society's budget scaled by the walker's pace, in
thousandths, which its kind states with the walking it moves by (a drafted body's is computed from
the height it stands at, :mod:`exulanica.things.gaits`). Routes and the traversal itself are the
first version's, called and not copied, so a walker at the society's own pace moves exactly as the
first version moves it.

A society of things runs this version when its first input records it among its movement modules
(:func:`exulanica.movement.registry.recorded_movement`); one that records none walks by the first.
The step reads the route it is handed and two figures, and nothing of the ground the route was
found on or of the engine that found it.

Pure: no connection, no store, no world, no floats.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Final

from exulanica.movement.registry import WALKING_V2, built_module
from exulanica.movement.walking import Leg, traverse

__all__ = [
    "PACE_PARAMETER",
    "REFERENCE_PACE_PERMILLE",
    "WALKING_V2_MODULE",
    "own_budget_mm",
    "traverse_paced",
]

#: The row, looked up once: a table that no longer builds it stops the import by name.
WALKING_V2_MODULE = built_module(WALKING_V2)
#: The figure a walker's kind states, by the name the row declares it under.
PACE_PARAMETER: Final = "pace_permille"
#: The pace of a walker whose kind states none: the society's own.
REFERENCE_PACE_PERMILLE: Final = WALKING_V2_MODULE.value("reference_pace_permille")


def own_budget_mm(budget_mm: int, pace_permille: int) -> int:
    """What a walker of ``pace_permille`` may spend in a tick of a society whose budget is
    ``budget_mm``: the budget times the pace over a thousand, a whole number of millimetres by
    floor division and never less than one, so the slowest walker on the smallest budget still
    arrives. Both figures are held to the bounds the row declares, refused by name outside them.
    """
    WALKING_V2_MODULE.checked("budget_mm_per_tick", budget_mm, where="a walk")
    WALKING_V2_MODULE.checked(PACE_PARAMETER, pace_permille, where="a walk")
    return max(1, budget_mm * pace_permille // REFERENCE_PACE_PERMILLE)


def traverse_paced(
    route: dict[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Mapping[frozenset[str], Mapping[str, Any]],
    budget_mm: int,
    pace_permille: int,
) -> Iterator[Leg]:
    """Spend one walker's own budget along ``route``: :func:`exulanica.movement.walking.traverse`
    over :func:`own_budget_mm`, advancing the route in place and yielding each leg walked."""
    return traverse(route, nodes, edges, own_budget_mm(budget_mm, pace_permille))
