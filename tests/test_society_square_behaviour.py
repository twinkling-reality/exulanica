"""People in a small square stay a while, stand, and stop to talk in pairs, deterministically.

The square is laid out and composed in memory as the runtime composes it
(``tests/living_square_support.py``), under the newest routine, and advanced two simulated hours
over every seed the living-square record judges and every development seed. Whatever the seed,
talking is between two people who both mean it, nobody talks with themselves or with two people
at once, two people never stand on one spot, two people talk only across an edge of the ground, and
a talk ends for both at once. A stay already under way when an edit moves a society to the newest
routine finishes as it was recorded, relief included, and nobody's destination moves with it.
"""

from __future__ import annotations

import math
import random
from copy import deepcopy
from itertools import pairwise

import pytest
from exulanica.world.assets import reviewed_assets
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society_catalogs import purposeful_routine
from exulanica.world.society_planner import (
    _graph,
    _paths,
    _talk_pairs,
    advance_purposeful_society,
    initial_purposeful_society,
    input_graph,
    routine_of,
    standing_exclusions,
)
from exulanica.world.society_social import (
    OBSERVATION_DISTANCE_MM,
    advance_social_society,
    initial_social_society,
    validate_proposal,
)

import living_square_support as square

TICKS = 120
SEEDS = (*square.JUDGED_SEEDS, *square.DEVELOPMENT_SEEDS)
TALK = purposeful_routine().in_setting("pair")
STAND = purposeful_routine().in_setting("open")


@pytest.fixture(scope="module")
def runs() -> dict[str, list[dict]]:
    document = square.compose(square.square_objects())
    return {seed: square.run(seed, TICKS, document) for seed in SEEDS}


def test_the_seed_lists_are_disjoint_and_the_judged_are_the_pace_records():
    assert len(square.JUDGED_SEEDS) == len(square.DEVELOPMENT_SEEDS) == 12
    assert not set(square.JUDGED_SEEDS) & set(square.DEVELOPMENT_SEEDS)
    assert square.JUDGED_SEEDS[0] == "7a" * 32


def test_talking_is_mutual_one_to_one_and_ends_for_both_at_once(runs):
    talks = 0
    for seed, states in runs.items():
        for state in states[1:]:
            people = {person["id"]: person for person in state["inhabitants"]}
            partners = [
                person["goal"]["partner_id"]
                for person in people.values()
                if person["goal"] is not None and person["goal"]["kind"] == TALK.key
            ]
            assert len(partners) == len(set(partners)), f"{seed} minute {state['tick']}"
            for person in people.values():
                goal, action = person["goal"], person["action"]
                if goal is None or goal["kind"] != TALK.key:
                    continue
                partner = people[goal["partner_id"]]
                assert partner is not person
                if action["kind"] != TALK.key:
                    continue
                talks += 1
                assert partner["goal"]["partner_id"] == person["id"]
                if partner["action"]["kind"] != TALK.key:
                    # The first of two to arrive waits for the other, who is still walking over;
                    # the talk's clock has not started.
                    assert partner["action"]["kind"] == "move"
                    assert action["remaining_ticks"] == goal["duration_ticks"]
                    continue
                # Both are at it, pointed at each other, a talking distance apart.
                assert partner["action"]["status"] == action["status"]
                assert partner["action"]["remaining_ticks"] == action["remaining_ticks"]
                apart = math.dist(person["position_mm"], partner["position_mm"])
                assert 0 < apart <= TALK.spacing_mm, f"{seed} minute {state['tick']}: {apart}"
    # A positive control: the invariants above were asked of real talks, not of none.
    assert talks > 1000


def test_nobody_stands_where_somebody_else_stands(runs):
    for seed, states in runs.items():
        for state in states:
            standing = [
                person["location"]["node_id"]
                for person in state["inhabitants"]
                if person["location"]["edge"] is None
            ]
            assert len(standing) == len(set(standing)), f"{seed} minute {state['tick']}"


def test_every_stay_lasts_within_its_activitys_range(runs):
    routine = purposeful_routine()
    document = square.compose(square.square_objects())
    activity_of = {target["target_id"]: target["activity"] for target in document["targets"]}
    checked = 0
    for states in runs.values():
        for before, after in pairwise(states):
            earlier = {person["id"]: person for person in before["inhabitants"]}
            for person in after["inhabitants"]:
                action = person["action"]
                if action["reason"] not in ("arrived_at_access_node", "standing_a_while"):
                    continue
                prior = earlier[person["id"]]["action"]
                # A stay starts in the minute a person arrives: before it, they were doing
                # something else, somewhere else, or had just finished.
                if (
                    prior["kind"] == action["kind"]
                    and prior["target_id"] == action["target_id"]
                    and prior["status"] == "active"
                ):
                    continue
                entry = (
                    routine.activities[activity_of[action["target_id"]]]
                    if action["target_id"] is not None
                    else STAND
                )
                assert entry.duration_minimum <= action["remaining_ticks"] <= entry.duration_maximum
                checked += 1
    assert checked > 1000


def test_the_same_seed_gives_the_same_minutes():
    seed = square.DEVELOPMENT_SEEDS[0]
    first = [square.digest(state) for state in square.run(seed, 40)]
    assert first == [square.digest(state) for state in square.run(seed, 40)]


def test_people_choosing_in_the_same_minute_pair_the_same_way_in_any_order(runs):
    """The pairing reads everybody in ordinal order, whatever order it is handed them in."""
    document = square.compose(square.square_objects())
    nodes, adjacent, edges = _graph(document)
    crowded = standing_exclusions(document)
    routine = routine_of(document)
    cache: dict = {}

    def paths_of(start):
        if start not in cache:
            cache[start] = _paths(start, adjacent)
        return cache[start]

    seed = square.DEVELOPMENT_SEEDS[1]
    found = 0
    for state in runs[seed][1:40]:
        people = deepcopy(state["inhabitants"])
        tick = state["tick"] + 1
        pairs = _talk_pairs(
            people, routine, TALK, (nodes, adjacent, edges), crowded, {}, paths_of, seed, tick
        )
        shuffled = list(people)
        random.Random(tick).shuffle(shuffled)
        again = _talk_pairs(
            shuffled, routine, TALK, (nodes, adjacent, edges), crowded, {}, paths_of, seed, tick
        )
        assert again == pairs
        for person, pair in pairs.items():
            assert pairs[pair["partner_id"]]["partner_id"] == person
        found += len(pairs)
    assert found > 0


def _talking_pair(states):
    for index, state in enumerate(states):
        people = {person["id"]: person for person in state["inhabitants"]}
        for person in people.values():
            action = person["action"]
            if (
                action["kind"] == TALK.key
                and action["status"] == "active"
                and action["reason"] == "talking"
                and action["remaining_ticks"] >= 2
            ):
                return index, person, people[person["goal"]["partner_id"]]
    raise AssertionError("no pair talked long enough to be interrupted")


def test_when_an_edit_takes_one_talker_away_the_other_stops_in_the_same_minute(runs):
    seed = square.DEVELOPMENT_SEEDS[2]
    states = runs[seed]
    index, leaving, staying = _talking_pair(states)
    # A lamp post blocks walking and offers nothing, so it takes the ground from under one talker
    # and puts no place beside the other.
    post = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.lamp-post")
    x_mm, z_mm = leaving["position_mm"]
    blocking = AuthoredObject(
        object_id="object:in-the-way",
        asset_sha256=post.content_sha256,
        region_id="region:starter",
        transform=Transform(x_mm, 0, z_mm, 0, 1000),
        origin=ObjectOrigin("authored", "fictional"),
    )
    first = square.compose(square.square_objects())
    edited = square.compose((*square.square_objects(), blocking), input_seq=2)
    state, events = advance_purposeful_society(states[index], seed, [first, edited])
    people = {person["id"]: person for person in state["inhabitants"]}
    goal = people[leaving["id"]]["goal"]
    assert goal is None or goal["kind"] != TALK.key
    assert people[staying["id"]]["action"] == {
        **people[staying["id"]]["action"],
        "kind": TALK.key,
        "status": "completed",
        "reason": "partner_left",
    }
    assert any(
        event.kind == "action_completed"
        and str(event.subject_id) == staying["id"]
        and event.document["reason"] == "partner_left"
        for event in events
    )


def test_a_stay_under_way_when_a_society_moves_to_the_newest_routine_ends_as_recorded():
    """A person resting under the released rules finishes that rest as it was recorded, when the
    edit that moves the society to the newest profile changes the ground elsewhere."""
    objects = square.square_objects()
    released = square.compose(objects, v2=True)
    seed = square.DEVELOPMENT_SEEDS[3]
    population = len(square.run(seed, 0, released)[0]["inhabitants"])
    state = initial_purposeful_society(square.SOCIETY, seed, released, population=population)
    resting = None
    while resting is None:
        state, _ = advance_purposeful_society(state, seed, [released])
        resting = next(
            (
                person["id"]
                for person in state["inhabitants"]
                if person["action"]["kind"] == "rest"
                and person["action"]["status"] == "active"
                and person["action"]["remaining_ticks"] >= 2
            ),
            None,
        )
    # The edit puts a lamp post on open ground as far from the resting person as there is, so the
    # navigation changes and only the rule that a stay under way keeps going keeps them at it.
    nodes, _ = input_graph(released)
    here = next(p for p in state["inhabitants"] if p["id"] == resting)["position_mm"]
    taken = {p["location"]["node_id"] for p in state["inhabitants"]} | {
        p["route"]["destination_node_id"] for p in state["inhabitants"] if p["route"]
    }
    far = max(
        (node for node in nodes if node not in standing_exclusions(released) | taken),
        key=lambda node: (math.dist(nodes[node]["position_mm"], here), node),
    )
    post = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.lamp-post")
    x_mm, z_mm = nodes[far]["position_mm"]
    elsewhere = AuthoredObject(
        object_id="object:elsewhere",
        asset_sha256=post.content_sha256,
        region_id="region:starter",
        transform=Transform(x_mm, 0, z_mm, 0, 1000),
        origin=ObjectOrigin("authored", "fictional"),
    )
    newest = square.compose((*objects, elsewhere), input_seq=2)
    assert newest["navigation"] != released["navigation"]
    stayed, moved = state, state
    kept, recorded = [], []
    moved, _ = advance_purposeful_society(moved, seed, [released, newest])
    stayed, _ = advance_purposeful_society(stayed, seed, [released])
    assert moved["input_seq"] == 2
    for _ in range(4):

        def mine(held):
            person = next(p for p in held["inhabitants"] if p["id"] == resting)
            return person["action"], person["need_milli"], person["position_mm"]

        kept.append(mine(moved))
        recorded.append(mine(stayed))
        moved, _ = advance_purposeful_society(moved, seed, [newest])
        stayed, _ = advance_purposeful_society(stayed, seed, [released])
    # Minute by minute until it ends, the stay is the one the released rules recorded, including
    # when it completes and what completing it relieves.
    ended = next(i for i, (action, _, _) in enumerate(recorded) if action["status"] == "completed")
    assert kept[: ended + 1] == recorded[: ended + 1]
    assert kept[ended][0]["reason"] == "reviewed_duration_elapsed"


def _slow(state: dict, budget_mm: int = 500) -> dict:
    """A society recorded with a slow walking budget, so a walk takes several minutes.

    A society walks at the budget its own state records, so a state recorded at another budget is
    a society as the planner meets it: here people are part way somewhere at a minute's end.
    """
    slowed = deepcopy(state)
    slowed["movement_budget_mm_per_tick"] = budget_mm
    return slowed


def test_the_society_moving_to_the_newest_routine_moves_nobodys_destination():
    """Walking somewhere, or just finished there, when the input moves to the newest profile: the
    same place is the same place, so nobody replans, and a walk arrives at a stay drawn under the
    routine the newest input records."""
    objects = square.square_objects()
    released = square.compose(objects, v2=True)
    newest = square.compose(objects, input_seq=2)
    # A positive control: nothing about the ground changed, only how each stay is stated.
    assert released["navigation"] == newest["navigation"]
    seed = square.DEVELOPMENT_SEEDS[4]
    state = _slow(initial_purposeful_society(square.SOCIETY, seed, released, population=8))
    for _ in range(60):
        state, _ = advance_purposeful_society(state, seed, [released])
        walking = [p for p in state["inhabitants"] if p["action"]["kind"] == "move" and p["target"]]
        finished = [
            p for p in state["inhabitants"] if p["action"]["status"] == "completed" and p["target"]
        ]
        if walking and finished:
            break
    else:
        raise AssertionError("nobody was walking to a place while somebody had just finished")
    walker = walking[0]
    moved, events = advance_purposeful_society(state, seed, [released, newest])
    assert not [event for event in events if event.kind == "replanned"]
    people = {person["id"]: person for person in moved["inhabitants"]}
    held = people[walker["id"]]
    assert held["goal"] == walker["goal"]
    newest_targets = {target["target_id"]: target for target in newest["targets"]}
    # Held as the newest input states it, so arriving there starts a stay in its terms.
    assert held["target"] == newest_targets[walker["target"]["target_id"]]
    routine = routine_of(newest)
    while held["action"]["kind"] == "move":
        moved, _ = advance_purposeful_society(moved, seed, [newest])
        held = next(p for p in moved["inhabitants"] if p["id"] == walker["id"])
    stay = routine.activities[held["target"]["activity"]]
    assert held["action"]["kind"] == stay.affordance
    assert stay.duration_minimum <= held["action"]["remaining_ticks"] <= stay.duration_maximum
    assert held["action"]["relief_milli"] == stay.relief


def test_a_remembered_place_is_the_same_place_when_the_newest_input_restates_its_stay():
    """The social cast neither observes the move to the newest profile as a change, nor refuses a
    proposal to go to a place it remembers from before it."""
    objects = square.square_objects()
    released = square.compose(objects, v2=True)
    newest = square.compose(objects, input_seq=2)
    seed = square.DEVELOPMENT_SEEDS[8]
    state = initial_social_society(square.SOCIETY, seed, released, population=8)
    for _ in range(6):
        state, _, _ = advance_social_society(state, seed, [released])
    remembered = [
        belief
        for agent in state["social"]["agents"].values()
        for belief in agent["beliefs"].values()
    ]
    # A positive control: the cast remembers places, stated with a fixed duration.
    assert remembered and all("duration_ticks" in b["target"] for b in remembered)

    def observed(events) -> list[tuple[str, str]]:
        return sorted(
            (str(event.subject_id), event.document["observation"]["target"]["target_id"])
            for event in events
            if event.kind == "observed"
        )

    _, stayed, _ = advance_social_society(state, seed, [released])
    _, moved, _ = advance_social_society(state, seed, [released, newest])
    assert observed(moved) == observed(stayed)
    belief = remembered[0]
    nodes, _ = input_graph(newest)
    context = {
        "can_choose_goal": True,
        "own_beliefs": [belief],
        "position_mm": nodes[belief["target"]["node_id"]]["position_mm"],
    }
    proposal = {"kind": "choose_goal", "target_id": belief["target"]["target_id"]}
    assert validate_proposal(context, newest, proposal) is None


def _remembering(state: dict, agent: dict, targets: list[dict], document: dict) -> None:
    """Give one member of the social cast observations of ``targets`` from ``document``."""
    state["social"]["agents"][agent["id"]]["beliefs"] = {
        target["target_id"]: {
            "origin": "observation",
            "source_subject_id": agent["id"],
            "source_fact_id": f"fact:{target['target_id']}",
            "communication_id": None,
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "learned_tick": state["tick"],
            "target": deepcopy(target),
            "available": True,
        }
        for target in targets
    }


def _stand_at(person: dict, node: str, nodes: dict) -> None:
    point = list(nodes[node]["position_mm"])
    person.update(
        position_mm=point, motion_path_mm=[point], location={"node_id": node, "edge": None}
    )


def test_the_cast_may_still_choose_a_place_it_remembers_from_before_the_newest_input():
    """Somebody of the cast, too far from every place to see it again, knows the places only as the
    older input stated them. After the move to the newest profile they may still choose them."""
    objects = square.square_objects()
    released = square.compose(objects, v2=True)
    newest = square.compose(objects, input_seq=2)
    seed = square.DEVELOPMENT_SEEDS[9]
    state = initial_social_society(square.SOCIETY, seed, released, population=8)
    nodes, adjacent, _ = _graph(released)
    places = {target["node_id"] for target in released["targets"]}

    def nearest_place(node: str) -> int:
        paths = _paths(node, adjacent)
        return min(paths[place][0] for place in places if place in paths)

    agent = state["inhabitants"][0]
    held = {p["location"]["node_id"] for p in state["inhabitants"][1:]}
    far = max(
        (n for n in nodes if adjacent[n] and n not in held),
        key=lambda n: (nearest_place(n), n),
    )
    # A positive control: from there no place can be seen again, so only memory offers them.
    assert nearest_place(far) > OBSERVATION_DISTANCE_MM
    _stand_at(agent, far, nodes)
    _remembering(state, agent, released["targets"], released)
    moved, _, _ = advance_social_society(state, seed, [released, newest])
    chosen = next(p for p in moved["inhabitants"] if p["id"] == agent["id"])
    assert chosen["action"]["status"] != "blocked", chosen["action"]
    assert chosen["goal"]["target_id"] in {t["target_id"] for t in released["targets"]}


def test_the_cast_sees_a_remembered_place_emptied_when_the_newest_input_moves_its_object():
    """Somebody of the cast standing where they remember a place, stated by the older input, sees
    it gone when the edit that moves the society to the newest profile moves its object far away:
    the newer input restates the place, and a restated place elsewhere is not the one remembered."""
    objects = square.square_objects()
    released = square.compose(objects, v2=True)
    seed = square.DEVELOPMENT_SEEDS[10]
    state = initial_social_society(square.SOCIETY, seed, released, population=8)
    nodes, adjacent, _ = _graph(released)
    remembered = next(t for t in released["targets"] if t["object_id"].endswith("-bench"))
    bench = next(o for o in objects if o.object_id == remembered["object_id"])
    here = remembered["node_id"]
    crowded = standing_exclusions(released)

    def moved_to(node: str) -> dict:
        x_mm, z_mm = nodes[node]["position_mm"]
        elsewhere = AuthoredObject(
            object_id=bench.object_id,
            asset_sha256=bench.asset_sha256,
            region_id=bench.region_id,
            transform=Transform(x_mm, 0, z_mm, bench.transform.yaw_microradians, 1000),
            origin=bench.origin,
        )
        moved = tuple(elsewhere if o is bench else o for o in objects)
        return square.compose(moved, input_seq=2, edit_seq=len(objects) + 1)

    def out_of_sight(document: dict) -> bool:
        """The bench is still a place to go, and cannot be seen from where it was."""
        graph = _graph(document)
        restated = next(
            (t for t in document["targets"] if t["target_id"] == remembered["target_id"]), None
        )
        if restated is None or not restated["enabled"] or here not in graph[0]:
            return False
        paths = _paths(here, graph[1])
        return paths.get(restated["node_id"], (math.inf,))[0] > OBSERVATION_DISTANCE_MM

    candidates = sorted(
        (n for n in nodes if adjacent[n] and n not in crowded),
        key=lambda n: (-math.dist(nodes[n]["position_mm"], nodes[here]["position_mm"]), n),
    )
    newest = next(document for document in map(moved_to, candidates) if out_of_sight(document))
    agent = state["inhabitants"][0]
    _stand_at(agent, here, nodes)
    _remembering(state, agent, [remembered], released)
    after, events, _ = advance_social_society(state, seed, [released, newest])
    belief = after["social"]["agents"][agent["id"]]["beliefs"][remembered["target_id"]]
    assert belief["available"] is False
    assert belief["target"] == remembered
    assert any(
        event.kind == "observed"
        and str(event.subject_id) == agent["id"]
        and event.document["observation"]["target"]["target_id"] == remembered["target_id"]
        and event.document["observation"]["available"] is False
        for event in events
    )


def test_a_stay_finishes_relieving_what_it_carries():
    """The relief a stay carries is the routine's it began under, whatever routine is in force when
    it finishes: a stay recorded as relieving 123 relieves 123."""
    document = square.compose(square.square_objects())
    seed = square.DEVELOPMENT_SEEDS[5]
    state = initial_purposeful_society(square.SOCIETY, seed, document, population=8)
    resting = None
    while resting is None:
        state, _ = advance_purposeful_society(state, seed, [document])
        resting = next(
            (
                person
                for person in state["inhabitants"]
                if person["action"]["kind"] == "rest"
                and person["action"]["status"] == "active"
                and person["action"]["remaining_ticks"] == 1
            ),
            None,
        )
    stay = routine_of(document).activities[resting["target"]["activity"]]
    assert resting["action"]["relief_milli"] == stay.relief != 123
    recorded = deepcopy(state)
    mine = next(p for p in recorded["inhabitants"] if p["id"] == resting["id"])
    mine["action"]["relief_milli"] = 123
    finished, _ = advance_purposeful_society(recorded, seed, [document])
    after = next(p for p in finished["inhabitants"] if p["id"] == resting["id"])
    assert after["action"]["status"] == "completed"
    assert after["need_milli"] == max(0, resting["need_milli"] + 1 - 123)


def test_the_first_of_two_to_arrive_waits_for_the_other_with_the_clock_stopped():
    """At a slow walking budget one of two people meeting to talk arrives first. They wait, their
    talk's clock stopped, until the other is there; then both talk and stop in the same minute."""
    document = square.compose(square.square_objects())
    seed = square.DEVELOPMENT_SEEDS[6]
    state = _slow(initial_purposeful_society(square.SOCIETY, seed, document, population=8))
    waited = None
    for _ in range(240):
        state, _ = advance_purposeful_society(state, seed, [document])
        waited = next(
            (p for p in state["inhabitants"] if p["action"]["reason"] == "waiting_for_partner"),
            None,
        )
        if waited is not None:
            break
    assert waited is not None, "nobody arrived to talk before the other"
    partner_id = waited["goal"]["partner_id"]
    duration = waited["goal"]["duration_ticks"]
    assert waited["action"]["remaining_ticks"] == duration
    ended = set()
    for _ in range(40):
        people = {person["id"]: person for person in state["inhabitants"]}
        me, other = people[waited["id"]], people[partner_id]
        if me["action"]["status"] == "completed" or other["action"]["status"] == "completed":
            ended = {me["action"]["status"], other["action"]["status"]}
            break
        if me["action"]["reason"] == "waiting_for_partner":
            # Waiting: the other is on the way, pointed at them, and nobody's clock runs.
            assert other["goal"]["partner_id"] == me["id"]
            assert other["action"]["kind"] in ("move", TALK.key)
            assert me["action"]["remaining_ticks"] == duration
        state, _ = advance_purposeful_society(state, seed, [document])
    assert ended == {"completed"}
    people = {person["id"]: person for person in state["inhabitants"]}
    assert people[waited["id"]]["action"]["reason"] == "reviewed_duration_elapsed"
    assert people[partner_id]["action"]["reason"] == "reviewed_duration_elapsed"


def _post_between(document: dict) -> tuple[dict, str, str]:
    """The square with a lamp post between two open lattice nodes: both nodes are left, and the
    edge between them is not. Returns the input and the two nodes."""
    post = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.lamp-post")
    nodes, edges = input_graph(document)
    crowded = standing_exclusions(document)
    for edge in sorted(edges.values(), key=lambda held: held["edge_id"]):
        a, b = edge["from_node_id"], edge["to_node_id"]
        if a in crowded or b in crowded:
            continue
        (ax, az), (bx, bz) = nodes[a]["position_mm"], nodes[b]["position_mm"]
        between = AuthoredObject(
            object_id="object:between",
            asset_sha256=post.content_sha256,
            region_id="region:starter",
            transform=Transform((ax + bx) // 2, 0, (az + bz) // 2, 0, 1000),
            origin=ObjectOrigin("authored", "fictional"),
        )
        edited = square.compose((*square.square_objects(), between))
        after_nodes, after_edges = input_graph(edited)
        left = {n for pair in after_edges for n in pair}
        if (
            a in after_nodes
            and b in after_nodes
            and {a, b} <= left
            and frozenset((a, b)) not in after_edges
            and not {a, b} & standing_exclusions(edited)
        ):
            return edited, a, b
    raise AssertionError("no edge a post cuts while leaving both of its nodes")


@pytest.mark.parametrize("second_is", ["free", "standing"])
def test_two_people_talk_only_where_nothing_stands_between_them(second_is):
    """Two people on either side of a lamp post, two metres apart, would talk where they stand if
    distance were all. They are not joined by an edge, so the two stand at nodes that are, whether
    the second was free to choose or standing there already."""
    document, a, b = _post_between(square.compose(square.square_objects()))
    nodes, edges = input_graph(document)
    # A positive control: the two nodes are open and within a talking distance, so only the rule
    # that the ground joins them keeps the two from talking through the post.
    assert math.dist(nodes[a]["position_mm"], nodes[b]["position_mm"]) <= TALK.spacing_mm
    seed = square.DEVELOPMENT_SEEDS[7]
    genesis = initial_purposeful_society(square.SOCIETY, seed, document, population=2)
    for person, node in zip(genesis["inhabitants"], (a, b), strict=True):
        point = list(nodes[node]["position_mm"])
        person.update(
            position_mm=point,
            motion_path_mm=[point],
            location={"node_id": node, "edge": None},
            need_milli=0,
        )
    first, second = (person["id"] for person in genesis["inhabitants"])
    if second_is == "standing":
        genesis["inhabitants"][1].update(
            goal={"kind": STAND.key, "target_id": None, "reason": "stopping_a_while"},
            route={
                "node_ids": [b],
                "edge_index": 0,
                "edge_progress_mm": 0,
                "destination_node_id": b,
                "input_sha256": document["document_sha256"],
            },
            route_geometry_sha256=square.digest(document["navigation"]),
            action={
                "kind": STAND.key,
                "status": "active",
                "target_id": None,
                "remaining_ticks": STAND.duration_maximum,
                "reason": "standing_a_while",
                "relief_milli": STAND.relief,
            },
        )
    talked = 0
    for tick in range(1, 80):
        state = deepcopy(genesis)
        state["tick"] = tick - 1
        after, _ = advance_purposeful_society(state, seed, [document])
        people = {person["id"]: person for person in after["inhabitants"]}
        goal = people[first]["goal"]
        if goal is None or goal["kind"] != TALK.key:
            continue
        assert goal["partner_id"] == second
        spots = (
            people[first]["route"]["destination_node_id"],
            people[second]["route"]["destination_node_id"],
        )
        assert frozenset(spots) in edges, spots
        assert set(spots) != {a, b}
        talked += 1
    assert talked > 0, "the two never stopped to talk"
