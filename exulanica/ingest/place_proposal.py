"""Whether a place the vision role proposed may be written: a versioned rule, applied in code.

The vision role proposes; this module decides. A place proposal is the only producer of a
place-class memory entity, so what it lets through is what a person is later asked to confirm,
and a place that is not really in the photograph is the failure a person is least able to notice.
Everything here is deterministic and makes no model call: the caller supplies the observation's
own words and, when it is needed, the answer to one separate question, and this module returns
the proposal to write or a named refusal.

Three measurements on synthetic photographs shaped it (docs/model-and-service-selection.md, the
place paragraph, and the records it links):

*   An observation prompt that asks for the proposal directly proposed every legible place name,
    and also the visible word of boards that a tree covered.
*   Asked inside the observation, as an instruction or as a schema field answered first, the
    vision model judged a board with a tree in front of it whole. Asked on its own whether the
    most prominent sign is whole or partly hidden, it answered all 24 boards of a probe correctly.
*   Asked on its own as a second call, it caught every partly hidden board of a held-out split,
    but one label the observation had already written, "Ashcombe (partial)", carried a word that
    no sign in the frame shows.

So a proposal passes two checks, each of which can only remove:

1.  **The label rule.** The label keeps only the words the observation itself transcribed from
    text it marked as signage in the same photograph. Words are compared case-folded, with
    apostrophes and every other character that is not a letter or a digit ignored, and the label
    that is written is spelled as the transcription spells it, never in the folded form. A label
    left with no word refuses the proposal. This holds whatever the model writes: it removes a
    descriptive word such as "partial" and a completed hidden word alike, and it removes a place
    named from a landmark or from world knowledge, because no sign in the frame reads it.
2.  **The sign judgement.** The completeness question the probe measured, asked in a separate
    call only when a label survives. The proposal is refused when the sign is judged partly
    hidden or absent, when the judgement came from a model this policy has not admitted, when the
    call failed, and when the sign judged is not the one carrying the name: the question asks
    about the most prominent sign, so every word the label keeps must be among the words the
    judgement read on it.

What this does not do. It cannot tell a place name from any other text on a sign: a product or a
slogan on a board passes both checks if the observation proposes it, and the observation prompt is
the only guard there. It proposes nothing from a landmark with no legible name. A name split
across two signs, or read on a sign less prominent than another sign in the frame, is refused.
And the answer to the completeness question is a model's judgement, not an observation: a board
judged whole that is not will pass, which is why the refusals above are measured on a held-out
split rather than assumed.

The policy is a data object with a version and a digest. The digest is part of the vision stage's
reprocessing key, through ``exulanica.ingest.vision.prompt_digest``, and every stored decision
records it, so a stored decision can always be traced to the exact rule that made it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.canonical import canonical_json

__all__ = [
    "PLACE_PROPOSAL_POLICY",
    "SIGN_QUESTION",
    "SIGN_SCHEMA",
    "SIGN_SCHEMA_NAME",
    "SIGN_SYSTEM",
    "AdmittedJudge",
    "LabelReading",
    "Outcome",
    "PlaceDecision",
    "PlaceProposalPolicy",
    "SignJudgement",
    "decide",
    "folded_words",
    "read_label",
]


# ---------------------------------------------------------------------------------------
# The outcomes. Each is a named constant, and this is the only place any of them is stated.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened to one proposal. ``code`` is what a stored decision records."""

    code: str
    writes: bool
    meaning: str


WRITTEN: Final = Outcome(
    "written", True, "the proposal passed both checks and its label is written"
)
NOTHING_PROPOSED: Final = Outcome("nothing_proposed", False, "the observation proposed no place")
NO_WORD_READ_FROM_A_SIGN: Final = Outcome(
    "no_word_read_from_a_sign",
    False,
    "no word of the label is among the words the observation transcribed as signage",
)
SIGN_CHECK_FAILED: Final = Outcome(
    "sign_check_failed", False, "the call asking whether the sign is whole did not return"
)
SIGN_JUDGE_NOT_ADMITTED: Final = Outcome(
    "sign_judge_not_admitted",
    False,
    "the sign was judged by a model whose judgement this policy has not admitted",
)
NO_SIGN_SEEN: Final = Outcome(
    "no_sign_seen", False, "the judgement found no sign with writing on it"
)
SIGN_PARTLY_HIDDEN: Final = Outcome(
    "sign_partly_hidden",
    False,
    "the judgement found the sign partly hidden or cut off by the edge of the photograph",
)
UNKNOWN_COMPLETENESS_ANSWER: Final = Outcome(
    "unknown_completeness_answer",
    False,
    "the judgement gave a completeness answer this policy has no meaning for",
)
JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME: Final = Outcome(
    "judged_sign_does_not_carry_the_name",
    False,
    "a word of the label is not among the words the judgement read on the sign it judged",
)

OUTCOMES: Final[tuple[Outcome, ...]] = (
    WRITTEN,
    NOTHING_PROPOSED,
    NO_WORD_READ_FROM_A_SIGN,
    SIGN_CHECK_FAILED,
    SIGN_JUDGE_NOT_ADMITTED,
    NO_SIGN_SEEN,
    SIGN_PARTLY_HIDDEN,
    UNKNOWN_COMPLETENESS_ANSWER,
    JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME,
)


# ---------------------------------------------------------------------------------------
# The sign question. Word for word the probe's, which is what makes its measurement apply.
# ---------------------------------------------------------------------------------------

#: The probe's system text, question and schema, unchanged
#: (docs/evaluation/2026-09-22-sign-completeness-probe-preregistration.json). Only the schema's
#: name is the product's own. Asked without the observation prompt's nonce, because the probe
#: asked without one and adding it would be an unmeasured question. An instruction painted on a
#: sign can at worst turn a refusal into an acceptance of a label the label rule already bounded
#: to words read from a sign; it cannot add a word.
SIGN_SYSTEM: Final = (
    "You look at one photograph and answer one question about the most prominent sign with "
    "writing on it. Report only what is visible. Do not guess at anything you cannot see. "
    "Reply with one JSON object matching the schema and nothing else."
)
SIGN_QUESTION: Final = (
    "Is there a sign with writing on it in this photograph? If there is, is the whole sign "
    "visible, or is part of it hidden behind something or cut off by the edge of the "
    "photograph? Transcribe the words you can read."
)
SIGN_SCHEMA_NAME: Final = "exulanica_sign_completeness_v1"
SIGN_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "sign_present": {"type": "boolean"},
        "completeness": {"type": "string", "enum": ["whole", "partly_hidden", "no_sign"]},
        "readable_text": {"type": "string"},
    },
    "required": ["sign_present", "completeness", "readable_text"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------------------
# The policy object.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdmittedJudge:
    """A model whose answer to the sign question is trusted, and the record that measured it."""

    model_id: str
    evidence: str


@dataclass(frozen=True, slots=True)
class PlaceProposalPolicy:
    """The rule, as data. Its digest keys reprocessing and is stored with every decision."""

    policy_id: str
    version: int
    outcomes: tuple[Outcome, ...]
    #: What each answer to the completeness question means. An answer mapped to ``None`` refuses
    #: nothing by itself; an answer this table does not name is refused as unknown.
    completeness: Mapping[str, Outcome | None]
    #: Models whose sign judgement is admitted. Any other model's answer, including the vision
    #: role's fallback when it answers, is refused by name until a measurement admits it here.
    admitted_judges: tuple[AdmittedJudge, ...]
    word_pattern: str
    word_folding: str
    label_source: str
    pairing: str
    sign_system: str = SIGN_SYSTEM
    sign_question: str = SIGN_QUESTION
    sign_schema_name: str = SIGN_SCHEMA_NAME
    sign_schema: Mapping[str, Any] = field(default_factory=lambda: SIGN_SCHEMA)

    def __post_init__(self) -> None:
        codes = [outcome.code for outcome in self.outcomes]
        if len(set(codes)) != len(codes):
            raise ValueError(f"outcome codes must be unique: {codes}")
        stray = [
            outcome
            for outcome in self.completeness.values()
            if outcome is not None and outcome not in self.outcomes
        ]
        if stray:
            raise ValueError(f"completeness answers map to outcomes the policy lacks: {stray}")

    def admits(self, model_id: str) -> bool:
        return any(judge.model_id == model_id for judge in self.admitted_judges)

    def as_record(self) -> dict[str, Any]:
        """Everything the rule depends on, in canonical form."""
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "outcomes": [
                {"code": o.code, "writes": o.writes, "meaning": o.meaning} for o in self.outcomes
            ],
            "completeness": {
                answer: (outcome.code if outcome is not None else None)
                for answer, outcome in sorted(self.completeness.items())
            },
            "admitted_judges": [
                {"model_id": judge.model_id, "evidence": judge.evidence}
                for judge in self.admitted_judges
            ],
            "word_pattern": self.word_pattern,
            "word_folding": self.word_folding,
            "label_source": self.label_source,
            "pairing": self.pairing,
            "sign_system": self.sign_system,
            "sign_question": self.sign_question,
            "sign_schema_name": self.sign_schema_name,
            "sign_schema": dict(self.sign_schema),
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_record())).hexdigest()


#: A word is a run of letters or digits, which may carry an apostrophe inside it ("Mary's").
_WORD: Final = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*")

PLACE_PROPOSAL_POLICY: Final = PlaceProposalPolicy(
    policy_id="place-proposal",
    version=1,
    outcomes=OUTCOMES,
    completeness={
        "whole": None,
        "partly_hidden": SIGN_PARTLY_HIDDEN,
        "no_sign": NO_SIGN_SEEN,
    },
    admitted_judges=(
        # 24 of 24 boards judged correctly when asked alone, the vision role's primary pinned
        # with its fallback off.
        AdmittedJudge(
            model_id="MiniMaxAI/MiniMax-M3",
            evidence="docs/evaluation/2026-09-22-sign-completeness-probe-outcome.json",
        ),
    ),
    word_pattern=_WORD.pattern,
    word_folding="Unicode NFKC, then casefold, then apostrophes removed",
    label_source=(
        "the proposal's label keeps each word found among the words of the observation's "
        "legible_text entries marked is_signage; the written label is the transcription's own "
        "text: the exact span of one transcription when the kept words are consecutive words of "
        "it in the label's order, otherwise the transcribed spellings joined by single spaces"
    ),
    pairing=(
        "every folded word the label keeps is among the folded words of the judgement's "
        "readable_text"
    ),
)


# ---------------------------------------------------------------------------------------
# Words.
# ---------------------------------------------------------------------------------------


def _fold(word: str) -> str:
    return unicodedata.normalize("NFKC", word).casefold().replace("'", "").replace("\u2019", "")


def folded_words(text: str | None) -> tuple[str, ...]:
    """The words of ``text``, folded as the policy compares them, in order."""
    return tuple(_fold(match.group()) for match in _WORD.finditer(text or ""))


# ---------------------------------------------------------------------------------------
# The label rule.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabelReading:
    """The label rule's result for one proposal, before any sign judgement.

    ``label`` is the text to write if the proposal survives, spelled as the transcription spells
    it, or ``None`` when no word survived. ``kept`` holds the folded words the pairing check needs.
    """

    proposed: str
    label: str | None
    kept: tuple[str, ...]
    dropped: tuple[str, ...]


def read_label(proposed: str, signs: Sequence[str]) -> LabelReading:
    """Keep the words of ``proposed`` that the observation transcribed as signage.

    ``signs`` is the text of every legible_text entry the observation marked as signage, in the
    order it listed them. The written label comes from those transcriptions, never from the
    proposal's own spelling: the exact span of one transcription when the kept words are
    consecutive words of it in the label's order, which keeps its casing, spacing and inner
    punctuation ("ST. MARY'S"), and otherwise each kept word as a transcription first spells it,
    joined by single spaces.
    """
    tokens = [list(_WORD.finditer(sign)) for sign in signs]
    spelling: dict[str, str] = {}
    for matches in tokens:
        for match in matches:
            spelling.setdefault(_fold(match.group()), match.group())

    kept: list[str] = []
    dropped: list[str] = []
    for match in _WORD.finditer(proposed):
        word = _fold(match.group())
        if word in spelling:
            kept.append(word)
        else:
            dropped.append(match.group())
    if not kept:
        return LabelReading(proposed=proposed, label=None, kept=(), dropped=tuple(dropped))

    for sign, matches in zip(signs, tokens, strict=True):
        folded = [_fold(match.group()) for match in matches]
        for start in range(len(folded) - len(kept) + 1):
            if folded[start : start + len(kept)] == kept:
                first, last = matches[start], matches[start + len(kept) - 1]
                return LabelReading(
                    proposed=proposed,
                    label=sign[first.start() : last.end()],
                    kept=tuple(kept),
                    dropped=tuple(dropped),
                )
    return LabelReading(
        proposed=proposed,
        label=" ".join(spelling[word] for word in kept),
        kept=tuple(kept),
        dropped=tuple(dropped),
    )


# ---------------------------------------------------------------------------------------
# The decision.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignJudgement:
    """The answer to the sign question, or why there is none.

    ``answer`` is the model's reply verbatim, already validated against ``SIGN_SCHEMA`` by the
    client. ``model_id`` names the model that answered, which is what admission is judged on.
    """

    answer: Mapping[str, Any] | None
    model_id: str | None
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class PlaceDecision:
    """The outcome for one proposal, and the label to write when it is written."""

    outcome: Outcome
    label: str | None
    reading: LabelReading | None
    judgement: SignJudgement | None
    policy: PlaceProposalPolicy

    @property
    def writes(self) -> bool:
        return self.outcome.writes

    def record(self) -> dict[str, Any]:
        """What a stored observation keeps about this decision, beside the model's own words."""
        return {
            "policy": {
                "policy_id": self.policy.policy_id,
                "version": self.policy.version,
                "sha256": self.policy.digest(),
            },
            "outcome": self.outcome.code,
            "proposed_label": self.reading.proposed if self.reading else None,
            "written_label": self.label,
            "dropped_words": list(self.reading.dropped) if self.reading else [],
            "sign_judgement": (
                dict(self.judgement.answer)
                if self.judgement and self.judgement.answer is not None
                else None
            ),
            "sign_judge": self.judgement.model_id if self.judgement else None,
            "sign_check_failure": self.judgement.failure if self.judgement else None,
        }


def decide(
    reading: LabelReading | None,
    judgement: SignJudgement | None,
    policy: PlaceProposalPolicy = PLACE_PROPOSAL_POLICY,
) -> PlaceDecision:
    """The proposal to write, or the named reason there is none.

    ``reading`` is ``None`` when the observation proposed nothing. ``judgement`` must be given
    whenever the label rule kept a word, because the sign question is asked exactly then; a caller
    that skips it is refused rather than trusted.
    """

    def refuse(outcome: Outcome) -> PlaceDecision:
        return PlaceDecision(outcome, None, reading, judgement, policy)

    if reading is None:
        return refuse(NOTHING_PROPOSED)
    if reading.label is None:
        return refuse(NO_WORD_READ_FROM_A_SIGN)
    if judgement is None or judgement.failure is not None or judgement.answer is None:
        return refuse(SIGN_CHECK_FAILED)
    if judgement.model_id is None or not policy.admits(judgement.model_id):
        return refuse(SIGN_JUDGE_NOT_ADMITTED)
    answer = judgement.answer
    if answer.get("sign_present") is not True:
        return refuse(NO_SIGN_SEEN)
    completeness = answer.get("completeness")
    if completeness not in policy.completeness:
        return refuse(UNKNOWN_COMPLETENESS_ANSWER)
    refusal = policy.completeness[completeness]
    if refusal is not None:
        return refuse(refusal)
    read_on_the_sign = set(folded_words(answer.get("readable_text")))
    if not set(reading.kept) <= read_on_the_sign:
        return refuse(JUDGED_SIGN_DOES_NOT_CARRY_THE_NAME)
    return PlaceDecision(WRITTEN, reading.label, reading, judgement, policy)
