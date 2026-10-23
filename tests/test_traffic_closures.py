"""A thing in the road under traffic rules 2: what placed things standing on a lane close.

A placed object that blocks walking and stands on a traffic lane closes that lane path (the
stretch between its two junctions) and the spaces it stands in or that are reached from it; routes
avoid what is closed, so an episode computed with the closure drives no vehicle through the thing,
where the open network drove one there. Across every lane of a street it closes the street. A
footprint off the lanes closes nothing, and an input with no obstacle keeps the first input profile
and its bytes, so a town made under rules 1, or one with nothing on its lanes, keeps its traffic.
"""

from __future__ import annotations

import hashlib
import types
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.roads import JunctionRecord, LaneRecord
from exulanica.traffic.closures import (
    CLOSURES_PROFILE,
    CONNECTION_CLOSURES_PROFILE,
    close_network,
)
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.routing import plan_route
from exulanica.world import traffic_episodes, traffic_host
from exulanica.world.traffic_closures import (
    CLOSING_RULES,
    JUNCTION_RULES,
    TRAFFIC_RULES,
    closed_connections,
    closures,
    obstacles_on_lanes,
    traffic_rules_of,
)
from exulanica.world.traffic_episodes import (
    CLOSING_INPUT_PROFILE,
    EPISODE,
    JUNCTION_INPUT_PROFILE,
    MODES,
    compute_episode,
    from_wire,
    window_of,
    wire,
    with_obstacles,
)

import traffic_corridor_support as corridor

#: Half the side of the square thing placed in the road, millimetres: a bench's depth, about.
HALF = 300
#: The longest window the roads module serves.
WINDOW = 60


def _square(centre: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    """A thing's footprint in the region's frame (east, south) about a plan point (east, north)."""
    x, y = centre
    return (
        (x - HALF, -y - HALF),
        (x + HALF, -y - HALF),
        (x + HALF, -y + HALF),
        (x - HALF, -y + HALF),
    )


def _inside(point: list[int], centre: tuple[int, int]) -> bool:
    return abs(point[0] - centre[0]) <= HALF and abs(point[1] - centre[1]) <= HALF


def _axles(value, episode) -> list[tuple[str, list[int]]]:
    """Every driving vehicle's front and rear axle, every second of one episode."""
    found = []
    for start in range(0, EPISODE, WINDOW):
        window = window_of(value, {0: episode}, start, WINDOW)
        for row in window["vehicles"]:
            for offset in range(WINDOW):
                if MODES[row["mode"][offset]] != "driving":
                    continue
                for field in ("front_axle_mm", "rear_axle_mm"):
                    found.append((row["vehicle_id"], row[field][2 * offset : 2 * offset + 2]))
    return found


@pytest.fixture(scope="module")
def driven():
    """The open corridor's first episode, and a point of a traffic lane a vehicle drives through."""
    value = corridor.value()
    episode = compute_episode(wire(value), 0)
    lanes = [r for r in corridor.records() if isinstance(r, LaneRecord)]
    network = corridor.prepared().network
    for _, point in _axles(value, episode):
        centre = (point[0], point[1])
        closed, _ = closures(
            network, corridor.records(), obstacles_on_lanes(lanes, [_square(centre)])
        )
        if len(closed) == 1:
            return episode, centre, closed[0]
    raise AssertionError("no vehicle drove a single traffic lane in the open corridor")


def test_a_town_pins_its_traffic_rules_and_one_that_pins_none_keeps_rules_1():
    assert traffic_rules_of({}) == 1
    assert traffic_rules_of({"traffic_rules": 2}) == 2
    for wrong in (0, "2", 2.0, None):
        with pytest.raises(ValueError):
            traffic_rules_of({"traffic_rules": wrong})


def test_an_input_with_no_obstacle_keeps_the_first_profile_and_its_bytes():
    value = corridor.value()
    again = with_obstacles(value, (), line_version="a version")
    assert again.sha256 == value.sha256 and again.obstacles == ()
    assert again.line_version == "a version" and value.line_version == ""
    assert wire(again) == wire(value) and "obstacles" not in wire(value)
    # Stored sealed minutes bind first-profile digests: these are the corridor's as main computed
    # them before traffic rules 2 (58d836c04), so a change that moves every such digest fails here.
    assert value.sha256 == "4a9036a9c7eca1dbaee4104dab7c110908f1f366d6e6db1588b402b9116df960"
    assert hashlib.sha256(canonical_json(wire(value))).hexdigest() == (
        "73b6a752b5ca02318a7e49e3000ae853ad6f81adb7961f0fc689640897e4d9ca"
    )


def test_towns_read_in_turn_make_each_town_once_whatever_their_versions_read(monkeypatch):
    """Reading a version keeps no second entry beside its town's input, so as many rules-2 towns as
    the inputs kept are read in turn, round after round, with each town's records made once."""
    base = corridor.value()
    made = {"town_records": 0}

    def receipt_of(world_id):
        receipt = {
            "grammar": {"grammar_version": base.grammar_version},
            "subject_identity": base.city_identity,
            "traffic_rules": 2,
        }
        return hashlib.sha256(world_id.encode()).hexdigest(), receipt

    def town_records(connection, workspace_id, world_id, snapshot_id):
        made["town_records"] += 1
        sha256, receipt = receipt_of(world_id)
        return types.SimpleNamespace(
            records=corridor.records(), receipt=receipt, receipt_sha256=sha256
        )

    monkeypatch.setattr(traffic_host, "states_records", lambda *args: True)
    monkeypatch.setattr(
        traffic_host, "generation_receipt", lambda c, w, world_id, s: receipt_of(world_id)
    )
    monkeypatch.setattr(traffic_host, "town_records", town_records)
    monkeypatch.setattr(traffic_host, "_inputs", type(traffic_host._inputs)())
    monkeypatch.setattr(traffic_host, "_version_inputs", type(traffic_host._version_inputs)())
    workspace = uuid.uuid4()
    towns = [
        (
            f"world:in-turn-{index}",
            types.SimpleNamespace(
                source_snapshot_id=uuid.uuid4(), version_id=uuid.uuid4(), edit_seq=1
            ),
        )
        for index in range(traffic_host._INPUT_LIMIT)
    ]
    for _round in range(3):
        for world_id, version in towns:
            value, seq = traffic_host.version_world_roads(None, workspace, world_id, version, ())
            assert value.line_version == str(version.version_id) and seq == 1
    assert made["town_records"] == len(towns)


def test_a_footprint_off_the_lanes_closes_nothing():
    records = corridor.records()
    far = max(abs(x) for r in records if isinstance(r, LaneRecord) for x, _, _ in r.centreline_mm)
    assert obstacles_on_lanes(records, [_square((far + 50_000, 0))]) == ()


def test_a_thing_on_a_lane_closes_its_stretch_and_the_spaces_reached_from_it(driven):
    _, centre, lane = driven
    network = corridor.prepared().network
    obstacles = obstacles_on_lanes(corridor.records(), [_square(centre)])
    closed_lanes, closed_spaces = closures(network, corridor.records(), obstacles)
    shut = close_network(network, closed_lanes, closed_spaces)
    assert shut.paths[lane].classes == () and network.paths[lane].classes
    for path in shut.paths.values():
        if lane in path.successors or lane in path.predecessors:
            assert path.kind == "lane" or path.classes == (), path.path_id
    assert all(space.access_path != lane for space in shut.spaces.values())
    assert set(shut.spaces) <= set(network.spaces) - set(closed_spaces)
    assert shut.document["closures"] == {
        "profile": CLOSURES_PROFILE,
        "lanes": [lane],
        "spaces": sorted(closed_spaces),
    }
    assert shut.digest != network.digest
    # Every route between two spaces of the closed network keeps off what is closed.
    classes = corridor.prepared().catalogs
    car = classes.vehicle_class("passenger_car")
    spaces = [s for s in shut.spaces.values() if "passenger_car" in s.classes][:12]
    routed = 0
    for origin in spaces:
        for target in spaces:
            if origin is target:
                continue
            route = plan_route(
                shut,
                car,
                origin.access_path,
                origin.access_end,
                target.access_path,
                target.access_start,
            )
            if route is not None:
                routed += 1
                assert all(shut.paths[path].classes for path in route)
    assert routed, "the closed network still routes between its spaces"


def test_closing_what_the_network_does_not_hold_is_refused():
    network = corridor.prepared().network
    assert close_network(network, ()) is network
    with pytest.raises(UnsupportedNetworkError):
        close_network(network, ["lane:no such lane"])
    with pytest.raises(UnsupportedNetworkError):
        close_network(network, (), ["no such space"])


def test_an_episode_with_the_thing_drives_no_vehicle_through_it(driven):
    episode, centre, _ = driven
    value = corridor.value()
    assert any(_inside(point, centre) for _, point in _axles(value, episode))
    obstacles = obstacles_on_lanes(corridor.records(), [_square(centre)])
    closed = with_obstacles(value, obstacles, line_version="a version")
    assert closed.sha256 != value.sha256 and closed.seed == value.seed
    assert from_wire(wire(closed)) == closed.__class__(**{**_fields(closed), "line_version": ""})
    ready = traffic_episodes.prepared(closed)
    assert ready.network.document["closures"]["lanes"]
    after = compute_episode(wire(closed), 0)
    assert after.input_sha256 == closed.sha256 and after.network_sha256 == ready.network.digest
    assert not any(_inside(point, centre) for _, point in _axles(closed, after))


def test_the_closing_input_names_its_profile_and_its_obstacles(driven):
    _, centre, _ = driven
    obstacles = obstacles_on_lanes(corridor.records(), [_square(centre)])
    closed = with_obstacles(corridor.value(), obstacles, line_version="a version")
    assert closed.obstacles == obstacles
    assert wire(closed)["obstacles"] == [[list(point) for point in ring] for ring in obstacles]
    moved = with_obstacles(
        corridor.value(),
        obstacles_on_lanes(corridor.records(), [_square((centre[0] + 1, centre[1]))]),
        line_version="a version",
    )
    assert moved.sha256 != closed.sha256, "a move is the version's next traffic"
    assert CLOSING_INPUT_PROFILE == "exulanica.traffic-input/v2"


def test_a_thing_across_every_lane_of_a_street_closes_the_street(driven):
    _, _, lane = driven
    network = corridor.prepared().network
    segment = network.paths[lane].segment
    lanes = [
        r
        for r in corridor.records()
        if isinstance(r, LaneRecord)
        and f"lane:{r.identity}" in network.paths
        and network.paths[f"lane:{r.identity}"].segment == segment
    ]
    # One footprint per lane of the street at its middle: the street's whole width covered.
    footprints = []
    for record in lanes:
        line = record.centreline_mm
        x, y, _ = line[len(line) // 2]
        footprints.append(_square((x, y)))
    obstacles = obstacles_on_lanes(corridor.records(), footprints)
    closed_lanes, _ = closures(network, corridor.records(), obstacles)
    street = {f"lane:{record.identity}" for record in lanes}
    assert street <= set(closed_lanes)
    shut = close_network(network, closed_lanes)
    assert all(shut.paths[path].classes == () for path in street)


def _fields(value) -> dict:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


# -- a thing inside a junction (traffic rules 3) --------------------------------------------------


@pytest.fixture(scope="module")
def junction_driven():
    """A point inside a junction of the open corridor, off every lane, that a vehicle drives through
    on a lane connection in the first episode."""
    value = corridor.value()
    episode = compute_episode(wire(value), 0)
    records = corridor.records()
    for _, point in _axles(value, episode):
        centre = (point[0], point[1])
        square = _square(centre)
        if obstacles_on_lanes(records, [square]) == () and obstacles_on_lanes(
            records, [square], JUNCTION_RULES
        ):
            return episode, centre
    raise AssertionError("no vehicle drove a junction off its lanes in the open corridor")


def test_a_thing_inside_a_junction_is_an_obstacle_only_under_rules_3(junction_driven):
    _, centre = junction_driven
    records = corridor.records()
    assert obstacles_on_lanes(records, [_square(centre)], CLOSING_RULES) == ()
    assert len(obstacles_on_lanes(records, [_square(centre)], JUNCTION_RULES)) == 1
    assert TRAFFIC_RULES == JUNCTION_RULES == 3


def test_a_thing_inside_a_junction_closes_the_connections_it_stands_on_and_no_other(
    junction_driven,
):
    _, centre = junction_driven
    network = corridor.prepared().network
    obstacles = obstacles_on_lanes(corridor.records(), [_square(centre)], JUNCTION_RULES)
    connectors = closed_connections(network, corridor.records(), obstacles)
    assert connectors and all(network.paths[path].kind == "connector" for path in connectors)
    assert closures(network, corridor.records(), obstacles) == ((), ())
    shut = close_network(network, (), (), connectors)
    for path_id, path in shut.paths.items():
        if path_id in connectors:
            assert path.classes == () and network.paths[path_id].classes
        else:
            assert path.classes == network.paths[path_id].classes, path_id
    assert shut.document["closures"] == {
        "profile": CONNECTION_CLOSURES_PROFILE,
        "lanes": [],
        "spaces": [],
        "connectors": list(connectors),
    }
    with pytest.raises(UnsupportedNetworkError):
        close_network(network, (), (), ["lane:not a connection"])


def test_a_thing_over_every_connection_of_a_junction_closes_the_junction():
    network = corridor.prepared().network
    records = corridor.records()
    junction = next(r for r in records if isinstance(r, JunctionRecord))
    extent = junction.extent
    box = (
        (extent.min_x_mm, extent.min_y_mm),
        (extent.max_x_mm, extent.min_y_mm),
        (extent.max_x_mm, extent.max_y_mm),
        (extent.min_x_mm, extent.max_y_mm),
    )
    connectors = closed_connections(network, records, [box])
    own = {
        path_id
        for path_id, path in network.paths.items()
        if path.kind == "connector" and path.start_junction == junction.identity
    }
    assert own and own <= set(connectors)


def test_an_episode_under_rules_3_drives_no_vehicle_through_a_thing_in_a_junction(junction_driven):
    episode, centre = junction_driven
    value = corridor.value()
    assert any(_inside(point, centre) for _, point in _axles(value, episode))
    obstacles = obstacles_on_lanes(corridor.records(), [_square(centre)], JUNCTION_RULES)
    closed = with_obstacles(
        value, obstacles, line_version="a version", closing_rules=JUNCTION_RULES
    )
    assert closed.sha256 != value.sha256 and closed.seed == value.seed
    assert from_wire(wire(closed)) == closed.__class__(**{**_fields(closed), "line_version": ""})
    after = compute_episode(wire(closed), 0)
    assert after.input_sha256 == closed.sha256
    assert traffic_episodes.prepared(closed).network.document["closures"]["connectors"]
    assert not any(_inside(point, centre) for _, point in _axles(closed, after))
    # The same thing read under rules 2 closes no connection: vehicles still drive through it.
    open_rules = with_obstacles(value, obstacles, line_version="a version")
    assert open_rules.sha256 != closed.sha256
    unclosed = corridor.prepared().network.digest
    assert traffic_episodes.prepared(open_rules).network.digest == unclosed


def test_a_rules_3_input_names_its_rules_only_with_an_obstacle(junction_driven):
    _, centre = junction_driven
    value = corridor.value()
    obstacles = obstacles_on_lanes(corridor.records(), [_square(centre)], JUNCTION_RULES)
    closed = with_obstacles(value, obstacles, line_version="v", closing_rules=JUNCTION_RULES)
    assert wire(closed)["closing_rules"] == JUNCTION_RULES
    assert JUNCTION_INPUT_PROFILE == "exulanica.traffic-input/v3"
    # With nothing in the road a rules-3 version keeps the first profile and its bytes.
    none = with_obstacles(value, (), line_version="v", closing_rules=JUNCTION_RULES)
    assert none.sha256 == value.sha256 and wire(none) == wire(value)
