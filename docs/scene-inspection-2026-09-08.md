# Scene to browser inspection, 2026-09-08

Executed on 2026-09-08 in the worktree `exulanica-scene-inspection`, branch `codex/scene-inspection`,
from `5675b33`. No retained row was written, no blob was written, no card was rented and no model
was called.

This record answers the "Immediate scene and infrastructure exit" instruction in
[product-direction.md](product-direction.md): inspect the previously trained Gaussian output in the
actual application, and say which stage limits it.

## What was run

| Step | Result |
| --- | --- |
| Isolated migrated copy `exulanica_inspect_test` built from `exulanica_spine_test` | 89 base tables, 15,906 rows, per-table counts identical to the source |
| `uv run exulanica-db` against the copy | `applied 0039`, `applied 0040`, `applied 0041`, roles re-provisioned |
| Reference API against the copy | `/readyz` `ready: true`, `schema.ok: true`, `/graph` HTTP 200, 22,832 bytes |
| Bowl opened at `http://127.0.0.1:5180/` | App mounts and draws. The reconstruction does not. |

The retained database was left at 0038 and still has no `asset_artifact_live`. The blob store was
read only: 1056 files before and after, manifest digest
`de34f444fa3d52e1e8ac132c518f1c6a9828a82b006a1108ce23205a36ae784f` unchanged.

## The migration rehearsal, and what it actually establishes

This is rehearsal evidence for a later activation decision. It is not activation, and it does not
authorize one.

0039, 0040 and 0041 apply cleanly over real retained rows. Nothing errored, no retained row was
altered by them, and the recorded checksums match the committed files byte for byte:

```
0039 59df2d65d5d3566dbe475272dd9e22e57f46397d2f1529ca63beb4dad062b987
0040 94f4b8a841c6243f44b7fac416262b6eb34fa3270c39a2f5322fff169af5a663
0041 f9ef0957e60056923a604b4a8a66d4a5f6c34a8fb9dca01d764d83e2e4646d9d
```

The only data changes were `schema_migrations` 38 to 41 and a new empty `training_use_consent`
table.

**Applying them cleanly is not the same as the bowl opening.** It replaces one visible failure with
a quieter one. At `main` against retained, `asset_read_policy.py:123` calls a function that does not
exist, so the app says "Atlas could not open" and `/readyz` reports `schema.ok=false`. Against the
migrated copy the app opens, `/readyz` is green, `/graph` is 200, and the bowl is delivered with
`trained_geometry: null`, `rendering_substrate: source_photographs`, `displayed_rung: 4` and one
reason: "Current permission or persisted geometry lineage is unavailable."

The cause was isolated by walking `scene_allowed` against the copy. Every one of the bowl's 51
members fails `asset_point_allows`, which fails inside `asset_screening_allows`, on exactly one
condition: `s.policy_version = current_privacy_policy()`.

| policy_version | eligibility | method | rows |
| --- | --- | --- | ---: |
| `exulanica.reconstruction-privacy/v1` | eligible | human_review | 275 |
| `exulanica.reconstruction-privacy/v1` | eligible | synthetic_exemption | 8 |
| `exulanica.reconstruction-privacy/v2` | blocked | person_detection_only | 2 |

`current_privacy_policy()` has returned `v2` since 0037. `asset_screening_allows` does not exist at
0038; 0040 creates it and makes the read path require a current-policy screening. All 283 retained
screenings are v1, so after activation every one of them stops admitting geometry.

This is the documented intent, not a defect:
[screening-currency.md](screening-currency.md) opens with "Migration 0040 separates a historical
review from permission for a new geometry operation. It does not rewrite dated screenings or apply
to retained public." The consequence for the activation decision is concrete: **0039 to 0041 are
necessary but not sufficient. Without a re-screening pass under v2, activating them turns "Atlas
could not open" into "Atlas opens and shows nothing", which is a worse failure because it looks
like success.**

No re-screening was performed. `rescreen` requires a human review attestation over the actual
photographs, the retained-activation brief states that personal media must not be rebuilt or
re-screened, and attesting to a review that did not happen would falsify a privacy record.

## What the bowl looks like at HEAD, and where it fails

Screenshots at 1280x720 are under
[artifacts/2026-09-08-scene-inspection](evaluation/artifacts/2026-09-08-scene-inspection), from a
headless run and a real headed Chrome.

The app renders the authored landscape. Over it sits an explicit unavailable state, which is the
correct behaviour: a source collection panel reading "No 3D reconstruction is loaded / The landscape
is authored. Use the source inspector to view the original photographs. / 51 original photographs".
Both scene rows read "Recorded rung 3; showing rung 4 from source photographs." The proof lens
legend reports tiers `unavailable` and `photographed`; there is no reconstructed geometry for it to
tint. The source inspector opens and serves the original photographs, and states in the panel
itself: "Original photograph. Reconstructed camera inspection is unavailable for this scene."

Nothing reconstructed is fetched. The application's own `?validation=1` record reports
`loaded_trained_scene_count: 0`, `uploaded_point_count: 0` and `authenticated_network_bytes: 0`.

The requested traversal through the first, central and last recovered cameras plus one adjacent
midpoint **could not be performed**. The same gate that withholds `trained_geometry` also nulls
`placement` and `recovered_camera` on every member, so the payload delivers zero recovered cameras
for either scene and the reconstruction inspector has nothing to step through. Recovered cameras
exist in the copy's rows; they are withheld at the read boundary.

### Measured frame timing

Sixty seconds standing still after arrival, then sixty seconds of traversal, sampled every five
seconds, plus the application's own sixty-second `?validation=1` measurement.

| | headed Chrome | headless Chrome |
| --- | ---: | ---: |
| First meaningful render | 23,265.7 ms | 23,968.7 ms |
| Frames measured | 7,201 | 3,601 |
| Frame p50 / p95 / p99 | 8.3 / 9.7 / 10.3 ms | 16.7 / 16.7 / 16.8 ms |
| Frames over 16.7 ms | 0 | 949 |
| 1% low FPS | 97.09 | 59.52 |
| Console errors | none | none |

The 23 second first render is a cold Vite dev server compiling on first request, not scene cost.

## The stub finding

The trained scene did not stop being drawn during idle or traversal, because it was never drawn.
Frame p95 stayed between 9.6 and 9.9 ms across all 120 seconds, far under the 20.83 ms overload
threshold, so `RepresentationPressureController` never left level 0 and the residency ceiling never
moved. **The live browser could neither reproduce nor refute the regression here: with no geometry
to draw there is no frame cost, so there is no pressure.**

The defect itself is independently established and is not in doubt:

- `docs/evaluation/2026-09-06-phase-10-atlas.json` records it as a limitation and states that
  nothing in that work fixed it.
- `scripts/capture_atlas_evidence.mjs` carries it in its own header as measured on 2026-09-06 and
  reproduced on the unmodified tree at HEAD `104e415`, and works around it by taking the world-view
  pair inside a thirteen second window.
- `docs/phase-10-tickets.md:449-454` records the same thirteen seconds.

The mechanism, read at HEAD:

1. `performance-pressure.ts:79-91` promotes a level after two overloaded sixty-frame windows, so
   level 3 needs six of them: 360 frames, about eleven to thirteen seconds at 30 ms frames. At
   level 3, `maxStage` is `stub` and `budgetScale` is 0.22.
2. `residency.ts:173` clamps every demanded region with
   `Math.min(stageRank(desired), stageRank(maxStage))`. At `stub` that is rank 0, so the descent
   loop at 174-180 never executes and every demanded region is granted `stub`, including the one
   the visitor is standing in, whose demand carries the highest non-pinned priority.
3. A second, independent clamp: a trained region costs a flat 24 at every drawn stage
   (`atlas-binding.ts:541-549`), while the level-3 budget is 96 x 0.22 = 21.12. Removing only the
   stage ceiling would still stub it.
4. `atlas-binding.ts:343-344` disables a trained entity whenever its region is at `stub` and it is
   not the inspected region, so the world empties.
5. `main.ts:1855-1857` builds status rows from constructed entities and never consults
   `entity.enabled`, so the panel keeps claiming the trained reconstruction is being shown.

Residency had no notion of the region the visitor occupies at all. The signal already existed:
`classifySpatialPhase(...).islandId` is computed at `atlas-binding.ts:1359`, twenty-five lines above
the plan call, and was simply never passed in.

### The fix

A ceiling bounds what may be **loaded** next. The region under the visitor is already loaded, so
releasing it saves nothing that is still being paid for and empties the world instead.

- `residency.ts` gains `ResidencyDemand.occupied` and `ResidencyView.occupied`.
  `residencyDemandsForView` marks the occupied region, adds it if the active neighbourhood omits it,
  and preserves the mark through the navigation pin's replacement; `combineDemands` merges it the
  way it already merges `pin`. `planResidency` skips the `maxStage` clamp for that one demand and,
  if the scaled budget cannot afford even its cheapest drawn stage, grants that stage anyway.
- `atlas-binding.ts` gains `residencyFrameInputs`, which carries the occupied region into the view
  **and into the replan signature**. Without the signature change, crossing a region boundary inside
  one neighbourhood at unchanged tiers would never revisit the plan that stubbed the region.
- `TRAINED_REGION_RESIDENCY_COST` is named rather than inlined, so tests bind the real number.

Every other region keeps staging down: the saving still comes from the halo and from regions the
visitor has left, and a region whose tier genuinely asks for `stub` still gets `stub`.

Focused tests fail on the unfixed tree and pass on the fixed one:
`web/packages/atlas-core/test/residency-occupied-region.test.ts` and
`web/packages/atlas-react/test/residency-occupancy.test.ts`, 11 of 13 failing before, 13 of 13
passing after.

## Stage diagnosis for a place

The bowl is an object scan: 51 photographs of a food bowl on a table, circled by hand. The volcanic
sample is 210 photographs of a rock. [product-direction.md](product-direction.md) already says it:
"A small object scan is a pipeline check, not proof of a reconstructed place." The volcanic set
failed coverage.

| Stage | What the retained runs prove | What is unproven for a room or an outdoor place |
| --- | --- | --- |
| Source coverage | Admission plumbing works end to end: 51/51 and 210/210 captures each carry an authorization and a screening receipt, from one named reviewer on 2026-09-05. | Nothing. No room or outdoor capture exists in the corpus at all; the corpus contract's own discovery found no dense people-free room capture. An object turntable has no occlusion, no doorways, no windows blowing out exposure, and no bystanders. All 283 screenings are policy v1, so the privacy chain has never actually admitted these bytes under the policy now in force. |
| Camera registration | The strongest retained result. 51/51 and 210/210 registered. Reprojection through the recovered camera: median 2.83 px, p95 6.73 px, max 9.88 px on 3060x4080. Cost measured: 3 to 4 min for 51 at 12 MP on 12 cores, about 45 min for 210. | Object scans are the easy case: one convex subject, dense parallax, every frame seeing the same thing. A room adds textureless walls, repeated fixtures that alias, and loop closure over a walked path. The real run already showed the fragility: two fully registered bowl captures were refused by a 9.0 normalized translation floor at 8.13 and 8.96 units, and the floor had to drop to 5.0. The only camera-accuracy ground truth in the repository is ETH3D pipes, 14 indoor images. Exhaustive matching is quadratic and is the stated bottleneck at 210. |
| Training | One accepted run: 30,000 iterations in 4,455.7 s (74.3 min) alone on an L40S for $1.312, held-out PSNR 25.2784 dB, SSIM 0.8959, LPIPS 0.3091, coverage 0.9831 over 7 views. Peak VRAM about 8.8 GB. | Held-out scores are appearance-only; pose and geometry condition on every registered image. A bowl fills the frame from every angle; a room has view-dependent windows, large low-parallax surfaces and a sky. The volcanic failure is the direct warning: coverage 0.730 then 0.629 against a predeclared 0.75, because the rock was turned over between series and shot against two different backdrops, so no single background could be learned. Per-view PSNR split bimodally, 23 to 29 dB on dark-backdrop views against 7 to 12 dB on white ones. That is a capture-protocol failure that a room reproduces easily by changing the lighting mid-session. The same turning-over destroyed the gravity axis: mean camera up length 0.337, 41% of cameras opposing the best common axis. |
| Conversion | SOG conversion of one million degree-3 Gaussians: three hours on one CPU core without finishing, 10.8 s on the L40S. Output 15,337,279 bytes with every SH band, artifact `c37d30fa`, SHA-256 `844678b9...`. | Only one asset at one scale has been converted. A room-sized model will hold more Gaussians over a larger volume; neither the conversion time nor the delivered size has been measured past one million splats, and no budget for a browser-deliverable size has been set. |
| Publication | The trained artifact reached a published scene bound to a pose receipt, a gate artifact and a placement artifact, and the bowl is presented at 0.352x nonmetric exhibit scale. | Scale is not metric. A place has to be walkable at human scale, and nothing has established a metric scale receipt: the retained scene's own recorded reasons are "no physically validated scale receipt", "no measured coverage receipt", "no measured corridor receipt". Placement is `unavailable`. |
| Delivery | Measured once, before 0040: 1,000,000 Gaussians plus 50 point maps, 9,757,711 points, 210,557,883 authenticated bytes, first meaningful render 24,386.8 ms. | **Delivery is the stage that is broken today**, and it is a permission failure, not a bandwidth one. At HEAD nothing is delivered: 0 trained scenes, 0 points, 0 authenticated bytes. The read guard withholds geometry, placement and recovered cameras together. This must be resolved before any statement about a place's delivery can be made. |
| Rendering | The renderer drew the bowl at 16.98 ms mean, 33.3 ms p99, 30.03 fps 1% low over 60 s. Volcanic point maps, 19,493,182 points, drew at 53.02 ms mean and 6 fps 1% low. | 33.3 ms p99 on a single object scan is already past the 20.83 ms overload threshold, which is exactly what drove the pressure controller to level 3 and stubbed the region. A room is larger than a bowl. The occupancy fix in this branch stops the visitor's own region being released, but it does not make a room affordable: the trained cost model is flat and all-or-nothing (24 at proxy, coarse and full), so there is no genuine level of detail for trained geometry yet. That is the next rendering problem, and it is unmeasured. |

**The limiting stage today is delivery.** Every stage upstream of it has a measured, accepted result
for one object. Nothing downstream can be judged until a current-policy screening exists.

## One capture pattern for a first place

One room, one continuous session, nothing moved and no lighting changed between frames. The
volcanic failure is the reason that sentence is first: a changing backdrop is not static scene
content, and the model cannot learn two of them.

- **192 photographs at 12 MP.** Two closed loops of the room perimeter at camera heights of about
  1.5 m and about 1.1 m. Walk each loop in one direction, stopping about every 0.5 m for three
  frames: one to the forward left, one forward, one to the forward right. That is about 32 stations
  and 96 frames per loop.
- **Overlap.** Consecutive frames along the walk should share at least 70% of their view, and each
  loop must close by re-shooting its first station last, so registration has a loop constraint
  rather than an open path that drifts.
- **Held out every eighth by lexicographic index**, matching the existing convention: 168 training
  and 24 held out. Because the held-out frames are drawn from the same walk, they measure appearance
  only, exactly as the bowl's did. Say so in the record rather than calling them generalization.
- **Fixed exposure, fixed white balance, fixed focal length.** Do not chase a window. If the room
  has a bright window, either shoot it consistently in every pass or exclude that wall and record
  the exclusion.
- Declare thresholds before the run, as the retained requests did, and expect coverage to be the one
  that bites.

192 keeps exhaustive matching affordable. Fitting the two measured points, 51 photographs in about
3.5 min and 210 in about 45 min, a quadratic gives 38 to 50 min for 192, so it stays inside the
observed envelope without needing the sequential or vocabulary-tree matcher that has not been built.

## Compute plan inside the observed balance

Rented nothing. The billing page read **$40.70** on 2026-09-08 at 11:09 UTC and the selector quoted
a single L40S MassedCompute option at **$1.06 per hour**, 48 GB VRAM, 12 CPUs. Everything below is a
planning allowance at that quoted rate, to be re-read against the live balance before any instance
is created.

One host, held up across the whole campaign so bootstrap and pose are paid once:

| Item | Wall clock | Cost |
| --- | ---: | ---: |
| Host bootstrap, 16.9 GB base image pull, gsplat compile | 25 min | $0.44 |
| Scene worker image build and push | 2 min | $0.04 |
| COLMAP pose, 192 photographs at 12 MP, CPU only | 60 min budgeted | $1.06 |
| Gaussian training, 30,000 iterations, three attempts | 3 x 90 min | $4.77 |
| SOG conversion on the card, three times | 3 x 5 min | $0.27 |
| Operator inspection between attempts | 3 x 30 min | $1.59 |
| **Campaign total** | **about 7.7 h** | **$8.17** |

Three training attempts are budgeted because the retained history needed four bowl requests before
one was accepted and refused both volcanic runs. Decoded images for 192 frames at 12 MP are about
7 GB, inside the 16 GiB `DecodedImages` budget, so training should stay GPU bound rather than
falling back to the 24% utilization measured before that cache existed.

Image registry time is budgeted at the full measured 25 minute pull. The private GitHub Container
Registry option would reduce it, but the saving is unmeasured and a prebuilt image still transfers
its layers. The separately proposed registry measurement allowance is **$3.18**, three billed
instance-hours across two hosts, and it needs `write:packages` credentials that the existing GitHub
CLI credential does not advertise.

Campaign plus registry measurement is **$11.35** against $40.70, leaving **$29.35**. Set a hard stop
budget of $12. Read the actual balance and rate before each instance, record provider start and
delete timestamps, image digests and before/after billing values, and do not substitute training
receipts for the bill.

## Limitations

- The `--schema=public` dump omits `CREATE EXTENSION`, so `pgcrypto`, `vector`, `btree_gist` and
  `pg_trgm` had to be created in the copy before the restore. Without that the restore drops 12
  tables and 159 statements fail. The copy was then verified table by table against the source.
- No re-screening was performed, so the bowl was never seen rendered at HEAD. Everything in "The
  stub finding" about the trained scene rests on the retained phase-10 measurement and on focused
  tests, not on a live sighting in this branch.
- The traversal through recovered cameras, the reconstruction inspector and click-to-evidence could
  not be exercised, because the read guard delivers no recovered cameras.
- Pointer lock did not engage under CDP-dispatched input, so the traversal moved the camera through
  key events without lock. The frame timing is still real; the path walked is not a considered tour.
- The rendering row of the stage table is the weakest. A trained region's residency cost is flat
  across proxy, coarse and full, so there is no level of detail for trained geometry. The occupancy
  fix keeps the visitor's region drawn; it does not make a larger place affordable.

# 2026-09-09: the volcanic scene, rendered

Executed 2026-09-09 in the same worktree, on `codex/scene-inspection` at `4ec6ead`. No retained row
was written, no blob was written, no worker was run, no card was rented and no model was called.
The retained database is still at 0038.

Since the section above, the orchestrator worked on `exulanica_inspect_test` only. The bowl was not
re-screened: photographs 33, 34, 35 and 43 to 51 show a partial person, so the September 5
"no visible people" attestation would be false for them, and the bowl's trained artifact stays
withheld. The volcanic set was re-screened under policy v2 through the ordinary reference admit
workflow, its 210 point maps were re-derived under v2, and a pose-only exact scene job was queued
and run with local pycolmap. Scene `45ad50b7-aea4-52b4-b6f4-2811b93deb88` is now delivered as
`posed_point_maps` with 210 registered and placed members and 210 recovered cameras, at rung 3.

## What was run

The API and the volcanic web instance were not running when this work started, so both were started
against the copy through the `EXULANICA_REFERENCE_DATABASE_URL` override. They were SIGTERMed twice
between tool calls and had to be restarted, so the later runs start their own pair and stop it again.

`scripts/capture_atlas_evidence.mjs` still cannot drive this scene. Its rung selector at line 191
requires a status summary containing `trained Gaussian`, and `status.ts:193-195` words a
`posed_point_maps` scene as `posed point maps`. The script therefore captured the proof lens triple
and then timed out waiting for an inspector that was never opened. Those three frames are retained
under `artifacts/2026-09-09-scene-inspection-rendered/capture-atlas-evidence`. Everything after that
point was driven by a separate driver, headed and headless, at 1280 by 720.

## What the volcanic scene looks like

**Delivery is proven for point maps at HEAD.** Both runs report 210 placed and 210 uploaded point
maps, 19,493,182 points and 390,141,944 authenticated bytes, no console errors, and no loader
issues. The status row reads "Recorded rung 3; showing rung 3 from posed point maps" and the proof
lens colours the whole region `reconstructed`.

Arrival puts the camera inside the cloud rather than in front of it. A large smooth blue-grey plane
fills the lower right, pale ribbed sheets cross the upper half, dark grey streaks run in from the
upper left, and a small warm tan cluster sits near the top edge. It reads as being inside a stack of
shells, not as standing in a place.

From the recovered cameras the subject is clear, and so is the problem. **The reconstruction is
mostly backdrop.** From Source camera 1 the frame is dominated by a pale grey sheet, with the rock
present only as a small dark reddish-brown cluster low and left of centre and a darker mass at the
upper right. From Source camera 106 the sheet fills almost the entire frame and the rock is hard to
pick out at all. From Source camera 210 the view is a dense grey speckle with no clear subject.
This is the turned-over, two-backdrop capture showing up as geometry: the two backdrops were
reconstructed as scene content, they occupy most of the points, and they are what the visitor
mostly sees.

Three artifacts are visible in every camera view:

- **Corrugation.** The backdrop, which was a flat surface, is reconstructed as regular parallel
  ridges. It is a systematic depth artifact over a low-texture white surface, not a property of
  anything that was photographed.
- **Holes and shells.** The cloud is a set of disconnected sheets with white gaps between them
  rather than one closed surface. At arrival the gaps are wide enough to see straight through.
- **Aliasing.** At the last camera the point size and spacing beat against the screen grid into a
  moire, which is a rendering artifact of drawing 19.5 million discs, not of the reconstruction.

The app says the rest itself. `geometry-api.ts:136` renders the gravity failure into the status
line: "its recovered cameras do not agree on an up direction, so no upright is claimed." The
inspector header says "Camera inspection · fitted relative scale · physical scale unverified. These
views do not establish a walkable surface."

## Traversal, the midpoint, and click to evidence

The inspector offers 419 views for this scene: 210 recovered source cameras interleaved with 209
interpolated midpoints. The traversal held fifteen seconds at each of Source camera 1, Source
camera 106, Between cameras 106 and 107, and Source camera 210, for sixty seconds in total.

The interpolated midpoint is the honest one. It labels itself "Midpoint between consecutive
recovered cameras. This is an unobserved viewpoint, not measured geometry or a validated route",
and when asked for evidence it refuses rather than approximating: "This is a midpoint between two
photographs. No camera stood here, so there is no calibrated projection to invert. Choose either
adjacent source camera."

**Click to evidence does not work on this scene.** The observation graph never loads. Across 56
clicks in each run the evidence panel only ever reported `loading` or `failed`, with the failure
text "Unexpected end of JSON input". `observations-api.ts:15-26` explains why this is structural
rather than a transient: the inspector requires the whole graph in a single response, because a page
"would silently make clicks miss recorded evidence", and the bowl's whole graph is already a
measured 97,633,587 canonical bytes for 15,005 points and 71,214 observations. This scene has
111,694 points and 860,160 observations, and its pose receipt artifact alone is 108,267,697 bytes.
The response is large enough that the browser aborts mid-parse. I did not fetch the endpoint
directly to size the response, because building it could exhaust an 18 GB machine that had already
swapped once that day.

## Frame timing

Sixty seconds idle after arrival, then the sixty second camera traversal, with the application's own
`?validation=1` measurement over sixty seconds.

| | headed Chrome | headless Chrome |
| --- | ---: | ---: |
| Mount, including the graph read | 54,948 ms | 57,217 ms |
| First meaningful render | 54,796.2 ms | 57,037.9 ms |
| Geometry load | 4,518.4 ms | 4,130.2 ms |
| Frames measured | 515 | 477 |
| Frame p50 / p95 / p99 | 9.5 / 350 / 366.8 ms | 16.8 / 350 / 366.8 ms |
| Frames over 16.7 ms | 241 | 287 |
| 1% low FPS | 2.73 | 2.73 |
| Peak JS heap | 414.82 MB | 413.58 MB |
| Console errors | none | none |

Both machines drew the same scene at a 1% low of 2.73 fps. The earlier retained measurement of the
same 210 point maps recorded 53.02 ms mean and a 6 fps 1% low on a quieter machine; a Companion task
was running here throughout, and that difference is not attributable to anything in this branch.

## The stub result

`9c01b32` was reverted in the working tree and the idle hold was repeated headed, with the inspector
closed, because inspection bypasses residency and would mask the effect. Four runs were made on the
unfixed tree and one on the restored tree. Drawing was measured as a texture fraction over a fixed
canvas box, calibrated on captures already taken: 0.063 with no reconstruction drawn, which is the
withheld bowl from the day before, and 0.105 to 0.116 with the volcanic point maps drawn.

| Run | Tree | Point maps loaded | Idle | rAF frames | 60-frame windows | Texture min to max |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `unfixed` | reverted | 210 | 120 s | 129 | 2 | flat |
| `unfixed-long` | reverted | 210 | 600 s | 3,440 | 57 | two transient near-flat frames at 25 s and 40 s |
| `unfixed-dense` | reverted | **0** | 420 s | 2,516 | 41 | 0.058 to 0.063, geometry never loaded |
| `unfixed-1` | reverted | 210 | 300 s | 1,662 | 27 | 0.1065 to 0.1066 |
| `fixed-1` | restored | 210 | 300 s | 1,405 | 23 | 0.1065 to 0.1066 |

**The regression did not reproduce with real geometry drawn.** On the unfixed tree, with 210 point
maps loaded and 27 sixty-frame windows elapsed against the six needed to reach level 3, the scene
kept drawing for the whole five minutes, and the restored tree is indistinguishable from it. The
`unfixed-dense` run is excluded: its geometry never loaded, so it says nothing about residency.

The most likely reason, which I did not confirm, is frame rate. The controller counts frames, not
seconds. The phase-10 bowl ran at roughly 33 fps, so the six windows that reach level 3 elapsed in
about thirteen seconds and the level held. Here the same scene runs at a 1% low of 2.73 fps with p95
frame times of 2.2 to 2.5 seconds, so the six windows take minutes, and each stub is followed by a
fast recovery, because five healthy windows at a high frame rate pass quickly. The two transient
near-flat frames in the 600 second run are consistent with exactly that oscillation, but they were
measured with an earlier camera-dependent metric and were not photographed, so they are not claimed
as the regression.

The fix is kept, on the strength of the phase-10 record and of the focused tests that fail on the
unfixed tree and pass on the fixed one. Nothing measured here argues against it, and the planner
change it makes is still the correct semantics: a ceiling on what may be loaded is not a reason to
release what is under the visitor.

## The graph read, measured but not fixed

`GET /graph` for the volcanic workspace was timed three times: **48,013 ms, 51,066 ms and 50,622 ms**
for a 320,775 byte response. The dominant cost is not the 0041 asset-read guard.

| Component | Time |
| --- | ---: |
| `read_snapshot` | 54,033 ms |
| `scene_inputs`, buffering the pose manifest | 1,232 ms |
| `scene_allowed` pass 1 | 124 ms |
| `scene_allowed` pass 2 under `final_check` | 128 ms |
| `asset_point_allows`, 210 calls | 132 ms |
| `asset_screening_allows`, 210 calls | 77 ms |
| `privacy_inputs_at`, 210 calls | 17 ms |
| `asset_capture_live`, 210 calls | 16 ms |
| `asset_artifact_live`, 3 calls | 1 ms |

The whole asset-read policy, both passes included, is about 252 ms of a 50 second request, and every
per-member predicate together is 242 ms. **No predicate is slow and no index is missing.**

A profile of the route body names the cost exactly. `read_snapshot` calls
`reconstruction_scene_rows` calls `_scene_row` calls `validate_placement_record` calls
`build_placement_record`, which runs `fit_point_map_scale` 210 times and `validate_opm` 210 times.
Under the profiler those are 78.2 s and 41.9 s cumulative, at 0.372 s and 0.199 s per call. The
work is a pure-Python walk of all 19,493,182 points: 19.5 million `all()` calls and 78 million
generator evaluations at `validation.py:268`, plus 60.9 million `min` and 58.5 million `max` calls.

A control confirms it. The bowl workspace, whose geometry is withheld entirely, still takes
**21,683 ms, 21,495 ms and 21,444 ms** for a 22,832 byte response over its 91 members. That is
0.238 s per member against the volcanic scene's 0.241 s per member. The cost tracks member count and
nothing else, and it is paid even when the answer is then stripped.

### Proposed backend follow-up

Not made here; every file involved is read-only for this branch.

1. **Memoise the validated placement record.** `build_placement_record` and `validate_opm` are pure
   functions of immutable, content-addressed bytes, and the route already holds the digests that key
   them: the placement digest, the pose receipt digest, the member digest and each point map's
   content digest. A process-level cache on that key removes the whole per-member cost from every
   request after the first.
2. **Do not build what will be stripped.** `_scene_row` builds the full placement record before
   `scene_allowed` runs, so a scene whose geometry is withheld pays for placement anyway. Evaluating
   the guard first would make the bowl's 21.5 seconds nearly free today.
3. **Stop walking every point in Python.** `validate_opm`'s finiteness and bounds pass is O(points)
   per call. Over an already digest-verified container it is repeat work, and where it must run it
   belongs in a bulk operation rather than a per-point generator.

`reconstruction_scene_rows` already carries a `scene_id` filter added for the World Read API for
this exact reason; the graph snapshot passes `None` and so pays for every scene.

**No index is needed and no migration reservation is needed.** There is no slow query here: the cost
is in-process numeric work, and the digests the cache would key on already exist in the schema.
Persisting a validated-placement marker in the database would need a migration, but the cheaper fix
does not.

## Two corrections

Recorded as successor observations in
[2026-09-09-scene-inspection-rendered.json](evaluation/2026-09-09-scene-inspection-rendered.json).
Neither earlier record was edited.

1. **The September 5 bowl screening statement is inaccurate for twelve photographs.**
   `2026-09-05-real-reconstruction.json` records "I, Glendon Chin, looked at every one of the 51 bowl
   and 210 volcanic photographs and found no visible people or sensitive person regions", reviewed at
   2026-09-05T17:26:09Z. Photographs 33, 34, 35 and 43 to 51 of the bowl set show a partial person.
   The volcanic half of that statement stands. The consequence is that **the retained bowl Gaussian
   scene is not deliverable under current policy**: a v2 screening for those captures would have to
   record the regions and their masks, and no such screening exists.
2. **The measured pipeline bottleneck on this machine is feature extraction memory.** Attempt 1 of
   scene job `c62ddc8b-7ae4-51fc-acaf-ca4932251a19` began extracting at 21:08:56 and reached file
   199 of 210 at 22:13:08, 63.7 minutes later, at roughly 19 seconds per 12 megapixel image, before
   it was SIGTERMed. The orchestrator observed the process footprint growing to about 20 GB with the
   machine swapping at 17.5 of 18.4 GB. Attempt 2 resumed from the COLMAP database at 22:30:00,
   skipped the 199 already-extracted images, and extracted the remaining eleven in 0.748 minutes,
   matched in 7.416 minutes and mapped in 6.623 minutes, succeeding in 14.8 minutes total. **This
   did not appear on the rented host**, which has 70 GiB of memory and 12 vCPUs against this
   machine's 18.0 GB, and where the whole 210 photograph COLMAP run took about 45 minutes. The
   durable COLMAP database is what made the restart cheap and should be treated as a required
   property of any local run, not a convenience.

## Stage diagnosis, updated

Only the rows that changed. Everything else in the table above still holds.

- **Delivery is now proven for point maps at HEAD.** 210 placed and uploaded maps, 19,493,182 points
  and 390,141,944 authenticated bytes reach the browser through the 0041 guard and are drawn. The
  guard is satisfied by a current-policy screening, which is what the volcanic re-screening supplied.
- **Trained delivery at HEAD remains unproven**, because the only trained scene in the corpus is the
  bowl, and the bowl is withheld. Nothing here changes that, and correction 1 makes it worse rather
  than better: the withholding is now known to be correct rather than merely conservative.
- **Rendering is the next limit after delivery.** 2.73 fps on an object scan is not a place. The
  trained cost model is still flat across proxy, coarse and full, and point maps still cost enough
  that a region either fits the budget or does not.
- **Source coverage keeps its verdict, for a new reason.** The volcanic set now has 210 current-policy
  screenings, but the scene it produces is mostly backdrop. A place still requires a capture that was
  planned as a place.

## Limitations

- `capture_atlas_evidence.mjs` cannot inspect a `posed_point_maps` scene, so the inspector, camera
  traversal and click-to-evidence captures come from a separate driver. The script is read-only here
  and was not changed.
- The stub regression neither reproduced nor was refuted on the unfixed tree with real geometry. The
  frame-rate explanation above is reasoning from the controller's own window arithmetic, not a
  measurement of the pressure level, which the app does not expose.
- One unfixed run loaded no geometry at all and is excluded. Two others were lost to the API being
  SIGTERMed between tool calls. A Companion task was running on the same machine throughout, so
  every frame timing here is an upper bound.
- Click to evidence could not be exercised at all, so nothing here tests the hit and miss answers on
  this scene.
- The observation-graph response was not fetched directly and its size is inferred from the scene's
  point and observation counts and its 108,267,697 byte pose receipt.
- The graph-read profile was taken under cProfile, which roughly doubles wall time; the per-call
  figures are relative, and the unprofiled component timings above are the ones to quote.

# 2026-09-09, later: the graph read fixed

The section above measured the fifty second graph read and proposed three follow-ups without making
them, because every file involved was read-only for this branch. The owner then asked for the first
of the three. **This changes the writable set: `exulanica/graph/reconstruction_scenes.py` and
`tests/test_scene_reconstruction_pipeline.py` were edited, so the whole backend suite is a gate
here where the earlier sections did not need one.** The other two proposals were not made.

The change was then reviewed adversarially, and the first version of it was wrong in three ways.
What is described below is the reviewed version; the corrections are called out where they land,
because an earlier draft of this section asserted one thing that is simply false.

## What changed

One file, `exulanica/graph/reconstruction_scenes.py`.

`_scene_row` rebuilt every scene's placement on every request. It fetched the pose receipt and every
point map from the store, which verifies each blob's digest as it reads it, then ran
`fit_point_map_scale` once per member and `validate_opm` over every point. None of that depends on
anything mutable: the pose receipt, the placement record, the gate receipt and each point map are
content addressed, and their digests are already columns on the scene row the function has just
read.

So the rebuilt placement and the recovered cameras are now memoised, keyed on the workspace, the
scene, those four digests, the scene's member list in order, the placement's point-map references in
record order, and whether each of those point maps' bytes are present. On a hit the pose receipt and
the point maps are not fetched at all.

What is deliberately **not** memoised is everything that can change without a digest changing: the
scene's members, the person regions and review states, the artifact rows with their `purged_at` and
tombstone predicates, the gate agreement, and the asset-read policy the route applies afterwards.
Those are re-read on every request as before. Nothing privacy-bearing is cached.

The memo is guarded by a lock, because FastAPI runs a synchronous endpoint on a threadpool, and is
process-local, so it cannot go stale across a restart. `clear_placement_memo()` empties it.

**The bound is on total members, not on entries.** MEASURED 2026-09-09 on the 210 member volcanic
scene: one entry is 639.6 KiB, or 3.05 KiB per member, and holds no point-map bytes at all. The
bound is 20,000 members, about 60 MiB, which is roughly 95 scenes the size of the volcanic one.
Entry count would have been the wrong unit, and a small entry count would have been worse than
wrong: `reconstruction_scene_rows` sweeps every scene in the workspace on a graph read, so the
access pattern is a cycle, and a bound shorter than the cycle evicts each entry before it is reused
and gives a hit rate of exactly zero rather than a lower one. The first draft of this change used
sixteen entries and would have fallen off that cliff at seventeen scenes.

## What the review found, and what it changed

- **A memory safeguard that did nothing, justified by a false claim.** The first draft stripped
  `point_map_inputs` from the record before caching, on the stated grounds that
  `validate_placement_record` returns a record still holding 780 MB of point-map bytes. It does not.
  `build_placement_record` rebuilds those inputs as three positional arguments, so `content` keeps
  its `None` default and the bytes never enter the record. The stripper was a no-op, its docstring
  was false, and the test written to protect it passed identically with the function deleted. All
  three are gone. The property itself is still worth pinning, because the memo makes it
  load-bearing, so the test remains with an honest docstring and the measured 639.6 KiB behind it.
- **A purge misclassified as an inconsistent receipt chain.** Moving the pose-receipt read out of
  the first `try` and into the memo-miss branch put it under a handler that catches
  `(KeyError, TypeError, ValueError)`. `BlobNotFoundError` is a `KeyError`, so a pose receipt purged
  between the presence check and the read would have been reported as `invalid` with "The pose,
  placement and gate records do not reproduce one consistent scene", where the old code said
  `bytes_missing`. It now has its own arm. The presence check was also moved ahead of the placement
  and gate reads, so a double fault still reports what the unmemoised reader reported.
- **A repair that would never be seen.** This is the one that mattered most. `store.exists` is a
  bare `is_file()`, so "present and valid" and "present but rotted" build the same key while
  producing different correct records. A point map that was corrupt when the memo was filled would
  have left its scene degraded for the life of the process even after an operator restored the
  bytes, because restoring under content addressing leaves every key component unchanged. **A record
  built from a read that failed its digest is now never cached**, so a repair is picked up on the
  very next request.

## The trade that remains, stated exactly

Before this memo every graph read pulled each point map through `store.get`, which re-hashes the
bytes. A blob that had rotted came back as `content=None`, its member was excluded as
`alignment-unavailable`, and no fetch reference was emitted. On a memo hit the only per-request
check is `store.exists`. So a point map that was sound when the entry was filled and rots afterwards
is reported as placed and available, with a `/geometry` reference, until the entry is evicted or the
memo is cleared.

The bytes themselves are still safe: `exulanica/api/routes/geometry.py:234` reads them through the
store and refuses on `IntegrityError`, so a visitor gets a refusal rather than wrong geometry. What
is lost is that the graph used to withhold the reference rather than advertise it. A purge is still
seen, because presence is in the key. A repair is seen, because a failed-digest read is never
cached. This is the single remaining narrowing, it is pinned by a test that asserts the behaviour as
it is, and it is the thing to revisit if it is judged too expensive.

## Measured

Same isolated copy, same machine, curl wall clock, on a genuinely cold process each time. An earlier
attempt at these numbers was invalid because a stale API process was still holding port 8000 and
serving from a warm memo; the measurement script now refuses to run if the port is taken.

| | before `51f8b01` | after, cold process | after, warm |
| --- | ---: | ---: | ---: |
| Volcanic, 210 members | 48,013 / 51,066 / 50,622 ms | 47,880 ms | **2,681 / 2,599 / 2,632 ms** |
| Bowl, 91 members, geometry withheld | 21,683 / 21,495 / 21,444 ms | 21,321 ms | **322 / 319 / 338 ms** |

That is 50.6 s to 2.63 s for the volcanic scene and 21.5 s to 0.32 s for the bowl, about nineteen
and sixty-seven times. Response bytes are unchanged at 320,775 and 22,832.

In the browser, with the memo warm, **mount fell from 54,948 ms to 15,741 ms**, frame p95 from
350 ms to 132.6 ms, and the measured frame count over the same sixty seconds rose from 515 to 1,072.
All 210 point maps still load and the scene still draws. The remaining sixteen seconds is the
390,141,944 bytes of geometry the browser fetches, decodes and uploads.

### What is left, now measured rather than proposed

A profile of the **warm** route body is 2.896 s, and `scene_inputs` is 2.060 s of it across two
calls, of which `json.loads` is 1.924 s. That is the 108,267,697 byte pose receipt being read,
hashed and parsed once per scene inside `read_snapshot` through `trained_geometry_row`, and once
again by the route. It is now the whole remaining cost.

The obvious next step is to stop parsing that receipt twice per request: either memoise the parsed
pose manifest on its digest the same way, or have the route reuse what `read_snapshot` already
produced. Neither needs an index or a migration reservation, for the same reason as before: there is
no slow query here.

Proposals 2 and 3 from the section above stand unmade. Proposal 2, evaluating the guard before
building the placement, is now worth much less: the bowl's withheld scene costs 0.32 s warm.
Proposal 3, the per-point Python walk in `validate_opm`, now runs only on a cold miss, and doing it
properly wants an array library this package does not depend on.

## Gates

The backend suite was run in full before and after, on a dedicated scratch database. **60 tests fail
in both runs and the two failure sets are identical**, so this change introduces no regression and
fixes none. The pre-existing failures are concentrated in `test_world_read_views.py` (28),
`test_asset_read_currency.py` (15) and `test_gsplat_runner.py` (7); a sampled one fails in its own
fixture setup with "no such scene" and is unrelated to anything here. Both lists are retained under
`artifacts/2026-09-09-graph-read-memo`.

Seven focused tests were added to `tests/test_scene_reconstruction_pipeline.py`, where the scene
fixtures already are: the reuse itself, the absent bytes, a point map lost after a memoised read,
the pose receipt lost after a memoised read, the member bound with eviction, the corruption that the
memo does not see, and the repair that it does. On the unfixed tree the module fails to import,
because the memo does not exist. Two mutations confirm the load-bearing assertions rather than
assuming them: making `_memo_get` always miss fails the reuse test on
`assert point_digests.isdisjoint(second_store.fetched)`, and caching failed-digest reads fails the
repair test on `assert placement_memo_size() == 0`.

## Limitations

- The cold path is unchanged. A fresh process still pays 47.9 s for the volcanic scene and 21.3 s
  for the bowl on the first request. Only repeat reads are fast.
- The memo is per process. Several API workers each keep their own, and the first request to each is
  cold.
- A point map that rots after a successful read is advertised until its entry is evicted. This is
  the deliberate trade described above, and the only one left.
- 20,000 members is sized against this corpus and the deployment note of three to five scenes. It is
  not a measured ceiling for a workspace an order of magnitude larger.
- The 60 pre-existing backend failures were not investigated beyond confirming they are identical
  before and after and sampling one. They were failing at `51f8b01`.
- The browser mount figure is with the memo already warm; a first visit after a restart still waits
  for the cold read.
