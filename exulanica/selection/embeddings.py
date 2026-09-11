"""Capture text vectors and deterministic retrieval over the existing permission boundary.

Vectors reference the whole-photograph span, so tombstones block reads and reinsertion.
Physical purge for ordinary caption vectors is not integrated: the existing worker only queues
person-dependent vectors. Do not enable live indexing until that acceptance failure is fixed.
Assertions remain the source text; text_chunk requires an artifact and is not a second copy of
assertions. A content fingerprint excludes stale vectors after a correction.
No model identifiers or prices are duplicated here. Callers supply a budgeted ModelClient.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

import psycopg
from psycopg import sql

from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.models.results import EmbeddingResult

PROMPT_VERSION = "companion-embedding-1"
FAMILY_PREFIX = f"companion_text:{PROMPT_VERSION}:"
SEARCHABLE_PREDICATES = ("caption_is", "ocr_text_is", "place_is")
# A provisional relevance floor, not a probability or a measured quality guarantee.
MIN_COSINE = 0.65

# The same source definition is used at ingest and retrieval. Sorting is needed for the digest.
_SOURCE_SQL = """
select c.capture_id, s.span_id,
       string_agg(a.object_value #>> '{}', E'\\n' order by a.assertion_id) as body
from capture c
join evidence_span s on s.workspace_id=c.workspace_id and s.blob_sha256=c.blob_sha256
                    and s.modality='still_image' and s.track_key='img'
                    and s.t_start_ns=0 and s.t_end_ns=1
                    and s.region is null and s.text_anchor is null
join assertion a on a.workspace_id=c.workspace_id
                and a.subject_ref->>'id'=c.capture_id::text and a.status='active'
join predicate p on p.predicate_id=a.predicate_id
where c.workspace_id=%s and c.deleted_at is null and p.key=any(%s::text[])
  and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
  and not tombstone_blocks_any_span(a.workspace_id, a.support_span_ids)
  and jsonb_typeof(a.object_value)='string'
group by c.capture_id, s.span_id
"""


@dataclass(frozen=True)
class QueryEmbedding:
    vector: tuple[float, ...]
    model_id: str
    pipeline_version: int

    def __post_init__(self) -> None:
        if len(self.vector) != 4096 or not all(math.isfinite(v) for v in self.vector):
            raise ValueError("A query embedding must contain 4096 finite dimensions")
        if not any(self.vector):
            raise ValueError("A zero vector has no cosine similarity")

    @property
    def literal(self) -> str:
        return "[" + ",".join(str(v) for v in self.vector) + "]"


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


def embed_capture(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    client: ModelClient,
) -> EmbeddingResult | None:
    """Embed active assertions once per capture/content/model version, including concurrent jobs.

    Workspace provisioning must already have created its vector partition. Never create schema
    at runtime. The transaction serializes this pass; the insert's tombstone guard refuses a
    deletion that arrived while the model ran. No response cache retains deleted caption text.
    """
    with connection.transaction():
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"companion-embedding:{workspace_id}:{capture_id}",),
        )
        source = connection.execute(
            "select * from (" + _SOURCE_SQL + ") source where capture_id=%s",
            (workspace_id, list(SEARCHABLE_PREDICATES), capture_id),
        ).fetchone()
        if source is None:
            return None
        model = client.manifest[Role.EMBEDDING].primary.model_id
        version = client.manifest.pipeline_version
        family = FAMILY_PREFIX + hashlib.sha256(source["body"].encode()).hexdigest()
        key = uuid.uuid5(workspace_id, f"{capture_id}:{family}:{model}:{version}:{PROMPT_VERSION}")
        if connection.execute(
            "select 1 from embedding where workspace_id=%s and embedding_id=%s",
            (workspace_id, key),
        ).fetchone():
            return None
        result = client.embed(
            [source["body"]], role=Role.EMBEDDING, prompt_version=PROMPT_VERSION, use_cache=False
        )
        if result.model_id != model or len(result.vectors) != 1:
            raise ValueError("The embedding role returned an unexpected model or vector count")
        vector = QueryEmbedding(result.vectors[0], result.model_id, version)
        connection.execute(
            "insert into embedding (embedding_id, workspace_id, family, ref_type, ref_id, "
            "model_ref, pipeline_version, dims, v) values (%s,%s,%s,'span',%s,%s,%s,4096,%s)",
            (
                key,
                workspace_id,
                family,
                source["span_id"],
                result.model_id,
                version,
                vector.literal,
            ),
        )
        return result


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
