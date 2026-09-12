"""Caption query embedding and lexical/cosine retrieval inside the permission boundary.

Persistence and source identity are shared below the ingest and selection layers. The exports
preserve existing callers; ranking and query orchestration stay in selection.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from time import perf_counter

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
               and e.model_ref=%s and e.pipeline_version=%s) as cosine
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
            "and e.model_ref=%s and e.pipeline_version=%s limit 1",
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
