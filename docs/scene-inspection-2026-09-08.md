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
