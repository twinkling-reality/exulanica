"""Server-side validation, fail-closed, in the order ``architecture-overview.md`` 5.2 fixes.

Six stages, "each of which can only reject":

1. Structural schema validation.
2. Reference resolution. "Nonexistent ids and ids belonging to another tenant return the
   identical ``unknown_reference`` code, so the surface is not an existence oracle."
3. Authorization derived from the session only, never from anything in the plan.
4. Cost bounds.
5. Compilation to parameterized SQL.
6. Execution in a read-only transaction with a ``statement_timeout``.

Stages 1 to 4 live here. Stages 5 and 6 live in :mod:`exulanica.selection.executor`, and the seam
between them is the whole point of this module: :class:`ValidatedPlan` is the only thing the
executor accepts, and this module is the only thing that constructs one. A caller who wants to
run an unvalidated plan has no type they can pass.

**Why stage 2 is a real database round trip and not a filter.** Row-level security already makes
another workspace's entity invisible, so a plan naming one would simply match nothing and return
an empty result. That is not good enough: an empty result and a rejection are distinguishable by
the caller, and "your filter matched nothing" versus "that id is not yours" is the difference
between a private database and an oracle that confirms whether an id exists. Both cases resolve
to the same count of visible ids and therefore the same rejection.

**What is deliberately not here.** There is no repair, no coercion, no defaulting of a field the
caller got wrong. Section 5.2 permits "exactly one model repair attempt, then a deterministic
clarifying question", and that retry belongs to the caller that owns the model, not to the
validator: a validator that fixed its input would be deciding what the user meant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

import psycopg
from pydantic import ValidationError

from exulanica.errors import ExulanicaError
from exulanica.selection.plan import (
    MAX_ENTITY_IDS,
    MAX_LIMIT,
    MAX_SEMANTIC_QUERY_CHARS,
    MAX_TIME_WINDOWS,
    EpistemicScope,
    SelectionPlan,
)

__all__ = [
    "RejectionCode",
    "SelectionRejected",
    "Session",
    "ValidatedPlan",
    "validate",
]


class RejectionCode(StrEnum):
    """The only reasons a plan is refused. A caller sees the code, never the internals."""

    #: The plan is not a plan: wrong shape, unknown field, value out of range.
    MALFORMED_PLAN = "malformed_plan"
    #: An id that does not exist, or exists and is not yours. Deliberately one code.
    UNKNOWN_REFERENCE = "unknown_reference"
    #: More work than a single request is allowed to ask for.
    COST_BOUND_EXCEEDED = "cost_bound_exceeded"
    #: The session may not run this at all.
    NOT_AUTHORISED = "not_authorised"


class SelectionRejected(ExulanicaError):
    """A plan was refused, with the code the caller is allowed to see.

    ``detail`` is for the operator's log and for a developer's screen. It may name an id the
    caller already supplied, and it may not name anything the caller did not: a rejection that
    reported "entity X belongs to workspace Y" would answer a question nobody was allowed to
    ask.
    """

    def __init__(self, code: RejectionCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Session:
    """Who is asking. The only source of authority in the whole path.

    Nothing in a :class:`~exulanica.selection.plan.SelectionPlan` can name a workspace or an
    actor, so this is where both come from and there is no route by which a plan could widen
    them.
    """

    workspace_id: uuid.UUID
    actor: uuid.UUID
    #: Whether this session may see unconfirmed links at all. A read-only demonstration surface
    #: might not, and the plan's epistemic dimension must not be able to grant it.
    may_include_proposals: bool = True


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    """A plan that has passed every stage, plus what resolution established.

    Constructed only by :func:`validate`. The executor takes this type and not
    :class:`~exulanica.selection.plan.SelectionPlan`, so "was this validated" is answered by the
    type system rather than by a flag somebody has to remember to check.
    """

    plan: SelectionPlan
    session: Session
    #: Entity ids confirmed present in this workspace, in the order the plan gave them.
    entity_ids: tuple[uuid.UUID, ...] = ()
    place_ids: tuple[uuid.UUID, ...] = ()
    #: Recorded so an evaluation run can replay the exact plan that produced an answer.
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.session.workspace_id


#: Statement timeout for the read-only transaction the executor opens. Generous enough that a
#: correct query never hits it and short enough that a pathological one cannot hold a connection.
STATEMENT_TIMEOUT_MS: Final = 5_000


def parse(payload: Any) -> SelectionPlan:
    """Stage 1. Turn whatever arrived into a plan, or reject it.

    Separate from :func:`validate` because the model path and the interface path arrive
    differently: a model emits JSON that the client has already validated against the schema it
    sent, while the interface constructs a ``SelectionPlan`` directly. Both end up here.
    """
    try:
        return SelectionPlan.model_validate(payload)
    except ValidationError as exc:
        raise SelectionRejected(
            RejectionCode.MALFORMED_PLAN,
            f"{exc.error_count()} problem(s) with the plan: {exc.errors(include_url=False)}",
        ) from exc


def validate(
    connection: psycopg.Connection, plan: SelectionPlan, session: Session
) -> ValidatedPlan:
    """Stages 2 to 4. Returns the only value the executor will accept.

    The connection is used for reference resolution and nothing else. It must already be scoped
    to ``session.workspace_id``: resolution asks "how many of these ids can I see", and a
    connection scoped elsewhere would answer that question about the wrong workspace.
    """
    _authorise(plan, session)
    _check_cost_bounds(plan)
    entity_ids = _resolve(connection, session, _ids(plan.entities), kind="entity")
    place_ids = _resolve(connection, session, _ids(plan.place), kind="place")
    return ValidatedPlan(
        plan=plan,
        session=session,
        entity_ids=entity_ids,
        place_ids=place_ids,
        notes={"epistemic": str(plan.epistemic), "intent": str(plan.intent)},
    )


def _ids(selector: Any) -> tuple[uuid.UUID, ...]:
    return () if selector is None else tuple(selector.ids)


def _authorise(plan: SelectionPlan, session: Session) -> None:
    """Stage 3. Authority comes from the session; the plan may only narrow, never widen."""
    if plan.epistemic is EpistemicScope.INCLUDE_PROPOSALS and not session.may_include_proposals:
        raise SelectionRejected(
            RejectionCode.NOT_AUTHORISED,
            "this session may not see unconfirmed links, and a plan cannot grant itself that",
        )


def _check_cost_bounds(plan: SelectionPlan) -> None:
    """Stage 4. The schema already caps these; this is the check that is not the schema.

    Both exist on purpose. The schema's caps are what a model is shown and what a strict decoder
    enforces, and a plan constructed in Python bypasses them entirely, because Pydantic
    validators run on ``model_validate`` and not on direct construction. This is the one that
    runs for every caller.
    """
    problems: list[str] = []
    entity_count = len(_ids(plan.entities)) + len(_ids(plan.place))
    if entity_count > MAX_ENTITY_IDS:
        problems.append(f"{entity_count} entity ids, limit {MAX_ENTITY_IDS}")
    if len(plan.time) > MAX_TIME_WINDOWS:
        problems.append(f"{len(plan.time)} time windows, limit {MAX_TIME_WINDOWS}")
    if plan.semantic_query and len(plan.semantic_query) > MAX_SEMANTIC_QUERY_CHARS:
        problems.append(
            f"semantic query of {len(plan.semantic_query)} characters, "
            f"limit {MAX_SEMANTIC_QUERY_CHARS}"
        )
    if not 1 <= plan.limit <= MAX_LIMIT:
        problems.append(f"limit {plan.limit}, permitted range 1 to {MAX_LIMIT}")
    if problems:
        raise SelectionRejected(RejectionCode.COST_BOUND_EXCEEDED, "; ".join(problems))


def _resolve(
    connection: psycopg.Connection,
    session: Session,
    ids: tuple[uuid.UUID, ...],
    *,
    kind: str,
) -> tuple[uuid.UUID, ...]:
    """Stage 2. Every id must resolve to a live entity this session can see.

    One query, one code. The count is compared rather than the set, and the rejection names the
    ids the caller supplied rather than the subset that failed, because reporting which ones
    failed is the oracle this stage exists to prevent: a caller could binary-search the
    workspace by submitting candidate ids and reading which ones came back.
    """
    if not ids:
        return ()
    statement = (
        "select count(*) as visible from entity "
        "where workspace_id = %s and entity_id = any(%s::uuid[]) and deleted_at is null "
        "and class = 'place' and merged_into is null"
        if kind == "place"
        else "select count(*) as visible from entity "
        "where workspace_id = %s and entity_id = any(%s::uuid[]) and deleted_at is null"
    )
    row = connection.execute(statement, (session.workspace_id, list(ids))).fetchone()
    assert row is not None
    visible = row["visible"] if isinstance(row, dict) else row[0]
    if visible != len(set(ids)):
        raise SelectionRejected(
            RejectionCode.UNKNOWN_REFERENCE,
            f"one or more of the {len(set(ids))} {kind} ids in this plan is not available",
        )
    return ids
