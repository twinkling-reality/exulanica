"""Hands in a society of things: ``exulanica-ability/hands/v1`` and ``v2``.

A being whose kind has the hands abilities uses its body plan's sockets: it picks a holdable thing
up into a free socket that fits it, puts what it holds down where it stands, hands a held thing to
a being that offers to receive it and has a free socket that fits, or takes a held thing from a
being that lets it be taken. Each happens with the thing, or the other being, within the module's
reach (``reach_mm``) of where the being stands. A thing farther away, within ``approach_mm``, is
offered too where an open node of the walking graph stands within reach of it: the being walks to
that node first and acts in the minute it arrives, for at most ``walk_minutes_maximum`` minutes.
Version 1 walks it to the open node nearest the thing or the other being; version 2 to the one
within reach nearest the being itself, so it comes up on its own side and never walks past or
through what it acts on. The two state the same abilities, figures and events. A
thing fits a socket when its longest side is within the socket's length; a thing that needs two
hands is not held in this version.

What this module states is pure: which acts are offered to a being in a state
(:func:`acts_offered`), which are open where it stands now (:func:`acts_open`), and what an act
does to the state (:func:`carry_out`). The society of things runs it only where its first input
recorded the module, and only a being's decider chooses a hands act: the routine never does, as it
never says anything.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.abilities.registry import HANDS, ability_module, recorded_row
from exulanica.things.catalogs import Socket, thing_catalogs
from exulanica.world.placed_things import ThingKindReference, shipped_kind

__all__ = [
    "ACTS",
    "HANDS_EVENT_KINDS",
    "HandsAct",
    "HandsOffer",
    "acts_offered",
    "acts_open",
    "approach_mm",
    "approach_node",
    "carry_out",
    "hand_over_mm",
    "reach_mm",
    "socket_of_held",
    "walk_minutes_maximum",
]

#: Each act, by the ability it is, with the event its minute records.
ACTS: Final = {"pick_up": "picked_up", "put_down": "put_down", "give": "gave", "take": "took"}
HANDS_EVENT_KINDS: Final = tuple(ACTS.values())


@dataclass(frozen=True, slots=True)
class HandsAct:
    """One act a being may do with its hands now: the ability, the thing and, for giving or taking,
    the other being; the socket it ends in; and how far the thing or the other being is."""

    ability: str
    actor_id: str
    thing_id: str
    other_id: str | None
    #: The socket the thing ends in: the actor's for picking up or taking, the other's for giving,
    #: none for putting down.
    socket: str | None
    distance_mm: int


def reach_mm() -> int:
    """How near the thing or the other being stands, as the module's row states it."""
    return ability_module(HANDS).value("reach_mm")


def approach_mm() -> int:
    """How far a thing or another being may be for an act to be offered, walking first."""
    return ability_module(HANDS).value("approach_mm")


def walk_minutes_maximum() -> int:
    """How many minutes a being walks toward an act before it is dropped."""
    return ability_module(HANDS).value("walk_minutes_maximum")


@dataclass(frozen=True, slots=True)
class HandsOffer:
    """An act offered to a being, and where it walks to do it: None where it acts where it
    stands, else the open node within reach of the thing or the other being."""

    act: HandsAct
    approach_node: str | None


def _where(state: Mapping[str, Any], target_id: str) -> Sequence[int] | None:
    """Where a thing on the ground or a being stands; None for a held thing or nobody here."""
    for person in state["inhabitants"]:
        if person["id"] == target_id:
            return person["position_mm"]
    for thing in state["things"]:
        if thing["id"] == target_id:
            return None if thing["held_by"] is not None else thing["position_mm"]
    return None


def approach_node(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    being: Mapping[str, Any],
    target_id: str,
) -> str | None:
    """The open node a being walks to so as to stand within reach of ``target_id``, one nobody
    else stands at or is headed to; None where none is, or the target is held or gone. Under the
    hands module's first version, the open node nearest the target, when that node is within reach
    of it; under the second, of the open nodes within reach of it the one nearest the being, by
    squared distance and then node id, first among the nodes nobody waiting would be in the way
    at, so the being comes up on its own side."""
    from exulanica.world.society_planner import open_ground, open_node_near

    point = _where(state, target_id)
    if point is None:
        return None
    others = [person for person in state["inhabitants"] if person["id"] != being["id"]]
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    being_there = any(person["id"] == target_id for person in state["inhabitants"])
    within = hand_over_mm(document) if being_there else reach_mm()
    row = recorded_row(state.get("modules", ()), "hands")
    if row is not None and row.version >= 2:
        x, z = being["position_mm"]
        for pool in open_ground(dict(document), others):
            near = [
                ((nodes[node][0] - x) ** 2 + (nodes[node][1] - z) ** 2, node)
                for node in pool
                if _distance(nodes[node], point) <= within
            ]
            if near:
                return min(near)[1]
        return None
    node = open_node_near(dict(document), others, list(point))
    if node is None:
        return None
    return node if _distance(nodes[node], point) <= within else None


def acts_offered(
    state: Mapping[str, Any], document: Mapping[str, Any], being: Mapping[str, Any]
) -> list[HandsOffer]:
    """Every act offered to ``being``, nearest first: each open where it stands, and each within
    the approach distance it can walk to stand within reach of, with the node it walks to. A held
    thing's hands acts (putting it down, giving it) and a thing another holds (taking it) follow
    the same rule by where the other being stands."""
    reach, near = reach_mm(), approach_mm()
    widened = {**dict(being), "position_mm": list(being["position_mm"])}
    found: list[HandsOffer] = []
    between = hand_over_mm(document)
    for act in _acts_within(state, widened, near):
        within = between if act.ability in ("give", "take") else reach
        if act.distance_mm <= within or act.ability == "put_down":
            found.append(HandsOffer(act, None))
            continue
        target = act.other_id if act.ability in ("give", "take") else act.thing_id
        assert target is not None
        node = approach_node(state, document, being, target)
        if node is not None:
            found.append(HandsOffer(act, node))
    return found


def _kind(reference: Mapping[str, Any]) -> Any:
    return shipped_kind(ThingKindReference(**reference))


def _abilities(kind: Any) -> frozenset[str]:
    return frozenset(str(ability["key"]) for ability in kind.document["abilities"])


def _offers(kind: Any) -> Mapping[str, Mapping[str, Any]]:
    return {str(offer["key"]): offer["parameters"] for offer in kind.document["offers"]}


def _sockets(kind: Any) -> tuple[Socket, ...]:
    plan = thing_catalogs().plans.get(str(kind.document["body"]["plan"]))
    return () if plan is None else plan.sockets


def _length_mm(kind: Any) -> int:
    """A rigid thing's longest side."""
    box = kind.document["body"].get("box_mm")
    return 0 if box is None else max(int(box["width"]), int(box["depth"]), int(box["height"]))


def _distance(a: Sequence[int], b: Sequence[int]) -> int:
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def socket_of_held(state: Mapping[str, Any], thing: Mapping[str, Any]) -> str | None:
    """The socket a held thing is in: the one its state names, or, for one held before sockets
    were stated (what a visitor carried in), the first of its holder's sockets that it fits and
    neither a named one nor such a thing before it in the state's order takes, so two things carried
    in are in two sockets."""
    if thing["held_by"] is None:
        return None
    if thing.get("socket") is not None:
        return str(thing["socket"])
    holder = next((p for p in state["inhabitants"] if p["id"] == thing["held_by"]), None)
    if holder is None:
        return None
    held = [other for other in state["things"] if other["held_by"] == holder["id"]]
    taken = {other["socket"] for other in held if other.get("socket") is not None}
    sockets = _sockets(_kind(holder["kind"]))
    for other in held:
        if other.get("socket") is not None:
            continue
        length = _length_mm(_kind(other["kind"]))
        found = next(
            (
                socket.key
                for socket in sockets
                if socket.key not in taken and length <= socket.length_mm_maximum
            ),
            None,
        )
        if other is thing or other["id"] == thing["id"]:
            return found
        if found is not None:
            taken.add(found)
    return None


def _free_socket(state: Mapping[str, Any], being: Mapping[str, Any], thing_kind: Any) -> str | None:
    """The first socket of ``being`` that holds nothing and fits a one-handed thing of
    ``thing_kind``, in its plan's order; None where none does, or the thing needs two hands."""
    holdable = _offers(thing_kind).get("holdable")
    if holdable is None or int(holdable.get("hands", 1)) != 1:
        return None
    taken = {
        socket_of_held(state, thing) for thing in state["things"] if thing["held_by"] == being["id"]
    }
    length = _length_mm(thing_kind)
    return next(
        (
            socket.key
            for socket in _sockets(_kind(being["kind"]))
            if socket.key not in taken and length <= socket.length_mm_maximum
        ),
        None,
    )


def acts_open(
    state: Mapping[str, Any],
    being: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    taken: frozenset[str] = frozenset(),
) -> list[HandsAct]:
    """Every act ``being`` may do with its hands where it stands now, nearest first, then by
    ability and ids: none for a being whose kind lacks the ability. A thing is within the
    module's reach; another being within :func:`hand_over_mm`. ``taken`` holds the things another
    act already took this minute, which none may act on again."""
    return _acts_within(state, being, reach_mm(), between=hand_over_mm(document), taken=taken)


def hand_over_mm(document: Mapping[str, Any]) -> int:
    """How near two beings stand to hand a thing over: the module's reach, or, where the input's
    walking graph spaces its nodes farther apart than that, its longest step between two joined
    nodes, so beings standing on neighbouring nodes can always hand over."""
    navigation = document["navigation"]
    nodes = {node["node_id"]: node["position_mm"] for node in navigation["nodes"]}
    steps = (
        _distance(nodes[edge["from_node_id"]], nodes[edge["to_node_id"]])
        for edge in navigation["edges"]
    )
    return max([reach_mm(), *steps])


def _acts_within(
    state: Mapping[str, Any],
    being: Mapping[str, Any],
    reach: int,
    *,
    between: int | None = None,
    taken: frozenset[str] = frozenset(),
) -> list[HandsAct]:
    """Every act ``being``'s hands could do with a thing within ``reach`` of it, or with a being
    within ``between`` of it (``reach`` where none is given)."""
    between = reach if between is None else between
    if "kind" not in being:
        return []
    abilities = _abilities(_kind(being["kind"])) & set(ACTS)
    if not abilities:
        return []
    here = being["position_mm"]
    people = {person["id"]: person for person in state["inhabitants"]}
    found: list[HandsAct] = []
    for thing in state["things"]:
        if thing["id"] in taken:
            continue
        thing_kind = _kind(thing["kind"])
        holder = thing["held_by"]
        if holder is None:
            if "pick_up" not in abilities or "holdable" not in _offers(thing_kind):
                continue
            # Distance first: only a thing within reach is worth a search of the being's sockets.
            distance = _distance(here, thing["position_mm"])
            if distance > reach or "height_mm" in thing:
                continue
            socket = _free_socket(state, being, thing_kind)
            if socket is not None:
                found.append(HandsAct("pick_up", being["id"], thing["id"], None, socket, distance))
        elif holder == being["id"]:
            if "put_down" in abilities:
                found.append(HandsAct("put_down", being["id"], thing["id"], None, None, 0))
            if "give" in abilities:
                for other in state["inhabitants"]:
                    if other["id"] == being["id"]:
                        continue
                    distance = _distance(here, other["position_mm"])
                    if distance > between or "receive" not in _offers(_kind(other["kind"])):
                        continue
                    socket = _free_socket(state, other, thing_kind)
                    if socket is not None:
                        found.append(
                            HandsAct(
                                "give", being["id"], thing["id"], other["id"], socket, distance
                            )
                        )
        elif "take" in abilities and holder in people:
            other = people[holder]
            distance = _distance(here, other["position_mm"])
            socket = _free_socket(state, being, thing_kind)
            if (
                distance <= between
                and socket is not None
                and "let_take" in _offers(_kind(other["kind"]))
            ):
                found.append(HandsAct("take", being["id"], thing["id"], holder, socket, distance))
    return sorted(
        found, key=lambda act: (act.distance_mm, act.ability, act.thing_id, act.other_id or "")
    )


def carry_out(state: dict[str, Any], act: HandsAct, *, at: Sequence[int]) -> dict[str, Any]:
    """Do ``act`` to ``state``, in place: the thing in the socket it ends in, held by whom it ends
    with, or, put down, on the ground at ``at``, where the actor stood. Answers the event's
    details."""
    thing = next(thing for thing in state["things"] if thing["id"] == act.thing_id)
    left = socket_of_held(state, thing)
    if act.ability == "put_down":
        thing["held_by"] = None
        thing.pop("socket", None)
        thing["position_mm"] = list(at)
    else:
        thing["held_by"] = act.other_id if act.ability == "give" else act.actor_id
        thing["socket"] = act.socket
        # A held thing is where its holder is: it states no place of its own.
        thing["position_mm"] = None
    details: dict[str, Any] = {
        "thing": thing["id"],
        "thing_kind": dict(thing["kind"]),
        "socket": act.socket,
        "left_socket": left,
        "with": act.other_id,
    }
    return details
