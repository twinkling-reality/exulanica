"""A creature from a drafted form: its recipe, body plan, kind and sketch look, checked as one.

A model asked for a creature a person imagined fills one form (:mod:`exulanica.selection.
creature_drafting` builds it and asks): a label and a summary, a body recipe's figures, the
movements it should have, its abilities and offers from the things catalogs, and its routine's
weights. :func:`assemble_creature` turns that form into four typed, versioned, fingerprinted
documents and holds each to the reader that owns it, so nothing about a creature is checked by
anything but the checks every thing passes:

1.  the **body recipe** (:func:`~exulanica.things.bodies.read_body_recipe`), which the body
    grammar bounds;
2.  the **body plan** built from it (:func:`~exulanica.things.bodies.build_body`), read back by
    :func:`~exulanica.things.catalogs.read_body_plan`;
3.  the **sketch look** of that plan (:func:`~exulanica.things.sketch.sketch_look`), read by
    :func:`~exulanica.things.looks.read_look`;
4.  the **thing kind** naming the plan by name and digest and the sketch as its first look, read by
    :func:`~exulanica.things.kinds.read_thing_kind`.

What a body cannot do, and what this world cannot do yet, is refused by name in a sentence a
person reads and a drafting model is told (:data:`CREATURE_CODES`): a creature asked to fly with
no wings, or to swim where no swimming is built. A refusal from any reader keeps that reader's
own code. Nothing names any particular creature: every creature is this function's data.

Pure: no connection, no store, no model.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.things.bodies import (
    BODY_RECIPE_PROFILE,
    BodyGrammar,
    BodyRefused,
    body_grammar,
    build_body,
    enabled_movements,
    read_body_recipe,
)
from exulanica.things.catalogs import (
    BodyPlan,
    BodyPlanRefused,
    ThingCatalogs,
    read_body_plan,
    thing_catalogs,
)
from exulanica.things.kinds import (
    THING_KIND_PROFILE,
    ThingKind,
    ThingKindRefused,
    read_thing_kind,
    shipped_thing_kinds,
)
from exulanica.things.looks import Look, LookRefused, read_look
from exulanica.things.origin import ORIGIN_PROFILE
from exulanica.things.sketch import sketch_look

__all__ = [
    "CREATURE_ABILITIES",
    "CREATURE_CODES",
    "CREATURE_OFFERS",
    "Creature",
    "CreatureRefused",
    "assemble_creature",
    "creature_key",
]

#: The abilities a creature may be drafted with: everything a being of the catalogs can do but
#: leaving, which only a visitor from outside the world has.
CREATURE_ABILITIES: Final = (
    "wait",
    "stand",
    "talk",
    "rest",
    "visit",
    "pick_up",
    "put_down",
    "give",
    "take",
    "follow",
    "say",
)
#: What a creature may let others do to it: the offers a being makes, which take no parameters.
CREATURE_OFFERS: Final = ("talk_to", "hear", "receive", "let_take", "be_followed")
#: The refusals only a creature meets, each with its sentence: what a person reads and what the
#: drafting model is told when it is asked again.
CREATURE_CODES: Final = (
    (
        "creature_cannot_move_so",
        "A creature moves only in the ways its body allows: it walks on legs, four or more "
        "tentacles or a long body, and flies with a pair of wings or a floating body.",
    ),
    (
        "creature_movement_unbuilt",
        "A creature may ask only for movements this world has built; the movement's own sentence "
        "says which are not built yet.",
    ),
    (
        "creature_name_taken",
        "A creature's name is new: it is not the name of a kind of thing this world already has.",
    ),
    (
        "creature_form_invalid",
        "The form states exactly its fields, each from its own list: the abilities, offers, "
        "movements and colours the instructions name.",
    ),
)
_LABEL: Final = re.compile(r"[a-z][a-z ]{0,38}[a-z]")
_ROUTINE_REASON: Final = (
    "Drafted with the creature: the weights the drafting model gave its abilities, which its "
    "routine draws among whenever no mind is choosing for it."
)
_SKETCH_LICENCE: Final = {
    "spdx": "CC0-1.0",
    "verdict": "SHIP",
    "attribution": None,
    "share_alike": False,
    "licence_url": None,
    "licence_text_sha256": None,
}
_DRAFTED_LICENCE: Final = {
    "spdx": "Apache-2.0",
    "verdict": "SHIP",
    "attribution": None,
    "share_alike": False,
    "licence_url": None,
    "licence_text_sha256": None,
}


class CreatureRefused(ValueError):
    """A drafted creature the checks refuse: the code of the check that refused it (a reader's own
    or one of :data:`CREATURE_CODES`), where in the form, and the sentence it reads as."""

    def __init__(self, code: str, where: str, detail: str) -> None:
        super().__init__(f"{code} at {where}: {detail}")
        self.code = code
        self.where = where
        self.detail = detail


@dataclass(frozen=True)
class Creature:
    """A creature assembled: each document as read, and the sketch's container."""

    recipe: Mapping[str, Any]
    recipe_sha256: str
    plan: BodyPlan
    plan_document: Mapping[str, Any]
    sketch: Look
    sketch_container: bytes
    kind: ThingKind

    @property
    def documents(self) -> Mapping[str, Mapping[str, Any]]:
        """The four documents by what each is, as the workspace's library keeps them."""
        return MappingProxyType(
            {
                "recipe": self.recipe,
                "plan": self.plan_document,
                "look": self.sketch.document,
                "kind": self.kind.document,
            }
        )


def creature_key(label: str) -> str:
    """The key a creature's kind and plan are named by: its label, spaces as underscores."""
    return label.replace(" ", "_")


def _refuse(code: str, where: str, detail: str) -> CreatureRefused:
    return CreatureRefused(code, where, detail)


def _origin(
    klass: str, by: Mapping[str, Any], licence: Mapping[str, Any], ingredients: Sequence[str]
) -> dict[str, Any]:
    return {
        "profile": ORIGIN_PROFILE,
        "class": klass,
        "by": dict(by),
        "sources": [],
        "licence": dict(licence),
        "authors": [],
        "lineage": {
            "ingredients": list(ingredients),
            "receipts": [],
            "translation_manifest_sha256": None,
        },
        "distribution": "private",
    }


def _form_value(form: Mapping[str, Any], name: str) -> Any:
    if name not in form:
        raise _refuse("creature_form_invalid", name, "the form states it")
    return form[name]


def _choices(form: Mapping[str, Any], name: str, allowed: Sequence[str], maximum: int) -> list[str]:
    values = _form_value(form, name)
    if not isinstance(values, list) or len(values) > maximum:
        raise _refuse("creature_form_invalid", name, f"is a list of at most {maximum}")
    for index, value in enumerate(values):
        if value not in allowed:
            raise _refuse("creature_form_invalid", f"{name}[{index}]", f"is one of {list(allowed)}")
    if len(set(values)) != len(values):
        raise _refuse("creature_form_invalid", name, "names each once")
    return [str(value) for value in values]


def recipe_of(form: Mapping[str, Any]) -> dict[str, Any]:
    """The body recipe document a drafted form states."""
    return {
        "profile": BODY_RECIPE_PROFILE,
        "posture": _form_value(form, "posture"),
        "spine": _form_value(form, "spine"),
        "upper_body": _form_value(form, "upper_body"),
        "heads": _form_value(form, "heads"),
        "limbs": _form_value(form, "limbs"),
        "tail": _form_value(form, "tail"),
        "extent_mm": {
            "length": _form_value(form, "length_mm"),
            "width": _form_value(form, "width_mm"),
            "height": _form_value(form, "height_mm"),
            "span": _form_value(form, "span_mm"),
        },
        "holds_with": _form_value(form, "holds_with"),
        "colours": _form_value(form, "colours"),
        "appearance": _form_value(form, "appearance"),
    }


def assemble_creature(
    form: Mapping[str, Any],
    *,
    by: Mapping[str, Any],
    version: int = 1,
    grammar: BodyGrammar | None = None,
    catalogs: ThingCatalogs | None = None,
    taken: frozenset[str] = frozenset(),
) -> Creature:
    """The creature ``form`` describes, every document checked by its own reader, or
    :class:`CreatureRefused`.

    ``by`` is the drafting model's provenance (an origin record's ``by`` of kind ``model``), which
    the kind's and the plan's origins name; ``taken`` holds the keys of kinds this world already
    has besides the shipped ones, which a new creature may not take."""
    grammar = grammar or body_grammar()
    catalogs = catalogs or thing_catalogs()
    label = _form_value(form, "label")
    if type(label) is not str or _LABEL.fullmatch(label) is None:
        raise _refuse(
            "thing_kind_invalid", "label", "is lowercase words and spaces, 2 to 40 letters"
        )
    key = creature_key(label)
    shipped = {kind for kind, _version in shipped_thing_kinds()} | {
        plan.key for plan in catalogs.plans.values()
    }
    if key in shipped or key in taken:
        raise _refuse(
            "creature_name_taken",
            "label",
            f"a kind of thing named {label} already exists here; use it, or name this one "
            "differently",
        )
    # 1. The recipe and the body it builds.
    recipe_document = recipe_of(form)
    try:
        recipe = read_body_recipe(recipe_document, grammar=grammar)
    except BodyRefused as exc:
        raise _refuse(exc.code, exc.where, exc.detail) from exc
    # What it should do, against what its body allows and what this world has built.
    moves = _choices(form, "moves", tuple(sorted(grammar.movements)), len(grammar.movements))
    able = set(enabled_movements(recipe, grammar))
    modules = []
    for index, movement in enumerate(moves):
        spec = grammar.movements[movement]
        if movement not in able:
            raise _refuse(
                "creature_cannot_move_so",
                f"moves[{index}]",
                f"a creature that {grammar.words[movement]} needs {spec['needs']}; this body has "
                "none of them",
            )
        if spec["module"] is None:
            raise _refuse("creature_movement_unbuilt", f"moves[{index}]", str(spec["refusal"]))
        modules.append(str(spec["module"]))
    drafted = _origin("drafted", by, _DRAFTED_LICENCE, [recipe.sha256])
    built = build_body(
        recipe,
        key=key,
        version=version,
        title=f"the body of a {label}",
        origin=drafted,
        grammar=grammar,
    )
    try:
        plan = read_body_plan(dict(built.plan), catalogs=catalogs)
    except BodyPlanRefused as exc:
        raise _refuse(exc.code, exc.where, exc.detail) from exc
    assert plan.sha256 is not None

    def plan_of(name: str) -> BodyPlan | None:
        return plan if name == plan.name else None

    # 2. The sketch, drawn by this project from the plan.
    sketch_origin = _origin(
        "authored", {"kind": "project"}, _SKETCH_LICENCE, [recipe.sha256, plan.sha256]
    )
    sketch_document, container = sketch_look(
        built,
        recipe,
        look=f"{key.replace('_', '-')}-sketch",
        version=version,
        plan_name=plan.name,
        origin=sketch_origin,
        grammar=grammar,
    )
    try:
        sketch = read_look(dict(sketch_document), catalogs=catalogs, plan_of=plan_of)
    except LookRefused as exc:
        raise _refuse(exc.code, exc.where, exc.detail) from exc
    assert sketch_document["container"]["sha256"] == hashlib.sha256(container).hexdigest()
    # 3. The kind.
    abilities = _choices(form, "abilities", CREATURE_ABILITIES, len(CREATURE_ABILITIES))
    offers = _choices(form, "offers", CREATURE_OFFERS, len(CREATURE_OFFERS))
    routine = _form_value(form, "routine")
    if not isinstance(routine, list) or len(routine) > len(CREATURE_ABILITIES):
        raise _refuse("creature_form_invalid", "routine", "is a list of abilities with weights")
    weights: dict[str, Any] = {}
    for index, entry in enumerate(routine):
        if not isinstance(entry, Mapping) or set(entry) != {"ability", "weight"}:
            raise _refuse(
                "creature_form_invalid", f"routine[{index}]", "states an ability and a weight"
            )
        if entry["ability"] in weights:
            raise _refuse(
                "creature_form_invalid", f"routine[{index}].ability", "weighs each ability once"
            )
        weights[str(entry["ability"])] = entry["weight"]
    summary = _form_value(form, "summary")
    kind_document = {
        "profile": THING_KIND_PROFILE,
        "kind": key,
        "version": version,
        "label": label,
        "summary": summary,
        "class": "being",
        "body": {
            "plan": plan.name,
            "plan_sha256": plan.sha256,
            "extent_mm": dict(recipe.extent),
        },
        "origin": _origin("drafted", by, _DRAFTED_LICENCE, [recipe.sha256, plan.sha256]),
        "moves": modules,
        "abilities": [{"key": ability, "parameters": {}} for ability in abilities],
        "offers": [{"key": offer, "parameters": {}} for offer in offers],
        "routine": {"weights": weights, "follow_holders_of": [], "reason": _ROUTINE_REASON},
        "deciders": {"default": "routine", "allowed": ["routine", "model", "person"]},
        "looks": [sketch.reference()],
        "ext": {},
    }
    try:
        kind = read_thing_kind(
            kind_document,
            catalogs=catalogs,
            plan_of=plan_of,
            look_of=lambda reference: sketch if dict(reference) == sketch.reference() else None,
        )
    except ThingKindRefused as exc:
        raise _refuse(exc.code, exc.where, exc.detail) from exc
    return Creature(
        recipe=MappingProxyType(dict(recipe.document)),
        recipe_sha256=recipe.sha256,
        plan=plan,
        plan_document=MappingProxyType(dict(built.plan)),
        sketch=sketch,
        sketch_container=container,
        kind=kind,
    )
