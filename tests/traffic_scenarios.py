"""SYNTHETIC demand and pedestrian schedules for the traffic tests.

Nothing here is a society or a model of real travel. Trips and crossings are drawn from the seed
with the grammar's one draw, so a scenario is a pure function of its seed, and every trip and
crossing it produces is a recorded input the simulation consumes in order.

Pedestrians are fed in the living society's v4 shape: they cross when they arrive, whatever the
signal shows, and traffic has to keep out of their way.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

from exulanica.grammar.draw import draw_integer
from exulanica.traffic.catalogs import TrafficCatalogs, load_traffic_catalogs
from exulanica.traffic.inputs import (
    LOOKAHEAD_S,
    CrossingEntry,
    CrossingFeed,
    TrafficInputs,
    TripRequest,
)
from exulanica.traffic.network import RoadNetwork, compile_network
from exulanica.traffic.simulation import advance_traffic, initial_traffic

from traffic_network_fixture import SCOPE, build_records

FLEET: Final = {"bicycle": 6, "city_bus": 2, "passenger_car": 14, "van": 4}
BUSY_FLEET: Final = {"bicycle": 10, "city_bus": 4, "passenger_car": 18, "van": 8}
#: A vehicle's trips start at least this many seconds apart, so a request rarely finds its
#: vehicle still out on the previous one.
TRIP_SPACING_S: Final = 420
#: Mean seconds between pedestrians at one crossing.
PEDESTRIAN_SPACING_S: Final = 90
#: The fixture's walking speed: MUTCD's 3.5 ft/s, the same number the signal plan cites.
WALK_MM_PER_S: Final = 1066


@lru_cache(maxsize=1)
def fixture() -> tuple[RoadNetwork, TrafficCatalogs]:
    catalogs = load_traffic_catalogs()
    return compile_network(build_records(), catalogs, scope=SCOPE), catalogs


def seed_for(label: str) -> str:
    return hashlib.sha256(f"exulanica traffic scenario {label}".encode()).hexdigest()


def traffic_id_for(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://exulanica.invalid/traffic-test/{label}"))


@dataclass(frozen=True)
class Scenario:
    label: str
    seed: str
    traffic_id: str
    demand_seconds: int
    run_seconds: int
    inputs: TrafficInputs
    initial: dict[str, Any]


def build_scenario(
    label: str,
    *,
    demand_seconds: int,
    run_seconds: int,
    fleet: dict[str, int] | None = None,
    pedestrians: bool = True,
    trip_spacing_s: int = TRIP_SPACING_S,
    pedestrian_spacing_s: int = PEDESTRIAN_SPACING_S,
) -> Scenario:
    network, catalogs = fixture()
    seed = seed_for(label)
    traffic_id = traffic_id_for(label)
    initial = initial_traffic(traffic_id, seed, network, catalogs, fleet or FLEET)
    segments = sorted({space.segment_ordinal for space in network.spaces.values()})
    trips = []
    for vehicle in initial["vehicles"]:
        ordinal = vehicle["ordinal"]
        depart = draw_integer(seed, "scenario.first_trip", ordinal, 0, trip_spacing_s)
        index = 0
        while depart < demand_seconds:
            segment = segments[
                draw_integer(
                    seed, "scenario.destination", ordinal * 1000 + index, 0, len(segments) - 1
                )
            ]
            trips.append(
                (
                    depart,
                    vehicle["id"],
                    f"{label}-trip-{ordinal}-{index}",
                    segment,
                )
            )
            index += 1
            depart += trip_spacing_s + draw_integer(
                seed, "scenario.spacing", ordinal * 1000 + index, 0, trip_spacing_s
            )
    trips.sort()
    requests = tuple(
        TripRequest(
            request_seq=seq,
            trip_id=trip_id,
            vehicle_id=vehicle_id,
            depart_second=depart,
            destination_kind="frontage",
            destination=f"fixture-destination-{segment}",
            street_segment_ordinal=segment,
            source="synthetic test demand",
        )
        for seq, (depart, vehicle_id, trip_id, segment) in enumerate(trips, start=1)
    )
    entries = []
    if pedestrians:
        for band in network.bands:
            arrival = draw_integer(
                seed, "scenario.pedestrian", band.band_id * 100_000, 0, pedestrian_spacing_s
            )
            count = 0
            while arrival < run_seconds + LOOKAHEAD_S:
                duration = -(-band.length_mm // WALK_MM_PER_S)
                entries.append(
                    CrossingEntry(
                        crossing_id=band.society_crossing_id,
                        arrival_second=arrival,
                        duration_seconds=duration,
                        source=f"synthetic pedestrian {band.band_id}:{count}",
                    )
                )
                count += 1
                arrival += duration + draw_integer(
                    seed,
                    "scenario.pedestrian",
                    band.band_id * 100_000 + count,
                    0,
                    2 * pedestrian_spacing_s,
                )
    entries.sort(key=lambda entry: (entry.arrival_second, entry.crossing_id, entry.source))
    feeds = []
    window = 60
    last = run_seconds + LOOKAHEAD_S + window
    for seq, start in enumerate(range(0, last, window), start=1):
        chunk = tuple(entry for entry in entries if start <= entry.arrival_second < start + window)
        feeds.append(CrossingFeed(seq, start + window - 1, chunk))
    inputs = TrafficInputs(trips=requests, feeds=tuple(feeds))
    return Scenario(label, seed, traffic_id, demand_seconds, run_seconds, inputs, initial)


def run(
    scenario: Scenario, *, observer: Any = None
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    network, catalogs = fixture()
    state = scenario.initial
    events: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for _ in range(scenario.run_seconds):
        step = advance_traffic(state, scenario.seed, network, catalogs, scenario.inputs)
        if observer is not None:
            observer(state, step)
        state = step.state
        events.extend(step.events)
        receipts.append(step.receipt)
    return state, events, receipts


@dataclass(frozen=True)
class AdaptiveRun:
    """A run whose trip requests were decided second by second and recorded as inputs."""

    scenario: Scenario
    inputs: TrafficInputs
    state: dict[str, Any]
    events: list[dict[str, Any]]
    receipts: list[dict[str, Any]]
    states: list[dict[str, Any]] | None


def _free_spaces(network: RoadNetwork, state: dict[str, Any]) -> set[str]:
    taken = {vehicle["space"] for vehicle in state["vehicles"] if vehicle["mode"] == "parked"}
    taken |= {vehicle["target_space"] for vehicle in state["vehicles"] if vehicle["target_space"]}
    return set(network.spaces) - taken


def run_adaptive(
    label: str,
    *,
    demand_seconds: int,
    run_seconds: int,
    fleet: dict[str, int] | None = None,
    dwell_s: tuple[int, int] = (30, 240),
    pedestrian_spacing_s: int = PEDESTRIAN_SPACING_S,
    observer: Any = None,
    keep_states: bool = False,
) -> AdaptiveRun:
    """Drive a scenario with demand that asks only for trips that can be made.

    A parked vehicle whose seeded dwell is over asks to go to a seeded street whose parking has
    a free space for its class. Each request is appended to the recorded inputs before the
    second that consumes it, so the finished inputs replay the run exactly.
    """
    network, catalogs = fixture()
    scenario = build_scenario(
        label,
        demand_seconds=0,
        run_seconds=run_seconds,
        fleet=fleet,
        pedestrian_spacing_s=pedestrian_spacing_s,
    )
    state = scenario.initial
    feeds = scenario.inputs.feeds
    trips: list[TripRequest] = []
    ready_at = {
        vehicle["id"]: draw_integer(
            scenario.seed, "scenario.dwell", vehicle["ordinal"], 0, dwell_s[1]
        )
        for vehicle in state["vehicles"]
    }
    trip_count: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    states = [state] if keep_states else None
    inputs = TrafficInputs(trips=(), feeds=feeds)
    for second in range(run_seconds):
        if second < demand_seconds:
            free = _free_spaces(network, state)
            added = False
            for vehicle in state["vehicles"]:
                if vehicle["mode"] != "parked" or vehicle["trip_id"]:
                    ready_at.pop(vehicle["id"], None)
                    continue
                if vehicle["id"] not in ready_at:
                    count = trip_count.get(vehicle["id"], 0)
                    ready_at[vehicle["id"]] = second + draw_integer(
                        scenario.seed, "scenario.dwell", vehicle["ordinal"] * 1000 + count, *dwell_s
                    )
                if ready_at[vehicle["id"]] > second:
                    continue
                here = network.spaces[vehicle["space"]].segment_ordinal
                options = sorted(
                    {
                        network.spaces[space].segment_ordinal
                        for space in free
                        if vehicle["vehicle_class"] in network.spaces[space].classes
                        and network.spaces[space].segment_ordinal != here
                    }
                )
                if not options:
                    continue
                count = trip_count.get(vehicle["id"], 0)
                segment = options[
                    draw_integer(
                        scenario.seed,
                        "scenario.destination",
                        vehicle["ordinal"] * 1000 + count,
                        0,
                        len(options) - 1,
                    )
                ]
                trip_count[vehicle["id"]] = count + 1
                trips.append(
                    TripRequest(
                        request_seq=len(trips) + 1,
                        trip_id=f"{label}-trip-{vehicle['ordinal']}-{count}",
                        vehicle_id=vehicle["id"],
                        depart_second=second,
                        destination_kind="frontage",
                        destination=f"fixture-destination-{segment}",
                        street_segment_ordinal=segment,
                        source="synthetic adaptive test demand",
                    )
                )
                ready_at[vehicle["id"]] = 1 << 40
                free -= {
                    space
                    for space in sorted(free)
                    if network.spaces[space].segment_ordinal == segment
                    and vehicle["vehicle_class"] in network.spaces[space].classes
                }
                added = True
            if added:
                inputs = TrafficInputs(trips=tuple(trips), feeds=feeds)
        step = advance_traffic(state, scenario.seed, network, catalogs, inputs)
        if observer is not None:
            observer(state, step)
        state = step.state
        if states is not None:
            states.append(state)
        events.extend(step.events)
        receipts.append(step.receipt)
    return AdaptiveRun(scenario, inputs, state, events, receipts, states)
