"""Record lossless normalized pixels while retaining HEIF camera bytes as evidence."""

from __future__ import annotations

import io

from PIL import Image

from exulanica.canonical import sha256_of_canonical
from exulanica.corpus.decode import decoder_inventory
from exulanica.evidence.blob import BlobId
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.ingest.spine.source_inputs import record_decoded
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites
from exulanica.reconstruction.source_lineage import DECODED_PARAMS, DECODED_PROFILE


def run(
    writes: StageWrites,
    blob_id: BlobId,
    upright: Image.Image,
    intake: StageResult,
    ledger: Ledger,
    outcome: IngestOutcome,
) -> StageResult:
    spec = stage("decoded_source")
    decoder = decoder_inventory()
    input_digest = input_digest_of([intake.content_sha256, sha256_of_canonical(decoder)])
    key = idempotency_key(blob_id, spec, input_digest)
    # The persisted PNG is the exact input all later consumers load. Strip metadata explicitly,
    # including ICC/EXIF, because copying Image.info can reapply orientation or change colors.
    rgb = upright.convert("RGB")
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())
    stream = io.BytesIO()
    clean.save(stream, format="PNG", compress_level=DECODED_PARAMS["compress_level"])
    payload = stream.getvalue()
    record = {
        "profile": DECODED_PROFILE,
        "source_sha256": blob_id.hex,
        "output_sha256": BlobId.of_bytes(payload).hex,
        "decoder": decoder,
        "parameters": spec.params,
        "pixel_grid": {
            "width": clean.width,
            "height": clean.height,
            "orientation": 1,
            "convention": DECODED_PARAMS["pixel_grid"],
        },
    }
    with (
        ledger.stage(spec, input_artifact_ids=[intake.artifact_id], input_blob=blob_id) as recorder,
        writes.committed_writes() as pending,
    ):
        result = writes.persist_artifact(
            spec=spec,
            blob_id=blob_id,
            key=key,
            input_digest=input_digest,
            payload=payload,
            recorder=recorder,
            outcome=outcome,
            pending=pending,
            produced_by_event=recorder.stage_started_event,
        )
        record_decoded(
            WorkspaceScope(writes.repository.connection, writes.repository.workspace_id),
            result.artifact_id,
            record,
        )
    return result
