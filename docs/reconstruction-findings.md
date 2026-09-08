# Reconstruction findings

Status: **Historical single-photograph findings plus a retained-bowl geometry observation.**
Sections 1 through 7 retain their original 2026-09-02/03 scope; section 8 records the later scene. This is the findings
document [architecture-overview.md](architecture-overview.md) section 8 reserves for "reconstruction
rungs and their quality bar". It records what was measured, on what, with what caveat, so that a
number in the code carries its provenance. Decisions drawn from these numbers live in the decision
records from [adr/0008-generated-geometry.md](adr/0008-generated-geometry.md) onward, not here.

Every number in sections 1 through 7 was measured on 2026-09-02 or 2026-09-03 on an Apple M3 Pro with 18 GiB of
unified memory, macOS 26.5.1, PyTorch 2.14.0 on MPS, and pycolmap 4.2.0 on CPU. The one photograph
is `web/packages/app/public/fixtures/memory/glasshouse-courtyard.jpg`, 1280x960, a wet courtyard with
a figure, a bicycle and a glasshouse. **One photograph is not a corpus.** Every threshold that
rests on it is labelled unvalidated in the code and stays so until the corpus contract in
[evaluation-corpus-contract.md](evaluation-corpus-contract.md) is met.

**What a later reader can and cannot reproduce from the repository.** Neither the photograph nor
the point map derived from it is committed: `web/.gitignore` excludes the whole fixtures directory,
and the only tracked `.opm` in the repository is the small cross-language pin at
`web/packages/atlas-react/test/fixtures/python-writer.opm`. The point map these numbers were taken
from was produced by a stage that is registered non-deterministic, so re-running the model does not
guarantee the same bytes. The scripts are committed and the conventions are recorded here, so the
method reproduces; the exact percentages do not without the same file.

The scripts that produced each table are in `scripts/` and are named in each section. They are
standalone harnesses in the same spirit as `scripts/verify_platform.py`: committed so the evidence
is reproducible, not part of the package.

---

## 1. The single-photograph reconstruction

Measured by the session that shipped the rung 3 support channel, on the fixture above, with
`Ruicheng/moge-2-vitl` at 512 px longest edge.

| Quantity | Value |
| --- | --- |
| Inference on MPS | 2 to 6 s (re-measured at 1.9 to 5.3 s during the lock work in section 6) |
| Points placed at 512 px, after the silhouette drop | 190,570 |
| File size | 3.27 MiB |
| Valid fraction from the model, before the drop | 0.9997 |
| Valid fraction recorded in the file, after the drop | 0.9693 |
| Vertical field of view recovered | 43.04 degrees, hence 55.46 degrees horizontal at 4:3 |
| Median depth | 4.85 m |
| 95th percentile depth | 21.7 m |
| Maximum depth | 35.8 m |
| Points beyond 20 m | 7.62 percent |
| RMS distance from the best-fit plane | 0.85 m against a 6.58 m principal spread |
| Median sample spacing | 1.43 cm |
| Mean support | 0.73 (0.90 at 3 to 6 m, 0.39 at 6 to 10 m, 0.30 at 10 to 20 m, 0.17 beyond) |
| Silhouette drop at `max_depth_step` 0.10 | 3.04 percent of the map, 5,973 points |

The two valid fractions are the same measurement either side of the filter, and both are in the
file: the model placed 99.97 percent of the 196,608 pixels of its working grid, the silhouette
filter removed 5,973 of those, and 190,570 survived, which is the 96.93 percent the header
records. A reader who divides the point count by the pixel count gets the second number and should
not read it as the model having failed on three percent of the frame.

Density does not fix the emptiness: at 1024 px the map has 773,136 points in 13.27 MiB and is not
visibly better from the same camera, and slightly worse close up because sprites overlap harder.

---

## 2. Top-down coverage, decomposed

The handoff to this work carried one number, 27.1 percent of the region's own bounding box filled
at a 12x12 grid, and called a single-view shell "a curtain, not a landscape". That number is
correct and it is the support-filtered figure the Map draws (`MIN_RELIEF_SUPPORT = 0.25` in
`web/packages/atlas-react/src/playcanvas/region-relief.ts`). Decomposing it changes what it means.

Script: `scripts/reconstruction_coverage.py`. Grid over the header's bounding box in X and Z.

| Grid | Any point | Support at or above 0.25 | Support and at least 3 samples, which is what the Map draws | Cell centre inside the camera's horizontal frustum |
| --- | --- | --- | --- | --- |
| 12x12 | 51.4 percent | 27.1 percent | 25.7 percent | 73.6 percent |
| 20x20 | 43.0 percent | 18.0 percent | not measured | 73.5 percent |
| 40x40 | 34.6 percent | 11.0 percent | 10.1 percent | 73.5 percent |

**Read the grid, not just the number.** The Map's relief samples at a 40x40 grid and discards any
cell with fewer than three samples, so **the figure that corresponds to what a viewer actually sees
from above is 10.1 percent**, not the 27.1 percent that a 12x12 grid gives. A coverage percentage
without its grid, its support floor and its minimum sample count is not a measurement, and the same
committed file yields anything from 10.1 to 51.4 percent depending only on those three conventions.

Within 20 m of the camera, on the same grid rather than a re-gridded shorter box, 83.8 percent of
the frustum cells hold a point and 67.6 percent survive the support floor at 12x12, falling to
62.8 and 30.8 percent at 40x40. So the map is dense where the camera was close and thins with
distance, which is what the support channel already says point by point.

Reading: 26.4 percent of the box lies outside the field of view by geometry alone. What one
photograph cannot cover is what it did not look at, plus the sky tail it did not resolve. A second
photograph from a different place raises the number by observation; nothing else does.

Frustum-union upper bounds from poses alone, no surface claimed
(`scripts/reconstruction_frustum_union.py`): one photograph 73.6 percent of the 12x12 box; the
eight synthetic views of section 3 on a 2.5 m arc 86.1 percent; hypothetical walks of 3, 5 and 8
stops 4 m apart with two photographs each, 81.9, 91.7 and 100 percent.

**Two cautions on those bounds, because the comparison is easy to overstate.** The synthetic views
were rendered with a 50 degree vertical field of view, which is 63.74 degrees horizontally against
the source photograph's 55.46, so the arc changes the lens as well as the viewpoint: a single
camera at the origin with the wider lens already covers 79.2 percent of the same box. About 5.6 of
the 12.5 point gain is the lens and only about 6.9 points is the eight viewpoints. And these are
unions of horizontal wedges with no range limit, no vertical frustum and no occlusion, so they
bound what could be seen and say nothing about what would be filled. **The filled fraction inside
those bounds is unmeasured**, because no multi-photograph capture of a real place exists locally.

---

## 3. Pose recovery on this machine

pycolmap 4.2.0 (BSD-3-Clause, `macosx_14_0_arm64` wheel on PyPI, published 2026-09-01) installs
on this Mac and reports `has_cuda == False`. There are no overlapping photographs among the
fixtures, so a synthetic capture was built: the courtyard point map rendered as square sprites
from eight camera poses on a gentle arc within 1.3 m of the original viewpoint, 1024x768,
50 degrees vertical field of view, known intrinsics and extrinsics.

**Caveat that governs every number in this section.** The inputs are renders of a monocular point
map, not photographs. Texture is correct and the geometry is exactly consistent across views, so
SIFT gets an easier problem than real photographs (no view-dependent shading, blur, rolling
shutter or lens). The accuracy figures are upper bounds; the runtimes, the API and the file
format are real measurements.

Scripts: `scripts/reconstruction_synthetic_views.py`, `scripts/reconstruction_pycolmap_run.py`,
`scripts/reconstruction_pycolmap_analyze.py`.

The mapper is not seeded (`random_seed = -1`), so point counts move by tens between runs of the
same configuration. The table is the run whose directory survives, read back by
`scripts/reconstruction_pycolmap_analyze.py`; timings are one run of three and varied by about
30 percent.

| Images | Intrinsics | Registered | Points | Mean reprojection | Extract / match / map | Centre residual after similarity alignment | Pairwise rotation error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | unknown, one camera per image | 8 | 4,337 | 0.44 px | 1.37 / 0.41 / 1.77 s | 2.6 mm | 0.018 degrees |
| 8 | known, shared pinhole | 8 | 4,362 | 0.44 px | 1.67 / 0.53 / 1.06 s | 1.0 mm | 0.043 degrees |
| 5 | known | 5 | 2,667 | 0.40 px | 0.92 / 0.29 / 0.45 s | 1.2 mm | 0.071 degrees |
| 3 adjacent | known | 3 | 1,146 | 0.36 px | 0.86 / 0.17 / 0.14 s | 0.7 mm | 0.095 degrees |
| 2 | any, default options | 0 | | | 0.8 / 0.15 / 0.03 s | | |
| 2 | known, `ignore_two_view_tracks=False` | 2 | 341 to 1,450 | 0.25 to 0.28 px | 0.8 / 0.15 / 0.04 s | not defined | 0.09 to 1.0 degrees |

End to end for eight images at 1024x768 is 3 to 4.5 s on this CPU. Three adjacent images are the
minimum that registers with default options, and only after COLMAP's built-in relaxation of
`init_min_tri_angle` from 16 to 4 degrees, because adjacent views on this arc have a median
triangulation angle of 2.4 degrees. Two images never register with defaults, whatever the
baseline: `IncrementalTriangulatorOptions.ignore_two_view_tracks` discards every track in a
two-image model and the initial pair is discarded for having no points. With unknown intrinsics
the two-view focal drifts to 992 to 1,228 px against 823.5 true, and rotation error rises to
0.8 to 12 degrees; with known intrinsics it stays below 1 degree.

Two facts about the existing controller, verified by loading `exulanica/reconstruction/pose.py`
unmodified against the export:

- `Reconstruction.write_text` produces `cameras.txt`, `images.txt` and `points3D.txt` in exactly
  the layout `pose.py`'s parser reads; its quality function returned `accepted=True` with
  `registered_fraction=1.0` and a reprojection mean identical to pycolmap's own to 1e-15.
- `run_colmap_pose_job` shells out to a `colmap` executable that this environment does not have,
  but it accepts an `executor` callable, so an in-process backend can drive it unchanged.

That backend now exists as `exulanica/reconstruction/pycolmap_executor.py`, and
`tests/test_reconstruction_pycolmap_executor.py` runs six synthetic views through the unmodified
controller: all six register, the receipt and checkpoint are written, a second call reuses the
receipt without invoking COLMAP, and `shared_metric_frame` stays false because no measured scale
was supplied. The tests skip where the `pose` extra is absent, which is CI.

### 3.1 pycolmap and torch cannot share a process on macOS

**MEASURED 2026-09-03**, pycolmap 4.2.0 and torch 2.14.0 in one environment on this machine.
Either alone imports cleanly. Importing both, in either order, aborts:

```
OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib already initialized.
```

followed by SIGABRT. Each wheel carries its own OpenMP runtime. The documented escape,
`KMP_DUPLICATE_LIB_OK=TRUE`, does let both load, and OpenMP's own message says it "may cause
crashes or silently produce incorrect results", so it is not set anywhere in this repository.

The consequence is architectural. **Depth and pose cannot run in one process on macOS**, so a
laptop that does both runs them as two processes. They do not need to share one: they are separate
stages over separate inputs, and the reconstruction barrel does not import the depth model, so
importing the pose path pulls no torch. Whether the two wheels coexist on Linux has not been
tested here and should not be assumed.

---

## 4. Monocular scale against structure from motion

COLMAP's sparse frame is scale-ambiguous; the pose controller's `shared_metric_frame` requires a
measured scale that nothing in the pipeline produces. MoGe-2 recovers metric depth per image,
which is a candidate scale source nobody had connected. Measured on the eight renders of
section 3, by the median over each registered image of the ratio between MoGe depth and COLMAP
depth at the same 2D observations, then the median across images
(`scripts/reconstruction_moge_scale_vs_colmap.py`):

**The reference is not physical, and the comparison is partly circular.** The 0.2565 m per COLMAP
unit that the errors below are measured against comes from aligning COLMAP's recovered cameras to
the positions the render rig used, and those positions were chosen inside the metric frame of the
point map MoGe-2 produced from the original photograph. So this compares MoGe against MoGe: it
measures how consistently the model reproduces its own scale when re-run on renders of its own
output, not how close that scale is to the world. Nothing here measures a metre. That makes the
result below worse news rather than better, because a self-consistency check is the easiest test
available and it was failed by 9 to 18 percent.

| MoGe field of view | Estimate, median of image medians | Error | Spread across images (median absolute deviation) |
| --- | --- | --- | --- |
| MoGe's own estimate (35.4 to 44.3 degrees against a true 50) | 0.280 m per unit | 9.0 percent high | 0.009 |
| True field of view supplied | 0.210 m per unit | 18.1 percent low | 0.006 |

The field-of-view error dominates the scale error, and forcing the true field of view made the
scale worse, not better, on this input.

The per-image spread is small by median absolute deviation, about 3 percent in both cases, **and
the distribution is bimodal rather than tight**: with the true field of view supplied, five of the
eight views sit between 0.204 and 0.214 and three sit between 0.245 and 0.251. A spread gate would
have passed an estimate that was 9 to 18 percent wrong, which is the point. **Agreement between
views is precision, not accuracy.**

**On renders only, against a reference derived from the same model.** This is the single datapoint
on the scale producer that posed multi-view rung 3 and any rung 2 corridor would need, and it is
unfavourable enough that `shared_metric_frame` stays false until the measurement is made on
photographs against a distance somebody physically measured.

---

## 5. Reading a point map as a surface without a container change

The handoff proposed that "oriented, soft edged splats with normals" were the fix for a point map
that reads as dust, and that screen-space methods should be tried before the container is opened
for a normal attribute. Measured in the app preview against the committed courtyard map, at three
fixed cameras, on the WebGL2 point-sprite path (full patch and 83 screenshots in the session
record; the harness and cameras are reproducible from the patch).

Four findings that correct the premise:

1. The shipped sprite is already a soft disc, not a square.
2. The image grid the silhouette drop destroys is recoverable exactly, without a spatial hash, by
   reprojecting every point through the header's own pinhole: 0 collisions and 0 out-of-grid on
   190,570 points, in 28 to 50 ms at load (about 0.2 us per point). This holds for single-view maps.
3. A normal is the wrong quantity. What closes a grazing surface is the anisotropic tangent frame
   (two half-extents to the row and column neighbours). Normal-only variants measured worse than
   the shipped disc at every camera.
4. A point sprite can carry an oriented ellipse without rotating: the sprite is the ellipse's
   bounding box and the fragment stage solves the ellipse.

At the grazing camera 0.3 m above the pavement (band of the near pavement, share of pixels showing
the clear colour):

| Variant | Near-pavement holes | Frame time, mean | Reads as |
| --- | --- | --- | --- |
| Shipped soft disc, 10 px cap | 50.4 percent | 2.13 ms | separate discs in a half-tone, not a surface |
| Disc, 24 px cap | 1.5 percent | 2.35 ms | covered by big round blobs, smeared |
| Facing-scaled disc (normal only) | 88.0 percent | 2.17 ms | nearly empty pavement |
| Tangent-frame ellipse at 2.0x, 40 px cap | 0.0 percent | 2.23 ms | continuous, correctly foreshortened; thin structures streak |
| Instanced quad, tangent ellipse 2.0x, no cap | 0.0 percent | 3.94 ms | pixel-identical to the sprite |

Frame times are from the PlayCanvas debug build and are relative. The instanced-quad path draws the
identical picture at 35 to 60 percent higher vertex cost and is what WebGPU would need, since WGSL
cannot set a point size. Remaining defects of the best variant, honestly: one-sided frames at
dropped silhouettes fringe the person and streak at the map's edge (201 of 190,570 points have a
frame on one axis only and 36 have none, while a separate outlier clamp touched 2.7 percent of
half-extents; the two numbers measure different things and should not be substituted); thin
structures such as spokes get frames that span the wall behind them; the 2.0x extent softens walls.

Consequence for the container: normals do not need to be in the file, and normals alone would
not have helped. The one thing a producer could supply that load-time estimation cannot recover
is the tangent frame at the cells whose neighbour the silhouette test dropped, computed before the
drop, or a per-point one-sided mark. That is the only per-point attribute this measurement
justifies, and it is not a normal.

---

## 5.1 What OPM/2 costs, and what its one-sided flag actually marks

**MEASURED 2026-09-03**, on the same photograph, by regenerating it through the current depth
stage under the new container. Harness: a standalone script in the same spirit as the ones above,
run once and not committed; every number below is reproducible from the committed writer plus the
photograph. The run reproduced section 1 exactly, which is the check that says the container
change moved nothing else: 190,570 points, a 3.04 percent silhouette drop, mean support 0.733 and
a 1.43 cm median sample spacing, all identical.

ADR-0010 asks for both of these numbers under "what must be measured before this is final".

### The byte cost, on a real map rather than in arithmetic

| Quantity | OPM/1 | OPM/2 |
| --- | --- | --- |
| File | 3,431,492 bytes | 3,812,696 bytes |
| Payload at 190,570 points | 3,430,260 bytes | 3,811,400 bytes |
| Stride | 18 bytes a point | 20 bytes a point |
| The segment channel | 381,140 bytes | 762,280 bytes as `tags` |
| JSON header | 1,133 bytes | 1,191 bytes |
| Header region, prefix and padding included | 1,232 bytes | 1,296 bytes |

**+381,140 bytes, or 11.11 percent per region at an unchanged point count.** The whole of it is
the tags section's second uint16 channel. The JSON header grew by 58 bytes for `modelImage`, the
`colorAlpha` value and the renamed section, and the reserved region it sits in by 64; that is
0.002 percent of the file and is noise beside the channel.

Read that against what it replaces rather than against zero. The WebGPU binding was allocating a
20-byte-per-point buffer anyway and filling the extra 2 bytes with a per-point CPU loop over every
point of every cloud, so on that path the change costs 11.11 percent of transfer and disk to
remove a pass over 190,570 points at load. On WebGL2 it is 11.11 percent for a flags channel
nothing renders yet. **At 512 px a photograph is 3.8 MB rather than 3.4 MB, and a thousand-region
library is 3.8 GB rather than 3.4 GB.** That is the number to weigh, and it is the reason
`max_edge_px` is a stage parameter: the same decision at 1024 px is four times the figure either
way.

### Bit 0 marks 2.07 percent of points, not a tenth of a percent

| Quantity | Points | Share |
| --- | --- | --- |
| Dropped by the silhouette test | 5,973 | 3.04 percent of the model grid |
| Survivors carrying bit 0 | 3,943 | **2.07 percent of the file** |
| Points with a tangent frame on one axis only (section 5) | 201 | 0.105 percent of the file |
| Points with no tangent frame at all (section 5) | 36 | 0.019 percent of the file |

**ADR-0010 D4 says the flag "addresses about a tenth of a percent of points", and that sentence
is comparing two different populations.** The tenth of a percent is section 5's count of points
whose load-time tangent frame came out degenerate on an axis. Bit 0, as the record defines it,
marks a point that lost ANY of its four neighbours to the drop, and that is a twentyfold larger
set: a point can lose its left neighbour and still be framed from its right one.

Both numbers are correct and neither is the other. Which one matters depends on what a renderer
does with the flag, and that is unmeasured: if the treatment is "estimate this frame differently",
the population is the 201; if it is "do not stretch a frame across a rim that was removed", it is
the 3,943. **The flag as specified is the coarser signal**, and the finer one is recoverable from
it at load, because a point marked on both row neighbours is exactly the degenerate case. So
nothing is lost by the coarse flag and the record's cost/benefit sentence understates the marked
population by twenty times.

What is still unmeasured is the thing D4 itself names: whether consuming bit 0 removes the
silhouette fringing, "by rendering with and without it and looking". Nothing consumes it yet.

---

## 6. Environment

- The reconstruction extra could not be installed on macOS from `uv.lock` because the lock pinned
  `torch 2.13.0+cu130` with no darwin wheel. Root cause, reproduced with uv 0.12.5: the pinned MoGe
  commit's own `pyproject.toml` declares the PyTorch cu130 index and torch sources, and uv applied
  them to the root resolution although nothing in this repository named that index; MoGe's
  `environments` restriction is root-only and was not inherited. The fix (explicit CPU and cu130
  indexes forked on platform, `required-environments` for darwin arm64 and linux x86_64, and a
  `dependency-metadata` override listing the six packages MoGe actually imports) produces one lock
  that installs on both platforms with every package outside the extra byte-identical. Verified by
  a real sync into a fresh venv, the reconstruction tests, ruff, lint-imports, the Dockerfile's
  older uv 0.9.5 accepting the lock, and three byte-identical MoGe runs on the courtyard.
- MoGe-2 imports torch, numpy, cv2, scipy, huggingface_hub and utils3d_moge and nothing else outside
  the standard library, traced through `sys.modules` on 2026-09-03. The `moge.py` docstring's list
  of four is short by scipy and huggingface_hub.
- A `torch 2.14.0` wheel for `macosx_14_0_arm64` exists on PyPI and reports MPS available on this
  machine.

---

## 7. What was not measured, and why

- **Multi-view coverage on photographs.** No two fixture photographs overlap and no consented
  multi-view capture exists locally, so every multi-view number above is on renders of one map.
- **Any feed-forward multi-view model on this machine.** The one license-clean candidate,
  `facebook/map-anything-apache` (Apache-2.0 code and weights, an MPS path merged upstream on
  2026-03-23, 4.9 GB of weights), was not downloaded; its peak memory on 18 GiB is unknown.
- **Splat training anywhere.** gsplat remains CUDA-only and non-resumable (verified 2026-09-02);
  no GPU job has ever run on the platform. The nearest sourced timing is 19.39 minutes for a
  30k-iteration Mip-NeRF 360 scene on an A100, which at the sourced Nebius L40S preset price of
  $1.548 per hour on demand would be about $0.50 per scene if an L40S matched an A100, which is
  unmeasured.
- **The fraction of places in a personal library that carry enough overlapping views for pose
  recovery.** No primary source measures it. The closest proxies are 1.6 percent registration over
  an unfiltered user-uploaded corpus (YFCC100M) and 20 to 25 percent over landmark-filtered
  collections; personal libraries have burst structure (about 6.5 near-duplicate images per
  cluster in the one published personal collection) that cuts both ways. The experiment that
  settles it is named in ADR-0008 as M5.


## 8. Retrospective masked-geometry count on the trained bowl

**MEASURED 2026-09-08, locally on the retained delivery artifact.** The read-only evaluator
`exulanica.evaluation.masked_geometry` decoded the bowl's compressed SOG delivery using the locked
`@playcanvas/splat-transform` 3.3.3 CPU path and called the existing masked-geometry counter. This
measures quantized delivery coordinates, not the original training PLY, which is not retained.

| Quantity | Observed |
| --- | ---: |
| Actual decoded Gaussians | 1,000,000 |
| Recovered cameras evaluated | 51 |
| Current recorded masked regions across those cameras | 0 |
| Current recorded confirmed regions across those cameras | 0 |
| Gaussian/view intersections over masked regions | 0 |
| Gaussian/view intersections over confirmed regions | 0 |

The Gaussian file is parsed and validated even when no regions exist. Empty-region views skip
projection after validation; this makes a million-Gaussian retrospective check practical without
turning a corrupt file into a zero. Counts are sums across views, not unique people or unique
Gaussians across the scene. Every camera's empty region snapshot is retained explicitly.

The delivered artifact is `c37d30fa-50b7-5612-8b22-e306ec7fa5ae`, bound to SHA-256
`844678b9374043b5f7e30038741fdf733e16a3da0d79b29078dd3d0b5f28eaa7`.
The decoded PLY SHA-256 is
`266d67266ffdbe128e13a9362f88f0645496f4fb5dee18db996f5d9a3551ab92`.
The [dated measurement record](evaluation/2026-09-08-bowl-retrospective-masked-geometry.json)
binds the publication and pose receipts, prior evaluation ZIP, current
region snapshot, executed decoder source, evaluator code and predecessor record. PostgreSQL's
transaction was repeatable-read and enforced read-only; no public row or retained artifact was
changed. Reproduce against the retained local state with a new output filename:

```sh
uv run python scripts/reference_instance.py evaluate-geometry --scene bowl \
  --artifact c37d30fa-50b7-5612-8b22-e306ec7fa5ae \
  --predecessor docs/evaluation/2026-09-05-person-consent-first-pass.json \
  --out <new-observation.json>
```

This is a new retrospective evaluation bundle containing `masked_geometry`; it does not rewrite
the old training ZIP. The production trainer has no current region/consent snapshot input, so it
cannot truthfully manufacture this count itself. The seven-component corpus `SCORED` registry is
unchanged. Historical training masks are unavailable. Non-pinhole cameras use an explicitly
labelled pinhole approximation with a 20,000 ppm margin; the margin is not proof of conservative
distortion inversion.

**Zero over zero recorded regions does not establish privacy or masking effectiveness.** No real
photograph screening, COLMAP run, CUDA training or hosted model ran in this follow-up. The fact
that this bowl was trained earlier comes from retained receipts/logs; the decoded geometry and
current empty-region count were executed here. The volcanic point-map scene was not retrained.

Verification includes a nonempty region regression, refusal of nonfinite opacity even with empty
regions, and exact predecessor/blob integrity checks. An isolated 23-test baseline passed before
three exactly-one-occurrence mutations: dropping masked intersections, bypassing empty-region
PLY validation, and omitting the bundle's count. Each mutation failed its named test. These
controls demonstrate test sensitivity; they do not substitute for a masked real-person scene.
Their [digest-bound result](evaluation/2026-09-08-gpu-geometry-negative-controls.json) follows
the bowl measurement record and binds each baseline and mutation log.
