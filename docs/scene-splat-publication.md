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
with stable ordering and timestamps. Its retained-byte budget and allowed file classes enter stage
identity; version 2 raised the budget from 256 MiB to 1 GiB after the 27 held-out 12 MP views of
the volcanic set produced a 266.9 MB bundle once and an over-budget one the next run, which lost
that completed run's receipt. It retains metrics, runtime/package inventory, required runtime-bound split and preprocessing receipts,
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

## The graph projection

A fourth deterministic artifact, `scene_projection`, publishes inside the same atomic acceptance as
the pose receipt, the placement and the gate. It carries what a graph reader would otherwise
rebuild: each placed member's `scene_from_opm` transform, scale and point-map references, each
excluded member's reason, and the recovered cameras. It exists because rebuilding those is what a
cold `GET /graph` used to cost. MEASURED 2026-09-09: 47.9 s for the 210 member volcanic scene in
every fresh process, none of it depending on anything mutable.

It is bound to five things, and a reader proves all five before using one. Three are the pose,
placement and gate content digests, so a projection belonging to a superseded build cannot answer
for the current one. The fourth is the scene's member capture refs in scene order, which is the one
input no digest covers: withdrawing a member leaves all three receipts byte-identical. The fifth is
the placement's point-map references in record order, which is how a superseded or re-pointed
point-map artifact row is seen. The reader also establishes that every one of those point maps is
present and reproduces its content digest, by reading the bytes through the store and dropping
them; that is a live fact rather than a binding and cannot be carried in an artifact.

Any of those failing falls back to the rebuild, and so does a projection that is absent, purged,
flagged for repair, unparseable or failing its own payload digest. A refused projection therefore
costs the read exactly what it cost before projections existed, and nothing else. The artifact rows
with their `purged_at` and tombstone predicates, the scene's members, the gate agreement, the person
regions and review states, and the asset-read policy the route applies afterwards are all re-read on
every request, unchanged. A projection shortens one computation and answers no question about
permission or liveness.

Nothing privacy-bearing enters it. It carries no person region, no review state, no source
photograph digest and no pose manifest frame. The source digests are the reason that is a rule
rather than an observation: `scene_allowed` denies a scene by comparing the pose manifest's frame
digest against the live artifact row, and re-masking a withdrawn person moves `read_source_sha256`.
A copy of those digests in a durable artifact would be a second, stale answer to a question the
asset-read policy exists to ask fresh.

The projection has no column on the job row, unlike the three receipts. The graph finds it by
selecting the newest few live projections for the scene and proving each from its own bindings.
Several rather than one because nothing sets `artifact.superseded_by` on a scene artifact, so every
projection a scene has ever had stays live. `scripts/backfill_scene_projections.py` gives an
already published scene the projection it was published without; it projects only a scene's current
job, for the same reason, and records what it wrote as JSON. It is idempotent, because the artifact
id is derived from the three receipt digests.

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
