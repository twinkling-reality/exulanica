"""Stage 4. One photograph becomes a metric point map, and the rung it earned is recorded.

**The point map is an artifact and never a blob.** Invariant 2: reconstruction is never
evidence. An ``evidence_span`` references ``blob``, artifacts do not live there, and so a point
map has nothing a citation could point at. That is structural rather than guarded, and
``tests/test_reconstruction_is_not_evidence.py`` asserts it from four directions.

**The rung is a proposal about presentation, not a claim about the world.** It is written as an
inference-class assertion on the capture, which is the only class it could honestly take: a
model looked at a photograph and reported how much of it could be placed. It supports no
historical clause and could not, because the vocabulary refuses.

With no depth model configured the compatibility summary still lists the stage as skipped, while
the durable ledger records the sharper `stage_unavailable` fact. A capture with no point map is a
rung 4 region, which is a real rung with a real experience, and the absence of an implementation
is not the same fact as a stage that failed.
"""

from __future__ import annotations

import uuid

from PIL import Image

from exulanica.evidence.blob import BlobId
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.privacy import require_privacy_screening
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites
from exulanica.reconstruction import (
    DepthModel,
    DepthPrediction,
    RungDecision,
    Viewpoint,
    build_point_map,
    decide_rung,
    encode_opm,
    validate_opm,
)

__all__ = ["run"]


def run(
    writes: StageWrites,
    model: DepthModel | None,
    binding: dict[str, str] | None,
    blob_id: BlobId,
    upright: Image.Image,
    capture_id: uuid.UUID,
    image_span_id: uuid.UUID,
    intake: StageResult,
    ledger: Ledger,
    outcome: IngestOutcome,
    privacy_screening_id: uuid.UUID | None,
    masked: StageResult | None = None,
    decoded: StageResult | None = None,
    decoded_receipt_sha256: bytes | None = None,
    masked_image: Image.Image | None = None,
    consent_digests: tuple[bytes, ...] = (),
) -> None:
    spec = stage("depth")
    if model is None:
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec,
            reason="no depth model is configured for this worker",
            input_blob=blob_id,
        )
        return

    if privacy_screening_id is None:
        from exulanica.errors import PrivacyAdmissionError

        raise PrivacyAdmissionError(
            "point-map inference requires an exact eligible privacy screening receipt"
        )
    screening = require_privacy_screening(writes.repository, capture_id, privacy_screening_id)

    # The confirmed regions and the consent states in force are part of what this point map was
    # computed from, so they belong in its key. Without them a revoked likeness would find the
    # existing point map by key and reuse it, and the person who withdrew would stay in the
    # geometry while every receipt said they had gone.
    input_digest = input_digest_of(
        [
            intake.content_sha256,
            screening.receipt_digest,
            *consent_digests,
            *([masked.content_sha256] if masked is not None else []),
            *([decoded.content_sha256] if decoded is not None else []),
            *([decoded_receipt_sha256] if decoded_receipt_sha256 is not None else []),
        ]
    )
    key = idempotency_key(blob_id, spec, input_digest, binding=binding)
    existing = writes.repository.find_artifact(key)
    if existing is not None:
        outcome.stages_reused.append(spec.key)
        ledger.reused(spec, existing.artifact_id, input_blob=blob_id)
        return

    with ledger.stage(
        spec,
        input_artifact_ids=[
            intake.artifact_id,
            *([decoded.artifact_id] if decoded else []),
            *([masked.artifact_id] if masked else []),
        ],
        input_blob=blob_id,
    ) as recorder:
        # The masked derivative when anybody in this photograph is hidden, the original otherwise.
        # This is the line that makes "mask before, not only after" true: a person who never
        # consented is neutral fill before the depth model sees a pixel, so they cannot become a
        # point map, and therefore cannot become Gaussians further down.
        source = masked_image if masked_image is not None else upright
        prediction = model.predict(source)
        points = build_point_map(
            prediction,
            source,
            max_depth_step=int(spec.params["max_depth_step_milli"]) / 1000,
        )
        decision = decide_rung(
            prediction,
            min_valid_fraction=int(spec.params["min_valid_fraction_milli"]) / 1000,
        )
        payload = encode_opm(
            points,
            generator=prediction.model_id,
            viewpoint=Viewpoint(
                fov_y_degrees=prediction.fov_y_degrees,
                # The SOURCE camera's aspect, not the model's working resolution.
                #
                # CORRECTED 2026-09-03. This read `prediction.width / prediction.height`, and both
                # validators check the declared aspect against `sourceImage`, which is the source
                # photograph's own dimensions. A model that downscales to a longest edge rounds to
                # whole pixels, so a 3:2 photograph became 512x341 and declared 1.5015 against a
                # source of 1.5, and every validator refused it. Measured: 1280x960 passed and both
                # 1500x1000 and 3000x2000 raised "viewpoint.aspect does not match sourceImage", so
                # the depth stage could reconstruct nothing but exactly 4:3 sources.
                #
                # The frustum this field describes is the camera that took the photograph, and the
                # only faithful statement of its shape is the photograph's own dimensions. The
                # vertical field of view beside it comes from the model because it is what the
                # model recovered, and a resize preserves it; the aspect does not come from the
                # model because a rounded working grid is an implementation detail of inference.
                aspect=source.width / max(1, source.height),
            ),
            source_size=source.size,
            # The grid the points were unprojected from, which OPM/2 states beside the
            # photograph rather than leaving to be inferred from a point count (ADR-0010 D6).
            # The two differ by the model's own rounding and both are facts the renderer needs:
            # the source frustum places the camera, and the model lattice is what a load-time
            # tangent frame is estimated on.
            model_size=(prediction.width, prediction.height),
            # What `build_point_map` actually put in the alpha channel. Support and not
            # confidence: it is a spacing ratio, which is coverage, counted rather than believed.
            # Declared rather than left for a renderer to infer from the presence of a statistics
            # key, which is the format flag nobody declared as one that ADR-0010 D5 closes.
            color_alpha="support",
            # Carried from the model rather than assumed. A map that is not metric produces a
            # region that is not metric, and a spatial question over it refuses with a stated
            # reason instead of estimating a distance.
            metric=prediction.metric,
        )
        # Refuse malformed bytes before they can become a durable artifact. The browser validates
        # again at its trust boundary, but that is not a reason to publish something it will reject.
        validate_opm(payload)
        with writes.committed_writes() as pending:
            result = writes.persist_artifact(
                spec=spec,
                blob_id=blob_id,
                key=key,
                input_digest=input_digest,
                payload=payload,
                recorder=recorder,
                produced_by_event=recorder.stage_started_event,
                outcome=outcome,
                pending=pending,
                privacy_screening_id=screening.screening_id,
                # Names the exact bytes the model read. Migration 0037's trigger refuses this row
                # when the capture requires masking and this is null or names anything but a real
                # masked derivative of it.
                read_source_sha256=(
                    masked.content_sha256
                    if masked is not None
                    else decoded.content_sha256
                    if decoded is not None
                    else None
                ),
            )
            _record_rung(writes, capture_id, image_span_id, decision, result, prediction, ledger)
    # `persist_artifact` already recorded the stage as run. Appending it here as well is what
    # printed "depth+depth" in the command line's per-file summary.


def _record_rung(
    writes: StageWrites,
    capture_id: uuid.UUID,
    image_span_id: uuid.UUID,
    decision: RungDecision,
    result: StageResult,
    prediction: DepthPrediction,
    ledger: Ledger,
) -> None:
    """Write the rung as what it is: something a model inferred about a photograph.

    ``inference`` and not ``capture``. A capture-supported fact is a deterministic property of
    the bytes, and how much of a frame a neural network could place is not one: a different
    checkpoint would give a different answer over the same file. Filing it as capture would be
    the exact flattening invariant 4 forbids.

    **It cites the photograph, not the point map**, and the support-span rule is what forced
    the question. An inference must name at least one evidence span, so a rung had to point at
    something; the only honest answer is the frame the model looked at. Citing the point map
    would have required the point map to be evidence, which is the thing invariant 2 exists to
    prevent, and the constraint refused it before anybody had to notice.
    """
    assertion_id = writes.repository.insert_assertion(
        kind="inference",
        predicate_key="reconstruction_rung_is",
        subject_ref={"type": "capture", "id": str(capture_id)},
        object_value={
            **decision.as_payload(),
            "model_id": prediction.model_id,
            "metric": prediction.metric,
            # The artifact id, so an interface explaining a rung can open the map it is
            # about. An artifact id and an evidence address are not the same kind of thing
            # and this is not a citation: nothing resolves it through the evidence route.
            "point_map_artifact": str(result.artifact_id),
        },
        emit_key=f"{result.idempotency_key}:rung",
        support_span_ids=[image_span_id],
        produced_by_run=ledger.run_id,
    )
    if assertion_id is not None:
        ledger.emitted("assertion", [assertion_id], stage("depth"))
