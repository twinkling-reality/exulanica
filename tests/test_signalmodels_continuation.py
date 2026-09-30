"""Traffic's bounded worker handoff preserves trips and discovers live signal choice points."""

from __future__ import annotations

import pytest
from exulanica.traffic.signal_actuation import SignalTimeline, signal_actuation
from exulanica.world.traffic_episodes import (
    EPISODE,
    TrafficRefused,
    compute_episode,
    compute_signal_replay,
    home_segment,
    window_of,
    window_of_segments,
    wire,
)

import traffic_corridor_support as corridor


def test_segment_seam_carries_the_whole_trip_rule_and_refuses_changed_state():
    value, ready = corridor.value(), corridor.prepared()
    whole, final, summary, point = home_segment(value, ready, 0, 120)
    assert point is None
    first, seam, _, point = home_segment(value, ready, 0, 60)
    assert point is None and seam["next_second"] == 60
    second, resumed, after, point = home_segment(value, ready, 0, 120, seam)
    assert point is None
    assert first + second == whole
    assert resumed == final and after == summary
    with pytest.raises(TrafficRefused, match="traffic_continuation_changed"):
        home_segment(value, ready, 0, 120, {**seam, "next_second": 61})
    with pytest.raises(TrafficRefused, match="traffic_continuation_changed"):
        home_segment(value, ready, 1, 120, seam)


def test_worker_pauses_at_a_near_vehicle_and_a_recorded_keep_changes_one_second():
    value, ready = corridor.value(), corridor.prepared()
    signal = next(
        junction.signal
        for junction in ready.network.junctions.values()
        if junction.signal is not None
        and junction.signal.identity == "4c2a6323-4ae3-5581-9d67-d681421f0f12"
    )
    assert signal is not None

    def timeline(choices: dict[int, str]) -> SignalTimeline:
        return SignalTimeline(
            ready.catalogs.plan(signal.plan),
            signal.offset_s,
            0,
            1260,
            choices,
            signal_actuation(),
        )

    states, seam, _, point = home_segment(
        value,
        ready,
        0,
        60,
        signal_timelines={signal.identity: timeline({})},
        chosen_signals=(signal.identity,),
    )
    assert point is not None
    assert point["choice_second"] == 24
    assert point["observation"]["near_vehicle_count"] == 1
    assert seam["state"]["second"] == 24 and seam["next_second"] == 25
    assert states[-1] == seam["state"]

    kept, next_seam, _, next_point = home_segment(
        value,
        ready,
        0,
        60,
        seam,
        signal_timelines={signal.identity: timeline({24: "keep"})},
        chosen_signals=(signal.identity,),
    )
    assert kept and kept[0]["second"] == 25
    assert next_point is None and next_seam["next_second"] == 60
    assert timeline({24: "keep"}).vehicle_indication(24, "phase_a") == "green"
    assert timeline({24: "keep"}).vehicle_indication(25, "phase_a") == "amber"
    assert next_seam["signal_choices"] == {signal.identity: {"24": "keep"}}


def test_signal_phase_cursor_keeps_all_red_across_a_segment_and_episode_seam():
    ready = corridor.prepared()
    plan = ready.catalogs.plan(signal_actuation().plan)
    before = SignalTimeline(plan, 0, 0, 1200, {1194: "keep"}, signal_actuation())
    # A keep at the final phase-b choice shifts amber and all-red through the seam.
    assert before.vehicle_indication(1199, "phase_b") == "red"
    after = SignalTimeline(plan, 0, 1200, 60, {}, signal_actuation(), before.cursor_at(1199))
    assert after.vehicle_indication(1200, "phase_a") == "red"
    assert after.vehicle_indication(1201, "phase_a") == "green"


def test_each_fixed_segment_and_the_episode_seam_replays_the_whole_frame_bytes():
    value = corridor.value()
    source = wire(value)
    segments = {}
    whole = {}
    for episode in (0, 1):
        whole[episode] = compute_episode(source, episode)
        continuation = None
        for segment in range(EPISODE // 60):
            packed, continuation, _digest = compute_signal_replay(
                source, episode, segment, continuation, {}, {}
            )
            segments[(episode, segment)] = packed
            start = episode * EPISODE + segment * 60
            served = window_of_segments(value, segments, start, 60)
            fixed = window_of(value, whole, start, 60)
            # A live segment's trip count is through its seal, while a whole episode knows its
            # future final count. Every displayed traffic frame and indication must still match.
            assert {key: row for key, row in served.items() if key != "episodes"} == {
                key: row for key, row in fixed.items() if key != "episodes"
            }
            assert served["episodes"][0]["derivation"] == fixed["episodes"][0]["derivation"]
            if segment == EPISODE // 60 - 1:
                assert served == fixed
    served = window_of_segments(value, segments, EPISODE - 30, 60)
    fixed = window_of(value, whole, EPISODE - 30, 60)
    assert {key: row for key, row in served.items() if key != "episodes"} == {
        key: row for key, row in fixed.items() if key != "episodes"
    }
    assert served["episodes"][0] == fixed["episodes"][0]
