"""The things an input of the society of things carries: what the world's author placed, by kind.

An ``exulanica.society-input/authored-ground-v5`` input lists every thing placed in its region and
not removed, in id order (:mod:`exulanica.world.placed_things`). Each entry states what the thing's
kind says it is and does, its semantics (:meth:`exulanica.things.kinds.ThingKind.semantics`, which
never holds a look), where it stands on the ground, which way it faces, and, for a gate, the point
visitors arrive at, turned with it. A thing that does not rest on the ground also states how high
above the ground's elevation it stands (``height_mm``); one on the ground states none. The kind's
semantics ride in the input, so a stored society replays from its inputs alone and never reads the
kind library again.

What the society does with them is :mod:`exulanica.world.society_things`'s: a placed being lives
there, a placed object is one of the society's things, and its obstacle and activity are already
the input's navigation and targets, composed by :mod:`exulanica.world.society_authored_ground`.

Pure: no connection and no library read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.world.objects import MAX_YAW_MICRORADIANS
from exulanica.world.placed_things import PLACED_THING_ID_PATTERN

__all__ = [
    "ENTRY_FIELDS",
    "SEMANTIC_FIELDS",
    "THINGS_BOUND",
    "arrival_points",
    "input_things",
    "placed_beings",
    "placed_objects",
    "validate_input_things",
]

#: The fields of one placed thing as an input states it, and the one it states only off the ground.
ENTRY_FIELDS: Final = frozenset(
    {"placed_id", "kind", "position_mm", "yaw_microradians", "arrival_mm"}
)
OFF_GROUND_FIELD: Final = "height_mm"
#: What a kind's semantics hold: its document without its looks, origin, summary and ``ext``, and
#: its reference by key, version and digest.
SEMANTIC_FIELDS: Final = frozenset(
    {
        "profile",
        "kind",
        "version",
        "label",
        "class",
        "body",
        "moves",
        "abilities",
        "offers",
        "routine",
        "deciders",
        "reference",
    }
)
#: The most things one input states, the bound every list of an input shares.
THINGS_BOUND: Final = 4096
_PLACED_ID: Final = re.compile(PLACED_THING_ID_PATTERN)
_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_COORDINATE: Final = 10**9


def _point(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(type(v) is int and -_COORDINATE <= v <= _COORDINATE for v in value)
    )


def _offers(kind: Mapping[str, Any]) -> set[str]:
    return {offer["key"] for offer in kind["offers"]}


def _check_reference(reference: Any, what: str) -> None:
    if (
        not isinstance(reference, dict)
        or set(reference) != {"kind", "version", "sha256"}
        or not isinstance(reference["kind"], str)
        or _KEY.fullmatch(reference["kind"]) is None
        or type(reference["version"]) is not int
        or reference["version"] < 1
        or not isinstance(reference["sha256"], str)
        or _HEX64.fullmatch(reference["sha256"]) is None
    ):
        raise ValueError(f"{what} is named by key, version and digest")


def _check_kind(kind: Any) -> None:
    if not isinstance(kind, dict) or set(kind) != SEMANTIC_FIELDS:
        raise ValueError("a placed thing's kind is its semantics")
    reference = kind["reference"]
    if (
        not isinstance(reference, dict)
        or set(reference) != {"kind", "version", "sha256"}
        or reference["kind"] != kind["kind"]
        or reference["version"] != kind["version"]
        or type(kind["version"]) is not int
        or kind["version"] < 1
        or not isinstance(kind["kind"], str)
        or _KEY.fullmatch(kind["kind"]) is None
        or not isinstance(reference["sha256"], str)
        or _HEX64.fullmatch(reference["sha256"]) is None
    ):
        raise ValueError("a placed thing names its kind by key, version and digest")
    if kind["class"] not in ("being", "object") or not isinstance(kind["label"], str):
        raise ValueError("a placed thing's kind states its class and label")
    if not isinstance(kind["offers"], list) or not all(
        isinstance(offer, dict) and isinstance(offer.get("key"), str) for offer in kind["offers"]
    ):
        raise ValueError("a placed thing's kind states its offers")


def validate_input_things(document: Mapping[str, Any]) -> None:
    """The things a v5 input carries, held to their shape: each placed thing once, in id order,
    with its kind's semantics, a ground position, a yaw within one turn, and an arrival point
    exactly where its kind offers arrival through it. An unavailable input carries none."""
    _check_reference(document["population_kind"], "the kind a things input's population is made of")
    things = document["things"]
    if not isinstance(things, list) or len(things) > THINGS_BOUND:
        raise ValueError("thing bound exceeded")
    if document["availability"] != "available" and things:
        raise ValueError("an unavailable input carries no things")
    names = []
    for entry in things:
        if not isinstance(entry, dict) or set(entry) - {OFF_GROUND_FIELD} != ENTRY_FIELDS:
            raise ValueError("invalid placed thing fields")
        if OFF_GROUND_FIELD in entry and (
            type(entry[OFF_GROUND_FIELD]) is not int
            or entry[OFF_GROUND_FIELD] == 0
            or not -_COORDINATE <= entry[OFF_GROUND_FIELD] <= _COORDINATE
        ):
            raise ValueError("a thing off the ground states its height, and one on it none")
        placed_id = entry["placed_id"]
        if not isinstance(placed_id, str) or _PLACED_ID.fullmatch(placed_id) is None:
            raise ValueError("invalid placed thing id")
        _check_kind(entry["kind"])
        if not _point(entry["position_mm"]):
            raise ValueError("invalid placed thing position")
        yaw = entry["yaw_microradians"]
        if type(yaw) is not int or not 0 <= yaw <= MAX_YAW_MICRORADIANS:
            raise ValueError("invalid placed thing yaw")
        arrives = "arrive_through" in _offers(entry["kind"])
        if arrives != (entry["arrival_mm"] is not None) or (
            arrives and not _point(entry["arrival_mm"])
        ):
            raise ValueError("a gate states where visitors arrive, and nothing else does")
        if entry["kind"]["class"] == "being" and arrives:
            raise ValueError("a being is no gate")
        names.append(placed_id)
    if names != sorted(set(names)):
        raise ValueError("placed things must be unique and sorted")


def input_things(document: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """The things an input states, or none for an input of an earlier composition."""
    return document.get("things", ())


def placed_beings(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The beings the world's author placed, in id order: each lives in the society."""
    return [entry for entry in input_things(document) if entry["kind"]["class"] == "being"]


def placed_objects(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The objects the world's author placed, in id order: the society's things."""
    return [entry for entry in input_things(document) if entry["kind"]["class"] == "object"]


def arrival_points(document: Mapping[str, Any]) -> dict[str, list[int]]:
    """Where visitors arrive, by the placed id of each gate offering arrival through it."""
    return {
        entry["placed_id"]: list(entry["arrival_mm"])
        for entry in input_things(document)
        if entry["arrival_mm"] is not None
    }
