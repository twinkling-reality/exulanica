# Durable scene training and publication

Implemented 2026-09-05. This is the normal production path from an admitted, exact capture set
through pose recovery, point-map correspondence fitting, Gaussian training, retained evaluation,
and authenticated delivery. Tests use numeric synthetic geometry and a named scripted trainer.
They do not establish CUDA convergence or accept a real reference scene.

## Queue and execution

`enqueue_exact_scene_reconstruction(..., splat_training=SceneSplatRequest(...))` adds an explicit
training request to the existing durable scene job. It requires an immutable runtime image digest,
requested GPU, dependency inventory, exact held-out original source hashes, iteration/checkpoint/
Gaussian limits, browser byte limit, an explicit GPU-hour rate, and quality thresholds. Queue
numbers use integer millionths; the complete request and stage bindings enter the immutable
build-input digest. The request does not provision a machine or authorize remote spending.

All members must already have current screened point maps and normal scene admission. A reference
source's retained authorization manifest freezes its evaluation split before training. Every
member must carry that same manifest, and both training and held-out membership must match it.
Generic sources without a prior reference manifest freeze their explicit split at enqueue.

The existing scene worker owns one lease and heartbeat throughout pose, placement and training.
It passes the accepted pose receipt, exact images and complete selected sparse model to the real
controller. The staged training dataset is keyed by the pose output it was cut from: a retried job
whose pose manifest changed re-runs COLMAP and produces different sparse bytes, and MEASURED
2026-09-05 a shared staging directory refused that second output as a resumed dataset with changed
input bytes. A failed trainer attempt now also retains the last 4000 bytes of its stderr and names
the last line in the job's failure message; a digest alone left the first real failure nameless. Runtime identity and metric verification remain the controller's responsibility;
see [the trainer contract](gsplat-scene-jobs.md). Install the locked compressor and make its
`node_modules/.bin` directory available on the worker's PATH. The installed
`exulanica-gsplat-scene-v1` launcher must run on the already authorized CUDA host with the pinned
image present. The [reference workflow](retained-reference-workflow.md) provides the operator
queue interface; no database hand edits or special publication fixtures are required.

## Artifacts and recorded claims

The worker uses the existing guarded scene artifact writer to prepare the pose receipt, fitted
placement, gate, training publication receipt, SOG delivery and private evaluation bundle.
Only the final succeeded job and its active rung assertion publish the exact artifact set.
Gate identity includes training outputs. A prepared replacement build cannot become readable
through an older successful build. Distinct exact build inputs also receive distinct pose output
identities, so new training requests do not assume COLMAP will reproduce identical bytes. Both
training receipt and SOG identities bind that exact build input as well as the training manifest;
a new point-map build cannot collide with an earlier run merely because its training settings
stayed the same. The immutable job identity also distinguishes separately authorized runs of
unchanged inputs, while retries of the same job retain their identities. The deterministic
evaluation ZIP is keyed by its actual retained content.

`scene_splat_training` and `scene_splat_delivery` are nondeterministic stages. The separate
`scene_splat_evaluation` stage deterministically packages fixed generated output bytes as a ZIP
with stable ordering and timestamps. Its 256 MiB budget and allowed file classes enter stage
identity. It retains metrics, runtime/package inventory, required runtime-bound split and preprocessing receipts,
attempt accounting, every declared held-out PNG, and rectified held-out reference pixels when they
differ from retained originals. Companion files must reproduce the runtime's digest bindings;
pixel files must reproduce their metric digests. Checkpoints and
the source training dataset are excluded. The training publication receipt binds the bundle's
artifact ID, hash and byte size. The bundle has no browser delivery route and shares ordinary
whole-scene withdrawal and purge provenance. These generated artifacts remain reconstructions,
never source evidence or citation targets.

An accepted SOG preserves the selected COLMAP frame and has an identity scene transform.
The delivery descriptor carries a conservative three-sigma support box: each Gaussian contributes
a sphere using its largest axis scale, so anisotropic rotation cannot underbound it. Bounds and
nonmetric coordinates do not establish physical scale, collision or navigability.

`SplatQuality.accepted` establishes the configured appearance and byte gates only. The recorded
scene gate independently requires accepted scale and coverage receipts for rung 1. A nonmetric
trained scene therefore remains at its supported recorded rung. Training quality refusal retains
the normal fitted point-map scene and the evaluation receipt. A missing or corrupted SOG falls
back to those verified point maps without rewriting the durable recorded claim.

## Delivery and recovery

`GET /scene-geometry/{artifact_id}` requires the ordinary workspace bearer token and exact current
published training receipt. It returns no-store, digest-bound bytes; a foreign workspace,
unpublished replacement, withdrawn scene, or evaluation bundle cannot obtain Gaussian bytes.
The graph's optional `trained_geometry` descriptor contains only the SOG reference, identity
transform, bounds and observed availability. Atlas verifies its bytes and self-contained SOG
texture inventory before native rendering.

Each registered member can separately carry an accepted `recovered_camera`: its unscaled world
transform and original COLMAP calibration, including off-centre principal point and unequal focal
lengths. Camera arrival and inspection therefore survive loss of all point-map bytes. Distorted
models retain every distortion coefficient while explicitly labelling the renderer's projection
as a pinhole approximation. This camera descriptor does not change the recorded rung.

SIGINT/SIGTERM requests training shutdown even in worker `--once` mode. The launcher confirms
owned Docker termination. A verified durable checkpoint releases the same queue job without
consuming its failure budget, so repeated graceful preemptions remain resumable. Completed
training also survives retryable object-store/publication failures; a retry reuses the original
controller receipt rather than generating conflicting measured durations or training bytes.

Withdrawal or lease loss is checked while an opaque subprocess runs and before every publication
boundary. Normal confirmed withdrawal clears private scratch. If container termination cannot
be confirmed, a durable ownership cleanup marker protects scratch even from abandoned-job sweeps.
The next launcher reconciles its owned container before starting another attempt; an unverified
owner requires operator recovery. Scratch is never deleted while the external process may still
hold source mounts.

## Reproduction

`tests/test_scene_splat_pipeline.py` covers the normal publication boundary, frozen split,
withdrawal, workspace separation, quality refusal, damaged delivery, repeated checkpoints,
prepared replacement isolation, and storage retry without retraining. Its scripted metrics and
Gaussian output are explicitly test-only; the native SOG format and real trainer have separate
tests. No real-scene appearance or GPU bill is claimed by these checks.

`python scripts/verify_scene_publication_controls.py` runs pure production mutations in an isolated
source copy. Add `--database-controls` only while exclusively owning the permitted disposable
database; it adds serialized queue/publication mutations and never changes the working checkout.
Every mutation must be detected by its named test between passing baseline and restored runs.
Logs and digest-bound control records are written under `.exulanica/reference-baseline/`.

The final serialized focused run passed 66 tests. All 18 isolated production mutations were
detected, followed by another passing 66-test run. Exact source and output hashes, the earlier
full-suite result, and the synthetic/CUDA limitations are retained in
[the publication verification record](evaluation/2026-09-05-scene-publication.json).
