"""Reconstruction: one photograph becomes a metric point map, and never becomes evidence.

**Invariant 2 is structural here.** This package does not import ``exulanica.evidence``,
``exulanica.store`` or ``exulanica.db``, an import-linter contract enforces it, and
``tests/test_reconstruction_is_not_evidence.py`` fails if any module in here so much as names an
evidence address in a return annotation. A producer that cannot construct a citation cannot
return one, however it is later changed by somebody who never read this sentence.

That absence is the whole product's safety margin. Reconstruction quality never participates in
the truth guarantee: a region may degrade to a photograph on a plane and the factual promise is
unchanged, which is only true while a claim cannot resolve to geometry. The point map is stored,
rendered and displayed with the rung it earned; it is never what a citation opens.

**What is here.** A depth model behind a protocol, with MoGe-2 as the real implementation and a
flat plane as the double; the point-map builder that drops what the model could not place; the
``.opm`` writer the renderer reads; the quality gate that decides between rung 3 and rung 4 for
one photograph; and the job controllers for the rungs above it: ``pose`` for camera recovery,
``splat`` for scene-specific Gaussian training, and ``navigation`` for corridors.

**What "above rung 3" means here.** The controllers exist and are contract tested. ``pose`` has
an in-process ``pycolmap_executor``. ``splat`` invokes a digest-pinned execution image's reviewed
``exulanica-gsplat-scene-v1`` entrypoint; it does not substitute upstream ``simple_trainer.py``.
:mod:`exulanica.ingest.scene_reconstruction` calls ``pose`` and ``splat`` for a leased capture
set. A trained splat's appearance receipt does not promote a recorded scene rung; scale and
coverage gates remain separate. ``gate.py`` decides rung 3 or rung 4 for a single photograph and
is not the gate for the rungs above it; those are the quality receipts the controllers return.
"""

from __future__ import annotations

from exulanica.reconstruction.build import (
    DEFAULT_MAX_DEPTH_STEP,
    DEFAULT_SEGMENT,
    build_point_map,
)
from exulanica.reconstruction.depth import DepthModel, DepthPrediction
from exulanica.reconstruction.gate import MIN_VALID_FRACTION, RungDecision, decide_rung
from exulanica.reconstruction.navigation import (
    CorridorArtifact,
    CorridorBuildManifest,
    Destination,
    NavigationPoseSample,
    build_corridor_artifact,
    validate_corridor_artifact,
)
from exulanica.reconstruction.opm import (
    OPM_MAGIC,
    OPM_SECTIONS,
    OPM_VERSION,
    SUPERSEDED_OPM_VERSION,
    ColorAlpha,
    Viewpoint,
    encode_opm,
)
from exulanica.reconstruction.placement import (
    PLACEMENT_PROFILE,
    ExcludedPlacementMember,
    PlacedPointMap,
    PlacementRecord,
    PointMapInput,
    build_placement_record,
    validate_placement_record,
)
from exulanica.reconstruction.pointmap import (
    MAX_SEGMENT_ID,
    POINT_STRIDE_BYTES,
    RESERVED_TAG_FLAGS,
    TAG_ONE_SIDED,
    PointMap,
    Segment,
)
from exulanica.reconstruction.pose import (
    CommandResult,
    PoseBuildManifest,
    PoseJobResult,
    PoseQuality,
    RecoveredCamera,
    SourceFrame,
    run_colmap_pose_job,
)
from exulanica.reconstruction.scene_gate import (
    SCENE_GATE_PROFILE,
    ReceiptMeasurement,
    SceneGateDecision,
    SceneGateInputs,
    SceneReceipt,
    decide_scene_rung,
)
from exulanica.reconstruction.splat import (
    SplatBuildManifest,
    SplatJobResult,
    SplatQuality,
    run_gsplat_job,
)
from exulanica.reconstruction.validation import (
    OpmIntegrityError,
    OpmIntegrityReport,
    validate_opm,
)

__all__ = [
    "DEFAULT_MAX_DEPTH_STEP",
    "DEFAULT_SEGMENT",
    "MAX_SEGMENT_ID",
    "MIN_VALID_FRACTION",
    "OPM_MAGIC",
    "OPM_SECTIONS",
    "OPM_VERSION",
    "PLACEMENT_PROFILE",
    "POINT_STRIDE_BYTES",
    "RESERVED_TAG_FLAGS",
    "SCENE_GATE_PROFILE",
    "SUPERSEDED_OPM_VERSION",
    "TAG_ONE_SIDED",
    "ColorAlpha",
    "CommandResult",
    "CorridorArtifact",
    "CorridorBuildManifest",
    "DepthModel",
    "DepthPrediction",
    "Destination",
    "ExcludedPlacementMember",
    "NavigationPoseSample",
    "OpmIntegrityError",
    "OpmIntegrityReport",
    "PlacedPointMap",
    "PlacementRecord",
    "PointMap",
    "PointMapInput",
    "PoseBuildManifest",
    "PoseJobResult",
    "PoseQuality",
    "ReceiptMeasurement",
    "RecoveredCamera",
    "RungDecision",
    "SceneGateDecision",
    "SceneGateInputs",
    "SceneReceipt",
    "Segment",
    "SourceFrame",
    "SplatBuildManifest",
    "SplatJobResult",
    "SplatQuality",
    "Viewpoint",
    "build_corridor_artifact",
    "build_placement_record",
    "build_point_map",
    "decide_rung",
    "decide_scene_rung",
    "encode_opm",
    "run_colmap_pose_job",
    "run_gsplat_job",
    "validate_corridor_artifact",
    "validate_opm",
    "validate_placement_record",
]
