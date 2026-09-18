"""Measurements of a living society run, read from its states alone.

These are the numbers a reviewer needs to tell a living population from a collapsed one: how
many distinct positions the population occupies, how full each destination is against its
capacity, what share of the population walked in a tick, and how time divides between
activities. Nothing here feeds a transition.

Every measure here keys a person by their plan position, so two people at one plan point are one
position, one collision and one stay. That holds while the place stands everybody on one level,
and stops holding the moment it stands two people at two heights over one plan point: the
measures would go on reporting numbers that had quietly stopped meaning what they say, which is
worse than no number. So such a place is refused rather than measured
(:func:`exulanica.world.society_place.place_stacks_heights`); measuring it needs these keys to
carry a level identity, which the place contract does not state yet. Stated heights alone are no
obstacle, since one level is one plan point per person.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from exulanica.world.society_place import place_stacks_heights

__all__ = ["RunMetrics", "measure_run"]


@dataclass
class RunMetrics:
    ticks: int = 0
    population: int = 0
    distinct_positions: list[int] = field(default_factory=list)
    outdoor: list[int] = field(default_factory=list)
    distinct_outdoor_positions: list[int] = field(default_factory=list)
    stationary_collisions: int = 0
    moving: list[int] = field(default_factory=list)
    activity_ticks: Counter = field(default_factory=Counter)
    peak_occupancy: dict[str, int] = field(default_factory=dict)
    capacity: dict[str, int] = field(default_factory=dict)
    over_capacity: int = 0
    longest_outdoor_stay: int = 0

    def summary(self) -> dict[str, Any]:
        total = max(1, self.ticks * self.population)
        return {
            "ticks": self.ticks,
            "population": self.population,
            "distinct_positions": _spread(self.distinct_positions),
            "outdoor_population": _spread(self.outdoor),
            "distinct_outdoor_positions": _spread(self.distinct_outdoor_positions),
            "stationary_collisions": self.stationary_collisions,
            "moving_share_milli": sum(self.moving) * 1000 // total,
            "moving_per_tick": _spread(self.moving),
            "activity_share_milli": {
                key: value * 1000 // total for key, value in sorted(self.activity_ticks.items())
            },
            "destinations": {
                key: {"peak": self.peak_occupancy.get(key, 0), "capacity": self.capacity[key]}
                for key in sorted(self.capacity)
            },
            "over_capacity_ticks": self.over_capacity,
            "longest_outdoor_stay_ticks": self.longest_outdoor_stay,
        }


def _spread(values: list[int]) -> dict[str, int]:
    if not values:
        return {"min": 0, "median": 0, "max": 0}
    ordered = sorted(values)
    return {"min": ordered[0], "median": ordered[len(ordered) // 2], "max": ordered[-1]}


def measure_run(states: Iterable[dict[str, Any]], place: dict[str, Any]) -> RunMetrics:
    """Measure consecutive states of one society over one place document."""
    if place_stacks_heights(place):
        raise ValueError("these measures key a person by plan position and this place has levels")
    metrics = RunMetrics()
    destinations = {d["destination_id"]: d for d in place["destinations"] if d["enabled"]}
    for key, dest in destinations.items():
        metrics.capacity[key] = dest["visitor_capacity"]
    spot_destinations = {s["spot_id"]: s["destination_ids"] for s in place["spots"]}
    stay: dict[str, tuple[tuple[int, int], int]] = {}
    for state in states:
        people = state["inhabitants"]
        metrics.ticks += 1
        metrics.population = len(people)
        metrics.distinct_positions.append(len({tuple(p["position_mm"]) for p in people}))
        outside = [p for p in people if not p["location"]["indoors"]]
        metrics.outdoor.append(len(outside))
        metrics.distinct_outdoor_positions.append(len({tuple(p["position_mm"]) for p in outside}))
        standing = Counter(
            tuple(p["position_mm"])
            for p in outside
            if p["location"]["edge"] is None and p["route"] is None
        )
        metrics.stationary_collisions += sum(n - 1 for n in standing.values() if n > 1)
        metrics.moving.append(sum(1 for p in people if len(p["motion_path_mm"]) > 1))
        occupancy: Counter = Counter()
        for person in people:
            metrics.activity_ticks[person["action"]["kind"]] += 1
            held = person["reservation"]
            if held is None:
                continue
            if held["kind"] == "visitor":
                occupancy[held["id"]] += 1
            elif held["kind"] == "spot":
                for dest_id in spot_destinations.get(held["id"], []):
                    occupancy[dest_id] += 1
        for key, count in occupancy.items():
            if key in metrics.capacity:
                metrics.peak_occupancy[key] = max(metrics.peak_occupancy.get(key, 0), count)
                if count > metrics.capacity[key]:
                    metrics.over_capacity += 1
        for person in outside:
            point = tuple(person["position_mm"])
            held = stay.get(person["id"])
            length = held[1] + 1 if held and held[0] == point else 1
            stay[person["id"]] = (point, length)
            metrics.longest_outdoor_stay = max(metrics.longest_outdoor_stay, length)
        for person in people:
            if person["location"]["indoors"]:
                stay.pop(person["id"], None)
    return metrics
