"""The generated city as a society place, from the city grammar's own v2 fixture records."""

from __future__ import annotations

import dataclasses
import json
import random
import uuid
from collections import Counter, deque
from itertools import pairwise

import pytest
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import OUTSIDE, point_in_ring
from exulanica.grammar.grammars.city.document import TileDocument
from exulanica.grammar.grammars.city.facade import EntranceRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.world.society_city_place import (
    CORNER_TOLERANCE_MM,
    city_street_names,
    place_from_city_documents,
    place_from_city_records,
)
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_metrics import measure_run
from exulanica.world.society_place import ceil_distance, validate_place

from city_v2_fixture import builder
from society_city_fixtures import (
    busier_document,
    city_catalogs,
    fixture_document,
    of_kind,
    owned_records,
)
from society_living_fixtures import routine

SEED = "5b" * 32


def document_place(document: TileDocument | None = None) -> dict:
    return place_from_city_documents(
        place_id="fixture-tile",
        documents=[document or fixture_document()],
        routine=routine(),
        catalogs=city_catalogs(),
    )


def records_place(records: list) -> dict:
    return place_from_city_records(place_id="fixture-tile", records=records, routine=routine())


def components(document: dict, *, without: frozenset[str] = frozenset()) -> list[set[str]]:
    adjacent: dict[str, set[str]] = {n["node_id"]: set() for n in document["nodes"]}
    for edge in document["edges"]:
        if edge["kind"] not in without:
            adjacent[edge["from_node_id"]].add(edge["to_node_id"])
            adjacent[edge["to_node_id"]].add(edge["from_node_id"])
    parts, seen = [], set()
    for start in sorted(adjacent):
        if start in seen:
            continue
        part, queue = {start}, deque([start])
        while queue:
            for neighbour in adjacent[queue.popleft()]:
                if neighbour not in part:
                    part.add(neighbour)
                    queue.append(neighbour)
        seen |= part
        parts.append(part)
    return parts


def curb(records: list, ordinal: int, side: str) -> CurbEdgeRecord:
    [segment] = [r for r in of_kind(records, StreetSegmentRecord) if r.segment_ordinal == ordinal]
    [found] = [
        r
        for r in of_kind(records, CurbEdgeRecord)
        if r.segment_identity == segment.identity and r.side == side
    ]
    return found


def test_the_fixture_tile_is_a_connected_place_reached_through_doors_corners_and_crossings():
    fixture = builder()
    records = owned_records()
    document = document_place()
    validate_place(document, routine())
    nodes = {n["node_id"]: n for n in document["nodes"]}
    edges = {e["edge_id"]: e for e in document["edges"]}
    destinations = {d["destination_id"]: d for d in document["destinations"]}
    units = {r.use_class: r for r in of_kind(records, PremisesRecord)}
    [bench] = [r for r in of_kind(records, StreetFurnitureRecord) if r.furniture_class == "bench"]
    assert set(destinations) == {f"premises:{r.identity}" for r in units.values()} | {
        f"furniture:{bench.identity}"
    }

    bakery = destinations[f"premises:{units['bakery'].identity}"]
    assert bakery["role"] == {"key": "baker", "label": "baker"}
    assert bakery["shift"] == {"start_minute": 360, "minutes": 480}
    assert bakery["address_number"] == 12 and bakery["street_segment_ordinal"] == 0
    assert bakery["indoors"] and bakery["spot_ids"] == []
    # The bakery lists its service door first, onto the lot; the shop door is the way in.
    assert units["bakery"].entrance_identities[0] == fixture.service_door.identity
    assert bakery["node_id"] == f"entrance:{fixture.shop_door.identity}"
    door = fixture.shop_door
    assert nodes[bakery["node_id"]]["position_mm"] == [door.threshold_x_mm, door.threshold_y_mm]
    [door_edge] = [
        e for e in document["edges"] if bakery["node_id"] in (e["from_node_id"], e["to_node_id"])
    ]
    assert door_edge["kind"] == "premises_access"
    assert f"entrance:{fixture.service_door.identity}" not in nodes
    assert "entrances onto a lot, not a footway (1)" in document["unsupported"]
    flats = destinations[f"premises:{units['residential'].identity}"]
    assert flats["resident_capacity"] == 2 and flats["street_segment_ordinal"] == 2
    seats = destinations[f"furniture:{bench.identity}"]
    assert seats["affordances"] == ["rest"] and len(seats["spot_ids"]) == 2

    crossings = {c["crossing_id"]: c for c in document["crossings"]}
    assert set(crossings) == {r.identity for r in of_kind(records, CrossingRecord)}
    assert {c["signal_id"] for c in crossings.values()} == {fixture.SIGNAL}
    assert {(c["street_segment_ordinal"], c["offset_mm"]) for c in crossings.values()} == {
        (0, 28_000),
        (2, 13_000),
    }
    assert all(edges[c["edge_id"]]["kind"] == "crossing" for c in crossings.values())

    # One place, and without its crossings exactly one walkable piece per block face.
    assert len(components(document)) == 1
    faces = sorted(
        sorted({":".join(n.split(":")[1:3]) for n in part if n.startswith("footway:")})
        for part in components(document, without=frozenset({"crossing"}))
    )
    assert faces == [["0:left", "2:left"], ["0:right", "1:right"], ["1:left", "2:right"]]

    # The corner round the shophouse follows the kerb's arc on the footway, outside the block.
    kerb = curb(records, 0, "left")
    follower = curb(records, 2, "left")
    (px, py, _), (qx, qy, _) = kerb.kerb_line_mm[-1], kerb.kerb_line_mm[-2]
    assert py == qy and px > qx, "the fixture's kerb runs east into the corner"
    centre = (px, py + kerb.corner_radius_mm)
    path = [
        "footway:0:left:30750",
        *sorted(n for n in nodes if n.startswith("corner:0:left:")),
        "footway:2:left:0",
    ]
    assert len(path) > 3
    for a, b in pairwise(path):
        assert f"{min(a, b)}|{max(a, b)}" in edges
    [block] = of_kind(records, BlockRecord)
    widest = max(kerb.footway_width_mm, follower.footway_width_mm)
    for name in path[1:-1]:
        point = nodes[name]["position_mm"]
        distance = ceil_distance(point, centre)
        assert kerb.corner_radius_mm - kerb.kerb_width_mm - widest <= distance
        assert distance <= kerb.corner_radius_mm - kerb.kerb_width_mm
        assert point_in_ring(tuple(point), block.boundary_mm) == OUTSIDE
    for a, b in pairwise(path):
        middle = [
            (nodes[a]["position_mm"][0] + nodes[b]["position_mm"][0]) // 2,
            (nodes[a]["position_mm"][1] + nodes[b]["position_mm"][1]) // 2,
        ]
        inner = min(ceil_distance(nodes[n]["position_mm"], centre) for n in (a, b))
        assert ceil_distance(middle, centre) >= inner - CORNER_TOLERANCE_MM - 2

    # Street names are presentation: nodes name a street's identity and the place holds no name.
    names = city_street_names(fixture_document().grammars[0].records())
    [market] = [
        r
        for r in fixture_document().grammars[0].halo
        if isinstance(r, StreetRecord) and r.name == "market_street"
    ]
    assert names[market.identity] == {"name": "market_street", "name_text": "Market Street"}
    assert nodes[bakery["node_id"]]["street_id"] == market.identity
    assert all(n["street_id"] is None for name, n in nodes.items() if name.startswith("corner:"))
    assert all(n["street_id"] in names for n in nodes.values() if n["street_id"] is not None)
    assert "Market Street" not in json.dumps(document) and "Mill Lane" not in json.dumps(document)


def test_documents_and_their_owned_records_give_one_place_whatever_the_order():
    records = owned_records()
    shuffled = records[:]
    random.Random(7).shuffle(shuffled)
    document = document_place()
    assert records_place(shuffled) == document
    assert records_place([*records, *fixture_document().grammars[0].halo]) == document
    # The input digest covers only the records a place is read from.
    [tree] = of_kind(records, StreetTreeRecord)
    replanted = dataclasses.replace(tree, species="tilia_cordata")
    assert records_place([replanted if r is tree else r for r in records]) == document
    [bench] = [r for r in of_kind(records, StreetFurnitureRecord) if r.furniture_class == "bench"]
    moved = dataclasses.replace(bench, x_mm=bench.x_mm - 100, along_mm=bench.along_mm - 100)
    other = records_place([moved if r is bench else r for r in records])
    assert other["source"]["document_sha256"] != document["source"]["document_sha256"]


def test_a_carriageway_is_crossed_only_on_a_crossing_record():
    document = records_place([r for r in owned_records() if not isinstance(r, CrossingRecord)])
    validate_place(document, routine())
    assert document["crossings"] == []
    assert not any(edge["kind"] == "crossing" for edge in document["edges"])
    assert len(components(document)) == 3


def test_a_unit_with_no_door_onto_a_footway_in_the_place_is_stated_never_given_one():
    fixture = builder()
    records = owned_records()
    units = {r.use_class: r for r in of_kind(records, PremisesRecord)}
    shut = [
        dataclasses.replace(r, approach_curb_identity=())
        if r.identity == fixture.shop_door.identity
        else r
        for r in records
    ]
    document = records_place(shut)
    validate_place(document, routine())
    bakery = units["bakery"].identity
    assert f"premises:{bakery}" not in {d["destination_id"] for d in document["destinations"]}
    stated = document["unsupported"]
    assert f"premises {bakery} has no entrance onto a footway in the place" in stated
    assert "entrances onto a lot, not a footway (2)" in stated
    renamed = [
        dataclasses.replace(r, use_class="laundrette", sign=(), sign_text=())
        if r.identity == units["bookshop"].identity
        else r
        for r in records
    ]
    document = records_place(renamed)
    stated = document["unsupported"]
    assert "premises use class laundrette (1 units) has no routine mapping" in stated
    assert f"premises:{units['bookshop'].identity}" not in {
        d["destination_id"] for d in document["destinations"]
    }


def test_a_corner_onto_a_curb_outside_the_place_ends_the_footway_there():
    records = owned_records()
    [mill] = [r for r in of_kind(records, StreetSegmentRecord) if r.segment_ordinal == 2]
    without = [
        r
        for r in records
        if mill.identity not in (r.identity, getattr(r, "segment_identity", None))
        and not isinstance(r, EntranceRecord | PremisesRecord)
    ]
    document = records_place(without)
    validate_place(document, routine())
    assert "footway corners that continue outside the place (1)" in document["unsupported"]
    assert not any(n["node_id"].startswith("corner:") for n in document["nodes"])
    assert len(components(document)) == 2


def test_documents_are_checked_and_malformed_record_sets_refused_before_a_place_exists():
    document = fixture_document()
    [entry] = document.grammars
    kerb = curb(list(entry.owned), 0, "left")
    tightened = dataclasses.replace(kerb, corner_radius_mm=kerb.corner_radius_mm - 1000)
    broken = TileDocument(
        document.tile,
        (
            dataclasses.replace(
                entry, owned=tuple(tightened if r is kerb else r for r in entry.owned)
            ),
        ),
    )
    with pytest.raises(InvalidRecordError, match="corner_radius"):
        document_place(broken)
    with pytest.raises(ValueError, match="two tiles own record"):
        place_from_city_documents(
            place_id="twice",
            documents=[document, document],
            routine=routine(),
            catalogs=city_catalogs(),
        )
    records = owned_records()
    with pytest.raises(ValueError, match="needs street segments"):
        records_place([r for r in records if not isinstance(r, StreetSegmentRecord)])
    with pytest.raises(ValueError, match="needs curb edges"):
        records_place([r for r in records if not isinstance(r, CurbEdgeRecord)])
    with pytest.raises(ValueError, match="not a city grammar record"):
        records_place([*records, object()])


def test_a_busier_fixture_tile_lives_a_day_of_homes_shifts_meals_and_sleep():
    model = routine()
    document = document_place(busier_document())
    place = LivingPlace(document, model)
    state = initial_living_society(uuid.UUID(int=9), SEED, place, model, branch_id="b")
    assert state["population"]["size"] == 12 and state["population"]["rule"] == "residents"
    roles = Counter(p["role"]["label"] for p in state["inhabitants"])
    assert roles == {"baker": 2, "bookseller": 1, "resident": 9}
    assert all(p["home"] is not None for p in state["inhabitants"])
    assert len(state["relationships"]) == 6
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
            assert sum(p["action"]["kind"] == "sleep" for p in state["inhabitants"]) >= 10
    assert left_home == {p["id"] for p in state["inhabitants"]}
    summary = measure_run(states, document).summary()
    assert summary["over_capacity_ticks"] == 0
    assert summary["stationary_collisions"] == 0
    for key in ("eat_out", "shop", "sleep", "work", "rest"):
        assert summary["activity_share_milli"].get(key, 0) > 0, key
    crossings = [c for e in events for c in e.document["crossings"]]
    assert crossings
    assert all(0 <= c["arrival_second"] <= 59 and c["duration_seconds"] >= 1 for c in crossings)
    published = {c["crossing_id"] for c in document["crossings"]}
    assert {c["crossing_id"] for c in crossings} <= published
    assert all("display_name" not in p for p in state["inhabitants"])
