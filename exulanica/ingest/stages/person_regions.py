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

**A person nobody could locate masks the whole photograph.** The vision schema makes ``box``
optional. Treating an unlocated person as nothing to do is precisely the failure this design
exists to prevent, so they become a whole-frame region instead.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from PIL import Image

from exulanica.consent.regions import DetectedPerson, region_key
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import DisplayGeometry
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.person_receipts import person_region_list
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites
from exulanica.ingest.vision import VisionObservation, validate_observation

__all__ = ["located_people", "observation_of", "run", "unlocated_people"]


def observation_of(document: dict[str, Any]) -> VisionObservation:
    """Revalidate the stored artifact through the schema that produced it.

    Not a hand-rolled read of the JSON. ``person_objects`` already knows which labels denote a
    human being and ``Box.clamped`` already knows that models routinely emit 1.02 for an edge; a
    second implementation here would drift from both, and the direction it would drift is a
    person who quietly stops being masked.
    """
    return validate_observation(document["observation"])


def located_people(document: dict[str, Any]) -> list[tuple[float, float, float, float, str]]:
    """Every person the observation placed, as clamped normalised boxes."""
    found: list[tuple[float, float, float, float, str]] = []
    for person in observation_of(document).person_objects:
        if person.box is None:
            continue
        clamped, _ = person.box.clamped()
        if clamped.is_degenerate:
            continue
        found.append((clamped.x, clamped.y, clamped.w, clamped.h, person.confidence))
    return found


def unlocated_people(document: dict[str, Any]) -> int:
    """How many people the observation named without a usable box.

    A degenerate box counts here too. A zero-area box locates nobody, and treating one as a
    located person would mask an empty rectangle and leave the person beside it visible.
    """
    total = 0
    for person in observation_of(document).person_objects:
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
    vision: StageResult | None,
    ledger: Ledger,
    outcome: IngestOutcome,
) -> StageResult | None:
    """Propose regions for one photograph, or record honestly that nothing looked."""
    spec = stage("person_regions")
    if detector is None or vision is None:
        # "Nothing looked" and "looked and found nobody" are different facts and must stay
        # different rows: the first blocks geometry under default deny and the second does not.
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
    pinned = str(spec.params["detector"])
    if detector.model_id != pinned:
        raise ValueError(
            f"stage version {spec.version} pins detector {pinned!r} and was handed "
            f"{detector.model_id!r}. Swapping a detector without editing the stage parameters "
            "would leave the corpus keyed as though nothing had changed."
        )
    input_digest = input_digest_of([vision.content_sha256])
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
    document = json.loads(writes.store.get(BlobId(vision.content_sha256)))
    context = {
        "person_boxes": located_people(document),
        "unlocated_people": unlocated_people(document),
    }
    with ledger.stage(
        spec, input_artifact_ids=[vision.artifact_id], input_blob=blob_id
    ) as recorder:
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
            return writes.persist_artifact(
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

    keyed = [(region_key(blob_id, found.silhouette, display), found) for found in detections]
    return canonical_json(
        person_region_list(
            source_sha256=source_sha256,
            detector_id=detector_id,
            stage_version=stage_version,
            detections=keyed,
            unlocated_people=unlocated,
        )
    )
