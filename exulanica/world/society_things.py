"""The society of things, ``exulanica-society/v7``: the purposeful society of things.

A society of things stands on a saved world's own ground and reads inputs of the things
composition (``exulanica.society-input/authored-ground-v5``,
:mod:`exulanica.world.society_thing_inputs`). Its people walk, choose, stay and talk by the
purposeful planner's rules (:mod:`exulanica.world.society_planner`), and each of them is a thing of
a stated kind, named in the state by key, version and digest, and by how it came to be there:

*   ``populated``: the villagers its ground's population brings, the purposeful genesis's own
    people, with the same names and draws;
*   ``placed``: each being the world's author placed in the version, standing at the open node
    nearest where it was placed; it arrives when an edit places it, is put where an edit moves it,
    and leaves when an edit removes it;
*   ``crossed``: visitors from an outside program (:mod:`exulanica.world.crossings`), each arriving
    at the open node nearest a gate's arrival point and leaving when its program sends it away or
    its grant ends; what a visitor carries in is held by it and leaves with it.

Its state also holds its things: every object the author placed, with its kind and where it
stands, and anything a visitor carried in, held by that visitor. A placed object's obstacle and
activity are already its input's navigation and targets, so the planner walks round it and uses it
with nothing more here.

A minute is the planner's minute, its directed requests and its role decisions, then the things
phase (:func:`advance_things`): placed beings are reconciled with the latest input, then the
crossings handed to the minute are taken in the order their door wrote them. Every event the
things phase records continues the minute's order, so a minute with no change to its placed beings
and no crossing records the planner's events alone.

No look reaches a society of things: its input carries each kind's semantics, never its looks, and
its state and events name kinds by key, version and digest.

Pure: no connection. The crossings a minute takes are passed in, and what became of each is
returned for the caller to bind.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Final

from exulanica.things.kinds import ThingKind
from exulanica.world.crossings import (
    ARRIVAL_PROFILE,
    BoundCrossing,
    Crossing,
    check_crossing,
)
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import ThingKindReference, named_kind, shipped_kind
from exulanica.world.society import (
    SOCIETY_NAMESPACE,
    SocietyEvent,
    _number,
    society_state_sha256,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_input_policy import THING_INPUTS
from exulanica.world.society_planner import (
    initial_purposeful_society,
    open_node_near,
    validate_society_input,
)
from exulanica.world.society_thing_inputs import (
    arrival_points,
    placed_beings,
    placed_objects,
)

__all__ = [
    "CAME_BY",
    "POPULATION_KIND",
    "THINGS_PROFILE",
    "THING_EVENT_KINDS",
    "THING_NAMESPACE",
    "THING_REASONS",
    "VISITORS_MAXIMUM",
    "advance_things",
    "initial_things_society",
    "validate_things_state",
]

THINGS_PROFILE: Final = "exulanica-society/v7"
#: The namespace a placed thing's id in a society is made in, with its world's id and its placed id,
#: so a thing a branch keeps is the same thing in every version that keeps it.
THING_NAMESPACE: Final = uuid.uuid5(SOCIETY_NAMESPACE, "exulanica.placed-thing/v1")
#: The kind of the people a ground's population brings.
POPULATION_KIND: Final = ("villager", 1)
#: How each person came to be in the society.
CAME_BY: Final = ("populated", "placed", "crossed")
#: The most visitors a society of things holds at once, so outside programs never crowd out the
#: world its own people live in: a visitor past it is refused (``visitor_limit``).
VISITORS_MAXIMUM: Final = 16
#: Every kind of event the things phase records.
THING_EVENT_KINDS: Final = (
    "thing_arrived",
    "thing_moved",
    "thing_departed",
    "arrival_refused",
    "departure_refused",
)
#: Every reason the things phase records, stated once: the browser has words for exactly these.
THING_REASONS: Final = frozenset(
    {
        # A placed being.
        "placed_by_author",
        "moved_by_author",
        "removed_by_author",
        "society_full",
        "no_place_to_stand",
        # A visitor.
        "crossed_in",
        "sent_home",
        "grant_ended",
        "no_arrival_place",
        "visitor_limit",
        "unknown_kind",
        "already_here",
        "not_here",
    }
)
#: Why a visitor left, by the reason its departure states: the program that sent it called it
#: back, or the grant it came under ended. Named apart from the world's owner sending everyone
#: away, which is another engine's.
_DEPARTURE_REASONS: Final = {"sent_away": "sent_home", "grant_ended": "grant_ended"}
_PERSON_FIELDS: Final = frozenset({"kind", "came_by", "placed_id", "placed_at_mm", "crossing"})
_THING_FIELDS: Final = frozenset(
    {"id", "placed_id", "kind", "position_mm", "yaw_microradians", "held_by"}
)
#: What a person or a thing states only where it applies, so a society of walkers on the ground
#: states none of them (agreed for v7 from its first state): how a being moves now where it has
#: more than one way or another way than walking (``mode``), how high above the ground's elevation
#: it is while it flies or a thing stands off the ground (``height_mm``), the velocity a flyer's
#: minute ended with, which its next minute starts from (``velocity_mm_s``), and the size class it
#: walks or flies by where it is not the people's (``size_class_mm``).
MODES: Final = ("walking", "flight")
_THING_MAY: Final = frozenset({"height_mm"})
#: A flyer's velocity, whole millimetres a second: x and y along the ground (``position_mm``'s
#: two axes), z up (the rate of ``height_mm``), each within this bound.
_VELOCITY_MM_S: Final = 100_000
#: The size classes a being other than a person may walk or fly by: whole half metres up to the
#: widest air column; the people's class (a 450 mm walking clearance) is stated by no field.
_SIZE_CLASS_MM: Final = (500, 8_000, 500)
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _thing_id(world_id: str, placed_id: str) -> str:
    return str(uuid.uuid5(THING_NAMESPACE, f"{world_id}:{placed_id}"))


def _reference(semantics: Mapping[str, Any]) -> dict[str, Any]:
    return dict(semantics["reference"])


def _label(kind: ThingKind | Mapping[str, Any]) -> str:
    label = kind.label if isinstance(kind, ThingKind) else str(kind["label"])
    return label[:1].upper() + label[1:]


def _name(people: Sequence[Mapping[str, Any]], label: str) -> str:
    """A kind's label as a name, numbered from the second present at once."""
    taken = {person["display_name"] for person in people}
    if label not in taken:
        return label
    number = 2
    while f"{label} {number}" in taken:
        number += 1
    return f"{label} {number}"


def _things_of(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The society's things the input places: every object the author placed, in id order."""
    return [
        {
            "id": _thing_id(document["world_id"], entry["placed_id"]),
            "placed_id": entry["placed_id"],
            "kind": _reference(entry["kind"]),
            "position_mm": list(entry["position_mm"]),
            "yaw_microradians": entry["yaw_microradians"],
            "held_by": None,
            **({"height_mm": entry["height_mm"]} if "height_mm" in entry else {}),
        }
        for entry in placed_objects(document)
    ]


def _newcomer(
    state: dict[str, Any],
    seed: str,
    *,
    identity: str,
    label: str,
    kind: Mapping[str, Any],
    came_by: str,
    node_id: str,
    point: list[int],
    placed_id: str | None = None,
    placed_at_mm: list[int] | None = None,
    crossing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A person new to the society, at ``node_id``, with nothing to do yet."""
    ordinal = state["next_ordinal"]
    state["next_ordinal"] = ordinal + 1
    return {
        "id": identity,
        "ordinal": ordinal,
        "display_name": _name(state["inhabitants"], label),
        "synthetic": True,
        "household": None,
        "role": label.lower(),
        "home_node": None,
        "work_node": None,
        "schedule": None,
        "position_mm": list(point),
        "destination": None,
        # How tired they are begins as the purposeful genesis draws it for an ordinal.
        "need_milli": 500 + _number(seed, "need", ordinal) % 401,
        "memory": [],
        "goal": None,
        "route": None,
        "location": {"node_id": node_id, "edge": None},
        "target": None,
        "action": {
            "kind": "idle",
            "status": "active",
            "target_id": None,
            "remaining_ticks": 0,
            "reason": "awaiting_goal",
        },
        "motion_path_mm": [list(point)],
        "explanation": {
            "summary": "Simulated inhabitant awaiting its first goal.",
            "event_ids": [],
        },
        "last_completed_target_id": None,
        "blocked_key": None,
        "route_geometry_sha256": None,
        "kind": dict(kind),
        "came_by": came_by,
        "placed_id": placed_id,
        "placed_at_mm": None if placed_at_mm is None else list(placed_at_mm),
        "crossing": None if crossing is None else dict(crossing),
    }


class _Minute:
    """One things phase: the state it changes and the events it records, in order after
    ``events``."""

    def __init__(
        self,
        previous: Mapping[str, Any],
        state: dict[str, Any],
        seed: str,
        document: Mapping[str, Any],
        events: Sequence[SocietyEvent],
    ) -> None:
        self.state = state
        self.seed = seed
        self.document = document
        self.events = list(events)
        self.previous_digest = society_state_sha256(dict(previous))
        self.maximum = society_engine(state["profile"]).population_maximum

    def emit(
        self,
        kind: str,
        subject_id: str,
        reason: str,
        outcome: str,
        *,
        person: dict[str, Any] | None,
        name: str,
        details: Mapping[str, Any],
    ) -> SocietyEvent:
        order = len(self.events)
        summary = f"{name} (simulated): {outcome.replace('_', ' ')}; {reason.replace('_', ' ')}."
        document = {
            "summary": summary,
            "synthetic": True,
            "profile": self.state["profile"],
            "branch_id": self.state["branch_id"],
            "subject_id": subject_id,
            "tick": self.state["tick"],
            "order": order,
            "input_seq": self.document["input_seq"],
            "input_sha256": self.document["document_sha256"],
            "target": None,
            "reason": reason,
            "outcome": outcome,
            "goal": None if person is None else deepcopy(person["goal"]),
            "action": None if person is None else deepcopy(person["action"]),
            "position_mm": None if person is None else list(person["position_mm"]),
            "motion_path_mm": [] if person is None else deepcopy(person["motion_path_mm"]),
            "previous_state_sha256": self.previous_digest,
            "seed_sha256": self.seed,
            "thing": dict(details),
            # The things phase takes effect as the minute begins: edits and crossings handed over
            # during the minute before it.
            "at_ms": 0,
        }
        identity = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{self.state['society_id']}:{self.state['tick']}:{order}:"
            f"{society_state_sha256(document)}",
        )
        event = SocietyEvent(
            identity, self.state["tick"], kind, uuid.UUID(subject_id), None, document
        )
        self.events.append(event)
        if person is not None:
            person["memory"] = [*person["memory"], str(identity)][-16:]
            person["explanation"] = {"summary": summary, "event_ids": [str(identity)]}
        return event

    def leave(
        self, person: dict[str, Any], reason: str, extra: Mapping[str, Any] | None = None
    ) -> SocietyEvent:
        """``person`` leaves the society, and whatever it holds leaves with it."""
        carried = [thing for thing in self.state["things"] if thing["held_by"] == person["id"]]
        self.state["things"] = [
            thing for thing in self.state["things"] if thing["held_by"] != person["id"]
        ]
        self.state["inhabitants"] = [
            other for other in self.state["inhabitants"] if other is not person
        ]
        return self.emit(
            "thing_departed",
            person["id"],
            reason,
            "departed",
            person=person,
            name=person["display_name"],
            details={
                "kind": person["kind"],
                "came_by": person["came_by"],
                "placed_id": person["placed_id"],
                "carried": [{"id": thing["id"], "kind": thing["kind"]} for thing in carried],
                **(extra or {}),
            },
        )

    def full(self) -> bool:
        return len(self.state["inhabitants"]) >= self.maximum


def _refusal_key(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {"placed_id": entry["placed_id"], "kind": _reference(entry["kind"])}


def _place_beings(minute: _Minute, *, record: bool) -> None:
    """Every placed being of the input that is not here yet comes, in id order, to the open node
    nearest where it was placed: recorded as arriving after genesis, silently at it. One that
    cannot (the society is full, or no node is open) is refused once, until its placement
    changes."""
    state, document = minute.state, minute.document
    present = {
        person["placed_id"] for person in state["inhabitants"] if person["came_by"] == "placed"
    }
    refused = [_refusal_key(entry) for entry in state["refused_placements"]]
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    for entry in placed_beings(document):
        if entry["placed_id"] in present or _refusal_key(entry) in refused:
            continue
        identity = _thing_id(document["world_id"], entry["placed_id"])
        node = (
            None
            if minute.full()
            else open_node_near(dict(document), state["inhabitants"], entry["position_mm"])
        )
        if node is None:
            reason = "society_full" if minute.full() else "no_place_to_stand"
            state["refused_placements"].append({**_refusal_key(entry), "reason": reason})
            if record:
                minute.emit(
                    "arrival_refused",
                    identity,
                    reason,
                    "not_placed",
                    person=None,
                    name=_label(entry["kind"]),
                    details={
                        "kind": _reference(entry["kind"]),
                        "came_by": "placed",
                        "placed_id": entry["placed_id"],
                    },
                )
            continue
        point = list(nodes[node])
        person = _newcomer(
            state,
            minute.seed,
            identity=identity,
            label=_label(entry["kind"]),
            kind=_reference(entry["kind"]),
            came_by="placed",
            node_id=node,
            point=point,
            placed_id=entry["placed_id"],
            placed_at_mm=entry["position_mm"],
        )
        state["inhabitants"].append(person)
        if record:
            minute.emit(
                "thing_arrived",
                identity,
                "placed_by_author",
                "arrived",
                person=person,
                name=person["display_name"],
                details={
                    "kind": person["kind"],
                    "came_by": "placed",
                    "placed_id": entry["placed_id"],
                },
            )


def _reconcile(minute: _Minute) -> None:
    """Placed beings as the latest input places them: removed or changed ones leave, moved ones
    are put where the edit says, and new ones arrive. An unavailable input changes nobody."""
    state, document = minute.state, minute.document
    if document["availability"] != "available" or document["navigation"]["unavailable_reason"]:
        return
    wanted = {entry["placed_id"]: entry for entry in placed_beings(document)}
    for person in list(state["inhabitants"]):
        if person["came_by"] != "placed":
            continue
        entry = wanted.get(person["placed_id"])
        if entry is None or _reference(entry["kind"]) != person["kind"]:
            minute.leave(person, "removed_by_author")
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    for person in state["inhabitants"]:
        if person["came_by"] != "placed":
            continue
        entry = wanted[person["placed_id"]]
        if entry["position_mm"] == person["placed_at_mm"]:
            continue
        others = [other for other in state["inhabitants"] if other is not person]
        node = open_node_near(dict(document), others, entry["position_mm"])
        person["placed_at_mm"] = list(entry["position_mm"])
        if node is None:
            # Nowhere open near where it was put: it stays where it is and keeps going.
            continue
        point = list(nodes[node])
        person.update(
            position_mm=point,
            location={"node_id": node, "edge": None},
            goal=None,
            target=None,
            route=None,
            action={
                "kind": "idle",
                "status": "completed",
                "target_id": None,
                "remaining_ticks": 0,
                "reason": "moved_by_author",
            },
            blocked_key=None,
            route_geometry_sha256=None,
        )
        if point != person["motion_path_mm"][-1]:
            person["motion_path_mm"].append(point)
        minute.emit(
            "thing_moved",
            person["id"],
            "moved_by_author",
            "put_elsewhere",
            person=person,
            name=person["display_name"],
            details={"kind": person["kind"], "came_by": "placed", "placed_id": person["placed_id"]},
        )
    # A refusal holds while its placement does: one whose thing was removed or changed is dropped.
    state["refused_placements"] = [
        held
        for held in state["refused_placements"]
        if held["placed_id"] in wanted
        and _reference(wanted[held["placed_id"]]["kind"]) == held["kind"]
    ]
    _place_beings(minute, record=True)
    state["things"] = [
        *_things_of(document),
        *(thing for thing in state["things"] if thing["held_by"] is not None),
    ]


def _visitor_kind(reference: Mapping[str, Any]) -> ThingKind | None:
    """The shipped being a visitor may be, by its exact reference, or None."""
    try:
        kind = shipped_kind(ThingKindReference(**reference))
    except (InvalidThingPlacement, TypeError):
        return None
    deciders = kind.document["deciders"]
    if kind.klass != "being" or deciders is None or "external" not in deciders["allowed"]:
        return None
    return kind


def _arrive(minute: _Minute, crossing: Crossing, document: Mapping[str, Any]) -> BoundCrossing:
    state = minute.state
    identity = document["thing_id"]
    kind = _visitor_kind(document["kind"])
    carried_kinds = [_carried_kind(held["kind"]) for held in document["carried"]]
    gates = arrival_points(minute.document)
    gate = document["gate"]
    if gate is None and gates:
        gate = min(gates)
    held_ids = {thing["id"] for thing in state["things"]}
    reason = None
    if kind is None or any(found is None for found in carried_kinds):
        reason = "unknown_kind"
    elif any(person["id"] == identity for person in state["inhabitants"]) or held_ids & {
        identity,
        *(held["thing_id"] for held in document["carried"]),
    }:
        reason = "already_here"
    elif (
        sum(1 for person in state["inhabitants"] if person["came_by"] == "crossed")
        >= VISITORS_MAXIMUM
        or minute.full()
    ):
        reason = "visitor_limit"
    elif gate is None or gate not in gates:
        reason = "no_arrival_place"
    node = None
    if reason is None:
        node = open_node_near(dict(minute.document), state["inhabitants"], gates[gate])
        if node is None:
            reason = "no_arrival_place"
    by = document["origin"]["by"]
    details = {
        "kind": dict(document["kind"]),
        "came_by": "crossed",
        "placed_id": None,
        "crossing_id": str(crossing.crossing_id),
        "gate": gate,
    }
    if reason is not None:
        event = minute.emit(
            "arrival_refused",
            identity,
            reason,
            "not_arrived",
            person=None,
            name=_label(kind) if kind is not None else "A visitor",
            details=details,
        )
        return BoundCrossing(crossing.crossing_id, "refused", reason, event.event_id)
    assert node is not None and kind is not None
    nodes = {n["node_id"]: n["position_mm"] for n in minute.document["navigation"]["nodes"]}
    person = _newcomer(
        state,
        minute.seed,
        identity=identity,
        label=_label(kind),
        kind=kind.reference(),
        came_by="crossed",
        node_id=node,
        point=list(nodes[node]),
        crossing={
            "arrival_id": document["arrival_id"],
            "bridge": by["bridge"],
            "grant_id": document["grant_id"],
        },
    )
    state["inhabitants"].append(person)
    for held, found in zip(document["carried"], carried_kinds, strict=True):
        assert found is not None
        state["things"].append(
            {
                "id": held["thing_id"],
                "placed_id": None,
                "kind": found.reference(),
                "position_mm": None,
                "yaw_microradians": None,
                "held_by": identity,
            }
        )
    event = minute.emit(
        "thing_arrived",
        identity,
        "crossed_in",
        "arrived",
        person=person,
        name=person["display_name"],
        details={
            **details,
            "carried": [dict(held) for held in document["carried"]],
        },
    )
    return BoundCrossing(crossing.crossing_id, "arrived", None, event.event_id)


def _carried_kind(reference: Mapping[str, Any]) -> ThingKind | None:
    """The shipped object a visitor may carry, by its exact reference, or None."""
    try:
        kind = shipped_kind(ThingKindReference(**reference))
    except (InvalidThingPlacement, TypeError):
        return None
    return kind if kind.klass == "object" and "holdable" in kind.offers else None


def _depart(minute: _Minute, crossing: Crossing, document: Mapping[str, Any]) -> BoundCrossing:
    person = next(
        (
            person
            for person in minute.state["inhabitants"]
            if person["id"] == document["thing_id"] and person["came_by"] == "crossed"
        ),
        None,
    )
    if person is None:
        event = minute.emit(
            "departure_refused",
            document["thing_id"],
            "not_here",
            "not_departed",
            person=None,
            name="A visitor",
            details={"crossing_id": str(crossing.crossing_id), "came_by": "crossed"},
        )
        return BoundCrossing(crossing.crossing_id, "not_here", "not_here", event.event_id)
    event = minute.leave(
        person, _DEPARTURE_REASONS[document["reason"]], {"crossing_id": str(crossing.crossing_id)}
    )
    return BoundCrossing(crossing.crossing_id, "departed", None, event.event_id)


def initial_things_society(
    society_id: uuid.UUID, seed: str, document: dict[str, Any], *, population: int
) -> dict[str, Any]:
    """A society of things' genesis over its first input: the purposeful genesis's people, each a
    villager, then every being the author placed, each at the open node nearest where it was
    placed."""
    validate_society_input(document)
    _require(
        document["profile"] in THING_INPUTS, "a society of things reads the things composition"
    )
    state = initial_purposeful_society(society_id, seed, document, population=population)
    state["profile"] = THINGS_PROFILE
    villager = named_kind(*POPULATION_KIND).document()
    for person in state["inhabitants"]:
        person.update(
            kind=dict(villager),
            came_by="populated",
            placed_id=None,
            placed_at_mm=None,
            crossing=None,
        )
    state["next_ordinal"] = len(state["inhabitants"])
    state["things"] = _things_of(document)
    state["refused_placements"] = []
    minute = _Minute(state, state, seed, document, ())
    _place_beings(minute, record=False)
    validate_things_state(state)
    return state


def advance_things(
    previous: Mapping[str, Any],
    state: dict[str, Any],
    seed: str,
    document: Mapping[str, Any],
    events: Sequence[SocietyEvent],
    crossings: Sequence[Crossing] = (),
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...], tuple[BoundCrossing, ...]]:
    """The things phase of a minute: ``state`` and ``events`` are the minute so far (the planner's,
    its directed requests' and its decisions'), ``previous`` the state it began from and
    ``document`` the input it consumed last. Answers the state, every event of the minute, and
    what became of each crossing, in the order they were handed over."""
    _require(state["profile"] == THINGS_PROFILE, "the things phase is a society of things'")
    result = deepcopy(state)
    minute = _Minute(previous, result, seed, document, events)
    _reconcile(minute)
    bound = []
    for crossing in crossings:
        checked = check_crossing(crossing)
        if checked["profile"] == ARRIVAL_PROFILE:
            bound.append(_arrive(minute, crossing, checked))
        else:
            bound.append(_depart(minute, crossing, checked))
    validate_things_state(result)
    return result, tuple(minute.events), tuple(bound)


def _reference_shape(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"kind", "version", "sha256"}
        and isinstance(value["kind"], str)
        and type(value["version"]) is int
        and isinstance(value["sha256"], str)
        and _HEX64.fullmatch(value["sha256"]) is not None
    )


def _optional_movement(person: Mapping[str, Any]) -> None:
    """A being's movement fields, each stated only where it applies: a mode other than the one
    every walker has, a height only while it flies, a velocity only while it flies and only where
    its module states one, a size class other than the people's."""
    mode = person.get("mode", "walking")
    _require(mode in MODES, "a being moves by a mode a module serves")
    _require(
        ("height_mm" in person) == (mode == "flight")
        and (
            "height_mm" not in person
            or (type(person["height_mm"]) is int and 0 <= person["height_mm"] <= 1_000_000)
        ),
        "a being states its height while it flies, and only then",
    )
    velocity = person.get("velocity_mm_s")
    _require(
        "velocity_mm_s" not in person
        or (
            mode == "flight"
            and isinstance(velocity, list)
            and len(velocity) == 3
            and all(type(part) is int and abs(part) <= _VELOCITY_MM_S for part in velocity)
        ),
        "a being states a velocity only while it flies, three whole millimetres a second",
    )
    low, high, step = _SIZE_CLASS_MM
    size = person.get("size_class_mm")
    _require(
        "size_class_mm" not in person
        or (type(size) is int and low <= size <= high and size % step == 0),
        "a size class is a whole half metre up to the widest air column",
    )


def validate_things_state(state: Mapping[str, Any]) -> None:
    """A society of things' state, held to its own fields beside the purposeful planner's: every
    person a thing of a kind, by how it came, every thing once, and nothing held by nobody here."""
    _require(state.get("profile") == THINGS_PROFILE, "unsupported society of things profile")
    people = state["inhabitants"]
    ids = [person["id"] for person in people]
    _require(len(ids) == len(set(ids)), "a person is in a society once")
    ordinals = [person["ordinal"] for person in people]
    _require(
        len(ordinals) == len(set(ordinals))
        and type(state["next_ordinal"]) is int
        and all(ordinal < state["next_ordinal"] for ordinal in ordinals),
        "every person has an ordinal of their own",
    )
    for person in people:
        _require(set(person) >= _PERSON_FIELDS, "a person of a society of things states its kind")
        _require(_reference_shape(person["kind"]), "a person names its kind")
        _optional_movement(person)
        came_by = person["came_by"]
        _require(came_by in CAME_BY, "a person came by a stated way")
        _require(
            (person["placed_id"] is not None) == (came_by == "placed")
            and (person["placed_at_mm"] is not None) == (came_by == "placed")
            and (person["crossing"] is not None) == (came_by == "crossed"),
            "a person's placement and crossing are how it came",
        )
    things = state["things"]
    _require(isinstance(things, list), "a society of things holds a list of things")
    thing_ids = [thing["id"] for thing in things]
    _require(len(thing_ids) == len(set(thing_ids)), "a thing is in a society once")
    _require(not set(thing_ids) & set(ids), "a thing is a person or a thing, never both")
    present = set(ids)
    for thing in things:
        _require(
            isinstance(thing, dict) and set(thing) - _THING_MAY == _THING_FIELDS,
            "invalid thing fields",
        )
        _require(
            "height_mm" not in thing
            or (type(thing["height_mm"]) is int and thing["height_mm"] != 0),
            "a thing off the ground states its height, and one on it none",
        )
        _require(_reference_shape(thing["kind"]), "a thing names its kind")
        _require(
            thing["held_by"] is None or thing["held_by"] in present,
            "a thing is held by somebody here, or by nobody",
        )
        _require(
            (thing["placed_id"] is None) == (thing["held_by"] is not None),
            "a thing stands where it was placed until somebody holds it",
        )
    refused = state["refused_placements"]
    _require(isinstance(refused, list), "refused placements are a list")
    for held in refused:
        _require(
            isinstance(held, dict)
            and set(held) == {"placed_id", "kind", "reason"}
            and _reference_shape(held["kind"])
            and held["reason"] in ("society_full", "no_place_to_stand"),
            "invalid refused placement",
        )
