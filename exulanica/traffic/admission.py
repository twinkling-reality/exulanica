"""Who may pass a junction stop line this second, by the junction's rule.

Releasing reservations whose vehicle has cleared its region and revoking those of vehicles that can
still stop (:func:`_release_and_revoke`), then admitting vehicles at their gates, junction by
junction (:func:`_admit`): a signal grants only on green, priority and all-way stops by their order,
and never to a vehicle with another standing between it and its stop line or a pedestrian due on a
crossing in its region. Steps 4 and 5 of :func:`~exulanica.traffic.simulation.advance_traffic`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from exulanica.traffic.inputs import LOOKAHEAD_S
from exulanica.traffic.kinematics import clearing_ticks, reach_ticks, stopping_distance
from exulanica.traffic.network import Gate, JunctionSpec, RoadNetwork
from exulanica.traffic.state import (
    _MS,
    Reservation,
    Vehicle,
    _absolute,
    _front_absolute,
    _route_distance,
    _route_offsets,
    _Step,
    _target_position,
)


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


def _vehicle_ahead(step: _Step, vehicle: Vehicle, lane: str, junction_id: str) -> bool:
    """Whether another vehicle stands on ``lane``, ahead of ``vehicle``'s front and before the
    stop line, without a reservation of ``junction_id``: one waiting, parking or leaving a space
    there, which ``vehicle`` cannot pass before the line. A vehicle not yet on the lane has every
    body on it ahead of it."""
    front = vehicle.position if vehicle.path == lane else -1
    for _rear, body_front, other_id in step.bodies.get(lane, ()):
        if other_id == vehicle.vehicle_id or body_front <= front:
            continue
        held = step.vehicles[other_id].reservation
        if held is not None and held.kind == "junction" and held.target == junction_id:
            continue
        return True
    return False


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
        if junction is not None and _vehicle_ahead(
            step, vehicle, reservation.gate_path, junction.identity
        ):
            # Held behind a vehicle it cannot pass, it could not clear the junction in its turn,
            # and the room it holds would keep that vehicle out: it waits outside, unreserved.
            reason = "vehicle_ahead"
        if (
            not reason
            and junction is not None
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
        if gate.kind != "junction" or gate.target != junction.identity:
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


def _along(vehicle: Vehicle, network: RoadNetwork, lane: str) -> int | None:
    """The front's position on ``lane``, negative by the distance still to go before reaching it."""
    if vehicle.path == lane:
        return vehicle.position
    distance = _route_distance(vehicle, network, lane, 0)
    return None if distance is None else -distance


def _exit_room(
    step: _Step, vehicle: Vehicle, lane: str, clear_position: int, transit_ids: set[str]
) -> tuple[bool, int]:
    """Whether the vehicles in transit ahead and this one all fit before the first body beyond.

    ``clear_position`` is where this vehicle's front must reach on ``lane``. Returns the verdict
    and the latest ``clear_by`` among the vehicles in transit ahead.

    A vehicle in transit is assumed to move on beyond its own clear point, except one ahead
    whose trip ends on this lane: it stops at its space and stands there for its parking
    manoeuvre, so its parked rear is an obstacle like any body beyond. Without that, a follower
    admitted behind it would be held inside the region it was admitted to cross.
    """
    network = step.network
    needed = clear_position
    latest = step.second
    region_start = clear_position - vehicle.length
    anchor = network.paths[lane].length + vehicle.vehicle_class.minimum_gap_mm
    own = _along(vehicle, network, lane)
    for other_id in sorted(transit_ids):
        other = step.vehicles[other_id]
        needed += other.length + other.vehicle_class.minimum_gap_mm
        assert other.reservation is not None
        latest = max(latest, other.reservation.clear_by)
        if other.route[-1] == lane and own is not None:
            ahead = _along(other, network, lane)
            if ahead is not None and ahead > own:
                anchor = min(anchor, _target_position(other, network) - other.length)
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
    target: str,
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
    for junction_id in sorted(network.junctions):
        junction = network.junctions[junction_id]
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
            if _vehicle_ahead(step, vehicle, candidate.lane, junction_id):
                reason = "vehicle_ahead"
            if not reason and policy.rule == "signal":
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
                junction_id,
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
                if item.kind == "band" and item.target == band.identity
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
                band.identity,
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
