"""A society of things over a generated town (walking-surfaces-v3): the town's own surfaces,
premises and furniture, with the things placed in its region on them. A thing that blocks walking
removes the surface it stands on, a premises or a seat it covers is no longer stood at, a thing
offering a rest or a visit offers it joined to the street, and the town's v1 and v2 inputs do not
change. Composed without a database, as tests/living_town_support.py composes a town."""

from __future__ import annotations

import dataclasses
import functools
import json
import math
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.abilities.registry import current_modules
from exulanica.environment.district_geometry import segment_blocked
from exulanica.grammar.geometry import OUTSIDE, point_in_ring
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.world.authored_delta import version_delta_sha256
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, named_kind, shipped_kind
from exulanica.world.scenes import SceneArrival
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_catalogs import purposeful_routine
from exulanica.world.society_city_place import city_obstructions
from exulanica.world.society_input_policy import (
    OFF_GROUND,
    THING_INPUTS,
    UNREACHABLE,
    WALKING_SURFACES_BY_FAMILY,
    WALKING_SURFACES_COMPOSITION_V3,
    WALKING_SURFACES_INPUT_V3,
)
from exulanica.world.society_living import current_routine
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    advance_purposeful_society,
    validate_input_successor,
)
from exulanica.world.society_things import advance_things, initial_things_society
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.world_recipes import town_recipe

import things_society_support as things_support
from living_town_support import town_input, version_of

#: The digests of the town's v1 and v2 inputs, read from a clean checkout of 1c16ea69, a tree
#: with no walking-surfaces-v3 composition, so they come from code without it: the things
#: composition must leave them as they are. A change to a town recipe moves them; read them again
#: from a checkout of that change's base.
UNCHANGED = {
    ("small_town", False): "1caba10f8ec01eec308734224c938332795459d0eb5b001a354f0b35572ebce3",
    ("small_town", True): "3dc7cbea1ef45d17d5962554104ffd11754555c349f4624f6603fbc6627367b8",
    ("market_town", False): "a5b869e3ebdd04ade21255e9405996b50f76b7a43f3c0b247e6ff00e912985ce",
    ("market_town", True): "c92070858437a293da44c824da6742c92579a334d3380480fa7fdaa44a2c8153",
}
SCENES = Path(__file__).resolve().parents[1] / "assets" / "catalogs" / "scenes"
SEED = "9" * 64
SOCIETY = uuid.uuid5(uuid.NAMESPACE_URL, "walking-surfaces-v3-society")


WORLD_ID = "world:generated:walking-surfaces-v3"


@functools.cache
def _composed() -> Any:
    return compose_generated_world(town_recipe("small_town"), WORLD_ID)


@functools.cache
def _town() -> tuple[Any, Any, Any, StandingPolicy]:
    world_id = WORLD_ID
    composed = _composed()
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = current_routine()
    policy = routine.policy
    standing = StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"])
    place = walking_surfaces_place(ground.place_id, composed.records, routine)
    return ground, place, version_of(world_id, snapshot_id), standing


def _thing(
    placed_id: str,
    kind: str,
    version: int,
    at: list[int],
    *,
    y_mm: int = 0,
    yaw: int = 0,
    removed=False,
) -> PlacedThing:
    ground = _town()[0]
    return PlacedThing(
        placed_id,
        named_kind(kind, version),
        ground.region_id,
        Transform(at[0], y_mm, at[1], yaw, 1000),
        ObjectOrigin("authored", "fictional"),
        removed,
    )


def _compose(
    *things: PlacedThing, as_things: bool = True, input_seq: int = 1, living: bool = False
) -> dict[str, Any]:
    ground, place, base, standing = _town()
    version = dataclasses.replace(base, things=tuple(things))
    version = dataclasses.replace(version, state_sha256=version_delta_sha256(version))
    return build_walking_surfaces_input(
        ground=ground,
        version=version,
        place=place,
        input_seq=input_seq,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=standing,
        things=as_things,
        segment_blocked=segment_blocked if as_things else None,
        obstructions=_obstructions() if as_things else None,
        living=current_routine() if living else None,
    )


@functools.cache
def _obstructions() -> Any:
    return city_obstructions(_composed().records)


@functools.cache
def _bare() -> dict[str, Any]:
    return _compose(as_things=False)


def _node(predicate) -> dict[str, Any]:
    return next(node for node in _bare()["navigation"]["nodes"] if predicate(node))


def _box(kind: str, version: int) -> tuple[int, int]:
    box = shipped_kind(named_kind(kind, version)).semantics()["body"]["box_mm"]
    return -(-box["width"] // 2), -(-box["depth"] // 2)


def _near_box(point: list[int], centre: list[int], half: tuple[int, int]) -> int:
    """The squared distance from ``point`` to an unturned box: worked out here, apart from the
    composer's geometry."""
    dx = max(abs(point[0] - centre[0]) - half[0], 0)
    dz = max(abs(point[1] - centre[1]) - half[1], 0)
    return dx * dx + dz * dz


@pytest.mark.parametrize(("recipe", "living"), sorted(UNCHANGED))
def test_a_town_s_v1_and_v2_inputs_are_the_ones_main_composed(recipe: str, living: bool):
    assert town_input(recipe, living=living)["document_sha256"] == UNCHANGED[(recipe, living)]


def test_the_things_family_composes_v3_and_v3_carries_things():
    assert WALKING_SURFACES_BY_FAMILY["things"] == WALKING_SURFACES_COMPOSITION_V3
    assert WALKING_SURFACES_INPUT_V3 in THING_INPUTS
    document = _compose()
    assert document["profile"] == WALKING_SURFACES_INPUT_V3
    assert document["things"] == [] and document["population_kind"]["kind"] == "villager"
    assert document["population"] == _bare()["population"]
    # With nothing placed, the town's surfaces and activities are v1's.
    assert document["navigation"]["nodes"] == _bare()["navigation"]["nodes"]
    assert document["targets"] == _bare()["targets"]


def test_a_blocking_thing_removes_exactly_the_surface_within_its_clearance():
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    half = _box("well", 2)
    assert shipped_kind(named_kind("well", 2)).semantics()["body"]["blocks_walking"]
    document = _compose(_thing("well", "well", 2, street["position_mm"]))
    bare = _bare()["navigation"]
    kept = {node["node_id"] for node in document["navigation"]["nodes"]}
    reach = CLEARANCE_MM * CLEARANCE_MM
    expected_gone = {
        node["node_id"]
        for node in bare["nodes"]
        if _near_box(node["position_mm"], street["position_mm"], half) <= reach
    }
    # No node lies within a millimetre of the boundary either way, so the check is exact.
    for node in bare["nodes"]:
        gap = math.sqrt(_near_box(node["position_mm"], street["position_mm"], half))
        assert abs(gap - CLEARANCE_MM) > 1
    assert street["node_id"] in expected_gone
    gone = {node["node_id"] for node in bare["nodes"]} - kept
    assert gone == expected_gone
    # Each line the well cut ends exactly a walking clearance from its box, to the millimetre.
    cuts = [n for n in document["navigation"]["nodes"] if n["node_id"].startswith("cut:")]
    assert cuts
    for cut in cuts:
        gap = math.sqrt(_near_box(cut["position_mm"], street["position_mm"], half))
        assert CLEARANCE_MM <= gap < CLEARANCE_MM + 2, (cut["node_id"], gap)
    surviving_edges = {edge["edge_id"] for edge in document["navigation"]["edges"]}
    for edge in bare["edges"]:
        if edge["from_node_id"] in gone or edge["to_node_id"] in gone:
            assert edge["edge_id"] not in surviving_edges, edge["edge_id"]


def test_a_premises_a_thing_stands_on_is_recorded_unreachable_and_the_thing_offers_its_visit():
    target = next(t for t in _bare()["targets"] if t["origin"] == "premises")
    door = _node(lambda node: node["node_id"] == target["node_id"])
    document = _compose(_thing("well", "well", 2, door["position_mm"]))
    assert target["target_id"] not in {t["target_id"] for t in document["targets"]}
    record = next(
        r for r in document["unavailable_affordances"] if r["target_id"] == target["target_id"]
    )
    assert record["reason"] == UNREACHABLE
    offered = next(t for t in document["targets"] if t["origin"] == "thing")
    assert (offered["target_id"], offered["subject_id"]) == ("thing:well:visit", "thing:well")
    assert offered["activity"] == purposeful_routine().at_object("visit", "well").key
    nodes = {node["node_id"]: node for node in document["navigation"]["nodes"]}
    joined = {e["to_node_id"]: e for e in document["navigation"]["edges"]}
    for place in offered["place_node_ids"]:
        assert place.startswith("place:thing/well:") and place in nodes
        # Each place is joined to a surface node the town states.
        assert joined[place]["from_node_id"] in {
            n["node_id"] for n in _bare()["navigation"]["nodes"]
        }


def _support(node_id: str) -> int:
    """The height the town's place states a person stands at on a node."""
    return next(n["support_z_mm"] for n in _town()[1]["nodes"] if n["node_id"] == node_id)


def test_a_thing_off_the_ground_blocks_and_offers_nothing():
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    above = _support(street["node_id"]) + 600
    document = _compose(_thing("well", "well", 2, street["position_mm"], y_mm=above))
    assert street["node_id"] not in {node["node_id"] for node in document["navigation"]["nodes"]}
    assert not [t for t in document["targets"] if t["origin"] == "thing"]
    record = next(r for r in document["unavailable_affordances"] if r["subject_id"] == "thing:well")
    assert record["reason"] == OFF_GROUND
    assert document["things"][0]["height_mm"] == 600


def test_a_being_neither_blocks_nor_offers_and_lives_in_the_society():
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    document = _compose(_thing("knight", "knight", 1, street["position_mm"]))
    assert document["navigation"]["nodes"] == _bare()["navigation"]["nodes"]
    assert [t["placed_id"] for t in document["things"]] == ["knight"]
    state = initial_things_society(
        SOCIETY, SEED, document, population=document["population"]["size"]
    )
    knight = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    assert knight["placed_id"] == "knight"
    for _ in range(3):
        planned, events = advance_purposeful_society(state, SEED, [document])
        state, _events, _crossings = advance_things(state, planned, SEED, document, events)
    assert {p["came_by"] for p in state["inhabitants"]} == {"populated", "placed"}


def test_every_placed_thing_and_kind_is_bound_and_an_unknown_kind_makes_the_input_unavailable():
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    gone = _thing("old-well", "well", 2, [street["position_mm"][0] + 50_000, 0], removed=True)
    document = _compose(_thing("well", "well", 2, street["position_mm"]), gone)
    refs = {(r["kind"], r["identity"]) for r in document["dependency_refs"]}
    version = document["version_id"]
    assert ("placed_thing", f"{version}:well") in refs and (
        "placed_thing",
        f"{version}:old-well",
    ) in refs
    assert ("thing_kind", "well.v2") in refs
    unknown = dataclasses.replace(
        _thing("well", "well", 2, street["position_mm"]),
        kind=dataclasses.replace(named_kind("well", 2), sha256="0" * 64),
    )
    refused = _compose(unknown)
    assert refused["availability"] == "unavailable"
    assert refused["unavailable_reason"] == "unknown_thing_kind:well"
    assert refused["things"] == [] and refused["targets"] == []


def _reachable(document: dict[str, Any], start: str) -> set[str]:
    """Every node a person at ``start`` can walk to over the input's edges."""
    adjacent: dict[str, list[str]] = {}
    for edge in document["navigation"]["edges"]:
        adjacent.setdefault(edge["from_node_id"], []).append(edge["to_node_id"])
        adjacent.setdefault(edge["to_node_id"], []).append(edge["from_node_id"])
    seen, todo = {start}, [start]
    while todo:
        for nxt in adjacent.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def _scene_things(raised_mm: int = 0) -> list[PlacedThing]:
    """The things of the town scene three-strangers-in-town v1, placed from the town's arrival as
    the scene places them (exulanica/world/scenes.py), at the arrival's height."""
    arrival = _composed().receipt["arrival"]
    region = _town()[0].region_id
    at = SceneArrival(
        "generated",
        region,
        (arrival["position_mm"][0], arrival["support_z_mm"], -arrival["position_mm"][1]),
        (arrival["facing_mm"][0], -arrival["facing_mm"][1]),
    )
    scene = json.loads((SCENES / "three-strangers-in-town.v1.json").read_text())
    things = []
    for entry in scene["things"]:
        pose = at.pose(entry["place"])
        things.append(
            PlacedThing(
                entry["thing_id"],
                named_kind(entry["kind"]["kind"], entry["kind"]["version"]),
                region,
                dataclasses.replace(pose, y_mm=pose.y_mm + raised_mm),
                ObjectOrigin("authored", "fictional"),
                False,
            )
        )
    return things


def test_the_town_scene_s_things_rest_on_its_footway_and_its_well_is_visited():
    """The scene places every thing at the arrival's height, which is the footway's, not the
    ground plane's: each rests on the surface, states no height, and the well offers its visit
    at places a resident can walk to. Raised by 600 mm the same things stand off the surface."""
    arrival = _composed().receipt["arrival"]
    assert arrival["support_z_mm"] != _town()[0].elevation_mm
    document = _compose(*_scene_things())
    assert [t for t in document["things"] if "height_mm" in t] == []
    assert OFF_GROUND not in {r["reason"] for r in document["unavailable_affordances"]}
    [well] = [t for t in document["targets"] if t["target_id"] == "thing:well:visit"]
    door = next(t for t in document["targets"] if t["origin"] == "premises")
    for place in well["place_node_ids"]:
        assert place in _reachable(document, door["node_id"])
    raised = _compose(*_scene_things(raised_mm=600))
    assert {t["placed_id"]: t.get("height_mm") for t in raised["things"]}["well"] >= 600 - 200
    assert "thing:well:visit" not in {t["target_id"] for t in raised["targets"]}


def _east_west_stretch() -> tuple[dict[str, Any], dict[str, Any]]:
    """Two adjacent footway stations on one east-west line, at least four metres apart, each
    with another way on, so the stretch between them is no dead end."""
    nav = _bare()["navigation"]
    nodes = {node["node_id"]: node for node in nav["nodes"]}
    degree: dict[str, int] = {}
    for edge in nav["edges"]:
        for end in (edge["from_node_id"], edge["to_node_id"]):
            degree[end] = degree.get(end, 0) + 1
    for edge in sorted(nav["edges"], key=lambda e: e["edge_id"]):
        a, b = nodes[edge["from_node_id"]], nodes[edge["to_node_id"]]
        if (
            edge["subject_id"] == "footway"
            and degree[a["node_id"]] > 1
            and degree[b["node_id"]] > 1
            and a["node_id"].startswith("footway:")
            and b["node_id"].startswith("footway:")
            and a["position_mm"][1] == b["position_mm"][1]
            and abs(a["position_mm"][0] - b["position_mm"][0]) >= 4_000
        ):
            return a, b
    raise AssertionError("the town has no east-west footway stretch")


@pytest.mark.parametrize("yaw", (0, 1_570_796))
def test_a_well_between_two_stations_is_visited_at_every_place_it_offers(yaw):
    """A well midway between two footway stations, square to the line or turned along it: its
    places stand off the walking line or on it, beyond 1.5 m of every station, and each is still
    joined to the line and walked to. The line keeps the stretches the well does not stand in."""
    a, b = _east_west_stretch()
    middle = [(a["position_mm"][0] + b["position_mm"][0]) // 2, a["position_mm"][1]]
    height = _support(a["node_id"])
    document = _compose(_thing("well", "well", 2, middle, y_mm=height, yaw=yaw))
    [well] = [t for t in document["targets"] if t["target_id"] == "thing:well:visit"]
    assert len(well["place_node_ids"]) == 2
    nodes = {node["node_id"]: node for node in document["navigation"]["nodes"]}
    # Every place is walked to from the stations either side, whose own ways on stay.
    reached = _reachable(document, a["node_id"]) | _reachable(document, b["node_id"])
    assert len(reached) > 10
    for place in well["place_node_ids"]:
        # Square to the line, no station is within the reviewed reach of 1.5 m of a place: a
        # join to stations alone would miss both.
        assert yaw != 0 or all(
            _squared_to(nodes[place]["position_mm"], station["position_mm"]) > 1_500**2
            for station in (a, b)
        )
        assert place in reached
    cut = [n for n in nodes if n.startswith("cut:")]
    assert any(n.startswith((f"cut:{a['node_id']}>", f"cut:{b['node_id']}>")) for n in cut)
    # Every step the well's subject owns (to a place, or round a corner) keeps at least a standing
    # radius from the well's box: the gap is worked out here, exactly, apart from the composer.
    half = _box("well", 2) if yaw == 0 else _box("well", 2)[::-1]
    radius = _town()[3].radius_mm
    owned = [e for e in document["navigation"]["edges"] if e["subject_id"] == "thing:well"]
    assert owned
    for edge in owned:
        start = nodes[edge["from_node_id"]]["position_mm"]
        end = nodes[edge["to_node_id"]]["position_mm"]
        assert _segment_box_gap(start, end, middle, half) >= radius, edge["edge_id"]


def _segment_box_gap(a: list[int], b: list[int], centre: list[int], half: tuple[int, int]) -> float:
    """The least distance from segment ``a``-``b`` to an unturned box, by ternary search on the
    convex distance along the segment (exact to well under a millimetre)."""
    low, high = 0.0, 1.0
    for _ in range(200):
        one, two = low + (high - low) / 3, high - (high - low) / 3
        if _gap_at(a, b, one, centre, half) <= _gap_at(a, b, two, centre, half):
            high = two
        else:
            low = one
    return _gap_at(a, b, low, centre, half)


def _gap_at(a, b, t: float, centre, half) -> float:  # type: ignore[no-untyped-def]
    x = a[0] + (b[0] - a[0]) * t - centre[0]
    z = a[1] + (b[1] - a[1]) * t - centre[1]
    return math.hypot(max(abs(x) - half[0], 0), max(abs(z) - half[1], 0))


def _squared_to(p: list[int], q: list[int]) -> int:
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2


def test_a_town_s_first_v3_input_records_the_modules_and_a_later_one_none():
    assert _compose()["modules"] == list(current_modules())
    assert "modules" not in _compose(input_seq=2)


def test_a_visitor_crosses_in_through_a_gate_placed_on_a_town():
    """A gate placed on a town's footway admits a visitor at the open node nearest its arrival
    point: the v3 input carries the gate's arrival as its things list does, with no pinned
    arrival of its own."""
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    gate = _thing("gate", "gate", 1, street["position_mm"], y_mm=_support(street["node_id"]))
    document = _compose(gate)
    assert "arrival" not in document
    [entry] = document["things"]
    assert entry["arrival_mm"] is not None
    state = initial_things_society(
        SOCIETY, SEED, document, population=document["population"]["size"]
    )
    planned, events = advance_purposeful_society(state, SEED, [document])
    state, events, bound = advance_things(
        state, planned, SEED, document, events, crossings=[things_support.arrival(0)]
    )
    assert [(b.disposition, b.reason) for b in bound] == [("arrived", None)]
    [arrived] = [e for e in events if e.kind == "thing_arrived"]
    assert arrived.document["reason"] == "crossed_in"
    visitor = next(p for p in state["inhabitants"] if p["came_by"] == "crossed")
    nodes = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    # It steps out on the town's own surface, a few metres at most from the gate's arrival point.
    assert nodes[visitor["location"]["node_id"]] == visitor["position_mm"]
    assert _squared_to(visitor["position_mm"], entry["arrival_mm"]) <= 5_000**2


@pytest.mark.parametrize("living", (False, True))
def test_a_town_s_v1_and_v2_inputs_read_no_thing_placed_in_it(living):
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    well = _thing("well", "well", 2, street["position_mm"])
    document = _compose(well, as_things=False, living=living)
    bare = _compose(as_things=False, living=living)
    assert "things" not in document
    for field in ("targets", "unavailable_affordances", "navigation"):
        assert document[field] == bare[field]
    if living:
        assert document["living"] == bare["living"]


def test_a_removed_thing_gives_the_town_back_its_surfaces():
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    placed = _compose(_thing("well", "well", 2, street["position_mm"]))
    assert placed["navigation"]["nodes"] != _bare()["navigation"]["nodes"]
    removed = _compose(_thing("well", "well", 2, street["position_mm"], removed=True))
    assert removed["navigation"]["nodes"] == _bare()["navigation"]["nodes"]
    assert removed["navigation"]["edges"] == _bare()["navigation"]["edges"]
    assert removed["targets"] == _bare()["targets"] and removed["things"] == []


def test_a_society_of_things_reads_no_living_place_and_needs_a_blocking_test():
    ground, place, base, standing = _town()
    common = {
        "ground": ground,
        "version": base,
        "place": place,
        "input_seq": 1,
        "dependency_refs": [],
        "availability": "available",
        "unavailable_reason": None,
        "reviewed_affordances": {},
        "standing": standing,
        "things": True,
    }
    with pytest.raises(ValueError, match="blocking test"):
        build_walking_surfaces_input(**common, segment_blocked=None, obstructions=_obstructions())
    with pytest.raises(ValueError, match="obstructions"):
        build_walking_surfaces_input(**common, segment_blocked=segment_blocked, obstructions=None)
    with pytest.raises(ValueError, match="living place"):
        build_walking_surfaces_input(
            **common,
            segment_blocked=segment_blocked,
            obstructions=_obstructions(),
            living=current_routine(),
        )


def test_a_thing_s_place_keeps_a_standing_spacing_from_a_place_the_town_offers():
    """A well whose first place would stand just inside a standing spacing east of a bench's seat
    gives that place up, and the input holds (its validation refuses two places that close); the
    bench keeps its seats."""
    seat_target = next(t for t in _bare()["targets"] if t["origin"] == "furniture")
    seat = _node(lambda node: node["node_id"] == seat_target["place_node_ids"][0])
    standing = _town()[3]
    a, b = _east_west_stretch()
    far = [(a["position_mm"][0] + b["position_mm"][0]) // 2, a["position_mm"][1]]
    probe = _compose(_thing("well", "well", 2, far, y_mm=_support(a["node_id"])))
    nodes = {node["node_id"]: node["position_mm"] for node in probe["navigation"]["nodes"]}
    place = "place:thing/well:0"
    offset = [nodes[place][0] - far[0], nodes[place][1] - far[1]]
    near = standing.spacing_mm - 40
    at = [seat["position_mm"][0] + near - offset[0], seat["position_mm"][1] - offset[1]]
    document = _compose(_thing("well", "well", 2, at, y_mm=_support(a["node_id"])))
    assert seat_target["target_id"] in {t["target_id"] for t in document["targets"]}
    offered = [t for t in document["targets"] if t["origin"] == "thing"]
    assert all(place not in t["place_node_ids"] for t in offered)


def test_a_thing_s_places_stand_outside_the_town_s_buildings():
    """A well on a premises' door would have a place on each side of it, one inside the building:
    only the one in the street is kept, and its step to the footway passes through no wall. The
    buildings are read from the town's records here, apart from the composer."""
    rings = [r.tiers[0].ring_mm for r in _composed().records if isinstance(r, MassingRecord)]
    target = next(t for t in _bare()["targets"] if t["origin"] == "premises")
    door = _node(lambda node: node["node_id"] == target["node_id"])
    document = _compose(
        _thing("well", "well", 2, door["position_mm"], y_mm=_support(door["node_id"]))
    )
    nodes = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    [offered] = [t for t in document["targets"] if t["origin"] == "thing"]
    assert len(offered["place_node_ids"]) == 1
    for place in offered["place_node_ids"]:
        x, south = nodes[place]
        assert all(point_in_ring((x, -south), ring) == OUTSIDE for ring in rings)


def _hour(document: dict[str, Any], minutes: int) -> tuple[dict[str, Any], list[Any]]:
    state = initial_things_society(
        SOCIETY, SEED, document, population=document["population"]["size"]
    )
    every = []
    for _ in range(minutes):
        planned, events = advance_purposeful_society(state, SEED, [document])
        state, events, _crossings = advance_things(state, planned, SEED, document, events)
        every.extend(events)
    return state, every


def test_the_dressed_town_lives_an_hour_on_its_own_surfaces_and_the_same_hour_again():
    """The town scene's things on the small town, sixty minutes: everybody stands at a node or
    on an edge the input states, so nobody stands where a thing cut the walking line, the placed
    beings live among the residents, residents visit the well, and the same seed lives the same
    hour again, event for event."""
    document = _compose(*_scene_things())
    state, events = _hour(document, 60)
    nodes = {node["node_id"] for node in document["navigation"]["nodes"]}
    assert {p["came_by"] for p in state["inhabitants"]} == {"populated", "placed"}
    assert {p["placed_id"] for p in state["inhabitants"] if p["came_by"] == "placed"} == {
        "knight",
        "lantern-spirit",
    }
    edges = {edge["edge_id"] for edge in document["navigation"]["edges"]}
    for person in state["inhabitants"]:
        location = person["location"]
        # At a node, or part way along an edge the input states.
        assert location["node_id"] in nodes or location["edge"]["edge_id"] in edges
    # Residents go to the well and use it.
    at_the_well = {e.kind for e in events if "thing:well:visit" in json.dumps(e.document)}
    assert {"goal_selected", "action_completed"} <= at_the_well
    again, repeated = _hour(document, 60)
    assert again == state
    assert [(e.kind, e.document) for e in repeated] == [(e.kind, e.document) for e in events]


def test_a_place_falling_exactly_on_a_node_is_given_up_and_the_input_holds():
    """A well whose front place lands to the millimetre on a footway station would be joined by a
    step of no length, which the input's validation refuses: that place is given up instead."""
    a, _b = _east_west_stretch()
    # At turn 0 the well's front place stands 1,590 mm north of its centre (well.v2.json).
    at = [a["position_mm"][0], a["position_mm"][1] + 1_590]
    document = _compose(_thing("well", "well", 2, at, y_mm=_support(a["node_id"])))
    nodes = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    assert nodes[a["node_id"]] == a["position_mm"]
    offered = [t for t in document["targets"] if t["origin"] == "thing"]
    assert all("place:thing/well:0" not in t["place_node_ids"] for t in offered)


@pytest.mark.parametrize(("above", "rests"), ((200, True), (201, False)))
def test_a_thing_rests_within_200_mm_of_the_line_and_not_a_millimetre_more(above, rests):
    street = _node(lambda node: node["subject_id"].startswith("footway"))
    y_mm = _support(street["node_id"]) + above
    document = _compose(_thing("well", "well", 2, street["position_mm"], y_mm=y_mm))
    [entry] = document["things"]
    assert entry.get("height_mm") == (None if rests else above)
    off = [r for r in document["unavailable_affordances"] if r["reason"] == OFF_GROUND]
    assert bool(off) is not rests


def test_the_surface_between_two_ends_of_different_heights_is_read_between_them():
    """A thing at the middle of an edge whose two ends stand at different heights stands above the
    height halfway between them, not above either end's."""
    place = _town()[1]
    heights = {node["node_id"]: node["support_z_mm"] for node in place["nodes"]}
    plan = {node["node_id"]: node["position_mm"] for node in place["nodes"]}
    a, b = next(
        (edge["from_node_id"], edge["to_node_id"])
        for edge in sorted(place["edges"], key=lambda e: e["edge_id"])
        if (heights[edge["from_node_id"]] - heights[edge["to_node_id"]]) % 2 == 0
        and heights[edge["from_node_id"]] != heights[edge["to_node_id"]]
        and all(
            (plan[edge["from_node_id"]][i] - plan[edge["to_node_id"]][i]) % 2 == 0 for i in (0, 1)
        )
    )
    middle = [(plan[a][0] + plan[b][0]) // 2, -((plan[a][1] + plan[b][1]) // 2)]
    surface = (heights[a] + heights[b]) // 2
    document = _compose(_thing("knight", "knight", 1, middle, y_mm=surface + 300))
    [entry] = document["things"]
    assert entry["height_mm"] == 300
    assert surface + 300 - heights[a] != 300 and surface + 300 - heights[b] != 300


def test_a_door_whose_way_to_the_street_a_thing_cuts_is_recorded_unreachable():
    """A lamp post standing across the middle of a door's three-metre way to the footway leaves
    both ends but cuts the way from both: the door is no longer offered, and says why."""
    nav = _bare()["navigation"]
    position = {node["node_id"]: node["position_mm"] for node in nav["nodes"]}
    target, edge = next(
        (target, edge)
        for target in sorted(_bare()["targets"], key=lambda t: t["target_id"])
        if target["origin"] == "premises"
        for edge in nav["edges"]
        if target["node_id"] in (edge["from_node_id"], edge["to_node_id"])
        and edge["length_mm"] == 3_000
        and (
            position[edge["from_node_id"]][0] == position[edge["to_node_id"]][0]
            or position[edge["from_node_id"]][1] == position[edge["to_node_id"]][1]
        )
    )
    a, b = position[edge["from_node_id"]], position[edge["to_node_id"]]
    middle = [(a[0] + b[0]) // 2, (a[1] + b[1]) // 2]
    # The post's narrow side (250 mm) lies along the way: turned a quarter where the way runs
    # east-west.
    yaw = 0 if a[0] == b[0] else 1_570_796
    document = _compose(
        _thing("post", "lamp_post", 1, middle, y_mm=_support(edge["to_node_id"]), yaw=yaw)
    )
    kept = {node["node_id"] for node in document["navigation"]["nodes"]}
    assert {edge["from_node_id"], edge["to_node_id"]} <= kept
    assert target["target_id"] not in {t["target_id"] for t in document["targets"]}
    [record] = [
        r for r in document["unavailable_affordances"] if r["target_id"] == target["target_id"]
    ]
    assert record["reason"] == UNREACHABLE


def test_a_society_of_things_reads_only_things_inputs():
    with pytest.raises(ValueError, match="its own kind of input"):
        validate_input_successor(_bare(), _compose(input_seq=2))


def test_the_same_things_in_another_order_compose_the_same_input():
    things = _scene_things()
    assert _compose(*things)["document_sha256"] == _compose(*reversed(things))["document_sha256"]
