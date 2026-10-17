"""The things an input of the society of things carries: what the world's author placed, by kind.

An ``exulanica.society-input/authored-ground-v5`` input lists every thing placed in its region and
not removed, in id order (:mod:`exulanica.world.placed_things`). Each entry states what the thing's
kind says it is and does, its semantics (:meth:`exulanica.things.kinds.ThingKind.semantics`, which
never holds a look), where it stands on the ground, which way it faces, and, for a gate, the point
visitors arrive at, turned with it. An entry of a kind its workspace keeps (a creature drafted
from a person's words) states that kind's reference alone, ``{source: "workspace", sha256}``, and
the input states the kind's run form once, under ``kinds`` (:mod:`exulanica.things.run_forms`,
:mod:`exulanica.world.society_kinds`): what a society runs of it, which holds no word a person
wrote. A placed thing whose made kind its workspace no longer holds is left out, and the input
names it, by its placed id, under ``things_gone``. A thing that does not rest on the ground also
states how high above the ground's elevation it stands (``height_mm``); one on the ground states
none. A kind's semantics or run form rides in the input, so a stored society replays from its
inputs alone and never reads the kind library or a workspace's store again.

A placed being's entry may also carry who its world's owner wrote it to be (``character``: a
``name``, words ``about`` it, or both, each one plain line within :data:`CHARACTER_NAME_MAXIMUM` and
:data:`CHARACTER_ABOUT_MAXIMUM` characters), and only in the inputs of a society whose first input
records the character module (:data:`CHARACTER_MODULE`): the composer adds the newest character of
each placed being to such a society's inputs (:func:`with_characters`), and to no other society's,
so a society made before the module reads its inputs as it always did.

A society's first input, and no later one, records what its minutes run for its whole life:
the ability modules (``modules``) and the movement modules that move its people
(``movement_modules``), each by version. :func:`record_modules` writes both, and every composer of
a things input calls it, so a society on any ground records the same. An input made before
either was recorded states none, and its society runs as it did: no ability module, or the first
walking.

What the society does with them is :mod:`exulanica.world.society_things`'s: a placed being lives
there, a placed object is one of the society's things, and its obstacle and activity are already
the input's navigation and targets, composed by :mod:`exulanica.world.society_authored_ground`.

Pure: no connection and no library read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Final

from exulanica.things.lines import LineRefused, check_line
from exulanica.world.objects import MAX_YAW_MICRORADIANS
from exulanica.world.placed_things import PLACED_THING_ID_PATTERN
from exulanica.world.society_kinds import (
    is_made,
    reference_shape,
    validate_kinds,
    validate_things_gone,
)

__all__ = [
    "CHARACTER_ABOUT_MAXIMUM",
    "CHARACTER_FIELD",
    "CHARACTER_MODULE",
    "CHARACTER_NAME_MAXIMUM",
    "ENTRY_FIELDS",
    "MOVEMENT_MODULES_FIELD",
    "SEMANTIC_FIELDS",
    "THINGS_BOUND",
    "arrival_points",
    "check_character",
    "check_kept_identity",
    "input_things",
    "keep_first_records",
    "placed_beings",
    "placed_objects",
    "record_modules",
    "things_engine",
    "validate_input_things",
    "with_characters",
]

#: The fields of one placed thing as an input states it, and the one it states only off the ground.
ENTRY_FIELDS: Final = frozenset(
    {"placed_id", "kind", "position_mm", "yaw_microradians", "arrival_mm"}
)
OFF_GROUND_FIELD: Final = "height_mm"
#: The field a placed being's entry states who its world's owner wrote it to be in, where its
#: society records :data:`CHARACTER_MODULE`.
CHARACTER_FIELD: Final = "character"
#: The module whose societies carry, keep and show an owner-written character.
CHARACTER_MODULE: Final = "exulanica-ability/character/v1"
#: The most characters of a character's name and of the words about the being, as the line rule
#: counts them: the bounds of its shape, which the module's own figures never exceed.
CHARACTER_NAME_MAXIMUM: Final = 40
CHARACTER_ABOUT_MAXIMUM: Final = 300
_CHARACTER_PARTS: Final = ("about", "name")
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
#: Where a first input and its society's state record the movement modules its people move by.
MOVEMENT_MODULES_FIELD: Final = "movement_modules"
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


def check_character(value: object, *, name_maximum: int, about_maximum: int) -> dict[str, str]:
    """``value`` as a character: a ``name``, words ``about`` the being, or both, each one plain
    line (:func:`~exulanica.things.lines.check_line`) of at most ``name_maximum`` and
    ``about_maximum`` characters, keyed in order; else ``ValueError`` saying what is wrong."""
    if not isinstance(value, Mapping) or not value or not set(value) <= set(_CHARACTER_PARTS):
        raise ValueError("a character holds a name, words about the being, or both")
    for key, maximum in (("name", name_maximum), ("about", about_maximum)):
        if key in value:
            try:
                check_line(value[key], maximum=maximum)
            except LineRefused as exc:
                raise ValueError(f"a character's {key}: {exc}") from exc
    return {key: str(value[key]) for key in _CHARACTER_PARTS if key in value}


def with_characters(
    document: Mapping[str, Any], characters: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    """``document`` with each placed being's character from ``characters`` (by placed id) in its
    entry, and none in any other entry, sealed again: what a society recording the character
    module reads. Objects and gates never carry one."""
    from exulanica.world.society_planner import input_sha256

    sealed = {key: value for key, value in document.items() if key != "document_sha256"}
    things = []
    for entry in document.get("things", ()):
        kept = {key: value for key, value in entry.items() if key != CHARACTER_FIELD}
        character = characters.get(entry["placed_id"])
        if character is not None and _class(entry) == "being":
            kept[CHARACTER_FIELD] = check_character(
                character,
                name_maximum=CHARACTER_NAME_MAXIMUM,
                about_maximum=CHARACTER_ABOUT_MAXIMUM,
            )
        things.append(kept)
    if "things" in document:
        sealed["things"] = things
    sealed["document_sha256"] = input_sha256(sealed)
    return sealed


def things_engine() -> str:
    """The engine that reads a things input: the engine table's one society of things."""
    from exulanica.world.society_engines import ENGINES

    [engine] = [row.engine for row in ENGINES if row.state_family == "things"]
    return engine


def record_modules(document: dict[str, Any], *, day: bool = False) -> None:
    """Write into a things input what a society's first input alone records, and nothing into a
    later one: the ability modules its minutes run, each built module at its newest version, the
    movement modules that move its people, the newest of each kind of movement, and the identity
    catalog version that names its people (:mod:`exulanica.world.society_identity`). The society
    runs exactly these for its whole life, whatever a later table adds. Every composer of a things
    input calls this before it seals the document."""
    if document["input_seq"] != 1:
        return
    from exulanica.abilities.registry import current_modules
    from exulanica.movement.registry import current_engine_modules
    from exulanica.world.society_identity import IDENTITY_FIELD, identity_record

    document["modules"] = list(current_modules(day=day))
    document[MOVEMENT_MODULES_FIELD] = list(current_engine_modules(things_engine()))
    document[IDENTITY_FIELD] = identity_record()


def keep_first_records(state: dict[str, Any], document: Mapping[str, Any], seed: str) -> None:
    """Keep in a society of things' genesis state what its first input alone records, for its whole
    life: the modules its minutes run, the movement modules that move its people, and the identity
    catalog version naming them, by which its invented people are named
    (:func:`~exulanica.world.society_identity.name_people`). What an input records none of, as one
    made before it was, the state keeps none of."""
    from exulanica.world.society_identity import IDENTITY_FIELD, name_people

    for recorded in ("modules", MOVEMENT_MODULES_FIELD, IDENTITY_FIELD):
        if recorded in document:
            state[recorded] = deepcopy(document[recorded])
    if IDENTITY_FIELD in state:
        name_people(state["inhabitants"], seed, state[IDENTITY_FIELD])


def check_kept_identity(state: Mapping[str, Any]) -> None:
    """A society of things' state holds the identity its first input recorded, where it holds one,
    to its shape."""
    from exulanica.world.society_identity import IDENTITY_FIELD, check_identity

    if IDENTITY_FIELD in state:
        check_identity(state[IDENTITY_FIELD])


def validate_input_things(document: Mapping[str, Any]) -> None:
    """The things a v5 input carries, held to their shape: each placed thing once, in id order,
    with its kind's semantics, a ground position, a yaw within one turn, and an arrival point
    exactly where its kind offers arrival through it, and the water its swimmers cross where it
    states any (:func:`~exulanica.world.society_water.validate_water`). An unavailable input
    carries neither."""
    from exulanica.abilities.registry import DAY
    from exulanica.world.society_input_policy import WALKING_SURFACES_INPUT_V3
    from exulanica.world.society_resident_day import validate_frame

    records_day = DAY in document.get("modules", ())
    if records_day != ("day" in document):
        raise ValueError("resident day input must match its recorded module")
    if records_day:
        if (
            document["input_seq"] != 1
            or document["profile"] != WALKING_SURFACES_INPUT_V3
            or "people" not in document
            or document["availability"] != "available"
        ):
            raise ValueError("resident day requires an available first input with people")
        validate_frame(document["day"], people=document["people"], document=document)
    _check_reference(document["population_kind"], "the kind a things input's population is made of")
    if "modules" in document:
        from exulanica.abilities.registry import AbilityError, recorded_modules

        modules = document["modules"]
        if (
            document["input_seq"] != 1
            or not isinstance(modules, list)
            or not modules
            or modules != sorted(set(modules))
        ):
            raise ValueError("a society's first input alone records its modules, each once, sorted")
        try:
            recorded_modules(document)
        except AbilityError as exc:
            raise ValueError(f"a things input records built modules only: {exc}") from exc
    if MOVEMENT_MODULES_FIELD in document:
        from exulanica.movement.registry import MovementError, check_recorded

        if document["input_seq"] != 1:
            raise ValueError("a society's first input alone records its movement modules")
        try:
            check_recorded(document[MOVEMENT_MODULES_FIELD], things_engine())
        except MovementError as exc:
            raise ValueError(f"a things input's movement modules: {exc}") from exc
    if "people" in document:
        from exulanica.world.town_people import TownPeopleRefused, validate_people_frame

        frame = document["people"]
        if (
            document["input_seq"] != 1
            or document["availability"] != "available"
            or document.get("population", {}).get("rule") != "residents"
        ):
            raise ValueError(
                "an available first input over a world of homes alone carries its people's frame"
            )
        try:
            validate_people_frame(frame)
        except TownPeopleRefused as exc:
            raise ValueError(f"a things input's people are out of shape: {exc}") from exc
        if frame["population"] != document["population"]["size"]:
            raise ValueError("a things input's people are as many as its population")
    things = document["things"]
    if not isinstance(things, list) or len(things) > THINGS_BOUND:
        raise ValueError("thing bound exceeded")
    if document["availability"] != "available" and things:
        raise ValueError("an unavailable input carries no things")
    names = []
    made: set[str] = set()
    for entry in things:
        if (
            not isinstance(entry, dict)
            or set(entry) - {OFF_GROUND_FIELD, CHARACTER_FIELD} != ENTRY_FIELDS
        ):
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
        if is_made(entry["kind"]):
            # A kind its workspace keeps: its reference alone, its run form stated once below.
            if not reference_shape(entry["kind"]):
                raise ValueError("a placed thing of a workspace's own kind names it by digest")
            made.add(entry["kind"]["sha256"])
        else:
            _check_kind(entry["kind"])
        if not _point(entry["position_mm"]):
            raise ValueError("invalid placed thing position")
        yaw = entry["yaw_microradians"]
        if type(yaw) is not int or not 0 <= yaw <= MAX_YAW_MICRORADIANS:
            raise ValueError("invalid placed thing yaw")
        arrives = not is_made(entry["kind"]) and "arrive_through" in _offers(entry["kind"])
        if arrives != (entry["arrival_mm"] is not None) or (
            arrives and not _point(entry["arrival_mm"])
        ):
            raise ValueError("a gate states where visitors arrive, and nothing else does")
        if _class(entry) == "being" and arrives:
            raise ValueError("a being is no gate")
        if CHARACTER_FIELD in entry:
            if _class(entry) != "being":
                raise ValueError("only a placed being carries a character")
            check_character(
                entry[CHARACTER_FIELD],
                name_maximum=CHARACTER_NAME_MAXIMUM,
                about_maximum=CHARACTER_ABOUT_MAXIMUM,
            )
        names.append(placed_id)
    if names != sorted(set(names)):
        raise ValueError("placed things must be unique and sorted")
    validate_kinds(document, made)
    validate_things_gone(document, set(names))
    from exulanica.world.society_identity import IDENTITY_FIELD, check_identity
    from exulanica.world.society_water import validate_water

    validate_water(document)
    if IDENTITY_FIELD in document:
        if document["input_seq"] != 1:
            raise ValueError("only a society's first input records the identity naming its people")
        check_identity(document[IDENTITY_FIELD])


def input_things(document: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """The things an input states, or none for an input of an earlier composition."""
    return document.get("things", ())


def _class(entry: Mapping[str, Any]) -> str:
    """Whether an entry's thing is a being or an object: a made kind is always a being's."""
    return "being" if is_made(entry["kind"]) else str(entry["kind"]["class"])


def placed_beings(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The beings the world's author placed, in id order: each lives in the society."""
    return [entry for entry in input_things(document) if _class(entry) == "being"]


def placed_objects(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The objects the world's author placed, in id order: the society's things."""
    return [entry for entry in input_things(document) if _class(entry) == "object"]


def arrival_points(document: Mapping[str, Any]) -> dict[str, list[int]]:
    """Where visitors arrive, by the placed id of each gate offering arrival through it."""
    return {
        entry["placed_id"]: list(entry["arrival_mm"])
        for entry in input_things(document)
        if entry["arrival_mm"] is not None
    }
