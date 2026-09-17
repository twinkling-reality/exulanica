"""The traffic simulation: one pure step per simulated second, byte-identical on replay.

``advance_traffic(state, seed, network, catalogs, inputs)`` returns the next state, the events
of that second and a transition receipt. Nothing here reads a clock, draws a random number, calls
a model or touches a float; the only draws are the seeded fleet choices at initialisation.

**A second, in order.**

1. Consume the trip requests for this second (route, destination space, or a blocked trip with
   its reason).
2. Record signal interval changes. Signals are a pure function of plan, offset and second.
3. Finish parking manoeuvres that end now, and start leaving where it is safe to.
4. Release reservations whose vehicle has cleared its region; revoke reservations of vehicles
   that can still stop when their signal is no longer green or a pedestrian is due.
5. Admit vehicles at their gates, junction by junction, by the junction's rule.
6. Move every driving vehicle by the highest speed the safety rule, the speed caps, the
   destination and its gates allow (see :mod:`exulanica.traffic.kinematics`). Decisions read the
   state at the start of the second, so the order vehicles are listed in never matters.
7. Record gate entries, arrivals, and trips that have waited past the stall limit.

**Regions.** A vehicle passes a junction stop line only while it holds a reservation of every
conflict zone of its connector (and of its exit lane's start), with room beyond for its whole
body, and with no pedestrian due on any crossing in its region before it can have cleared it.
A signal reservation is only granted on green; a vehicle that can no longer stop commits only if
it will cross the line before red.

Every state change is an event with a uuid5 identity over the traffic id, second, order and the
digest of its document.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.draw import draw_integer
from exulanica.grammar.seed import require_seed
from exulanica.traffic.catalogs import TrafficCatalogs, VehicleClass
from exulanica.traffic.errors import InvalidTrafficInputError, InvalidTrafficStateError
from exulanica.traffic.inputs import LOOKAHEAD_S, CrossingEntry, TrafficInputs, TripRequest
from exulanica.traffic.kinematics import (
    braking_run,
    cap_allows,
    clearing_ticks,
    follows_safely,
    highest_speed,
    reach_ticks,
    stopping_distance,
)
from exulanica.traffic.network import Gate, JunctionSpec, RoadNetwork
from exulanica.traffic.routing import plan_route
from exulanica.traffic.signals import interval_index, seconds_until_red, vehicle_indication

__all__ = [
    "STALL_LIMIT_S",
    "TRAFFIC_NAMESPACE",
    "TRAFFIC_PROFILE",
    "TrafficStep",
    "advance_traffic",
    "body_intervals",
    "initial_traffic",
    "state_sha256",
    "vehicle_id",
]

TRAFFIC_PROFILE: Final = "exulanica-traffic/v1"
TRAFFIC_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/traffic")
#: A trip whose vehicle has made no progress for this many simulated seconds is recorded as
#: blocked, with the reason it is waiting. A reporting threshold, not a physical parameter.
STALL_LIMIT_S: Final = 300
_MS: Final = 1000
_MODES: Final = ("parked", "leaving", "driving", "arriving")


def state_sha256(state: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(state)).hexdigest()


def vehicle_id(traffic_id: str, ordinal: int) -> str:
    return str(uuid.uuid5(TRAFFIC_NAMESPACE, f"{traffic_id}:vehicle:{ordinal}"))


def _ceil_seconds(milliseconds: int) -> int:
    return -(-milliseconds // _MS)


@dataclass(slots=True)
class Reservation:
    kind: str
    target: int
    gate_index: int
    gate_path: str
    gate_position: int
    connector: str
    zones: tuple[tuple[int, str], ...]
    bands: tuple[int, ...]
    clear_path: str
    clear_position: int
    granted_second: int
    clear_by: int
    facts: dict[str, Any]

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "gate_index": self.gate_index,
            "gate_path": self.gate_path,
            "gate_position_mm": self.gate_position,
            "connector": self.connector,
            "zones": [[zone, side] for zone, side in self.zones],
            "bands": list(self.bands),
            "clear_path": self.clear_path,
            "clear_position_mm": self.clear_position,
            "granted_second": self.granted_second,
            "clear_by_second": self.clear_by,
            "facts": self.facts,
        }

    @classmethod
    def read(cls, document: Mapping[str, Any]) -> Reservation:
        return cls(
            kind=document["kind"],
            target=document["target"],
            gate_index=document["gate_index"],
            gate_path=document["gate_path"],
            gate_position=document["gate_position_mm"],
            connector=document["connector"],
            zones=tuple((zone, side) for zone, side in document["zones"]),
            bands=tuple(document["bands"]),
            clear_path=document["clear_path"],
            clear_position=document["clear_position_mm"],
            granted_second=document["granted_second"],
            clear_by=document["clear_by_second"],
            facts=dict(document["facts"]),
        )


@dataclass(slots=True)
class Vehicle:
    vehicle_id: str
    ordinal: int
    vehicle_class: VehicleClass
    body_family: str
    colour: str
    mode: str
    space: str
    target_space: str
    trip_id: str
    route: list[str]
    route_index: int
    position: int
    speed: int
    manoeuvre_until: int
    reservation: Reservation | None
    stopped_since: int
    lane_entry: list[Any]
    wait_reason: str
    wait_since: int
    motion_path: list[list[int]] = field(default_factory=list)

    @property
    def length(self) -> int:
        return self.vehicle_class.length_mm

    @property
    def path(self) -> str:
        return self.route[self.route_index]

    def document(self) -> dict[str, Any]:
        return {
            "id": self.vehicle_id,
            "ordinal": self.ordinal,
            "vehicle_class": self.vehicle_class.key,
            "body_family": self.body_family,
            "colour": self.colour,
            "mode": self.mode,
            "space": self.space,
            "target_space": self.target_space,
            "trip_id": self.trip_id,
            "route": list(self.route),
            "route_index": self.route_index,
            "position_mm": self.position,
            "speed_mm_per_s": self.speed,
            "manoeuvre_until": self.manoeuvre_until,
            "reservation": None if self.reservation is None else self.reservation.document(),
            "stopped_at_line_since": self.stopped_since,
            "lane_entry": list(self.lane_entry),
            "wait_reason": self.wait_reason,
            "wait_since": self.wait_since,
            "motion_path_mm": [list(point) for point in self.motion_path],
            "synthetic": True,
        }


@dataclass(slots=True)
class Trip:
    trip_id: str
    vehicle_id: str
    request_seq: int
    status: str
    reason: str
    origin_space: str
    target_space: str
    requested_second: int
    departed_second: int
    arrived_second: int
    blocked_second: int
    destination: dict[str, Any]

    def document(self) -> dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "vehicle_id": self.vehicle_id,
            "request_seq": self.request_seq,
            "status": self.status,
            "reason": self.reason,
            "origin_space": self.origin_space,
            "target_space": self.target_space,
            "requested_second": self.requested_second,
            "departed_second": self.departed_second,
            "arrived_second": self.arrived_second,
            "blocked_second": self.blocked_second,
            "destination": dict(self.destination),
        }


@dataclass(frozen=True)
class TrafficStep:
    state: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]


def initial_traffic(
    traffic_id: str,
    seed: str,
    network: RoadNetwork,
    catalogs: TrafficCatalogs,
    fleet: Mapping[str, int],
) -> dict[str, Any]:
    """A parked fleet, every vehicle in a space its class fits, chosen by seeded draws."""
    require_seed(seed)
    try:
        uuid.UUID(traffic_id)
    except (TypeError, ValueError) as error:
        raise InvalidTrafficInputError("traffic_id is a UUID") from error
    if network.catalog_sha256 != catalogs.digest:
        raise InvalidTrafficInputError("the network was compiled against other catalogs")
    free = sorted(network.spaces)
    vehicles = []
    ordinal = 0
    for class_key in sorted(fleet):
        count = fleet[class_key]
        if type(count) is not int or count < 0:
            raise InvalidTrafficInputError(f"fleet count for {class_key} is a non-negative int")
        vehicle_class = catalogs.vehicle_class(class_key)
        for index in range(count):
            fits = [space for space in free if class_key in network.spaces[space].classes]
            if not fits:
                raise InvalidTrafficInputError(f"no free space fits another {class_key}")
            space = fits[draw_integer(seed, f"traffic.fleet.{class_key}", index, 0, len(fits) - 1)]
            free.remove(space)
            families = vehicle_class.body_families
            colours = vehicle_class.colours
            vehicles.append(
                Vehicle(
                    vehicle_id=vehicle_id(traffic_id, ordinal),
                    ordinal=ordinal,
                    vehicle_class=vehicle_class,
                    body_family=families[
                        draw_integer(seed, "traffic.body_family", ordinal, 0, len(families) - 1)
                    ],
                    colour=colours[
                        draw_integer(seed, "traffic.colour", ordinal, 0, len(colours) - 1)
                    ],
                    mode="parked",
                    space=space,
                    target_space="",
                    trip_id="",
                    route=[],
                    route_index=0,
                    position=0,
                    speed=0,
                    manoeuvre_until=-1,
                    reservation=None,
                    stopped_since=-1,
                    lane_entry=[],
                    wait_reason="",
                    wait_since=-1,
                ).document()
            )
            ordinal += 1
    vehicles.sort(key=lambda item: item["id"])
    return {
        "profile": TRAFFIC_PROFILE,
        "traffic_id": traffic_id,
        "seed_sha256": hashlib.sha256(seed.encode()).hexdigest(),
        "network_sha256": network.digest,
        "catalog_sha256": catalogs.digest,
        "second": 0,
        "trip_requests_consumed": 0,
        "crossing_feeds_consumed": 0,
        "vehicles": vehicles,
        "trips": [],
    }


def _read_state(
    state: Mapping[str, Any], seed: str, network: RoadNetwork, catalogs: TrafficCatalogs
) -> tuple[list[Vehicle], list[Trip]]:
    if state.get("profile") != TRAFFIC_PROFILE:
        raise InvalidTrafficStateError("unsupported traffic profile")
    if state["seed_sha256"] != hashlib.sha256(seed.encode()).hexdigest():
        raise InvalidTrafficStateError("the seed is not the one this state was started with")
    if state["network_sha256"] != network.digest or state["catalog_sha256"] != catalogs.digest:
        raise InvalidTrafficStateError("the state was built on another network or catalog")
    vehicles = []
    for item in state["vehicles"]:
        if item["mode"] not in _MODES:
            raise InvalidTrafficStateError(f"unknown vehicle mode {item['mode']!r}")
        vehicles.append(
            Vehicle(
                vehicle_id=item["id"],
                ordinal=item["ordinal"],
                vehicle_class=catalogs.vehicle_class(item["vehicle_class"]),
                body_family=item["body_family"],
                colour=item["colour"],
                mode=item["mode"],
                space=item["space"],
                target_space=item["target_space"],
                trip_id=item["trip_id"],
                route=list(item["route"]),
                route_index=item["route_index"],
                position=item["position_mm"],
                speed=item["speed_mm_per_s"],
                manoeuvre_until=item["manoeuvre_until"],
                reservation=None
                if item["reservation"] is None
                else Reservation.read(item["reservation"]),
                stopped_since=item["stopped_at_line_since"],
                lane_entry=list(item["lane_entry"]),
                wait_reason=item["wait_reason"],
                wait_since=item["wait_since"],
            )
        )
    trips = [
        Trip(
            trip_id=item["trip_id"],
            vehicle_id=item["vehicle_id"],
            request_seq=item["request_seq"],
            status=item["status"],
            reason=item["reason"],
            origin_space=item["origin_space"],
            target_space=item["target_space"],
            requested_second=item["requested_second"],
            departed_second=item["departed_second"],
            arrived_second=item["arrived_second"],
            blocked_second=item["blocked_second"],
            destination=dict(item["destination"]),
        )
        for item in state["trips"]
    ]
    return vehicles, trips


def body_intervals(vehicle: Vehicle, network: RoadNetwork) -> list[tuple[str, int, int]]:
    """``(path, rear, front)`` for each path the body covers, front first."""
    if vehicle.mode == "parked":
        return []
    remaining = vehicle.length
    index = vehicle.route_index
    front = vehicle.position
    intervals = []
    while True:
        path = vehicle.route[index]
        rear = front - remaining
        if rear >= 0 or index == 0:
            intervals.append((path, max(rear, 0), front))
            return intervals
        intervals.append((path, 0, front))
        remaining -= front
        index -= 1
        front = network.paths[vehicle.route[index]].length


def _route_offsets(vehicle: Vehicle, network: RoadNetwork) -> list[int]:
    offsets = [0]
    for path in vehicle.route[:-1]:
        offsets.append(offsets[-1] + network.paths[path].length)
    return offsets


def _target_position(vehicle: Vehicle, network: RoadNetwork) -> int:
    return network.spaces[vehicle.target_space].access_end


@dataclass
class _Step:
    """Everything one second computes, discarded at the end of it."""

    network: RoadNetwork
    catalogs: TrafficCatalogs
    second: int
    traffic_id: str
    vehicles: dict[str, Vehicle]
    trips: dict[str, Trip]
    occupancies: list[CrossingEntry]
    events: list[dict[str, Any]] = field(default_factory=list)
    bodies: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)
    holders: dict[tuple[int, str], set[str]] = field(default_factory=dict)
    breaches: list[dict[str, Any]] = field(default_factory=list)
    band_windows: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    red_cache: dict[tuple[int, str], int] = field(default_factory=dict)
    #: Why a vehicle at a gate was not admitted this second.
    denials: dict[str, str] = field(default_factory=dict)

    def emit(self, kind: str, **facts: Any) -> None:
        self.events.append({"kind": kind, "second": self.second, **facts})

    # Indexes -----------------------------------------------------------------------------------

    def index_bodies(self) -> None:
        self.bodies = {}
        for vehicle in self.vehicles.values():
            for path, rear, front in body_intervals(vehicle, self.network):
                self.bodies.setdefault(path, []).append((rear, front, vehicle.vehicle_id))
        for items in self.bodies.values():
            items.sort()

    def index_holders(self) -> None:
        self.holders = {}
        for vehicle in self.vehicles.values():
            if vehicle.reservation is not None:
                for zone, side in vehicle.reservation.zones:
                    self.holders.setdefault((zone, side), set()).add(vehicle.vehicle_id)

    def index_bands(self) -> None:
        by_id = {band.society_crossing_id: band.band_id for band in self.network.bands}
        self.band_windows = {}
        for entry in self.occupancies:
            band_id = by_id.get(entry.crossing_id)
            if band_id is None:
                raise InvalidTrafficInputError(
                    f"the crossing feed names unknown {entry.crossing_id}"
                )
            self.band_windows.setdefault(band_id, []).append(
                (entry.arrival_second, entry.last_second)
            )

    # Signals -----------------------------------------------------------------------------------

    def indication(self, junction: JunctionSpec, connector: str, second: int) -> str:
        signal = junction.signal
        assert signal is not None
        plan = self.catalogs.plan(signal.plan)
        return vehicle_indication(plan, signal.offset_s, second, signal.group_of(connector))

    def until_red(self, junction: JunctionSpec, connector: str) -> int:
        key = (junction.ordinal, connector)
        if key not in self.red_cache:
            signal = junction.signal
            assert signal is not None
            plan = self.catalogs.plan(signal.plan)
            self.red_cache[key] = seconds_until_red(
                plan, signal.offset_s, self.second, signal.group_of(connector)
            )
        return self.red_cache[key]

    # Geometry of routes ------------------------------------------------------------------------

    def next_gate(self, vehicle: Vehicle) -> tuple[Gate, int, int] | None:
        """The first gate at or ahead of the front: ``(gate, route index, distance)``."""
        distance = 0
        start = vehicle.position
        for index in range(vehicle.route_index, len(vehicle.route)):
            path = vehicle.route[index]
            for gate in self.network.gates.get(path, ()):
                if gate.position >= start:
                    return gate, index, distance + gate.position - start
            distance += self.network.paths[path].length - start
            start = 0
        return None

    def band_free(self, bands: Sequence[int], start: int, end: int) -> bool:
        for band in bands:
            for arrival, last in self.band_windows.get(band, ()):
                if arrival <= end and start <= last:
                    return False
        return True

    def speed_cap(self, path: str, vehicle_class: VehicleClass) -> int:
        spec = self.network.paths[path]
        cap = min(spec.speed_limit_mm_per_s, vehicle_class.speed_cap_mm_per_s)
        if spec.is_turn:
            cap = min(cap, vehicle_class.turning_speed_mm_per_s)
        return cap


def advance_traffic(
    state: Mapping[str, Any],
    seed: str,
    network: RoadNetwork,
    catalogs: TrafficCatalogs,
    inputs: TrafficInputs,
) -> TrafficStep:
    require_seed(seed)
    previous_digest = state_sha256(state)
    vehicles, trips = _read_state(state, seed, network, catalogs)
    second = state["second"]
    feed_count = inputs.feeds_needed(second)
    if feed_count < state["crossing_feeds_consumed"]:
        raise InvalidTrafficStateError("the state consumed feeds these inputs do not have")
    step = _Step(
        network=network,
        catalogs=catalogs,
        second=second,
        traffic_id=state["traffic_id"],
        vehicles={vehicle.vehicle_id: vehicle for vehicle in vehicles},
        trips={trip.trip_id: trip for trip in trips},
        occupancies=inputs.occupancies(feed_count),
    )
    step.index_bands()
    consumed = state["trip_requests_consumed"]
    requests = inputs.trips_at(second)
    for request in requests:
        if request.request_seq != consumed + 1:
            raise InvalidTrafficInputError("trip requests must be consumed in order")
        consumed = request.request_seq
        _start_trip(step, request)
    for vehicle in step.vehicles.values():
        vehicle.motion_path = []
    _signal_changes(step)
    _finish_manoeuvres(step)
    step.index_bodies()
    _start_leaving(step)
    step.index_bodies()
    step.index_holders()
    _release_and_revoke(step)
    step.index_holders()
    _admit(step)
    decisions = {
        vehicle_id: _choose_speed(step, vehicle)
        for vehicle_id, vehicle in sorted(step.vehicles.items())
        if vehicle.mode == "driving"
    }
    for vehicle_id in sorted(decisions):
        _move(step, step.vehicles[vehicle_id], decisions[vehicle_id])
    step.second = second + 1
    _after_move(step)
    _stalls(step)

    next_state = {
        "profile": TRAFFIC_PROFILE,
        "traffic_id": state["traffic_id"],
        "seed_sha256": state["seed_sha256"],
        "network_sha256": state["network_sha256"],
        "catalog_sha256": state["catalog_sha256"],
        "second": second + 1,
        "trip_requests_consumed": consumed,
        "crossing_feeds_consumed": feed_count,
        "vehicles": [step.vehicles[key].document() for key in sorted(step.vehicles)],
        "trips": [step.trips[key].document() for key in sorted(step.trips)],
    }
    events = []
    for order, event in enumerate(step.events):
        document = {"order": order, "synthetic": True, **event}
        digest = hashlib.sha256(canonical_json(document)).hexdigest()
        event_id = str(
            uuid.uuid5(TRAFFIC_NAMESPACE, f"{state['traffic_id']}:{second}:{order}:{digest}")
        )
        events.append({"event_id": event_id, "document_sha256": digest, "document": document})
    next_digest = state_sha256(next_state)
    receipt = {
        "profile": "exulanica.traffic-transition/v1",
        "traffic_id": state["traffic_id"],
        "from_second": second,
        "to_second": second + 1,
        "previous_state_sha256": previous_digest,
        "state_sha256": next_digest,
        "inputs_sha256": inputs.digest_through(second, feed_count),
        "trip_requests_consumed": [state["trip_requests_consumed"], consumed],
        "crossing_feeds_consumed": feed_count,
        "event_ids": [event["event_id"] for event in events],
        "events_sha256": hashlib.sha256(
            canonical_json([event["document"] for event in events])
        ).hexdigest(),
        "breaches": step.breaches,
    }
    return TrafficStep(state=next_state, events=tuple(events), receipt=receipt)


# Trips -----------------------------------------------------------------------------------------


def _start_trip(step: _Step, request: TripRequest) -> None:
    network = step.network
    destination = {
        "kind": request.destination_kind,
        "id": request.destination,
        "street_segment_ordinal": request.street_segment_ordinal,
    }
    trip = Trip(
        trip_id=request.trip_id,
        vehicle_id=request.vehicle_id,
        request_seq=request.request_seq,
        status="waiting",
        reason="",
        origin_space="",
        target_space="",
        requested_second=step.second,
        departed_second=-1,
        arrived_second=-1,
        blocked_second=-1,
        destination=destination,
    )
    if request.trip_id in step.trips:
        raise InvalidTrafficInputError(f"trip {request.trip_id} was already requested")
    step.trips[trip.trip_id] = trip
    vehicle = step.vehicles.get(request.vehicle_id)

    def block(reason: str) -> None:
        trip.status = "blocked"
        trip.reason = reason
        trip.blocked_second = step.second
        step.emit(
            "trip_blocked", trip_id=trip.trip_id, vehicle_id=request.vehicle_id, reason=reason
        )

    step.emit(
        "trip_requested",
        trip_id=trip.trip_id,
        vehicle_id=request.vehicle_id,
        request_seq=request.request_seq,
        destination=destination,
    )
    if vehicle is None:
        block("unknown_vehicle")
        return
    if vehicle.mode != "parked" or vehicle.trip_id:
        block("vehicle_busy")
        return
    taken = {other.space for other in step.vehicles.values() if other.mode == "parked"}
    taken |= {other.target_space for other in step.vehicles.values() if other.target_space}
    class_key = vehicle.vehicle_class.key
    if request.destination_kind == "space":
        space = network.spaces.get(request.destination)
        if space is None:
            block("unknown_space")
            return
        if class_key not in space.classes:
            block("space_does_not_fit_class")
            return
        if space.identity in taken:
            block("destination_space_taken")
            return
        target = space.identity
    else:
        candidates = [
            space.identity
            for space in sorted(network.spaces.values(), key=lambda item: item.ordinal)
            if space.segment_ordinal == request.street_segment_ordinal
            and class_key in space.classes
            and space.identity not in taken
        ]
        if not candidates:
            block("no_parking_at_destination")
            return
        target = candidates[0]
    origin = network.spaces[vehicle.space]
    goal = network.spaces[target]
    route = plan_route(
        network,
        vehicle.vehicle_class,
        origin.access_path,
        origin.access_end,
        goal.access_path,
        goal.access_end,
    )
    if route is None:
        block("no_route")
        return
    trip.origin_space = vehicle.space
    trip.target_space = target
    vehicle.trip_id = trip.trip_id
    vehicle.target_space = target
    vehicle.route = list(route)
    vehicle.route_index = 0
    vehicle.position = origin.access_end
    vehicle.speed = 0
    vehicle.wait_reason = "waiting_to_leave"
    vehicle.wait_since = step.second
    step.emit(
        "trip_routed",
        trip_id=trip.trip_id,
        vehicle_id=vehicle.vehicle_id,
        origin_space=vehicle.space,
        target_space=target,
        route=list(route),
    )


def _signal_changes(step: _Step) -> None:
    for junction in step.network.junctions.values():
        signal = junction.signal
        if signal is None:
            continue
        plan = step.catalogs.plan(signal.plan)
        now = interval_index(plan, signal.offset_s, step.second)
        if step.second > 0 and now == interval_index(plan, signal.offset_s, step.second - 1):
            continue
        interval = plan.intervals[now]
        step.emit(
            "signal_interval",
            junction=junction.ordinal,
            controller=signal.controller_identity,
            interval=now,
            vehicle_green=list(interval.vehicle_green),
            vehicle_amber=list(interval.vehicle_amber),
            pedestrian_walk=list(interval.pedestrian_walk),
            pedestrian_clearance=list(interval.pedestrian_clearance),
        )


def _finish_manoeuvres(step: _Step) -> None:
    for vehicle in (step.vehicles[key] for key in sorted(step.vehicles)):
        if vehicle.manoeuvre_until != step.second:
            continue
        trip = step.trips[vehicle.trip_id]
        if vehicle.mode == "leaving":
            vehicle.mode = "driving"
            vehicle.manoeuvre_until = -1
            vehicle.space = ""
            trip.departed_second = step.second
            if trip.status != "blocked":
                trip.status = "driving"
            vehicle.lane_entry = [vehicle.path, step.second, vehicle.position]
            vehicle.wait_reason = ""
            vehicle.wait_since = -1
            step.emit("trip_departed", trip_id=trip.trip_id, vehicle_id=vehicle.vehicle_id)
        elif vehicle.mode == "arriving":
            vehicle.mode = "parked"
            vehicle.manoeuvre_until = -1
            vehicle.space = vehicle.target_space
            vehicle.target_space = ""
            vehicle.route = []
            vehicle.route_index = 0
            vehicle.position = 0
            vehicle.speed = 0
            vehicle.trip_id = ""
            vehicle.lane_entry = []
            vehicle.wait_reason = ""
            vehicle.wait_since = -1
            trip.status = "arrived"
            trip.reason = ""
            trip.arrived_second = step.second
            step.emit(
                "trip_arrived",
                trip_id=trip.trip_id,
                vehicle_id=vehicle.vehicle_id,
                space=vehicle.space,
            )


def _route_distance(vehicle: Vehicle, network: RoadNetwork, path: str, position: int) -> int | None:
    """Distance from the vehicle's front to ``position`` on ``path`` along its route, if ahead."""
    distance = 0
    start = vehicle.position
    for index in range(vehicle.route_index, len(vehicle.route)):
        current = vehicle.route[index]
        if current == path and position >= start:
            return distance + position - start
        distance += network.paths[current].length - start
        start = 0
    return None


def _start_leaving(step: _Step) -> None:
    network = step.network
    for vehicle in (step.vehicles[key] for key in sorted(step.vehicles)):
        if vehicle.mode != "parked" or not vehicle.trip_id:
            continue
        trip = step.trips[vehicle.trip_id]
        space = network.spaces[vehicle.space]
        lane = space.access_path
        front = space.access_end
        rear = front - vehicle.length
        gap = vehicle.vehicle_class.minimum_gap_mm
        reason = ""
        for body_rear, body_front, other_id in step.bodies.get(lane, []):
            other = step.vehicles[other_id]
            margin = max(gap, other.vehicle_class.minimum_gap_mm)
            if body_rear <= front + margin and rear - margin <= body_front:
                reason = "lane_occupied"
                break
        if not reason:
            for other in step.vehicles.values():
                if other.reservation is not None and other.reservation.clear_path == lane:
                    reason = "region_in_use"
                    break
        if not reason:
            for other in step.vehicles.values():
                if other.mode != "driving" or other is vehicle:
                    continue
                distance = _route_distance(other, network, lane, rear)
                if distance is None:
                    continue
                other_class = other.vehicle_class
                fastest = min(
                    other.speed + other_class.acceleration_mm_per_s2,
                    step.speed_cap(other.path, other_class),
                )
                fastest = max(fastest, other.speed - other_class.deceleration_mm_per_s2, 0)
                if (
                    fastest
                    + stopping_distance(fastest, other_class.deceleration_mm_per_s2)
                    + (other_class.minimum_gap_mm)
                    > distance
                ):
                    reason = "traffic_approaching"
                    break
        if reason:
            if vehicle.wait_reason != reason:
                vehicle.wait_reason = reason
            continue
        vehicle.mode = "leaving"
        vehicle.manoeuvre_until = step.second + _ceil_seconds(vehicle.vehicle_class.parking_exit_ms)
        vehicle.speed = 0
        vehicle.wait_reason = "parking_manoeuvre"
        # The body is on the lane from now on, and a neighbour leaving later this second must
        # see it.
        entries = step.bodies.setdefault(lane, [])
        entries.append((rear, front, vehicle.vehicle_id))
        entries.sort()
        step.emit(
            "parking_exit_started",
            trip_id=trip.trip_id,
            vehicle_id=vehicle.vehicle_id,
            space=vehicle.space,
            until_second=vehicle.manoeuvre_until,
        )


# Reservations ----------------------------------------------------------------------------------


def _front_absolute(vehicle: Vehicle, network: RoadNetwork) -> int:
    return _route_offsets(vehicle, network)[vehicle.route_index] + vehicle.position


def _absolute(vehicle: Vehicle, network: RoadNetwork, path: str, position: int, after: int) -> int:
    offsets = _route_offsets(vehicle, network)
    for index in range(after, len(vehicle.route)):
        if vehicle.route[index] == path:
            return offsets[index] + position
    raise InvalidTrafficStateError(f"{path} is not on the route of {vehicle.vehicle_id}")


def _reservation_points(step: _Step, vehicle: Vehicle) -> tuple[int, int]:
    """Absolute route positions of the reservation's gate and of its clear point."""
    reservation = vehicle.reservation
    assert reservation is not None
    offsets = _route_offsets(vehicle, step.network)
    gate = offsets[reservation.gate_index] + reservation.gate_position
    clear = _absolute(
        vehicle,
        step.network,
        reservation.clear_path,
        reservation.clear_position,
        reservation.gate_index,
    )
    return gate, clear


def _release_and_revoke(step: _Step) -> None:
    network = step.network
    for vehicle in (step.vehicles[key] for key in sorted(step.vehicles)):
        reservation = vehicle.reservation
        if reservation is None:
            continue
        front = _front_absolute(vehicle, network)
        gate, clear = _reservation_points(step, vehicle)
        if front >= clear:
            vehicle.reservation = None
            step.emit(
                "reservation_released",
                vehicle_id=vehicle.vehicle_id,
                reservation_kind=reservation.kind,
                target=reservation.target,
            )
            continue
        if front > gate:
            continue
        deceleration = vehicle.vehicle_class.deceleration_mm_per_s2
        can_stop = stopping_distance(vehicle.speed, deceleration) <= gate - front
        if not can_stop:
            continue
        reason = ""
        junction = network.junctions[reservation.target] if reservation.kind == "junction" else None
        if (
            junction is not None
            and junction.signal is not None
            and step.indication(junction, reservation.connector, step.second) != "green"
        ):
            reason = "signal_no_longer_green"
        if not reason:
            ticks = clearing_ticks(
                clear - front,
                vehicle.speed,
                vehicle.vehicle_class.acceleration_mm_per_s2,
                deceleration,
                _route_cap(step, vehicle),
            )
            if not step.band_free(reservation.bands, step.second, step.second + ticks):
                reason = "pedestrian_due"
        if reason:
            vehicle.reservation = None
            step.emit(
                "reservation_revoked",
                vehicle_id=vehicle.vehicle_id,
                reservation_kind=reservation.kind,
                target=reservation.target,
                reason=reason,
            )


def _route_cap(step: _Step, vehicle: Vehicle) -> int:
    reservation = vehicle.reservation
    caps = [step.speed_cap(vehicle.path, vehicle.vehicle_class)]
    if reservation is not None and reservation.connector:
        caps.append(step.speed_cap(reservation.connector, vehicle.vehicle_class))
    return min(caps)


def _time_to_gate_ms(step: _Step, vehicle: Vehicle, distance: int) -> int:
    ticks = reach_ticks(
        distance,
        vehicle.speed,
        vehicle.vehicle_class.acceleration_mm_per_s2,
        step.speed_cap(vehicle.path, vehicle.vehicle_class),
    )
    return max(ticks - 1, 0) * _MS


def _approaching(step: _Step, junction: JunctionSpec) -> dict[str, list[tuple[Vehicle, int, str]]]:
    """Per inbound lane, the unreserved vehicles heading for this junction's gate, nearest first.

    Each item is ``(vehicle, distance to the gate, the connector it will take)``.
    """
    found: dict[str, list[tuple[Vehicle, int, str]]] = {
        lane: [] for approach in junction.approaches for lane in approach.inbound_lanes
    }
    for vehicle in step.vehicles.values():
        if vehicle.mode != "driving" or vehicle.reservation is not None:
            continue
        upcoming = step.next_gate(vehicle)
        if upcoming is None:
            continue
        gate, index, distance = upcoming
        if gate.kind != "junction" or gate.target != junction.ordinal:
            continue
        if index + 1 >= len(vehicle.route):
            continue
        found[gate.path_id].append((vehicle, distance, vehicle.route[index + 1]))
    for items in found.values():
        items.sort(key=lambda item: (item[1], item[0].vehicle_id))
    return found


def _binding(vehicle: Vehicle, distance: int, step: _Step) -> bool:
    """Whether the gate will bind within two ticks, so admission is worth deciding now."""
    vehicle_class = vehicle.vehicle_class
    fastest = min(
        vehicle.speed + vehicle_class.acceleration_mm_per_s2,
        step.speed_cap(vehicle.path, vehicle_class),
    )
    return distance <= 2 * fastest + stopping_distance(
        fastest, vehicle_class.deceleration_mm_per_s2
    )


def _zone_conflict(step: _Step, vehicle: Vehicle, zones: Sequence[tuple[int, str]]) -> bool:
    """Whether anyone holds, or physically stands in, the other side of any of these zones."""
    network = step.network
    for zone_id, side in zones:
        own = network.zones[zone_id].side(side)
        assert own is not None
        _, _, other_path, other_interval = own
        if step.holders.get((zone_id, other_path), set()) - {vehicle.vehicle_id}:
            return True
        for rear, front, other_id in step.bodies.get(other_path, []):
            if (
                other_id != vehicle.vehicle_id
                and rear <= other_interval[1]
                and other_interval[0] <= front
            ):
                return True
    return False


def _region(
    step: _Step, vehicle: Vehicle, connector: str
) -> tuple[tuple[tuple[int, str], ...], tuple[int, ...], str, int]:
    """The zones and bands a reservation through ``connector`` holds, and its clear point."""
    network = step.network
    exit_lane = network.paths[connector].successors[0]
    extent = network.exit_extent[exit_lane]
    zones = [(zone_id, connector) for zone_id, _ in network.zones_by_path.get(connector, ())]
    zones += [
        (zone_id, exit_lane)
        for zone_id, interval in network.zones_by_path.get(exit_lane, ())
        if interval[0] <= extent
    ]
    bands = {band_id for band_id, _ in network.bands_by_path.get(connector, ())}
    bands |= {
        band_id
        for band_id, interval in network.bands_by_path.get(exit_lane, ())
        if network.bands[band_id].junction is not None and interval[0] <= extent
    }
    return tuple(sorted(set(zones))), tuple(sorted(bands)), exit_lane, extent + vehicle.length


def _exit_room(
    step: _Step, vehicle: Vehicle, lane: str, clear_position: int, transit_ids: set[str]
) -> tuple[bool, int]:
    """Whether the vehicles in transit ahead and this one all fit before the first body beyond.

    ``clear_position`` is where this vehicle's front must reach on ``lane``. Returns the verdict
    and the latest ``clear_by`` among the vehicles in transit ahead.
    """
    network = step.network
    needed = clear_position
    latest = step.second
    for other_id in sorted(transit_ids):
        other = step.vehicles[other_id]
        needed += other.length + other.vehicle_class.minimum_gap_mm
        assert other.reservation is not None
        latest = max(latest, other.reservation.clear_by)
    region_start = clear_position - vehicle.length
    anchor = network.paths[lane].length + vehicle.vehicle_class.minimum_gap_mm
    for rear, front, other_id in step.bodies.get(lane, []):
        if other_id in transit_ids or other_id == vehicle.vehicle_id:
            continue
        if front > region_start or rear >= region_start:
            anchor = min(anchor, rear)
    return needed + vehicle.vehicle_class.minimum_gap_mm <= anchor, latest


def _clear_by(
    step: _Step,
    vehicle: Vehicle,
    distance: int,
    cap: int,
    transit_latest: int,
    transit_length: int,
) -> int:
    """The second by which the vehicle's front will have travelled ``distance``, at the latest.

    Alone, that is the controller's own run to a stop at that distance. Behind vehicles still in
    transit it is, in addition, a run from rest over the queue they occupy plus its own
    distance, starting when the last of them is due to have cleared.
    """
    vehicle_class = vehicle.vehicle_class
    own = clearing_ticks(
        distance,
        vehicle.speed,
        vehicle_class.acceleration_mm_per_s2,
        vehicle_class.deceleration_mm_per_s2,
        cap,
    )
    if transit_length == 0:
        return step.second + own
    after = clearing_ticks(
        transit_length + distance,
        0,
        vehicle_class.acceleration_mm_per_s2,
        vehicle_class.deceleration_mm_per_s2,
        cap,
    )
    return max(step.second + own, transit_latest + after)


def _grant(
    step: _Step,
    vehicle: Vehicle,
    kind: str,
    target: int,
    gate_index: int,
    gate: Gate,
    connector: str,
    zones: tuple[tuple[int, str], ...],
    bands: tuple[int, ...],
    clear_path: str,
    clear_position: int,
    clear_by: int,
    facts: dict[str, Any],
) -> None:
    vehicle.reservation = Reservation(
        kind=kind,
        target=target,
        gate_index=gate_index,
        gate_path=gate.path_id,
        gate_position=gate.position,
        connector=connector,
        zones=zones,
        bands=bands,
        clear_path=clear_path,
        clear_position=clear_position,
        granted_second=step.second,
        clear_by=clear_by,
        facts=facts,
    )
    for zone_id, side in zones:
        step.holders.setdefault((zone_id, side), set()).add(vehicle.vehicle_id)
    step.denials.pop(vehicle.vehicle_id, None)
    step.emit(
        "reservation_granted",
        vehicle_id=vehicle.vehicle_id,
        trip_id=vehicle.trip_id,
        reservation_kind=kind,
        target=target,
        connector=connector,
        clear_by_second=clear_by,
        facts=facts,
    )


def _on_right(first: tuple[int, int], second: tuple[int, int]) -> bool:
    """Whether a vehicle travelling ``second`` comes from the right of one travelling ``first``.

    Right-hand traffic in a counter-clockwise frame: the vehicle on the right is heading a
    quarter turn counter-clockwise of this one.
    """
    return first[0] * second[1] - first[1] * second[0] > 0


def _opposite(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return first[0] * second[1] - first[1] * second[0] == 0 and (
        first[0] * second[0] + first[1] * second[1] < 0
    )


@dataclass
class _Candidate:
    vehicle: Vehicle
    distance: int
    connector: str
    lane: str
    gate_index: int
    approach: Any
    order: int
    turn: str
    stopped: int


def _all_way_yield(
    policy: Any, candidate: _Candidate, peers: list[_Candidate], conflicts: set[tuple[str, str]]
) -> str:
    """Why a stopped vehicle at an all-way stop must let a peer go first, or ``""``.

    Earlier stoppers go first. Among vehicles that stopped in the same second, a vehicle yields
    to a conflicting one on its right and, facing an opposite approach, a turn of lower rank
    yields; if every such vehicle has to yield to another, the first approach in record order
    goes, so a full four-way tie cannot deadlock.
    """
    same = [
        peer
        for peer in peers
        if peer.stopped == candidate.stopped
        and peer is not candidate
        and (candidate.connector, peer.connector) in conflicts
    ]
    for peer in peers:
        if peer is candidate or (candidate.connector, peer.connector) not in conflicts:
            continue
        if 0 <= peer.stopped < candidate.stopped:
            return "arrival_order"

    def yields_to(first: _Candidate, second: _Candidate) -> bool:
        if _on_right(first.approach.direction, second.approach.direction):
            return True
        return _opposite(first.approach.direction, second.approach.direction) and (
            policy.turn_rank(second.turn) < policy.turn_rank(first.turn)
        )

    if not any(yields_to(candidate, peer) for peer in same):
        return ""
    group = [candidate, *same]
    blocked = [
        member
        for member in group
        if any(
            yields_to(member, other)
            for other in group
            if other is not member and (member.connector, other.connector) in conflicts
        )
    ]
    if len(blocked) == len(group) and min(group, key=lambda member: member.order) is candidate:
        return ""
    return "yield_to_right"


def _candidate_rank(policy: Any, candidate: _Candidate) -> tuple[Any, ...]:
    """The order a junction's rule decides its candidates in; ties broken by vehicle id."""
    if policy.rule == "all_way_stop":
        stopped = candidate.stopped if candidate.stopped >= 0 else 1 << 40
        return (stopped, candidate.order, candidate.vehicle.vehicle_id)
    if policy.rule == "priority":
        return (
            candidate.approach.rank,
            policy.turn_rank(candidate.turn),
            candidate.vehicle.vehicle_id,
        )
    if policy.rule == "signal":
        return (policy.turn_rank(candidate.turn), candidate.vehicle.vehicle_id)
    return (candidate.vehicle.vehicle_id,)


def _admit(step: _Step) -> None:
    network = step.network
    for ordinal in sorted(network.junctions):
        junction = network.junctions[ordinal]
        policy = step.catalogs.policy(junction.policy)
        approaching = _approaching(step, junction)
        approach_of = {
            lane: approach for approach in junction.approaches for lane in approach.inbound_lanes
        }
        order_of = {approach.identity: index for index, approach in enumerate(junction.approaches)}
        conflicts = set(junction.conflicts) | {(b, a) for a, b in junction.conflicts}
        candidates: list[_Candidate] = []
        for lane, items in sorted(approaching.items()):
            if not items:
                continue
            vehicle, distance, connector = items[0]
            if not _binding(vehicle, distance, step):
                continue
            gate = step.next_gate(vehicle)
            assert gate is not None
            approach = approach_of[lane]
            candidates.append(
                _Candidate(
                    vehicle=vehicle,
                    distance=distance,
                    connector=connector,
                    lane=lane,
                    gate_index=gate[1],
                    approach=approach,
                    order=order_of[approach.identity],
                    turn=network.paths[connector].turn,
                    stopped=vehicle.stopped_since if distance == 0 and vehicle.speed == 0 else -1,
                )
            )

        candidates.sort(key=partial(_candidate_rank, policy))
        for candidate in candidates:
            vehicle = candidate.vehicle
            connector = candidate.connector
            facts: dict[str, Any] = {
                "rule": policy.rule,
                "policy": policy.key,
                "turn": candidate.turn,
                "approach": candidate.approach.identity,
                "stopped_since": candidate.stopped,
            }
            reason = ""
            if policy.rule == "signal":
                shown = step.indication(junction, connector, step.second)
                facts["indication"] = shown
                if shown != "green":
                    reason = f"signal_{shown}"
            if not reason and candidate.approach.control == "stop" and candidate.stopped < 0:
                reason = "must_stop_first"
            if not reason and policy.rule == "all_way_stop":
                reason = _all_way_yield(policy, candidate, candidates, conflicts)
            zones, bands, exit_lane, clear_position = _region(step, vehicle, connector)
            if not reason and _zone_conflict(step, vehicle, zones):
                reason = "conflict_zone_occupied"
            if not reason and policy.rule in ("priority", "signal"):
                reason = _gap_check(
                    step, junction, policy, candidate, approaching, conflicts, facts
                )
            transit = {
                other.vehicle_id
                for other in step.vehicles.values()
                if other.reservation is not None
                and other.reservation.clear_path == exit_lane
                and other is not vehicle
            }
            latest = step.second
            if not reason:
                fits, latest = _exit_room(step, vehicle, exit_lane, clear_position, transit)
                if not fits:
                    reason = "no_room_beyond_junction"
            clear_by = step.second
            if not reason:
                transit_length = sum(
                    step.vehicles[other_id].length
                    + step.vehicles[other_id].vehicle_class.minimum_gap_mm
                    for other_id in transit
                )
                cap = min(
                    step.speed_cap(vehicle.path, vehicle.vehicle_class),
                    step.speed_cap(connector, vehicle.vehicle_class),
                )
                clear_by = _clear_by(
                    step,
                    vehicle,
                    candidate.distance + network.paths[connector].length + clear_position,
                    cap,
                    latest,
                    transit_length,
                )
                if clear_by - step.second > LOOKAHEAD_S:
                    reason = "clearance_beyond_lookahead"
                elif not step.band_free(bands, step.second, clear_by):
                    reason = "pedestrian_due"
            if reason:
                step.denials[vehicle.vehicle_id] = reason
                continue
            _grant(
                step,
                vehicle,
                "junction",
                ordinal,
                candidate.gate_index,
                network.gates[candidate.lane][-1],
                connector,
                zones,
                bands,
                exit_lane,
                clear_position,
                clear_by,
                facts,
            )
    _admit_bands(step)


def _gap_check(
    step: _Step,
    junction: JunctionSpec,
    policy: Any,
    candidate: _Candidate,
    approaching: Mapping[str, list[tuple[Vehicle, int, str]]],
    conflicts: set[tuple[str, str]],
    facts: dict[str, Any],
) -> str:
    """Gap acceptance against every approaching vehicle whose movement has priority over this one.

    The gap is the soonest that vehicle could reach its stop line accelerating flat out, a lower
    bound, compared with the policy's critical headway for this movement.

    Only the front vehicle of each lane counts: nothing behind it can reach the junction first.
    A front vehicle stopped at its line and already refused this second (higher priorities are
    decided first) is waiting, not approaching, so it does not hold this movement back; once this
    movement holds its zones, that vehicle is kept out until they are released.
    """
    network = step.network
    ranks = sorted({item.rank for item in junction.approaches})
    minor = policy.rule == "priority" and candidate.approach.rank > ranks[0]
    gaps: list[list[Any]] = []
    for other_lane, items in sorted(approaching.items()):
        other_approach = junction.approach_of_lane(other_lane)
        if other_approach.identity == candidate.approach.identity:
            continue
        for other, distance, other_connector in items[:1]:
            if distance == 0 and other.speed == 0 and other.vehicle_id in step.denials:
                continue
            if (candidate.connector, other_connector) not in conflicts:
                continue
            other_turn = network.paths[other_connector].turn
            if policy.rule == "signal":
                if step.indication(junction, other_connector, step.second) != "green":
                    continue
                if policy.turn_rank(other_turn) >= policy.turn_rank(candidate.turn):
                    continue
                headway = policy.headway_ms("permitted_left")
            else:
                higher = other_approach.rank < candidate.approach.rank or (
                    other_approach.rank == candidate.approach.rank
                    and policy.turn_rank(other_turn) < policy.turn_rank(candidate.turn)
                )
                if not higher:
                    continue
                if minor:
                    movement = {
                        "left": "minor_left",
                        "right": "minor_right",
                        "straight": "minor_through",
                    }
                    headway = policy.headway_ms(movement[candidate.turn])
                else:
                    headway = policy.headway_ms("major_left")
            arrival = _time_to_gate_ms(step, other, distance)
            gaps.append([other.vehicle_id, arrival, headway])
            if arrival < headway:
                facts["gaps"] = gaps
                return "gap_rejected"
    facts["gaps"] = gaps
    return ""


def _admit_bands(step: _Step) -> None:
    network = step.network
    for band in network.bands:
        if band.junction is not None:
            continue
        for path_id, low, high in band.intervals:
            gate = next(
                item
                for item in network.gates[path_id]
                if item.kind == "band" and item.target == band.band_id
            )
            candidates = []
            for vehicle in step.vehicles.values():
                if vehicle.mode != "driving" or vehicle.reservation is not None:
                    continue
                upcoming = step.next_gate(vehicle)
                if upcoming is None or upcoming[0] != gate:
                    continue
                candidates.append((upcoming[2], vehicle.vehicle_id, upcoming[1], vehicle))
            if not candidates:
                continue
            distance, _, gate_index, vehicle = min(candidates, key=lambda item: (item[0], item[1]))
            if not _binding(vehicle, distance, step):
                continue
            transit = {
                other.vehicle_id
                for other in step.vehicles.values()
                if other.reservation is not None
                and other.reservation.clear_path == path_id
                and other is not vehicle
            }
            clear_position = high + vehicle.length
            fits, latest = _exit_room(step, vehicle, path_id, clear_position, transit)
            reason = "" if fits else "no_room_beyond_crossing"
            clear_by = step.second
            if not reason:
                transit_length = sum(
                    step.vehicles[other_id].length
                    + step.vehicles[other_id].vehicle_class.minimum_gap_mm
                    for other_id in transit
                )
                clear_by = _clear_by(
                    step,
                    vehicle,
                    distance + clear_position - low,
                    step.speed_cap(path_id, vehicle.vehicle_class),
                    latest,
                    transit_length,
                )
                if clear_by - step.second > LOOKAHEAD_S:
                    reason = "clearance_beyond_lookahead"
                elif not step.band_free((band.band_id,), step.second, clear_by):
                    reason = "pedestrian_due"
            if reason:
                step.denials[vehicle.vehicle_id] = reason
                continue
            _grant(
                step,
                vehicle,
                "band",
                band.band_id,
                gate_index,
                gate,
                "",
                (),
                (band.band_id,),
                path_id,
                clear_position,
                clear_by,
                {"rule": "crossing", "crossing": band.society_crossing_id},
            )


# Movement --------------------------------------------------------------------------------------


@dataclass
class _Decision:
    speed: int
    reason: str
    breach: bool


def _choose_speed(step: _Step, vehicle: Vehicle) -> _Decision:
    """The highest speed every obstacle, cap, destination and gate on the route allows."""
    network = step.network
    vehicle_class = vehicle.vehicle_class
    acceleration = vehicle_class.acceleration_mm_per_s2
    deceleration = vehicle_class.deceleration_mm_per_s2
    gap = vehicle_class.minimum_gap_mm
    low = max(0, vehicle.speed - deceleration)
    high = max(low, min(vehicle.speed + acceleration, step.speed_cap(vehicle.path, vehicle_class)))
    horizon = high + stopping_distance(high, deceleration) + gap + 1
    obstacles: dict[str, tuple[int, int, int]] = {}
    statics: list[tuple[int, str]] = []
    caps: list[tuple[int, int]] = []
    guard: tuple[int, JunctionSpec, str] | None = None
    reservation = vehicle.reservation
    distance = 0
    start = vehicle.position

    def note(other_id: str, gap_to: int) -> None:
        other = step.vehicles[other_id]
        known = obstacles.get(other_id)
        if known is None or gap_to < known[0]:
            obstacles[other_id] = (
                gap_to,
                other.speed if other.mode == "driving" else 0,
                other.vehicle_class.deceleration_mm_per_s2,
            )

    for index in range(vehicle.route_index, len(vehicle.route)):
        path = vehicle.route[index]
        spec = network.paths[path]
        if index > vehicle.route_index:
            cap = step.speed_cap(path, vehicle_class)
            if cap < high:
                caps.append((distance, cap))
        for rear, front, other_id in step.bodies.get(path, []):
            if other_id != vehicle.vehicle_id and front > start:
                note(other_id, distance + rear - start)
        last = index == len(vehicle.route) - 1
        if last:
            statics.append((distance + _target_position(vehicle, network) - start, "destination"))
        blocked = False
        for gate in network.gates.get(path, ()):
            if gate.position < start:
                continue
            gate_distance = distance + gate.position - start
            held = (
                reservation is not None
                and reservation.gate_index == index
                and reservation.gate_position == gate.position
            )
            if held:
                if gate.kind == "junction" and network.junctions[gate.target].signal is not None:
                    guard = (gate_distance, network.junctions[gate.target], reservation.connector)
                continue
            statics.append((gate_distance, "gate"))
            blocked = True
            break
        if blocked or last:
            break
        following = vehicle.route[index + 1]
        for successor in spec.successors:
            if successor == following:
                continue
            extent = network.joint_extent[(path, successor)]
            for rear, _, other_id in step.bodies.get(successor, []):
                if other_id != vehicle.vehicle_id and rear <= extent:
                    note(other_id, distance + spec.length - start + rear)
        distance += spec.length - start
        start = 0
        if distance > horizon:
            break

    def allowed(candidate: int) -> bool:
        for gap_to, other_speed, other_deceleration in obstacles.values():
            if not follows_safely(
                candidate, deceleration, gap, gap_to, other_speed, other_deceleration
            ):
                return False
        for gap_to, _ in statics:
            if not follows_safely(candidate, deceleration, 0, gap_to, 0, 1):
                return False
        for cap_distance, cap in caps:
            if not cap_allows(candidate, deceleration, cap_distance, cap):
                return False
        return True

    best = highest_speed(low, high, allowed)
    breach = best is None
    speed = low if best is None else best
    if guard is not None and not breach:
        gate_distance, junction, connector = guard
        if not _guard_ok(step, speed, deceleration, gate_distance, junction, connector):
            fallback = highest_speed(
                low,
                speed,
                lambda candidate: (
                    gate_distance - candidate >= stopping_distance(candidate, deceleration)
                ),
            )
            if fallback is None:
                breach = True
                speed = low
            else:
                speed = fallback
    reason = ""
    if speed == 0:
        limits = [(gap_to, "queued") for gap_to, _, _ in obstacles.values()]
        limits.extend(statics)
        reason = min(limits)[1] if limits else "stopped"
    if breach:
        step.breaches.append(
            {"vehicle_id": vehicle.vehicle_id, "second": step.second, "kind": "no_safe_speed"}
        )
    return _Decision(speed=speed, reason=reason, breach=breach)


def _guard_ok(
    step: _Step,
    speed: int,
    deceleration: int,
    gate_distance: int,
    junction: JunctionSpec,
    connector: str,
) -> bool:
    """A held signal gate: cross now on green or amber, stay able to stop, or cross before red."""
    remaining = gate_distance - speed
    if remaining < 0:
        return step.indication(junction, connector, step.second) in ("green", "amber")
    if remaining >= stopping_distance(speed, deceleration):
        return True
    ticks = 1
    while braking_run(speed, deceleration, ticks) <= remaining:
        ticks += 1
    return ticks < step.until_red(junction, connector)


def _move(step: _Step, vehicle: Vehicle, decision: _Decision) -> None:
    network = step.network
    before = _front_absolute(vehicle, network)
    old_index = vehicle.route_index
    points = [list(network.paths[vehicle.path].line.point_at(vehicle.position))]
    travel = decision.speed
    while travel > 0:
        spec = network.paths[vehicle.path]
        room = spec.length - vehicle.position
        end = vehicle.position + min(travel, room)
        for vertex in range(1, spec.line.piece_count):
            if vehicle.position < spec.line.offsets[vertex] <= end:
                points.append(list(spec.line.points[vertex]))
        if travel <= room:
            vehicle.position = end
            travel = 0
            break
        if vehicle.route_index + 1 >= len(vehicle.route):
            vehicle.position = spec.length
            step.breaches.append(
                {"vehicle_id": vehicle.vehicle_id, "second": step.second, "kind": "ran_off_route"}
            )
            break
        points.append(list(spec.line.points[-1]))
        travel -= room
        vehicle.route_index += 1
        vehicle.position = 0
    points.append(list(network.paths[vehicle.path].line.point_at(vehicle.position)))
    trail: list[list[int]] = []
    for point in points:
        if not trail or trail[-1] != point:
            trail.append(point)
    vehicle.motion_path = trail
    vehicle.speed = decision.speed
    after = _front_absolute(vehicle, network)
    offsets = _route_offsets(vehicle, network)
    for index in range(old_index, vehicle.route_index + 1):
        for gate in network.gates.get(vehicle.route[index], ()):
            absolute = offsets[index] + gate.position
            if before <= absolute < after:
                _record_entry(step, vehicle, gate, index)
    for index in range(old_index + 1, vehicle.route_index + 1):
        if network.paths[vehicle.route[index]].kind == "lane":
            vehicle.lane_entry = [vehicle.route[index], step.second + 1, 0]
    if decision.speed > 0:
        vehicle.stopped_since = -1
        vehicle.wait_reason = ""
        vehicle.wait_since = -1
        return
    upcoming = step.next_gate(vehicle)
    at_line = upcoming is not None and upcoming[2] == 0
    if at_line and vehicle.stopped_since < 0:
        vehicle.stopped_since = step.second + 1
    reason = decision.reason
    if reason == "gate":
        reason = step.denials.get(vehicle.vehicle_id, "approaching_gate")
    vehicle.wait_reason = reason
    if vehicle.wait_since < 0:
        vehicle.wait_since = step.second


def _record_entry(step: _Step, vehicle: Vehicle, gate: Gate, index: int) -> None:
    network = step.network
    reservation = vehicle.reservation
    held = (
        reservation is not None
        and reservation.gate_index == index
        and reservation.gate_position == gate.position
    )
    if not held:
        step.breaches.append(
            {
                "vehicle_id": vehicle.vehicle_id,
                "second": step.second,
                "kind": "entered_without_reservation",
            }
        )
    if gate.kind == "junction":
        junction = network.junctions[gate.target]
        connector = vehicle.route[index + 1]
        facts: dict[str, Any] = {}
        if junction.signal is not None:
            facts["indication"] = step.indication(junction, connector, step.second)
        entry_path, entry_second, entry_position = vehicle.lane_entry or [
            gate.path_id,
            step.second,
            0,
        ]
        travelled = gate.position - entry_position if entry_path == gate.path_id else gate.position
        speed = max(step.speed_cap(gate.path_id, vehicle.vehicle_class), 1)
        free_flow = -(-travelled * _MS // speed)
        step.emit(
            "junction_entered",
            vehicle_id=vehicle.vehicle_id,
            trip_id=vehicle.trip_id,
            junction=gate.target,
            connector=connector,
            delay_ms=max(0, (step.second + 1 - entry_second) * _MS - free_flow),
            facts=facts,
        )
    else:
        step.emit(
            "crossing_entered",
            vehicle_id=vehicle.vehicle_id,
            trip_id=vehicle.trip_id,
            band=gate.target,
            crossing=network.bands[gate.target].society_crossing_id,
        )


def _after_move(step: _Step) -> None:
    network = step.network
    for vehicle in (step.vehicles[key] for key in sorted(step.vehicles)):
        if vehicle.mode != "driving" or vehicle.speed != 0:
            continue
        if vehicle.route_index != len(vehicle.route) - 1:
            continue
        if vehicle.position != _target_position(vehicle, network):
            continue
        vehicle.mode = "arriving"
        vehicle.manoeuvre_until = step.second + _ceil_seconds(
            vehicle.vehicle_class.parking_entry_ms
        )
        vehicle.wait_reason = "parking_manoeuvre"
        vehicle.wait_since = -1
        step.emit(
            "parking_entry_started",
            trip_id=vehicle.trip_id,
            vehicle_id=vehicle.vehicle_id,
            space=vehicle.target_space,
            until_second=vehicle.manoeuvre_until,
        )


def _stalls(step: _Step) -> None:
    for trip in (step.trips[key] for key in sorted(step.trips)):
        if trip.status not in ("waiting", "driving", "blocked") or not trip.origin_space:
            continue
        vehicle = step.vehicles[trip.vehicle_id]
        if vehicle.trip_id != trip.trip_id:
            continue
        stalled = (
            vehicle.mode in ("parked", "driving")
            and vehicle.wait_since >= 0
            and step.second - vehicle.wait_since >= STALL_LIMIT_S
        )
        if trip.status != "blocked" and stalled:
            trip.status = "blocked"
            trip.reason = vehicle.wait_reason or "waiting"
            trip.blocked_second = step.second
            step.emit(
                "trip_blocked",
                trip_id=trip.trip_id,
                vehicle_id=vehicle.vehicle_id,
                reason=trip.reason,
                waiting_since=vehicle.wait_since,
            )
        elif trip.status == "blocked" and not stalled:
            trip.status = "driving" if trip.departed_second >= 0 else "waiting"
            step.emit(
                "trip_unblocked",
                trip_id=trip.trip_id,
                vehicle_id=vehicle.vehicle_id,
                reason=trip.reason,
            )
            trip.reason = ""
