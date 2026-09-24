"""Bounded v2 society policy over the reviewed composed input, never a district compiler."""

from __future__ import annotations

import heapq
import math
import uuid
from copy import deepcopy
from itertools import pairwise
from typing import Any

from exulanica.world.society import (
    SOCIETY_NAMESPACE,
    SOCIETY_POPULATION,
    SocietyEvent,
    society_state_sha256,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_INPUT,
    AUTHORED_GROUND_INPUT_V2,
    AUTHORED_GROUND_INPUTS,
    LOCAL_FAILURE_INPUTS,
    LOCAL_INPUT,
    UNREAD_PLACEMENT_REASONS,
    is_authored_ground,
    validate_local_affordances,
    validate_unread_placements,
)
from exulanica.world.society_legacy import initial_society

PURPOSEFUL_PROFILE = "exulanica-society/v2"
INPUT_PROFILE = "exulanica.society-input/v1"
#: The travel budget a new society records in its state, 60 m per one-minute tick: at most a
#: metre each simulated second. A stored society walks at the budget its own state records.
MOVEMENT_BUDGET_MM = 60_000
#: The two reviewed activities and how many ticks each takes after arrival.
DURATIONS = {"visit": 1, "rest": 3}
#: The v2 policy's own utility figures: a need at or above this prefers rest to a visit, and a
#: completed activity lowers the need by its relief. They are part of what exulanica-society/v2
#: is, so a stored v2 history replays under exactly these; a different figure is a new profile.
NEED_PREFERS_REST_MILLI = 750
RELIEF_MILLI = {"visit": 20, "rest": 500}
#: Every input profile the policy consumes, and the navigation and frame each one declares.
#: A district projection states the geodetic origin its millimetres are measured from; a saved
#: world's authored ground has no surveyed origin and states none rather than inventing one.
DISTRICT_INPUTS = (INPUT_PROFILE, LOCAL_INPUT)
NAVIGATION_PROFILES = {
    INPUT_PROFILE: "bounded-sidewalk-graph/v1",
    LOCAL_INPUT: "bounded-sidewalk-graph/v1",
    AUTHORED_GROUND_INPUT: "authored-ground-lattice/v1",
    AUTHORED_GROUND_INPUT_V2: "authored-ground-lattice/v1",
}
FRAME_NAMES = {
    INPUT_PROFILE: "flatiron-local-mm",
    LOCAL_INPUT: "flatiron-local-mm",
    AUTHORED_GROUND_INPUT: "authored-ground-local-mm",
    AUTHORED_GROUND_INPUT_V2: "authored-ground-local-mm",
}
#: Input profiles whose activities state the places their occupants stand at. A society advancing
#: over one keeps each place to one person and keeps people waiting clear of every place.
PLACE_INPUTS = (AUTHORED_GROUND_INPUT_V2,)
CLEARANCE_MM = 450
#: The fewest inhabitants a society over a district starts with. The database no longer holds a
#: v2 or v3 population to this, because a row cannot tell a district from a saved world's own
#: ground; the initializer, which every creation and every replay passes through, does.
DISTRICT_MINIMUM_POPULATION = 100
#: No inhabitant of a saved world starts on, or within this many millimetres of, the point a
#: person arrives at, so the first view of a world is never somebody's back.
ARRIVAL_CLEARANCE_MM = 2_000


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 1000


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def input_sha256(document: dict[str, Any]) -> str:
    return society_state_sha256({k: v for k, v in document.items() if k != "document_sha256"})


def _validate_society_input(document: dict[str, Any]) -> None:
    """Validate the frozen simulation projection. Geometry and live rights remain adapter duties."""
    fields = {
        "profile",
        "input_seq",
        "world_id",
        "version_id",
        "district_id",
        "district_document_sha256",
        "base_artifact_sha256",
        "frame",
        "authored_state",
        "navigation",
        "targets",
        "dependency_refs",
        "availability",
        "unavailable_reason",
        "document_sha256",
    }
    _require(isinstance(document, dict), "invalid society input fields")
    if document.get("profile") in LOCAL_FAILURE_INPUTS:
        fields.add("unavailable_affordances")
    if document.get("profile") in UNREAD_PLACEMENT_REASONS:
        fields.add("unread_placements")
    _require(set(document) == fields, "invalid society input fields")
    profile = document["profile"]
    _require(profile in NAVIGATION_PROFILES, "unsupported society input profile")
    _require(_integer(document["input_seq"], 1, 2**53 - 1), "invalid input sequence")
    _require(all(_text(document[k]) for k in ("world_id", "district_id")), "invalid input scope")
    _require(str(uuid.UUID(document["version_id"])) == document["version_id"], "invalid version ID")
    for key in ("district_document_sha256", "base_artifact_sha256", "document_sha256"):
        _require(_digest(document[key]), f"invalid {key}")
    frame = document["frame"]
    surveyed = profile in DISTRICT_INPUTS
    expected = {"name", "axis_order", "horizontal_unit", "altitude_reference"}
    if surveyed:
        expected = expected | {"origin_crs84_e7"}
    _require(isinstance(frame, dict) and set(frame) == expected, "invalid frame")
    _require(
        frame["name"] == FRAME_NAMES[profile]
        and frame["axis_order"] == ["east", "south"]
        and frame["horizontal_unit"] == "millimetre"
        and frame["altitude_reference"] == "authored-flat-ground",
        "unsupported frame",
    )
    _require(
        not surveyed
        or (
            isinstance(frame["origin_crs84_e7"], list)
            and len(frame["origin_crs84_e7"]) == 2
            and all(_integer(v, -1800000000, 1800000000) for v in frame["origin_crs84_e7"])
        ),
        "invalid frame origin",
    )
    authored = document["authored_state"]
    _require(
        isinstance(authored, dict)
        and set(authored) == {"edit_seq", "delta_sha256"}
        and _integer(authored["edit_seq"], 0, 2**53 - 1)
        and _digest(authored["delta_sha256"]),
        "invalid authored cursor",
    )
    _require(document["availability"] in ("available", "unavailable"), "invalid availability")
    _require(
        (document["availability"] == "available" and document["unavailable_reason"] is None)
        or (document["availability"] == "unavailable" and _text(document["unavailable_reason"])),
        "availability requires an explicit reason",
    )
    nav = document["navigation"]
    navigation_fields = {
        "profile",
        "clearance_mm",
        "nodes",
        "edges",
        "destinations",
        "unavailable_reason",
    }
    if is_authored_ground(profile):
        navigation_fields.update(("walkable_area", "arrival_mm"))
    if profile in PLACE_INPUTS:
        navigation_fields.add("standing_spacing_mm")
    _require(isinstance(nav, dict) and set(nav) == navigation_fields, "invalid navigation fields")
    _require(
        nav["profile"] == NAVIGATION_PROFILES[profile] and nav["clearance_mm"] == CLEARANCE_MM,
        "unsupported navigation profile",
    )
    _require(
        nav["unavailable_reason"] is None or _text(nav["unavailable_reason"]),
        "invalid navigation unavailable reason",
    )
    _require(isinstance(nav["nodes"], list) and len(nav["nodes"]) <= 16384, "node bound exceeded")
    nodes = {}
    for node in nav["nodes"]:
        _require(
            set(node) == {"node_id", "subject_id", "position_mm"}
            and _text(node["node_id"])
            and _text(node["subject_id"]),
            "invalid node",
        )
        point = node["position_mm"]
        _require(
            isinstance(point, list)
            and len(point) == 2
            and all(_integer(v, -(10**9), 10**9) for v in point),
            "invalid node position",
        )
        _require(node["node_id"] not in nodes, "duplicate node")
        nodes[node["node_id"]] = node
    _require(list(nodes) == sorted(nodes), "nodes must be sorted")
    if is_authored_ground(profile):
        _validate_walkable_area(nav["walkable_area"], nodes.values(), nav["clearance_mm"])
        arrival = nav["arrival_mm"]
        _require(
            isinstance(arrival, list)
            and len(arrival) == 2
            and all(_integer(v, -(10**9), 10**9) for v in arrival),
            "invalid arrival point",
        )
    _require(isinstance(nav["edges"], list) and len(nav["edges"]) <= 65536, "edge bound exceeded")
    edge_ids = []
    pairs = set()
    for edge in nav["edges"]:
        _require(
            set(edge) == {"edge_id", "from_node_id", "to_node_id", "length_mm", "subject_id"}
            and _text(edge["edge_id"])
            and _text(edge["subject_id"]),
            "invalid edge",
        )
        a, b = edge["from_node_id"], edge["to_node_id"]
        _require(a in nodes and b in nodes and a != b, "unknown edge endpoint")
        pair = tuple(sorted((a, b)))
        _require(pair not in pairs, "duplicate edge pair")
        pairs.add(pair)
        squared = sum(
            (x - y) ** 2
            for x, y in zip(nodes[a]["position_mm"], nodes[b]["position_mm"], strict=True)
        )
        length = math.isqrt(squared)
        length += length * length < squared
        _require(
            _integer(edge["length_mm"], 1, 2**53 - 1) and edge["length_mm"] == length,
            "edge length must be ceil Euclidean distance",
        )
        edge_ids.append(edge["edge_id"])
    _require(edge_ids == sorted(set(edge_ids)), "edges must be unique and sorted")
    _require(
        isinstance(nav["destinations"], list) and len(nav["destinations"]) <= 4096,
        "destination bound exceeded",
    )
    destination_ids = set()
    for dest in nav["destinations"]:
        _require(
            set(dest) == {"destination_id", "subject_id", "node_id", "affordance", "duration_ticks"}
            and _text(dest["destination_id"])
            and _text(dest["subject_id"])
            and dest["node_id"] in nodes,
            "invalid destination",
        )
        _require(
            dest["affordance"] in DURATIONS
            and type(dest["duration_ticks"]) is int
            and dest["duration_ticks"] == DURATIONS[dest["affordance"]],
            "unreviewed affordance",
        )
        _require(dest["destination_id"] not in destination_ids, "duplicate destination")
        destination_ids.add(dest["destination_id"])
    _require(
        isinstance(document["targets"], list) and len(document["targets"]) <= 4096,
        "target bound exceeded",
    )
    target_fields = {
        "target_id",
        "subject_id",
        "node_id",
        "affordance",
        "duration_ticks",
        "origin",
        "object_id",
        "version_id",
        "enabled",
    }
    if profile in PLACE_INPUTS:
        target_fields.add("place_node_ids")
    target_ids = []
    for target in document["targets"]:
        _require(set(target) == target_fields, "invalid target fields")
        _require(
            _text(target["target_id"]) and _text(target["subject_id"]) and _text(target["node_id"]),
            "invalid target reference",
        )
        _require(target["version_id"] == document["version_id"], "cross-branch target")
        _require(
            target["affordance"] in DURATIONS
            and type(target["duration_ticks"]) is int
            and target["duration_ticks"] == DURATIONS[target["affordance"]],
            "unreviewed affordance",
        )
        _require(type(target["enabled"]) is bool, "invalid enabled value")
        _require(
            not target["enabled"]
            or target["node_id"] in nodes
            or document["availability"] == "unavailable",
            "unknown target access node",
        )
        _require(
            (target["origin"] == "district" and target["object_id"] is None)
            or (target["origin"] == "authored" and _text(target["object_id"])),
            "invalid target origin",
        )
        target_ids.append(target["target_id"])
    _require(target_ids == sorted(set(target_ids)), "targets must be unique and sorted")
    if profile in PLACE_INPUTS:
        _validate_places(document, nodes)
    if profile in LOCAL_FAILURE_INPUTS:
        validate_local_affordances(document, DURATIONS)
    if profile in UNREAD_PLACEMENT_REASONS:
        validate_unread_placements(document)
    refs = document["dependency_refs"]
    _require(isinstance(refs, list) and len(refs) <= 8192, "dependency bound exceeded")
    for ref in refs:
        _require(
            set(ref) == {"kind", "identity", "sha256"}
            and _text(ref["kind"])
            and _text(ref["identity"])
            and _digest(ref["sha256"]),
            "invalid dependency",
        )
    keys = [(r["kind"], r["identity"], r["sha256"]) for r in refs]
    _require(keys == sorted(set(keys)), "dependencies must be unique and sorted")
    _require(input_sha256(document) == document["document_sha256"], "society input digest mismatch")


def _validate_places(document: dict[str, Any], nodes: dict[str, Any]) -> None:
    """Every activity names where its occupants stand, and no two of them stand too close.

    A place is a node of the input's own graph, belongs to one activity only, and lies at least
    the stated standing spacing from every other place, so an input cannot seat two people inside
    one another however the society fills it.
    """
    spacing = document["navigation"]["standing_spacing_mm"]
    _require(_integer(spacing, 1, 10**6), "invalid standing spacing")
    seen: list[str] = []
    for target in document["targets"]:
        places = target["place_node_ids"]
        _require(
            isinstance(places, list)
            and bool(places)
            and len(places) <= 4096
            and all(_text(node) and node in nodes for node in places),
            "invalid destination places",
        )
        seen.extend(places)
    _require(len(seen) == len(set(seen)), "a place belongs to one activity")
    positions = [nodes[node]["position_mm"] for node in seen]
    for index, point in enumerate(positions):
        _require(
            all(
                (point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2 >= spacing**2
                for other in positions[index + 1 :]
            ),
            "two places stand closer than the standing spacing",
        )


def _validate_walkable_area(area: Any, nodes: Any, clearance_mm: int) -> None:
    """A saved world's input states the area it routes across, and routes nowhere else.

    ``source`` says whether the ground stated that extent or the society declared it because the
    ground states none. Every node sits a full clearance inside the area, so a stored input cannot
    carry a route the area it names would not have produced.
    """
    _require(
        isinstance(area, dict)
        and set(area) == {"source", "centre_mm", "half_width_mm", "half_depth_mm"}
        and area["source"] in ("ground", "declared")
        and isinstance(area["centre_mm"], list)
        and len(area["centre_mm"]) == 2
        and all(_integer(v, -(10**9), 10**9) for v in area["centre_mm"])
        and _integer(area["half_width_mm"], 1, 10**9)
        and _integer(area["half_depth_mm"], 1, 10**9),
        "invalid walkable area",
    )
    cx, cz = area["centre_mm"]
    width = area["half_width_mm"] - clearance_mm
    depth = area["half_depth_mm"] - clearance_mm
    for node in nodes:
        x_mm, z_mm = node["position_mm"]
        _require(
            abs(x_mm - cx) <= width and abs(z_mm - cz) <= depth,
            "a route node lies outside the stated walkable area",
        )


def validate_society_input(document: dict[str, Any]) -> None:
    try:
        _validate_society_input(document)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("malformed society input") from exc


def validate_input_successor(previous: dict[str, Any], current: dict[str, Any]) -> None:
    validate_society_input(current)
    _require(current["input_seq"] == previous["input_seq"] + 1, "input sequence gap")
    for key in ("world_id", "version_id", "district_id", "frame", "base_artifact_sha256"):
        _require(current[key] == previous[key], f"input changed immutable {key}")
    if is_authored_ground(previous["profile"]) or is_authored_ground(current["profile"]):
        _require(
            is_authored_ground(previous["profile"]) and is_authored_ground(current["profile"]),
            "a saved world's society reads only its own ground's inputs",
        )
        # A composition policy moves forward: a society that has consumed a later profile's input
        # never goes back to an earlier one.
        _require(
            AUTHORED_GROUND_INPUTS.index(current["profile"])
            >= AUTHORED_GROUND_INPUTS.index(previous["profile"]),
            "input profile moved backwards",
        )
        # A society's area is part of what the society is, like its seed. An edit changes what is
        # in the area, never where the area is.
        _require(
            current["navigation"]["walkable_area"] == previous["navigation"]["walkable_area"],
            "input changed immutable walkable_area",
        )
        # Where a person arrives is the snapshot's own and cannot move under a society either.
        _require(
            current["navigation"]["arrival_mm"] == previous["navigation"]["arrival_mm"],
            "input changed immutable arrival_mm",
        )
    old, new = previous["authored_state"], current["authored_state"]
    _require(new["edit_seq"] >= old["edit_seq"], "authored edit order regressed")
    _require(
        new["edit_seq"] != old["edit_seq"] or new["delta_sha256"] == old["delta_sha256"],
        "authored digest changed without an edit",
    )


def _graph(document: dict[str, Any]) -> tuple[dict, dict, dict]:
    nodes = {n["node_id"]: n for n in document["navigation"]["nodes"]}
    adjacent: dict[str, list] = {n: [] for n in nodes}
    edges = {}
    for edge in document["navigation"]["edges"]:
        a, b = edge["from_node_id"], edge["to_node_id"]
        adjacent[a].append((b, edge))
        adjacent[b].append((a, edge))
        edges[frozenset((a, b))] = edge
    for values in adjacent.values():
        values.sort(key=lambda pair: pair[0])
    return nodes, adjacent, edges


def _paths(start: str, adjacent: dict) -> dict[str, tuple[int, tuple[str, ...]]]:
    queue = [(0, (start,), start)]
    best = {start: (0, (start,))}
    while queue:
        distance, path, node = heapq.heappop(queue)
        if best[node] != (distance, path):
            continue
        for neighbor, edge in adjacent[node]:
            candidate = (distance + edge["length_mm"], (*path, neighbor))
            if neighbor not in best or candidate < best[neighbor]:
                best[neighbor] = candidate
                heapq.heappush(queue, (*candidate, neighbor))
    return best


def _spawn_nodes(document: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    """The nodes a newcomer may be placed at over this input, and whether it is a saved world's.

    Only declared nodes in components containing reviewed targets. This is placement of people
    who are not yet there, never recovery or teleportation of anybody who is.
    """
    _require(
        document["availability"] == "available"
        and document["navigation"]["unavailable_reason"] is None,
        "initial district unavailable",
    )
    nodes, adjacent, _ = _graph(document)
    targets = [t for t in document["targets"] if t["enabled"]]
    _require(bool(nodes) and bool(targets), "initial society requires reachable targets")
    reachable = set()
    for target in targets:
        if target["node_id"] not in reachable:
            reachable.update(_paths(target["node_id"], adjacent))
    spawn_nodes = sorted(reachable)
    authored = is_authored_ground(document["profile"])
    if authored:
        # A saved world: nobody starts where a person arrives or beside it, and the few who live
        # there start spread across the area in node order rather than in its first column.
        ax, az = document["navigation"]["arrival_mm"]
        spawn_nodes = [
            node
            for node in spawn_nodes
            if (nodes[node]["position_mm"][0] - ax) ** 2 + (nodes[node]["position_mm"][1] - az) ** 2
            > ARRIVAL_CLEARANCE_MM**2
        ]
        if document["profile"] in PLACE_INPUTS:
            # Nobody starts at a destination: not on a place, not where it joins the lattice and
            # not within a standing spacing of one.
            crowded = standing_exclusions(document)
            spawn_nodes = [node for node in spawn_nodes if node not in crowded]
        _require(
            bool(spawn_nodes),
            "no reachable place to start clear of the arrival point and every destination",
        )
    return nodes, spawn_nodes, authored


def _newcomers(
    society_id: uuid.UUID,
    seed: str,
    document: dict[str, Any],
    *,
    population: int,
    engine_profile: str,
) -> dict[str, Any]:
    """The seeded people of a society, each placed at a starting node over ``document``."""
    nodes, spawn_nodes, authored = _spawn_nodes(document)
    engine = society_engine(engine_profile)
    state = initial_society(
        society_id,
        seed,
        population=population,
        minimum_population=engine.population_minimum if authored else DISTRICT_MINIMUM_POPULATION,
        maximum_population=engine.population_maximum,
    )
    for person in state["inhabitants"]:
        node = (
            spawn_nodes[person["ordinal"] * len(spawn_nodes) // population]
            if authored
            else spawn_nodes[person["ordinal"] % len(spawn_nodes)]
        )
        point = nodes[node]["position_mm"]
        person.update(
            position_mm=list(point),
            goal=None,
            route=None,
            location={"node_id": node, "edge": None},
            target=None,
            action={
                "kind": "idle",
                "status": "active",
                "target_id": None,
                "remaining_ticks": 0,
                "reason": "awaiting_goal",
            },
            motion_path_mm=[list(point)],
            explanation={
                "summary": "Simulated inhabitant awaiting its first goal.",
                "event_ids": [],
            },
            last_completed_target_id=None,
            blocked_key=None,
            route_geometry_sha256=None,
        )
    return state


def initial_purposeful_society(
    society_id: uuid.UUID,
    seed: str,
    document: dict[str, Any],
    *,
    population: int = SOCIETY_POPULATION,
    engine_profile: str = PURPOSEFUL_PROFILE,
) -> dict[str, Any]:
    """A purposeful genesis over input 1, within ``engine_profile``'s population bounds."""
    validate_society_input(document)
    _require(document["input_seq"] == 1, "genesis requires input sequence 1")
    state = _newcomers(
        society_id, seed, document, population=population, engine_profile=engine_profile
    )
    state.update(
        profile=PURPOSEFUL_PROFILE,
        branch_id=document["version_id"],
        input_seq=1,
        input_sha256=document["document_sha256"],
        movement_budget_mm_per_tick=MOVEMENT_BUDGET_MM,
        seed_sha256=seed,
    )
    return state


def arriving_inhabitants(
    society_id: uuid.UUID,
    seed: str,
    document: dict[str, Any],
    *,
    population: int,
    engine_profile: str = PURPOSEFUL_PROFILE,
) -> list[dict[str, Any]]:
    """The same seeded people, placed over ``document`` by the rule a genesis places them by.

    For inhabitants who were sent away and are brought back: the same identities and names, at
    spread starting places over the world as it is now, with no goal. What they did before they
    left stays in the history; nothing of it is restored.
    """
    validate_society_input(document)
    return _newcomers(
        society_id, seed, document, population=population, engine_profile=engine_profile
    )["inhabitants"]


def standing_exclusions(document: dict[str, Any]) -> frozenset[str]:
    """The nodes nobody waits or starts at in an input whose activities state places.

    Every place, the lattice node each place is joined to, and every node within a standing
    spacing of a place: a person standing at any of them would stand in the way of, or inside,
    somebody using a destination.
    """
    navigation = document["navigation"]
    spacing = navigation["standing_spacing_mm"]
    positions = {node["node_id"]: node["position_mm"] for node in navigation["nodes"]}
    places = {node for target in document["targets"] for node in target["place_node_ids"]}
    excluded = set(places)
    for edge in navigation["edges"]:
        if edge["to_node_id"] in places:
            excluded.add(edge["from_node_id"])
        if edge["from_node_id"] in places:
            excluded.add(edge["to_node_id"])
    for node, (x, z) in positions.items():
        if any(
            (x - positions[place][0]) ** 2 + (z - positions[place][1]) ** 2 < spacing**2
            for place in places
        ):
            excluded.add(node)
    return frozenset(excluded)


def input_graph(document: dict[str, Any]) -> tuple[dict, dict]:
    """The nodes and edges an input's navigation states, keyed as the planner walks them."""
    nodes, _, edges = _graph(document)
    return nodes, edges


def supports(graph: tuple[dict, dict], person: dict) -> bool:
    """Whether a graph still has the node or edge a person stands on, where the person is."""
    return _location_valid(person, *graph)


def held_nodes(people: list[dict], me: dict, *, graph: tuple[dict, dict] | None = None) -> set[str]:
    """Where everybody else stands or is on the way to, as the minute has left them so far.

    Given the ``graph`` of the input a place is taken in, somebody that graph no longer supports
    holds nothing: a position an edit left behind never keeps a place from anybody else.
    """
    held = set()
    for other in people:
        if other is me:
            continue
        if graph is not None and not _location_valid(other, *graph):
            continue
        if other["goal"] is not None and other["route"] is not None:
            held.add(other["route"]["destination_node_id"])
        if other["location"]["edge"] is None:
            held.add(other["location"]["node_id"])
    return held


def _step_aside(
    person: dict,
    people: list[dict],
    graph: tuple[dict, dict, dict],
    places: frozenset[str],
    crowded: frozenset[str],
) -> str | None:
    """The lattice node a person steps to when an edit took away where it stood, or None.

    The nearest node of the new graph to where the person is, by squared distance and then node
    id, that is not a place, has an edge, and that nobody else stands at or is headed to; first
    among the nodes nobody waiting would be in the way at, as a person making room waits, then
    among the rest.
    """
    nodes, adjacent, edges = graph
    held = held_nodes(people, person, graph=(nodes, edges))
    x, z = person["position_mm"]
    open_ground = [
        ((node["position_mm"][0] - x) ** 2 + (node["position_mm"][1] - z) ** 2, node_id)
        for node_id, node in nodes.items()
        if node_id not in places and node_id not in held and adjacent[node_id]
    ]
    for pool in (
        [pair for pair in open_ground if pair[1] not in crowded],
        open_ground,
    ):
        if pool:
            return min(pool)[1]
    return None


def _performing_at(person: dict, targets: dict[str, dict]) -> dict | None:
    """The target a person performing at a place keeps performing at, or None.

    Somebody part way through an activity at a place the new input still states, for the same
    activity and duration, keeps going: an edit elsewhere in the world does not get them up.
    """
    action, location, held = person["action"], person["location"], person["target"]
    if (
        held is None
        or location["edge"] is not None
        or action["status"] != "active"
        or action["kind"] not in DURATIONS
    ):
        return None
    current = targets.get(held["target_id"])
    if (
        current is None
        or not current["enabled"]
        or current["affordance"] != held["affordance"]
        or current["duration_ticks"] != held["duration_ticks"]
        or location["node_id"] not in current.get("place_node_ids", ())
    ):
        return None
    return current


def _place_for(
    target: dict, policy: dict | None, paths: dict, held: set[str], here: str | None
) -> str | None:
    """The place a person takes at an activity, or None when it has no room for them.

    A person directed there takes the place its request was promised before the step; anybody
    else takes the place it stands at, or the first one nobody holds.
    """
    if policy and policy.get("preferred_target_id") == target["target_id"]:
        promise = policy.get("place_node_id")
        if promise is not None:
            return promise if promise in paths else None
    return _free_place(target, paths, held, here)


def _free_place(target: dict, paths: dict, held: set[str], here: str | None) -> str | None:
    """The place a person takes at an activity: the one it stands at, else the first free one."""
    if here in target["place_node_ids"]:
        return here
    return next(
        (node for node in target["place_node_ids"] if node in paths and node not in held), None
    )


def _location_valid(person: dict, nodes: dict, edges: dict) -> bool:
    loc = person["location"]
    if loc["edge"] is None:
        return (
            loc["node_id"] in nodes
            and nodes[loc["node_id"]]["position_mm"] == person["position_mm"]
        )
    held = loc["edge"]
    a, b = held["from_node_id"], held["to_node_id"]
    edge = edges.get(frozenset((a, b)))
    return (
        edge is not None
        and edge["edge_id"] == held["edge_id"]
        and edge["length_mm"] == held["length_mm"]
        and nodes[a]["position_mm"] == held["from_position_mm"]
        and nodes[b]["position_mm"] == held["to_position_mm"]
    )


def _route_valid(person: dict, nodes: dict, edges: dict) -> bool:
    route = person["route"]
    if route is None:
        return True
    path = route["node_ids"][route["edge_index"] :]
    return all(n in nodes for n in path) and all(
        frozenset((a, b)) in edges for a, b in pairwise(path)
    )


def advance_purposeful_society(
    state: dict[str, Any],
    seed: str,
    inputs: list[dict[str, Any]],
    *,
    goal_policy: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...]]:
    """Consume current input and every queued successor, then take exactly one explicit tick."""
    _require(state["profile"] == PURPOSEFUL_PROFILE, "unsupported purposeful profile")
    _require(state["seed_sha256"] == seed, "society seed lineage mismatch")
    _require(bool(inputs), "historical current input is required")
    validate_society_input(inputs[0])
    _require(
        inputs[0]["input_seq"] == state["input_seq"]
        and inputs[0]["document_sha256"] == state["input_sha256"]
        and inputs[0]["version_id"] == state["branch_id"],
        "current input binding mismatch",
    )
    for prior, current in pairwise(inputs):
        validate_input_successor(prior, current)
    # The budget is the one the state recorded at creation, so a society walks at the speed it
    # was created with however the module constant for new societies moves.
    budget_per_tick = state["movement_budget_mm_per_tick"]
    _require(_integer(budget_per_tick, 1, 10**9), "invalid movement budget")
    result = deepcopy(state)
    tick = state["tick"] + 1
    result["tick"] = tick
    events: list[SocietyEvent] = []
    previous_digest = society_state_sha256(state)

    def emit(person: dict, kind: str, reason: str, outcome: str, doc: dict) -> None:
        order = len(events)
        summary = (
            f"{person['display_name']} (simulated): {outcome.replace('_', ' ')}; "
            f"{reason.replace('_', ' ')}."
        )
        document = {
            "summary": summary,
            "synthetic": True,
            "profile": PURPOSEFUL_PROFILE,
            "branch_id": result["branch_id"],
            "subject_id": person["id"],
            "tick": tick,
            "order": order,
            "input_seq": doc["input_seq"],
            "input_sha256": doc["document_sha256"],
            "target": deepcopy(person["target"]),
            "reason": reason,
            "outcome": outcome,
            "goal": deepcopy(person["goal"]),
            "action": deepcopy(person["action"]),
            "position_mm": list(person["position_mm"]),
            "motion_path_mm": deepcopy(person["motion_path_mm"]),
            "previous_state_sha256": previous_digest,
            "seed_sha256": seed,
        }
        identity = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{state['society_id']}:{tick}:{order}:{society_state_sha256(document)}",
        )
        event = SocietyEvent(identity, tick, kind, uuid.UUID(person["id"]), None, document)
        events.append(event)
        person["memory"] = [*person["memory"], str(identity)][-16:]
        person["explanation"] = {"summary": summary, "event_ids": [str(identity)]}

    def block(person: dict, reason: str, doc: dict) -> None:
        person["action"] = {
            "kind": "idle",
            "status": "blocked",
            "target_id": person["goal"]["target_id"] if person["goal"] else None,
            "remaining_ticks": 0,
            "reason": reason,
        }
        # An unchanged failure does not flood the event log on every tick.
        key = [reason, person["action"]["target_id"]]
        if person["blocked_key"] != key:
            emit(person, "blocked", reason, "unable_to_act", doc)
        person["blocked_key"] = key

    for person in result["inhabitants"]:
        person["motion_path_mm"] = [list(person["position_mm"])]
    # Validate every accepted edit, including a move followed by undo before any time passes.
    for prior, doc in pairwise(inputs):
        graph = _graph(doc)
        nodes, _, edges = graph
        targets = {t["target_id"]: t for t in doc["targets"]}
        local_failures = {
            t["target_id"]: t["reason"] for t in doc.get("unavailable_affordances", [])
        }
        available = (
            doc["availability"] == "available" and not doc["navigation"]["unavailable_reason"]
        )
        # Over an input that states places, nobody is left standing where an edit took the
        # ground away: whoever it no longer supports steps aside to open ground, and somebody
        # part way through an activity at a place the edit left where it was keeps going.
        places_here = doc["profile"] in PLACE_INPUTS and available
        places: frozenset[str] = frozenset()
        crowded: frozenset[str] = frozenset()
        was_place: frozenset[str] = frozenset()
        if places_here:
            places = frozenset(n for t in doc["targets"] for n in t["place_node_ids"])
            crowded = standing_exclusions(doc)
            was_place = frozenset(n for t in prior["targets"] for n in t.get("place_node_ids", ()))
        for person in result["inhabitants"]:
            reason = None
            if not available:
                reason = doc["unavailable_reason"] or doc["navigation"]["unavailable_reason"]
            elif not _location_valid(person, nodes, edges):
                reason = "current_position_invalidated"
                if places_here:
                    loc = person["location"]
                    stood = (
                        {loc["node_id"]}
                        if loc["edge"] is None
                        else {loc["edge"]["from_node_id"], loc["edge"]["to_node_id"]}
                    )
                    aside = _step_aside(person, result["inhabitants"], graph, places, crowded)
                    if aside is not None:
                        why = "place_moved" if stood & was_place else "standing_node_removed"
                        person["position_mm"] = list(nodes[aside]["position_mm"])
                        if person["position_mm"] != person["motion_path_mm"][-1]:
                            person["motion_path_mm"].append(list(person["position_mm"]))
                        person["location"] = {"node_id": aside, "edge": None}
                        person["action"] = {
                            "kind": "idle",
                            "status": "blocked",
                            "target_id": person["target"]["target_id"]
                            if person["target"]
                            else None,
                            "remaining_ticks": 0,
                            "reason": why,
                        }
                        emit(person, "replanned", why, "stepped_aside", doc)
                        person["goal"] = None
                        person["target"] = None
                        person["route"] = None
                        continue
            elif places_here and (kept := _performing_at(person, targets)) is not None:
                person["target"] = deepcopy(kept)
                person["route_geometry_sha256"] = society_state_sha256(doc["navigation"])
                person["route"]["input_sha256"] = doc["document_sha256"]
                continue
            elif person["target"] is not None:
                target = targets.get(person["target"]["target_id"])
                if target is None or not target["enabled"]:
                    reason = local_failures.get(
                        person["target"]["target_id"], "target_disabled_or_removed"
                    )
                elif target != person["target"]:
                    reason = "target_changed"
                elif not _route_valid(person, nodes, edges) or person[
                    "route_geometry_sha256"
                ] != society_state_sha256(doc["navigation"]):
                    reason = "route_invalidated"
            elif person["goal"] is not None and (
                not _route_valid(person, nodes, edges)
                or person["route_geometry_sha256"] != society_state_sha256(doc["navigation"])
            ):
                # Only a walk to make room has a goal and no target, and only a place-stating
                # input starts one: it holds to a changed graph no more than a goal does.
                reason = "route_invalidated"
            if reason:
                person["action"] = {
                    "kind": "idle",
                    "status": "blocked",
                    "target_id": person["target"]["target_id"] if person["target"] else None,
                    "remaining_ticks": 0,
                    "reason": reason,
                }
                emit(person, "replanned", reason, "plan_invalidated", doc)
                person["goal"] = None
                person["target"] = None
                person["route"] = None
            elif person["route"]:
                person["route"]["input_sha256"] = doc["document_sha256"]
    doc = inputs[-1]
    nodes, adjacent, edges = _graph(doc)
    targets = [t for t in doc["targets"] if t["enabled"]]
    paths_cache = {}
    # An input that states where each activity's occupants stand keeps every place to one person
    # and keeps people who are waiting clear of every place.
    places_mode = doc["profile"] in PLACE_INPUTS
    place_target: dict[str, str] = {}
    crowded: frozenset[str] = frozenset()
    if places_mode:
        place_target = {node: t["target_id"] for t in targets for node in t["place_node_ids"]}
        crowded = standing_exclusions(doc)
    for person in result["inhabitants"]:
        person["need_milli"] = min(1000, person["need_milli"] + 1)
        unavailable = doc["unavailable_reason"] or doc["navigation"]["unavailable_reason"]
        if doc["availability"] != "available" or unavailable:
            block(person, unavailable or "input_unavailable", doc)
            continue
        if not _location_valid(person, nodes, edges):
            block(person, "current_position_invalidated", doc)
            continue
        policy = (goal_policy or {}).get(person["id"])
        if person["action"]["status"] == "completed" or (
            policy
            and person["action"]["status"] == "blocked"
            and (policy.get("preferred_target_id") or policy.get("wait"))
        ):
            person["goal"] = None
            person["target"] = None
            person["route"] = None
        if person["goal"] is None:
            if policy and policy.get("wait"):
                block(person, "validated_model_wait", doc)
                continue
            loc = person["location"]
            start = loc["node_id"] if loc["edge"] is None else loc["edge"]["to_node_id"]
            if start not in paths_cache:
                paths_cache[start] = _paths(start, adjacent)
            paths = paths_cache[start]
            candidates = [t for t in targets if t["node_id"] in paths]
            if policy is not None:
                candidates = [
                    t for t in candidates if t["target_id"] in policy["allowed_target_ids"]
                ]
            reachable = candidates
            held: set[str] = set()
            standing_at = None
            asked = policy.get("preferred_target_id") if policy else None
            if places_mode:
                # A person never takes up again, unasked, the activity whose place it is standing
                # at, so somebody waiting gets a turn; an activity needs a place nobody else holds.
                held = held_nodes(result["inhabitants"], person, graph=(nodes, edges)) | {
                    other["place_node_id"]
                    for subject, other in (goal_policy or {}).items()
                    if subject != person["id"] and "place_node_id" in other
                }
                standing_at = place_target.get(loc["node_id"]) if loc["edge"] is None else None
                candidates = [
                    t
                    for t in reachable
                    if (t["target_id"] != standing_at or t["target_id"] == asked)
                    and _place_for(t, policy, paths, held, loc["node_id"]) is not None
                ]
            target = None
            if candidates:
                preferred = "rest" if person["need_milli"] >= NEED_PREFERS_REST_MILLI else "visit"
                target = min(
                    candidates,
                    key=lambda t: (
                        bool(policy and policy.get("preferred_target_id"))
                        and t["target_id"] != policy["preferred_target_id"],
                        t["affordance"] != preferred,
                        t["target_id"] == person["last_completed_target_id"],
                        paths[t["node_id"]][0],
                        t["target_id"],
                    ),
                )
                destination = (
                    _place_for(target, policy, paths, held, loc["node_id"])
                    if places_mode
                    else target["node_id"]
                )
                goal = {
                    "kind": target["affordance"],
                    "target_id": target["target_id"],
                    "reason": "remembered_target_selected"
                    if policy and target["target_id"] == policy.get("preferred_target_id")
                    else "restore_need"
                    if target["affordance"] == "rest"
                    else "visit_place",
                }
            elif standing_at is not None:
                # Somebody who has finished at a place and has nothing else to do steps away to
                # the nearest node where nobody stands, is headed or would be in the way.
                waiting = min(
                    (
                        (paths[node][0], node)
                        for node in paths
                        if node not in crowded and node not in held
                    ),
                    default=None,
                )
                if waiting is None:
                    block(person, "no_room_to_wait", doc)
                    continue
                destination = waiting[1]
                goal = {"kind": "make_room", "target_id": None, "reason": "making_room"}
            else:
                reason = "no_reachable_affordance" if targets else "no_enabled_affordance"
                if policy is not None and targets:
                    reason = "no_known_reachable_affordance"
                if places_mode and reachable:
                    reason = "no_room_at_destination"
                block(person, reason, doc)
                continue
            path = list(paths[destination][1])
            progress = 0
            if loc["edge"]:
                path.insert(0, loc["edge"]["from_node_id"])
                progress = loc["edge"]["progress_mm"]
            person["route_geometry_sha256"] = society_state_sha256(doc["navigation"])
            person["goal"] = goal
            person["target"] = deepcopy(target)
            person["route"] = {
                "node_ids": path,
                "edge_index": 0,
                "edge_progress_mm": progress,
                "destination_node_id": destination,
                "input_sha256": doc["document_sha256"],
            }
            person["action"] = {
                "kind": "move",
                "status": "active",
                "target_id": None if target is None else target["target_id"],
                "remaining_ticks": 0,
                "reason": "following_reachable_route" if target is not None else "making_room",
            }
            person["blocked_key"] = None
            emit(person, "goal_selected", person["goal"]["reason"], "goal_selected", doc)
        target = person["target"]
        if person["action"]["kind"] in DURATIONS and person["action"]["status"] == "active":
            # These are subsequent ticks; arrival never spends the first action tick.
            standing_node = (
                person["route"]["destination_node_id"] if places_mode else target["node_id"]
            )
            if person["location"]["node_id"] != standing_node:
                block(person, "action_precondition_failed", doc)
                continue
            person["action"]["remaining_ticks"] -= 1
            if person["action"]["remaining_ticks"] == 0:
                person["action"]["status"] = "completed"
                person["action"]["reason"] = "reviewed_duration_elapsed"
                person["last_completed_target_id"] = target["target_id"]
                person["need_milli"] = max(
                    0, person["need_milli"] - RELIEF_MILLI[target["affordance"]]
                )
                emit(
                    person,
                    "action_completed",
                    "reviewed_duration_elapsed",
                    target["affordance"] + "_completed",
                    doc,
                )
            continue
        route = person["route"]
        budget = budget_per_tick
        while route["edge_index"] < len(route["node_ids"]) - 1 and budget > 0:
            index = route["edge_index"]
            a, b = route["node_ids"][index : index + 2]
            edge = edges[frozenset((a, b))]
            progress = route["edge_progress_mm"]
            step = min(budget, edge["length_mm"] - progress)
            progress += step
            budget -= step
            start, end = nodes[a]["position_mm"], nodes[b]["position_mm"]
            point = [
                x + (y - x) * progress // edge["length_mm"] for x, y in zip(start, end, strict=True)
            ]
            person["position_mm"] = point
            if point != person["motion_path_mm"][-1]:
                person["motion_path_mm"].append(point)
            if progress == edge["length_mm"]:
                route["edge_index"] += 1
                route["edge_progress_mm"] = 0
                person["location"] = {"node_id": b, "edge": None}
            else:
                route["edge_progress_mm"] = progress
                person["location"] = {
                    "node_id": None,
                    "edge": {
                        "edge_id": edge["edge_id"],
                        "from_node_id": a,
                        "to_node_id": b,
                        "from_position_mm": list(start),
                        "to_position_mm": list(end),
                        "length_mm": edge["length_mm"],
                        "progress_mm": progress,
                    },
                }
        if route["edge_index"] == len(route["node_ids"]) - 1 and target is None:
            person["action"] = {
                "kind": "idle",
                "status": "completed",
                "target_id": None,
                "remaining_ticks": 0,
                "reason": "made_room",
            }
            emit(person, "route_progressed", "made_room", "waiting", doc)
        elif route["edge_index"] == len(route["node_ids"]) - 1:
            person["action"] = {
                "kind": target["affordance"],
                "status": "active",
                "target_id": target["target_id"],
                "remaining_ticks": target["duration_ticks"],
                "reason": "arrived_at_access_node",
            }
            emit(person, "route_progressed", "arrived_at_access_node", "action_started", doc)
        elif len(person["motion_path_mm"]) > 1:
            emit(person, "route_progressed", "following_reachable_route", "moved", doc)
    result["input_seq"] = doc["input_seq"]
    result["input_sha256"] = doc["document_sha256"]
    return result, tuple(events)


def ordered_events_document(events: tuple[SocietyEvent, ...]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": str(e.event_id),
            "tick": e.tick,
            "event_kind": e.kind,
            "subject_id": str(e.subject_id),
            "object_id": None if e.object_id is None else str(e.object_id),
            "document": e.document,
            "document_sha256": society_state_sha256(e.document),
        }
        for e in events
    ]
