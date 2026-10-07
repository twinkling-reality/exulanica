"""A thing kind: what a kind of thing is and can do, as one typed, versioned, fingerprinted record.

A thing is anything addressable in a world: a knight, a lantern spirit, a sword, a well, a visitor
from a game. Its kind, profile ``exulanica.thing-kind/v1``, states what the engine understands of
it and nothing about how it is drawn: its class (a ``being``, which acts and has a decider, or an
``object``, which decides nothing), its body plan and the figures that plan bounds, the movement
modules it moves by, its abilities (what it can do) and offers (what it lets others do to it) from
the things catalogs, its routine's weights, the deciders that may run it, the looks suggested for
it, its origin, and source data kept verbatim in ``ext``, which no engine reads.

:func:`read_thing_kind` holds a document to its checks and refuses by name
(:class:`ThingKindRefused`, a code from :data:`THING_KIND_CODES`, the field at fault and a
sentence): a key it does not state, a float, a figure outside its plan's bounds, a reference that
does not resolve, an ability the body cannot serve (holding things with no socket, following with
no way to move), an offer its geometry makes implausible (a grip outside the box, a holdable thing
longer than any hand holds), a look of another body plan, a routine weight for saying something
(the routine never says anything), and an origin or licence the record refuses.

The digest is the SHA-256 of the document's canonical bytes, and every version is immutable: the
lock beside the kinds (``kinds.lock.json``, :func:`read_kind_lock`) names every shipped version with
the digest it shipped with, and :func:`shipped_thing_kinds` refuses a file the lock does not name
at that digest, so a changed kind is a new version and a new line, never an edit. What a society
reads of a kind is :meth:`ThingKind.semantics`: everything but its looks, its origin and its
``ext``, so a society never reads a look and a replay never reads the kind library.

Pure: no connection, no store.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.grammar.documents import read_json
from exulanica.things.catalogs import AXES, ThingCatalogs, thing_catalogs
from exulanica.things.looks import Look
from exulanica.things.origin import OriginRefused, read_origin

__all__ = [
    "CLASSES",
    "DECIDER_KINDS",
    "KINDS_DIRECTORY",
    "KINDS_LOCK",
    "LOCK_PROFILE",
    "THING_KIND_CODES",
    "THING_KIND_PROFILE",
    "ThingKind",
    "ThingKindRefused",
    "read_kind_lock",
    "read_thing_kind",
    "shipped_thing_kinds",
]

THING_KIND_PROFILE: Final = "exulanica.thing-kind/v1"
CLASSES: Final = ("being", "object")
#: The deciders a kind may allow, as the decider descriptor names them.
DECIDER_KINDS: Final = ("routine", "model", "person", "external")
KINDS_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "assets/catalogs/things/kinds"
#: Every shipped kind version and the digest it shipped with, beside the kinds.
KINDS_LOCK: Final = KINDS_DIRECTORY.parent / "kinds.lock.json"
LOCK_PROFILE: Final = "exulanica.thing-kind-lock/v1"
#: The most canonical bytes a kind's ``ext`` may hold: source data kept, never read.
EXT_BYTES_MAXIMUM: Final = 8 * 1024
#: The abilities a routine draws among, each by weight; saying and leaving are never drawn.
_ROUTINE_ABILITIES: Final = frozenset(
    {"wait", "stand", "talk", "rest", "visit", "pick_up", "put_down", "give", "take", "follow"}
)
_WEIGHT_MAXIMUM: Final = 10_000
_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_LABEL: Final = re.compile(r"[a-z][a-z ]{0,38}[a-z]")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_FACES: Final = ("+x", "-x", "+y", "-y")
#: The refusals a kind meets, each with what it means.
THING_KIND_CODES: Final = (
    (
        "thing_kind_invalid",
        "The document is not a thing kind: a key it does not state, a float, a missing field, a "
        "malformed value.",
    ),
    (
        "thing_kind_reference_unknown",
        "A body plan, ability, offer, movement module or look the catalogs do not state.",
    ),
    ("thing_kind_out_of_bounds", "A figure outside its body plan's or its parameter's bounds."),
    (
        "thing_kind_body_unmet",
        "An ability the body cannot serve: holding things with no socket, going with no way to "
        "move, or an object that acts.",
    ),
    (
        "thing_kind_offer_implausible",
        "An offer its geometry makes implausible: a grip outside the box, a holdable thing longer "
        "than any hand holds, a place out of reach of the box.",
    ),
    ("thing_kind_look_unfit", "A look of another body plan than the kind's."),
    ("thing_kind_origin_invalid", "An origin record the origin reader refuses."),
    (
        "thing_kind_not_locked",
        "A shipped kind file the lock does not name at its digest, or a locked version with no "
        "file: a shipped version never changes.",
    ),
)
_TOP: Final = frozenset(
    {
        "profile",
        "kind",
        "version",
        "label",
        "summary",
        "class",
        "body",
        "origin",
        "moves",
        "abilities",
        "offers",
        "routine",
        "deciders",
        "looks",
        "ext",
    }
)


class ThingKindRefused(ValueError):
    """A thing kind this code will not read, by a code, the field at fault and a sentence."""

    def __init__(self, code: str, where: str, detail: str) -> None:
        super().__init__(f"{code} at {where}: {detail}")
        self.code = code
        self.where = where
        self.detail = detail


def _refuse(code: str, where: str, detail: str) -> ThingKindRefused:
    return ThingKindRefused(code, where, detail)


def _invalid(where: str, detail: str) -> ThingKindRefused:
    return _refuse("thing_kind_invalid", where, detail)


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _invalid(where, f"states exactly {sorted(keys)}")
    return value


def _whole(where: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _refuse(
            "thing_kind_out_of_bounds", where, f"is a whole number from {minimum} to {maximum}"
        )
    return value


def _integer(where: str, value: object) -> int:
    if type(value) is not int:
        raise _invalid(where, "is a whole number")
    return value


def _text(where: str, value: object, maximum: int) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise _invalid(where, "is non-empty text with no surrounding space")
    if len(value) > maximum or any(
        ord(c) < 32 or 0x7F <= ord(c) < 0xA0 or 0x200B <= ord(c) <= 0x200F for c in value
    ):
        raise _invalid(where, f"is one line of at most {maximum} plain characters")
    return value


@dataclass(frozen=True, slots=True)
class ThingKind:
    """A read thing kind, its parts resolved against the catalogs it was checked with."""

    kind: str
    version: int
    label: str
    klass: str
    plan: str
    abilities: Mapping[str, Mapping[str, int]]
    offers: Mapping[str, Mapping[str, Any]]
    looks: tuple[Mapping[str, Any], ...]
    document: Mapping[str, Any]
    sha256: str
    catalogs_sha256: str

    def reference(self) -> dict[str, Any]:
        """How a thing names its kind: key, version and digest."""
        return {"kind": self.kind, "version": self.version, "sha256": self.sha256}

    def semantics(self) -> dict[str, Any]:
        """What a society reads of the kind: everything but its looks, its origin and its
        ``ext``, with the kind's reference, so no look ever reaches a society."""
        kept = {
            key: value
            for key, value in self.document.items()
            if key not in ("looks", "origin", "ext", "summary")
        }
        return {**kept, "reference": self.reference()}


def _point(where: str, value: object, box: Mapping[str, int]) -> Mapping[str, int]:
    point = _closed(where, value, frozenset({"x_mm", "y_mm", "z_mm"}))
    x, y, z = (_integer(f"{where}.{axis}", point[axis]) for axis in ("x_mm", "y_mm", "z_mm"))
    if not (abs(2 * x) <= box["width"] and abs(2 * y) <= box["depth"] and 0 <= z <= box["height"]):
        raise _refuse("thing_kind_offer_implausible", where, "lies inside the thing's box")
    return point


def _place(where: str, value: object, box: Mapping[str, int], reach: int) -> None:
    """A place a person stands at, in the thing's slot frame, the way they face there, and the
    seat they sit on when they rest, inside the box, or none."""
    place = _closed(where, value, frozenset({"x_mm", "y_mm", "faces", "seat"}))
    x = _integer(f"{where}.x_mm", place["x_mm"])
    y = _integer(f"{where}.y_mm", place["y_mm"])
    if abs(2 * x) > box["width"] + 2 * reach or abs(2 * y) > box["depth"] + 2 * reach:
        raise _refuse("thing_kind_offer_implausible", where, "lies within reach of the thing")
    if place["faces"] not in _FACES:
        raise _invalid(f"{where}.faces", f"is one of {list(_FACES)}")
    seat = place["seat"]
    if seat is not None:
        held = _closed(f"{where}.seat", seat, frozenset({"x_mm", "y_mm", "z_mm", "faces"}))
        _point(f"{where}.seat", {key: held[key] for key in ("x_mm", "y_mm", "z_mm")}, box)
        if held["faces"] not in _FACES:
            raise _invalid(f"{where}.seat.faces", f"is one of {list(_FACES)}")


def _offer_parameters(
    where: str,
    key: str,
    raw: object,
    catalogs: ThingCatalogs,
    box: Mapping[str, int] | None,
    reach: int,
) -> Mapping[str, Any]:
    offer = catalogs.offers[key]
    stated = {parameter.name for parameter in offer.parameters}
    values = _closed(where, raw, frozenset(stated))
    for parameter in offer.parameters:
        at = f"{where}.{parameter.name}"
        value = values[parameter.name]
        if parameter.kind == "integer":
            assert parameter.minimum is not None and parameter.maximum is not None
            _whole(at, value, parameter.minimum, parameter.maximum)
        elif parameter.kind == "axis":
            if value not in AXES:
                raise _invalid(at, f"is one of {list(AXES)}")
        elif parameter.kind in ("point", "places", "place"):
            if box is None:
                raise _refuse(
                    "thing_kind_offer_implausible", at, "only a thing with a box states places"
                )
            if parameter.kind == "point":
                _point(at, value, box)
            elif parameter.kind == "place":
                _place(at, value, box, reach)
            else:
                if not isinstance(value, list) or not 1 <= len(value) <= 16:
                    raise _invalid(at, "is a list of 1 to 16 places")
                for index, place in enumerate(value):
                    _place(f"{at}[{index}]", place, box, reach)
        elif parameter.kind in ("perches", "flyers"):
            # Read by flight alone, as the world object catalog states them; held to their shape
            # by that catalog, from which a kind carrying them is derived.
            if not isinstance(value, list | dict):
                raise _invalid(at, "is the world object catalog's own statement")
    return values


def read_thing_kind(
    raw: object,
    *,
    catalogs: ThingCatalogs | None = None,
    look_of: Callable[[Mapping[str, Any]], Look | None] | None = None,
) -> ThingKind:
    """``raw`` as a thing kind, every field checked against ``catalogs`` (the process's, left
    out), and each look it suggests resolved by ``look_of`` and held to the kind's body plan; with
    no resolver, a look's reference is checked for shape alone. Or :class:`ThingKindRefused`."""
    catalogs = catalogs or thing_catalogs()
    document = _closed("kind", raw, _TOP)
    try:
        canonical_json(document)
    except CanonicalisationError as exc:
        raise _invalid("kind", f"is canonical JSON with no floats: {exc}") from exc
    if document["profile"] != THING_KIND_PROFILE:
        raise _invalid("profile", f"is {THING_KIND_PROFILE}")
    kind = document["kind"]
    if type(kind) is not str or _KEY.fullmatch(kind) is None:
        raise _invalid("kind", "is a lowercase key")
    version = _whole("version", document["version"], 1, 10_000)
    label = document["label"]
    if type(label) is not str or _LABEL.fullmatch(label) is None:
        raise _invalid("label", "is lowercase words, 2 to 40 letters and spaces")
    _text("summary", document["summary"], 160)
    klass = document["class"]
    if klass not in CLASSES:
        raise _invalid("class", f"is one of {list(CLASSES)}")
    # The body: a plan and the figures it bounds.
    body = document["body"]
    if not isinstance(body, Mapping) or "plan" not in body:
        raise _invalid("body", "names its body plan")
    plan = catalogs.plan(str(body["plan"]))
    if plan is None:
        raise _refuse(
            "thing_kind_reference_unknown", "body.plan", "names a plan the catalog states"
        )
    box: Mapping[str, int] | None = None
    if "height_mm" in plan.size:
        figures = _closed("body", body, frozenset({"plan", "height_mm"}))
        low, high = plan.size["height_mm"]
        span = _closed("body.height_mm", figures["height_mm"], frozenset({"from", "to"}))
        first = _whole("body.height_mm.from", span["from"], low, high)
        _whole("body.height_mm.to", span["to"], first, high)
    elif "radius_mm" in plan.size:
        figures = _closed("body", body, frozenset({"plan", "radius_mm"}))
        low, high = plan.size["radius_mm"]
        _whole("body.radius_mm", figures["radius_mm"], low, high)
    else:
        figures = _closed("body", body, frozenset({"plan", "box_mm", "blocks_walking"}))
        low, high = plan.size["box_mm"]
        sides = _closed("body.box_mm", figures["box_mm"], frozenset({"width", "depth", "height"}))
        box = {side: _whole(f"body.box_mm.{side}", sides[side], low, high) for side in sides}
        if type(figures["blocks_walking"]) is not bool:
            raise _invalid("body.blocks_walking", "is true or false")
    # Moving, and what a being can do.
    moves = document["moves"]
    if not isinstance(moves, list) or len(set(moves)) != len(moves):
        raise _invalid("moves", "is a list of movement modules, each once")
    for index, module in enumerate(moves):
        if module not in plan.moves:
            raise _refuse(
                "thing_kind_reference_unknown",
                f"moves[{index}]",
                f"is a movement module a {plan.name} body moves by: {list(plan.moves)}",
            )
    abilities: dict[str, Mapping[str, int]] = {}
    raw_abilities = document["abilities"]
    if not isinstance(raw_abilities, list):
        raise _invalid("abilities", "is a list")
    for index, raw_ability in enumerate(raw_abilities):
        at = f"abilities[{index}]"
        entry = _closed(at, raw_ability, frozenset({"key", "parameters"}))
        ability = catalogs.abilities.get(str(entry["key"]))
        if ability is None:
            raise _refuse("thing_kind_reference_unknown", f"{at}.key", "names an ability")
        if ability.key in abilities:
            raise _invalid(f"{at}.key", "names each ability once")
        if klass == "object":
            raise _refuse("thing_kind_body_unmet", at, "an object decides nothing and does nothing")
        if ability.needs_socket and not plan.sockets:
            raise _refuse(
                "thing_kind_body_unmet", at, f"{ability.key} needs a socket a {plan.name} lacks"
            )
        if ability.needs_moves and not moves:
            raise _refuse("thing_kind_body_unmet", at, f"{ability.key} needs a way to move")
        names = {parameter.name for parameter in ability.parameters}
        values = _closed(f"{at}.parameters", entry["parameters"], frozenset(names))
        abilities[ability.key] = MappingProxyType(
            {
                parameter.name: _whole(
                    f"{at}.parameters.{parameter.name}",
                    values[parameter.name],
                    parameter.minimum,
                    parameter.maximum,
                )
                for parameter in ability.parameters
            }
        )
    offers: dict[str, Mapping[str, Any]] = {}
    raw_offers = document["offers"]
    if not isinstance(raw_offers, list):
        raise _invalid("offers", "is a list")
    for index, raw_offer in enumerate(raw_offers):
        at = f"offers[{index}]"
        entry = _closed(at, raw_offer, frozenset({"key", "parameters"}))
        key = str(entry["key"])
        if key not in catalogs.offers:
            raise _refuse("thing_kind_reference_unknown", f"{at}.key", "names an offer")
        if key in offers:
            raise _invalid(f"{at}.key", "names each offer once")
        offers[key] = MappingProxyType(
            dict(
                _offer_parameters(
                    f"{at}.parameters", key, entry["parameters"], catalogs, box, 1_500
                )
            )
        )
    if "holdable" in offers:
        _holdable(plan.name, box, offers["holdable"], catalogs)
    # The routine, the deciders and the looks.
    routine = document["routine"]
    deciders = document["deciders"]
    if klass == "object":
        if routine is not None or deciders is not None or moves:
            raise _refuse(
                "thing_kind_body_unmet", "class", "an object has no routine, decider or movement"
            )
    else:
        _routine(routine, abilities)
        _deciders(deciders)
    raw_looks = document["looks"]
    if not isinstance(raw_looks, list) or len(raw_looks) > 16:
        raise _invalid("looks", "is a list of at most 16 looks")
    for index, reference in enumerate(raw_looks):
        at = f"looks[{index}]"
        ref = _closed(at, reference, frozenset({"look", "version", "sha256"}))
        if type(ref["sha256"]) is not str or _HEX64.fullmatch(ref["sha256"]) is None:
            raise _invalid(f"{at}.sha256", "is a SHA-256 digest in lowercase hex")
        if look_of is not None:
            look = look_of(ref)
            if look is None:
                raise _refuse("thing_kind_reference_unknown", at, "names a look that exists")
            if look.body_plan != plan.name:
                raise _refuse(
                    "thing_kind_look_unfit", at, f"is a look of {look.body_plan}, not {plan.name}"
                )
    try:
        read_origin(document["origin"], where="origin")
    except OriginRefused as exc:
        raise _refuse("thing_kind_origin_invalid", "origin", str(exc)) from exc
    ext = document["ext"]
    if not isinstance(ext, Mapping) or len(canonical_json(dict(ext))) > EXT_BYTES_MAXIMUM:
        raise _invalid("ext", f"is an object of at most {EXT_BYTES_MAXIMUM} canonical bytes")
    return ThingKind(
        kind=str(kind),
        version=version,
        label=str(label),
        klass=str(klass),
        plan=plan.name,
        abilities=MappingProxyType(abilities),
        offers=MappingProxyType(offers),
        looks=tuple(MappingProxyType(dict(ref)) for ref in raw_looks),
        document=MappingProxyType(dict(document)),
        sha256=sha256_of_canonical(dict(document)).hex(),
        catalogs_sha256=catalogs.sha256,
    )


def _holdable(
    plan: str, box: Mapping[str, int] | None, holdable: Mapping[str, Any], catalogs: ThingCatalogs
) -> None:
    """A holdable thing is a box some socket of some body can hold: no longer than its length,
    with a grip a hand closes around or a float socket holds."""
    if box is None:
        raise _refuse("thing_kind_offer_implausible", "offers.holdable", "only an object is held")
    longest = max(box.values())
    sockets = [socket for body in catalogs.plans.values() for socket in body.sockets]
    if not any(longest <= socket.length_mm_maximum for socket in sockets):
        raise _refuse(
            "thing_kind_offer_implausible",
            "offers.holdable",
            f"no socket of any body holds a thing {longest} mm long",
        )


def _routine(raw: object, abilities: Mapping[str, Any]) -> None:
    routine = _closed("routine", raw, frozenset({"weights", "follow_holders_of", "reason"}))
    weights = routine["weights"]
    if not isinstance(weights, Mapping):
        raise _invalid("routine.weights", "maps abilities to whole-number weights")
    for key, weight in weights.items():
        at = f"routine.weights.{key}"
        if key not in abilities:
            raise _refuse("thing_kind_body_unmet", at, "weighs an ability the kind does not have")
        if key not in _ROUTINE_ABILITIES:
            raise _refuse(
                "thing_kind_body_unmet", at, "the routine never says anything, nor leaves"
            )
        _whole(at, weight, 0, _WEIGHT_MAXIMUM)
    held = routine["follow_holders_of"]
    if not isinstance(held, list) or len(held) > 8:
        raise _invalid("routine.follow_holders_of", "is a list of at most 8 thing kind keys")
    if held and "follow" not in abilities:
        raise _refuse("thing_kind_body_unmet", "routine.follow_holders_of", "needs follow")
    for index, key in enumerate(held):
        if type(key) is not str or _KEY.fullmatch(key) is None:
            raise _invalid(f"routine.follow_holders_of[{index}]", "is a thing kind key")
    _text("routine.reason", routine["reason"], 1000)


def _deciders(raw: object) -> None:
    deciders = _closed("deciders", raw, frozenset({"default", "allowed"}))
    allowed = deciders["allowed"]
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(set(allowed)) != len(allowed)
        or any(kind not in DECIDER_KINDS for kind in allowed)
    ):
        raise _invalid("deciders.allowed", f"names deciders among {list(DECIDER_KINDS)}, each once")
    if deciders["default"] not in ("routine", "external") or deciders["default"] not in allowed:
        raise _invalid("deciders.default", "is the routine or an outside program it allows")


def read_kind_lock(path: Path = KINDS_LOCK) -> dict[tuple[str, int], str]:
    """The lock: every shipped kind version, in key and version order, with its digest."""
    where = path.name
    document = _closed(where, read_json(path), frozenset({"profile", "reason", "kinds"}))
    if document["profile"] != LOCK_PROFILE:
        raise _invalid(f"{where}.profile", f"is {LOCK_PROFILE}")
    _text(f"{where}.reason", document["reason"], 1000)
    if not isinstance(document["kinds"], list):
        raise _invalid(f"{where}.kinds", "is a list")
    locked: dict[tuple[str, int], str] = {}
    for index, raw in enumerate(document["kinds"]):
        at = f"{where}.kinds[{index}]"
        entry = _closed(at, raw, frozenset({"kind", "version", "sha256"}))
        if not isinstance(entry["kind"], str) or _KEY.fullmatch(entry["kind"]) is None:
            raise _invalid(f"{at}.kind", "is a kind key")
        version = _whole(f"{at}.version", entry["version"], 1, 10_000)
        if not isinstance(entry["sha256"], str) or _HEX64.fullmatch(entry["sha256"]) is None:
            raise _invalid(f"{at}.sha256", "is a digest")
        locked[(entry["kind"], version)] = entry["sha256"]
    if list(locked) != sorted(locked) or len(locked) != len(document["kinds"]):
        raise _invalid(f"{where}.kinds", "names each version once, in key and version order")
    return locked


def shipped_thing_kinds(
    directory: Path = KINDS_DIRECTORY,
    *,
    catalogs: ThingCatalogs | None = None,
    lock: Path = KINDS_LOCK,
) -> dict[tuple[str, int], ThingKind]:
    """Every thing kind this repository ships, by key and version, each read and checked; a file
    named for another kind or version than it states is refused, and so is one the lock does not
    name at its digest, or a version the lock names with no file."""
    found = {}
    for path in sorted(directory.glob("*.v*.json")):
        kind = read_thing_kind(read_json(path), catalogs=catalogs)
        if path.name != f"{kind.kind}.v{kind.version}.json":
            raise _invalid(path.name, "names the kind and version it states")
        found[(kind.kind, kind.version)] = kind
    locked = read_kind_lock(lock)
    for (key, version), kind in found.items():
        if locked.get((key, version)) != kind.sha256:
            raise _refuse(
                "thing_kind_not_locked",
                f"{key}.v{version}.json",
                f"is not the document the lock ({lock.name}) says version {version} shipped as",
            )
    for key, version in sorted(set(locked) - set(found)):
        raise _refuse(
            "thing_kind_not_locked", lock.name, f"names {key} version {version}, which has no file"
        )
    return found
