"""The water a society can cross: swim nodes over a world's water, a graph of its own in an input.

A world's composer states the water its world holds, with the swimming module's lattice points
inside each body, and a things input of a society that swims carries the graph laid over them
(:mod:`exulanica.world.society_water`). What is shown, with no database, on the fixture farm, whose
site lays a pond of 35.1 m by 32.5 m (``tests/water_society_support.py``):

*   the site composer states the pond, at the level ground every site stands on, as the lattice
    points 2 m apart that lie a clearance inside it, worked by hand from its record;
*   the input lays those points as nodes named by where they are, joined to their neighbours in the
    pond and, at its edge, to the nearest walking node within reach whose way is clear, and to no
    activity's place; its walking graph is the one an input without water states, byte for byte,
    and no walking route enters the water;
*   a society that does not swim, as every one made before swimming was built, reads its inputs as
    it always did: no water is laid into them;
*   the validator refuses water out of shape, by name;
*   on land, a body is where the land lies below its level inside its outline; a site on land
    states its pond at the level the land graded it to; a town on its land holds none inside its
    own ground on the lands its recipes make;
*   the kind worker hands the site's water over with its place, and the runtime hands it to a later
    input only of a society whose first input records swimming.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.grammar.landform import WaterBody, within_water
from exulanica.movement.registry import WALKING_V2
from exulanica.movement.walking import routes_from
from exulanica.world.kinds.worker import _placed
from exulanica.world.society_planner import validate_society_input
from exulanica.world.society_site_place import site_obstructions
from exulanica.world.society_water import (
    WATER_FIELD,
    WaterStatement,
    land_water,
    rectangle_water,
    water_graph,
)
from exulanica.world.society_water_sources import site_water, water_for_input

from water_society_support import (
    compose_farm,
    farm,
    finned_walker,
    placed,
    pond_water_statement,
    resealed,
)

LATTICE = 2_000
CLEARANCE = 450
REACH = 4_000


def _pond_box() -> tuple[int, int, int, int]:
    pond = farm().pond
    return pond.min_x_mm, pond.min_y_mm, pond.max_x_mm, pond.max_y_mm


def _figures(low: int, high: int) -> list[int]:
    """The lattice's figures a clearance inside ``low`` and ``high``."""
    first = -(-(low + CLEARANCE) // LATTICE) * LATTICE
    return list(range(first, high - CLEARANCE + 1, LATTICE))


def test_the_site_composer_states_its_pond_as_the_lattice_points_inside_it():
    x0, y0, x1, y1 = _pond_box()
    assert (x0, y0, x1, y1) == (59_400, 2_500, 94_500, 35_000)
    xs, ys = _figures(x0, x1), _figures(y0, y1)
    assert (xs[0], xs[-1], len(xs)) == (60_000, 94_000, 18)
    assert (ys[0], ys[-1], len(ys)) == (4_000, 34_000, 16)
    [pond] = pond_water_statement()
    assert pond["body_id"] == f"site.area:{farm().pond.identity}"
    assert (pond["kind"], pond["level_mm"]) == ("pond", 0)
    assert sorted(map(tuple, pond["points_mm"])) == sorted((x, y) for x in xs for y in ys)


def _water(document: dict[str, Any]) -> dict[str, Any]:
    return document[WATER_FIELD]


def test_a_swimming_society_s_input_lays_its_water_as_a_graph_of_its_own():
    document = compose_farm()
    validate_society_input(document)
    water = _water(document)
    assert water["profile"] == "exulanica.society-water/v1"
    assert (water["lattice_mm"], water["clearance_mm"], water["shore_reach_mm"]) == (
        LATTICE,
        CLEARANCE,
        REACH,
    )
    assert water["bodies"] == [
        {"body_id": f"site.area:{farm().pond.identity}", "kind": "pond", "level_mm": 0}
    ]
    # Every node is a lattice point inside the pond, as the input states positions: east, and
    # south as the negative of the site's north; named by where it is.
    x0, y0, x1, y1 = _pond_box()
    nodes = {node["node_id"]: tuple(node["position_mm"]) for node in water["nodes"]}
    assert len(nodes) == 18 * 16
    for node_id, (x, z) in nodes.items():
        assert node_id == f"water:{x:+09d}:{z:+09d}"
        assert x0 + CLEARANCE <= x <= x1 - CLEARANCE and y0 + CLEARANCE <= -z <= y1 - CLEARANCE
    swims = [edge for edge in water["edges"] if edge["kind"] == "swim"]
    # Seventeen steps along each of sixteen rows and fifteen along each of eighteen columns.
    assert len(swims) == 17 * 16 + 15 * 18
    assert all(edge["length_mm"] == LATTICE for edge in swims)


def test_the_water_meets_the_walking_graph_only_at_its_shore_and_never_at_a_place():
    document = compose_farm()
    water = _water(document)
    nodes = {node["node_id"]: node["position_mm"] for node in water["nodes"]}
    walking = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    places = {node for target in document["targets"] for node in target["place_node_ids"]}
    neighbours: dict[str, int] = dict.fromkeys(nodes, 0)
    for edge in water["edges"]:
        if edge["kind"] == "swim":
            neighbours[edge["from_node_id"]] += 1
            neighbours[edge["to_node_id"]] += 1
    shores = [edge for edge in water["edges"] if edge["kind"] == "shore"]
    assert shores
    for edge in shores:
        ends = {edge["from_node_id"], edge["to_node_id"]}
        [swum] = ends & set(nodes)
        [shore] = ends & set(walking)
        assert neighbours[swum] < 4, "a shore edge leaves from the lattice's edge"
        assert shore not in places
        length = math.dist(nodes[swum], walking[shore])
        assert edge["length_mm"] == math.ceil(length) and length <= REACH
    # Each swim node at the edge of the lattice joins at most one walking node, and the water and
    # the walking graph share no edge but these.
    assert len(
        {e["from_node_id"] if e["from_node_id"] in nodes else e["to_node_id"] for e in shores}
    ) == len(shores)
    for edge in document["navigation"]["edges"]:
        assert not {edge["from_node_id"], edge["to_node_id"]} & set(nodes)


def test_a_place_is_never_the_shore_even_where_it_is_the_nearest_walking_node():
    """A pond 8 m by 6 m whose lattice is two rows of three, its west column 3 m from a place and
    3.5 m from a path node, both west of it: the place is nearer, and the path is the shore."""
    pond = rectangle_water(
        "pond:a", "pond", 0, (0, 0, 8_000, 6_000), (-9_000, -9_000, 9_000, 9_000)
    )
    assert pond["points_mm"] == [[x, y] for x in (2_000, 4_000, 6_000) for y in (2_000, 4_000)]
    walking = [
        {"node_id": "path", "position_mm": [-1_500, -2_000]},
        {"node_id": "place", "position_mm": [-1_000, -2_000]},
    ]
    area = {"centre_mm": [0, 0], "half_width_mm": 9_000, "half_depth_mm": 9_000}

    def shores(exclude: list[str]) -> list[tuple[str, str, int]]:
        graph = water_graph(WaterStatement((pond,)), nodes=walking, exclude=exclude, area=area)
        assert graph is not None
        return [
            (edge["from_node_id"], edge["to_node_id"], edge["length_mm"])
            for edge in graph["edges"]
            if edge["kind"] == "shore"
        ]

    # Of the west column, the node 2 m south of the place's row is 3.606 m from the place and
    # 4.031 m from the path, beyond reach.
    assert shores(["place"]) == [("path", "water:+00002000:-00002000", 3_500)]
    assert shores([]) == [
        ("place", "water:+00002000:-00002000", 3_000),
        ("place", "water:+00002000:-00004000", 3_606),
    ]


def test_the_walking_graph_is_the_one_an_input_without_water_states_and_never_enters_it():
    with_water, without = compose_farm(), compose_farm(water=False)
    assert WATER_FIELD not in without
    assert with_water["navigation"] == without["navigation"]
    assert with_water["targets"] == without["targets"]
    assert resealed(with_water, water=None) == without
    # Every walking edge is clear of the pond, by the walking capsule's radius round it, and every
    # route over the walking graph stays on it.
    pond = site_obstructions([list(_pond_box())])
    walking = {n["node_id"]: n["position_mm"] for n in without["navigation"]["nodes"]}
    for edge in without["navigation"]["edges"]:
        a, b = walking[edge["from_node_id"]], walking[edge["to_node_id"]]
        assert pond.steps((a[0], -a[1]), (b[0], -b[1])), edge["edge_id"]
    adjacent: dict[str, list] = {node: [] for node in walking}
    for edge in without["navigation"]["edges"]:
        adjacent[edge["from_node_id"]].append((edge["to_node_id"], edge))
        adjacent[edge["to_node_id"]].append((edge["from_node_id"], edge))
    for values in adjacent.values():
        values.sort(key=lambda pair: pair[0])
    routes = routes_from("zone:02:high:006", adjacent)
    assert all(not node.startswith("water:") for _cost, path in routes.values() for node in path)


def test_a_society_that_does_not_swim_reads_its_inputs_as_it_always_did(monkeypatch):
    """A first input that records the walking alone, as every one made before swimming was built,
    is composed byte for byte as if the world held no water; a later input is handed water only
    where its society swims, and one handed none states none."""
    from exulanica.movement import registry

    monkeypatch.setattr(registry, "current_engine_modules", lambda engine: (WALKING_V2,))
    before = compose_farm()
    assert before["movement_modules"] == [WALKING_V2]
    assert WATER_FIELD not in before
    assert before == compose_farm(water=False)
    monkeypatch.undo()
    assert WATER_FIELD in compose_farm(input_seq=2)
    later = compose_farm(input_seq=2, water=False)
    assert WATER_FIELD not in later and "movement_modules" not in later
    validate_society_input(later)


def _mutated(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    document = compose_farm()
    water = copy.deepcopy(document[WATER_FIELD])
    change(water)
    return resealed(document, water=water)


def _first_node(water: dict[str, Any]) -> dict[str, Any]:
    return water["nodes"][0]


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda w: w.update(profile="exulanica.society-water/v0"), "unsupported water profile"),
        (lambda w: w.pop("edges"), "invalid water fields"),
        (lambda w: w.update(lattice_mm=0), "invalid water figures"),
        (lambda w: w["bodies"][0].update(kind="river"), "invalid water body"),
        (lambda w: _first_node(w).update(body_id="elsewhere"), "invalid water node"),
        (
            lambda w: _first_node(w)["position_mm"].__setitem__(0, 60_001),
            "lies on its lattice, named by where it is",
        ),
        (
            lambda w: _first_node(w).update(node_id="water:+00060000:-00004002"),
            "lies on its lattice, named by where it is",
        ),
        (lambda w: w["nodes"].reverse(), "water nodes must be sorted"),
        (lambda w: w["edges"].reverse(), "water edges must be unique and sorted"),
        (
            lambda w: next(e for e in w["edges"] if e["kind"] == "swim").update(length_mm=2_001),
            "a swim edge joins two lattice neighbours",
        ),
        (
            lambda w: next(e for e in w["edges"] if e["kind"] == "shore").update(kind="swim"),
            "a swim edge joins two lattice neighbours",
        ),
        (
            lambda w: next(e for e in w["edges"] if e["kind"] == "swim").update(kind="shore"),
            "a shore edge joins a water node to the walking graph",
        ),
        (
            lambda w: next(e for e in w["edges"] if e["kind"] == "shore").update(length_mm=1),
            "edge length must be ceil Euclidean distance",
        ),
        (
            lambda w: next(e for e in w["edges"] if e["kind"] == "swim").update(edge_id="x|y"),
            "named by its two nodes, in order",
        ),
    ],
    ids=[
        "profile",
        "fields",
        "figure",
        "body_kind",
        "node_body",
        "off_lattice",
        "misnamed",
        "nodes_order",
        "edges_order",
        "swim_length",
        "shore_as_swim",
        "swim_as_shore",
        "shore_length",
        "edge_name",
    ],
)
def test_water_out_of_shape_is_refused_by_name(change, match):
    validate_society_input(compose_farm())  # positive control
    with pytest.raises(ValueError, match=match):
        validate_society_input(_mutated(change))


def test_water_is_refused_on_an_input_that_cannot_carry_it():
    document = compose_farm()
    water = document[WATER_FIELD]
    # A first input of a society that does not swim, and an unavailable input, state none.
    with pytest.raises(ValueError, match="only the input of a society that swims"):
        validate_society_input(resealed(document, movement_modules=[WALKING_V2]))
    unavailable = compose_farm(unavailable_reason="authored_source_invalidated")
    assert WATER_FIELD not in unavailable
    validate_society_input(unavailable)
    with pytest.raises(ValueError, match="an unavailable input states no water"):
        validate_society_input(resealed(unavailable, water=water))
    # A water node may not take a walking node's name.
    taken = copy.deepcopy(water)
    walking = document["navigation"]["nodes"][0]["node_id"]
    taken["nodes"][0]["node_id"] = walking
    with pytest.raises(ValueError):
        validate_society_input(resealed(document, water=taken))


def test_on_land_a_body_is_where_the_land_lies_below_its_level_inside_its_outline():
    """A lake of radius 6 m about (10 m, 10 m) at a level of 1 m, on land at 0 inside a radius of
    5 m and 2 m outside it: the water is the land below the level within the lake's circle, so
    the lattice lies inside the 5 m, a clearance from its edge. A fall is no body to cross."""
    lake = WaterBody(
        id="lake", kind="lake", level_mm=1_000, centre_mm=(10_000, 10_000), radius_mm=6_000
    )
    fall = WaterBody(id="fall", kind="fall", level_mm=1_000, rect_mm=(0, 0, 0, 0))

    def height(x: int, y: int) -> int:
        return 0 if (x - 10_000) ** 2 + (y - 10_000) ** 2 < 5_000**2 else 2_000

    [laid] = land_water({"land:lake": lake, "land:fall": fall}, height, (0, 0, 40_000, 40_000))
    assert (laid["body_id"], laid["kind"], laid["level_mm"]) == ("land:lake", "lake", 1_000)
    inside = sorted(
        (x, y)
        for x in range(0, 20_001, LATTICE)
        for y in range(0, 20_001, LATTICE)
        if all(
            (x + dx - 10_000) ** 2 + (y + dy - 10_000) ** 2 < 5_000**2
            for dx, dy in ((CLEARANCE, 0), (-CLEARANCE, 0), (0, CLEARANCE), (0, -CLEARANCE), (0, 0))
        )
    )
    assert sorted(map(tuple, laid["points_mm"])) == inside and len(inside) == 21
    # Within ``bounds`` alone: the same lake laid in a world 10 m square keeps its south-west part.
    [clipped] = land_water({"land:lake": lake}, height, (0, 0, 10_000, 10_000))
    assert {tuple(p) for p in clipped["points_mm"]} == {p for p in inside if max(p) <= 10_000}
    assert land_water({"land:lake": lake}, lambda x, y: 5_000, (0, 0, 40_000, 40_000)) == []


def test_a_site_on_land_states_its_pond_at_the_level_the_land_graded_it_to():
    """The farm laid on tilted land grades its pond's basin and stands the pond at 6.269 m, not at
    the level ground of a site without land. The composer states it under its area's name: each
    lattice point of its rectangle that lies, with a clearance along each axis, within its outline
    where the land is below that level. The land's sea lies below the whole site, so none is
    stated."""
    from exulanica.world.composers import site_plan

    import test_site_land as on_land

    world = on_land.made("farm")
    records = tuple(world.records)
    land = site_plan.receipt_land(world.receipt, records)
    [pond] = [body for body in land.water if body.kind == "pond"]
    [stated] = site_plan.swim_nodes(world.receipt, records)
    assert stated["body_id"].startswith("site.area:")
    assert (stated["kind"], stated["level_mm"]) == ("pond", pond.level_mm) == ("pond", 6_269)

    def wet(x: int, y: int) -> bool:
        return within_water(pond, x, y) and land.height_at(x, y) < pond.level_mm

    x0, y0, x1, y1 = pond.rect_mm
    clear = ((0, 0), (CLEARANCE, 0), (-CLEARANCE, 0), (0, CLEARANCE), (0, -CLEARANCE))
    expected = [
        [x, y]
        for x in range(-(-x0 // LATTICE) * LATTICE, x1 + 1, LATTICE)
        for y in range(-(-y0 // LATTICE) * LATTICE, y1 + 1, LATTICE)
        if all(wet(x + dx, y + dy) for dx, dy in clear)
    ]
    assert stated["points_mm"] == expected and len(expected) == 184


def test_a_town_holds_no_water_inside_its_own_ground_on_the_lands_its_recipes_make():
    """A level town holds no water; a town on the coast has its sea and its cascade's pools, all
    south of its own ground, so it lays none."""
    from exulanica.world.composers import city_grammar_town as town
    from exulanica.world.generated_worlds import compose_generated_world
    from exulanica.world.world_recipes import town_recipe

    import test_city_grammar_town_on_land as on_land

    level = compose_generated_world(town_recipe("small_town"), on_land.WORLD)
    assert town.swim_nodes(level.receipt, level.records) == []
    made = on_land._made()
    water = town.graded_land(made.receipt, made.records).water
    assert {body.kind for body in water} >= {"sea", "pool"}
    assert town.swim_nodes(made.receipt, made.records) == []


def test_the_kind_worker_hands_the_site_s_water_over_with_its_place():
    made = farm()
    answer = _placed(made.ground.place_id, made.receipt, made.records)
    assert answer["water"] == pond_water_statement()
    statement = site_water(answer)
    assert statement is not None and list(statement.bodies) == answer["water"]
    # A way to the shore keeps clear of everything the site blocks walking with but its water:
    # from the walking line south of the pond to the lattice row 2.5 m inside it is clear, which
    # the site's whole blocked ground would not let it be.
    assert statement.clear is not None
    assert statement.clear((78_045, 1_500), (78_000, 4_000))
    assert not site_obstructions(answer["blocked"]).steps((78_045, 1_500), (78_000, 4_000))
    # An answer kept before the worker stated water hands none.
    assert site_water({k: v for k, v in answer.items() if k != "water"}) is None


class _Rows:
    """A connection that answers the read of a society's first input with ``modules``."""

    def __init__(self, modules: list[str] | None) -> None:
        self.modules, self.asked = modules, 0

    def execute(self, _sql: str, _parameters: Any) -> _Rows:
        self.asked += 1
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return None if self.modules is None else {"modules": self.modules}


def test_the_runtime_hands_water_to_the_inputs_of_a_society_that_swims_alone():
    from types import SimpleNamespace

    binding = SimpleNamespace(workspace_id="w", world_id="world", version_id="v")
    statement = site_water(_placed(farm().ground.place_id, farm().receipt, farm().records))
    sha256, form = finned_walker()
    first = compose_farm(placed("swimmer", sha256, 74_181, 1_500), made_kinds={sha256: form})
    swimming = first["movement_modules"]
    assert water_for_input(_Rows(None), binding, 1, statement) is statement
    assert water_for_input(_Rows(swimming), binding, 2, statement) is statement
    assert water_for_input(_Rows([WALKING_V2]), binding, 2, statement) is None
    assert water_for_input(_Rows(None), binding, 2, statement) is None
    unread = _Rows(swimming)
    assert water_for_input(unread, binding, 2, None) is None and unread.asked == 0
