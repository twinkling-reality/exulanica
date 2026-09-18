"""The nine hard-pass keys of the visual gate, and the only spellings that resolve to them.

Three retained rejection records scored the same questions under three drifted spellings: six
keys in the first Helsinki record, seven in its successor and nine in Melbourne. A corridor scored
against a fourth spelling would be comparable to none of them, so this module is the one place the
spellings are reconciled, and it is a closed vocabulary rather than a convention.

**A spelling nobody listed raises.** :func:`resolve` refuses an unknown spelling instead of passing
it through, because a key that silently passes through is a key that silently drops out of the
block the corridor has to beat.

**Absence is not a value.** A key a retained record did not score is absent from that record's
entry in :data:`RETAINED_RECORDS`. Nothing here infers ``True`` or ``False`` for it, and nothing
here re-scores a retained run: the retained values are quoted under their own spellings by the
reconciliation record and no canonical value is asserted for any predecessor run.

**Every threshold is an integer.** Lengths are millimetres and budgets are bytes or counts, so a
threshold can enter a digest input as it stands. ``exulanica.canonical`` refuses floats there, and
a record that restated a threshold as a float would not be writable at all.

**Version 2 changed the judged key and nothing else.** The rubric asked one plain question of
each picture and stopped at the first no, where version 1 asked three questions of each.
:data:`RUBRIC_V1` keeps version 1's wording so its retained record can still be checked.

**Version 3 changed the question and one definition's wording, and nothing that is measured.**
Version 2's question was answered yes for all three pictures of a district drawn in flat colour, so
it did not separate a finished street from a block mock-up; version 3 asked that directly. The
product-shell key named only keyboard listeners while the product enters its world with a click on
the world canvas; version 3 names keyboard and pointer listeners and says what carrying a click
means. No measurement, threshold or mechanical decision moved.

**Version 4 gave the question one meaning.** Version 3's question joined two claims, so a yes, a no
or a short negation in the judge's own words could attach to either. Version 4 asks one thing and
each option says what it means.

**Version 5 changed only how a typed reply is read.** A typed reply with no pick counts as no when
it holds the whole word "no" and not the whole word "yes", and never counts as yes, so a typed reply
can fail the key and never pass it. Nothing the judge is shown changed. :data:`VERSION_2`,
:data:`VERSION_3` and :data:`VERSION_4` keep the earlier wording for their records.

Pure: this module imports nothing from the product, performs no I/O and holds no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

__all__ = [
    "ANSWER_OPTIONS",
    "ANSWER_REQUIREMENT",
    "AUTHENTICATION_CONDITIONS",
    "CANONICAL_KEYS",
    "CANONICAL_SPELLINGS",
    "CAPTURE_LABELS",
    "CARRIED_WORDS_NOTICE",
    "CLASSIFICATION",
    "EVIDENCE_KINDS",
    "GATE_KEY_SET_VERSION",
    "GATE_TARGETS",
    "GATE_TARGET_IDS",
    "GENERATED_TILE_TARGET",
    "JUDGED_KEY",
    "MELBOURNE_ENVELOPE",
    "NOT_ASKED",
    "OPTION_ANSWERS",
    "OWNED_DISTRICT_TARGET",
    "PICTURE_TITLES",
    "REASON_FOLLOW_UP",
    "RETAINED_RECORDS",
    "RUBRIC_GUIDANCE",
    "RUBRIC_PATH",
    "RUBRIC_QUESTION",
    "RUBRIC_V1",
    "RUBRIC_VERSION",
    "SUPERSEDED_VERSIONS",
    "THRESHOLDS",
    "TYPED_REPLY_RULE",
    "VERSION_2",
    "VERSION_3",
    "VERSION_4",
    "WORDS_STORAGE",
    "GateKey",
    "GateTarget",
    "RetainedRecord",
    "SupersededRubric",
    "SupersededVersion",
    "UnknownGateKey",
    "gate_target",
    "judge_prompt",
    "key",
    "reason_follow_up",
    "resolve",
    "target_of",
]

EvidenceKind = Literal["mechanical", "judged"]

#: Bumped only by a new reconciliation record. The corridor is scored against this version.
GATE_KEY_SET_VERSION: Final = "exulanica.visual-gate-keys/v5"

EVIDENCE_KINDS: Final[tuple[EvidenceKind, ...]] = ("mechanical", "judged")

#: The three route captures every key that reads a capture reads, in route order.
CAPTURE_LABELS: Final[tuple[str, ...]] = ("start", "midpoint", "endpoint")

RUBRIC_PATH: Final = "docs/visual-gate-rubric.md"

#: The rubric's own version line reads ``Rubric version: 5``.
RUBRIC_VERSION: Final = 5

#: How each capture is labelled when it is shown to the judge, alone, in route order.
PICTURE_TITLES: Final[Mapping[str, str]] = MappingProxyType(
    {
        label: f"Picture {index} of {len(CAPTURE_LABELS)}"
        for index, label in enumerate(CAPTURE_LABELS, start=1)
    }
)

#: The one question, asked of each picture in these words and never paraphrased.
RUBRIC_QUESTION: Final = (
    "Is this a finished, lived-in street? Yes or no, and say why in your own words."
)

#: Shown directly under the question. Guidance for what each answer means, not more questions.
RUBRIC_GUIDANCE: Final = (
    "A yes means: the surfaces look like real materials (brick, stone, glass, paving), not flat "
    "colour; you could name what at least three ground-floor shops or entrances are; the "
    "buildings form an unbroken street edge with no cut or hole; you can see things near (about "
    "30 m), middle (about 100 m) and far (about 300 m). A no means it looks like a plain block "
    "mock-up."
)

#: The last line of every ask, so that an answer arrives with its reason.
ANSWER_REQUIREMENT: Final = (
    "Pick Yes or No and type a few words why in the notes; the answer cannot be recorded "
    "without them."
)

#: The only options the judge is offered, in this order, neither marked or preselected. Each says
#: what it means, so a pick cannot be read two ways.
ANSWER_OPTIONS: Final[tuple[str, ...]] = (
    "Yes, a finished, lived-in street",
    "No, a plain block mock-up",
)

#: The answer each option gives.
OPTION_ANSWERS: Final[Mapping[str, str]] = MappingProxyType(
    {ANSWER_OPTIONS[0]: "yes", ANSWER_OPTIONS[1]: "no"}
)

#: What a record says of each picture after the first no. Those pictures are never asked.
NOT_ASKED: Final = "not asked after a decisive no"

#: The one follow-up a picture may get, and only when its answer arrived with no words. Its reply
#: is the answer's reason and never changes the answer.
REASON_FOLLOW_UP: Final = "You answered {answer}. In a few words, why?"

#: Where the judge's words are kept, as every rubric version states it. The words never enter the
#: repository; a public record carries their SHA-256 and byte count in their place.
WORDS_STORAGE: Final = (
    "The judge's own words are kept exactly as typed in a private companion record under "
    ".exulanica/judge-words/, which never enters the repository. The public record binds that "
    "companion by SHA-256 and carries, for each reply, the SHA-256 and byte count of its words in "
    "their place."
)

#: Shown above a picture's question when words the judge wrote about that picture under an earlier
#: rubric version are carried into its ask. It explains the ask and nothing about the picture.
CARRIED_WORDS_NOTICE: Final = (
    "The question now has one meaning. Pick the answer you mean. The words you already wrote "
    "about this picture are kept; add more if you like."
)


#: How a reply the judge types instead of picking an option is read, as the records state it.
TYPED_REPLY_RULE: Final = (
    "A typed reply with no pick counts as no when it contains the whole word no, in any case, and "
    "does not contain the whole word yes. A typed reply never counts as yes; a yes must be picked. "
    "Any other typed reply is not an answer."
)

#: How versions 2 to 4 read a typed reply.
_TYPED_REPLY_RULE_BEFORE_V5: Final = (
    "A typed reply with no pick counts only when its first word is yes or no, and then as that "
    "word."
)


def judge_prompt(label: str) -> str:
    """Exactly what the judge reads for one capture: label, question, guidance, requirement."""
    if label not in PICTURE_TITLES:
        raise ValueError(f"{label!r} is not a route capture; expected one of {CAPTURE_LABELS}")
    return (
        f"{PICTURE_TITLES[label]}\n\n{RUBRIC_QUESTION}\n\n{RUBRIC_GUIDANCE}\n\n{ANSWER_REQUIREMENT}"
    )


def reason_follow_up(answer: str) -> str:
    """Exactly what the judge reads when an answer, ``yes`` or ``no``, arrived without words."""
    if answer not in OPTION_ANSWERS.values():
        raise ValueError(f"{answer!r} is not an answer the options give")
    return REASON_FOLLOW_UP.format(answer=answer.capitalize())


@dataclass(frozen=True, slots=True)
class SupersededRubric:
    """Rubric version 1, which no record may be scored against, as its record stated it."""

    key_set: str
    questions: tuple[tuple[str, str], ...]
    judged_definition: str
    composition: str


#: Version 1, superseded before any corridor was scored. Its record is retained, not rewritten.
RUBRIC_V1: Final = SupersededRubric(
    key_set="exulanica.visual-gate-keys/v1",
    questions=(
        (
            "premises",
            "Can the viewer name a plausible use for at least three ground-floor premises?",
        ),
        (
            "frontage",
            "Is the frontage continuous, with no gap that reads as a cut?",
        ),
        (
            "depth",
            "Is there a legible depth cue at roughly 30 m, 100 m and 300 m?",
        ),
    ),
    judged_definition=(
        "True only when the human judge named in docs/visual-gate-rubric.md answers yes to all "
        "three rubric questions for each of the start, midpoint and endpoint captures, nine "
        "yes answers of nine, and never when an answer is missing or was given by a model."
    ),
    composition=(
        "Each of the three questions is answered yes or no for each of the three captures. The "
        "key is true only for nine yes answers of nine. The score is the number of yes answers, "
        "and a corridor fails unless its score is strictly greater than the Flatiron baseline's."
    ),
)


@dataclass(frozen=True, slots=True)
class SupersededVersion:
    """A one-question rubric and key set version no record may be scored against any longer."""

    key_set: str
    rubric_version: int
    rubric_sha256: str
    question: str
    guidance: str
    #: The last line of each ask, or None when the version had none.
    requirement: str | None
    options: tuple[str, ...]
    composition: str
    #: Canonical definitions that differ from the current ones, keyed by spelling.
    definitions: Mapping[str, str]
    #: The line shown above a question that carries earlier words, or None when there was none.
    carried_notice: str | None = None
    typed_reply_rule: str = _TYPED_REPLY_RULE_BEFORE_V5

    def prompt(self, label: str) -> str:
        """What the judge read for one capture under this version."""
        parts = [PICTURE_TITLES[label], self.question, self.guidance]
        if self.requirement is not None:
            parts.append(self.requirement)
        return "\n\n".join(parts)

    def shows_what_is_shown_now(self) -> bool:
        """Whether the judge saw exactly what the current version shows: every line and option."""
        return (
            self.question,
            self.guidance,
            self.requirement,
            self.options,
            self.carried_notice,
        ) == (
            RUBRIC_QUESTION,
            RUBRIC_GUIDANCE,
            ANSWER_REQUIREMENT,
            ANSWER_OPTIONS,
            CARRIED_WORDS_NOTICE,
        )


_SHELL_DEFINITION_V2: Final = (
    "True only when every capture was taken in the product's own shell document with a mounted "
    "world and no credential gate, empty-world or error surface, every listener on the window, "
    "the document and the world canvas comes from the product's own modules, the product's "
    "keyboard listeners carried every interaction the harness made, and no page or handler was "
    "substituted; as the retained Melbourne record used it, the key does not by itself assert a "
    "bearer credential, so every record states its authentication condition in a separate field."
)

#: Version 2, superseded before any corridor or any record was scored against it. Its record is
#: retained, and the answers given under it are version 3's calibration evidence.
VERSION_2: Final = SupersededVersion(
    key_set="exulanica.visual-gate-keys/v2",
    rubric_version=2,
    rubric_sha256="05bd20cebcc06bbbdc143102fd21c2b979adae6ea882cdc74b06a347b938ab1d",
    question=(
        "Does this look like a real street where people live, shop and work? "
        "Yes or no, and say why in your own words."
    ),
    guidance=(
        "A yes means: you could name what at least three ground-floor shops or entrances are; the "
        "buildings form an unbroken street edge with no cut or hole; you can see things near "
        "(about 30 m), middle (about 100 m) and far (about 300 m)."
    ),
    requirement=None,
    options=("Yes", "No"),
    composition=(
        "Each capture is shown alone, in route order, and the judge answers the one question yes "
        "or no with their own words. The first no makes the key false and the pictures after it "
        "are not asked. The key is true only when all three pictures got yes. There is no score."
    ),
    definitions=MappingProxyType(
        {"authenticatedShellAndAuthoredHandlersPreserved": _SHELL_DEFINITION_V2}
    ),
)

#: Version 3, superseded before any answer was scored under it. Its record is retained, and the
#: pick and message given under it are version 4's calibration evidence.
VERSION_3: Final = SupersededVersion(
    key_set="exulanica.visual-gate-keys/v3",
    rubric_version=3,
    rubric_sha256="2a1c9c62451dc8ad18b3f870d74a021e6ed419cb6059fa6da0bd11927f9fc560",
    question=(
        "Does this look like a finished, lived-in street, not a plain block mock-up? "
        "Yes or no, and say why in your own words."
    ),
    guidance=(
        "A yes means: the surfaces look like real materials (brick, stone, glass, paving), not "
        "flat colour; you could name what at least three ground-floor shops or entrances are; the "
        "buildings form an unbroken street edge with no cut or hole; you can see things near "
        "(about 30 m), middle (about 100 m) and far (about 300 m)."
    ),
    requirement=(
        "Pick Yes or No and type a few words why in the notes; the answer cannot be recorded "
        "without them."
    ),
    options=("Yes", "No"),
    composition=(
        "Each capture is shown alone, in route order, and the judge answers the one question yes "
        "or no with their own words. An answer that arrives without words may be followed once, "
        "with the picture shown alone again, by a request for the reason, and that reply never "
        "changes the answer. The first no makes the key false and the pictures after it are not "
        "asked. The key is true only when all three pictures got yes. There is no score."
    ),
    definitions=MappingProxyType({}),
)

#: Version 4, superseded before any answer was scored under it. Its record is retained, and the
#: reply given under it is the first one version 5's typed-reply rule reads.
VERSION_4: Final = SupersededVersion(
    key_set="exulanica.visual-gate-keys/v4",
    rubric_version=4,
    rubric_sha256="ad66410202ee39eca938db435fa7417dabd342a075f48567df316c2db706bb0b",
    question="Is this a finished, lived-in street? Yes or no, and say why in your own words.",
    guidance=(
        "A yes means: the surfaces look like real materials (brick, stone, glass, paving), not "
        "flat colour; you could name what at least three ground-floor shops or entrances are; the "
        "buildings form an unbroken street edge with no cut or hole; you can see things near "
        "(about 30 m), middle (about 100 m) and far (about 300 m). A no means it looks like a "
        "plain block mock-up."
    ),
    requirement=(
        "Pick Yes or No and type a few words why in the notes; the answer cannot be recorded "
        "without them."
    ),
    options=("Yes, a finished, lived-in street", "No, a plain block mock-up"),
    composition=(
        "Each capture is shown alone, in route order, and the judge answers the one question with "
        "the option they mean and their own words. An answer that arrives without words may be "
        "followed once, with the picture shown alone again, by a request for the reason, and that "
        "reply never changes the answer. A pick that the judge's own words, given right after it, "
        "may contradict is not recorded. Words the judge wrote about a picture before its question "
        "was reworded are carried into its next ask, under a line that says so; they are part of "
        "the reason for a no, and a yes needs new words. The first no makes the key false and the "
        "pictures after it are not asked. The key is true only when all three pictures got yes. "
        "There is no score."
    ),
    definitions=MappingProxyType({}),
    carried_notice=(
        "The question now has one meaning. Pick the answer you mean. The words you already wrote "
        "about this picture are kept; add more if you like."
    ),
)

#: Every one-question version this one supersedes, oldest first.
SUPERSEDED_VERSIONS: Final[tuple[SupersededVersion, ...]] = (VERSION_2, VERSION_3, VERSION_4)

#: The two conditions the product-shell key has actually been scored under. Melbourne's record
#: set the key true while its preview API answered three 404s, so the key alone never says which.
AUTHENTICATION_CONDITIONS: Final[tuple[str, ...]] = ("credentialed-api", "vite-preview-api")

#: The page a run scored, as data rather than as a check written into the harness.
#:
#: **Why this is a closed list and not a rule.** The gate refuses any page whose title is not the
#: one its target states. A pattern would let the next page through for free; a list makes admitting
#: one an edit somebody has to make and somebody else has to read. Appending is how a target is
#: added, and a record naming a target nobody listed is refused rather than scored.
#:
#: **Why a record without a target reads as the owned district.** The retained records were written
#: before any other page could be scored and they are immutable, so the default is the only reading
#: that keeps them true. :func:`target_of` is the one place that reading lives.
#:
#: Each target states how its page is reached, the exact title it must show, what mounted means for
#: it, which conditions it may run under, what its record binds, and where the route rule's inputs
#: come from. The titles are NOT written here: the harness derives each from the product's own
#: source, and halts when the derivation finds nothing.
OWNED_DISTRICT_TARGET: Final = "owned-district"
GENERATED_TILE_TARGET: Final = "generated-tile-evaluation"


@dataclass(frozen=True)
class GateTarget:
    """One page the gate may score, and everything that makes a run of it comparable."""

    identifier: str
    path: str
    #: Query parameters the page must carry, and for each the parameters it may be selected by.
    required_parameters: tuple[str, ...]
    selector_parameters: tuple[str, ...]
    #: Where the expected title comes from in the product's own source.
    title_source: str
    title_symbol: str
    mounted: str
    authentication_conditions: tuple[str, ...]
    binds: tuple[str, ...]
    route_inputs: str


GATE_TARGETS: Final[tuple[GateTarget, ...]] = (
    GateTarget(
        identifier=OWNED_DISTRICT_TARGET,
        path="/",
        required_parameters=(),
        selector_parameters=(),
        title_source="web/packages/app/src/config.ts",
        title_symbol="PRODUCT_TITLE",
        mounted=(
            "#shell carries no data-world-state, #atlas is a canvas that is not hidden and states "
            "worldTopology, and neither a credential gate nor an empty world is on the page"
        ),
        authentication_conditions=AUTHENTICATION_CONDITIONS,
        binds=(
            "the owned district artifact, matched byte for byte on the wire",
            "the renderer module that drew it",
        ),
        route_inputs=(
            "the product's own arrival pose, the collision rings its navigation world holds, and "
            "the field bounds the artifact states"
        ),
    ),
    GateTarget(
        identifier=GENERATED_TILE_TARGET,
        path="/",
        required_parameters=("preview",),
        selector_parameters=("tile", "baked_tile", "city"),
        title_source="web/packages/app/src/config.ts",
        title_symbol="PREVIEW_TITLE",
        mounted=(
            "everything the owned district target requires, and the tile runtime reporting the "
            "containers it loaded"
        ),
        # A committed golden is served by the development module with no credential; a stored tile
        # is fetched from /tiles with the session's own, so both conditions are reachable here.
        authentication_conditions=AUTHENTICATION_CONDITIONS,
        binds=(
            "every drawn container's sha256, matched byte for byte on the wire",
            "every drawn container's tile_inputs_digest",
            "the city seed and the grammar id and version set the containers state",
            "the tile runtime module that drew them",
            "the look descriptor id and version",
        ),
        route_inputs=(
            "the arrival pose the tile's own records state, and the route obstruction rings its "
            "navigation side states: the plan regions a walking capsule is kept clear of, READ "
            "from the runtime's navigation world rather than re-derived here, because a gate that "
            "derives its own rings scores a walk past obstacles the world does not have. They are "
            "not collision solids and must never be read as any: they are an input to CHOOSING a "
            "heading, and nothing in them stops a body. A run may choose neither input, and the "
            "gate halts while the tile states neither"
        ),
    ),
)

GATE_TARGET_IDS: Final[tuple[str, ...]] = tuple(target.identifier for target in GATE_TARGETS)


def gate_target(identifier: str) -> GateTarget:
    """The declared target, or a refusal naming the list it is missing from."""
    for target in GATE_TARGETS:
        if target.identifier == identifier:
            return target
    raise ValueError(
        f"{identifier!r} is not a gate target; declared targets are {', '.join(GATE_TARGET_IDS)}"
    )


def target_of(record: Mapping[str, object]) -> str:
    """The target a record scored. A record without one is the owned district, and always was."""
    stated = record.get("target", OWNED_DISTRICT_TARGET)
    if not isinstance(stated, str):
        raise ValueError("a record's target is a string")
    return gate_target(stated).identifier


#: Every geometric tolerance the gate uses. Millimetres unless the name says otherwise.
THRESHOLDS: Final[Mapping[str, int]] = MappingProxyType(
    {
        # The grounded Atlas contract: eye height, capsule radius and maximum step.
        "eyeHeightMm": 1620,
        "eyeHeightToleranceMm": 50,
        "capsuleRadiusMm": 340,
        "capsuleHeightMm": 1900,
        "stepHeightMm": 180,
        "walkableSlopeDegrees": 12,
        # "Support resampled to within 0.05 m": both the sample spacing and the agreement.
        "supportSampleSpacingMm": 50,
        "supportAgreementMm": 50,
        # The same 0.05 m is the only contact tolerance, so nothing here invents a second one.
        "contactToleranceMm": 50,
        # The deepest reveal the corridor target allows, 120 to 250 mm, bounds what counts as
        # facade: a surface farther than this from the collision ring is not the facade.
        "facadeBandMm": 250,
        # Where a collision edge is probed for a drawn facade: the eye-level band.
        "facadeProbeHeightMm": 1000,
        # The bounded route: roughly 125 m, walked at least 120 m, with no collision slide.
        "routeLengthMm": 125_000,
        "minimumWalkedMm": 120_000,
        "maximumLateralDeviationMm": 340,
        # How far to either side a building counts as frontage when a route is chosen.
        "frontageSearchMm": 40_000,
    }
)

#: Melbourne's measured values, which docs/evaluation names its accepted 125 m envelope. Only the
#: values that do not vary between runs of one build decide ``practicalBrowserBudget``.
MELBOURNE_ENVELOPE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "environmentTransferredBytes": 28_247_006,
        "drawnTriangles": 227_173,
        "environmentDecodedTextureBytes": 167_772_160,
        "maxDrawCalls": 87,
    }
)

#: How the mechanical keys classify a drawn triangle. Stated once so both implementations and
#: the reconciliation record say the same thing.
CLASSIFICATION: Final[Mapping[str, str]] = MappingProxyType(
    {
        "drawnGeometry": (
            "Every triangle of every enabled, visible mesh instance the application renders in "
            "its world layer, in world coordinates, read from the live renderer."
        ),
        "walkingSurfaceTriangle": (
            "A drawn triangle whose unit normal has an upward component of at least cos(12 "
            "degrees) and whose centroid lies no more than 0.18 m above the navigation support."
        ),
        "facadeTriangle": (
            "A drawn triangle whose unit normal has a vertical component of at most sin(12 "
            "degrees), whose centroid lies within 0.25 m horizontally of a building exterior ring "
            "edge and between the support and that building's top."
        ),
        "texturedTriangle": (
            "A drawn triangle whose mesh carries a texture coordinate channel and whose material "
            "binds at least one texture with nonzero decoded bytes."
        ),
        "component": (
            "A connected set of drawn triangles, joined where vertices coincide to the millimetre."
        ),
        "contact": (
            "Two components are in contact when a vertex of one lies within 0.05 m of a triangle "
            "of the other, or inside the other's closed volume, or an edge of one crosses a "
            "triangle of the other."
        ),
        "buildingVolume": (
            "The prism of a building exterior ring from its support to its top, shrunk by 0.05 m "
            "on every side."
        ),
        "routeSample": (
            "A point of the walked trace resampled along its length at 0.05 m spacing."
        ),
    }
)


@dataclass(frozen=True, slots=True)
class GateKey:
    """One canonical key: what makes it true, and what decides it."""

    spelling: str
    definition: str
    evidence_kind: EvidenceKind
    #: The named measurement that decides a mechanical key. None for the judged key.
    measurement: str | None
    #: The measured fields the decision reads. Empty for the judged key.
    decided_by: tuple[str, ...]
    #: Retained spellings, other than the canonical spelling itself, that resolve to this key.
    predecessor_spellings: tuple[str, ...]


JUDGED_KEY: Final = "readsAsInhabitedStreet"

CANONICAL_KEYS: Final[tuple[GateKey, ...]] = (
    GateKey(
        spelling="continuousTexturedStreetAndFacades",
        definition=(
            "True only when at least one walking-surface or facade triangle is drawn, every drawn "
            "walking-surface and facade triangle is textured, and the drawn walking surface has "
            "no gap at any route sample."
        ),
        evidence_kind="mechanical",
        measurement="textured-surface-coverage/v1",
        decided_by=(
            "streetAndFacadeTriangles",
            "untexturedStreetAndFacadeTriangles",
            "routeSupportGapSamples",
        ),
        predecessor_spellings=(
            "continuousTexturedGround",
            "continuousTexturedStreet",
            "continuousSourceTexturedStreetAndFacades",
        ),
    ),
    GateKey(
        spelling=JUDGED_KEY,
        definition=(
            "True only when the human judge named in docs/visual-gate-rubric.md, shown the start, "
            "midpoint and endpoint captures one at a time and in that order, answers yes to the "
            "rubric's one question for all three, each answer with the judge's own words; the "
            "first no makes it false and the pictures after it are not asked, and it is never "
            "true while a picture is unasked or when an answer was given, suggested or pre-filled "
            "by a model."
        ),
        evidence_kind="judged",
        measurement=None,
        decided_by=(),
        predecessor_spellings=(
            "recognizableUrbanStreet",
            "recognizableUrbanScene",
            "recognizableMelbourneUrbanScene",
        ),
    ),
    GateKey(
        spelling="noCutsOrFloatingGeometry",
        definition=(
            "True only when the drawn walking surface has no gap at any route sample, every "
            "building exterior ring edge has drawn geometry within 0.05 m of its midpoint at 1 m "
            "above the support, every drawn component reaches the walking surface through a chain "
            "of contacts, and no drawn triangle lies inside a building volume."
        ),
        evidence_kind="mechanical",
        measurement="drawn-geometry-integrity/v1",
        decided_by=(
            "routeSupportGapSamples",
            "ringEdgesWithoutDrawnFacade",
            "componentsDetachedFromSupport",
            "trianglesInsideBuildings",
        ),
        predecessor_spellings=(
            "noFloatingOrCutGeometry",
            "noCutOrFloatingGeometry",
            "noLargeCutsOrFloatingGeometry",
        ),
    ),
    GateKey(
        spelling="usefulEyeLevelMovement",
        definition=(
            "True only when key events delivered to the product's own handlers, with no position "
            "written by the harness, carried the player at least 120 m along the route heading "
            "with at most 0.34 m of lateral deviation and no recovery event, and every route "
            "sample of the live per-frame trace had drawn walking surface beneath it and stood "
            "1.62 m, within 0.05 m, above it, where the product's navigation support and the drawn "
            "support agree within 0.05 m."
        ),
        evidence_kind="mechanical",
        measurement="product-driven-route-trace/v1",
        decided_by=(
            "walkedDisplacementMm",
            "maxLateralDeviationMm",
            "recoveryEvents",
            "harnessPositionWrites",
            "traceSamples",
            "routeSupportGapSamples",
            "maxEyeHeightErrorMm",
            "maxSupportResampleDeltaMm",
        ),
        predecessor_spellings=("eyeLevelMovement", "verifiedEyeLevelMovement"),
    ),
    GateKey(
        spelling="completeCapsuleClearanceVerification",
        definition=(
            "True only when, at every route sample, a vertical capsule of radius 0.34 m and total "
            "height 1.9 m standing on the drawn walking surface keeps at least 0.34 m from every "
            "drawn triangle that rises more than 0.18 m above that surface and lies outside every "
            "building exterior ring with at least 0.34 m to its nearest edge, with no sample "
            "skipped."
        ),
        evidence_kind="mechanical",
        measurement="capsule-clearance/v1",
        decided_by=(
            "capsuleSamples",
            "capsuleSamplesChecked",
            "capsuleTriangleContactSamples",
            "capsuleRingContactSamples",
        ),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="practicalBrowserBudget",
        definition=(
            "True only when the environment's transferred bytes, the drawn triangles, the "
            "environment's decoded texture bytes and the run's maximum per-frame draw calls are "
            "each no greater than Melbourne's envelope of 28,247,006 bytes, 227,173 triangles, "
            "167,772,160 bytes and 87 draw calls, and the run recorded no GPU error and no "
            "uncaught page exception or unhandled rejection; frame time, low-percentile frame "
            "rate and heap are reported beside Melbourne's and do not decide the key, because "
            "they vary between runs of one build."
        ),
        evidence_kind="mechanical",
        measurement="browser-envelope/v1",
        decided_by=(
            "environmentTransferredBytes",
            "drawnTriangles",
            "environmentDecodedTextureBytes",
            "maxDrawCalls",
            "gpuErrors",
            "pageErrors",
        ),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="companionPresent",
        definition=(
            "True only when, at each of the three captures, the product's Companion presence "
            "element is connected, ready, marked shown and laid out with a nonzero box inside the "
            "viewport, and its encounter surface is connected and open."
        ),
        evidence_kind="mechanical",
        measurement="live-dom-companion/v1",
        decided_by=("captures", "capturesWithCompanionShown"),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="reticlePresent",
        definition=(
            "True only when, at each of the three captures, the product's reticle element is "
            "connected, displayed with nonzero opacity and a nonzero box, and centred on the "
            "viewport within 1 px."
        ),
        evidence_kind="mechanical",
        measurement="live-dom-reticle/v1",
        decided_by=("captures", "capturesWithReticleCentred"),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="authenticatedShellAndAuthoredHandlersPreserved",
        definition=(
            "True only when every capture was taken in the product's own shell document with a "
            "mounted world and no credential gate, empty-world or error surface, every listener on "
            "the window, the document and the world canvas comes from the product's own modules, "
            "the product's own keyboard and pointer listeners carried every interaction the "
            "harness made, and no page or handler was substituted. A key press counts as carried "
            "when the state its product handler controls changes as that handler defines it: the "
            "Companion opens, the Companion closes, or the player moves. A click counts as carried "
            "when it lands on the world canvas, whose listeners are all the product's own, and the "
            "canvas then holds keyboard focus. As the retained Melbourne record used it, the key "
            "does not by itself assert a bearer credential, so every record states its "
            "authentication condition in a separate field."
        ),
        evidence_kind="mechanical",
        measurement="product-shell-and-listeners/v1",
        decided_by=(
            "captures",
            "capturesInProductShell",
            "foreignListeners",
            "productWindowKeydownListeners",
            "interactionsNotCarriedByProduct",
            "substitutedPages",
        ),
        predecessor_spellings=(),
    ),
)

CANONICAL_SPELLINGS: Final[tuple[str, ...]] = tuple(item.spelling for item in CANONICAL_KEYS)


class UnknownGateKey(KeyError):
    """A spelling this module does not list. Never passed through, never guessed."""


def _resolution_table() -> Mapping[str, str]:
    """Every spelling that resolves, built once, refusing any spelling claimed twice.

    Raising at import is deliberate: an ambiguous table is a vocabulary that means two things,
    and a module that cannot be imported is louder than a test that nobody runs.
    """
    table: dict[str, str] = {}
    for item in CANONICAL_KEYS:
        for spelling in (item.spelling, *item.predecessor_spellings):
            claimed = table.get(spelling)
            if claimed is not None and claimed != item.spelling:
                raise RuntimeError(
                    f"gate key spelling {spelling!r} resolves to both {claimed!r} and "
                    f"{item.spelling!r}"
                )
            table[spelling] = item.spelling
    return MappingProxyType(table)


_RESOLVE: Final = _resolution_table()
_BY_SPELLING: Final = MappingProxyType({item.spelling: item for item in CANONICAL_KEYS})


def resolve(spelling: str) -> str:
    """The canonical spelling ``spelling`` resolves to, or :class:`UnknownGateKey`."""
    canonical = _RESOLVE.get(spelling)
    if canonical is None:
        raise UnknownGateKey(
            f"{spelling!r} is not a hard-pass key spelling this gate reconciles. Add it to "
            "exulanica/evaluation/gate_keys.py through a new reconciliation record, or use one of "
            f"{', '.join(CANONICAL_SPELLINGS)}."
        )
    return canonical


def key(spelling: str) -> GateKey:
    """The canonical key a spelling resolves to."""
    return _BY_SPELLING[resolve(spelling)]


@dataclass(frozen=True, slots=True)
class RetainedRecord:
    """A retained rejection record, and the spelling it used for each key it scored."""

    label: str
    path: str
    record_sha256: str
    brief_path: str
    #: Canonical spelling to the spelling this record used. A key it did not score is absent.
    spellings: Mapping[str, str]


RETAINED_RECORDS: Final[tuple[RetainedRecord, ...]] = (
    RetainedRecord(
        label="helsinki-visual-feasibility",
        path="docs/evaluation/2026-09-12-helsinki-visual-feasibility.json",
        record_sha256="caf3c54cbd14cc7be35702b4b0abb583d3db8f821628a6e6312d02b84758087a",
        brief_path="docs/briefs/2026-09-12-helsinki-visual-feasibility.md",
        spellings=MappingProxyType(
            {
                "continuousTexturedStreetAndFacades": "continuousTexturedGround",
                "readsAsInhabitedStreet": "recognizableUrbanStreet",
                "noCutsOrFloatingGeometry": "noFloatingOrCutGeometry",
                "usefulEyeLevelMovement": "eyeLevelMovement",
                "companionPresent": "companionPresent",
                "reticlePresent": "reticlePresent",
            }
        ),
    ),
    RetainedRecord(
        label="helsinki-terminal-lod-successor",
        path="docs/evaluation/2026-09-12-helsinki-terminal-lod-successor.json",
        record_sha256="6cc00994c74ddf976c1bd3899dd637fdea4f4acf9e1b4e7605ea63426dd26c85",
        brief_path="docs/briefs/2026-09-12-helsinki-terminal-lod-successor.md",
        spellings=MappingProxyType(
            {
                "continuousTexturedStreetAndFacades": "continuousTexturedStreet",
                "readsAsInhabitedStreet": "recognizableUrbanScene",
                "noCutsOrFloatingGeometry": "noCutOrFloatingGeometry",
                "usefulEyeLevelMovement": "verifiedEyeLevelMovement",
                "companionPresent": "companionPresent",
                "reticlePresent": "reticlePresent",
                "authenticatedShellAndAuthoredHandlersPreserved": (
                    "authenticatedShellAndAuthoredHandlersPreserved"
                ),
            }
        ),
    ),
    RetainedRecord(
        label="melbourne-c4-29-visual-feasibility",
        path="docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json",
        record_sha256="97b66da014db8457b6ef60e31ffea84eb3e3c37c821b019862bf2838f7bc8206",
        brief_path="docs/briefs/2026-09-12-melbourne-c4-29-visual-feasibility.md",
        spellings=MappingProxyType(
            {
                "continuousTexturedStreetAndFacades": "continuousSourceTexturedStreetAndFacades",
                "readsAsInhabitedStreet": "recognizableMelbourneUrbanScene",
                "noCutsOrFloatingGeometry": "noLargeCutsOrFloatingGeometry",
                "usefulEyeLevelMovement": "usefulEyeLevelMovement",
                "completeCapsuleClearanceVerification": "completeCapsuleClearanceVerification",
                "practicalBrowserBudget": "practicalBrowserBudget",
                "companionPresent": "companionPresent",
                "reticlePresent": "reticlePresent",
                "authenticatedShellAndAuthoredHandlersPreserved": (
                    "authenticatedShellAndAuthoredHandlersPreserved"
                ),
            }
        ),
    ),
)
