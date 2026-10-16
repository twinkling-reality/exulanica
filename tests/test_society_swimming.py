"""Swimming: a body that swims crosses a world's water, walking the land on either side of it.

The swimming module (``exulanica-movement/swimming/v1``) moves a being of a society of things whose
first input records it, and whose kind's moves name it, over the water its input states
(``tests/test_society_water.py``) as well as its walking graph. What is shown, with no database:

*   the row, what a new society records, and the arithmetic by hand: the reference pace in water
    is 400 in a thousand, so 60,000 mm of a society's budget swims 24,000 mm;
*   the quickest route walks round water where that is quicker and swims across where it is not;
    over a graph with no water it is walking's own route;
*   a minute over land and water shares the society's budget stretch by stretch, worked by hand;
*   on the fixture farm, a body with legs and a pair of fins asked to stand across its pond walks
    to the shore, swims across at the swim pace and walks on, minute by minute, and the society
    replays;
*   nobody whose kind does not swim ever enters the water, and a society made before swimming
    was built walks the same body round the pond.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from exulanica.movement import steps, swimming, walking
from exulanica.movement.registry import (
    SWIMMING,
    WALKING,
    WALKING_V2,
    built_module,
    current_engine_modules,
)
from exulanica.movement.swimming import (
    crossing,
    own_budget_mm,
    quickest_routes,
    spent_mm,
    traverse_swimming,
)
from exulanica.movement.walking import routes_from, traverse
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import (
    MOVEMENT_BUDGET_MM,
    advance_purposeful_society,
    routine_of,
)
from exulanica.world.society_things import (
    THINGS_PROFILE,
    advance_things,
    initial_things_society,
)
from exulanica.world.society_water import WATER_FIELD

from water_society_support import (
    SEED,
    SOCIETY,
    compose_farm,
    farm,
    finned_walker,
    placed,
    resealed,
)

#: Where the body is put, in the site's own frame (east and north): on the walking line along the
#: pond's south side, at its node zone:02:high:006; and where it is asked to stand, across the pond
#: by its north-east corner.
START_MM = (74181, 1500)
ACROSS = "zone:02:yard:0086000:0036500"


# -- the module ---------------------------------------------------------------------------------


def test_the_swimming_row_moves_the_society_of_things_and_a_new_one_records_it():
    row = built_module(SWIMMING)
    assert (row.agents_catalog, row.agents_kinds) == ("society-engines", (THINGS_PROFILE,))
    assert (row.space_kind, row.space_profiles) == (
        "water-lattice",
        ("exulanica.society-water/v1",),
    )
    assert (row.clock_kind, row.step_ms) == ("society", 60_000)
    assert row.output_profile == walking.MOTION_PATH_PROFILE
    assert row.supplied() == ("budget_mm_per_tick", "pace_permille")
    assert row.value("reference_pace_permille") == swimming.REFERENCE_PACE_PERMILLE == 400
    assert steps.step_of(SWIMMING) is traverse_swimming
    assert current_engine_modules(THINGS_PROFILE) == (SWIMMING, WALKING_V2)
    # No other engine swims: its people walk as they always did.
    assert current_engine_modules("exulanica-society/v3") == (WALKING,)


def test_a_swimmer_spends_its_pace_of_the_society_s_budget_by_hand():
    # 60,000 mm at 400 in a thousand is 24,000 mm; the floor keeps a whole millimetre, at least one.
    assert own_budget_mm(60_000, 400) == 24_000
    assert own_budget_mm(2_000, 333) == 666
    assert own_budget_mm(1, 1) == 1
    # What swimming 24,000 mm at 400 in a thousand spends of the budget, rounded up.
    assert spent_mm(24_000, 400) == 60_000
    assert spent_mm(1, 400) == 3
    with pytest.raises(ValueError, match="pace_permille"):
        own_budget_mm(60_000, 0)


def _graph(edges: list[tuple[str, str, int]]) -> tuple[dict, dict, dict]:
    nodes: dict[str, Any] = {}
    adjacent: dict[str, list] = {}
    keyed = {}
    for a, b, length in edges:
        edge = {"edge_id": f"{a}|{b}", "length_mm": length}
        for one, other in ((a, b), (b, a)):
            adjacent.setdefault(one, []).append((other, edge))
            nodes.setdefault(one, {"position_mm": [0, 0]})
        keyed[frozenset((a, b))] = edge
    for values in adjacent.values():
        values.sort(key=lambda pair: pair[0])
    return nodes, adjacent, keyed


def test_the_quickest_route_swims_only_where_walking_round_takes_longer():
    """From a to d: round by land is 30 m, across the water 10 m. At 400 in a thousand in water
    and the society's own pace on land, the water takes the time 25 m of walking does, so the
    route swims; at 300 it takes the time of 33.3 m, so the route walks round."""
    _nodes, adjacent, _edges = _graph(
        [("a", "b", 10_000), ("b", "c", 10_000), ("c", "d", 10_000), ("a", "d", 10_000)]
    )
    wet = {"a|d"}
    assert quickest_routes("a", adjacent, wet, 1000, 400)["d"] == (10_000 * 1000, ("a", "d"))
    assert quickest_routes("a", adjacent, wet, 1000, 300)["d"] == (
        30_000 * 300,
        ("a", "b", "c", "d"),
    )
    # With no water, the quickest route is walking's own, every cost the length times the pace.
    for start in "abcd":
        dry = quickest_routes(start, adjacent, set(), 846, 400)
        walked = routes_from(start, adjacent)
        assert {node: (cost // 400, path) for node, (cost, path) in dry.items()} == walked


def test_a_minute_over_land_and_water_shares_the_budget_stretch_by_stretch_by_hand():
    """10 m of land, 10 m of water, 10 m of land, on a budget of 20,000 mm, walked at the
    society's own pace (the first walking) and swum at 400. The land takes 10,000 of it; the
    10,000 left swims 4,000 mm; the minute ends 4,000 mm into the water. The next minute swims the
    other 6,000 mm, which spends 15,000, and walks 5,000 mm of the last stretch."""
    nodes = {
        "a": {"position_mm": [0, 0]},
        "b": {"position_mm": [10_000, 0]},
        "c": {"position_mm": [20_000, 0]},
        "d": {"position_mm": [30_000, 0]},
    }
    _n, _adjacent, edges = _graph([("a", "b", 10_000), ("b", "c", 10_000), ("c", "d", 10_000)])
    route = {"node_ids": ["a", "b", "c", "d"], "edge_index": 0, "edge_progress_mm": 0}

    def minute() -> list[tuple[str, str, int, list[int]]]:
        legs = crossing(
            route, nodes, edges, {"b|c"}, 20_000, traverse, None, traverse_swimming, 400
        )
        return [(leg.from_node, leg.to_node, leg.step_mm, leg.point) for leg in legs]

    assert minute() == [("a", "b", 10_000, [10_000, 0]), ("b", "c", 4_000, [14_000, 0])]
    assert (route["edge_index"], route["edge_progress_mm"]) == (1, 4_000)
    assert minute() == [("b", "c", 6_000, [20_000, 0]), ("c", "d", 5_000, [25_000, 0])]
    assert (route["edge_index"], route["edge_progress_mm"]) == (2, 5_000)


# -- a body with fins on the farm ------------------------------------------------------------


def _swimmer_society(**compose: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    sha256, form = finned_walker()
    document = compose_farm(
        placed("swimmer", sha256, *START_MM), made_kinds={sha256: form}, **compose
    )
    state = initial_things_society(
        SOCIETY, SEED, document, population=document["population"]["size"]
    )
    [being] = [p for p in state["inhabitants"] if p.get("placed_id") == "swimmer"]
    return document, state, being["id"]


def _asked_to_stand(document: dict[str, Any], subject: str, node: str) -> dict[str, Any]:
    """A person's request that the being go and stand at ``node``."""
    stand = routine_of(document).in_setting("open")
    assert stand is not None
    return {
        subject: {
            "allowed_target_ids": [],
            "activity": stand.key,
            "place_node_id": node,
            "chosen_by": "person",
        }
    }


def _minutes(
    state: dict[str, Any], document: dict[str, Any], policy: dict[str, Any] | None, count: int
) -> list[tuple[dict[str, Any], list[Any]]]:
    """``count`` minutes over ``document``, the request handed to the first."""
    played = []
    for minute in range(count):
        planned, events = advance_purposeful_society(
            state, SEED, [document], goal_policy=policy if minute == 0 else None
        )
        state, events, _bound = advance_things(state, planned, SEED, document, events)
        played.append((state, list(events)))
    return played


def _person(state: dict[str, Any], subject: str) -> dict[str, Any]:
    return next(person for person in state["inhabitants"] if person["id"] == subject)


def _wet_points(document: dict[str, Any]) -> set[tuple[int, int]]:
    return {tuple(node["position_mm"]) for node in document[WATER_FIELD]["nodes"]}


def test_a_finned_body_walks_to_the_shore_swims_across_and_walks_on():
    """Worked by hand from the farm's walking line and the lattice laid 2 m apart in its pond. The
    body's own walking budget is 60,000 mm at its pace of 846 in a thousand.

    Minute 1: it walks the 3,864 mm from its node to the next along the line, which spends
    3,864,000 / 846, rounded up, 4,568 of the budget; the 55,432 left swim 22,172 mm: 2,501 mm out
    to the lattice node 2.5 m off the line, and 19,671 mm north, so the minute ends at
    (78000, -23671), on a swim edge. Minute 2: it swims the 10,329 mm to the lattice's far row and
    the 2,001 mm to the shore, 12,330 mm that spend 30,825; the 29,175 left let it walk 24,682 mm,
    more than the 3,864 mm and 4,122 mm to where it was asked to stand, so it arrives and stands."""
    document, state, subject = _swimmer_society()
    _sha256, form = finned_walker()
    assert [move["module"] for move in form["moves"]] == [SWIMMING, WALKING]
    assert form["moves"][1]["parameters"] == {"pace_permille": 846}
    assert MOVEMENT_BUDGET_MM == state["movement_budget_mm_per_tick"] == 60_000
    assert _person(state, subject)["location"] == {"node_id": "zone:02:high:006", "edge": None}
    (first, _events), (second, _), (third, _) = _minutes(
        state, document, _asked_to_stand(document, subject, ACROSS), 3
    )
    wet = _wet_points(document)
    walked = 78045 - 74181
    left = MOVEMENT_BUDGET_MM - math.ceil(walked * 1000 / 846)
    assert (walked, left, left * 400 // 1000) == (3_864, 55_432, 22_172)
    me = _person(first, subject)
    path = me["motion_path_mm"]
    assert path[:2] == [[74181, -1500], [78045, -1500]]  # walked along the line to the shore
    assert path[2] == [78000, -4000] and all(tuple(point) in wet for point in path[2:-1])
    assert path[-1] == [78000, -4000 - (22_172 - 2_501)] == [78000, -23671]
    assert me["action"]["kind"] == "move" and me["location"]["node_id"] is None
    assert me["location"]["edge"]["edge_id"] == (
        "water:+00078000:-00022000|water:+00078000:-00024000"
    )
    me = _person(second, subject)
    path = me["motion_path_mm"]
    swum = (34_000 - 23_671) + 2_001
    left = MOVEMENT_BUDGET_MM - math.ceil(swum * 1000 / 400)
    assert (swum, left, left * 846 // 1000) == (12_330, 29_175, 24_682)
    assert path[0] == [78000, -23671] and path[6] == [78000, -34000]
    assert all(tuple(point) in wet for point in path[1:7])
    assert path[7:] == [[78045, -36000], [81909, -36000], [86000, -36500]]  # walked on, ashore
    assert me["location"] == {"node_id": ACROSS, "edge": None}
    assert (me["action"]["kind"], me["action"]["reason"]) == ("stand", "standing_a_while")
    assert _person(third, subject)["motion_path_mm"] == [[86000, -36500]]


def test_the_society_replays_minute_by_minute():
    document, state, subject = _swimmer_society()
    policy = _asked_to_stand(document, subject, ACROSS)
    played = _minutes(state, document, policy, 12)
    again = _minutes(state, document, policy, 12)
    assert [society_state_sha256(after) for after, _ in played] == [
        society_state_sha256(after) for after, _ in again
    ]
    assert [[event.event_id for event in events] for _, events in played] == [
        [event.event_id for event in events] for _, events in again
    ]
    # The minute it swam in is in the history it replays.
    assert any(
        point and tuple(point) in _wet_points(document)
        for after, _ in played
        for point in _person(after, subject)["motion_path_mm"]
    )


def test_nobody_whose_kind_does_not_swim_enters_the_water():
    """An hour of the farm's own people, beside the body that swims: not one of them stands on,
    walks along or passes a point of the water."""
    document, state, subject = _swimmer_society()
    wet = _wet_points(document)
    wet_nodes = {node["node_id"] for node in document[WATER_FIELD]["nodes"]}
    pond = farm().pond
    walkers = 0
    for after, _events in _minutes(state, document, _asked_to_stand(document, subject, ACROSS), 60):
        for person in after["inhabitants"]:
            if person["id"] == subject:
                continue
            walkers += 1
            location = person["location"]
            assert location["node_id"] not in wet_nodes
            assert (
                location["edge"] is None
                or not {
                    location["edge"]["from_node_id"],
                    location["edge"]["to_node_id"],
                }
                & wet_nodes
            )
            for x, z in person["motion_path_mm"]:
                assert (x, z) not in wet
                assert not (
                    pond.min_x_mm < x < pond.max_x_mm and pond.min_y_mm < -z < pond.max_y_mm
                )
    assert walkers > 0


def _walks_round(after: list[tuple[dict[str, Any], list[Any]]], subject: str) -> None:
    pond = farm().pond
    points = [point for state, _ in after for point in _person(state, subject)["motion_path_mm"]]
    assert points and not any(
        pond.min_x_mm < x < pond.max_x_mm and pond.min_y_mm < -z < pond.max_y_mm for x, z in points
    )
    assert _person(after[-1][0], subject)["location"] == {"node_id": ACROSS, "edge": None}


def test_a_society_made_before_swimming_walks_the_same_body_round_the_pond():
    """A society whose first input records the walking alone, as every one made before swimming
    was built: its input states no water, and the body walks round, arriving later."""
    document, state, subject = _swimmer_society()
    before = resealed(document, movement_modules=[WALKING_V2], water=None)
    state = initial_things_society(SOCIETY, SEED, before, population=before["population"]["size"])
    after = _minutes(state, before, _asked_to_stand(before, subject, ACROSS), 4)
    assert WATER_FIELD not in before
    _walks_round(after, subject)


def test_a_society_that_records_no_swimming_never_swims_over_an_input_stating_water():
    """The runtime hands no water to a society made before swimming was built; should a later
    input state some all the same, the planner reads none for it, since its society records no
    swimming."""
    document, state, subject = _swimmer_society()
    first = resealed(document, movement_modules=[WALKING_V2], water=None)
    state = initial_things_society(SOCIETY, SEED, first, population=first["population"]["size"])
    later = compose_farm(
        placed("swimmer", finned_walker()[0], *START_MM),
        input_seq=2,
        made_kinds={finned_walker()[0]: finned_walker()[1]},
    )
    assert WATER_FIELD in later
    played = []
    policy = _asked_to_stand(later, subject, ACROSS)
    for minute in range(4):
        inputs = [first, later] if minute == 0 else [later]
        planned, events = advance_purposeful_society(
            state, SEED, inputs, goal_policy=policy if minute == 0 else None
        )
        state, events, _bound = advance_things(state, planned, SEED, later, events)
        played.append((state, list(events)))
    _walks_round(played, subject)


def test_a_body_that_does_not_swim_walks_round_in_a_society_that_swims():
    """The same body drafted to walk alone: its kind's moves name no swimming, so the water its
    society's input states is no way for it."""
    from exulanica.selection.creature_drafting import assembled_form
    from exulanica.things.bodies import body_grammar, read_body_recipe
    from exulanica.things.creatures import assemble_creature
    from exulanica.things.run_forms import run_form

    from creature_support import form_of
    from water_society_support import BY

    form = form_of("three_heads", label="finned stroller", moves=["walking"])
    form["fins"], form["fin_segments"] = 2, 2
    creature = assemble_creature(assembled_form(form, body_grammar()), by=BY)
    run = run_form(creature.kind, creature.plan, read_body_recipe(dict(creature.recipe)))
    document = compose_farm(
        placed("walker", creature.kind.sha256, *START_MM), made_kinds={creature.kind.sha256: run}
    )
    assert WATER_FIELD in document
    state = initial_things_society(
        SOCIETY, SEED, document, population=document["population"]["size"]
    )
    [subject] = [p["id"] for p in state["inhabitants"] if p.get("placed_id") == "walker"]
    _walks_round(_minutes(state, document, _asked_to_stand(document, subject, ACROSS), 4), subject)


def test_a_swimmer_in_the_water_is_offered_nothing_until_it_is_ashore():
    """The choices a decider is offered read the walking graph: a being in the water stands on no
    node of it, so it is offered nothing, and nothing is refused for it, until it is ashore."""
    from exulanica.world.society_decision_contract import choice_options, person_role

    document, state, subject = _swimmer_society()
    [(first, _events)] = _minutes(state, document, _asked_to_stand(document, subject, ACROSS), 1)
    swimming_now = _person(first, subject)
    assert swimming_now["location"]["edge"]["from_node_id"].startswith("water:")
    swimming_now["goal"] = None  # as at a choice point, mid-water
    role = person_role()
    contract = role.contract(role.terms(THINGS_PROFILE).versions)
    assert choice_options(first, document, subject, contract, seed=SEED) == ()
