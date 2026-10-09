"""Following in a society of things: ``exulanica-ability/follow/v2``.

A being whose kind lists follow may follow another being whose kind offers to be followed. Its
decider chooses to follow one; from that minute the being keeps near it, re-planned each minute it
has nothing else under way: within the module's ``follow_distance_mm`` of the one it follows it
waits where it stands, and farther off it walks to the open node within that distance of it nearest
itself, standing there until the next minute re-plans (a stand it is in ends for the walk, as a
request ends a stay). It stops when its decider chooses anything but going on or saying something
(``chose_otherwise``) or chooses to stop (``chose_to_stop_following``), when the one it follows is
no longer here (``target_gone``), or after ``lost_after_minutes`` minutes in a row ending with it
farther off than that distance and no open node within it (``lost_target``).

What this module states is pure: whether a society runs it, the goal policy a follower's minute is
given (:func:`follow_goal_policy`), and the node it walks to (:func:`approach_node`). The society of
things runs it only where its first input recorded the module (societies made since it was built),
so every society made before replays as it ran. Only a being's decider chooses to follow; the
routine never does, and the world's owner's direct requests do not ask it.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Final

from exulanica.abilities.registry import AbilityModule, recorded_row
from exulanica.world.placed_things import ThingKindReference, shipped_kind

__all__ = [
    "FOLLOW_EVENT_KINDS",
    "KEEPS_FOLLOWING",
    "approach_node",
    "follow_goal_policy",
    "follow_row",
    "followable",
    "runs_follow",
]

#: The events a society running the module records: a being began following another, or stopped.
FOLLOW_EVENT_KINDS: Final = ("followed", "stopped_following")
#: The choices a follower may make and go on following: going on, and saying something.
KEEPS_FOLLOWING: Final = frozenset({"carry_on", "say_to", "say_all"})


def follow_row(state: Mapping[str, Any]) -> AbilityModule | None:
    """The follow module's row at the version the society recorded; None where it recorded none."""
    return recorded_row(state.get("modules", ()), "follow")


def runs_follow(state: Mapping[str, Any]) -> bool:
    """Whether a society's first input recorded the follow module, which its minutes then run."""
    return follow_row(state) is not None


def _kind_document(reference: Mapping[str, Any]) -> Mapping[str, Any]:
    return shipped_kind(ThingKindReference(**reference)).document


def followable(follower: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    """Whether ``follower``'s kind lists follow and ``other``'s offers to be followed."""
    if "kind" not in follower or "kind" not in other or follower["id"] == other["id"]:
        return False
    follows = any(a["key"] == "follow" for a in _kind_document(follower["kind"])["abilities"])
    offered = any(o["key"] == "be_followed" for o in _kind_document(other["kind"])["offers"])
    return follows and offered


def _distance(a: Sequence[int], b: Sequence[int]) -> int:
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def approach_node(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    follower: Mapping[str, Any],
    target: Mapping[str, Any],
    within_mm: int,
    promised: Collection[str] = (),
) -> str | None:
    """The open node within ``within_mm`` of ``target`` nearest ``follower``, by squared distance
    and then node id, first among the nodes nobody waiting would be in the way at: one nobody else
    stands at or is headed to, no activity's place, and none ``promised`` to another this minute.
    None where there is none."""
    from exulanica.world.society_planner import open_ground

    others = [person for person in state["inhabitants"] if person["id"] != follower["id"]]
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    x, z = follower["position_mm"]
    point = target["position_mm"]
    for pool in open_ground(dict(document), others):
        near = [
            ((nodes[node][0] - x) ** 2 + (nodes[node][1] - z) ** 2, node)
            for node in pool
            if node not in promised and _distance(nodes[node], point) <= within_mm
        ]
        if near:
            return min(near)[1]
    return None


def follow_goal_policy(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject: str,
    target_id: str,
    promised: Collection[str] = (),
) -> dict[str, Any] | str | None:
    """The planner's goal policy for a follower's minute, from where everybody stood as it began:
    ``thing_gone`` where the one followed is not here or does not offer to be followed; within the
    follow distance, a wait where the follower has nothing under way and no policy otherwise (it
    goes on with what it is doing); farther off, a stand at :func:`approach_node`, marked with whom
    it follows so the planner ends a stand under way for it; and, with no such node or no standing
    activity, the same as within the distance."""
    from exulanica.world.society_decision_contract import (
        CHOSEN_BY_MODEL,
        at_choice_point,
        stand_activity,
    )

    row = follow_row(state)
    people = {person["id"]: person for person in state["inhabitants"]}
    follower, target = people.get(subject), people.get(target_id)
    if row is None or follower is None or target is None or not followable(follower, target):
        return "thing_gone"
    within = row.value("follow_distance_mm")
    idle = {"allowed_target_ids": [], "wait": True} if at_choice_point(follower) else None
    if _distance(follower["position_mm"], target["position_mm"]) <= within:
        return idle
    node = approach_node(state, document, follower, target, within, promised)
    stand = stand_activity(document)
    if node is None or stand is None:
        return idle
    return {
        "allowed_target_ids": [],
        "activity": stand.key,
        "place_node_id": node,
        "chosen_by": CHOSEN_BY_MODEL,
        "follow": target_id,
    }
