"""The living society, profile ``exulanica-society/v4``: routines over a place, with occupancy.

V4 is a successor to the v2 purposeful policy, never a change to it. Each inhabitant carries the
needs its place can relieve. Every simulated minute those needs grow at their catalogued rates,
and an inhabitant with nothing in progress chooses the activity whose weighted need is most
pressing among those it can actually reach and fit into. It then walks the place's navigation
graph at its own speed and stays for the activity's duration. Every standing spot holds one
person, every indoor destination holds its catalogued number of visitors, and every home and
workplace position belongs to one inhabitant, so no rule can pile the population onto one point.

Three properties keep the population from settling into one state:

- a finished activity lowers its need by the catalogued relief, and a need below its threshold
  is not pressing, so the same choice cannot simply repeat;
- an inhabitant never chooses the spot or destination it is already at, so a choice outdoors is
  always a walk; and
- walking to another open spot is always available on the graph and is the fallback when
  nothing is pressing, and a population may fill at most the catalogued share of what its place
  can hold.

Identity reuses the v1 uuid5 derivation; nothing here names a person. A role, home and workplace
exist only where the place's premises supply them, and are otherwise recorded as unavailable.
There is no clock, randomness or model output in a transition: every draw is the seeded SHA-256
function the earlier profiles use, and every length is an integer number of millimetres.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Sequence
from functools import cache
from itertools import pairwise
from typing import Any, Final

from exulanica.world.society import (
    SOCIETY_NAMESPACE,
    SocietyEvent,
    _inhabitant_id,
    _number,
    society_state_sha256,
)
from exulanica.world.society_catalogs import (
    MINUTES_PER_DAY,
    ROUTINE_VERSIONS,
    Activity,
    RoutineModel,
    load_routine_model,
)
from exulanica.world.society_place import (
    ceil_distance,
    place_capacity,
    place_from_society_input,
    validate_place,
)
from exulanica.world.society_planner import _paths

__all__ = [
    "LIVING_PROFILE",
    "LivingPlace",
    "advance_living_society",
    "current_routine",
    "initial_living_society",
    "living_places",
    "living_places_follow",
    "routine_for",
]

LIVING_PROFILE: Final = "exulanica-society/v4"
TICK_SECONDS: Final = 60
_WEATHER_UNAVAILABLE: Final = {
    "availability": "unavailable",
    "reason": "no weather source is connected to this society",
}
_RESOURCES_UNAVAILABLE: Final = {
    "availability": "unavailable",
    "reason": "no resource source is connected to this society",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _span(seed: str, domain: str, ordinal: int, low: int, high: int) -> int:
    return low + _number(seed, domain, ordinal) % (high - low + 1)


def _clone(value: Any) -> Any:
    """A deep copy of plain JSON data, several times faster than the generic copy module."""
    return json.loads(json.dumps(value))


class LivingPlace:
    """One validated place document with its lookups and route cache. Never persisted.

    The document is copied on construction, so later changes to the caller's dictionary cannot
    disagree with the digest that was validated. Routes are pure functions of the graph, so the
    cache is shared by every tick advanced over the same place.
    """

    def __init__(self, document: dict[str, Any], routine: RoutineModel) -> None:
        validate_place(document, routine)
        document = _clone(document)
        self.routine_sha256 = routine.sha256
        self.document = document
        self.available = document["availability"] == "available"
        self.nodes = {n["node_id"]: n for n in document["nodes"]}
        self.adjacent: dict[str, list] = {n: [] for n in self.nodes}
        self.edges: dict[frozenset, dict] = {}
        for edge in document["edges"]:
            a, b = edge["from_node_id"], edge["to_node_id"]
            self.adjacent[a].append((b, edge))
            self.adjacent[b].append((a, edge))
            self.edges[frozenset((a, b))] = edge
        for values in self.adjacent.values():
            values.sort(key=lambda pair: pair[0])
        self.crossings = {c["edge_id"]: c for c in document["crossings"]}
        self.spots = {s["spot_id"]: s for s in document["spots"]}
        self.plain_spots = [s["spot_id"] for s in document["spots"] if not s["destination_ids"]]
        self.destinations = {
            d["destination_id"]: d for d in document["destinations"] if d["enabled"]
        }
        self.unavailable = {
            r["destination_id"]: r["reason"] for r in document["unavailable_destinations"]
        }
        self.graph_sha256 = society_state_sha256(
            {"nodes": document["nodes"], "edges": document["edges"]}
        )
        self._paths: dict[str, dict] = {}
        self._pieces: dict[str, int] | None = None

    def paths(self, start: str) -> dict[str, tuple[int, tuple[str, ...]]]:
        if start not in self._paths:
            self._paths[start] = _paths(start, self.adjacent)
        return self._paths[start]

    @property
    def pieces(self) -> dict[str, int]:
        """Which connected piece of the walking graph each node is in.

        A place is allowed to be in pieces and says so: an island, or one tile of a city whose
        joining corners lie outside it. This answers whether two nodes are in the same piece in
        one pass over the graph, where asking :meth:`paths` once per person is a shortest-path
        search per person and answers a question nobody asked.
        """
        if self._pieces is None:
            found: dict[str, int] = {}
            index = 0
            for start in self.adjacent:
                if start in found:
                    continue
                queue = [start]
                found[start] = index
                while queue:
                    node = queue.pop()
                    for other, _ in self.adjacent[node]:
                        if other not in found:
                            found[other] = index
                            queue.append(other)
                index += 1
            self._pieces = found
        return self._pieces

    def position(self, node_id: str) -> list[int]:
        return list(self.nodes[node_id]["position_mm"])

    def binding(self) -> dict[str, Any]:
        source = self.document["source"]
        return {
            "place_id": self.document["place_id"],
            "input_seq": source["input_seq"],
            "input_sha256": source["document_sha256"],
            "place_sha256": self.document["document_sha256"],
            "capacity": place_capacity(self.document),
            "unsupported": list(self.document["unsupported"]),
        }


@cache
def _routine(versions: tuple[tuple[str, int], ...]) -> RoutineModel:
    return load_routine_model(versions=dict(versions))


def current_routine() -> RoutineModel:
    """The routine new societies are created under."""
    return _routine(tuple(sorted(ROUTINE_VERSIONS.items())))


def routine_for(state: dict[str, Any]) -> RoutineModel:
    """The routine a stored society recorded; a changed catalog file fails the digest check."""
    versions = state["routine"]["catalog_versions"]
    return _routine(tuple(sorted((str(k), int(v)) for k, v in versions.items())))


def living_places(
    documents: Iterable[dict[str, Any]],
    routine: RoutineModel,
    held: dict[str, LivingPlace] | None = None,
) -> list[LivingPlace]:
    """Project persisted society inputs to places, reusing any already prepared by digest."""
    held = {} if held is None else held
    places = []
    for document in documents:
        key = document["document_sha256"]
        if key not in held:
            held[key] = LivingPlace(place_from_society_input(document, routine), routine)
        places.append(held[key])
    return places


def _supported_needs(place: LivingPlace, routine: RoutineModel) -> set[str]:
    homes = any(d["resident_capacity"] for d in place.destinations.values())
    offered = {a for d in place.destinations.values() for a in d["affordances"]}
    needs = set()
    for activity in routine.activities.values():
        if activity.mode != "need":
            continue
        if (
            (activity.setting == "home" and homes)
            or (activity.setting == "destination" and activity.affordance in offered)
            or (activity.setting == "standing" and len(place.spots) > 1)
        ):
            needs.add(activity.need)
    return needs


def _positions(place: LivingPlace, kind: str) -> list[tuple[str, int]]:
    rows = []
    for dest_id, dest in sorted(place.destinations.items()):
        count = dest["resident_capacity"] if kind == "home" else dest["staff_capacity"]
        rows.extend((dest_id, index) for index in range(count))
    return rows


def _require_work_is_walkable(place: LivingPlace, inhabitants: list[dict[str, Any]]) -> None:
    """No inhabitant may be given a workplace it cannot walk to from where it lives.

    A place in pieces is not the fault: an island is a place, and so is one tile of a city whose
    joining corners lie outside it, which such a place states in its own ``unsupported``. The
    fault is a society handing somebody a job across a cut and then saying nothing. Measured on
    the corridor's own tile before this check existed: three pieces of 172, 101 and 94 nodes, 37
    of 64 inhabitants unable to reach their workplace, their shift silently skipped every tick
    for a simulated day, and every measure in :mod:`exulanica.world.society_metrics` reporting a
    healthy society. The numbers are in the refusal because the place is what has to change, and
    a refusal naming only itself sends the reader back to measure what it already knew.
    """
    pieces = place.pieces
    stranded = 0
    for person in inhabitants:
        if person["work"] is None:
            continue
        here = person["location"]["node_id"]
        there = place.destinations[person["work"]["destination_id"]]["node_id"]
        if here not in pieces or there not in pieces or pieces[here] != pieces[there]:
            stranded += 1
    _require(
        not stranded,
        f"this place's walking graph is in {len(set(pieces.values()))} pieces and {stranded} of "
        f"{len(inhabitants)} inhabitants could not walk from where they live to their workplace",
    )


def initial_living_society(
    society_id: uuid.UUID,
    seed: str,
    place: LivingPlace,
    routine: RoutineModel,
    *,
    branch_id: str,
    population: int | None = None,
) -> dict[str, Any]:
    """A population sized to its place, spread over that place's own spots and homes."""
    _require(
        isinstance(seed, str) and len(seed) == 64 and all(c in "0123456789abcdef" for c in seed),
        "society seed must be a lowercase SHA-256",
    )
    _require(place.routine_sha256 == routine.sha256, "place prepared under another routine")
    place_document = place.document
    _require(place_document["source"]["input_seq"] == 1, "genesis requires input sequence 1")
    _require(place.available, "initial place unavailable")
    policy = routine.policy
    homes = _positions(place, "home")
    shared = len(place.spots) + sum(
        d["visitor_capacity"] for d in place.destinations.values() if d["indoors"]
    )
    if homes:
        limit = len(homes)
        size = limit if population is None else population
        rule = "residents"
        reason = "Everyone who lives here: one inhabitant per catalogued place in a home."
    else:
        limit = shared * policy["occupancy_maximum_milli"] // 1000
        size = (
            shared * policy["occupancy_target_milli"] // 1000 if population is None else population
        )
        rule = "place_sized" if population is None else "requested"
        reason = (
            "No homes are published, so the population fills the catalogued share of the "
            "place's standing spots and indoor visitor places."
        )
    _require(type(size) is int and size >= 1, "place supports no population")
    _require(size <= limit, f"this place supports at most {limit} inhabitants")
    staff = _positions(place, "work")
    order = sorted(range(size), key=lambda i: (_number(seed, "work", i), i))
    jobs = dict(zip(order, staff, strict=False))
    spot_order = sorted(place.spots, key=lambda s: (_number(seed, f"spot:{s}", 0), s))
    supported = _supported_needs(place, routine)
    inhabitants = []
    spot_cursor = 0
    for ordinal in range(size):
        home = homes[ordinal] if homes else None
        job = jobs.get(ordinal)
        person: dict[str, Any] = {
            "id": str(_inhabitant_id(society_id, ordinal)),
            "ordinal": ordinal,
            "synthetic": True,
            "role": None,
            "role_reason": "place_publishes_no_premises",
            "home": None,
            "work": None,
            "walk_speed_mm_per_tick": _span(
                seed,
                "walk_speed",
                ordinal,
                policy["walk_speed_minimum_mm_per_tick"],
                policy["walk_speed_maximum_mm_per_tick"],
            ),
            "needs": {
                key: _span(seed, f"need:{key}", ordinal, need.initial_minimum, need.initial_maximum)
                for key, need in sorted(routine.needs.items())
                if key in supported
            },
            "goal": None,
            "route": None,
            "memory": [],
            "last_completed": None,
            "last_shift_day": None,
            "blocked_key": None,
            "explanation": {
                "summary": "Simulated inhabitant awaiting its first choice.",
                "event_ids": [],
            },
        }
        if home is not None:
            dest = place.destinations[home[0]]
            person["home"] = {"destination_id": home[0]}
            person["role"] = {"key": "resident", "label": "resident", "destination_id": home[0]}
            person["role_reason"] = "lives_at_premises"
            if dest["role"] is not None:
                person["role"] = {**dest["role"], "destination_id": home[0]}
        if job is not None:
            dest = place.destinations[job[0]]
            jitter = policy["shift_jitter_minutes"]
            start = dest["shift"]["start_minute"] + _span(seed, "shift", ordinal, -jitter, jitter)
            person["work"] = {
                "destination_id": job[0],
                "shift_start_minute": start % MINUTES_PER_DAY,
                "shift_minutes": dest["shift"]["minutes"],
            }
            person["role"] = {**dest["role"], "destination_id": job[0]}
            person["role_reason"] = "works_at_premises"
        elif homes and staff:
            person["role_reason"] = "no_open_position"
        if home is not None:
            dest = place.destinations[home[0]]
            person.update(
                position_mm=place.position(dest["node_id"]),
                location={
                    "node_id": dest["node_id"],
                    "edge": None,
                    "spot_id": None,
                    "destination_id": home[0],
                    "indoors": True,
                },
                reservation={"kind": "home", "id": home[0]},
                action={
                    "kind": "stay_home",
                    "status": "active",
                    "destination_id": home[0],
                    "remaining_ticks": _span(seed, "start_at_home", ordinal, 1, 45),
                    "reason": "starting_at_home",
                },
            )
        else:
            _require(spot_cursor < len(spot_order), "place has too few spots for its population")
            spot = place.spots[spot_order[spot_cursor]]
            spot_cursor += 1
            person.update(
                position_mm=list(spot["position_mm"]),
                location={
                    "node_id": spot["node_id"],
                    "edge": None,
                    "spot_id": spot["spot_id"],
                    "destination_id": None,
                    "indoors": False,
                },
                reservation={"kind": "spot", "id": spot["spot_id"]},
                action={
                    "kind": "idle",
                    "status": "active",
                    "destination_id": None,
                    "remaining_ticks": 0,
                    "reason": "awaiting_choice",
                },
            )
        person["motion_path_mm"] = [list(person["position_mm"])]
        inhabitants.append(person)
    _require_work_is_walkable(place, inhabitants)
    by_home: dict[str, list[str]] = {}
    for person in inhabitants:
        if person["home"]:
            by_home.setdefault(person["home"]["destination_id"], []).append(person["id"])
    relationships = [
        {"left": a, "right": b, "kind": "household", "destination_id": home}
        for home, ids in sorted(by_home.items())
        for a, b in pairwise(ids)
    ]
    start = policy["start_minute_of_day"]
    return {
        "profile": LIVING_PROFILE,
        "society_id": str(society_id),
        "branch_id": branch_id,
        "tick": 0,
        "tick_seconds": TICK_SECONDS,
        "clock": {"start_minute_of_day": start, "minute_of_day": start, "day": 0},
        "seed_sha256": seed,
        "routine": routine.binding(),
        "place": place.binding(),
        "input_seq": place_document["source"]["input_seq"],
        "input_sha256": place_document["source"]["document_sha256"],
        "population": {
            "size": size,
            "requested": population,
            "limit": limit,
            "capacity": place_capacity(place_document),
            "rule": rule,
            "reason": reason,
            "supported_needs": sorted(supported),
        },
        "environment": {
            "weather": dict(_WEATHER_UNAVAILABLE),
            "resources": dict(_RESOURCES_UNAVAILABLE),
        },
        "inhabitants": inhabitants,
        "relationships": relationships,
    }


def living_places_follow(previous_place: LivingPlace, current_place: LivingPlace) -> None:
    """A successor place continues its predecessor's sequence, identity and frame."""
    previous, current = previous_place.document, current_place.document
    _require(
        current["source"]["input_seq"] == previous["source"]["input_seq"] + 1,
        "place sequence gap",
    )
    for key in ("place_id", "frame"):
        _require(current[key] == previous[key], f"place changed immutable {key}")


def _weight(seed: str, routine: RoutineModel, activity: Activity, ordinal: int) -> int:
    spread = activity.weight * routine.policy["preference_spread_milli"] // 2000
    return activity.weight + _span(seed, f"preference:{activity.key}", ordinal, -spread, spread)


def _shift_due(person: dict, minute: int, day: int, lead: int) -> tuple[bool, int, int]:
    """Whether the shift is due now, the day it belongs to, and minutes until it ends."""
    work = person["work"]
    start, length = work["shift_start_minute"], work["shift_minutes"]
    for shift_day in (day, day - 1):
        begin = shift_day * MINUTES_PER_DAY + start
        now = day * MINUTES_PER_DAY + minute
        if begin - lead <= now < begin + length and person["last_shift_day"] != shift_day:
            return True, shift_day, begin + length - now
    return False, day, 0


def advance_living_society(
    state: dict[str, Any],
    seed: str,
    places: Sequence[LivingPlace],
    routine: RoutineModel,
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...]]:
    """Consume the current place and every queued successor, then take one simulated minute."""
    _require(state.get("profile") == LIVING_PROFILE, "unsupported living society profile")
    _require(state["seed_sha256"] == seed, "society seed lineage mismatch")
    _require(state["routine"] == routine.binding(), "society was built under another routine")
    _require(bool(places), "the current place is required")
    _require(
        all(place.routine_sha256 == routine.sha256 for place in places),
        "place prepared under another routine",
    )
    first = places[0].document
    _require(
        first["source"]["input_seq"] == state["input_seq"]
        and first["source"]["document_sha256"] == state["input_sha256"]
        and first["document_sha256"] == state["place"]["place_sha256"],
        "current place binding mismatch",
    )
    for prior, current in pairwise(places):
        living_places_follow(prior, current)
    policy = routine.policy
    result = _clone(state)
    tick = state["tick"] + 1
    absolute = state["clock"]["start_minute_of_day"] + tick
    minute, day = absolute % MINUTES_PER_DAY, absolute // MINUTES_PER_DAY
    result["tick"] = tick
    result["clock"] = {**state["clock"], "minute_of_day": minute, "day": day}
    previous_digest = society_state_sha256(state)
    events: list[SocietyEvent] = []
    current = places[0]

    def emit(person: dict, kind: str, reason: str, outcome: str, detail: dict) -> None:
        order = len(events)
        role = person["role"]["label"] if person["role"] else "person"
        summary = f"A {role} (simulated): {outcome.replace('_', ' ')}; {reason.replace('_', ' ')}."
        if detail.get("because"):
            summary = summary[:-1] + f": {detail['because']}."
        source = current.document["source"]
        document = {
            "summary": summary,
            "synthetic": True,
            "profile": LIVING_PROFILE,
            "branch_id": result["branch_id"],
            "subject_id": person["id"],
            "tick": tick,
            "minute_of_day": minute,
            "order": order,
            "input_seq": source["input_seq"],
            "input_sha256": source["document_sha256"],
            "place_sha256": current.document["document_sha256"],
            "reason": reason,
            "outcome": outcome,
            "goal": _clone(person["goal"]),
            "action": _clone(person["action"]),
            "needs": dict(person["needs"]),
            "position_mm": list(person["position_mm"]),
            "motion_path_mm": _clone(person["motion_path_mm"]),
            "crossings": _clone(detail.get("crossings", [])),
            "previous_state_sha256": previous_digest,
            "seed_sha256": seed,
        }
        identity = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{state['society_id']}:{tick}:{order}:{society_state_sha256(document)}",
        )
        events.append(SocietyEvent(identity, tick, kind, uuid.UUID(person["id"]), None, document))
        person["memory"] = [*person["memory"], str(identity)][-policy["memory_limit"] :]
        person["explanation"] = {"summary": summary, "event_ids": [str(identity)]}

    def block(person: dict, reason: str) -> None:
        person["goal"] = None
        person["route"] = None
        person["action"] = {
            "kind": "idle",
            "status": "blocked",
            "destination_id": None,
            "remaining_ticks": 0,
            "reason": reason,
        }
        key = [reason, current.document["source"]["input_seq"]]
        if person["blocked_key"] != key:
            emit(person, "blocked", reason, "unable_to_act", {})
        person["blocked_key"] = key

    for person in result["inhabitants"]:
        person["motion_path_mm"] = [list(person["position_mm"])]

    # Every accepted place edit is checked in order before time passes, as v2 does for inputs.
    for current in places[1:]:
        document = current.document
        for person in result["inhabitants"]:
            reason = None
            if not current.available:
                reason = document["unavailable_reason"]
            elif not _location_valid(person, current):
                reason = "current_position_invalidated"
            elif person["goal"] is not None:
                target = person["goal"]["destination_id"]
                if target is not None and target not in current.destinations:
                    reason = current.unavailable.get(target, "destination_disabled_or_removed")
                elif target is not None and _destination_changed(person, current):
                    reason = "destination_changed"
                elif person["route"] and person["route"]["graph_sha256"] != current.graph_sha256:
                    reason = "route_invalidated"
                elif person["goal"]["spot_id"] and person["goal"]["spot_id"] not in current.spots:
                    reason = "spot_removed"
            if reason:
                emit(person, "replanned", reason, "plan_invalidated", {})
                _abandon(person, current)
                person["action"] = {
                    "kind": "idle",
                    "status": "blocked",
                    "destination_id": None,
                    "remaining_ticks": 0,
                    "reason": reason,
                }
    result["place"] = current.binding()
    result["input_seq"] = current.document["source"]["input_seq"]
    result["input_sha256"] = current.document["source"]["document_sha256"]

    spot_holder: dict[str, str] = {}
    visitors: dict[str, int] = {}
    for person in result["inhabitants"]:
        held = person["reservation"]
        if held is None:
            continue
        if held["kind"] == "spot":
            spot_holder[held["id"]] = person["id"]
        elif held["kind"] == "visitor":
            visitors[held["id"]] = visitors.get(held["id"], 0) + 1

    def release(person: dict) -> None:
        held = person["reservation"]
        if held and held["kind"] == "spot" and spot_holder.get(held["id"]) == person["id"]:
            del spot_holder[held["id"]]
        elif held and held["kind"] == "visitor":
            visitors[held["id"]] -= 1
        person["reservation"] = None

    for person in result["inhabitants"]:
        for key in person["needs"]:
            person["needs"][key] = min(1000, person["needs"][key] + routine.needs[key].growth)
        if not current.available:
            block(person, current.document["unavailable_reason"])
            continue
        if not _location_valid(person, current):
            block(person, "current_position_invalidated")
            continue
        action = person["action"]
        if action["kind"] in routine.activities and action["status"] == "active":
            # Arrival started the timer; each subsequent minute spends one tick of it.
            action["remaining_ticks"] -= 1
            if action["remaining_ticks"] > 0:
                continue
            activity = routine.activities[action["kind"]]
            if activity.mode == "need":
                need = person["needs"][activity.need]
                person["needs"][activity.need] = max(0, need - activity.relief)
            else:
                person["last_shift_day"] = person["goal"]["shift_day"]
            action["status"] = "completed"
            action["reason"] = "duration_elapsed"
            person["last_completed"] = {
                "activity": activity.key,
                "destination_id": action["destination_id"],
                "spot_id": person["location"]["spot_id"],
            }
            emit(person, "action_completed", "duration_elapsed", f"{activity.key}_completed", {})
            continue
        if person["route"] is None:
            chosen = _choose(
                person, current, routine, seed, tick, minute, day, spot_holder, visitors
            )
            if isinstance(chosen, str):
                block(person, chosen)
                continue
            activity, target, because = chosen
            release(person)
            _take(person, target, spot_holder, visitors)
            _plan(person, current, activity, target, because)
            person["blocked_key"] = None
            emit(
                person,
                "goal_selected",
                person["goal"]["reason"],
                "goal_selected",
                {"because": because},
            )
        crossings = _walk(person, current, routine)
        if person["route"]["arrived"]:
            _arrive(person, current, routine, seed, tick, absolute)
            emit(
                person,
                "route_progressed",
                "arrived",
                "action_started",
                {"crossings": crossings},
            )
        elif len(person["motion_path_mm"]) > 1:
            emit(
                person,
                "route_progressed",
                "following_route",
                "moved",
                {"crossings": crossings},
            )
    return result, tuple(events)


def _location_valid(person: dict, place: LivingPlace) -> bool:
    loc = person["location"]
    if loc["edge"] is not None:
        held = loc["edge"]
        edge = place.edges.get(frozenset((held["from_node_id"], held["to_node_id"])))
        return (
            edge is not None
            and edge["edge_id"] == held["edge_id"]
            and edge["length_mm"] == held["length_mm"]
            and place.nodes[held["from_node_id"]]["position_mm"] == held["from_position_mm"]
            and place.nodes[held["to_node_id"]]["position_mm"] == held["to_position_mm"]
        )
    if loc["node_id"] not in place.nodes:
        return False
    if loc["spot_id"] is not None:
        spot = place.spots.get(loc["spot_id"])
        return spot is not None and spot["position_mm"] == person["position_mm"]
    if loc["indoors"]:
        dest = place.destinations.get(loc["destination_id"])
        return (
            dest is not None
            and dest["node_id"] == loc["node_id"]
            and place.nodes[loc["node_id"]]["position_mm"] == person["position_mm"]
        )
    return place.nodes[loc["node_id"]]["position_mm"] == person["position_mm"]


def _destination_changed(person: dict, place: LivingPlace) -> bool:
    goal = person["goal"]
    dest = place.destinations[goal["destination_id"]]
    return dest["node_id"] != goal["node_id"] or (
        goal["spot_id"] is not None and goal["spot_id"] not in dest["spot_ids"]
    )


def _abandon(person: dict, place: LivingPlace) -> None:
    """Drop a plan. A person standing on a still-valid spot keeps it; nobody else is displaced."""
    person["goal"] = None
    person["route"] = None
    loc = person["location"]
    held = person["reservation"]
    if loc["edge"] is None and loc["spot_id"] is not None and loc["spot_id"] in place.spots:
        person["reservation"] = {"kind": "spot", "id": loc["spot_id"]}
    elif not (
        loc["edge"] is None
        and loc["indoors"]
        and held is not None
        and held["kind"] != "spot"
        and held["id"] == loc["destination_id"]
        and held["id"] in place.destinations
    ):
        person["reservation"] = None


def _take(person: dict, target: dict, spot_holder: dict, visitors: dict) -> None:
    if target["spot_id"] is not None:
        spot_holder[target["spot_id"]] = person["id"]
        person["reservation"] = {"kind": "spot", "id": target["spot_id"]}
    else:
        kind = target["kind"]
        if kind == "visitor":
            visitors[target["destination_id"]] = visitors.get(target["destination_id"], 0) + 1
        person["reservation"] = {"kind": kind, "id": target["destination_id"]}


def _start_node(person: dict) -> str:
    loc = person["location"]
    return loc["node_id"] if loc["edge"] is None else loc["edge"]["to_node_id"]


def _choose(
    person: dict,
    place: LivingPlace,
    routine: RoutineModel,
    seed: str,
    tick: int,
    minute: int,
    day: int,
    spot_holder: dict,
    visitors: dict,
) -> tuple[Activity, dict, str] | str:
    """The most pressing reachable activity with room, or the reason nothing was possible.

    A pressing activity with nowhere to go is stepped over here, and :func:`_targets` now says
    why so that a successor profile can stop stepping over it. It cannot be said in v4: a goal's
    ``because`` and a blocked action's reason are both canonical state, ``_replay_living``
    recomputes every stored transition digest from genesis, and the pinned digests in
    ``tests/test_society_living.py`` carry the rule in one line, that a change there is a new
    profile. Measured either side: consuming the reason moves the tick-30 digest and leaves
    behaviour identical over 240 ticks, while returning it moves nothing at all. So it is
    returned and not yet used, and the consumer arrives with the profile that carries the city
    place join. Until then the cost is visible: on the corridor's own tile 37 of 64 inhabitants
    spent a simulated day unable to reach their workplace, their shift stepped over every tick,
    while every measure in :mod:`exulanica.world.society_metrics` reported a healthy society.
    :func:`_require_work_is_walkable` refuses that society at creation instead.
    """
    start = _start_node(person)
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
            due, shift_day, _ = _shift_due(
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
            urgency = value * _weight(seed, routine, activity, person["ordinal"]) // 1000
            is_pressing = value >= need.threshold
            because = f"{need.label} at {value} of 1000"
            if not is_pressing:
                because = f"nothing pressing; {because}"
        # The shortage is deliberately discarded: see this function's docstring for which profile
        # consumes it and why v4 cannot.
        targets, _shortage = _targets(
            person, place, activity, paths, here_spot, here_dest, spot_holder, visitors
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
    pool = pressing or fallback
    if not pool:
        return "no_reachable_place_with_room"
    _, _, activity, pick, because = max(pool, key=lambda row: (row[0], row[1]))
    return activity, pick, because


def _targets(
    person: dict,
    place: LivingPlace,
    activity: Activity,
    paths: dict,
    here_spot: str | None,
    here_dest: str | None,
    spot_holder: dict,
    visitors: dict,
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
        return rows, None if rows else _shortage(
            "standing spot", out_of_reach, taken_spots, already_here
        )
    offered = out_of_reach = no_room = already_here = 0
    for dest_id, dest in sorted(place.destinations.items()):
        if activity.affordance not in dest["affordances"]:
            continue
        offered += 1
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
    return [], _shortage(
        f"place that offers {activity.affordance}", out_of_reach, no_room, already_here
    )


def _shortage(what: str, out_of_reach: int, no_room: int, already_here: int = 0) -> str:
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
    if not causes:
        return f"this place publishes no {what}"
    return f"no {what} is open to this person: {', '.join(causes)}"


def _plan(
    person: dict,
    place: LivingPlace,
    activity: Activity,
    target: dict,
    because: str,
) -> None:
    loc = person["location"]
    path = list(place.paths(_start_node(person))[target["node_id"]][1])
    progress = 0
    if loc["edge"] is not None:
        path.insert(0, loc["edge"]["from_node_id"])
        progress = loc["edge"]["progress_mm"]
    person["goal"] = {
        "activity": activity.key,
        "destination_id": target["destination_id"],
        "spot_id": target["spot_id"],
        "node_id": target["node_id"],
        "need": activity.need if activity.mode == "need" else None,
        "shift_day": target.get("shift_day"),
        "reason": "shift_due" if activity.mode == "shift" else "most_pressing_need",
        "because": because,
    }
    stay = (
        loc["edge"] is None and loc["indoors"] and loc["destination_id"] == target["destination_id"]
    )
    person["route"] = {
        "node_ids": path,
        "edge_index": 0,
        "edge_progress_mm": progress,
        "leave_spot": loc["spot_id"] if loc["edge"] is None else None,
        "arrived": stay,
        "graph_sha256": place.graph_sha256,
    }
    person["action"] = {
        "kind": "move",
        "status": "active",
        "destination_id": target["destination_id"],
        "remaining_ticks": 0,
        "reason": "staying_here" if stay else "following_route",
    }


def _step_to(person: dict, point: list[int]) -> None:
    person["position_mm"] = list(point)
    if point != person["motion_path_mm"][-1]:
        person["motion_path_mm"].append(list(point))


def _walk(person: dict, place: LivingPlace, routine: RoutineModel) -> list[dict]:
    """Spend this inhabitant's walking budget along its route; return the crossings it entered."""
    route = person["route"]
    if route["arrived"]:
        return []
    speed = person["walk_speed_mm_per_tick"]
    budget = speed
    walked = 0
    crossings = []
    loc = person["location"]
    if route["leave_spot"] is not None:
        node = place.nodes[loc["node_id"]]["position_mm"]
        connector = ceil_distance(person["position_mm"], node)
        if connector > budget:
            return []
        budget -= connector
        walked += connector
        route["leave_spot"] = None
        person["location"] = {
            "node_id": loc["node_id"],
            "edge": None,
            "spot_id": None,
            "destination_id": None,
            "indoors": False,
        }
        _step_to(person, list(node))
    elif loc["indoors"]:
        person["location"] = {**loc, "destination_id": None, "indoors": False}
    while route["edge_index"] < len(route["node_ids"]) - 1 and budget > 0:
        index = route["edge_index"]
        a, b = route["node_ids"][index : index + 2]
        edge = place.edges[frozenset((a, b))]
        progress = route["edge_progress_mm"]
        if progress == 0 and edge["edge_id"] in place.crossings:
            crossing = place.crossings[edge["edge_id"]]
            crossings.append(
                {
                    "crossing_id": crossing["crossing_id"],
                    "arrival_second": walked * TICK_SECONDS // speed,
                    "duration_seconds": -(-edge["length_mm"] * TICK_SECONDS // speed),
                }
            )
        step = min(budget, edge["length_mm"] - progress)
        progress += step
        budget -= step
        walked += step
        start, end = place.nodes[a]["position_mm"], place.nodes[b]["position_mm"]
        _step_to(
            person,
            [x + (y - x) * progress // edge["length_mm"] for x, y in zip(start, end, strict=True)],
        )
        if progress == edge["length_mm"]:
            route["edge_index"] += 1
            route["edge_progress_mm"] = 0
            person["location"] = {
                "node_id": b,
                "edge": None,
                "spot_id": None,
                "destination_id": None,
                "indoors": False,
            }
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
                "spot_id": None,
                "destination_id": None,
                "indoors": False,
            }
    if route["edge_index"] == len(route["node_ids"]) - 1:
        goal = person["goal"]
        if goal["spot_id"] is None:
            route["arrived"] = True
        else:
            spot = place.spots[goal["spot_id"]]["position_mm"]
            connector = ceil_distance(person["position_mm"], spot)
            if connector <= budget:
                _step_to(person, list(spot))
                route["arrived"] = True
    return crossings


def _arrive(
    person: dict, place: LivingPlace, routine: RoutineModel, seed: str, tick: int, absolute: int
) -> None:
    goal = person["goal"]
    activity = routine.activities[goal["activity"]]
    dest = place.destinations.get(goal["destination_id"]) if goal["destination_id"] else None
    person["location"] = {
        "node_id": goal["node_id"],
        "edge": None,
        "spot_id": goal["spot_id"],
        "destination_id": goal["destination_id"],
        "indoors": goal["spot_id"] is None,
    }
    if activity.mode == "shift":
        work = person["work"]
        begin = goal["shift_day"] * MINUTES_PER_DAY + work["shift_start_minute"]
        duration = max(1, begin + work["shift_minutes"] - absolute)
    elif dest is not None and dest["duration_ticks"] is not None:
        duration = dest["duration_ticks"]
    else:
        duration = _span(
            seed,
            f"duration:{activity.key}:{tick}",
            person["ordinal"],
            activity.duration_minimum,
            activity.duration_maximum,
        )
    person["route"] = None
    person["action"] = {
        "kind": activity.key,
        "status": "active",
        "destination_id": goal["destination_id"],
        "remaining_ticks": duration,
        "reason": "arrived",
    }
