"""A new town's people spend free time when no need presses, and choose a place by how far and how
full it is.

Measured on generated towns over a simulated day (14 October 2026): under the earlier town routine,
with no need pressing the rule took whichever activity scored highest, so people went out to eat
with a meal need of about 40 of 1000 (some eight meals out a day each) and shopped and sat on
benches with nothing pressing; and a destination was ordered emptiest first, so everybody choosing
in one minute walked across town to whichever place had just opened. The routine a new town is
made under (``TOWN_ROUTINE_VERSIONS``) offers only free time when nothing presses, draws among it by
each person's own weights, and orders a destination by its walking cost grown by how full it is.
A town made under the earlier routine keeps it.

Pure: every town is composed as the runtime composes it (``tests/living_town_support.py``).
"""

from __future__ import annotations

import copy
import functools
import uuid
from collections import Counter
from typing import Any

import pytest
from exulanica.world import society_catalogs
from exulanica.world.society_catalogs import MINUTES_PER_DAY
from exulanica.world.society_day import (
    activity_targets,
    admitting_destinations,
    day_options,
    preference_weight,
    rule_pick,
    staffed_workplaces,
)
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    advance_living_society,
    initial_living_society,
    input_routine,
    living_places,
    next_minute_options,
)

from living_town_support import SEED, town_input

SOCIETY = uuid.UUID("5a5a5a5a-0000-4000-8000-0000000000f7")
#: Minutes from the town's 06:00 start to noon, when its cafes, shops and bookshops are open.
TO_NOON = 360
#: What a person does with free time in a town: at home, a walk, a visit.
FREE_TIME = frozenset({"stay_home", "stroll", "visit"})


@functools.cache
def _noon(versions: tuple[tuple[str, int], ...]) -> dict[str, Any]:
    """A small town lived from genesis to noon under the town routine ``versions``: the place, the
    routine, the state at noon and every event of the morning."""
    patch = pytest.MonkeyPatch()
    patch.setattr(society_catalogs, "TOWN_ROUTINE_VERSIONS", dict(versions))
    try:
        document = town_input()
    finally:
        patch.undo()
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        SOCIETY,
        SEED,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    events = []
    for _ in range(TO_NOON):
        state, minute = advance_living_society(state, SEED, [place], routine)
        events.extend(event.document for event in minute)
    return {"routine": routine, "place": place, "state": state, "events": events}


def _now() -> dict[str, Any]:
    return _noon(tuple(sorted(society_catalogs.TOWN_ROUTINE_VERSIONS.items())))


def _before() -> dict[str, Any]:
    return _noon(tuple(sorted(society_catalogs.TOWN_ROUTINE_VERSIONS_BEFORE_FREE_TIME.items())))


def _free(town: dict[str, Any]) -> set[str]:
    return {key for key, activity in town["routine"].activities.items() if activity.free_time}


def _idle_resident(town: dict[str, Any], needs: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """The noon state with one resident who keeps no job free to choose, every need at ``needs``."""
    state = copy.deepcopy(town["state"])
    person = next(
        p
        for p in state["inhabitants"]
        if p["work"] is None and p["location"]["edge"] is None and p["location"]["indoors"]
    )
    person["needs"] = dict.fromkeys(person["needs"], needs)
    person["action"] = {**person["action"], "status": "completed"}
    person["route"] = None
    person["last_completed"] = None
    return state, person


def test_with_nothing_pressing_a_new_town_offers_only_free_time():
    """Every need below its threshold: the answer set holds only free time (at home, a walk, a
    visit), never a meal, shopping or a rest nobody needs. The same resident under the earlier
    routine is offered those, which is what this changes."""
    offered = {}
    for name, town in (("now", _now), ("before", _before)):
        state, person = _idle_resident(town(), needs=100)
        offered[name] = {
            key
            for key, *_ in next_minute_options(
                state, SEED, town()["place"], town()["routine"], person["id"]
            )
        }
        if name == "now":
            assert offered["now"] and offered["now"] <= FREE_TIME, offered["now"]
    assert offered["before"] - FREE_TIME, offered["before"]
    assert _free(_now()) == FREE_TIME
    assert _free(_before()) == set()


def test_with_nothing_pressing_free_time_is_drawn_by_the_person_s_own_weights():
    """The rule draws among the free-time rows in proportion to the person's own weight for each
    (the catalogued weight with their seeded spread), from the seed, the minute and the person:
    the same draw replays, and over many minutes each row is taken about as often as its weight
    says, rather than the top row every time."""
    town = _now()
    routine, place = town["routine"], town["place"]
    state, person = _idle_resident(town, needs=100)
    spot_holder: dict[str, str] = {}
    visitors: dict[str, int] = {}
    for other in state["inhabitants"]:
        held = other["reservation"]
        if held and held["kind"] == "spot":
            spot_holder[held["id"]] = other["id"]
        elif held and held["kind"] == "visitor":
            visitors[held["id"]] = visitors.get(held["id"], 0) + 1
    minute = (routine.policy["start_minute_of_day"] + TO_NOON) % MINUTES_PER_DAY
    admitting = admitting_destinations(place, routine, minute, staffed_workplaces(state, routine))
    taken: Counter = Counter()
    draws = 600
    rows = None
    for tick in range(TO_NOON + 1, TO_NOON + 1 + draws):
        pool = day_options(
            person, place, routine, SEED, tick, minute, 0, spot_holder, visitors, admitting
        )
        rows = {key: activity for _, key, activity, _, _ in pool}
        chosen = rule_pick(pool, person=person, routine=routine, seed=SEED, tick=tick)
        again = rule_pick(pool, person=person, routine=routine, seed=SEED, tick=tick)
        assert not isinstance(chosen, str) and chosen == again
        taken[chosen[0].key] += 1
    assert rows is not None and len(rows) >= 2
    weights = {
        key: preference_weight(SEED, routine, activity, person["ordinal"])
        for key, activity in rows.items()
    }
    total = sum(weights.values())
    for key, weight in weights.items():
        assert abs(taken[key] / draws - weight / total) < 0.07, (key, taken, weights)


def test_a_pressing_need_is_still_taken_by_the_rule_alone():
    """With a need above its threshold, the most pressing row is taken as before: no draw."""
    town = _now()
    state, person = _idle_resident(town, needs=100)
    person["needs"]["meal"] = 950
    pool = day_options(
        person,
        town["place"],
        town["routine"],
        SEED,
        TO_NOON + 1,
        (town["routine"].policy["start_minute_of_day"] + TO_NOON) % MINUTES_PER_DAY,
        0,
        {},
        {},
        admitting_destinations(
            town["place"],
            town["routine"],
            (town["routine"].policy["start_minute_of_day"] + TO_NOON) % MINUTES_PER_DAY,
            staffed_workplaces(state, town["routine"]),
        ),
    )
    assert pool and all(row[2].need == "meal" for row in pool)
    top = max(pool, key=lambda row: (row[0], row[1]))
    chosen = rule_pick(pool, person=person, routine=town["routine"], seed=SEED, tick=TO_NOON + 1)
    assert chosen == (top[2], top[3], top[4])


def test_a_destination_is_ordered_by_its_walking_cost_grown_by_how_full_it_is():
    """A nearer place half full counts as half as far again: chosen over an empty place more than
    one and a half times as far, and passed over for an empty one nearer than that. The earlier
    routine took the empty place first wherever it was."""
    for name, made in (("now", _now), ("before", _before)):
        town = made()
        routine, place = town["routine"], town["place"]
        state, person = _idle_resident(town, needs=100)
        person["needs"]["meal"] = 950
        activity = routine.activities["eat_out"]
        minute = (routine.policy["start_minute_of_day"] + TO_NOON) % MINUTES_PER_DAY
        admitting = admitting_destinations(
            place, routine, minute, staffed_workplaces(state, routine)
        )
        paths = place.paths(person["location"]["node_id"])
        targets, _ = activity_targets(person, place, activity, paths, None, None, {}, {}, admitting)
        ordered = sorted(targets, key=lambda t: (t["cost_mm"], t["destination_id"]))
        assert len(ordered) >= 2, "the town has at least two places to eat open at noon"
        near = ordered[0]
        far = next(t for t in ordered if t["cost_mm"] * 2 > near["cost_mm"] * 3)
        capacity = place.destinations[near["destination_id"]]["visitor_capacity"]
        # Every other place to eat is full, so only the near one (half full) and the far one
        # (empty) have room.
        visitors = {
            t["destination_id"]: place.destinations[t["destination_id"]]["visitor_capacity"]
            for t in ordered
            if t["destination_id"] not in (near["destination_id"], far["destination_id"])
        }
        visitors[near["destination_id"]] = capacity // 2
        pool = day_options(
            person, place, routine, SEED, TO_NOON + 1, minute, 0, {}, visitors, admitting
        )
        [eat_out] = [row for row in pool if row[1] == "eat_out"]
        picked = eat_out[3]["destination_id"]
        if name == "now":
            grown = near["cost_mm"] * (1000 + (capacity // 2) * 1000 // capacity) // 1000
            assert grown < far["cost_mm"]
            assert picked == near["destination_id"]
        else:
            assert picked == far["destination_id"]


def test_over_a_morning_nobody_in_a_new_town_goes_out_for_a_need_that_does_not_press():
    """Every goal the rule chose between 06:00 and noon is free time, a due shift, or an activity
    whose need was at or above its threshold when it was chosen. The earlier routine's morning
    holds goals that are none of those, which is what this changes."""
    for name, made in (("now", _now), ("before", _before)):
        town = made()
        routine = town["routine"]
        unneeded = [
            event
            for event in town["events"]
            if event["outcome"] == "goal_selected"
            and event["goal"]["need"] is not None
            and event["goal"]["activity"] not in FREE_TIME
            and event["needs"][event["goal"]["need"]]
            < routine.needs[event["goal"]["need"]].threshold
        ]
        chosen = [event for event in town["events"] if event["outcome"] == "goal_selected"]
        assert chosen
        if name == "now":
            assert unneeded == [], [
                (e["goal"]["activity"], e["goal"]["because"]) for e in unneeded[:5]
            ]
            assert {event["goal"]["activity"] for event in chosen} & FREE_TIME
        else:
            assert len(unneeded) > len(chosen) // 4
