"""No vehicle is admitted to a junction, or keeps its reservation, behind a vehicle it cannot pass.

In a generated market town at a 600 second departure window, a car was admitted to a junction
while a bicycle leaving a cycle stand stood on the lane between the car and its stop line. The
bicycle then reached the line and waited for room beyond the junction that the car's reservation
held, the car waited behind the bicycle, the queue behind them grew, and nothing moved after
second 751 (finding 87). The rule in ``exulanica/traffic/simulation.py`` (``_vehicle_ahead``):
a vehicle with another vehicle ahead of it before the stop line, one that holds no reservation of
that junction, is not admitted, and a reservation whose holder can still stop is revoked while one
is there, so it waits outside the junction.

The town is the one the lock was measured in; the control arm runs it with the rule switched off
and must lock, so this test fails if the town ever stops exercising the defect.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from exulanica.traffic import simulation
from exulanica.world import traffic_episodes
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.traffic_episodes import prepared, traffic_input
from exulanica.world.world_recipes import load_world_recipes

#: Where the lock was measured (lane W5's departures sample): the preset, the world identity and
#: the departure window it locked at.
PRESET = "market_town"
WORLD_ID = "world:generated:departures-4"
DEPARTURE_STEPS = 600
#: The recipe catalog version the town was made under when the lock was measured: specification
#: v2 (recipe catalog version 3) draws every preset town afresh, so the town is read at version 2.
RECIPE_CATALOG_VERSION = 2
#: The reasons a trip is refused as it is requested (simulation._start_trip); a trip blocked for
#: any other reason waited past the stall limit.
_START_REASONS = frozenset(
    {
        "unknown_vehicle",
        "vehicle_busy",
        "unknown_space",
        "space_does_not_fit_class",
        "destination_space_taken",
        "no_parking_at_destination",
        "no_route",
    }
)


def _episode(monkeypatch, guard) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    """Episode 0 of the town with ``guard`` as the rule: its trip summary, how many times the
    rule held a vehicle, and the revocations it made."""
    [recipe] = [
        recipe
        for recipe in load_world_recipes(catalog_version=RECIPE_CATALOG_VERSION)
        if recipe.key == PRESET
    ]
    composed = compose_generated_world(recipe, WORLD_ID)
    value = traffic_input(
        world_id=WORLD_ID,
        version_id=composed.receipt_sha256,
        city_identity=composed.receipt["subject_identity"],
        grammar_version=composed.receipt["grammar"]["grammar_version"],
        records=composed.records,
    )
    held = 0
    revoked: list[dict[str, Any]] = []

    def counted(*args: Any) -> bool:
        nonlocal held
        found = guard(*args)
        held += found
        return found

    real_advance = simulation.advance_traffic

    def advance(*args: Any):
        step = real_advance(*args)
        revoked.extend(
            event["document"]
            for event in step.events
            if event["document"]["kind"] == "reservation_revoked"
            and event["document"]["reason"] == "vehicle_ahead"
        )
        return step

    monkeypatch.setattr(traffic_episodes, "_DEPARTURE", DEPARTURE_STEPS)
    monkeypatch.setattr(simulation, "_vehicle_ahead", counted)
    monkeypatch.setattr(traffic_episodes, "advance_traffic", advance)
    _states, _trips, summary = traffic_episodes._home_trip_rule(value, prepared(value), 0)
    return summary, held, revoked


def _stalled(summary: dict[str, Any]) -> int:
    return sum(
        count for reason, count in summary["blocked"].items() if reason not in _START_REASONS
    )


@pytest.mark.parametrize("arm", ["rule switched off", "rule"])
def test_a_vehicle_behind_one_it_cannot_pass_waits_outside_the_junction(monkeypatch, arm):
    real = simulation._vehicle_ahead
    if arm == "rule switched off":
        # The control: without the rule the measured town locks, so the town still exercises the
        # defect the rule removes.
        summary, _held, _revoked = _episode(monkeypatch, lambda *_args: False)
        assert _stalled(summary) > 0, summary
        return
    summary, held, _revoked = _episode(monkeypatch, real)
    assert held > 0, "the rule never held a vehicle in the town it was measured in"
    assert _stalled(summary) == 0, summary
    assert summary["arrived"] == summary["requested"], summary
    assert summary["unfinished"] == 0, summary


def _seconds(label: str):
    """Each second of a fixture run, as a step whose indexes are built as a second builds them
    before it releases, revokes and admits."""
    from traffic_scenarios import build_scenario, fixture

    network, catalogs = fixture()
    scenario = build_scenario(label, demand_seconds=240, run_seconds=240, pedestrians=False)
    state = scenario.initial
    for _ in range(scenario.run_seconds):
        vehicles, trips = simulation._read_state(state, scenario.seed, network, catalogs)
        second = state["second"]
        step = simulation._Step(
            network=network,
            catalogs=catalogs,
            second=second,
            traffic_id=state["traffic_id"],
            vehicles={vehicle.vehicle_id: vehicle for vehicle in vehicles},
            trips={trip.trip_id: trip for trip in trips},
            occupancies=scenario.inputs.occupancies(scenario.inputs.feeds_needed(second)),
        )
        step.index_bands()
        step.index_bodies()
        step.index_holders()
        yield step
        state = simulation.advance_traffic(
            state, scenario.seed, network, catalogs, scenario.inputs
        ).state


def _copy(step):
    """The step with copies of its vehicles, so what a control arm decides leaves it as it was."""
    copied = simulation._Step(
        network=step.network,
        catalogs=step.catalogs,
        second=step.second,
        traffic_id=step.traffic_id,
        vehicles={key: dataclasses.replace(vehicle) for key, vehicle in step.vehicles.items()},
        trips=step.trips,
        occupancies=step.occupancies,
    )
    copied.band_windows, copied.bodies = step.band_windows, step.bodies
    copied.index_holders()
    return copied


def _plant_ahead(step, vehicle, lane: str, gate_position: int) -> bool:
    """Stand another unreserved vehicle's body on ``lane`` just ahead of ``vehicle``, before the
    line, as a vehicle leaving a space there would; False when there is no room for one."""
    other = next(
        item
        for item in step.vehicles.values()
        if item.reservation is None and item.vehicle_id != vehicle.vehicle_id
    )
    front = vehicle.position if vehicle.path == lane else 0
    ahead = front + vehicle.vehicle_class.minimum_gap_mm + other.length
    if ahead >= gate_position:
        return False
    step.bodies[lane] = sorted(
        [*step.bodies.get(lane, []), (ahead - other.length, ahead, other.vehicle_id)]
    )
    return True


def test_a_reservation_held_behind_a_vehicle_that_pulled_out_ahead_is_revoked():
    """A vehicle holding its junction reservation, still able to stop, finds another standing
    ahead of it before the line, as one leaving a space would: the reservation is revoked by that
    reason. The control: the same second without the vehicle ahead keeps the reservation."""
    for step in _seconds("vehicle-ahead-revoked"):
        for holder in (step.vehicles[key] for key in sorted(step.vehicles)):
            held = holder.reservation
            if held is None or held.kind != "junction" or holder.path != held.gate_path:
                continue
            stopping = simulation.stopping_distance(
                holder.speed, holder.vehicle_class.deceleration_mm_per_s2
            )
            if held.gate_position - holder.position <= stopping:
                continue
            control = _copy(step)
            simulation._release_and_revoke(control)
            if control.vehicles[holder.vehicle_id].reservation is None:
                # Revoked for another reason this second: not one that can show this rule.
                continue
            if not _plant_ahead(step, holder, held.gate_path, held.gate_position):
                continue
            simulation._release_and_revoke(step)
            assert holder.reservation is None
            [revoked] = [
                event
                for event in step.events
                if event["kind"] == "reservation_revoked"
                and event["vehicle_id"] == holder.vehicle_id
            ]
            assert revoked["reason"] == "vehicle_ahead"
            return
    raise AssertionError("no second of the fixture run holds a reservation that can show the rule")


def test_a_vehicle_with_another_standing_ahead_of_it_before_the_line_is_not_admitted():
    """A vehicle its junction admits this second (the control) is not admitted when another
    stands between it and the line, and waits with that reason."""
    for step in _seconds("vehicle-ahead-admitted"):
        control = _copy(step)
        simulation._admit(control)
        granted = sorted(
            vehicle_id
            for vehicle_id, vehicle in control.vehicles.items()
            if vehicle.reservation is not None
            and vehicle.reservation.kind == "junction"
            and step.vehicles[vehicle_id].reservation is None
        )
        for vehicle_id in granted:
            vehicle = step.vehicles[vehicle_id]
            gate, _index, _distance = step.next_gate(vehicle)
            if not _plant_ahead(step, vehicle, gate.path_id, gate.position):
                continue
            simulation._admit(step)
            assert vehicle.reservation is None
            assert step.denials[vehicle_id] == "vehicle_ahead"
            return
    raise AssertionError("no second of the fixture run admits a vehicle that can show the rule")
