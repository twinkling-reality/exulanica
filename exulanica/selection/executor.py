"""Stages 5 and 6: compile a validated plan to parameterized SQL, and run it deterministically.

No model runs in this module. That is the property the whole design rests on: a plan may have
come from a language model, and what happens to it afterwards is a fixed compiler and a fixed
query. ``architecture-overview.md`` 5.1 puts it as "a fixed compiler turns the plan into
parameterized SQL with **zero string interpolation of model output**".

That claim is checkable, and it is worth stating exactly what makes it true here:

*   Every SQL fragment in this file is a literal in this file. Which fragments are used is
    decided by ``if`` statements over enum members, so the set of possible statements is finite
    and enumerable by reading the source.
*   Every value from the plan is bound. Ids are bound as ``uuid[]``, times as ``timestamptz``,
    the limit as an integer.
*   The one free-text field goes to ``plainto_tsquery``, not ``to_tsquery``. The difference is
    the whole safety argument: ``plainto_tsquery`` treats its input as plain words and discards
    operator syntax, so ``'gullfoss & secret | admin'`` becomes ``'gullfoss' & 'secret' &
    'admin'`` rather than a boolean expression the caller authored. Verified on the server.

Execution runs in a **read-only transaction with a statement timeout**, per 5.2 stage 6. Both
matter and they are not the same guarantee: read-only means a plan cannot write whatever
happens upstream of it, and the timeout means a plan cannot hold a connection open. The
deployment adds a third, which is that the executor connects as ``exulanica_ro``, a role that
holds SELECT and nothing else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

import psycopg
from psycopg import sql

from exulanica.evidence.blob import BlobId
from exulanica.selection.plan import EntityMode, EpistemicScope, Intent, ProcessingState
from exulanica.selection.validation import STATEMENT_TIMEOUT_MS, ValidatedPlan

__all__ = [
    "SelectedCapture",
    "SelectedEntity",
    "SelectionResult",
    "Support",
    "execute",
]

#: Which link states count, per the plan's epistemic dimension. An ``auto_provisional`` link may
#: drive layout and filtering; it may never support a historical factual clause, which is why
#: :mod:`exulanica.selection.packet` refuses to build a citable packet from a proposal-inclusive
#: result rather than trusting a caller to remember.
_LINK_STATES: Final[dict[EpistemicScope, tuple[str, ...]]] = {
    EpistemicScope.CONFIRMED: ("confirmed",),
    EpistemicScope.INCLUDE_PROPOSALS: ("confirmed", "auto_provisional"),
}

#: The predicates whose object is capture-derived text worth searching. All three are model
#: output over the user's own photographs, so anything matched through them is untrusted input
#: and is tagged as such on the way out.
_SEARCHABLE_PREDICATES: Final = ("caption_is", "ocr_text_is", "place_is")


@dataclass(frozen=True, slots=True)
class Support:
    """One reason a capture matched, and the evidence that reason rests on.

    ``assertion_id`` is None for a match that is a property of the capture itself rather than of
    a claim about it: a time window matches because the EXIF timestamp says so, and there is no
    assertion to cite beyond the photograph.
    """

    span_id: uuid.UUID
    assertion_id: uuid.UUID | None
    #: One of ``entity``, ``place``, ``time``, ``text``, ``capture``. Which dimension put this
    #: here. ``capture`` is the last of them and means the photograph matched on a property of
    #: itself, with the whole-photograph span as the record of that property.
    dimension: str
    #: The entity this support is about, when the dimension is entity or place.
    entity_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SelectedCapture:
    capture_id: uuid.UUID
    blob_id: BlobId
    captured_at: str | None
    support: tuple[Support, ...]

    @property
    def span_ids(self) -> tuple[uuid.UUID, ...]:
        seen: dict[uuid.UUID, None] = {}
        for item in self.support:
            seen.setdefault(item.span_id, None)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class SelectedEntity:
    entity_id: uuid.UUID
    entity_class: str
    display_name: str | None
    #: How many captures inside this Selection the entity appears in.
    capture_count: int


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """What a Selection resolved to. Deterministic given the same plan and the same data."""

    intent: Intent
    captures: tuple[SelectedCapture, ...]
    entities: tuple[SelectedEntity, ...]
    #: Matches before ``limit`` was applied. Reported rather than implied: a bounded result that
    #: does not say it was bounded reads as "that is all there is".
    total_matched: int
    #: True when the plan's epistemic scope admitted unconfirmed links. Carried on the result so
    #: a downstream caller cannot lose it between here and the citation validator.
    includes_proposals: bool

    @property
    def truncated(self) -> bool:
        return self.total_matched > len(self.captures)

    @property
    def is_empty(self) -> bool:
        return not self.captures and not self.entities


def execute(connection: psycopg.Connection, validated: ValidatedPlan) -> SelectionResult:
    """Run a validated plan. The only function in this package that touches data."""
    plan = validated.plan
    with connection.transaction():
        connection.execute(
            sql.SQL("set local statement_timeout = {}").format(sql.Literal(STATEMENT_TIMEOUT_MS))
        )
        connection.execute("set local transaction read only")
        capture_ids, total = _matching_captures(connection, validated)
        captures = _describe_captures(connection, validated, capture_ids)
        entities = (
            _describe_entities(connection, validated, capture_ids)
            if plan.intent is Intent.ENTITIES
            else ()
        )
    return SelectionResult(
        intent=plan.intent,
        captures=captures,
        entities=entities,
        total_matched=total,
        includes_proposals=plan.epistemic is EpistemicScope.INCLUDE_PROPOSALS,
    )


def _matching_captures(
    connection: psycopg.Connection, validated: ValidatedPlan
) -> tuple[tuple[uuid.UUID, ...], int]:
    """Intersect the active dimensions, then order and bound.

    Two shapes of predicate, and the difference is the whole of M6. ``ANY`` and ``TOGETHER`` are
    questions about one capture, so they join the WHERE clause. ``ALL`` is a question about the
    SCOPE: "every named entity present within the scope, not necessarily in the same
    photograph". A scope-level predicate cannot be a row filter, because the answer for a given
    capture depends on the other captures. So the scope is computed first from every other
    dimension, the coverage question is asked of that whole set, and the scope is returned
    entire or not at all. That is M6's trap (c) satisfied by construction: TOGETHER over a pair
    that never shares a photograph returns nothing, while ALL over the same pair returns the
    region.

    The ordering is fixed by the code rather than chosen by the caller: newest capture first,
    ties broken by capture id, so two runs over unchanged data return the same page.
    """
    plan = validated.plan
    workspace = validated.workspace_id
    scope_clauses, scope_params = _scope_clauses(validated)
    mode = plan.entities.mode if plan.entities is not None else None

    row_clauses = list(scope_clauses)
    row_params = list(scope_params)
    if validated.entity_ids and mode in {EntityMode.ANY, EntityMode.TOGETHER}:
        clause, values = _entity_clause(validated.entity_ids, mode, plan.epistemic, workspace)
        row_clauses.append(clause)
        row_params.extend(values)

    if (
        validated.entity_ids
        and mode is EntityMode.ALL
        and not _scope_covers_every_entity(connection, validated, scope_clauses, scope_params)
    ):
        return (), 0

    where = sql.SQL(" and ").join(
        [sql.SQL("c.workspace_id = %s"), sql.SQL("c.deleted_at is null"), *row_clauses]
    )
    statement = sql.SQL(
        "select c.capture_id, count(*) over () as total from capture c "
        "where {} order by c.started_at desc nulls last, c.capture_id limit %s"
    ).format(where)
    rows = connection.execute(statement, [workspace, *row_params, plan.limit]).fetchall()
    total = rows[0]["total"] if rows else 0
    return tuple(row["capture_id"] for row in rows), int(total)


def _scope_clauses(validated: ValidatedPlan) -> tuple[list[sql.Composed], list[object]]:
    """Every dimension except the entity one, which is where the two shapes diverge."""
    plan = validated.plan
    workspace = validated.workspace_id
    clauses: list[sql.Composed] = []
    params: list[object] = []

    if validated.place_ids:
        # Places combine as ANY within their own dimension: a photograph is at one place, so
        # asking for two places means either of them.
        clause, values = _entity_clause(
            validated.place_ids, EntityMode.ANY, plan.epistemic, workspace
        )
        clauses.append(clause)
        params.extend(values)
    if plan.time:
        clauses.append(
            sql.SQL(
                "c.started_at is not null and exists ("
                "  select 1 from unnest(%s::timestamptz[], %s::timestamptz[]) as w(lo, hi)"
                "   where c.started_at >= w.lo and c.started_at < w.hi)"
            )
        )
        params.append([window.start for window in plan.time])
        params.append([window.end for window in plan.time])
    if plan.capture is not None:
        clauses.append(_processing_state_clause(plan.capture.processing_states))
        params.append(workspace)
    if plan.semantic_query:
        clauses.append(
            sql.SQL(
                "exists (select 1 from assertion a"
                "         join predicate p on p.predicate_id = a.predicate_id"
                "        where a.workspace_id = %s and a.status = 'active'"
                "          and p.key = any(%s::text[])"
                "          and a.subject_ref->>'id' = c.capture_id::text"
                "          and to_tsvector('simple', a.object_value #>> '{}')"
                "              @@ plainto_tsquery('simple', %s))"
            )
        )
        params.extend([workspace, list(_SEARCHABLE_PREDICATES), plan.semantic_query])
    return clauses, params


def _scope_covers_every_entity(
    connection: psycopg.Connection,
    validated: ValidatedPlan,
    scope_clauses: list[sql.Composed],
    scope_params: list[object],
) -> bool:
    """Does every named entity appear somewhere in the scope?

    Counted over the WHOLE scope, not over the page the caller will see. Asking the limited page
    would make the answer depend on the limit, so a plan asking for ten captures could report
    that somebody was absent from a trip they were on.

    M6's trap (a): ALL over entities that never co-occur "must return empty rather than 'no
    results, here is something similar'". An empty scope therefore fails coverage, and the
    caller gets nothing rather than a consolation set.
    """
    where = sql.SQL(" and ").join(
        [sql.SQL("c.workspace_id = %s"), sql.SQL("c.deleted_at is null"), *scope_clauses]
    )
    statement = sql.SQL(
        "select count(distinct l.entity_id) as covered from capture c "
        "join occurrence o on o.capture_id = c.capture_id and o.workspace_id = c.workspace_id "
        "join entity_link l on l.occurrence_id = o.occurrence_id "
        "where {} and l.state = any(%s::link_state[]) and l.entity_id = any(%s::uuid[])"
    ).format(where)
    row = connection.execute(
        statement,
        [
            validated.workspace_id,
            *scope_params,
            list(_LINK_STATES[validated.plan.epistemic]),
            list(validated.entity_ids),
        ],
    ).fetchone()
    assert row is not None
    return int(row["covered"]) == len(set(validated.entity_ids))


def _entity_clause(
    ids: tuple[uuid.UUID, ...],
    mode: EntityMode,
    epistemic: EpistemicScope,
    workspace: uuid.UUID,
) -> tuple[sql.Composed, list[object]]:
    """The per-capture entity predicates. ANY is an existence test; TOGETHER is not.

    TOGETHER is the strict filter: the occurrences' ``presence`` multiranges must OVERLAP inside
    one capture, which is what ADR-0005 means by "a shared evidence window, not merely
    co-presence in one capture". The distinction is invisible for photographs, where every
    occurrence carries the degenerate interval ``[0, 1)`` and therefore always overlaps, and it
    is the entire meaning of "together" for video. Implementing the general form costs one
    aggregate and means the video path needs no second implementation.

    The union-then-intersect order is load-bearing. ``range_agg`` per entity first, because one
    entity may occur twice in a capture and intersecting its own two occurrences with each other
    would ask whether somebody was in two places at once. Then ``range_intersect_agg`` across
    entities, which is the question actually being asked.

    ALL never reaches here: it is a question about the scope rather than about a capture, and it
    is answered by :func:`_scope_covers_every_entity`.
    """
    states = list(_LINK_STATES[epistemic])
    if mode is not EntityMode.TOGETHER:
        return (
            sql.SQL(
                "exists (select 1 from occurrence o"
                "         join entity_link l on l.occurrence_id = o.occurrence_id"
                "        where o.workspace_id = %s and o.capture_id = c.capture_id"
                "          and l.state = any(%s::link_state[])"
                "          and l.entity_id = any(%s::uuid[]))"
            ),
            [workspace, states, list(ids)],
        )
    return (
        sql.SQL(
            "exists ("
            "  with per_entity as ("
            "    select l.entity_id, range_agg(o.presence) as presence"
            "      from occurrence o"
            "      join entity_link l on l.occurrence_id = o.occurrence_id"
            "     where o.workspace_id = %s and o.capture_id = c.capture_id"
            "       and l.state = any(%s::link_state[])"
            "       and l.entity_id = any(%s::uuid[])"
            "     group by l.entity_id)"
            "  select 1 from per_entity"
            "  having count(*) = %s and not isempty(range_intersect_agg(presence)))"
        ),
        [workspace, states, list(ids), len(set(ids))],
    )


def _processing_state_clause(states: list[ProcessingState]) -> sql.Composed:
    """Whether the vision stage produced anything for this capture's bytes.

    Composed from the requested states rather than parameterised, because the states are enum
    members and the fragments are literals in this file. There is no caller-supplied string
    anywhere in the result.
    """
    has_vision = sql.SQL(
        "exists (select 1 from artifact v where v.workspace_id = %s"
        "         and v.source_blob_sha256 = c.blob_sha256 and v.stage_key = 'vision'"
        "         and v.purged_at is null)"
    )
    wanted = set(states)
    if wanted == {ProcessingState.COMPLETE}:
        return has_vision
    if wanted == {ProcessingState.CAPTURE_ONLY}:
        return sql.SQL("not ") + has_vision
    # Both states requested: every capture is one or the other, so the filter is vacuous. The
    # workspace parameter is still consumed, because the caller has already appended it.
    return sql.SQL("(%s is not null)")


def _describe_captures(
    connection: psycopg.Connection, validated: ValidatedPlan, capture_ids: tuple[uuid.UUID, ...]
) -> tuple[SelectedCapture, ...]:
    """Fetch each matching capture with the evidence that made it match.

    Two round trips rather than one join, deliberately. A single query returning captures joined
    to their support rows multiplies the capture columns by the support count, and the support
    count is unbounded: a photograph with forty labelled objects would return forty copies of
    its row. The second query is bounded by the first one's ``limit``.
    """
    if not capture_ids:
        return ()
    plan = validated.plan
    workspace = validated.workspace_id
    rows = connection.execute(
        "select c.capture_id, c.blob_sha256, c.started_at, s.span_id "
        "from capture c "
        "join evidence_span s on s.workspace_id = c.workspace_id "
        " and s.blob_sha256 = c.blob_sha256 and s.modality = 'still_image' "
        "where c.workspace_id = %s and c.capture_id = any(%s::uuid[]) "
        "order by c.started_at desc nulls last, c.capture_id",
        (workspace, list(capture_ids)),
    ).fetchall()

    support = _support_for(connection, validated, capture_ids)
    captures: list[SelectedCapture] = []
    for row in rows:
        reasons = list(support.get(row["capture_id"], ()))
        if plan.time:
            # The whole-photograph span is what a time match rests on: EXIF said so, and the
            # photograph is the record of that.
            #
            # `plan.is_unconstrained` used to be in this condition, which meant the Atlas's
            # opening view -- an empty plan, the most common Selection in the product -- told
            # every client through SupportView that a time window had put each photograph there
            # when no window was asked for. That is the same mislabel the branch below exists to
            # avoid, and an unconstrained plan falls into it now: it sets no dimension, so it
            # produces no support of its own, so `reasons` is empty.
            reasons.append(
                Support(span_id=row["span_id"], assertion_id=None, dimension="time")
            )
        elif not reasons:
            # **A capture that matched must never leave here with nothing to cite.**
            #
            # The claim this support makes is narrow and exactly true: this photograph is in
            # this Selection, and the whole-photograph span is the record that it exists. It is
            # the same claim the branch above makes for a time match, under its own dimension
            # rather than mislabelled as one.
            #
            # Three routes reach it, and the second and third are why the condition is
            # `not reasons` rather than a test on one dimension.
            #
            # *   An unconstrained plan, which sets no dimension at all. The photograph is in
            #     the Selection because everything is.
            #
            # *   A plan whose only dimension is `capture.processing_states`. `is_unconstrained`
            #     is false as soon as any dimension is set, `_support_for` returns nothing
            #     without entity ids, place ids or a semantic query, and the branch above needs
            #     a time window. Every capture carried `support=()`, so the packet was empty and
            #     the question came back "Nothing in your library matches, so there is nothing I
            #     could cite" while `total_matched` was four. That is a false abstention (M3),
            #     and it is worse than a wrong answer because it is stated as a fact about
            #     somebody's own library.
            #
            # *   `EntityMode.ALL`, which is a question about the SCOPE and returns the scope
            #     entire, including captures holding none of the named entities. Those have no
            #     entity support and never will; M6 specifies that reading. They did not cause
            #     an abstention, because the captures that do hold an entity fill the packet.
            #     What they caused was worse to read: `EvidencePacket.truncated` compares
            #     `total_matched` against the captures in the packet, so the composer was told
            #     "more captures matched than are shown here" when nothing had been truncated
            #     and one capture simply had nothing citable. A scope member that cannot be
            #     cited is a scope member the answer cannot mention.
            reasons.append(
                Support(span_id=row["span_id"], assertion_id=None, dimension="capture")
            )
        captures.append(
            SelectedCapture(
                capture_id=row["capture_id"],
                blob_id=BlobId(bytes(row["blob_sha256"])),
                captured_at=row["started_at"].isoformat() if row["started_at"] else None,
                support=tuple(reasons),
            )
        )
    return tuple(captures)


def _support_for(
    connection: psycopg.Connection, validated: ValidatedPlan, capture_ids: tuple[uuid.UUID, ...]
) -> dict[uuid.UUID, list[Support]]:
    """The occurrence and assertion rows that justify each capture, per dimension."""
    plan = validated.plan
    workspace = validated.workspace_id
    found: dict[uuid.UUID, list[Support]] = {}

    wanted = [*validated.entity_ids, *validated.place_ids]
    if wanted:
        rows = connection.execute(
            "select o.capture_id, o.primary_span_id, l.entity_id, e.class "
            "from occurrence o "
            "join entity_link l on l.occurrence_id = o.occurrence_id "
            "join entity e on e.entity_id = l.entity_id "
            "where o.workspace_id = %s and o.capture_id = any(%s::uuid[]) "
            "and l.state = any(%s::link_state[]) and l.entity_id = any(%s::uuid[]) "
            "order by o.capture_id, o.occurrence_id",
            (workspace, list(capture_ids), list(_LINK_STATES[plan.epistemic]), wanted),
        ).fetchall()
        for row in rows:
            found.setdefault(row["capture_id"], []).append(
                Support(
                    span_id=row["primary_span_id"],
                    assertion_id=None,
                    dimension="place" if row["class"] == "place" else "entity",
                    entity_id=row["entity_id"],
                )
            )

    if plan.semantic_query:
        rows = connection.execute(
            "select a.assertion_id, a.support_span_ids, a.subject_ref->>'id' as capture_id "
            "from assertion a join predicate p on p.predicate_id = a.predicate_id "
            "where a.workspace_id = %s and a.status = 'active' and p.key = any(%s::text[]) "
            "and a.subject_ref->>'id' = any(%s::text[]) "
            "and to_tsvector('simple', a.object_value #>> '{}') "
            "    @@ plainto_tsquery('simple', %s) "
            "order by a.assertion_id",
            (
                workspace,
                list(_SEARCHABLE_PREDICATES),
                [str(capture_id) for capture_id in capture_ids],
                plan.semantic_query,
            ),
        ).fetchall()
        for row in rows:
            capture_id = uuid.UUID(row["capture_id"])
            for span_id in row["support_span_ids"]:
                found.setdefault(capture_id, []).append(
                    Support(
                        span_id=span_id,
                        assertion_id=row["assertion_id"],
                        dimension="text",
                    )
                )
    return found


def _describe_entities(
    connection: psycopg.Connection, validated: ValidatedPlan, capture_ids: tuple[uuid.UUID, ...]
) -> tuple[SelectedEntity, ...]:
    """Who and what appears inside this Selection, with how often.

    Ordered by count and then by id, so the same Selection lists the same entities in the same
    order twice running. Not ordered by name: a name is optional and an entity without one would
    sort arbitrarily against one with.
    """
    if not capture_ids:
        return ()
    rows = connection.execute(
        "select e.entity_id, e.class, e.display_name, "
        "       count(distinct o.capture_id) as capture_count "
        "from occurrence o "
        "join entity_link l on l.occurrence_id = o.occurrence_id "
        "join entity e on e.entity_id = l.entity_id and e.deleted_at is null "
        "where o.workspace_id = %s and o.capture_id = any(%s::uuid[]) "
        "and l.state = any(%s::link_state[]) "
        "group by e.entity_id, e.class, e.display_name "
        "order by count(distinct o.capture_id) desc, e.entity_id "
        "limit %s",
        (
            validated.workspace_id,
            list(capture_ids),
            list(_LINK_STATES[validated.plan.epistemic]),
            validated.plan.limit,
        ),
    ).fetchall()
    return tuple(
        SelectedEntity(
            entity_id=row["entity_id"],
            entity_class=row["class"],
            display_name=row["display_name"],
            capture_count=int(row["capture_count"]),
        )
        for row in rows
    )
