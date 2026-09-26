"""Movement modules: the table, the dispatcher's named refusals, and walking through the module.

The walking pins that matter most live elsewhere and are unchanged by moving walking here: a saved
world's v2 history replays byte for byte (tests/test_society_v2_history_replay.py), the living
society over the Flatiron district keeps its genesis and minute-60 digests
(tests/test_society_living_unchanged.py) and the recorder's minute-180 digest
(tests/test_society_choice_seam.py). This file proves the society actually walks by the module: a
spy in the dispatcher's step table sees every walk, and a society that walked around the module
would leave it unseen.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import json
from dataclasses import fields
from pathlib import Path
from types import MappingProxyType

import pytest
from exulanica.movement import steps, walking
from exulanica.movement.flight import FlightKind
from exulanica.movement.registry import (
    FLIGHT,
    MODULES,
    MODULES_PATH,
    ROADS,
    WALKING,
    MovementModuleNotConnected,
    ParameterOutOfBounds,
    UnknownMovementModule,
    built_module,
    load_movement_modules,
    movement_module,
)
from exulanica.world.society import society_state_sha256
from exulanica.world.society_engines import ENGINES
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_place import PLACE_PROFILES
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    MOVEMENT_BUDGET_MM,
    NAVIGATION_PROFILES,
)

from living_square_support import run as run_square
from society_living_fixtures import GRID_SOCIETY, SEEDS, grid_input, grid_place, routine

UNKNOWN = "exulanica-movement/swimming/v1"


def _table() -> dict:
    return json.loads(MODULES_PATH.read_text(encoding="utf-8"))


def _load(tmp_path: Path, document: dict):
    path = tmp_path / MODULES_PATH.name
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_movement_modules(path)


# -- the dispatcher refuses by name -----------------------------------------------------------


def test_an_unknown_module_is_refused_by_name():
    for lookup in (movement_module, built_module, steps.step_of):
        with pytest.raises(UnknownMovementModule, match="swimming/v1"):
            lookup(UNKNOWN)
    with pytest.raises(UnknownMovementModule, match="None"):
        movement_module(None)


def test_roads_are_stated_and_refused_with_their_own_refusal():
    roads = movement_module(ROADS)
    assert (roads.status, roads.refusal, roads.space_kind) == (
        "not_connected",
        "roads_not_connected",
        "road-graph",
    )
    for lookup in (built_module, steps.step_of):
        with pytest.raises(MovementModuleNotConnected) as refused:
            lookup(ROADS)
        assert refused.value.code == "roads_not_connected"


def test_the_step_table_holds_exactly_the_built_modules():
    assert set(steps.STEPS) == {module.module for module in MODULES if module.status == "built"}
    assert steps.step_of(WALKING) is walking.traverse


def test_the_published_table_loads_through_the_path_its_refusals_take(tmp_path):
    """Positive control: an unchanged copy loads, so every refusal below is its mutation's."""
    assert _load(tmp_path, _table()) == MODULES


def _mutated(change):
    document = _table()
    change(document)
    return document


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: d["modules"].reverse(), "once each, in order"),
        (lambda d: d["modules"].append(copy.deepcopy(d["modules"][0])), "once each, in order"),
        (lambda d: d["modules"][0].update(refusal="not_needed"), "no refusal"),
        (lambda d: d["modules"][1].update(refusal=None), "no refusal"),
        (lambda d: d["modules"][0]["space"].update(kind="water"), "space states its kind"),
        (lambda d: d["modules"][0]["clock"].update(kind="wall"), "clock states its kind"),
        (lambda d: d["modules"][0].pop("output"), "states exactly"),
        (lambda d: d["modules"][0]["parameters"].reverse(), "in name order"),
        (
            lambda d: d["modules"][0]["parameters"][2].update(value=13000),
            "value inside its bounds",
        ),
        (lambda d: d["modules"][0]["parameters"][2].pop("reason"), "states exactly"),
        (lambda d: d.update(profile="exulanica.movement-modules/v0"), "is not a"),
    ],
    ids=[
        "out_of_order",
        "twice",
        "built_with_refusal",
        "unbuilt_without_refusal",
        "unknown_space",
        "unknown_clock",
        "no_output",
        "parameters_out_of_order",
        "value_outside_bounds",
        "parameter_without_reason",
        "wrong_profile",
    ],
)
def test_the_table_refuses_by_name(tmp_path, change, match):
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, _mutated(change))


def test_a_kind_value_outside_the_module_bounds_is_refused_naming_both():
    flight = built_module(FLIGHT)
    with pytest.raises(ParameterOutOfBounds, match=r"cruise_speed_mm_s.*got 40000"):
        flight.checked("cruise_speed_mm_s", 40_000, where="flight kind test")


def test_a_flight_kind_supplies_exactly_the_parameters_the_module_leaves_to_kinds():
    stated = {field.name for field in fields(FlightKind)} - {"key"}
    assert stated == set(built_module(FLIGHT).supplied())


# -- walking is the society's -----------------------------------------------------------------


def test_a_walk_stopping_part_way_along_a_diagonal_edge_floors_each_coordinate():
    """The rounding the society contract states: every point by integer floor division.

    Every recorded history the replay pins hold walks edges along one axis, where the division is
    exact, so no pin sees the rounding. This edge runs along two axes, one of them negative, where
    floor division, truncation and rounding up all differ.
    """
    nodes = {"a": {"position_mm": [0, 0, 0]}, "b": {"position_mm": [1000, 0, -333]}}
    edges = {frozenset(("a", "b")): {"edge_id": "a-b", "length_mm": 1055}}
    route = {"node_ids": ["a", "b"], "edge_index": 0, "edge_progress_mm": 0}
    [leg] = walking.traverse(route, nodes, edges, 500)
    assert leg.point == [473, 0, -158]  # 473.93 and -157.82, floored
    assert (leg.step_mm, leg.arrived, route["edge_progress_mm"]) == (500, False, 500)


def test_walking_declares_the_figures_the_society_records():
    walking_row = built_module(WALKING)
    assert walking_row.value("new_society_budget_mm_per_tick") == MOVEMENT_BUDGET_MM == 60_000
    assert walking_row.value("clearance_mm") == CLEARANCE_MM == 450
    budget = walking_row.parameter("budget_mm_per_tick")
    assert (budget.minimum, budget.maximum) == (1, 10**9)
    # Every graph a society walks is a space the module declares.
    assert set(NAVIGATION_PROFILES.values()) | set(PLACE_PROFILES) <= set(
        walking_row.space_profiles
    )
    # Exactly the engines that route their people over a graph walk by it; v1 keeps its own.
    routed = {engine.engine for engine in ENGINES if engine.state_family != "legacy"}
    assert set(walking_row.agents_kinds or ()) == routed


def test_a_living_walk_speed_is_inside_the_walking_bounds():
    policy = routine().policy
    walking_row = built_module(WALKING)
    for name in ("walk_speed_minimum_mm_per_tick", "walk_speed_maximum_mm_per_tick"):
        assert walking_row.admits("budget_mm_per_tick", policy[name])


class _Spy:
    """The walking step, counted: every walk the society takes passes through here."""

    def __init__(self) -> None:
        self.legs = 0
        self.calls = 0

    def __call__(self, route, nodes, edges, budget):
        self.calls += 1
        for leg in walking.traverse(route, nodes, edges, budget):
            self.legs += 1
            yield leg


def _spied(monkeypatch) -> _Spy:
    spy = _Spy()
    monkeypatch.setattr(steps, "STEPS", MappingProxyType({**steps.STEPS, WALKING: spy}))
    return spy


def test_a_saved_world_society_walks_through_the_module(monkeypatch):
    seed = SEEDS[0]
    unspied = [society_state_sha256(state) for state in run_square(seed, 12)]
    spy = _spied(monkeypatch)
    spied = [society_state_sha256(state) for state in run_square(seed, 12)]
    assert spy.calls > 0 and spy.legs > 0, "nobody walked through the walking module"
    assert spied == unspied


def _living(ticks: int) -> list[str]:
    place = LivingPlace(grid_place(grid_input()), routine())
    state = initial_living_society(
        GRID_SOCIETY, SEEDS[0], place, routine(), branch_id=str(grid_input()["version_id"])
    )
    digests = [society_state_sha256(state)]
    for _ in range(ticks):
        state, _events = advance_living_society(state, SEEDS[0], [place], routine())
        digests.append(society_state_sha256(state))
    return digests


def test_a_living_society_walks_through_the_module(monkeypatch):
    living = _living
    unspied = living(30)
    spy = _spied(monkeypatch)
    assert living(30) == unspied
    assert spy.calls > 0 and spy.legs > 0, "nobody walked through the walking module"


def test_a_table_without_walking_stops_the_society_by_name(monkeypatch):
    """The dispatcher, not a fallback: a table that states no walking refuses the walk by name."""

    def without_walking(name):
        if name == WALKING:
            raise UnknownMovementModule(f"unknown movement module {name!r}")
        return built_module(name)

    monkeypatch.setattr(steps, "built_module", without_walking)
    with pytest.raises(UnknownMovementModule, match="walking/v1"):
        run_square(SEEDS[0], 2)


def test_both_societies_record_the_points_the_walking_step_hands_them(monkeypatch):
    """A step that moves every point a millimetre east moves what both societies record: they
    keep the step's points and compute none of their own."""

    def nudged(route, nodes, edges, budget):
        for leg in walking.traverse(route, nodes, edges, budget):
            yield dataclasses.replace(leg, point=[leg.point[0] + 1, *leg.point[1:]])

    square = [society_state_sha256(state) for state in run_square(SEEDS[0], 12)]
    living = _living(30)
    monkeypatch.setattr(steps, "STEPS", MappingProxyType({**steps.STEPS, WALKING: nudged}))
    assert [society_state_sha256(state) for state in run_square(SEEDS[0], 12)] != square
    assert _living(30) != living


def test_both_societies_find_routes_by_the_walking_module():
    from exulanica.world import society_living, society_planner

    assert society_planner._paths is walking.routes_from
    assert society_living.routes_from is walking.routes_from


def test_every_profile_a_row_declares_is_the_one_its_code_reads_or_writes():
    from exulanica.movement.air import AIR_VOLUME_PROFILE, AirVolume
    from exulanica.traffic.network import NETWORK_PROFILE
    from exulanica.traffic.presentation import presentation_frame

    rows = {row.module: row for row in MODULES}
    flight_row, roads_row, walking_row = rows[FLIGHT], rows[ROADS], rows[WALKING]
    volume = AirVolume("declared", 0, 500, 0, 500, 0, 500, 500)
    assert tuple(flight_row.space_profiles) == (AIR_VOLUME_PROFILE,)
    assert volume.document()["profile"] == AIR_VOLUME_PROFILE
    # The traffic package writes its frame's profile as a literal, not a constant.
    assert tuple(roads_row.space_profiles) == (NETWORK_PROFILE,)
    assert f'"profile": "{roads_row.output_profile}"' in inspect.getsource(presentation_frame)
    assert walking_row.output_profile == walking.MOTION_PATH_PROFILE
    assert set(walking_row.space_profiles) == set(NAVIGATION_PROFILES.values()) | set(
        PLACE_PROFILES
    )
