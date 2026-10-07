"""A creature drafted from a person's own words, as a proposal the server's checks decide.

A person, or an agent through the API, describes a creature in a few words, real or imagined,
with any number of heads, legs, wings or tentacles. When no kind the library holds fits, an open
model fills a form whose answer is a whole creature: a label and summary, its body recipe's
figures, the movements it should have, its abilities, offers and routine's weights. The form is
built from the body grammar and the things catalogs at call time, so every choice is one of
theirs, and
:func:`~exulanica.things.creatures.assemble_creature` turns the answer into a recipe, a body plan,
a sketch look and a thing kind, each held to its own reader, which decide:

*   **The words say every rule the checks hold.** The instructions render the grammar's postures,
    parts, movements and colours, the abilities and offers, and the sentence of every check that
    may refuse a creature, from the checks' own tables, so no check holds a rule the model was
    never told (the lesson of the kind drafter's first measured run).
*   **The form is strict and its arrays come last** in every object, so a reply's lists are
    followed only by their object's closing brace.
*   **One repair.** A creature the checks refuse is told the check's code, where in the form, and
    the check's own sentence, never the reply's text, and drafted once more; a second refusal is
    refused by name (:attr:`CreatureDraftRefusalCode.NOT_DRAFTED`).
*   **Every saved name is replaced before sending** by the caller
    (:func:`~exulanica.selection.world_drafting.sendable`), and the request passes the policy
    boundary every hosted request passes.
*   **What it records.** The kind's and plan's origins name the model that answered, the prompt's
    version, the SHA-256 of the instructions sent and of the words sent, never the words.

The words the model is asked with are data (``creature-drafting.v1.json`` beside this module).
Pure apart from the model client: nothing is read from a connection and nothing is written.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.models.response import Runaway
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.things.bodies import BODY_RECIPE_CODES, BodyGrammar, body_grammar
from exulanica.things.catalogs import BODY_PLAN_CODES, ThingCatalogs, thing_catalogs
from exulanica.things.creatures import (
    CREATURE_ABILITIES,
    CREATURE_CODES,
    CREATURE_OFFERS,
    Creature,
    CreatureRefused,
    assemble_creature,
)
from exulanica.things.kinds import THING_KIND_CODES

__all__ = [
    "CHECK_SENTENCES",
    "DRAFT_ATTEMPTS",
    "PROMPT_PATH",
    "CreatureDraftOutcome",
    "CreatureDraftRefusal",
    "CreatureDraftRefusalCode",
    "CreatureDraftingPrompt",
    "assembled_form",
    "creature_drafting_prompt",
    "draft_creature",
    "draft_form",
    "form_where",
    "render_instructions",
]

PROMPT_PATH: Final = Path(__file__).with_name("creature-drafting.v1.json")
_PROMPT_PROFILE: Final = "exulanica.creature-drafting-prompt/v1"
#: One form and one repair, as the kind drafter: a creature the checks refuse twice is refused by
#: name, never escalated to a larger model.
DRAFT_ATTEMPTS: Final = 2
#: The sentence of every check that may refuse a drafted creature, by its code: what the model is
#: told in the instructions and in a repair, and what a person reads.
CHECK_SENTENCES: Final[Mapping[str, str]] = {
    code: sentence
    for code, sentence in (*BODY_RECIPE_CODES, *CREATURE_CODES, *BODY_PLAN_CODES, *THING_KIND_CODES)
}
#: Abilities a routine may weigh: the creature's abilities but saying, which only a mind does.
_ROUTINE_ABILITIES: Final = tuple(ability for ability in CREATURE_ABILITIES if ability != "say")
_LABEL_PATTERN: Final = r"^[a-z][a-z ]{0,38}[a-z]$"


class CreatureDraftRefusalCode(StrEnum):
    """Why no creature was drafted: the form or the checks refused it, twice."""

    NOT_DRAFTED = "creature_not_drafted"


@dataclass(frozen=True, slots=True)
class CreatureDraftRefusal:
    code: CreatureDraftRefusalCode
    detail: str
    #: The last check that refused the creature: its code, where in the form, and its sentence.
    check: tuple[str, str, str] | None = None


@dataclass(frozen=True, slots=True)
class CreatureDraftingPrompt:
    """The words the creature drafter is asked with, read from a ``creature-drafting.v<N>.json``
    file."""

    version: int
    sha256: str
    instructions: str
    repair_refused: str
    repair_truncated: str
    repair_whitespace: str
    repair_repetition: str
    repair_checks: str
    description_characters_maximum: int
    drafted_licence: str

    @property
    def prompt_version(self) -> str:
        """The name every request is sent under: part of the response cache key."""
        return f"creature-drafting-{self.version}"

    def repair_cut(self, runaway: str | None) -> str:
        if runaway == Runaway.WHITESPACE:
            return self.repair_whitespace
        if runaway == Runaway.REPETITION:
            return self.repair_repetition
        return self.repair_truncated


@functools.cache
def creature_drafting_prompt(path: Path = PROMPT_PATH) -> CreatureDraftingPrompt:
    """The creature drafter's words, read once and named by the file's SHA-256."""
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("profile") != _PROMPT_PROFILE:
        raise ValueError(f"{path.name} is not a {_PROMPT_PROFILE} document")
    repair = document["repair"]
    return CreatureDraftingPrompt(
        version=int(document["version"]),
        sha256=hashlib.sha256(raw).hexdigest(),
        instructions=str(document["instructions"]),
        repair_refused=str(repair["refused"]),
        repair_truncated=str(repair["truncated"]),
        repair_whitespace=str(repair["whitespace"]),
        repair_repetition=str(repair["repetition"]),
        repair_checks=str(repair["checks"]),
        description_characters_maximum=int(document["description_characters_maximum"]),
        drafted_licence=str(document["drafted_licence"]),
    )


# -- the vocabulary, from the catalogs --------------------------------------------------------


def _bounds(spec: Mapping[str, Any]) -> str:
    return f"{spec['minimum']} to {spec['maximum']}"


def render_instructions(
    prompt: CreatureDraftingPrompt,
    grammar: BodyGrammar,
    catalogs: ThingCatalogs,
    taken: Sequence[str] = (),
) -> str:
    """The system message: the prompt's words, then the vocabulary, bounds and check sentences the
    grammar, the catalogs and the checks state, rendered here so the words never drift from them.
    ``taken`` names the kinds of thing this world already has, which a new name may not be."""
    lines = [prompt.instructions, "", "Postures:"]
    for key in sorted(grammar.postures):
        spec = grammar.postures[key]
        extent = spec["extent_mm"]
        lines.append(
            f"- {key}: {grammar.words[key]}. Spine segments {_bounds(spec['spine'])}; leg pairs "
            f"{_bounds(spec['leg_pairs'])}; parts it may have: {', '.join(spec['parts'])}; "
            f"length_mm {_bounds(extent['length'])}, width_mm {_bounds(extent['width'])}, "
            f"height_mm {_bounds(extent['height'])}, span_mm {_bounds(extent['span'])}."
        )
    lines += ["", "Parts:"]
    parts = grammar.parts
    heads, necks = _bounds(parts["head"]["count"]), _bounds(parts["neck"]["bones_per_head"])
    lines.append(f"- heads: {heads} heads; each with {necks} neck bones, and a jaw or none.")
    lines.append(f"- tail: {_bounds(parts['tail']['bones'])} bones.")
    for role in ("leg", "arm", "wing", "fin"):
        spec = parts[role]
        pairs = spec["pairs"]
        lines.append(
            f"- {role}: {grammar.words[role]}; in left and right pairs, a count of "
            f"{pairs['minimum'] * 2} to {pairs['maximum'] * 2} (always even); "
            f"segments {_bounds(spec['segments'])}."
        )
    tentacle = parts["tentacle"]
    lines.append(
        f"- tentacle: {grammar.words['tentacle']}; a count of {_bounds(tentacle['count'])}; "
        f"segments {_bounds(tentacle['segments'])}."
    )
    lines += ["", "Movements (moves):"]
    for key in sorted(grammar.movements):
        spec = grammar.movements[key]
        built = "built here" if spec["module"] is not None else f"not built yet: {spec['refusal']}"
        lines.append(f"- {key}: {grammar.words[key]}; needs {spec['needs']}; {built}")
    lines += ["", f"Colours: {', '.join(sorted(grammar.colours))}.", "", "Abilities:"]
    for key in CREATURE_ABILITIES:
        ability = catalogs.abilities[key]
        needs = [
            word
            for word, flag in (
                ("something to hold with", ability.needs_socket),
                ("a way to move", ability.needs_moves),
            )
            if flag
        ]
        lines.append(
            f"- {key}: {ability.words}" + (f"; needs {' and '.join(needs)}" if needs else "")
        )
    lines += ["", "Offers:"]
    lines += [f"- {key}: {catalogs.offers[key].words}" for key in CREATURE_OFFERS]
    if taken:
        lines += [
            "",
            f"Kinds of thing this world already has (not a new name): {', '.join(sorted(taken))}.",
        ]
    lines += ["", "The checks every creature passes, each by its code:"]
    lines += [f"- {code}: {sentence}" for code, sentence in CHECK_SENTENCES.items()]
    return "\n".join(lines)


# -- the form -------------------------------------------------------------------------------------


def _model(name: str, fields: Mapping[str, Any]) -> type[BaseModel]:
    return create_model(  # type: ignore[call-overload,no-any-return]
        name, __config__=ConfigDict(extra="forbid"), **dict(fields)
    )


def _whole(low: int, high: int, description: str) -> Any:
    return (Annotated[int, Field(ge=low, le=high)], Field(description=description))


#: Forms already built, by the digests of the grammar and catalogs they were built from.
_FORMS: Final[dict[tuple[str, str], type[BaseModel]]] = {}
#: The kinds of limb, each counted and segmented by two fields of the form.
_ROLES: Final = ("leg", "arm", "wing", "fin", "tentacle")
#: The four colours of a sketch, each a field of the form, in the recipe's order.
_COLOUR_FIELDS: Final = ("colour_body", "colour_belly", "colour_accent", "colour_eyes")


def _build_form(grammar: BodyGrammar) -> type[BaseModel]:
    """A flat form: every field a single value, no list anywhere, so no reply can stop between a
    list and the field after it (the strict-schema runaway that lists invite). A body's heads are
    alike (how many, each neck's bones, a jaw or none); each kind of limb is a count and its
    segments; each movement, ability and offer is a yes or no, and each ability a routine weighs
    has its weight."""
    postures = tuple(sorted(grammar.postures))
    widest = max(
        int(spec["extent_mm"][side]["maximum"])
        for spec in grammar.postures.values()
        for side in ("length", "width", "height", "span")
    )
    colours = tuple(sorted(grammar.colours))
    appearance = grammar.limits["appearance_characters"]
    parts = grammar.parts
    fields: dict[str, Any] = {
        "label": (
            Annotated[str, Field(pattern=_LABEL_PATTERN)],
            Field(description="lowercase words and spaces"),
        ),
        "summary": (Annotated[str, Field(min_length=1, max_length=160)], ...),
        "appearance": (
            Annotated[
                str,
                Field(min_length=int(appearance["minimum"]), max_length=int(appearance["maximum"])),
            ],
            Field(description="what it looks like, no numerals, no names"),
        ),
        "posture": (Literal[postures], ...),  # type: ignore[valid-type]
        "spine": _whole(1, 24, "torso segments"),
        "upper_body": (Literal["none", "upright"], ...),
        "heads": _whole(1, int(parts["head"]["count"]["maximum"]), "how many heads"),
        "neck_bones": _whole(
            0, int(parts["neck"]["bones_per_head"]["maximum"]), "neck bones of each head"
        ),
        "jaws": (bool, Field(description="whether its heads have jaws")),
    }
    for role in _ROLES:
        fields[f"{role}s"] = _whole(0, 12, f"how many {role}s; even for legs, arms, wings and fins")
        fields[f"{role}_segments"] = _whole(0, 8, f"segments of each {role}, 0 when it has none")
    fields |= {
        "tail": _whole(0, int(parts["tail"]["bones"]["maximum"]), "tail bones"),
        "length_mm": _whole(1, widest, "nose to tail tip"),
        "width_mm": _whole(1, widest, "side to side, wings folded"),
        "height_mm": _whole(1, widest, "ground to the top of its head"),
        "span_mm": _whole(0, widest, "wingtip to wingtip, 0 with no wings"),
        "holds_with": (Literal["none", "jaws", "hands", "front_claws"], ...),
    }
    for name in _COLOUR_FIELDS:
        fields[name] = (Literal[colours], ...)  # type: ignore[valid-type]
    for movement in sorted(grammar.movements):
        fields[f"moves_{movement}"] = (
            bool,
            Field(description=f"whether it {grammar.words[movement]}"),
        )
    for ability in CREATURE_ABILITIES:
        fields[f"can_{ability}"] = (bool, ...)
        if ability in _ROUTINE_ABILITIES:
            fields[f"weight_{ability}"] = _whole(0, 10_000, f"how often its routine does {ability}")
    for offer in CREATURE_OFFERS:
        fields[f"offers_{offer}"] = (bool, ...)
    return _model("Creature", fields)


def assembled_form(flat: Mapping[str, Any], grammar: BodyGrammar) -> dict[str, Any]:
    """The creature form :func:`~exulanica.things.creatures.assemble_creature` reads, from the flat
    form a model filled: alike heads listed, each kind of limb with a count a limb group, the
    colours in order, and every yes a list entry."""
    heads = [{"neck": flat["neck_bones"], "jaw": flat["jaws"]} for _ in range(flat["heads"])]
    limbs = [
        {"role": role, "count": flat[f"{role}s"], "segments": flat[f"{role}_segments"]}
        for role in _ROLES
        if flat[f"{role}s"]
    ]
    abilities = [ability for ability in CREATURE_ABILITIES if flat[f"can_{ability}"]]
    return {
        "label": flat["label"],
        "summary": flat["summary"],
        "posture": flat["posture"],
        "spine": flat["spine"],
        "upper_body": flat["upper_body"],
        "tail": flat["tail"],
        "length_mm": flat["length_mm"],
        "width_mm": flat["width_mm"],
        "height_mm": flat["height_mm"],
        "span_mm": flat["span_mm"],
        "holds_with": flat["holds_with"],
        "appearance": flat["appearance"],
        "heads": heads,
        "limbs": limbs,
        "colours": [flat[name] for name in _COLOUR_FIELDS],
        "moves": [movement for movement in sorted(grammar.movements) if flat[f"moves_{movement}"]],
        "abilities": abilities,
        "offers": [offer for offer in CREATURE_OFFERS if flat[f"offers_{offer}"]],
        "routine": [
            {"ability": ability, "weight": flat[f"weight_{ability}"]}
            for ability in abilities
            if ability in _ROUTINE_ABILITIES and flat[f"weight_{ability}"]
        ],
    }


def draft_form(
    grammar: BodyGrammar | None = None, catalogs: ThingCatalogs | None = None
) -> type[BaseModel]:
    """The flat form a model fills: every choice from the grammar and the catalogs, no lists."""
    grammar = grammar or body_grammar()
    catalogs = catalogs or thing_catalogs()
    key = (grammar.sha256, catalogs.sha256)
    found = _FORMS.get(key)
    if found is None:
        found = _FORMS[key] = _build_form(grammar)
    return found


# -- where a refusal is, in the form ---------------------------------------------------------------

_EXTENT_FIELDS: Final = {
    "extent_mm.length": "length_mm",
    "extent_mm.width": "width_mm",
    "extent_mm.height": "height_mm",
    "extent_mm.span": "span_mm",
    "body.extent_mm.length": "length_mm",
    "body.extent_mm.width": "width_mm",
    "body.extent_mm.height": "height_mm",
    "body.extent_mm.span": "span_mm",
}


def form_where(where: str, form: Mapping[str, Any] | None = None) -> str:
    """A refusal's place in a recipe, a plan or a kind, as the field of the flat form the model
    filled: an extent's side is its ``*_mm`` field, a head's neck or jaw is ``neck_bones`` or
    ``jaws``, a limb group is its role's count and segments, a colour its colour field, a movement
    its ``moves_*`` field, an ability its ``can_*`` field, a routine weight the ``weight_*``
    fields, and a place the form has no field for is the whole creature. ``form`` is the assembled
    form the place indexes into."""
    if where in _EXTENT_FIELDS:
        return _EXTENT_FIELDS[where]
    if where.startswith("extent_mm"):
        return "length_mm, width_mm, height_mm and span_mm"
    if where.startswith("heads"):
        if where.endswith(".jaw"):
            return "jaws"
        return "neck_bones" if where.endswith(".neck") else "heads"
    match = re.match(r"(limbs|colours|moves|abilities|offers)\[(\d+)\]", where)
    if match and form is not None:
        group, index = match.group(1), int(match.group(2))
        items = form.get(group, [])
        if index < len(items):
            item = items[index]
            if group == "limbs":
                role = item["role"]
                return f"{role}_segments" if where.endswith(".segments") else f"{role}s"
            if group == "colours":
                return _COLOUR_FIELDS[index]
            if group == "moves":
                return f"moves_{item}"
            if group == "abilities":
                return f"can_{item}"
            return f"offers_{item}"
    if where.startswith("routine"):
        return "the weight_ fields"
    if where == "colours":
        return ", ".join(_COLOUR_FIELDS)
    for field in (
        "label",
        "summary",
        "posture",
        "spine",
        "upper_body",
        "tail",
        "appearance",
        "holds_with",
    ):
        if where == field or where.startswith(f"{field}."):
            return field
    return "the whole creature"


# -- drafting -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CreatureDraftOutcome:
    creature: Creature | None
    refusal: CreatureDraftRefusal | None
    model_id: str | None
    calls: tuple[ModelCall, ...]
    #: Each attempt's outcome, in order: passed, a check's code, a refused form or a cut-off one.
    attempts: tuple[str, ...]
    #: Each refused attempt's check: its code, where in the form, and its sentence.
    refusals: tuple[tuple[str, str, str], ...] = ()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def draft_creature(
    client: ModelClient,
    description: str,
    *,
    role: Role,
    version: int = 1,
    prompt: CreatureDraftingPrompt | None = None,
    grammar: BodyGrammar | None = None,
    catalogs: ThingCatalogs | None = None,
    taken: frozenset[str] = frozenset(),
    placeholders: Mapping[Any, str] | None = None,
    log: CallLog | None = None,
    max_tokens: int | None = None,
) -> CreatureDraftOutcome:
    """Ask the drafter for a creature of ``description``, assemble and check it, with one repair
    and no fallback.

    ``description`` is the text as it is sent, every saved name already replaced, and
    ``placeholders`` the record of those replacements, handed to the boundary with the request.
    ``taken`` holds the keys of kinds this world already has besides the shipped ones."""
    prompt = creature_drafting_prompt() if prompt is None else prompt
    grammar = grammar or body_grammar()
    catalogs = catalogs or thing_catalogs()
    if max_tokens is None:
        declared = client.manifest[role].max_tokens
        max_tokens = None if declared is None else declared.value
    instructions = render_instructions(prompt, grammar, catalogs, sorted(taken))
    form = draft_form(grammar, catalogs)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": f'The description:\n"""{description}"""'},
    ]
    log = CallLog() if log is None else log
    attempts: list[str] = []
    refusals: list[tuple[str, str, str]] = []
    for attempt in range(1, DRAFT_ATTEMPTS + 1):
        repair: str
        try:
            drafted = client.structured(
                role,
                messages,
                form,
                prompt_version=prompt.prompt_version,
                placeholders=placeholders,
                max_tokens=max_tokens,
                arrays_last=True,
            )
            log.record(drafted.call)
            binding = client.manifest[role]
            served = next(
                (
                    spec
                    for spec in (binding.primary, binding.fallback)
                    if spec is not None and spec.model_id == drafted.call.served_model_id
                ),
                binding.primary,
            )
            by = {
                "kind": "model",
                "provider": served.provider,
                "model_id": drafted.call.served_model_id,
                "prompt_version": prompt.prompt_version,
                "prompt_sha256": _digest(instructions),
                "words_sha256": _digest(description),
                "execution_sha256": None,
            }
            form_values = assembled_form(drafted.value.model_dump(mode="json"), grammar)
            try:
                creature = assemble_creature(
                    form_values,
                    by=by,
                    version=version,
                    grammar=grammar,
                    catalogs=catalogs,
                    taken=taken,
                )
            except CreatureRefused as refused:
                where = form_where(refused.where, form_values)
                sentence = CHECK_SENTENCES.get(refused.code, "")
                detail = f"{refused.detail}. {sentence}".strip()
                refusals.append((refused.code, where, detail))
                attempts.append(f"check:{refused.code}")
                log.rejected((f"refused by check {refused.code} at {where}",))
                repair = prompt.repair_checks.format(
                    code=refused.code, where=where, sentence=detail
                )
            else:
                attempts.append("passed")
                return CreatureDraftOutcome(
                    creature=creature,
                    refusal=None,
                    model_id=drafted.call.served_model_id,
                    calls=log.calls,
                    attempts=tuple(attempts),
                    refusals=tuple(refusals),
                )
        except TruncatedResponseError as cut:
            attempts.append("truncated" if cut.runaway is None else f"truncated:{cut.runaway}")
            repair = prompt.repair_cut(cut.runaway)
        except StructuredOutputError:
            attempts.append("form_refused")
            repair = prompt.repair_refused
        if attempt == DRAFT_ATTEMPTS:
            break
        messages.append({"role": "user", "content": repair})
    return CreatureDraftOutcome(
        creature=None,
        refusal=CreatureDraftRefusal(
            CreatureDraftRefusalCode.NOT_DRAFTED,
            "No creature was drafted from these words that this world can build.",
            refusals[-1] if refusals else None,
        ),
        model_id=None,
        calls=log.calls,
        attempts=tuple(attempts),
        refusals=tuple(refusals),
    )
