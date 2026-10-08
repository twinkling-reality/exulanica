"""A world kind drafted from a person's own words, as a proposal the server checks.

A person, or an agent through the API, describes a kind of place ("a fishing harbour with a fish
market and boats"). When no kind the library holds fits, an open model fills a brief of what the
place holds, the server compiles the brief into a whole world kind (``exulanica.world-kind/v1``,
:mod:`exulanica.world.kinds.document`), and holds that kind to both stages of its checks before
anything is kept or made:

*   **The model fills a brief with no keys** (:func:`~exulanica.selection.kind_brief.brief_form`,
    built from the kind catalogs and the society's routine at call time): what each zone holds
    nested in it, each part's use stated where it stands, every closed word a list to choose from
    and every object's arrays last. It names nothing twice, so nothing it names can be missing.
*   **The server compiles the brief** (:func:`~exulanica.selection.kind_brief.compile_brief`):
    the keys, every reference, the use classes, the spine and the boundary, the figures the
    document's shape needs, and the site's size, from the layout's own needs and the kind's own
    sample worlds.
*   **The server's checks are the one authority.** The caller's check runs stage A
    (``read_kind``) and stage B (sample worlds, in the kind worker) and its verdict decides. The
    model is told the rules the compiler cannot keep for it (the prompt file's ``rules``, each
    with the check that refuses a kind breaking it, which a test breaks to prove), and a kind the
    checks refuse is told the check's code, where in the brief, the check's own sentence and what
    the code means, never the reply's own text, and drafted again; a third refusal is refused by
    name.
*   **Every saved name is replaced before sending** (the caller's
    :func:`~exulanica.selection.world_drafting.sendable`), and the request passes the policy
    boundary every hosted request passes.
*   **What a drafted kind records.** Its origin is ``drafted`` and its provenance names the role,
    the model that answered, the prompt's version, the SHA-256 of the instructions sent (these
    words with the vocabulary the catalogs state) and the SHA-256 of the words sent, never the
    words.

The words the model is asked with are data (``kind-drafting.v4.json`` beside this module). Pure
apart from the model client: nothing is read from a connection and nothing is written.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from exulanica.grammar.grammars.site.layout import SPACING
from exulanica.grammar.grammars.site.plan import (
    ACCESS,
    ENCLOSURES,
    LOOK_FAMILIES,
    PLACEMENTS,
    ROOF_FORMS,
)
from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.models.response import Runaway
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.kind_brief import (
    COMPILED_ROLES,
    FORM_LOOKS,
    ROOM_FIXTURE_PATTERNS,
    USE_ROLES,
    ZONE_FIXTURE_PATTERNS,
    brief_form,
    brief_where,
    compile_brief,
)
from exulanica.world.kinds.catalogs import KindCatalogs, load_kind_catalogs
from exulanica.world.kinds.document import KIND_CODES, KindDocument
from exulanica.world.society_catalogs import RoutineModel

__all__ = [
    "DRAFT_ATTEMPTS",
    "PROMPT_PATH",
    "KindCheck",
    "KindDraftOutcome",
    "KindDraftRefusal",
    "KindDraftRefusalCode",
    "KindDraftingPrompt",
    "KindVerdict",
    "draft_kind",
    "kind_drafting_prompt",
    "render_instructions",
]

PROMPT_PATH: Final = Path(__file__).with_name("kind-drafting.v4.json")
_PROMPT_PROFILE: Final = "exulanica.kind-drafting-prompt/v3"
#: One brief and two repairs: a kind the checks refuse three times is refused by name, never
#: escalated to a larger model. Each repair names one check, so a second lets a draft that met one
#: refusal meet the next.
DRAFT_ATTEMPTS: Final = 3
#: The layout's clearances (:data:`~exulanica.grammar.grammars.site.layout.SPACING`), in the
#: words the instructions give them.
_SPACING_WORDS: Final = (
    ("verge", "the walkable verge along a zone's front"),
    ("setback", "a structure's front behind the verge"),
    ("structure_gap", "between two structures"),
    ("lane", "the lane between structures and the areas behind them"),
    ("side_margin", "kept clear at each side of a lot"),
    ("back_margin", "kept clear at a lot's back"),
    ("area_gap", "between two areas"),
    ("clearance", "kept clear round every fixture and structure"),
    ("minimum_area", "the narrowest area"),
    ("minimum_room", "the narrowest room"),
)
#: The bounds the instructions state: the ones a brief's own figures and counts meet.
_STATED_BOUNDS: Final = (
    "zones",
    "holdings",
    "rooms",
    "parts",
    "use_classes",
    "placed_things",
    "residents",
    "holding_count",
    "site_width_mm",
    "site_depth_mm",
    "structure_width_mm",
    "structure_depth_mm",
    "storeys",
    "fixture_size_mm",
    "fixture_places",
    "walking_nodes",
)


class KindDraftRefusalCode(StrEnum):
    """Why no kind was drafted: every brief was refused or the checks refused each kind."""

    NOT_DRAFTED = "kind_not_drafted"


@dataclass(frozen=True, slots=True)
class KindDraftRefusal:
    code: KindDraftRefusalCode
    detail: str
    #: The last check that refused the kind, by code and where in the brief, when one did.
    check: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class KindRule:
    """A rule the kind checks hold every kind to that the compiler cannot keep for the model, as
    the drafter is told it: its words, the check that refuses a kind breaking it, and the case a
    test breaks to prove that check still does."""

    rule: str
    code: str
    case: str


@dataclass(frozen=True, slots=True)
class KindDraftingPrompt:
    """The words the kind drafter is asked with, read from a ``kind-drafting.v<N>.json`` file."""

    version: int
    sha256: str
    instructions: str
    rules: tuple[KindRule, ...]
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
        return f"kind-drafting-{self.version}"

    def repair_cut(self, runaway: str | None) -> str:
        """The repair after a reply the token limit cut, by how it ran on
        (``TruncatedResponseError.runaway``): a brief that plainly ran on in blank space or
        repetition is told so; one that was neither was too large, and is asked for smaller."""
        if runaway == Runaway.WHITESPACE:
            return self.repair_whitespace
        if runaway == Runaway.REPETITION:
            return self.repair_repetition
        return self.repair_truncated


@functools.cache
def kind_drafting_prompt(path: Path = PROMPT_PATH) -> KindDraftingPrompt:
    """The kind drafter's words, read once and named by the file's SHA-256."""
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("profile") != _PROMPT_PROFILE:
        raise ValueError(f"{path.name} is not a {_PROMPT_PROFILE} document")
    repair = document["repair"]
    return KindDraftingPrompt(
        version=int(document["version"]),
        sha256=hashlib.sha256(raw).hexdigest(),
        instructions=str(document["instructions"]),
        rules=tuple(
            KindRule(str(rule["rule"]), str(rule["code"]), str(rule["case"]))
            for rule in document["rules"]
        ),
        repair_refused=str(repair["refused"]),
        repair_truncated=str(repair["truncated"]),
        repair_whitespace=str(repair["whitespace"]),
        repair_repetition=str(repair["repetition"]),
        repair_checks=str(repair["checks"]),
        description_characters_maximum=int(document["description_characters_maximum"]),
        drafted_licence=str(document["drafted_licence"]),
    )


# -- the vocabulary, from the catalogs ------------------------------------------------------------


def _clock(minute: int) -> str:
    return f"{minute // 60 % 24:02d}:{minute % 60:02d}"


def render_instructions(
    prompt: KindDraftingPrompt, catalogs: KindCatalogs, routine: RoutineModel
) -> str:
    """The system message: the prompt's words, then the vocabulary and bounds the kind catalogs
    and the society's routine state, rendered here so the words can never drift from them."""
    from exulanica.world.kinds.catalogs import CATALOG_DIRECTORY

    roles = json.loads(CATALOG_DIRECTORY.joinpath("kind-role.v1.json").read_text("utf-8"))
    entries = sorted(roles["entries"], key=lambda entry: entry["key"])
    lines = [
        prompt.instructions,
        "",
        "What a part may be used as (its use_role), with the part forms that may be used so. The "
        "server makes each part's use class from its use_role, work and visit:",
    ]
    for entry in entries:
        if entry["key"] in USE_ROLES:
            lines.append(f"- {entry['key']} ({', '.join(entry['forms'])}): {entry['reason']}")
    lines.append("")
    lines.append("The other roles a part may take (its roles), with the part forms that may:")
    for entry in entries:
        if entry["key"] not in USE_ROLES and entry["key"] not in COMPILED_ROLES:
            lines.append(f"- {entry['key']} ({', '.join(entry['forms'])}): {entry['reason']}")
    lines.append("")
    lines.append(f"Look families: {', '.join(LOOK_FAMILIES)}. The look each may name:")
    named = {
        "path": "the spine",
        "area": "an area",
        "structure": "a structure",
        "room": "a room's floor",
        "fixture": "a fixture",
        "boundary": "the boundary",
    }
    for form, families in FORM_LOOKS.items():
        lines.append(f"- {named[form]}: {', '.join(families)}")
    lines.append(
        "- a structure's roof_look: roof, and its wall_look: wall; a zone's and the site's "
        "ground: ground."
    )
    lines.append("")
    lines.append(
        f"Patterns a zone lays its fixtures out by: {', '.join(ZONE_FIXTURE_PATTERNS)}; a room "
        f"its fixtures: {', '.join(ROOM_FIXTURE_PATTERNS)}."
    )
    lines.append(f"Placements: {', '.join(PLACEMENTS)}. Access: {', '.join(ACCESS)}.")
    lines.append(f"Enclosures: {', '.join(ENCLOSURES)}. Roof forms: {', '.join(ROOF_FORMS)}.")
    affordances = sorted({activity.affordance for activity in routine.activities.values()})
    lines.append(f"What visitors may do (visitor_affordances): {', '.join(affordances)}.")
    shifts = ", ".join(
        f"{key} ({_clock(shift.start_minute)} to {_clock(shift.start_minute + shift.minutes)})"
        for key, shift in sorted(routine.shifts.items())
    )
    lines.append(f"Shifts: {shifts}. Minutes count from midnight, 0 to 1440.")
    lines.append("")
    lines.append(
        "Rules the server cannot keep for you; it refuses a kind that breaks one by the check "
        "named:"
    )
    for rule in prompt.rules:
        lines.append(f"- {rule.rule} ({rule.code})")
    lines.append("")
    lines.append("The room the layout keeps, in mm, outdoors and indoors:")
    for name, meaning in _SPACING_WORDS:
        outdoors, indoors = getattr(SPACING["open"], name), getattr(SPACING["indoor"], name)
        lines.append(f"- {meaning}: {outdoors} outdoors, {indoors} indoors")
    lines.append("")
    lines.append("Bounds every kind is held to (least to greatest):")
    for key in _STATED_BOUNDS:
        low, high = catalogs.bound(key)
        lines.append(f"- {key}: {low} to {high}")
    return "\n".join(lines)


# -- the draft ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KindVerdict:
    """What the checks said of one drafted kind: passed, with the kind read and its validation
    report, or refused by code and where in the kind document."""

    passed: bool
    kind: KindDocument | None = None
    report: Mapping[str, Any] | None = None
    code: str = ""
    where: str = ""
    #: The check's own sentence, which the repair repeats: the server's words, never the reply's.
    detail: str = ""


#: The checks a drafted kind meets: stage A and stage B, as the caller runs them (the API in the
#: kind worker; a measurement in its own process).
KindCheck = Callable[[dict[str, Any]], KindVerdict]


@dataclass(frozen=True, slots=True)
class KindDraftOutcome:
    """A drafted kind that passed every check, or why there is none, with every call made."""

    document: dict[str, Any] | None
    kind: KindDocument | None
    report: Mapping[str, Any] | None
    refusal: KindDraftRefusal | None
    #: The model that answered the accepted brief; None when no kind passed.
    model_id: str | None
    calls: tuple[ModelCall, ...]
    #: Each attempt's outcome: ``passed``, ``form_refused``, ``truncated`` (``truncated:whitespace``
    #: or ``truncated:repetition`` when the reply plainly ran on so) or ``check:<code>``.
    attempts: tuple[str, ...] = ()
    #: Each attempt as it went: its outcome, the brief and what sizing changed, and for a kind the
    #: checks refused the check's code, place and sentence and the document it refused; for a
    #: measurement's record.
    trail: tuple[Mapping[str, Any], ...] = ()


_MEANINGS: Final = dict(KIND_CODES)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def draft_kind(
    client: ModelClient,
    description: str,
    *,
    role: Role,
    check: KindCheck,
    version: int = 1,
    prompt: KindDraftingPrompt | None = None,
    catalogs: KindCatalogs | None = None,
    routine: RoutineModel | None = None,
    placeholders: Mapping[Any, str] | None = None,
    log: CallLog | None = None,
    max_tokens: int | None = None,
    trail: list[dict[str, Any]] | None = None,
) -> KindDraftOutcome:
    """Ask the drafter for a kind of ``description``, compile and check it, with two repairs and
    no fallback.

    ``description`` is the text as it is sent, every saved name already replaced, and
    ``placeholders`` the record of those replacements, handed to the boundary with the request.
    A brief the client refuses (outside the schema, or cut off, named by how it ran on when it
    plainly did) and a kind the checks refuse are each told why, by the check's code, place and
    sentence and never the reply's own words; a third refusal is
    :attr:`KindDraftRefusalCode.NOT_DRAFTED`.

    ``trail``, when given, is the caller's own list each attempt is recorded in as it goes, so a
    measurement keeps the attempts made before a call that raises (a provider's timeout).
    """
    prompt = kind_drafting_prompt() if prompt is None else prompt
    catalogs = load_kind_catalogs() if catalogs is None else catalogs
    if routine is None:
        from exulanica.world.society_living import town_routine

        routine = town_routine()
    if max_tokens is None:
        declared = client.manifest[role].max_tokens
        max_tokens = None if declared is None else declared.value
    instructions = render_instructions(prompt, catalogs, routine)
    form = brief_form(catalogs, routine)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": f'The description:\n"""{description}"""'},
    ]
    log = CallLog() if log is None else log
    attempts: list[str] = []
    trail = [] if trail is None else trail
    last_check: tuple[str, str] | None = None
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
            provenance = {
                "role": str(role.value),
                "model": drafted.call.served_model_id,
                "prompt_version": prompt.prompt_version,
                "prompt_sha256": _digest(instructions),
                "words_sha256": _digest(description),
            }
            brief = drafted.value.model_dump(mode="json")
            compiled = compile_brief(
                brief,
                version=version,
                provenance=provenance,
                licence=prompt.drafted_licence,
                catalogs=catalogs,
                routine=routine,
            )
            verdict = check(compiled.document)
            if verdict.passed:
                attempts.append("passed")
                trail.append({"outcome": "passed", "sizing": list(compiled.sizing), "brief": brief})
                return KindDraftOutcome(
                    document=compiled.document,
                    kind=verdict.kind,
                    report=verdict.report,
                    refusal=None,
                    model_id=drafted.call.served_model_id,
                    calls=log.calls,
                    attempts=tuple(attempts),
                    trail=tuple(trail),
                )
            where = brief_where(verdict.where, compiled)
            # The check's own sentence, on one line: the server's words about the kind, which
            # quote at most a key, a label or a figure the brief held to its pattern and bounds.
            detail = " ".join(verdict.detail.split())[:400]
            last_check = (verdict.code, where)
            attempts.append(f"check:{verdict.code}")
            trail.append(
                {
                    "outcome": f"check:{verdict.code}",
                    "code": verdict.code,
                    "where": where,
                    "detail": detail,
                    "sizing": list(compiled.sizing),
                    "brief": brief,
                    "document": compiled.document,
                }
            )
            log.rejected((f"refused by check {verdict.code} at {where}",))
            repair = prompt.repair_checks.format(
                code=verdict.code,
                where=where or "the whole kind",
                detail=detail or "refused",
                meaning=_MEANINGS.get(verdict.code, ""),
            )
        except TruncatedResponseError as cut:
            outcome = "truncated" if cut.runaway is None else f"truncated:{cut.runaway}"
            attempts.append(outcome)
            trail.append({"outcome": outcome})
            repair = prompt.repair_cut(cut.runaway)
        except StructuredOutputError:
            attempts.append("form_refused")
            trail.append({"outcome": "form_refused"})
            repair = prompt.repair_refused
        if attempt == DRAFT_ATTEMPTS:
            break
        messages.append({"role": "user", "content": repair})
    return KindDraftOutcome(
        document=None,
        kind=None,
        report=None,
        refusal=KindDraftRefusal(
            KindDraftRefusalCode.NOT_DRAFTED,
            "No kind of world was drafted from these words that people could live, walk and work "
            "in.",
            last_check,
        ),
        model_id=None,
        calls=log.calls,
        attempts=tuple(attempts),
        trail=tuple(trail),
    )
