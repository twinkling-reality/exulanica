"""The generated city as a society place, from hand-written grammar records only."""

from __future__ import annotations

import random
import uuid
from collections import Counter, deque
from dataclasses import replace

import pytest
from exulanica.world.society_city_place import place_from_city_records
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_metrics import measure_run
from exulanica.world.society_place import validate_place

from society_city_fixtures import BUILDINGS, city_block_records
from society_living_fixtures import routine

SEED = "5b" * 32


def city_place(records=None):
    return place_from_city_records(
        place_id="fixture-block", records=records or city_block_records(), routine=routine()
    )


def reachable(document, start):
    adjacent = {n["node_id"]: [] for n in document["nodes"]}
    for edge in document["edges"]:
        adjacent[edge["from_node_id"]].append(edge["to_node_id"])
        adjacent[edge["to_node_id"]].append(edge["from_node_id"])
    seen, queue = {start}, deque([start])
    while queue:
        for neighbour in adjacent[queue.popleft()]:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def test_city_records_become_a_connected_place_with_premises_and_a_crossing():
    document = city_place()
    validate_place(document, routine())
    destinations = {d["destination_id"]: d for d in document["destinations"]}
    assert len(destinations) == 14
    bakery = destinations[f"premises:{BUILDINGS[0]}:0"]
    assert bakery["role"] == {"key": "baker", "label": "baker"}
    assert bakery["shift"] == {"start_minute": 360, "minutes": 480}
    assert bakery["address_number"] == 12 and bakery["street_segment_ordinal"] == 0
    assert (
        bakery["indoors"]
        and bakery["spot_ids"] == []
        and bakery["node_id"].startswith("footway:0:left:")
    )
    bench = destinations["furniture:0"]
    assert bench["affordances"] == ["rest"] and len(bench["spot_ids"]) == 2
    assert "furniture:1" not in destinations
    assert any("laundrette (1 units)" in line for line in document["unsupported"])
    assert any("premises entrances" in line for line in document["unsupported"])
    [crossing] = document["crossings"]
    edge = next(e for e in document["edges"] if e["edge_id"] == crossing["edge_id"])
    assert edge["kind"] == "crossing" and edge["length_mm"] == 2 * 5300
    names = {n["node_id"] for n in document["nodes"]}
    assert reachable(document, next(iter(names))) == names
    pairs = {frozenset((e["from_node_id"], e["to_node_id"])) for e in document["edges"]}
    assert frozenset(("footway:0:left:100000", "footway:1:left:0")) in pairs
    assert frozenset(("footway:0:right:100000", "footway:1:right:0")) in pairs
    assert frozenset(("footway:0:left:100000", "footway:1:right:0")) not in pairs


def test_city_place_ignores_record_order_and_splits_without_a_crossing():
    records = city_block_records()
    shuffled = records[:]
    random.Random(7).shuffle(shuffled)
    assert city_place(shuffled) == city_place(records)
    no_crossing = [
        replace(r, crossing_offsets_mm=()) if hasattr(r, "crossing_offsets_mm") else r
        for r in records
    ]
    document = city_place(no_crossing)
    assert document["crossings"] == []
    names = {n["node_id"] for n in document["nodes"]}
    assert reachable(document, "footway:0:left:0") < names


def test_city_day_follows_homes_shifts_meals_and_sleep():
    model = routine()
    document = city_place()
    place = LivingPlace(document, model)
    state = initial_living_society(uuid.UUID(int=9), SEED, place, model, branch_id="b")
    assert state["population"]["size"] == 18 and state["population"]["rule"] == "residents"
    roles = Counter(p["role"]["label"] for p in state["inhabitants"])
    assert roles == {
        "office worker": 8,
        "grocery clerk": 3,
        "baker": 2,
        "barista": 2,
        "resident": 3,
    }
    assert all(p["home"] is not None for p in state["inhabitants"])
    assert len(state["relationships"]) == 9
    workers = {p["id"] for p in state["inhabitants"] if p["work"]}
    states, events, left_home = [], [], set()
    for tick in range(1, 1441):
        state, produced = advance_living_society(state, SEED, [place], model)
        states.append(state)
        events.extend(produced)
        left_home.update(p["id"] for p in state["inhabitants"] if not p["location"]["indoors"])
        if tick == 180:
            at_work = {p["id"] for p in state["inhabitants"] if p["action"]["kind"] == "work"}
            assert at_work == workers
        if tick == 1140:
            assert sum(p["action"]["kind"] == "sleep" for p in state["inhabitants"]) >= 16
    assert left_home == {p["id"] for p in state["inhabitants"]}
    summary = measure_run(states, document).summary()
    assert summary["over_capacity_ticks"] == 0
    assert summary["stationary_collisions"] == 0
    for key in ("eat_out", "shop", "sleep", "work", "rest"):
        assert summary["activity_share_milli"].get(key, 0) > 0, key
    crossings = [c for e in events for c in e.document["crossings"]]
    assert crossings
    assert all(0 <= c["arrival_second"] <= 59 and c["duration_seconds"] >= 1 for c in crossings)
    assert {c["crossing_id"] for c in crossings} == {"crossing:0:50000"}
    assert all("display_name" not in p for p in state["inhabitants"])


def test_unknown_street_nodes_and_empty_cities_are_refused():
    records = [r for r in city_block_records() if type(r).__name__ != "StreetNodeRecord"]
    with pytest.raises(ValueError, match="unknown street node"):
        city_place(records)
    with pytest.raises(ValueError, match="needs street segments"):
        city_place([r for r in records if type(r).__name__ != "StreetSegmentRecord"])
