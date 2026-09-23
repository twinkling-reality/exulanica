"""Shared caption sources, vector identity and persistence for ingest and retrieval.

Vectors reference the whole-photograph span. Migration 0044 durably records vector targets in
capture/workspace tombstone transactions and the purge worker removes them. Indexing refuses
schemas without that lifecycle capability before any model call. Assertions remain the source
text; a content fingerprint excludes stale vectors after a correction. Callers supply the
configured budgeted ModelClient, and no response cache retains deleted caption text.

Caption text is written about a photograph by the vision model, so it is as personal as the
photograph. It leaves only through ``before_send``, which every caller supplies and which is
handed every model the request can reach and where it goes; the caller decides, and a refusal
raises before anything is sent. This layer cannot import that decision, which lives in
``exulanica.ingest.model_rights``, so it asks for it instead.

The text also carries whatever the photograph showed in writing, and a sign or a shirt can carry a
name the account holder saved. Every saved name is replaced in what is sent, as it is in the
Companion's packet (:mod:`exulanica.epistemics.saved_names`). The stored vector is keyed by the
text as stored, so a name saved after a vector was made does not make it again.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus

from exulanica.epistemics.saved_names import redact_names, saved_names
from exulanica.models.client import ModelClient
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import Role
from exulanica.models.results import EmbeddingResult

#: Called with every model a caption request can reach and where it goes, immediately before the
#: text is sent. It returns to allow the hand-over and raises to refuse it.
BeforeSend = Callable[[ModelHandoff], Any]

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
    *,
    before_send: BeforeSend,
) -> EmbeddingResult | None:
    """Embed active assertions once per capture/content/model version, including concurrent jobs.

    Workspace provisioning must already have created its vector partition. Never create schema
    at runtime. A session lock per capture serializes this pass, and no transaction is open while
    the model runs. The text is read first, with every saved name in it replaced; ``before_send``
    is then called on the idle connection with the embedding role's whole chain and its endpoint,
    and a refusal it raises propagates with nothing sent. The write re-reads the text and stores
    nothing when it changed or went, and the
    insert's tombstone guard refuses a deletion that arrived while the model ran. No response cache
    retains deleted caption text.

    Returns the model's result whenever a request was sent, so its cost is counted, and None when
    nothing was sent.
    """
    if not callable(before_send):
        raise TypeError("caption text is sent only after a before_send check")
    # A later search-path schema can have newer migrations. Its lifecycle guard does not
    # protect embedding rows in the active schema.
    if (
        connection.execute(
            "select to_regprocedure(format("
            "'%I.caption_vector_purge_is_authorized(uuid,uuid,uuid)',current_schema())) as guard"
        ).fetchone()["guard"]
        is None
    ):
        raise RuntimeError("Caption indexing requires lifecycle migration 0044")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("caption text is handed to a model only from an idle connection")
    lock = f"companion-embedding:{workspace_id}:{capture_id}"
    connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (lock,))
    try:
        with connection.transaction():
            source = _source(connection, workspace_id, capture_id)
            if source is None:
                return None
            model = client.manifest[Role.EMBEDDING].primary.model_id
            version = client.manifest.pipeline_version
            family = _family(source["body"])
            key = uuid.uuid5(
                workspace_id, f"{capture_id}:{family}:{model}:{version}:{PROMPT_VERSION}"
            )
            if _stored(connection, workspace_id, key):
                return None
            sent = redact_names(source["body"], saved_names(connection, workspace_id)).text
        before_send(ModelHandoff.hosted(client.manifest, Role.EMBEDDING))
        result = client.embed(
            [sent], role=Role.EMBEDDING, prompt_version=PROMPT_VERSION, use_cache=False
        )
        if result.model_id != model or len(result.vectors) != 1:
            raise ValueError("The embedding role returned an unexpected model or vector count")
        vector = QueryEmbedding(result.vectors[0], result.model_id, version)
        with connection.transaction():
            current = _source(connection, workspace_id, capture_id)
            if (
                current is None
                or current["span_id"] != source["span_id"]
                or _family(current["body"]) != family
                or _stored(connection, workspace_id, key)
            ):
                return result
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
    finally:
        if not connection.closed:
            connection.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (lock,))


class CaptionEmbeddingPass:
    """The derivative worker's caption vector pass over one configured client.

    States the models it reaches, so the worker can ask for the right to reach them, and sends
    nothing until the worker's ``before_send`` allows it.
    """

    def __init__(self, client: ModelClient) -> None:
        self.client = client

    @property
    def model_handoff(self) -> ModelHandoff:
        """The embedding role's whole chain, at the endpoint of the client's manifest."""
        return ModelHandoff.hosted(self.client.manifest, Role.EMBEDDING)

    def __call__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        capture_id: uuid.UUID,
        *,
        before_send: BeforeSend,
    ) -> EmbeddingResult | None:
        return embed_capture(
            connection, workspace_id, capture_id, self.client, before_send=before_send
        )


def _source(
    connection: psycopg.Connection, workspace_id: uuid.UUID, capture_id: uuid.UUID
) -> dict[str, Any] | None:
    return connection.execute(
        "select * from (" + SOURCE_SQL + ") source where capture_id=%s",
        (workspace_id, list(SEARCHABLE_PREDICATES), capture_id),
    ).fetchone()


def _family(body: str) -> str:
    return FAMILY_PREFIX + hashlib.sha256(body.encode()).hexdigest()


def _stored(connection: psycopg.Connection, workspace_id: uuid.UUID, key: uuid.UUID) -> bool:
    return (
        connection.execute(
            "select 1 from embedding where workspace_id=%s and embedding_id=%s",
            (workspace_id, key),
        ).fetchone()
        is not None
    )
