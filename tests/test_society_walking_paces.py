"""A society of things walks each body at its own pace, where its first input records that it does.

The second walking module (``exulanica-movement/walking/v2``) spends, for each walker, the
society's budget scaled by the pace its kind states. What is shown, on society-of-things states
and with no database:

*   the row, and what a new society of each engine records;
*   the arithmetic, by hand: a budget of 60,000 mm at a pace of 251 in a thousand is 15,060 mm;
*   every first things input, on every ground a society of things is composed over here, records
    its ability modules and its movement modules, and no later input records either;
*   a society that records the second walking moves each walker along its route by exactly its own
    budget in every minute it does not arrive, read from the route's own progress;
*   a society of shipped kinds alone lives the same hour whether or not it records it;
*   a society that records none (every stored one) walks a made creature at the society's pace,
    whatever its run form states, by the first module.

The paces are the ones tests/test_creature_gaits.py works by hand from each fixture's joints
(bat 251, horse 1,040, dragon 1,171); the budgets below are those times the society's budget over
a thousand, floored.
"""

from __future__ import annotations

import copy
import math
from itertools import pairwise
from types import MappingProxyType
from typing import Any

import pytest
from exulanica.movement import steps, walking, walking_v2
from exulanica.movement.registry import (
    FLIGHT_V2,
    MODULES,
    ROADS,
    WALKING,
    WALKING_V2,
    MovementError,
    ParameterOutOfBounds,
    built_module,
    check_recorded,
    current_engine_modules,
    recorded_movement,
)
from exulanica.things.gaits import PACE_PERMILLE
from exulanica.things.run_forms import RunFormRefused, read_run_form
from exulanica.world.society_engines import ENGINES
from exulanica.world.society_grounds import society_grounds
from exulanica.world.society_kinds import pace_permille_of
from exulanica.world.society_planner import (
    NAVIGATION_PROFILES,
    THING_INPUTS,
    advance_purposeful_society,
    input_sha256,
    tick_budgets,
    validate_society_input,
    walker_paces,
)
from exulanica.world.society_thing_inputs import (
    MOVEMENT_MODULES_FIELD,
    record_modules,
    things_engine,
)
from exulanica.world.society_things import (
    THINGS_PROFILE,
    advance_things,
    initial_things_society,
    validate_things_state,
)

import test_society_hands_requests as asked
import test_walking_surfaces_v3 as town
from test_society_made_kinds import KNIGHT, WELL, _made, _placed
from things_society_support import SEED, SOCIETY, compose, reference

#: What tests/test_creature_gaits.py works by hand for these fixtures' bodies.
PACES = {"bat": 251, "horse": 1040, "dragon": 1171}
#: A society's budget here: 2 m a minute, so a walk across the square takes several minutes and
#: a walker is seen walking a whole minute through, between a route's first minute and its last.
BUDGET = 2_000
#: What each spends in a minute at that budget: 2,000 times its pace over 1,000, floored.
OWN = {"bat": 502, "horse": 2_080, "dragon": 2_342, "shipped": 2_000}
POPULATION = 6


# -- the row and what a society records -------------------------------------------------------


def test_the_second_walking_moves_the_society_of_things_alone_and_declares_a_pace():
    row = built_module(WALKING_V2)
    things = [engine.engine for engine in ENGINES if engine.state_family == "things"]
    assert things == [THINGS_PROFILE] == [things_engine()]
    assert (row.agents_catalog, row.agents_kinds) == ("society-engines", (THINGS_PROFILE,))
    # The graphs a things input states, and no other.
    assert set(row.space_profiles) == {NAVIGATION_PROFILES[profile] for profile in THING_INPUTS}
    assert row.output_profile == walking.MOTION_PATH_PROFILE
    assert (row.clock_kind, row.step_ms) == ("society", 60_000)
    assert sorted(row.parameters) == [
        "budget_mm_per_tick",
        "pace_permille",
        "reference_pace_permille",
    ]
    assert row.supplied() == ("budget_mm_per_tick", "pace_permille")
    assert row.value("reference_pace_permille") == walking_v2.REFERENCE_PACE_PERMILLE == 1000
    # The budget's bounds are the first version's; the name a kind states a pace under is the
    # row's.
    first, second = (built_module(m).parameter("budget_mm_per_tick") for m in (WALKING, WALKING_V2))
    assert (first.minimum, first.maximum) == (second.minimum, second.maximum)
    assert walking_v2.PACE_PARAMETER == PACE_PERMILLE == "pace_permille"
    assert steps.step_of(WALKING_V2) is walking_v2.traverse_paced


def test_a_new_society_records_the_newest_walking_that_moves_its_engine():
    assert current_engine_modules(THINGS_PROFILE) == (WALKING_V2,)
    for engine in ENGINES:
        if engine.state_family not in ("legacy", "things"):
            assert current_engine_modules(engine.engine) == (WALKING,), engine.engine
    # An engine no row moves records none.
    assert current_engine_modules("exulanica-society/v1") == ()
    assert current_engine_modules("exulanica-society/v99") == ()


@pytest.mark.parametrize(
    ("modules", "match"),
    [
        ([WALKING_V2], None),
        ([WALKING], None),
        ([], "once each, in order, at least one"),
        ((WALKING_V2,), "once each, in order, at least one"),
        ([WALKING_V2, WALKING_V2], "once each, in order"),
        ([WALKING_V2, WALKING], "once each, in order"),
        ([WALKING, WALKING_V2], "one version of each kind"),
        ([FLIGHT_V2], "does not move the people"),
        ([ROADS], "does not move the people"),
        (["exulanica-movement/swimming/v1"], "unknown movement module"),
        ([7], "unknown movement module"),
    ],
)
def test_a_recorded_list_is_held_to_its_shape(modules, match):
    if match is None:
        assert check_recorded(modules, THINGS_PROFILE) == tuple(modules)
        return
    with pytest.raises(MovementError, match=match):
        check_recorded(modules, THINGS_PROFILE)


def test_a_module_that_moves_another_engine_alone_is_refused_for_this_one():
    # The second walking lists the society of things alone.
    with pytest.raises(MovementError, match="does not move the people of exulanica-society/v2"):
        check_recorded([WALKING_V2], "exulanica-society/v2")


def test_the_recorded_walking_is_the_version_recorded_or_none():
    assert recorded_movement(None, "walking") is None
    assert recorded_movement((), "walking") is None
    assert recorded_movement([WALKING_V2], "walking") is built_module(WALKING_V2)
    assert recorded_movement([WALKING], "walking") is built_module(WALKING)
    assert recorded_movement([WALKING_V2], "flight") is None


# -- the arithmetic ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("budget", "pace", "spent"),
    [
        (60_000, 1000, 60_000),
        (60_000, 251, 15_060),
        (60_000, 1171, 70_260),
        (2_000, 251, 502),
        (2_000, 1040, 2_080),
        (2_000, 1171, 2_342),
        (999, 333, 332),  # 332.667, floored
        (7, 100, 1),  # 0.7: never less than one
        (1, 1, 1),
        (10**9, 10_000, 10**10),
    ],
)
def test_a_walker_spends_the_budget_times_its_pace_over_a_thousand_floored(budget, pace, spent):
    assert walking_v2.own_budget_mm(budget, pace) == spent


@pytest.mark.parametrize(
    ("budget", "pace"),
    [(60_000, 0), (60_000, 10_001), (60_000, -1), (0, 1000), (10**9 + 1, 1000), (60_000, True)],
)
def test_a_figure_outside_the_row_s_bounds_is_refused(budget, pace):
    with pytest.raises(ParameterOutOfBounds):
        walking_v2.own_budget_mm(budget, pace)


def _diagonal() -> tuple[dict, dict, dict]:
    """tests/test_movement_modules.py's diagonal edge: 1,055 mm along two axes, one negative."""
    nodes = {"a": {"position_mm": [0, 0, 0]}, "b": {"position_mm": [1000, 0, -333]}}
    edges = {frozenset(("a", "b")): {"edge_id": "a-b", "length_mm": 1055}}
    return nodes, edges, {"node_ids": ["a", "b"], "edge_index": 0, "edge_progress_mm": 0}


def test_the_paced_step_is_the_first_step_over_the_walker_s_own_budget():
    nodes, edges, route = _diagonal()
    # Half pace on a budget of 1,000 is the 500 mm the first module's own test walks.
    [leg] = walking_v2.traverse_paced(route, nodes, edges, 1000, 500)
    assert leg.point == [473, 0, -158]
    assert (leg.step_mm, leg.arrived, route["edge_progress_mm"]) == (500, False, 500)
    # At the society's own pace it is the first module's walk, leg for leg.
    for budget in (1, 400, 1055, 5000):
        _, _, first = _diagonal()
        _, _, second = _diagonal()
        assert list(walking_v2.traverse_paced(second, nodes, edges, budget, 1000)) == list(
            walking.traverse(first, nodes, edges, budget)
        )
        assert first == second


def test_a_run_form_s_pace_reads_across_exactly_the_row_s_bounds():
    """The reader of a made kind's run form and the module that spends its pace state one range."""
    _sha, form = _made("horse")
    pace = built_module(WALKING_V2).parameter("pace_permille")

    def with_pace(value: object) -> dict[str, Any]:
        changed = copy.deepcopy(form)
        [move] = [m for m in changed["moves"] if PACE_PERMILLE in m["parameters"]]
        move["parameters"][PACE_PERMILLE] = value
        return changed

    for inside in (pace.minimum, pace.maximum):
        read_run_form(with_pace(inside))
    for outside in (pace.minimum - 1, pace.maximum + 1):
        with pytest.raises(RunFormRefused):
            read_run_form(with_pace(outside))


# -- what a first input records ---------------------------------------------------------------


def _first_and_later() -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """A first and a later things input over each ground composed here, by the ground's composer."""
    return {
        "authored-starter-world": (compose((KNIGHT,)), compose((KNIGHT,), input_seq=2, edit_seq=9)),
        "city-grammar-town": (town._compose(), town._compose(input_seq=2)),
    }


def test_every_first_things_input_records_both_lists_and_no_later_one_either():
    from exulanica.abilities.registry import current_modules

    composed = _first_and_later()
    for composer, (first, later) in composed.items():
        assert first["profile"] in THING_INPUTS, composer
        assert first["modules"] == list(current_modules()), composer
        assert first[MOVEMENT_MODULES_FIELD] == [WALKING_V2], composer
        assert "modules" not in later and MOVEMENT_MODULES_FIELD not in later, composer
        validate_society_input(first)
        validate_society_input(later)
    # Every graph a things input states is composed above: a ground composed another way joins
    # this test with its composer.
    walked = {NAVIGATION_PROFILES[first["profile"]] for first, _later in composed.values()}
    assert walked == {NAVIGATION_PROFILES[profile] for profile in THING_INPUTS}
    known = {ground.composer_key for ground in society_grounds()}
    assert set(composed) <= known


def test_the_one_function_writes_a_first_input_s_lists_and_nothing_into_a_later_one():
    from exulanica.abilities.registry import current_modules

    first: dict[str, Any] = {"input_seq": 1}
    record_modules(first)
    assert first == {
        "input_seq": 1,
        "modules": list(current_modules()),
        MOVEMENT_MODULES_FIELD: [WALKING_V2],
    }
    later: dict[str, Any] = {"input_seq": 2}
    record_modules(later)
    assert later == {"input_seq": 2}


def _resealed(document: dict[str, Any]) -> dict[str, Any]:
    document.pop("document_sha256")
    document["document_sha256"] = input_sha256(document)
    return document


def _recording(document: dict[str, Any], modules: object) -> dict[str, Any]:
    """``document`` recording ``modules`` as its movement modules, or none for None, resealed."""
    changed = copy.deepcopy(document)
    changed.pop(MOVEMENT_MODULES_FIELD, None)
    if modules is not None:
        changed[MOVEMENT_MODULES_FIELD] = modules
    return _resealed(changed)


@pytest.mark.parametrize(
    ("modules", "match"),
    [
        ([], "movement modules"),
        ([WALKING, WALKING_V2], "one version of each kind"),
        ([FLIGHT_V2], "does not move the people"),
        (["exulanica-movement/swimming/v1"], "unknown movement module"),
        (WALKING_V2, "movement modules"),
    ],
)
def test_an_input_recording_a_list_out_of_shape_is_refused(modules, match):
    first = compose((KNIGHT,))
    validate_society_input(_recording(first, [WALKING_V2]))  # positive control
    validate_society_input(_recording(first, [WALKING]))
    validate_society_input(_recording(first, None))
    with pytest.raises(ValueError, match=match):
        validate_society_input(_recording(first, modules))


def test_a_later_input_that_records_movement_modules_is_refused():
    later = compose((KNIGHT,), input_seq=2, edit_seq=9)
    validate_society_input(later)
    with pytest.raises(ValueError, match="first input alone records its movement modules"):
        validate_society_input(_recording(later, [WALKING_V2]))


def test_a_later_input_that_records_none_reads_the_same_as_the_first():
    from exulanica.api.society_runtime import _reads_the_same

    first = compose((KNIGHT,))
    later = compose((KNIGHT,), input_seq=2, edit_seq=9)
    assert MOVEMENT_MODULES_FIELD in first and MOVEMENT_MODULES_FIELD not in later
    assert _reads_the_same(first, later)
    # A list a later input did state would be a difference: only its absence is none.
    assert not _reads_the_same(first, {**later, "things": []})


# -- the state --------------------------------------------------------------------------------


def _genesis(document: dict[str, Any], *, budget: int | None = BUDGET) -> dict[str, Any]:
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    if budget is not None:
        # A society walks at the budget its own state records.
        state["movement_budget_mm_per_tick"] = budget
    return state


def _minute(state: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    planned, events = advance_purposeful_society(state, SEED, [document])
    after, events, _bound = advance_things(state, planned, SEED, document, events)
    return after, list(events)


def test_genesis_keeps_the_list_its_first_input_records_and_none_where_it_records_none():
    first = compose((KNIGHT,))
    state = _genesis(first)
    assert state[MOVEMENT_MODULES_FIELD] == first[MOVEMENT_MODULES_FIELD] == [WALKING_V2]
    assert state[MOVEMENT_MODULES_FIELD] is not first[MOVEMENT_MODULES_FIELD]
    assert MOVEMENT_MODULES_FIELD not in _genesis(_recording(first, None))
    after, _events = _minute(state, first)
    assert after[MOVEMENT_MODULES_FIELD] == [WALKING_V2]


@pytest.mark.parametrize(
    "modules", [[], [WALKING, WALKING_V2], [FLIGHT_V2], ["exulanica-movement/swimming/v1"]]
)
def test_a_state_recording_a_list_out_of_shape_is_refused(modules):
    state = _genesis(compose((KNIGHT,)))
    validate_things_state(state)
    state[MOVEMENT_MODULES_FIELD] = modules
    with pytest.raises(ValueError, match="movement modules"):
        validate_things_state(state)


# -- the walk ---------------------------------------------------------------------------------


def _creatures() -> tuple[dict[str, Any], dict[str, str]]:
    """The square with a knight, a well, and a bat, a horse and a dragon its workspace keeps:
    the first input, and each creature's kind digest by its name."""
    made = {name: _made(name) for name in PACES}
    placed = [
        _placed(f"creature:{name}", made[name][0], x, z)
        for name, (x, z) in zip(
            PACES, [(-2_000, 4_000), (2_000, -4_000), (-5_000, -3_000)], strict=True
        )
    ]
    document = compose(
        (WELL, KNIGHT, *placed), made_kinds={sha256: form for sha256, form in made.values()}
    )
    return document, {made[name][0]: name for name in PACES}


def test_the_fixtures_run_forms_state_the_paces_worked_by_hand():
    document, names = _creatures()
    state = _genesis(document)
    stated = {
        names[sha256]: pace_permille_of(state, {"source": "workspace", "sha256": sha256})
        for sha256 in names
    }
    assert stated == PACES
    # A shipped kind states none, and neither does a made kind the records no longer state.
    assert pace_permille_of(state, reference("knight", 1)) is None
    assert pace_permille_of(state, {"source": "workspace", "sha256": "0" * 64}) is None
    assert pace_permille_of(None, {"source": "workspace", "sha256": next(iter(names))}) is None


def _name(person: dict[str, Any], names: dict[str, str]) -> str:
    kind = person["kind"]
    return names[kind["sha256"]] if kind.get("source") == "workspace" else "shipped"


def test_each_walker_is_handed_its_own_pace_and_spends_its_own_budget():
    document, names = _creatures()
    state = _genesis(document)
    pace, spends = walker_paces(state), tick_budgets(state)
    assert pace is not None
    seen = set()
    for person in state["inhabitants"]:
        name = _name(person, names)
        seen.add(name)
        assert pace(person) == PACES.get(name, 1000), name
        assert spends(person) == OWN[name], name
    assert seen == {"bat", "horse", "dragon", "shipped"}
    # Somebody of no kind, as a purposeful society's people are, walks at the society's pace.
    assert pace({"id": "nobody"}) == 1000
    # A society that records none, or the first walking, paces nobody and spends one budget.
    for recorded in (None, [WALKING]):
        before = _genesis(_recording(document, recorded))
        assert walker_paces(before) is None
        assert {tick_budgets(before)(person) for person in before["inhabitants"]} == {BUDGET}


def _progress(route: dict[str, Any], lengths: dict[frozenset[str], int]) -> int:
    """How far along its route a walker is: the edges behind it and its progress on this one."""
    behind = pairwise(route["node_ids"][: route["edge_index"] + 1])
    return sum(lengths[frozenset(pair)] for pair in behind) + route["edge_progress_mm"]


def _walked(document: dict[str, Any], state: dict[str, Any], minutes: int) -> dict[str, list[int]]:
    """For each walker, by its name here, how far it moved along its route in each minute it
    walked the whole minute through: on the same route before and after, and not arrived."""
    _document, names = _creatures()
    lengths = {
        frozenset((edge["from_node_id"], edge["to_node_id"])): edge["length_mm"]
        for edge in document["navigation"]["edges"]
    }
    moved: dict[str, list[int]] = {}
    for _ in range(minutes):
        after, _events = _minute(state, document)
        was = {person["id"]: person for person in state["inhabitants"]}
        for person in after["inhabitants"]:
            before, route = was.get(person["id"]), person["route"]
            if before is None or route is None or before["route"] is None:
                continue
            same = route["node_ids"] == before["route"]["node_ids"]
            arrived = route["edge_index"] == len(route["node_ids"]) - 1
            if same and not arrived and before["action"]["kind"] == "move":
                step = _progress(route, lengths) - _progress(before["route"], lengths)
                moved.setdefault(_name(person, names), []).append(step)
        state = after
    return moved


def test_a_society_that_records_the_second_walking_moves_each_body_by_its_own_budget():
    document, _names = _creatures()
    assert document[MOVEMENT_MODULES_FIELD] == [WALKING_V2]
    moved = _walked(document, _genesis(document), 120)
    # Everybody was seen walking a whole minute through, so the figures below are not vacuous.
    assert set(moved) == {"bat", "horse", "dragon", "shipped"}
    for name, steps_walked in moved.items():
        assert set(steps_walked) == {OWN[name]}, name
    # The bat is the slowest and the dragon the fastest, by their bodies.
    assert OWN["bat"] < OWN["shipped"] < OWN["horse"] < OWN["dragon"]


def test_a_society_that_records_none_walks_every_body_at_the_society_s_pace():
    """A stored society's first input records no movement module: its made creature's run form
    may state a pace, and it still walks by the first module, at the one budget."""
    document, _names = _creatures()
    stored = _recording(document, None)
    state = _genesis(stored)
    assert MOVEMENT_MODULES_FIELD not in state
    moved = _walked(stored, state, 120)
    assert set(moved) == {"bat", "horse", "dragon", "shipped"}
    for name, steps_walked in moved.items():
        assert set(steps_walked) == {BUDGET}, name


class _Spy:
    """A walking step, counted, and the figures each call was handed after the route's graph."""

    def __init__(self, step) -> None:
        self.step = step
        self.figures: list[tuple[int, ...]] = []

    def __call__(self, route, nodes, edges, *figures):
        self.figures.append(figures)
        return self.step(route, nodes, edges, *figures)


def _spied(monkeypatch) -> dict[str, _Spy]:
    spies = {WALKING: _Spy(walking.traverse), WALKING_V2: _Spy(walking_v2.traverse_paced)}
    monkeypatch.setattr(steps, "STEPS", MappingProxyType({**steps.STEPS, **spies}))
    return spies


def test_a_society_walks_by_the_module_it_recorded_through_the_dispatcher(monkeypatch):
    document, _names = _creatures()
    spies = _spied(monkeypatch)
    state = _genesis(document)
    for _ in range(20):
        state, _events = _minute(state, document)
    assert not spies[WALKING].figures
    # Every call is handed the society's budget and then the walker's own pace.
    assert {figures[0] for figures in spies[WALKING_V2].figures} == {BUDGET}
    assert {figures[1] for figures in spies[WALKING_V2].figures} == {1000, *PACES.values()}
    assert {len(figures) for figures in spies[WALKING_V2].figures} == {2}

    spies = _spied(monkeypatch)
    for recorded in (None, [WALKING]):
        stored = _recording(document, recorded)
        state = _genesis(stored)
        for _ in range(20):
            state, _events = _minute(state, stored)
    assert not spies[WALKING_V2].figures
    assert set(spies[WALKING].figures) == {(BUDGET,)}


def _lived(person: dict[str, Any]) -> dict[str, Any]:
    """What a minute left of a person, without what names the input the minute read."""
    route = person["route"]
    return {
        "id": person["id"],
        "position_mm": person["position_mm"],
        "location": person["location"],
        "motion_path_mm": person["motion_path_mm"],
        "action": person["action"],
        "goal": person["goal"],
        "need_milli": person["need_milli"],
        "route": None if route is None else {**route, "input_sha256": None},
    }


@pytest.mark.parametrize("budget", [None, BUDGET])
def test_a_society_of_shipped_kinds_lives_the_same_hour_whether_or_not_it_records_it(budget):
    """Every shipped kind walks at the society's own pace, so the second walking moves a society
    with no made creature exactly as the first does: person for person and event for event, at
    the budget a new society records (None here) and at a small one."""
    recording = compose((WELL, KNIGHT))
    stored = _recording(recording, None)
    assert recording[MOVEMENT_MODULES_FIELD] == [WALKING_V2]
    one, other = _genesis(recording, budget=budget), _genesis(stored, budget=budget)
    walked = 0
    for _ in range(60):
        one, events = _minute(one, recording)
        other, others = _minute(other, stored)
        assert [_lived(p) for p in one["inhabitants"]] == [_lived(p) for p in other["inhabitants"]]
        assert [(e.kind, e.document["reason"], e.document["outcome"]) for e in events] == [
            (e.kind, e.document["reason"], e.document["outcome"]) for e in others
        ]
        walked += sum(len(p["motion_path_mm"]) > 1 for p in one["inhabitants"])
    assert walked > 0, "nobody walked: the hour compares nothing"


def test_a_table_without_the_second_walking_stops_a_society_that_recorded_it_by_name(monkeypatch):
    from exulanica.movement.registry import UnknownMovementModule

    document, _names = _creatures()
    state = _genesis(document)

    def without(name):
        if name == WALKING_V2:
            raise UnknownMovementModule(f"unknown movement module {name!r}")
        return built_module(name)

    monkeypatch.setattr(steps, "built_module", without)
    with pytest.raises(UnknownMovementModule, match="walking/v2"):
        _minute(state, document)


def test_the_table_s_walking_rows_are_the_two_this_file_names():
    assert [row.module for row in MODULES if "/walking/" in row.module] == [WALKING, WALKING_V2]


# -- a hands act is timed by what its walker spends -------------------------------------------


def _polyline_mm(path: list[list[int]]) -> int:
    return sum(math.isqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) for a, b in pairwise(path))


@pytest.mark.parametrize(
    ("recorded", "spends"),
    # A crocodile's hips stand 238 mm up: the whole root of 1,000,000 * 238 // 900 is 514, and
    # 60,000 mm at 514 in a thousand is 30,840 mm a minute. A society that records no movement
    # module walks it at the one budget.
    [([WALKING_V2], 30_840), (None, 60_000)],
)
def test_a_thing_walked_to_is_picked_up_at_the_moment_the_walker_s_own_pace_brings_it(
    recorded, spends
):
    sha256, form = _made("crocodile", hands=True)
    assert (
        pace_permille_of({"kinds": {sha256: form}}, {"source": "workspace", "sha256": sha256})
        == 514
    )
    document = _recording(
        compose(
            (asked.GATE, asked.FAR_SWORD, _placed("creature:1", sha256, 3_000, 3_000)),
            made_kinds={sha256: form},
        ),
        recorded,
    )
    state = _genesis(document, budget=None)
    assert state["movement_budget_mm_per_tick"] == 60_000
    being = next(p for p in state["inhabitants"] if p["placed_id"] == "creature:1")
    sword = next(t for t in state["things"] if t["placed_id"] == "sword")
    request = asked._ask(state, document, being, "pick_up", sword["id"])
    after, events, dispositions, _policies = asked._minute(state, document, [request])
    assert dispositions[0].disposition == "applied"
    [picked] = [e for e in events if e.kind == "picked_up"]
    walker = next(p for p in after["inhabitants"] if p["id"] == being["id"])
    walked = _polyline_mm(walker["motion_path_mm"])
    # It walked some metres and arrived within the minute, so the moment is neither end.
    assert 2_000 < walked < spends
    assert picked.document["at_ms"] == -(-walked * 60_000 // spends)
    assert 0 < picked.document["at_ms"] < 59_999
