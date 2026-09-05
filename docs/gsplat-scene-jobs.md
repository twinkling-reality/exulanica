# Per-scene gsplat jobs

Status 2026-09-05, evening: **the runner image has been built from this recipe and executed on a
rented NVIDIA L40S; real CUDA training of the retained bowl collection ran through the normal scene
worker.** The morning statement that no CUDA execution existed is superseded. The first real run
found and fixed four trainer defects the CPU tests could not see: a Double seed scale beside Float
means, a stderr digest that left the failure nameless, per-iteration JPEG decoding that held the GPU
at 24 percent utilization, and glog's failure handler claiming the worker's SIGTERM after pycolmap
was imported. A SIGTERM to the running trainer container produced a durable checkpoint at iteration
3858 and exit 75, as designed. Measured speeds and costs are in
[the GPU compute note](reference-gpu-compute.md); the accepted-scene outcome is recorded in the
evaluation record that accompanies the retained workflow, not asserted here.

`exulanica.reconstruction.splat` remains the content-addressed controller for one scene-specific
Gaussian optimization. The manifest pins the exact original source set, accepted pose-manifest
digest, Exulanica revision, gsplat revision, execution image digest, requested GPU, dependency
inventory, complete training/metric protocol, checkpoint interval, iteration and Gaussian caps,
held-out policy, price rate, and quality thresholds. Changes to settings or metric definitions create
a new build identity.

The previous statement that the resumable trainer was missing is superseded by
`exulanica.reconstruction.gsplat_runner`. This is an independent single-GPU training loop using
Apache-2.0 gsplat `v1.5.3`, commit `937e29912570c372bed6747a5c9bf85fed877bae`. It uses the actual
gsplat differentiable rasterizer and MCMC strategy, torch Adam optimizers, and image losses. It does
not use upstream `simple_trainer.py --ckpt`, which is an evaluation-only path. CUDA execution has
now happened on real photographs; what remains open is recorded per scene in the evaluation records.

## Input and coordinate contract

Both controller and executable require an accepted full v2 pose receipt whose carried manifest
reproduces its digest, whose exact source filenames/hashes match the dataset, and whose complete
sparse artifact inventory matches every supplied model byte. The selected connected model is used
explicitly. An unrelated model cannot acquire authority merely by receiving a fresh dataset digest.

Accepted nonmetric poses may be optimized in their declared world units. A present physical-scale
measurement must be finite and positive; joint metric claims still require the shared metric frame.
`SplatQuality.accepted` only means the declared appearance-quality and delivery-byte gates passed.
It never records rung 1. `SceneGate` still requires independent accepted scale and coverage receipts
for rung 1. Agreement between models, a trained PLY, and a browser draw cannot earn physical scale.
This separates a mathematical training prerequisite from the existing recorded-rung claim; see
`docs/adr/gsplat-training-and-recorded-rung.md`.

Source images must exactly match the manifest SHA-256 set. The dataset is an authorized COLMAP
workspace with `images/` and `sparse/` (or `sparse/0/`); checkpoint identity additionally binds all
sparse model bytes. Symlinks and image paths outside that dataset are refused.

Distorted camera models are rectified through actual pycolmap 4.2.0 inside `output/training/`, using
versioned interpolation, scale bounds, and JPEG quality. This does not replace original source
hashes. A retained preparation receipt maps each original image digest to the image pixels used in
training and binds the entire resulting calibration/model. Camera poses and sparse coordinates
must be unchanged. A later change to sources, camera models, or rectified bytes refuses reuse. An interrupted
rectification with no committed receipt is regenerated only within the job-owned private directory.
PINHOLE inputs retain their original pixel bytes. The trainer does not recenter or normalize the
world. Coordinates remain the authoritative COLMAP world frame; cameras use +X right, +Y down,
+Z forward. The delivery layer must apply the independently established physical scale and Atlas
axis transform, and must not label raw COLMAP coordinates as metres.

## Resumption and accounting

The controller invokes `exulanica-gsplat-scene-v1 train --profile
exulanica.gsplat-scene-runner/v1 --manifest ... --pose-receipt ... --dataset ... --output ...
--resume auto`. The installed executable launches the exact manifest image with Docker GPU device
0, read-only source/manifest/pose mounts, one writable job-output mount, no network, and no added
capabilities. The launcher serializes access to that output, durably records a unique container
ownership label before launch, and captures Docker's exact container ID. On cancellation it asks
the daemon to stop that owned container, allows 15 seconds for a checkpoint, then kills if needed.
It verifies stopped or absent state before returning or permitting scratch removal. A confirmed
trainer checkpoint preserves exit75; forced termination never claims a checkpoint. If Docker
cannot confirm cleanup, exit76 and `container-cleanup-required.json` retain private scratch.
The next launch reconciles that guard against the same ownership label before starting anything
new. Unverified ownership requires recovery; it never authorizes stopping an unrelated container.

The trainer checkpoints **after** backward, optimizer, scheduler, and MCMC updates. Each atomic,
digest-bound checkpoint contains:

- Every Gaussian parameter and every Adam moment/step counter.
- Learning-rate scheduler state, MCMC strategy state, and the next iteration.
- Python, NumPy, Torch CPU and all visible CUDA RNG states.
- The shuffled training-image order and cursor, so restart does not silently change the next view.
- Manifest/dataset identity, observed elapsed duration, and observed peak allocated CUDA memory.

A durable `latest.json` pointer appears only after the checkpoint and directory entry are synced.
Loading uses Torch's restricted `weights_only` loader and refuses changed identity, corrupt bytes,
missing optimizer state, or an uncommitted pointer. SIGINT/SIGTERM is handled at the next completed
iteration, checkpoints, and returns 75. The next call restores state and continues optimization.
A hard kill can lose work since the last checkpoint; it cannot manufacture a complete runtime bill.
The runtime records a lower observed duration and `duration_accounting_complete=false` for an
unfinished prior attempt, and the quality controller refuses that result until complete external
accounting can be provided by a future reviewed protocol. Graceful interruption remains resumable
without this cost ambiguity.

Runtime receipts record actual GPU name, CUDA, driver, loaded distributions, installed version
inventory, Gaussian/iteration counts, summed measured process-attempt time including startup and final evaluation, and
Torch's peak CUDA allocation across attempts. Peak allocation excludes allocations outside Torch
and is not presented as total board memory. Cost is measured duration times the manifest's versioned
hourly rate; provider provisioning time and a provider invoice are outside this measurement. The requested GPU must match the actual allocated GPU. The loaded gsplat checkout and
Exulanica image revision must match the manifest. Common blocked INRIA rasterizer distributions
remain a hard refusal.

## Evaluation before publication

Before reconstruction, the source-preparation workflow declares exact held-out original source
SHA-256 values. The build requires `heldout_source_sha256` to be a nonempty proper subset of its
source inventory. `split.json` maps these hashes to registered views and records held-out sources
that failed registration. Renaming images or losing earlier registrations cannot change the split. At least three training views and one held-out view are required.
The trainer never optimizes held-out RGB or uses those colors to initialize Gaussians (initial
color is neutral gray). **COLMAP geometry and camera estimation may condition on all registered
images.** These are appearance-held-out scores with pose/geometry conditioning, not an independent
pose-recovery generalization result.

MEASURED 2026-09-05 on the first real trained scene (51 bowl photographs, 7 held out): PSNR
25.38 dB, SSIM 0.896, LPIPS 0.310 and coverage 0.983 all passed their predeclared rules, and the
held-out renders matched the photographs on inspection, but the floater proxy measured 0.472 against
a predeclared 0.15 and refused delivery. The proxy counts opacity mass farther than five times the
median sparse neighbour spacing from any sparse point; that spacing was 0.0093 units because COLMAP
matched the bowl densely, so every Gaussian on the plain table around it counted as a floater. The
proxy therefore stays a retained diagnostic and the request's ceiling is a divergence guard (0.9 in
the retained requests); floaters a person can see are judged in the visual pass, and a scale-aware
or visibility-based floater measure is future work. Changing the ceiling is a new request and a
new build; the refused run's receipt and evaluation bundle remain retained.

Evaluation renders every held-out view at the documented rectified resolution without exposure
matching or color correction. It records per-view and mean PSNR, SSIM, AlexNet LPIPS, source and
render digests, and pixel dimensions. Coverage is the mean held-out pixel fraction with rendered
alpha at least 0.95. The floater fraction is an opacity-weighted sparse-support proxy: Gaussian
means farther than five times median sparse nearest-neighbor spacing. It is **not** a measurement
of every human-visible floater or of complete physical geometry. These definitions are frozen in
the build manifest before tuning. Browser traversal and visual inspection remain necessary.

Missing/nonfinite values, incomplete duration accounting, a mismatched manifest/protocol, or a
changed PLY refuse receipt acceptance. A failed threshold keeps rung 3 and prevents compression.
Only an accepted PLY is converted after verifying `splat-transform v3.3.3` against the manifest
protocol. Install the locked tool with `npm ci --prefix deploy/gsplat/compressor`, then put that
directory's `node_modules/.bin` on the worker PATH or pass its executable explicitly. The documented
PlayCanvas CLI shape is:

```text
splat-transform --no-tty --overwrite -g cpu input.ply output.sog
```

The output SOG size/digest enters the gate receipt. An actual local CPU conversion of 512 generated
test-only Gaussians verified version-2 `meta.json` and ZIP STORE entries; this format smoke test
is not a training, image-quality, or reference-scene acceptance result. Checkpoints, rectified training data, attempt
logs, and held-out renders are private operational artifacts, not default publication assets.
`accepted.ply` is the legacy controller filename; its presence by itself is not acceptance.

## Build and run on available CUDA compute

`deploy/gsplat/Dockerfile` is the concrete build recipe. It requires a real **digest-pinned** CUDA
development base compatible with Torch 2.7.1 / torchvision 0.22.1 / CUDA 12.8 and a 40-character
Exulanica commit. The build compiles the reviewed gsplat checkout and downloads the LPIPS weights
before network-isolated scene execution. The resolved package inventory is retained in the image.
The example architecture list targets NVIDIA Ampere/Ada/Hopper; choose the actual target
architecture at build time. The final immutable image digest belongs in `SplatBuildManifest`.

```bash
# From a clean committed checkout on the CUDA build host; substitute reviewed real values.
docker build -f deploy/gsplat/Dockerfile \
  --build-arg CUDA_BASE='pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel@sha256:<verified-digest>' \
  --build-arg CODE_REVISION="$(git rev-parse HEAD)" \
  -t '<authorized-registry>/exulanica-gsplat:<revision>' .
```

Publish/inspect that image through an authorized registry and use its returned immutable digest,
not an invented placeholder or a mutable tag. Run the existing controller with the accepted scene
pose receipt, exact dataset, and this manifest. It owns training, interruption, quality evaluation,
and SOG conversion; publication still goes through normal authorization and recorded-rung gates.
A GPU access credential, any required spending approval, an accepted independent physical scale,
and a built immutable runner image are concrete prerequisites for the first metric rung-1 candidate.
An accepted nonmetric scene may train before the scale reference exists; its rung remains gated.

## Executed verification and limits

The focused tests exercise real CPU Adam continuation, all three CPU RNG streams, sampler/strategy
and scheduler restoration, real COLMAP undistortion in a separate process, source/calibration
integrity refusal, and the controller's receipt gates. Container cancellation tests run real child
processes against an explicit local Docker-protocol stand-in whose daemon state survives CLI exit;
they verify stop/kill confirmation, ownership, uncertain cleanup retention, and reconciliation.
They do not establish behavior on a real Docker daemon or GPU host.
They do not claim CUDA convergence, GPU determinism, visual quality, a trained asset, or a measured
training bill. Torch checks run in isolated child processes so their OpenMP runtime does not
conflict with native COLMAP already loaded by the ordinary test suite. No duplicate-runtime
override is used. CUDA kernels can be nondeterministic; exact CPU continuation proves state handling
and does not promise bit-identical GPU output.

```bash
uv run pytest tests/test_gsplat_runner.py tests/test_gsplat_dataset.py tests/test_gsplat_container.py tests/test_reconstruction_splat.py
```

The local Apple M3 Pro host reports Torch 2.14.0, CUDA unavailable, and MPS available. gsplat's reviewed
CUDA path cannot be tested by substituting MPS or by labelling a point map as a Gaussian scene.
Executed isolated production-mutation controls and the source-bound verification record are under
`docs/evaluation/2026-09-05-gsplat-trainer-*.json`. Reproduce isolated mutation controls with
`uv run python scripts/verify_gsplat_controls.py`; this script never connects to a database.

Primary upstream interfaces inspected:

- <https://github.com/nerfstudio-project/gsplat/tree/937e29912570c372bed6747a5c9bf85fed877bae>
- <https://github.com/nerfstudio-project/gsplat/blob/937e29912570c372bed6747a5c9bf85fed877bae/gsplat/strategy/mcmc.py>
- <https://github.com/nerfstudio-project/gsplat/blob/937e29912570c372bed6747a5c9bf85fed877bae/gsplat/exporter.py>
- <https://github.com/colmap/colmap/tree/4.2.0/python>
- <https://github.com/playcanvas/splat-transform>
