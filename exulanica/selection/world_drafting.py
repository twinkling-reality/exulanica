"""A world's specification drafted from a person's own words, as a proposal the server checks.

A person, or an agent through the API, describes the world they want ("a quiet town with short
blocks and low buildings"). An open model reads the specification this server makes worlds from,
as the server serves it (``GET /worlds/specification``), and fills a form whose every field is one
of that specification's values. What comes back is a proposal and nothing more:

*   **The form is the specification, built at call time.** A preset is an enum over the presets
    the document states; each value a person may set is an enum over the values its range and
    step allow, or null to keep the preset's; nothing else has a field. A value the document does
    not declare cannot be drafted, and a value off its range or step cannot be written, because
    the endpoint enforces the schema and the client checks the reply against it again.
*   **No model prose reaches the person.** Besides values, the model returns only which parts of
    the description ask for what the form cannot say, and each must be copied word for word from
    the description it was sent: :func:`verbatim_span` finds each in that text and returns the
    text's own slice, and a draft naming a phrase that is not there is repaired once and then
    refused. A draft that says nothing the description asks for is a town is refused by name
    (:attr:`DraftRefusalCode.DESCRIPTION_NOT_SUPPORTED`).
*   **The server's validation is the one authority.** This module validates nothing about the
    world: the caller runs the proposal's preset and values through the same validation a person's
    own values pass (``POST /worlds/generated``), and nothing is made until the person confirms
    there. A model answer is never clamped into range and never applied.
*   **Every saved name is replaced before sending, a place's included** (:func:`sendable`):
    describing a world to be made is no use a place-name right offers
    (``exulanica/consent/place-name-uses.v1.json``), so no place's name is left for the boundary
    to release. The request still passes the one policy boundary every hosted request passes.

*   **Reference notes are quoted data, never instructions.** A draft may be handed a finished
    reference request's notes (:mod:`exulanica.references.for_drafting`), short descriptions drafted
    from web search results. They follow the description in the person's message as one quoted,
    bounded block under a heading that says they describe and never instruct; saved names in them
    are replaced as in the description; the form is the same; and a copied phrase is still checked
    against the description alone, so nothing in the notes can be shown as the person's words.

The words the model is asked with are data (``world-drafting.v2.json`` beside this module, and
``world-drafting.v3.json`` for a draft handed notes, so every draft records which words saw notes):
each draft records the prompt's version and the file's SHA-256. Pure apart from the model client: no
connection is read here except by :func:`sendable`, and nothing is written.
"""

from __future__ import annotations

import functools
import hashlib
import json
import keyword
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, create_model

from exulanica.epistemics.saved_names import (
    PLACEHOLDER,
    recognised_spans,
    redact_names,
    saved_names,
)
from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.selection.calls import CallLog, ModelCall

__all__ = [
    "DRAFTER_ROLE",
    "DRAFT_ATTEMPTS",
    "ENUMERATED_VALUES_MAXIMUM",
    "NOTES_PROMPT_PATH",
    "PROMPT_PATH",
    "Adjustable",
    "CutPlaceholder",
    "DraftOutcome",
    "DraftRefusal",
    "DraftRefusalCode",
    "DraftingPrompt",
    "Fixed",
    "Preset",
    "Requirement",
    "SentDescription",
    "SpecificationView",
    "UnreadableSpecification",
    "WorldDraft",
    "draft_schema",
    "draft_world_specification",
    "drafting_prompt",
    "notes_prompt",
    "render_form",
    "sendable",
    "specification_view",
    "verbatim_bounds",
    "verbatim_span",
]

#: The manifest role that drafts a specification from words, named by its job.
DRAFTER_ROLE: Final = Role.SPECIFICATION_DRAFTER
#: The words the drafter asks with: version 2, which says what a share is and names no value;
#: version 1 stays beside it, byte for byte, as the words the judged comparison asked with.
PROMPT_PATH: Final = Path(__file__).with_name("world-drafting.v2.json")
#: The words a draft handed reference notes asks with: version 2's, saying what the notes are and
#: that the person's words win. A draft without notes asks with version 2, byte for byte.
NOTES_PROMPT_PATH: Final = Path(__file__).with_name("world-drafting.v3.json")
_PROMPT_PROFILE: Final = "exulanica.world-drafting-prompt/v1"
#: The served specification document's profile, the one shape this module reads.
SPECIFICATION_PROFILE: Final = "exulanica.world-specification/v1"
#: One try and one repair, the drafts' rule (:mod:`exulanica.selection.environment_proposal`): a
#: refused form is told why once, and a second refusal is the person's refusal to read.
DRAFT_ATTEMPTS: Final = 2
#: The most values a key's enum lists. An enum of every allowed value keeps a drafted value on the
#: schema's step, which a minimum and maximum alone do not; a key allowing more is drafted within
#: its minimum and maximum, and its step is left to the server's validation, because a list longer
#: than this costs more of every prompt than the step it would enforce.
ENUMERATED_VALUES_MAXIMUM: Final = 64
#: The form's own fields, which no specification key may take.
_FORM_FIELDS: Final = ("preset", "fit", "not_supported")
#: Punctuation a model may wrap a copied phrase in, which is not part of the copy.
_WRAPPING: Final = " \t\n\"'\u201c\u201d\u2018\u2019.,;:!?()"


class UnreadableSpecification(ValueError):
    """The served specification document does not state what a form can be built from."""

    code: Final = "specification_unreadable"


class DraftRefusalCode(StrEnum):
    #: The model said nothing the description asks for is a town this specification can make.
    DESCRIPTION_NOT_SUPPORTED = "description_not_supported"
    #: The model could not fill the form, with its one repair.
    NOT_DRAFTED = "not_drafted"


#: What an API caller reads for each refusal; the page words them from its own copy.
_REFUSAL_DETAILS: Final = {
    DraftRefusalCode.DESCRIPTION_NOT_SUPPORTED: (
        "nothing the description asks for is a world this server makes; the specification "
        "document says what a world can be"
    ),
    DraftRefusalCode.NOT_DRAFTED: "the model could not fill the specification's form",
}


@dataclass(frozen=True, slots=True)
class DraftRefusal:
    code: DraftRefusalCode
    detail: str


@dataclass(frozen=True, slots=True)
class DraftingPrompt:
    """The words the drafter is asked with, read from a ``world-drafting.v<N>.json`` file."""

    version: int
    sha256: str
    instructions: str
    repair_refused: str
    repair_truncated: str
    repair_not_verbatim: str
    phrases_maximum: int
    phrase_characters_maximum: int
    description_characters_maximum: int

    @property
    def prompt_version(self) -> str:
        """The name every request is sent under: part of the response cache key."""
        return f"world-drafting-{self.version}"


@functools.cache
def drafting_prompt(path: Path = PROMPT_PATH) -> DraftingPrompt:
    """The drafter's words, read once and named by the file's SHA-256."""
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("profile") != _PROMPT_PROFILE:
        raise ValueError(f"{path.name} is not a {_PROMPT_PROFILE} document")
    repair = document["repair"]
    return DraftingPrompt(
        version=int(document["version"]),
        sha256=hashlib.sha256(raw).hexdigest(),
        instructions=str(document["instructions"]),
        repair_refused=str(repair["refused"]),
        repair_truncated=str(repair["truncated"]),
        repair_not_verbatim=str(repair["not_verbatim"]),
        phrases_maximum=int(document["phrases_maximum"]),
        phrase_characters_maximum=int(document["phrase_characters_maximum"]),
        description_characters_maximum=int(document["description_characters_maximum"]),
    )


def notes_prompt(notes: str | None) -> DraftingPrompt:
    """The words a draft asks with: version 3 when it is handed reference notes, else version 2."""
    return drafting_prompt(NOTES_PROMPT_PATH) if notes else drafting_prompt()


# -- the specification, as the server serves it -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Requirement:
    """While ``when`` lies from ``start`` to ``end``, the value stating this lies from ``minimum``
    to ``maximum``, for ``reason``: a range another value narrows, as the document states it."""

    when: str
    start: int
    end: int
    minimum: int
    maximum: int
    reason: str


@dataclass(frozen=True, slots=True)
class Adjustable:
    """A value a person may set: its key, words, unit and range, as the document states.

    An ``integer`` ranges from ``minimum`` to ``maximum`` in steps of ``step``; a ``choice`` is
    one of ``choices``.
    """

    key: str
    label: str
    kind: Literal["integer", "choice"]
    unit: str
    minimum: int
    maximum: int
    step: int
    choices: tuple[str, ...]
    reason: str
    #: When another value narrows this one's range, and why.
    requires: tuple[Requirement, ...] = ()

    def allowed(self) -> tuple[int, ...] | tuple[str, ...]:
        """Every value the range allows: from the minimum up by the step, or each choice."""
        if self.kind == "choice":
            return self.choices
        return tuple(range(self.minimum, self.maximum + 1, self.step))


@dataclass(frozen=True, slots=True)
class Fixed:
    """A value every world of the specification holds, with the document's reason."""

    key: str
    label: str
    value: object
    reason: str


@dataclass(frozen=True, slots=True)
class Preset:
    """A named starting point: the value it sets for every adjustable key."""

    key: str
    label: str
    values: Mapping[str, int | str]
    #: How many tiles a world of the preset covers, where the document states it.
    tiles: int | None = None


@dataclass(frozen=True, slots=True)
class SpecificationView:
    """What a form is built from: the served document's values, fixed values and presets."""

    version: int
    #: SHA-256 of the served document's canonical JSON, recorded on every draft.
    sha256: str
    adjustable: tuple[Adjustable, ...]
    fixed: tuple[Fixed, ...]
    presets: tuple[Preset, ...]

    def preset(self, key: str) -> Preset:
        for preset in self.presets:
            if preset.key == key:
                return preset
        raise KeyError(key)


def _whole(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UnreadableSpecification(f"{where} is not a whole number")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise UnreadableSpecification(f"{where} is not text")
    return value


def _adjustable(entry: Mapping[str, Any]) -> Adjustable:
    key = _text(entry["key"], "a value's key")
    kind = entry["kind"]
    if kind not in ("integer", "choice"):
        raise UnreadableSpecification(f"{key} is a value of no kind a form carries: {kind!r}")
    integer = kind == "integer"
    return Adjustable(
        key=key,
        label=_text(entry["label"], f"{key}'s label"),
        kind=kind,
        unit=_text(entry["unit"], f"{key}'s unit"),
        minimum=_whole(entry["minimum"], f"{key}'s minimum") if integer else 0,
        maximum=_whole(entry["maximum"], f"{key}'s maximum") if integer else 0,
        step=_whole(entry["step"], f"{key}'s step") if integer else 1,
        choices=() if integer else tuple(_text(c, f"a choice of {key}") for c in entry["choices"]),
        reason=_text(entry["reason"], f"{key}'s reason"),
        requires=tuple(
            Requirement(
                when=_text(stated["when"], f"what narrows {key}"),
                start=_whole(stated["from"], f"where {key} is narrowed from"),
                end=_whole(stated["to"], f"where {key} is narrowed to"),
                minimum=_whole(stated["minimum"], f"{key}'s narrowed minimum"),
                maximum=_whole(stated["maximum"], f"{key}'s narrowed maximum"),
                reason=_text(stated["reason"], f"why {key} is narrowed"),
            )
            for stated in entry.get("requires", ())
        ),
    )


def _preset_value(value: object, where: str) -> int | str:
    if isinstance(value, str):
        return value
    return _whole(value, where)


def specification_view(document: Mapping[str, Any]) -> SpecificationView:
    """Read the served specification document into the view a form is built from.

    The document states every value with whether it is adjustable (``GET /worlds/specification``,
    profile ``exulanica.world-specification/v1``): an adjustable one becomes a field of the form,
    a fixed one a line saying what every town holds. Every adjustable key must be a name the form
    can carry as a field and allow at least one value, and every preset must set every adjustable
    key to a value it allows; a document stating anything else is refused by name rather than
    half read.
    """
    if document.get("profile") != SPECIFICATION_PROFILE:
        raise UnreadableSpecification(f"the specification document is not {SPECIFICATION_PROFILE}")
    try:
        stated = list(document["values"])
        adjustable = tuple(_adjustable(entry) for entry in stated if entry["adjustable"] is True)
        fixed = tuple(
            Fixed(
                key=_text(entry["key"], "a fixed value's key"),
                label=_text(entry["label"], f"{entry['key']}'s label"),
                value=entry["value"],
                reason=_text(entry["reason"], f"{entry['key']}'s reason"),
            )
            for entry in stated
            if entry["adjustable"] is False
        )
        presets = tuple(
            Preset(
                key=_text(entry["key"], "a preset's key"),
                label=_text(entry["label"], f"{entry['key']}'s label"),
                values={
                    str(key): _preset_value(value, f"preset {entry['key']}'s {key}")
                    for key, value in dict(entry["values"]).items()
                },
                tiles=None
                if entry.get("tiles") is None
                else _whole(entry["tiles"], f"preset {entry['key']}'s tiles"),
            )
            for entry in document["presets"]
        )
        version = _whole(document["schema"]["catalog_version"], "the schema's version")
    except (KeyError, TypeError) as exc:
        raise UnreadableSpecification(f"the specification document lacks {exc}") from exc
    if len(adjustable) + len(fixed) != len(stated):
        raise UnreadableSpecification("a value states neither that it is adjustable nor fixed")
    keys = [entry.key for entry in adjustable]
    if not adjustable or len(set(keys)) != len(keys):
        raise UnreadableSpecification("the specification states no values, or one twice")
    for entry in adjustable:
        if not entry.key.isidentifier() or keyword.iskeyword(entry.key):
            raise UnreadableSpecification(f"{entry.key!r} cannot be a field of a form")
        if entry.key in _FORM_FIELDS:
            raise UnreadableSpecification(f"{entry.key!r} is a field of the form itself")
        if not entry.allowed() or entry.step < 1:
            raise UnreadableSpecification(f"{entry.key} allows no value")
    if not presets:
        raise UnreadableSpecification("the specification states no preset to start from")
    for preset in presets:
        if set(preset.values) != set(keys):
            raise UnreadableSpecification(f"preset {preset.key} does not set every value once")
        for entry in adjustable:
            if preset.values[entry.key] not in entry.allowed():
                raise UnreadableSpecification(
                    f"preset {preset.key} sets {entry.key} to a value its range does not allow"
                )
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return SpecificationView(
        version=version,
        sha256=hashlib.sha256(canonical).hexdigest(),
        adjustable=adjustable,
        fixed=fixed,
        presets=presets,
    )


# -- the form -----------------------------------------------------------------------------------


def draft_schema(view: SpecificationView, prompt: DraftingPrompt) -> type[BaseModel]:
    """The form a draft fills, one field per adjustable value, built from ``view``."""
    phrase = Annotated[str, Field(min_length=1, max_length=prompt.phrase_characters_maximum)]
    fields: dict[str, Any] = {
        "preset": (
            Literal[tuple(preset.key for preset in view.presets)],  # type: ignore[misc]
            Field(description="The listed starting point closest to the description."),
        ),
        "fit": (
            Literal["all", "part", "none"],
            Field(description="How much of what the description asks for is on this form."),
        ),
        "not_supported": (
            Annotated[list[phrase], Field(max_length=prompt.phrases_maximum)],  # type: ignore[valid-type]
            Field(
                description=(
                    "Short parts of the description, copied exactly, that ask for what this "
                    "form cannot say."
                )
            ),
        ),
    }
    for entry in view.adjustable:
        allowed = entry.allowed()
        value: Any = (
            Literal[allowed]  # type: ignore[valid-type]
            if entry.kind == "choice" or len(allowed) <= ENUMERATED_VALUES_MAXIMUM
            else Annotated[int, Field(ge=entry.minimum, le=entry.maximum)]
        )
        fields[entry.key] = (
            value | None,
            Field(description=f"{entry.label}, in {entry.unit}; null keeps the preset's."),
        )
    return create_model(  # type: ignore[call-overload,no-any-return]
        "WorldSpecificationDraft", __config__=ConfigDict(extra="forbid"), **fields
    )


#: How a value of a unit is also written in the words people use, beside the figure the form takes,
#: so a description in metres meets a range stated in millimetres. A unit with no entry is written
#: as its figure alone.
_READ_AS: Final = {"mm": lambda value: f"{value / 1000:g} m"}


def _figure(value: object, unit: str) -> str:
    """A value as the form states it, with its reading in people's units where there is one."""
    reading = _READ_AS.get(unit)
    return (
        str(value)
        if reading is None or not isinstance(value, int)
        else (f"{value} ({reading(value)})")
    )


def render_form(view: SpecificationView, description: str, notes: str | None = None) -> str:
    """The user message: the presets, every value with what it allows and why, the fixed values,
    and the description as it is sent, then the reference notes' quoted block when there is one. A
    value in millimetres is also written in metres."""
    units = {entry.key: entry.unit for entry in view.adjustable}
    lines = ["Presets, each a starting point with the value it sets for each key:"]
    for preset in view.presets:
        values = ", ".join(
            f"{key} {_figure(preset.values[key], units.get(key, ''))}"
            for key in sorted(preset.values)
        )
        covers = "" if preset.tiles is None else f", {preset.tiles} tiles"
        lines.append(f"- {preset.key} ({preset.label}{covers}): {values}")
    lines.append("")
    lines.append("Values a person may set:")
    for entry in view.adjustable:
        allowed = entry.allowed()
        shown = (
            ", ".join(_figure(value, entry.unit) for value in allowed)
            if entry.kind == "choice" or len(allowed) <= ENUMERATED_VALUES_MAXIMUM
            else f"{_figure(entry.minimum, entry.unit)} to {_figure(entry.maximum, entry.unit)} "
            f"in steps of {_figure(entry.step, entry.unit)}"
        )
        lines.append(f"- {entry.key}: {entry.label}, in {entry.unit}. Allowed: {shown}.")
        lines.append(f"  Why: {entry.reason}")
        for narrowed in entry.requires:
            when = units.get(narrowed.when, "")
            lines.append(
                f"  Only while {narrowed.when} is {_figure(narrowed.start, when)} to "
                f"{_figure(narrowed.end, when)}: {entry.key} is "
                f"{_figure(narrowed.minimum, entry.unit)} to "
                f"{_figure(narrowed.maximum, entry.unit)}. Why: {narrowed.reason}"
            )
    lines.append("")
    lines.append("Fixed for every town, which no description changes:")
    for fixed in view.fixed:
        lines.append(f"- {fixed.key}: {fixed.label}, {fixed.value}. Why: {fixed.reason}")
    lines.append("")
    lines.append(f'The description:\n"""{description}"""')
    if notes:
        lines.append("")
        lines.append(notes)
    return "\n".join(lines)


# -- the draft ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorldDraft:
    """A drafted specification: a preset, every adjustable value, and what the words asked for
    that the form cannot say. A proposal only; the server's validation decides."""

    preset: str
    #: Every adjustable key's value: the preset's, or the one the words set.
    values: Mapping[str, int | str]
    #: The keys the words set to a value other than the preset's, in the document's order.
    set_by_words: tuple[str, ...]
    fit: Literal["all", "part"]
    #: Each part of the description the form cannot say, as the description sent spells it.
    not_supported: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    draft: WorldDraft | None
    refusal: DraftRefusal | None
    #: The model that answered the accepted or refusing form; None when no form was accepted.
    model_id: str | None
    calls: tuple[ModelCall, ...]
    #: Each part of the description the form cannot say, as the description sent spells it, for a
    #: draft and for a refusal alike.
    not_supported: tuple[str, ...] = ()
    #: Where in the description sent each of those was copied from, ``(start, end)``.
    not_supported_at: tuple[tuple[int, int], ...] = ()


def _folded(text: str) -> tuple[str, list[int]]:
    """``text`` case-folded with each run of whitespace one space, and for each character of the
    result the index in ``text`` it came from."""
    out: list[str] = []
    where: list[int] = []
    spaced = False
    for index, character in enumerate(text):
        if character.isspace():
            if out and not spaced:
                out.append(" ")
                where.append(index)
            spaced = True
            continue
        spaced = False
        for folded in character.casefold():
            out.append(folded)
            where.append(index)
    return "".join(out), where


def verbatim_bounds(phrase: str, text: str) -> tuple[int, int] | None:
    """Where in ``text`` ``phrase`` is copied from, as ``(start, end)``, or None when it is not.

    A copy may differ from the text only in letter case, in how much whitespace separates its
    words, and in punctuation wrapped around it. A copy that would begin or end inside a
    placeholder the text carries (``[person A]``) is no copy: the words it stands for are the
    person's, and half a placeholder names nothing, so only an occurrence that takes each
    placeholder whole or not at all counts.
    """
    wanted, _ = _folded(phrase.strip(_WRAPPING))
    wanted = wanted.strip()
    if not wanted:
        return None
    haystack, where = _folded(text)
    placeholders = [(match.start(), match.end()) for match in PLACEHOLDER.finditer(text)]
    found = haystack.find(wanted)
    while found >= 0:
        start, end = where[found], where[found + len(wanted) - 1] + 1
        if not any((a < start < b) or (a < end < b) for a, b in placeholders):
            return start, end
        found = haystack.find(wanted, found + 1)
    return None


def verbatim_span(phrase: str, text: str) -> str | None:
    """``text``'s own slice that ``phrase`` copies (:func:`verbatim_bounds`), or None."""
    bounds = verbatim_bounds(phrase, text)
    return None if bounds is None else text[bounds[0] : bounds[1]]


def _read(
    value: BaseModel, view: SpecificationView, description: str
) -> tuple[WorldDraft | None, str | None, tuple[tuple[int, int], ...], tuple[str, ...]]:
    """A filled form read as a draft, or the fit it refused with, and where in the description
    each phrase it could not place was copied from; or, with neither, the phrases it did not copy
    from the description."""
    form = value.model_dump()
    copied: list[tuple[int, int]] = []
    missing: list[str] = []
    for phrase in form["not_supported"]:
        bounds = verbatim_bounds(phrase, description)
        if bounds is None:
            missing.append(phrase)
        elif bounds not in copied:
            copied.append(bounds)
    if missing:
        return None, None, (), tuple(missing)
    if form["fit"] == "none":
        return None, "none", tuple(copied), ()
    preset = view.preset(form["preset"])
    values = dict(preset.values)
    for entry in view.adjustable:
        if form[entry.key] is not None:
            values[entry.key] = form[entry.key]
    return (
        WorldDraft(
            preset=preset.key,
            values=values,
            set_by_words=tuple(
                entry.key
                for entry in view.adjustable
                if values[entry.key] != preset.values[entry.key]
            ),
            fit=form["fit"],
            not_supported=tuple(description[a:b] for a, b in copied),
        ),
        None,
        tuple(copied),
        (),
    )


def draft_world_specification(
    client: ModelClient,
    description: str,
    view: SpecificationView,
    *,
    prompt: DraftingPrompt | None = None,
    placeholders: Mapping[uuid.UUID, str] | None = None,
    log: CallLog | None = None,
    max_tokens: int | None = None,
    notes: str | None = None,
) -> DraftOutcome:
    """Ask the drafter to fill the form for ``description``, with one repair and no fallback.

    ``description`` is the text as it is sent, every saved name already replaced
    (:func:`sendable`), and ``placeholders`` the record of those replacements, handed to the
    boundary with the request. ``notes`` is a reference notes block as it is sent, its saved names
    replaced too, placed after the description; a copied phrase is checked against the description
    alone. ``log`` hears every attempt when ``client`` is the request's own
    copy (``ModelClient.with_attempts``). A form the client refuses (outside the schema, or
    truncated) and a form naming a phrase the description does not hold are each told why once;
    a second refusal is :attr:`DraftRefusalCode.NOT_DRAFTED`.
    """
    prompt = drafting_prompt() if prompt is None else prompt
    if max_tokens is None:
        # The ceiling the role declares, as the comparison that chose its model asked with; the
        # chain's own default would truncate a reasoning model's draft.
        declared = client.manifest[DRAFTER_ROLE].max_tokens
        max_tokens = None if declared is None else declared.value
    schema = draft_schema(view, prompt)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.instructions},
        {"role": "user", "content": render_form(view, description, notes)},
    ]
    log = CallLog() if log is None else log
    for attempt in range(1, DRAFT_ATTEMPTS + 1):
        repair: str
        try:
            drafted = client.structured(
                DRAFTER_ROLE,
                messages,
                schema,
                prompt_version=prompt.prompt_version,
                placeholders=placeholders,
                max_tokens=max_tokens,
            )
            log.record(drafted.call)
            draft, fit, copied, phrases = _read(drafted.value, view, description)
            if draft is not None or fit is not None:
                return DraftOutcome(
                    draft=draft,
                    refusal=None
                    if draft is not None
                    else DraftRefusal(
                        DraftRefusalCode.DESCRIPTION_NOT_SUPPORTED,
                        _REFUSAL_DETAILS[DraftRefusalCode.DESCRIPTION_NOT_SUPPORTED],
                    ),
                    model_id=drafted.call.served_model_id,
                    calls=log.calls,
                    not_supported=tuple(description[a:b] for a, b in copied),
                    not_supported_at=copied,
                )
            log.rejected(
                (f"{len(phrases)} not_supported phrase(s) not copied from the description",)
            )
            repair = prompt.repair_not_verbatim.format(
                phrases="; ".join(json.dumps(phrase, ensure_ascii=False) for phrase in phrases)
            )
        except TruncatedResponseError:
            repair = prompt.repair_truncated
        except StructuredOutputError as rejected:
            repair = prompt.repair_refused.format(reason=rejected)
        if attempt == DRAFT_ATTEMPTS:
            break
        messages.append({"role": "user", "content": repair})
    return DraftOutcome(
        draft=None,
        refusal=DraftRefusal(
            DraftRefusalCode.NOT_DRAFTED, _REFUSAL_DETAILS[DraftRefusalCode.NOT_DRAFTED]
        ),
        model_id=None,
        calls=log.calls,
    )


# -- names ---------------------------------------------------------------------------------------


class CutPlaceholder(ValueError):
    """A span of the description sent that begins or ends inside a replaced name."""


@dataclass(frozen=True, slots=True)
class SentDescription:
    """A description as it is sent, every saved name replaced, and the way back to the words the
    person typed. No saved name is kept here: a phrase is written back from the typed text."""

    text: str
    #: entity id -> placeholder, handed to the boundary with the request.
    placeholders: Mapping[uuid.UUID, str]
    #: The description as the person typed it.
    typed: str
    #: For each replaced name, in order: where its placeholder is in ``text`` and where the words
    #: it replaced are in ``typed``, ``(sent_start, sent_end, typed_start, typed_end)``.
    replaced: tuple[tuple[int, int, int, int], ...]

    def _typed_at(self, position: int) -> int:
        offset = 0
        for sent_start, sent_end, _typed_start, typed_end in self.replaced:
            if position >= sent_end:
                offset = typed_end - sent_end
            elif position > sent_start:
                raise CutPlaceholder("the span begins or ends inside a replaced name")
            else:
                break
        return position + offset

    def typed_words(self, start: int, end: int) -> str:
        """The person's own words for ``text[start:end]``: each placeholder inside it read as the
        words it replaced, as the person typed them. A span cutting a placeholder is refused."""
        return self.typed[self._typed_at(start) : self._typed_at(end)]


def sendable(
    connection: psycopg.Connection, workspace_id: uuid.UUID, description: str
) -> SentDescription:
    """``description`` with every saved name the workspace holds replaced, a place's included,
    each replacement recorded by position so a copied phrase can be read in the typed words."""
    names = saved_names(connection, workspace_id)
    # The labels, as the boundary would give them; the spans, as the same recognition finds them.
    labels = redact_names(description, names).placeholders
    pieces: list[str] = []
    replaced: list[tuple[int, int, int, int]] = []
    typed_at = sent_at = 0
    for start, end, saved in recognised_spans(description, names):
        label = labels.get(saved.entity_id)
        if label is None:
            # Nothing here labels it, so it is left as typed for the boundary to replace.
            continue
        before = description[typed_at:start]
        pieces.append(before)
        sent_at += len(before)
        pieces.append(label)
        replaced.append((sent_at, sent_at + len(label), start, end))
        sent_at += len(label)
        typed_at = end
    pieces.append(description[typed_at:])
    return SentDescription(
        text="".join(pieces),
        placeholders=dict(labels),
        typed=description,
        replaced=tuple(replaced),
    )


def propose_world_specification(
    connection: psycopg.Connection,
    client: ModelClient,
    description: str,
    workspace_id: uuid.UUID,
    view: SpecificationView,
    *,
    notes: str | None = None,
) -> tuple[DraftOutcome, SentDescription]:
    """Draft a specification for ``description`` with the workspace's saved names replaced first.

    The request sends through its own copy of the client, so its record lists every attempt it
    paid for; an error that ends it carries that record to the problem body. The phrases a draft
    could not place are returned by where they are in the description sent;
    :meth:`SentDescription.typed_words` reads each in the words the person typed. ``notes``, a
    reference notes block, is sent after the description with the same saved names replaced, each
    under the placeholder the description gave it, and the draft asks with :func:`notes_prompt`.
    """
    log = CallLog()
    prompt = notes_prompt(notes)
    try:
        sent = sendable(connection, workspace_id, description)
        placeholders: Mapping[uuid.UUID, str] = sent.placeholders
        notes_sent = None
        if notes:
            redacted = redact_names(
                notes,
                saved_names(connection, workspace_id),
                sent.placeholders,
                reserved=[match.group(0) for match in PLACEHOLDER.finditer(sent.text)],
            )
            notes_sent, placeholders = redacted.text, redacted.placeholders
        outcome = draft_world_specification(
            client.with_attempts(log.attempt),
            sent.text,
            view,
            prompt=prompt,
            placeholders=placeholders,
            log=log,
            notes=notes_sent,
        )
    except Exception as failed:
        log.on_failure(prompt.prompt_version).note(failed)
        raise
    return outcome, sent
