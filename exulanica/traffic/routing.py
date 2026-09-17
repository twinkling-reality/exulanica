"""Bounded routing over lanes and connectors, with deterministic ties.

A route is the sequence of paths a vehicle's front follows from one position to another. Its
cost is free-flow time in milliseconds at each path's speed limit (capped by the class), rounded
up per path. Among routes of equal cost the one whose path id sequence sorts first wins, so a
route never depends on dictionary order. A class only uses paths that allow it.
"""

from __future__ import annotations

import heapq
from typing import Final

from exulanica.traffic.catalogs import VehicleClass
from exulanica.traffic.network import RoadNetwork

__all__ = ["plan_route"]

_MS_PER_SECOND: Final = 1000


def _cost(length: int, speed: int) -> int:
    return -(-length * _MS_PER_SECOND // speed)


def plan_route(
    network: RoadNetwork,
    vehicle: VehicleClass,
    origin_path: str,
    origin_position: int,
    target_path: str,
    target_position: int,
) -> tuple[str, ...] | None:
    """The cheapest route, or ``None`` when the target cannot be reached by this class."""
    paths = network.paths
    for path_id in (origin_path, target_path):
        if vehicle.key not in paths[path_id].classes:
            return None
    if origin_path == target_path and target_position > origin_position:
        return (origin_path,)

    def speed(path_id: str) -> int:
        return min(paths[path_id].speed_limit_mm_per_s, vehicle.speed_cap_mm_per_s)

    start_cost = _cost(paths[origin_path].length - origin_position, speed(origin_path))
    frontier: list[tuple[int, tuple[str, ...]]] = [(start_cost, (origin_path,))]
    settled: set[str] = set()
    while frontier:
        cost, route = heapq.heappop(frontier)
        current = route[-1]
        if current == target_path and len(route) > 1:
            return route
        if current in settled:
            continue
        settled.add(current)
        for successor in paths[current].successors:
            if vehicle.key not in paths[successor].classes:
                continue
            # The target may be the origin path, reached again round a loop.
            if successor in settled and successor != target_path:
                continue
            if successor == target_path:
                extra = _cost(target_position, speed(successor))
            else:
                extra = _cost(paths[successor].length, speed(successor))
            heapq.heappush(frontier, (cost + extra, (*route, successor)))
    return None
