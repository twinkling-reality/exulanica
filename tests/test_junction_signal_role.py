"""A signal role's data and pure green extension stay inside the fixed plan's safety intervals."""

from __future__ import annotations

import uuid

import pytest
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.signal_actuation import SignalTimeline, signal_actuation
from exulanica.traffic.signals import interval_index
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import role_request, validate_role_request


@pytest.fixture
def plan():
    policy = signal_actuation()
    return load_traffic_catalogs().plan(policy.plan)


def test_no_sealed_choice_replays_the_fixed_plan_byte_for_byte(plan):
    policy = signal_actuation()
    timeline = SignalTimeline(plan, 0, 0, 1260, {}, policy)
    assert [timeline.index_at(second) for second in range(1260)] == [
        interval_index(plan, 0, second) for second in range(1260)
    ]


def test_a_keep_extends_only_the_current_green_and_keeps_amber_and_all_red(plan):
    policy = signal_actuation()
    kept = {second: "keep" for second in range(24, 24 + policy.green_extension_seconds_maximum)}
    timeline = SignalTimeline(plan, 0, 0, 1260, kept, policy)
    assert [timeline.index_at(second) for second in range(23, 43)] == (
        [1] + [8] * policy.green_extension_seconds_maximum + [2] * 4 + [3] * 2 + [4]
    )
    assert timeline.vehicle_indication(35, "phase_a") == "green"
    assert timeline.vehicle_indication(36, "phase_a") == "amber"
    assert timeline.vehicle_indication(40, "phase_a") == "red"
    assert timeline.vehicle_indication(42, "phase_b") == "green"
    assert timeline.pedestrian_indication(35, "walk_a") == "dont_walk"


def test_a_choice_outside_a_reachable_green_point_is_refused(plan):
    policy = signal_actuation()
    with pytest.raises(ValueError, match="reachable green choice point"):
        SignalTimeline(plan, 0, 0, 1260, {25: "keep"}, policy)
    with pytest.raises(ValueError, match="reachable green choice point"):
        SignalTimeline(plan, 0, 0, 1260, {24: "switch", 25: "keep"}, policy)
    with pytest.raises(ValueError, match="keep or switch"):
        SignalTimeline(plan, 0, 0, 1260, {24: "skip"}, policy)


def test_the_registered_signal_role_seals_only_a_nearby_vehicle_choice():
    role = decision_roles().role("junction_signal")
    assert role.engines == ()
    contract = role.contract()
    subject = "signal:crossroads"
    state = {
        "branch_id": str(uuid.uuid4()),
        "tick": 24,
        "signals": [subject],
        "choice_points": [subject],
    }
    source = {
        "signal_id": subject,
        "world_id": "world:town",
        "roads_version": "a" * 64,
        "episode": 0,
        "segment": 0,
        "choice_generation": 1,
        "choice_second": 24,
        "state_sha256": "b" * 64,
        "observation": {
            "near_vehicle_count": 2,
            "active_near": 1,
            "other_near": 1,
            "active_wait_seconds": 3,
            "other_wait_seconds": 9,
            "green_elapsed_seconds": 24,
        },
        "input_seq": 1,
        "document_sha256": "c" * 64,
    }
    provider = {
        "provider": "nebius",
        "model_id": "chosen",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "d" * 64,
        "prompt_version": role.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    request, status = role_request(
        role,
        state,
        source,
        subject,
        request_id=uuid.uuid4(),
        contract=contract,
        seed="0" * 64,
        provider_config=provider,
    )
    assert status == "in_progress" and request is not None
    validate_role_request(role, request)
    assert [item["kind"] for item in request["context"]["options"]] == ["switch", "keep"]
    source["observation"]["near_vehicle_count"] = 0
    absent, reason = role_request(
        role,
        state,
        source,
        subject,
        request_id=uuid.uuid4(),
        contract=contract,
        seed="0" * 64,
        provider_config=provider,
    )
    assert absent is None and reason == "nothing_to_choose"


def test_the_step_and_the_served_codes_use_the_same_sealed_extension():
    from exulanica.traffic.inputs import CrossingFeed, TrafficInputs
    from exulanica.traffic.presentation import signal_codes
    from exulanica.traffic.simulation import advance_traffic, initial_traffic
    from traffic_scenarios import fixture, seed_for, traffic_id_for

    network, catalogs = fixture()
    signal = next(j.signal for j in network.junctions.values() if j.signal is not None)
    assert signal is not None
    timeline = SignalTimeline(
        catalogs.plan(signal.plan), signal.offset_s, 0, 1260, {24: "keep"}, signal_actuation()
    )
    timelines = {signal.identity: timeline}
    seed = seed_for("actuated")
    state = initial_traffic(
        traffic_id_for("actuated"), seed, network, catalogs, {"passenger_car": 1}
    )
    inputs = TrafficInputs(trips=(), feeds=(CrossingFeed(1, 1300, ()),))
    for _ in range(25):
        step = advance_traffic(
            state, seed, network, catalogs, inputs, signal_timelines=timelines
        )
        state = step.state
    changes = [event["document"] for event in step.events if event["document"]["kind"] == "signal_interval"]
    assert any(event["interval"] == 8 for event in changes)
    heads = [j.signal for j in sorted(network.junctions.values(), key=lambda j: j.identity) if j.signal]
    index = next(index for index, item in enumerate(heads) if item.identity == signal.identity)
    groups = catalogs.plan(signal.plan).groups
    codes = signal_codes(network, catalogs, 24, signal_timelines=timelines)[index]
    assert codes[next(i for i, group in enumerate(groups) if group.key == "phase_a")] == 0
    assert codes[next(i for i, group in enumerate(groups) if group.key == "walk_a")] == 2
