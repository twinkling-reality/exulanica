"""Stage 1. Hash the bytes, read EXIF, register the capture, and file what the file itself says.

The source bytes, the single-sample ``img`` track, the wall-clock anchor, the whole-image span,
and the capture-supported assertions. Everything written here is a deterministic property of
the file. Everything a photograph merely suggests is inference and none of it is written here.
"""

from __future__ import annotations

import uuid
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.ingest.exif import ExifFacts
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites

__all__ = ["key_for", "run"]


def key_for(blob_id: BlobId) -> str:
    """This stage's idempotency key for these bytes, computed in exactly one place.

    The pipeline recovers a committed intake artifact by this key when the derivative stages run
    in a different process from the one that admitted the photograph. Two copies of the
    expression would be two things that can drift, and the symptom of drift is a worker that
    reports a photograph as never intaken while its artifact row sits in the table.
    """
    return idempotency_key(blob_id, stage("intake"), input_digest_of([]))


def run(
    writes: StageWrites,
    blob_id: BlobId,
    data: bytes,
    display_size: tuple[int, int],
    facts: ExifFacts,
    ledger: Ledger,
    outcome: IngestOutcome,
) -> tuple[StageResult, uuid.UUID, uuid.UUID]:
    """Returns the intake artifact, the capture it registered, and the whole-image span id."""
    spec = stage("intake")
    input_digest = input_digest_of([])
    key = key_for(blob_id)
    probe_bytes = canonical_json(facts.as_probe_json())
    repository = writes.repository

    with ledger.stage(spec, input_blob=blob_id) as recorder:
        with writes.committed_writes() as pending:
            # THE SAME LOCK THE PURGER TAKES, and taking it here is the whole of what makes it
            # a lock rather than a formality.
            #
            # `orimera/deletion/worker.py` holds `purge_lock_object(<content hash>)` across
            # asking whether the bytes may go and destroying them. That serialises purger
            # against purger. It does NOT serialise a purger against an ingest, and measured
            # without this line: workspace A's purger asks the question, workspace B commits a
            # live capture of the same bytes in the window, and the purger then destroys an
            # object B is using. B has no tombstone, has deleted nothing, and its photograph is
            # gone with nothing reporting it. `blob` is not workspace-scoped, so the natural
            # path there is the DEDUPLICATION path, where this ingest writes no bytes at all
            # because they were already present.
            #
            # With it, the ingest waits for the purge to commit and then writes the bytes back
            # through `committed_writes`, which is the correct outcome: a deliberate re-import
            # gets its own copy.
            repository.lock_stored_object(blob_id)
            # Queued, not written. The source bytes land in the store only once the whole
            # intake transaction has committed, so a tombstone that fires on ``upsert_span``
            # below leaves the store exactly as it found it.
            pending.append(data)
            repository.upsert_blob(
                blob_id,
                byte_size=len(data),
                media_type=facts.media_type,
                storage_key=writes.store.key_for(blob_id),
            )
            capture = repository.live_capture_for_blob(blob_id)
            if capture is None:
                capture = repository.insert_capture(
                    blob_id,
                    device_id=facts.device_id,
                    started_at=facts.clock.utc.isoformat() if facts.clock else None,
                )
            track_id = repository.upsert_image_track(
                blob_id,
                coded_w=facts.coded_width,
                coded_h=facts.coded_height,
                disp_w=display_size[0],
                disp_h=display_size[1],
                # Zero, not the rotation that was applied. The column means "still to apply"
                # (ADR-0012), the pixels behind disp_w/disp_h are already upright, and what was
                # applied is in probe_json -> 'orientation' where nothing hashes it.
                rotation=0,
                codec=facts.codec,
                probe_json=facts.as_probe_json(),
            )
            if facts.clock is not None:
                repository.insert_clock_anchor(
                    track_id,
                    utc_instant=facts.clock.utc.isoformat(),
                    source=facts.clock.source,
                    uncertainty_ms=facts.clock.uncertainty_ms,
                )
            image_address = EvidenceAddress.photograph(blob_id)
            image_span_id = repository.upsert_span(image_address)
            result = writes.persist_artifact(
                spec=spec,
                blob_id=blob_id,
                key=key,
                input_digest=input_digest,
                payload=probe_bytes,
                recorder=recorder,
                outcome=outcome,
                pending=pending,
                produced_by_event=recorder.stage_started_event,
            )
            emitted = _capture_assertions(
                writes, facts, capture.capture_id, image_span_id, key, ledger
            )
        ledger.emitted("assertion", emitted, spec)
    return result, capture.capture_id, image_span_id


def _capture_assertions(
    writes: StageWrites,
    facts: ExifFacts,
    capture_id: uuid.UUID,
    image_span_id: uuid.UUID,
    key: str,
    ledger: Ledger,
) -> list[uuid.UUID]:
    """The whole of the ``capture`` class for a photograph, and nothing more.

    File hash, byte size, pixel dimensions, EXIF device model, EXIF timestamps, EXIF GPS.
    Everything else a photograph "says" is inference, and none of it is written here.
    """
    subject = {"type": "capture", "id": str(capture_id)}
    support = [image_span_id]
    claims: list[tuple[str, Any]] = [
        ("pixel_size_is", {"w": facts.display_width, "h": facts.display_height}),
    ]
    if facts.clock is not None:
        claims.append(("captured_at", facts.clock.utc.isoformat()))
    if facts.device_id is not None:
        claims.append(("device_model_is", facts.device_id))
    if facts.gps is not None:
        claims.append(("gps_position_is", facts.gps.as_object_value()))
    emitted: list[uuid.UUID] = []
    for ordinal, (predicate_key, value) in enumerate(claims):
        assertion_id = writes.repository.insert_assertion(
            kind="capture",
            predicate_key=predicate_key,
            subject_ref=subject,
            object_value=value,
            emit_key=f"{key}:a:{ordinal}",
            support_span_ids=support,
            produced_by_run=ledger.run_id,
        )
        if assertion_id is not None:
            emitted.append(assertion_id)
    return emitted
