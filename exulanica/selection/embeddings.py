"""Caption query embedding and lexical/cosine retrieval inside the permission boundary.

Persistence and source identity are shared below the ingest and selection layers. The exports
preserve existing callers; ranking and query orchestration stay in selection.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from time import perf_counter
from typing import Final

import psycopg
from psycopg import sql

from exulanica.epistemics.caption_embeddings import (
    FAMILY_PREFIX,
    PROMPT_VERSION,
    SEARCHABLE_PREDICATES,
    QueryEmbedding,
    embed_capture,
)
from exulanica.epistemics.caption_embeddings import (
    SOURCE_SQL as _SOURCE_SQL,
)
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.models.results import EmbeddingResult

__all__ = ["QueryEmbedding", "embed_capture", "embed_query", "has_embeddings", "text_match_query"]

# A provisional relevance floor, not a probability or a measured quality guarantee.
MIN_COSINE = 0.65

#: The one tombstone scope whose stop can be followed by the same entry made again: migration
#: 0104's insert guard keeps 0044's refusal of an id recorded as a target for every other scope and
#: admits it for this one while a current search right covers it, because a vector id is a digest
#: of the capture, text and model and a right granted again makes the same id.
#: ``tests/test_search_entry_granted_again.py`` holds this value to the guard's own definition.
READMITTED_SCOPE: Final = "caption_search"

# A search entry is left out while any tombstone names it as a vector target (0044, 0104), of
# whatever scope. The one exception is a target of READMITTED_SCOPE whose purge job is done: the
# purge worker deletes the entry and marks its job done in one transaction, so an entry that exists
# beside that done job is a later row the guard admitted under a right granted again. A target of
# any other scope stays excluding after its purge, as the guard never admits its id again. The
# target rows stay as the stop's record.
_NOT_A_PENDING_TARGET = f"""not exists (
    select 1 from tombstone_embedding_target d
      join tombstone t on t.workspace_id = d.workspace_id and t.tombstone_id = d.tombstone_id
     where d.workspace_id = e.workspace_id and d.embedding_id = e.embedding_id
       and not (t.scope::text = '{READMITTED_SCOPE}'
                and exists (select 1 from purge_job p
                             where p.workspace_id = d.workspace_id
                               and p.tombstone_id = d.tombstone_id
                               and p.target_kind = 'embedding'
                               and p.target_ref = d.embedding_id::text
                               and p.state = 'done')))"""


def embed_query(
    client: ModelClient,
    query: str,
    *,
    record: Callable[[EmbeddingResult, int], None] | None = None,
) -> QueryEmbedding:
    started = perf_counter()
    result = client.embed(
        [query], role=Role.EMBEDDING, prompt_version=PROMPT_VERSION, use_cache=False
    )
    if record is not None:
        record(result, round((perf_counter() - started) * 1000))
    if len(result.vectors) != 1:
        raise ValueError("The embedding role must return exactly one query vector")
    return QueryEmbedding(result.vectors[0], result.model_id, client.manifest.pipeline_version)


def text_match_query(
    workspace_id: uuid.UUID,
    query: str,
    embedding: QueryEmbedding | None,
) -> tuple[sql.Composed, list[object]]:
    """English OR retrieval with ceil(unique content lexemes / 2) required, then cosine.

    Operator syntax never comes from the caller: PostgreSQL lexes plain text, then quotes each
    lexeme before assembling an OR query. Duplicate words cannot inflate minimum match.
    Semantic-only candidates must clear the cosine floor; unrelated queries may still abstain.
    The executor intersects these candidates with every other validated dimension before fusion.
    A search entry a deletion or a stopped search right has targeted is not ranked from the moment
    it is targeted until its purge destroys it; an entry made again under a right granted after
    that purge is ranked (``_NOT_A_PENDING_TARGET``).
    """
    statement = sql.SQL(
        "with source as ("
        + _SOURCE_SQL
        + """),
        terms as (select tsvector_to_array(to_tsvector('english', %s)) as words),
        q as (select words, array_to_string(
                   array(select quote_literal(w) from unnest(words) w), ' | ')::tsquery
                   as query from terms),
        scored as (
          select source.capture_id,
            case when (select count(*) from unnest(q.words) w
                 where w = any(tsvector_to_array(to_tsvector('english', source.body))))
                 >= greatest(1, ceil(cardinality(q.words)::numeric / 2))
            then ts_rank(to_tsvector('english', source.body), q.query) else 0 end as lexical,
            (select max(1 - (e.v <=> %s::halfvec)) from embedding e
             where e.workspace_id=%s and e.ref_type='span' and e.ref_id=source.span_id
               and e.family=%s || encode(digest(source.body, 'sha256'), 'hex')
               and e.model_ref=%s and e.pipeline_version=%s
               and """
        + _NOT_A_PENDING_TARGET
        + """) as cosine
          from source cross join q where cardinality(q.words) > 0
        )
        select capture_id, lexical, case when cosine >= %s then cosine end as cosine
        from scored where lexical > 0 or cosine >= %s
        """
    )
    return statement, [
        workspace_id,
        list(SEARCHABLE_PREDICATES),
        query,
        embedding.literal if embedding else None,
        workspace_id,
        FAMILY_PREFIX,
        embedding.model_id if embedding else None,
        embedding.pipeline_version if embedding else None,
        MIN_COSINE,
        MIN_COSINE,
    ]


def has_embeddings(
    connection: psycopg.Connection, workspace_id: uuid.UUID, client: ModelClient
) -> bool:
    """An unindexed workspace uses lexical search without paying for an unusable query vector."""
    return (
        connection.execute(
            "with source as (" + _SOURCE_SQL + ") "
            "select 1 from source join embedding e on e.ref_id=source.span_id "
            "where e.workspace_id=%s and e.ref_type='span' "
            "and e.family=%s || encode(digest(source.body, 'sha256'), 'hex') "
            "and e.model_ref=%s and e.pipeline_version=%s "
            "and " + _NOT_A_PENDING_TARGET + " limit 1",
            (
                workspace_id,
                list(SEARCHABLE_PREDICATES),
                workspace_id,
                FAMILY_PREFIX,
                client.manifest[Role.EMBEDDING].primary.model_id,
                client.manifest.pipeline_version,
            ),
        ).fetchone()
        is not None
    )
