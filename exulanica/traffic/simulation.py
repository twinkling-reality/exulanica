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
   that can still stop when another vehicle without a reservation of that junction stands between
   them and their stop line, their signal is no longer green or a pedestrian is due.
5. Admit vehicles at their gates, junction by junction, by the junction's rule, never one with
   another vehicle standing between it and its stop line.
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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.seed import require_seed
from exulanica.traffic.admission import _admit, _release_and_revoke
from exulanica.traffic.catalogs import TrafficCatalogs
from exulanica.traffic.errors import InvalidTrafficInputError, InvalidTrafficStateError
from exulanica.traffic.inputs import TrafficInputs, TripRequest
from exulanica.traffic.kinematics import (
    braking_run,
    cap_allows,
    follows_safely,
    highest_speed,
    stopping_distance,
)
from exulanica.traffic.network import Gate, JunctionSpec, RoadNetwork
from exulanica.traffic.routing import plan_route
from exulanica.traffic.signal_actuation import SignalTimeline
from exulanica.traffic.signals import interval_index
from exulanica.traffic.state import (
    _MS,
    TRAFFIC_NAMESPACE,
    TRAFFIC_PROFILE,
    TrafficStep,
    Trip,
    Vehicle,
    _ceil_seconds,
    _front_absolute,
    _read_state,
    _route_distance,
    _route_offsets,
    _Step,
    _target_position,
    body_intervals,
    initial_traffic,
    state_sha256,
    vehicle_id,
)

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

#: A trip whose vehicle has made no progress for this many simulated seconds is recorded as
#: blocked, with the reason it is waiting. A reporting threshold, not a physical parameter.
STALL_LIMIT_S: Final = 300


def advance_traffic(
    state: Mapping[str, Any],
    seed: str,
    network: RoadNetwork,
    catalogs: TrafficCatalogs,
    inputs: TrafficInputs,
    *,
    signal_timelines: Mapping[str, SignalTimeline] | None = None,
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
        signal_timelines={} if signal_timelines is None else signal_timelines,
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
    for driving_id in sorted(decisions):
        _move(step, step.vehicles[driving_id], decisions[driving_id])
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
    # A space is full when its parked vehicles and the vehicles heading for it reach its capacity.
    holding: dict[str, int] = {}
    for other in step.vehicles.values():
        for held in (other.space if other.mode == "parked" else "", other.target_space):
            if held:
                holding[held] = holding.get(held, 0) + 1

    def full(identity: str) -> bool:
        return holding.get(identity, 0) >= network.spaces[identity].capacity

    class_key = vehicle.vehicle_class.key
    if request.destination_kind == "space":
        space = network.spaces.get(request.destination)
        if space is None:
            block("unknown_space")
            return
        if class_key not in space.classes:
            block("space_does_not_fit_class")
            return
        if full(space.identity):
            block("destination_space_taken")
            return
        target = space.identity
    else:
        candidates = [
            space.identity
            for space in network.spaces.values()
            if network.segment_ordinals[space.segment] == request.street_segment_ordinal
            and class_key in space.classes
            and not full(space.identity)
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
        timeline = step.signal_timelines.get(signal.identity)
        now = (
            timeline.index_at(step.second)
            if timeline is not None
            else interval_index(plan, signal.offset_s, step.second)
        )
        previous = (
            timeline.index_at(step.second - 1)
            if timeline is not None and step.second > timeline.start_second
            else interval_index(plan, signal.offset_s, step.second - 1)
        )
        if step.second > 0 and now == previous:
            continue
        interval = (
            timeline.interval_at(step.second) if timeline is not None else plan.intervals[now]
        )
        step.emit(
            "signal_interval",
            junction=junction.identity,
            signal=signal.identity,
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
            vehicle.slot = -1
            trip.departed_second = step.second
            if trip.status != "blocked":
                trip.status = "driving"
            vehicle.lane_entry = [vehicle.path, step.second, vehicle.position]
            vehicle.wait_reason = ""
            vehicle.wait_since = -1
            step.emit("trip_departed", trip_id=trip.trip_id, vehicle_id=vehicle.vehicle_id)
        elif vehicle.mode == "arriving":
            if vehicle.reservation is not None:
                # Every clear point lies before the destination, so this is a simulation fault.
                step.breaches.append(
                    {
                        "vehicle_id": vehicle.vehicle_id,
                        "second": step.second,
                        "kind": "parked_holding_reservation",
                    }
                )
                step.emit(
                    "reservation_released",
                    vehicle_id=vehicle.vehicle_id,
                    reservation_kind=vehicle.reservation.kind,
                    target=vehicle.reservation.target,
                )
                vehicle.reservation = None
            vehicle.mode = "parked"
            vehicle.manoeuvre_until = -1
            vehicle.space = vehicle.target_space
            taken_slots = {
                other.slot
                for other in step.vehicles.values()
                if other.mode == "parked" and other.space == vehicle.space and other is not vehicle
            }
            vehicle.slot = min(set(range(len(taken_slots) + 1)) - taken_slots)
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
            crossing_identity=gate.target,
            crossing=network.band(gate.target).society_crossing_id,
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
