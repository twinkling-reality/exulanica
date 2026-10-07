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
    CROSSINGS_PER_MINUTE,
    DEPARTURE_PROFILE,
    MALFORMED,
    BoundCrossing,
    Crossing,
    CrossingRefused,
    check_crossing,
)
from exulanica.world.deciders import DECIDED_BY, decided_by_world
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import ThingKindReference, shipped_kind
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
    "THINGS_PROFILE",
    "THING_EVENT_KINDS",
    "THING_NAMESPACE",
    "THING_OUTCOMES",
    "THING_REASONS",
    "VISITORS_MAXIMUM",
    "advance_things",
    "initial_things_society",
    "kind_allows",
    "validate_things_state",
]

THINGS_PROFILE: Final = "exulanica-society/v7"
#: The namespace a placed thing's id in a society is made in, with its world's id and its placed id,
#: so a thing a branch keeps is the same thing in every version that keeps it.
THING_NAMESPACE: Final = uuid.uuid5(SOCIETY_NAMESPACE, "exulanica.placed-thing/v1")
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
    "said",
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
        "id_taken",
        # A visitor.
        "crossed_in",
        "sent_home",
        "grant_ended",
        "no_arrival_place",
        "visitor_limit",
        "unknown_kind",
        "already_here",
        "not_here",
        MALFORMED,
        # A being's decider: it said a line, or a visitor chose to leave, or the program deciding
        # for a visitor stayed quiet for as many minutes as its kind waits.
        "chose_to_say",
        "chose_to_leave",
        "decider_lost",
    }
)
#: Every outcome the things phase records, stated once: the browser has words for exactly these.
THING_OUTCOMES: Final = (
    "arrived",
    "not_arrived",
    "not_placed",
    "put_elsewhere",
    "departed",
    "not_departed",
    "said",
)
#: The reasons an outside program's request ends with for a visitor, counted as a quiet minute: it
#: had no live connection, or it did not answer in time. A program that passed answered.
QUIET_REASONS: Final = frozenset({"decider_disconnected", "no_answer_in_time"})
#: The kinds of a decision whose minute the things phase carries out: a line said, or leaving.
_SPOKEN_KINDS: Final = frozenset({"say_to", "say_all"})
#: Why a visitor left, by the reason its departure states: the program that sent it called it
#: back, or the grant it came under ended. Named apart from the world's owner sending everyone
#: away, which is another engine's.
_DEPARTURE_REASONS: Final = {"sent_away": "sent_home", "grant_ended": "grant_ended"}
_PERSON_FIELDS: Final = frozenset({"kind", "came_by", "placed_id", "placed_at_mm", "crossing"})
#: What a visitor's crossing record states; ``decided_by`` beside them only where its arrival said.
_CROSSING_FIELDS: Final = frozenset({"arrival_id", "bridge", "grant_id"})
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
    """A placement as a refusal names it: its id, its kind and where it was put, so moving it is a
    new placement."""
    return {
        "placed_id": entry["placed_id"],
        "kind": _reference(entry["kind"]),
        "placed_at_mm": list(entry["position_mm"]),
    }


def _place_beings(minute: _Minute, *, record: bool, before_population: bool = False) -> None:
    """Every placed being of the input that is not here yet comes, in id order, to the open node
    nearest where it was placed: recorded as arriving after genesis, silently at it. One that
    cannot is refused once, until its placement changes: no node is open there, or its id is
    already somebody's or something's here. One refused because the society is full is tried
    again every minute, silently, and comes when there is room. ``before_population``: at genesis
    the ground's population does not yet hold the nodes it was spread over, so an author's
    placement is kept as nearly as the ground allows, and the population steps aside after."""
    state, document = minute.state, minute.document
    present = {
        person["placed_id"] for person in state["inhabitants"] if person["came_by"] == "placed"
    }
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    for entry in placed_beings(document):
        if entry["placed_id"] in present:
            continue
        key = _refusal_key(entry)
        held = next(
            (
                refusal
                for refusal in state["refused_placements"]
                if {name: refusal[name] for name in key} == key
            ),
            None,
        )
        if held is not None and (held["reason"] != "society_full" or minute.full()):
            continue
        if held is not None:
            state["refused_placements"].remove(held)
        identity = _thing_id(document["world_id"], entry["placed_id"])
        here = {person["id"] for person in state["inhabitants"]} | {
            thing["id"] for thing in state["things"]
        }
        standing = [
            person
            for person in state["inhabitants"]
            if not (before_population and person["came_by"] == "populated")
        ]
        node = (
            None
            if minute.full() or identity in here
            else open_node_near(dict(document), standing, entry["position_mm"])
        )
        if node is None:
            reason = (
                "id_taken"
                if identity in here
                else "society_full"
                if minute.full()
                else "no_place_to_stand"
            )
            state["refused_placements"].append({**key, "reason": reason})
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
    # A refusal holds while its placement does: one whose thing was removed, changed or moved is
    # dropped, so the placement is tried again.
    state["refused_placements"] = [
        held
        for held in state["refused_placements"]
        if held["placed_id"] in wanted
        and _refusal_key(wanted[held["placed_id"]])
        == {name: held[name] for name in ("placed_id", "kind", "placed_at_mm")}
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
    # Every id a person or a thing has here: the visitor and each thing it carries must be new.
    here = {person["id"] for person in state["inhabitants"]} | {
        thing["id"] for thing in state["things"]
    }
    reason = None
    if kind is None or any(found is None for found in carried_kinds):
        reason = "unknown_kind"
    elif here & {identity, *(held["thing_id"] for held in document["carried"])}:
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
            # Who decides for it here, as its arrival said; stated only where it said so.
            **({"decided_by": document["decided_by"]} if "decided_by" in document else {}),
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


def kind_allows(state: Mapping[str, Any], subject_id: str, decider_kind: str) -> bool:
    """Whether a decider of ``decider_kind`` (``routine``, ``model``, ``person`` or ``external``)
    may decide for ``subject_id`` here, by its kind's allowed deciders: true for a person of a
    society whose people state no kind."""
    person = next((p for p in state["inhabitants"] if p["id"] == subject_id), None)
    if person is None or "kind" not in person:
        return True
    try:
        kind = shipped_kind(ThingKindReference(**person["kind"]))
    except (InvalidThingPlacement, TypeError):
        return False
    deciders = kind.document["deciders"]
    return deciders is not None and decider_kind in deciders["allowed"]


def _malformed(minute: _Minute, crossing: Crossing) -> BoundCrossing:
    """A crossing whose document fails its check, refused and bound with an event that names its
    crossing and nothing from the document: a departure's when the document says it is one, an
    arrival's otherwise."""
    document = crossing.document
    departing = isinstance(document, Mapping) and document.get("profile") == DEPARTURE_PROFILE
    event = minute.emit(
        "departure_refused" if departing else "arrival_refused",
        str(crossing.crossing_id),
        MALFORMED,
        "not_departed" if departing else "not_arrived",
        person=None,
        name="A visitor",
        details={"crossing_id": str(crossing.crossing_id)},
    )
    return BoundCrossing(crossing.crossing_id, "refused", MALFORMED, event.event_id)


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
    # The kind the ground's catalog entry names, as the input recorded it.
    villager = dict(document["population_kind"])
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
    # The author's beings first, where they were put; then the population steps aside from them.
    _place_beings(minute, record=False, before_population=True)
    _population_steps_aside(state, document)
    validate_things_state(state)
    return state


def _population_steps_aside(state: dict[str, Any], document: Mapping[str, Any]) -> None:
    """At genesis, each person of the ground's population whose starting node a placed being took
    steps to the open node nearest it, in ordinal order, as a person makes room; one with nowhere
    to go stays where it was spread."""
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    taken = {
        person["location"]["node_id"]
        for person in state["inhabitants"]
        if person["came_by"] == "placed"
    }
    for person in state["inhabitants"]:
        if person["came_by"] != "populated" or person["location"]["node_id"] not in taken:
            continue
        others = [other for other in state["inhabitants"] if other is not person]
        node = open_node_near(dict(document), others, person["position_mm"])
        if node is None:
            continue
        point = list(nodes[node])
        person.update(
            position_mm=point,
            location={"node_id": node, "edge": None},
            motion_path_mm=[list(point)],
        )


def advance_things(
    previous: Mapping[str, Any],
    state: dict[str, Any],
    seed: str,
    document: Mapping[str, Any],
    events: Sequence[SocietyEvent],
    crossings: Sequence[Crossing] = (),
    decisions: Sequence[tuple[Mapping[str, Any], Any]] = (),
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...], tuple[BoundCrossing, ...]]:
    """The things phase of a minute: ``state`` and ``events`` are the minute so far (the planner's,
    its directed requests' and its decisions'), ``previous`` the state it began from and
    ``document`` the input it consumed last. ``decisions`` are the receipts the minute consumed,
    each with what the minute did with it: an applied line is said, an applied leaving is carried
    out, and a visitor whose program stays quiet for as many minutes as its kind waits is sent home.
    Answers the state, every event of the minute, and what became of each crossing, in the order
    they were handed over."""
    _require(state["profile"] == THINGS_PROFILE, "the things phase is a society of things'")
    _require(len(crossings) <= CROSSINGS_PER_MINUTE, "a minute takes a bounded number of crossings")
    result = deepcopy(state)
    minute = _Minute(previous, result, seed, document, events)
    _reconcile(minute)
    bound = []
    for crossing in crossings:
        try:
            checked = check_crossing(crossing)
        except CrossingRefused:
            bound.append(_malformed(minute, crossing))
            continue
        if checked["profile"] == ARRIVAL_PROFILE:
            bound.append(_arrive(minute, crossing, checked))
        else:
            bound.append(_depart(minute, crossing, checked))
    _decided(minute, previous, decisions)
    validate_things_state(result)
    return result, tuple(minute.events), tuple(bound)


def _say_bounds(profile: str) -> tuple[int, int]:
    """How far a line carries and how many lines a being keeps, as the contract the people of a
    society of ``profile`` are asked under states them."""
    from exulanica.world.society_decision_contract import person_role

    role = person_role()
    contract = role.contract(role.terms(profile).versions)
    return contract.value("hearing_reach_mm"), contract.value("lines_heard_maximum")


def _program_decides(person: Mapping[str, Any]) -> bool:
    """Whether a visitor's own program decides for it: one the world decides for never goes
    quiet, since nobody outside is asked for it."""
    return person["came_by"] == "crossed" and not decided_by_world(person)


def _quiet_limit(person: Mapping[str, Any]) -> int | None:
    """How many quiet minutes a being's kind waits before it goes home, by its leave ability's
    ``quiet_minutes``; None for a kind that does not leave."""
    kind = shipped_kind(ThingKindReference(**person["kind"]))
    leave = next((a for a in kind.document["abilities"] if a["key"] == "leave"), None)
    return None if leave is None else int(leave["parameters"]["quiet_minutes"])


def _decided(
    minute: _Minute,
    previous: Mapping[str, Any],
    decisions: Sequence[tuple[Mapping[str, Any], Any]],
) -> None:
    """What the minute's consumed decisions do beside the planner's goals, in decision order: a
    visitor's quiet minutes are counted, an applied line is said where the speaker stood as the
    minute began and heard by every being then within reach that hears, and an applied leaving
    sends the visitor home; then every visitor whose program stayed quiet long enough leaves."""
    from exulanica.world.deciders import receipt_from_outside
    from exulanica.world.society_decision_contract import hearers

    if not decisions:
        return
    reach, kept = _say_bounds(minute.state["profile"])
    began = {person["id"]: person for person in previous["inhabitants"]}
    for receipt, disposition in decisions:
        person = next(
            (p for p in minute.state["inhabitants"] if p["id"] == receipt["subject_id"]), None
        )
        if person is None:
            continue
        if _program_decides(person):
            quiet = disposition.disposition == "unavailable" and receipt["reason"] in QUIET_REASONS
            if quiet:
                person["quiet_minutes"] = person.get("quiet_minutes", 0) + 1
            else:
                person.pop("quiet_minutes", None)
        if disposition.disposition != "applied" or receipt["proposal"] is None:
            continue
        option = receipt["proposal"]["option"]
        if option["kind"] == "leave" and person["came_by"] == "crossed":
            minute.leave(person, "chose_to_leave")
        elif option["kind"] in _SPOKEN_KINDS:
            line = receipt["proposal"]["line"]
            to = option.get("addressee_id")
            here = {p["id"] for p in minute.state["inhabitants"]}
            # Who heard: within reach where everybody stood as the minute began, and still here.
            origin = began.get(person["id"], person)
            heard_by = [
                other["id"]
                for _distance, other in hearers(
                    {"inhabitants": [p for i, p in began.items() if i in here]}, origin, reach
                )
            ]
            # The speaker and the one it was said to, by kind and number as the minute began, so
            # the event alone names both, whoever has left since. The option was offered over the
            # state the minute began from, so the one it names was there.
            addressee = None if to is None else began.get(to)
            minute.emit(
                "said",
                person["id"],
                "chose_to_say",
                "said",
                person=person,
                name=person["display_name"],
                details={
                    "line": line,
                    "to": to,
                    "to_kind": None if addressee is None else dict(addressee["kind"]),
                    "to_number": None if addressee is None else addressee["ordinal"] + 1,
                    "from_kind": dict(person["kind"]),
                    "from_number": person["ordinal"] + 1,
                    "heard_by": heard_by,
                    "decider": "external" if receipt_from_outside(receipt) else "model",
                },
            )
            heard = {
                "tick": minute.state["tick"],
                "from": person["id"],
                "from_kind": dict(person["kind"]),
                "from_number": person["ordinal"] + 1,
                "to": to,
                "line": line,
            }
            for hearer in minute.state["inhabitants"]:
                if hearer["id"] in heard_by:
                    hearer["heard"] = [*hearer.get("heard", ()), dict(heard)][-kept:]
    for person in list(minute.state["inhabitants"]):
        limit = _quiet_limit(person) if _program_decides(person) else None
        if limit is not None and person.get("quiet_minutes", 0) >= limit:
            minute.leave(person, "decider_lost")


#: Why a placed being is not in the society: it is full, no node is open where it was put, or the
#: id it would have is already somebody's or something's here.
_PLACEMENT_REFUSALS: Final = ("society_full", "no_place_to_stand", "id_taken")


def _point_shape(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(type(c) is int for c in value)


def _reference_shape(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"kind", "version", "sha256"}
        and isinstance(value["kind"], str)
        and type(value["version"]) is int
        and isinstance(value["sha256"], str)
        and _HEX64.fullmatch(value["sha256"]) is not None
    )


#: The most lines a state lets one being keep, whatever its contract keeps: a bound on the field.
_HEARD_BOUND: Final = 64
_HEARD_FIELDS: Final = frozenset({"tick", "from", "from_kind", "from_number", "to", "line"})


def _optional_lines(person: Mapping[str, Any]) -> None:
    """The lines a being heard, stated only once it heard one (oldest first, each with when, who
    said it, by kind and number, to whom and the line itself), and a visitor's quiet minutes,
    stated only while its program has been quiet."""
    from exulanica.things.lines import LineRefused, check_line

    heard = person.get("heard")
    if heard is not None:
        _require(
            isinstance(heard, list) and 1 <= len(heard) <= _HEARD_BOUND,
            "a being states the lines it heard only once it heard one",
        )
        ticks = [entry.get("tick") if isinstance(entry, dict) else None for entry in heard]
        for entry in heard:
            _require(
                isinstance(entry, dict)
                and set(entry) == _HEARD_FIELDS
                and type(entry["tick"]) is int
                and isinstance(entry["from"], str)
                and _reference_shape(entry["from_kind"])
                and type(entry["from_number"]) is int
                and entry["from_number"] >= 1
                and (entry["to"] is None or isinstance(entry["to"], str)),
                "invalid heard line",
            )
            try:
                check_line(entry["line"])
            except LineRefused as exc:
                raise ValueError("a heard line is held to the line rule") from exc
        _require(ticks == sorted(ticks), "a being's heard lines are oldest first")
    quiet = person.get("quiet_minutes")
    if quiet is not None:
        _require(
            _program_decides(person) and type(quiet) is int and quiet >= 1,
            "only a visitor its program decides for counts the program's quiet minutes, and only "
            "while it is quiet",
        )


def _optional_movement(person: Mapping[str, Any]) -> None:
    """A being's movement fields, each stated only where it applies: a mode other than the one
    every walker has, a height only while it flies, a velocity only while it flies and only where
    its module states one, a size class other than the people's."""
    mode = person.get("mode", "walking")
    _require(mode in MODES, "a being moves by a mode a module serves")
    _require(person.get("mode") != "walking", "a walker states no mode")
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
        _optional_lines(person)
        came_by = person["came_by"]
        _require(came_by in CAME_BY, "a person came by a stated way")
        _require(
            (person["placed_id"] is not None) == (came_by == "placed")
            and (person["placed_at_mm"] is not None) == (came_by == "placed")
            and (person["crossing"] is not None) == (came_by == "crossed"),
            "a person's placement and crossing are how it came",
        )
        crossing = person["crossing"]
        _require(
            crossing is None
            or (
                isinstance(crossing, dict)
                and set(crossing) - {"decided_by"} == _CROSSING_FIELDS
                and crossing.get("decided_by", "program") in DECIDED_BY
            ),
            "a visitor's crossing names its arrival, bridge and grant, and who decides for it",
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
            and set(held) == {"placed_id", "kind", "placed_at_mm", "reason"}
            and _reference_shape(held["kind"])
            and _point_shape(held["placed_at_mm"])
            and held["reason"] in _PLACEMENT_REFUSALS,
            "invalid refused placement",
        )
