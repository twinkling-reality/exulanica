"""Stage 3. One structured call over the rendition, filed as inference and never as anything else.

Every row this stage writes is ``kind='inference'`` and carries at least one evidence address.
There is no branch that could write one as ``capture``: the predicate vocabulary refuses it at
the data layer, so the discipline here is a convenience and the guarantee is in the schema.

The reuse branch is the whole cost control. A second run of a directory reaches it for every
photograph and issues no model call at all. It is also where an edited prompt or a swapped
model correctly misses, because both are inside the key: the prompt through
``params["prompt_sha256"]`` and the model through the run-time binding.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, Final

from exulanica.evidence import PHOTOGRAPH_INTERVAL, EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import DisplayGeometry, Rect, Region
from exulanica.identity.keys import occurrence_identity_key
from exulanica.ingest.exif import ExifFacts
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.privacy import require_privacy_screening
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites
from exulanica.ingest.vision import (
    OBSERVATION_SCHEMA_NAME,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    VisionModel,
    VisionObservation,
    prompt_digest,
)

__all__ = ["run"]

#: Written onto every occurrence this stage creates, so a re-run at a new version is
#: distinguishable in the ledger from the same detector running twice.
DETECTOR_VERSION: Final = "vision:1"


def run(
    writes: StageWrites,
    model: VisionModel | None,
    binding: dict[str, str] | None,
    blob_id: BlobId,
    rendition: StageResult,
    capture_id: uuid.UUID,
    image_span_id: uuid.UUID,
    facts: ExifFacts,
    ledger: Ledger,
    outcome: IngestOutcome,
    privacy_screening_id: uuid.UUID | None = None,
) -> StageResult | None:
    """Observe one photograph, or report honestly that nothing looked.

    Returns its ``StageResult`` so a later stage can read the observation it stored. ``None`` means
    no observation exists, which is not the same fact as an observation that found nobody: the
    person-region stage treats a missing observation as unscreened rather than as empty.

    **This stage sends the photograph to a model, so it is gated like the one that reconstructs
    it.** Until 2026-09-06 it was not: depth required an eligible screening receipt and vision
    required nothing, which meant the first thing to touch a photograph after intake handed it to
    a hosted service with no authorization recorded anywhere. That is the wrong way round. Vision
    is also the stage that now enumerates every visible trace of a person, so running it ungated
    would locate people in order to protect them by first sending them somewhere else.

    The screening's digest is deliberately NOT in the input digest, unlike depth's. Re-recording a
    screening does not change what is in the photograph, and keying on it would re-bill a model
    call every time a receipt was superseded. The receipt id is recorded on the artifact instead,
    so the provenance is kept without paying for it twice.
    """
    spec = stage("vision")
    if model is None:
        # Checked before the key rather than after it. The key names the model that will
        # produce the output, and with no model configured there is no such name, so there
        # is no key to look an artifact up by. Reporting this as skipped rather than reused
        # is also the more honest of the two: this run did not process vision.
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec,
            reason="no vision model is configured for this worker",
            input_blob=blob_id,
        )
        return None
    if privacy_screening_id is None:
        # Unavailable, not failed, and the distinction is the same one the no-model branch above
        # draws. Nothing went wrong: nobody has authorized sending this photograph to a model, so
        # it was not sent. Raising instead would make the one-shot ingest path impossible rather
        # than merely quiet, because a screening is keyed to a capture that does not exist until
        # intake has run; and an ingest that errors on every unscreened photograph is an ingest
        # somebody switches off. The ledger records the reason either way, and the important
        # property holds: no bytes left this machine.
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec,
            reason="no privacy screening receipt authorizes sending these bytes to a model",
            input_blob=blob_id,
        )
        return None
    # An expired, blocked, withdrawn or superseded receipt DOES raise. Having looked and been
    # refused is not the same as never having asked, and a photograph whose screening was
    # revoked must not keep being observed on the strength of an old one.
    screening = require_privacy_screening(writes.repository, capture_id, privacy_screening_id)
    input_digest = input_digest_of([rendition.content_sha256])
    key = idempotency_key(blob_id, spec, input_digest, binding=binding)
    existing = writes.repository.find_artifact(key)
    if existing is not None:
        # The whole cost control, in one branch: the second run of a directory reaches this
        # line for every photograph and issues no model call at all. It is also where an
        # edited prompt or a swapped model correctly misses, because both are inside the
        # key: the prompt through ``params["prompt_sha256"]`` and the model through the
        # binding.
        outcome.stages_reused.append(spec.key)
        ledger.reused(spec, existing.artifact_id, input_blob=blob_id)
        if existing.content_sha256 is None:
            # A row with no content hash names an output that was never stored, so there is
            # nothing a later stage could read back. Reported as reused, because that is what the
            # ledger records, but not handed on as though an observation existed.
            return None
        return StageResult(
            artifact_id=existing.artifact_id,
            content_sha256=existing.content_sha256,
            idempotency_key=key,
            reused=True,
        )

    image_bytes = writes.store.get(BlobId(rendition.content_sha256))
    with ledger.stage(
        spec, input_artifact_ids=[rendition.artifact_id], input_blob=blob_id
    ) as recorder:
        result = model.observe(image_bytes=image_bytes, media_type="image/jpeg")
        recorder.record_model_call(
            result.model_ref,
            result.cost,
            result.attempts,
            result.tried,
        )
        outcome.model_calls += 1
        outcome.input_tokens += int(result.cost.get("input_tokens", 0))
        outcome.output_tokens += int(result.cost.get("output_tokens", 0))
        outcome.usd_estimate += Decimal(str(result.cost.get("usd_estimate", "0")))

        document = {
            "header": {
                "stage_key": spec.key,
                "stage_version": spec.version,
                "schema_version": SCHEMA_VERSION,
                "schema_name": OBSERVATION_SCHEMA_NAME,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": prompt_digest(),
                "params_digest": spec.params_digest.hex(),
                "model_ref": result.model_ref,
                "models_tried": list(result.tried),
                "usage": result.cost,
                # Everything below is derived from pixels the system did not author, so it
                # is untrusted for every downstream purpose, and anything derived from it
                # inherits the tier. A summary of an injected sign does not become
                # trustworthy by passing through a model once.
                "trust_tier": "T2",
                "epistemic_class": "inference",
            },
            "observation": result.payload,
            # Recorded so the artifact says what the detector called the people it saw.
            # None of these strings is a name and none of them can become one: `occurrence`
            # has no column for a name, and `entity.display_name` is refused by trigger
            # unless an active kind='user' assertion says so.
            "person_labels": result.observation.person_labels,
        }
        with writes.committed_writes() as pending:
            produced = writes.persist_artifact(
                spec=spec,
                blob_id=blob_id,
                key=key,
                input_digest=input_digest,
                payload=_verbatim_json(document),
                recorder=recorder,
                outcome=outcome,
                pending=pending,
                produced_by_event=recorder.stage_started_event,
                privacy_screening_id=screening.screening_id,
            )
            emitted = _observation_rows(
                writes,
                result.observation,
                blob_id=blob_id,
                capture_id=capture_id,
                image_span_id=image_span_id,
                display=DisplayGeometry(w=facts.display_width, h=facts.display_height, rotation=0),
                key=key,
                ledger=ledger,
            )
        ledger.emitted("assertion", emitted, spec)
    return produced


def _observation_rows(
    writes: StageWrites,
    observation: VisionObservation,
    *,
    blob_id: BlobId,
    capture_id: uuid.UUID,
    image_span_id: uuid.UUID,
    display: DisplayGeometry,
    key: str,
    ledger: Ledger,
) -> list[uuid.UUID]:
    """Turn a validated observation into spans, occurrences and inference assertions.

    Every row written here is ``kind='inference'`` and carries at least one evidence
    address. There is no branch that can write one as ``capture``: the predicate vocabulary
    refuses it at the data layer.
    """
    repository = writes.repository
    emitted: list[uuid.UUID] = []
    ordinal = 0

    def emit(**kwargs: Any) -> None:
        nonlocal ordinal
        assertion_id = repository.insert_assertion(
            kind="inference",
            produced_by_run=ledger.run_id,
            emit_key=f"{key}:a:{ordinal}",
            **kwargs,
        )
        ordinal += 1
        if assertion_id is not None:
            emitted.append(assertion_id)

    emit(
        predicate_key="caption_is",
        subject_ref={"type": "capture", "id": str(capture_id)},
        object_value=observation.scene_description,
        support_span_ids=[image_span_id],
    )

    # People first, so their emit-key ordinals are stable as the object list changes.
    for index, person in enumerate(observation.person_traces):
        span_id, address = _region_span(writes, blob_id, person.box, display, image_span_id)
        emit(
            predicate_key="person_present",
            subject_ref={"type": "capture", "id": str(capture_id)},
            support_span_ids=[span_id],
        )
        if address is None:
            # A person with no usable box has no distinguishing evidence address, so every
            # unlocated person in this photograph would share one identity key. Rejection
            # memory is keyed on that, so they would suppress each other's proposals. The
            # claim that somebody is present still stands: it is the assertion above.
            continue
        repository.insert_occurrence(
            capture_id=capture_id,
            occurrence_class="person",
            primary_span_id=span_id,
            span_ids=[span_id],
            presence=[(PHOTOGRAPH_INTERVAL.start_ns, PHOTOGRAPH_INTERVAL.end_ns)],
            produced_by_run=ledger.run_id,
            detector_version=DETECTOR_VERSION,
            identity_key=occurrence_identity_key(address, "person"),
            emit_key=f"{key}:p:{index}",
            quality={
                "confidence_band": person.confidence,
                # Which visible trace this is, from a closed vocabulary. Schema version 1 stored
                # the model's free-text label here instead, and a label is a description of
                # somebody: "woman in a red coat" is exactly the sentence a person who has not
                # consented to being described should not have written about them. A part is
                # where they are, which is all this needs in order to hide them.
                "part": person.part,
                "trust_tier": "T2",
            },
        )

    for index, detected in enumerate(observation.non_person_objects):
        span_id, address = _region_span(writes, blob_id, detected.box, display, image_span_id)
        emit(
            predicate_key="object_present",
            subject_ref={"type": "capture", "id": str(capture_id)},
            object_value=detected.label,
            support_span_ids=[span_id],
        )
        if address is not None:
            # An occurrence is created only for a located object. Without a region every
            # boxless object in one photograph would share an identity key, which is what
            # rejection memory is keyed on, so they would suppress each other's proposals.
            repository.insert_occurrence(
                capture_id=capture_id,
                occurrence_class="object",
                primary_span_id=span_id,
                span_ids=[span_id],
                presence=[(PHOTOGRAPH_INTERVAL.start_ns, PHOTOGRAPH_INTERVAL.end_ns)],
                produced_by_run=ledger.run_id,
                detector_version=DETECTOR_VERSION,
                identity_key=occurrence_identity_key(address, "object"),
                emit_key=f"{key}:o:{index}",
                quality={
                    "confidence_band": detected.confidence,
                    "salience": detected.salience,
                    "label": detected.label,
                    "trust_tier": "T2",
                },
            )

    for legible in observation.legible_text:
        span_id, _ = _region_span(writes, blob_id, legible.box, display, image_span_id)
        emit(
            predicate_key="ocr_text_is",
            subject_ref={"type": "capture", "id": str(capture_id)},
            object_value=legible.text,
            support_span_ids=[span_id],
        )

    place = observation.proposed_place
    if place is not None:
        emit(
            predicate_key="place_is",
            subject_ref={"type": "capture", "id": str(capture_id)},
            object_value=place.label,
            support_span_ids=[image_span_id],
        )
        repository.insert_occurrence(
            capture_id=capture_id,
            occurrence_class="place",
            primary_span_id=image_span_id,
            span_ids=[image_span_id],
            presence=[(PHOTOGRAPH_INTERVAL.start_ns, PHOTOGRAPH_INTERVAL.end_ns)],
            produced_by_run=ledger.run_id,
            detector_version=DETECTOR_VERSION,
            identity_key=occurrence_identity_key(EvidenceAddress.photograph(blob_id), "place"),
            emit_key=f"{key}:o:place",
            quality={
                "confidence_band": place.confidence,
                "basis": place.basis,
                "trust_tier": "T2",
            },
        )
    return emitted


def _region_span(
    writes: StageWrites,
    blob_id: BlobId,
    box: Any,
    display: DisplayGeometry,
    image_span_id: uuid.UUID,
) -> tuple[uuid.UUID, EvidenceAddress | None]:
    """A span for a located item, or the whole-image span when there is no usable box."""
    if box is None:
        return image_span_id, None
    clamped, _ = box.clamped()
    if clamped.is_degenerate:
        return image_span_id, None
    address = EvidenceAddress.photograph(
        blob_id,
        region=Region(
            rect=Rect.from_normalised(clamped.x, clamped.y, clamped.w, clamped.h),
            display=display,
        ),
    )
    return writes.repository.upsert_span(address), address


def _verbatim_json(document: dict[str, Any]) -> bytes:
    """Serialise a vision artifact exactly as the model wrote it.

    Deliberately not ``exulanica.canonical.canonical_json``, which refuses floats. That refusal
    is right for a digest input, where two implementations must agree byte for byte, and wrong
    here: this artifact is the record of what the model actually said, and rewriting its
    numbers into another representation before storing it would make the audit record something
    other than the model's output. Nothing downstream hashes this document as a digest input;
    ``content_sha256`` is a hash of the stored bytes, which is a different claim.

    The coordinates that DO enter a digest are quantised to integers first, in
    ``exulanica.evidence.region``, before any span is built from them.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
