# What a composed world's frame costs in draw calls, and why 179 against 87 is not a comparison

Written 2026-09-19 by the draw budget lane on `lane/draw-budget` at `0a415394`, which is local main
`0a415394`, in `/Users/glendonchin/dev/Technology/orimera-draw-budget`. Every figure below was
measured on that tree. No source file was changed to produce any of them.

The lane was asked to fix `practicalBrowserBudget`, which fails on `maxDrawCalls` 179 against a
budget of 87, on the stated cause that SETS ARE SHARED ACROSS TILES AND BATCHES ARE NOT. That cause
is exactly right about batches and the key does not count batches.

  draws in a frame = (batches the world submits, after culling) x (passes the look runs over each)
                     + the passes the look runs regardless

  THE BUDGET KNOWS ONLY THE PRODUCT. The two factors moved independently and four days apart: the
  world's batches went 14 to 56 when neighbours were drawn, and the look's multiplier went from one
  submission per batch to as many as five when `TILE_LOOK_V1` arrived, since an opaque casting batch
  is drawn once in the forward pass, once in the depth prepass and once per cascade. A budget on the
  product cannot say which moved, and re-measuring it today freezes the product at today's look, so
  the next look change breaks it again and just as silently. THE QUESTION IS WHICH QUANTITY, NOT
  WHICH NUMBER.

## The world measured here is the world the gate scored, and that is established rather than assumed

`scripts/bake_corridor_tiles.py` was run unmodified against a PostgreSQL server private to this
worktree, started by `scripts/test_postgres.py serve` and migrated through 0082, and a store
directory owned by this session. The shared store and the shared server were not touched. Five
tiles, baked twice each, `identical` on every second pass.

The four containers of the composed world reproduce the digests
`docs/evaluation/2026-09-19-corridor-composed-world-private-store.json` binds, compared by reading
both values in one command rather than by eye:

| tile | bytes | container sha256 |
| --- | ---: | --- |
| (0,0) | 2,481,768 | `21b31c9f9ab9904104a319ddee8aaa5ea87f9cb361da39a793c48a123d0dace9` |
| (1,0) | 12,294,448 | `7ef4d85c1413f4cc0e6ac289a9e23634896658d2dc8ddf322f4f890c64029507` |
| (2,0) | 12,682,860 | `ed9acb98268d80fc7b0bf856b682c95c15f59e50bf9c70aef1c2258cd713e999` |
| (3,0) | 11,630,744 | `47e6457e74812f8f84f923a222bf70966cf26b8a513ebc1e86f02233fe61818c` |

Loaded and attached, the composed triangle count is 175,034, which is the figure the earlier gate run
recorded. Same digests and same triangle count, so this is that world and not a lookalike.

**A RUN AGAINST A PRIVATE STORE IS A TRUE MEASUREMENT OF A COMPOSED WORLD AND IS NOT A MEASUREMENT
OF WHAT THE PRODUCT SERVES.** The shared store still holds tessellator 19.

## The stated cause, measured

Counted from the scene the runtime builds, not from a figure written here: every drawn surface is
batched by what it is drawn with, one batch per texture set plus one for every unavailable surface.

    batches submitted               56    which equals the mesh instances in the scene
    per tile                        14    on each of the four, identically
    distinct batch keys             14    thirteen texture sets and one unavailable-surfaces batch
    ratio                          4.0    EXACTLY the tile count
    floor if each key submits once  14

So the stated cause holds to the digit, and 56 is also the "56 meshes read" the gate's own scene
reader reports. What follows is why that does not settle the key.

## `maxDrawCalls` is the whole frame, read from the engine rather than assumed

`web/packages/app/src/browser-validation.ts` takes `binding.app.stats.drawCalls.total`. In
PlayCanvas 2.21.4 that field is assigned `device._drawCallsPerFrame` in `Stats.updateBasic`, and
`_drawCallsPerFrame` is incremented at every GL draw. Shadow passes, depth prepasses, post effect
quads and the sky are all in it. The tile batches are 56 of the 179 and the other 123 are not tile
batches.

One consequence worth writing down because it will mislead somebody: `updateBasic` runs at the START
of a tick, and the product's recorder reads the field at `frameend`, so what it reads is the PREVIOUS
tick's count. Harmless for a maximum over thousands of frames, and wrong for anybody comparing one
frame to one change.

## The gate run on this tree

Condition `preview-shell-credentialed-tiles`, target `generated-tile-evaluation`, walk
`docs/visual-gate-corridor-walk.md`, pose 256000,70300 facing 1,0, four containers on the wire,
56 meshes read.

    maxDrawCalls                   179      decidingMax
                                   179      productWindowMax, over 60 seconds
                                   179      routeMax, over 5,012 rendered frames of the walk
    drawnTriangles             175,034      against 227,173
    drawnMeshes                     56
    environmentTransferredBytes 12,683,297  against 28,247,006
    environmentDecodedTextureBytes 150,831,076  against 167,772,160
    frameP95Ms                    16.8      fpsP1Low 59.52, 3,601 frames

    practicalBrowserBudget       FALSE      on maxDrawCalls alone
    noCutsOrFloatingGeometry     FALSE      componentsDetachedFromSupport 322
    the other six                 as before, key for key

**THE TWO WINDOW FIGURES AGREE EXACTLY.** `decidingMax` is the larger of the product's own 60 second
validation window and the harness's maximum over the whole walk. Melbourne's 87 is a product window
figure alone, from a Playwright run holding W for thirteen seconds, and its record has no route
maximum because that field did not exist. So today's figure is a maximum over a strictly longer
window than the budget it is compared to. That asymmetry is real, and on this run it did not bite.

## Where the 179 goes

Measured by wrapping the device's own draw entry point and counting by the RENDER TARGET bound at
that moment, which is the pass that made the draw, with the triangles each draw submits beside it.
`web/packages/atlas-react/test/gpu/measure-draw-calls.mjs` is that measurement; every figure in this
section is its output. It defines no new number: each arm checks its own count against
`app.stats.drawCalls.total` for the same frames and refuses to report when the two disagree.

Walk's opening pose, the busiest frame, reproduced exactly by two runs of the whole arm set:

| pass | draws | triangles rasterised |
| --- | ---: | ---: |
| `ShadowMap2D_DEPTH` | 93 | 381,336 |
| `SceneColor`, the forward pass | 43 | 165,898 |
| `PrepassRT`, the depth the occlusion needs | 39 | 164,502 |
| `SsaoFinalTexture` | 2 | 4 |
| `SsaoTempTexture` | 1 | 2 |
| `WebglFramebuffer`, the composite | 1 | 2 |
| total | **179** | **711,744** |

Four arms, each restored before the next:

    whole            179     711,744 triangles
    noTileShadows     86     330,408      every batch stops casting; the 93 go and nothing else moves
    worldHidden        5          20      the frame with no world in it at all
    oneCascade       138     503,952      three cascades to one

  SO 135 OF THE 179 ARE SHADOW CASCADES, A DEPTH PREPASS AND AN OCCLUSION BLUR. What is left is the
  forward pass and the composite, 44 draws, and 43 of those 44 are the world. A composed four tile
  street of 175,034 triangles costs 43 forward draws, against a budget of 87 measured on a frame
  that ran no cascade, no prepass and no occlusion pass.

## The budget's frame did not run those passes, and the comparable one does not either

`docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json` is where 87 comes from:
`record.browser.maxDrawCalls`, and the same 87 at `browserReport.renderer.max_draw_calls` in its
artifact, through the same recorder profile `exulanica.browser-reconstruction-validation/v1`. The
field is the same field. What it was measured on is a City of Melbourne photogrammetry tile,
227,173 triangles in 4 chunks with 10 atlases, and the record says of the code that drew it:
"Failed preprocessing and runtime implementation removed before commit."

  THE RUNTIME THAT PRODUCED 87 IS NOT IN THIS REPOSITORY, so there is no look to compare and no way
  to obtain the missing cell. `TILE_LOOK_V1` was written four days after that measurement.

Note where that record lives: it is listed in `.git/info/exclude` and exists only as an untracked
file in the main checkout, so no lane worktree has it. A number that gates the project's stop
condition is justified by a document that is in one tree on one machine.

The only figure this harness has ever produced on the baseline is 29, and it produced it twice: the
retained run and its repeat both state `observation/maxDrawCalls` 29 with `drawnMeshes` 16 and
`drawnTriangles` 63,730, in
`docs/evaluation/artifacts/2026-09-15-flatiron-owned-district-baseline/`. Sixteen instances and
twenty-nine draws is 1.8 draws per instance against the corridor's 3.2. THAT RATIO IS NOT A
DECOMPOSITION: the 29 includes whatever else that frame drew, and nobody has ever split it, which is
what the harness change in this lane exists to stop happening again.

**AND 29 IS NOT REPRODUCIBLE BY A LANE.** Two attempts on this tree, both halted by the product
rather than by the harness: first `not_authorised: this credential does not hold library.read, which
GET /graph requires`, and after widening the grant, `the product showed its empty world`. The
district's geometry is a committed asset but the product refuses to mount a world until the graph
holds live regions, and a private server has none. So the number is retained and its conditions
cannot be recreated without the shared database. THE FIGURE SURVIVES AND THE THING THAT WOULD LET
ANYBODY CHECK IT DOES NOT.

What could be measured instead is the development preview, which draws the owned district without a
graph. It is NOT the scored baseline and is not offered as a substitute for 29. Through the same
instrument:

    every district draw goes to `WebglFramebuffer`. THERE IS NO PrepassRT, NO SceneColor AND NO
    SSAO TARGET AT ALL: that page runs one pass to the screen.
    its sun states `cascades: 1`, read from the live scene.
    of the 70 batches in that scene the 6 the district draws and the 52 the society draws cast
    NOTHING, and the only 9 shadow draws in the frame come from the player character.

The two pages differ structurally and not by degree, and now by measurement rather than by reading
two files.

## The second population fault in the same key

`drawnTriangles` reports 175,034 against a budget of 227,173 and passes. THE FRAME RASTERISES
711,744 TRIANGLES, four times the number being budgeted, because the field counts the scene's
triangles once and the browser draws them once per pass. Melbourne's 227,173 was also a scene count,
so that field IS comparable and is not broken the way `maxDrawCalls` is. But nothing in the key
measures what the GPU actually pays, on either side, and it never did.

`environmentTransferredBytes` is broken a third way, and this one is arithmetic rather than
interpretation. The budget 28,247,006 is Melbourne's `preprocessing.totalBrowserAssetBytes`, an
offline artefact total; the same record's browser measurement of network transfer was 15,958,164.
Today's 12,683,297 is ONE HTTP RESPONSE, `network.environment.requestPath`
`/api/tiles/<own tile>/bytes`, on a world whose four containers total 39,089,820 bytes before a
texture set is counted. Neither side counts what the other counts, and today's side does not count
the world it drew.

## Culling buys triangles, not draws

Same position, heading reversed so the tiles that were ahead are behind:

    draws       179 to 177              two
    triangles   711,744 to 567,158      a hundred and forty-four thousand

The forward pass submits 43 draws at both headings. This is the number that decides whether batching
across tiles is worth building, and it points the opposite way from the draw count: merging to one
batch per key would put every batch in every cascade, so the shadow pass would rasterise 3 x 175,034
where it now rasterises 381,336. Roughly 875,000 triangles against 711,744, a 23 per cent rise, for
a 60 per cent fall in draws. THAT LAST SENTENCE IS ARITHMETIC AND NOT A MEASUREMENT: nothing was
merged and nothing was built.

## An instrument note for whoever measures this next

PlayCanvas exposes rasterised triangles as `app.stats.frame.triangles`, computed by
`Stats.updateDetailed`. **NOTHING IN THIS BUILD CALLS `updateDetailed`.** The device accumulates
`_primsPerFrame` and nothing reads it and nothing resets it, so that field reads whatever it was
initialised to and grows without bound underneath it. Anybody reaching for the obvious field would
have got a confident wrong number. The measurement here counts triangles at the draw instead.

## What this lane did not do

**IT DID NOT BUILD THE BATCHING CHANGE.** The measurement said the change would optimise the smaller
half of the frame against a budget that is not a comparison, and that decision was the orchestrator's
on this evidence. The change remains available and its case has to be made on rasterised triangles
and frame time rather than on a draw count.

**IT DID NOT TOUCH THE CASCADES.** Reducing them to 138 draws, or removing the occlusion pass, would
pass the key by changing what the named judge saw when they called it a street. That is a decision
about the look for whoever owns the look, and the number is here for them: the third cascade and the
occlusion pass together are 135 of 179 draws and 381,336 of 711,744 triangles.

**IT DID NOT WIDEN OR WEAKEN ANY KEY.** Nothing here turns a red gate green. `noCutsOrFloatingGeometry`
is false for reasons that have nothing to do with this key, and the judged key is the judge's.

## One thing reproduced that this lane does not own

`usefulEyeLevelMovement` measured `maxEyeHeightErrorMm` 0 again, on an independent bake, an
independent store, an independent database and an independent run, with `maxSupportResampleDeltaMm`
0 and 2,502 trace samples. The lane that first saw it go from 146 to 0 could not explain it and filed
it as an open question rather than taking the pass. IT IS NOT A FLUKE OF THAT RUN. It is still
unexplained, nothing in this lane touches it, and a second observation is worth having beside the
first.

## The gate carries the same figures, from its own recorder, over the whole walk

Added after the sections above, which were committed before this run and are unedited.

`scripts/capture_visual_gate.mjs` now records the pass each draw belongs to and the triangles each
pass rasterised, as evidence beside `decidingMax`. No key reads any of it. A second run of the same
walk, same pose, same four containers, at `d1b9fb87` plus that one file:

    decidingMax        179      productWindowMax 179, routeMax 179, over 4,986 rendered frames
    routeMaxCounted    179      the harness's own count of the same frames, from the device
    routeBusiestFrame  PrepassRT 39, ShadowMap2D_DEPTH 93, SceneColor 43, SsaoFinalTexture 2,
                       SsaoTempTexture 1, WebglFramebuffer 1
    rasterised         711,744  PrepassRT 164,502, ShadowMap2D_DEPTH 381,336, SceneColor 165,898

**THE BUSIEST FRAME OF A 125 METRE WALK IS THE FRAME THE STANDALONE MEASUREMENT FOUND AT THE OPENING
POSE**, target for target and triangle for triangle. Two instruments written separately, one driving
its own browser and one inside the gate's, agreeing on every figure. THAT IS AN INDEPENDENT
CONFIRMATION AND NOT A REPEAT: different browser, different process, different code, and a maximum
taken over 4,986 frames of a walk rather than over one pose.

And `routeMaxCounted` agrees with `routeMax`, which is the product's own field. That agreement is
what makes this a decomposition rather than a second opinion: without it the per-pass figures would
be about a frame, and with it they are about THE SAME 179 THE KEY DECIDES ON.

All eight mechanical keys are what the first run measured, key for key, including the two that are
false. Nothing in this lane moved a key.

## Two halts worth writing down, because neither was a fault in the harness

**The owned district halted on a credential and then on an empty world**, which is the section above.

**The corridor halted once on a credential that could read too much.** Widening the token to
`library.read` for the district attempt left the corridor run unable to name its own authentication
condition: `preview requests 6, graph read true, anonymous status 401`, which matches no declared
condition. THE HARNESS REFUSED TO SCORE A PAGE IT COULD NOT NAME THE CONDITIONS OF, which is what it
should do, and the fix was to put the grant back to `world.read` and `tiles.materialise` so the run
is the same condition as the first. Recorded because a lane widening a grant for an unrelated reason
is an easy way to make a run incomparable to the one before it, and the only thing that caught it was
the harness declining.

## The unavailable hatching is in the world, and this lane left it exactly where it was

The rule this lane was given first is that the magenta unavailable hatching is the world drawing
honestly the surfaces it has no material for, and that a judge must see it. Nothing here touched the
batching, so nothing could have merged an unavailable surface into a material one, and the scored run
says the surfaces are there:

    own tile (2,0)   86 surfaces      all for one reason, which the record states in the tile's own
    tile (1,0)       89               words: "No surface_material record dresses this surface: the
    tile (0,0)        7                tile states that none exists."
    tile (3,0)       83
    the world       265

Each is drawn in that tile's own unavailable-surfaces batch, which is the batch whose key is the
empty string and which therefore can never merge with a textured one: THE KEY IS THE MATERIAL. Any
future batching change keeps that property for free, and a test should say so out loud anyway.

## Checkpoint, 2026-09-19 11:30, written because the machine is about to pause mid turn

**WHERE THIS LANE IS.** `lane/draw-budget`, four commits, the last of which this file is part of.
Local main was `775d44f8` when this was written and this branch is based on `0a415394`. NOT REBASED
YET. Measured rather than assumed: the four commits main gained touch NO FILE UNDER `web/`, and the
new `scripts/record_visual_gate_evidence.py` still indexes only `decidingMax` out of the `drawCalls`
block and spreads the rest, so the harness change in this lane is compatible with it.

**WHAT RAN AND WHAT IT SAID.**

    web `pnpm run check` at 8e8eb38f     typecheck and boundaries PASS; vitest 2,853 passed,
                                         7 skipped, 3 FAILED, all three TIMEOUTS in
                                         generated-tile-runtime.test.ts, at load average 82 to 96
                                         with seven lanes on the machine
    the same file at 15e8198c            490 passed, 6 skipped, all three of those tests among them,
                                         at load average 15
    web typecheck of the gate harness    `tsc -p web/tsconfig.scripts.json` exit 0, which is where
                                         `scripts/capture_visual_gate.mjs` is actually checked

**THE THREE FAILURES ARE UNEXPLAINED AND THE LANE IS NOT CLAIMING THEY ARE LOAD.** They took 5,863,
2,763 and 3,051 ms in the clean baseline against timeouts of 30,000 and 5,000 ms, which is consistent
with a loaded machine and is not evidence. A re-run of that one file in the quiet slot was started
and STOPPED BEFORE IT TOOK THE SLOT, because holding the machine-wide lock across a pause blocks
every lane. THE NEXT THING TO DO IS THAT RE-RUN.

**WHAT IS LEFT, IN ORDER.** Re-run `generated-tile-runtime.test.ts` in the quiet slot and settle the
three timeouts. Rebase onto current main. Re-run the web check on the rebased tree. Run the backend
suite once through `.exulanica/bin/full-suite`, expecting 6 skips. Send the final report with the
key redefinition proposal.

**THE STACK THIS LANE BUILT IS STILL UP AND IS LOCAL.** A private PostgreSQL server on port 59783
migrated through 0082, a private store holding the five corridor tiles at tessellator 20, the API on
port 8031 and the app dev server on port 5345 with a token granted `world.read` and
`tiles.materialise` and nothing else. THE GRANT MATTERS: widening it to `library.read` makes the
corridor run unable to name its authentication condition, which is the halt recorded above.

**NOT IN A FILE ANYWHERE ELSE.** The batching change was NOT built, by the orchestrator's decision on
this evidence, and the reason is in this record rather than in a commit: merging optimises 44 draws
of a 179 draw frame against a budget that is not a comparison, and it trades 144,000 rasterised
triangles for two draw calls at the pose where that trade was measured.
