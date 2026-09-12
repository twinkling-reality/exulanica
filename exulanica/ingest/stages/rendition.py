"""Stage 2. A 768 px display-space JPEG with no EXIF: the only pixels a model ever sees.

The short circuit at the top is not an optimisation with a correctness caveat. A rendition that
is already encoded and already in the store is the finished output of this stage, and decoding
the original again to rebuild bytes that exist would be the expensive way to reach the same
artifact row. The reuse is still recorded, because a stage satisfied without running is a step
in the graph and the Assembly Replay is generated from the ledger and from nothing else.
"""

from __future__ import annotations

from PIL import Image

from exulanica.evidence.blob import BlobId
from exulanica.ingest.derivatives import render
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites

__all__ = ["run"]


def run(
    writes: StageWrites,
    blob_id: BlobId,
    upright: Image.Image,
    intake: StageResult,
    ledger: Ledger,
    outcome: IngestOutcome,
    decoded: StageResult | None = None,
    decoded_receipt_sha256: bytes | None = None,
) -> StageResult:
    spec = stage("rendition")
    input_digest = input_digest_of(
        [
            intake.content_sha256,
            *([decoded.content_sha256] if decoded is not None else []),
            *([decoded_receipt_sha256] if decoded_receipt_sha256 is not None else []),
        ]
    )
    key = idempotency_key(blob_id, spec, input_digest)
    existing = writes.repository.find_artifact(key)
    if (
        existing is not None
        and existing.content_sha256 is not None
        and writes.store.exists(BlobId(existing.content_sha256))
    ):
        # The whole file is already encoded and stored. No decode, no resample, no write.
        # Recorded, because a stage satisfied without running is still a step in the DAG and
        # the replay is generated from the ledger and from nothing else.
        outcome.stages_reused.append(spec.key)
        ledger.reused(spec, existing.artifact_id, input_blob=blob_id)
        return StageResult(
            artifact_id=existing.artifact_id,
            content_sha256=existing.content_sha256,
            idempotency_key=key,
            reused=True,
        )
    with ledger.stage(
        spec,
        input_artifact_ids=[intake.artifact_id, *([decoded.artifact_id] if decoded else [])],
        input_blob=blob_id,
    ) as recorder:
        encoded = render(upright, spec)
        with writes.committed_writes() as pending:
            result = writes.persist_artifact(
                spec=spec,
                blob_id=blob_id,
                key=key,
                input_digest=input_digest,
                payload=encoded.data,
                recorder=recorder,
                outcome=outcome,
                pending=pending,
                produced_by_event=recorder.stage_started_event,
            )
    return result
