"""Stage 5. Where the people in one photograph are, proposed and never decided.

This stage replaces nothing and decides nothing. It writes a list of candidate regions with
``confirmed_by`` null on every one, because a detector's guess about somebody else's photograph is
not a decision about them. What turns a candidate into a confirmed region is a person editing it,
and every such edit is its own receipt.

**It reads detections this system already made rather than calling a model.** The ``vision`` stage
at version 2 already records ``person_objects`` with boxes and already writes them as ``person``
occurrences. Reusing that costs no new model call, no new weights and no new privacy posture, and
it is the difference between a real detection and an invented one. MEASURED 2026-09-05: no local
person detector exists in either extra, so inventing one here was never an option and a fabricated
region would have been worse than none.

**A box is recorded as a box.** The vision schema gives an axis-aligned box, not an outline.
Masking a box hides a superset of the person, which is the safe direction under default deny, so
the region is usable now; ``shape='box'`` travels with it so nothing downstream calls it a
measured silhouette.

**A person nobody could locate masks the whole photograph, and keeps a key of their own.** The
vision schema makes ``box`` optional. Treating an unlocated person as nothing to do is precisely
the failure this design exists to prevent, so they become a whole-frame region instead. That
region carries ``located=False`` all the way into ``region_key``, because a whole-frame outline's
centre is the middle of the photograph and the identity key buckets on the centre. MEASURED
2026-09-07: without it an unlocated person and an ordinary body standing centre-frame produced one
key, one row survived the ``person_region_current`` view, and it was the located one, so the
person nobody could place was visible in the masked derivative.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image

from exulanica.canonical import sha256_digest
from exulanica.consent.regions import DetectedPerson, region_key
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import DisplayGeometry
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.person_receipts import person_region_list, region_edit_receipt
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites
from exulanica.ingest.vision import VisionObservation, validate_observation

__all__ = ["ObservedTrace", "located_people", "observation_of", "run", "unlocated_people"]


@dataclass(frozen=True, slots=True)
class ObservedTrace:
    """One person the observation placed, as the detector adapter needs it.

    A named shape rather than a tuple. It was a five-member tuple destructured by position in a
    different module, which is the kind of contract that silently gains a sixth member and starts
    assigning `part` to `confidence` somewhere else entirely.
    """

    x: float
    y: float
    w: float
    h: float
    confidence: str
    part: str


def observation_of(document: dict[str, Any]) -> VisionObservation:
    """Revalidate the stored artifact through the schema that produced it.

    Not a hand-rolled read of the JSON. ``person_objects`` already knows which labels denote a
    human being and ``Box.clamped`` already knows that models routinely emit 1.02 for an edge; a
    second implementation here would drift from both, and the direction it would drift is a
    person who quietly stops being masked.
    """
    return validate_observation(document["observation"])


def located_people(document: dict[str, Any]) -> list[ObservedTrace]:
    """Every person the observation placed, as clamped normalised boxes."""
    found: list[ObservedTrace] = []
    for person in observation_of(document).person_traces:
        if person.box is None:
            continue
        clamped, _ = person.box.clamped()
        if clamped.is_degenerate:
            continue
        found.append(
            ObservedTrace(
                clamped.x, clamped.y, clamped.w, clamped.h, person.confidence, person.part
            )
        )
    return found


def unlocated_people(document: dict[str, Any]) -> int:
    """How many people the observation named without a usable box.

    A degenerate box counts here too. A zero-area box locates nobody, and treating one as a
    located person would mask an empty rectangle and leave the person beside it visible.
    """
    total = 0
    for person in observation_of(document).person_traces:
        if person.box is None:
            total += 1
            continue
        clamped, _ = person.box.clamped()
        if clamped.is_degenerate:
            total += 1
    return total


def run(
    writes: StageWrites,
    detector: Any | None,
    blob_id: BlobId,
    upright: Image.Image,
    capture_id: uuid.UUID,
    intake: StageResult,
    vision: StageResult | None,
    ledger: Ledger,
    outcome: IngestOutcome,
) -> StageResult | None:
    """Propose regions for one photograph, or record honestly that nothing looked."""
    spec = stage("person_regions")
    if detector is None or (detector.requires_observation and vision is None):
        # "Nothing looked" and "looked and found nobody" are different facts and must stay
        # different rows: the first blocks geometry under default deny and the second does not.
        # A detector that needs the vision observation and has none has not looked, whatever an
        # empty result from it would suggest.
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec,
            reason=(
                "no person detector is configured for this worker"
                if detector is None
                else "no vision observation exists to read person regions from"
            ),
            input_blob=blob_id,
        )
        return None
    # The observation when there is one, the source bytes otherwise, and always the identity of
    # the detector that will be asked. Its identity is an input to this region list in the plainest
    # sense: change the detector and the regions are a different answer, so the key must move and
    # the old artifact must not be reused.
    upstream = [intake.content_sha256] if vision is None else [vision.content_sha256]
    input_digest = input_digest_of([*upstream, sha256_digest(detector.model_id.encode("utf-8"))])
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
    if vision is None:
        context: dict[str, Any] = {"person_boxes": [], "unlocated_people": 0}
    else:
        document = json.loads(writes.store.get(BlobId(vision.content_sha256)))
        context = {
            "person_boxes": located_people(document),
            "unlocated_people": unlocated_people(document),
        }
    inputs = [intake.artifact_id] if vision is None else [vision.artifact_id]
    with ledger.stage(spec, input_artifact_ids=inputs, input_blob=blob_id) as recorder:
        display = DisplayGeometry(w=upright.width, h=upright.height)
        detections = detector.detect(upright, context)
        payload = encode_region_list(
            source_sha256=blob_id.hex,
            detector_id=detector.model_id,
            stage_version=spec.version,
            detections=detections,
            blob_id=blob_id,
            display=display,
            unlocated=int(context["unlocated_people"]),
        )
        with writes.committed_writes() as pending:
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
            _record_regions(
                writes,
                blob_id=blob_id,
                capture_id=capture_id,
                detections=detections,
                display=display,
                detector_id=detector.model_id,
                unlocated=int(context["unlocated_people"]),
            )
        return result


def encode_region_list(
    *,
    source_sha256: str,
    detector_id: str,
    stage_version: int,
    detections: Sequence[DetectedPerson],
    blob_id: BlobId,
    display: DisplayGeometry,
    unlocated: int,
) -> bytes:
    """The artifact bytes: a canonical region list keyed on the evidence, confirming nobody."""
    from exulanica.canonical import canonical_json

    # Keyed exactly as `_record_regions` keys the rows. The artifact and the database disagreeing
    # about a region's identity would be its own defect: a reviewer's confirmation would be
    # recorded against a key the listed region does not have.
    keyed = [
        (region_key(blob_id, found.silhouette, display, located=found.located), found)
        for found in detections
    ]
    return canonical_json(
        person_region_list(
            source_sha256=source_sha256,
            detector_id=detector_id,
            stage_version=stage_version,
            detections=keyed,
            unlocated_people=unlocated,
        )
    )


def _record_regions(
    writes: StageWrites,
    *,
    blob_id: BlobId,
    capture_id: uuid.UUID,
    detections: Sequence[DetectedPerson],
    display: DisplayGeometry,
    detector_id: str,
    unlocated: int,
) -> None:
    """Write one ``detected`` edit per proposed region, in the transaction that stores the artifact.

    **This is what arms default deny.** A detected row carries no subject, and
    ``person_region_is_masked`` in migration 0037 returns true for a null subject, so from the
    moment these rows exist the photograph requires masking and the geometry trigger will refuse a
    point map over the original bytes. Writing the artifact without these rows, which is what this
    stage did before, left the whole database guard inert: `capture_requires_masking` was false for
    every capture in every workspace because nothing had ever written to the table it reads.

    Recorded inside ``committed_writes`` so the rows and the artifact commit together. A region
    list that survived without its rows would claim a screening that arms nothing.
    """
    if not detections and not unlocated:
        return
    repository = writes.repository
    recorded_at = dt.datetime.now(dt.UTC)
    for found in detections:
        # `located=` is what stops a whole-frame region being swallowed by a body standing in the
        # middle of the same photograph. Both key to grid cell 8:8, the first insert is already
        # visible in this transaction, so the second is read as an already-edited region and
        # skipped by the `continue` below. MEASURED 2026-09-07: the whole-frame mask was the one
        # lost, because a detector reports located people first.
        key = region_key(blob_id, found.silhouette, display, located=found.located)
        sequence = repository.next_person_region_sequence(capture_id=capture_id, region_key=key)
        if sequence:
            # Somebody has already edited this region, and a re-run of a detector must not
            # overwrite a human's decision. The bucketed key exists precisely so that the second
            # run lands here rather than proposing the same body again.
            continue
        edit_id, record, canonical, digest = region_edit_receipt(
            workspace_id=repository.workspace_id,
            capture_id=capture_id,
            source_sha256=blob_id.hex,
            region_key=key,
            sequence=0,
            action="detected",
            shape=found.shape,
            part=found.part,
            silhouette=found.silhouette,
            subject_id=None,
            actor=None,
            detector_id=detector_id,
            confidence=found.confidence,
            recorded_at=recorded_at,
        )
        repository.insert_person_region_edit(
            region_edit_id=edit_id,
            capture_id=capture_id,
            source_sha256=blob_id,
            region_key=key,
            sequence=0,
            action="detected",
            shape=found.shape,
            part=found.part,
            silhouette=found.silhouette.as_digest_input(),
            subject_id=None,
            detector_id=detector_id,
            confidence=found.confidence,
            confirmed_by=None,
            recorded_at=recorded_at,
            region_record=record,
            region_canonical=canonical,
            region_digest=digest,
        )
