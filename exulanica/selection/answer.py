"""The answer object, the validator that refuses it, and the answer that exists regardless.

``architecture-overview.md`` 5.3 makes answers structured rather than prose: "per-clause text, a
clause type in ``historical | uncertain | meta``, citation tokens, and value references. Prose is
rendered client side from the structure."

Three enforcement mechanisms, "none of which depends on the model behaving":

1. **Tokens are unforgeable and packet-scoped.** A citation that does not resolve is a lookup
   failure, not a judgement call.
2. **No digit sequence may appear in clause text unless a value reference covers it.** A
   syntactic check on the output string, not a semantic one. It kills the highest-damage
   hallucination class in a memory product: a confidently invented date, count or duration.
3. **On a second failure the model output is discarded entirely** and a deterministic answer is
   rendered from the query result and its citations.

Point 3 is what makes 1 and 2 safe to enforce strictly, and it is the reason this module ends
with a renderer rather than an exception: "rejecting model output has a defined, useful outcome,
so the validator has no incentive to be lenient." A correct, cited answer exists at zero model
compliance.

**Abstention is an answer, not a failure.** When the packet is empty the composer is never
called. Guessing from an empty packet is the one thing a memory product must not do, and the
cheapest way to guarantee it is to have no code path that could.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from exulanica.selection.packet import EvidencePacket

__all__ = [
    "MAX_CLAUSES",
    "Abstention",
    "Answer",
    "AnswerClause",
    "AnswerRejected",
    "ClauseType",
    "abstain",
    "render_deterministic_answer",
    "validate_answer",
]

MAX_CLAUSES: Final = 12

#: Any run of digits. Deliberately crude: "2019", "3", "1st" and "10:00" all match, and every
#: one of them is a number a model could have invented. A cleverer pattern would be a place for
#: a hallucination to hide.
_DIGITS: Final = re.compile(r"\d+")


class ClauseType(StrEnum):
    """What kind of thing a clause is claiming, which decides what it must carry."""

    #: A statement about the user's past. Must cite. This is the product's promise.
    HISTORICAL = "historical"
    #: A hedge, a possibility, an explicitly unconfirmed reading. May cite and need not.
    UNCERTAIN = "uncertain"
    #: A statement about the system rather than the world: what was searched, what was found,
    #: what is missing. Needs no citation, and is still subject to the digit rule.
    META = "meta"


class Abstention(StrEnum):
    """Why there is no answer. Three codes, scored separately and never merged.

    ``evaluation-methodology.md`` M3 is explicit about why: "Score
    ``UNANSWERABLE_NOT_CAPTURED`` ('I have no photograph of that') separately from
    ``UNANSWERABLE_AMBIGUOUS`` (correct response is a clarifying question). **Merging them lets
    a system that always says 'I don't know' score perfectly.**"

    The third is specific to this corpus: "Add a third reason code,
    ``UNANSWERABLE_NOT_IN_MODALITY``, for questions whose answer would require audio, speech, or
    continuous time (what was said, who spoke, how long, what happened between two photographs)
    ... Scoring them separately prevents the corpus's modality gap from being laundered into a
    general abstention score."

    A code is carried on the abstention rather than inferred from the text afterwards, because
    inferring it is exactly the laundering the methodology forbids.
    """

    #: Nothing in the library matches. "I have no photograph of that."
    NOT_CAPTURED = "UNANSWERABLE_NOT_CAPTURED"
    #: The question has more than one reading and the right response is to ask which.
    AMBIGUOUS = "UNANSWERABLE_AMBIGUOUS"
    #: The answer would need audio, speech or continuous time, none of which this corpus has.
    NOT_IN_MODALITY = "UNANSWERABLE_NOT_IN_MODALITY"


class AnswerClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=600)]
    type: ClauseType
    citations: Annotated[list[str], Field(max_length=8)] = Field(
        default_factory=list,
        description="Evidence tokens from the packet. Anything else is a lookup failure.",
    )
    value_refs: Annotated[list[str], Field(max_length=8)] = Field(
        default_factory=list,
        description="Value reference keys covering every digit sequence in `text`.",
    )


class Answer(BaseModel):
    """What the composer returns. Never a string."""

    model_config = ConfigDict(extra="forbid")

    clauses: Annotated[list[AnswerClause], Field(min_length=1, max_length=MAX_CLAUSES)]


@dataclass(frozen=True, slots=True)
class AnswerRejected(Exception):
    """Why an answer was refused, in the words a repair prompt can act on."""

    reasons: tuple[str, ...]

    def __str__(self) -> str:
        return "; ".join(self.reasons)


def validate_answer(answer: Answer, packet: EvidencePacket) -> Answer:
    """Refuse anything the packet does not support. Returns the answer unchanged, or raises.

    Every check is mechanical. None of them asks whether a clause is true, because that is not
    a question a validator can answer; they ask whether it is *supported*, which is.
    """
    reasons: list[str] = []
    for ordinal, clause in enumerate(answer.clauses):
        where = f"clause {ordinal}"

        for token in clause.citations:
            if packet.resolve(token) is None:
                # Not "a wrong citation". The token space is per-request and random, so this is
                # a reference to something that does not exist.
                reasons.append(f"{where} cites {token!r}, which is not in the packet")

        if clause.type is ClauseType.HISTORICAL and not clause.citations:
            reasons.append(
                f"{where} is a historical claim with no citation. Every statement about the "
                "user's past resolves to the original source or it is not made."
            )

        covered: set[str] = set()
        for key in clause.value_refs:
            value = packet.value(key)
            if value is None:
                reasons.append(f"{where} references value {key!r}, which the packet does not have")
            else:
                # **Whole digit runs, not substrings, and the difference was measured.**
                #
                # This used to ask whether the clause's digits appeared anywhere inside the
                # referenced text. A packet over any dated library carries a `date_N` reference
                # like "2026-05-20", and substring containment made every single digit 0 to 9
                # free, along with "20", "26", "05", "202" and "0-0". A model could state an
                # invented count, ordinal or year and pass, which is the "confidently invented
                # date, count or duration" this rule exists to stop.
                #
                # Splitting the reference into its own digit runs keeps what the rule is for and
                # drops what it never meant. Writing "2026" from the date "2026-05-20" is a
                # legitimate rendering of a value the query produced; writing "20 photographs"
                # from it is not, and no longer passes.
                covered.update(_DIGITS.findall(value.text))

        for digits in _DIGITS.findall(clause.text):
            if digits not in covered:
                reasons.append(
                    f"{where} contains the number {digits!r} with no value reference covering "
                    "it. A number the query did not produce is a number the model invented."
                )
    if reasons:
        raise AnswerRejected(tuple(reasons))
    return answer


def abstain(
    packet: EvidencePacket, reason: Abstention = Abstention.NOT_CAPTURED
) -> tuple[Answer, Abstention]:
    """The answer when there is nothing to answer from, and the code it is scored under.

    Two different silences, said differently, because they mean different things to a user. An
    empty packet means the Selection matched nothing. A packet marked not citable means the
    Selection matched things that are guesses, and a guess is not something this product will
    assert.

    Every clause here is ``meta``. That is not a formality: M3 scores a false answer as "a
    **historical factual claim** emitted on an unanswerable question", so an abstention that
    emitted a historical clause would be the failure it exists to avoid.
    """
    if not packet.citable:
        return (
            Answer(
                clauses=[
                    AnswerClause(
                        text=(
                            "That selection includes matches that have not been confirmed, so "
                            "there is nothing here I can state as fact. Confirm them, or ask "
                            "again for confirmed matches only."
                        ),
                        type=ClauseType.META,
                    )
                ]
            ),
            Abstention.AMBIGUOUS,
        )
    return (
        Answer(
            clauses=[
                AnswerClause(
                    text=(
                        "I have no evidence for that. Nothing in your library matches, so there "
                        "is nothing I could cite."
                    ),
                    type=ClauseType.META,
                )
            ]
        ),
        reason,
    )


def render_deterministic_answer(packet: EvidencePacket) -> Answer:
    """The answer that exists at zero model compliance. A first-class output, not an error page.

    Counts come from value references and citations come from the packet, so this answer passes
    :func:`validate_answer` by construction. It is deliberately dull: it says what was found and
    points at it, which is the irreducible thing the product promises.
    """
    if packet.is_empty:
        return abstain(packet)[0]

    total = packet.value("capture_count")
    shown = packet.value("shown_count")
    assert total is not None and shown is not None

    clauses = [
        AnswerClause(
            text=f"{total.text} captures match, and I can show you {shown.text}.",
            type=ClauseType.META,
            value_refs=[total.key, shown.key],
        )
    ]
    by_capture: dict[str, list[str]] = {}
    for item in packet.items:
        by_capture.setdefault(str(item.capture_id), []).append(item.token)
    for tokens in list(by_capture.values())[: MAX_CLAUSES - 1]:
        clauses.append(
            AnswerClause(
                text="One of them is this photograph.",
                type=ClauseType.HISTORICAL,
                citations=tokens[:8],
            )
        )
    return Answer(clauses=clauses)
