"""A town's served standing spot stays clear of the geometry already generated around it."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import uuid
from pathlib import Path

import pytest
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.composers import city_grammar_town as town
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    LivingPlace,
    initial_living_society,
    town_routine,
)
from exulanica.world.society_walking_surfaces import walking_surfaces_place
from exulanica.world.world_recipes import world_recipe


def _clearance() -> int:
    path = Path(town.__file__).with_name("town-arrival.v1.json")
    return json.loads(path.read_text())["minimum_object_clearance_mm"]


def _resident_clearance() -> int:
    path = Path(town.__file__).with_name("town-arrival.v1.json")
    return json.loads(path.read_text())["minimum_resident_clearance_mm"]


def _plan_distance_to_extent(point: list[int], extent: Extent) -> float:
    x, y = point
    return math.hypot(
        max(extent.min_x_mm - x, 0, x - extent.max_x_mm),
        max(extent.min_y_mm - y, 0, y - extent.max_y_mm),
    )


@pytest.mark.parametrize("preset", ("small_town", "market_town"))
def test_new_town_arrival_is_a_clear_footway_spot_and_receipt_replays(preset):
    recipe = world_recipe(preset)
    composed = compose_generated_world(recipe, f"world:arrival-clearance:{preset}")
    arrival = composed.receipt["arrival"]
    place = walking_surfaces_place("checked", composed.records)
    spot = next(spot for spot in place["spots"] if spot["spot_id"] == arrival["spot_id"])
    assert arrival["spot_id"].startswith("footway:")
    assert spot["destination_ids"] == []
    assert arrival["position_mm"] == spot["position_mm"]
    assert arrival["support_z_mm"] == spot["support_z_mm"]
    assert any(arrival["facing_mm"])
    [spawn] = composed.candidate.placement["destinations"]
    assert (spawn["x_mm"], spawn["y_mm"], spawn["z_mm"]) == (
        arrival["position_mm"][0],
        arrival["support_z_mm"],
        -arrival["position_mm"][1],
    )
    obstacles = (
        record.extent
        for record in composed.records
        if isinstance(record, (StreetFurnitureRecord, StreetTreeRecord))
    )
    nearest = min(_plan_distance_to_extent(arrival["position_mm"], extent) for extent in obstacles)
    assert nearest >= _clearance()
    routine = town_routine()
    living = LivingPlace(
        walking_surfaces_place("checked", composed.records, routine=routine), routine
    )
    identity = f"world:arrival-clearance:{preset}"
    state = initial_living_society(
        uuid.uuid5(uuid.NAMESPACE_URL, identity),
        hashlib.sha256(identity.encode()).hexdigest(),
        living,
        routine,
        branch_id="arrival-test",
        profile=LIVING_TOWN_PROFILE,
    )
    residents = [person["position_mm"] for person in state["inhabitants"]]
    assert residents
    assert (
        min(math.dist(arrival["position_mm"], resident) for resident in residents)
        >= _resident_clearance()
    )
    assert town.records(composed.receipt) == composed.records
    changed = dict(composed.receipt)
    changed["arrival"] = {**arrival, "support_z_mm": arrival["support_z_mm"] + 1}
    with pytest.raises(InvalidStructuralData, match="generated_world_arrival_changed"):
        town.records(changed)


def test_a_bench_nearest_centre_and_a_far_object_centre_do_not_hide_its_extent(monkeypatch):
    monkeypatch.setattr(town, "_facing", lambda _position, _records: [1, 0])
    monkeypatch.setattr(town, "_resident_starts", lambda _place, _routine: [])
    extent = Extent(65_000, 63_500, 0, 67_000, 64_500, 2_500)
    furniture = StreetFurnitureRecord(
        identity="fixture-furniture",
        curb_identity="curb",
        segment_identity="segment",
        item_ordinal=0,
        furniture_class="bench",
        along_mm=0,
        kerb_offset_mm=0,
        x_mm=70_000,
        y_mm=64_000,
        z_mm=0,
        facing_dx_mm=1,
        facing_dy_mm=0,
        parts=(),
        exclusion_radius_mm=0,
        extent=extent,
    )
    place = {
        "spots": [
            {
                "spot_id": "bench:seat:0",
                "position_mm": [64_000, 64_000],
                "destination_ids": ["bench"],
            },
            {"spot_id": "footway:blocked", "position_mm": [64_500, 64_000], "destination_ids": []},
            {"spot_id": "footway:clear", "position_mm": [59_000, 64_000], "destination_ids": []},
        ]
    }
    # The bench seat is nearest the centre. The blocked spot is outside the object's centre,
    # but its occupied shape reaches within the policy clearance of that spot.
    assert (
        town._arrival_v2(place, ((0, 0),), (furniture,), town_routine())["spot_id"]
        == "footway:clear"
    )
    assert town._arrival_v2(place, ((0, 0),), (), town_routine())["spot_id"] == "footway:blocked"


def test_a_resident_start_excludes_the_nearest_footway_spot(monkeypatch):
    monkeypatch.setattr(town, "_facing", lambda _position, _records: [1, 0])
    monkeypatch.setattr(town, "_resident_starts", lambda _place, _routine: [[64_000, 64_000]])
    place = {
        "spots": [
            {"spot_id": "footway:near", "position_mm": [64_500, 64_000], "destination_ids": []},
            {"spot_id": "footway:clear", "position_mm": [61_000, 64_000], "destination_ids": []},
        ]
    }
    assert town._arrival_v2(place, ((0, 0),), (), town_routine())["spot_id"] == "footway:clear"


def test_no_clear_spot_refuses_each_bounded_candidate(monkeypatch):
    def no_spot(_place, _tiles, _records, _routine):
        raise InvalidRecordError("town_arrival_clearance: no clear footway standing spot")

    monkeypatch.setattr(town, "_arrival_v2", no_spot)
    recipe = dataclasses.replace(world_recipe("small_town"), candidates=2)
    with pytest.raises(GeneratedWorldRefused) as caught:
        compose_generated_world(recipe, "world:arrival-clearance:refused")
    assert len(caught.value.refusals) == 2
    assert "town_arrival_clearance" in caught.value.refusals[0]["refusal"]
