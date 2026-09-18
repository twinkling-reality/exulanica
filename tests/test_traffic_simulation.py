"""The traffic simulation: property runs, replay, blocked trips, inputs, presentation and metrics.

**Property runs.** A busy fleet on the synthetic network, with pedestrians crossing every
crosswalk about once a minute whatever the signals show. New trips are requested for 15 simulated
minutes, and the run then drains until every trip has arrived or been recorded as blocked, for at
most an hour. Every transition is checked by ``TransitionChecker``, written apart from the step,
and the tests require: no overlap, no entry without a reservation, none on red, none without
stopping, no gap refused to priority traffic, all-way stop order kept, no vehicle in a crossing a
pedestrian is on, no vehicle over its speed cap, no internal breach recorded, and every trip
either arrived or recorded as blocked with its reason, before the hour is out.

**Replay.** The recorded inputs alone reproduce every receipt, event and state byte for byte, in
this process and in a new one under another hash seed.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import os
import subprocess
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.roads import LaneConnectionRecord, LaneRecord, SignalRecord
from exulanica.traffic.checks import TransitionChecker
from exulanica.traffic.city_roads import road_input_from_city
from exulanica.traffic.errors import InvalidTrafficInputError, InvalidTrafficStateError
from exulanica.traffic.inputs import (
    LOOKAHEAD_S,
    CrossingEntry,
    CrossingFeed,
    TrafficInputs,
    TripRequest,
    feed_from_society_crossings,
)
from exulanica.traffic.metrics import METRICS_PROFILE, MetricsAccumulator
from exulanica.traffic.network import compile_network
from exulanica.traffic.presentation import PRESENTATION_PROFILE, presentation_frame
from exulanica.traffic.simulation import (
    STALL_LIMIT_S,
    TRAFFIC_NAMESPACE,
    advance_traffic,
    initial_traffic,
    state_sha256,
    vehicle_id,
)

from traffic_network_fixture import CITY, build_records, identity
from traffic_scenarios import (
    BUSY_FLEET,
    FLEET,
    AdaptiveRun,
    Scenario,
    build_scenario,
    fixture,
    run,
    run_adaptive,
    seed_for,
    traffic_id_for,
)

ROOT = Path(__file__).resolve().parents[1]
DEMAND_S = 900
#: The fixed-demand runs' length, and the cap on a busy run's drain.
RUN_S = 1_800
DRAIN_CAP_S = 3_600
BUSY_PEDESTRIAN_SPACING_S = 45
PROPERTY_LABELS = ("busy-1", "busy-2", "busy-3", "busy-4", "busy-5", "busy-6")


def _speed_caps_hold(state) -> list[str]:
    network, catalogs = fixture()
    problems = []
    for vehicle in state["vehicles"]:
        if vehicle["mode"] != "driving":
            continue
        path = network.paths[vehicle["route"][vehicle["route_index"]]]
        vehicle_class = catalogs.vehicle_class(vehicle["vehicle_class"])
        cap = min(path.speed_limit_mm_per_s, vehicle_class.speed_cap_mm_per_s)
        if path.is_turn:
            cap = min(cap, vehicle_class.turning_speed_mm_per_s)
        if vehicle["speed_mm_per_s"] > cap:
            problems.append(f"{vehicle['id']} at {vehicle['speed_mm_per_s']} over {cap}")
    return problems


@dataclass
class CheckedRun:
    result: AdaptiveRun
    violations: list
    over_cap: list[str]
    metrics: dict
    #: Space-seconds a parked vehicle stood in each group of spaces, counted here independently.
    parked_seconds: Counter


@cache
def _checked_busy_run(label: str) -> CheckedRun:
    """A busy adaptive run with every transition checked and measured; cached per process."""
    network, catalogs = fixture()
    feeds = build_scenario(
        label,
        demand_seconds=0,
        run_seconds=DRAIN_CAP_S,
        fleet=BUSY_FLEET,
        pedestrian_spacing_s=BUSY_PEDESTRIAN_SPACING_S,
    ).inputs
    checker = TransitionChecker(network, catalogs, feeds)
    metrics = MetricsAccumulator(network)
    violations: list = []
    over_cap: list[str] = []
    parked_seconds: Counter = Counter()

    def observe(before, step):
        violations.extend(checker.check(before, step.state))
        over_cap.extend(_speed_caps_hold(step.state))
        metrics.observe(step.state, step.events)
        parked_seconds.update(
            network.spaces[vehicle["space"]].kind
            for vehicle in step.state["vehicles"]
            if vehicle["mode"] == "parked"
        )

    result = run_adaptive(
        label,
        demand_seconds=DEMAND_S,
        run_seconds=DRAIN_CAP_S,
        fleet=BUSY_FLEET,
        pedestrian_spacing_s=BUSY_PEDESTRIAN_SPACING_S,
        observer=observe,
        until_settled=True,
    )
    assert result.inputs.feeds == feeds.feeds
    return CheckedRun(result, violations, over_cap, metrics.report(result.state), parked_seconds)


def _documents(events, kind: str) -> list[dict]:
    return [event["document"] for event in events if event["document"]["kind"] == kind]


# ---------------------------------------------------------------------------------------------
# Property runs


@pytest.mark.parametrize("label", PROPERTY_LABELS)
def test_a_busy_run_keeps_every_rule_and_every_trip_ends_arrived_or_blocked(label):
    checked = _checked_busy_run(label)
    result = checked.result
    assert checked.violations == [], checked.violations[:5]
    assert checked.over_cap == [], checked.over_cap[:5]
    assert [breach for receipt in result.receipts for breach in receipt["breaches"]] == []
    trips = result.state["trips"]
    assert len(trips) >= 50
    assert result.state["second"] < DRAIN_CAP_S, "the run did not settle within the cap"
    statuses = Counter(trip["status"] for trip in trips)
    assert set(statuses) <= {"arrived", "blocked"}, statuses
    assert all(trip["reason"] for trip in trips if trip["status"] == "blocked")
    # The run must have exercised what it claims to check.
    network, catalogs = fixture()
    # Every vehicle class the catalogs hold drove in this run. The coverage is read from the
    # catalogs, not from the fleet in traffic_scenarios.py, so a class added there later cannot
    # ride along unexercised while these runs still pass.
    of_vehicle = {vehicle["id"]: vehicle["vehicle_class"] for vehicle in result.state["vehicles"]}
    drove = {
        of_vehicle[event["vehicle_id"]] for event in _documents(result.events, "trip_departed")
    }
    assert drove == {entry.key for entry in catalogs.vehicle_classes}, sorted(drove)
    entered = Counter(event["junction"] for event in _documents(result.events, "junction_entered"))
    assert set(entered) == set(network.junctions), entered
    assert _documents(result.events, "crossing_entered")
    assert len(_documents(result.events, "trip_arrived")) >= 50
    rules = Counter(
        grant["facts"]["rule"] for grant in _documents(result.events, "reservation_granted")
    )
    assert {"signal", "priority", "all_way_stop", "crossing"} <= set(rules), rules
    crossed = {entry.crossing_id for feed in result.inputs.feeds for entry in feed.entries}
    assert crossed == {band.society_crossing_id for band in network.bands}


@pytest.mark.parametrize("label", PROPERTY_LABELS[:2])
def test_the_metrics_report_accounts_for_every_entry_space_second_and_trip(label):
    network, _ = fixture()
    checked = _checked_busy_run(label)
    result, report = checked.result, checked.metrics
    seconds = len(result.receipts)
    assert report["profile"] == METRICS_PROFILE and report["seconds"] == seconds
    entered = Counter(event["junction"] for event in _documents(result.events, "junction_entered"))
    delays = Counter()
    for event in _documents(result.events, "junction_entered"):
        delays[event["junction"]] += event["delay_ms"]
    for row in report["junctions"]:
        assert row["entries"] == entered[row["junction"]] > 0
        assert row["entries_per_hour"] == row["entries"] * 3600 // seconds
        assert row["mean_delay_ms"] == delays[row["junction"]] // row["entries"]
    spaces = Counter(space.kind for space in network.spaces.values())
    places = Counter()
    for space in network.spaces.values():
        places[space.kind] += space.capacity
    assert [row["kind"] for row in report["parking"]] == sorted(spaces)
    for row in report["parking"]:
        kind = row["kind"]
        assert (row["spaces"], row["places"]) == (spaces[kind], places[kind])
        expected = checked.parked_seconds[kind] * 1_000_000 // (places[kind] * seconds)
        assert row["occupancy_ppm"] == expected
        assert 0 < row["occupancy_ppm"] <= 1_000_000
    trips = report["trips"]
    assert trips["requested"] == trips["arrived"] + trips["blocked"] + trips["in_progress"]
    assert trips["requested"] == len(result.inputs.trips)
    assert trips["mean_door_to_door_s"] > 0


@pytest.mark.parametrize("label", ("fixed-1", "fixed-2"))
def test_fixed_demand_that_cannot_always_be_met_ends_every_trip_with_a_reason(label):
    network, catalogs = fixture()
    scenario = build_scenario(label, demand_seconds=DEMAND_S, run_seconds=RUN_S, fleet=FLEET)
    checker = TransitionChecker(network, catalogs, scenario.inputs)
    violations = []
    state, _, receipts = run(
        scenario, observer=lambda before, step: violations.extend(checker.check(before, step.state))
    )
    assert violations == []
    assert [breach for receipt in receipts for breach in receipt["breaches"]] == []
    statuses = Counter(trip["status"] for trip in state["trips"])
    assert set(statuses) <= {"arrived", "blocked"}, statuses
    assert statuses["arrived"] > 0
    reasons = Counter(trip["reason"] for trip in state["trips"] if trip["status"] == "blocked")
    assert all(reasons), reasons
    assert len(state["trips"]) == len(scenario.inputs.trips)


# ---------------------------------------------------------------------------------------------
# Replay

_REPLAY = r"""
import hashlib, sys
sys.path.insert(0, "tests")
import exulanica.traffic
from exulanica.canonical import canonical_json
from traffic_scenarios import BUSY_FLEET, run_adaptive
label, demand, total, spacing = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
result = run_adaptive(label, demand_seconds=demand, run_seconds=total, fleet=BUSY_FLEET,
                      pedestrian_spacing_s=spacing)
print(exulanica.traffic.__file__)
print(hashlib.sha256(canonical_json(result.receipts)).hexdigest())
print(hashlib.sha256(canonical_json([event["document"] for event in result.events])).hexdigest())
print(hashlib.sha256(canonical_json(result.state)).hexdigest())
"""

REPLAY_LABEL = "replay"
REPLAY_DEMAND_S = 600
REPLAY_RUN_S = 1_200


@cache
def _replay_source() -> AdaptiveRun:
    return run_adaptive(
        REPLAY_LABEL,
        demand_seconds=REPLAY_DEMAND_S,
        run_seconds=REPLAY_RUN_S,
        fleet=BUSY_FLEET,
        pedestrian_spacing_s=BUSY_PEDESTRIAN_SPACING_S,
        keep_states=True,
    )


def test_the_recorded_inputs_alone_replay_every_byte():
    source = _replay_source()
    assert len(source.inputs.trips) > 20
    scenario = source.scenario
    replay = Scenario(
        scenario.label,
        scenario.seed,
        scenario.traffic_id,
        REPLAY_DEMAND_S,
        REPLAY_RUN_S,
        source.inputs,
        copy.deepcopy(scenario.initial),
    )
    state, events, receipts = run(replay)
    assert canonical_json(receipts) == canonical_json(source.receipts)
    assert canonical_json(events) == canonical_json(source.events)
    assert canonical_json(state) == canonical_json(source.state)


def test_a_new_process_under_other_hash_seeds_reproduces_the_run():
    source = _replay_source()
    expected = [
        hashlib.sha256(canonical_json(source.receipts)).hexdigest(),
        hashlib.sha256(canonical_json([event["document"] for event in source.events])).hexdigest(),
        hashlib.sha256(canonical_json(source.state)).hexdigest(),
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _REPLAY,
            REPLAY_LABEL,
            str(REPLAY_DEMAND_S),
            str(REPLAY_RUN_S),
            str(BUSY_PEDESTRIAN_SPACING_S),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTHONHASHSEED": "4294967295"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    module_path, *digests = result.stdout.split()
    # A child that imported another checkout's package would measure the wrong code.
    assert Path(module_path).resolve().is_relative_to(ROOT), module_path
    assert digests == expected


def test_receipts_chain_states_and_name_every_event_by_its_digest():
    source = _replay_source()
    previous = state_sha256(source.scenario.initial)
    events = iter(source.events)
    for second, receipt in enumerate(source.receipts):
        assert receipt["profile"] == "exulanica.traffic-transition/v1"
        assert (receipt["from_second"], receipt["to_second"]) == (second, second + 1)
        assert receipt["previous_state_sha256"] == previous
        previous = receipt["state_sha256"]
        documents = []
        for order, event_id in enumerate(receipt["event_ids"]):
            event = next(events)
            document = event["document"]
            assert (document["order"], document["synthetic"]) == (order, True)
            # Decisions made at the start of a second carry it; what is true once the vehicles
            # have moved (arrivals, stalls) carries the next one.
            assert document["second"] in (second, second + 1)
            digest = hashlib.sha256(canonical_json(document)).hexdigest()
            assert event["document_sha256"] == digest
            assert (
                event_id
                == event["event_id"]
                == str(
                    uuid.uuid5(
                        TRAFFIC_NAMESPACE, f"{receipt['traffic_id']}:{second}:{order}:{digest}"
                    )
                )
            )
            documents.append(document)
        assert receipt["events_sha256"] == hashlib.sha256(canonical_json(documents)).hexdigest()
    assert previous == state_sha256(source.state)
    assert next(events, None) is None


def test_a_step_does_not_change_the_state_it_is_given():
    network, catalogs = fixture()
    scenario = build_scenario("pure", demand_seconds=120, run_seconds=200, fleet=FLEET)
    state = scenario.initial
    for _ in range(150):
        frozen = copy.deepcopy(state)
        step = advance_traffic(state, scenario.seed, network, catalogs, scenario.inputs)
        assert state == frozen
        again = advance_traffic(frozen, scenario.seed, network, catalogs, scenario.inputs)
        assert canonical_json(again.receipt) == canonical_json(step.receipt)
        state = step.state


# ---------------------------------------------------------------------------------------------
# Blocked trips and their reasons


def _space(segment: int, side: str, index: int) -> str:
    segment_id = identity("street_segment", CITY, segment)
    curb = identity("curb_edge", segment_id, 1 if side == "right" else 0)
    return identity("parking_space", curb, index)


def _feed_through(second: int, entries=()) -> tuple[CrossingFeed, ...]:
    return (CrossingFeed(1, second, tuple(entries)),)


def _request(seq, vehicle, destination, *, second=0, kind="space", segment=-1):
    return TripRequest(
        request_seq=seq,
        trip_id=f"trip-{seq}",
        vehicle_id=vehicle,
        depart_second=second,
        destination_kind=kind,
        destination=destination,
        street_segment_ordinal=segment,
        source="test request",
    )


def test_a_trip_that_cannot_start_is_blocked_at_once_with_its_reason():
    network, catalogs = fixture()
    seed, traffic_id = seed_for("reasons"), traffic_id_for("reasons")
    state = initial_traffic(traffic_id, seed, network, catalogs, {"bicycle": 1, "passenger_car": 3})
    cars = [vehicle for vehicle in state["vehicles"] if vehicle["vehicle_class"] == "passenger_car"]
    [bicycle] = [vehicle for vehicle in state["vehicles"] if vehicle["vehicle_class"] == "bicycle"]
    taken = {vehicle["space"] for vehicle in state["vehicles"]}
    free_car_spaces = [
        space.identity
        for space in network.spaces.values()
        if "passenger_car" in space.classes and space.identity not in taken
    ]
    bus_space = next(space for space in network.spaces.values() if space.classes == ("city_bus",))
    first, second, third = cars
    requests = (
        _request(1, str(uuid.uuid5(TRAFFIC_NAMESPACE, "nobody")), free_car_spaces[0]),
        _request(2, first["id"], free_car_spaces[0]),
        _request(3, first["id"], free_car_spaces[1]),
        _request(4, second["id"], "not-a-space"),
        _request(5, bicycle["id"], bus_space.identity),
        _request(6, second["id"], third["space"]),
        _request(7, second["id"], free_car_spaces[0]),
        _request(8, second["id"], "a ring street", kind="frontage", segment=4),
    )
    inputs = TrafficInputs(trips=requests, feeds=_feed_through(LOOKAHEAD_S + 5))
    step = advance_traffic(state, seed, network, catalogs, inputs)
    trips = {trip["trip_id"]: trip for trip in step.state["trips"]}
    assert {trip_id: trip["reason"] for trip_id, trip in trips.items()} == {
        "trip-1": "unknown_vehicle",
        "trip-2": "",
        "trip-3": "vehicle_busy",
        "trip-4": "unknown_space",
        "trip-5": "space_does_not_fit_class",
        "trip-6": "destination_space_taken",
        "trip-7": "destination_space_taken",
        "trip-8": "no_parking_at_destination",
    }
    assert trips["trip-2"]["status"] == "waiting"
    blocked = [
        event["document"] for event in step.events if event["document"]["kind"] == "trip_blocked"
    ]
    assert [event["trip_id"] for event in blocked] == [f"trip-{n}" for n in (1, 3, 4, 5, 6, 7, 8)]


def test_a_destination_no_route_reaches_is_blocked_as_no_route():
    fixture_network, catalogs = fixture()
    seed, traffic_id = seed_for("no-route"), traffic_id_for("no-route")
    placed = initial_traffic(traffic_id, seed, fixture_network, catalogs, {"passenger_car": 1})
    [placed_car] = placed["vehicles"]
    # Cut every movement into the outbound lane of the next spoke round from the car's.
    here = fixture_network.segment_ordinals[fixture_network.spaces[placed_car["space"]].segment]
    target_segment = identity("street_segment", CITY, (here + 1) % 4)
    base = build_records()
    [target_lane] = [
        record
        for record in base
        if type(record) is LaneRecord
        and record.segment_identity == target_segment
        and record.direction == "forward"
    ]
    cut = {
        record.identity
        for record in base
        if type(record) is LaneConnectionRecord and record.to_lane_identity == target_lane.identity
    }
    assert len(cut) == 3
    records = []
    for record in base:
        if type(record) is LaneConnectionRecord and record.identity in cut:
            continue
        if type(record) is SignalRecord:
            record = dataclasses.replace(
                record,
                groups=tuple(
                    dataclasses.replace(
                        group,
                        connection_identities=tuple(
                            item for item in group.connection_identities if item not in cut
                        ),
                    )
                    for group in record.groups
                ),
                heads=tuple(head for head in record.heads if head.serves_identity not in cut),
            )
        records.append(record)
    network = compile_network(road_input_from_city(records, catalogs, city_identity=CITY), catalogs)
    target_path = f"lane:{target_lane.identity}"
    assert network.paths[target_path].predecessors == ()
    state = initial_traffic(traffic_id, seed, network, catalogs, {"passenger_car": 1})
    [car] = state["vehicles"]
    # The spaces did not change, so the seeded fleet stands where it stood on the fixture.
    assert car["space"] == placed_car["space"]
    assert network.spaces[car["space"]].access_path != target_path
    goal = next(
        space
        for space in network.spaces.values()
        if space.access_path == target_path and "passenger_car" in space.classes
    )
    inputs = TrafficInputs(
        trips=(_request(1, car["id"], goal.identity),), feeds=_feed_through(LOOKAHEAD_S + 5)
    )
    step = advance_traffic(state, seed, network, catalogs, inputs)
    [trip] = step.state["trips"]
    assert (trip["status"], trip["reason"]) == ("blocked", "no_route")


def test_a_vehicle_held_at_a_crosswalk_is_blocked_with_the_reason_then_arrives():
    """A pedestrian on a mid-block crossing for 700 s: the car waits, is recorded, then goes."""
    network, catalogs = fixture()
    seed, traffic_id = seed_for("held"), traffic_id_for("held")
    state = initial_traffic(traffic_id, seed, network, catalogs, {"passenger_car": 1})
    [car] = state["vehicles"]
    # The accessible bay on the spoke's right side lies beyond its mid-block crossing.
    goal = _space(0, "right", 4)
    if car["space"] == goal:
        goal = _space(1, "right", 4)
    assert network.spaces[goal].kind == "accessible"
    band = next(
        band
        for band in network.bands
        if band.junction is None
        and any(path == network.spaces[goal].access_path for path, _, _ in band.intervals)
    )
    total = 1_200
    pedestrian = CrossingEntry(band.society_crossing_id, 0, 700, "a long crossing")
    inputs = TrafficInputs(
        trips=(_request(1, car["id"], goal),),
        feeds=_feed_through(total + LOOKAHEAD_S, [pedestrian]),
    )
    checker = TransitionChecker(network, catalogs, inputs)
    events = []
    for _ in range(total):
        step = advance_traffic(state, seed, network, catalogs, inputs)
        assert checker.check(state, step.state) == []
        events += [event["document"] for event in step.events]
        state = step.state
    by_kind = {}
    for event in events:
        by_kind.setdefault(event["kind"], []).append(event)
    [blocked] = by_kind["trip_blocked"]
    assert blocked["reason"] == "pedestrian_due"
    assert blocked["second"] - blocked["waiting_since"] >= STALL_LIMIT_S
    [unblocked] = by_kind["trip_unblocked"]
    [entered] = [
        event
        for event in by_kind["crossing_entered"]
        if event["crossing"] == band.society_crossing_id
    ]
    # The vehicle enters the band only after the pedestrian's last second, 0 + 700, and the trip
    # is unblocked once it has moved, stamped with the second after it started.
    assert entered["second"] > 700
    assert blocked["second"] < entered["second"]
    assert unblocked["second"] in (entered["second"], entered["second"] + 1)
    [arrived] = by_kind["trip_arrived"]
    assert arrived["space"] == goal
    [trip] = state["trips"]
    assert (trip["status"], trip["reason"]) == ("arrived", "")


# ---------------------------------------------------------------------------------------------
# Inputs


def test_trip_requests_refuse_malformed_fields():
    good = dict(
        request_seq=1,
        trip_id="t",
        vehicle_id="v",
        depart_second=0,
        destination_kind="space",
        destination="s",
        street_segment_ordinal=-1,
        source="test",
    )
    TripRequest(**good)
    for change, message in (
        ({"request_seq": 0}, "request_seq"),
        ({"trip_id": ""}, "trip_id"),
        ({"depart_second": -1}, "depart_second"),
        ({"destination_kind": "anywhere"}, "destination kind"),
        ({"street_segment_ordinal": 3}, "a space destination carries no segment"),
        ({"destination_kind": "frontage", "street_segment_ordinal": -1}, "street_segment_ordinal"),
        ({"source": " padded"}, "source"),
        ({"depart_second": True}, "depart_second"),
    ):
        with pytest.raises(InvalidTrafficInputError, match=message):
            TripRequest(**{**good, **change})


def test_crossing_feeds_refuse_malformed_or_out_of_order_entries():
    entry = CrossingEntry("crossing:0:52750", 10, 12, "walker")
    assert entry.last_second == 22
    with pytest.raises(InvalidTrafficInputError, match="duration_seconds"):
        CrossingEntry("crossing:0:52750", 10, 0, "walker")
    later = CrossingEntry("crossing:0:16500", 11, 12, "walker")
    with pytest.raises(InvalidTrafficInputError, match="sorted"):
        CrossingFeed(1, 59, (later, entry))
    with pytest.raises(InvalidTrafficInputError, match="after the second the feed covers"):
        CrossingFeed(1, 9, (entry,))
    one = CrossingFeed(1, 59, (entry,))
    with pytest.raises(InvalidTrafficInputError, match="contiguous"):
        TrafficInputs(trips=(), feeds=(CrossingFeed(2, 59, ()),))
    with pytest.raises(InvalidTrafficInputError, match="covers later seconds"):
        TrafficInputs(trips=(), feeds=(one, CrossingFeed(2, 59, ())))
    with pytest.raises(InvalidTrafficInputError, match="an earlier feed covered"):
        TrafficInputs(trips=(), feeds=(one, CrossingFeed(2, 119, (later,))))
    request = _request(2, "v", "s")
    with pytest.raises(InvalidTrafficInputError, match="contiguous from 1"):
        TrafficInputs(trips=(request,), feeds=(one,))
    with pytest.raises(InvalidTrafficInputError, match="a trip id repeats"):
        TrafficInputs(
            trips=(_request(1, "v", "s"), _duplicate_id(_request(2, "w", "s"))), feeds=(one,)
        )


def _duplicate_id(request: TripRequest) -> TripRequest:
    return TripRequest(
        request_seq=request.request_seq,
        trip_id="trip-1",
        vehicle_id=request.vehicle_id,
        depart_second=request.depart_second,
        destination_kind=request.destination_kind,
        destination=request.destination,
        street_segment_ordinal=request.street_segment_ordinal,
        source=request.source,
    )


def test_a_step_refuses_inputs_and_states_it_cannot_trust():
    network, catalogs = fixture()
    scenario = build_scenario("refusals", demand_seconds=60, run_seconds=120, fleet=FLEET)
    state, seed = scenario.initial, scenario.seed
    short = TrafficInputs(trips=(), feeds=_feed_through(LOOKAHEAD_S - 1))
    with pytest.raises(InvalidTrafficInputError, match="needs it to reach 60"):
        advance_traffic(state, seed, network, catalogs, short)
    unknown = TrafficInputs(
        trips=(), feeds=_feed_through(100, [CrossingEntry("crossing:99:1", 5, 3, "nobody")])
    )
    with pytest.raises(InvalidTrafficInputError, match="unknown crossing:99:1"):
        advance_traffic(state, seed, network, catalogs, unknown)
    with pytest.raises(InvalidTrafficStateError, match="not the one this state was started with"):
        advance_traffic(state, seed_for("another"), network, catalogs, scenario.inputs)
    with pytest.raises(InvalidTrafficStateError, match="another network or catalog"):
        advance_traffic(
            {**state, "network_sha256": "0" * 64}, seed, network, catalogs, scenario.inputs
        )
    with pytest.raises(InvalidTrafficStateError, match="unsupported traffic profile"):
        advance_traffic(
            {**state, "profile": "traffic/v0"}, seed, network, catalogs, scenario.inputs
        )
    flying = copy.deepcopy(state)
    flying["vehicles"][0]["mode"] = "flying"
    with pytest.raises(InvalidTrafficStateError, match="unknown vehicle mode"):
        advance_traffic(flying, seed, network, catalogs, scenario.inputs)
    skipped = TrafficInputs(
        trips=(
            _request(1, state["vehicles"][0]["id"], "s", second=3),
            _request(2, state["vehicles"][1]["id"], "s", second=5),
        ),
        feeds=_feed_through(200),
    )
    at_five = {**state, "second": 5}
    with pytest.raises(InvalidTrafficInputError, match="consumed in order"):
        advance_traffic(at_five, seed, network, catalogs, skipped)


def test_initial_traffic_places_a_seeded_fleet_in_spaces_that_fit_it():
    network, catalogs = fixture()
    seed, traffic_id = seed_for("fleet"), traffic_id_for("fleet")
    state = initial_traffic(traffic_id, seed, network, catalogs, BUSY_FLEET)
    assert state == initial_traffic(traffic_id, seed, network, catalogs, dict(BUSY_FLEET))
    assert state != initial_traffic(traffic_id, seed_for("other"), network, catalogs, BUSY_FLEET)
    vehicles = state["vehicles"]
    assert len(vehicles) == sum(BUSY_FLEET.values())
    # A space holds up to its capacity, each vehicle in its own place, taken from 0 upward.
    places = Counter(vehicle["space"] for vehicle in vehicles)
    assert len({(vehicle["space"], vehicle["slot"]) for vehicle in vehicles}) == len(vehicles)
    for space, count in places.items():
        assert count <= network.spaces[space].capacity
        assert sorted(v["slot"] for v in vehicles if v["space"] == space) == list(range(count))
    assert max(places.values()) > 1
    for vehicle in vehicles:
        vehicle_class = catalogs.vehicle_class(vehicle["vehicle_class"])
        assert vehicle["vehicle_class"] in network.spaces[vehicle["space"]].classes
        assert vehicle["body_family"] in vehicle_class.body_families
        assert vehicle["colour"] in vehicle_class.colours
        assert vehicle["id"] == vehicle_id(traffic_id, vehicle["ordinal"])
        assert (vehicle["mode"], vehicle["synthetic"]) == ("parked", True)
    assert [vehicle["id"] for vehicle in vehicles] == sorted(vehicle["id"] for vehicle in vehicles)
    with pytest.raises(InvalidTrafficInputError, match="traffic_id is a UUID"):
        initial_traffic("not-a-uuid", seed, network, catalogs, FLEET)
    with pytest.raises(InvalidTrafficInputError, match="non-negative int"):
        initial_traffic(traffic_id, seed, network, catalogs, {"van": -1})
    with pytest.raises(InvalidTrafficInputError, match="no free space fits another city_bus"):
        initial_traffic(traffic_id, seed, network, catalogs, {"city_bus": 9})


def test_the_society_feed_adapter_turns_walker_crossings_into_absolute_seconds():
    feed = feed_from_society_crossings(
        3,
        "society-a",
        239,
        [
            (
                3,
                7,
                [{"crossing_id": "crossing:0:52750", "arrival_second": 59, "duration_seconds": 12}],
            ),
            (
                2,
                1,
                [{"crossing_id": "crossing:1:16500", "arrival_second": 5, "duration_seconds": 9}],
            ),
            (
                3,
                2,
                [{"crossing_id": "crossing:0:16500", "arrival_second": 59, "duration_seconds": 12}],
            ),
        ],
    )
    assert feed.feed_seq == 3 and feed.covers_through_second == 239
    assert [(entry.arrival_second, entry.crossing_id, entry.source) for entry in feed.entries] == [
        (125, "crossing:1:16500", "society-a:2:1"),
        (239, "crossing:0:16500", "society-a:3:2"),
        (239, "crossing:0:52750", "society-a:3:7"),
    ]
    with pytest.raises(InvalidTrafficInputError, match="exactly three fields"):
        feed_from_society_crossings(
            1, "s", 59, [(0, 0, [{"crossing_id": "c", "arrival_second": 1}])]
        )
    with pytest.raises(InvalidTrafficInputError, match="0 to 59"):
        feed_from_society_crossings(
            1,
            "s",
            200,
            [(0, 0, [{"crossing_id": "c", "arrival_second": 60, "duration_seconds": 5}])],
        )


# ---------------------------------------------------------------------------------------------
# Presentation


def test_the_presentation_frame_is_canonical_and_places_axles_on_the_body():
    network, catalogs = fixture()
    states = _replay_source().states
    assert states is not None
    frames = []
    for before, after in pairwise(states[:401]):
        frame = presentation_frame(after, network, catalogs)
        canonical_json(frame)
        frames.append((before, after, frame))
    checked_driving = checked_parked = 0
    for before, after, frame in frames:
        assert frame["profile"] == "exulanica.traffic-presentation-frame/v1"
        assert frame["second"] == after["second"]
        previous = {vehicle["id"]: vehicle for vehicle in before["vehicles"]}
        for record, vehicle in zip(frame["vehicles"], after["vehicles"], strict=True):
            vehicle_class = catalogs.vehicle_class(record["vehicle_class"])
            assert record["profile"] == PRESENTATION_PROFILE and record["synthetic"] is True
            assert record["dimensions_mm"]["wheelbase"] == vehicle_class.wheelbase_mm
            front, rear = record["front_axle_mm"], record["rear_axle_mm"]
            chord = (front[0] - rear[0]) ** 2 + (front[1] - rear[1]) ** 2
            # On a curve the axles sit on the path, so the chord is at most the wheelbase.
            assert chord <= (vehicle_class.wheelbase_mm + 2) ** 2
            if record["mode"] == "parked":
                space = network.spaces[vehicle["space"]]
                xs, ys = [p[0] for p in space.footprint], [p[1] for p in space.footprint]
                if space.placement == "carriageway":
                    for axle in (front, rear):
                        assert min(xs) <= axle[0] <= max(xs) and min(ys) <= axle[1] <= max(ys)
                else:
                    # At a stand the vehicle stands across the footprint, centred in its place.
                    middle = ((front[0] + rear[0]) // 2, (front[1] + rear[1]) // 2)
                    assert min(xs) <= middle[0] <= max(xs) and min(ys) <= middle[1] <= max(ys)
                    assert 0 <= record["slot"] < space.capacity
                checked_parked += 1
            if record["mode"] == "driving" and previous[vehicle["id"]]["mode"] == "driving":
                path = record["motion_path_mm"]
                old = previous[vehicle["id"]]
                was = network.paths[old["route"][old["route_index"]]].line.point_at(
                    old["position_mm"]
                )
                now = network.paths[vehicle["route"][vehicle["route_index"]]].line.point_at(
                    vehicle["position_mm"]
                )
                assert path[0] == list(was) and path[-1] == list(now)
                checked_driving += 1
    assert checked_driving > 1_000 and checked_parked > 1_000
