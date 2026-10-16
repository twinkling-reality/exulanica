"""Swimming: the movement module that moves a body across water, one society minute at a time.

A society of things whose first input records ``exulanica-movement/swimming/v1`` moves each being
whose kind's moves name it over the water its input states as well as its walking graph; the
module's row in ``movement-modules.v1.json`` declares the lattice that water is laid as, the pace a
swimmer whose kind states none swims at, and the bounds of the figures it reads. Three parts:

- :func:`traverse_swimming` is the step: a swimmer's own budget, the society's scaled by its pace
  in water (:func:`own_budget_mm`), spent along a route over water by the walking module's
  traversal (:func:`exulanica.movement.walking.traverse`), called and not copied, so every point a
  swimmer reaches is floored as a walker's is.
- :func:`quickest_routes` is the route a swimmer takes from one node to every node it reaches over
  land and water together: an edge costs the time crossing it takes, its length over the pace it
  is crossed at, so a swimmer walks round water where that is quicker and swims across where it is
  not. Among routes of equal cost the lexicographically least node path wins, as among walking's
  routes, so a graph a swimmer crosses no water of routes as walking routes it.
- :func:`crossing` is one minute along such a route: each stretch of land is walked by the walking
  step the society records and each stretch of water swum by this one, every stretch handed what
  is left of the society's budget and spending the part of it its pace takes to cover what it
  moved (:func:`spent_mm`).

Pure: no connection, no store, no world, no floats.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Container, Iterator, Mapping, Sequence
from typing import Any, Final

from exulanica.movement.registry import SWIMMING, built_module
from exulanica.movement.walking import Leg, traverse

__all__ = [
    "PACE_PARAMETER",
    "REFERENCE_PACE_PERMILLE",
    "SWIMMING_MODULE",
    "crossing",
    "own_budget_mm",
    "quickest_routes",
    "spent_mm",
    "traverse_swimming",
]

#: The row, looked up once: a table that no longer builds it stops the import by name.
SWIMMING_MODULE = built_module(SWIMMING)
#: The figure a swimmer's kind states, by the name the row declares it under.
PACE_PARAMETER: Final = "pace_permille"
#: The pace in water of a swimmer whose kind states none, in thousandths of the society's.
REFERENCE_PACE_PERMILLE: Final = SWIMMING_MODULE.value("reference_pace_permille")
#: A society's own pace, in thousandths: what every pace is a share of.
_OWN_PACE: Final = 1000

Adjacent = Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]]
#: A movement module's step: a route, its nodes and edges, and the figures the module reads.
Step = Callable[..., Iterator[Leg]]


def own_budget_mm(budget_mm: int, pace_permille: int) -> int:
    """What a swimmer of ``pace_permille`` may swim of ``budget_mm`` at the society's own pace:
    the budget times the pace over a thousand, a whole number of millimetres by floor division and
    never less than one, as a walker's own budget is. Both figures are held to the bounds the row
    declares, refused by name outside them."""
    SWIMMING_MODULE.checked("budget_mm_per_tick", budget_mm, where="a swim")
    SWIMMING_MODULE.checked(PACE_PARAMETER, pace_permille, where="a swim")
    return max(1, budget_mm * pace_permille // _OWN_PACE)


def traverse_swimming(
    route: dict[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Mapping[frozenset[str], Mapping[str, Any]],
    budget_mm: int,
    pace_permille: int,
) -> Iterator[Leg]:
    """Spend one swimmer's own budget along ``route``: :func:`exulanica.movement.walking.traverse`
    over :func:`own_budget_mm`, advancing the route in place and yielding each leg swum."""
    return traverse(route, nodes, edges, own_budget_mm(budget_mm, pace_permille))


def spent_mm(moved_mm: int, pace_permille: int) -> int:
    """The part of a society's budget that moving ``moved_mm`` at ``pace_permille`` took: the
    millimetres over the pace, in the society's own millimetres, rounded up."""
    return -(-moved_mm * _OWN_PACE // pace_permille)


def quickest_routes(
    start: str, adjacent: Adjacent, wet: Container[str], walk_pace: int, swim_pace: int
) -> dict[str, tuple[int, tuple[str, ...]]]:
    """Every node ``start`` reaches over land and water, with the least cost of reaching it and
    that route's node path.

    ``adjacent`` maps each node to its neighbours in node order, each with the edge joining them;
    an edge whose id is in ``wet`` is swum at ``swim_pace``, any other walked at ``walk_pace``.
    Each costs its length times the other pace: the time crossing it takes, in units both paces
    share, so the least cost is the quickest route. Among routes of equal cost the
    lexicographically least node path wins, because the heap orders by ``(cost, path)``.
    """
    queue = [(0, (start,), start)]
    best = {start: (0, (start,))}
    while queue:
        cost, path, node = heapq.heappop(queue)
        if best[node] != (cost, path):
            continue
        for neighbor, edge in adjacent[node]:
            weight = edge["length_mm"] * (walk_pace if edge["edge_id"] in wet else swim_pace)
            candidate = (cost + weight, (*path, neighbor))
            if neighbor not in best or candidate < best[neighbor]:
                best[neighbor] = candidate
                heapq.heappush(queue, (*candidate, neighbor))
    return best


def crossing(
    route: dict[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Mapping[frozenset[str], Mapping[str, Any]],
    wet: Container[str],
    budget_mm: int,
    walk: Step,
    walk_pace: int | None,
    swim: Step,
    swim_pace: int,
) -> Iterator[Leg]:
    """One minute along ``route`` over land and water, advancing it in place, one leg per edge.

    The route is taken a stretch at a time, a stretch being its edges from where the swimmer is
    up to the next change between land and water (an edge whose id is in ``wet`` is water). A
    stretch of land is walked by ``walk``, the walking step the society records, handed the pace
    it takes (``walk_pace``) where it takes one; a stretch of water is swum by ``swim`` at
    ``swim_pace``. Each is handed what is left of the society's ``budget_mm`` and spends the part
    of it its pace took to cover what it moved (:func:`spent_mm`). A stretch its step does not
    finish ends the minute, and so does what is left when it would move the next stretch less than
    a millimetre. A route of land alone is one stretch handed the whole budget, so it is walked
    exactly as the walking step walks it.
    """
    left = budget_mm
    ids = route["node_ids"]

    def in_water(index: int) -> bool:
        return edges[frozenset(ids[index : index + 2])]["edge_id"] in wet

    while left > 0 and route["edge_index"] < len(ids) - 1:
        index = route["edge_index"]
        water = in_water(index)
        end = index + 1
        while end < len(ids) - 1 and in_water(end) == water:
            end += 1
        pace = swim_pace if water else _OWN_PACE if walk_pace is None else walk_pace
        if left < budget_mm and left * pace // _OWN_PACE == 0:
            return
        stretch = {
            "node_ids": ids[index : end + 1],
            "edge_index": 0,
            "edge_progress_mm": route["edge_progress_mm"],
        }
        figures = (left, swim_pace) if water else (left,) if walk_pace is None else (left, pace)
        moved = 0
        for leg in (swim if water else walk)(stretch, nodes, edges, *figures):
            moved += leg.step_mm
            yield leg
        route["edge_index"] = index + stretch["edge_index"]
        route["edge_progress_mm"] = stretch["edge_progress_mm"]
        if route["edge_index"] < end:
            return
        left -= spent_mm(moved, pace)
