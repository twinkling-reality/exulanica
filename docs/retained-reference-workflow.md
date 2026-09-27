# Retained reference collections

This guide reuses two public CC0 photograph collections, retained outside Git, to exercise building
a place in a world from photographs end to end: admission with a named human review, depth, pose,
placement, optional GPU training and delivery. It also shows how to run the same workflow for
another authorized set. The contracts it follows are
[scene-reconstruction-operations.md](scene-reconstruction-operations.md) and
[gsplat-scene-jobs.md](gsplat-scene-jobs.md).

## Contents

- [Outcome](#outcome)
- [What is retained](#what-is-retained)
- [Open the collections](#open-the-collections)
- [Reuse the workflow for another scene](#reuse-the-workflow-for-another-scene)
- [Run the scene worker on an authorized CUDA host](#run-the-scene-worker-on-an-authorized-cuda-host)
- [Alignment, quality and inspection](#alignment-quality-and-inspection)
- [Verification](#verification)

## Outcome

Both collections were admitted with a named human screening statement, went through depth, COLMAP
pose, correspondence placement and publication as point-map scenes, and were trained on a rented
NVIDIA L40S. The 51-photograph bowl is a delivered Gaussian scene (held-out PSNR 25.28 dB, SSIM
0.896, LPIPS 0.309 and coverage 0.983 over 7 views; a 15.3 MB browser asset) traversed at 60 fps
with its measured quality on screen. The 210-photograph volcanic set trained twice and was refused
on measured coverage (0.73 and 0.63 against 0.75), because the rock was turned over against
different backdrops; its point-map scene stands. Nothing here claims physical scale, and both
recorded rungs are 3. The digest-bound outcome is the
[real reconstruction record](evaluation/2026-09-05-real-reconstruction.json).

## What is retained

All paths below are relative to the repository and live in ignored local storage. Runtime
credentials are in `.exulanica/reference-baseline/runtime/access.json` (mode 0600); never commit
that file. The shared content-addressed store is `.exulanica/reference-baseline/runtime/blobs`, and
original asset keys use `sha-256/<first two hex>/<next two hex>/<full SHA-256>` beneath it, with the
exact digests in each frozen manifest and intake journal. Only
`postgresql://localhost:5433/exulanica_spine_test` is used; tests use isolated disposable schemas in
that database, and the demonstration workspaces live in its public schema.

| Collection | Exact originals | Frozen training / held out | Local inputs |
| --- | ---: | ---: | --- |
| Chili salmon bowl, Charin Rungchaowarat (promto-c) | 51 | 44 / 7 | `.exulanica/reference-baseline/inputs/chili-salmon-bowl/images` |
| Montserrat volcanic sample, Mike R. James and Stuart Robson | 210 | 183 / 27 | `.exulanica/reference-baseline/inputs/volcanic-sample/photographs` |

The bowl workspace is `bdba4f95-07e3-4ff6-8c5b-eb8989ab63cb`, with source region
`d3e3db87-1fa6-5591-9981-d4247a5d6f59`. The volcanic workspace is
`79004d44-ca24-4d17-9eef-56786415e233`, with source region
`92ee2c49-be60-5de4-9d6e-8b710ed7f0a7`.

Prepared manifests, intake journals, review forms and authored source compositions are under
`.exulanica/reference-baseline/bowl` and `.../volcanic`. Committed copies of the frozen manifests
are `docs/evaluation/2026-09-05-reference-{bowl,volcanic}-inputs.json`; they include every
filename, SHA-256, size, image dimension, licence attribution, split and visual rubric. The split
was frozen before image inspection and before any reconstruction or tuning.

The bowl source is the [author's dataset](https://huggingface.co/datasets/promc/reconstruction-scenes)
at revision `bb2ec30fd17ffb65e24ab40e713517d0c65de41b`; only its original
`chili-salmon-bowl/images/*` photographs were acquired, and each download matched the publisher's
LFS SHA-256. No pretrained scene was substituted. The author lists CC0 in the dataset card.

The second source is [James et al. sample-scale data](https://doi.org/10.6084/m9.figshare.9120020),
also CC0. Its original archive is
[images.zip](https://ndownloader.figshare.com/files/16636739), 611,535,084 bytes, publisher MD5
`a62826fd45a89551a548897cf6b62b01`; the independent reference is
[scale_data.zip](https://ndownloader.figshare.com/files/16636586), 1,351,117 bytes, MD5
`7d92a4243d4e81ffa956dc349969f408`. Both checksums were verified before safe extraction. The
reference lists six measured target distances and an identification photograph. These have **not**
been associated with reconstructed points or used to validate physical scale.

Publisher metadata and the [CC0 legal text](https://creativecommons.org/publicdomain/zero/1.0/legalcode.en)
are retained in the local inputs directory. Licence permission is separate from the required named
human screening of the exact photographs.

## Open the collections

Run each long-lived process in its own terminal from the repository:

```bash
uv run python scripts/reference_instance.py api
uv run python scripts/reference_instance.py web --scene bowl --port 5180
uv run python scripts/reference_instance.py web --scene volcanic --port 5181
```

Open `http://127.0.0.1:5180/` for the bowl or `http://127.0.0.1:5181/` for the volcanic sample, in
a desktop viewport wider than 60 rem; comparisons use 1280 by 720 CSS pixels. While no
reconstruction has loaded, a **No 3D reconstruction is loaded** panel counts the authorized
originals and offers **Inspect source photographs**; the inspector's **Return to your world**
button returns to the world view.

The launcher clears inherited deployment URLs, model credentials and the database-creation flag,
sets the permitted database explicitly, and runs the ordinary API with the normal application and
read-only roles. It never prints tokens. Stop the API and any source, depth or scene workers before
database verification. The two `web` commands start browser development servers, not reconstruction
workers.

The static review server exposes only the public input directory, never runtime credentials:

```bash
uv run python -m http.server 8765 --bind 127.0.0.1 \
  --directory .exulanica/reference-baseline/inputs
```

Its exact-byte review pages are `http://127.0.0.1:8765/review-bowl.html` and
`http://127.0.0.1:8765/review-volcanic.html`.

## Reuse the workflow for another scene

1. Obtain authorized original photographs and retain the licence and source evidence. For an
   account holder's own photographs, follow [personal admission](personal-admission.md); the
   benchmark endpoint cannot turn a personal manifest into benchmark permission. Training personal
   photographs also needs a scene training right naming the destination
   ([personal-admission.md](personal-admission.md#scene-training-right)); the `queue` command below
   declares no destination, so it trains only benchmark and synthetic sets.
2. Freeze sources and the held-out split with `scripts/reference_scene.py prepare`. It requires
   `--sources`, `--output`, `--title`, `--source-url`, `--license-name`, `--license-url`,
   `--license-file`, `--attribution` and `--retrieval-date`. The default `--heldout-every 8`
   selects the first original and then every eighth original in lexicographic order (zero-based
   indices 0, 8, 16 and so on). A frozen manifest cannot be replaced with changed bytes or a changed
   split; use another output directory for another experiment.
3. Provision a stable local workspace with `scripts/reference_instance.py init --scene <label>`.
   Start or restart the API with `scripts/reference_instance.py api --scene <label>` so it loads
   the workspace token, then upload with the command below. Uploads use ordinary authenticated
   intake in conservative batches, and the journal binds returned capture ids to original content
   hashes.
4. A named human must inspect **every exact original** and complete a copy of `review-request.json`:
   name, time, exact attestation and every per-source result. An unanswered or changed review is
   refused. If there are people or sensitive regions, use the sensitive-region and personal
   admission path; do not attest to their absence.
5. Submit the completed review. The authenticated endpoint binds the full frozen manifest and
   held-out split into the authorization and screening receipts, then queues normal derivative
   work. It does not accept another actor or workspace in the request body.
6. Run the depth worker with the reviewed MoGe runtime. Current point maps and an exact screening
   are prerequisites for pose and training jobs. The source-only worker stays useful without them
   and cannot invent depth.
7. Queue the exact scene with the same capture identities, optionally with a fully specified
   training request, and run the normal scene worker on the authorized runtime. Its durable job
   owns pose, alignment, training, acceptance and publication; there is no demonstration database
   writer.
8. Compose source slots into an existing region, open the application and run the declared visual
   pass. Keep the successful scene; run deletion tests in disposable workspaces.

Example commands after preparing a directory `reviewed-scene` and initializing label `example`:

```bash
uv run python scripts/reference_instance.py workflow --scene example intake \
  --sources photographs --manifest reviewed-scene/inputs.json --output reviewed-scene
uv run python scripts/reference_instance.py sources-worker --scene example
uv run python scripts/reference_instance.py workflow --scene example admit \
  --sources photographs --manifest reviewed-scene/inputs.json --output reviewed-scene \
  --human-review reviewed-scene/completed-human-review.json \
  --permitted-use 'The actual retained license and permitted processing scope'
uv run python scripts/reference_instance.py depth-worker --scene example
uv run python scripts/reference_instance.py queue --scene example \
  --directory reviewed-scene --training-request reviewed-scene/training-request.json
uv run python scripts/reference_instance.py compose --scene example --directory reviewed-scene
```

The source and depth worker commands drain eligible work and exit. The local depth launcher selects
MoGe on Apple MPS and needs the reviewed depth dependencies and model runtime already available.
`queue` submits work and does not execute it; run the scene worker separately.

Omit `--training-request` to request only pose and point-map reconstruction. The selector refuses
missing current derivatives or screening; absence is not success. `compose` requires one existing
region or an explicit `--region`, and uses the protected topology writer and existing evidence
spans. For a non-local deployment, use its authenticated intake and review API and its operator and
worker configuration instead of the local test-database launcher.

A training request is the strict `exulanica.scene-splat-request/v1` payload of
[gsplat-scene-jobs.md](gsplat-scene-jobs.md): the real immutable execution-image digest, the actual
requested GPU, a dependency inventory, exact frozen held-out hashes, iteration, checkpoint, Gaussian
and byte limits, a declared hourly rate and predeclared image, coverage and floater thresholds, with
fractions in integer millionths. Never substitute a fabricated image digest, rate or GPU name. A
threshold is a proposed acceptance rule until the held-out measurement and visual inspection have
run.

The scene worker requires `EXULANICA_DATABASE_URL`, `EXULANICA_DATA_DIR`,
`EXULANICA_WORKSPACE_IDS`, `EXULANICA_CODE_REVISION` and `EXULANICA_POSE_RUNTIME_IMAGE`; configure
its database role according to
[section 7 of the reconstruction scenes contract](scene-reconstruction-operations.md#7-running-the-worker).
Depth and pycolmap run in separate processes because their native OpenMP runtimes conflict. GPU
training also needs the reviewed Docker runtime and the pinned compressor on the worker's PATH, so
in practice the worker runs on the CUDA host.

Admission also queues the ordinary metadata-group scene job, so a workspace can hold a group scene
and an exact-set scene over overlapping photographs. A job whose stage bindings are no longer
current is refused rather than run under different rules; queue another exact request instead of
retrying it.

## Run the scene worker on an authorized CUDA host

This pattern keeps the permitted database and the retained store as the authority while pose,
placement and training run where the GPU is. The trainer launcher bind-mounts local paths and talks
to the local Docker daemon, so the worker itself must run on that host, not through a remote Docker
context. It was exercised on a rented NVIDIA L40S virtual machine running Ubuntu 22.04 and
Docker 29.

1. Bootstrap the host once with `deploy/gsplat/host-bootstrap.sh`. It verifies the GPU inside
   Docker, installs the NVIDIA container toolkit if the runtime is missing, unpacks the official
   Node tarball for the locked compressor, and starts a local registry on `127.0.0.1:5000` so every
   image gets a real immutable manifest digest without an external account.
2. Ship the committed tree:
   `git archive HEAD | ssh <host> 'mkdir -p ~/exulanica && tar -x -C ~/exulanica'`, then on the host
   run `npm ci --prefix deploy/gsplat/compressor` with `~/node/bin` on the PATH.
3. Build and push both images at that revision. The worker image is the root `Dockerfile`; the
   trainer image is `deploy/gsplat/Dockerfile` with `CUDA_BASE` set to the digest-pinned reference
   `docker inspect --format '{{index .RepoDigests 0}}'` reports for the pulled PyTorch base. Push
   each to `localhost:5000/...:<short revision>` and read its `RepoDigests` entry back. The
   trainer's build revision must equal the worker's `EXULANICA_CODE_REVISION`, and the runner
   refuses any other pairing, so a code change means rebuilding both and queueing a request with
   the trainer's digest.
4. Sync the store:
   `rsync -a .exulanica/reference-baseline/runtime/blobs/ <host>:~/exulanica-data/blobs/`.
5. Keep a reverse tunnel to the database open while the worker runs:
   `ssh -N -R 127.0.0.1:5433:127.0.0.1:5433 <host>`. The worker's URL names a database user the
   tunnelled server accepts and the permitted database, and `PGOPTIONS=-c role=exulanica_app`
   selects the ordinary application role.
6. Queue the exact scene with a training request whose `execution_image` is the trainer digest and
   whose `requested_gpu` is exactly what `torch.cuda.get_device_name(0)` reports inside that image,
   then run `deploy/gsplat/run-scene-worker.sh exulanica-scene-worker --once --name <name> --job <job id>`
   on the host with `CODE_REVISION`, `EXULANICA_WORKSPACE_IDS` and `EXULANICA_DATABASE_URL` set. The
   launcher refuses to start without a job scope (`--job` or `EXULANICA_SCENE_JOB_IDS`), so a rented
   pass never drains an older stale job first. It runs the worker inside the worker image with host
   networking, the host Docker socket and the store mounted at its host path, so pose receipts
   record the runtime they ran in, and it gives the container the GPU with graphics capability and
   `EXULANICA_COMPRESSOR_GPU=0`, so the SOG compressor runs on the card. The host needs the NVIDIA
   driver's Vulkan ICD, which the driver installs.
7. Pull results back with
   `rsync -a --ignore-existing <host>:~/exulanica-data/blobs/ .exulanica/reference-baseline/runtime/blobs/`;
   the store is content-addressed, so the merge is safe, and the database rows already point at those
   objects. Reload the application.

## Alignment, quality and inspection

[Placement](scene-reconstruction-operations.md#3-placement-coordinates-scale-and-correspondence-fitting)
fits positive scale from exact COLMAP track, image and point-map correspondences and validates
held-out correspondences and coverage; failed members stay explicit exclusions. It is coordinate
alignment, not physical measurement. Trained geometry stays in the accepted COLMAP frame, and
browser delivery uses its explicit transform, bounds and authenticated content digest.

The frozen visual rubric requires every dimension to reach at least 3 of 4: surfaces, colour and
detail, arrival and motion, world boundary, and source, loading, failure and return experience. The
intended traversal is 60 seconds at 1280 by 720 through the first, central and last registered
source poses and adjacent-camera midpoints, with identical cameras and settings across iterations.
After a reconstruction loads, expand its status and choose **Inspect reconstruction**. Accepted
source cameras are available independently of point-map bytes, so a trained scene can be inspected
even when every point map is unavailable. The browser uses the accepted pose, calibrated focal
lengths and principal point; records without calibrated intrinsics fall back to the point map's
field-of-view estimate, and distorted camera models are labelled pinhole approximations. Midpoints
are unobserved viewpoints, not validated walking routes. **Return to your world** restores the
prior position, orientation, field of view and projection. The real reconstruction record retains
the traversal of the delivered bowl scene.

Point-map inspection disables atmospheric fog and boundary thinning and uses full display density.
Source confidence and semantic visibility still apply, so this does not establish that every
uploaded point becomes visible. Source photographs stay available beside reconstructed camera views.

Pose estimation may use held-out photographs; their RGB is excluded from Gaussian optimization and
colour initialization. Report this as appearance-held-out evaluation, not unseen-pose recovery.
After a training run,
`uv run python scripts/heldout_comparisons.py --sha256 <bundle digest> --output <evidence directory>`
produces the photograph-beside-render images and the digest-bound `comparisons.json`; the bundle
digest is the training receipt's evaluation artifact hash. Look at every held-out view, not the best
one.

## Verification

To repeat verification, stop the retained workers and API, leave
`EXULANICA_TEST_ALLOW_DATABASE_CREATION` unset, and set
`EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test`. Run backend tests
serially. `scripts/verify_reference_controls.py` uses only that exact database;
`scripts/verify_gsplat_controls.py` uses no database. Run the web workspace checks with the package
commands.

The retained records distinguish real public-source intake and browser observations from synthetic
operational tests: the [real reconstruction record](evaluation/2026-09-05-real-reconstruction.json)
for the reconstruction and training outcomes, the
[progress record](evaluation/2026-09-05-retained-reference-progress.json) for the frozen inputs,
controls and source-state audit before any reconstruction ran, and the
[source-presentation record](evaluation/2026-09-05-source-presentation-correction.json) for the
source inspection captures. CPU optimizer resumption and CPU SOG compression are implementation
evidence and do not establish CUDA convergence. Withdrawal and corrupt-byte tests use disposable
fixtures, never either retained workspace.
