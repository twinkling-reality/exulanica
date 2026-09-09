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

DELIVERED 2026-09-06: the fourth bowl request (floater ceiling 0.9, compressor on the GPU) trained
30000 iterations in 74 minutes alone on the L40S, measured PSNR 25.28 dB, SSIM 0.896, LPIPS 0.309,
coverage 0.983 and floater proxy 0.466 over the same 7 held-out views, compressed to a 15.3 MB
SOG with every SH band, and is displayed in Atlas at 60 fps with these numbers beside its rung.
The three earlier requests are retained as refusals and failures in the
[real reconstruction record](evaluation/2026-09-05-real-reconstruction.json).

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
splat-transform --no-tty --overwrite -g <device> input.ply output.sog
```

`<device>` is the worker's `EXULANICA_COMPRESSOR_GPU` setting: `cpu` by default, or a WebGPU
adapter index. Every spherical-harmonic band is delivered either way, and the device is recorded
in `compression-attempt.json`. MEASURED 2026-09-06 on one million degree-3 Gaussians: the
compressor's k-means over 65536 clusters of 45 coefficients ran for three hours on one CPU core
without finishing, and completed in 4.1 s (10.8 s wall clock for the whole compression, 15.3 MB
output) on the L40S through Vulkan. The scene worker container therefore carries the Vulkan
loader and `deploy/gsplat/run-scene-worker.sh` gives it the GPU with graphics capability. An
attempt to sidestep the cost by dropping higher bands with `-H 0` did not take effect in the
position it was given and was withdrawn; the delivered format is unchanged from the protocol's
first version.

The output SOG size/digest enters the gate receipt. An actual local CPU conversion of 512 generated
test-only Gaussians verified version-2 `meta.json` and ZIP STORE entries; this format smoke test
is not a training, image-quality, or reference-scene acceptance result. Checkpoints, rectified training data, attempt
logs, and held-out renders are private operational artifacts, not default publication assets.
`accepted.ply` is the legacy controller filename; its presence by itself is not acceptance.

To look at what the scores measured, `scripts/heldout_comparisons.py` reads a retained evaluation
bundle (by path, or by content digest inside the blob store), verifies every file it uses against
the bundle's own inventory and the render digests in `metrics.json`, and writes one photograph
beside render JPEG per held-out view with that view's PSNR, SSIM, LPIPS and coverage printed on it,
plus a `comparisons.json` that binds the bundle, the render and reference digests and the output
images. A tampered or truncated bundle is refused rather than drawn. The comparisons show
appearance at photographed viewpoints only.

## Masked members and the held-out remap

Implemented 2026-09-09. A scene may contain members whose photograph is replaced by a masked
derivative before anything reads a pixel: pose, placement and the gate have run fully masked since
`exulanica.ingest.masked_inputs` existed. Training was refused until now, and the refusal was
about one specific hazard rather than about masking generally. The build manifest requires
`heldout_source_sha256` to be a proper subset of `source_sha256`; `source_sha256` comes from the
pose frames, which under masking are derivative digests, while a held-out split is declared over
the photographs a person actually reviewed. Relaxing the subset rule to accept the mismatch is the
fix that looks obvious and is wrong: on a partially masked scene the unmasked held-out members
still match by digest, so `load_dataset` finds a held-out view, raises nothing, and trains on the
masked photographs the split said it was withholding.

What is delivered instead is a remap. At enqueue, `_enqueue_capture_set` derives from the same
current privacy selection that produced `masked_sources` a second view of it: per hidden member,
the capture reference, the original photograph's SHA-256 and the derivative's SHA-256. It binds
that into the stored training request, which also resolves `heldout_source_sha256` onto the
derivatives. The request an operator wrote still names the photographs they reviewed; what the
queue stores names the bytes training will read, beside the map that says which is which. **The
subset rule is unchanged.**

Resolving at enqueue rather than carrying originals downstream is forced, not preferred.
`world_package/training_inputs.py` validates a training export by comparing pose-frame digests,
which are derivative digests, against `build_inputs.splat_training.heldout_source_sha256` and
against `manifest.parameters.heldout_source_sha256` in the publication receipt. Leaving originals
in either place would make package export refuse every masked trained scene with "training split
differs from the frozen scene build", in a file this work does not touch. Nothing downstream has
to infer one space from the other, and the frozen split of an admitted reference source is still
compared in the original space, before the substitution, so `validate_admitted_sources` means
exactly what it always meant.

The map is checked three times, in three different currencies:

- **At enqueue**, against current privacy inputs. `selected_masks` already refuses a member that
  needs a mask and has no current one, or whose declared derivative has gone stale under 0040's
  matcher; `bind_masked_sources` additionally refuses a map naming bytes outside the admitted
  source set, a map an operator declared rather than one derived here, and any resolution that
  would collapse two held-out photographs onto one derivative.
- **At manifest construction**, against the pose frames. By then the worker has re-resolved every
  declared mask and rebound each hidden member, so the frames are the ground truth of what will be
  staged. `SceneSplatRequest.manifest` refuses when the derivative a frame carries is not the one
  the map was frozen with, which is what catches a map whose entries were exchanged between two
  hidden members, or a stored declaration and a map that fell out of step. A mask genuinely
  rebuilt between enqueue and run does not normally reach here: `verify_masked_sources` resolves
  the declared artifact before pose runs, `mask_is_current` no longer matches it, and the job is
  refused earlier and more cheaply. This bullet is the second line for that case and the only
  line for the exchange, which the manifest cannot catch on its own because it never learns which
  capture a hash belonged to. That is why the map carries a capture reference and not only a pair
  of digests.
- **In the manifest, against the hashes alone.** A declared derivative must be among the training
  sources, and a mapped original must not be. The second is the load-bearing one: it is the rule
  that says the photograph of somebody who asked to be hidden is not in the set the trainer reads.

`verify_masked_training_sources` restates the last of those against files rather than hashes, in
the runner and before `prepare_dataset` rather than merely before `load_dataset`. The earlier
position is the point: rectification decodes every staged image and writes it back into the job
directory, so a leaked original checked afterwards would already be re-encoded into retained
scratch by the time anything refused it. The check is otherwise deliberately a restatement. The
controller's `_verify_dataset_sources` already proves the staged bytes are exactly `source_sha256`,
and the manifest has already refused any map whose originals appear there, so the two together
leave no room; this buys independence, not new coverage. A build with nobody hidden returns from it
immediately and pays no extra pass over the images.

Nothing had to change for the renders themselves to be scored against the masked derivative,
because the staged dataset holds only derivatives and every pixel path is rooted in it.
`per_view.source_sha256` digests the staged image, so on a masked scene it is the derivative's;
`per_view.reference_pixels_sha256` digests the pixels actually compared, which is the same file
for a PINHOLE scene and its rectification for a distorted one. Neither is ever an original, and
that inequality is exactly what the evaluation bundle uses to decide whether to retain a rectified
reference, so recording an original in `per_view` would break the bundle as well as falsify it.
This has never run on a masked scene: it is a property of the paths, not an observation.

What the receipts now add is the statement of which photograph each derivative replaced. The
training publication receipt carries the map under `manifest.parameters.masked_source_remap`, and
`split.json` carries it again beside `heldout_original_source_sha256` and an explicit
`reference_pixels` note, inside the retained evaluation bundle.

### What changes identity, and what does not

Only scenes that actually have a hidden member. `masked_source_remap` is omitted from the request
payload and from the manifest's `parameters` when it is empty, exactly as `masked_sources` is
omitted from the build inputs, so a corpus with nobody in it reproduces its request bytes, build
input digest, job id, manifest digest, job directory, checkpoint identity, `split.json` and
retained bundle byte for byte. No stage version or stage parameter changes, and `pipeline_digest()`
is unchanged: the map alters no output schema any stage owns, and identity separation between a
mapped and an unmapped build already comes from the build input and manifest digests. For a masked
scene every one of those identities moves, which is the intended behaviour and the same rule a
consent change has always followed: a new build rather than a mutated accepted one.

### Limits

**No masked scene has been trained on a GPU.** Every check above is exercised through the scripted
trainer in `tests/test_scene_splat_pipeline.py` against real PostgreSQL, real person regions and
the real `masked_source` stage, plus manifest-level controls in `tests/test_reconstruction_splat.py`
and the read helper's own tests. Those establish the enqueue, manifest, staging and receipt
boundaries. They establish nothing about appearance, convergence, cost or how a masked region
behaves under Gaussian optimization, and the floater and coverage proxies have never been measured
on a scene containing flat masked fill. A masked reference scene remains the next thing to measure.

**The runner-side check has never executed at its call site.** `verify_masked_training_sources` has
direct tests, and an ordering test reads its position out of `_train_locked` rather than running
it, because `_train_locked` needs torch, numpy and pycolmap in one process and this host cannot
give it that. The same is true of the `split.json` remap block: the scripted trainer writes it
through the same helper the runner uses, which is what makes the retained bundle's shape real, but
the runner's own call site is unexecuted here.

**The map publishes a hidden member's original photograph digest.** It has to: a map from original
to derivative is what was asked for, and a receipt that named only derivatives would say nothing.
The consequence is that `manifest.parameters.masked_source_remap` now carries, in the published
training receipt and therefore in a world package export, a content address for bytes that were
deliberately not exported. That address discloses no pixels, but it does let anyone already holding
the photograph confirm it was in this scene. Nothing before this change put that digest in a
training receipt.

**`scripts/heldout_comparisons.py` will mislabel a masked scene.** It captions its left panel
"held-out photograph" and copies `per_view.source_sha256` into `comparisons.json`, both of which
are the masked derivative on a masked scene, and it never reads `split.json` where the remap and
its `reference_pixels` note live. It is correct about the pixels and wrong about the word. That
script is outside this work's scope; a masked scene's comparisons should not be read as showing a
photograph until it is corrected.

**`TRAINING_PROTOCOL["split"]` still describes the frozen split in terms of original source
digests.** That wording predates masked training and is now imprecise for a masked build, where
the frozen split names derivatives and the remap names the originals. It is left alone on purpose:
it is inside the manifest's protocol block, so editing it would change every existing build
identity, including the retained bowl and volcanic receipts.

The remap is a statement about bytes, not about people. It says which derivative replaced which
photograph; it does not establish that the derivative hides everyone it should, which is the
`masked_source` stage's claim and the human review's, recorded elsewhere. A mixed-format corpus is
worth one caution: a masked derivative is always JPEG, so a hidden member whose original was a PNG
stages under a different filename than it would have unmasked, and only that member does. That
interacts badly with a pre-existing defect outside this work, where per-member registration is
computed from the un-rebound media type and so looks for `000003.png` when the staged frame is
`000003.jpg`; a masked non-JPEG member is recorded unregistered until that is fixed separately.

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

The masked-training contract additionally needs a database, because its subject is what current
privacy inputs say rather than what a fixture asserts:

```bash
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest tests/test_scene_splat_pipeline.py tests/test_masked_scene_inputs.py tests/test_reconstruction_splat.py
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
