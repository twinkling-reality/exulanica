"""What a stage is handed, and the one shape every stage returns.

``StageWrites`` is the complete surface a stage module may reach for. ``PhotoIngestPipeline``
satisfies it and holds several other things a stage has no business touching, which is the
reason this Protocol exists rather than the stages taking the pipeline and helping themselves:
a stage that needs something new has to widen this list, in this file, and say why. The
alternative is four modules that each grew their own idea of what the sequencer owes them.

The two members that are not plain accessors are the two guarantees:

*   ``committed_writes`` is the ordering that makes deletion stick. Bytes reach the object
    store only after the transaction that permitted them has committed, so a tombstone
    discovered inside that transaction leaves the store exactly as it found it.
*   ``persist_artifact`` is the only place an artifact row is written, and the only place the
    outcome learns whether a stage ran or was satisfied from an existing row. Recording that
    twice is not a cosmetic bug: it printed ``depth+depth`` in the command line summary once.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from exulanica.evidence.blob import BlobId
from exulanica.ingest.ledger import StageRecorder
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import StageSpec
from exulanica.store.base import ContentAddressedStore

__all__ = ["StageResult", "StageWrites"]


@dataclass(frozen=True, slots=True)
class StageResult:
    """A stage's output artifact, and whether it had to be produced."""

    artifact_id: uuid.UUID
    content_sha256: bytes
    idempotency_key: str
    reused: bool


class StageWrites(Protocol):
    """The sequencer, narrowed to what a stage is permitted to use."""

    @property
    def repository(self) -> IngestRepository: ...

    @property
    def store(self) -> ContentAddressedStore: ...

    def committed_writes(self) -> AbstractContextManager[list[bytes]]: ...

    def persist_artifact(
        self,
        *,
        spec: StageSpec,
        blob_id: BlobId,
        key: str,
        input_digest: bytes,
        payload: bytes,
        recorder: StageRecorder,
        outcome: IngestOutcome,
        pending: list[bytes],
        produced_by_event: uuid.UUID | None = None,
        privacy_screening_id: uuid.UUID | None = None,
    ) -> StageResult: ...
