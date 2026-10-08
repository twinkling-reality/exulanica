"""The society over a world whose own records state its walking surfaces.

A world generated from the city grammar states, in its records, every surface a person stands on:
footways beside their kerbs, corners, crossings and the entrances of its premises. Its society
walks those, not a lattice over a declared square. This module reads such a world's ground from
its structural snapshot (:func:`walking_surfaces_ground`) and composes the purposeful society's
input over the world's records (:func:`build_walking_surfaces_input`), under
``exulanica.society-composition/walking-surfaces-v1``:

* **The graph** is the city place the living society reads a city by
  (:func:`~exulanica.world.society_city_place.place_from_city_records`): its nodes and edges,
  each position turned into the region's east and south millimetres, each node named by the kind
  of surface it stands on and each edge by what it crosses. The positions are plan positions; the
  height a person stands at stays in the records.
* **The activities** are the world's own. Every premises whose use class admits visitors is
  somewhere to visit, stood at at its entrance, and every piece of street furniture whose use
  class seats people is somewhere to rest, one place per seat, each seat a node joined to the
  furniture's access node. Places keep a standing spacing apart in destination order; one that
  cannot is recorded as unreachable, as an object the person placed in the world is: the
  composition joins nothing a person placed to the world's surfaces.
* **Placed things** are read only by a society of things, under walking-surfaces-v3: each rests on
  the walking line nearest it within a kerb's height, a thing that blocks walking cuts the lines it
  stands in the way of, and a thing's places are joined to the nearest point of a line
  (:func:`_things_on_surfaces`).
* **The population** is the ground's rule over the world's premises: one inhabitant per place in
  a home, counted from every premises the place reaches (``population``). A count past the
  ground's figure is refused by name before the input is validated, and the repository holds the
  recorded figure to it again (:func:`~exulanica.world.society_grounds.society_population`).

Pure: no connection and no store. The caller reads the records through the world's receipt
(:func:`exulanica.world.generated_worlds.town_records`) and makes the place from them
(:func:`walking_surfaces_place`) before it takes any lock, so composing the input generates
nothing.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.composers import composer_module
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.placed_things import PlacedThing
from exulanica.world.society_authored_ground import (
    PLACE_NODE_PREFIX,
    PLACED_THING_PREFIX,
    SocietyGround,
    StandingPolicy,
    WalkableArea,
    _input_things,
    _refused_activity,
    _thing_kinds,
    _things_one_by_one,
    _UsableObject,
    area_supports,
    destination_places,
    objects_in_region,
    thing_dependency_refs,
    things_in_region,
)
from exulanica.world.society_catalogs import PurposefulRoutine, RoutineModel, purposeful_routine
from exulanica.world.society_city_place import CityObstructions, place_from_city_records
from exulanica.world.society_composition import (
    SegmentBlocked,
    clearance_test,
    object_dependency_refs,
    policy_dependency_refs,
    validate_reviewed_affordances,
    validate_workspace_obstacles,
)
from exulanica.world.society_grounds import (
    SocietyGroundKind,
    place_dependency_for,
    refuse_population_over_budget,
    society_ground_for_navigation,
)
from exulanica.world.society_input_policy import (
    NO_AUTHORED_FRAME,
    UNREACHABLE,
    WALKING_SURFACES_COMPOSITION,
    WALKING_SURFACES_COMPOSITION_V2,
    WALKING_SURFACES_COMPOSITION_V3,
    input_profile,
)
from exulanica.world.society_living import current_routine
from exulanica.world.society_place import ceil_distance
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    input_sha256,
    validate_society_input,
)

__all__ = [
    "SEAT_NODE_PREFIX",
    "build_walking_surfaces_input",
    "place_residents",
    "walking_surfaces_ground",
    "walking_surfaces_place",
]

#: How a seat's own node is named: this prefix and the seat's spot identity.
SEAT_NODE_PREFIX: Final = "seat:"
#: The purposeful activity each kind of the world's destination offers, by the affordance its
#: use class states: a premises that admits visitors is visited, furniture that seats people is
#: rested at. Anything else the world holds is somewhere people pass, not an activity.
_VISIT: Final = "visit"
_REST: Final = "rest"


def walking_surfaces_ground(
    kind: SocietyGroundKind,
    *,
    world_id: str,
    snapshot_id: uuid.UUID,
    snapshot_sha256: str,
    composer_key: str,
    composer_version: int,
    topology: Mapping[str, Any],
    placement: Mapping[str, Any],
    region_id: str | None,
) -> SocietyGround:
    """A generated world's ground: its one region, the rectangle its tiles cover and its spawn.

    The world's composer reads its own snapshot (``stated_extent``); a snapshot it refuses, or a
    region the world does not state, is refused by name. The walkable area is the rectangle a
    walking clearance beyond each edge, because the world's surfaces run to its edge and every
    route node keeps a clearance inside the area it is published under.
    """
    if (kind.navigation, kind.floor, kind.arrival) != ("walking_surfaces", "stated", "spawn"):
        raise InvalidStructuralData(
            f"a world's walking surfaces are read on a floor it states from its spawn, not "
            f"{kind.navigation} on a {kind.floor} floor from its {kind.arrival}"
        )
    try:
        stated = composer_module(composer_key, composer_version).stated_extent(topology, placement)
    except ValueError as exc:
        raise InvalidStructuralData(str(exc)) from exc
    if region_id is not None and region_id != stated.region_id:
        raise InvalidStructuralData(f"the generated world states no region {region_id!r}")
    west, east = stated.east_mm
    north, south = stated.south_mm
    return SocietyGround(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot_sha256,
        region_id=stated.region_id,
        element_id=None,
        module_key=composer_key,
        module_version=composer_version,
        ground_kind="surfaces",
        elevation_mm=0,
        area=WalkableArea(
            "ground",
            (west + east) // 2,
            (north + south) // 2,
            (east - west) // 2 + CLEARANCE_MM,
            (south - north) // 2 + CLEARANCE_MM,
        ),
        arrival_x_mm=stated.arrival_mm[0],
        arrival_z_mm=stated.arrival_mm[2],
        world_region_ids=stated.region_ids,
        lattice_mm=kind.lattice_mm,
        navigation_profile=kind.navigation_profile,
        navigation_form=kind.navigation,
    )


def _node_kind(node_id: str) -> str:
    """What a place node stands on, from its identity: the kind the place producer names it by."""
    return node_id.split(":", 1)[0]


def _squared(a: Sequence[int], b: Sequence[int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _world_target_record(
    version_id: uuid.UUID, destination: Mapping[str, Any], affordance: str
) -> dict[str, Any]:
    """An activity of the world's own that no place can be kept for, recorded as unreachable."""
    object_id, subject_id = _subject(destination)
    return {
        "target_id": f"{subject_id}:{affordance}",
        "subject_id": subject_id,
        "object_id": object_id,
        "version_id": str(version_id),
        "affordance": affordance,
        "reason": UNREACHABLE,
    }


def _subject(destination: Mapping[str, Any]) -> tuple[str, str]:
    """A destination's object and the record subject it names: the place states its subject
    (``city.premises:<identity>`` for a city's premises, ``site.structure:<identity>`` for a site's
    structure), whose identity is the destination's own after its prefix."""
    object_id = destination["destination_id"].split(":", 1)[1]
    subject_id = str(destination["subject_id"])
    if subject_id.split(":", 1)[1] != object_id:
        raise ValueError("a destination's subject names another record than the destination")
    return object_id, subject_id


def _affordance(destination: Mapping[str, Any]) -> str | None:
    if destination["origin"] == "premises" and destination["visitor_capacity"] > 0:
        return _VISIT
    if destination["origin"] == "furniture" and _REST in destination["affordances"]:
        return _REST
    return None


def walking_surfaces_place(
    place_id: str, records: Sequence[object], routine: RoutineModel | None = None
) -> dict[str, Any]:
    """The city place a generated world's records make: its walking surfaces, spots, premises and
    furniture, as the living society reads a city (:func:`place_from_city_records`), under
    ``routine`` (the living routine a new district reads when left out; a town's living input
    names the routine its place was made under). The costly half of composing the world's input,
    so a caller makes it before taking any lock and hands it to
    :func:`build_walking_surfaces_input`, which does no generation of its own."""
    return place_from_city_records(
        place_id=place_id,
        records=list(records),
        routine=current_routine() if routine is None else routine,
    )


def place_residents(place: Mapping[str, Any]) -> int:
    """The population the ``residents`` rule gives a place: one inhabitant for each place in a home,
    the resident capacity of every destination the place reaches. The society's input records it,
    and a world's composer refuses a candidate whose count no society over its ground may hold."""
    return sum(
        int(destination.get("resident_capacity", 0)) for destination in place["destinations"]
    )


def _things_on_surfaces(
    ground: SocietyGround,
    version: AlternateVersion,
    *,
    height_above: Callable[[PlacedThing], int | None],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    things: Sequence[PlacedThing],
    kinds: Mapping[str, Any],
    standing: StandingPolicy,
    routine: PurposefulRoutine,
    segment_blocked: SegmentBlocked,
    town: CityObstructions,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The town's surfaces with its placed things on them.

    A thing rests on the surface where ``height_above`` says so (:func:`surface_height_above`);
    one that does not offers nothing
    (``OFF_GROUND``) and still blocks. An object whose kind blocks walking cuts the walking lines
    within a walking clearance of its box turned with it (:func:`_cut_at_things`). A premises or a
    seat whose node it removed is no longer stood at: the target keeps the places left, and one
    with none, or whose own node went, is recorded as unreachable. An object whose kind offers
    somewhere to rest or to visit offers it at its kind's places, turned with it, each joined to
    the nearest point of a walking line (:func:`_joined_places`), kept a standing spacing from
    every place the town still offers and every one kept before it; its activity is the
    routine's entry for its kind. A being is neither: it lives in the society."""
    usable, obstacles, records = _things_one_by_one(
        things, kinds, ground, version.version_id, height_above=height_above
    )
    clear = _near_clear(obstacles, supports=area_supports(ground), segment_blocked=segment_blocked)
    nodes, edges = _cut_at_things(nodes, edges, clear)
    at = {node["node_id"]: node["position_mm"] for node in nodes}
    remaining = set(at)
    reached = _reached_from_the_town(nodes, edges)
    kept_targets: list[dict[str, Any]] = []
    for target in targets:
        # A place is still stood at when it is left and still reached from the rest of the town:
        # a thing beside the short edge to a door or a seat can cut that edge from both ends.
        places = [node for node in target["place_node_ids"] if node in reached]
        if target["node_id"] not in remaining or not places:
            records.append(
                {
                    "target_id": target["target_id"],
                    "subject_id": target["subject_id"],
                    "object_id": target["object_id"],
                    "version_id": target["version_id"],
                    "affordance": target["affordance"],
                    "reason": UNREACHABLE,
                }
            )
            continue
        kept_targets.append({**target, "place_node_ids": places})

    def activity(item: _UsableObject) -> dict[str, Any]:
        # A placed thing's activity is the routine's entry for its own kind, where it has one.
        return {
            "activity": routine.at_object(
                item.reviewed["affordance"], item.reviewed["thing_kind"]
            ).key
        }

    nodes, edges, placed_targets, unreachable = _joined_places(
        nodes,
        edges,
        usable,
        clear,
        obstacles=dict(obstacles),
        segment_blocked=segment_blocked,
        town=town,
        version_id=version.version_id,
        standing=standing,
        activity=activity,
        kept=[
            (position[0], position[1])
            for target in kept_targets
            for node in target["place_node_ids"]
            for position in (at[node],)
        ],
    )
    records.extend(unreachable)
    return nodes, edges, [*kept_targets, *placed_targets], records


#: How far a placed thing may stand above or below the walking line under it and still rest on
#: the surface: a kerb's height (the street hierarchy's tallest kerb is 180 mm) with a footway's
#: crossfall, so a thing placed at the arrival's height anywhere on a footway beside it rests there.
RESTS_ON_SURFACE_MM: Final = 200
#: How far a placed thing's place may be from the walking line it is joined to: the footway
#: station spacing the town's place is made with (the society policy's
#: ``footway_station_spacing_mm``), fixed here so the composition does not move with that catalog.
#: A footway is wider than its walking line, so a person crosses up to that much of it to stand
#: at a thing.
PLACE_JOIN_REACH_MM: Final = 4_000
#: How the end of a walking line a placed thing cuts short is named: this prefix, the node the
#: line runs from and the node it ran towards.
CUT_NODE_PREFIX: Final = "cut:"
#: How the point a place is joined to the walking line at is named: this prefix and the place.
JOIN_NODE_PREFIX: Final = "join:"
#: How the corner of a thing's box a step goes round to reach one of its places is named: this
#: prefix and the place.
ROUND_NODE_PREFIX: Final = "round:"
#: Edges a place is never joined to: a crossing lies in the carriageway.
_UNJOINED: Final = frozenset({"crossing"})

Point = tuple[int, int]


def _plan(point: Sequence[int]) -> Point:
    """A point of the region (east, south) in the city's plan frame (east, north)."""
    return (point[0], -point[1])


def _nearest_on(point: Sequence[int], a: Sequence[int], b: Sequence[int]) -> tuple[int, int]:
    """The nearest point of segment ``a``-``b`` to ``point``, as a fraction along it: the
    numerator and the squared length, the numerator clamped to the segment."""
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dz * dz
    if length == 0:
        return 0, 1
    along = (point[0] - a[0]) * dx + (point[1] - a[1]) * dz
    return max(0, min(length, along)), length


def _at(a: Sequence[int], b: Sequence[int], along: int, length: int) -> Point:
    """The point ``along / length`` of the way from ``a`` to ``b``, to the nearest millimetre."""
    return (
        a[0] + ((b[0] - a[0]) * along * 2 + length) // (2 * length),
        a[1] + ((b[1] - a[1]) * along * 2 + length) // (2 * length),
    )


def surface_height_above(
    place: Mapping[str, Any], ground: SocietyGround
) -> Callable[[PlacedThing], int | None]:
    """How high a placed thing stands above the walking line nearest it, or None where it rests on
    the surface there (within ``RESTS_ON_SURFACE_MM``).

    The surface's height is read along the place's own edges: the nearest point of the nearest
    edge (by squared distance, then edge identity), its height the two ends' support heights
    weighed by where it lies between them. A place with no edges is the ground's plane."""
    heights = {node["node_id"]: node["support_z_mm"] for node in place["nodes"]}
    plan = {
        node["node_id"]: (node["position_mm"][0], -node["position_mm"][1])
        for node in place["nodes"]
    }
    lines = sorted(
        (edge["edge_id"], edge["from_node_id"], edge["to_node_id"]) for edge in place["edges"]
    )

    def surface(point: Point) -> int:
        best: tuple[int, int, str] | None = None
        height = ground.elevation_mm
        for edge_id, a, b in lines:
            along, length = _nearest_on(point, plan[a], plan[b])
            dx = (plan[a][0] - point[0]) * length + (plan[b][0] - plan[a][0]) * along
            dz = (plan[a][1] - point[1]) * length + (plan[b][1] - plan[a][1]) * along
            # Squared distances over a common denominator, compared exactly.
            key = (dx * dx + dz * dz, length * length, edge_id)
            if best is None or (key[0] * best[1], key[2]) < (best[0] * key[1], best[2]):
                best = key
                rise = (heights[b] - heights[a]) * along
                height = heights[a] + (2 * rise + length) // (2 * length)
        return height

    def height_above(thing: PlacedThing) -> int | None:
        above = thing.transform.y_mm - surface((thing.transform.x_mm, thing.transform.z_mm))
        return None if abs(above) <= RESTS_ON_SURFACE_MM else above

    return height_above


def _near_clear(
    obstacles: Sequence[tuple[str, list[Point]]],
    *,
    supports: Callable[..., Any],
    segment_blocked: SegmentBlocked,
) -> Callable[..., bool]:
    """``clearance_test``'s answer over every thing, asking only the things whose box comes within
    a walking clearance of the segment's bounds: a box farther than that on either axis is farther
    than a clearance from every point of the segment, so the answer is the same."""
    boxes = [
        (
            identity,
            ring,
            min(x for x, _ in ring) - CLEARANCE_MM - 1,
            min(z for _, z in ring) - CLEARANCE_MM - 1,
            max(x for x, _ in ring) + CLEARANCE_MM + 1,
            max(z for _, z in ring) + CLEARANCE_MM + 1,
        )
        for identity, ring in obstacles
    ]

    def clear(a: Point, b: Point, excluded: str | None = None) -> bool:
        low = (min(a[0], b[0]), min(a[1], b[1]))
        high = (max(a[0], b[0]), max(a[1], b[1]))
        near = [
            (identity, ring)
            for identity, ring, west, north, east, south in boxes
            if west <= high[0] and low[0] <= east and north <= high[1] and low[1] <= south
        ]
        return clearance_test(
            near, clearance_mm=CLEARANCE_MM, supports=supports, segment_blocked=segment_blocked
        )(a, b, excluded)

    return clear


def _reached_from_the_town(
    nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]
) -> set[str]:
    """Every node joined, through edges left, to at least two of the town's own nodes: the nodes a
    person walking the town can reach, which leaves out a door or a seat left joined only to the
    stub a thing cut short (a cut end is no node of the town)."""
    parent = {node["node_id"]: node["node_id"] for node in nodes}

    def root(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for edge in edges:
        a, b = root(edge["from_node_id"]), root(edge["to_node_id"])
        if a != b:
            parent[max(a, b)] = min(a, b)
    town: dict[str, int] = {}
    for node in parent:
        if not node.startswith(CUT_NODE_PREFIX):
            town[root(node)] = town.get(root(node), 0) + 1
    return {node for node in parent if town.get(root(node), 0) >= 2}


def _cut_at_things(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], clear: Callable[..., bool]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The walking lines with every placed thing that blocks walking cut out of them.

    A node within a thing's clearance goes. An edge clear of every thing stays whole; one that
    is not keeps, from each end that stays, the longest part a person walks clear from that end
    (to the millimetre), ending at a node of its own (``CUT_NODE_PREFIX``), so a thing beside a
    walking line takes only the stretch it stands in the way of."""
    kept = [node for node in nodes if clear(tuple(node["position_mm"]), tuple(node["position_mm"]))]
    position = {node["node_id"]: tuple(node["position_mm"]) for node in kept}
    cut_nodes: list[dict[str, Any]] = []
    cut_edges: list[dict[str, Any]] = []
    ends = {node["node_id"]: tuple(node["position_mm"]) for node in nodes}
    for edge in edges:
        a, b = edge["from_node_id"], edge["to_node_id"]
        if a in position and b in position and clear(position[a], position[b]):
            cut_edges.append(edge)
            continue
        for start, towards in ((a, b), (b, a)):
            if start not in position:
                continue
            origin, far = ends[start], ends[towards]
            length = ceil_distance(origin, far)
            low, high = 0, length
            while low < high:
                middle = (low + high + 1) // 2
                if clear(origin, _at(origin, far, middle, length)):
                    low = middle
                else:
                    high = middle - 1
            end = _at(origin, far, low, length)
            if end == origin:
                continue
            node_id = f"{CUT_NODE_PREFIX}{start}>{towards}"
            cut_nodes.append(
                {"node_id": node_id, "subject_id": edge["subject_id"], "position_mm": list(end)}
            )
            cut_edges.append(
                {
                    "edge_id": f"{start}|{node_id}",
                    "from_node_id": start,
                    "to_node_id": node_id,
                    "length_mm": ceil_distance(origin, end),
                    "subject_id": edge["subject_id"],
                }
            )
    return [*kept, *cut_nodes], cut_edges


def _round_corners(ring: Sequence[Point], out_mm: int) -> list[Point]:
    """The corners of a thing's box pushed out along both its faces by ``out_mm``, in ring order:
    a point that far from each face meeting there, so a step round that corner keeps that far."""
    corners = list(ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring)
    turned = []
    for index, corner in enumerate(corners):
        outward = [0.0, 0.0]
        for other in (corners[index - 1], corners[(index + 1) % len(corners)]):
            dx, dz = corner[0] - other[0], corner[1] - other[1]
            length = (dx * dx + dz * dz) ** 0.5
            outward[0] += dx / length
            outward[1] += dz / length
        turned.append(
            (round(corner[0] + out_mm * outward[0]), round(corner[1] + out_mm * outward[1]))
        )
    return turned


def _joined_places(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    usable: Sequence[_UsableObject],
    clear: Callable[..., bool],
    *,
    obstacles: Mapping[str, list[Point]],
    segment_blocked: SegmentBlocked,
    town: CityObstructions,
    version_id: uuid.UUID,
    standing: StandingPolicy,
    activity: Callable[[_UsableObject], dict[str, Any]],
    kept: list[Point],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Each placed thing's places, each joined to a walking line by a step a person can take.

    A place is kept where it is clear of every thing and of the town's own buildings, furniture
    and trees (``town``, read in the city's plan frame), at least a standing spacing from every
    place kept before it, and not exactly on a node already there. A step keeps a walking
    clearance from every other thing and from the town's own obstructions, and at least a standing
    radius from its own thing. Each line offers its one nearest point to the place, within
    ``PLACE_JOIN_REACH_MM``; the nearest offered point a step reaches (by squared distance, then
    edge identity) is the join. Where none does, the place steps first to one corner of its
    thing's box pushed out a standing radius along both faces (``ROUND_NODE_PREFIX``), and from
    there to the nearest point a line offers that corner; the shortest such way (then edge
    identity, then corner order) is kept. An end of the line is joined as it is, and any other
    point splits the line at a node of its own (``JOIN_NODE_PREFIX``), or at the place itself
    where the place stands on the line. A thing with no place kept is recorded as unreachable.
    Returns the nodes, edges, targets and records."""
    position = {node["node_id"]: tuple(node["position_mm"]) for node in nodes}
    lines = sorted(
        (edge for edge in edges if edge["subject_id"] not in _UNJOINED),
        key=lambda edge: edge["edge_id"],
    )
    by_id = {edge["edge_id"]: edge for edge in lines}
    # Every split of a line, by the point it is split at: how far along it, out of its squared
    # length, and the node there.
    splits: dict[str, dict[Point, tuple[int, str]]] = {}
    added: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    reach = PLACE_JOIN_REACH_MM * PLACE_JOIN_REACH_MM
    radius = standing.radius_mm

    def offered(point: Point) -> list[tuple[int, str, int, int, Point]]:
        found = []
        for edge in lines:
            a, b = position[edge["from_node_id"]], position[edge["to_node_id"]]
            along, length = _nearest_on(point, a, b)
            at = _at(a, b, along, length)
            gap = _squared(at, point)
            if gap <= reach:
                found.append((gap, edge["edge_id"], along, length, at))
        return sorted(found)

    for item in sorted(usable, key=lambda value: value.obj.object_id):
        obj, reviewed = item.obj, item.reviewed
        subject_id = f"thing:{obj.object_id}"
        own = f"{PLACED_THING_PREFIX}{obj.object_id}"
        ring = obstacles.get(own)

        def steps_clear(a: Point, b: Point, own: str = own, ring: Any = ring) -> bool:
            return (
                a != b
                and clear(a, b, own)
                and not (ring is not None and segment_blocked(a, b, ring, radius))
                and town.steps(_plan(a), _plan(b))
            )

        chosen: list[tuple[str, str]] = []
        for index, point in enumerate(destination_places(item, standing, CLEARANCE_MM)):
            if not clear(point, point) or not town.stands(_plan(point)):
                continue
            if any(_squared(point, other) < standing.spacing_mm**2 for other in kept):
                continue
            # A place exactly on a node would be joined by a step of no length.
            if point in position.values():
                continue
            node_id = f"{PLACE_NODE_PREFIX}{PLACED_THING_PREFIX}{obj.object_id}:{index}"
            way: tuple[tuple[int, str, int, int, Point], Point | None] | None = next(
                (
                    (candidate, None)
                    for candidate in offered(point)
                    if candidate[4] == point or steps_clear(candidate[4], point)
                ),
                None,
            )
            if way is None and ring is not None:
                rounds = []
                for order, corner in enumerate(_round_corners(ring, radius + 2)):
                    if (
                        corner in position.values()
                        or not clear(corner, corner, own)
                        or not town.stands(_plan(corner))
                        or not steps_clear(point, corner)
                    ):
                        continue
                    first = ceil_distance(point, corner)
                    for candidate in offered(corner):
                        if candidate[4] != corner and steps_clear(candidate[4], corner):
                            total = first + ceil_distance(candidate[4], corner)
                            rounds.append((total, candidate[1], order, candidate, corner))
                            break
                if rounds:
                    _total, _edge, _order, candidate, corner = min(rounds)
                    way = (candidate, corner)
            if way is None:
                continue
            kept.append(point)
            added.append({"node_id": node_id, "subject_id": subject_id, "position_mm": list(point)})
            position[node_id] = point
            (_gap, edge_id, along, _length, at), corner = way
            edge = by_id[edge_id]
            if at == position[edge["from_node_id"]]:
                join = edge["from_node_id"]
            elif at == position[edge["to_node_id"]]:
                join = edge["to_node_id"]
            elif at in splits.setdefault(edge_id, {}):
                join = splits[edge_id][at][1]
            else:
                join = node_id if at == point else f"{JOIN_NODE_PREFIX}{node_id}"
                splits[edge_id][at] = (along, join)
                if join != node_id:
                    added.append(
                        {"node_id": join, "subject_id": edge["subject_id"], "position_mm": list(at)}
                    )
                    position[join] = at
            route = [join] if corner is None else [join, f"{ROUND_NODE_PREFIX}{node_id}"]
            if corner is not None:
                added.append(
                    {"node_id": route[1], "subject_id": subject_id, "position_mm": list(corner)}
                )
                position[route[1]] = corner
            route.append(node_id)
            for a, b in itertools.pairwise(route if join != node_id else []):
                steps.append(
                    {
                        "edge_id": f"{a}|{b}",
                        "from_node_id": a,
                        "to_node_id": b,
                        "length_mm": ceil_distance(position[a], position[b]),
                        "subject_id": subject_id,
                    }
                )
            chosen.append((node_id, join))
        if not chosen:
            records.append(_refused_activity(version_id, obj, reviewed, UNREACHABLE, item.origin))
            continue
        targets.append(
            {
                "target_id": f"{subject_id}:{reviewed['affordance']}",
                "subject_id": subject_id,
                "node_id": chosen[0][1],
                "affordance": reviewed["affordance"],
                **activity(item),
                "origin": item.origin,
                "object_id": obj.object_id,
                "version_id": str(version_id),
                "enabled": True,
                "place_node_ids": [node_id for node_id, _join in chosen],
            }
        )
    joined: list[dict[str, Any]] = []
    for edge in edges:
        held = splits.get(edge["edge_id"])
        if not held:
            joined.append(edge)
            continue
        inner = [node for _along, node in sorted(held.values())]
        chain = [edge["from_node_id"], *inner, edge["to_node_id"]]
        for a, b in itertools.pairwise(chain):
            joined.append(
                {
                    "edge_id": f"{a}|{b}",
                    "from_node_id": a,
                    "to_node_id": b,
                    "length_mm": ceil_distance(position[a], position[b]),
                    "subject_id": edge["subject_id"],
                }
            )
    return [*nodes, *added], [*joined, *steps], targets, records


def build_walking_surfaces_input(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    place: Mapping[str, Any],
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    standing: StandingPolicy,
    routine: PurposefulRoutine | None = None,
    living: RoutineModel | None = None,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
    things: bool = False,
    segment_blocked: SegmentBlocked | None = None,
    obstructions: CityObstructions | None = None,
) -> dict[str, Any]:
    """Compose a generated world's input over the walking surfaces its records state, from the
    place :func:`walking_surfaces_place` made of them for ``ground``.

    With ``living``, the living routine ``place`` was made under, the input is a
    walking-surfaces-v2 input that also carries the place itself, for the living town to walk;
    with ``things``, a walking-surfaces-v3 input for a society of things, which also reads the
    things placed in the world's region (``segment_blocked`` tells whether a step crosses one,
    ``obstructions`` what of the town's own a thing's place keeps clear of);
    without either, the walking-surfaces-v1 input the purposeful society reads."""
    if version_delta_sha256(version) != version.state_sha256:
        raise ValueError("authored delta digest mismatch")
    validate_reviewed_affordances(reviewed_affordances)
    validate_workspace_obstacles(workspace_obstacles)
    if availability not in ("available", "unavailable"):
        raise ValueError("invalid current availability")
    if (availability == "available") != (unavailable_reason is None):
        raise ValueError("availability and reason disagree")
    if version.world_id != ground.world_id:
        raise ValueError("the ground belongs to another world")
    if ground.navigation_form != "walking_surfaces":
        raise ValueError("this composition walks a world's own surfaces")
    chosen = purposeful_routine() if routine is None else routine
    if things and (living is not None or segment_blocked is None or obstructions is None):
        raise ValueError(
            "a society of things reads no living place and needs a blocking test and the town's "
            "obstructions"
        )
    composition = (
        WALKING_SURFACES_COMPOSITION_V3
        if things
        else WALKING_SURFACES_COMPOSITION
        if living is None
        else WALKING_SURFACES_COMPOSITION_V2
    )
    if living is not None and place.get("routine_sha256") != living.sha256:
        raise ValueError("the place was made under another living routine")
    if place.get("place_id") != ground.place_id:
        raise ValueError("the place was made for another ground")
    reason = unavailable_reason
    if version.source_snapshot_id != ground.snapshot_id:
        reason = reason or "authored_ground_snapshot_mismatch"
    if version.source_invalidated:
        reason = reason or "authored_source_invalidated"
    if version.element_overrides:
        reason = reason or "unsupported_structural_overrides"
    if place["availability"] != "available":
        reason = reason or f"walking_surfaces_unavailable:{place['unavailable_reason']}"

    def point(position: Sequence[int]) -> list[int]:
        return [position[0], -position[1]]

    nodes = [
        {
            "node_id": node["node_id"],
            "subject_id": _node_kind(node["node_id"]),
            "position_mm": point(node["position_mm"]),
        }
        for node in place["nodes"]
    ]
    edges = [
        {
            "edge_id": edge["edge_id"],
            "from_node_id": edge["from_node_id"],
            "to_node_id": edge["to_node_id"],
            "length_mm": edge["length_mm"],
            "subject_id": edge["kind"],
        }
        for edge in place["edges"]
    ]
    by_node = {node["node_id"]: node for node in nodes}
    spots = {spot["spot_id"]: spot for spot in place["spots"]}
    targets: list[dict[str, Any]] = []
    records_list: list[dict[str, Any]] = []
    kept: list[list[int]] = []
    residents = place_residents(place)
    for destination in sorted(place["destinations"], key=lambda d: d["destination_id"]):
        affordance = _affordance(destination)
        if affordance is None or not destination["enabled"]:
            continue
        if destination["origin"] == "premises":
            candidates = [(destination["node_id"], by_node[destination["node_id"]]["position_mm"])]
        else:
            candidates = [
                (f"{SEAT_NODE_PREFIX}{spot_id}", point(spots[spot_id]["position_mm"]))
                for spot_id in destination["spot_ids"]
            ]
        places = []
        for node_id, position in candidates:
            if any(_squared(position, other) < standing.spacing_mm**2 for other in kept):
                continue
            kept.append(position)
            places.append((node_id, position))
        if not places:
            records_list.append(_world_target_record(version.version_id, destination, affordance))
            continue
        object_id, subject_id = _subject(destination)
        if destination["origin"] == "furniture":
            access = by_node[destination["node_id"]]
            for node_id, position in places:
                nodes.append(
                    {"node_id": node_id, "subject_id": subject_id, "position_mm": position}
                )
                edges.append(
                    {
                        "edge_id": f"{access['node_id']}|{node_id}",
                        "from_node_id": access["node_id"],
                        "to_node_id": node_id,
                        "length_mm": ceil_distance(access["position_mm"], position),
                        "subject_id": subject_id,
                    }
                )
        targets.append(
            {
                "target_id": f"{subject_id}:{affordance}",
                "subject_id": subject_id,
                "node_id": destination["node_id"],
                "affordance": affordance,
                "activity": chosen.default(affordance).key,
                "origin": destination["origin"],
                "object_id": object_id,
                "version_id": str(version.version_id),
                "enabled": True,
                "place_node_ids": [node_id for node_id, _ in places],
            }
        )
    placed = things_in_region(version, ground) if things else []
    thing_kinds, unknown = _thing_kinds(placed)
    # Only a society of things reads how high a thing stands: v1 and v2 read no height.
    height_above = surface_height_above(place, ground) if things else None
    if things and unknown is not None:
        reason = reason or unknown
    if (
        things
        and unknown is None
        and segment_blocked is not None
        and obstructions is not None
        and height_above is not None
    ):
        nodes, edges, targets, refused = _things_on_surfaces(
            ground,
            version,
            height_above=height_above,
            nodes=nodes,
            edges=edges,
            targets=targets,
            things=placed,
            kinds=thing_kinds,
            standing=standing,
            routine=chosen,
            segment_blocked=segment_blocked,
            town=obstructions,
        )
        records_list.extend(refused)
    # A world whose homes hold more people than a society over its ground may is refused by that
    # name here, before the input is validated against the schema's own ceiling of 512.
    refuse_population_over_budget(
        residents, society_ground_for_navigation(ground.navigation_profile)
    )
    in_region = objects_in_region(version, ground)
    for obj in in_region:
        reviewed = reviewed_affordances.get(obj.asset_sha256)
        if not obj.removed and reviewed is not None and reviewed.get("affordance"):
            records_list.append(_refused_activity(version.version_id, obj, reviewed, UNREACHABLE))
    unread = [
        {"instance_id": instance.instance_id, "reason": NO_AUTHORED_FRAME}
        for instance in sorted(version.environment_instances, key=lambda value: value.instance_id)
        if not instance.removed
    ]
    refs = [dict(ref) for ref in dependency_refs]
    refs.extend(
        policy_dependency_refs(
            composition_profile=composition,
            version_id=version.version_id,
            registration=ground.registration(),
            reviewed_affordances=reviewed_affordances,
        )
    )
    refs.extend(
        object_dependency_refs(
            version,
            reviewed_affordances,
            objects=in_region,
            workspace_obstacles=workspace_obstacles,
        )
    )
    if things:
        refs.extend(thing_dependency_refs(version.version_id, placed, thing_kinds))
    refs.append(
        {
            # The kind of place its ground says the producer of its surfaces makes.
            "kind": place_dependency_for(ground.navigation_profile),
            "identity": ground.place_id,
            "sha256": place["document_sha256"],
        }
    )
    navigation = {
        "profile": ground.navigation_profile,
        "clearance_mm": CLEARANCE_MM,
        "walkable_area": ground.area.document(),
        "arrival_mm": [ground.arrival_x_mm, ground.arrival_z_mm],
        "nodes": sorted(nodes, key=lambda node: node["node_id"]),
        "edges": sorted(edges, key=lambda edge: edge["edge_id"]),
        "destinations": [],
        "unavailable_reason": None,
        "standing_spacing_mm": standing.spacing_mm,
    }
    if reason is not None:
        navigation.update(nodes=[], edges=[], unavailable_reason=reason)
        targets, records_list, unread = [], [], []
    deduplicated = {(r["kind"], r["identity"], r["sha256"]): r for r in refs}
    document = {
        "profile": input_profile(composition),
        "input_seq": input_seq,
        "world_id": version.world_id,
        "version_id": str(version.version_id),
        "district_id": ground.place_id,
        "district_document_sha256": ground.document_sha256,
        "base_artifact_sha256": ground.snapshot_sha256,
        "frame": ground.frame(),
        "authored_state": {"edit_seq": version.edit_seq, "delta_sha256": version.state_sha256},
        "navigation": navigation,
        "targets": sorted(targets, key=lambda target: target["target_id"]),
        "dependency_refs": [deduplicated[key] for key in sorted(deduplicated)],
        "availability": "available" if reason is None else "unavailable",
        "unavailable_reason": reason,
        "unavailable_affordances": sorted(records_list, key=lambda row: row["target_id"]),
        "unread_placements": unread,
        "routine": chosen.binding(),
        "population": {"rule": "residents", "size": residents},
    }
    if things:
        document["things"] = (
            _input_things(placed, thing_kinds, ground, height_above) if reason is None else []
        )
        # The kind the ground's catalog entry names its population of, recorded here so genesis
        # and replay read it from the input, whatever a later catalog version says.
        kind = society_ground_for_navigation(ground.navigation_profile).population_kind
        if kind is None:
            raise ValueError("the ground's catalog entry names no kind its population is made of")
        document["population_kind"] = dict(kind)
        if input_seq == 1:
            # A society's first input records the ability modules it runs, by version, and its
            # minute runs exactly those for its whole life, whatever a later table adds.
            from exulanica.abilities.registry import current_modules

            document["modules"] = list(current_modules())
    if living is not None:
        document["living"] = {
            "routine": living.binding(),
            "place": dict(place) if reason is None else None,
        }
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)
    return document
