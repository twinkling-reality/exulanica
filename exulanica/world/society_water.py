"""The water a society can cross: swim nodes over a world's water, recorded as a graph of its own.

A world's composer states the water its world holds (``swim_nodes`` of
:mod:`exulanica.world.composers.site_plan` and of
:mod:`exulanica.world.composers.city_grammar_town`): each body by name, kind and level, with the
points of the swimming module's lattice inside it (:func:`rectangle_water`, :func:`land_water`). The
lattice is laid as a saved world's ground lattice is
(:mod:`exulanica.world.society_authored_ground_area`): points ``lattice_mm`` apart at multiples of
it about the region's origin, each kept where the water reaches a ``clearance_mm`` beyond it along
both axes, both figures the swimming module's (``exulanica-movement/swimming/v1``). A body's level
is its surface's height in millimetres above the datum its world's heights stand on: a level site's
ground (0) for its ponds, the graded level of a pond, lake or pool on land, and the datum for the
sea.

A things input of a society that swims carries, under :data:`WATER_FIELD`, the graph
:func:`water_graph` lays over that statement, profile :data:`WATER_PROFILE`:

* **bodies**: each body laid, by identity, kind and level;
* **nodes**: each point inside the society's walkable area a clearance from its edge, as the input
  states positions (east and south millimetres), named by where it is; a point two bodies share is
  the first body's, and a body that would take the input past the module's ``max_nodes`` is left
  unlaid;
* **edges**: each node joined to its lattice neighbours of the same body (``swim``), and each node
  at the edge of its body's lattice joined to the nearest node of the walking graph within the
  module's ``shore_reach_mm`` whose straight way is clear of everything a walker keeps clear of but
  the water (``shore``). Those walking nodes are the shore, the only nodes at which the two graphs
  meet; no activity's place is one.

The walking graph is not changed: no walking route enters the water, and only a swimmer reads it
(:mod:`exulanica.world.society_movement`). An input with no water to cross, and every input of a
society that does not swim, states none, so every input composed before reads as it did.

Pure: no connection and no store.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.grammar.landform import WaterBody, within_water
from exulanica.movement.registry import SWIMMING, built_module, recorded_movement
from exulanica.world.society_thing_inputs import MOVEMENT_MODULES_FIELD

__all__ = [
    "WATER_FIELD",
    "WATER_PROFILE",
    "WaterStatement",
    "land_water",
    "records_swimming",
    "rectangle_water",
    "validate_water",
    "water_graph",
]

#: Where a things input states the water its society's swimmers cross.
WATER_FIELD: Final = "water"
WATER_PROFILE: Final = "exulanica.society-water/v1"
#: What a body of water may be: a world's own pond, or on land a lake, a cascade's pool or the sea.
WATER_KINDS: Final = ("lake", "pond", "pool", "sea")
_SWIMMING = built_module(SWIMMING)
#: The figures the lattice is laid and joined by, the swimming module's.
LATTICE_MM: Final = _SWIMMING.value("lattice_mm")
CLEARANCE_MM: Final = _SWIMMING.value("clearance_mm")
SHORE_REACH_MM: Final = _SWIMMING.value("shore_reach_mm")
MAX_NODES: Final = _SWIMMING.value("max_nodes")
#: The most bodies and edges one input states: the bounds every list of an input shares.
_BODIES_BOUND: Final = 4096
_EDGES_BOUND: Final = 65536
_COORDINATE: Final = 10**9
_FIELDS: Final = frozenset(
    {"profile", "lattice_mm", "clearance_mm", "shore_reach_mm", "bodies", "nodes", "edges"}
)
_NODE: Final = re.compile(r"water:[+-][0-9]{8,}:[+-][0-9]{8,}")
Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class WaterStatement:
    """The water a world holds, as its composer states it, and what a way to its shore keeps clear
    of: ``clear`` answers whether the straight way between two points of the world's own frame
    (east and north millimetres) is clear of everything a walker keeps clear of but the water, and
    is None where nothing else stands."""

    bodies: tuple[Mapping[str, Any], ...]
    clear: Callable[[Point, Point], bool] | None = None


def _axis(low: int, high: int) -> range:
    """The lattice's figures from ``low`` to ``high`` on one axis, both kept."""
    return range(-(-low // LATTICE_MM) * LATTICE_MM, high + 1, LATTICE_MM)


def _body(
    body_id: str,
    kind: str,
    level_mm: int,
    inside: Callable[[int, int], bool],
    box: tuple[int, int, int, int],
) -> dict[str, Any]:
    """A body of water as a composer states it: the lattice points of ``box`` (a world's own frame)
    at which ``inside`` holds, and holds a clearance away along each axis."""
    reach = CLEARANCE_MM
    points = [
        [x, y]
        for x in _axis(box[0], box[2])
        for y in _axis(box[1], box[3])
        if inside(x, y)
        and all(
            inside(x + dx, y + dy) for dx, dy in ((reach, 0), (-reach, 0), (0, reach), (0, -reach))
        )
    ]
    return {"body_id": body_id, "kind": kind, "level_mm": level_mm, "points_mm": points}


def rectangle_water(
    body_id: str,
    kind: str,
    level_mm: int,
    rect_mm: tuple[int, int, int, int],
    bounds: tuple[int, int, int, int],
) -> dict[str, Any]:
    """A body of water that fills a rectangle (``x0, y0, x1, y1``) of a world's own frame, as a
    level site's pond fills its area, laid within ``bounds``, the world's extent."""
    x0, y0, x1, y1 = rect_mm
    box = (max(x0, bounds[0]), max(y0, bounds[1]), min(x1, bounds[2]), min(y1, bounds[3]))
    return _body(body_id, kind, level_mm, lambda x, y: x0 < x < x1 and y0 < y < y1, box)


def land_water(
    bodies: Mapping[str, WaterBody],
    height_at: Callable[[int, int], int],
    bounds: tuple[int, int, int, int],
) -> list[dict[str, Any]]:
    """The water graded land holds, by the name each body is stated under: a point is in a body
    where it lies within the body's outline (:func:`~exulanica.grammar.landform.within_water`) and
    the graded land under it lies below the body's level, laid within ``bounds``, the world's
    extent. A fall is a sheet of water, not a body anything crosses, and is left out, and so is a
    body with no point of the lattice inside ``bounds``."""
    stated = []
    for body_id, body in sorted(bodies.items()):
        if body.kind not in WATER_KINDS:
            continue
        box = bounds
        if body.kind in ("pond", "pool"):
            box = body.rect_mm
        elif body.kind == "lake":
            (cx, cy), r = body.centre_mm, body.radius_mm
            box = (cx - r, cy - r, cx + r, cy + r)
        box = (
            max(box[0], bounds[0]),
            max(box[1], bounds[1]),
            min(box[2], bounds[2]),
            min(box[3], bounds[3]),
        )

        def inside(x: int, y: int, body: WaterBody = body) -> bool:
            return within_water(body, x, y) and height_at(x, y) < body.level_mm

        laid = _body(body_id, body.kind, body.level_mm, inside, box)
        if laid["points_mm"]:
            stated.append(laid)
    return stated


def records_swimming(modules: object) -> bool:
    """Whether a first input's movement modules (``movement_modules``) name a swimming."""
    return isinstance(modules, list) and recorded_movement(modules, "swimming") is not None


def _node_id(x_mm: int, z_mm: int) -> str:
    return f"water:{x_mm:+09d}:{z_mm:+09d}"


def _ceil_distance(a: Sequence[int], b: Sequence[int]) -> int:
    squared = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
    length = math.isqrt(squared)
    return length + (length * length < squared)


def _edge(a: str, b: str, length_mm: int, body_id: str, kind: str) -> dict[str, Any]:
    first, second = sorted((a, b))
    return {
        "edge_id": f"{first}|{second}",
        "from_node_id": first,
        "to_node_id": second,
        "length_mm": length_mm,
        "body_id": body_id,
        "kind": kind,
    }


def water_graph(
    statement: WaterStatement,
    *,
    nodes: Iterable[Mapping[str, Any]],
    exclude: Iterable[str],
    area: Mapping[str, Any],
) -> dict[str, Any] | None:
    """The graph a things input states over the water ``statement`` holds, or None where none of it
    lies inside the input's walkable ``area`` (its ``walkable_area``): its walking graph is
    ``nodes``, positions east and south as the input states them, and ``exclude`` names the walking
    nodes that join no water, every activity's places."""
    cx, cz = area["centre_mm"]
    width = area["half_width_mm"] - CLEARANCE_MM
    depth = area["half_depth_mm"] - CLEARANCE_MM
    owner: dict[Point, str] = {}
    bodies = []
    for body in sorted(statement.bodies, key=lambda stated: stated["body_id"]):
        points = [
            (x, -y)
            for x, y in body["points_mm"]
            if abs(x - cx) <= width and abs(-y - cz) <= depth and (x, -y) not in owner
        ]
        if not points or len(owner) + len(points) > MAX_NODES:
            continue
        bodies.append({key: body[key] for key in ("body_id", "kind", "level_mm")})
        owner.update((point, body["body_id"]) for point in points)
    if not owner:
        return None
    steps = ((LATTICE_MM, 0), (-LATTICE_MM, 0), (0, LATTICE_MM), (0, -LATTICE_MM))
    edges = []
    rim = []
    for (x, z), body_id in owner.items():
        if any(owner.get((x + dx, z + dz)) != body_id for dx, dz in steps):
            rim.append((x, z))
        for nx, nz in ((x + LATTICE_MM, z), (x, z + LATTICE_MM)):
            if owner.get((nx, nz)) == body_id:
                edges.append(_edge(_node_id(x, z), _node_id(nx, nz), LATTICE_MM, body_id, "swim"))
    # The walking nodes a swim node may join, filed in cells as wide as the reach, so a node near
    # one is never more than one cell away.
    skipped = set(exclude)
    cells: dict[Point, list[tuple[str, Point]]] = {}
    for node in nodes:
        if node["node_id"] in skipped:
            continue
        position = (int(node["position_mm"][0]), int(node["position_mm"][1]))
        cell = (position[0] // SHORE_REACH_MM, position[1] // SHORE_REACH_MM)
        cells.setdefault(cell, []).append((str(node["node_id"]), position))
    for x, z in rim:
        cell = (x // SHORE_REACH_MM, z // SHORE_REACH_MM)
        near = sorted(
            ((x - px) ** 2 + (z - pz) ** 2, node_id, (px, pz))
            for dx in (-1, 0, 1)
            for dz in (-1, 0, 1)
            for node_id, (px, pz) in cells.get((cell[0] + dx, cell[1] + dz), ())
        )
        for squared, node_id, (px, pz) in near:
            if squared > SHORE_REACH_MM**2:
                break
            if statement.clear is None or statement.clear((x, -z), (px, -pz)):
                length = _ceil_distance((x, z), (px, pz))
                edges.append(_edge(_node_id(x, z), node_id, length, owner[x, z], "shore"))
                break
    return {
        "profile": WATER_PROFILE,
        "lattice_mm": LATTICE_MM,
        "clearance_mm": CLEARANCE_MM,
        "shore_reach_mm": SHORE_REACH_MM,
        "bodies": bodies,
        "nodes": sorted(
            (
                {"node_id": _node_id(x, z), "body_id": body_id, "position_mm": [x, z]}
                for (x, z), body_id in owner.items()
            ),
            key=lambda node: node["node_id"],
        ),
        "edges": sorted(edges, key=lambda edge: edge["edge_id"]),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _whole(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 1000


def validate_water(document: Mapping[str, Any]) -> None:
    """The water a things input states, held to its shape where it states any: only an available
    input of a society that swims (its first input records the swimming module), a lattice of nodes
    named by where they are inside its walkable area, each of a body it states, and edges that join
    two nodes of one body a lattice step apart or one of them to a node of its walking graph, each
    as long as the straight way between them, rounded up."""
    if WATER_FIELD not in document:
        return
    water, navigation = document[WATER_FIELD], document["navigation"]
    _require(
        document["availability"] == "available" and navigation["unavailable_reason"] is None,
        "an unavailable input states no water",
    )
    _require(
        document["input_seq"] != 1 or records_swimming(document.get(MOVEMENT_MODULES_FIELD)),
        "only the input of a society that swims states water",
    )
    _require(isinstance(water, dict) and set(water) == _FIELDS, "invalid water fields")
    _require(water["profile"] == WATER_PROFILE, "unsupported water profile")
    _require(
        all(_whole(water[k], 1, _COORDINATE) for k in ("lattice_mm", "clearance_mm"))
        and _whole(water["shore_reach_mm"], 1, _COORDINATE),
        "invalid water figures",
    )
    lattice = water["lattice_mm"]
    bodies = water["bodies"]
    _require(isinstance(bodies, list) and 0 < len(bodies) <= _BODIES_BOUND, "invalid water bodies")
    for body in bodies:
        _require(
            isinstance(body, dict)
            and set(body) == {"body_id", "kind", "level_mm"}
            and _text(body["body_id"])
            and body["kind"] in WATER_KINDS
            and _whole(body["level_mm"], -_COORDINATE, _COORDINATE),
            "invalid water body",
        )
    named = [body["body_id"] for body in bodies]
    _require(named == sorted(set(named)), "water bodies must be unique and sorted")
    area = navigation["walkable_area"]
    (cx, cz), clearance = area["centre_mm"], water["clearance_mm"]
    nodes = water["nodes"]
    _require(isinstance(nodes, list) and 0 < len(nodes) <= MAX_NODES, "water node bound exceeded")
    walking = {node["node_id"]: node["position_mm"] for node in navigation["nodes"]}
    swum: dict[str, Any] = {}
    for node in nodes:
        _require(
            isinstance(node, dict)
            and set(node) == {"node_id", "body_id", "position_mm"}
            and node["body_id"] in named,
            "invalid water node",
        )
        point = node["position_mm"]
        _require(
            isinstance(point, list)
            and len(point) == 2
            and all(_whole(v, -_COORDINATE, _COORDINATE) and v % lattice == 0 for v in point)
            and node["node_id"] == _node_id(*point)
            and _NODE.fullmatch(node["node_id"]) is not None,
            "a water node lies on its lattice, named by where it is",
        )
        _require(
            abs(point[0] - cx) <= area["half_width_mm"] - clearance
            and abs(point[1] - cz) <= area["half_depth_mm"] - clearance,
            "a water node lies outside the stated walkable area",
        )
        _require(node["node_id"] not in swum and node["node_id"] not in walking, "duplicate node")
        swum[node["node_id"]] = node
    _require(list(swum) == sorted(swum), "water nodes must be sorted")
    edges = water["edges"]
    _require(isinstance(edges, list) and len(edges) <= _EDGES_BOUND, "water edge bound exceeded")
    keys = []
    for edge in edges:
        _require(
            isinstance(edge, dict)
            and set(edge)
            == {"edge_id", "from_node_id", "to_node_id", "length_mm", "body_id", "kind"}
            and edge["kind"] in ("swim", "shore"),
            "invalid water edge",
        )
        a, b = edge["from_node_id"], edge["to_node_id"]
        _require(
            isinstance(a, str) and isinstance(b, str) and a < b and edge["edge_id"] == f"{a}|{b}",
            "a water edge is named by its two nodes, in order",
        )
        if edge["kind"] == "swim":
            ends = [swum.get(a), swum.get(b)]
            _require(
                all(end is not None and end["body_id"] == edge["body_id"] for end in ends)
                and edge["length_mm"] == lattice
                and _ceil_distance(ends[0]["position_mm"], ends[1]["position_mm"]) == lattice,
                "a swim edge joins two lattice neighbours of its body",
            )
        else:
            water_end, land_end = (a, b) if a in swum else (b, a)
            _require(
                water_end in swum
                and swum[water_end]["body_id"] == edge["body_id"]
                and land_end in walking,
                "a shore edge joins a water node to the walking graph",
            )
            _require(
                edge["length_mm"]
                == _ceil_distance(swum[water_end]["position_mm"], walking[land_end]),
                "edge length must be ceil Euclidean distance",
            )
        keys.append(edge["edge_id"])
    _require(keys == sorted(set(keys)), "water edges must be unique and sorted")
