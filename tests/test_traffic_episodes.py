"""The traffic host's episodes: the fleet by rule, round trips home, and windows cut from episodes.

An episode is computed whole from one genesis; a window cut from the episodes it spans is exactly
each second's presentation frame; every vehicle that leaves home drives back, and one that is not
home at the episode's end is named. The worker serves the same windows in this process and in its
own.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from exulanica.movement.registry import ROADS, built_module
from exulanica.traffic.presentation import presentation_frame
from exulanica.world import traffic_episodes
from exulanica.world.traffic_episodes import (
    EPISODE,
    MODES,
    TrafficRefused,
    compute_episode,
    from_wire,
    window_of,
    wire,
)
from exulanica.world.traffic_host import TrafficEpisodes, traffic_process_pool

import traffic_corridor_support as corridor

ROADS_MODULE = built_module(ROADS)


@pytest.fixture(scope="module")
def episodes():
    value = corridor.value()
    return {episode: compute_episode(wire(value), episode) for episode in (0, 1)}


def test_the_fleet_is_half_of_each_kinds_places_divided_among_the_classes_it_admits():
    ready = corridor.prepared()
    places: dict[str, int] = {}
    for space in ready.network.spaces.values():
        places[space.kind] = places.get(space.kind, 0) + space.capacity
    share = ROADS_MODULE.value("fleet_share_permille")
    general = places["general"] * share // 1000
    assert ready.fleet == {
        "bicycle": places["cycle_stand"] * share // 1000,
        "passenger_car": general - general // 2,
        "van": general // 2,
    }
    assert "city_bus" not in ready.fleet, "no layover is derived, so no bus has a home"


def test_a_world_hosting_more_vehicles_than_the_bound_is_refused_by_name(monkeypatch):
    monkeypatch.setattr(traffic_episodes, "_MAX_VEHICLES", 10)
    with pytest.raises(TrafficRefused) as refused:
        traffic_episodes._fleet(corridor.prepared().network, corridor.prepared().catalogs)
    assert refused.value.code == "roads_world_too_large"


def test_the_wire_form_rebuilds_the_input_and_refuses_another():
    value = corridor.value()
    assert from_wire(wire(value)) == value
    tampered = {**wire(value), "version_id": "another version"}
    with pytest.raises(ValueError, match="does not rebuild"):
        from_wire(tampered)


def test_an_episode_is_the_same_bytes_computed_again(episodes):
    assert compute_episode(wire(corridor.value()), 1) == episodes[1]


def test_every_vehicle_that_leaves_home_drives_back_and_is_home_when_the_episode_ends(episodes):
    for packed in episodes.values():
        trips = packed.trips
        assert trips["blocked"] == {} and trips["unfinished"] == 0
        assert trips["arrived"] == trips["requested"] and trips["requested"] % 2 == 0
        assert packed.late_home == ()
    assert episodes[0].trips["requested"] >= len(episodes[0].vehicles)


def test_a_window_cut_from_the_episodes_it_spans_is_each_seconds_presentation_frame(episodes):
    value = corridor.value()
    ready = corridor.prepared()
    states = {
        episode: traffic_episodes._home_trip_rule(value, ready, episode)[0] for episode in (0, 1)
    }
    start, seconds = EPISODE - 30, 60
    window = window_of(value, episodes, start, seconds)
    assert window["crossings_fed"] is False
    assert window["from_second"] == start and window["episode_steps"] == EPISODE
    for offset in range(seconds):
        absolute = start + offset
        episode, second = divmod(absolute, EPISODE)
        frame = presentation_frame(states[episode][second], ready.network, ready.catalogs)
        for row, record in zip(window["vehicles"], frame["vehicles"], strict=True):
            assert row["vehicle_id"] == record["vehicle_id"]
            assert row["front_axle_mm"][2 * offset : 2 * offset + 2] == record["front_axle_mm"]
            assert row["rear_axle_mm"][2 * offset : 2 * offset + 2] == record["rear_axle_mm"]
            assert MODES[row["mode"][offset]] == record["mode"]
            assert row["speed_mm_per_s"][offset] == record["speed_mm_per_s"]
            assert row["slot"][offset] == record["slot"]
            flat = [value for point in record["motion_path_mm"] for value in point[:2]]
            assert row["motion_path_mm"][offset] == flat
    # Around an episode's end every vehicle is home; within its first minutes some are driving.
    within = window_of(value, episodes, 150, 60)
    assert any(any(MODES[m] == "driving" for m in row["mode"]) for row in within["vehicles"])


def test_a_window_is_refused_past_a_minute_or_before_the_epoch():
    for from_second, seconds, code in (
        (0, 61, "traffic_window_too_long"),
        (-1, 1, "traffic_second_out_of_range"),
    ):
        with pytest.raises(TrafficRefused) as refused:
            traffic_episodes.check_request(from_second, seconds)
        assert refused.value.code == code


@pytest.mark.parametrize("executor", ["thread", "process"])
def test_the_worker_serves_the_windows_the_episodes_cut(episodes, executor):
    """In this process, and in the spawned worker process a server uses."""
    make = (
        (lambda: ThreadPoolExecutor(max_workers=1))
        if executor == "thread"
        else traffic_process_pool
    )
    worker = TrafficEpisodes(make)
    try:
        value = corridor.value()
        start = EPISODE - 30
        assert worker.window(value, start, 60) == window_of(value, episodes, start, 60)
        assert (
            sorted(worker.held()) == [(value.sha256, 0), (value.sha256, 1)]
            or (
                value.sha256,
                2,
            )
            in [key for key, _ in worker.waiting()] + worker.held()
        )
    finally:
        worker.close()
