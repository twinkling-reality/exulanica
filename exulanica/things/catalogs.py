"""The vocabularies every thing kind is read against: body plans, abilities, offers and look kinds.

Four catalogs under ``assets/catalogs/things`` state, as data, what a thing kind may name:

*   **body plans** (``body-plans``): the semantic shape of a body, its bones, sockets, size and the
    motions a look must have, named ``<key>/v<version>`` (``humanoid/v1``);
*   **abilities** (``abilities``): what a thing can do, each served by one ability module, with
    what it needs of the body and what its target must offer;
*   **offers** (``offers``): what a thing lets others do to it, and the parameters a kind states
    for each;
*   **look kinds** (``look-kinds``): how a look is drawn, and which plans it fits.

Each is a catalog as every catalog in this repository is one, read by
:func:`exulanica.grammar.catalogs.load_catalog`: the envelope, a ``key`` and a ``licence`` on every
entry under the licence matrix's rules, and a ``reason``. A nested field is checked by its reader
here and carried as canonical JSON text, as the world object catalog carries its own.
:attr:`ThingCatalogs.sha256` is :func:`~exulanica.grammar.catalogs.catalog_digest` over the four,
so a kind checked against them names exactly what it was checked against. Reading a catalog is not
registering one.

A body plan a model drafted for a workspace is not a catalog entry but its own document, profile
``exulanica.body-plan/v1`` (:func:`read_body_plan`), read by the same field readers with its origin
record in place of a catalog licence. It may state what no shipped plan does: ``limbs``, the chains
of bones a drawing moves together (a leg, a wing, a tail, a neck), and the size figure
``extent_mm`` (a length, a width, a height and a wingspan). A look kind may fit every plan with
bones rather than a list of plans (``plans`` holding ``any_with_bones``).

Pure: no connection, no store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.grammar.catalogs import (
    Catalog,
    CatalogEntry,
    CatalogSchema,
    Licence,
    catalog_digest,
    integer_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.documents import split_versioned_name
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.records import KEY_PATTERN
from exulanica.things.origin import OriginRefused, read_origin

__all__ = [
    "ANY_PLAN_WITH_BONES",
    "AXES",
    "BODY_PLAN_BONES_MAXIMUM",
    "BODY_PLAN_PROFILE",
    "CATALOG_DIRECTORY",
    "EXTENT_SIDES",
    "LIMB_ROLES",
    "LIMB_SIDES",
    "MOTIONS",
    "Ability",
    "AbilityParameter",
    "BodyPlan",
    "BodyPlanRefused",
    "Bone",
    "Limb",
    "LookKind",
    "Offer",
    "OfferParameter",
    "Socket",
    "ThingCatalogError",
    "ThingCatalogs",
    "load_thing_catalogs",
    "read_body_plan",
    "thing_catalogs",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
CATALOG_DIRECTORY: Final = _ROOT / "assets" / "catalogs" / "things"
#: The six directions a held thing may extend along from the hand, in the slot frame.
AXES: Final = ("+x", "-x", "+y", "-y", "+z", "-z")
#: A bone's name: a lowercase letter, then letters and digits (the VRM humanoid names, and a drafted
#: plan's ``leg3Left2``).
_BONE: Final = re.compile(r"[a-z][A-Za-z0-9]{0,47}")
_SOCKET: Final = re.compile(r"[a-z][a-z0-9_]{0,23}(\.[a-z][a-z0-9_]{0,23})?")
_MODULE: Final = re.compile(r"exulanica-[a-z]+/[a-z][a-z0-9-]{0,31}/v[1-9][0-9]{0,3}")
_PLAN: Final = re.compile(r"([a-z][a-z0-9_]{0,31})/v([1-9][0-9]{0,3})")
#: The kinds of value an offer's parameter takes.
OFFER_PARAMETER_KINDS: Final = ("integer", "point", "axis", "places", "perches", "flyers", "place")
_CEILING: Final = 1_000_000_000
#: The profile of a body plan that is its own document rather than a catalog entry.
BODY_PLAN_PROFILE: Final = "exulanica.body-plan/v1"
#: The most bones a body plan may have: the most joints one skinned look may move in the browser.
BODY_PLAN_BONES_MAXIMUM: Final = 128
#: What a chain of bones is, for whatever moves it: a serpentine body's travelling wave, a neck's
#: reach, a tail's sway, a jaw's opening, a leg's step, an arm's reach, a wing's beat, a fin's
#: stroke, a tentacle's drift.
LIMB_ROLES: Final = ("spine", "neck", "tail", "jaw", "leg", "arm", "wing", "fin", "tentacle")
#: Which side of the body a chain is on, the body facing +y with its left at -x.
LIMB_SIDES: Final = ("left", "right", "centre")
#: In a look kind's ``plans``: the kind fits every body plan that has bones, whatever its name.
ANY_PLAN_WITH_BONES: Final = "any_with_bones"
#: The motions a body plan may ask of a look, and a rig may name clips for.
MOTIONS: Final = (
    "idle",
    "walk",
    "run",
    "reach",
    "hold",
    "talk",
    "sit",
    "fly",
    "glide",
    "take_off",
    "land",
)
_LIMB_KEY: Final = re.compile(r"[a-z][A-Za-z0-9]{0,47}")
_PLAN_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


class ThingCatalogError(CatalogError):
    """A things catalog this code will not read, by the place at fault."""


class BodyPlanRefused(ValueError):
    """A body plan document this code will not read, by a code, the field at fault and a
    sentence."""

    def __init__(self, code: str, where: str, detail: str) -> None:
        super().__init__(f"{code} at {where}: {detail}")
        self.code = code
        self.where = where
        self.detail = detail


def _fail(where: str, message: str) -> ThingCatalogError:
    return ThingCatalogError(f"{where}: {message}")


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _fail(where, f"states exactly {sorted(keys)}")
    return value


def _text(where: str, value: object, *, maximum: int = 2000) -> str:
    text_field(where, value)
    assert isinstance(value, str)
    if len(value) > maximum or any(ord(c) < 32 for c in value):
        raise _fail(where, f"is one line of at most {maximum} characters")
    return value


def _whole(where: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _fail(where, f"is a whole number from {minimum} to {maximum}")
    return value


def _flag(where: str, value: object) -> bool:
    if type(value) is not bool:
        raise _fail(where, "is true or false")
    return value


def _matching(where: str, value: object, pattern: re.Pattern[str], what: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _fail(where, f"is {what}")
    return value


@dataclass(frozen=True, slots=True)
class _Nested:
    """A catalog field check that reads a nested value and carries it as canonical JSON text,
    parsed back where the entry is built."""

    reader: Callable[[str, object], object]

    def __call__(self, where: str, value: object) -> str:
        self.reader(where, value)
        return canonical_json(value).decode("utf-8")


def _words(where: str, value: object) -> str:
    return _text(where, value, maximum=80)


@dataclass(frozen=True, slots=True)
class Bone:
    name: str
    parent: str | None
    required: bool


@dataclass(frozen=True, slots=True)
class Limb:
    """A chain of bones a drawing moves together, from the one nearest the body to the tip."""

    key: str
    role: str
    side: str
    #: Where along the body it is, counting from the front: 0 is the foremost of its role.
    order: int
    bones: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Socket:
    """Where a body holds a thing: on a bone, or beside a body with none."""

    key: str
    bone: str | None
    holds: int
    length_mm_maximum: int
    grip_section_mm_maximum: int | None


@dataclass(frozen=True, slots=True)
class BodyPlan:
    """A body's semantic shape, named ``<key>/v<version>``."""

    key: str
    version: int
    title: str
    bones: tuple[Bone, ...]
    sockets: tuple[Socket, ...]
    #: The figures a kind of this plan states, each a range: a height, a radius or a box side.
    size: Mapping[str, tuple[int, int]]
    reach_mm: int | None
    motions_required: tuple[str, ...]
    motions_optional: tuple[str, ...]
    moves: tuple[str, ...]
    reason: str
    #: A catalog entry's licence; none for a plan that is its own document, which has an origin.
    licence: Licence | None
    #: The chains of bones a drawing moves together, where the plan states them.
    limbs: tuple[Limb, ...] = ()
    #: A plan document's origin record, and the SHA-256 of its canonical bytes; none for a catalog
    #: entry, which the catalogs' digest covers.
    origin: Mapping[str, Any] | None = None
    sha256: str | None = None

    @property
    def name(self) -> str:
        return f"{self.key}/v{self.version}"

    @property
    def bone_names(self) -> frozenset[str]:
        return frozenset(bone.name for bone in self.bones)

    @property
    def required_bones(self) -> tuple[str, ...]:
        return tuple(bone.name for bone in self.bones if bone.required)

    def socket(self, key: str) -> Socket | None:
        return next((socket for socket in self.sockets if socket.key == key), None)


@dataclass(frozen=True, slots=True)
class AbilityParameter:
    name: str
    unit: str
    minimum: int
    maximum: int
    reason: str


@dataclass(frozen=True, slots=True)
class Ability:
    """What a thing can do: served by one ability module, needing a socket or movement of the
    body, and naming what its target must offer."""

    key: str
    module: str
    needs_socket: bool
    needs_moves: bool
    target_offer: str | None
    takes_line: bool
    words: str
    parameters: tuple[AbilityParameter, ...]
    reason: str
    licence: Licence


@dataclass(frozen=True, slots=True)
class OfferParameter:
    name: str
    kind: str
    minimum: int | None
    maximum: int | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class Offer:
    """What a thing lets others do to it, and the parameters a kind states for it."""

    key: str
    words: str
    parameters: tuple[OfferParameter, ...]
    reason: str
    licence: Licence


@dataclass(frozen=True, slots=True)
class LookKind:
    """How a look is drawn, and which body plans it fits."""

    key: str
    plans: tuple[str, ...]
    #: Whether a look of this kind names a container: ``required`` or ``none``.
    container: str
    rig: bool
    light: bool
    role: bool
    words: str
    reason: str
    licence: Licence

    def fits(self, plan: BodyPlan) -> bool:
        """Whether a look of this kind may be a look of ``plan``: named, or any plan with bones
        where the kind says so."""
        return plan.name in self.plans or (ANY_PLAN_WITH_BONES in self.plans and bool(plan.bones))


# -- the nested fields, each read where it is checked and again where it is built ---------------


def _bones(where: str, value: object) -> tuple[Bone, ...]:
    if not isinstance(value, list):
        raise _fail(where, "is a list of bones")
    bones: list[Bone] = []
    names: set[str] = set()
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        bone = _closed(at, raw, frozenset({"name", "parent", "required"}))
        name = _matching(f"{at}.name", bone["name"], _BONE, "a bone name")
        parent = bone["parent"]
        if parent is not None and parent not in names:
            raise _fail(f"{at}.parent", "names a bone stated before it")
        if name in names:
            raise _fail(f"{at}.name", "names a bone once")
        names.add(name)
        bones.append(Bone(name, parent, _flag(f"{at}.required", bone["required"])))
    if bones and sum(1 for bone in bones if bone.parent is None) != 1:
        raise _fail(where, "have exactly one root")
    return tuple(bones)


def _sockets(where: str, value: object) -> tuple[Socket, ...]:
    if not isinstance(value, list):
        raise _fail(where, "is a list of sockets")
    sockets = []
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        socket = _closed(
            at,
            raw,
            frozenset({"key", "bone", "holds", "length_mm_maximum", "grip_section_mm_maximum"}),
        )
        bone = socket["bone"]
        if bone is not None:
            _matching(f"{at}.bone", bone, _BONE, "a bone name")
        section = socket["grip_section_mm_maximum"]
        sockets.append(
            Socket(
                key=_matching(f"{at}.key", socket["key"], _SOCKET, "a socket key"),
                bone=bone,
                holds=_whole(f"{at}.holds", socket["holds"], 1, 8),
                length_mm_maximum=_whole(
                    f"{at}.length_mm_maximum", socket["length_mm_maximum"], 1, 10_000
                ),
                grip_section_mm_maximum=None
                if section is None
                else _whole(f"{at}.grip_section_mm_maximum", section, 1, 1_000),
            )
        )
    if len({socket.key for socket in sockets}) != len(sockets):
        raise _fail(where, "name each socket once")
    return tuple(sockets)


#: The four ranges an ``extent_mm`` figure states, each read as ``extent_<side>_mm``: nose to tail
#: tip, side to side with wings folded, ground to top, and wingtip to wingtip (0 with no wings).
EXTENT_SIDES: Final = ("length", "width", "height", "span")


def _range(at: str, span: object, lowest: int) -> tuple[int, int]:
    bounds = _closed(at, span, frozenset({"minimum", "maximum"}))
    low = _whole(f"{at}.minimum", bounds["minimum"], lowest, 100_000)
    return low, _whole(f"{at}.maximum", bounds["maximum"], low, 100_000)


def _size(where: str, value: object) -> Mapping[str, tuple[int, int]]:
    if not isinstance(value, Mapping) or len(value) != 1:
        raise _fail(where, "states one figure's range")
    size = {}
    for figure, span in value.items():
        at = f"{where}.{figure}"
        if figure == "extent_mm":
            sides = _closed(at, span, frozenset(EXTENT_SIDES))
            for side in EXTENT_SIDES:
                # Only a span may be nothing: a body with no wings spans nothing.
                lowest = 0 if side == "span" else 1
                size[f"extent_{side}_mm"] = _range(f"{at}.{side}", sides[side], lowest)
            continue
        if figure not in ("height_mm", "radius_mm", "box_mm"):
            raise _fail(at, "is a height, a radius, a box side or an extent")
        size[figure] = _range(at, span, 1)
    return MappingProxyType(size)


def _limbs(where: str, value: object, bones: tuple[Bone, ...]) -> tuple[Limb, ...]:
    """Chains of the plan's own bones, each parent-linked from the body outward, no bone in two
    chains, each role from :data:`LIMB_ROLES`."""
    if not isinstance(value, list) or len(value) > BODY_PLAN_BONES_MAXIMUM:
        raise _fail(where, f"is a list of at most {BODY_PLAN_BONES_MAXIMUM} chains")
    parents = {bone.name: bone.parent for bone in bones}
    limbs: list[Limb] = []
    claimed: set[str] = set()
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        limb = _closed(at, raw, frozenset({"key", "role", "side", "order", "bones"}))
        key = _matching(f"{at}.key", limb["key"], _LIMB_KEY, "a chain's key")
        if limb["role"] not in LIMB_ROLES:
            raise _fail(f"{at}.role", f"is one of {list(LIMB_ROLES)}")
        if limb["side"] not in LIMB_SIDES:
            raise _fail(f"{at}.side", f"is one of {list(LIMB_SIDES)}")
        order = _whole(f"{at}.order", limb["order"], 0, BODY_PLAN_BONES_MAXIMUM)
        chain = limb["bones"]
        if not isinstance(chain, list) or not chain:
            raise _fail(f"{at}.bones", "names the chain's bones from the body outward")
        for position, bone in enumerate(chain):
            place = f"{at}.bones[{position}]"
            if bone not in parents:
                raise _fail(place, "names one of the plan's bones")
            if bone in claimed:
                raise _fail(place, "names a bone no other chain names")
            if position and parents[bone] != chain[position - 1]:
                raise _fail(place, "is a child of the bone before it in the chain")
            claimed.add(bone)
        limbs.append(Limb(key, str(limb["role"]), str(limb["side"]), order, tuple(chain)))
    if len({limb.key for limb in limbs}) != len(limbs):
        raise _fail(where, "name each chain once")
    return tuple(limbs)


def _reach(where: str, value: object) -> int | None:
    return None if value is None else _whole(where, value, 1, 100_000)


def _keys(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _fail(where, "is a list of keys")
    keys = tuple(
        _matching(f"{where}[{i}]", item, KEY_PATTERN, "a lowercase key")
        for i, item in enumerate(value)
    )
    if len(set(keys)) != len(keys):
        raise _fail(where, "names each key once")
    return keys


def _motions(where: str, value: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    motions = _closed(where, value, frozenset({"required", "optional"}))
    return _keys(f"{where}.required", motions["required"]), _keys(
        f"{where}.optional", motions["optional"]
    )


def _modules(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _fail(where, "is a list of movement modules")
    return tuple(
        _matching(f"{where}[{i}]", item, _MODULE, "a movement module")
        for i, item in enumerate(value)
    )


def _module(where: str, value: object) -> str:
    return _matching(where, value, _MODULE, "an ability module")


def _needs(where: str, value: object) -> tuple[bool, bool]:
    needs = _closed(where, value, frozenset({"socket", "moves"}))
    return _flag(f"{where}.socket", needs["socket"]), _flag(f"{where}.moves", needs["moves"])


def _target(where: str, value: object) -> str | None:
    return None if value is None else _matching(where, value, KEY_PATTERN, "an offer key")


def _ability_parameters(where: str, value: object) -> tuple[AbilityParameter, ...]:
    if not isinstance(value, list):
        raise _fail(where, "is a list")
    parameters = []
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        parameter = _closed(at, raw, frozenset({"name", "unit", "minimum", "maximum", "reason"}))
        low = _whole(f"{at}.minimum", parameter["minimum"], 0, _CEILING)
        parameters.append(
            AbilityParameter(
                name=_matching(f"{at}.name", parameter["name"], KEY_PATTERN, "a lowercase key"),
                unit=_text(f"{at}.unit", parameter["unit"], maximum=24),
                minimum=low,
                maximum=_whole(f"{at}.maximum", parameter["maximum"], low, _CEILING),
                reason=_text(f"{at}.reason", parameter["reason"]),
            )
        )
    return tuple(parameters)


def _offer_parameters(where: str, value: object) -> tuple[OfferParameter, ...]:
    if not isinstance(value, list):
        raise _fail(where, "is a list")
    parameters = []
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        if not isinstance(raw, Mapping) or raw.get("kind") not in OFFER_PARAMETER_KINDS:
            raise _fail(f"{at}.kind", f"is one of {list(OFFER_PARAMETER_KINDS)}")
        integer = raw["kind"] == "integer"
        expected = {"name", "kind"} | ({"minimum", "maximum", "unit"} if integer else set())
        _closed(at, raw, frozenset(expected))
        low = _whole(f"{at}.minimum", raw["minimum"], 0, _CEILING) if integer else None
        parameters.append(
            OfferParameter(
                name=_matching(f"{at}.name", raw["name"], KEY_PATTERN, "a lowercase key"),
                kind=raw["kind"],
                minimum=low,
                maximum=_whole(f"{at}.maximum", raw["maximum"], low or 0, _CEILING)
                if integer
                else None,
                unit=_text(f"{at}.unit", raw["unit"], maximum=24) if integer else None,
            )
        )
    if len({parameter.name for parameter in parameters}) != len(parameters):
        raise _fail(where, "name each parameter once")
    return tuple(parameters)


def _plans(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _fail(where, "names the body plans it fits")
    plans = tuple(
        plan
        if plan == ANY_PLAN_WITH_BONES
        else _matching(f"{where}[{i}]", plan, _PLAN, "a body plan name")
        for i, plan in enumerate(value)
    )
    if len(set(plans)) != len(plans):
        raise _fail(where, "names each plan once")
    return plans


def _container(where: str, value: object) -> str:
    if value not in ("required", "none"):
        raise _fail(where, "is required or none")
    return str(value)


def _schema(catalog_id: str, version: int, fields: tuple[tuple[str, Any], ...]) -> CatalogSchema:
    return CatalogSchema(catalog_id, version, (*fields, ("reason", text_field)))


#: What each catalog's entries carry besides ``key``, ``licence`` and ``reason``, by catalog id.
_FIELDS: Final[Mapping[str, tuple[tuple[str, Any], ...]]] = MappingProxyType(
    {
        "body-plans": (
            ("version", integer_field(1, 1_000)),
            ("title", lambda where, value: _text(where, value, maximum=80)),
            ("bones", _Nested(_bones)),
            ("sockets", _Nested(_sockets)),
            ("size", _Nested(_size)),
            ("reach_mm", _Nested(_reach)),
            ("motions", _Nested(_motions)),
            ("moves", _Nested(_modules)),
        ),
        "abilities": (
            ("module", _module),
            ("needs", _Nested(_needs)),
            ("target_offer", _Nested(_target)),
            ("takes_line", _Nested(_flag)),
            ("words", _words),
            ("parameters", _Nested(_ability_parameters)),
        ),
        "offers": (("words", _words), ("parameters", _Nested(_offer_parameters))),
        "look-kinds": (
            ("plans", _Nested(_plans)),
            ("container", _container),
            ("rig", _Nested(_flag)),
            ("light", _Nested(_flag)),
            ("role", _Nested(_flag)),
            ("words", _words),
        ),
    }
)


def _values(catalog_id: str, entry: CatalogEntry) -> dict[str, Any]:
    """An entry's fields as read: plain where plain, and nested ones parsed back from their text."""
    nested = {name for name, check in _FIELDS[catalog_id] if isinstance(check, _Nested)}
    return {
        name: json.loads(str(value)) if name in nested else value for name, value in entry.values
    }


def _body_plan(where: str, entry: CatalogEntry) -> BodyPlan:
    values = _values("body-plans", entry)
    bones = _bones(f"{where}.bones", values["bones"])
    sockets = _sockets(f"{where}.sockets", values["sockets"])
    names = {bone.name for bone in bones}
    for index, socket in enumerate(sockets):
        if socket.bone is not None and socket.bone not in names:
            raise _fail(f"{where}.sockets[{index}].bone", "names one of the plan's bones")
    required, optional = _motions(f"{where}.motions", values["motions"])
    return BodyPlan(
        key=entry.key,
        version=int(values["version"]),
        title=str(values["title"]),
        bones=bones,
        sockets=sockets,
        size=_size(f"{where}.size", values["size"]),
        reach_mm=_reach(f"{where}.reach_mm", values["reach_mm"]),
        motions_required=required,
        motions_optional=optional,
        moves=_modules(f"{where}.moves", values["moves"]),
        reason=str(values["reason"]),
        licence=entry.licence,
    )


#: The fields of a body plan document, which a catalog entry states as ``key`` and fields.
_PLAN_DOCUMENT: Final = frozenset(
    {
        "profile",
        "key",
        "version",
        "title",
        "bones",
        "limbs",
        "sockets",
        "size",
        "reach_mm",
        "motions",
        "moves",
        "reason",
        "origin",
    }
)
#: The refusals a body plan document meets, each with what it means.
BODY_PLAN_CODES: Final = (
    (
        "body_plan_invalid",
        "The document is not a body plan: a field it does not state, a value out of shape, a "
        "chain that is not the plan's own bones.",
    ),
    ("body_plan_name_taken", "A key a shipped body plan already has."),
    ("body_plan_too_many_bones", f"More than {BODY_PLAN_BONES_MAXIMUM} bones."),
    ("body_plan_origin_invalid", "An origin record the origin reader refuses."),
)


def read_body_plan(raw: object, *, catalogs: ThingCatalogs | None = None) -> BodyPlan:
    """``raw`` as a body plan document (:data:`BODY_PLAN_PROFILE`): a plan a model drafted for a
    workspace, read by the same field readers as a catalog entry, with its limbs, its origin
    record and its digest, or :class:`BodyPlanRefused`. Its key may not be a shipped plan's."""
    catalogs = catalogs or thing_catalogs()
    if not isinstance(raw, Mapping) or set(raw) != _PLAN_DOCUMENT:
        raise BodyPlanRefused(
            "body_plan_invalid", "plan", f"states exactly {sorted(_PLAN_DOCUMENT)}"
        )
    document = dict(raw)
    try:
        canonical_json(document)
    except CanonicalisationError as exc:
        raise BodyPlanRefused("body_plan_invalid", "plan", f"is canonical JSON: {exc}") from exc
    if document["profile"] != BODY_PLAN_PROFILE:
        raise BodyPlanRefused("body_plan_invalid", "profile", f"is {BODY_PLAN_PROFILE}")
    key = document["key"]
    if type(key) is not str or _PLAN_KEY.fullmatch(key) is None:
        raise BodyPlanRefused("body_plan_invalid", "key", "is a lowercase key")
    if any(plan.key == key for plan in catalogs.plans.values()):
        raise BodyPlanRefused("body_plan_name_taken", "key", f"{key} is a shipped body plan's key")
    try:
        version = _whole("version", document["version"], 1, 1_000)
        title = _text("title", document["title"], maximum=80)
        if not isinstance(document["bones"], list) or not document["bones"]:
            raise _fail("bones", "is a list of at least one bone")
        if len(document["bones"]) > BODY_PLAN_BONES_MAXIMUM:
            raise BodyPlanRefused(
                "body_plan_too_many_bones",
                "bones",
                f"a body here has at most {BODY_PLAN_BONES_MAXIMUM} bones",
            )
        bones = _bones("bones", document["bones"])
        limbs = _limbs("limbs", document["limbs"], bones)
        sockets = _sockets("sockets", document["sockets"])
        names = {bone.name for bone in bones}
        for index, socket in enumerate(sockets):
            if socket.bone is not None and socket.bone not in names:
                raise _fail(f"sockets[{index}].bone", "names one of the plan's bones")
        required, optional = _motions("motions", document["motions"])
        for at, motion in [
            *(("motions.required", m) for m in required),
            *(("motions.optional", m) for m in optional),
        ]:
            if motion not in MOTIONS:
                raise _fail(at, f"names motions among {list(MOTIONS)}")
        size = _size("size", document["size"])
        reach = _reach("reach_mm", document["reach_mm"])
        moves = _modules("moves", document["moves"])
        reason = _text("reason", document["reason"])
    except ThingCatalogError as exc:
        where, _, detail = str(exc).partition(": ")
        raise BodyPlanRefused("body_plan_invalid", where, detail) from exc
    try:
        read_origin(document["origin"], where="origin")
    except OriginRefused as exc:
        raise BodyPlanRefused("body_plan_origin_invalid", "origin", str(exc)) from exc
    return BodyPlan(
        key=key,
        version=version,
        title=title,
        bones=bones,
        sockets=sockets,
        size=size,
        reach_mm=reach,
        motions_required=required,
        motions_optional=optional,
        moves=moves,
        reason=reason,
        licence=None,
        limbs=limbs,
        origin=MappingProxyType(dict(document["origin"])),
        sha256=sha256_of_canonical(document).hex(),
    )


def _ability(where: str, entry: CatalogEntry) -> Ability:
    values = _values("abilities", entry)
    socket, moves = _needs(f"{where}.needs", values["needs"])
    return Ability(
        key=entry.key,
        module=str(values["module"]),
        needs_socket=socket,
        needs_moves=moves,
        target_offer=_target(f"{where}.target_offer", values["target_offer"]),
        takes_line=_flag(f"{where}.takes_line", values["takes_line"]),
        words=str(values["words"]),
        parameters=_ability_parameters(f"{where}.parameters", values["parameters"]),
        reason=str(values["reason"]),
        licence=entry.licence,
    )


def _offer(where: str, entry: CatalogEntry) -> Offer:
    values = _values("offers", entry)
    return Offer(
        key=entry.key,
        words=str(values["words"]),
        parameters=_offer_parameters(f"{where}.parameters", values["parameters"]),
        reason=str(values["reason"]),
        licence=entry.licence,
    )


def _look_kind(where: str, entry: CatalogEntry) -> LookKind:
    values = _values("look-kinds", entry)
    return LookKind(
        key=entry.key,
        plans=_plans(f"{where}.plans", values["plans"]),
        container=str(values["container"]),
        rig=_flag(f"{where}.rig", values["rig"]),
        light=_flag(f"{where}.light", values["light"]),
        role=_flag(f"{where}.role", values["role"]),
        words=str(values["words"]),
        reason=str(values["reason"]),
        licence=entry.licence,
    )


@dataclass(frozen=True)
class ThingCatalogs:
    """The four vocabularies at the versions read, each by key, and one digest over them."""

    plans: Mapping[str, BodyPlan]
    abilities: Mapping[str, Ability]
    offers: Mapping[str, Offer]
    look_kinds: Mapping[str, LookKind]
    versions: Mapping[str, int]
    sha256: str

    def plan(self, name: str) -> BodyPlan | None:
        return self.plans.get(name)


def _newest(directory: Path, catalog_id: str) -> Catalog:
    """The newest version of one catalog in ``directory``, read against its schema."""
    versions = sorted(
        split_versioned_name(path)[1] for path in directory.glob(f"{catalog_id}.v*.json")
    )
    if not versions:
        raise ThingCatalogError(f"{directory} holds no {catalog_id} catalog")
    newest = versions[-1]
    return load_catalog(
        directory / f"{catalog_id}.v{newest}.json",
        _schema(catalog_id, newest, _FIELDS[catalog_id]),
    )


def load_thing_catalogs(directory: Path = CATALOG_DIRECTORY) -> ThingCatalogs:
    """The four catalogs at their newest versions in ``directory``, held to each other: every
    ability's target offer is an offer, every look kind's plans are plans."""
    read = {catalog_id: _newest(directory, catalog_id) for catalog_id in _FIELDS}
    plans = {}
    for index, entry in enumerate(read["body-plans"].entries):
        plan = _body_plan(f"body-plans[{index}]", entry)
        if plan.name in plans:
            raise ThingCatalogError(f"body-plans[{index}] states {plan.name} twice")
        plans[plan.name] = plan
    abilities = {
        entry.key: _ability(f"abilities[{index}]", entry)
        for index, entry in enumerate(read["abilities"].entries)
    }
    offers = {
        entry.key: _offer(f"offers[{index}]", entry)
        for index, entry in enumerate(read["offers"].entries)
    }
    look_kinds = {
        entry.key: _look_kind(f"look-kinds[{index}]", entry)
        for index, entry in enumerate(read["look-kinds"].entries)
    }
    for ability in abilities.values():
        if ability.target_offer is not None and ability.target_offer not in offers:
            raise ThingCatalogError(f"ability {ability.key} targets an offer no catalog states")
    for look_kind in look_kinds.values():
        if set(look_kind.plans) - set(plans) - {ANY_PLAN_WITH_BONES}:
            raise ThingCatalogError(f"look kind {look_kind.key} fits plans no catalog states")
    return ThingCatalogs(
        plans=MappingProxyType(plans),
        abilities=MappingProxyType(abilities),
        offers=MappingProxyType(offers),
        look_kinds=MappingProxyType(look_kinds),
        versions=MappingProxyType(
            {catalog_id: catalog.catalog_version for catalog_id, catalog in read.items()}
        ),
        sha256=catalog_digest(list(read.values())),
    )


@cache
def thing_catalogs() -> ThingCatalogs:
    """The catalogs this process reads, once."""
    return load_thing_catalogs(CATALOG_DIRECTORY)
