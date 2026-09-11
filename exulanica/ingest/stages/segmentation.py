"""Stage 5. Object masks for one photograph, found locally and filed as regions and inference.

What this stage writes, and why each piece is the shape it is:

*   **One ``frame_region`` evidence span per mask**, holding the mask's bounding box in parts per
    million of the upright display square. A span's region is a rectangle and nothing else: the
    ``evidence_span_region_shape`` constraint in migration 0033 admits ``kind='rect'`` only, and
    ADR-0013 keeps ``kind`` as the discriminator a polygon kind would be added under. So the span
    addresses the pixels the object occupies at the precision the spine can carry today, exactly
    as ADR-0016 addresses a piece of text: by where it was read from.
*   **The outline itself is in this stage's artifact**, as integer ppm vertices beside the digest
    of the span it belongs to. That is the precision the span cannot hold, recorded where a later
    reader can check it against the span rather than in a second address format. The artifact is
    a derivative and not evidence, so nothing cites a polygon; a citation opens the rectangle.
*   **One ``object_present`` inference per mask, supported by that span.** The predicate's
    vocabulary entry is "a common noun for a thing in the frame, out of a detector's label set",
    which is precisely this. The label is its object value and the segmenter's own score for the
    mask is its ``raw_score``, which is never rendered and never thresholds a claim. The model
    that produced it is named where every model is named, on the stage event's ``model_ref`` and
    ``models_tried`` for the run the assertion's ``produced_by_run`` points at; the label's own
    confidence, the detector score or the hosted pass's band, is in the artifact.

**Where the boxes come from.** The hosted vision pass's located objects when it located any,
otherwise the local open-vocabulary detector over a declared vocabulary. Both are prompts for the
same local segmenter; the artifact records which source ran and why.

**The person path is untouched, and three things keep it that way.** The segmenter reads the
masked derivative whenever anybody in the photograph is hidden, so a person who has not consented
is neutral fill before a pixel reaches it, which is the rule depth follows. No prompt can name a
person: the hosted pass's people are in their own field and are never prompts, and the local
vocabulary contains no person term, which a test checks against the vision stage's own filter.
And a mask that lies mostly inside any person region is dropped, so an object outline can never
become a second, unreviewed outline of somebody. People reach the scene only through their
reviewed outlines; see ``exulanica/ingest/scene_segments.py``.

**Nothing leaves the machine.** Both models run locally, on MPS where the host has it and on the
CPU otherwise. The stage is still gated on an eligible privacy screening, the receipt depth
requires, because what it produces is lifted into geometry.

**Not bit-reproducible, and declared so.** A neural forward pass differs across accelerators and
library versions, so the stage is ``deterministic=False`` (ADR-0017). It carries no
``model_role``: the checkpoints are pinned by revision in ``models.manifest.json`` and their
identity goes into this stage's input digest per photograph, the arrangement ``person_regions``
uses for its detector.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Final, Protocol

from PIL import Image

from exulanica.canonical import canonical_json, sha256_digest, sha256_of_canonical
from exulanica.consent.regions import Silhouette
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import PPM, DisplayGeometry, Rect, Region, to_ppm
from exulanica.ingest.exif import ExifFacts
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.privacy import require_privacy_screening
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.writes import StageResult, StageWrites
from exulanica.ingest.vision import validate_observation
from exulanica.models.manifest import MANIFEST_PATH

if TYPE_CHECKING:
    import numpy as np

__all__ = [
    "DETECTION_ROLE",
    "OBJECT_MASK_KIND",
    "OBJECT_MASK_PROFILE",
    "SEGMENTATION_ROLE",
    "SEGMENTER_CONTRACT",
    "BoxPrompt",
    "DetectionPolicy",
    "Detections",
    "LocalModelPin",
    "LocalObjectSegmenter",
    "LocalRole",
    "ObjectSegmenter",
    "OutlinePolicy",
    "SegmentedMask",
    "SegmenterUnavailable",
    "local_model_roles",
    "outline_from_mask",
    "run",
]

#: The output kind and profile. The kind is spelled again in ``exulanica/ingest/scene_segments.py``
#: and in ``exulanica/graph/reconstruction_scenes.py`` and a test pins the three together.
OBJECT_MASK_KIND: Final = "object_mask_list"
OBJECT_MASK_PROFILE: Final = "exulanica.object-mask-list/v1"

#: The contract an object segmenter satisfies, which is what the stage parameters name. The
#: resolved checkpoints are part of the input digest, not of the parameters, so a scripted
#: segmenter in a test and the real one run through the same stage.
SEGMENTER_CONTRACT: Final = "exulanica.object-segmenter/v1"

#: The two local roles in ``models.manifest.json``. Code names a role and never an identifier.
SEGMENTATION_ROLE: Final = "object_segmentation"
DETECTION_ROLE: Final = "open_vocabulary_detection"


class SegmenterUnavailable(RuntimeError):
    """The segmentation extra is not installed, or a pinned checkpoint failed its licence check."""


# -- the manifest's local section ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocalModelPin:
    """One checkpoint this codebase runs itself, exactly as the manifest pins it."""

    repo_id: str
    revision: str
    license: str

    @property
    def ref(self) -> str:
        """``repo@revision``, the spelling every receipt and ledger row uses."""
        return f"{self.repo_id}@{self.revision}"

    def as_identity(self) -> dict[str, str]:
        return {"repo_id": self.repo_id, "revision": self.revision, "license": self.license}


@dataclass(frozen=True, slots=True)
class LocalRole:
    """A local role: the checkpoint to load, and the one to load when that cannot be."""

    primary: LocalModelPin
    fallback: LocalModelPin | None


def _pin(models: Mapping[str, Any], repo_id: object, role: str) -> LocalModelPin:
    if not isinstance(repo_id, str) or repo_id not in models:
        raise ValueError(f"local role {role!r} names {repo_id!r}, which has no local_models entry")
    entry = models[repo_id]
    revision = entry.get("revision") if isinstance(entry, Mapping) else None
    licence = entry.get("license") if isinstance(entry, Mapping) else None
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        raise ValueError(f"{repo_id} must be pinned to a full lowercase revision SHA")
    if not isinstance(licence, str) or not licence:
        raise ValueError(f"{repo_id} must carry the licence read from its frontmatter")
    return LocalModelPin(repo_id=repo_id, revision=revision, license=licence)


def local_model_roles(document: Mapping[str, Any] | None = None) -> dict[str, LocalRole]:
    """The manifest's ``local_roles``, resolved to pinned checkpoints and validated.

    Read from the manifest file rather than restated here, which is invariant 7 applied to the
    checkpoints this codebase runs itself: no identifier appears in Python source, and a test
    greps this module and its sibling to keep it so.
    """
    if document is None:
        document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    models = document.get("local_models")
    roles = document.get("local_roles")
    if not isinstance(models, Mapping) or not isinstance(roles, Mapping):
        raise ValueError("the manifest has no local_models and local_roles sections")
    resolved: dict[str, LocalRole] = {}
    for name in (SEGMENTATION_ROLE, DETECTION_ROLE):
        raw = roles.get(name)
        if not isinstance(raw, Mapping):
            raise ValueError(f"the manifest does not bind the local role {name!r}")
        primary = _pin(models, raw.get("primary"), name)
        fallback = None if raw.get("fallback") is None else _pin(models, raw.get("fallback"), name)
        if fallback is not None and fallback.repo_id == primary.repo_id:
            raise ValueError(f"local role {name!r} names its primary as its own fallback")
        resolved[name] = LocalRole(primary=primary, fallback=fallback)
    return resolved


def _frontmatter_licence(readme: str) -> str | None:
    """The ``license`` key of a README's leading YAML block, or None when there is none.

    Deliberately not a YAML parser. The key is one scalar on one line in every card this reads,
    and a parser would accept shapes, a list of licences for instance, that this should refuse.
    """
    lines = readme.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        key, _, value = line.partition(":")
        if key.strip() == "license":
            return value.strip().strip("'\"") or None
    return None


def verify_frontmatter_licence(pin: LocalModelPin) -> None:
    """Re-read the pinned README and refuse a checkpoint whose licence has moved.

    ``docs/model-and-service-selection.md`` section 2.3: the licence is read from the raw
    frontmatter at a pinned revision, and a drift fails rather than warns. A revision is immutable,
    so this can only fail if the manifest was edited by hand, which is the case it exists for.
    """
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(pin.repo_id, "README.md", revision=pin.revision)
    with open(path, encoding="utf-8") as handle:
        found = _frontmatter_licence(handle.read())
    if found != pin.license:
        raise SegmenterUnavailable(
            f"{pin.ref} declares licence {found!r} in its frontmatter and the manifest pins "
            f"{pin.license!r}; refusing to load it"
        )


# -- what crosses the segmenter protocol ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoxPrompt:
    """One box a mask is asked for, and where the box came from.

    ``score_millionths`` is a local detector's own score; ``confidence_band`` is the hosted
    pass's. Exactly one is set, because the two are not the same scale and a reader must not be
    handed a number that looks comparable when it is not.
    """

    label: str
    box: Rect
    source: str
    score_millionths: int | None = None
    confidence_band: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "source": self.source,
            "box": self.box.as_digest_input(),
            "score_millionths": self.score_millionths,
            "confidence_band": self.confidence_band,
        }


@dataclass(frozen=True, slots=True)
class Detections:
    """What the local detector found, and which checkpoint found it."""

    boxes: tuple[BoxPrompt, ...]
    model: str
    models_tried: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True, slots=True)
class SegmentedMask:
    """One mask, reduced to the outline the stage records.

    ``components`` is how many separate pieces the mask had. Only the largest becomes the
    outline, so a count above one says the outline is less than the mask was.
    """

    outline: Silhouette
    confidence_millionths: int
    area_millionths: int
    components: int


@dataclass(frozen=True, slots=True)
class DetectionPolicy:
    vocabulary: tuple[str, ...]
    box_threshold_millionths: int
    text_threshold_millionths: int
    fallback_threshold_millionths: int
    max_boxes: int
    duplicate_iou_millionths: int


@dataclass(frozen=True, slots=True)
class OutlinePolicy:
    simplify_millionths_of_diagonal: int
    max_vertices: int


class ObjectSegmenter(Protocol):
    """A local segmenter, and the detector it falls back on for prompts.

    ``identity`` enters the stage's input digest, so it must be canonical JSON: strings and
    integers only. Swapping a checkpoint therefore re-keys every photograph rather than leaving
    old masks filed under a new model.
    """

    @property
    def identity(self) -> Mapping[str, Any]: ...

    @property
    def device(self) -> str: ...

    def detect(self, image: Image.Image, policy: DetectionPolicy) -> Detections: ...

    def segment(
        self, image: Image.Image, boxes: Sequence[Rect], policy: OutlinePolicy
    ) -> list[SegmentedMask | None]: ...


def _policies(params: Mapping[str, Any]) -> tuple[DetectionPolicy, OutlinePolicy]:
    outline = params["outline"]
    return (
        DetectionPolicy(
            vocabulary=tuple(params["detector_vocabulary"]),
            box_threshold_millionths=int(params["detector_box_threshold_millionths"]),
            text_threshold_millionths=int(params["detector_text_threshold_millionths"]),
            fallback_threshold_millionths=int(params["fallback_detector_threshold_millionths"]),
            max_boxes=int(params["max_prompts"]),
            duplicate_iou_millionths=int(params["duplicate_box_iou_millionths"]),
        ),
        OutlinePolicy(
            simplify_millionths_of_diagonal=int(outline["simplify_millionths_of_diagonal"]),
            max_vertices=int(outline["max_vertices"]),
        ),
    )


# -- the stage -----------------------------------------------------------------------------------


def run(
    writes: StageWrites,
    segmenter: ObjectSegmenter | None,
    blob_id: BlobId,
    upright: Image.Image,
    capture_id: uuid.UUID,
    facts: ExifFacts,
    intake: StageResult,
    vision: StageResult | None,
    ledger: Ledger,
    outcome: IngestOutcome,
    privacy_screening_id: uuid.UUID | None,
    *,
    masked: StageResult | None = None,
    masked_image: Image.Image | None = None,
    consent_digests: tuple[bytes, ...] = (),
    person_outlines: tuple[Silhouette, ...] = (),
) -> StageResult | None:
    """Mask the objects in one photograph, or say honestly why nothing looked."""
    spec = stage("segmentation")
    if segmenter is None:
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec, reason="no object segmenter is configured for this worker", input_blob=blob_id
        )
        return None
    if privacy_screening_id is None:
        # Unavailable rather than failed, for the reason the vision stage gives: nobody has
        # authorized this photograph for the geometry path yet, so it was not segmented.
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec,
            reason="no privacy screening receipt authorizes object segmentation of these bytes",
            input_blob=blob_id,
        )
        return None
    try:
        screening = require_privacy_screening(writes.repository, capture_id, privacy_screening_id)
    except PrivacyAdmissionError as refusal:
        # Unavailable, not failed, and this is a deliberate difference from depth. The receipt
        # that arrives here during a person-detection pass authorizes looking for people and
        # nothing else, and a worker configured with a segmenter must not fail that pass for it.
        # Nothing is produced either way; the ledger records which receipt refused and why.
        outcome.stages_skipped.append(spec.key)
        outcome.stages_unavailable.append(spec.key)
        ledger.unavailable(
            spec,
            reason=f"the privacy screening does not permit object segmentation: {refusal}",
            input_blob=blob_id,
        )
        return None

    hosted = _hosted_prompts(writes, vision)
    # What the masks are a function of: the source and its orientation (the intake probe, as depth
    # keys it), the masked derivative when one was read and the consent state that made it, the
    # boxes offered, and the checkpoints that ran. Not the screening receipt: re-recording one
    # changes nothing in the pixels, and its id is on the artifact row instead.
    offered = (
        vision.content_sha256
        if vision is not None and hosted
        else sha256_of_canonical({"hosted_observation": None})
    )
    identity = canonical_json(dict(segmenter.identity))
    input_digest = input_digest_of(
        [
            intake.content_sha256,
            *([masked.content_sha256] if masked is not None else []),
            *consent_digests,
            offered,
            sha256_digest(identity),
        ]
    )
    key = idempotency_key(blob_id, spec, input_digest)
    existing = writes.repository.find_artifact(key)
    if existing is not None:
        outcome.stages_reused.append(spec.key)
        ledger.reused(spec, existing.artifact_id, input_blob=blob_id)
        if existing.content_sha256 is None:
            # A row naming output that was never stored has nothing a lift could read back.
            return None
        return StageResult(
            artifact_id=existing.artifact_id,
            content_sha256=existing.content_sha256,
            idempotency_key=key,
            reused=True,
        )

    detection_policy, outline_policy = _policies(spec.params)
    source = masked_image if masked_image is not None else upright
    working = _fit(source.convert("RGB"), int(spec.params["max_edge_px"]))
    inputs = [intake.artifact_id]
    if vision is not None and hosted:
        inputs.append(vision.artifact_id)
    if masked is not None:
        inputs.append(masked.artifact_id)

    with ledger.stage(spec, input_artifact_ids=inputs, input_blob=blob_id) as recorder:
        started = time.monotonic()
        detections: Detections | None = None
        outside_vocabulary = 0
        if hosted:
            prompts = hosted[: detection_policy.max_boxes]
        else:
            detections = segmenter.detect(working, detection_policy)
            # The vocabulary is the only thing a local box may be labelled with. A detector that
            # returned anything else, a person term above all, is not believed.
            prompts = [p for p in detections.boxes if p.label in detection_policy.vocabulary]
            outside_vocabulary = len(detections.boxes) - len(prompts)
            prompts = prompts[: detection_policy.max_boxes]
        masks = (
            segmenter.segment(working, [p.box for p in prompts], outline_policy) if prompts else []
        )
        if len(masks) != len(prompts):
            raise ValueError("the segmenter returned a different number of masks than prompts")
        elapsed_ms = int((time.monotonic() - started) * 1000)

        display = DisplayGeometry(w=facts.display_width, h=facts.display_height, rotation=0)
        kept, dropped = _keep(prompts, masks, person_outlines, spec.params)
        dropped["outside_vocabulary"] = outside_vocabulary
        segmenter_ref = (
            str(segmenter.identity["segmenter"]["repo_id"])
            + "@"
            + str(segmenter.identity["segmenter"]["revision"])
        )
        records = []
        addresses = []
        for index, (prompt_index, prompt, mask) in enumerate(kept):
            address = EvidenceAddress.photograph(
                blob_id, region=Region(rect=mask.outline.bounding_rect(), display=display)
            )
            addresses.append(address)
            records.append(
                {
                    "index": index,
                    "prompt_index": prompt_index,
                    "label": prompt.label,
                    "label_source": prompt.source,
                    "label_confidence": (
                        {"score_millionths": prompt.score_millionths}
                        if prompt.score_millionths is not None
                        else {"band": prompt.confidence_band}
                    ),
                    "mask_confidence_millionths": mask.confidence_millionths,
                    "model": segmenter_ref,
                    "outline": mask.outline.as_digest_input(),
                    "bounds": mask.outline.bounding_rect().as_digest_input(),
                    "area_millionths": mask.area_millionths,
                    "components": mask.components,
                    "span_digest": address.span_digest_hex,
                    "prompt_span_digest": (
                        EvidenceAddress.photograph(
                            blob_id, region=Region(rect=prompt.box, display=display)
                        ).span_digest_hex
                        if prompt.source == "hosted_vision"
                        else None
                    ),
                }
            )
        document = {
            "profile": OBJECT_MASK_PROFILE,
            "stage": {
                "key": spec.key,
                "version": spec.version,
                "params_sha256": spec.params_digest.hex(),
            },
            "source": {
                "blob_sha256": blob_id.hex,
                # The masked derivative's digest when one was read, and null when the segmenter
                # read the upright original, which ``blob_sha256`` already names.
                "read_sha256": None if masked is None else masked.content_sha256.hex(),
                "masked": masked is not None,
                "display": {"w": display.w, "h": display.h},
                "working": {"w": working.width, "h": working.height},
            },
            "segmenter": json.loads(identity),
            "prompt_source": "hosted_vision" if hosted else "local_detector",
            "detector": (
                None
                if detections is None
                else {
                    "model": detections.model,
                    "models_tried": list(detections.models_tried),
                    "fallback_used": detections.fallback_used,
                    "boxes_found": len(detections.boxes),
                }
            ),
            "prompts": [prompt.as_record() for prompt in prompts],
            "masks": records,
            "dropped": dropped,
        }
        payload = canonical_json(document) + b"\n"
        tried = [segmenter_ref]
        if detections is not None:
            tried = [*detections.models_tried, segmenter_ref]
        recorder.record_model_call(
            {
                "provider": "local",
                "model_id": str(segmenter.identity["segmenter"]["repo_id"]),
                "revision": str(segmenter.identity["segmenter"]["revision"]),
                "license": str(segmenter.identity["segmenter"]["license"]),
                "detector": None if detections is None else detections.model,
                "device": segmenter.device,
            },
            {"usd_estimate": "0", "local_compute_ms": elapsed_ms, "device": segmenter.device},
            1,
            tried,
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
                privacy_screening_id=screening.screening_id,
                read_source_sha256=None if masked is None else masked.content_sha256,
            )
            emitted: list[uuid.UUID] = []
            for record, address, (_prompt_index, prompt, mask) in zip(
                records, addresses, kept, strict=True
            ):
                span_id = writes.repository.upsert_span(address)
                assertion_id = writes.repository.insert_assertion(
                    kind="inference",
                    predicate_key="object_present",
                    subject_ref={"type": "capture", "id": str(capture_id)},
                    object_value=prompt.label,
                    support_span_ids=[span_id],
                    raw_score=mask.confidence_millionths / 1_000_000,
                    produced_by_run=ledger.run_id,
                    emit_key=f"{key}:m:{record['index']}",
                )
                if assertion_id is not None:
                    emitted.append(assertion_id)
        ledger.emitted("assertion", emitted, spec)
    return result


def _hosted_prompts(writes: StageWrites, vision: StageResult | None) -> list[BoxPrompt]:
    """The hosted pass's located objects, as prompts, or nothing when it located none.

    Read back from the stored observation and validated again, rather than handed over in memory,
    so a reprocess that only runs this stage sees exactly what an ingest saw. People are never
    prompts: ``non_person_objects`` is the vision stage's own split, and the hosted schema puts
    people in a field of their own.
    """
    if vision is None:
        return []
    document = json.loads(writes.store.get(BlobId(vision.content_sha256)))
    observation = validate_observation(document["observation"])
    prompts: list[BoxPrompt] = []
    for detected in observation.non_person_objects:
        if detected.box is None:
            continue
        clamped, _ = detected.box.clamped()
        if clamped.is_degenerate:
            continue
        try:
            rect = Rect.from_normalised(clamped.x, clamped.y, clamped.w, clamped.h)
        except ValueError:
            # A box that rounds to nothing at one ppm. The vision stage falls back to the whole
            # frame for such a box; as a prompt it asks for nothing, so it is not offered.
            continue
        prompts.append(
            BoxPrompt(
                label=detected.label,
                box=rect,
                source="hosted_vision",
                confidence_band=detected.confidence,
            )
        )
    return prompts


def _keep(
    prompts: Sequence[BoxPrompt],
    masks: Sequence[SegmentedMask | None],
    person_outlines: Sequence[Silhouette],
    params: Mapping[str, Any],
) -> tuple[list[tuple[int, BoxPrompt, SegmentedMask]], dict[str, int]]:
    """Drop masks too small to be an object and masks that are mostly a person."""
    minimum = int(params["min_mask_area_millionths"])
    person_limit = int(params["person_overlap_drop_millionths"])
    dropped = {"below_min_area": 0, "person_overlap": 0, "unusable_outline": 0}
    kept: list[tuple[int, BoxPrompt, SegmentedMask]] = []
    for index, (prompt, mask) in enumerate(zip(prompts, masks, strict=True)):
        if mask is None:
            dropped["unusable_outline"] += 1
        elif mask.area_millionths < minimum:
            dropped["below_min_area"] += 1
        elif person_outlines and person_overlap_millionths(mask.outline, person_outlines) >= (
            person_limit
        ):
            dropped["person_overlap"] += 1
        else:
            kept.append((index, prompt, mask))
    return kept, dropped


#: The sampling lattice for the person-overlap estimate: this many points on each axis of the
#: object's bounding box. Integer containment at every point, so two hosts agree on the answer.
_OVERLAP_LATTICE: Final = 32


def person_overlap_millionths(outline: Silhouette, persons: Sequence[Silhouette]) -> int:
    """The share of an object outline that lies inside any person outline, in millionths.

    Estimated on a fixed lattice over the object's bounding box rather than computed as a polygon
    intersection, because person outlines are not convex and the containment test in
    ``Silhouette`` is already exact and integer. The lattice bounds the error to roughly one cell,
    three per cent of the box on each axis, which is well inside the fifty per cent it decides.
    """
    bound = outline.bounding_rect()
    inside = 0
    covered = 0
    for row in range(_OVERLAP_LATTICE):
        y = bound.y_ppm + (2 * row + 1) * bound.h_ppm // (2 * _OVERLAP_LATTICE)
        for column in range(_OVERLAP_LATTICE):
            x = bound.x_ppm + (2 * column + 1) * bound.w_ppm // (2 * _OVERLAP_LATTICE)
            if not outline.contains(x, y):
                continue
            inside += 1
            if any(person.contains(x, y) for person in persons):
                covered += 1
    return 0 if inside == 0 else covered * 1_000_000 // inside


def _fit(image: Image.Image, max_edge: int) -> Image.Image:
    """Downscale so the longest edge is at most ``max_edge``. Never upscales."""
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
    )


def box_iou_millionths(first: Rect, second: Rect) -> int:
    """Intersection over union of two ppm boxes, in exact integer millionths."""
    left = max(first.x_ppm, second.x_ppm)
    top = max(first.y_ppm, second.y_ppm)
    right = min(first.x_ppm + first.w_ppm, second.x_ppm + second.w_ppm)
    bottom = min(first.y_ppm + first.h_ppm, second.y_ppm + second.h_ppm)
    if right <= left or bottom <= top:
        return 0
    overlap = (right - left) * (bottom - top)
    union = first.w_ppm * first.h_ppm + second.w_ppm * second.h_ppm - overlap
    return overlap * 1_000_000 // union


def deduplicate(boxes: Sequence[BoxPrompt], *, iou_millionths: int, limit: int) -> list[BoxPrompt]:
    """Keep the higher-scoring of any two boxes that overlap past the threshold, whatever label.

    A detector asked about "rock" and "boulder" reports the same stone twice, and two prompts on
    one object become two masks of it. Class-agnostic on purpose. Ordered by score and then by
    position, so the result is a function of the boxes rather than of the order they arrived in.
    """
    ordered = sorted(
        boxes,
        key=lambda item: (
            -(item.score_millionths or 0),
            item.box.x_ppm,
            item.box.y_ppm,
            item.box.w_ppm,
            item.box.h_ppm,
            item.label,
        ),
    )
    kept: list[BoxPrompt] = []
    for candidate in ordered:
        if all(box_iou_millionths(candidate.box, other.box) < iou_millionths for other in kept):
            kept.append(candidate)
        if len(kept) == limit:
            break
    return kept


def outline_from_mask(
    mask: np.ndarray, policy: OutlinePolicy
) -> tuple[Silhouette, int, int] | None:
    """The largest external contour of a boolean mask, simplified, in ppm of the unit square.

    Returns the outline, the mask's area in millionths of the frame, and how many separate pieces
    it had; None when nothing usable is left. Vertices are pixel centres quantised through the one
    rounding rule, so the digest of an outline does not depend on the host that drew it.
    """
    import cv2
    import numpy as np

    height, width = mask.shape
    area = int(np.count_nonzero(mask))
    if area == 0:
        return None
    contours, _hierarchy = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contours = [contour for contour in contours if len(contour) >= 3]
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    epsilon = policy.simplify_millionths_of_diagonal * math.hypot(width, height) / 1_000_000
    approximate = cv2.approxPolyDP(largest, epsilon, True)
    while len(approximate) > policy.max_vertices:
        epsilon *= 1.5
        approximate = cv2.approxPolyDP(largest, epsilon, True)
    points: list[tuple[int, int]] = []
    for vertex in approximate.reshape(-1, 2):
        x, y = int(vertex[0]), int(vertex[1])
        point = (to_ppm(Fraction(2 * x + 1, 2 * width)), to_ppm(Fraction(2 * y + 1, 2 * height)))
        if not points or points[-1] != point:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    try:
        outline = Silhouette(tuple(points))
    except ValueError:
        return None
    return outline, area * 1_000_000 // (width * height), len(contours)


# -- the real segmenter --------------------------------------------------------------------------


def _resolve_device(requested: str | None) -> str:
    import torch

    if requested:
        return requested
    return "mps" if torch.backends.mps.is_available() else "cpu"


class LocalObjectSegmenter:
    """SAM 2.1 for masks and Grounding DINO, with OWLv2 behind it, for boxes. Local only.

    Loaded once per worker and not thread safe. The detectors load lazily: a corpus the hosted
    pass has already located objects in never pays for them.

    **MPS with a CPU fallback, in two places.** The device is MPS when the host has it and the CPU
    otherwise, and a forward pass that raises on MPS moves every loaded model to the CPU and runs
    again there, once, which the device string then says for the rest of the worker's life. An
    operator reading ``cpu (fell back from mps: ...)`` in a ledger row knows the numbers beside it
    were not measured on the accelerator.

    **No torchvision.** transformers imports it at module level in the SAM 2 image processor and
    in the fast detector processors, so this drives ``Sam2Model`` from the checkpoint's own
    preprocessor configuration and uses the PIL processors for the detectors. See the
    ``segmentation`` extra in ``pyproject.toml``.
    """

    def __init__(
        self,
        *,
        device: str | None = None,
        roles: Mapping[str, LocalRole] | None = None,
        verify_licences: bool = True,
    ) -> None:
        try:
            import numpy  # noqa: F401
            import torch
            import transformers
            from transformers import Sam2Model
        except ImportError as exc:  # pragma: no cover - exercised by not installing the extra
            raise SegmenterUnavailable(
                "object segmentation needs torch and transformers, which are the segmentation "
                "extra in pyproject.toml"
            ) from exc
        resolved = roles or local_model_roles()
        self._segmenter_pin = resolved[SEGMENTATION_ROLE].primary
        detection = resolved[DETECTION_ROLE]
        self._detector_pins = tuple(
            pin for pin in (detection.primary, detection.fallback) if pin is not None
        )
        if verify_licences:
            for pin in (self._segmenter_pin, *self._detector_pins):
                verify_frontmatter_licence(pin)
        self._torch = torch
        self._versions = {"torch": torch.__version__, "transformers": transformers.__version__}
        self._device = _resolve_device(device)
        self._fallback_note: str | None = None
        self._sam = Sam2Model.from_pretrained(
            self._segmenter_pin.repo_id, revision=self._segmenter_pin.revision
        )
        self._sam.to(self._device).eval()
        self._sam_config = _preprocessor_config(self._segmenter_pin)
        self._detectors: dict[str, Any] = {}

    @property
    def identity(self) -> dict[str, Any]:
        detection = list(self._detector_pins)
        return {
            "contract": SEGMENTER_CONTRACT,
            "segmenter": self._segmenter_pin.as_identity(),
            "detector": detection[0].as_identity(),
            "detector_fallback": detection[1].as_identity() if len(detection) > 1 else None,
            "library": dict(self._versions),
        }

    @property
    def device(self) -> str:
        return self._device if self._fallback_note is None else f"cpu ({self._fallback_note})"

    def _on_device(self, call: Any) -> Any:
        """Run ``call`` on the current device, moving to the CPU once if MPS refuses it."""
        try:
            return call(self._device)
        except RuntimeError as error:
            if self._device != "mps":
                raise
            self._fallback_note = f"fell back from mps: {type(error).__name__}"
            self._device = "cpu"
            self._sam.to("cpu")
            for model, _processor in self._detectors.values():
                model.to("cpu")
            return call(self._device)

    # -- boxes ----------------------------------------------------------------------------------

    def detect(self, image: Image.Image, policy: DetectionPolicy) -> Detections:
        """Boxes from the primary detector, or from the fallback when the primary cannot run."""
        tried: list[str] = []
        last_error: Exception | None = None
        for position, pin in enumerate(self._detector_pins):
            tried.append(pin.ref)
            try:
                if position == 0:
                    found = self._grounding_boxes(pin, image, policy)
                else:
                    found = self._owl_boxes(pin, image, policy)
            except Exception as error:  # the fallback exists for exactly this
                last_error = error
                continue
            return Detections(
                boxes=tuple(
                    deduplicate(
                        found,
                        iou_millionths=policy.duplicate_iou_millionths,
                        limit=policy.max_boxes,
                    )
                ),
                model=pin.ref,
                models_tried=tuple(tried),
                fallback_used=position > 0,
            )
        raise SegmenterUnavailable(
            f"no detector could run: tried {tried}, last error {last_error!r}"
        ) from last_error

    def _loaded(self, pin: LocalModelPin, kind: str) -> Any:
        if pin.ref in self._detectors:
            return self._detectors[pin.ref]
        from transformers import AutoTokenizer

        if kind == "grounding":
            from transformers import AutoModelForZeroShotObjectDetection
            from transformers.models.grounding_dino.image_processing_pil_grounding_dino import (
                GroundingDinoImageProcessorPil,
            )
            from transformers.models.grounding_dino.processing_grounding_dino import (
                GroundingDinoProcessor,
            )

            processor = GroundingDinoProcessor(
                image_processor=GroundingDinoImageProcessorPil.from_pretrained(
                    pin.repo_id, revision=pin.revision
                ),
                tokenizer=AutoTokenizer.from_pretrained(pin.repo_id, revision=pin.revision),
            )
            model = AutoModelForZeroShotObjectDetection.from_pretrained(
                pin.repo_id, revision=pin.revision
            )
        else:
            from transformers import Owlv2ForObjectDetection
            from transformers.models.owlv2.image_processing_pil_owlv2 import (
                Owlv2ImageProcessorPil,
            )
            from transformers.models.owlv2.processing_owlv2 import Owlv2Processor

            processor = Owlv2Processor(
                image_processor=Owlv2ImageProcessorPil.from_pretrained(
                    pin.repo_id, revision=pin.revision
                ),
                tokenizer=AutoTokenizer.from_pretrained(pin.repo_id, revision=pin.revision),
            )
            model = Owlv2ForObjectDetection.from_pretrained(pin.repo_id, revision=pin.revision)
        model.to(self._device).eval()
        self._detectors[pin.ref] = (model, processor)
        return self._detectors[pin.ref]

    def _grounding_boxes(
        self, pin: LocalModelPin, image: Image.Image, policy: DetectionPolicy
    ) -> list[BoxPrompt]:
        """Grounding DINO over the vocabulary, one label per box chosen by its own tokens.

        The processor's ``post_process_grounded_object_detection`` decodes a label from every
        token above a threshold, and MEASURED 2026-09-11 on the first volcanic photograph it
        returned ``'rock boulder cliff mountain hill'`` for one box: the five vocabulary words
        whose tokens all cleared it. So each vocabulary entry is scored here over its own token
        span and a box takes the best-scoring entry, which is always exactly one of them.
        """
        torch = self._torch
        model, processor = self._loaded(pin, "grounding")
        vocabulary = [word.lower() for word in policy.vocabulary]
        prompt = ". ".join(vocabulary) + "."
        encoded = processor.tokenizer(prompt, return_offsets_mapping=True)
        offsets = encoded["offset_mapping"]
        spans: list[list[int]] = []
        cursor = 0
        for word in vocabulary:
            start = prompt.index(word, cursor)
            end = start + len(word)
            cursor = end
            spans.append(
                [
                    index
                    for index, (left, right) in enumerate(offsets)
                    if right > left and left >= start and right <= end
                ]
            )
        if any(not tokens for tokens in spans):
            raise ValueError("a vocabulary entry has no tokens in the detector prompt")

        def forward(device: str) -> tuple[Any, Any]:
            inputs = processor(images=image, text=prompt, return_tensors="pt").to(device)
            with torch.no_grad():
                output = model(**inputs)
            return output.logits[0].float().sigmoid().cpu(), output.pred_boxes[0].float().cpu()

        probabilities, boxes = self._on_device(forward)
        scores = torch.stack(
            [probabilities[:, tokens].max(dim=-1).values for tokens in spans], dim=-1
        )
        best, labels = scores.max(dim=-1)
        found: list[BoxPrompt] = []
        threshold = policy.box_threshold_millionths / 1_000_000
        for query in range(best.shape[0]):
            score = float(best[query])
            if score <= threshold:
                continue
            centre_x, centre_y, width, height = (float(value) for value in boxes[query])
            rect = _normalised_rect(
                centre_x - width / 2,
                centre_y - height / 2,
                centre_x + width / 2,
                centre_y + height / 2,
            )
            if rect is not None:
                found.append(
                    BoxPrompt(
                        label=policy.vocabulary[int(labels[query])],
                        box=rect,
                        source="local_detector",
                        score_millionths=round(score * 1_000_000),
                    )
                )
        return found

    def _owl_boxes(
        self, pin: LocalModelPin, image: Image.Image, policy: DetectionPolicy
    ) -> list[BoxPrompt]:
        """OWLv2 over the same vocabulary, as text queries it was trained on."""
        torch = self._torch
        model, processor = self._loaded(pin, "owl")
        queries = [f"a photo of a {word}" for word in policy.vocabulary]
        threshold = policy.fallback_threshold_millionths / 1_000_000

        def forward(device: str) -> Any:
            inputs = processor(images=image, text=[queries], return_tensors="pt").to(device)
            with torch.no_grad():
                output = model(**inputs)
            return processor.post_process_grounded_object_detection(
                output, threshold=threshold, target_sizes=[(image.height, image.width)]
            )[0]

        result = self._on_device(forward)
        found: list[BoxPrompt] = []
        for score, label, box in zip(
            result["scores"].tolist(),
            result["labels"].tolist(),
            result["boxes"].tolist(),
            strict=True,
        ):
            rect = _normalised_rect(
                box[0] / image.width,
                box[1] / image.height,
                box[2] / image.width,
                box[3] / image.height,
            )
            if rect is not None:
                found.append(
                    BoxPrompt(
                        label=policy.vocabulary[int(label)],
                        box=rect,
                        source="local_detector",
                        score_millionths=round(float(score) * 1_000_000),
                    )
                )
        return found

    # -- masks ----------------------------------------------------------------------------------

    def segment(
        self, image: Image.Image, boxes: Sequence[Rect], policy: OutlinePolicy
    ) -> list[SegmentedMask | None]:
        """One mask per box, from one forward pass over the whole set."""
        if not boxes:
            return []
        import numpy as np

        torch = self._torch
        config = self._sam_config
        size = (int(config["size"]["width"]), int(config["size"]["height"]))
        square = image.resize(size, Image.Resampling(int(config.get("resample", 2))))
        mean = np.asarray(config["image_mean"], dtype=np.float32)
        std = np.asarray(config["image_std"], dtype=np.float32)
        pixels = np.asarray(square, dtype=np.float32) * float(config["rescale_factor"])
        pixels = (pixels - mean) / std
        scale_x = size[0] / PPM
        scale_y = size[1] / PPM
        prompt_boxes = [
            [
                box.x_ppm * scale_x,
                box.y_ppm * scale_y,
                (box.x_ppm + box.w_ppm) * scale_x,
                (box.y_ppm + box.h_ppm) * scale_y,
            ]
            for box in boxes
        ]

        def forward(device: str) -> tuple[Any, Any]:
            tensor = torch.from_numpy(pixels.transpose(2, 0, 1).copy()).unsqueeze(0).to(device)
            prompts = torch.tensor([prompt_boxes], dtype=torch.float32, device=device)
            with torch.no_grad():
                output = self._sam(pixel_values=tensor, input_boxes=prompts, multimask_output=False)
            upscaled = torch.nn.functional.interpolate(
                output.pred_masks[0].float(),
                (image.height, image.width),
                mode="bilinear",
                align_corners=False,
            )
            return (upscaled[:, 0] > 0).cpu().numpy(), output.iou_scores[0, :, 0].float().cpu()

        masks, qualities = self._on_device(forward)
        results: list[SegmentedMask | None] = []
        for mask, quality in zip(masks, qualities.tolist(), strict=True):
            traced = outline_from_mask(mask, policy)
            if traced is None:
                results.append(None)
                continue
            outline, area, components = traced
            results.append(
                SegmentedMask(
                    outline=outline,
                    confidence_millionths=max(0, min(1_000_000, round(quality * 1_000_000))),
                    area_millionths=area,
                    components=components,
                )
            )
        return results


def _preprocessor_config(pin: LocalModelPin) -> dict[str, Any]:
    """The checkpoint's own preprocessing, read rather than restated, and refused if unfamiliar.

    Every key this reads is checked, because a checkpoint revision that changed its normalisation
    would otherwise be preprocessed with the old constants and produce masks that look plausible.
    """
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(pin.repo_id, "preprocessor_config.json", revision=pin.revision)
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    size = config.get("size")
    if (
        not isinstance(size, dict)
        or set(size) != {"height", "width"}
        or config.get("do_resize") is not True
        or config.get("do_rescale") is not True
        or config.get("do_normalize") is not True
        or len(config.get("image_mean", ())) != 3
        or len(config.get("image_std", ())) != 3
    ):
        raise SegmenterUnavailable(
            f"{pin.ref} declares preprocessing this stage does not implement"
        )
    return config


def _normalised_rect(left: float, top: float, right: float, bottom: float) -> Rect | None:
    """A detector's corner box, clamped into the unit square and quantised, or None if empty."""
    left, right = max(0.0, min(1.0, left)), max(0.0, min(1.0, right))
    top, bottom = max(0.0, min(1.0, top)), max(0.0, min(1.0, bottom))
    if right <= left or bottom <= top:
        return None
    x, y = to_ppm(left), to_ppm(top)
    width = min(to_ppm(right), PPM) - x
    height = min(to_ppm(bottom), PPM) - y
    if width < 1 or height < 1:
        return None
    return Rect(x, y, width, height)
