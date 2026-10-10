"""What a society runs of a kind its workspace keeps: the kind's run form, which holds no words.

A kind a workspace keeps (a creature drafted from a person's words, :mod:`exulanica.things.
creatures`) holds words drafted from that person's: its label, its key, its summary, its plan's
title, its recipe's appearance and the digest of the words themselves. An erasure promises every
one of them gone at once (:mod:`exulanica.world.thing_store`), and a society's records are bound to
each other by digest, so none of them can be blanked afterwards. A society therefore never holds
them. What it runs of such a kind is this document, profile ``exulanica.thing-kind-run/v1``, built
here by code from the kept kind, its drafted plan and that plan's recipe:

*   its **reference**, the digest of the kind's document alone (``{source: "workspace", sha256}``,
    as a placed thing and a worn look name what a workspace keeps);
*   its **body**: the plan's digest, the kind's four figures, the plan's reach and sockets, and the
    recipe's figures and grammar names (posture, spine, heads, limbs, tail, what it holds with,
    colours), never its appearance;
*   what it **moves** by, its **abilities** and **offers**, its routine's weights and its
    **deciders**, as the kind states them; with the walking it moves by, its **pace** in
    thousandths of a society's own, from its body's standing height
    (:func:`exulanica.things.gaits.pace_permille`, ``assets/catalogs/things/gaits.v1.json``);
*   its **label**, a body name, and its **summary**, a sentence of its size, its parts, whether
    it walks and what it carries with: catalog words built from the body's own figures
    (:func:`body_name`, :func:`body_summary`, ``assets/catalogs/things/body-names.v1.json``),
    which a society names it by and a decider reads. The name and the summary its maker's words
    gave it are the workspace's to show.

The document is an allow-list written field by field, never the kind with fields removed, and
:func:`read_run_form` holds every string of it to a catalog's vocabulary, a module's name or a
digest, and its label and summary to what its own figures give under the names catalog it states.
So no field of a run form can carry a word a person wrote, whoever composed it.

A later run form is a new profile beside this one; a society keeps the one its input recorded.
:func:`body_name`, :func:`body_summary` and the reader are frozen with this profile and the names
catalog version a form states: a stored input or state holding a made kind is read by them as
written, against the body grammar and the ability and offer catalogs as they stand, so a change to
any of them that a stored form would no longer pass is a new profile or a new catalog version.

Pure: no connection, no store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.grammar.catalogs import CatalogSchema, load_catalog, text_field
from exulanica.grammar.errors import CatalogError
from exulanica.things.bodies import BodyGrammar, BodyRecipe, body_grammar
from exulanica.things.catalogs import (
    CATALOG_DIRECTORY,
    BodyPlan,
    ThingCatalogError,
    ThingCatalogs,
    thing_catalogs,
)
from exulanica.things.gaits import PACE_PERMILLE, pace_permille
from exulanica.things.kinds import ThingKind

__all__ = [
    "BODY_NAMES_ID",
    "RUN_FORM_FIELDS",
    "RUN_FORM_PROFILE",
    "WORKSPACE_SOURCE",
    "BodyNames",
    "RunFormRefused",
    "body_name",
    "body_names",
    "body_parts",
    "body_summary",
    "load_body_names",
    "read_run_form",
    "run_form",
    "workspace_reference",
]

RUN_FORM_PROFILE: Final = "exulanica.thing-kind-run/v1"
#: How a reference says its kind is the workspace's own, as a placed thing's does.
WORKSPACE_SOURCE: Final = "workspace"
BODY_NAMES_ID: Final = "body-names"
#: Exactly what a run form states.
RUN_FORM_FIELDS: Final = frozenset(
    {
        "profile",
        "reference",
        "class",
        "label",
        "summary",
        "named_by",
        "body",
        "moves",
        "abilities",
        "offers",
        "routine",
        "deciders",
    }
)
_BODY_FIELDS: Final = frozenset(
    {
        "plan_sha256",
        "extent_mm",
        "reach_mm",
        "posture",
        "upper_body",
        "spine",
        "heads",
        "limbs",
        "tail",
        "holds_with",
        "colours",
        "sockets",
    }
)
_EXTENT: Final = ("length", "width", "height", "span")
_LIMB_ROLES: Final = ("leg", "arm", "wing", "fin", "tentacle")
_HOLDS_WITH: Final = ("none", "jaws", "hands", "front_claws")
_DECIDERS: Final = ("routine", "model", "person", "external")
_SOCKET_FIELDS: Final = frozenset({"key", "holds", "length_mm_maximum", "grip_section_mm_maximum"})
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
#: A socket's key as the body builder and the plan catalog name one: a place, then whose.
_SOCKET_KEY: Final = re.compile(r"(mouth|hand|claw|float)(\.(left|right|head[1-9]))?")
_NAMED_BY: Final = re.compile(rf"{BODY_NAMES_ID}/v([1-9][0-9]{{0,3}})")
_FIGURE_MAXIMUM: Final = 10**9
_GROUPS: Final = ("noun", "limit", "feature", "number", "part", "sentence")
#: The parts a body name's features may count, each a figure of the run form's body.
_NAMED_PARTS: Final = ("heads", "wings", "legs", "tentacles", "arms", "fins", "spine")
_COUNT: Final = "{count}"
#: The parts a body summary counts, each with the word for one and for many.
_SUMMARY_PARTS: Final = ("heads", "wings", "legs", "tentacles", "arms", "fins")
_SENTENCE_FIELDS: Final = frozenset({"lead", "with", "tail", "join", "moves", "holds"})
_PLAIN: Final = re.compile(r"[A-Za-z0-9 .,{}]*")


class RunFormRefused(ValueError):
    """A run form the reader refuses: where, and why."""

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(f"{where}: {detail}")
        self.where = where
        self.detail = detail


def _refuse(where: str, detail: str) -> RunFormRefused:
    return RunFormRefused(where, detail)


# -- body names ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class BodyNames:
    """The body names catalog, read: the noun, the features in rank order, the number words and
    how many features a name states."""

    noun: str
    #: Each feature in rank order: ``(part, least, counted, without, words)``.
    features: tuple[tuple[str, int, bool, tuple[str, ...], str], ...]
    numbers: Mapping[int, str]
    features_maximum: int
    #: What a summary calls each part, in rank order: ``(part, one, many)``.
    parts: tuple[tuple[str, str, str], ...]
    #: The summary's sentence: its lead, how its parts are joined, and what it says of moving and
    #: of carrying, by what the body holds with.
    sentence: Mapping[str, Any]
    version: int

    @property
    def name(self) -> str:
        return f"{BODY_NAMES_ID}/v{self.version}"


def _spec(where: str, value: object) -> str:
    if not isinstance(value, Mapping):
        raise ThingCatalogError(f"{where}: is an object")
    try:
        return canonical_json(dict(value)).decode("utf-8")
    except CanonicalisationError as exc:
        raise ThingCatalogError(f"{where}: {exc}") from exc


def _group(where: str, value: object) -> str:
    if value not in _GROUPS:
        raise ThingCatalogError(f"{where}: is one of {list(_GROUPS)}")
    return str(value)


def _name_words(where: str, value: object) -> str:
    text = text_field(where, value)
    plain = text.replace(_COUNT, "count") if type(text) is str else ""
    if re.fullmatch(r"[a-z]+( [a-z]+)*", plain) is None or len(plain) > 40:
        raise ThingCatalogError(f"{where}: is lowercase words and spaces, at most 40 characters")
    return text


def load_body_names(version: int, directory: Path = CATALOG_DIRECTORY) -> BodyNames:
    """The body names catalog at ``version``, read and held to its shape."""
    schema = CatalogSchema(
        BODY_NAMES_ID,
        version,
        (("group", _group), ("words", _name_words), ("spec", _spec), ("reason", text_field)),
    )
    catalog = load_catalog(directory / f"{BODY_NAMES_ID}.v{version}.json", schema)
    nouns: list[str] = []
    limits: list[Mapping[str, Any]] = []
    features: list[tuple[int, tuple[str, int, bool, tuple[str, ...], str]]] = []
    numbers: dict[int, str] = {}
    parts: list[tuple[int, tuple[str, str, str]]] = []
    sentences: list[Mapping[str, Any]] = []
    for entry in catalog.entries:
        values = dict(entry.values)
        where = f"{BODY_NAMES_ID}.{entry.key}"
        spec = json.loads(str(values["spec"]))
        words = str(values["words"])
        group = values["group"]
        if group != "feature" and _COUNT in words:
            raise ThingCatalogError(f"{where}: only a feature's words state a count")
        if group == "noun":
            nouns.append(words)
        elif group == "limit":
            limits.append(spec)
        elif group == "number":
            value = spec.get("value")
            if set(spec) != {"value"} or type(value) is not int or value < 1 or value in numbers:
                raise ThingCatalogError(f"{where}: states one whole number, once")
            numbers[value] = words
        elif group == "part":
            if (
                set(spec) != {"part", "one", "rank"}
                or spec["part"] not in _SUMMARY_PARTS
                or spec["part"] != words
                or not isinstance(spec["one"], str)
                or re.fullmatch(r"[a-z]+", spec["one"]) is None
                or type(spec["rank"]) is not int
            ):
                raise ThingCatalogError(
                    f"{where}: a part states which it is (its words, many), its word for one "
                    "and its rank"
                )
            parts.append((spec["rank"], (spec["part"], spec["one"], words)))
        elif group == "sentence":
            texts = [spec.get(name) for name in ("lead", "with", "tail", "join")] + [
                text
                for name in ("moves", "holds")
                for text in (spec.get(name) or {}).values()
                if isinstance(spec.get(name), Mapping)
            ]
            if (
                set(spec) != _SENTENCE_FIELDS
                or not isinstance(spec["moves"], Mapping)
                or set(spec["moves"]) != {"walks", "still"}
                or not isinstance(spec["holds"], Mapping)
                or set(spec["holds"]) != set(_HOLDS_WITH)
                or not all(isinstance(t, str) and _PLAIN.fullmatch(t) for t in texts)
            ):
                raise ThingCatalogError(
                    f"{where}: a sentence states its lead, how parts are joined, a tail, and "
                    "what it says of moving and of each way of carrying, in plain characters"
                )
            sentences.append(MappingProxyType(spec))
        else:
            without = spec.get("without", [])
            if (
                not {"part", "least", "rank", "counted"} <= set(spec)
                or not set(spec) <= {"part", "least", "rank", "counted", "without"}
                or spec["part"] not in _NAMED_PARTS
                or type(spec["least"]) is not int
                or spec["least"] < 1
                or type(spec["rank"]) is not int
                or type(spec["counted"]) is not bool
                or not isinstance(without, list)
                or not all(part in _NAMED_PARTS for part in without)
                or spec["counted"] != (_COUNT in words)
            ):
                raise ThingCatalogError(
                    f"{where}: a feature states its part, the least of it, its rank, whether it "
                    "is counted, and its words with a count exactly where it is"
                )
            features.append(
                (
                    spec["rank"],
                    (spec["part"], spec["least"], spec["counted"], tuple(without), words),
                )
            )
    ranks = [rank for rank, _ in features]
    if (
        len(nouns) != 1
        or len(limits) != 1
        or len(sentences) != 1
        or len(set(ranks)) != len(ranks)
        or sorted(part for _rank, (part, _one, _many) in parts) != sorted(_SUMMARY_PARTS)
        or len({rank for rank, _ in parts}) != len(parts)
    ):
        raise ThingCatalogError(
            f"{BODY_NAMES_ID}: states one noun, one entry of limits, one sentence, each "
            "feature's rank once and each part once"
        )
    maximum = limits[0].get("features_maximum")
    if set(limits[0]) != {"features_maximum"} or type(maximum) is not int or maximum < 0:
        raise ThingCatalogError(f"{BODY_NAMES_ID}.limits: states features_maximum")
    return BodyNames(
        noun=nouns[0],
        features=tuple(feature for _rank, feature in sorted(features)),
        numbers=MappingProxyType(numbers),
        features_maximum=maximum,
        parts=tuple(part for _rank, part in sorted(parts)),
        sentence=sentences[0],
        version=catalog.catalog_version,
    )


@cache
def body_names(version: int = 1) -> BodyNames:
    """The shipped body names catalog at ``version``. A new run form names under the newest
    version this function defaults to; a recorded one is read under the version it states."""
    return load_body_names(version)


def body_parts(body: Mapping[str, Any]) -> dict[str, int]:
    """How many of each part a run form's body has, as a body name counts them: single limbs
    (a pair of legs is two legs), heads and spine segments."""
    counts = {str(limb["role"]): int(limb["count"]) for limb in body["limbs"]}
    return {
        "heads": len(body["heads"]),
        "wings": counts.get("wing", 0),
        "legs": counts.get("leg", 0),
        "tentacles": counts.get("tentacle", 0),
        "arms": counts.get("arm", 0),
        "fins": counts.get("fin", 0),
        "spine": int(body["spine"]),
    }


def body_name(body: Mapping[str, Any], names: BodyNames | None = None) -> str:
    """The name a society gives a body: its first features in the catalog's rank order, at most
    as many as the catalog states, then the noun. Words and spaces alone."""
    names = names or body_names()
    parts = body_parts(body)
    said: list[str] = []
    for part, least, counted, without, words in names.features:
        if len(said) >= names.features_maximum:
            break
        if parts[part] < least or any(parts[other] > 0 for other in without):
            continue
        if counted:
            number = names.numbers.get(parts[part])
            if number is None:
                continue
            said.append(words.replace(_COUNT, number))
        else:
            said.append(words)
    return " ".join([*said, names.noun])


def _metres(millimetres: int) -> str:
    """A length in metres as a decider reads it: to a tenth below ten metres, whole from there."""
    tenths = (millimetres + 50) // 100
    if tenths >= 100:
        return f"{(millimetres + 500) // 1000} m"
    return f"{tenths // 10}.{tenths % 10} m"


def body_summary(body: Mapping[str, Any], walks: bool, names: BodyNames | None = None) -> str:
    """What a decider reads of a body: its length and height, its parts by count in the
    catalog's order, a tail where it has one, whether it walks, and what it carries with. One
    plain line, every word the catalog's and every figure the body's own."""
    names = names or body_names()
    counts = body_parts(body)
    sentence = names.sentence
    said = []
    for part, one, many in names.parts:
        count = counts[part]
        if count < 1:
            continue
        said.append(f"{names.numbers.get(count, str(count))} {one if count == 1 else many}")
    if int(body["tail"]) > 0:
        said.append(str(sentence["tail"]))
    listed = ""
    if said:
        joined = ", ".join(said[:-1]) + (str(sentence["join"]) if len(said) > 1 else "") + said[-1]
        listed = str(sentence["with"]).replace("{parts}", joined)
    lead = (
        str(sentence["lead"])
        .replace("{length}", _metres(int(body["extent_mm"]["length"])))
        .replace("{height}", _metres(int(body["extent_mm"]["height"])))
    )
    return (
        f"{lead}{listed}."
        f"{sentence['moves']['walks' if walks else 'still']}"
        f"{sentence['holds'][body['holds_with']]}"
    )


# -- the run form -------------------------------------------------------------------------------


def workspace_reference(sha256: str) -> dict[str, str]:
    """How a society names a kind its workspace keeps: by its document's digest alone."""
    return {"sha256": sha256, "source": WORKSPACE_SOURCE}


def _move(entry: object) -> dict[str, Any]:
    if isinstance(entry, str):
        return {"module": entry, "parameters": {}}
    assert isinstance(entry, Mapping)
    return {"module": str(entry["module"]), "parameters": dict(entry.get("parameters", {}))}


def run_form(
    kind: ThingKind,
    plan: BodyPlan,
    recipe: BodyRecipe,
    *,
    names: BodyNames | None = None,
    grammar: BodyGrammar | None = None,
    catalogs: ThingCatalogs | None = None,
) -> dict[str, Any]:
    """The run form of ``kind``, a being drafted on ``plan``, which was built from ``recipe``:
    each field written from a figure, a catalog name or a digest, read back by
    :func:`read_run_form` before it is returned. :class:`RunFormRefused` where the three do not
    belong together or the result does not read."""
    names = names or body_names()
    document = kind.document
    if kind.klass != "being" or document["body"].get("plan_sha256") != plan.sha256:
        raise _refuse("kind", "is a being drafted on the plan given, named by its digest")
    lineage = (plan.origin or {}).get("lineage", {})
    if recipe.sha256 not in lineage.get("ingredients", ()):
        raise _refuse("recipe", "is the recipe the plan was built from")
    stated = {
        str(limb["role"]): (int(limb["count"]), int(limb["segments"]))
        for limb in recipe.document["limbs"]
    }
    body = {
        "plan_sha256": plan.sha256,
        "extent_mm": {side: int(document["body"]["extent_mm"][side]) for side in _EXTENT},
        "reach_mm": plan.reach_mm,
        "posture": recipe.posture,
        "upper_body": recipe.upper_body,
        "spine": recipe.spine,
        "heads": [{"neck": neck, "jaw": jaw} for neck, jaw in recipe.heads],
        # Single limbs, as the recipe's document counts them (a pair of legs is two).
        "limbs": [
            {"role": role, "count": stated[role][0], "segments": stated[role][1]}
            for role in _LIMB_ROLES
            if role in stated and stated[role][0] > 0
        ],
        "tail": recipe.tail,
        "holds_with": recipe.holds_with,
        "colours": list(recipe.colours),
        "sockets": [
            {
                "key": socket.key,
                "holds": socket.holds,
                "length_mm_maximum": socket.length_mm_maximum,
                "grip_section_mm_maximum": socket.grip_section_mm_maximum,
            }
            for socket in plan.sockets
        ],
    }
    deciders = document["deciders"]
    routine = document["routine"]
    shipped = _shipped_kind_keys()
    moves = [_move(entry) for entry in document["moves"]]
    for move in moves:
        # A body that walks states the pace its own standing height gives it.
        if PACE_PERMILLE in _MOVE_PARAMETERS.get(move["module"], frozenset()):
            move["parameters"][PACE_PERMILLE] = pace_permille(recipe)
    form = {
        "profile": RUN_FORM_PROFILE,
        "reference": workspace_reference(kind.sha256),
        "class": "being",
        "label": body_name(body, names),
        "summary": body_summary(body, bool(moves), names),
        "named_by": names.name,
        "body": body,
        "moves": moves,
        "abilities": [
            {"key": str(ability["key"]), "parameters": dict(ability["parameters"])}
            for ability in document["abilities"]
        ],
        "offers": [
            {"key": str(offer["key"]), "parameters": dict(offer["parameters"])}
            for offer in document["offers"]
        ],
        "routine": {
            "weights": {str(key): int(weight) for key, weight in routine["weights"].items()},
            # Only a shipped kind's key is carried: a kept kind's key is words.
            "follow_holders_of": [
                str(key) for key in routine["follow_holders_of"] if key in shipped
            ],
        },
        "deciders": {
            "default": str(deciders["default"]),
            "allowed": [str(allowed) for allowed in deciders["allowed"]],
        },
    }
    read_run_form(form, grammar=grammar, catalogs=catalogs)
    return form


@cache
def _shipped_kind_keys() -> frozenset[str]:
    """The keys of the kinds this release ships, read once."""
    from exulanica.things.kinds import shipped_thing_kinds

    return frozenset(key for key, _version in shipped_thing_kinds())


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _refuse(where, f"states exactly {sorted(keys)}")
    return value


def _whole(where: str, value: object, minimum: int, maximum: int = _FIGURE_MAXIMUM) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _refuse(where, f"is a whole number from {minimum} to {maximum}")
    return value


def _keyed(
    where: str, value: object, vocabulary: Mapping[str, Any], what: str
) -> list[Mapping[str, Any]]:
    """A list of ``{key, parameters}``, each key from ``vocabulary`` once, each parameter a whole
    number under a name that key's catalog entry declares."""
    if not isinstance(value, list) or len(value) > len(vocabulary):
        raise _refuse(where, "is a list no longer than its catalog")
    seen: set[str] = set()
    for index, entry in enumerate(value):
        at = f"{where}[{index}]"
        row = _closed(at, entry, frozenset({"key", "parameters"}))
        if row["key"] not in vocabulary or row["key"] in seen:
            raise _refuse(f"{at}.key", f"is {what} of the catalogs, named once")
        seen.add(row["key"])
        declared = frozenset(parameter.name for parameter in vocabulary[row["key"]].parameters)
        _figures(f"{at}.parameters", row["parameters"], declared)
    return value


def _figures(where: str, value: object, declared: frozenset[str]) -> None:
    """Whole numbers under names from ``declared`` alone: the names a module, an ability or an
    offer states for the figures a kind may give it, so a parameter's name is never free text."""
    if not isinstance(value, Mapping) or not all(
        name in declared and type(figure) is int and abs(figure) <= _FIGURE_MAXIMUM
        for name, figure in value.items()
    ):
        raise _refuse(where, "holds whole numbers under the names its catalog entry declares")


#: The figures a run form may state for a movement module its kind moves by, by module: the
#: walking a body moves by takes its pace. Each is optional: a form written before a figure was
#: declared states none and reads as it did, and whatever reads the figure takes its absence as
#: the society's own pace. Another module that takes a figure from each kind (a wingspan) is
#: added here with that figure's name.
_MOVE_PARAMETERS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {"exulanica-movement/walking/v1": frozenset({PACE_PERMILLE})}
)
#: The widest a pace may be read: from one thousandth of a society's own pace to ten times it.
#: The gaits catalog holds a pace it computes to its own, narrower limits.
_PACE_RANGE: Final = (1, 10_000)


def read_run_form(
    document: object,
    *,
    grammar: BodyGrammar | None = None,
    catalogs: ThingCatalogs | None = None,
) -> Mapping[str, Any]:
    """``document`` held to a run form's shape, or :class:`RunFormRefused` naming the field.

    Every string is a digest, a module's name, a socket's key or a name of the body grammar or the
    things catalogs; every other value is a whole number or true or false; and the label is the
    name the body's own figures give under the names catalog ``named_by`` states. A document that
    passes holds nothing that could be a person's words."""
    grammar = grammar or body_grammar()
    catalogs = catalogs or thing_catalogs()
    form = _closed("run form", document, RUN_FORM_FIELDS)
    if form["profile"] != RUN_FORM_PROFILE:
        raise _refuse("profile", f"is {RUN_FORM_PROFILE}")
    reference = _closed("reference", form["reference"], frozenset({"source", "sha256"}))
    if (
        reference["source"] != WORKSPACE_SOURCE
        or not isinstance(reference["sha256"], str)
        or _HEX64.fullmatch(reference["sha256"]) is None
    ):
        raise _refuse("reference", "names a workspace's own kind by its document's digest")
    if form["class"] != "being":
        raise _refuse("class", "is being")
    body = _closed("body", form["body"], _BODY_FIELDS)
    if not isinstance(body["plan_sha256"], str) or _HEX64.fullmatch(body["plan_sha256"]) is None:
        raise _refuse("body.plan_sha256", "is a digest")
    extent = _closed("body.extent_mm", body["extent_mm"], frozenset(_EXTENT))
    for side in _EXTENT:
        _whole(f"body.extent_mm.{side}", extent[side], 0)
    if body["reach_mm"] is not None:
        _whole("body.reach_mm", body["reach_mm"], 0)
    if body["posture"] not in grammar.postures:
        raise _refuse("body.posture", f"is one of {sorted(grammar.postures)}")
    if type(body["upper_body"]) is not bool:
        raise _refuse("body.upper_body", "is true or false")
    _whole("body.spine", body["spine"], 1, 128)
    _whole("body.tail", body["tail"], 0, 128)
    heads = body["heads"]
    if not isinstance(heads, list) or not 1 <= len(heads) <= 16:
        raise _refuse("body.heads", "is a list of heads")
    for index, head in enumerate(heads):
        row = _closed(f"body.heads[{index}]", head, frozenset({"neck", "jaw"}))
        _whole(f"body.heads[{index}].neck", row["neck"], 0, 128)
        if type(row["jaw"]) is not bool:
            raise _refuse(f"body.heads[{index}].jaw", "is true or false")
    limbs = body["limbs"]
    if not isinstance(limbs, list):
        raise _refuse("body.limbs", "is a list")
    roles = []
    for index, limb in enumerate(limbs):
        row = _closed(f"body.limbs[{index}]", limb, frozenset({"role", "count", "segments"}))
        if row["role"] not in _LIMB_ROLES:
            raise _refuse(f"body.limbs[{index}].role", f"is one of {list(_LIMB_ROLES)}")
        roles.append(_LIMB_ROLES.index(row["role"]))
        _whole(f"body.limbs[{index}].count", row["count"], 1, 128)
        _whole(f"body.limbs[{index}].segments", row["segments"], 1, 128)
    if roles != sorted(set(roles)):
        raise _refuse("body.limbs", "names each role once, in the grammar's order")
    if body["holds_with"] not in _HOLDS_WITH:
        raise _refuse("body.holds_with", f"is one of {list(_HOLDS_WITH)}")
    colours = body["colours"]
    if (
        not isinstance(colours, list)
        or len(colours) > int(grammar.limits["colours"]["maximum"])
        or not all(colour in grammar.colours for colour in colours)
    ):
        raise _refuse("body.colours", "names colours of the body grammar, as many as it allows")
    sockets = body["sockets"]
    if not isinstance(sockets, list) or len(sockets) > 16:
        raise _refuse("body.sockets", "is a list of at most 16 sockets")
    keys = []
    for index, socket in enumerate(sockets):
        at = f"body.sockets[{index}]"
        row = _closed(at, socket, _SOCKET_FIELDS)
        if not isinstance(row["key"], str) or _SOCKET_KEY.fullmatch(row["key"]) is None:
            raise _refuse(f"{at}.key", "is a socket's key as a body plan names one")
        keys.append(row["key"])
        _whole(f"{at}.holds", row["holds"], 1, 16)
        _whole(f"{at}.length_mm_maximum", row["length_mm_maximum"], 1)
        if row["grip_section_mm_maximum"] is not None:
            _whole(f"{at}.grip_section_mm_maximum", row["grip_section_mm_maximum"], 1)
    if len(set(keys)) != len(keys):
        raise _refuse("body.sockets", "names each socket once")
    # The movement modules a body may move by are the ones the body grammar's movements name.
    modules = {
        str(spec["module"]) for spec in grammar.movements.values() if spec.get("module") is not None
    }
    moves = form["moves"]
    if not isinstance(moves, list) or len(moves) > len(modules):
        raise _refuse("moves", "is a list no longer than the movement modules the grammar names")
    moved_by: set[str] = set()
    for index, move in enumerate(moves):
        row = _closed(f"moves[{index}]", move, frozenset({"module", "parameters"}))
        if row["module"] not in modules or row["module"] in moved_by:
            raise _refuse(
                f"moves[{index}].module", "is a movement module the body grammar names, once"
            )
        moved_by.add(row["module"])
        _figures(
            f"moves[{index}].parameters",
            row["parameters"],
            _MOVE_PARAMETERS.get(row["module"], frozenset()),
        )
        pace = row["parameters"].get(PACE_PERMILLE)
        if pace is not None and not _PACE_RANGE[0] <= pace <= _PACE_RANGE[1]:
            raise _refuse(
                f"moves[{index}].parameters.{PACE_PERMILLE}",
                f"is a whole number of thousandths from {_PACE_RANGE[0]} to {_PACE_RANGE[1]}",
            )
    abilities = {
        entry["key"]
        for entry in _keyed("abilities", form["abilities"], catalogs.abilities, "an ability")
    }
    _keyed("offers", form["offers"], catalogs.offers, "an offer")
    routine = _closed("routine", form["routine"], frozenset({"weights", "follow_holders_of"}))
    weights = routine["weights"]
    if not isinstance(weights, Mapping) or not all(
        key in abilities and type(weight) is int and 0 <= weight <= 10_000
        for key, weight in weights.items()
    ):
        raise _refuse("routine.weights", "weighs abilities the kind has, 0 to 10,000")
    shipped = _shipped_kind_keys()
    follows = routine["follow_holders_of"]
    if not isinstance(follows, list) or not all(key in shipped for key in follows):
        raise _refuse("routine.follow_holders_of", "names shipped kinds")
    deciders = _closed("deciders", form["deciders"], frozenset({"default", "allowed"}))
    allowed = deciders["allowed"]
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(set(allowed)) != len(allowed)
        or not all(one in _DECIDERS for one in allowed)
        or deciders["default"] not in allowed
    ):
        raise _refuse(
            "deciders", f"names deciders among {list(_DECIDERS)}, the default one of them"
        )
    named_by = form["named_by"]
    found = _NAMED_BY.fullmatch(named_by) if isinstance(named_by, str) else None
    if found is None:
        raise _refuse("named_by", f"is {BODY_NAMES_ID}/v<N>")
    try:
        names = body_names(int(found.group(1)))
    except (CatalogError, OSError) as exc:
        raise _refuse("named_by", "names a body names catalog this release holds") from exc
    if form["label"] != body_name(body, names):
        raise _refuse("label", "is the name its body's figures give under the catalog it states")
    if form["summary"] != body_summary(body, bool(moves), names):
        raise _refuse(
            "summary", "is the sentence its body's figures give under the catalog it states"
        )
    return form
