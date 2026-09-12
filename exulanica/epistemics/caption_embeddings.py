"""Shared caption sources, vector identity and persistence for ingest and retrieval.

Vectors reference the whole-photograph span. Migration 0044 durably records vector targets in
capture/workspace tombstone transactions and the purge worker removes them. Indexing refuses
schemas without that lifecycle capability before any model call. Assertions remain the source
text; a content fingerprint excludes stale vectors after a correction. Callers supply the
configured budgeted ModelClient, and no response cache retains deleted caption text.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass

import psycopg

from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.models.results import EmbeddingResult

PROMPT_VERSION = "companion-embedding-1"
FAMILY_PREFIX = f"companion_text:{PROMPT_VERSION}:"
SEARCHABLE_PREDICATES = ("caption_is", "ocr_text_is", "place_is")
# The same source definition is used at ingest and retrieval. Sorting is needed for the digest.
SOURCE_SQL = """
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
    if (
        connection.execute(
            "select to_regprocedure(format("
            "'%I.caption_vector_purge_is_authorized(uuid,uuid,uuid)',current_schema())) as guard"
        ).fetchone()["guard"]
        is None
    ):
        raise RuntimeError("Caption indexing requires lifecycle migration 0044")
    with connection.transaction():
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"companion-embedding:{workspace_id}:{capture_id}",),
        )
        source = connection.execute(
            "select * from (" + SOURCE_SQL + ") source where capture_id=%s",
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
