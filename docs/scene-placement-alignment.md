# Correspondence-based point-map placement

Implemented 2026-09-05. This corrects the identity-scale limitation documented in
`scene-reconstruction-operations.md`. Verification here concerns numeric synthetic geometry and
production lifecycle behavior; it is not a visual-quality acceptance for a real scene.

## Invariant and representation

A registered photograph receives a scene transform only when its exact OPM bytes can be aligned
to actual COLMAP sparse correspondences. Missing or inconsistent correspondence never substitutes
an identity scale. Pose registration alone does not establish that a monocular point map fits it.

`scene_pose` version 3 preserves version 2's pose thresholds and calibration and additionally
retains actual COLMAP model parameters, image dimensions and a bounded, deterministic sample of COLMAP pixel/3D tracks in each
recovered camera. Version 4 keeps all of that and lowers only the camera-translation floor to 5.0
normalized units after the first real captures showed the 9.0 floor refusing fully registered,
sub-pixel reconstructions; see [scene operations](scene-reconstruction-operations.md). Real COLMAP
output can also list one image observing the same sparse point at two keypoints; the receipt drops
every observation of such a point from that image rather than choosing a keypoint. The sparse text files remain bound by the pose artifact inventory; camera and
observation fields enter the quality digest. No learned feature descriptors are persisted.

`scene_placement` version 2 emits `exulanica.posed-point-map-placement/v2`. It binds every supplied
point-map artifact and digest, including maps excluded from rendering. Per-member diagnostics
record correspondence counts, spatial coverage, fitting and validation inliers, residuals, and
`physically_validated: false`. Both accepted placements and exclusions are reproducible from exact
pose and point-map bytes.

The transform is `scene_from_opm = [s R^T diag(1,-1,-1), -R^T t; 0,0,0,1]`, stored row-major.
It acts directly on raw OPM coordinates. `local_units_to_scene_units = s` describes the scale
already in its linear block; a consumer must not multiply positions by it a second time.
Camera centres are not scaled by the per-image fit. OPM axes remain +X right, +Y up, -Z forward;
scene coordinates remain the selected COLMAP world with no assumed gravity or physical unit.

## Fitting and refusal

The producer reconstructs the OPM's model-image sample lattice from its declared centred pinhole
camera, matches COLMAP pixels to actual retained samples, and uses each sample at most once.
Tracks need at least two observations and at most two pixels of sparse reprojection error.
The backend's existing mapping policy continues to decide which tracks can be reconstructed.

A deterministic fold based on model-image sample location reserves every fifth correspondence
for validation before fitting. A robust median scalar fits all three camera-space components of
the remaining correspondences, followed by an inlier refit. Rotation and translation are taken
from COLMAP and are not fitted over monocular points. All-three-component residuals prevent a
wrong focal geometry from passing solely because its depth ratio agrees.

The initial engineering rejection policy requires at least 24 fitting samples, six validation
samples, and six occupied cells of a 4-by-4 source-image grid. Fitting and validation each need
at least 60 percent inliers within 15 percent relative 3D residual. These limits are versioned
engineering choices, not corpus-calibrated quality claims. P90 residual is retained for inspection;
it is not a second acceptance threshold. The full integer policy enters stage identity.

Exclusions are `pose-not-registered`, `point-map-unavailable`, `alignment-unavailable`,
`alignment-insufficient-correspondences`, or `alignment-inconsistent`. Every exclusion retains
ordinary source access. A consistent fit records `scale_status: colmap-correspondence-fit`.
Agreement between models does not establish metres, collision, navigability, complete surfaces,
or visual quality and does not promote the reconstruction rung.

## Compatibility and affected surfaces

Version 1's `unvalidated-identity` placement is not upgraded or reinterpreted. Its current graph
delivery falls back to source photographs until a new exact build runs under the new stage
versions. No frozen migration changes and no database schema change are required. Exact build
inputs, current-build publication, artifact provenance, authorization and deletion paths remain
in place. Scene identity is unchanged by a new build.

The normal worker reads digest-verified OPM bytes and computes the fit before publication. Graph
and World Memory Package delivery revalidate available members against the same bytes. If one
map is missing or corrupt, its geometry is withheld while healthy members remain available;
the durable recorded rung is preserved. A malformed scene receipt withholds the scene's geometry.
The browser validates and applies the fitted similarity transform, with the scalar exactly once.

Registered members also expose an independent recovered camera from an accepted pose receipt.
Its renderer-camera-to-scene transform has unit scale and uses the actual recovered camera centre.
Calibration retains `fx`, `fy`, `cx`, `cy`, image dimensions, model name and every original parameter.
PINHOLE/SIMPLE_PINHOLE projection is exact; distortion models disclose `pinhole-approximation`.
This supports calibrated arrival and viewing of a trained SOG even when every OPM is unavailable,
without changing the recorded rung or inferring physical units.

## Verification and limitations

`tests/test_reconstruction_placement.py` and `tests/test_reconstruction_pose.py` passed 29 tests.
Ten isolated mutations of production code were executed and all were detected, including an
identity fallback, omitted byte-digest check, omitted validation-fold gate, false physical-scale
claim, discarded COLMAP tracks, and doubled/missing scale handling. The restored source copy
passed all 29 tests again. The retained digest-bound result is
`evaluation/2026-09-05-placement-alignment.json`.

The scene-worker test fixture now uses genuine OPM containers and one numeric plane projected
consistently through each declared camera, rather than arbitrary placeholder bytes. The root
verification run owns serialized database testing and its retained report. This module's work
did not access a database.

Real scenes may fail these limits or retain nonrigid monocular depth distortion despite passing.
Scale-only alignment cannot correct arbitrary depth warping, repair missing surfaces, or establish
a supported navigation envelope. A retained real-scene visual inspection and independent physical
reference, when metric scale is needed, remain separate requirements.
