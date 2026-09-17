"""Negative controls for the transition checker: every check it makes, shown able to fire.

A checker that reports nothing on a real run proves nothing until it has been seen to report
something. Each test here takes a real recorded transition from a busy run, plants exactly one
violation of one kind into a copy of it (a vehicle placed on another, a reservation removed, the
clock moved to red, a stop that never happened, a priority vehicle close to its line, a vehicle
that stopped first left waiting, a pedestrian on a crosswalk), and requires the checker to name
that kind, while the unplanted transition stays clean for that kind.
"""

from __future__ import annotations

import copy
import uuid
from functools import cache

from exulanica.traffic.checks import CHECK_KINDS, TransitionChecker
from exulanica.traffic.inputs import CrossingEntry, CrossingFeed, TrafficInputs
from exulanica.traffic.network import JunctionSpec

from traffic_scenarios import BUSY_FLEET, AdaptiveRun, fixture, run_adaptive

PLANTED_KINDS = (
    "overlap",
    "entered_without_reservation",
    "entered_on_red",
    "did_not_stop",
    "gap_not_given",
    "all_way_order",
    "crossing_conflict",
)


@cache
def _history() -> AdaptiveRun:
    return run_adaptive(
        "checks",
        demand_seconds=600,
        run_seconds=900,
        fleet=BUSY_FLEET,
        pedestrian_spacing_s=45,
        keep_states=True,
    )


def _states() -> list[dict]:
    states = _history().states
    assert states is not None
    return states


def _checker(inputs: TrafficInputs | None = None) -> TransitionChecker:
    network, catalogs = fixture()
    return TransitionChecker(network, catalogs, inputs or _history().inputs)


def _events(kind: str) -> list[dict]:
    return [event["document"] for event in _history().events if event["document"]["kind"] == kind]


def _vehicle(state: dict, vehicle_id: str) -> dict:
    [found] = [vehicle for vehicle in state["vehicles"] if vehicle["id"] == vehicle_id]
    return found


def _kinds(violations, vehicle_id: str | None = None) -> set[str]:
    return {
        violation.kind
        for violation in violations
        if vehicle_id is None or vehicle_id in violation.vehicles
    }


def _observed_through(second: int, states=None) -> TransitionChecker:
    """A checker that has watched every state up to and including ``second``."""
    checker = _checker()
    for state in (states or _states())[: second + 1]:
        checker.observe_stops(state)
    return checker


def _planted_vehicle(template: dict, lane: str, connector: str, position: int, speed: int) -> dict:
    network, _ = fixture()
    planted = copy.deepcopy(template)
    planted.update(
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"planted:{lane}:{position}:{speed}")),
            "ordinal": 9_999,
            "vehicle_class": "passenger_car",
            "mode": "driving",
            "space": "",
            "trip_id": "planted",
            "route": [lane, connector, network.paths[connector].successors[0]],
            "route_index": 0,
            "position_mm": position,
            "speed_mm_per_s": speed,
            "reservation": None,
            "manoeuvre_until": -1,
            "motion_path_mm": [],
        }
    )
    return planted


def _without_lane(state: dict, lane: str) -> dict:
    """A copy of ``state`` with every vehicle whose front is on ``lane`` removed."""
    copied = copy.deepcopy(state)
    copied["vehicles"] = [
        vehicle
        for vehicle in copied["vehicles"]
        if not vehicle["route"] or vehicle["route"][vehicle["route_index"]] != lane
    ]
    return copied


def test_every_check_kind_has_a_negative_control_here():
    assert PLANTED_KINDS == CHECK_KINDS


# ---------------------------------------------------------------------------------------------
# Overlap


def test_a_vehicle_placed_on_another_is_an_overlap():
    checker = _checker()
    for state in _states()[300:]:
        driving = [vehicle for vehicle in state["vehicles"] if vehicle["mode"] == "driving"]
        if len(driving) >= 2:
            break
    else:
        raise AssertionError("the run never had two vehicles driving at once")
    assert _kinds(checker.overlaps(state)) == set()
    first, second = driving[:2]
    planted = copy.deepcopy(state)
    moved = _vehicle(planted, second["id"])
    for field in ("route", "route_index", "position_mm"):
        moved[field] = copy.deepcopy(first[field])
    violations = checker.overlaps(planted)
    assert [violation.kind for violation in violations] == ["overlap"]
    assert set(violations[0].vehicles) == {first["id"], second["id"]}


# ---------------------------------------------------------------------------------------------
# Entries


def _entry_transition(kind: str, **match) -> tuple[dict, dict, dict]:
    for event in _events(kind):
        if all(event[key] == value for key, value in match.items()):
            second = event["second"]
            return event, _states()[second], _states()[second + 1]
    raise AssertionError(f"no {kind} event matching {match}")


def test_crossing_a_gate_without_holding_its_reservation_is_caught():
    checker = _checker()
    for kind in ("junction_entered", "crossing_entered"):
        event, before, after = _entry_transition(kind)
        vehicle_id = event["vehicle_id"]
        assert "entered_without_reservation" not in _kinds(
            checker.entries(before, after), vehicle_id
        )
        planted = copy.deepcopy(after)
        _vehicle(planted, vehicle_id)["reservation"] = None
        assert "entered_without_reservation" in _kinds(checker.entries(before, planted), vehicle_id)


def _red_second(checker: TransitionChecker, junction: JunctionSpec, connector: str, start: int):
    return next(
        second
        for second in range(start, start + 60)
        if checker.indication(junction, connector, second) == "red"
    )


def test_entering_or_being_admitted_on_red_is_caught():
    network, _ = fixture()
    checker = _checker()
    junction = network.junctions[0]
    event, before, after = _entry_transition("junction_entered", junction=0)
    vehicle_id, connector = event["vehicle_id"], event["connector"]
    assert event["facts"]["indication"] in ("green", "amber")
    assert "entered_on_red" not in _kinds(checker.entries(before, after), vehicle_id)
    red = _red_second(checker, junction, connector, before["second"])
    moved_before = {**copy.deepcopy(before), "second": red}
    moved_after = {**copy.deepcopy(after), "second": red + 1}
    assert "entered_on_red" in _kinds(checker.entries(moved_before, moved_after), vehicle_id)

    grant = next(
        event
        for event in _events("reservation_granted")
        if event["reservation_kind"] == "junction" and event["target"] == 0
    )
    vehicle_id, second = grant["vehicle_id"], grant["second"]
    before, after = _states()[second], _states()[second + 1]
    assert "entered_on_red" not in _kinds(checker.grant_rules(before, after), vehicle_id)
    red = _red_second(checker, junction, grant["connector"], second)
    moved_before = {**copy.deepcopy(before), "second": red}
    moved_after = copy.deepcopy(after)
    _vehicle(moved_after, vehicle_id)["reservation"]["granted_second"] = red
    assert "entered_on_red" in _kinds(checker.grant_rules(moved_before, moved_after), vehicle_id)


# ---------------------------------------------------------------------------------------------
# Stops, gaps and arrival order


def _grants_at(rule: str) -> list[dict]:
    return [
        event
        for event in _events("reservation_granted")
        if event["reservation_kind"] == "junction" and event["facts"]["rule"] == rule
    ]


def test_admission_at_a_stop_line_the_vehicle_never_stopped_at_is_caught():
    grant = _grants_at("all_way_stop")[0]
    vehicle_id, second = grant["vehicle_id"], grant["second"]
    before, after = _states()[second], _states()[second + 1]
    honest = _observed_through(second)
    assert "did_not_stop" not in _kinds(honest.grant_rules(before, after), vehicle_id)
    # The same history, except that the vehicle crept instead of standing still.
    rolled = []
    for state in _states()[: second + 1]:
        copied = copy.deepcopy(state)
        vehicle = _vehicle(copied, vehicle_id)
        if vehicle["mode"] == "driving" and vehicle["speed_mm_per_s"] == 0:
            vehicle["speed_mm_per_s"] = 1
        rolled.append(copied)
    rolling = _observed_through(second, rolled)
    assert "did_not_stop" in _kinds(rolling.grant_rules(rolled[second], after), vehicle_id)


def _minor_grant():
    network, _ = fixture()
    for grant in _grants_at("priority"):
        junction = network.junctions[grant["target"]]
        before = _states()[grant["second"]]
        vehicle = _vehicle(before, grant["vehicle_id"])
        lane = vehicle["route"][vehicle["route_index"]]
        if junction.approach_of_lane(lane).control == "stop":
            return grant, junction
    raise AssertionError("no minor-approach grant at a priority junction")


def _conflicting_major_movement(junction: JunctionSpec, connector: str) -> tuple[str, str]:
    network, _ = fixture()
    conflicts = set(junction.conflicts) | {(b, a) for a, b in junction.conflicts}
    ranks = min(approach.rank for approach in junction.approaches)
    for approach in junction.approaches:
        if approach.rank != ranks:
            continue
        for lane in approach.inbound_lanes:
            for other in network.paths[lane].successors:
                if (connector, other) in conflicts:
                    return lane, other
    raise AssertionError("no conflicting major movement")


def test_admitting_a_minor_movement_ahead_of_close_priority_traffic_is_caught():
    network, _ = fixture()
    grant, junction = _minor_grant()
    vehicle_id, second = grant["vehicle_id"], grant["second"]
    lane, other = _conflicting_major_movement(junction, grant["connector"])
    length = network.paths[lane].length
    checker = _observed_through(second)
    base_before = _without_lane(_states()[second], lane)
    base_after = _without_lane(_states()[second + 1], lane)
    template = base_before["vehicles"][0]

    def violations(position: int, speed: int) -> set[str]:
        planted = _planted_vehicle(template, lane, other, position, speed)
        before = copy.deepcopy(base_before)
        after = copy.deepcopy(base_after)
        before["vehicles"].append(planted)
        after["vehicles"].append(copy.deepcopy(planted))
        return {
            violation.kind
            for violation in checker.grant_rules(before, after)
            if violation.vehicles == (vehicle_id, planted["id"])
        }

    # Five metres from its line at 5 m/s: it reaches the junction well inside the headway.
    assert violations(length - 5_000, 5_000) == {"gap_not_given"}
    # Standing at the start of a long lane: nowhere near.
    assert violations(0, 0) == set()
    # Standing at its own line and still waiting: it is not approaching, so it is not refused.
    assert violations(length, 0) == set()


def _all_way_case(tie: bool):
    """A grant at an all-way stop, the second its vehicle stopped, and a lane to plant on."""
    network, _ = fixture()
    for grant in _grants_at("all_way_stop"):
        second = grant["second"]
        junction = network.junctions[grant["target"]]
        vehicle = _vehicle(_states()[second], grant["vehicle_id"])
        own_lane = vehicle["route"][vehicle["route_index"]]
        stop = _observed_through(second).stops.get(grant["vehicle_id"])
        if stop is None or stop[2] < 2:
            continue
        own = junction.approach_of_lane(own_lane).direction
        conflicts = set(junction.conflicts) | {(b, a) for a, b in junction.conflicts}
        for approach in junction.approaches:
            if own_lane in approach.inbound_lanes:
                continue
            on_right = own[0] * approach.direction[1] - own[1] * approach.direction[0] > 0
            if tie and not on_right:
                continue
            for lane in approach.inbound_lanes:
                for other in network.paths[lane].successors:
                    if (grant["connector"], other) in conflicts:
                        return grant, stop[2], lane, other
    raise AssertionError("no suitable all-way stop grant")


def _with_waiting_vehicle(lane: str, connector: str, from_second: int, through: int):
    network, _ = fixture()
    length = network.paths[lane].length
    states = [copy.deepcopy(state) for state in _states()[: through + 2]]
    template = states[0]["vehicles"][0]
    planted = _planted_vehicle(template, lane, connector, length, 0)
    for index in range(from_second, through + 2):
        states[index] = _without_lane(states[index], lane)
        states[index]["vehicles"].append(copy.deepcopy(planted))
    return states, planted["id"]


def test_admitting_a_vehicle_before_one_that_stopped_first_is_caught():
    grant, stopped, lane, other = _all_way_case(tie=False)
    vehicle_id, second = grant["vehicle_id"], grant["second"]
    for from_second, expected in ((stopped - 1, True), (stopped + 1, False)):
        states, planted = _with_waiting_vehicle(lane, other, from_second, second)
        checker = _observed_through(second, states)
        found = [
            violation
            for violation in checker.grant_rules(states[second], states[second + 1])
            if violation.kind == "all_way_order"
        ]
        assert bool(found) == expected, (from_second, stopped, found)
        if expected:
            assert found[0].vehicles == (vehicle_id, planted)


def test_a_same_second_tie_that_went_to_the_vehicle_on_the_left_is_caught():
    grant, stopped, lane, other = _all_way_case(tie=True)
    vehicle_id, second = grant["vehicle_id"], grant["second"]
    states, _ = _with_waiting_vehicle(lane, other, stopped, second)
    checker = _observed_through(second, states)
    found = [
        violation
        for violation in checker.grant_rules(states[second], states[second + 1])
        if violation.kind == "all_way_order"
    ]
    assert [violation.vehicles for violation in found] == [(vehicle_id,)]


# ---------------------------------------------------------------------------------------------
# Crossings


def _over_the_crosswalk() -> tuple[str, str, int]:
    """A vehicle, a crosswalk and a second in which the body passes over its centre line.

    Found from positions alone: the gate sits where the widest class's corridor first meets the
    band, so the second a gate is crossed a narrower body may not have reached the paint yet.
    """
    network, catalogs = fixture()
    for event in _events("crossing_entered"):
        band = network.bands[event["band"]]
        vehicle_id = event["vehicle_id"]
        length = catalogs.vehicle_class(
            _vehicle(_states()[event["second"]], vehicle_id)["vehicle_class"]
        ).length_mm
        for second in range(event["second"], min(event["second"] + 30, len(_states()) - 1)):
            before = _vehicle(_states()[second], vehicle_id)
            after = _vehicle(_states()[second + 1], vehicle_id)
            if before["mode"] != "driving" or after["route"] != before["route"]:
                break
            path = before["route"][before["route_index"]]
            if after["route_index"] != before["route_index"]:
                break
            for band_path, low, high in band.intervals:
                centre = (low + high) // 2
                rear, front = before["position_mm"] - length, after["position_mm"]
                if band_path == path and rear < centre <= front:
                    return vehicle_id, event["crossing"], second
    raise AssertionError("no vehicle was seen passing over a crosswalk")


def test_sweeping_over_a_crosswalk_a_pedestrian_is_on_is_caught():
    vehicle_id, crossing, second = _over_the_crosswalk()
    before, after = _states()[second], _states()[second + 1]

    def conflicts(arrival: int) -> set[str]:
        walker = CrossingEntry(crossing, arrival, 5, "planted pedestrian")
        inputs = TrafficInputs(trips=(), feeds=(CrossingFeed(1, second + 100, (walker,)),))
        return _kinds(_checker(inputs).crossings(before, after), vehicle_id)

    assert conflicts(second) == {"crossing_conflict"}
    # Arriving just as the second ends still counts; arriving later does not.
    assert conflicts(second + 1) == {"crossing_conflict"}
    assert conflicts(second + 2) == set()
    assert _kinds(_checker().crossings(before, after), vehicle_id) == set()
