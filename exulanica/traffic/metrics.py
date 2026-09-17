"""Throughput, delay and parking occupancy, read from states and events.

Integers only. A rate is per hour of simulated time, rounded down; a mean is rounded down; an
occupancy is in parts per million of space-seconds.

``junctions``
    Per junction: vehicles that entered, entries per simulated hour, and the mean delay per
    entry. An entry's delay is the time from reaching its approach lane to crossing the stop line,
    minus the free-flow time for that distance at the lane's cap, never below zero.
``parking``
    Per parking kind: how many spaces, how many vehicles they hold together, and the share of
    those places a vehicle stood in, over every second.
``trips``
    Requested, arrived and blocked trips with their reasons, and the mean door-to-door time
    of arrived trips (from the request second to the arrival second).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.traffic.network import RoadNetwork

__all__ = ["METRICS_PROFILE", "MetricsAccumulator"]

METRICS_PROFILE: Final = "exulanica.traffic-metrics/v1"
_PARTS: Final = 1_000_000
_SECONDS_PER_HOUR: Final = 3600


@dataclass
class MetricsAccumulator:
    network: RoadNetwork
    seconds: int = 0
    entries: Counter[str] = field(default_factory=Counter)
    delay_ms: Counter[str] = field(default_factory=Counter)
    occupied_seconds: Counter[str] = field(default_factory=Counter)

    def observe(self, state: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> None:
        """Account one completed second: the state after it and the events it produced."""
        self.seconds += 1
        for event in events:
            document = event["document"]
            if document["kind"] == "junction_entered":
                self.entries[document["junction"]] += 1
                self.delay_ms[document["junction"]] += document["delay_ms"]
        for vehicle in state["vehicles"]:
            if vehicle["mode"] == "parked":
                self.occupied_seconds[self.network.spaces[vehicle["space"]].kind] += 1

    def report(self, final_state: Mapping[str, Any]) -> dict[str, Any]:
        spaces = Counter(space.kind for space in self.network.spaces.values())
        places = Counter()
        for space in self.network.spaces.values():
            places[space.kind] += space.capacity
        trips = final_state["trips"]
        arrived = [trip for trip in trips if trip["status"] == "arrived"]
        return {
            "profile": METRICS_PROFILE,
            "seconds": self.seconds,
            "junctions": [
                {
                    "junction": identity,
                    "policy": self.network.junctions[identity].policy,
                    "entries": self.entries[identity],
                    "entries_per_hour": self.entries[identity]
                    * _SECONDS_PER_HOUR
                    // max(self.seconds, 1),
                    "mean_delay_ms": self.delay_ms[identity] // self.entries[identity]
                    if self.entries[identity]
                    else 0,
                }
                for identity in sorted(self.network.junctions)
            ],
            "parking": [
                {
                    "kind": kind,
                    "spaces": count,
                    "places": places[kind],
                    "occupancy_ppm": self.occupied_seconds[kind]
                    * _PARTS
                    // max(places[kind] * self.seconds, 1),
                }
                for kind, count in sorted(spaces.items())
            ],
            "trips": {
                "requested": len(trips),
                "arrived": len(arrived),
                "blocked": sum(1 for trip in trips if trip["status"] == "blocked"),
                "in_progress": sum(1 for trip in trips if trip["status"] in ("waiting", "driving")),
                "blocked_reasons": dict(
                    sorted(
                        Counter(
                            trip["reason"] for trip in trips if trip["status"] == "blocked"
                        ).items()
                    )
                ),
                "mean_door_to_door_s": sum(
                    trip["arrived_second"] - trip["requested_second"] for trip in arrived
                )
                // len(arrived)
                if arrived
                else 0,
            },
        }
