"""A saved world starts with a handful of inhabitants, none of them where a person arrives.

A saved world's walkable area is a square about 23 metres across with 121 places to stand. A
society sized for a district (128 people) overlaps there from the first minute, so a society on a
saved world's own ground starts with ``AUTHORED_GROUND_POPULATION`` people, spread across the
area, none on or within two metres of the arrival point. The arrival point is in the society's
first input, so replay starts everybody in the same places. A district keeps its population and
its floor of 100, which the initializer holds now that the database cannot tell the two apart.
"""

from __future__ import annotations

import copy
import math
import uuid

import psycopg
import pytest
from exulanica.world import society_repository
from exulanica.world.society_authored_ground import AUTHORED_GROUND_POPULATION
from exulanica.world.society_planner import (
    ARRIVAL_CLEARANCE_MM,
    initial_purposeful_society,
    input_sha256,
    validate_input_successor,
)
from exulanica.world.starter import AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Z_MM

import test_society_authored_ground as authored
import test_society_authored_world_postgres as saved
import test_society_runtime as district

saved_world = saved.saved_world
runtime_world = district.runtime_world
SEED = "7a" * 32
SOCIETY = uuid.UUID("5f0c7a2e-1b3d-4c5e-8f60-718293a4b5c6")
ARRIVAL = (AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Z_MM)
FACING_THE_PERSON = 3_141_593


def world_input(area):
    return authored.compose(
        area,
        authored.version(
            authored.placed("object:cushion", authored.PLATE, 3_000, 5_000),
        ),
    )


AREAS = pytest.mark.parametrize(
    "area", [authored.ground(), authored.endless()], ids=["bounded", "endless"]
)


@AREAS
def test_a_saved_world_input_states_where_a_person_arrives(area):
    document = world_input(area)
    assert document["navigation"]["arrival_mm"] == list(ARRIVAL) == [0, 4_000]
    assert area.document()["arrival_mm"] == [0, 4_000]


@AREAS
def test_where_a_person_arrives_cannot_move_under_a_society(area):
    first = world_input(area)
    moved = copy.deepcopy(first)
    moved["input_seq"] = 2
    moved["navigation"]["arrival_mm"] = [2_000, 4_000]
    moved["document_sha256"] = input_sha256(moved)
    with pytest.raises(ValueError, match="immutable arrival_mm"):
        validate_input_successor(first, moved)
    kept = copy.deepcopy(first)
    kept["input_seq"] = 2
    kept["document_sha256"] = input_sha256(kept)
    validate_input_successor(first, kept)


def _start_nodes(state):
    return [person["location"]["node_id"] for person in state["inhabitants"]]


@AREAS
def test_eight_people_start_spread_out_and_clear_of_the_arrival_the_same_way_each_time(area):
    document = world_input(area)
    state = initial_purposeful_society(
        SOCIETY, SEED, document, population=AUTHORED_GROUND_POPULATION
    )
    assert AUTHORED_GROUND_POPULATION == 8
    assert len(state["inhabitants"]) == 8
    for person in state["inhabitants"]:
        x_mm, z_mm = person["position_mm"]
        assert math.hypot(x_mm - ARRIVAL[0], z_mm - ARRIVAL[1]) > ARRIVAL_CLEARANCE_MM, person
    assert len(set(_start_nodes(state))) == 8
    again = initial_purposeful_society(
        SOCIETY, SEED, document, population=AUTHORED_GROUND_POPULATION
    )
    assert _start_nodes(again) == _start_nodes(state)
    # What the rule prevents: in plain node order the third starting place is the arrival point.
    first_eight = sorted(node["node_id"] for node in document["navigation"]["nodes"])[:8]
    assert "ground:+00000000:+00004000" in first_eight


def test_a_measurement_can_set_another_population_and_nobody_still_starts_at_the_arrival():
    document = world_input(authored.endless())
    state = initial_purposeful_society(SOCIETY, SEED, document, population=128)
    assert len(state["inhabitants"]) == 128
    assert all(
        math.hypot(p["position_mm"][0] - ARRIVAL[0], p["position_mm"][1] - ARRIVAL[1])
        > ARRIVAL_CLEARANCE_MM
        for p in state["inhabitants"]
    )


def test_a_saved_world_society_starts_with_eight_and_replays_them(saved_world):
    world = saved_world
    saved.place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    # Turned to face the person who placed it, as placing one in front of yourself does.
    objects = world["objects"]
    version = objects.version(world["binding"].version_id)
    objects.add_object(
        version.version_id,
        saved.AuthoredObject(
            object_id="object:facing",
            asset_sha256=world["plate"].content_sha256,
            region_id=world["binding"].region_id,
            transform=saved.Transform(
                x_mm=-3_000,
                y_mm=0,
                z_mm=-5_000,
                yaw_microradians=FACING_THE_PERSON,
                scale_milli=1000,
            ),
            origin=saved.ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=version.state_sha256,
        actor=world["session"].actor,
    )
    society, _ = saved.create_society(world)
    assert society["population_size"] == 8
    assert len(society["state"]["inhabitants"]) == 8
    for person in society["state"]["inhabitants"]:
        x_mm, z_mm = person["position_mm"]
        assert math.hypot(x_mm - ARRIVAL[0], z_mm - ARRIVAL[1]) > ARRIVAL_CLEARANCE_MM
    advanced = saved.society_repository(world).advance(
        world["binding"].version_id,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )
    replay = saved.society_repository(world).replay(world["binding"].version_id)
    assert replay["replay_verified"] and replay["state_sha256"] == advanced["state_sha256"]


def test_a_legacy_society_still_needs_a_hundred_people_in_the_database(saved_world):
    world = saved_world
    connection = world["connection"]
    with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
        connection.execute(
            "insert into world_society(workspace_id,world_id,version_id,place_id,region_id,"
            "engine_version,seed,population_size,tick_seconds,state,state_sha256,created_by) "
            "values(%s,%s,%s,%s,%s,'exulanica-society/v1',%s,8,60,'{}'::jsonb,%s,%s)",
            (
                world["workspace"],
                world["world_id"],
                world["binding"].version_id,
                world["binding"].place_id,
                world["binding"].region_id,
                SEED,
                "0" * 64,
                world["session"].actor,
            ),
        )
    assert refused.value.diag.constraint_name == "world_society_population_size_check"


@pytest.mark.parametrize("profile", ["exulanica-society/v2", "exulanica-society/v3"])
def test_a_district_society_under_a_hundred_is_refused_through_the_repository(
    runtime_world, monkeypatch, profile
):
    """The database accepts 1 to 512 for v2 and v3; the district's floor is the initializer's."""
    w = runtime_world
    monkeypatch.setattr(society_repository, "SOCIETY_POPULATION", 50)
    b = w["binding"]
    with pytest.raises(ValueError, match="between 100 and 512"):
        district.society(w).create(
            b.version_id,
            place_id=b.place_id,
            region_id=b.region_id,
            seed=SEED,
            actor=w["session"].actor,
            profile=profile,
            initial_input=district.initial(w),
        )
    assert (
        w["connection"]
        .execute("select count(*) as n from world_society where workspace_id=%s", (w["workspace"],))
        .fetchone()["n"]
        == 0
    )


def test_without_the_initializer_floor_nothing_else_refuses_a_small_district(
    runtime_world, monkeypatch
):
    """The control for the test above: remove the floor and the database lets 50 through."""
    from exulanica.world import society_planner

    w = runtime_world
    monkeypatch.setattr(society_repository, "SOCIETY_POPULATION", 50)
    monkeypatch.setattr(society_planner, "DISTRICT_MINIMUM_POPULATION", 1)
    b = w["binding"]
    created = district.society(w).create(
        b.version_id,
        place_id=b.place_id,
        region_id=b.region_id,
        seed=SEED,
        actor=w["session"].actor,
        profile="exulanica-society/v2",
        initial_input=district.initial(w),
    )
    assert created["population_size"] == 50
