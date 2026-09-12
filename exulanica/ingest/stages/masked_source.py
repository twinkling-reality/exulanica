"""Stage 6. The photograph reconstruction is allowed to read.

**This is the stage that makes "mask before, not only after" true.** Depth, pose, placement and
training read this derivative when anybody in the photograph is hidden, so a person who never
consented never becomes depth, point maps or Gaussians in the first place. Hiding them in the
renderer instead would leave their body in the geometry, recoverable by anybody who fetched the
bytes, and would make every consent decision a promise about the client rather than about the
world. The one exception is deliberate: a person who consented to their likeness and is
temporarily hidden keeps their geometry, because that state is reversible and rebuilding the
world on a toggle would make it useless.

**Its digest is what turns a changed mind into a new build.** The input digest covers the exact
source bytes, the confirmed region set and the resolved consent states. Any of the three moving
moves this artifact's key, which moves the depth key, which moves the scene build inputs. So a
revoked consent produces a new build and never mutates an accepted one, and that property is
inherited from the existing idempotency rules rather than added by a new mechanism.

**No masks means no artifact.** A photograph where everybody has consented produces nothing here
and reconstruction reads the original, which is what the design's state table says and also what
keeps the store from holding a re-encoded copy of every photograph in a corpus with nobody in it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from PIL import Image

from exulanica.consent.regions import Silhouette
from exulanica.consent.states import ResolvedPresentation
from exulanica.evidence.blob import BlobId
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.masking import encode_masked_source, mask_image
from exulanica.ingest.person_receipts import (
    consent_state_digest,
    masked_source_manifest,
    region_set_digest,
)
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites

__all__ = ["hidden_outlines", "masked_source_input_digest", "masked_source_key", "run"]


def hidden_outlines(
    regions: Mapping[bytes, Silhouette], resolved: Mapping[bytes, ResolvedPresentation]
) -> tuple[Silhouette, ...]:
    """The outlines that must be filled, ordered by region key.

    A region with no resolved state is masked rather than skipped. That is default deny at the
    one place it would be easiest to lose it: a lookup miss here would silently reveal exactly
    the person whose state nobody had recorded.
    """
    return tuple(
        regions[key] for key in sorted(regions) if key not in resolved or resolved[key].masked
    )


def masked_source_input_digest(
    *,
    intake_sha256: bytes,
    capture_id: uuid.UUID,
    blob_id: BlobId,
    regions: Mapping[bytes, Silhouette],
    resolved: Mapping[bytes, ResolvedPresentation],
    predecessor_sha256: bytes | None = None,
    decoded_receipt_sha256: bytes | None = None,
) -> bytes:
    """The three inputs that decide whether a derivative is still the right one, folded.

    Separate from :func:`masked_source_key` only because :func:`run` records this digest on the
    ledger row beside the key. Everything that decides currency is in here.
    """
    return input_digest_of(
        [
            intake_sha256,
            *([predecessor_sha256] if predecessor_sha256 is not None else []),
            *([decoded_receipt_sha256] if decoded_receipt_sha256 is not None else []),
            region_set_digest(capture_id=capture_id, source_sha256=blob_id.hex, regions=regions),
            consent_state_digest(
                capture_id=capture_id, source_sha256=blob_id.hex, resolved=resolved
            ),
        ]
    )


def masked_source_key(
    *,
    intake_sha256: bytes,
    capture_id: uuid.UUID,
    blob_id: BlobId,
    regions: Mapping[bytes, Silhouette],
    resolved: Mapping[bytes, ResolvedPresentation],
    predecessor_sha256: bytes | None = None,
    decoded_receipt_sha256: bytes | None = None,
) -> bytes:
    """The key the derivative for this photograph must carry to be the CURRENT one.

    Exported so that "is this photograph's mask up to date" has one derivation and two callers
    rather than a second implementation growing beside the first. :func:`run` writes the artifact
    under this key and ``exulanica.ingest.masked_inputs`` asks whether one exists under it. A
    screening rule that answered that question with its own arithmetic would drift, and the
    direction it would drift is a photograph admitted against a mask built before somebody changed
    their mind.

    All three inputs are load bearing, and the module docstring says why the third is: the
    resolved consent states are inside the key, so a revoked consent produces a different key and
    the old derivative stops being current rather than being quietly reused.
    """
    return idempotency_key(
        blob_id,
        stage("masked_source"),
        masked_source_input_digest(
            intake_sha256=intake_sha256,
            capture_id=capture_id,
            blob_id=blob_id,
            regions=regions,
            resolved=resolved,
            predecessor_sha256=predecessor_sha256,
            decoded_receipt_sha256=decoded_receipt_sha256,
        ),
    )


def run(
    writes: StageWrites,
    blob_id: BlobId,
    upright: Image.Image,
    capture_id: uuid.UUID,
    regions: Mapping[bytes, Silhouette],
    resolved: Mapping[bytes, ResolvedPresentation],
    subjects: Mapping[bytes, uuid.UUID | None],
    intake: StageResult,
    ledger: Ledger,
    outcome: IngestOutcome,
    *,
    decoded: StageResult | None = None,
    decoded_receipt_sha256: bytes | None = None,
) -> StageResult | None:
    """Produce the masked derivative and its manifest, or nothing when nobody is hidden."""
    spec = stage("masked_source")
    outlines = hidden_outlines(regions, resolved)
    if not outlines:
        return None
    input_digest = masked_source_input_digest(
        intake_sha256=intake.content_sha256,
        capture_id=capture_id,
        blob_id=blob_id,
        regions=regions,
        resolved=resolved,
        predecessor_sha256=None if decoded is None else decoded.content_sha256,
        decoded_receipt_sha256=decoded_receipt_sha256,
    )
    key = idempotency_key(blob_id, spec, input_digest)
    existing = writes.repository.find_artifact(key)
    if (
        existing is not None
        and existing.content_sha256 is not None
        and writes.store.exists(BlobId(existing.content_sha256))
    ):
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
        payload = encode_masked_source(
            mask_image(
                upright, outlines, dilation_millionths=int(spec.params["dilation_millionths"])
            ),
            spec.params,
        )
        with writes.committed_writes() as pending:
            masked = writes.persist_artifact(
                spec=spec,
                blob_id=blob_id,
                key=key,
                input_digest=input_digest,
                payload=payload,
                recorder=recorder,
                outcome=outcome,
                pending=pending,
                produced_by_event=recorder.stage_started_event,
                read_source_sha256=None if decoded is None else decoded.content_sha256,
            )
    _manifest(
        writes,
        blob_id=blob_id,
        capture_id=capture_id,
        masked=masked,
        regions=regions,
        resolved=resolved,
        subjects=subjects,
        predecessor_sha256=None if decoded is None else decoded.content_sha256,
        decoded_receipt_sha256=decoded_receipt_sha256,
        ledger=ledger,
        outcome=outcome,
    )
    return masked


def _manifest(
    writes: StageWrites,
    *,
    blob_id: BlobId,
    capture_id: uuid.UUID,
    masked: StageResult,
    regions: Mapping[bytes, Silhouette],
    resolved: Mapping[bytes, ResolvedPresentation],
    subjects: Mapping[bytes, uuid.UUID | None],
    predecessor_sha256: bytes | None,
    decoded_receipt_sha256: bytes | None,
    ledger: Ledger,
    outcome: IngestOutcome,
) -> StageResult:
    """Record whose each mask is, in its own artifact row.

    Its own row rather than a field on the image because both have to be reachable by the
    tombstone and purge paths: a withdrawal looking for what to destroy has to be able to find
    the record of whose body was hidden, and a manifest living only inside the image's metadata
    would not be found by it.
    """
    spec = stage("masked_source_manifest")
    masked_spec = stage("masked_source")
    input_digest = input_digest_of([masked.content_sha256])
    key = idempotency_key(blob_id, spec, input_digest)
    existing = writes.repository.find_artifact(key)
    if existing is not None and existing.content_sha256 is not None:
        outcome.stages_reused.append(spec.key)
        ledger.reused(spec, existing.artifact_id, input_blob=blob_id)
        return StageResult(
            artifact_id=existing.artifact_id,
            content_sha256=existing.content_sha256,
            idempotency_key=key,
            reused=True,
        )
    _identifier, _record, canonical, _digest = masked_source_manifest(
        workspace_id=writes.repository.workspace_id,
        capture_id=capture_id,
        source_sha256=blob_id.hex,
        masked_sha256=masked.content_sha256.hex(),
        predecessor_sha256=None if predecessor_sha256 is None else predecessor_sha256.hex(),
        decoded_receipt_sha256=None
        if decoded_receipt_sha256 is None
        else decoded_receipt_sha256.hex(),
        stage_version=masked_spec.version,
        dilation_millionths=int(masked_spec.params["dilation_millionths"]),
        masks=[
            (
                key_bytes,
                subjects.get(key_bytes),
                resolved[key_bytes].state if key_bytes in resolved else "unknown",
            )
            for key_bytes in sorted(regions)
            if key_bytes not in resolved or resolved[key_bytes].masked
        ],
    )
    with (
        ledger.stage(spec, input_artifact_ids=[masked.artifact_id], input_blob=blob_id) as recorder,
        writes.committed_writes() as pending,
    ):
        return writes.persist_artifact(
            spec=spec,
            blob_id=blob_id,
            key=key,
            input_digest=input_digest,
            payload=canonical,
            recorder=recorder,
            outcome=outcome,
            pending=pending,
            produced_by_event=recorder.stage_started_event,
        )
