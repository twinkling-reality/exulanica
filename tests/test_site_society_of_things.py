"""A world made from a world kind as a society of things, without a database.

What a site hands a society of things, and where its people start: the site's blocked ground as the
kind worker hands it over with the place; the things input composed over a site's own surfaces
with the people its place houses; and genesis, which starts people where there is something to
visit and, where a site offers nothing to visit at all, where their own premises are.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.environment.district_geometry import segment_blocked
from exulanica.grammar.grammars.site.records import SiteAreaRecord, SiteStructureRecord
from exulanica.world.composers import composer_module
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.worker import _placed, compose_job
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_planner import (
    SocietyStartRefused,
    input_sha256,
    spawn_nodes,
    validate_society_input,
)
from exulanica.world.society_site_place import site_blocked_boxes, site_obstructions
from exulanica.world.society_things import initial_things_society
from exulanica.world.society_walking_surfaces import build_walking_surfaces_input
from exulanica.world.town_people import people_frame

from living_town_support import version_of

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
SITE = composer_module("site-plan", 1)
SEED = "5" * 64
NAMES = ("farm", "cafe", "site")


def _kind(name: str):
    return read_kind(json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8")))


def _composed(name: str):
    kind = _kind(name)
    world_id = f"world:generated:site-of-things-{name}"
    return world_id, SITE.compose_kind(kind, kind.values(kind.presets[0][0]), world_id)


def _things_input(name: str, input_seq: int = 1) -> tuple[dict[str, Any], dict[str, Any]]:
    """An input of a society of things over a fixture's site, nothing placed, with the people
    its place houses (the first records them; a later one is given them for its population
    alone), and the place it was composed over."""
    world_id, composed = _composed(name)
    receipt = json.loads(json.dumps(composed.receipt))
    routine = SITE.receipt_routine(receipt)
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
    answer = _placed(ground.place_id, receipt, composed.records)
    place = answer["place"]
    policy = routine.policy
    document = build_walking_surfaces_input(
        ground=ground,
        version=version_of(world_id, snapshot_id),
        place=place,
        input_seq=input_seq,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        things=True,
        segment_blocked=segment_blocked,
        obstructions=site_obstructions(answer["blocked"]),
        people=people_frame(place, routine),
    )
    return document, place


def _resealed(document: dict[str, Any]) -> dict[str, Any]:
    sealed = {k: v for k, v in document.items() if k != "document_sha256"}
    sealed["document_sha256"] = input_sha256(sealed)
    validate_society_input(sealed)
    return sealed


@pytest.mark.parametrize("name", NAMES)
def test_the_worker_hands_a_site_s_blocked_ground_over_with_its_place(name: str):
    """The blocked boxes are the list the place's own walking graph was laid clear of, so by the
    tests made from them every place of the graph can be stood at, every way of it is clear, and
    the middle of every structure and every area cannot be stood at."""
    _world_id, composed = _composed(name)
    receipt = json.loads(json.dumps(composed.receipt))
    answer = _placed("place:test", receipt, composed.records)
    assert answer["status"] == "done"
    boxes = answer["blocked"]
    assert boxes == site_blocked_boxes(composed.records)
    assert boxes and all(len(box) == 4 and box[0] < box[2] and box[1] < box[3] for box in boxes)
    assert json.loads(json.dumps(boxes)) == boxes
    town = site_obstructions(boxes)
    place = answer["place"]
    at = {node["node_id"]: tuple(node["position_mm"]) for node in place["nodes"]}
    assert all(town.stands(point) for point in at.values())
    assert all(town.steps(at[e["from_node_id"]], at[e["to_node_id"]]) for e in place["edges"])
    built = [r for r in composed.records if isinstance(r, SiteStructureRecord | SiteAreaRecord)]
    assert built or name == "cafe"
    for record in built:
        centre = (
            (record.min_x_mm + record.max_x_mm) // 2,
            (record.min_y_mm + record.max_y_mm) // 2,
        )
        assert not town.stands(centre), record.identity
        # A step straight through it is no step.
        west = (record.min_x_mm - 5_000, centre[1])
        east = (record.max_x_mm + 5_000, centre[1])
        assert not town.steps(west, east), record.identity


def test_the_job_that_makes_a_world_keeps_the_blocked_ground_beside_the_place_it_keeps():
    kind = _kind("farm")
    made = compose_job(
        "workspace",
        dict(kind.document),
        dict(kind.values(kind.presets[0][0])),
        "world:generated:site-of-things-kept",
    )
    assert made["status"] == "done"
    kept = made["placed"]
    assert kept["status"] == "done" and kept["place"]["place_id"] == made["place_id"]
    assert kept["blocked"] == site_blocked_boxes(tuple(made["composed"].records))


@pytest.mark.parametrize("name", NAMES)
def test_a_site_s_things_input_is_its_own_surfaces_and_its_own_people(name: str):
    document, place = _things_input(name)
    assert document["profile"] == "exulanica.society-input/walking-surfaces-v3"
    assert document["navigation"]["profile"] == "site-walking-surfaces/v1"
    frame = document["people"]
    homes = sum(d["resident_capacity"] for d in place["destinations"] if d["enabled"])
    assert frame["population"] == document["population"]["size"] == homes > 0
    assert frame["place"]["document_sha256"] == place["document_sha256"]
    # Every premises of the frame has a door on the walking graph the input states.
    nodes = {node["node_id"] for node in document["navigation"]["nodes"]}
    assert {row["node_id"] for row in frame["premises"]} <= nodes
    state = initial_things_society(
        uuid.uuid5(uuid.NAMESPACE_URL, name), SEED, document, population=homes
    )
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    assert len(villagers) == homes and all("resident" in p for p in villagers)


def test_people_start_where_their_premises_are_on_a_site_with_nothing_to_visit():
    """A site that offers nothing to visit or rest at still has the people who live there: they
    start in the parts of the walking graph their own premises' doors are in. With no people
    stated either, there is nowhere to start anybody and the society is refused by name."""
    document, _place = _things_input("farm")
    assert document["targets"], "the fixture farm offers somewhere to go"
    bare = _resealed({**document, "targets": []})
    doors = {row["node_id"] for row in bare["people"]["premises"]}
    adjacent: dict[str, set[str]] = {}
    for edge in bare["navigation"]["edges"]:
        adjacent.setdefault(edge["from_node_id"], set()).add(edge["to_node_id"])
        adjacent.setdefault(edge["to_node_id"], set()).add(edge["from_node_id"])
    reached, frontier = set(doors), list(doors)
    while frontier:
        for neighbour in adjacent.get(frontier.pop(), ()):
            if neighbour not in reached:
                reached.add(neighbour)
                frontier.append(neighbour)
    starts = spawn_nodes(bare)
    assert starts and set(starts) <= reached
    people = bare["population"]["size"]
    state = initial_things_society(
        uuid.uuid5(uuid.NAMESPACE_URL, "bare"), SEED, bare, population=people
    )
    assert len(state["inhabitants"]) == people
    assert {p["location"]["node_id"] for p in state["inhabitants"]} <= set(starts)
    nobody = _resealed({k: v for k, v in bare.items() if k != "people"})
    with pytest.raises(SocietyStartRefused) as refused:
        spawn_nodes(nobody)
    assert refused.value.code == "no_reachable_targets"


@pytest.mark.parametrize("name", NAMES)
def test_a_site_with_somewhere_to_go_starts_its_people_where_it_always_would(name: str):
    """An input that offers a target is read as it always was: who lives there changes nothing
    about where anybody starts, so no society that exists starts anywhere else."""
    document, _place = _things_input(name)
    assert document["targets"]
    without = _resealed({k: v for k, v in document.items() if k != "people"})
    assert spawn_nodes(document) == spawn_nodes(without)
    targets = {t["node_id"] for t in document["targets"] if t["enabled"]}
    doors = {row["node_id"] for row in document["people"]["premises"]}
    assert doors - targets, "the frame names doors that are no target, and they start nobody"


def test_a_door_cut_off_from_everything_to_visit_starts_nobody_while_there_is_a_target():
    """The old rule, held where it could differ: with a target on the graph, a part of the graph
    that holds a premises' door and no target starts nobody, people stated or not."""
    document, _place = _things_input("site")
    targets = {t["node_id"] for t in document["targets"] if t["enabled"]}
    edges = document["navigation"]["edges"]
    adjacent: dict[str, set[str]] = {}
    for edge in edges:
        adjacent.setdefault(edge["from_node_id"], set()).add(edge["to_node_id"])
        adjacent.setdefault(edge["to_node_id"], set()).add(edge["from_node_id"])
    # A door that is no target, with a neighbour that is neither: cut the pair off from the rest.
    door, beside = next(
        (row["node_id"], neighbour)
        for row in document["people"]["premises"]
        if row["node_id"] not in targets
        for neighbour in sorted(adjacent[row["node_id"]])
        if neighbour not in targets
    )
    island = {door, beside}
    kept = [
        edge
        for edge in edges
        if ({edge["from_node_id"], edge["to_node_id"]} <= island)
        or not ({edge["from_node_id"], edge["to_node_id"]} & island)
    ]
    assert len(kept) < len(edges)
    cut = _resealed({**document, "navigation": {**document["navigation"], "edges": kept}})
    starts = set(spawn_nodes(cut))
    assert starts and not starts & island
    # With no target left, the island is somewhere its people are.
    bare = _resealed({**cut, "targets": []})
    assert set(spawn_nodes(bare)) & island
