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
from exulanica.grammar.geometry import OUTSIDE, Extent, point_in_ring
from exulanica.grammar.grammars.city import CITY_GRAMMAR
from exulanica.grammar.grammars.city.document import TileDocument, support_top_mm
from exulanica.grammar.grammars.city.facade import EntranceRecord
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.roads import RoadMarkingRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import (
    KERB_HEIGHT_MAXIMUM_MM,
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.world.society_city_place import (
    CORNER_TOLERANCE_MM,
    city_navigation,
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
from exulanica.world.society_place import (
    PLACE_PROFILE_V2,
    STEP_LIMIT_MM,
    ceil_distance,
    place_stacks_heights,
    seal_place,
    validate_place,
)

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


def records_place(records: list, **options: object) -> dict:
    return place_from_city_records(
        place_id="fixture-tile",
        records=records,
        routine=routine(),
        **options,  # type: ignore[arg-type]
    )


def shifted(extent: Extent, dx: int, dy: int) -> Extent:
    return dataclasses.replace(
        extent,
        min_x_mm=extent.min_x_mm + dx,
        max_x_mm=extent.max_x_mm + dx,
        min_y_mm=extent.min_y_mm + dy,
        max_y_mm=extent.max_y_mm + dy,
    )


def navigation_with(**rows: tuple[str, str]) -> object:
    """The city's own navigation table with some kinds' ground or obstruction words replaced."""
    held = city_navigation()
    ground, obstruction = dict(held.ground), dict(held.obstruction)
    for kind, (field, word) in rows.items():
        (ground if field == "ground" else obstruction)[f"city.{kind}"] = word
    return dataclasses.replace(held, ground=ground, obstruction=obstruction)


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
    # Everyone standing keeps two standing radii from everyone else, seated or not.
    apart = 2 * routine().policy["standing_radius_mm"]
    standing = [spot["position_mm"] for spot in document["spots"]]
    assert all(
        ceil_distance(a, b) >= apart for i, a in enumerate(standing) for b in standing[i + 1 :]
    )
    # A station sits beside its kerb line: the kerb top's width and half the footway away.
    south = curb(records, 0, "left")
    assert nodes["footway:0:left:28000"]["position_mm"] == [
        south.kerb_line_mm[0][0] + 28_000,
        south.kerb_line_mm[0][1] + south.kerb_width_mm + south.footway_width_mm // 2,
    ]

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
    # The input digest covers only the records a place is read from: paint is not one of them.
    [line] = [r for r in of_kind(records, RoadMarkingRecord) if r.marking == "lane_line"]
    repainted = dataclasses.replace(line, marking="edge_line")
    assert records_place([repainted if r is line else r for r in records]) == document
    [bench] = [r for r in of_kind(records, StreetFurnitureRecord) if r.furniture_class == "bench"]
    moved = dataclasses.replace(bench, x_mm=bench.x_mm - 100, along_mm=bench.along_mm - 100)
    other = records_place([moved if r is bench else r for r in records])
    assert other["source"]["document_sha256"] != document["source"]["document_sha256"]


def test_a_carriageway_is_crossed_only_on_a_crossing_record():
    records = owned_records()
    document = records_place([r for r in records if not isinstance(r, CrossingRecord)])
    validate_place(document, routine())
    assert document["crossings"] == []
    assert not any(edge["kind"] == "crossing" for edge in document["edges"])
    assert len(components(document)) == 3
    # A crossing whose line never reaches the far kerb joins nothing.
    crossing = next(r for r in of_kind(records, CrossingRecord) if r.offset_mm == 28_000)
    (x, _, z), (_, near, _) = crossing.line_mm
    short = dataclasses.replace(crossing, line_mm=((x, near - 500, z), (x, near, z)))
    document = records_place([short if r is crossing else r for r in records])
    assert [c["offset_mm"] for c in document["crossings"]] == [13_000]
    assert "crossings that do not join two footways in the place (1)" in document["unsupported"]
    assert len(components(document)) == 2


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


def test_standing_spots_keep_clear_of_what_the_navigation_table_says_obstructs():
    records = owned_records()
    plain = records_place(records)
    spots = {spot["spot_id"]: spot["position_mm"] for spot in plain["spots"]}
    [bench] = [r for r in of_kind(records, StreetFurnitureRecord) if r.furniture_class == "bench"]
    # A seat is inside its own bench and clear of everything else, side by side along the bench.
    seats = sorted(p for k, p in spots.items() if k.startswith(f"furniture:{bench.identity}:seat"))
    assert seats == [[bench.x_mm - 350, bench.y_mm], [bench.x_mm + 350, bench.y_mm]]
    station = "footway:0:left:26357"
    assert station in spots and not any("obstruction" in line for line in plain["unsupported"])

    # A lamp moved onto the footway takes that station's standing spot and blocks the walk past it.
    [lamp] = [
        r for r in of_kind(records, StreetFurnitureRecord) if r.furniture_class == "street_lamp"
    ]
    x, y = spots[station]
    moved = dataclasses.replace(
        lamp, x_mm=x, y_mm=y, extent=shifted(lamp.extent, x - lamp.x_mm, y - lamp.y_mm)
    )
    with_lamp = [moved if r is lamp else r for r in records]
    blocked = records_place(with_lamp)
    validate_place(blocked, routine())
    assert station not in {spot["spot_id"] for spot in blocked["spots"]}
    [walking] = [line for line in blocked["unsupported"] if "obstruction" in line]
    assert walking.startswith("walking pieces that pass within a capsule radius of an obstruction")
    assert int(walking.rsplit("(", 1)[1].rstrip(")")) >= 2
    # The table, not a list of kinds in code, says furniture obstructs.
    unblocked = records_place(
        with_lamp, navigation=navigation_with(street_furniture=("obstruction", "none"))
    )
    assert station in {spot["spot_id"] for spot in unblocked["spots"]}
    assert not any("obstruction" in line for line in unblocked["unsupported"])

    # A building grown to within 100 mm of Mill Lane's footway line takes the spots beside it.
    [building] = of_kind(records, MassingRecord)
    ring = tuple((54_700, py) if px == 53_050 else (px, py) for px, py in building.tiers[0].ring_mm)
    wider = dataclasses.replace(
        building,
        tiers=(dataclasses.replace(building.tiers[0], ring_mm=ring), *building.tiers[1:]),
        extent=dataclasses.replace(building.extent, max_x_mm=54_700),
    )
    beside = records_place([wider if r is building else r for r in records])
    kept = {spot["spot_id"] for spot in beside["spots"]}
    for along in (0, 4178):
        assert f"footway:2:left:{along}" in spots and f"footway:2:left:{along}" not in kept
    assert "footway:2:left:12535" in kept
    assert "footway:2:left:0" in {
        spot["spot_id"]
        for spot in records_place(
            [wider if r is building else r for r in records],
            navigation=navigation_with(massing=("obstruction", "none")),
        )["spots"]
    }


def test_the_navigation_table_decides_what_a_person_may_stand_on():
    records = owned_records()
    with pytest.raises(ValueError, match="lets nobody stand on a curb"):
        records_place(records, navigation=navigation_with(curb_edge=("ground", "none")))
    no_crossings = records_place(records, navigation=navigation_with(crossing=("ground", "none")))
    assert no_crossings["crossings"] == [] and len(components(no_crossings)) == 3
    assert (
        "crossings (the city's navigation table lets nobody stand on one)"
        in no_crossings["unsupported"]
    )
    no_doors = records_place(records, navigation=navigation_with(entrance=("ground", "none")))
    assert not any(d["origin"] == "premises" for d in no_doors["destinations"])
    assert (
        "entrances (the city's navigation table lets nobody stand on one)"
        in no_doors["unsupported"]
    )
    rooftops = records_place(
        records, navigation=navigation_with(rooftop_object=("obstruction", "low_parts"))
    )
    assert (
        "obstructions of city.rooftop_object by low_parts, which this place does not read"
        in rooftops["unsupported"]
    )


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


def lifted(place: dict, changes: dict[str, int]) -> dict:
    """The same place with those nodes standing that much higher, their spots carried with them."""
    copy = json.loads(json.dumps(place))
    for node in copy["nodes"]:
        node["support_z_mm"] += changes.get(node["node_id"], 0)
    for spot in copy["spots"]:
        spot["support_z_mm"] += changes.get(spot["node_id"], 0)
    return seal_place(copy)


def test_every_node_stands_on_a_surface_the_records_themselves_state():
    records = owned_records()
    place = records_place(records)
    assert place["profile"] == PLACE_PROFILE_V2
    assert place["frame"]["vertical_unit"] == "millimetre" and place["frame"]["datum"]
    nodes = {n["node_id"]: n for n in place["nodes"]}
    assert all(node["support_z_mm"] is not None for node in nodes.values())
    assert all(spot["support_z_mm"] is not None for spot in place["spots"])
    footways = 0
    for node_id, node in sorted(nodes.items()):
        if not node_id.startswith("footway:"):
            continue
        footways += 1
        _, ordinal, side, _along = node_id.split(":")
        edge = curb(records, int(ordinal), side)
        floor = min(z for _x, _y, z in edge.kerb_line_mm) + edge.kerb_height_mm
        # The walking line stands on the footway: at or above the kerb top it starts from, at or
        # below the top of the whole strip, which the grammar computes for itself. It is the
        # middle of the footway and not its back edge, so a footway that falls stands below that.
        assert floor <= node["support_z_mm"] <= support_top_mm(edge)
        assert edge.footway_crossfall_millionths == 0 or node["support_z_mm"] < support_top_mm(edge)
    assert footways == sum(1 for name in nodes if name.startswith("footway:"))
    # A door stands on its own threshold, and the step up to it from the footway beneath is the
    # step its record states: the place says so by never saying otherwise.
    doors = 0
    for entrance in of_kind(records, EntranceRecord):
        node = nodes.get(f"entrance:{entrance.identity}")
        if node is None:
            continue
        doors += 1
        assert node["support_z_mm"] == entrance.threshold_z_mm
    assert doors == 3
    assert not any("stated step" in line for line in place["unsupported"])
    assert not place_stacks_heights(place)


def test_a_walking_edge_climbs_at_most_a_step_and_a_stated_step_is_the_records_to_state():
    model = routine()
    place = document_place()
    validate_place(place, model)
    standing = {n["node_id"]: n["support_z_mm"] for n in place["nodes"]}

    def hung(node_id: str, rise: int) -> dict:
        """The place with a node that hangs off one edge standing that far above its other end."""
        [edge] = [e for e in place["edges"] if node_id in (e["from_node_id"], e["to_node_id"])]
        other = edge["from_node_id"] if edge["to_node_id"] == node_id else edge["to_node_id"]
        return lifted(place, {node_id: standing[other] + rise - standing[node_id]})

    # A bench is reached over the footway it stands on, and a door over its own threshold. Each
    # hangs off one edge, so moving it changes that edge's rise and no other's.
    [bench] = [n for n in standing if n.startswith("furniture:")]
    door = next(n for n in standing if n.startswith("entrance:"))
    validate_place(hung(bench, STEP_LIMIT_MM - 1), model)
    validate_place(hung(bench, STEP_LIMIT_MM), model)
    with pytest.raises(ValueError, match="may not climb more than one kerb step"):
        validate_place(hung(bench, STEP_LIMIT_MM + 1), model)
    validate_place(hung(door, 10 * STEP_LIMIT_MM), model)
    # A crossing carries the other stated step. Lifting one side of the street whole leaves every
    # rise inside that side as it was and changes only what the crossings climb.
    side = next(
        part for part in components(place, without=frozenset({"crossing"})) if bench not in part
    )
    lifted_side = lifted(place, dict.fromkeys(side, 2_000))
    raised = {n["node_id"]: n["support_z_mm"] for n in lifted_side["nodes"]}
    climbs = [
        abs(raised[e["from_node_id"]] - raised[e["to_node_id"]])
        for e in lifted_side["edges"]
        if e["kind"] == "crossing" and (e["from_node_id"] in side) != (e["to_node_id"] in side)
    ]
    assert climbs and all(climb > STEP_LIMIT_MM for climb in climbs)
    validate_place(lifted_side, model)


def test_the_step_this_contract_allows_is_the_one_the_city_grammar_publishes():
    # Two sources, neither of them this line: the tallest kerb a curb may have, and the tallest
    # step a door's threshold may stand above the footway.
    assert STEP_LIMIT_MM == KERB_HEIGHT_MAXIMUM_MM
    assert CITY_GRAMMAR.parameters.get("threshold_height_mm").maximum == STEP_LIMIT_MM


def test_plan_keyed_measures_refuse_a_place_that_stands_people_over_each_other():
    model = routine()
    place = document_place()
    assert measure_run([], place).ticks == 0
    copy = json.loads(json.dumps(place))
    ground = next(s for s in copy["spots"] if s["spot_id"].startswith("footway:"))
    deck = dict(
        ground, spot_id=f"{ground['spot_id']}:deck", support_z_mm=ground["support_z_mm"] + 3_000
    )
    copy["spots"].insert(copy["spots"].index(ground) + 1, deck)
    stacked = seal_place(copy)
    # The contract allows it: two spots at one plan point are one spot only at one height.
    validate_place(stacked, model)
    assert place_stacks_heights(stacked)
    with pytest.raises(ValueError, match="this place has levels"):
        measure_run([], stacked)


def test_a_place_may_not_stand_a_person_where_it_states_no_support():
    model = routine()
    place = document_place()
    spot = place["spots"][0]

    def without_support(node_id: str) -> dict:
        copy = json.loads(json.dumps(place))
        for row in [*copy["nodes"], *copy["spots"]]:
            if row.get("node_id") == node_id:
                row["support_z_mm"] = None
        return seal_place(copy)

    with pytest.raises(ValueError, match="may not stand a person where it states no support"):
        validate_place(without_support(spot["node_id"]), model)
    indoors = next(d for d in place["destinations"] if d["indoors"])
    with pytest.raises(ValueError, match="destination is reached at a node that states no support"):
        validate_place(without_support(indoors["node_id"]), model)


def test_a_door_whose_stated_step_is_not_the_footway_beneath_it_is_stated():
    records = owned_records()
    assert not any("stated step" in line for line in records_place(records)["unsupported"])
    [door] = [
        r
        for r in of_kind(records, EntranceRecord)
        if r.approach_curb_identity and r.step_height_mm == 150
    ][:1]
    misread = dataclasses.replace(door, step_height_mm=door.step_height_mm + 1)
    place = records_place([misread if r is door else r for r in records])
    assert (
        "doors whose stated step is not the height of the footway beneath them (1)"
        in place["unsupported"]
    )
    # The door is still a door: the place states the disagreement rather than dropping the unit.
    assert any(d["origin"] == "premises" for d in place["destinations"])


def test_two_footways_meet_at_a_corner_only_while_their_surfaces_are_within_a_step():
    records = owned_records()
    joined = records_place(records)
    edge = curb(records, 0, "left")
    lifted_line = tuple((x, y, z + 4 * STEP_LIMIT_MM) for x, y, z in edge.kerb_line_mm)
    deck = dataclasses.replace(
        edge,
        kerb_line_mm=lifted_line,
        extent=dataclasses.replace(
            edge.extent,
            min_z_mm=edge.extent.min_z_mm + 4 * STEP_LIMIT_MM,
            max_z_mm=edge.extent.max_z_mm + 4 * STEP_LIMIT_MM,
        ),
    )
    place = records_place([deck if r is edge else r for r in records])
    assert (
        "footway corners whose two surfaces stand more than one step apart (1)"
        in place["unsupported"]
    )
    # Lifting the footway carried its door's step with it, and the place says that too rather
    # than publishing a threshold whose stated step is no longer the ground beneath it.
    assert (
        "doors whose stated step is not the height of the footway beneath them (1)"
        in place["unsupported"]
    )
    # The lifted footway is still walked along; it is no longer walked onto.
    assert len(components(place)) > len(components(joined))
    validate_place(place, routine())
