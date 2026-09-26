"""Walking: the movement module that moves a society's people over a graph of nodes and edges.

This is the rule every society engine that routes its people walks by, written once: the purposeful
society (``exulanica-society/v2`` and ``v3``, :mod:`exulanica.world.society_planner`) and the
living society (``v4``, :mod:`exulanica.world.society_living`) both call it. It moved here from
the planner unchanged in its arithmetic, so every stored society replays byte for byte; its row in
``movement-modules.v1.json`` declares its space, its clock and its parameters.

Two parts:

- :func:`routes_from` is the shortest route from one node to every node it reaches: integer edge
  lengths, ties broken by the lexicographically least node path, so the same graph always gives
  the same route whatever order its edges were read in.
- :func:`traverse` spends a travel budget along a route, one edge at a time, and yields each leg
  it walks: how far along the edge it got and the point it reached, interpolated with integer
  floor division. It advances the route's position in place, and nothing else: where the person
  stands, what their location record looks like and what happens on arrival are the engine's, so
  each engine keeps the state shape its own history was recorded in.

Pure: no connection, no store, no world, no floats.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.movement.registry import WALKING, built_module

__all__ = ["MOTION_PATH_PROFILE", "WALKING_MODULE", "Leg", "routes_from", "traverse"]

#: The walking row, looked up once: a table that no longer builds walking stops every society
#: engine at import with the refusal its row names, rather than walking by a rule nobody declared.
WALKING_MODULE = built_module(WALKING)
#: What a walk hands a society to record: each person's ``motion_path_mm``, every point passed in a
#: tick. The walking row declares it as its output.
MOTION_PATH_PROFILE: Final = "exulanica.motion-path/v1"

Adjacent = Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]]


def routes_from(start: str, adjacent: Adjacent) -> dict[str, tuple[int, tuple[str, ...]]]:
    """Every node ``start`` reaches, with its least route length and that route's node path.

    ``adjacent`` maps each node to its neighbours in node order, each with the edge joining them.
    Among routes of equal length the lexicographically least node path wins, because the heap
    orders by ``(distance, path)``.
    """
    queue = [(0, (start,), start)]
    best = {start: (0, (start,))}
    while queue:
        distance, path, node = heapq.heappop(queue)
        if best[node] != (distance, path):
            continue
        for neighbor, edge in adjacent[node]:
            candidate = (distance + edge["length_mm"], (*path, neighbor))
            if neighbor not in best or candidate < best[neighbor]:
                best[neighbor] = candidate
                heapq.heappush(queue, (*candidate, neighbor))
    return best


@dataclass(frozen=True, slots=True)
class Leg:
    """One edge a walker moved along in a tick, and where on it the walker stopped."""

    from_node: str
    to_node: str
    edge: Mapping[str, Any]
    start: Sequence[int]
    end: Sequence[int]
    #: Millimetres walked along this edge in this leg.
    step_mm: int
    #: How far along the edge the walker is after this leg; the edge's length when it arrived.
    progress_mm: int
    #: The point reached, interpolated along the edge with integer floor division.
    point: list[int]
    #: Whether the walker reached the edge's far node in this leg.
    arrived: bool
    #: Whether this leg began at the edge's near node, rather than part way along it.
    entered: bool

    def edge_location(self) -> dict[str, Any]:
        """The edge record a walker part way along this leg's edge stands on."""
        return {
            "edge_id": self.edge["edge_id"],
            "from_node_id": self.from_node,
            "to_node_id": self.to_node,
            "from_position_mm": list(self.start),
            "to_position_mm": list(self.end),
            "length_mm": self.edge["length_mm"],
            "progress_mm": self.progress_mm,
        }


def traverse(
    route: dict[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Mapping[frozenset[str], Mapping[str, Any]],
    budget_mm: int,
) -> Iterator[Leg]:
    """Spend ``budget_mm`` along ``route``, advancing its position in place, one leg per edge.

    ``route`` holds ``node_ids``, ``edge_index`` and ``edge_progress_mm``. Walking stops at the
    route's last node or when the budget is spent. Each leg moves the whole remaining budget or
    the rest of its edge, whichever is less; a leg that reaches the edge's far node moves the
    route to the next edge at progress zero.
    """
    budget = budget_mm
    while route["edge_index"] < len(route["node_ids"]) - 1 and budget > 0:
        index = route["edge_index"]
        a, b = route["node_ids"][index : index + 2]
        edge = edges[frozenset((a, b))]
        progress = route["edge_progress_mm"]
        entered = progress == 0
        step = min(budget, edge["length_mm"] - progress)
        progress += step
        budget -= step
        start, end = nodes[a]["position_mm"], nodes[b]["position_mm"]
        point = [
            x + (y - x) * progress // edge["length_mm"] for x, y in zip(start, end, strict=True)
        ]
        arrived = progress == edge["length_mm"]
        if arrived:
            route["edge_index"] += 1
            route["edge_progress_mm"] = 0
        else:
            route["edge_progress_mm"] = progress
        yield Leg(a, b, edge, start, end, step, progress, point, arrived, entered)
