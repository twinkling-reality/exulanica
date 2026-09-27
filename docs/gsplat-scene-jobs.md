# Scene training

A reconstruction scene can be trained into a Gaussian scene that a world draws in place of its
point maps. This contract owns that training: the request and its queue, the trainer and its
container, checkpoints and accounting, held-out evaluation, masked inputs, compression,
publication and delivery of the trained asset, and recovery. The scene pipeline it extends is
[scene-reconstruction-operations.md](scene-reconstruction-operations.md); the right that lets a
trainer read an account holder's own photographs is in
[personal-admission.md](personal-admission.md); the operator walkthrough for the retained
collections is [retained-reference-workflow.md](retained-reference-workflow.md). Training a scene
is distinct from training or integrating a general world-generation model.

## Contents

- [Training request and queue](#training-request-and-queue)
- [Trainer and container](#trainer-and-container)
- [Input and coordinate contract](#input-and-coordinate-contract)
- [Resumption and accounting](#resumption-and-accounting)
- [Held-out evaluation](#held-out-evaluation)
- [Artifacts, compression and recorded claims](#artifacts-compression-and-recorded-claims)
- [Delivery and recovery](#delivery-and-recovery)
- [Masked members and the held-out remap](#masked-members-and-the-held-out-remap)
- [Build and run on CUDA compute](#build-and-run-on-cuda-compute)
- [Verification and limits](#verification-and-limits)

## Training request and queue

`enqueue_exact_scene_reconstruction(..., splat_training=SceneSplatRequest(...))` adds an explicit
training request to the durable scene job. The request is a strict
`exulanica.scene-splat-request/v1` payload: an immutable runtime image digest, the requested GPU, a
dependency inventory, exact held-out original source hashes, iteration, checkpoint and Gaussian
limits, a browser byte limit, a declared GPU-hour rate and quality thresholds, with fractional
values in integer millionths. The complete request and its stage bindings enter the immutable
build-input digest. The request provisions no machine and authorizes no spending.

A job over an account holder's own photographs also declares where they travel
(`training_destination`, stored in the build inputs as `scene_training_destination`). The database
refuses to queue it, or to publish what it produced, unless a current scene training right covers
every personal member at that destination
([personal-admission.md](personal-admission.md#scene-training-right)). Synthetic and benchmark
captures need no training right.

Every member must already have a current screened point map and normal scene admission. A
reference source's retained authorization manifest freezes its evaluation split before training;
every member must carry that manifest, and both training and held-out membership must match it.
Other sources freeze their explicit split at enqueue.

The scene worker owns one lease and heartbeat throughout pose, placement and training, and passes
the accepted pose receipt, exact images and complete selected sparse model to the controller. The
staged training dataset is keyed by the pose output it was cut from, so a retried job whose pose
manifest changed stages a separate dataset instead of resuming one with changed input bytes. A
failed trainer attempt retains the last 4000 bytes of its stderr and names the last line in the
job's failure message.

## Trainer and container

`exulanica.reconstruction.splat` is the controller and `exulanica.reconstruction.gsplat_runner` is
the trainer: an independent single-GPU training loop using Apache-2.0 gsplat `v1.5.3`, commit
`937e29912570c372bed6747a5c9bf85fed877bae`, with gsplat's differentiable rasterizer and MCMC
strategy, torch Adam optimizers and image losses. It does not use upstream
`simple_trainer.py --ckpt`, which is an evaluation-only path.

The build manifest pins the exact original source set, accepted pose-manifest digest, Exulanica
revision, gsplat revision, execution image digest, requested GPU, dependency inventory, complete
training and metric protocol, checkpoint interval, iteration and Gaussian caps, held-out policy,
price rate and quality thresholds. A change to any setting or metric definition is a different
build identity.

The controller invokes:

```text
exulanica-gsplat-scene-v1 train --profile exulanica.gsplat-scene-runner/v1 --manifest ... \
  --pose-receipt ... --dataset ... --output ... --resume auto
```

The installed executable launches the exact manifest image on Docker GPU device 0 with read-only
source, manifest and pose mounts, one writable job-output mount, no network, a read-only root, all
capabilities dropped and no new privileges. The launcher serializes access to that output, durably
records a unique container ownership label before launch, and captures Docker's exact container
id. On cancellation it asks the daemon to stop that owned container, allows 15 seconds for a
checkpoint, then kills if needed, and verifies a stopped or absent state before returning or
permitting scratch removal. A confirmed trainer checkpoint preserves exit 75; forced termination
never claims a checkpoint. If Docker cannot confirm cleanup, the launcher exits 76 and
`container-cleanup-required.json` retains private scratch. The next launch reconciles that guard
against the same ownership label before starting anything; unverified ownership requires operator
recovery and never authorizes stopping an unrelated container.

## Input and coordinate contract

Controller and executable both require an accepted full v2 pose receipt whose carried manifest
reproduces its digest, whose exact source filenames and hashes match the dataset, and whose
complete sparse artifact inventory matches every supplied model byte. The selected connected model
is used explicitly; an unrelated model cannot acquire authority by receiving a fresh dataset
digest.

Accepted nonmetric poses may be optimized in their declared world units. A present physical-scale
measurement must be finite and positive; joint metric claims still require the shared metric frame.
`SplatQuality.accepted` means only that the declared appearance-quality and delivery-byte gates
passed. It never records rung 1: the scene gate still requires independent accepted scale and
coverage receipts ([adr/gsplat-training-and-recorded-rung.md](adr/gsplat-training-and-recorded-rung.md)).
Agreement between models, a trained PLY and a browser draw cannot earn physical scale.

Source images must exactly match the manifest SHA-256 set. The dataset is an authorized COLMAP
workspace with `images/` and `sparse/` (or `sparse/0/`); checkpoint identity also binds all sparse
model bytes. Symlinks and image paths outside the dataset are refused.

Distorted camera models are rectified through pycolmap 4.2.0 inside `output/training/`, with
versioned interpolation, scale bounds and JPEG quality. This does not replace original source
hashes. A retained preparation receipt maps each original image digest to the pixels used in
training and binds the resulting calibration and model; camera poses and sparse coordinates must
be unchanged. A later change to sources, camera models or rectified bytes refuses reuse, and an
interrupted rectification with no committed receipt is regenerated only within the job-owned
private directory. PINHOLE inputs keep their original pixel bytes. The trainer does not recenter or
normalize the world: coordinates stay in the authoritative COLMAP frame, with cameras at +X right,
+Y down, +Z forward. The delivery layer must apply any independently established physical scale and
world placement transform, and must not label raw COLMAP coordinates as metres.

## Resumption and accounting

The trainer checkpoints after backward, optimizer, scheduler and MCMC updates. Each atomic,
digest-bound checkpoint contains:

- every Gaussian parameter and every Adam moment and step counter;
- learning-rate scheduler state, MCMC strategy state and the next iteration;
- Python, NumPy, Torch CPU and all visible CUDA RNG states;
- the shuffled training-image order and cursor, so a restart does not change the next view; and
- manifest and dataset identity, observed elapsed duration and observed peak allocated CUDA
  memory.

A durable `latest.json` pointer appears only after the checkpoint and directory entry are synced.
Loading uses Torch's restricted `weights_only` loader and refuses changed identity, corrupt bytes,
missing optimizer state or an uncommitted pointer. SIGINT and SIGTERM are handled at the next
completed iteration, which checkpoints and returns 75; the next call restores state and continues
optimization. A hard kill can lose work since the last checkpoint and cannot manufacture a complete
runtime bill: the runtime records a lower observed duration and `duration_accounting_complete=false`
for the unfinished attempt, and the quality controller refuses that result. Graceful interruption
stays resumable without that ambiguity.

Runtime receipts record the actual GPU name, CUDA, driver, loaded distributions, installed version
inventory, Gaussian and iteration counts, summed measured process-attempt time including startup
and final evaluation, and Torch's peak CUDA allocation across attempts. Peak allocation excludes
allocations outside Torch and is not total board memory. Cost is measured duration times the
manifest's versioned hourly rate; provider provisioning time and invoices are outside this
measurement. The requested GPU must match the allocated GPU, the loaded gsplat checkout and
Exulanica image revision must match the manifest, and common blocked INRIA rasterizer distributions
are a hard refusal.

## Held-out evaluation

Before reconstruction, the source-preparation workflow declares exact held-out original source
SHA-256 values. The build requires `heldout_source_sha256` to be a nonempty proper subset of its
source inventory. `split.json` maps these hashes to registered views and records held-out sources
that failed registration, so renaming images or losing registrations cannot change the split. At
least three training views and one held-out view are required. The trainer never optimizes
held-out RGB or uses those colours to initialize Gaussians (initial colour is neutral grey). COLMAP
geometry and camera estimation may condition on all registered images, so these are
appearance-held-out scores with pose conditioning, not an independent pose-recovery result.

Evaluation renders every held-out view at the documented rectified resolution without exposure
matching or colour correction, and records per-view and mean PSNR, SSIM, AlexNet LPIPS, source and
render digests and pixel dimensions. Coverage is the mean held-out pixel fraction with rendered
alpha of at least 0.95. The floater fraction is an opacity-weighted sparse-support proxy: Gaussian
means farther than five times the median sparse nearest-neighbour spacing. It is not a measurement
of every visible floater or of complete geometry. These definitions are frozen in the build
manifest before tuning; browser traversal and visual inspection remain necessary.

MEASURED on the retained 51-photograph bowl collection with 7 held-out views, on an NVIDIA L40S: the
delivered request scored PSNR 25.28 dB, SSIM 0.896, LPIPS 0.309 and coverage 0.983 and compressed
to a 15.3 MB SOG with every spherical-harmonic band. An earlier request whose image scores also
passed was refused by a floater ceiling of 0.15 against a measured proxy of 0.472: COLMAP matched the bowl so
densely (median spacing 0.0093 units) that every Gaussian on the plain table counted as a floater.
The retained requests therefore use the proxy as a divergence guard (ceiling 0.9) and leave visible
floaters to the visual pass; a scale-aware floater measure does not exist. Changing a ceiling is a
different request and build, and refused runs keep their receipts and evaluation bundles
([real reconstruction record](evaluation/2026-09-05-real-reconstruction.json)).

`scripts/heldout_comparisons.py` reads a retained evaluation bundle (by path, or by content digest
in the blob store), verifies every file it uses against the bundle's inventory and the render
digests in `metrics.json`, and writes one photograph-beside-render JPEG per held-out view with that
view's scores printed on it, plus a `comparisons.json` binding the bundle, render and reference
digests and the output images. A tampered or truncated bundle is refused. The comparisons show
appearance at photographed viewpoints only.

## Artifacts, compression and recorded claims

Missing or non-finite values, incomplete duration accounting, a mismatched manifest or protocol, or
a changed PLY refuse receipt acceptance. A failed threshold keeps the scene's point-map rung and
prevents compression. Only an accepted PLY is converted, after verifying `splat-transform v3.3.3`
against the manifest protocol. Install the locked tool with
`npm ci --prefix deploy/gsplat/compressor` and put that directory's `node_modules/.bin` on the
worker's PATH, or pass the executable explicitly:

```text
splat-transform --no-tty --overwrite -g <device> input.ply output.sog
```

`<device>` is the worker's `EXULANICA_COMPRESSOR_GPU` setting: `cpu` by default, or a WebGPU adapter
index. Every spherical-harmonic band is delivered either way, and the device is recorded in
`compression-attempt.json`. MEASURED on one million degree-3 Gaussians: the compressor's k-means
over 65536 clusters did not finish in three hours on one CPU core and completed in 10.8 s of wall
clock on the L40S through Vulkan, which is why the scene worker container carries the Vulkan loader
and `deploy/gsplat/run-scene-worker.sh` gives it the GPU with graphics capability.

The worker writes, through the guarded scene artifact writer, the pose receipt, fitted placement,
gate, training publication receipt, SOG delivery and private evaluation bundle. Only the final
succeeded job and its active rung assertion publish the exact artifact set. Gate identity includes
training outputs, so a prepared replacement build cannot become readable through an older
successful build. Distinct build inputs receive distinct pose output identities, so a request does
not assume COLMAP reproduces identical bytes. Training receipt and SOG identities bind the exact
build input as well as the training manifest, and the immutable job identity distinguishes
separately authorized runs of unchanged inputs, while retries of one job keep their identities.

`scene_splat_training` and `scene_splat_delivery` are nondeterministic stages. The
`scene_splat_evaluation` stage deterministically packages fixed generated output bytes as a ZIP
with stable ordering and timestamps; its retained-byte budget (1 GiB in version 2, because 27
held-out 12 MP views exceeded 256 MiB) and allowed file classes enter stage identity. The bundle
keeps metrics, runtime and package inventory, the runtime-bound split and preprocessing receipts,
attempt accounting, every declared held-out PNG, and rectified held-out reference pixels where they
differ from the originals. Companion files must reproduce the runtime's digest bindings, and pixel
files their metric digests. Checkpoints and the training dataset are excluded. The training
publication receipt binds the bundle's artifact id, hash and byte size. The bundle has no browser
route and shares whole-scene withdrawal and purge. These generated artifacts are reconstructions,
never source evidence or citation targets. Checkpoints, rectified training data, attempt logs and
held-out renders are private operational artifacts. `accepted.ply` is the controller's filename;
its presence alone is not acceptance.

An accepted SOG keeps the selected COLMAP frame and an identity scene transform. Its delivery
descriptor carries a conservative three-sigma support box in which each Gaussian contributes a
sphere of its largest axis scale, so anisotropic rotation cannot underbound it. Bounds and nonmetric
coordinates do not establish physical scale, collision or navigability. A nonmetric trained scene
keeps its supported recorded rung; a training refusal keeps the fitted point-map scene and the
evaluation receipt; a missing or corrupt SOG falls back to the verified point maps without
rewriting the durable claim.

## Delivery and recovery

`GET /scene-geometry/{artifact_id}` requires the workspace bearer and the exact current published
training receipt, and returns no-store, digest-bound bytes. A foreign workspace, an unpublished
replacement, a withdrawn scene or the evaluation bundle cannot obtain Gaussian bytes. The graph's
optional `trained_geometry` descriptor carries only the SOG reference, identity transform, bounds
and observed availability; the renderer verifies the bytes and the SOG's self-contained texture
inventory before drawing. Each registered member can separately carry an accepted recovered camera
(scene-reconstruction-operations.md section 3), so camera arrival and inspection survive the loss
of every point map.

SIGINT and SIGTERM request training shutdown even in worker `--once` mode, and the launcher
confirms owned Docker termination. A verified durable checkpoint releases the queue job without
consuming its failure budget, so repeated graceful preemptions stay resumable. Completed training
survives retryable object-store and publication failures; a retry reuses the original controller
receipt instead of producing conflicting durations or training bytes.

Withdrawal and lease loss are checked while the opaque subprocess runs and before every publication
boundary. A confirmed withdrawal clears private scratch. If container termination cannot be
confirmed, a durable ownership cleanup marker protects scratch even from abandoned-job sweeps, and
the next launcher reconciles its owned container before another attempt. Scratch is never deleted
while the external process may still hold source mounts.

## Masked members and the held-out remap

A scene may contain members whose photograph is replaced by a masked derivative before anything
reads a pixel; pose, placement and the gate run on those derivatives
([person-presentation-consent.md](person-presentation-consent.md)). Training reads them too, under
one rule about the held-out split. The build manifest requires `heldout_source_sha256` to be a
proper subset of `source_sha256`, and `source_sha256` comes from the pose frames, which are
derivative digests for masked members, while the split is declared over the photographs a person
reviewed. Relaxing the subset rule would be wrong: on a partially masked scene the unmasked held-out
members still match, so a relaxed check would train on the masked photographs the split withholds.

The queue therefore stores a remap. At enqueue, `_enqueue_capture_set` derives from the same current
privacy selection that produced `masked_sources`, per hidden member, the capture reference, the
original photograph's SHA-256 and the derivative's SHA-256, binds that map into the stored training
request, and resolves `heldout_source_sha256` onto the derivatives. The operator's request keeps
naming the reviewed photographs; the stored request names the bytes training reads, beside the map.
The subset rule is unchanged, and export validation in
`exulanica/world_package/training_inputs.py`, which compares pose-frame digests with the frozen
split, needs no inference between the two spaces.

The map is checked three times:

- **At enqueue, against current privacy inputs.** `selected_masks` refuses a member that needs a
  mask and has no current one, or whose declared derivative is stale under the mask matcher;
  `bind_masked_sources` refuses a map naming bytes outside the admitted source set, a map an
  operator declared instead of one derived here, and any resolution that collapses two held-out
  photographs onto one derivative.
- **At manifest construction, against the pose frames.** `SceneSplatRequest.manifest` refuses when
  a frame carries a derivative other than the one the map was frozen with, which catches entries
  exchanged between two hidden members. A mask rebuilt between enqueue and run is normally refused
  earlier, when `verify_masked_sources` resolves the declared artifact before pose runs.
- **In the manifest, against the hashes alone.** A declared derivative must be among the training
  sources and a mapped original must not be. This is the rule that keeps the photograph of somebody
  who asked to be hidden out of the set the trainer reads.

`verify_masked_training_sources` restates the last check against files, in the runner and before
`prepare_dataset`, because rectification decodes and rewrites every staged image and a leaked
original checked afterwards would already be re-encoded into scratch. A build with nobody hidden
returns from it immediately. Renders are scored against the masked derivative because the staged
dataset holds only derivatives: `per_view.source_sha256` digests the staged image and
`per_view.reference_pixels_sha256` the pixels compared, and neither is ever an original.

The training publication receipt carries the map under `manifest.parameters.masked_source_remap`,
and `split.json` carries it again beside `heldout_original_source_sha256` and an explicit
`reference_pixels` note. For a scene with no hidden member the map is omitted from the request and
the manifest, so its request bytes, build input digest, job id, manifest digest, job directory,
checkpoint identity, `split.json` and bundle are byte for byte what they would be without masking.
No stage version or parameter changes. For a masked scene every one of those identities moves, the
same rule a consent change follows: a different build, never a mutated accepted one.

The remap is a statement about bytes, not about people: it says which derivative replaced which
photograph, not that the derivative hides everyone it should, which is the `masked_source` stage's
and the human review's claim. A masked derivative is always JPEG, so a hidden member whose original
was a PNG stages under a `.jpg` name; registration outcomes are read from the staged frame names, so
that member registers under the name it was staged with.

## Build and run on CUDA compute

`deploy/gsplat/Dockerfile` is the build recipe. It requires a digest-pinned CUDA development base
compatible with Torch 2.7.1, torchvision 0.22.1 and CUDA 12.8, and a 40-character Exulanica commit.
The build compiles the reviewed gsplat checkout and downloads the LPIPS weights before
network-isolated scene execution, and retains the resolved package inventory in the image. The
example architecture list targets NVIDIA Ampere, Ada and Hopper; choose the actual target at build
time. The immutable image digest belongs in `SplatBuildManifest`.

```bash
# From a clean committed checkout on the CUDA build host; substitute reviewed real values.
docker build -f deploy/gsplat/Dockerfile \
  --build-arg CUDA_BASE='pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel@sha256:<verified-digest>' \
  --build-arg CODE_REVISION="$(git rev-parse HEAD)" \
  -t '<authorized-registry>/exulanica-gsplat:<revision>' .
```

Publish the image through an authorized registry and use its immutable digest, never a placeholder
or mutable tag. The trainer's build revision must equal the scene worker's
`EXULANICA_CODE_REVISION`. Publication still goes through normal authorization and the recorded-rung
gate. A GPU credential, any required spending approval, an accepted independent physical scale and
a built runner image are prerequisites for a metric rung-1 candidate; an accepted nonmetric scene
may train before a scale reference exists, and its rung stays gated.
[retained-reference-workflow.md](retained-reference-workflow.md) walks through running the scene
worker on a CUDA host.

## Verification and limits

Focused tests exercise CPU Adam continuation, all three CPU RNG streams, sampler, strategy and
scheduler restoration, real COLMAP undistortion in a separate process, source and calibration
integrity refusal, and the controller's receipt gates. Container cancellation tests run real child
processes against a local Docker-protocol stand-in; they verify stop and kill confirmation,
ownership, uncertain cleanup retention and reconciliation, not behaviour on a real Docker daemon or
GPU host. Torch checks run in isolated child processes so their OpenMP runtime does not conflict
with native COLMAP loaded by the ordinary suite. CUDA kernels can be nondeterministic; exact CPU
continuation proves state handling and does not promise bit-identical GPU output.

```bash
uv run pytest tests/test_gsplat_runner.py tests/test_gsplat_dataset.py tests/test_gsplat_container.py tests/test_reconstruction_splat.py
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest tests/test_scene_splat_pipeline.py tests/test_masked_scene_inputs.py
```

`tests/test_scene_splat_pipeline.py` covers the publication boundary, frozen split, withdrawal,
workspace separation, quality refusal, damaged delivery, repeated checkpoints, prepared replacement
isolation, storage retry without retraining and the masked remap, with explicitly test-only scripted
metrics and Gaussian output. `uv run python scripts/verify_gsplat_controls.py` runs isolated trainer
mutation controls and never connects to a database; `scripts/verify_scene_publication_controls.py`
runs publication mutations in an isolated source copy, adding serialized queue and publication
mutations with `--database-controls` only while the caller exclusively owns the permitted
disposable database. The retained records are the
[trainer verification](evaluation/2026-09-05-gsplat-trainer-verification.json),
[trainer negative controls](evaluation/2026-09-05-gsplat-trainer-negative-controls.json) and
[publication verification](evaluation/2026-09-05-scene-publication.json).

Limits:

- The retained evidence holds no masked scene trained on a GPU. The masked checks above run
  through the scripted trainer against real PostgreSQL, real person regions and the real
  `masked_source` stage; they establish the enqueue, manifest, staging and receipt boundaries, and
  nothing about appearance, convergence, cost or how flat masked fill behaves under optimization.
- `verify_masked_training_sources` has direct tests, and its position in `_train_locked` is read
  by an ordering test rather than executed, because that function needs torch, numpy and pycolmap
  in one process.
- The map publishes a hidden member's original photograph digest in the training receipt and
  therefore in a world package export. The digest discloses no pixels, but lets anyone already
  holding the photograph confirm it was in the scene.
- `scripts/heldout_comparisons.py` captions its left panel "held-out photograph" and copies
  `per_view.source_sha256`, both of which are the masked derivative on a masked scene; it does not
  read `split.json`. Its comparisons of a masked scene should not be read as showing a photograph.
- `TRAINING_PROTOCOL["split"]` describes the frozen split in original-source terms, which is
  imprecise for a masked build. It sits inside the manifest's protocol block, so editing it would
  change every existing build identity.

Primary upstream interfaces inspected:

- <https://github.com/nerfstudio-project/gsplat/tree/937e29912570c372bed6747a5c9bf85fed877bae>
- <https://github.com/nerfstudio-project/gsplat/blob/937e29912570c372bed6747a5c9bf85fed877bae/gsplat/strategy/mcmc.py>
- <https://github.com/nerfstudio-project/gsplat/blob/937e29912570c372bed6747a5c9bf85fed877bae/gsplat/exporter.py>
- <https://github.com/colmap/colmap/tree/4.2.0/python>
- <https://github.com/playcanvas/splat-transform>
