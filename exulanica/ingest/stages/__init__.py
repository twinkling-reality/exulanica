"""The stage registry and the derivative identity key.

A derivative's identity is ``(source_blob_sha256, stage_key, stage_version, params_digest,
input_digest, binding_digest)``. Not the capture id, because two captures of identical bytes
should share derivatives. Not the wall clock, obviously.

``binding_digest`` covers the part of a stage's identity that is resolved at run time rather
than declared in this file: for a model-backed stage, the identifier the stage will actually
call. A stage whose ``model_role`` is set cannot have a key computed without one, so swapping
the model behind a role cannot leave the corpus keyed as though nothing changed.

This is a **cost control as much as a correctness control**, and that is why it exists on day
one rather than being added when it hurts. Re-running the pipeline after changing one stage
regenerates that stage only. Retries re-bill nothing. Duplicate photographs, which are normal
in a personal library, compute their derivatives once.

This module is the package root because the registry IS what "stages" means in general: what
the stages are, and how a derivative produced by one is identified. The four modules beside it
are the stages themselves, one per key, and they are imported by name rather than re-exported
from here, so that importing the registry does not drag a database repository in behind it.
``scene_group`` is declared here and has no module beside it: it runs over the whole corpus
once the photographs are in, from ``exulanica.ingest.scenes``, rather than inside one file's run.

``version`` is bumped when **output semantics** change: a new model, a changed prompt, a
changed schema, a changed threshold. It is not bumped for a pure performance change. Every
semantic parameter is inside ``params``, so a threshold edit that someone forgets to record as
a version bump still changes the key and still forces regeneration.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.evidence.blob import BlobId
from exulanica.ingest.vision import SCHEMA_VERSION, prompt_digest
from exulanica.reconstruction.alignment import ALIGNMENT_POLICY
from exulanica.reconstruction.place_alignment import PLACE_ALIGNMENT_POLICY

__all__ = [
    "ARTIFACT_NAMESPACE",
    "KEY_FORMAT_VERSION",
    "STAGES",
    "ScenePoseQualityThresholds",
    "StageSpec",
    "artifact_id_for",
    "binding_digest_of",
    "idempotency_key",
    "input_digest_of",
    "pipeline_digest",
    "scene_pose_quality_thresholds",
    "stage",
    "vision_stage_params",
]

#: A fixed UUIDv5 namespace, so ``artifact_id`` is a pure function of the idempotency key on
#: every machine. Generated once and frozen; changing it orphans every existing artifact row.
ARTIFACT_NAMESPACE: Final = uuid.UUID("6f3d5b2e-8a41-5c6b-9d0e-1f2a3b4c5d6e")

#: Bumped when the *encoding* of the idempotency key changes, as distinct from the values that
#: go into it. Version 1 concatenated variable-length fields with no framing, so
#: ``("vision", 11)`` and ``("vision1", 1)`` hashed identically and two different stages could
#: silently share one artifact row. Version 2 length-prefixes every field. Bumping this
#: invalidates every existing key exactly once, which is the price of the encoding being
#: injective, and it is recorded here rather than in a commit message so that a package written
#: at version 1 can be recognised as such.
KEY_FORMAT_VERSION: Final = 2

#: Domain separation. This digest is not a hash of anything else in the system, and prefixing
#: it means it can never be confused with one.
_KEY_DOMAIN: Final = b"exulanica/idempotency-key"


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One pipeline stage: what it is, what version of it, and what it was parameterised with.

    ``deterministic`` is not decoration. When two runs sharing an idempotency key produce
    different content hashes, a deterministic stage emits ``nondeterminism_detected`` and a
    non-deterministic one does not, so a sampled generation is not reported as a fault while a
    changed resampling filter is.

    **What the flag does and does not claim (ADR-0017).** ``deterministic = True`` declares that a
    content difference on this stage is a **fault worth an event**. That is necessary for an
    exact-recomputation claim and is not the same as one: ``scene_pose`` sets it because a fixed
    ``random_seed`` makes a differing pose worth investigating, while
    ``exulanica/reconstruction/pycolmap_executor.py`` records that RANSAC threading still admits
    variation and that nobody has measured how much. Only a stage that is both declared
    deterministic and observed to reproduce may be described as exactly recomputable.

    ``deterministic = False`` is required of every stage carrying a ``model_role``, enforced
    below. A model-produced artifact is not bit-reproducible, and no wording anywhere in this
    product may imply that it is.
    """

    key: str
    version: int
    output_kind: str
    deterministic: bool
    params: dict[str, Any] = field(default_factory=dict)
    model_role: str | None = None

    def __post_init__(self) -> None:
        canonical_json(self.params)  # refuse a float parameter at import, not at hash time
        if self.model_role is not None and self.deterministic:
            # ADR-0017. A stage that calls a model may not claim byte reproducibility. Sampled
            # generation differs run to run by design, and a neural forward pass differs across
            # accelerators and library versions even at temperature zero. Declaring one
            # deterministic would file every legitimate difference as a fault and, worse, would
            # put a stage behind the exact-recomputation claim that cannot support it.
            raise ValueError(
                f"stage {self.key!r} names model role {self.model_role!r} and declares itself "
                "deterministic. A model-produced artifact is not bit-reproducible; see "
                "docs/adr/0017-exact-recomputation.md."
            )

    @property
    def params_digest(self) -> bytes:
        return sha256_of_canonical(self.params)


@dataclass(frozen=True, slots=True)
class ScenePoseQualityThresholds:
    """Pose thresholds decoded from the registry's integer-only canonical parameters."""

    min_registered_fraction: float | None
    max_mean_reprojection_error_px: float | None
    min_camera_translation_units: float | None


def scene_pose_quality_thresholds(spec: StageSpec) -> ScenePoseQualityThresholds:
    """Decode a scene-pose policy without allowing floats into its digest input."""
    if spec.key != "scene_pose":
        raise ValueError("pose quality thresholds require the scene_pose stage")
    fields = (
        (
            "min_registered_fraction",
            "min_registered_fraction_millionths",
            1_000_000,
            1_000_000,
        ),
        (
            "max_mean_reprojection_error_px",
            "max_mean_reprojection_error_micropixels",
            1_000_000,
            None,
        ),
        (
            "min_camera_translation_units",
            "min_camera_translation_microunits",
            1_000_000,
            None,
        ),
    )
    decoded: list[float | None] = []
    for legacy_key, quantized_key, denominator, maximum in fields:
        legacy = spec.params.get(legacy_key)
        if legacy is not None:
            raise ValueError(
                f"{legacy_key} must be replaced by the integer {quantized_key} parameter"
            )
        value = spec.params.get(quantized_key)
        if value is None:
            decoded.append(None)
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{quantized_key} must be a positive integer")
        if maximum is not None and value > maximum:
            raise ValueError(f"{quantized_key} exceeds its allowed maximum")
        decoded.append(value / denominator)
    return ScenePoseQualityThresholds(*decoded)


#: The measured rendition size. Image tokens are strongly sub-linear in pixel area: 277 tokens
#: at 256 px and 772 at 768 px, so nine times the area costs 2.8 times the tokens. Downscaling
#: below this buys almost nothing and throws away the legible signage that the OCR and place
#: proposal both depend on.
_RENDITION_MAX_EDGE: Final = 768


def vision_stage_params() -> dict[str, Any]:
    """The vision stage's parameters, **derived from the prompt text every time it is called**.

    A function rather than a literal so that "what the registry would say if the prompt were
    edited" is answerable without anybody writing a digest down. That is what makes the
    reprocessing rule testable: a test can edit the prompt template and rebuild the parameters
    through this same expression, and if the expression ever goes back to a hand-maintained
    version integer the rebuilt parameters stop moving and the test fails.
    """
    return {
        # Derived, never restated. It was the literal 1 while the observation schema moved to 2,
        # which is the same class of bug the prompt digest below exists to prevent: a number
        # somebody has to remember to bump is a number that silently stops describing the thing.
        "schema_version": SCHEMA_VERSION,
        # The computed digest of the actual prompt text, never a hand-maintained integer. A
        # version integer is a thing somebody has to remember to bump, and the symptom of
        # forgetting is a corpus that silently never reprocesses after a prompt edit: the
        # instruction "never write a person's name" could be reversed and every idempotency key
        # would be unmoved. The digest cannot be forgotten, because nobody maintains it.
        "prompt_sha256": prompt_digest(),
        "max_tokens": 2000,
        "temperature_milli": 0,
        "response_format": "json_schema_strict",
    }


STAGES: Final[dict[str, StageSpec]] = {
    "intake": StageSpec(
        key="intake",
        version=1,
        output_kind="probe",
        deterministic=True,
        params={
            "extractor": "pillow_exif",
            "orientation_policy": "normalise_pixels_at_ingest",
            "probe_version": 1,
        },
    ),
    "rendition": StageSpec(
        key="rendition",
        # Version 2 disables libjpeg's optional entropy-table optimisation. Version 1 always
        # requested it, but Pillow's encoder can fail on ordinary high-entropy images with
        # ``broken data stream when writing image file``.
        # This changes the encoded bytes, so it is a versioned output change rather than an
        # unrecorded implementation fallback.
        version=2,
        output_kind="rendition",
        deterministic=True,
        params={
            "max_edge_px": _RENDITION_MAX_EDGE,
            "format": "JPEG",
            "quality": 90,
            "subsampling": "4:4:4",
            "optimize": False,
            "resample": "lanczos",
            "colour_space": "sRGB",
            "orientation": "display",
        },
    ),
    "vision": StageSpec(
        key="vision",
        # Version 3: people have their own field in the observation schema, and it asks for
        # partial traces by name. Version 2 told the model NOT to list people in `objects` and
        # then filtered `objects` for them against a whitelist of singular nouns, so the field a
        # person could appear in was one the model had been told to leave them out of, and the
        # filter matched none of "arms", "hands" or "diners". MEASURED against the retained bowl
        # photographs' own review: those are exactly the traces that collection contains. The new
        # field also drops the free-text label for a person, so the model no longer writes a
        # description of somebody who has not consented to being described.
        #
        # Version 2 recorded a located person as a scene-local occurrence, which version 1 did
        # not; that behaviour is unchanged here.
        version=3,
        output_kind="vision_observation",
        deterministic=False,
        model_role="vision",
        params=vision_stage_params(),
    ),
    "depth": StageSpec(
        key="depth",
        version=1,
        output_kind="point_map",
        # A neural depth model is not deterministic in the sense this flag means: the same
        # weights on the same bytes can differ across accelerators and across library versions.
        # Marking it false is what stops a legitimate difference being reported as a fault.
        deterministic=False,
        model_role="depth",
        params={
            # UNVALIDATED DEFAULTS, in the parameters rather than in constants precisely because
            # the corpus that would validate them is the thing this stage exists to produce. An
            # edit changes the stage key and regenerates, so a later tuning pass cannot leave
            # stale rungs behind.
            "min_valid_fraction_milli": 150,
            # The longest edge handed to the model. Monocular depth cost is quadratic in pixels
            # and a point map is 20 bytes per pixel, so this is a size decision and a storage
            # decision at once: 512 is roughly 190k points and 3.8 MB per photograph.
            "max_edge_px": 512,
            # How far a point's depth may disagree with its neighbour's before it is read as
            # spanning a silhouette rather than lying on a surface. Milli, like the fraction
            # above, so the params stay integers and the digest stays stable across platforms
            # that would not agree on the last bit of a float.
            "max_depth_step_milli": 100,
            # OPM/2, per ADR-0010. The version is in here rather than in a constant precisely
            # because it belongs in the idempotency key: the bump has to regenerate, since D9 is
            # refuse and regenerate and both validators now refuse version 1 by name. Editing
            # this string is what reprices every artifact row, which is the whole reason the
            # record says to do it before a corpus exists rather than after.
            "container": "opm/2",
        },
    ),
    "scene_group": StageSpec(
        key="scene_group",
        version=1,
        output_kind="scene_group",
        deterministic=True,
        params={
            # Unvalidated defaults. They are parameters rather than constants precisely because
            # the corpus has not been inspected yet: an edit changes the key and regenerates,
            # so a later tuning pass cannot silently leave stale groups behind.
            "max_time_gap_s": 3600,
            "max_distance_m": 250,
            "algorithm": "sequential_time_then_distance",
        },
    ),
    "scene_pose": StageSpec(
        key="scene_pose",
        # Version 4 corrects the camera-translation floor after the first real captures; it keeps
        # version 3's retained sparse tracks, calibration record and receipt profile unchanged.
        # Version 2 closed the unmeasured policy after the fixed synthetic and licensed ETH3D
        # pipes runs, and its floor of 9.0 units was the greatest whole unit below those two runs
        # (9.76 and 10.92). COLMAP normalizes the central camera centres of a sparse model to an
        # extent of 10 units, so the maximum pairwise camera distance of any model it could
        # normalize lies near 10, while a model of near-coincident centres reports near zero.
        # MEASURED 2026-09-05 on the first retained real collection: two fully registered handheld
        # captures circling one subject, 0.85 px mean reprojection error, measured 8.13 and 8.96
        # units and were refused, while a third run of the same 51 photographs measured above 9 and
        # passed. A floor that a nondeterministic mapper crosses at random is not a policy. 5.0 is
        # a normalized non-degeneracy check and nothing more: it refuses only a model whose camera
        # centres could not be normalized, and no measured capture, real or fixed, approaches it.
        # The calibration record is part of the parameter digest so later corpus evidence cannot
        # silently change what this version meant.
        version=4,
        output_kind="pose_receipt",
        deterministic=True,
        params={
            "controller": "colmap-sparse-checkpointed",
            "alignment_observations": "colmap-point-tracks/v1",
            "recovered_camera_calibration": "colmap-model-parameters/v1",
            "max_sparse_observations_per_image": 4096,
            "receipt_profile": "exulanica.colmap-pose-receipt/v2",
            "min_registered_fraction_millionths": 800_000,
            "max_mean_reprojection_error_micropixels": 1_000_000,
            "min_camera_translation_microunits": 5_000_000,
            "calibration": {
                "profile": "exulanica.scene-pose-policy-calibration/v1",
                "synthetic_pose_evaluation_sha256": (
                    "dc0680b24fc85ba3ebe2ed55d3ed92a10e9ea161ded9701b73014c336808c5d7"
                ),
                "benchmark_pose_evaluation_sha256": (
                    "68640ca95fce5adf54d8217b53139a4706edf6c6430cd6d854b58079b59408d8"
                ),
                "colmap_normalization_extent_microunits": 10_000_000,
                "observed": {
                    "registered_fraction_millionths_min": 1_000_000,
                    "mean_reprojection_error_micropixels_max": 571_911,
                    "camera_translation_extent_microunits_min": 9_757_480,
                },
                "real_capture_observations": [
                    {
                        "collection": "chili-salmon-bowl",
                        "photographs": 40,
                        "registered_fraction_millionths": 1_000_000,
                        "mean_reprojection_error_micropixels": 852_567,
                        "camera_translation_extent_microunits": 8_132_481,
                        "pose_receipt_sha256": (
                            "2976a64d54ecb4e8dc8d53533b84e38cb4996176efb7655f96b60ded982cb883"
                        ),
                    },
                    {
                        "collection": "chili-salmon-bowl",
                        "photographs": 51,
                        "registered_fraction_millionths": 1_000_000,
                        "mean_reprojection_error_micropixels": 846_657,
                        "camera_translation_extent_microunits": 8_961_565,
                        "pose_receipt_sha256": (
                            "c582bb5d4a7f239b09ce8f776a06528d5d15af4d04f244d2accef446d7cffd95"
                        ),
                    },
                ],
                "selection_rule": {
                    "registered_fraction": (
                        "product specification 80 percent floor, validated below both runs"
                    ),
                    "reprojection_error": (
                        "smallest whole-pixel ceiling above the maximum observed error"
                    ),
                    "camera_translation": (
                        "half the COLMAP normalization extent: refuses only a model whose camera "
                        "centres could not be normalized, below every measured capture"
                    ),
                },
            },
        },
    ),
    "scene_placement": StageSpec(
        key="scene_placement",
        version=2,
        output_kind="point_map_placement",
        deterministic=True,
        params={
            "profile": "exulanica.posed-point-map-placement/v2",
            "alignment": ALIGNMENT_POLICY,
            "opm_container": "opm/2",
            "scale_status": "colmap-correspondence-fit",
        },
    ),
    "scene_splat_training": StageSpec(
        key="scene_splat_training",
        version=1,
        output_kind="scene_splat_receipt",
        deterministic=False,
        params={
            "profile": "exulanica.scene-splat-publication/v1",
            "runner": "exulanica.gsplat-scene-runner/v1",
        },
    ),
    "scene_splat_delivery": StageSpec(
        key="scene_splat_delivery",
        version=1,
        output_kind="gaussian_splat_scene",
        deterministic=False,
        params={
            "container": "sog/1",
            "coordinate_frame": "unchanged-COLMAP-world",
            "profile": "exulanica.scene-splat-publication/v1",
        },
    ),
    "scene_splat_evaluation": StageSpec(
        key="scene_splat_evaluation",
        # Version 2 raises only the retained-byte budget. MEASURED 2026-09-05/06: the 210-photograph
        # volcanic set holds out 27 views at 12 MP; its first bundle (PNG renders plus rectified
        # references) was 266.9 MB and passed the 256 MiB budget by 1.5 MB, its second exceeded it
        # and the completed run lost its receipt and bundle. 1 GiB keeps every held-out view of a
        # capture that size at full resolution; the bundle format is unchanged.
        version=2,
        output_kind="scene_splat_evaluation_bundle",
        deterministic=True,
        params={
            "profile": "exulanica.scene-splat-evaluation/v1",
            "container": "zip-stored/1",
            "max_bytes": 1_073_741_824,
            "files": ["metrics", "runtime", "split", "preparation", "attempts", "heldout-pixels"],
            "delivery": "private-operational-artifact-no-browser-route",
        },
    ),
    "generated_scene": StageSpec(
        key="generated_scene",
        version=1,
        output_kind="generated_scene",
        # A model produced these bytes, so they are not bit-reproducible and a content difference
        # between two runs is not a fault. ADR-0017 follows from this flag: a generated artifact is
        # REMOVED on deletion, never regenerated, because re-running a sampled generation would
        # produce different bytes and an exactness claim over them would be false.
        deterministic=False,
        # No `model_role`, deliberately, and this is not an oversight to be tidied up. A role names
        # a slot the platform routes through its own reviewed model manifest; the model here is
        # supplied per generation by whoever is generating, and its identity travels in the
        # receipt rather than in a registry entry. The stage's model identity therefore reaches
        # the artifact through `generation_input_digest`, which folds model, version, prompt digest
        # and every conditioning digest into `input_digest`, so a model swap produces a different
        # artifact id. See `exulanica/reconstruction/generated.py`.
        params={
            "profile": "exulanica.generated-scene/v1",
            "tier": "generated",
            "below_every_recorded_rung": True,
            "citable": False,
            "promotes_rung": False,
        },
    ),
    "scene_gate": StageSpec(
        key="scene_gate",
        version=1,
        output_kind="scene_gate_receipt",
        deterministic=True,
        params={
            "profile": "exulanica.reconstruction-scene-gate/v1",
            "policy": "highest-complete-accepted-receipt-chain",
        },
    ),
    "person_regions": StageSpec(
        key="person_regions",
        version=1,
        output_kind="person_region_list",
        # Deterministic, and the detector is pinned HERE rather than resolved at run time. The
        # obvious alternative is `model_role="person_detector"`, which would put the detector in
        # the run-time binding; it was rejected for two reasons. It would make this stage
        # model-backed, which ADR-0017 requires to be `deterministic=False`, and that would drag
        # `person_regions` into the exact-recomputation exclusion sentence AND into
        # `docs/evaluation/2026-09-05-unblocked-goal-d.json`, whose bytes are digest-pinned twice
        # by the backend-program record. Editing a dated record of an executed measurement to
        # accommodate a stage that did not exist when it ran is not a maintenance chore, it is a
        # false claim about what was measured.
        #
        # Pinning the detector in `params` gets the property that mattered without any of that:
        # `run` refuses a detector whose `model_id` is not this string, so swapping detectors
        # without editing this line is a hard error rather than a corpus silently keyed as though
        # nothing changed. A future detector that runs a real model on the pixels IS model-backed
        # and would take `model_role` and a version bump at that point, deliberately.
        deterministic=True,
        params={
            "profile": "exulanica.person-region-list/v1",
            # The contract a detector must satisfy, not one detector's name. The resolved
            # detector's identity goes into this stage's INPUT digest instead, per photograph,
            # which gets the property the design note wanted -- swapping a detector regenerates
            # rather than silently reusing the old regions -- while still allowing a test double
            # and a future real segmenter to run through the same stage. Pinning a single literal
            # here made the stage refuse every detector but one, including its own test doubles.
            "detector_contract": "exulanica.person-detector/v1",
            # Bodies, not faces. Clothing, tattoos, hands and posture identify people, so a region
            # covers the whole silhouette and a face-only detector does not satisfy this stage.
            "scope": "whole-silhouette-not-face",
            # Vertices are integers in parts per million of the upright unit square, the grid
            # `exulanica.evidence.region` froze. A polygon enters a digest and a detector's last
            # float bit is not a fact; `canonical_json` refuses floats outright.
            "coordinate_units": "ppm-of-upright-unit-square",
            "coordinate_space": "upright-display",
            # A person the detector could not locate masks the whole photograph. Reconstructing
            # somebody because nobody could say where they were is the failure this design exists
            # to prevent, and a smaller default would be a guess about where they were not.
            "unlocated_person_policy": "mask-whole-image",
            # Nothing this stage writes is a decision. A region is unconfirmed until a human
            # reviews it, and `masked_source` reads the confirmed list rather than this artifact.
            "review_state_default": "unconfirmed",
            # No embedding, descriptor or keypoint set is produced or stored. Recorded as a
            # parameter so that a detector which did produce one would be a new stage version
            # rather than a quiet change of posture.
            "biometric_template": "never",
        },
    ),
    "masked_source": StageSpec(
        key="masked_source",
        version=1,
        output_kind="masked_source",
        # No model runs here. The inputs are the exact source bytes, the confirmed outlines as
        # parts-per-million integers, and the resolved consent-state digest; the operation is an
        # integer scanline, an integer dilation and a per-pixel select. Per ADR-0017 this flag
        # declares that a content difference is a fault worth an event, and claims nothing more.
        deterministic=True,
        params={
            "profile": "exulanica.masked-source/v1",
            # Neutral, never generative. A generated fill would be a claim about what was behind
            # a person; the design note puts that out of scope and the status says the area is
            # blank rather than pretending it was never occupied.
            "fill": "neutral-flat",
            "fill_srgb": [128, 128, 128],
            # Grown before filling, in millionths of the longest edge. A mask cut exactly on a
            # detector's boundary leaves a rim of the person's own pixels, which is the difference
            # between hiding somebody and outlining them.
            "dilation_millionths": 8_000,
            # Encoder settings live here for the reason rendition's do: a changed quality changes
            # the bytes, and a change that did not move the stage digest would leave two different
            # derivatives sharing one artifact row. `optimize` is False for the reason rendition
            # version 2 records, that libjpeg's entropy optimisation fails on ordinary images.
            "format": "JPEG",
            "quality": 95,
            "subsampling": "4:4:4",
            "optimize": False,
            "orientation": "display",
        },
    ),
    "masked_source_manifest": StageSpec(
        key="masked_source_manifest",
        version=1,
        output_kind="masked_source_manifest",
        deterministic=True,
        params={
            # Its own stage, and its own artifact row, because `persist_artifact` writes one
            # payload per run and both the image and the manifest have to be reachable by the
            # tombstone and purge paths. A manifest that lived only inside the image's metadata
            # could not be found by a withdrawal looking for what to destroy.
            "profile": "exulanica.masked-source-manifest/v1",
        },
    ),
    "place_alignment": StageSpec(
        key="place_alignment",
        version=1,
        output_kind="place_alignment_receipt",
        # Deterministic in the sense this flag actually carries, which is `scene_pose`'s sense
        # and nothing more: a content difference between two runs of one union under one policy
        # is a fault worth an event. It is not a claim of bit reproduction. This stage runs the
        # same mapper `scene_pose` does, and `pycolmap_executor` records that RANSAC threading
        # still admits variation and that nobody has measured how much.
        deterministic=True,
        # No `model_role`, and that is a decision rather than an omission. Nothing here calls a
        # model: the joint run is COLMAP and the fit is arithmetic. Naming a role would force
        # `deterministic=False` under ADR-0017, which would drag this stage into the
        # exact-recomputation exclusion sentence in `docs/domain-and-evidence-model.md` and into
        # the digest-pinned `docs/evaluation/2026-09-05-unblocked-goal-d.json`, and amending a
        # dated record of an executed measurement so a later stage fits is a false claim about
        # what was measured.
        params={
            "profile": "exulanica.place-alignment-receipt/v1",
            # The fitter's own policy, imported rather than restated, exactly as
            # `scene_placement` embeds `ALIGNMENT_POLICY`. A changed tolerance therefore changes
            # this stage's identity instead of silently reinterpreting a recorded refusal.
            # Integer only, which is what lets it into a digest input at all.
            "alignment": PLACE_ALIGNMENT_POLICY,
            # The joint sparse model is a third frame that no scene is addressed in. It is a
            # build intermediate and its digest travels in the receipt; promoting it to citable
            # geometry would put a place's history in a frame nothing else resolves.
            "joint_model": "build-intermediate-not-retained",
            # A place's shared frame is its anchor scene's own recovered frame, so the anchor's
            # transform is identity and every other version's is measured or composed toward it.
            "frame": "anchor-scene-recovered-frame",
            # Both frames are recovered COLMAP frames. Two captures sharing one is a statement
            # about their consistency with each other and about nothing physical.
            "physically_validated": False,
        },
    ),
}


def stage(key: str) -> StageSpec:
    try:
        return STAGES[key]
    except KeyError:
        raise KeyError(f"no stage {key!r}; the registry declares {sorted(STAGES)}") from None


def input_digest_of(input_content_hashes: list[bytes]) -> bytes:
    """SHA-256 over the sorted content hashes of a stage's inputs.

    Sorted, so the key does not depend on the order a worker happened to resolve its inputs.
    An empty list is a real value, not a missing one: a source stage genuinely has no inputs
    beyond the blob, which is already named separately in the key.
    """
    return sha256_of_canonical([digest.hex() for digest in sorted(input_content_hashes)])


def binding_digest_of(binding: Mapping[str, str] | None) -> bytes:
    """SHA-256 over the run-time binding of a stage. Empty binding is a real, stable value."""
    return sha256_of_canonical(dict(binding or {}))


def _require_binding(spec: StageSpec, binding: Mapping[str, str] | None) -> Mapping[str, str]:
    """A model-backed stage must name the model it will call. Nothing else may name one.

    This is the structural half of the fix for "swapping the model did not reprocess". The
    resolved identifier is not in ``params`` because it does not live in this file: it comes
    from the manifest at run time. Making it a mandatory argument means a new model-backed
    stage cannot be added without deciding what identifier its key covers.
    """
    resolved = dict(binding or {})
    for name, value in resolved.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"stage {spec.key!r}: binding {name!r} must be a non-empty string")
    if spec.model_role is not None:
        if not resolved.get("model_id"):
            raise ValueError(
                f"stage {spec.key!r} calls the {spec.model_role!r} role, so its idempotency key "
                "must name the resolved model_id. Without it, swapping the model behind the role "
                "would leave every artifact keyed as though nothing had changed and the corpus "
                "would never reprocess."
            )
    elif resolved:
        raise ValueError(
            f"stage {spec.key!r} declares no model_role, so it has no run-time binding; "
            f"passing {sorted(resolved)} would change its key for no recorded reason"
        )
    return resolved


def idempotency_key(
    source_blob: BlobId,
    spec: StageSpec,
    input_digest: bytes,
    *,
    binding: Mapping[str, str] | None = None,
) -> str:
    """``hex(sha256(domain, format, blob, stage_key, version, params, inputs, binding))``.

    Every field is **length-prefixed** before it is hashed. Plain concatenation of
    variable-length fields is not injective: with ``stage_key || stage_version``, the pair
    ``("vision", 11)`` and the pair ``("vision1", 1)`` both produce the bytes ``vision11``, so
    two different stages would compute one key, share one artifact row, and each read the
    other's output as its own cached result. Framing removes the ambiguity rather than relying
    on no stage key ever ending in a digit.
    """
    resolved = _require_binding(spec, binding)
    hasher = hashlib.sha256()
    for part in (
        _KEY_DOMAIN,
        str(KEY_FORMAT_VERSION).encode("ascii"),
        source_blob.digest,
        spec.key.encode("utf-8"),
        str(spec.version).encode("ascii"),
        spec.params_digest,
        input_digest,
        binding_digest_of(resolved),
    ):
        hasher.update(len(part).to_bytes(8, "big"))
        hasher.update(part)
    return hasher.hexdigest()


def artifact_id_for(key: str) -> uuid.UUID:
    """Deterministic ``artifact_id``, so a retry inserts the same row rather than a second."""
    return uuid.uuid5(ARTIFACT_NAMESPACE, key)


def pipeline_digest(bindings: Mapping[str, Mapping[str, str]] | None = None) -> str:
    """A short digest over the whole registry, for "already processed at this version".

    Computed from the registry rather than maintained by hand. A hand-maintained version
    integer is forgotten exactly once, and the symptom is a corpus that silently never
    reprocesses after a prompt change.

    ``params`` now carries the vision prompt's own SHA-256, so an edit to the prompt text moves
    this digest without anybody remembering to bump anything. ``bindings`` carries the run-time
    half, keyed by stage: pass ``{"vision": {"model_id": ...}}`` and swapping the model behind
    the role moves the digest too. It is an argument rather than a manifest lookup so that this
    function stays pure and a run with a stubbed model reports the model it actually used.
    """
    supplied = bindings or {}
    payload = {
        key: {
            "version": spec.version,
            "params": spec.params,
            "model_role": spec.model_role,
            "binding": dict(supplied.get(key, {})),
        }
        for key, spec in sorted(STAGES.items())
    }
    return sha256_of_canonical(payload).hex()[:16]
