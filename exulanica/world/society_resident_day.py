"""A recorded resident day for the society of things, using the living day's shared rules.

Only inputs explicitly recording day/v1 participate. Its retained context supplies destinations,
standing nodes and a pinned routine; the planner still owns every movement. Old inputs and states
have none of these fields and keep their existing execution. Production composition opts out.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, Protocol

from exulanica.abilities.registry import DAY
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import MINUTES_PER_DAY, RoutineModel
from exulanica.world.society_day import (
    admitting_destinations,
    day_options,
    rule_pick,
    seeded_span,
    stay_ticks,
)


class DayMinute(Protocol):
    state: dict[str, Any]
    seed: str
    document: dict[str, Any]

    def emit(
        self,
        kind: str,
        subject_id: str,
        reason: str,
        outcome: str,
        *,
        person: dict[str, Any],
        name: str,
        details: Mapping[str, Any],
    ) -> Any: ...


PROFILE = "exulanica.resident-day/v1"
_DESTINATION_KEYS = (
    "destination_id",
    "subject_id",
    "node_id",
    "indoors",
    "affordances",
    "duration_ticks",
    "use_class",
    "label",
    "staff_capacity",
    "visitor_capacity",
    "resident_capacity",
)


def runs_day(state: Mapping[str, Any]) -> bool:
    return DAY in state.get("modules", ())


def inside(person: Mapping[str, Any]) -> bool:
    """Physical interior state, introduced only by a recorded resident day."""
    return "day" in person and person.get("location", {}).get("indoors") is True


def same_space(one: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    a, b = inside(one), inside(other)
    return (not a and not b) or (
        a and b and one["location"]["destination_id"] == other["location"]["destination_id"]
    )


def routine_of(frame: Mapping[str, Any]) -> RoutineModel:
    from exulanica.world.society_living import routine_for

    model = routine_for({"routine": frame["routine"]})
    if model.binding() != frame["routine"]:
        raise ValueError("resident day routine digest mismatch")
    return model


def make_frame(
    place: Mapping[str, Any],
    routine: RoutineModel,
    people: Mapping[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    """Freeze a place's day facts against the composed walking graph, without a seed or store."""
    from exulanica.world.society_planner import _input_graph, _input_routes, spawn_nodes

    if (
        people["routine"] != routine.binding()
        or people["place"]["document_sha256"] != place["document_sha256"]
    ):
        raise ValueError("resident day and people must name the same place and routine")
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    places = sorted(
        (d for d in place["destinations"] if d["enabled"]), key=lambda d: d["destination_id"]
    )
    graph = _input_graph(document)
    doors = {d["node_id"] for d in places}
    free = set(spawn_nodes(document)) - doors
    destinations, shortages = [], []
    for source in places:
        dest = {key: deepcopy(source[key]) for key in _DESTINATION_KEYS}
        dest["standing_nodes"] = []
        if dest["node_id"] not in nodes:
            shortages.append(
                {
                    "destination_id": dest["destination_id"],
                    "reason": "door_unreachable",
                    "missing": 1,
                }
            )
        elif not dest["indoors"]:
            count = dest["staff_capacity"] + dest["visitor_capacity"]
            x, z = nodes[dest["node_id"]]
            # Own access node first; extra nodes never occupy another destination's door.
            reachable = _input_routes(document, dest["node_id"], graph[1])
            candidates = {dest["node_id"], *(free & reachable.keys())}
            chosen = sorted(
                candidates, key=lambda n: ((nodes[n][0] - x) ** 2 + (nodes[n][1] - z) ** 2, n)
            )[:count]
            dest["standing_nodes"] = chosen
            free.difference_update(chosen)
            if len(chosen) < count:
                shortages.append(
                    {
                        "destination_id": dest["destination_id"],
                        "reason": "outdoor_capacity_shortage",
                        "missing": count - len(chosen),
                    }
                )
        destinations.append(dest)
    frame = {
        "profile": PROFILE,
        "routine": routine.binding(),
        "place": dict(people["place"]),
        "start_minute_of_day": people["day"]["start_minute_of_day"],
        "destinations": destinations,
        "shortages": shortages,
    }
    frame["document_sha256"] = society_state_sha256(frame)
    validate_frame(frame, people=people, document=document)
    return frame


def validate_frame(
    frame: Any,
    *,
    people: Mapping[str, Any] | None = None,
    document: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(frame, dict) or set(frame) != {
        "profile",
        "routine",
        "place",
        "start_minute_of_day",
        "destinations",
        "shortages",
        "document_sha256",
    }:
        raise ValueError("invalid resident day fields")
    if frame["profile"] != PROFILE or frame["document_sha256"] != society_state_sha256(
        {k: v for k, v in frame.items() if k != "document_sha256"}
    ):
        raise ValueError("invalid resident day profile or digest")
    if (
        type(frame["start_minute_of_day"]) is not int
        or not 0 <= frame["start_minute_of_day"] < MINUTES_PER_DAY
    ):
        raise ValueError("invalid resident day start")
    routine = routine_of(frame)
    place = frame["place"]
    if (
        not isinstance(place, dict)
        or set(place) != {"place_id", "document_sha256"}
        or not all(isinstance(v, str) and v for v in place.values())
    ):
        raise ValueError("invalid resident day place binding")
    if not isinstance(frame["destinations"], list) or not isinstance(frame["shortages"], list):
        raise ValueError("invalid resident day destinations or shortages")
    if people is not None and (
        frame["routine"] != people["routine"]
        or frame["place"] != people["place"]
        or frame["start_minute_of_day"] != people["day"]["start_minute_of_day"]
    ):
        raise ValueError("resident day and people binding mismatch")
    ids, held = [], set()
    for dest in frame["destinations"]:
        if (
            not isinstance(dest, dict)
            or set(dest) != {*_DESTINATION_KEYS, "standing_nodes"}
            or type(dest["indoors"]) is not bool
        ):
            raise ValueError("invalid resident day destination")
        if not all(
            isinstance(dest[k], str) and dest[k]
            for k in ("destination_id", "subject_id", "node_id", "label")
        ):
            raise ValueError("invalid resident day destination identity")
        if dest["use_class"] is not None and dest["use_class"] not in routine.use_classes:
            raise ValueError("invalid resident day use class")
        affordances = dest["affordances"]
        if (
            not isinstance(affordances, list)
            or not all(isinstance(v, str) for v in affordances)
            or affordances != sorted(set(affordances))
            or not set(affordances) <= {a.affordance for a in routine.activities.values()}
        ):
            raise ValueError("invalid resident day affordances")
        duration = dest["duration_ticks"]
        if duration is not None and (
            type(duration) is not int or not 1 <= duration <= MINUTES_PER_DAY
        ):
            raise ValueError("invalid resident day duration")
        ids.append(dest["destination_id"])
        if any(
            type(dest[k]) is not int or dest[k] < 0
            for k in ("staff_capacity", "visitor_capacity", "resident_capacity")
        ):
            raise ValueError("invalid resident day capacity")
        nodes = dest["standing_nodes"]
        if (
            not isinstance(nodes, list)
            or not all(isinstance(n, str) and n for n in nodes)
            or len(nodes) != len(set(nodes))
            or len(nodes) > dest["staff_capacity"] + dest["visitor_capacity"]
            or held.intersection(nodes)
            or (dest["indoors"] and nodes)
        ):
            raise ValueError("resident day standing nodes must be exclusive and outdoors")
        held.update(nodes)
    for shortage in frame["shortages"]:
        if (
            not isinstance(shortage, dict)
            or set(shortage) != {"destination_id", "reason", "missing"}
            or shortage["destination_id"] not in ids
            or shortage["reason"] not in ("door_unreachable", "outdoor_capacity_shortage")
            or type(shortage["missing"]) is not int
            or shortage["missing"] < 1
        ):
            raise ValueError("invalid resident day shortage")
    if ids != sorted(set(ids)):
        raise ValueError("resident day destinations must be sorted and unique")
    if document is not None:
        nodes = {n["node_id"] for n in document["navigation"]["nodes"]}
        if not held <= nodes:
            raise ValueError("resident day standing node absent from navigation")
    if people is not None:
        known = set(ids)
        if any(p["destination_id"] not in known for p in people["premises"]):
            raise ValueError("resident day omits a resident's premises")


def initialize(state: dict[str, Any], document: Mapping[str, Any], seed: str) -> None:
    if not runs_day(state):
        return
    frame = deepcopy(document["day"])
    state["day_context"] = frame
    start = frame["start_minute_of_day"]
    state["clock"] = {"start_minute_of_day": start, "minute_of_day": start, "day": 0}
    subjects = {d["subject_id"]: d for d in frame["destinations"]}
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    routine = routine_of(frame)
    for person in state["inhabitants"]:
        resident = person.get("resident")
        if resident is None:
            continue
        premises = state["people"]["premises"]
        home = subjects[premises[resident["home"]["premises"]]["subject_id"]]
        if not home["indoors"] or home["node_id"] not in nodes:
            raise ValueError("resident day requires a reachable indoor home")
        job = resident["job"]
        person["day_home"] = home["destination_id"]
        person["day_work"] = (
            None
            if job is None
            else {
                "destination_id": subjects[premises[job["premises"]]["subject_id"]][
                    "destination_id"
                ],
                "shift_start_minute": job["shift"]["start_minute"],
                "shift_minutes": job["shift"]["minutes"],
                "position": job["position"],
            }
        )
        person["needs"] = {
            key: seeded_span(
                seed, f"need:{key}", person["ordinal"], need.initial_minimum, need.initial_maximum
            )
            for key, need in sorted(routine.needs.items())
        }
        person["last_completed"] = None
        person["last_shift_day"] = None
        person["day"] = {
            "activity": "stay_home",
            "destination_id": home["destination_id"],
            "ends_at": seeded_span(seed, "start_at_home", person["ordinal"], 1, 45),
            "shift_day": None,
        }
        person.update(
            position_mm=list(nodes[home["node_id"]]),
            motion_path_mm=[list(nodes[home["node_id"]])],
            location={
                "node_id": home["node_id"],
                "edge": None,
                "indoors": True,
                "destination_id": home["destination_id"],
            },
            goal=None,
            target=None,
            route=None,
        )
        _action(person, "stay_home", person["day"]["ends_at"], "starting_at_home")


def _action(
    person: dict[str, Any], activity: str, remaining: int, reason: str, status: str = "active"
) -> None:
    person["action"] = {
        "kind": activity,
        "status": status,
        "target_id": None,
        "remaining_ticks": remaining,
        "reason": reason,
    }


def _finish(person: dict[str, Any], routine: RoutineModel) -> None:
    stay = person["day"]
    activity = routine.activities[stay["activity"]]
    if activity.need in person["needs"]:
        person["needs"][activity.need] = max(0, person["needs"][activity.need] - activity.relief)
    if activity.mode == "shift":
        person["last_shift_day"] = stay["shift_day"]
    person["last_completed"] = {"activity": activity.key, "destination_id": stay["destination_id"]}
    person["day"] = None
    person["goal"] = person["route"] = person["target"] = None
    _action(person, activity.key, 0, "duration_elapsed", "completed")


class _Place:
    def __init__(self, frame: Mapping[str, Any], document: dict[str, Any]) -> None:
        from exulanica.world.society_planner import _input_graph, _input_routes

        self.graph = _input_graph(document)
        self.document = document
        nodes = self.graph[0]
        self.destinations = {}
        self.spots = {}
        for row in frame["destinations"]:
            if row["node_id"] not in nodes:
                continue
            dest = dict(row)
            dest["spot_ids"] = [
                n for n in row["standing_nodes"][row["staff_capacity"] :] if n in nodes
            ]
            self.destinations[row["destination_id"]] = dest
            self.spots.update({n: {"node_id": n} for n in dest["spot_ids"]})
        from exulanica.world.society_planner import spawn_nodes

        reserved = {n for row in frame["destinations"] for n in row["standing_nodes"]}
        doors = {row["node_id"] for row in frame["destinations"]}
        self.plain_spots = tuple(sorted(set(spawn_nodes(document)) - reserved - doors))
        self.spots.update({n: {"node_id": n} for n in self.plain_spots})
        self._route = _input_routes

    def paths(self, start: str) -> dict[str, tuple[int, tuple[str, ...]]]:
        return self._route(self.document, start, self.graph[1]) if start in self.graph[0] else {}


def _person_view(person: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **person,
        "home": {"destination_id": person["day_home"]},
        "work": person["day_work"],
        "location": {
            **person["location"],
            "spot_id": person["location"]["node_id"] if not inside(person) else None,
            "destination_id": person["location"].get("destination_id"),
        },
    }


def prepare(
    state: dict[str, Any],
    document: dict[str, Any],
    seed: str,
    policies: Mapping[str, dict[str, Any]] | None,
    emit: Callable[..., Any],
) -> Mapping[str, dict[str, Any]] | None:
    """Advance the recorded clock/needs, finish stays, and fill only otherwise undecided goals."""
    if not runs_day(state):
        return policies
    frame = state["day_context"]
    routine = routine_of(frame)
    absolute = frame["start_minute_of_day"] + state["tick"]
    minute, day = absolute % MINUTES_PER_DAY, absolute // MINUTES_PER_DAY
    state["clock"] = {
        "start_minute_of_day": frame["start_minute_of_day"],
        "minute_of_day": minute,
        "day": day,
    }
    result = dict(policies or {})
    available = (
        document["availability"] == "available" and not document["navigation"]["unavailable_reason"]
    )
    for person in state["inhabitants"]:
        if "day" not in person:
            continue
        for key, need in routine.needs.items():
            person["needs"][key] = min(1000, person["needs"][key] + need.growth)
        if person["day"] and state["tick"] >= person["day"]["ends_at"]:
            _finish(person, routine)
            emit(person, "action_completed", "duration_elapsed", "day_stay_completed", document)
    if not available:
        return result
    place = _Place(frame, document)
    occupied, visitors = {}, {}
    for p in state["inhabitants"]:
        if not inside(p) and p["location"]["edge"] is None:
            occupied[p["location"]["node_id"]] = p["id"]
        stay = p.get("day")
        visiting = stay or (p.get("goal") or {}).get("day")
        if visiting and routine.activities[visiting["activity"]].setting not in (
            "home",
            "work",
            "standing",
        ):
            dest_id = visiting["destination_id"]
            visitors[dest_id] = visitors.get(dest_id, 0) + 1
    staffed = frozenset(
        p["day"]["destination_id"]
        for p in state["inhabitants"]
        if p.get("day") and routine.activities[p["day"]["activity"]].mode == "shift"
    )
    admitting = admitting_destinations(
        place, routine, minute, staffed if routine.keeps_hours else None
    )
    for person in state["inhabitants"]:
        if "day" not in person:
            continue
        stay = person["day"]
        if stay and not inside(person):
            destination = place.destinations.get(stay["destination_id"])
            if routine.activities[stay["activity"]].setting != "standing" and (
                destination is None
                or person["location"]["node_id"] not in destination["standing_nodes"]
            ):
                person["day"] = stay = None
                person["goal"] = person["route"] = person["target"] = None
                _action(person, "idle", 0, "day_place_invalidated", "completed")
        policy = result.get(person["id"])
        if policy and not policy.get("day_keep"):
            person["day"] = None
            person["goal"] = person["route"] = person["target"] = None
            _action(person, "idle", 0, "called_away", "completed")
            continue
        if (
            stay
            or policy
            or (
                person["goal"] is not None
                and person["action"]["status"] not in ("completed", "blocked")
            )
        ):
            continue
        view = _person_view(person)
        choice = rule_pick(
            day_options(
                view,
                place,
                routine,
                seed,
                state["tick"],
                minute,
                day,
                occupied,
                visitors,
                admitting,
            ),
            person=view,
            routine=routine,
            seed=seed,
            tick=state["tick"],
        )
        if isinstance(choice, str):
            result[person["id"]] = {
                "allowed_target_ids": [],
                "chosen_by": "day",
                "wait": True,
                "day_wait": choice,
            }
            continue
        activity, pick, _because = choice
        dest = place.destinations.get(pick["destination_id"])
        node = pick["node_id"]
        if dest is None:
            occupied[node] = person["id"]
        elif not dest["indoors"]:
            choices = dest["standing_nodes"]
            if activity.setting == "work":
                position = person["day_work"]["position"]
                choices = choices[position : position + 1]
            else:
                choices = choices[dest["staff_capacity"] :]
            paths = place.paths(
                view["location"]["node_id"]
                if view["location"]["edge"] is None
                else view["location"]["edge"]["to_node_id"]
            )
            choices = [
                n
                for n in choices
                if n in paths and (n not in occupied or occupied[n] == person["id"])
            ]
            if not choices:
                continue
            node = choices[0]
            occupied[node] = person["id"]
        elif activity.setting not in ("home", "work"):
            visitors[dest["destination_id"]] = visitors.get(dest["destination_id"], 0) + 1
        result[person["id"]] = {
            "allowed_target_ids": [],
            "chosen_by": "day",
            "place_node_id": node,
            "day": {
                "activity": activity.key,
                "destination_id": pick["destination_id"],
                "shift_day": pick.get("shift_day"),
                "reason": "shift_due" if activity.mode == "shift" else "most_pressing_need",
                "indoors": dest is not None and dest["indoors"],
            },
        }
    return result


def stays_inside(person: Mapping[str, Any], policy: Mapping[str, Any] | None) -> bool:
    return (
        "day" in person
        and person.get("day") is not None
        and (policy is None or bool(policy.get("day_keep")))
    )


def arrive(minute: DayMinute) -> None:
    state = minute.state
    if not runs_day(state):
        return
    routine = routine_of(state["day_context"])
    destinations = {d["destination_id"]: d for d in state["day_context"]["destinations"]}
    current_nodes = {n["node_id"] for n in minute.document["navigation"]["nodes"]}
    available = (
        minute.document["availability"] == "available"
        and not minute.document["navigation"]["unavailable_reason"]
    )
    for person in state["inhabitants"]:
        if "day" not in person:
            continue
        person["location"].setdefault("indoors", False)
        person["location"].setdefault("destination_id", None)
        stay = person["day"]
        if stay:
            remaining = max(0, stay["ends_at"] - state["tick"])
            if available and person["location"]["node_id"] in current_nodes:
                _action(person, stay["activity"], remaining, "staying")
            else:
                person["action"]["remaining_ticks"] = remaining
            continue
        goal = person.get("goal") or {}
        held = goal.get("day")
        if held is None or person["action"]["reason"] != "day_arrived":
            continue
        dest = destinations.get(held["destination_id"])
        activity = routine.activities[held["activity"]]
        duration = stay_ticks(
            _person_view(person),
            activity,
            dest,
            minute.seed,
            state["tick"],
            state["day_context"]["start_minute_of_day"] + state["tick"],
            held["shift_day"],
        )
        person["day"] = {
            "activity": activity.key,
            "destination_id": held["destination_id"],
            "ends_at": state["tick"] + duration,
            "shift_day": held["shift_day"],
        }
        indoors = dest is not None and dest["indoors"]
        person["location"].update(indoors=indoors, destination_id=held["destination_id"])
        person["goal"] = person["target"] = person["route"] = None
        _action(person, activity.key, duration, "arrived")
        minute.emit(
            "route_progressed",
            person["id"],
            "arrived",
            "day_stay_started",
            person=person,
            name=person["display_name"],
            details={"day": dict(person["day"]), "indoors": indoors},
        )


def validate_state(state: Mapping[str, Any]) -> None:
    active = runs_day(state)
    if ("day_context" in state) != active or ("clock" in state) != active:
        raise ValueError("resident day state must match its recorded module")
    if not active:
        if any("day" in p or "day_home" in p for p in state["inhabitants"]):
            raise ValueError("resident day fields without recorded module")
        return
    validate_frame(state["day_context"])
    routine = routine_of(state["day_context"])
    start = state["day_context"]["start_minute_of_day"]
    absolute = start + state["tick"]
    if state["clock"] != {
        "start_minute_of_day": start,
        "minute_of_day": absolute % MINUTES_PER_DAY,
        "day": absolute // MINUTES_PER_DAY,
    }:
        raise ValueError("resident day clock disagrees with its tick")
    known = {d["destination_id"]: d for d in state["day_context"]["destinations"]}
    for p in state["inhabitants"]:
        if ("day" in p) != ("resident" in p):
            raise ValueError("only residents carry a day")
        if "day" not in p:
            continue
        if (
            p["day_home"] not in known
            or not known[p["day_home"]]["indoors"]
            or set(p["needs"]) != set(routine.needs)
            or any(type(v) is not int or not 0 <= v <= 1000 for v in p["needs"].values())
        ):
            raise ValueError("invalid resident day needs or home")
        loc = p["location"]
        if type(loc.get("indoors")) is not bool or (
            loc["indoors"]
            and (
                loc.get("destination_id") not in known
                or not known[loc["destination_id"]]["indoors"]
                or loc["edge"] is not None
                or loc["node_id"] != known[loc["destination_id"]]["node_id"]
            )
        ):
            raise ValueError("resident day location must state its physical interior")
        stay = p["day"]
        if stay is not None and (
            set(stay) != {"activity", "destination_id", "ends_at", "shift_day"}
            or stay["activity"] not in routine.activities
            or (
                stay["destination_id"] not in known
                and routine.activities[stay["activity"]].setting != "standing"
            )
            or type(stay["ends_at"]) is not int
            or stay["ends_at"] < state["tick"]
        ):
            raise ValueError("invalid resident day stay")
