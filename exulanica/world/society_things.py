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

import math
import re
import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy
from itertools import pairwise
from typing import Any, Final

from exulanica.things.kinds import ThingKind
from exulanica.things.lines import HEARD_LINES_MAXIMUM
from exulanica.world.crossings import (
    ARRIVAL_PROFILE,
    CROSSINGS_PER_MINUTE,
    DEPARTURE_PROFILE,
    MALFORMED,
    BoundCrossing,
    Crossing,
    CrossingRefused,
    check_crossing,
    is_carry_out_list,
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
    never_tired,
    open_node_near,
    routine_of,
    routine_withheld,
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
#: The most placed things the visitors of one grant carry out of a world in any
#: :data:`CARRY_OUT_WINDOW_TICKS` minutes; a thing past it stays, put down where its visitor stood.
CARRY_OUT_MAXIMUM: Final = 8
CARRY_OUT_WINDOW_TICKS: Final = 60
#: Every kind of event the things phase records.
THING_EVENT_KINDS: Final = (
    "thing_arrived",
    "thing_moved",
    "thing_departed",
    "arrival_refused",
    "departure_refused",
    "said",
    # Where the society records the hands module: a hands act done, or one dropped.
    "picked_up",
    "put_down",
    "gave",
    "took",
    "hands_missed",
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
        # A being's decider chose a hands act, done in the minute the being stood within reach,
        # or dropped: the thing or the other being was gone, or never came within reach in the
        # minutes the module walks.
        "chose_to_pick_up",
        "chose_to_put_down",
        "chose_to_give",
        "chose_to_take",
        # The world's owner asked a being for a hands act, done the same way.
        "asked_to_pick_up",
        "asked_to_put_down",
        "asked_to_give",
        "asked_to_take",
        "thing_gone",
        "out_of_reach",
        # A hands act left undone for another: an asked act its decider's choice replaced, or a
        # decider's act a request replaced.
        "chose_otherwise",
        "asked_otherwise",
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
    "picked_up",
    "put_down",
    "gave",
    "took",
    "not_done",
)
#: The reasons an outside program's request ends with for a visitor, counted as a quiet minute: it
#: had no live connection, it did not answer in time, the grant it came under was revoked or has
#: expired, so a visitor goes home even when no grant_ended crossing follows, or it could not be
#: asked, since a name the account holder saved is among the words its request would send. A
#: program that passed answered.
QUIET_REASONS: Final = frozenset(
    {
        "decider_disconnected",
        "no_answer_in_time",
        "grant_revoked",
        "grant_expired",
        "saved_name_withheld",
    }
)
#: The kinds of a decision whose minute the things phase carries out: a line said, or leaving.
_SPOKEN_KINDS: Final = frozenset({"say_to", "say_all"})
#: The kinds of a decision the hands step carries out, each by the event it records.
_HANDS_ACTS: Final = {
    "pick_up": "picked_up",
    "put_down": "put_down",
    "give": "gave",
    "take": "took",
}
#: Why a visitor left, by the reason its departure states: the program that sent it called it
#: back, or the grant it came under ended. Named apart from the world's owner sending everyone
#: away, which is another engine's.
_DEPARTURE_REASONS: Final = {"sent_away": "sent_home", "grant_ended": "grant_ended"}
_PERSON_FIELDS: Final = frozenset({"kind", "came_by", "placed_id", "placed_at_mm", "crossing"})
#: What a visitor's crossing record states; ``decided_by`` beside them only where its arrival said,
#: ``may_carry_out`` (true) only where its arrival said so in a society running hands, and, beside
#: that only, ``carries_out``, the kinds of the world's things its program can take.
_CROSSING_FIELDS: Final = frozenset({"arrival_id", "bridge", "grant_id"})
_CROSSING_MAY: Final = frozenset({"decided_by", "may_carry_out", "carries_out"})
#: What each carried-out placement states, so the thing is never put back while it stands.
_CARRIED_OUT_FIELDS: Final = frozenset({"placed_id", "kind", "placed_at_mm", "grant_id", "tick"})
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
#: A thing of a society running the hands module also states where its author placed it
#: (``placed_at_mm``, for a placed thing), so an author's move is told from a being's, and the
#: socket a being holds it in (``socket``, while held).
_THING_MAY: Final = frozenset({"brought_by", "height_mm", "placed_at_mm", "socket"})
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


def _things_of(document: Mapping[str, Any], *, hands: bool = False) -> list[dict[str, Any]]:
    """The society's things the input places: every object the author placed, in id order, each
    where it was placed, and, in a society running the hands module, stating that placement."""
    return [
        {
            "id": _thing_id(document["world_id"], entry["placed_id"]),
            "placed_id": entry["placed_id"],
            "kind": _reference(entry["kind"]),
            "position_mm": list(entry["position_mm"]),
            "yaw_microradians": entry["yaw_microradians"],
            "held_by": None,
            **({"height_mm": entry["height_mm"]} if "height_mm" in entry else {}),
            **({"placed_at_mm": list(entry["position_mm"])} if hands else {}),
        }
        for entry in placed_objects(document)
    ]


def _records_modules(state: Mapping[str, Any]) -> bool:
    """Whether a society's first input recorded the modules it runs: every society of things made
    since they were. One made before keeps recording its minutes as it did, so they replay."""
    return "modules" in state


def _runs_hands(state: Mapping[str, Any]) -> bool:
    """Whether a society's first input recorded the hands module, at any version, which its
    minutes then run."""
    from exulanica.abilities.registry import recorded_row

    return recorded_row(state.get("modules", ()), "hands") is not None


def _gone_home(thing: Mapping[str, Any], here: set[str]) -> bool:
    """Whether a thing on the ground goes home: one a visitor brought stays in a world only while
    its bringer is here or a being here holds it, so the things nobody placed are at most what the
    visitors here brought and what the beings here hold."""
    return (
        thing["placed_id"] is None and thing["held_by"] is None and thing["brought_by"] not in here
    )


def _placement(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    """A placement as the author made it: its id, its kind and where it was put."""
    return (entry["placed_id"], dict(entry["kind"]), list(entry["placed_at_mm"]))


def _carries_out(person: Mapping[str, Any], reason: str, extra: Mapping[str, Any] | None) -> bool:
    """Whether a leaving visitor carries out the world's placed things it holds: only where its
    arrival let it (``may_carry_out``), and only when it leaves by its own choice or its player
    calls it home; never when the world's owner sends it away, its grant ends or its program is
    lost."""
    crossing = person.get("crossing") or {}
    if person["came_by"] != "crossed" or crossing.get("may_carry_out") is not True:
        return False
    return reason == "chose_to_leave" or (
        reason == "sent_home" and (extra or {}).get("called_by") == "player"
    )


def _carry_out_room(state: Mapping[str, Any], grant_id: str) -> int:
    """How many more placed things the visitors of ``grant_id`` may carry out now: the bound less
    those carried out under it in the last :data:`CARRY_OUT_WINDOW_TICKS` minutes."""
    lately = sum(
        1
        for entry in state.get("carried_out", ())
        if entry["grant_id"] == grant_id and state["tick"] - entry["tick"] < CARRY_OUT_WINDOW_TICKS
    )
    return max(0, CARRY_OUT_MAXIMUM - lately)


def _moved_things(state: Mapping[str, Any], document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A hands society's things as the latest input places them: a placed thing the author left
    where it was stays as the society has it (held, or where a being put it down), and one nobody
    moved from its place takes the author's turn and height; one the author moved or changed is
    where the author put it, out of any hand; one the author removed is gone, from any hand; a new
    one is where it was placed; a thing a visitor carried out stays out while its placement
    stands; and a thing nobody placed (carried in) stays as it is."""
    current = {t["placed_id"]: t for t in state["things"] if t["placed_id"] is not None}
    gone = [_placement(entry) for entry in state.get("carried_out", ())]
    kept = []
    for entry in _things_of(document, hands=True):
        found = current.get(entry["placed_id"])
        if found is None and _placement(entry) in gone:
            continue
        if (
            found is None
            or found["kind"] != entry["kind"]
            or found["placed_at_mm"] != entry["placed_at_mm"]
        ):
            kept.append(entry)
            continue
        if found["held_by"] is None and found["position_mm"] == entry["position_mm"]:
            # Still where its author placed it: an edit's new turn or height applies to it.
            found = {key: value for key, value in found.items() if key != "height_mm"}
            found["yaw_microradians"] = entry["yaw_microradians"]
            if "height_mm" in entry:
                found["height_mm"] = entry["height_mm"]
        kept.append(found)
    return [*kept, *(thing for thing in state["things"] if thing["placed_id"] is None)]


def _newcomer(
    state: dict[str, Any],
    seed: str,
    document: Mapping[str, Any],
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
    # Where its society holds it to its kind, a being whose kind does not list what tiredness sends
    # it to is never tired.
    withheld = routine_withheld(state, {"kind": kind})
    tireless = bool(withheld) and never_tired(routine_of(document), withheld)
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
        "need_milli": 0 if tireless else 500 + _number(seed, "need", ordinal) % 401,
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
        self.previous_digest = society_state_sha256(previous)
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
        at_ms: int = 0,
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
            # The things phase takes effect as the minute begins (edits and crossings handed over
            # during the minute before it), but for a hands act, done the moment the later of its
            # parties' walks ends.
            "at_ms": at_ms,
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
        """``person`` leaves the society. In a society running hands, a visitor takes home what it
        brought, in its hands or wherever it stands here, but not what a being still here holds;
        a visitor whose arrival let it carry the world's things out, leaving by its own choice or
        called home by its player, also takes the placed things it holds, within its grant's bound
        (:func:`_carries_out`), and, where its arrival named the kinds its program can take
        (``carries_out``), only things of those kinds; everything else it holds, and everything a
        being of the world holds, is put down where it stood, and a thing put down whose bringer
        has left already goes home to it (:func:`_gone_home`). In a society without hands,
        whatever it holds leaves with it."""
        held = [thing for thing in self.state["things"] if thing["held_by"] == person["id"]]
        left: list[dict[str, Any]] = []
        returned: list[dict[str, Any]] = []
        kept_back: list[dict[str, Any]] = []
        limited = False
        if _runs_hands(self.state):
            carried = [
                thing
                for thing in self.state["things"]
                if person["came_by"] == "crossed"
                and thing.get("brought_by") == person["id"]
                and thing["held_by"] in (None, person["id"])
            ]
            if _carries_out(person, reason, extra):
                grant = person["crossing"]["grant_id"]
                placed = [thing for thing in held if thing["placed_id"] is not None]
                listed = person["crossing"].get("carries_out")
                if listed is not None:
                    # Only the kinds its program can take leave; the rest are put down, and the
                    # bound counts only what leaves.
                    kept_back = [t for t in placed if t["kind"]["kind"] not in listed]
                    placed = [t for t in placed if t["kind"]["kind"] in listed]
                room = _carry_out_room(self.state, grant)
                limited = len(placed) > room
                for thing in placed[:room]:
                    self.state["carried_out"] = [
                        *self.state.get("carried_out", ()),
                        {
                            "placed_id": thing["placed_id"],
                            "kind": dict(thing["kind"]),
                            "placed_at_mm": list(thing["placed_at_mm"]),
                            "grant_id": grant,
                            "tick": self.state["tick"],
                        },
                    ]
                carried = [*carried, *placed[:room]]
            left = [thing for thing in held if not any(thing is c for c in carried)]
            for thing in left:
                thing["held_by"] = None
                thing.pop("socket", None)
                thing["position_mm"] = list(person["position_mm"])
            staying = {other["id"] for other in self.state["inhabitants"] if other is not person}
            returned = [thing for thing in left if _gone_home(thing, staying)]
            left = [thing for thing in left if not any(thing is r for r in returned)]
        else:
            carried = held
        gone = [*carried, *returned]
        self.state["things"] = [
            thing for thing in self.state["things"] if not any(thing is g for g in gone)
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
                "carried": [
                    {
                        "id": thing["id"],
                        "kind": thing["kind"],
                        # A thing of the world it carried out names its placement.
                        **(
                            {"placed_id": thing["placed_id"]}
                            if thing["placed_id"] is not None
                            else {}
                        ),
                    }
                    for thing in carried
                ],
                # What stayed, put down where it stood: stated only where something did.
                **({"left": [thing["id"] for thing in left]} if left else {}),
                # The grant's bound held some of the world's things back: only where it did.
                **({"carry_out_limited": True} if limited else {}),
                # What it put down because its program cannot take that kind: only where any.
                **({"not_let_out": [thing["id"] for thing in kept_back]} if kept_back else {}),
                # What it put down that went home to a visitor that had left: only where any did.
                **({"returned": [thing["id"] for thing in returned]} if returned else {}),
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
            minute.document,
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
    if _runs_hands(state):
        state["things"] = _moved_things(state, document)
        if "carried_out" in state:
            # A carried-out placement the author has since moved, changed or removed no longer
            # keeps anything out; it is dropped once the bound no longer counts it either.
            standing = [_placement(entry) for entry in _things_of(document, hands=True)]
            state["carried_out"] = [
                entry
                for entry in state["carried_out"]
                if _placement(entry) in standing
                or state["tick"] - entry["tick"] < CARRY_OUT_WINDOW_TICKS
            ]
        return
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
        # Who decides for it here, where its arrival said.
        **({"decided_by": document["decided_by"]} if "decided_by" in document else {}),
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
        minute.document,
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
            # Whether it may carry the world's things out, as its arrival said: kept on the
            # visitor, so a later leaving reads it here and never the grant.
            **(
                {"may_carry_out": True}
                if document.get("may_carry_out") is True and _runs_hands(state)
                else {}
            ),
            # Which kinds of the world's things its program can take, as its arrival said: kept
            # beside may_carry_out only, and only where the arrival said.
            **(
                {"carries_out": list(document["carries_out"])}
                if "carries_out" in document
                and document.get("may_carry_out") is True
                and _runs_hands(state)
                else {}
            ),
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
                # With hands, the socket it is in, found from its holder's plan when first used,
                # and the visitor that brought it, which it goes home with.
                **({"socket": None, "brought_by": identity} if _runs_hands(state) else {}),
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
        person,
        _DEPARTURE_REASONS[document["reason"]],
        {
            "crossing_id": str(crossing.crossing_id),
            # Its player called it home, where the departure says so.
            **({"called_by": document["called_by"]} if "called_by" in document else {}),
        },
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
    state["refused_placements"] = []
    if "modules" in document:
        # The modules its first input records, which its minutes run for its whole life.
        state["modules"] = list(document["modules"])
    state["things"] = _things_of(document, hands=_runs_hands(state))
    minute = _Minute(state, state, seed, document, ())
    # The author's beings first, where they were put; then the population steps aside from them.
    _place_beings(minute, record=False, before_population=True)
    _population_steps_aside(state, document)
    validate_things_state(state)
    return state


def _population_steps_aside(state: dict[str, Any], document: Mapping[str, Any]) -> None:
    """At genesis, each person of the ground's population whose starting node a placed being took
    steps to the nearest node it could have been spread to (:func:`spawn_nodes`: clear of where a
    person arrives and of every destination) that nobody stands at, in ordinal order; one with
    nowhere to go stays where it was spread."""
    from exulanica.world.society_planner import spawn_nodes

    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    allowed = spawn_nodes(dict(document))
    taken = {
        person["location"]["node_id"]
        for person in state["inhabitants"]
        if person["came_by"] == "placed"
    }
    for person in state["inhabitants"]:
        if person["came_by"] != "populated" or person["location"]["node_id"] not in taken:
            continue
        held = {other["location"]["node_id"] for other in state["inhabitants"]}
        x, y = person["position_mm"]
        node = min(
            (node for node in allowed if node not in held),
            key=lambda node: ((nodes[node][0] - x) ** 2 + (nodes[node][1] - y) ** 2, node),
            default=None,
        )
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
    asked: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...], tuple[BoundCrossing, ...]]:
    """The things phase of a minute: ``state`` and ``events`` are the minute so far (the planner's,
    its directed requests' and its decisions'), ``previous`` the state it began from and
    ``document`` the input it consumed last. ``decisions`` are the receipts the minute consumed,
    each with what the minute did with it: an applied line is said, an applied leaving is carried
    out, an applied hands act is done by the hands step once the being stands within reach (where
    the society runs the hands module), and a visitor whose program stays quiet for as many minutes
    as its kind waits is sent home. ``asked`` are the hands acts the world's owner asked for and
    the minute applied (``exulanica.society-action-request/v2``), done the same way, each marked as
    asked.
    Answers the state, every event of the minute, and what became of each crossing, in the order
    they were handed over."""
    _require(state["profile"] == THINGS_PROFILE, "the things phase is a society of things'")
    _require(len(crossings) <= CROSSINGS_PER_MINUTE, "a minute takes a bounded number of crossings")
    # A hands society made before bringers were recorded holds a carried-in thing that names no
    # bringer, so whether it stays or goes home cannot be told: refused by name here rather than
    # failing part way through the minute.
    _require(
        not _runs_hands(state)
        or all("brought_by" in thing for thing in state["things"] if thing["placed_id"] is None),
        "a carried-in thing names no visitor that brought it: this society of things was made "
        "before bringers were recorded and cannot be played on",
    )
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
    if _runs_hands(result):
        _asked(minute, asked)
        _hands(minute, previous)
    if _remembers(result):
        _remember(minute, decisions)
    validate_things_state(result)
    return result, tuple(minute.events), tuple(bound)


#: The contract a society of things' lines were first said under: version 3 of the person's
#: action and policy catalogs. A minute reads how far a line carries and how many a being keeps
#: from it, never from whatever terms the registry states now, so a later version of the terms
#: leaves every stored minute replaying as it ran.
LINES_CONTRACT: Final = {"society-decision-action": 3, "society-decision-policy": 3}


def _remembers(state: Mapping[str, Any]) -> bool:
    """Whether a society of things records the memory module, at any version, so its minute writes
    what the beings a model or a program decides for remember."""
    from exulanica.abilities.registry import recorded_row

    return recorded_row(state.get("modules", ()), "remember") is not None


def _remember(minute: _Minute, decisions: Sequence[tuple[Mapping[str, Any], Any]]) -> None:
    """The memory step, last among the things phase's steps: the minute's events, every one in
    the order it recorded them, written into the recollections of the beings that keep one
    (:func:`exulanica.world.society_recollection.remember`). A being starts keeping one the first
    minute a model or a program decides for it: one a receipt the minute consumed names, or a
    visitor its own program decides for. Bounded by the row of the version the society recorded."""
    from exulanica.abilities.registry import recorded_row
    from exulanica.world.society_decision_contract import _activity_label
    from exulanica.world.society_planner import _input_value, routine_of
    from exulanica.world.society_recollection import RecollectionBounds, remember

    row = recorded_row(minute.state.get("modules", ()), "remember")
    assert row is not None
    bounds = RecollectionBounds(
        beings_maximum=row.value("beings_maximum"),
        places_maximum=row.value("places_maximum"),
        handed_maximum=row.value("handed_maximum"),
        bytes_maximum=row.value("bytes_maximum"),
    )
    minds = {str(receipt["subject_id"]) for receipt, _disposition in decisions}
    minds |= {person["id"] for person in minute.state["inhabitants"] if _program_decides(person)}
    document = minute.document
    routine = _input_value(
        document, ("recollection", "routine"), lambda: routine_of(dict(document))
    )
    remember(
        minute.state,
        minute.events,
        bounds,
        minds,
        lambda target: _activity_label(routine, target)[1],
    )


def _say_bounds() -> tuple[int, int]:
    """How far a line carries and how many lines a being keeps, as :data:`LINES_CONTRACT` states
    them."""
    from exulanica.world.society_decision_contract import person_role

    contract = person_role().contract(LINES_CONTRACT)
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
    from exulanica.world.deciders import receipt_decider
    from exulanica.world.society_decision_contract import hearers

    if not decisions:
        return
    reach, kept = _say_bounds()
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
        if option["kind"] in _HANDS_ACTS and _runs_hands(minute.state):
            # What its hands do, done by the hands step in the minute it stands within reach. An
            # act the world's owner asked for that it replaces is recorded as left undone.
            pending = person.get("hands")
            if pending is not None and pending.get("asked"):
                _missed(minute, person, "chose_otherwise")
            person["hands"] = {
                "ability": option["kind"],
                "thing": option["target_id"],
                "with": option.get("addressee_id"),
                "since": minute.state["tick"],
            }
            continue
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
            # A society made since modules were recorded also keeps the model behind a line, the
            # speaker's name as the page showed it, and what each being said; one made before keeps
            # exactly what its stored minutes recorded, so they replay.
            keeps = _records_modules(minute.state)
            said_by = _model_of(receipt) if keeps else None
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
                    "request_id": str(receipt["request_id"]),
                    "line": line,
                    "to": to,
                    "to_kind": None if addressee is None else dict(addressee["kind"]),
                    "to_number": None if addressee is None else addressee["ordinal"] + 1,
                    "from_kind": dict(person["kind"]),
                    "from_number": person["ordinal"] + 1,
                    "heard_by": heard_by,
                    # Who chose the line: a model, an outside program, or a person playing.
                    "decider": receipt_decider(receipt),
                    # The model a line's decider asked, where a model decided it.
                    **({"model": said_by} if said_by is not None else {}),
                },
            )
            heard = {
                "tick": minute.state["tick"],
                "from": person["id"],
                "from_kind": dict(person["kind"]),
                "from_number": person["ordinal"] + 1,
                # The name the page shows for the speaker as it said it.
                **({"from_name": person["display_name"]} if keeps else {}),
                "to": to,
                "line": line,
                **({"model": dict(said_by)} if said_by is not None else {}),
            }
            for hearer in minute.state["inhabitants"]:
                if hearer["id"] in heard_by:
                    hearer["heard"] = [*hearer.get("heard", ()), dict(heard)][-kept:]
            # The speaker keeps what it said as many as a being keeps of what it heard, so its
            # decider is shown what it already said.
            said = {
                "tick": minute.state["tick"],
                "to": to,
                "to_name": None if addressee is None else addressee["display_name"],
                "to_kind": None if addressee is None else dict(addressee["kind"]),
                "line": line,
            }
            if keeps:
                person["said"] = [*person.get("said", ()), said][-kept:]
    for person in list(minute.state["inhabitants"]):
        limit = _quiet_limit(person) if _program_decides(person) else None
        if limit is not None and person.get("quiet_minutes", 0) >= limit:
            minute.leave(person, "decider_lost")


def _asked(minute: _Minute, asked: Sequence[Mapping[str, Any]]) -> None:
    """Each hands act the world's owner asked for and the minute applied: the being's intent, as a
    decider's applied act sets it, marked as asked, for the hands step to do once it stands within
    reach. A request is applied only for a being nobody else decided for this minute."""
    for request in asked:
        person = next(
            (p for p in minute.state["inhabitants"] if p["id"] == request["subject_id"]), None
        )
        if person is None:
            continue
        intent = request["intent"]
        if person.get("hands") is not None:
            # A pending act the request replaces is recorded as left undone.
            _missed(minute, person, "asked_otherwise")
        person["hands"] = {
            "ability": intent["ability"],
            "thing": intent["thing_id"],
            "with": intent["with_id"],
            "since": minute.state["tick"],
            "asked": True,
        }


def _missed(minute: _Minute, person: dict[str, Any], reason: str) -> None:
    """The being's pending hands act left undone, by name: ``hands_missed`` naming the act, and
    for an act the world's owner asked for, ``asked`` (only then, so a decider's act is recorded
    as it always was)."""
    intent = person.pop("hands")
    minute.emit(
        "hands_missed",
        person["id"],
        reason,
        "not_done",
        person=person,
        name=person["display_name"],
        details={
            "ability": intent["ability"],
            "thing": intent["thing"],
            "with": intent["with"],
            **({"asked": True} if intent.get("asked") else {}),
        },
    )


def _model_of(receipt: Mapping[str, Any]) -> dict[str, str] | None:
    """The model a receipt's request asked, by provider and identifier, where a model answered it;
    None for an outside program's answer."""
    provider = receipt.get("provider")
    if not isinstance(provider, Mapping) or provider.get("kind") == "external":
        return None
    named = (provider.get("provider"), provider.get("model_id"))
    if not all(isinstance(value, str) for value in named):
        return None
    return {"provider": provider["provider"], "model_id": provider["model_id"]}


def _walked_mm(person: Mapping[str, Any]) -> int:
    """How far a being walked this minute, along the path its minute drew."""
    path = person["motion_path_mm"]
    return sum(math.isqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) for a, b in pairwise(path))


def _hands(minute: _Minute, previous: Mapping[str, Any]) -> None:
    """Each hands act a being's decider chose, in the order of the beings' numbers: done in the
    minute the being stands within the module's reach of the thing, or within the hand-over
    distance (``hand_over_mm``) of the being it gives to or takes from, where the minute's walks
    ended; dropped, by name, when the thing or the other
    being is gone (``thing_gone``) or the module's minutes of walking pass first
    (``out_of_reach``). An act done names the moment within the minute (``at_ms``) the later of
    its parties' walks ended, at the society's recorded pace: 0 where both stood within reach as
    the minute began (the hand-over rule agreed with the renderer)."""
    from exulanica.world.society_hands import (
        acts_open,
        carry_out,
        hand_over_mm,
        reach_mm,
        walk_minutes_maximum,
    )

    state = minute.state
    began = {person["id"]: person for person in previous["inhabitants"]}
    budget = state["movement_budget_mm_per_tick"]
    taken: set[str] = set()
    for person in sorted(state["inhabitants"], key=lambda p: p["ordinal"]):
        intent = person.get("hands")
        if intent is None:
            continue
        chosen = (intent["ability"], intent["thing"], intent["with"])
        found = next(
            (
                act
                for act in acts_open(state, person, minute.document, taken=frozenset(taken))
                if (act.ability, act.thing_id, act.other_id) == chosen
            ),
            None,
        )
        if found is None and person["id"] in began:
            # Within reach as the minute began, though a walk then took one of them away: done as
            # the minute began (at_ms 0), so an act chosen while walking is not missed.
            moved = {
                **state,
                "inhabitants": [_as_began(other, began) for other in state["inhabitants"]],
            }
            found = next(
                (
                    act
                    for act in acts_open(
                        moved, _as_began(person, began), minute.document, taken=frozenset(taken)
                    )
                    if (act.ability, act.thing_id, act.other_id) == chosen
                ),
                None,
            )
        reason = ("asked_to_" if intent.get("asked") else "chose_to_") + intent["ability"]
        if found is None:
            things = {thing["id"] for thing in state["things"]}
            here = {other["id"] for other in state["inhabitants"]}
            gone = intent["thing"] not in things or (
                intent["with"] is not None and intent["with"] not in here
            )
            if not gone and state["tick"] - intent["since"] < walk_minutes_maximum():
                continue
            _missed(minute, person, "thing_gone" if gone else "out_of_reach")
            continue
        parties = [person] + [
            other for other in state["inhabitants"] if other["id"] == found.other_id
        ]
        started = began.get(person["id"], person)
        already = found.other_id is None or all(p["id"] in began for p in parties)
        at_ms = 0
        within = reach_mm() if found.other_id is None else hand_over_mm(minute.document)
        if not (
            already
            and _distance_mm(started["position_mm"], _target_point(previous, found)) <= within
        ):
            walked = max(_walked_mm(party) for party in parties)
            at_ms = min(59_999, -(-walked * 60_000 // budget)) if budget > 0 else 0
        details = carry_out(state, found, at=person["position_mm"])
        taken.add(found.thing_id)
        put = next(thing for thing in state["things"] if thing["id"] == found.thing_id)
        if _gone_home(put, {other["id"] for other in state["inhabitants"]}):
            # Put down after the visitor that brought it left: it goes home to it.
            state["things"] = [thing for thing in state["things"] if thing is not put]
            details = {**details, "returned": True}
        person.pop("hands")
        minute.emit(
            _HANDS_ACTS[found.ability],
            person["id"],
            reason,
            _HANDS_ACTS[found.ability],
            person=person,
            name=person["display_name"],
            details={"ability": found.ability, **details},
            at_ms=at_ms,
        )


def _as_began(person: Mapping[str, Any], began: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """``person`` where it stood as the minute began, where it was here then."""
    then = began.get(person["id"])
    return dict(person) if then is None else {**person, "position_mm": then["position_mm"]}


def _distance_mm(a: Sequence[int] | None, b: Sequence[int] | None) -> int:
    if a is None or b is None:
        return 1 << 62
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _target_point(state: Mapping[str, Any], act: Any) -> Sequence[int] | None:
    """Where what an act is for stood in ``state``: the other being, or the thing on the ground;
    the actor's own place for putting down."""
    target = act.other_id if act.other_id is not None else act.thing_id
    if act.ability == "put_down":
        target = act.actor_id
    for person in state["inhabitants"]:
        if person["id"] == target:
            return person["position_mm"]
    for thing in state["things"]:
        if thing["id"] == target:
            return thing["position_mm"]
    return None


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


_HEARD_FIELDS: Final = frozenset({"tick", "from", "from_kind", "from_number", "to", "line"})
#: What a heard line may state beside those: the model that wrote it, and the name the page showed
#: for its speaker as it was said.
_HEARD_MAY: Final = frozenset({"model", "from_name"})
_SAID_FIELDS: Final = frozenset({"tick", "to", "to_name", "to_kind", "line"})
#: The longest name a heard or said line keeps for a being: a kind's label and a number.
_NAME_MAXIMUM: Final = 120


def _optional_lines(person: Mapping[str, Any]) -> None:
    """The lines a being heard, stated only once it heard one (oldest first, each with when, who
    said it, by kind and number, to whom and the line itself), the lines it said, stated only once
    it said one (oldest first, each with when, to whom and the line), and a visitor's quiet minutes,
    stated only while its program has been quiet."""
    from exulanica.things.lines import LineRefused, check_line

    heard = person.get("heard")
    if heard is not None:
        _require(
            isinstance(heard, list) and 1 <= len(heard) <= HEARD_LINES_MAXIMUM,
            "a being states the lines it heard only once it heard one",
        )
        ticks = [entry.get("tick") if isinstance(entry, dict) else None for entry in heard]
        for entry in heard:
            _require(
                isinstance(entry, dict)
                and set(entry) - _HEARD_MAY == _HEARD_FIELDS
                and (
                    "from_name" not in entry
                    or (
                        isinstance(entry["from_name"], str)
                        and 1 <= len(entry["from_name"]) <= _NAME_MAXIMUM
                    )
                )
                and (
                    "model" not in entry
                    or (
                        isinstance(entry["model"], dict)
                        and set(entry["model"]) == {"provider", "model_id"}
                        and all(isinstance(v, str) and v for v in entry["model"].values())
                    )
                )
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
    said = person.get("said")
    if said is not None:
        _require(
            isinstance(said, list) and 1 <= len(said) <= HEARD_LINES_MAXIMUM,
            "a being states the lines it said only once it said one",
        )
        for entry in said:
            _require(
                isinstance(entry, dict)
                and set(entry) == _SAID_FIELDS
                and type(entry["tick"]) is int
                and (entry["to"] is None) == (entry["to_name"] is None)
                and (entry["to"] is None) == (entry["to_kind"] is None)
                and (entry["to_kind"] is None or _reference_shape(entry["to_kind"]))
                and (entry["to"] is None or isinstance(entry["to"], str))
                and (
                    entry["to_name"] is None
                    or (
                        isinstance(entry["to_name"], str)
                        and 1 <= len(entry["to_name"]) <= _NAME_MAXIMUM
                    )
                ),
                "invalid said line",
            )
            try:
                check_line(entry["line"])
            except LineRefused as exc:
                raise ValueError("a said line is held to the line rule") from exc
        said_ticks = [entry["tick"] for entry in said]
        _require(said_ticks == sorted(said_ticks), "a being's said lines are oldest first")
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
    if "modules" in state:
        from exulanica.abilities.registry import AbilityError, recorded_modules

        modules = state["modules"]
        _require(
            isinstance(modules, list) and bool(modules) and modules == sorted(set(modules)),
            "a society of things states the modules it runs once each, sorted",
        )
        try:
            recorded_modules(state)
        except AbilityError as exc:
            raise ValueError(f"a society of things runs built modules only: {exc}") from exc
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
        if "recollection" in person:
            from exulanica.world.society_recollection import validate_recollection

            _require(_remembers(state), "only a society running memory keeps a recollection")
            try:
                validate_recollection(person["recollection"])
            except ValueError as exc:
                raise ValueError(f"a being's recollection is out of shape: {exc}") from exc
        intent = person.get("hands")
        _require(
            intent is None
            or (
                _runs_hands(state)
                and isinstance(intent, dict)
                # ``asked``, only ever true, marks an act the world's owner asked for.
                and set(intent) - {"asked"} == {"ability", "thing", "with", "since"}
                and intent.get("asked", True) is True
                and intent["ability"] in _HANDS_ACTS
                and isinstance(intent["thing"], str)
                and (intent["with"] is None or isinstance(intent["with"], str))
                and type(intent["since"]) is int
                and 0 <= intent["since"] <= state["tick"]
            ),
            "a being states a hands act it was chosen to do only in a society running hands",
        )
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
                and set(crossing) - _CROSSING_MAY == _CROSSING_FIELDS
                and crossing.get("decided_by", "program") in DECIDED_BY
                and crossing.get("may_carry_out", True) is True
                and ("may_carry_out" not in crossing or _runs_hands(state))
                and (
                    "carries_out" not in crossing
                    or (
                        crossing.get("may_carry_out") is True
                        and is_carry_out_list(crossing["carries_out"])
                    )
                )
            ),
            "a visitor's crossing names its arrival, bridge and grant, who decides for it, and "
            "whether it may carry the world's things out, and which",
        )
    things = state["things"]
    hands = _runs_hands(state)
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
        if not hands:
            _require(
                "placed_at_mm" not in thing and "socket" not in thing and "brought_by" not in thing,
                "only a society running the hands module states placements, sockets and bringers",
            )
            _require(
                (thing["placed_id"] is None) == (thing["held_by"] is not None),
                "a thing stands where it was placed until somebody holds it",
            )
            continue
        # With hands, a thing is held or on the ground, a placed one states where its author put
        # it, and a held one the socket it is in.
        _require(
            ("placed_at_mm" in thing) == (thing["placed_id"] is not None)
            and ("placed_at_mm" not in thing or _point_shape(thing["placed_at_mm"])),
            "a placed thing states where its author put it, and nothing else does",
        )
        _require(
            (thing["position_mm"] is None) == (thing["held_by"] is not None)
            and (thing["position_mm"] is None or _point_shape(thing["position_mm"])),
            "a thing is held by somebody or stands on the ground",
        )
        _require(
            ("socket" in thing) == (thing["held_by"] is not None)
            and (
                "socket" not in thing or thing["socket"] is None or isinstance(thing["socket"], str)
            ),
            "a held thing states the socket it is in",
        )
        _require(
            ("brought_by" in thing) == (thing["placed_id"] is None)
            and ("brought_by" not in thing or isinstance(thing["brought_by"], str)),
            "a thing nobody placed states the visitor that brought it",
        )
        _require(
            thing["placed_id"] is not None
            or thing["held_by"] is not None
            or thing["brought_by"] in present,
            "a thing a visitor brought stays only while its bringer is here or a being holds it",
        )
    carried_out = state.get("carried_out")
    _require(
        carried_out is None
        or (
            hands
            and isinstance(carried_out, list)
            and all(
                isinstance(entry, dict)
                and set(entry) == _CARRIED_OUT_FIELDS
                and isinstance(entry["placed_id"], str)
                and _reference_shape(entry["kind"])
                and _point_shape(entry["placed_at_mm"])
                and isinstance(entry["grant_id"], str)
                and type(entry["tick"]) is int
                and 0 <= entry["tick"] <= state["tick"]
                for entry in carried_out
            )
        ),
        "only a society running hands states what visitors carried out, each by its placement",
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
