"""Integer kinematics and signal timing, against brute force and by induction over swept states.

The no-collision guarantee along a lane is the braking-envelope rule in
``exulanica.traffic.kinematics``: a follower may only choose a speed from which it could still
stop behind a leader that brakes fully from now on. This file shows the closed forms equal their
brute-force sums, and then shows the induction the rule's docstring claims, on every state of an
integer grid: if the rule held when the speed was chosen, then whatever the leader legally does,
the gap is never less than the minimum and full braking satisfies the rule again next tick.

Signals are a pure function of plan, offset and second; they are checked against an expansion of
the plan into one entry per second.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

import pytest
from exulanica.traffic import signals
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.kinematics import (
    braking_run,
    cap_allows,
    clearing_ticks,
    follows_safely,
    highest_speed,
    reach_ticks,
    stopping_distance,
)
from exulanica.traffic.signals import (
    PEDESTRIAN_INDICATIONS,
    VEHICLE_INDICATIONS,
    interval_index,
    pedestrian_indication,
    seconds_until_red,
    vehicle_indication,
)

DECELERATIONS = (500, 1_200, 1_670, 2_300)


def _braking_sum(speed: int, deceleration: int, ticks: int) -> int:
    return sum(max(0, speed - step * deceleration) for step in range(1, ticks + 1))


@cache
def _braking_sums(speed: int, deceleration: int) -> tuple[int, ...]:
    """``_braking_sum`` for 0 to 60 ticks, added up tick by tick."""
    sums = [0]
    for step in range(1, 61):
        sums.append(sums[-1] + max(0, speed - step * deceleration))
    return tuple(sums)


def _follows_by_sum(
    new_speed: int, deceleration: int, gap: int, distance: int, leader: int, leader_brake: int
) -> bool:
    # Past 60 ticks every vehicle here has long stopped, so both sums are constant.
    own = _braking_sums(new_speed, deceleration)
    other = _braking_sums(leader, leader_brake)
    return all(new_speed + own[ticks] + gap <= distance + other[ticks + 1] for ticks in range(60))


# ---------------------------------------------------------------------------------------------
# Closed forms against sums


def test_the_braking_run_is_the_sum_of_the_braking_ticks():
    for deceleration in DECELERATIONS:
        for speed in range(0, 20_000, 233):
            for ticks in range(0, 45, 4):
                assert braking_run(speed, deceleration, ticks) == _braking_sum(
                    speed, deceleration, ticks
                )
            assert stopping_distance(speed, deceleration) == _braking_sum(speed, deceleration, 60)


def test_the_safety_rule_checks_every_future_tick():
    checked = 0
    for deceleration in (1_200, 1_670):
        for leader_brake in (1_200, 1_670, 2_300):
            for gap in (0, 2_000):
                for new_speed in range(0, 14_000, 1_300):
                    for leader in range(0, 14_000, 1_900):
                        for distance in range(0, 70_000, 2_900):
                            expected = _follows_by_sum(
                                new_speed, deceleration, gap, distance, leader, leader_brake
                            )
                            assert (
                                follows_safely(
                                    new_speed, deceleration, gap, distance, leader, leader_brake
                                )
                                == expected
                            )
                            checked += expected
    assert checked > 5_000


def test_the_safety_rule_is_an_induction_whatever_the_leader_does():
    """If the rule held, the gap holds this tick and full braking keeps the rule next tick."""
    acceleration = 730
    steps = 0
    for deceleration, leader_brake in ((1_670, 1_670), (1_200, 2_300), (2_300, 1_200)):
        for gap in (0, 2_000):
            for leader in range(0, 16_000, 1_450):
                for distance in range(0, 60_000, 1_750):
                    for new_speed in range(0, 16_000, 1_150):
                        if not follows_safely(
                            new_speed, deceleration, gap, distance, leader, leader_brake
                        ):
                            continue
                        lowest = max(0, leader - leader_brake)
                        for leader_new in (lowest, (lowest + leader) // 2, leader + acceleration):
                            after = distance + leader_new - new_speed
                            assert after >= gap, (new_speed, leader, leader_new, distance)
                            braked = max(0, new_speed - deceleration)
                            assert follows_safely(
                                braked, deceleration, gap, after, leader_new, leader_brake
                            ), (new_speed, leader, leader_new, distance, gap)
                            steps += 1
    assert steps > 50_000


def test_a_static_obstacle_is_a_leader_that_never_moves():
    for deceleration in DECELERATIONS:
        for new_speed in range(0, 12_000, 170):
            for distance in range(0, 40_000, 530):
                safe = follows_safely(new_speed, deceleration, 0, distance, 0, 1)
                assert safe == (new_speed + stopping_distance(new_speed, deceleration) <= distance)


def _cap_by_simulation(new_speed: int, deceleration: int, distance: int, cap: int) -> bool:
    speed, position = new_speed, 0
    while speed > cap:
        position += speed
        if position > distance:
            return False
        speed = max(0, speed - deceleration)
    return True


def test_a_cap_ahead_is_met_before_the_front_reaches_it():
    for deceleration in DECELERATIONS:
        for cap in (0, 4_166, 8_333):
            for new_speed in range(0, 14_000, 290):
                for distance in range(0, 45_000, 710):
                    assert cap_allows(new_speed, deceleration, distance, cap) == (
                        _cap_by_simulation(new_speed, deceleration, distance, cap)
                    )


def test_highest_speed_is_the_largest_allowed_speed_of_a_monotone_rule():
    for low in (0, 300, 5_000):
        for high in (0, 299, 5_000, 9_999):
            for threshold in (-1, 0, 299, 300, 4_999, 5_000, 7_777, 20_000):

                def allowed(speed: int, threshold: int = threshold) -> bool:
                    return speed <= threshold

                candidates = [speed for speed in range(low, high + 1) if allowed(speed)]
                expected = max(candidates) if candidates and allowed(low) else None
                assert highest_speed(low, high, allowed) == expected


def test_reach_ticks_counts_a_flat_out_run():
    for speed in (0, 1_000, 8_333):
        for acceleration in (500, 730, 1_000):
            for cap in (4_166, 8_333):
                for distance in range(0, 60_000, 1_130):
                    ticks, covered, current = 0, 0, speed
                    while covered < distance:
                        current = min(current + acceleration, cap)
                        covered += current
                        ticks += 1
                    assert reach_ticks(distance, speed, acceleration, cap) == ticks


def _clearing_by_scan(distance: int, speed: int, acceleration: int, deceleration: int, cap: int):
    covered, ticks = 0, 0
    while covered < distance:
        remaining = distance - covered
        low = max(0, speed - deceleration)
        high = max(low, min(speed + acceleration, cap))
        # Every speed from the top down; the first one that can stop in time is the choice.
        speed = next(
            (
                candidate
                for candidate in range(high, low - 1, -1)
                if candidate + stopping_distance(candidate, deceleration) <= remaining
            ),
            low,
        )
        covered += speed
        ticks += 1
    return ticks


def test_clearing_ticks_is_the_controller_driving_alone_to_its_target():
    for acceleration, deceleration in ((730, 1_670), (1_000, 1_200), (500, 2_300)):
        for cap in (4_166, 8_333):
            for speed in (0, 2_000, 8_333):
                for distance in range(1, 50_000, 3_700):
                    expected = _clearing_by_scan(distance, speed, acceleration, deceleration, cap)
                    got = clearing_ticks(distance, speed, acceleration, deceleration, cap)
                    assert got == expected
                    if speed <= cap:
                        # Nothing covers a distance sooner than a flat-out run under the cap.
                        # Above the cap the controller must first brake, which reach_ticks,
                        # used only for vehicles already under their cap, does not model.
                        assert got >= reach_ticks(distance, speed, acceleration, cap)


# ---------------------------------------------------------------------------------------------
# Signals


@pytest.fixture(scope="module")
def plan():
    return load_traffic_catalogs().plan("fixed_two_phase_60s")


def _expanded(plan) -> list[int]:
    seconds = []
    for index, interval in enumerate(plan.intervals):
        seconds += [index] * (interval.duration_ms // 1000)
    return seconds


def test_the_published_indications_are_the_ones_the_module_can_return():
    """Both tuples are read back from the returns of the functions that produce them.

    VEHICLE_INDICATIONS and PEDESTRIAN_INDICATIONS are exported for the society lane to read, and
    until this test nothing in the repository loaded either: they stated what an indication can be
    where nothing compared the statement with the code, so a fourth indication would have left
    both tuples quietly wrong. The indications are returned as literals by two small functions, so
    the sets come from there.
    """
    tree = ast.parse(Path(signals.__file__).read_text(encoding="utf-8"), filename=signals.__file__)
    returned: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.endswith("_indication"):
            returned[node.name] = {
                child.value.value
                for child in ast.walk(node)
                if isinstance(child, ast.Return)
                and isinstance(child.value, ast.Constant)
                and isinstance(child.value.value, str)
            }
    assert set(returned) == {"vehicle_indication", "pedestrian_indication"}, sorted(returned)
    assert all(len(values) >= 3 for values in returned.values()), returned
    assert returned["vehicle_indication"] == set(VEHICLE_INDICATIONS)
    assert returned["pedestrian_indication"] == set(PEDESTRIAN_INDICATIONS)


def test_indications_are_the_plan_expanded_second_by_second(plan):
    expanded = _expanded(plan)
    assert len(expanded) == 60
    for offset in range(60):
        for second in range(-60, 180):
            index = expanded[(second - offset) % 60]
            assert interval_index(plan, offset, second) == index
            interval = plan.intervals[index]
            for group in ("phase_a", "phase_b"):
                expected = (
                    "green"
                    if group in interval.vehicle_green
                    else "amber"
                    if group in interval.vehicle_amber
                    else "red"
                )
                assert vehicle_indication(plan, offset, second, group) == expected
            for group in ("walk_a", "walk_b"):
                expected = (
                    "walk"
                    if group in interval.pedestrian_walk
                    else "clearance"
                    if group in interval.pedestrian_clearance
                    else "dont_walk"
                )
                assert pedestrian_indication(plan, offset, second, group) == expected


def test_the_fixed_plan_never_releases_both_phases_and_clears_between_them(plan):
    shown = {
        group: [vehicle_indication(plan, 0, second, group) for second in range(60)]
        for group in ("phase_a", "phase_b")
    }
    assert shown["phase_a"] == ["green"] * 24 + ["amber"] * 4 + ["red"] * 32
    assert shown["phase_b"] == ["red"] * 30 + ["green"] * 24 + ["amber"] * 4 + ["red"] * 2
    walks = [pedestrian_indication(plan, 0, second, "walk_a") for second in range(60)]
    assert walks == ["walk"] * 7 + ["clearance"] * 17 + ["dont_walk"] * 36
    for second in range(60):
        assert "red" in (shown["phase_a"][second], shown["phase_b"][second])
    # The two seconds after each amber are red for both phases.
    assert shown["phase_a"][28:30] == shown["phase_b"][28:30] == ["red", "red"]


def test_seconds_until_red_counts_the_seconds_before_the_first_red(plan):
    for offset in (0, 17, 59):
        for second in range(0, 150):
            for group in ("phase_a", "phase_b"):
                steps = 0
                while vehicle_indication(plan, offset, second + steps, group) != "red":
                    steps += 1
                assert seconds_until_red(plan, offset, second, group) == steps
