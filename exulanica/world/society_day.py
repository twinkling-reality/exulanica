"""The rule of a day: what a person with needs, a home and perhaps a job does next.

Every need grows each minute; a shift that is due outranks every need; a pressing need narrows what
is offered to the pressing activities alone; a destination of a use class that keeps hours admits
visitors only while it is open, and a workplace only while one of its workers is at work there; a
destination admits only while it has room; and a stay lasts to the end of its shift, the
destination's own fixed length, or a seeded draw within its activity's range.

The functions here read a person, a place, a routine, a seed and the minute, and nothing else: no
walk, no reservation book, no engine's state shape beyond the person's own fields. A place is
anything that answers :class:`DayPlace`. The living society
(:mod:`~exulanica.world.society_living`) runs its minute by them.

Pure: no connection, no store, no clock. Every draw is the seeded SHA-256 function in
:mod:`exulanica.world.society`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from exulanica.world.society import _number
from exulanica.world.society_catalogs import MINUTES_PER_DAY, Activity, RoutineModel

__all__ = [
    "DayPlace",
    "OptionRow",
    "activity_targets",
    "admitting_destinations",
    "day_options",
    "preference_weight",
    "rule_pick",
    "seeded_span",
    "shift_due",
    "shortage_reason",
    "staffed_workplaces",
    "start_node",
    "stay_ticks",
]

#: One row of the closed answer set: urgency, activity key, the activity, the pick, and why.
OptionRow = tuple[int, str, "Activity", dict, str]


class DayPlace(Protocol):
    """What the rule reads of a place: its enabled destinations and its standing spots by id, the
    spots that belong to no destination, and the routes from a node (cost in millimetres and the
    nodes of the way, by the node reached)."""

    destinations: Mapping[str, dict[str, Any]]
    spots: Mapping[str, dict[str, Any]]
    plain_spots: Sequence[str]

    def paths(self, start: str) -> dict[str, tuple[int, tuple[str, ...]]]: ...


def seeded_span(seed: str, domain: str, ordinal: int, low: int, high: int) -> int:
    return low + _number(seed, domain, ordinal) % (high - low + 1)


def preference_weight(seed: str, routine: RoutineModel, activity: Activity, ordinal: int) -> int:
    spread = activity.weight * routine.policy["preference_spread_milli"] // 2000
    return activity.weight + seeded_span(
        seed, f"preference:{activity.key}", ordinal, -spread, spread
    )


def shift_due(person: dict, minute: int, day: int, lead: int) -> tuple[bool, int, int]:
    """Whether the shift is due now, the day it belongs to, and minutes until it ends."""
    work = person["work"]
    start, length = work["shift_start_minute"], work["shift_minutes"]
    for shift_day in (day, day - 1):
        begin = shift_day * MINUTES_PER_DAY + start
        now = day * MINUTES_PER_DAY + minute
        if begin - lead <= now < begin + length and person["last_shift_day"] != shift_day:
            return True, shift_day, begin + length - now
    return False, day, 0


def start_node(person: dict) -> str:
    loc = person["location"]
    return loc["node_id"] if loc["edge"] is None else loc["edge"]["to_node_id"]


def day_options(
    person: dict,
    place: DayPlace,
    routine: RoutineModel,
    seed: str,
    tick: int,
    minute: int,
    day: int,
    spot_holder: dict,
    visitors: dict,
    admitting: frozenset[str] | None = None,
) -> list[OptionRow]:
    """Every activity this inhabitant can act on now, the pressing ones alone when any press.

    This is the closed answer set, and it is a function of its own so that something other than
    the rule in :func:`rule_pick` can be offered the same rows. A set assembled separately
    for a model would be a second source of truth for what was possible, which is the failure
    this project names most.

    A pressing activity with nowhere to go is stepped over here, and :func:`activity_targets` says
    why. It cannot be said in v4: a goal's ``because`` and a blocked action's reason are both
    canonical state, the living replay recomputes every stored transition digest from genesis,
    and the pinned digests in ``tests/test_society_living.py`` carry the rule in one line, that
    a change there is a new profile. Measured either side: consuming the reason moves the
    tick-30 digest and leaves behaviour identical over 240 ticks, while returning it moves
    nothing at all. So it is returned and unused. v4 does not consume it.
    The living genesis refuses that unwalkable-work society at creation instead.

    **The shortage is not handed to the seam either, and for the same reason.** Putting it into a
    :class:`~exulanica.world.society_choice.ChoiceQuestion` would let a model answer on grounds
    v4's own record cannot carry, and a decision that cannot be reproduced from the record is the
    thing the seam exists to avoid. The shortage stays out of the question.
    """
    start = start_node(person)
    paths = place.paths(start)
    loc = person["location"]
    here_spot = loc["spot_id"] if loc["edge"] is None else None
    here_dest = loc["destination_id"] if loc["edge"] is None else None
    last = person["last_completed"] or {}
    pressing = []
    fallback = []
    for key in sorted(routine.activities):
        activity = routine.activities[key]
        if activity.mode == "shift":
            if person["work"] is None:
                continue
            due, shift_day, _ = shift_due(
                person, minute, day, routine.policy["commute_lead_minutes"]
            )
            if not due:
                continue
            urgency, is_pressing, because = activity.weight, True, "the shift is due"
        else:
            if activity.need not in person["needs"] or not activity.open_at(minute):
                continue
            need = routine.needs[activity.need]
            value = person["needs"][activity.need]
            urgency = value * preference_weight(seed, routine, activity, person["ordinal"]) // 1000
            is_pressing = value >= need.threshold
            because = f"{need.label} at {value} of 1000"
            if not is_pressing:
                because = f"nothing pressing; {because}"
        # The shortage is deliberately discarded: v4 cannot record it (see this function's
        # docstring).
        targets, _shortage = activity_targets(
            person,
            place,
            activity,
            paths,
            here_spot,
            here_dest,
            spot_holder,
            visitors,
            admitting,
        )
        if not targets:
            continue
        if activity.mode == "shift":
            targets = [{**t, "shift_day": shift_day} for t in targets]
        if activity.setting == "standing":
            pick = targets[_number(seed, f"stroll:{tick}", person["ordinal"]) % len(targets)]
        else:
            pick = min(
                targets,
                key=lambda t: (
                    t["destination_id"] == last.get("destination_id"),
                    t["load_milli"],
                    t["cost_mm"],
                    t["destination_id"] or "",
                    t["spot_id"] or "",
                ),
            )
        row = (urgency, key, activity, pick, because)
        (pressing if is_pressing else fallback).append(row)
    return pressing or fallback


def rule_pick(pool: list[OptionRow]) -> tuple[Activity, dict, str] | str:
    """The rule: the most pressing row, or the reason nothing was possible. Never randomised."""
    if not pool:
        return "no_reachable_place_with_room"
    _, _, activity, pick, because = max(pool, key=lambda row: (row[0], row[1]))
    return activity, pick, because


def staffed_workplaces(state: dict[str, Any], routine: RoutineModel) -> frozenset[str] | None:
    """The workplaces one of whose workers is at work there, or None under a routine whose use
    classes keep no hours, where nobody asks."""
    if not routine.keeps_hours:
        return None
    return frozenset(
        p["action"]["destination_id"]
        for p in state["inhabitants"]
        if p["action"]["kind"] in routine.activities
        and routine.activities[p["action"]["kind"]].mode == "shift"
        and p["action"]["status"] == "active"
    )


def admitting_destinations(
    place: DayPlace, routine: RoutineModel, minute: int, staffed: frozenset[str] | None
) -> frozenset[str] | None:
    """The destinations that admit a visitor this minute, or None where every one does.

    Under a routine whose use classes keep hours (a town's), a destination of such a use class
    admits visitors inside its opening hours, and a workplace only while one of its workers is at
    work there; a destination of no use class, or of one that states no hours, admits them as
    always, by its activity's own window alone.
    """
    if staffed is None:
        return None
    admitting = set()
    for dest_id, dest in place.destinations.items():
        use = routine.use_classes.get(dest["use_class"]) if dest["use_class"] else None
        if (
            use is None
            or use.opening is None
            or (use.open_at(minute) and (not use.staff_per_unit or dest_id in staffed))
        ):
            admitting.add(dest_id)
    return frozenset(admitting)


def activity_targets(
    person: dict,
    place: DayPlace,
    activity: Activity,
    paths: dict,
    here_spot: str | None,
    here_dest: str | None,
    spot_holder: dict,
    visitors: dict,
    admitting: frozenset[str] | None = None,
) -> tuple[list[dict], str | None]:
    """Every target this activity could take now, and when there are none, which shortage it is.

    Nothing here offers it, the places that do are full, and no route reaches them are three
    findings with three different fixes, and an empty list reports all three as one. The reason
    is counted from the same pass that builds the rows, so it cannot describe a different walk
    over the place than the one that found nothing.
    """
    rows = []

    def route_cost(node_id: str) -> int | None:
        found = paths.get(node_id)
        return None if found is None else found[0]

    if activity.setting in ("home", "work"):
        held = person[activity.setting]
        if held is None:
            return [], f"this person has no {activity.setting}"
        dest = place.destinations.get(held["destination_id"])
        if dest is None:
            return [], f"the place no longer holds this person's {activity.setting}"
        cost = route_cost(dest["node_id"])
        if cost is None:
            return [], f"no route reaches this person's {activity.setting}"
        return [
            {
                "destination_id": dest["destination_id"],
                "spot_id": None,
                "node_id": dest["node_id"],
                "kind": activity.setting,
                "cost_mm": cost,
                "load_milli": 0,
            }
        ], None
    if activity.setting == "standing":
        pool = place.plain_spots or sorted(place.spots)
        taken_spots = out_of_reach = already_here = 0
        for spot_id in pool:
            if spot_id == here_spot:
                already_here += 1
                continue
            if spot_id in spot_holder:
                taken_spots += 1
                continue
            spot = place.spots[spot_id]
            cost = route_cost(spot["node_id"])
            if cost is None:
                out_of_reach += 1
                continue
            rows.append(
                {
                    "destination_id": None,
                    "spot_id": spot_id,
                    "node_id": spot["node_id"],
                    "kind": "spot",
                    "cost_mm": cost,
                    "load_milli": 0,
                }
            )
        return rows, None if rows else shortage_reason(
            "standing spot", out_of_reach, taken_spots, already_here
        )
    offered = out_of_reach = no_room = already_here = closed = 0
    for dest_id, dest in sorted(place.destinations.items()):
        if activity.affordance not in dest["affordances"]:
            continue
        offered += 1
        if admitting is not None and dest_id not in admitting:
            closed += 1
            continue
        # Somewhere this person is already standing, and somewhere with no room, are both places
        # that offer this: only the count of destinations OFFERING it may decide whether the
        # place publishes any. A person in the only cafe wanting a meal is the first case, and
        # reporting that as "nowhere here offers eating" is the collapse this function exists to
        # stop, one level down from the empty list itself.
        if dest_id == here_dest:
            already_here += 1
            continue
        if not dest["visitor_capacity"]:
            no_room += 1
            continue
        cost = route_cost(dest["node_id"])
        if cost is None:
            out_of_reach += 1
            continue
        if dest["indoors"]:
            taken = visitors.get(dest_id, 0)
            if taken >= dest["visitor_capacity"]:
                no_room += 1
                continue
            rows.append(
                {
                    "destination_id": dest_id,
                    "spot_id": None,
                    "node_id": dest["node_id"],
                    "kind": "visitor",
                    "cost_mm": cost,
                    "load_milli": taken * 1000 // dest["visitor_capacity"],
                }
            )
            continue
        free = [s for s in dest["spot_ids"] if s not in spot_holder and s != here_spot]
        if not free:
            no_room += 1
            continue
        taken = sum(1 for s in dest["spot_ids"] if s in spot_holder)
        rows.append(
            {
                "destination_id": dest_id,
                "spot_id": free[0],
                "node_id": dest["node_id"],
                "kind": "spot",
                "cost_mm": cost,
                "load_milli": taken * 1000 // len(dest["spot_ids"]),
            }
        )
    if rows:
        return rows, None
    if not offered:
        return [], f"this place publishes nowhere that offers {activity.affordance}"
    return [], shortage_reason(
        f"place that offers {activity.affordance}", out_of_reach, no_room, already_here, closed
    )


def shortage_reason(
    what: str, out_of_reach: int, no_room: int, already_here: int = 0, closed: int = 0
) -> str:
    """Why no target of this kind is open, naming every cause that got this far.

    Every non-zero count is stated, because a person kept indoors by a full street, one kept
    indoors by a cut in the walking graph, and one standing in the only place that would have
    served want three different things done, and a message naming only the largest cause sends
    the reader to whichever happened to win.
    """
    causes = []
    if out_of_reach:
        causes.append(f"no route reaches {out_of_reach}")
    if no_room:
        causes.append(f"{no_room} {'has' if no_room == 1 else 'have'} no room")
    if already_here:
        causes.append(f"this person is already at {already_here}")
    if closed:
        causes.append(f"{closed} {'is' if closed == 1 else 'are'} closed")
    if not causes:
        return f"this place publishes no {what}"
    return f"no {what} is open to this person: {', '.join(causes)}"


def stay_ticks(
    person: dict,
    activity: Activity,
    dest: Mapping[str, Any] | None,
    seed: str,
    tick: int,
    absolute: int,
    shift_day: int | None,
) -> int:
    """How many minutes a stay that begins now lasts: a shift to its own end, a destination's
    fixed length where it states one, else a seeded draw within the activity's range.
    ``absolute`` is the minute since the society's first day began and ``shift_day`` the day the
    shift belongs to."""
    if activity.mode == "shift":
        work = person["work"]
        assert shift_day is not None
        begin = shift_day * MINUTES_PER_DAY + work["shift_start_minute"]
        return max(1, begin + work["shift_minutes"] - absolute)
    if dest is not None and dest["duration_ticks"] is not None:
        return dest["duration_ticks"]
    return seeded_span(
        seed,
        f"duration:{activity.key}:{tick}",
        person["ordinal"],
        activity.duration_minimum,
        activity.duration_maximum,
    )
