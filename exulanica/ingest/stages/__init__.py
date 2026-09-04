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
from exulanica.ingest.vision import prompt_digest

__all__ = [
    "ARTIFACT_NAMESPACE",
    "KEY_FORMAT_VERSION",
    "STAGES",
    "StageSpec",
    "artifact_id_for",
    "binding_digest_of",
    "idempotency_key",
    "input_digest_of",
    "pipeline_digest",
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
    """

    key: str
    version: int
    output_kind: str
    deterministic: bool
    params: dict[str, Any] = field(default_factory=dict)
    model_role: str | None = None

    def __post_init__(self) -> None:
        canonical_json(self.params)  # refuse a float parameter at import, not at hash time

    @property
    def params_digest(self) -> bytes:
        return sha256_of_canonical(self.params)


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
        "schema_version": 1,
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
        # Version 2: a located person now becomes a scene-local occurrence. Version 1 recorded
        # the person labels in the artifact and wrote no occurrence for them, so a corpus
        # ingested at version 1 has people in its observations and none in its occurrence table.
        # That is a change in what the stage produces, which is exactly what this number is for:
        # the bump regenerates rather than leaving two incompatible corpora sharing one key.
        version=2,
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
        version=1,
        output_kind="pose_receipt",
        deterministic=True,
        params={
            "controller": "colmap-sparse-checkpointed",
            "receipt_profile": "exulanica.colmap-pose-receipt/v2",
            "min_registered_fraction": None,
            "max_mean_reprojection_error_px": None,
            "min_camera_translation_units": None,
        },
    ),
    "scene_placement": StageSpec(
        key="scene_placement",
        version=1,
        output_kind="point_map_placement",
        deterministic=True,
        params={
            "profile": "exulanica.posed-point-map-placement/v1",
            "opm_container": "opm/2",
            "scale_status": "unvalidated-identity",
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
