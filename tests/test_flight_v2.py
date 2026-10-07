"""Flight for beings: minutes flown over air columns, held to an independent checker.

Every flight these tests fly is judged by the checker in this file, which reads the air's document,
the kind's figures and what the module hands back, and derives on its own which columns lie under a
body, how high it must keep over them and which moves a step may make. It calls none of the
module's helpers: a rule the module applied wrongly is a violation here rather than an error both
agree on. Each step's state is read with a spy on the module's step; the waypoints are the minute's
own output and must be the steps' positions at every second.
"""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.movement import flight_v2, steps
from exulanica.movement.flight_v2 import (
    AIR_COLUMNS_PROFILE,
    GOAL_REFUSALS,
    MINUTE_PROFILE,
    FlightMinuteRefused,
    FlyerFigures,
    air_columns,
    check_flyers,
    column_mm_for,
    fly_minute,
    flyer_figures,
)
from exulanica.movement.registry import (
    FLIGHT_V2,
    MovementModuleNotConnected,
    ParameterOutOfBounds,
    built_module,
)

ROOT = Path(__file__).resolve().parents[1]
ROW = built_module(FLIGHT_V2)
STEP_MS = ROW.value("step_ms")
STEPS = ROW.value("steps_per_minute")
WAYPOINTS = ROW.value("waypoints_per_minute")
SEED = "test-seed"

#: A large flyer declared for the screen: 2.5 m/s, turning at half a radian a second, so its
#: smallest turn is 5 m; 3 m across.
FIGURES = {
    "acceleration_mm_per_s2": 1000,
    "band_minimum_mm": 8000,
    "clearance_mm": 2000,
    "climb_mm_per_s": 1500,
    "cruise_mm_per_s": 2500,
    "descent_mm_per_s": 1500,
    "hovers": 0,
    "span_mm": 3000,
    "turn_rate_mrad_per_s": 500,
}
TURN_RADIUS = 5000


def air_document(
    blocks=(), *, columns=60, column_mm=2000, ceiling_mm=60_000, origin=(0, 0)
) -> dict:
    """An air of ``columns`` by ``columns`` columns, open but for ``blocks``: each
    ``(ix0, ix1, iy0, iy1, top)``, columns inclusive."""
    tops = [0] * (columns * columns)
    for ix0, ix1, iy0, iy1, top in blocks:
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                tops[iy * columns + ix] = top
    return {
        "profile": AIR_COLUMNS_PROFILE,
        "origin_mm": list(origin),
        "column_mm": column_mm,
        "columns_x": columns,
        "columns_y": columns,
        "ceiling_mm": ceiling_mm,
        "tops_mm": tops,
    }


def airborne(x, y, height=8000, velocity=(2500, 0, 0), thing_id="dragon") -> dict:
    return {
        "thing_id": thing_id,
        "position_mm": [x, y],
        "mode": "flight",
        "height_mm": height,
        "velocity_mm_s": list(velocity),
    }


def grounded(x, y, thing_id="dragon") -> dict:
    return {"thing_id": thing_id, "position_mm": [x, y], "mode": "walking"}


#: A tower 20 m tall, 6 m across and 20 m long, between x 24 and 30 m: one a kind clearing it by
#: 2 m under a 60 m ceiling can fly over.
LOW_TOWER = (12, 14, 25, 34, 20_000)
#: The same footprint 59 m tall: with 2 m of clearance it reaches above the 60 m ceiling, so no
#: kind of these figures can fly over it.
TALL_TOWER = (12, 14, 20, 40, 59_000)


# -- the independent checker -------------------------------------------------------------------


@dataclass
class Checked:
    violations: list[str] = field(default_factory=list)
    held: int = 0


class Air:
    """The air as this checker reads its document, with nothing of the module's."""

    def __init__(self, document: dict) -> None:
        self.x0, self.y0 = document["origin_mm"]
        self.size = document["column_mm"]
        self.nx, self.ny = document["columns_x"], document["columns_y"]
        self.ceiling = document["ceiling_mm"]
        self.tops = document["tops_mm"]

    def under(self, low_x, high_x, low_y, high_y):
        """The tops of every column a closed box meets, or None where it leaves the air."""
        if low_x < self.x0 or low_y < self.y0:
            return None
        if high_x >= self.x0 + self.nx * self.size or high_y >= self.y0 + self.ny * self.size:
            return None
        first_x, last_x = (low_x - self.x0) // self.size, (high_x - self.x0) // self.size
        first_y, last_y = (low_y - self.y0) // self.size, (high_y - self.y0) // self.size
        return [
            self.tops[iy * self.nx + ix]
            for iy in range(first_y, last_y + 1)
            for ix in range(first_x, last_x + 1)
        ]


def _reach(figures) -> int:
    return -(-figures["span_mm"] // 2)


def _needed(air: Air, figures, tops, low: bool) -> int:
    """How high a body over ``tops`` must be: its clearance over the tallest, or the ground over
    open columns while it lands or takes off."""
    if low and max(tops) == 0:
        return 0
    return max(tops) + figures["clearance_mm"]


def _point_ok(air: Air, figures, x, y, height, low: bool) -> bool:
    reach = _reach(figures)
    tops = air.under(x - reach, x + reach, y - reach, y + reach)
    return (
        tops is not None
        and 0 <= height <= air.ceiling
        and height >= _needed(air, figures, tops, low)
    )


def check_minute(document, figures, flyer, goal, trace, waypoints, outcome) -> Checked:
    """One minute judged: every step's position and the box each move sweeps, every waypoint, and
    the speed and turn between consecutive steps."""
    air = Air(document)
    reach = _reach(figures)
    found = Checked()
    dt = STEP_MS / 1000
    landing = goal.get("kind") == "land"
    # Taking off: from the ground, or below its clearance over open ground, until it is first at
    # or above its clearance.
    start_x, start_y = flyer["position_mm"]
    start_height = flyer.get("height_mm", 0)
    rising = flyer["mode"] == "walking" or (
        not _point_ok(air, figures, start_x, start_y, start_height, low=False)
        and _point_ok(air, figures, start_x, start_y, start_height, low=True)
    )
    if len(trace) != STEPS:
        found.violations.append(f"{len(trace)} steps, not {STEPS}")
    for index, (before, after) in enumerate(trace, start=1):
        found.held += after.held
        where = f"step {index} at {(after.x, after.y, after.height)}"
        if not after.flying:
            if before.flying:
                # Touching down: onto the landing point, over open ground only.
                tops = air.under(
                    min(before.x, after.x) - reach,
                    max(before.x, after.x) + reach,
                    min(before.y, after.y) - reach,
                    max(before.y, after.y) + reach,
                )
                if (
                    not landing
                    or tops is None
                    or max(tops) != 0
                    or [after.x, after.y, after.height] != [*goal["point_mm"], 0]
                ):
                    found.violations.append(f"{where}: touched down where it may not")
            continue
        # A step is judged by where it starts: the step that climbs out of the ground's open air
        # is still part of taking off.
        low = landing or rising
        if rising and _point_ok(air, figures, after.x, after.y, after.height, low=False):
            rising = False
        if not _point_ok(air, figures, after.x, after.y, after.height, low):
            found.violations.append(f"{where}: under its clearance or out of the air")
        if before.flying:
            tops = air.under(
                min(before.x, after.x) - reach,
                max(before.x, after.x) + reach,
                min(before.y, after.y) - reach,
                max(before.y, after.y) + reach,
            )
            bottom = min(before.height, after.height)
            if tops is None or bottom < _needed(air, figures, tops, low):
                found.violations.append(f"{where}: the move sweeps what it may not")
        if after.held or not before.flying:
            continue
        # The move is the velocity over a step, truncated.
        for part, speed in ((after.x - before.x, after.vx), (after.y - before.y, after.vy)):
            if abs(part - speed * dt) >= 1:
                found.violations.append(f"{where}: moved {part} at {speed} mm/s")
        old, new = math.hypot(before.vx, before.vy), math.hypot(after.vx, after.vy)
        if new > figures["cruise_mm_per_s"] + 1:
            found.violations.append(f"{where}: {new:.0f} mm/s over its cruise speed")
        if abs(new - old) > figures["acceleration_mm_per_s2"] * dt + 2:
            found.violations.append(f"{where}: speed {old:.0f} to {new:.0f} in a step")
        if old and new:
            angle = abs(
                math.atan2(
                    before.vx * after.vy - before.vy * after.vx,
                    before.vx * after.vx + before.vy * after.vy,
                )
            )
            bound = figures["turn_rate_mrad_per_s"] / 1000 * dt + 2 / min(old, new)
            if angle > bound:
                found.violations.append(f"{where}: turned {angle:.3f} rad in a step")
        if abs(after.vz - before.vz) > figures["acceleration_mm_per_s2"] * dt + 1:
            found.violations.append(f"{where}: vertical speed {before.vz} to {after.vz}")
        if not -figures["descent_mm_per_s"] <= after.vz <= figures["climb_mm_per_s"]:
            found.violations.append(f"{where}: vertical speed {after.vz} out of its rates")
    every = STEPS // WAYPOINTS
    expected = [[after.x, after.y, after.height] for _, after in trace[every - 1 :: every]]
    if waypoints != expected or outcome["waypoints_mm"] != waypoints or len(waypoints) != WAYPOINTS:
        found.violations.append("the waypoints are not the steps' positions at every second")
    if outcome["held_steps"] != found.held:
        found.violations.append(
            f"held {found.held} steps, the outcome says {outcome['held_steps']}"
        )
    return found


@contextmanager
def traced(monkeypatch) -> Iterator[list]:
    """Every step the module takes, as (state before, state after)."""
    taken: list = []
    step = flight_v2._step

    def spy(minute, plan, body):
        after = step(minute, plan, body)
        taken.append((body, after))
        return after

    monkeypatch.setattr(flight_v2, "_step", spy)
    yield taken


@dataclass
class Flight:
    flyers: list[dict]
    waypoints: list[list[int]]
    outcomes: list[dict]
    checks: list[Checked]

    @property
    def violations(self) -> list[str]:
        return [v for checked in self.checks for v in checked.violations]

    @property
    def held(self) -> int:
        return sum(checked.held for checked in self.checks)


def fly(monkeypatch, document, flyer, goal, minutes, figures=FIGURES, ordinal=0) -> Flight:
    """``minutes`` minutes of one flyer toward one goal, every minute judged by the checker."""
    air = air_columns(document)
    flight = Flight([flyer], [], [], [])
    with traced(monkeypatch) as taken:
        for tick in range(minutes):
            taken.clear()
            after, waypoints, outcome = fly_minute(air, flyer, goal, figures, SEED, tick, ordinal)
            flight.checks.append(
                check_minute(document, figures, flyer, goal, list(taken), waypoints, outcome)
            )
            flight.flyers.append(after)
            flight.waypoints.extend(waypoints)
            flight.outcomes.append(outcome)
            flyer = after
    return flight


# -- the row and its step ------------------------------------------------------------------------


def test_the_row_is_the_module_its_code_runs():
    assert steps.step_of(FLIGHT_V2) is fly_minute
    assert ROW.space_kind == "air-columns"
    assert ROW.space_profiles == (AIR_COLUMNS_PROFILE,)
    assert ROW.output_profile == MINUTE_PROFILE
    assert (ROW.clock_kind, ROW.step_ms) == ("society", STEPS * STEP_MS)
    assert WAYPOINTS * 2 == STEPS
    assert set(FlyerFigures.__dataclass_fields__) == set(ROW.supplied())


def test_the_row_is_a_switch_asked_where_a_minute_is_flown(monkeypatch):
    def switched_off(name):
        raise MovementModuleNotConnected(name, "flight_v2_not_connected")

    monkeypatch.setattr(flight_v2, "built_module", switched_off)
    with pytest.raises(MovementModuleNotConnected) as refused:
        fly_minute(air_document(), airborne(10_000, 10_000), {"kind": "stay"}, FIGURES, SEED, 0, 0)
    assert refused.value.code == "flight_v2_not_connected"


# -- the air -------------------------------------------------------------------------------------


def test_an_air_s_digest_is_the_sha256_of_its_canonical_document():
    document = air_document([LOW_TOWER])
    air = air_columns(document)
    assert air.sha256 == hashlib.sha256(canonical_json(document)).hexdigest()
    *_, outcome = fly_minute(air, airborne(10_000, 60_000), {"kind": "stay"}, FIGURES, SEED, 0, 0)
    assert outcome["air_sha256"] == air.sha256


def test_an_air_of_more_columns_than_the_module_admits_is_refused_by_name_before_its_tops():
    limit = ROW.value("max_columns")
    side = math.isqrt(limit)
    assert side * side == limit
    admitted = {**air_document(columns=1), "columns_x": side, "columns_y": side}
    admitted["tops_mm"] = [0] * limit
    assert air_columns(admitted).columns_x == side
    larger = {**admitted, "columns_y": side + 1, "tops_mm": []}
    with pytest.raises(FlightMinuteRefused) as refused:
        air_columns(larger)
    assert refused.value.code == "flight_world_too_large"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(profile="exulanica.air-volume/v1"),
        lambda d: d.pop("ceiling_mm"),
        lambda d: d.update(origin_mm=[0]),
        lambda d: d.update(column_mm=1999),
        lambda d: d.update(column_mm=8001),
        lambda d: d.update(columns_x=0),
        lambda d: d.update(ceiling_mm=200_001),
        lambda d: d.update(tops_mm=d["tops_mm"][:-1]),
        lambda d: d["tops_mm"].__setitem__(0, -1),
        lambda d: d["tops_mm"].__setitem__(0, True),
        lambda d: d["tops_mm"].__setitem__(0, 1.5),
    ],
    ids=[
        "profile",
        "missing_ceiling",
        "origin",
        "column_too_narrow",
        "column_too_wide",
        "no_columns",
        "ceiling_too_high",
        "tops_short",
        "negative_top",
        "boolean_top",
        "float_top",
    ],
)
def test_an_air_the_profile_does_not_state_is_refused_by_name(change):
    document = air_document(columns=4)
    assert air_columns(document).columns_x == 4, "positive control"
    change(document)
    with pytest.raises(FlightMinuteRefused) as refused:
        air_columns(document)
    assert refused.value.code == "invalid_air_columns"


@pytest.mark.parametrize(
    ("span", "column"),
    [
        (0, 2000),
        (3000, 2000),
        (4001, 2500),
        (5000, 2500),
        (9001, 5000),
        (16_000, 8000),
        (60_000, 8000),
    ],
)
def test_an_air_s_column_is_half_its_widest_span_rounded_up_and_held_to_its_bounds(span, column):
    assert column_mm_for(span) == column


def test_more_flyers_than_the_module_moves_are_refused_by_name():
    limit = ROW.value("max_flyers")
    check_flyers(limit)
    with pytest.raises(FlightMinuteRefused) as refused:
        check_flyers(limit + 1)
    assert refused.value.code == "too_many_flyers"


# -- figures, flyers and goals -------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FIGURES))
def test_a_figure_outside_the_module_s_bounds_is_refused_naming_it(name):
    assert flyer_figures(FIGURES).cruise_mm_per_s == 2500, "positive control"
    parameter = ROW.parameter(name)
    for value in (parameter.minimum - 1, parameter.maximum + 1):
        with pytest.raises(ParameterOutOfBounds, match=rf"{name}.*got {value}"):
            flyer_figures({**FIGURES, name: value})
        with pytest.raises(ParameterOutOfBounds):
            fly_minute(
                air_document(),
                airborne(10_000, 10_000),
                {"kind": "stay"},
                {**FIGURES, name: value},
                SEED,
                0,
                0,
            )


def test_figures_that_do_not_state_exactly_the_kind_s_parameters_are_refused_by_name():
    for values in ({k: v for k, v in FIGURES.items() if k != "hovers"}, {**FIGURES, "wings": 2}):
        with pytest.raises(FlightMinuteRefused) as refused:
            flyer_figures(values)
        assert refused.value.code == "invalid_flight_figures"


@pytest.mark.parametrize(
    ("flyer", "code"),
    [
        ({**airborne(10_000, 10_000), "thing_id": ""}, "invalid_flyer"),
        ({**airborne(10_000, 10_000), "mode": "swimming"}, "invalid_flyer"),
        ({**airborne(10_000, 10_000), "height_mm": -1}, "invalid_flyer"),
        ({**airborne(10_000, 10_000), "velocity_mm_s": [1, 2]}, "invalid_flyer"),
        ({**grounded(10_000, 10_000), "height_mm": 0}, "invalid_flyer"),
        ({**airborne(10_000, 10_000), "position_mm": [10_000.0, 10_000]}, "invalid_flyer"),
        (airborne(-1, 10_000), "flyer_outside_air"),
        (airborne(10_000, 120_000), "flyer_outside_air"),
    ],
    ids=[
        "no_identity",
        "unknown_mode",
        "negative_height",
        "short_velocity",
        "height_on_the_ground",
        "float_position",
        "west_of_the_air",
        "north_of_the_air",
    ],
)
def test_a_flyer_the_state_shape_does_not_admit_is_refused_by_name(flyer, code):
    fly_minute(air_document(), airborne(10_000, 10_000), {"kind": "stay"}, FIGURES, SEED, 0, 0)
    with pytest.raises(FlightMinuteRefused) as refused:
        fly_minute(air_document(), flyer, {"kind": "stay"}, FIGURES, SEED, 0, 0)
    assert refused.value.code == code


@pytest.mark.parametrize(
    "goal",
    [
        {"point_mm": [1, 2]},
        {"kind": "go_near", "point_mm": [1, 2]},
        {"kind": "go_near", "point_mm": [1, 2], "within_mm": -1},
        {"kind": "circle", "point_mm": [1], "radius_mm": 5},
        {"kind": "land", "point_mm": None},
        {"kind": "keep_near", "target_id": "", "point_mm": [1, 2], "within_mm": 5},
        {"kind": "stay", "point_mm": [1, 2]},
    ],
    ids=[
        "no_kind",
        "no_within",
        "negative_within",
        "short_point",
        "no_point",
        "no_target",
        "extra",
    ],
)
def test_a_goal_its_primitive_does_not_state_is_refused_by_name(goal):
    with pytest.raises(FlightMinuteRefused) as refused:
        fly_minute(air_document(), airborne(10_000, 10_000), goal, FIGURES, SEED, 0, 0)
    assert refused.value.code == "invalid_flight_goal"


# -- the state agreed with the things engine ----------------------------------------------------


def test_a_minute_replaces_only_the_flyer_s_movement_and_keeps_every_other_field():
    flyer = {**airborne(10_000, 60_000), "size_class_mm": 6000, "kind": "wyvern"}
    after, _, _ = fly_minute(air_document(), flyer, {"kind": "stay"}, FIGURES, SEED, 0, 0)
    assert (after["size_class_mm"], after["kind"], after["thing_id"]) == (6000, "wyvern", "dragon")
    assert after["mode"] == "flight" and isinstance(after["height_mm"], int)
    assert all(type(value) is int for value in [*after["position_mm"], *after["velocity_mm_s"]])
    assert flyer == {**airborne(10_000, 60_000), "size_class_mm": 6000, "kind": "wyvern"}


def _digest_of_minutes() -> str:
    """Three minutes of one flyer, by every output, as one digest."""
    flights = [
        fly_minute(air_document([LOW_TOWER]), airborne(10_000, 60_000), goal, FIGURES, SEED, 3, 1)
        for goal in (
            {"kind": "go_near", "point_mm": [100_000, 60_000], "within_mm": 5000},
            {"kind": "land", "point_mm": [60_000, 100_000]},
            {"kind": "stay"},
        )
    ]
    return hashlib.sha256(canonical_json(flights)).hexdigest()


def test_a_minute_replays_to_the_same_bytes_in_this_process_and_another():
    here = _digest_of_minutes()
    assert _digest_of_minutes() == here
    # Another interpreter, with another string hash seed, flies the same bytes.
    child = subprocess.run(
        [sys.executable, "-c", "import test_flight_v2 as t; print(t._digest_of_minutes())"],
        cwd=ROOT / "tests",
        env={**os.environ, "PYTHONHASHSEED": "12345", "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert child.stdout.strip() == here


# -- goals flown --------------------------------------------------------------------------------


def test_go_near_arrives_over_open_air_within_two_minutes_and_circles_the_point(monkeypatch):
    goal = {"kind": "go_near", "point_mm": [90_000, 90_000], "within_mm": 6000}
    flight = fly(monkeypatch, air_document(), airborne(10_000, 10_000), goal, 3)
    assert (flight.violations, flight.held) == ([], 0)
    assert [o["status"] for o in flight.outcomes][1:] == ["reached", "reached"]
    # Circling the point at the distance it was asked to come within, its smallest turn being less.
    last = [math.dist(point[:2], goal["point_mm"]) for point in flight.waypoints[-60:]]
    assert min(last) >= 6000 * 0.98 and max(last) <= 6000 * 1.02


def test_a_circle_holds_its_radius_within_two_percent_after_entry(monkeypatch):
    goal = {"kind": "circle", "point_mm": [60_000, 60_000], "radius_mm": 12_000}
    flight = fly(monkeypatch, air_document(), airborne(10_000, 60_000), goal, 4)
    assert (flight.violations, flight.held) == ([], 0)
    after_entry = [math.dist(point[:2], goal["point_mm"]) for point in flight.waypoints[60:]]
    assert all(12_000 * 0.98 <= distance <= 12_000 * 1.02 for distance in after_entry)
    assert {o["status"] for o in flight.outcomes[1:]} == {"reached"}


def test_a_circle_narrower_than_the_kind_s_smallest_turn_is_flown_at_that_turn(monkeypatch):
    goal = {"kind": "circle", "point_mm": [60_000, 60_000], "radius_mm": 1000}
    flight = fly(monkeypatch, air_document(), airborne(30_000, 60_000), goal, 3)
    assert flight.violations == []
    after_entry = [math.dist(point[:2], goal["point_mm"]) for point in flight.waypoints[60:]]
    assert all(TURN_RADIUS * 0.98 <= distance <= TURN_RADIUS * 1.02 for distance in after_entry)


def test_a_winged_flyer_staying_circles_where_it_is_at_its_smallest_turn(monkeypatch):
    flight = fly(monkeypatch, air_document(), airborne(60_000, 60_000), {"kind": "stay"}, 3)
    assert (flight.violations, flight.held) == ([], 0)
    for tick, start in enumerate(flight.flyers[:-1]):
        # Each minute's circle passes through where the flyer was, a smallest turn to its left.
        (x, y), (vx, vy, _) = start["position_mm"], start["velocity_mm_s"]
        speed = math.hypot(vx, vy)
        centre = (x - vy * TURN_RADIUS / speed, y + vx * TURN_RADIUS / speed)
        minute = flight.waypoints[60 * tick + 10 : 60 * (tick + 1)]
        distances = [math.dist(point[:2], centre) for point in minute]
        assert all(TURN_RADIUS * 0.95 <= d <= TURN_RADIUS * 1.05 for d in distances), tick
    assert all("velocity_mm_s" in after for after in flight.flyers[1:])


def test_a_kind_that_hovers_slows_to_rest_where_it_is_when_it_stays(monkeypatch):
    figures = {**FIGURES, "hovers": 1}
    flight = fly(
        monkeypatch, air_document(), airborne(60_000, 60_000), {"kind": "stay"}, 2, figures
    )
    assert (flight.violations, flight.held) == ([], 0)
    rest = flight.flyers[-1]
    assert "velocity_mm_s" not in rest and rest["height_mm"] == 8000
    # Slowing by 500 mm/s a step from 2.5 m/s, it moves 1,000, 750, 500 and 250 mm and rests.
    assert rest["position_mm"] == [62_500, 60_000]
    assert flight.waypoints[-30:] == [[62_500, 60_000, 8000]] * 30


def test_a_tower_in_the_way_that_can_be_flown_over_is_flown_over(monkeypatch):
    goal = {"kind": "go_near", "point_mm": [100_000, 60_000], "within_mm": 5000}
    flight = fly(monkeypatch, air_document([LOW_TOWER]), airborne(10_000, 60_000), goal, 2)
    assert (flight.violations, flight.held) == ([], 0)
    over = [p for p in flight.waypoints if 24_000 <= p[0] < 30_000 and 50_000 <= p[1] < 70_000]
    assert over and all(p[2] >= 20_000 + 2000 for p in over), "it went over the tower"
    assert flight.outcomes[-1]["status"] == "reached"


def test_a_tower_in_the_way_that_cannot_be_flown_over_is_flown_round(monkeypatch):
    goal = {"kind": "go_near", "point_mm": [100_000, 60_000], "within_mm": 5000}
    flight = fly(monkeypatch, air_document([TALL_TOWER]), airborne(10_000, 60_000), goal, 2)
    assert (flight.violations, flight.held) == ([], 0)
    assert all(point[2] < 59_000 for point in flight.waypoints), "it never climbed over it"
    passed = [p for p in flight.waypoints if p[0] >= 30_000]
    assert passed and all(not 40_000 <= p[1] < 82_000 for p in passed if p[0] < 32_000)
    assert flight.outcomes[0]["status"] == "reached"


def test_a_landing_ends_on_the_point_at_height_0_walking(monkeypatch):
    goal = {"kind": "land", "point_mm": [80_000, 40_000]}
    flight = fly(monkeypatch, air_document([LOW_TOWER]), airborne(10_000, 60_000), goal, 2)
    assert (flight.violations, flight.held) == ([], 0)
    first = flight.outcomes[0]
    [landed] = first["events"]
    assert landed["kind"] == "landed" and 0 <= landed["at_ms"] < 60_000
    assert first["status"] == "reached"
    after = flight.flyers[1]
    assert after == grounded(80_000, 40_000)
    # Every waypoint from touching down on is the point on the ground.
    touched = landed["at_ms"] // 1000
    assert flight.waypoints[touched:60] == [[80_000, 40_000, 0]] * (60 - touched)
    assert (flight.outcomes[1]["status"], flight.outcomes[1]["events"]) == ("reached", [])


def test_a_landing_from_high_above_its_point_comes_down_a_spiral(monkeypatch):
    goal = {"kind": "land", "point_mm": [60_000, 60_000]}
    start = airborne(60_000, 60_000, height=30_000)
    flight = fly(monkeypatch, air_document(), start, goal, 2)
    assert (flight.violations, flight.held) == ([], 0)
    assert flight.flyers[1] == grounded(60_000, 60_000)
    # It loses its height circling within two of its smallest turns of the point.
    descending = [p for p in flight.waypoints if p[2] > 2000]
    assert all(math.dist(p[:2], goal["point_mm"]) <= 2 * TURN_RADIUS + 1000 for p in descending)
    assert max(p[2] for p in flight.waypoints) <= 30_000


@pytest.mark.parametrize("hovers", [0, 1], ids=["winged", "hovering"])
def test_a_take_off_climbs_from_the_ground_to_the_band(monkeypatch, hovers):
    figures = {**FIGURES, "hovers": hovers}
    start = grounded(60_000, 60_000)
    flight = fly(monkeypatch, air_document(), start, {"kind": "take_off"}, 1, figures)
    assert (flight.violations, flight.held) == ([], 0)
    outcome = flight.outcomes[0]
    assert outcome["events"] == [{"kind": "took_off", "at_ms": 0}]
    assert outcome["status"] == "reached"
    assert flight.flyers[1]["mode"] == "flight" and flight.flyers[1]["height_mm"] == 8000
    if hovers:
        # A kind that hovers rises straight up and holds there.
        assert {tuple(point[:2]) for point in flight.waypoints} == {(60_000, 60_000)}
        assert "velocity_mm_s" not in flight.flyers[1]


def test_a_kind_that_hovers_lands_straight_down_onto_its_point(monkeypatch):
    figures = {**FIGURES, "hovers": 1}
    goal = {"kind": "land", "point_mm": [60_000, 60_000]}
    flight = fly(
        monkeypatch, air_document(), airborne(60_000, 60_000, height=30_000), goal, 1, figures
    )
    assert (flight.violations, flight.held) == ([], 0)
    assert flight.flyers[1] == grounded(60_000, 60_000)
    # It drifts to rest over the point and comes down: never further than its stopping distance.
    assert all(math.dist(point[:2], goal["point_mm"]) <= 3200 for point in flight.waypoints)


def test_a_flyer_asked_to_fly_from_the_ground_takes_off_first(monkeypatch):
    goal = {
        "kind": "keep_near",
        "target_id": "knight",
        "point_mm": [100_000, 20_000],
        "within_mm": 0,
    }
    flight = fly(monkeypatch, air_document([LOW_TOWER]), grounded(20_000, 100_000), goal, 2)
    assert (flight.violations, flight.held) == ([], 0)
    assert flight.outcomes[0]["events"] == [{"kind": "took_off", "at_ms": 0}]
    assert flight.outcomes[1]["status"] == "reached"


def test_a_grounded_flyer_that_stays_stays_on_the_ground(monkeypatch):
    start = {**grounded(60_000, 60_000), "size_class_mm": 9000}
    flight = fly(monkeypatch, air_document(), start, {"kind": "stay"}, 1)
    assert flight.flyers[1] == start
    assert flight.waypoints == [[60_000, 60_000, 0]] * 60
    assert flight.outcomes[0]["status"] == "reached"


# -- refusals by name, each beside a goal the same air serves ------------------------------------

#: A pen of 59 m walls around the point (90 m, 90 m): no kind of these figures flies over them.
PEN = [
    (40, 50, 40, 40, 59_000),
    (40, 50, 50, 50, 59_000),
    (40, 40, 40, 50, 59_000),
    (50, 50, 40, 50, 59_000),
]
#: The same pen with a gap of three columns in its west wall.
OPEN_PEN = [
    (40, 50, 40, 40, 59_000),
    (40, 50, 50, 50, 59_000),
    (40, 40, 40, 43, 59_000),
    (40, 40, 47, 50, 59_000),
    (50, 50, 40, 50, 59_000),
]

REFUSALS = {
    "not_served_by_module": (
        air_document(),
        airborne(10_000, 60_000),
        {"kind": "follow", "thing_id": "knight"},
        {"kind": "stay"},
    ),
    "target_gone": (
        air_document(),
        airborne(10_000, 60_000),
        {"kind": "keep_near", "target_id": "knight", "point_mm": None, "within_mm": 3000},
        {
            "kind": "keep_near",
            "target_id": "knight",
            "point_mm": [60_000, 60_000],
            "within_mm": 3000,
        },
    ),
    "lost_target": (
        air_document(),
        airborne(10_000, 60_000),
        {
            "kind": "keep_near",
            "target_id": "knight",
            "point_mm": [130_000, 60_000],
            "within_mm": 3000,
        },
        {
            "kind": "keep_near",
            "target_id": "knight",
            "point_mm": [110_000, 60_000],
            "within_mm": 3000,
        },
    ),
    "no_route": (
        air_document(PEN),
        airborne(10_000, 60_000),
        {"kind": "go_near", "point_mm": [91_000, 91_000], "within_mm": 0},
        None,
    ),
    "circle_blocked": (
        air_document([TALL_TOWER]),
        airborne(10_000, 100_000),
        {"kind": "circle", "point_mm": [27_000, 50_000], "radius_mm": 8000},
        {"kind": "circle", "point_mm": [60_000, 50_000], "radius_mm": 8000},
    ),
    "no_room_to_land": (
        air_document([LOW_TOWER]),
        airborne(10_000, 100_000),
        {"kind": "land", "point_mm": [31_000, 60_000]},
        {"kind": "land", "point_mm": [33_000, 60_000]},
    ),
    "no_room_to_rise": (
        air_document([LOW_TOWER]),
        grounded(31_000, 60_000),
        {"kind": "take_off"},
        None,
    ),
}


def test_every_refusal_a_goal_can_meet_is_tested_here():
    assert set(REFUSALS) == set(GOAL_REFUSALS)


@pytest.mark.parametrize("code", sorted(REFUSALS))
def test_a_goal_is_refused_by_name_and_the_flyer_stays(monkeypatch, code):
    document, flyer, refused_goal, served_goal = REFUSALS[code]
    flight = fly(monkeypatch, document, flyer, refused_goal, 1)
    outcome = flight.outcomes[0]
    assert (outcome["status"], outcome["refusal"]) == ("refused", code)
    assert outcome["goal"] == refused_goal["kind"]
    assert (flight.violations, flight.held) == ([], 0)
    assert flight.flyers[1]["mode"] == flyer["mode"], (
        "it stayed as it was, in the air or on the ground"
    )
    # Positive control: the same air serves a goal beside it.
    if code == "no_route":
        document = air_document(OPEN_PEN)
        served_goal = refused_goal
    if code == "no_room_to_rise":
        flyer = grounded(33_000, 60_000)
        served_goal = refused_goal
    served = fly(monkeypatch, document, flyer, served_goal, 3)
    assert {o["refusal"] for o in served.outcomes} == {None}
    assert served.outcomes[-1]["status"] == "reached"
    assert served.violations == []


# -- the guard, and the checker's own control ----------------------------------------------------


def _blind(monkeypatch):
    """Steering that never climbs: whatever stands ahead, it aims at its band."""
    monkeypatch.setattr(
        flight_v2,
        "_height_target",
        lambda minute, body, desired, height, low: (minute.figures.band_minimum_mm, desired),
    )


def test_the_guard_alone_keeps_a_flyer_that_never_climbs_out_of_a_tower(monkeypatch):
    """Positive control for the checker: steering flies at the tower and the guard holds it."""
    _blind(monkeypatch)
    goal = {"kind": "go_near", "point_mm": [100_000, 60_000], "within_mm": 5000}
    flight = fly(monkeypatch, air_document([LOW_TOWER]), airborne(10_000, 60_000), goal, 1)
    assert flight.violations == []
    assert flight.held > 0, "steering never met the tower, so this tests nothing"


def test_with_the_guard_off_the_checker_catches_a_flight_through_the_tower(monkeypatch):
    _blind(monkeypatch)

    def unguarded(minute, body, velocity, low):
        vx, vy, vz = velocity
        return flight_v2._Body(
            body.x + flight_v2._move(vx),
            body.y + flight_v2._move(vy),
            body.height + flight_v2._move(vz),
            vx,
            vy,
            vz,
            flying=True,
        )

    monkeypatch.setattr(flight_v2, "_guarded", unguarded)
    goal = {"kind": "go_near", "point_mm": [100_000, 60_000], "within_mm": 5000}
    flight = fly(monkeypatch, air_document([LOW_TOWER]), airborne(10_000, 60_000), goal, 1)
    inside = [p for p in flight.waypoints if 24_000 <= p[0] < 30_000 and p[2] < 22_000]
    assert inside, "the mutant never entered the tower"
    assert any("under its clearance" in violation for violation in flight.violations)


def test_a_flyer_under_a_column_placed_since_its_last_minute_climbs_out(monkeypatch):
    """Its state is legal in the air it flew, not in this one: a 20 m tower now stands under it."""
    document = air_document([(28, 32, 28, 32, 20_000)])
    start = airborne(60_000, 60_000)
    air = air_columns(document)
    with traced(monkeypatch) as taken:
        fly_minute(air, start, {"kind": "stay"}, FIGURES, SEED, 0, 0)
    legal = [
        _point_ok(Air(document), FIGURES, after.x, after.y, after.height, low=False)
        for _, after in taken
    ]
    first = legal.index(True)
    assert first > 0 and all(legal[first:]), "once out it stays clear"
    # Out of the tower straight up, every step until then held.
    assert all(
        (after.x, after.y, after.held) == (60_000, 60_000, True) for _, after in taken[:first]
    )


# -- a minute's cost ----------------------------------------------------------------------------


def test_a_minute_for_24_flyers_is_timed(record_property):
    """A timing note, recorded and not asserted: 24 flyers over a 200 m square of 2 m columns
    with tall and low blocks, each flying one minute toward a goal of each kind in turn."""
    blocks = [
        (5 + 9 * i, 7 + 9 * i, 5 + 7 * j, 6 + 7 * j, 6000 * (1 + (i + j) % 5))
        for i in range(10)
        for j in range(12)
    ]
    air = air_columns(air_document(blocks, columns=100))
    goals = [
        {"kind": "go_near", "point_mm": [150_000, 150_000], "within_mm": 4000},
        {"kind": "circle", "point_mm": [100_000, 100_000], "radius_mm": 12_000},
        {"kind": "land", "point_mm": [3_000, 3_000]},
        {"kind": "stay"},
    ]
    flyers = [
        airborne(9_000 + 7_000 * i, 195_000, height=40_000, thing_id=f"f{i}") for i in range(24)
    ]
    started = time.perf_counter()
    outcomes = [
        fly_minute(air, flyer, goals[i % 4], FIGURES, SEED, 0, i)[2]
        for i, flyer in enumerate(flyers)
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000
    record_property("minute_of_24_flyers_ms", round(elapsed_ms, 1))
    print(f"a minute of 24 flyers: {elapsed_ms:.1f} ms")
    assert [len(outcome["waypoints_mm"]) for outcome in outcomes] == [WAYPOINTS] * 24
    assert {outcome["refusal"] for outcome in outcomes} == {None}
