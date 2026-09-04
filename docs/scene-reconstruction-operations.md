# Production reconstruction scenes

Status: **IMPLEMENTED and PostgreSQL-tested 2026-09-04; licensed benchmark acquired, production
run pending named human privacy review**.

This document is the operating contract for Exulanica's production rung-3 multi-photograph path.
It covers scene selection, durable work, pose recovery, placement, graph delivery, rendering,
deletion, and recovery. It does not claim that the path has passed a representative real-corpus
quality gate. No consented dense capture set or digest-pinned production pose image was available
for that measurement.

## Verification baseline

**VERIFIED 2026-09-04 at `ea70b80`.** The exact campaign database and required clean-bytecode
command sequence completed with 1,349 passed tests, 2 intentional skips, and 3 warnings. Ruff
passed, and all four import-layer contracts passed over 256 files and 1,760 dependencies.

```bash
find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest
uv run ruff check .
uv run lint-imports
```

The first full campaign run found four migration-test failures and one import-layer violation.
The withdrawal exercise had been placed in `exulanica.evaluation` even though it composes World
Memory Package projection and therefore belongs in the top-level orchestration layer. Commit
`d60be1c` moved that workflow without changing its retained record. The migration failures exposed
an unqualified ledger lookup: a fresh deployment schema could inherit a later search-path schema's
`schema_migrations` table. Commit `ea70b80` qualified ledger reads and writes to the connection's
current schema and added a decoy-ledger PostgreSQL regression. A deliberate reversal made that
regression fail by reading the decoy before the correction was restored.

## 1. Production flow

The normal ingest flow runs scene grouping after capture processing. `run_scene_grouping` records
the groups, applies `SceneGroupPosePolicy`, and enqueues a selected exact member set only after
every member has a current point-map artifact. The
initial policy is deliberately narrow and versioned as
`exulanica.scene-group-pose-selection/v1`:

- it considers the deterministic presentation order already produced by `scene_group` version 1;
- it selects groups with at least three members because the current sparse backend discards
  two-view tracks; and
- it records that the policy has not been validated against a representative photograph corpus
  and does not predict registration or quality.

The grouping stage's current one-hour and 250-metre boundaries are unvalidated stage parameters.
They are not hidden product rules. Changing them changes the stage digest and therefore creates a
new deterministic grouping result. A future reviewed selection policy can replace
`SceneGroupPosePolicy` without changing scene identity, job leasing, placement, or delivery.

Sources that honestly lack the automatic policy's EXIF assumptions may use
`enqueue_exact_scene_reconstruction`. This is a narrow operator-authorized selection interface,
not a metadata repair. Its versioned policy binds the operator, authorization time, purpose,
ordered capture ids, and source digests. It still waits for every privacy-bound point map and uses
the same admission, build-input, queue, worker, and publication contracts as automatic grouping.

The queue row is durable before compute starts. It owns an immutable ordered membership table, the
complete member-set digest, the selection-policy digest, an exact build-input record and digest, a
deterministic job id, and the deterministic `reconstruction_scene` id. The build-input record binds
every member to one point-map artifact id and content digest plus the pose, placement and gate stage
versions and parameter digests. Registration is not part of scene or job identity. The completed
scene and the per-build registration outcomes are inserted only after pose recovery.

`reconstruction_scene` remains the stable identity of the exact capture set. A replacement point
map or scene-stage version creates a new immutable job under that scene. Each successful job keeps
its own registration rows and output artifacts. Only the scene's `current_job_id` advances, in the
same transaction that publishes the new rung assertion and successful job state. Graph and package
readers follow that pointer. Older successful builds remain inspectable and reproducible.

The separate `exulanica-scene-worker` process then performs this sequence:

1. Claim the next eligible exact set with `FOR UPDATE SKIP LOCKED` and a renewable lease.
2. Stage only the declared source blobs under the job's canonical workspace/job scratch key,
   verifying every byte digest and refusing undeclared files.
3. Run checkpointed pycolmap feature extraction, matching, sparse mapping, and model conversion.
4. Resolve and verify the exact point-map artifacts declared by the job, then compute a pose
   receipt, point-map placement record, and scene-gate decision without writing object bytes early.
5. Hold purge-compatible session locks for all three content digests, then commit the completed
   scene, per-build registration outcomes, and artifact rows through the tombstone guards.
6. Flush the exact receipt bytes to the content-addressed store after that row transaction commits.
7. In one final transaction, record the scene-rung assertion, mark the job succeeded, and advance
   the current-build pointer. These writes are the publication point.
8. Remove the sensitive scratch directory after success, handled failure, or cancellation.

The graph and World Memory Package omit a prepared job until that publication transaction succeeds.
If storage fails after the prepared rows commit, the job remains retryable and a deterministic
retry verifies those rows and heals the missing bytes. If deletion lands between row commit and
publication, the session locks make the purger wait until the writer stops; publication is refused,
then the normal purge removes the receipt bytes. This prevents a late writer from recreating an
object after the purger marked it gone.

## 2. Durable artifact chain

The accepted chain has three independently versioned records:

| Record | Current profile | What it binds |
| --- | --- | --- |
| Pose receipt | `exulanica.colmap-pose-receipt/v2` | exact source manifest, source digests, code revision, pycolmap version, runtime image digest, commands, sparse outputs, recovered cameras, registration and quality |
| Placement | `exulanica.posed-point-map-placement/v1` | scene id, complete ordered member set, pose receipt digest, pose manifest digest, each current point-map artifact id and content digest, transform, scale status, and every exclusion |
| Gate | `exulanica.reconstruction-scene-gate/v1` | every receipt digest it read, complete and registered counts, awarded rung, and all withholding reasons |

Artifact ids are deterministic functions of the scene, stage version and parameters, and exact
input digests. A retry may reproduce and verify the same row. It cannot create a second conflicting
truth for the same input key.

The placement validator refuses unsupported versions, missing or duplicate members, outcomes that
do not cover the exact member set, point maps from outside the scene, unknown or changed artifact
rows, content-digest disagreement, pose-member disagreement, non-finite transforms, non-affine
matrices, non-orthonormal rotations, reflections, and non-positive scales. It rebuilds the expected
record from the current pose receipt and point-map inputs and requires exact equality.

## 3. Coordinate and scale convention

OPM/2 remains a per-photograph artifact in its source-camera frame. Placement never changes its
bytes.

COLMAP reports `camera_from_world` with camera axes +X right, +Y down, +Z forward. OPM uses +X
right, +Y up, -Z forward. The placement producer first applies `diag(1, -1, -1)` to map OPM axes
into COLMAP camera axes, then applies the inverse recovered camera pose. The stored transform is a
row-major 4 by 4 `scene_from_opm` matrix.

COLMAP world units are scale ambiguous. Version 1 records `local_units_to_scene_units = 1.0` and
`scale_status = unvalidated-identity` for display only. It explicitly says the result is not metric.
No query, corridor, navigation, or rung gate may treat those units as metres.

## 4. Graph delivery and rendering

`GET /graph` reads graph state and reconstruction scenes inside one repeatable-read, read-only
transaction. Each `reconstruction_scenes` entry carries one authoritative scene description:

- ordered registered and unregistered members;
- pose, placement, and gate digests;
- recorded rung and recorded withholding reasons from the assertion;
- displayed rung and display reasons;
- current rendering substrate;
- each registered member's validated point-map descriptor and transform; and
- an explicit exclusion reason for every member without a placement.

Before exposing any transform, the server retrieves and digest-checks the three durable records,
reproduces the gate decision, validates the placement against the immutable scene members, and
requires each placed point map to match its exact live artifact row. Missing or invalid scene
receipts preserve the recorded assertion for explanation but switch delivery to source photographs.

The browser fetches every available placed map with its workspace bearer, verifies the declared
SHA-256 before decoding OPM/2, validates the matrix, and creates one scene root with one transformed
point-cloud child per accepted member. Residency cost, footprint, arrival framing, and camera
coverage include all loaded children. A corrupt or missing member degrades independently, while
the member's source photograph remains available through the ordinary source-first region.

Captures that have ever belonged to a reconstruction scene are omitted from the legacy unposed
`GET /geometry` list. This prevents deletion or a broken scene receipt from silently putting a
surviving member back at an invented island origin. Exact bytes for a live point-map artifact remain
available when another validated scene refers to them.

## 5. Recorded rung, displayed rung, and substrate

These are separate facts:

- `recorded_rung` is the durable scene assertion produced by the scene gate;
- `displayed_rung` is the worst-first mode this client can honestly show now; and
- `rendering_substrate` is either `posed_point_maps` or `source_photographs` in this client.

Decoded geometry never promotes `recorded_rung`. With the current unmeasured thresholds, a scene
with at least one registered and placed point map records rung 3. The gate also records why rung 1
has no reviewed splat receipt and why rung 2 lacks physically validated scale, measured coverage,
and a measured corridor. If no verified placed bytes are available, the client displays rung 4
source photographs while retaining the recorded rung and reasons in the disclosure. If a future
assertion records rung 1 or 2 before this client supports that substrate, the displayed rung stays
3 and the disclosure says why.

The status disclosure is the authoritative render site for rung copy. Its sentence comes from the
single `RUNG_COPY` table in `web/packages/formation/src/labels.ts`; the app carries no second table.
It names the recorded scene rung, displayed rung, substrate, registered count, and all gate or
fallback reasons.

## 6. Deletion and scratch lifecycle

A tombstone for any scene or queued-job member, including an unregistered member, does all of the
following:

- cancels a queued, failed, or running scene job in the database;
- makes the running worker's cancellation check stop pycolmap;
- blocks completed scene assertions and artifacts immediately;
- removes the scene from graph delivery and World Memory Package projection; and
- makes scene artifact bytes eligible for the separately authorized purge flow.

COLMAP databases, feature descriptors, staged sources, and sparse working files live only under
`EXULANICA_DATA_DIR/reconstruction-scratch/<workspace>/<job>`. Durable receipts live in the
content-addressed store, outside scratch. Receipt writes use the shared post-commit store boundary
and keep purge-compatible session locks through final publication. The worker also holds a
non-blocking filesystem lock for the whole sensitive scratch lifetime. Cleanup accepts only
canonical UUID path pairs, refuses symbolic links, skips a locked directory, and never deletes
scratch protected by queued, running, or retryable work.

A process crash leaves its checkpointed scratch in place. After lease expiry, another worker
reclaims the same job and the pose controller skips only checkpoints whose required outputs still
verify. A startup sweep removes old unprotected scratch. If a process dies on the final allowed
claim, startup first changes the expired job to terminal `failed` with
`failure_class = claim_exhausted`, then makes its old scratch eligible for that sweep. A retry after
handled cleanup safely restages the exact source set.

## 7. Running the worker

Compose builds two dependency-specific images from one reviewed Dockerfile. The derivative worker
selects the reconstruction extra and starts MoGe, while the API and scene worker use the default
server and pinned `pycolmap==4.2.0` pose extras. Torch and pycolmap never need to load in one
process. The derivative worker's model cache shares the durable media volume.

The derivative worker requires no depth flag in Compose. For a local source checkout, configure it
explicitly:

```bash
export EXULANICA_DEPTH_MODEL=moge
export EXULANICA_DEPTH_MODEL_ID=Ruicheng/moge-2-vitl
export EXULANICA_DEPTH_MODEL_REVISION=39c4d5e957afe587e04eec59dc2bcc3be5ecd968
export EXULANICA_DEPTH_DEVICE=cpu
uv run --extra reconstruction exulanica-derivative-worker
```

For the scene worker, install or invoke the pose extra explicitly.

```bash
export EXULANICA_DATABASE_URL=postgresql://exulanica_app:<password>@localhost:5433/${POSTGRES_DB:-exulanica}
export EXULANICA_DATA_DIR=.exulanica/local
export EXULANICA_WORKSPACE_IDS=<workspace-uuid>[,<workspace-uuid>...]
export EXULANICA_CODE_REVISION=<exact-40-character-git-revision>
export EXULANICA_POSE_RUNTIME_IMAGE=<registry/image@sha256:digest>
uv run --extra pose exulanica-scene-worker
```

Both provenance variables are required. A mutable image tag or guessed checkout is not accepted.
The worker also refuses an owner, superuser, or BYPASSRLS database role and an empty workspace set.
Use `--once` to drain the work currently eligible and exit. Defaults are a 900-second lease,
30-second heartbeat, 2-second polling interval, and 3600-second abandoned-scratch age.

Authenticated operators can read top-level state from `GET /operations/reconstruction-scenes`.
It distinguishes derivative work, ready or running scene work, groups blocked on missing point
maps, published scenes, and superseded builds. `GET /operations/reconstruction-scenes/{job_id}`
returns one job's exact inputs, member outcomes, outputs, failure and current-build state. A
retryable failure can be made immediately eligible with
`POST /operations/reconstruction-scenes/{job_id}/retry`; succeeded, cancelled and exhausted jobs
are immutable and return a conflict instead of being rewritten.

## 8. Deterministic synthetic plumbing fixture

**BUILT AND VERIFIED 2026-09-04.**
`exulanica.evaluation.synthetic_multiview` generates eight overlapping 800 by 600 views of one
explicit textured 3D room. The seed, room surfaces, point sampling, camera arc, intrinsics,
extrinsics, renderer versions, and image inventory are stored in canonical digest-bound scene,
camera, and source manifests. Every frame has a visible SYNTHETIC banner and a synthetic EXIF
description. No generated image call or personal input participates.

Generate it in ignored Exulanica storage:

```bash
uv run python scripts/generate_synthetic_multiview.py .exulanica/validation/synthetic-v1
```

On the measured Apple M3 Pro host, the exact default source manifest digest was
`a419ad40ce6dd4769750a40eedb687fe3bc39c734ecabfed2dea4d78d2a0ec0f`. Real pycolmap 4.2.0
registered all eight views through `run_colmap_pose_job`. The pinned
`Ruicheng/moge-2-vitl@39c4d5e957afe587e04eec59dc2bcc3be5ecd968` checkpoint executed on MPS
at the production 512-pixel edge, producing 196,608 points with 196,583 valid points. Model load
took 9.466 seconds and inference took 2.384 seconds on that run. Those values prove executable
plumbing, coordinate conversion, and manifest provenance only. A procedural room is not evidence
of real-photograph reconstruction quality.

## 9. Licensed real benchmark

**ACQUIRED AND VERIFIED 2026-09-04; PRODUCTION ADMISSION PENDING NAMED HUMAN REVIEW.** The selected
corpus is the 14-image `pipes` training scene from the ETH3D High-resolution Multi-view Stereo
Benchmark. ETH3D's official site licenses its data under CC BY-NC-SA 4.0. The selected undistorted
archive is 145,321,540 bytes and includes 14 images at 6,220 by 4,141 pixels plus COLMAP-format
camera calibration and sparse points. Surface ground truth is available separately and is not in
this bounded download.

The committed digest-bound source manifest is
`exulanica/evaluation/benchmarks/eth3d-pipes-v1.json`. It fixes the official source URL, retrieval
date, archive checksum, license legal-code checksum, exact file inventory, per-image checksums and
dimensions, ground-truth availability, and privacy-inspection state. Acquire only those declared
bytes into ignored Exulanica storage:

```bash
uv run python scripts/acquire_benchmark_scene.py \
  .exulanica/validation/benchmark/eth3d-pipes
```

On 2026-09-04 the downloader verified source-manifest digest
`4402e042b99153d1cbf247449b16b36f2864338bac28e44dc59f631a25815814` and archive digest
`718981351c14e84759fcc73215e7251fce93d6e9ea1fe24f9e15f1028232c12c`. A Codex visual review of
all 14 frames found no visible people, but that review is explicitly provisional. The production
privacy policy requires a named human to review the exact bytes, so no eligibility receipt may be
created until that confirmation occurs. This fail-closed state is evidence that benchmark
availability does not bypass real-media admission.

The archive and source images remain ignored local inputs. They are not committed. Although the
license permits qualified redistribution, the validation campaign avoids adding ShareAlike media
to the Apache-2.0 source tree. Benchmark results can establish engineering and reconstruction
measurements only. They cannot establish personal-media acceptance.

## 10. Synthetic person-withdrawal exercise

**EXECUTED AND RETAINED 2026-09-04.** A clearly simulated person occurrence was linked through
the normal identity path to one capture in the all-synthetic production scene. The normal entity
tombstone immediately removed the scene and its rung claim from graph delivery and World Memory
Package projection. The dedicated `exulanica_purge` role then destroyed the target point map, pose
receipt, placement receipt, and scene-gate receipt. Seven unrelated point maps remained live and
stored. A late artifact publication attempt was refused with SQLSTATE 23000.

The exact database, package, purge, and retained-source observations are digest-bound in
`docs/evaluation/2026-09-04-synthetic-person-withdrawal.json`. The first evaluator process stopped
after committing the tombstone because its probe caught a database exception below the repository
domain-error boundary. No purge job had run. The corrected evaluator resumed the durable tombstone
and queue, then completed the exercise. This interruption is recorded as evidence rather than
discarded.

The follow-up production browser observation is digest-bound in
`docs/evaluation/2026-09-04-synthetic-person-withdrawal-browser.json`. The authenticated graph had
zero live islands, occurrences, and reconstruction scenes. Chrome rendered one semantic empty
state, hid the canvas, and mounted no renderer. The exact original still returned HTTP 200 from its
authorized evidence citation with the admitted 768,370 bytes and SHA-256, while the higher-level
source catalog returned `world_not_configured` because no protected topology remained. The latter
distinction matters: source retention and citation retrieval succeeded, but the result does not
claim that a topology-dependent catalog still discovers the retained file.

The occurrence, entity, and name in this exercise are synthetic simulation records. The evidence
proves dependency reachability, immediate serving withdrawal, package withdrawal, late-write
refusal, privileged stored-byte purge, browser disappearance, and source retention for this exact
synthetic scene. It does not prove a real person's identity, request, legal basis, consent, or
personal-media acceptance.

## 11. Known blockers

Rung 2 is not implemented by this path. It requires a physically validated scale receipt, measured
coverage, a measured collision-safe corridor, required destinations, and structural-world
authority. Rung 1 is not implemented by this path. It requires a reviewed resumable gsplat runner,
compatible GPU execution, physically validated scale, measured coverage, and real held-out quality
results.

Those producers are additive inputs to the scene gate. They do not change scene identity, member
registration, OPM/2, the placement record, deletion reachability, or the graph's distinction among
recorded rung, displayed rung, and substrate.
