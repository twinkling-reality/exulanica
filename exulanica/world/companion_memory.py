"""Durable Companion memory: what was asked, what was answered, and what was corrected.

The browser already models all of this. ``web/packages/companion-runtime/src/memory.ts`` holds
the Not sure and Skip cooldown windows, the wrong-question signal and a transcript of every turn,
and every field of it is built at mount and dropped at unload. Migration 0043 gives that model a
place to live between page loads; this module is the only way in and out of it.

**Conversation text lives here and may never become an interaction-policy input.**
``WorldInteractionPolicyRepository._validate_provenance`` refuses a proposal whose input carries
any of ``{"conversation", "messages", "raw_utterance", "transcript", "prompt_text"}``, and 0021
says the same in its own header. Nothing in this module builds an ``InteractionProposal``, imports
one, or returns a value shaped to be passed to one, and that is a structural property rather than
a promise: the import list below names no interaction type, so a future call site that wanted to
launder a question into a capability decision would have to add the import first, in a diff a
reviewer can see. ``tests/test_companion_memory_policy_boundary.py`` holds it.

The two senses of "policy" collide here and the collision is worth naming once. 4.4's "policy over
the entity graph snapshot plus the conversation transcript" is the TURN GENERATOR: per session,
in the browser, producing a question. The plane the exclusion protects is the durable capability
policy: what this system is PERMITTED to do. A question somebody typed is evidence about them; a
capability is a rule. The first may inform the next question and may never author the second.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import psycopg

from exulanica.errors import ExulanicaError, TombstonedError

__all__ = [
    "AnswerCitation",
    "AnswerOrigin",
    "CompanionAnswer",
    "CompanionEscape",
    "CompanionMemoryError",
    "CompanionMemoryRepository",
    "CompanionMemorySnapshot",
    "EscapeKind",
    "InvalidCompanionMemory",
    "MemoryStatus",
    "RecordedAnswer",
    "RecordedEscape",
    "UnknownCompanionMemory",
]

#: The recent read is bounded because it runs on every session open and its result is rendered.
#: An unbounded default would make a long-lived workspace's first paint proportional to its whole
#: conversational history, which is the cost `world_write.py` calls "permanent per-read".
DEFAULT_RECENT_LIMIT: Final = 50
MAX_RECENT_LIMIT: Final = 200

#: The four abstention codes, spelled as `POST /selection/ask` spells them. Carried through rather
#: than collapsed: `evaluation-methodology.md` M3 says merging them "lets a system that always says
#: 'I don't know' score perfectly".
ABSTENTIONS: Final = frozenset(
    {
        "UNANSWERABLE_NOT_CAPTURED",
        "UNANSWERABLE_AMBIGUOUS",
        "UNANSWERABLE_NOT_IN_MODALITY",
        "UNANSWERABLE_NOT_UNDERSTOOD",
    }
)


class CompanionMemoryError(ExulanicaError):
    """Base class for failures owned by durable Companion memory."""


class UnknownCompanionMemory(CompanionMemoryError):
    """A memory is absent, withdrawn, or belongs to another workspace or another person."""


class InvalidCompanionMemory(CompanionMemoryError):
    """A recorded answer, citation, or escape is not in the shape this plane accepts."""


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class AnswerOrigin(StrEnum):
    ASKED = "asked"
    CORRECTION = "correction"


class EscapeKind(StrEnum):
    """The four escapes of interaction-model.md 4.3, spelled as the runtime spells them."""

    NOT_SURE = "not_sure"
    SKIP = "skip"
    LATER = "later"
    WRONG_QUESTION = "wrong_question"


@dataclass(frozen=True, slots=True)
class AnswerCitation:
    """One photograph an answer quoted, in reading order.

    The span rather than the citation token, because token namespaces are random per request:
    `companion-ask-api.ts` says a stored token "would silently resolve nothing", and a chip built
    from one would open nothing on the next page load. The capture is recorded beside it so a
    withdrawal is an indexed lookup rather than a join through the blob on every tombstone.
    """

    span_id: uuid.UUID
    capture_id: uuid.UUID
    ordinal: int


@dataclass(frozen=True, slots=True)
class CompanionAnswer:
    answer_id: uuid.UUID
    asked_at: dt.datetime
    question: str
    answer_text: str
    abstained: str | None
    deterministic: bool
    repaired: bool
    served_model: str | None
    planned_by: str | None
    prompt_version: str
    latency_ms: int
    origin: AnswerOrigin
    supersedes: uuid.UUID | None
    correction_note: str | None
    status: MemoryStatus
    citations: tuple[AnswerCitation, ...]


@dataclass(frozen=True, slots=True)
class CompanionEscape:
    escape_id: uuid.UUID
    taken_at: dt.datetime
    escape: EscapeKind
    intent: str
    entity_id: uuid.UUID | None
    turn_id: str


@dataclass(frozen=True, slots=True)
class RecordedAnswer:
    """What the browser hands back after an answer has rendered."""

    question: str
    answer_text: str
    abstained: str | None
    deterministic: bool
    repaired: bool
    served_model: str | None
    planned_by: str | None
    prompt_version: str
    latency_ms: int
    citations: tuple[AnswerCitation, ...]


@dataclass(frozen=True, slots=True)
class RecordedEscape:
    escape: EscapeKind
    intent: str
    entity_id: uuid.UUID | None
    turn_id: str


@dataclass(frozen=True, slots=True)
class CompanionMemorySnapshot:
    """Everything a session open needs, in one read."""

    answers: tuple[CompanionAnswer, ...]
    escapes: tuple[CompanionEscape, ...]


class CompanionMemoryRepository:
    """Append-only conversation memory for one person in one workspace.

    **The actor is a constructor argument rather than a per-method keyword, which is a deliberate
    deviation from the three world repositories.** Those take ``(connection, workspace_id)`` and
    accept ``actor=`` on the methods that record a human decision, because for them the actor is
    provenance on an otherwise workspace-wide object. Here the actor is the SCOPE: two people
    sharing a workspace have not had the same conversation, and row-level security scopes to the
    workspace and cannot see the actor at all, so ``and actor_id=%s`` in every statement is the
    only thing standing between one person's typed questions and the other's screen. A keyword a
    caller can omit is the wrong shape for the one clause that must never be omitted.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor_id = actor_id

    # -- reads ----------------------------------------------------------------------------

    def recent(self, *, limit: int = DEFAULT_RECENT_LIMIT) -> CompanionMemorySnapshot:
        """The active memory for this person, newest first.

        Superseded answers are absent because the correction replaced them and the correction is
        what stands; withdrawn answers are absent because a withdrawal is a deletion. Both are
        still rows, and that is the point of superseding rather than editing: the history is
        readable by anything that asks for it explicitly, and the default read is what the person
        would recognise as their memory.
        """
        if limit < 1 or limit > MAX_RECENT_LIMIT:
            raise InvalidCompanionMemory(
                f"recent limit must be between 1 and {MAX_RECENT_LIMIT}, not {limit}"
            )
        rows = self.connection.execute(
            "select * from companion_answer "
            "where workspace_id=%s and actor_id=%s and status='active' "
            "order by asked_at desc, answer_id desc limit %s",
            (self.workspace_id, self.actor_id, limit),
        ).fetchall()
        citations = self._citations_for(tuple(row["answer_id"] for row in rows))
        answers = tuple(
            _row_to_answer(row, citations.get(row["answer_id"], ())) for row in rows
        )
        escape_rows = self.connection.execute(
            "select * from companion_escape "
            "where workspace_id=%s and actor_id=%s "
            "order by taken_at desc, escape_id desc limit %s",
            (self.workspace_id, self.actor_id, limit),
        ).fetchall()
        return CompanionMemorySnapshot(
            answers=answers,
            escapes=tuple(_row_to_escape(row) for row in escape_rows),
        )

    def answer(self, answer_id: uuid.UUID) -> CompanionAnswer:
        """One answer, active or superseded, or raise.

        Withdrawn is absent rather than raising a distinct error, for the reason
        ``world_write.py`` gives about unknown and foreign ids: a surface that answered
        differently for "withdrawn" and "never existed" would let a reader learn that something
        used to be there.
        """
        row = self.connection.execute(
            "select * from companion_answer "
            "where workspace_id=%s and actor_id=%s and answer_id=%s and status<>'withdrawn'",
            (self.workspace_id, self.actor_id, answer_id),
        ).fetchone()
        if row is None:
            raise UnknownCompanionMemory(f"no companion memory {answer_id}")
        citations = self._citations_for((answer_id,))
        return _row_to_answer(row, citations.get(answer_id, ()))

    def _citations_for(
        self, answer_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[AnswerCitation, ...]]:
        """Every citation for a set of answers, in one query rather than one per answer."""
        if not answer_ids:
            return {}
        rows = self.connection.execute(
            "select * from companion_answer_citation "
            "where workspace_id=%s and answer_id = any(%s) order by answer_id, ordinal",
            (self.workspace_id, list(answer_ids)),
        ).fetchall()
        grouped: dict[uuid.UUID, list[AnswerCitation]] = {}
        for row in rows:
            grouped.setdefault(row["answer_id"], []).append(
                AnswerCitation(
                    span_id=row["span_id"],
                    capture_id=row["capture_id"],
                    ordinal=row["ordinal"],
                )
            )
        return {answer_id: tuple(items) for answer_id, items in grouped.items()}

    # -- writes ---------------------------------------------------------------------------

    def record_answer(self, recorded: RecordedAnswer) -> CompanionAnswer:
        """Store a question and the answer it received.

        One transaction, because the citations are what a withdrawal travels along: an answer
        committed without them would be a stored description of photographs that no deletion can
        reach, which is the exact failure 0043's header quotes from
        ``domain-and-evidence-model.md`` 6.4.
        """
        self._validate(recorded)
        try:
            row = self._insert_answer(recorded)
        # `psycopg.IntegrityError` rather than `errors.IntegrityConstraintViolation`, and the
        # difference is not cosmetic. The two SQLSTATE classes the citation guard raises,
        # 23000 and 23503, are SIBLINGS in psycopg's hierarchy rather than parent and child, so
        # catching the narrower one silently missed every `foreign_key_violation` and let it
        # reach the client as a 500.
        except psycopg.IntegrityError as exc:
            raise _refusal(exc) from exc
        return _row_to_answer(row, tuple(sorted(recorded.citations, key=_by_ordinal)))

    def _insert_answer(self, recorded: RecordedAnswer) -> Mapping[str, Any]:
        with self.connection.transaction():
            row = self.connection.execute(
                "insert into companion_answer "
                "(workspace_id,actor_id,question,answer_text,abstained,deterministic,repaired,"
                "served_model,planned_by,prompt_version,latency_ms,origin) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'asked') returning *",
                (
                    self.workspace_id,
                    self.actor_id,
                    recorded.question,
                    recorded.answer_text,
                    recorded.abstained,
                    recorded.deterministic,
                    recorded.repaired,
                    recorded.served_model,
                    recorded.planned_by,
                    recorded.prompt_version,
                    recorded.latency_ms,
                ),
            ).fetchone()
            assert row is not None
            self._insert_citations(row["answer_id"], recorded.citations)
        return row

    def record_escape(self, recorded: RecordedEscape) -> CompanionEscape:
        """Store an escape, which is what makes its cooldown outlive the page.

        4.3 and 5.5 both say the Companion may never speak "within 7 days of a Skip or 14 days of
        a Not sure on the same entity". A fourteen-day window held only in a tab has never once
        been enforced past a reload, and this row is what changes that.
        """
        if not recorded.intent.strip() or len(recorded.intent) > 64:
            raise InvalidCompanionMemory("an escape names an intent of 1 to 64 characters")
        if not recorded.turn_id.strip() or len(recorded.turn_id) > 128:
            raise InvalidCompanionMemory("an escape names a turn of 1 to 128 characters")
        with self.connection.transaction():
            row = self.connection.execute(
                "insert into companion_escape "
                "(workspace_id,actor_id,escape,intent,entity_id,turn_id) "
                "values (%s,%s,%s,%s,%s,%s) returning *",
                (
                    self.workspace_id,
                    self.actor_id,
                    recorded.escape.value,
                    recorded.intent,
                    recorded.entity_id,
                    recorded.turn_id,
                ),
            ).fetchone()
            assert row is not None
        return _row_to_escape(row)

    def correct(
        self,
        answer_id: uuid.UUID,
        *,
        answer_text: str,
        correction_note: str | None,
    ) -> CompanionAnswer:
        """Record the person's correction as a NEW answer that supersedes the old one.

        Never an UPDATE of the wrong text, and the reason is not tidiness. A correction is
        somebody telling the system it was wrong, which is the single most valuable row in this
        table; overwriting the wrong answer would destroy the evidence that it had ever been
        wrong, which is the one record the correction exists to create. 5.4: "Nothing is ever
        silently rewritten, including by the system's own later inferences."

        The correction inherits the superseded answer's citations verbatim. It is the same
        question about the same photographs, so it must be reachable by the same withdrawal; a
        correction with no citations would be a stored sentence about somebody's library that no
        deletion could reach, which is the whole failure this plane is built against.
        """
        if not answer_text.strip() or len(answer_text) > 8000:
            raise InvalidCompanionMemory("a correction carries 1 to 8000 characters of text")
        if correction_note is not None and len(correction_note) > 2000:
            raise InvalidCompanionMemory("a correction note is at most 2000 characters")
        with self.connection.transaction():
            target = self.connection.execute(
                "select * from companion_answer "
                "where workspace_id=%s and actor_id=%s and answer_id=%s for update",
                (self.workspace_id, self.actor_id, answer_id),
            ).fetchone()
            if target is None or target["status"] == MemoryStatus.WITHDRAWN:
                raise UnknownCompanionMemory(f"no companion memory {answer_id}")
            if target["status"] == MemoryStatus.SUPERSEDED:
                raise InvalidCompanionMemory(
                    f"companion memory {answer_id} was already corrected; correct the correction"
                )
            row = self.connection.execute(
                "insert into companion_answer "
                "(workspace_id,actor_id,question,answer_text,abstained,deterministic,repaired,"
                "served_model,planned_by,prompt_version,latency_ms,origin,supersedes,"
                "correction_note) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'correction',%s,%s) returning *",
                (
                    self.workspace_id,
                    self.actor_id,
                    target["question"],
                    answer_text,
                    # A corrected answer is not an abstention: the person supplied the content the
                    # system could not. Carrying the old code forward would file their sentence
                    # under "nothing in your library matches", which is a claim about their
                    # photographs made from a correction of the system.
                    None,
                    False,
                    False,
                    # No model wrote this one, and saying otherwise would attribute the person's
                    # own sentence to a model. The provenance line has a case for exactly this.
                    None,
                    target["planned_by"],
                    target["prompt_version"],
                    0,
                    answer_id,
                    correction_note,
                ),
            ).fetchone()
            assert row is not None
            self.connection.execute(
                "insert into companion_answer_citation "
                "(workspace_id,answer_id,ordinal,span_id,capture_id) "
                "select %s,%s,ordinal,span_id,capture_id from companion_answer_citation "
                "where workspace_id=%s and answer_id=%s",
                (self.workspace_id, row["answer_id"], self.workspace_id, answer_id),
            )
            self.connection.execute(
                "update companion_answer set status='superseded', superseded_at=now() "
                "where workspace_id=%s and answer_id=%s",
                (self.workspace_id, answer_id),
            )
        citations = self._citations_for((row["answer_id"],))
        return _row_to_answer(row, citations.get(row["answer_id"], ()))

    def withdraw(self, answer_id: uuid.UUID) -> None:
        """Delete one memory: withdraw it and its whole correction lineage.

        The lineage rather than the row, in both directions. A correction contains the subject of
        the answer it corrected and often quotes it; leaving the correction behind when the person
        deleted the memory would leave the thing they deleted on the screen inside its own
        replacement. Walking backwards matters for the same reason: the superseded original is
        still readable through ``answer`` and is still about the photographs they asked about.

        ``withdrawn_by`` stays NULL, which is what says a person did this to their own
        conversation rather than a tombstone reaching it. Migration 0043 keeps the two
        distinguishable on purpose.
        """
        with self.connection.transaction():
            found = self.connection.execute(
                "select 1 from companion_answer "
                "where workspace_id=%s and actor_id=%s and answer_id=%s and status<>'withdrawn'",
                (self.workspace_id, self.actor_id, answer_id),
            ).fetchone()
            if found is None:
                raise UnknownCompanionMemory(f"no companion memory {answer_id}")
            # A recursive walk rather than a loop in Python, so the whole lineage is withdrawn in
            # one statement and a chain cannot be half-deleted by a failure partway along it.
            self.connection.execute(
                "with recursive lineage(answer_id) as ("
                "  select answer_id from companion_answer"
                "   where workspace_id=%(ws)s and actor_id=%(actor)s and answer_id=%(seed)s"
                "  union"
                "  select a.answer_id from companion_answer a join lineage l"
                "    on a.workspace_id=%(ws)s"
                "   and (a.supersedes = l.answer_id or a.answer_id = ("
                "         select s.supersedes from companion_answer s"
                "          where s.workspace_id=%(ws)s and s.answer_id = l.answer_id))"
                ") update companion_answer set status='withdrawn', withdrawn_at=now() "
                "where workspace_id=%(ws)s and actor_id=%(actor)s "
                "and answer_id in (select answer_id from lineage) and status<>'withdrawn'",
                {"ws": self.workspace_id, "actor": self.actor_id, "seed": answer_id},
            )

    # -- internal validation and rows -----------------------------------------------------

    def _insert_citations(
        self, answer_id: uuid.UUID, citations: Sequence[AnswerCitation]
    ) -> None:
        for citation in sorted(citations, key=_by_ordinal):
            self.connection.execute(
                "insert into companion_answer_citation "
                "(workspace_id,answer_id,ordinal,span_id,capture_id) values (%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    answer_id,
                    citation.ordinal,
                    citation.span_id,
                    citation.capture_id,
                ),
            )

    @staticmethod
    def _validate(recorded: RecordedAnswer) -> None:
        if not recorded.question.strip() or len(recorded.question) > 2000:
            raise InvalidCompanionMemory("a question is 1 to 2000 characters")
        if len(recorded.answer_text) > 8000:
            raise InvalidCompanionMemory("an answer is at most 8000 characters")
        if recorded.abstained is not None and recorded.abstained not in ABSTENTIONS:
            raise InvalidCompanionMemory(f"{recorded.abstained} is not an abstention code")
        if recorded.latency_ms < 0:
            raise InvalidCompanionMemory("latency is a whole number of milliseconds, not negative")
        if not recorded.prompt_version.strip() or len(recorded.prompt_version) > 64:
            raise InvalidCompanionMemory("a recorded answer names the prompt version that made it")
        ordinals = [citation.ordinal for citation in recorded.citations]
        if len(set(ordinals)) != len(ordinals):
            raise InvalidCompanionMemory("two citations claim the same reading position")
        if any(ordinal < 0 for ordinal in ordinals):
            raise InvalidCompanionMemory("a citation's reading position is not negative")


def _by_ordinal(citation: AnswerCitation) -> int:
    return citation.ordinal


def _refusal(exc: psycopg.Error) -> Exception:
    """Turn the database's refusal into the error the API surface already knows how to answer.

    The database refuses with an SQLSTATE and a sentence, and `create_app` already maps
    `TombstonedError` to 410 `tombstoned` and treats an unknown reference as 404. Without this
    translation the citation guard would reach the client as an unhandled psycopg exception,
    which is a 500: the caller would be told the server broke when what actually happened is that
    they cited a photograph somebody withdrew. `EpistemicViolation`'s docstring makes the same
    point about the same class of failure: "The database refuses the same write with an SQLSTATE
    and no explanation. This carries the explanation."

    Migration 0043 splits "not in this workspace" from "deleted" for exactly this reason, so the
    branch below reads a distinction the trigger drew rather than guessing at one.
    """
    message = str(exc)
    if "tombstoned:" in message:
        return TombstonedError(
            "this answer cites a photograph that has been deleted, so it was not kept"
        )
    if "not in this workspace" in message:
        return UnknownCompanionMemory("this answer cites a photograph that is not in this library")
    return InvalidCompanionMemory(message)


def _row_to_answer(
    row: Mapping[str, Any], citations: tuple[AnswerCitation, ...]
) -> CompanionAnswer:
    return CompanionAnswer(
        row["answer_id"],
        row["asked_at"],
        row["question"],
        row["answer_text"],
        row["abstained"],
        row["deterministic"],
        row["repaired"],
        row["served_model"],
        row["planned_by"],
        row["prompt_version"],
        row["latency_ms"],
        AnswerOrigin(row["origin"]),
        row["supersedes"],
        row["correction_note"],
        MemoryStatus(row["status"]),
        citations,
    )


def _row_to_escape(row: Mapping[str, Any]) -> CompanionEscape:
    return CompanionEscape(
        row["escape_id"],
        row["taken_at"],
        EscapeKind(row["escape"]),
        row["intent"],
        row["entity_id"],
        row["turn_id"],
    )
