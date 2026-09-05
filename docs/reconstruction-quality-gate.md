# Reconstruction quality gate

Status: **implemented; first benchmark-calibrated pose policy verified 2026-09-04**.

`exulanica.reconstruction.validate_opm` now validates every production point map before it is
persisted. The PlayCanvas reader independently validates its untrusted byte boundary before it
constructs typed-array views. Both sides check the format, version, rung, explicit metric flag,
camera axes, source dimensions and aspect, field of view, bounds, section types, exact lengths,
alignment, and container range. Since OPM/2 ([adr/0010-opm-2.md](adr/0010-opm-2.md)) both also
refuse version 1 **by name**, with a message naming the regeneration path rather than a converter,
check that `colorAlpha` declares which quantity the alpha channel holds, and check `modelImage`
against `sourceImage` for reachability by one uniform resize rather than for equality.

**The division of labour between the two is per-point work, and it is deliberate.** The production
validator additionally checks every position is finite, in front of the source camera, and agrees
with the declared bounds; that every point uses a declared segment id inside the range the
renderer's semantic table can index; and that every reserved bit of the tags flags channel is
zero. The reader does none of those, because the one requirement of that module is no per-point
JavaScript: parsing cost must not land inside a number that is supposed to be about rendering.
Reading is therefore weaker than writing here, on purpose, and the writer's boundary is the one
that stands in front of a durable artifact.

The renderer exposes a source-panel envelope derived from the artifact's measured depth bounds and
source-camera frustum. That envelope is an observed presentation extent only. It is not navigation,
collision, an Atlas-space scale, or permission to move away from the source viewpoint.

`exulanica.reconstruction.quality` is the versioned report contract for the remaining real checks:

- structural OPM integrity;
- PlayCanvas consumption and actual load duration;
- authorized source opening and evidence linkage;
- visual alignment from the exact source-camera pose;
- metric versus non-metric behavior;
- deletion closure;
- production duration, byte size, and returned cost; and
- the valid-fraction distribution used to review the rung-3 threshold.

Missing values remain absent and block the gate. Synthetic or development observations can test the
contract but can never pass the real-corpus gate. The existing `min_valid_fraction_milli = 150`
stage parameter remains explicitly unvalidated and unchanged.

`max_depth_step_milli = 100` joins it as a second explicitly unvalidated parameter. It drops the
points that span a silhouette, which a monocular model produces wherever a pixel covers two
surfaces at different depths, and it was chosen on ONE photograph: at 100 it removed 3.04% of the
map and left the receding pavement and a bicycle standing proud of a wall intact, and at 50 it
began deleting that bicycle's frame and wheel rims. A single image is not a corpus, so the number
carries the same status as the one above and the same reason for being a stage parameter: an edit
changes the stage key and regenerates rather than leaving stale point maps behind. The
`discontinuityDropped` statistic now travels in every `.opm`, so the distribution needed to review
this threshold can be read off a real corpus the same way the valid fraction is. `oneSidedPoints`
joins it under OPM/2 and counts the survivors that lost a neighbour to that drop, which is the
population ADR-0010 D4's flag marks and a number that had never been measured.

No consented OGC-1 corpus, signed consent record, or real quality observations were found locally on
2026-08-31. Therefore Phase 3A has a productionized contract but has **not** passed its roadmap gate.

**CORRECTED 2026-09-04:** scene pose manifests previously wrote all three quality thresholds as
unmeasured constants even though the durable build input bound the `scene_pose` stage parameters.
The scene worker now decodes the exact bound stage policy into each pose manifest. Non-integral
thresholds remain integer-quantized in the canonical stage registry as millionths and are converted
to their declared units only at the pose manifest boundary. The current version 1 policy still
contains no measured values, so this correction changes no awarded rung. A future measured policy
will change both its stage version and parameter digest, queue a new build, and retain the old
unmeasured receipt rather than rewriting it.

**VERIFIED 2026-09-04:** the fixed synthetic scene and licensed ETH3D `pipes` scene both completed
the production pose path. The synthetic run registered 8 of 8 views with 0.256429 pixel mean
reprojection error and 9.757480 normalized camera-translation units. The benchmark run registered
14 of 14 views with 0.571911 pixel mean reprojection error and 10.915851 normalized units. Against
ETH3D's supplied cameras, similarity-aligned camera centres had 0.006594 ground-truth-unit RMS
error and 0.014844 maximum error over a 2.593471-unit camera extent. Maximum relative-rotation
error was 0.354748 degrees.

Stage `scene_pose` version 2 binds both evaluation-record digests and selects three integer policy
values by declared rules: the product specification's 80 percent registration floor, the smallest
whole-pixel ceiling above the largest observed reprojection error, and the greatest whole
normalized unit below the smallest observed camera extent. This yields 0.8, 1.0 pixel, and 9.0
normalized units. The last value is not a metric-distance claim. COLMAP normalizes reconstructions
to an extent of 10 units, so it is only a non-degeneracy check within this exact controller.

This is a strict first calibration from one synthetic and one indoor benchmark scene. It is not a
representative personal-photo threshold study. New corpus evidence must create a new stage version
and new build rather than changing version 2 in place. The retained benchmark comparison is
`evaluation/2026-09-04-benchmark-pose.json`.
