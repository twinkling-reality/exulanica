"""A traffic state, what one simulated second reads and writes.

The vehicles, trips and junction reservations of a state, read from its document and checked
(:func:`_read_state`), the first state a world's fleet takes (:func:`initial_traffic`), the digest
and ids every receipt and event names, where a vehicle is along its route, and the working state
of one second (:class:`_Step`). :mod:`exulanica.traffic.simulation` advances it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.draw import draw_integer
from exulanica.grammar.seed import require_seed
from exulanica.traffic.catalogs import TrafficCatalogs, VehicleClass
from exulanica.traffic.errors import InvalidTrafficInputError, InvalidTrafficStateError
from exulanica.traffic.inputs import CrossingEntry
from exulanica.traffic.network import Gate, JunctionSpec, RoadNetwork
from exulanica.traffic.signal_actuation import SignalTimeline
from exulanica.traffic.signals import seconds_until_red, vehicle_indication

TRAFFIC_PROFILE: Final = "exulanica-traffic/v1"

TRAFFIC_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/traffic")

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
    #: The junction's identity for a junction reservation, the crossing's for a band.
    target: str
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
    #: Which of its space's places a parked vehicle stands in, from 0; -1 when not parked.
    slot: int
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
            "slot": self.slot,
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
    """A parked fleet, every vehicle in a place of a space its class fits, chosen by seeded draws.

    A space holds as many vehicles as its capacity; each takes the lowest free slot.
    """
    require_seed(seed)
    try:
        uuid.UUID(traffic_id)
    except (TypeError, ValueError) as error:
        raise InvalidTrafficInputError("traffic_id is a UUID") from error
    if network.catalog_sha256 != catalogs.digest:
        raise InvalidTrafficInputError("the network was compiled against other catalogs")
    used: dict[str, int] = {}
    vehicles = []
    ordinal = 0
    for class_key in sorted(fleet):
        count = fleet[class_key]
        if type(count) is not int or count < 0:
            raise InvalidTrafficInputError(f"fleet count for {class_key} is a non-negative int")
        vehicle_class = catalogs.vehicle_class(class_key)
        for index in range(count):
            fits = [
                identity
                for identity, space in network.spaces.items()
                if class_key in space.classes and used.get(identity, 0) < space.capacity
            ]
            if not fits:
                raise InvalidTrafficInputError(f"no free space fits another {class_key}")
            space = fits[draw_integer(seed, f"traffic.fleet.{class_key}", index, 0, len(fits) - 1)]
            slot = used.get(space, 0)
            used[space] = slot + 1
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
                    slot=slot,
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
                slot=item["slot"],
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
    signal_timelines: Mapping[str, SignalTimeline] = field(default_factory=dict)
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
        timeline = self.signal_timelines.get(signal.identity)
        if timeline is not None:
            return timeline.vehicle_indication(second, signal.group_of(connector))
        plan = self.catalogs.plan(signal.plan)
        return vehicle_indication(plan, signal.offset_s, second, signal.group_of(connector))

    def until_red(self, junction: JunctionSpec, connector: str) -> int:
        key = (junction.identity, connector)
        if key not in self.red_cache:
            signal = junction.signal
            assert signal is not None
            timeline = self.signal_timelines.get(signal.identity)
            if timeline is not None:
                self.red_cache[key] = timeline.seconds_until_red(
                    self.second, signal.group_of(connector)
                )
            else:
                plan = self.catalogs.plan(signal.plan)
                self.red_cache[key] = seconds_until_red(
                    plan, signal.offset_s, self.second, signal.group_of(connector)
                )
        return self.red_cache[key]

    # Geometry of routes ------------------------------------------------------------------------

    def next_gate(self, vehicle: Vehicle) -> tuple[Gate, int, int] | None:
        """The first gate at or ahead of the front: ``(gate, route index, distance)``.

        A gate on the last path at or beyond the destination is not on the trip, because the
        front stops at the destination, so it is never returned.
        """
        distance = 0
        start = vehicle.position
        last = len(vehicle.route) - 1
        for index in range(vehicle.route_index, len(vehicle.route)):
            path = vehicle.route[index]
            for gate in self.network.gates.get(path, ()):
                if index == last and gate.position >= _target_position(vehicle, self.network):
                    return None
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


def _front_absolute(vehicle: Vehicle, network: RoadNetwork) -> int:
    return _route_offsets(vehicle, network)[vehicle.route_index] + vehicle.position


def _absolute(vehicle: Vehicle, network: RoadNetwork, path: str, position: int, after: int) -> int:
    offsets = _route_offsets(vehicle, network)
    for index in range(after, len(vehicle.route)):
        if vehicle.route[index] == path:
            return offsets[index] + position
    raise InvalidTrafficStateError(f"{path} is not on the route of {vehicle.vehicle_id}")
