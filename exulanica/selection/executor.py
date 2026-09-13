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
*   The free-text field goes through English plain-text lexing. Code assembles an OR query
    from quoted lexemes, never from operator syntax supplied by a caller. The minimum-match
    rule and ts_rank/cosine fusion are fixed code, with every query value bound.


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
from exulanica.selection.embeddings import (
    SEARCHABLE_PREDICATES,
    QueryEmbedding,
    text_match_query,
)
from exulanica.selection.plan import (
    ContentPageCursor,
    ContentScope,
    EntityMode,
    EpistemicScope,
    Intent,
    ProcessingState,
)
from exulanica.selection.validation import STATEMENT_TIMEOUT_MS, ValidatedPlan
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "SelectedCapture",
    "SelectedContent",
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
_SEARCHABLE_PREDICATES: Final = SEARCHABLE_PREDICATES


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
class SelectedContent:
    """One authorized member of a unified, place-related result page."""

    result_kind: str
    origin_kind: str
    content_kind: str
    authored_role: str | None
    place_relationship: str
    match_reason: str
    memory_place_entity_id: uuid.UUID
    canonical_place_id: uuid.UUID | None
    world_id: str | None
    version_id: uuid.UUID | None
    source_id: str
    lineage_ids: tuple[str, ...]
    label: str | None
    availability: str
    personal_visit_evidence: bool


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
    content: tuple[SelectedContent, ...] = ()
    next_page: ContentPageCursor | None = None

    @property
    def truncated(self) -> bool:
        if self.intent is Intent.CONTENT:
            return self.next_page is not None
        return self.total_matched > len(self.captures)

    @property
    def is_empty(self) -> bool:
        return not self.captures and not self.entities and not self.content


def execute(
    connection: psycopg.Connection,
    validated: ValidatedPlan,
    *,
    query_embedding: QueryEmbedding | None = None,
    store: ContentAddressedStore | None = None,
) -> SelectionResult:
    """Run a validated plan. The only function in this package that touches data."""
    plan = validated.plan
    with connection.transaction():
        connection.execute(
            sql.SQL("set local statement_timeout = {}").format(sql.Literal(STATEMENT_TIMEOUT_MS))
        )
        connection.execute("set local transaction read only")
        if plan.intent is Intent.CONTENT:
            content, total, next_page = _matching_content(connection, validated, store)
            captures: tuple[SelectedCapture, ...] = ()
            entities: tuple[SelectedEntity, ...] = ()
        else:
            capture_ids, total = _matching_captures(connection, validated, query_embedding)
            captures = _describe_captures(connection, validated, capture_ids)
            entities = (
                _describe_entities(connection, validated, capture_ids)
                if plan.intent is Intent.ENTITIES
                else ()
            )
            content = ()
            next_page = None
    return SelectionResult(
        intent=plan.intent,
        captures=captures,
        entities=entities,
        total_matched=total,
        includes_proposals=plan.epistemic is EpistemicScope.INCLUDE_PROPOSALS,
        content=content,
        next_page=next_page,
    )


_MEMORY_CONTENT_SQL: Final = """
with selected_places as (
  select entity_id,place_id
    from confirmed_place_entity_bridge
   where workspace_id=%(workspace)s and entity_id=any(%(place_ids)s::uuid[])
), memory_candidates as (
select distinct on(c.capture_id)
       'memory_capture'::text result_kind,
       'personal'::text origin_kind,
       'capture'::text content_kind,
       null::text authored_role,
       'captured_at'::text place_relationship,
       'confirmed_memory_place'::text match_reason,
       l.entity_id memory_place_entity_id,
       selected.place_id canonical_place_id,
       null::text world_id,
       null::uuid version_id,
       c.capture_id::text source_id,
       array[
         'capture:'||c.capture_id::text,
         'blob:'||encode(c.blob_sha256,'hex'),
         'place-entity:'||l.entity_id::text
       ]::text[] lineage_ids,
       null::text label,
       true personal_visit_evidence,
       0::integer kind_order,
       coalesce(c.started_at,c.created_at) sort_time,
       'memory:'||c.capture_id::text result_key,
       c.blob_sha256 source_sha256,
       null::bytea render_sha256,
       null::bytea index_sha256
  from capture c
  join occurrence o
    on o.workspace_id=c.workspace_id and o.capture_id=c.capture_id and o.class='place'
  join entity_link l
    on l.workspace_id=o.workspace_id and l.occurrence_id=o.occurrence_id
   and l.state='confirmed'
  left join selected_places selected on selected.entity_id=l.entity_id
 where c.workspace_id=%(workspace)s
   and c.deleted_at is null
   and l.entity_id=any(%(place_ids)s::uuid[])
   and not tombstone_blocks_capture(c.workspace_id,c.capture_id)
   and not tombstone_blocks_any_span(o.workspace_id,o.span_ids)
 order by c.capture_id,l.entity_id
)
select * from memory_candidates
"""

_RELATED_CONTENT_SQL: Final = (
    _MEMORY_CONTENT_SQL
    + """
union all
select 'admitted_environment_source','imported','environment_source',null::text,
       'admitted_for','canonical_place_bridge',
       selected.entity_id,s.place_id,null::text,null::uuid,
       s.admission_id::text,
       array[
         'admission:'||s.admission_id::text,
         'provider:'||s.provider_key||':'||s.provider_original_id||':'||s.provider_revision,
         'source-receipt:'||encode(s.receipt_sha256,'hex')
       ]::text[],
       s.attribution,false,1,s.admitted_at,
       'source:'||s.admission_id::text,
       s.source_sha256,null::bytea,null::bytea
  from environment_source_admission s
  join selected_places selected on selected.place_id=s.place_id
 where s.workspace_id=%(workspace)s
   and s.withdrawn_at is null
   and environment_resource_allows(
         %(workspace)s,'source',s.admission_id,'display',statement_timestamp())
union all
select 'admitted_environment_feature','imported','environment_feature',null::text,
       'admitted_for','canonical_place_bridge',
       selected.entity_id,f.place_id,null::text,null::uuid,
       f.publication_id::text||':'||f.feature_id,
       array[
         'admission:'||f.admission_id::text,
         'publication:'||f.publication_id::text,
         'feature:'||f.feature_id,
         'index-asset:'||p.index_asset_id::text,
         'render-asset:'||p.render_asset_id::text
       ]::text[],
       f.label,false,2,p.published_at,
       'feature:'||f.publication_id::text||':'||f.feature_id,
       p.source_sha256,p.render_sha256,p.index_sha256
  from environment_feature_index_entry f
  join selected_places selected on selected.place_id=f.place_id
  join environment_feature_index_publication p
    on p.workspace_id=f.workspace_id and p.publication_id=f.publication_id
  join environment_source_admission s
    on s.workspace_id=p.workspace_id and s.admission_id=p.admission_id
  join derived_environment_asset idx
    on idx.workspace_id=p.workspace_id and idx.asset_id=p.index_asset_id
  join derived_environment_asset render
    on render.workspace_id=p.workspace_id and render.asset_id=p.render_asset_id
 where f.workspace_id=%(workspace)s
   and s.withdrawn_at is null and idx.withdrawn_at is null and render.withdrawn_at is null
   and p.publication_id=(
     select newest.publication_id
       from environment_feature_index_publication newest
      where newest.workspace_id=p.workspace_id and newest.admission_id=p.admission_id
      order by newest.published_at desc,newest.publication_id desc limit 1)
   and environment_resource_allows(
         %(workspace)s,'source',p.admission_id,'index',statement_timestamp())
   and environment_resource_allows(
         %(workspace)s,'asset',p.index_asset_id,'index',statement_timestamp())
   and environment_resource_allows(
         %(workspace)s,'asset',p.render_asset_id,'index',statement_timestamp())
union all
select 'authored_environment_instance','authored','environment_instance',i.origin_role,
       'derived_from','authored_from_canonical_place',
       selected.entity_id,i.source_place_id,i.world_id,i.version_id,
       i.world_id||':'||i.version_id::text||':'||i.instance_id,
       array_remove(array[
         'admission:'||i.admission_id::text,
         'render-asset:'||i.render_asset_id::text,
         case when i.publication_id is null then null
              else 'publication:'||i.publication_id::text end,
         case when i.feature_id is null then null else 'feature:'||i.feature_id end,
         'world-version:'||i.world_id||':'||i.version_id::text
       ]::text[],null),
       null::text,false,3,v.created_at,
       'authored:'||i.world_id||':'||i.version_id::text||':'||i.instance_id,
       i.source_sha256,i.render_sha256,i.index_sha256
  from world_alternate_environment_instance i
  join world_alternate_version v
    on v.workspace_id=i.workspace_id and v.world_id=i.world_id and v.version_id=i.version_id
  join selected_places selected on selected.place_id=i.source_place_id
  join environment_source_admission s
    on s.workspace_id=i.workspace_id and s.admission_id=i.admission_id
  join derived_environment_asset render
    on render.workspace_id=i.workspace_id and render.asset_id=i.render_asset_id
  left join environment_feature_index_publication p
    on p.workspace_id=i.workspace_id and p.publication_id=i.publication_id
  left join derived_environment_asset idx
    on idx.workspace_id=p.workspace_id and idx.asset_id=p.index_asset_id
 where i.workspace_id=%(workspace)s and not i.removed
   and s.withdrawn_at is null and render.withdrawn_at is null
   and s.place_id=i.source_place_id
   and s.source_sha256=i.source_sha256 and s.receipt_sha256=i.source_receipt_sha256
   and render.content_sha256=i.render_sha256
   and render.receipt_sha256=i.render_receipt_sha256
   and environment_resource_allows(
         %(workspace)s,'source',i.admission_id,'compose',statement_timestamp())
   and environment_resource_allows(
         %(workspace)s,'asset',i.render_asset_id,'compose',statement_timestamp())
   and (
     (i.selection_kind='whole_asset' and i.publication_id is null)
     or
     (i.selection_kind='feature'
      and p.publication_id is not null and idx.withdrawn_at is null
      and p.source_sha256=i.source_sha256
      and p.source_receipt_sha256=i.source_receipt_sha256
      and p.render_sha256=i.render_sha256
      and p.render_receipt_sha256=i.render_receipt_sha256
      and p.index_sha256=i.index_sha256
      and p.index_receipt_sha256=i.index_receipt_sha256
      and p.receipt_sha256=i.publication_receipt_sha256
      and p.publication_id=(
        select newest.publication_id
          from environment_feature_index_publication newest
         where newest.workspace_id=p.workspace_id and newest.admission_id=p.admission_id
         order by newest.published_at desc,newest.publication_id desc limit 1)
      and environment_resource_allows(
            %(workspace)s,'asset',p.index_asset_id,'compose',statement_timestamp()))
   )
union all
select 'synthetic_inhabitant','simulated','inhabitant',null::text,
       'simulated_at','scheduled_presence',
       selected.entity_id,s.place_id,s.world_id,s.version_id,
       inhabitant->>'id',
       array[
         'society:'||s.society_id::text,
         'inhabitant:'||(inhabitant->>'id'),
         'world-version:'||s.world_id||':'||s.version_id::text
       ]::text[],
       (inhabitant->>'display_name')||' · synthetic '||(inhabitant->>'role'),
       false,4,s.created_at,
       'inhabitant:'||(inhabitant->>'id'),
       null::bytea,null::bytea,null::bytea
  from world_society s
  join selected_places selected on selected.place_id=s.place_id
  cross join lateral jsonb_array_elements(s.state->'inhabitants') inhabitant
 where s.workspace_id=%(workspace)s
union all
select 'simulation_event','simulated','event',null::text,
       'simulated_at','recorded_simulation_event',
       selected.entity_id,e.place_id,s.world_id,s.version_id,
       e.event_id::text,
       array[
         'society:'||s.society_id::text,
         'event:'||e.event_id::text,
         'inhabitant:'||e.subject_id::text
       ]::text[],
       e.document->>'summary',false,5,e.recorded_at,
       'event:'||e.event_id::text,
       null::bytea,null::bytea,null::bytea
  from world_society_event e
  join world_society s
    on s.workspace_id=e.workspace_id and s.society_id=e.society_id
  join selected_places selected on selected.place_id=e.place_id
 where e.workspace_id=%(workspace)s
"""
)


def _matching_content(
    connection: psycopg.Connection,
    validated: ValidatedPlan,
    store: ContentAddressedStore | None,
) -> tuple[tuple[SelectedContent, ...], int, ContentPageCursor | None]:
    plan = validated.plan
    assert plan.content is not None
    candidate_sql = sql.SQL(
        _MEMORY_CONTENT_SQL
        if plan.content.scope is ContentScope.MEMORIES_ONLY
        else _RELATED_CONTENT_SQL
    )
    parameters: dict[str, object] = {
        "workspace": validated.workspace_id,
        "place_ids": list(validated.place_ids),
    }
    total_row = connection.execute(
        sql.SQL("select count(*) total from ({}) candidates").format(candidate_sql),
        parameters,
    ).fetchone()
    assert total_row is not None
    total = int(total_row["total"])

    cursor = plan.content.after
    parameters.update(
        {
            "cursor_kind": None if cursor is None else cursor.kind_order,
            "cursor_time": None if cursor is None else cursor.sort_time,
            "cursor_key": None if cursor is None else cursor.result_key,
            "page_size": plan.limit + 1,
        }
    )
    statement = sql.SQL(
        """
        select * from ({}) candidates
         where %(cursor_kind)s::integer is null
            or kind_order>%(cursor_kind)s
            or (kind_order=%(cursor_kind)s and sort_time<%(cursor_time)s)
            or (kind_order=%(cursor_kind)s and sort_time=%(cursor_time)s
                and result_key>%(cursor_key)s)
         order by kind_order,sort_time desc,result_key
         limit %(page_size)s
        """
    ).format(candidate_sql)
    rows = connection.execute(statement, parameters).fetchall()
    has_more = len(rows) > plan.limit
    visible_rows = rows[: plan.limit]
    results = tuple(_content_from_row(row, store) for row in visible_rows)
    next_page = None
    if has_more and visible_rows:
        last = visible_rows[-1]
        next_page = ContentPageCursor(
            kind_order=last["kind_order"],
            sort_time=last["sort_time"],
            result_key=last["result_key"],
        )
    return results, total, next_page


def _content_from_row(
    row: dict[str, object], store: ContentAddressedStore | None
) -> SelectedContent:
    availability = "unknown"
    if store is not None:
        digests = [
            value
            for value in (
                row["source_sha256"],
                row["render_sha256"],
                row["index_sha256"],
            )
            if value is not None
        ]
        availability = (
            "available"
            if all(store.exists(BlobId(bytes(value))) for value in digests)
            else "unavailable_bytes"
        )
    return SelectedContent(
        result_kind=str(row["result_kind"]),
        origin_kind=str(row["origin_kind"]),
        content_kind=str(row["content_kind"]),
        authored_role=(
            row["authored_role"] if isinstance(row["authored_role"], str) else None
        ),
        place_relationship=str(row["place_relationship"]),
        match_reason=str(row["match_reason"]),
        memory_place_entity_id=row["memory_place_entity_id"],  # type: ignore[arg-type]
        canonical_place_id=row["canonical_place_id"],  # type: ignore[arg-type]
        world_id=row["world_id"] if isinstance(row["world_id"], str) else None,
        version_id=row["version_id"],  # type: ignore[arg-type]
        source_id=str(row["source_id"]),
        lineage_ids=tuple(row["lineage_ids"]),  # type: ignore[arg-type]
        label=row["label"] if isinstance(row["label"], str) else None,
        availability=availability,
        personal_visit_evidence=bool(row["personal_visit_evidence"]),
    )


def _matching_captures(
    connection: psycopg.Connection,
    validated: ValidatedPlan,
    query_embedding: QueryEmbedding | None = None,
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

    Text queries use relevance, then newest capture and capture id. Other queries use newest
    capture and capture id. Two runs over unchanged data return the same page.
    """
    plan = validated.plan
    workspace = validated.workspace_id
    prefix = sql.SQL("")
    prefix_params: list[object] = []
    scope_clauses, scope_params = _scope_clauses(validated)
    if plan.semantic_query:
        text_sql, prefix_params = text_match_query(workspace, plan.semantic_query, query_embedding)
        prefix = sql.SQL("with text_matches as ({}) ").format(text_sql)
        scope_clauses.append(sql.SQL("c.capture_id in (select capture_id from text_matches)"))
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
        and not _scope_covers_every_entity(
            connection, validated, scope_clauses, scope_params, prefix, prefix_params
        )
    ):
        return (), 0

    where = sql.SQL(" and ").join(
        [sql.SQL("c.workspace_id = %s"), sql.SQL("c.deleted_at is null"), *row_clauses]
    )
    if not plan.semantic_query:
        statement = sql.SQL(
            "select c.capture_id, count(*) over () as total from capture c where {} "
            "order by c.started_at desc nulls last, c.capture_id limit %s"
        ).format(where)
    else:
        # Rank inside the permitted scope, and send at most plan.limit IDs to Python.
        ordering = sql.SQL("lexical desc")
        if query_embedding is not None:
            ordering = sql.SQL(
                "(case when lexical > 0 then 1.0/(60+lex_rank) else 0 end + "
                " case when cosine is not null then 1.0/(60+sem_rank) else 0 end) desc"
            )
        statement = prefix + sql.SQL(
            ", permitted as (select c.capture_id, c.started_at, m.lexical, m.cosine "
            "from capture c join text_matches m on m.capture_id=c.capture_id where {}), "
            "ranked as (select *, dense_rank() over (order by lexical desc) as lex_rank, "
            "dense_rank() over (order by cosine desc nulls last) as sem_rank from permitted) "
            "select capture_id, count(*) over () as total from ranked "
            "order by {}, started_at desc nulls last, capture_id limit %s"
        ).format(where, ordering)
    rows = connection.execute(statement, [*prefix_params, workspace, *row_params, plan.limit])
    rows = rows.fetchall()
    return tuple(row["capture_id"] for row in rows), int(rows[0]["total"]) if rows else 0


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
    return clauses, params


def _scope_covers_every_entity(
    connection: psycopg.Connection,
    validated: ValidatedPlan,
    scope_clauses: list[sql.Composed],
    scope_params: list[object],
    prefix: sql.Composable | None = None,
    prefix_params: list[object] | None = None,
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
        (prefix if prefix is not None else sql.SQL("")) + statement,
        [
            *(prefix_params or []),
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
            reasons.append(Support(span_id=row["span_id"], assertion_id=None, dimension="time"))
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
            reasons.append(Support(span_id=row["span_id"], assertion_id=None, dimension="capture"))
        captures.append(
            SelectedCapture(
                capture_id=row["capture_id"],
                blob_id=BlobId(bytes(row["blob_sha256"])),
                captured_at=row["started_at"].isoformat() if row["started_at"] else None,
                support=tuple(reasons),
            )
        )
    by_id = {capture.capture_id: capture for capture in captures}
    return tuple(by_id[key] for key in capture_ids if key in by_id)


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
            "and not tombstone_blocks_any_span(a.workspace_id, a.support_span_ids) "
            "order by a.assertion_id",
            (
                workspace,
                list(_SEARCHABLE_PREDICATES),
                [str(capture_id) for capture_id in capture_ids],
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
