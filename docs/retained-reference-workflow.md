# Retained photographic references — 2026-09-05

**The requested strong reconstructed baseline is not established.** Two real, CC0 photographic
collections are retained and viewable through ordinary Atlas source/evidence delivery. Their
reconstruction privacy reviews are unanswered, and this Apple M3 Pro host has no CUDA device.
No trained real scene, held-out image score, physical-scale result, GPU bill, or reconstructed
walkthrough is claimed. Source-only browser screenshots are evidence of fallback UX only.

## What is retained

All paths below are relative to the repository. Runtime credentials are in
`.exulanica/reference-baseline/runtime/access.json` (mode 0600); do not commit that file.
The shared content-addressed store is `.exulanica/reference-baseline/runtime/blobs`.
Original asset keys use `sha-256/<first two hex>/<next two hex>/<full SHA-256>` beneath that
store, using the exact digests in each frozen manifest and intake journal.
Only `postgresql://localhost:5433/exulanica_spine_test` is used. Public-schema demonstration
workspaces survive tests, which use isolated disposable schemas in that same permitted database.

| Collection | Exact originals | Frozen training / held out | Local inputs |
| --- | ---: | ---: | --- |
| Chili salmon bowl, Charin Rungchaowarat (promto-c) | 51 | 44 / 7 | `.exulanica/reference-baseline/inputs/chili-salmon-bowl/images` |
| Montserrat volcanic sample, Mike R. James and Stuart Robson | 210 | 183 / 27 | `.exulanica/reference-baseline/inputs/volcanic-sample/photographs` |

The bowl workspace is `bdba4f95-07e3-4ff6-8c5b-eb8989ab63cb`, with source region
`d3e3db87-1fa6-5591-9981-d4247a5d6f59`. The volcanic workspace is
`79004d44-ca24-4d17-9eef-56786415e233`, with source region
`92ee2c49-be60-5de4-9d6e-8b710ed7f0a7`. These are source-world identities;
no accepted real reconstruction scene or trained asset ID exists yet.

Prepared manifests, intake journals, unanswered review forms, and authored source compositions
are retained under `.exulanica/reference-baseline/bowl` and `.../volcanic`. Committed copies of the
frozen manifests are `docs/evaluation/2026-09-05-reference-{bowl,volcanic}-inputs.json`. They include
every filename, SHA-256, size, image dimension, license attribution, split and visual rubric.
The split was frozen before image inspection and any reconstruction or tuning.

The bowl source is the [author's dataset](https://huggingface.co/datasets/promc/reconstruction-scenes)
at revision `bb2ec30fd17ffb65e24ab40e713517d0c65de41b`; only its original
`chili-salmon-bowl/images/*` photographs were acquired. Each download matched the publisher's LFS
SHA-256. No pretrained scene was substituted. The author lists CC0 in the dataset card.

The second source is [James et al. sample-scale data](https://doi.org/10.6084/m9.figshare.9120020),
also CC0. Its original archive is
[images.zip](https://ndownloader.figshare.com/files/16636739), 611,535,084 bytes, publisher MD5
`a62826fd45a89551a548897cf6b62b01`; the independent reference is
[scale_data.zip](https://ndownloader.figshare.com/files/16636586), 1,351,117 bytes, MD5
`7d92a4243d4e81ffa956dc349969f408`. Both checksums were verified before safe extraction.
The reference lists six measured target distances and an identification photograph. These have
**not** been associated with reconstructed points or used to validate physical scale.

Publisher metadata and the [CC0 legal text](https://creativecommons.org/publicdomain/zero/1.0/legalcode.en)
are retained in the local inputs directory. License permission is separate from the repository's
required named human screening of the exact photographs. No real screening receipt was fabricated.

## Open the existing source collections

Run each long-lived process in its own terminal from the repository:

```bash
uv run python scripts/reference_instance.py api
uv run python scripts/reference_instance.py web --scene bowl --port 5180
uv run python scripts/reference_instance.py web --scene volcanic --port 5181
```

Open `http://127.0.0.1:5180/` for the bowl or `http://127.0.0.1:5181/` for the volcanic sample.
Use a desktop viewport wider than 60 rem; comparisons use 1280 × 720 CSS pixels. The `web` command
sets `VITE_EXULANICA_SOURCE_PRESENTATION=inspection`, so these review instances keep the original
photographs in the inspector instead of placing the ordinary world's photo veils in the landscape.
A veil is a flat photograph with softened, animated edges; during reconstruction review it read as
floating geometry, which is why review instances omit veils and the camera targeting that aimed at
them. While no reconstruction has loaded, a prominent **No 3D reconstruction is loaded** panel names
the exact authorized source inventory and offers **Inspect source photographs**; switch sources, then
**Return to Atlas**. The footer's smaller "grouped photographs" count is metadata group membership
(40 for the bowl), while the panel and inspector count the authorized originals (51). Ordinary Atlas
without that setting keeps its world presentation unchanged. The existing Aeroheart appearance and
world/source-slot architecture are reused. The decorative world is not a reconstructed surface.

The bowl's metadata-derived group has 40 photographs; its explicitly authored gallery includes
all 51 selected originals. Authored gallery membership does not invent timestamps or assert a
new evidence relationship. Exact-set reconstruction selects the full declared input inventory,
through the existing operator-selection boundary, without altering EXIF or automatic grouping.

The launcher clears inherited deployment URLs, model credentials and the database-creation flag,
sets the permitted database explicitly, and runs the ordinary API with the normal application and
read-only roles. It never prints tokens. Stop the API and any source, depth, or scene workers
before database verification. The two `web` commands launch browser development servers, not
reconstruction workers.

The static review server exposes only the public input directory, never runtime credentials:

```bash
uv run python -m http.server 8765 --bind 127.0.0.1 \
  --directory .exulanica/reference-baseline/inputs
```

Its exact-byte review pages are `http://127.0.0.1:8765/review-bowl.html` and
`http://127.0.0.1:8765/review-volcanic.html`.

## Reuse the workflow for another scene

1. Obtain authorized original photographs and retain the license/source evidence. For personal
   media, follow the existing personal-media admission process; the benchmark endpoint cannot
   turn a personal manifest into benchmark permission.
2. Freeze sources and the held-out split with `scripts/reference_scene.py prepare`. It requires
   `--sources`, `--output`, `--title`, `--source-url`, `--license-name`, `--license-url`,
   `--license-file`, `--attribution`, and `--retrieval-date`. Default `--heldout-every 8` selects
   the first original and then every eighth original in lexicographic order (zero-based indices
   0, 8, 16, …). Existing frozen manifests cannot be replaced
   with changed bytes or a new split. Use a new output directory for a new experiment.
3. Provision a stable local workspace with `scripts/reference_instance.py init --scene <label>`.
   Start or restart the API with `scripts/reference_instance.py api --scene <label>` so it loads
   the new workspace token, then upload with the command below. Uploads use ordinary authenticated
   intake and conservative batches; the journal binds returned capture IDs to original content hashes.
4. A named human must inspect **every exact original** and complete a copy of `review-request.json`:
   name, time, exact attestation, and every per-source result. An unanswered or changed review is
   refused. If there are people/sensitive regions, use the existing sensitive-region/personal
   admission path; do not attest to their absence.
5. Submit the completed review. The authenticated endpoint binds the full frozen manifest and
   held-out split into the existing authorization/screening receipts, then queues normal derivative
   work. It does not accept another actor or workspace in the request body.
6. Run the depth worker with the reviewed MoGe runtime. Current point maps plus exact screening
   are prerequisites for pose/training jobs. The source-only worker remains useful without
   these prerequisites and cannot silently invent depth.
7. Queue the exact scene with the same capture identities, optionally providing a fully specified
   training request. Run the normal scene worker on the authorized runtime. Its durable job owns
   pose, alignment, training, acceptance and publication; there is no demonstration database writer.
8. Compose source slots into an existing region, open ordinary Atlas, and execute the declared
   visual pass. Retain the successful scene; perform deletion tests in disposable workspaces.

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

The source and depth worker commands drain currently eligible work and exit. The local depth
launcher selects MoGe on Apple MPS; it needs the reviewed depth dependencies and model runtime
already available. Run the scene worker separately as described below; `queue` submits work
and does not execute it.

Omit `--training-request` to request only pose/point-map reconstruction. The selector refuses
missing current derivatives or screening; absence is not success. `compose` requires one existing
region or an explicit `--region`. It uses the protected topology writer and existing evidence spans.
For an existing non-local deployment, use its authenticated intake/review API and the existing
operator/worker configuration instead of the local test-database launcher.

Training configuration uses `SceneSplatRequest`'s strict
`exulanica.scene-splat-request/v1` payload. It includes the real immutable execution-image digest,
actual requested GPU, dependency inventory, exact frozen held-out hashes, iteration/checkpoint/
Gaussian/byte limits, declared hourly price, and predeclared image/coverage/floater thresholds.
Rates and thresholds in the queue request use integer millionths. Do not substitute a fabricated
image digest, billing rate or GPU name. See [the training guide](gsplat-scene-jobs.md) for the image
build, runtime isolation, optimizer state, metrics and accounting limits. A threshold is a proposed
acceptance rule until the actual held-out measurement and visual inspection have run.

The scene worker requires `EXULANICA_DATABASE_URL`, `EXULANICA_DATA_DIR`,
`EXULANICA_WORKSPACE_IDS`, `EXULANICA_CODE_REVISION` and `EXULANICA_POSE_RUNTIME_IMAGE`.
Configure its database role according to [scene operations](scene-reconstruction-operations.md),
then run `uv run --extra pose exulanica-scene-worker`. Depth and pycolmap run in separate processes
because their native OpenMP runtimes conflict on this Mac. GPU training additionally needs the
reviewed Docker runtime and pinned compressor executable on the worker's PATH.

## Alignment, quality and operational evidence

[Placement v2](scene-placement-alignment.md) replaces the historical display-only identity scale.
It fits positive scale from exact COLMAP track/image/point-map correspondences, then validates
held-out correspondences and coverage. Failed members remain explicit exclusions. This is
coordinate alignment, not an independent physical measurement. Old identity-scale placements
are withheld until rebuilt. Trained geometry remains in the accepted COLMAP frame; browser
delivery uses its explicit transform/bounds and authenticated content digest.

The frozen visual rubric requires every dimension to reach at least 3/4: surfaces, color/detail,
arrival/motion, world boundary, and source/loading/failure/return UX. The intended traversal is
60 seconds at 1280 × 720 through first/central/last registered source poses and adjacent-camera
midpoints, with identical cameras/settings across iterations. After reconstruction loads,
expand its status and choose **Inspect reconstruction**. Accepted source cameras are available
independently of point-map bytes, so a trained scene can be inspected even when every OPM is
unavailable. The browser uses the accepted pose, calibrated focal lengths and principal point;
legacy records can fall back to the OPM field-of-view estimate. Distorted camera models are
explicitly labelled pinhole approximations, and canvas aspect can extend horizontal coverage.
Midpoints are unobserved viewpoints, not validated walking routes. **Return to Atlas** restores
the prior position, orientation, field of view and projection.

Point-map inspection disables its atmospheric fog and boundary thinning and uses full display
density. Source confidence and semantic visibility still apply; this does not establish that
every uploaded point becomes visible. Source photographs remain available beside reconstructed
camera views. None of these reconstructed-camera behaviors has yet been visually validated on
either retained real collection.

Pose estimation may use held-out photographs; their RGB is excluded from Gaussian optimization
and color initialization. Report this as appearance-held-out evaluation, not unseen-pose recovery.

The retained record and companion mutation records under `docs/evaluation/2026-09-05-*` distinguish
real public-source intake/browser observations from synthetic operational tests. CPU optimizer
resumption and actual CPU SOG compression are useful implementation evidence; neither establishes
real CUDA convergence. Scripted GPU receipts in isolated pipeline tests are labelled synthetic.
Withdrawal/corrupt-byte tests use disposable fixtures, never either retained source workspace.

To repeat verification, stop retained workers/API, leave `EXULANICA_TEST_ALLOW_DATABASE_CREATION`
unset, and set `EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test`.
Run backend tests serially. `scripts/verify_reference_controls.py` also uses only that exact
database; `scripts/verify_gsplat_controls.py` never uses a database. Run the web workspace checks
with the existing package commands. The final evaluation record records actual results and
limitations, including any unrelated in-flight failures.

## Retained verification outcome

The [digest-bound progress record](evaluation/2026-09-05-retained-reference-progress.json)
binds the frozen inputs, exact code, companion control records, source-state audit and screenshots.
The final full backend run passed **1604 tests**, with three disclosed skips. The subsequent final
publication suite passed **66 tests** after the last identity/provenance fixes. The web checks passed
**717 tests**, type checking and package boundaries; the app build passed with the existing large-bundle
warning. All 18 final publication mutations failed at their intended regression assertions, and the
restored suite passed. The companion records retain the other executed negative controls.

The final read-only audit checked every retained original's database identity and content hash:
51 bowl originals (126046395 bytes) and 210 volcanic originals (614030051 bytes), with zero
reconstruction jobs, scenes or human screening receipts in either retained workspace.
Representative actual browser captures are retained under
`docs/evaluation/artifacts/2026-09-05-reference/`: source-world and source-inspection views for each
collection, plus `atlas-unavailable.png`. They establish source fallback and service-retry behavior.
A reconstructed walkthrough, held-out scores and traversal performance remain unavailable.

Those captures show the earlier world presentation, in which each review instance placed a source
veil in the landscape; they remain historical. The later
[source-presentation correction record](evaluation/2026-09-05-source-presentation-correction.json)
binds the inspection presentation, its tests and executed mutation controls, and repeatable
1280 × 720 captures under `docs/evaluation/artifacts/2026-09-05-source-presentation/`, taken with
the retained headless capture script beside them. It records an honest unavailable state, not
reconstruction progress.

## Exact dependencies to resume real reconstruction

- Named human confirmation for both complete exact-byte galleries, with review time and the
  actual sensitive-region findings. The prepared manifests and blank forms identify the exact set.
- An accessible authorized CUDA host/account, or authorization to provision one with a spending
  cap. The immutable image must then be built and its actual digest recorded; that is execution
  work, not something a placeholder can satisfy.
- Independent target association/measurement validation before any physical scale or rung 1 claim.
  Nonmetric training is permitted, but it cannot promote the recorded rung by itself.

Until those dependencies are supplied and the real visual/quality pass succeeds, these changes
are a tested pipeline and a usable source fallback, **not the exceptional reference scene requested**.
