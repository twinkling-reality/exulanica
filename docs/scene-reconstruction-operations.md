# Reconstruction scenes

Reconstruction is one way to build a world: an admitted set of photographs of a real place becomes
a scene a world can place and draw. This contract owns that pipeline from an exact capture set to
a published scene: selection, the durable job, pose recovery, point-map placement, the quality
gate and recorded rung, the graph projection, delivery, deletion and the scene worker.

Neighbouring owners: scene training in [gsplat-scene-jobs.md](gsplat-scene-jobs.md), object and
person segments in [scene-segments.md](scene-segments.md), coverage verdicts before a run in
[capture-overlap-and-recovery-state.md](capture-overlap-and-recovery-state.md), admission and model
rights in [personal-admission.md](personal-admission.md), masking and screening in
[person-presentation-consent.md](person-presentation-consent.md), and serving under current
permission in [asset-read-currency.md](asset-read-currency.md). The product guide is
[capabilities/scene-reconstruction.md](capabilities/scene-reconstruction.md).

## Contents

- [1. Scene selection and the durable job](#1-scene-selection-and-the-durable-job)
- [2. Durable artifact chain](#2-durable-artifact-chain)
- [3. Placement: coordinates, scale and correspondence fitting](#3-placement-coordinates-scale-and-correspondence-fitting)
- [4. Graph delivery and rendering](#4-graph-delivery-and-rendering)
- [5. Quality gate and recorded rung](#5-quality-gate-and-recorded-rung)
- [6. Deletion and scratch lifecycle](#6-deletion-and-scratch-lifecycle)
- [7. Running the worker](#7-running-the-worker)
- [8. The graph projection](#8-the-graph-projection)
- [9. Rung 2 corridor artifacts](#9-rung-2-corridor-artifacts)
- [10. Evidence](#10-evidence)
- [11. Limits](#11-limits)
- [12. The pose job controller](#12-the-pose-job-controller)

## 1. Scene selection and the durable job

Ingest runs scene grouping after capture processing. `run_scene_grouping` records the groups,
applies `SceneGroupPosePolicy` and enqueues a selected exact member set only after every member
has a current point-map artifact. The automatic policy, `exulanica.scene-group-pose-selection/v1`,
is deliberately narrow:

- it reads the deterministic presentation order produced by `scene_group` version 1;
- it selects groups with at least three members, because the sparse backend's defaults discard
  two-view tracks; and
- its selection record states that it is not validated against a representative photograph
  corpus and does not predict registration or quality.

The grouping stage's one-hour and 250-metre boundaries (`max_time_gap_s` and `max_distance_m`)
are unvalidated stage parameters, not product rules. Changing them changes the stage digest and
therefore the grouping result. A reviewed policy can replace `SceneGroupPosePolicy` without
changing scene identity, job leasing, placement or delivery.

Sources whose metadata does not satisfy the automatic policy may use
`enqueue_exact_scene_reconstruction`, an operator-authorized selection and not a metadata repair.
Its versioned policy (`exulanica.operator-exact-set-pose-selection/v1`) binds the operator,
authorization time, purpose, ordered capture ids and source digests. It waits for every
privacy-bound point map and uses the same admission, build-input, queue, worker and publication
contracts as automatic grouping. It also carries an optional training request and the destination
a training run sends photographs to ([gsplat-scene-jobs.md](gsplat-scene-jobs.md)).

The queue row is durable before compute starts. It owns an immutable ordered membership table, the
member-set digest, the selection-policy digest, an exact build-input record and digest, a
deterministic job id and the deterministic `reconstruction_scene` id. The build-input record binds
every member to one point-map artifact id and content digest plus the pose, placement and gate
stage versions and parameter digests. Registration is not part of scene or job identity; the
completed scene and the per-build registration outcomes are written only after pose recovery.

`reconstruction_scene` is the stable identity of the exact capture set. A replacement point map or
scene-stage version creates another immutable job under that scene. Each successful job keeps its
own registration rows and output artifacts. Only the scene's `current_job_id` advances, in the
transaction that publishes the rung assertion and the job's success. Graph and package readers
follow that pointer, and older successful builds stay inspectable and reproducible.

The `exulanica-scene-worker` process runs this sequence:

1. Claim the next eligible exact set with `FOR UPDATE SKIP LOCKED` and a renewable lease.
2. Stage only the declared source blobs under the job's canonical workspace and job scratch key,
   verifying every byte digest and refusing undeclared files. A member whose person must be
   hidden is staged as its declared masked derivative.
3. Run checkpointed pycolmap feature extraction, matching, sparse mapping and model conversion
   (section 12).
4. Resolve and verify the exact point-map artifacts the job declares, then compute a pose receipt,
   a placement record and a scene-gate decision without writing object bytes early. A job that
   carries a training request trains under the same lease before publication.
5. Hold purge-compatible session locks for the receipt digests, then commit the completed scene,
   per-build registration outcomes and artifact rows through the tombstone guards.
6. Flush the exact receipt bytes to the content-addressed store after that transaction commits.
7. In one final transaction, record the scene-rung assertion, mark the job succeeded and advance
   the current-build pointer. These writes are the publication point.
8. Remove the sensitive scratch directory after success, handled failure or cancellation.

The graph and the World Memory Package omit a prepared job until publication succeeds. If storage
fails after the prepared rows commit, the job stays retryable and a deterministic retry verifies
those rows and heals the missing bytes. If a deletion lands between row commit and publication, the
session locks make the purger wait until the writer stops; publication is refused, then the
normal purge removes the receipt bytes. A late writer therefore cannot recreate an object after the
purger marked it gone.

## 2. Durable artifact chain

Every published build has three independently versioned receipts:

| Record | Profile | What it binds |
| --- | --- | --- |
| Pose receipt | `exulanica.colmap-pose-receipt/v2` | exact source manifest, source digests, code revision, pycolmap version, runtime image digest, commands, sparse outputs, recovered cameras, registration and quality |
| Placement | `exulanica.posed-point-map-placement/v2` | scene id, complete ordered member set, pose receipt digest, pose manifest digest, each current point-map artifact id and content digest, correspondence-fit evidence, transform, scale status and every exclusion |
| Gate | `exulanica.reconstruction-scene-gate/v1` | every receipt digest it read, complete and registered counts, awarded rung and all withholding reasons |

The same acceptance publishes the graph projection (section 8), and a trained build adds its
training receipt, SOG delivery and private evaluation bundle
([gsplat-scene-jobs.md](gsplat-scene-jobs.md)).

Artifact ids are deterministic functions of the scene, stage version and parameters, and exact
input digests. A retry may reproduce and verify the same row. It cannot create a second,
conflicting truth for the same input key.

The placement validator refuses unsupported versions, missing or duplicate members, outcomes that
do not cover the exact member set, point maps from outside the scene, unknown or changed artifact
rows, content-digest disagreement, pose-member disagreement, non-finite transforms, non-affine
matrices, non-orthonormal rotations, reflections and non-positive scales. It rebuilds the expected
record from the current pose receipt and point-map inputs and requires exact equality.

## 3. Placement: coordinates, scale and correspondence fitting

OPM/2 is a per-photograph artifact in its source-camera frame
([adr/0010-opm-2.md](adr/0010-opm-2.md)). Placement never changes its bytes.

COLMAP reports `camera_from_world` with camera axes +X right, +Y down, +Z forward. OPM uses +X
right, +Y up, -Z forward. The placement producer first applies `diag(1, -1, -1)` to map OPM axes
into COLMAP camera axes, then applies the inverse recovered camera pose. The stored transform is
the row-major 4 by 4 matrix `scene_from_opm = [s R^T diag(1,-1,-1), -R^T t; 0,0,0,1]`, acting
directly on raw OPM coordinates. `local_units_to_scene_units = s` describes the scale already in
its linear block, so a consumer must not multiply positions by it a second time. Camera centres are
not scaled by the per-image fit.

`scene_placement` version 2 gives a registered photograph a scene transform only when its exact
OPM bytes align with actual COLMAP sparse correspondences. Missing or inconsistent correspondence
never substitutes an identity scale, and pose registration alone does not establish that a
monocular point map fits it.

- **Inputs.** `scene_pose` retains the COLMAP model parameters, image dimensions and a bounded,
  deterministic sample of pixel and 3D tracks for each recovered camera. When one image observes
  the same sparse point at two keypoints, every observation of that point from that image is
  dropped rather than one chosen. Camera and observation fields enter the quality digest; no
  learned feature descriptors are persisted.
- **Fitting.** The producer reconstructs the OPM's model-image sample lattice from its declared
  centred pinhole camera and matches COLMAP pixels to retained samples, using each sample at most
  once. Tracks need at least two observations and at most two pixels of reprojection error. A
  deterministic fold by sample location reserves every fifth correspondence for validation. A
  robust median scalar fits all three camera-space components of the rest, followed by an inlier
  refit; rotation and translation come from COLMAP and are not fitted. Residuals over all three
  components stop a wrong focal geometry from passing because its depth ratio agrees.
- **Acceptance.** `ALIGNMENT_POLICY` in `exulanica/reconstruction/alignment.py`, which enters stage
  identity, requires at least 24 fitting and 6 validation correspondences, at least 6 occupied
  cells of a 4 by 4 source-image grid, and at least 60 percent inliers within 15 percent relative
  3D residual in both folds. The P90 residual is retained for inspection and is not a second
  threshold. These are engineering choices, not corpus-calibrated quality claims.
- **Result.** An accepted member records `scale_status: colmap-correspondence-fit` and
  `physically_validated: false` with its correspondence counts, spatial coverage, inliers and
  residuals. An excluded member records `pose-not-registered`, `point-map-unavailable`,
  `alignment-unavailable`, `alignment-insufficient-correspondences` or `alignment-inconsistent` and
  keeps ordinary source access. Both outcomes reproduce from the exact pose and point-map bytes.

A version 1 identity-scale placement is not upgraded or reinterpreted. The client draws only
`colmap-correspondence-fit` placements (`web/packages/app/src/geometry-api.ts`), so such a scene
falls back to its source photographs until a build runs under the version 2 stages.

The fit is coordinate alignment, not physical measurement. Scene coordinates are the selected
COLMAP world with no assumed gravity or physical unit, and no query, corridor, navigation or rung
gate may treat them as metres. Agreement between models does not establish collision,
navigability, complete surfaces or visual quality. Scale-only alignment cannot correct nonrigid
monocular depth warping.

Registered members also expose an independent recovered camera from the accepted pose receipt: a
unit-scale renderer-camera-to-scene transform at the recovered camera centre, and a calibration
that keeps `fx`, `fy`, `cx`, `cy`, image dimensions, model name and every original parameter.
PINHOLE and SIMPLE_PINHOLE projection is exact; a distortion model is disclosed as
`pinhole-approximation`. Camera arrival and inspection therefore work even when every point map is
unavailable, without changing the recorded rung.

The placement rule's synthetic verification and mutation controls are retained in
[the placement record](evaluation/2026-09-05-placement-alignment.json). They concern numeric
synthetic geometry, not visual acceptance of a real scene.

## 4. Graph delivery and rendering

`GET /graph` reads graph state and reconstruction scenes inside one repeatable-read, read-only
transaction. Each `reconstruction_scenes` entry carries one authoritative scene description:

- ordered registered and unregistered members;
- pose, placement and gate digests;
- recorded rung and recorded withholding reasons from the assertion;
- displayed rung and display reasons;
- the rendering substrate;
- each registered member's validated point-map descriptor and transform; and
- an explicit exclusion reason for every member without a placement.

Before exposing any transform, the server re-reads the scene's members and gate agreement and
requires each placed point map to match its exact live artifact row and reproduce its content
digest. The transforms come from the graph projection when it proves its bindings (section 8);
otherwise the server rebuilds them by validating the placement against the pose receipt and the
point-map bytes. Missing or invalid scene receipts keep the recorded assertion for explanation but
switch delivery to source photographs.

The browser fetches every available placed map with its workspace bearer, verifies the declared
SHA-256 before decoding OPM/2, validates the matrix, and creates one scene root with one transformed
point-cloud child per accepted member. Residency cost, footprint, arrival framing and camera
coverage include all loaded children. A corrupt or missing member degrades independently, while its
source photograph stays available.

Captures that have ever belonged to a reconstruction scene are omitted from the unposed
`GET /geometry` list, so a deletion or a broken scene receipt cannot put a surviving member back at
an invented origin. Exact bytes for a live point-map artifact stay available when another validated
scene refers to them.

### Photographs joined from one standpoint

Photographs taken from about one position give pose recovery no parallax, so their scene publishes
with no member registered. The `scene_standpoint` stage
([`exulanica/ingest/standpoint_scenes.py`](../exulanica/ingest/standpoint_scenes.py)) measures how
such photographs were turned relative to one another and writes one `standpoint_scene` artifact
(`exulanica.standpoint-scene/v1`,
[`standpoint_record.py`](../exulanica/reconstruction/standpoint_record.py)) that the graph serves in
place of an unmeasured arrangement. It runs from the scene worker's refresh pass
(`--standpoints-refresh-seconds`) or on demand with
`python -m exulanica.ingest.standpoint_scenes --workspace <uuid> [--scene <uuid>]` where pycolmap is
installed; it needs pycolmap and numpy only, which the scene worker's image carries. It never
touches a scene whose pose recovery placed a member.

- **Method.** COLMAP SIFT features per photograph, a rotation-only fit per pair through each
  photograph's EXIF 35 mm equivalent focal length, a global rotation solve over the set, the focal
  length refined from the overlaps against a prior on the stated lens, and each photograph's
  MoGe-2 depth brought to one scale on the overlaps
  ([`standpoint.py`](../exulanica/reconstruction/standpoint.py)). No model runs in this stage; the
  depth estimates come from the depth stage. Every parameter is in the versioned stage entry in
  [`exulanica/ingest/stages/__init__.py`](../exulanica/ingest/stages/__init__.py).
- **Refusal by name.** A pair is joined or refused as `insufficient_overlap`,
  `moved_between_photographs`, `scene_changed` or `inconsistent_with_set`. A member is `joined`,
  `not_joined`, or never read: `not_permitted`, `point_map_unreadable` or `focal_length_unstated`
  (a photograph that does not state its lens stays a separate photograph, because the depth model's
  own field-of-view estimate joins visibly wrong). Photographs that overlap nothing stay separate.
  A pair is `scene_changed` when more than 2 percent of the view the two photographs share shows
  something else. A smaller change may be joined, and the arrangement then shows it as the
  photograph drawn there has it.
- **Permission and withdrawal.** A member is read only under the permission the depth stage
  requires for its point map, including a personal model right naming the depth model where the
  capture needs one, and the question is asked again inside the publication transaction. The graph
  withholds the whole arrangement when any member it read can no longer be read, and the stage then
  joins what remains.
- **Truth status.** The arrangement is an estimate over the members' own depth estimates. It does
  not change the recorded rung, it is not a camera pose, and its units are the depth model's scale,
  not measured metres.

The browser draws a joined arrangement as one view from the standpoint
([`standpoint-scene.ts`](../web/packages/atlas-react/src/playcanvas/standpoint-scene.ts)). Each
direction belongs to the photograph whose frame centre is nearer, so seams fall where both
photographs are least stretched. Away from the standpoint every member flattens towards one shared
print, a dome at the scene's median distance floored at the ground, which holds the parallax error
within the single-photograph limit and keeps the seams joined. An edge that no other photograph
continues is drawn as a thin line in the theme's absence colour instead of fading out. Nobody can
walk round to the far side of anything: only what the photographs saw from the standpoint exists.

MEASURED on synthetic same-standpoint sets with exact ground truth, under pre-registered gates:
version 1 passed every gate on a held-out split of 66 sets and 210 photographs, with no pair taken
metres apart and no pair across a change joined
([pre-registration](evaluation/2026-09-23-standpoint-join-preregistration.json),
[outcome](evaluation/2026-09-23-standpoint-join-outcome.json)). Versions 2 and 3, which add an up
direction from vertical edges, a zoom in the pair fit and a cause named only where it is measured,
failed their gates on fresh held-out splits
([version 2](evaluation/2026-09-24-standpoint-join-v2-outcome.json),
[version 3](evaluation/2026-09-25-standpoint-join-v3-outcome.json)). The stage therefore registers
version 1; the later paths are selectable only through their parameters.

## 5. Quality gate and recorded rung

**Point-map validation.** `exulanica.reconstruction.validate_opm` validates every production point
map before it is persisted, and the PlayCanvas reader independently validates its untrusted byte
boundary before it constructs typed-array views. Both check the format, version, rung, explicit
metric flag, camera axes, source dimensions and aspect, field of view, bounds, section types, exact
lengths, alignment and container range. Under OPM/2 both refuse version 1 by name with a message
naming the regeneration path, check that `colorAlpha` declares which quantity the alpha channel
holds, and check that `modelImage` is reachable from `sourceImage` by one uniform resize. The
production validator also checks per point that every position is finite, in front of the source
camera and within the declared bounds, that every segment id is one the renderer's semantic table
can index, and that every reserved bit of the tags channel is zero. The reader does none of those,
because its one requirement is no per-point JavaScript: the writer's boundary is the one in front of
a durable artifact.

The renderer's source-panel envelope, derived from the artifact's measured depth bounds and
source-camera frustum, is an observed presentation extent only. It is not navigation, collision, a
world-space scale, or permission to move away from the source viewpoint.

**Point-map stage parameters.** `min_valid_fraction_milli = 150` and `max_depth_step_milli = 100`
are explicitly unvalidated stage parameters, so an edit changes the stage key and regenerates. The
depth-step limit drops points that span a silhouette, where a monocular model's pixel covers two
surfaces at different depths; it was chosen on one photograph, where 100 removed 3.04 percent of the
map and kept a bicycle standing proud of a wall, and 50 began deleting its frame. Every `.opm`
carries the `discontinuityDropped` and `oneSidedPoints` statistics, so both thresholds can be
reviewed against a real corpus.

**The quality report.** `exulanica.reconstruction.quality` is the versioned report contract for the
real checks: structural OPM integrity, PlayCanvas consumption and load duration, authorized source
opening and evidence linkage, visual alignment from the exact source-camera pose, metric versus
non-metric behaviour, deletion closure, production duration, byte size and returned cost, and the
valid-fraction distribution. Missing values stay absent and block the gate, and synthetic or
development observations can test the contract but never pass the real-corpus gate. No worker or
route calls it, and no real corpus has passed it.

**Pose policy.** `scene_pose` version 4 requires at least 80 percent registration, a mean
reprojection error of at most 1.0 pixel, and a COLMAP-normalized camera-translation extent of at
least 5.0 units (`min_registered_fraction_millionths`, `max_mean_reprojection_error_micropixels`
and `min_camera_translation_microunits` in the stage registry). Version 2 selected its values by
declared rules from one synthetic scene and the licensed ETH3D benchmark
([benchmark pose record](evaluation/2026-09-04-benchmark-pose.json)): the product floor of 80
percent registration, the smallest whole-pixel ceiling above the largest observed reprojection
error, and the greatest whole unit below the smallest observed extent, 9.0. Version 4 keeps the
first two and lowers the extent to 5.0, because fully registered, sub-pixel handheld builds of the
retained bowl collection measured 8.13 and 8.96 units and were refused
([real reconstruction record](evaluation/2026-09-05-real-reconstruction.json)). COLMAP normalizes
central camera centres to a 10-unit extent, so the value is a non-degeneracy check within this
controller and not a metric distance. Every earlier build keeps its own parameter digest; new
corpus evidence creates a new stage version and a new build rather than changing one in place.

**Recorded rung, displayed rung and substrate.** These are separate facts:

- `recorded_rung` is the durable scene assertion produced by the scene gate;
- `displayed_rung` is the worst-first mode this client can honestly show; and
- `rendering_substrate` is `posed_point_maps` or `source_photographs` in this client.

`decide_scene_rung` in `exulanica/reconstruction/scene_gate.py` awards the highest rung whose exact
receipt chain is present and accepted. Rung 1 needs accepted scale, coverage and splat receipts;
rung 2 needs accepted scale, coverage and corridor receipts; rung 3 needs a registered member with
an accepted placement; anything less records rung 4, source photographs. The scene worker produces
pose, placement and, for a training build, splat receipts. Nothing produces scale, coverage or
corridor receipts, so a published scene records rung 3 or rung 4, trained or not.

Decoded geometry never promotes `recorded_rung`. If no verified placed bytes are available, the
client displays rung 4 source photographs while keeping the recorded rung and reasons in the
disclosure. If an assertion records a rung whose substrate this client does not support, the
displayed rung stays 3 and the disclosure says why. The status disclosure is the authoritative
render site for rung copy; its sentence comes from the single `RUNG_COPY` table in
`web/packages/formation/src/labels.ts`, and names the recorded rung, displayed rung, substrate,
registered count and every gate or fallback reason.

## 6. Deletion and scratch lifecycle

A tombstone for any scene or queued-job member, including an unregistered member:

- cancels a queued, failed or running scene job in the database;
- makes the running worker's cancellation check stop pycolmap;
- retracts the current scene-rung assertion with a durable retraction tied to the tombstone;
- blocks completed scene artifacts immediately;
- removes the scene from graph delivery and World Memory Package projection; and
- makes scene artifact bytes eligible for the separately authorized purge flow.

COLMAP databases, feature descriptors, staged sources and sparse working files live only under
`EXULANICA_DATA_DIR/reconstruction-scratch/<workspace>/<job>`. Durable receipts live in the
content-addressed store, outside scratch. Receipt writes use the shared post-commit store boundary
and keep purge-compatible session locks through publication. The worker also holds a non-blocking
filesystem lock for the whole sensitive scratch lifetime. Cleanup accepts only canonical UUID path
pairs, refuses symbolic links, skips a locked directory, and never deletes scratch protected by
queued, running or retryable work.

A process crash leaves its checkpointed scratch in place. After lease expiry, another worker
reclaims the same job and the pose controller skips only checkpoints whose required outputs still
verify. A startup sweep removes old unprotected scratch. If a process dies on the final allowed
claim, startup first changes the expired job to terminal `failed` with
`failure_class = claim_exhausted`, then makes its scratch eligible for that sweep. A retry after
handled cleanup restages the exact source set.

A deliberate re-import of the same source bytes creates or reuses a live capture identity. Under
the shared purge lock it also restores a globally purged blob row's storage key and clears its
purged marker before the post-commit store publication finishes. The old capture tombstone keeps
blocking the old scene identity. Without an exact privacy screening for the re-imported capture, a
derivative worker produces no replacement point map: its depth stage records that the photograph
awaits admission and sends nothing to the model.

## 7. Running the worker

Compose builds dependency-specific images from one reviewed Dockerfile. The derivative worker
image adds the `reconstruction` extra and runs MoGe; the API and scene worker images carry the
default `server` and `pose` extras, with `pycolmap==4.2.0` pinned. Torch and pycolmap never load in
one process. [derivative-worker-operations.md](derivative-worker-operations.md) owns the derivative
worker's configuration. For a local source checkout, run depth explicitly:

```bash
export EXULANICA_DEPTH_MODEL=moge
export EXULANICA_DEPTH_DEVICE=cpu
uv run --extra reconstruction exulanica-derivative-worker
```

**A photograph awaiting admission waits; its job does not fail.** An upload queues its derivative
job before anybody has reviewed the photograph, and a worker that runs the depth model can claim it
first. The depth stage then records `stage_unavailable` with the reason `AWAITING_ADMISSION` in
[depth.py](../exulanica/ingest/stages/depth.py), sends nothing to the model, and the job ends
succeeded. Admitting the photograph through `POST /personal-admission` records its screening and
queues its derivative job again, and that job runs the depth stage under the exact receipt. A
photograph that is never admitted keeps no point map, and its ledger states why.
[test_depth_awaits_admission.py](../tests/test_depth_awaits_admission.py) walks both orders through
the routes and the worker.

**A write the database defers is retried, not failed.** While a delivery holds the asset read lock,
migration 0041 refuses every guarded write with SQLSTATE 40001, including the stage registration a
derivative job makes when it is claimed. The worker returns such a job to the queue, recorded as
`retry_scheduled` in its events, as it does a retryable stage failure. After `MAX_CLAIMS` delivery
attempts ([derivative_queue.py](../exulanica/ingest/derivative_queue.py)) the job fails as
`retry_exhausted`, with each refusal in its error.

For the scene worker, install or invoke the pose extra explicitly:

```bash
export EXULANICA_DATABASE_URL=postgresql://exulanica_app:<password>@localhost:5433/${POSTGRES_DB:-exulanica}
export EXULANICA_DATA_DIR=.exulanica/local
export EXULANICA_WORKSPACE_IDS=<workspace-uuid>[,<workspace-uuid>...]
export EXULANICA_CODE_REVISION=<exact-40-character-git-revision>
export EXULANICA_POSE_RUNTIME_IMAGE=<registry/image@sha256:digest>
uv run --extra pose exulanica-scene-worker
```

Both provenance variables are required; a mutable image tag or guessed checkout is not accepted.
The worker refuses an owner, superuser or BYPASSRLS database role and an empty workspace set.
`--once` drains the work eligible at that moment and exits. Repeat `--job <job-uuid>` (or set
`EXULANICA_SCENE_JOB_IDS`) to claim only the named jobs; without it the worker takes every eligible
job in its workspaces oldest first, including a stale retryable job. A job-scoped worker that finds
nothing in its scope claims nothing and exits cleanly under `--once`. Defaults are a 900-second
lease, 30-second heartbeat, 2-second polling interval and 3600-second abandoned-scratch age.
Training builds need the GPU runtime described in [gsplat-scene-jobs.md](gsplat-scene-jobs.md).

After a scene publishes, the worker lifts its members' object masks and reviewed, shown people into
scene segments in the same run, with numpy alone ([scene-segments.md](scene-segments.md) section
5). A lift that fails is `stage_failed` on `scene_segments` and the scene stays published. After
each drain it also lifts again any published scene whose members all have masks its newest segments
do not bind, at most every `--segments-refresh-seconds` (default 300; `0` turns it off), and
reports what it did as one `segments_refreshed` event. The standpoint join (section 4) runs on the
same kind of pass, at most every `--standpoints-refresh-seconds` (default 300; `0` turns it off). A
job-scoped worker lifts the scenes it publishes and does not sweep.

Authenticated operators read top-level state from `GET /operations/reconstruction-scenes`, which
distinguishes derivative work, ready or running scene work, groups blocked on missing point maps,
published scenes and superseded builds. `GET /operations/reconstruction-scenes/{job_id}` returns one
job's exact inputs, member outcomes, outputs, failure and current-build state. A retryable failure
can be made immediately eligible with `POST /operations/reconstruction-scenes/{job_id}/retry`;
succeeded, cancelled and exhausted jobs are immutable and return a conflict instead of being
rewritten.

## 8. The graph projection

A deterministic `scene_projection` artifact (`exulanica.scene-graph-projection/v1`,
`exulanica/ingest/scene_projection.py`) publishes inside the same atomic acceptance as the pose
receipt, placement and gate. It carries what a graph reader would otherwise rebuild on every cold
`GET /graph`: each placed member's `scene_from_opm` transform, scale and point-map references, each
excluded member's reason, and the recovered cameras. It is a cache of conclusions the receipts
already stand behind, not a receipt, and it promotes nothing.

A reader proves five bindings before using it: the pose, placement and gate content digests, so a
projection of a superseded build cannot answer for the current one; the scene's member capture
refs in scene order, the one input no digest covers, because withdrawing a member leaves all three
receipts byte-identical; and the placement's point-map references in record order, a self-check
derived from placement bytes the second binding already pins. The reader's live query sees a
superseded, re-pointed or purged point-map row, and the reader confirms each point map is present
and reproduces its content digest; presence is a live fact and is never carried in the artifact.
The reader also refuses a transform that lacks an affine last row, a positive scale or a proper
orthonormal rotation, the conditions a rebuilt record must meet. An absent, purged, repair-flagged,
unparseable or self-inconsistent projection falls back to the rebuild, so a refused projection
costs the read time and nothing else. Artifact rows, members, gate agreement, person regions, review states and
the asset-read policy are re-read on every request regardless.

Nothing privacy-bearing enters a projection: no person region, review state, source photograph
digest or pose manifest frame. `scene_allowed` denies a scene by comparing the pose manifest's frame
digest with the live artifact row, and re-masking a withdrawn person moves `read_source_sha256`, so
a durable copy of those digests would be a second, stale answer to a question the asset-read policy
asks fresh. A projection that cannot be built is recorded as a failed `scene_projection` stage and
the three receipts publish anyway.

The projection has no column on the job row. The graph selects the newest few live projections for
the scene and proves each from its own bindings, because nothing sets `artifact.superseded_by` on
a scene artifact. `scripts/backfill_scene_projections.py` gives an already published scene the
projection of its current job and records what it wrote as JSON; it is idempotent because the
artifact id derives from the three receipt digests.

That id has generations, because `artifact` is unique on its identity key over every row, purged or
not, and a purged row keeps its id. `projection_identity_key` returns the receipt-derived key for
generation 0, which is the only generation the worker writes, and a length-prefixed digest of that
key and the generation number after it. The backfill walks generations from 0 before any expensive
work:

| At the first generation that is not spent | What the backfill does |
| --- | --- |
| No row | Writes the projection there. |
| A live row whose bytes are present | Nothing; reports `already-present`. |
| A live row whose bytes are gone, reproduced by the receipts | Writes the bytes back under the same id and reports `repaired_missing_bytes`. |
| A live row naming content the receipts do not reproduce | Refuses; the stage has disagreed with itself. |

A generation is spent when the graph would never offer its row to a reader: purged, flagged
`needs_repair`, or recording no content. That is the reader's own candidate predicate, and every
generation passed over is named in the backfill's record. A purged row is never deleted,
un-purged, rewritten or reused; it stays the record that those bytes were destroyed. A deletion
that reaches the scene makes `tombstone_blocks_scene` keep the backfill from selecting it, and the
artifact insert guard refuses every generation alike (`tests/test_scene_projection_backfill.py`).
A refused disagreement is resolved by finding out why the stage produced other bytes, then flagging
the row `needs_repair` so the next run passes over it.

## 9. Rung 2 corridor artifacts

`exulanica/reconstruction/navigation.py` builds a rung-2 corridor artifact
(`exulanica.corridor-artifact/v1`) from a `CorridorBuildManifest` (`exulanica.corridor-build/v1`)
of ordered metric pose samples. Each sample records a camera reference, position in metres, unit
forward vector, independently measured clearance radius and slope, and whether it is a source
vantage or a recovery pose. The manifest also pins the reconstruction and topology digests, agent
radius, lateral cap, maximum pose gap, slope limit, look envelope and required destinations.

The lateral half-width at each pose is the smaller of the lateral cap and the measured clearance
minus the agent radius, floored at zero; it is never inferred from splat opacity or pixels.
Insufficient clearance, excessive slope, a gap wider than the maximum, a missing destination, no
source vantage or no recovery pose makes the artifact publish rung 3 with every reason. An
artifact binds its centreline, widths, clearances, slopes, forwards, look envelope, destination,
source-vantage and recovery indices to a canonical SHA-256. `validate_corridor_artifact` refuses a
changed digest, a stale reconstruction or topology base, arrays that describe different poses,
and a result whose rung contradicts its acceptance.

The browser adapter `corridorRuleFromArtifact` (`web/packages/atlas-core/src/corridor.ts`)
independently checks the profile, digests, bases, accepted rung 2, array shapes, finite values,
clearance for the agent radius and look bounds. It transforms the metric centreline through the
island placement and uses the narrowest measured width across the whole path, so it can only
narrow the recorded envelope, never widen it. `constrainCorridorLook` clamps the camera to the
recorded envelope around each pose's forward direction.

Nothing produces a corridor. No worker builds a manifest from measured clearance, no application
code calls the adapter, and the scene gate never receives a corridor receipt, so no scene records
rung 2.

## 10. Evidence

These records establish behaviour at their own scope. None is a representative real-corpus or
personal-media acceptance.

- **Synthetic plumbing fixture.** `exulanica.evaluation.synthetic_multiview` generates eight
  overlapping 800 by 600 views of one explicit textured room, with a visible SYNTHETIC banner and
  digest-bound scene, camera and source manifests
  (`uv run python scripts/generate_synthetic_multiview.py .exulanica/validation/synthetic-v1`).
  Real pycolmap 4.2.0 registered all eight views, and the pinned MoGe checkpoint ran at the
  production 512-pixel edge. That proves executable plumbing, coordinate conversion and manifest
  provenance only.
- **Licensed benchmark.** The 14-image ETH3D `pipes` training scene (CC BY-NC-SA 4.0) is declared
  by the digest-bound manifest `exulanica/evaluation/benchmarks/eth3d-pipes-v1.json` and acquired
  into ignored storage with `scripts/acquire_benchmark_scene.py`; its media is not committed. The
  production path registered 14 of 14 photographs under pose version 2 with 0.569790 pixel mean
  reprojection error and a 10.913192-unit span, and camera centres matched ETH3D's cameras to
  0.006594 ground-truth units RMS ([pose](evaluation/2026-09-04-benchmark-pose.json)). The
  authenticated browser rendered all 14 placed maps as one scene
  ([browser](evaluation/2026-09-04-benchmark-browser.json)). A tombstone for one member removed the
  scene from graph and browser delivery, retracted its rung, and purged the scene receipts and the
  member's unique objects while unrelated point maps survived; re-import produced no point map
  without a new screening ([withdrawal](evaluation/2026-09-04-benchmark-scene-withdrawal.json)).
- **Synthetic person withdrawal.** A clearly simulated person linked to one capture of the
  synthetic scene was withdrawn through the entity tombstone: the scene and its rung left graph and
  package delivery, the purge role destroyed the dependent point map and scene receipts, unrelated
  point maps stayed, and a late artifact publication was refused
  ([record](evaluation/2026-09-04-synthetic-person-withdrawal.json),
  [browser](evaluation/2026-09-04-synthetic-person-withdrawal-browser.json)). It proves dependency
  reachability and serving withdrawal for that synthetic scene, not a real person's request.
- **Retained reference collections.** Two public CC0 collections ran the full path, including GPU
  training; [retained-reference-workflow.md](retained-reference-workflow.md) is the guide and the
  [real reconstruction record](evaluation/2026-09-05-real-reconstruction.json) the outcome.
- **Standpoint joins.** The measurements are in section 4.

## 11. Limits

- Rung 1 and rung 2 are not reachable: nothing produces scale, coverage or corridor receipts
  (sections 5 and 9). A trained scene records rung 3.
- Placement scale is COLMAP-normalized, not metres, and scale-only alignment cannot repair depth
  warping or missing surfaces.
- The automatic grouping boundaries, the point-map thresholds and the placement acceptance policy
  are unvalidated against a representative corpus, and the quality report has no caller.
- Standpoint join version 1 is the registered stage; versions 2 and 3 failed their gates.
- Pose recovery reads photographs under scene admission and screening; it asks for no personal
  model right, because COLMAP carries no learned weights
  ([personal-admission.md](personal-admission.md)).

## 12. The pose job controller

`exulanica.reconstruction.pose` runs COLMAP feature extraction, exhaustive matching and sparse
mapping from an exact authorized source manifest, through a `CommandExecutor` seam. The scene
worker supplies `PycolmapExecutor` (`exulanica/reconstruction/pycolmap_executor.py`), which performs
each command shape through pycolmap in process. The default subprocess executor shells out to a
`colmap` binary that is not in the container image.

**The manifest and the job directory.** The manifest pins every staged filename and byte digest,
an exact Git revision, the recorded COLMAP version, a digest-pinned execution image, explicit
reviewed quality thresholds, capture-set membership, and an optional measured scale with its
method. Original paths, media bytes, semantic labels and inferred consent are absent. Each manifest
has one content-addressed job directory outside Git, and a filesystem lock serializes claimants.

**The recorded COLMAP version.** `PoseBuildManifest.colmap_version` must be non-empty and is not
checked against the library that ran. The in-process backend closes that gap by building the string
from the library about to do the work (`pycolmap_version`); the subprocess backend leaves it open.

**What a stage records, and what a restart may skip.** Every executor result records the exact
argument vector, actual duration, return code, and stdout and stderr digests. A checkpoint is
fsynced after feature extraction, matching, mapping and each binary-to-text model conversion. A
restart skips only completed stages whose required durable outputs still exist, and a completed
receipt is reused only after the current sparse artifacts reproduce its quality digest.

**What the parser reads.** Registered image names and camera centres from COLMAP `images.txt`, and
actual reprojection errors from `points3D.txt`. It reports registration fraction, mean reprojection
error, camera-translation extent, all output digests and sizes, the selected connected model and
every fallback reason. The largest connected model is selected deterministically by registered
image count and path; a place name never participates.

**Co-registration is not metricity.** Multiple capture sets are co-registered only when registered
images from every declared set occur in one connected model. That still does not make the result
metric: a shared metric frame also requires an explicit positive measured scale and its method.
Failure, low coverage, poor reprojection, insufficient translation, disconnection or missing scale
keeps rung 3 with the recorded reason.

**Sensitive scratch.** Staged images, COLMAP databases, descriptors and sparse working files are
separate from the durable receipt and are removed after success, handled failure or cancellation. A
process crash keeps only restartable scratch until lease reclaim or the age-gated startup sweep,
and a crash on the final claim is made terminal before that sweep, so no expired job stays
`running`. Section 6 is the fuller deletion contract.
