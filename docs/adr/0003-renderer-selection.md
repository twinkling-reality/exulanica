# ADR-0003: Browser renderer for the Atlas

- Status: **ACCEPTED, PlayCanvas Engine 2.21.4**. Resolved 2026-08-28 by matched-resolution
  measurement. See "Resolution" at the end of this document. The body below is preserved as the
  reasoning that existed before the numbers, including a lean that the measurement overturned.
- Date: 2026-08-27, resolved 2026-08-28
- Deciders: Exulanica build
- Settled at: the bake-off, ahead of the renderer deadline
- Supersedes: nothing
- Related: [architecture-overview.md](../architecture-overview.md) section 1.1
- Mobile-delivery consequences in the preserved analysis are superseded by ADR-0006.

## CORRECTED 2026-08-31: verified SVG Companion; guessed robot and Spline removed

The supplied reference was identified as the Grok Bot-style geometric avatar documented by the
MIT-licensed Bloub project: one configurable silhouette and two slit eyes. The ordinary and
production application uses an original DOM/SVG implementation of that verified grammar. It
supports saved shape, colour, and expression choices through the V3 presentation contract.

The rejected humanoid PlayCanvas robot, its renderer attachment, and its body/accessory controls are
deleted. The Spline runtime, hosted scene, development query route, and fallback are also deleted.
The Companion therefore creates no canvas, no network request, and no second 3D renderer. The
historical corrections below remain only as an audit of superseded decisions.

Bloub's MIT license covers its code, not xAI's imitated design. Exulanica does not copy Bloub source or
claim xAI affiliation; it implements the abstract, user-supplied geometric grammar locally and
retains attribution in the evaluation document. VRM remains separate research for a
rights-cleared humanoid request, not a justification for adding a body to this reference.

## HISTORICAL CORRECTION 2026-08-30: the supplied authored Companion reopened one narrow Spline exception

**DECISION, CORRECTED.** The 2026-08-29 closure rested on a false product premise: that there was no
approved authored Companion and that the code therefore had to invent one. The account holder has
supplied the source file and its production scene:

- source: `https://app.spline.design/file/9ec46d55-e993-44ae-b5d4-d34e6e3babfd`;
- runtime scene: `https://prod.spline.design/fqke6-9pFgVx3uvG/scene.splinecode`.

The live scene was inspected rather than inferred from a screenshot. It contains the `body`,
`eyes_opened`, `eyes_blinking`, and `eye` hierarchy, and exposes authored `lookAt`, `start`, and
`mouseHover` events. Moving the cursor to opposite sides of the running export visibly rotates the
body toward it. This is the Companion source of truth. The CSS source-plane mark and provisional
mote field were not approximations of it and have been deleted.

The narrow runtime exception is therefore open again. `@splinetool/runtime` may be imported only by
`packages/app/src/ui/companion-stage.ts`; the dependency boundary names that exact file, so a second
import fails the build. PlayCanvas remains the sole Atlas renderer. Spline receives no graph,
topology, evidence, navigation, customization, or versioning authority and is loaded only on first
summon.

This exception is necessary because Spline's glTF/GLB export does not preserve states, events, or
interactivity. Converting the scene to an Atlas asset would discard the exact Look At behaviour that
settled the question. The DOM glass exchange remains a separate renderer because its responses and
evidence must stay accessible and are not part of the character model.

**Verified compatibility pin.** The scene loads and its authored events run under the pinned
`@splinetool/runtime@2.0.15` browser module. Its npm package could not be installed on 2026-08-30
because it declares `@splinetool/animation-core`, which the configured npm registry returned as
404. The application therefore imports that exact versioned browser module from unpkg on first
summon. The installable `1.12.98` fallback rendered the scene but emitted a real schema downgrade
warning (`131` to `122`) and was rejected rather than presented as equivalent. Re-test the exact
scene before changing the runtime URL or version.

**Delivery and licensing remain open.** The published `@splinetool/runtime@2.0.15` package manifest
contains no `license` field and the package exposes no `LICENSE` file. That absence is not evidence
that use is forbidden, but it is also not a redistribution grant. Spline's current official
self-hosting documentation says a fully offline export including the runtime is an Enterprise-plan
feature. The current unpkg import and `prod.spline.design` scene therefore remain an externally
hosted comparison baseline, not an approved offline or redistributable supply chain. Resolve rights
and delivery terms with Spline before production; do not infer them from public package access.

**SUPERSEDED EXPERIMENT, 2026-08-30: one-renderer native Companion.** The first paired-shutter
prototype established the lifecycle and renderer boundary. The 2026-08-31 correction replaced it
with the configurable modular character and made native the default.

**2026-08-29 closure preserved as rejected reasoning.** The earlier decision chose a 2D mote field
because a speculative face could make social claims unsupported by the graph. That caution remains
valid for expressions Exulanica invents. It does not authorize replacing an account-holder-supplied
character with generated geometry. Epistemic states therefore remain unmapped until approved named
states exist in the authored scene.

## Context

Two independent research streams designed the front end against two incompatible engines, and neither
cited the other.

- The browser-rendering stream recommends **PlayCanvas Engine 2.21.x**, with unified GSplat rendering,
  Streamed SOG assets, and a WebGPU compute path with automatic WebGL2 fallback.
- The interaction-architecture stream designs the entire Companion, Atlas, focus solver, anchor
  overlay and layout system against **three.js / react-three-fiber / drei / d3-force**, citing
  three.js `PointerLockControls` source, `Vector3.project`, drei `<Html>` props and d3-force's
  seeded PRNG as primary sources.

These are not compatible choices. This is the largest unreconciled architectural disagreement in the
research corpus, and it is unresolved here on purpose. Both engines are MIT, so licensing does not
break the tie.

**VERIFIED, licenses and maintenance, all retrieved 2026-08-27 from the GitHub REST API and the npm
registry:** `playcanvas/engine` MIT, v2.21.4, released 2026-08-13, repository pushed 2026-08-27;
`sparkjsdev/spark` MIT, v2.1.0, released 2026-05-18, 23 commits in the preceding 90 days; `three.js`
MIT; react-three-fiber and drei MIT; d3-force ISC. All are compatible with an Apache-2.0 repository
subject to retaining their notices.

## Options considered

### Option A: three.js r185 + `@sparkjsdev/spark` 2.1.0

**In favour.**

- The entire interaction design is already written against three.js APIs. The focus solver, the
  anchor overlay projection, the camera rigs and the deterministic layout all cite three.js and
  d3-force primary sources.
- **VERIFIED:** Spark 2.0 ships LoD, a `SplatPager` LRU virtual paging system, the chunked `.RAD`
  streaming format and camera foveation. Splats on three.js are not a compromise stack. Source:
  https://github.com/sparkjsdev/spark/blob/main/CHANGELOG.md
- `SparkRenderer.lodSplatCount` provides a detail budget, and the Dyno shader-graph modifier chain is
  more ergonomic than PlayCanvas's split between a scene-wide material and per-component work-buffer
  modifiers.
- It inherits the whole three.js ecosystem for the Companion, post-processing and DOM anchoring.
- Multiple `SparkRenderer` instances give free multi-viewport, which is useful if the Atlas ever wants
  a picture-in-picture of the source moment.

**Against.**

- **VERIFIED:** WebGL2 only. No WebGPU compute path. Measured WebGL2 versus WebGPU splat framerates
  show a flat **2.0x on an iPhone 13 Pro Max at every splat count** (1M: 38.1 versus 77.6; 4M: 20.4
  versus 42.4), and up to 5.7x on an M4 Max at 35M splats. Source:
  https://blog.playcanvas.com/new-in-supersplat-webgpu-and-streaming-bring-huge-performance-wins/
- No collision-from-splats toolchain at all, so containment becomes Exulanica's own problem.
- `.RAD` is a single-vendor format with no published spec, which is a lock-in that SOG is not.
- No shipped first-person controller or annotation system.

### Option B: PlayCanvas Engine 2.21.x

**In favour.** Every advantage below is **VERIFIED**, and every one of them is a *splat* advantage.

- **Unified global sort across N splat components is the documented default**, not a mode assembled
  by hand. Sources: https://developer.playcanvas.com/user-manual/gaussian-splatting/rendering-architecture/
  and a local measurement on the actual M3 Pro demo machine on 2026-08-27: `pc.version = "2.21.0"`,
  three independent gsplat components in one canvas, `app.stats.vram = {tex: 25050504, vb: 103312,
  ib: 23172}`, ANGLE Metal Renderer, WebGPU available.
- **Cross-asset detail budget.** `app.scene.gsplat.splatBudget` is a target splat count *across all
  GSplat assets in the scene*, automatically degrading distant geometry first. Documented budgets are
  1 million mobile and 3 million-plus desktop. The Atlas overview, three to five distant islands plus
  one near island, is exactly this workload, and nothing else has a documented cross-asset balancer.
  Source: https://developer.playcanvas.com/user-manual/gaussian-splatting/building/performance/
- **WebGPU compute path with automatic WebGL2 fallback**, with published per-splat-count benchmarks on
  both a Mac and an iPhone. Source: as above.
- **Collision from splats exists in the toolchain.** `splat-transform -K` voxelizes a splat,
  flood-fills the navigable interior and writes a watertight `.collision.glb` plus a sparse voxel
  octree. Nobody else has this. Source:
  https://developer.playcanvas.com/user-manual/splat-transform/collision/
- **A shipped production reference with published numbers.** Grace Cathedral renders about 3.5M splats
  with a 3.5M desktop / 1.4M mobile budget, streamed SOG, WebGPU hybrid with WebGL2 fallback,
  coarse-LOD-first loading, on-demand rendering, and reuses the collision mesh as a depth-only
  occluder. Source: https://blog.playcanvas.com/building-the-grace-cathedral-experience/
- Shipped MIT dissolve shaders, first-person controller, camera controllers and an annotation system
  in the same repository.

**Against.**

- The entire interaction design would have to be rewritten against PlayCanvas APIs.
- **VERIFIED:** the PlayCanvas gsplat API is moving fast. `gsplatCustomizeVS` was deprecated in 2.15
  and removed in 2.16; the unified renderer landed in 2.19 in June 2026. Custom shader code will break
  on upgrade, so the engine version must be pinned and not upgraded during the build.
- The collision advantage may not survive real input. The browser-rendering stream rates the `-K`
  flood-fill as **high risk** on messy room captures; it is demonstrated on a clean cathedral scan.

### Rejected outright

- **Babylon.js.** Excellent splat feature set and the friendliest license, but **VERIFIED:** roadmap
  issue #16671 lists "GS LOD", async improvements, VRAM storage optimization and compute-shader
  sorting as unchecked with no pull request. Every island fully resident is disqualifying for an
  Atlas. Source: https://github.com/BabylonJS/Babylon.js/issues/16671
- **mkkellogg GaussianSplats3D.** **VERIFIED:** MIT but zero commits in the preceding 90 days, last
  release 2025-01-25. Fine for a single-scene viewer, wrong for a multi-year product.
- **`@lumaai/luma-web`.** **VERIFIED:** npm-deprecated, "Package no longer supported", last publish
  2024-03-06.

## Which way the evidence leans, and why

**Toward Option A, three.js plus Spark. Not decisively, and undecided.**

The reasoning is not that PlayCanvas is worse. On its own terms the browser-rendering stream is right:
if photoreal Gaussian splats are the substrate the Atlas is made of, PlayCanvas is the better engine
and it is not close. The reasoning is that **three of the four research streams have already
de-prioritized splats as the MVP substrate**, and every one of PlayCanvas's six advantages is a splat
advantage.

- The reconstruction stream recommends full 3DGS islands be **pre-baked for three to five scenes
  only**, with monocular depth cards as the guaranteed floor, and says explicitly never to put
  reconstruction in the live demo path.
- The interaction stream's own MVP cut line specifies **decimated mesh rather than splats** at its
  top tier.
- The evaluation and deployment stream's Decision Point D is "if photoreal splats are too slow or too
  ugly, fall back to the stylized Atlas."

If the substrate is decimated meshes and depth cards, PlayCanvas buys almost nothing and costs the
entire interaction design.

Three further facts narrow the gap even if splats do survive as the substrate:

1. Spark supplies LoD, virtual paging, chunked streaming and camera foveation, so the streaming story
   on three.js is complete rather than absent.
2. **The collision-from-splats advantage is partly moot.** The interaction stream's containment design
   is spline-constrained camera rigs plus authored soft boundary volumes, which is exactly the
   browser-rendering stream's own "layer 2", and layer 2 is needed regardless of engine. The stream
   that recommends PlayCanvas rates the `-K` flood-fill as high risk on the kind of capture Exulanica
   actually has.
3. **The WebGPU loss lands mostly on a mode that is not the default.** The 2.0x gap is measured on
   mobile, and **VERIFIED:** Pointer Lock is not supported on iOS Safari 3.2 through 26.6, Android
   Chrome 151, or Samsung Internet 4 through 30. Source: https://caniuse.com/pointerlock (secondary
   source, flagged as such). The interaction stream has therefore already decided that mobile defaults
   to the flat World Index rather than the first-person Atlas.

**What would flip this to Option B.** One thing only: if the bake-off shows that gsplat output on
Exulanica's own footage is good enough to be the *primary* substrate rather than a hero-scene garnish.
In that world the workload becomes the one PlayCanvas was built for, and the cross-asset budget plus
WebGPU plus shipped collision are worth a rewrite.

## The experiment that settles it: X-R1

**A bake-off, not an argument.** It runs after X-1 produces one real baked scene, and takes about half
a day.

1. Bake one real Exulanica capture to a Gaussian splat on a Nebius preemptible L40S (experiment X-1).
2. Load the identical output in **three.js r185 + Spark 2.1.0** and in **PlayCanvas 2.21.4**.
3. Run both on **the actual M3 Pro demo machine, in visible Chrome with the window in the foreground**,
   because a hidden render pane throttles `requestAnimationFrame` and invalidates the numbers.
4. Measure frames per second at 1M, 2M, 3M and 4M splats, on WebGL2 and, where available, WebGPU.
5. Answer two questions, in this order:
   - **Does it look like a place worth walking in?** This is the substrate question and it decides the
     ADR. It is a judgement call made by looking, and it should be made by looking.
   - **Does it hold 60 fps at 1.5M splats?** This is the budget question and it retires a separate
     assumption regardless of which engine wins.

X-R1 also retires the standing assumption that a browser can render 1 to 4M splats at 60 fps on
desktop. **Every desktop splat number in the research corpus is extrapolated from an M4 Max, not
measured on the M3 Pro that runs the demo.**

**Fixed regardless of which engine wins**, so that the ADR's outcome changes as little as possible:

- Budget the scene, not the island: 1.5M splats desktop and 800K mobile, with a runtime auto-downgrade
  driven by **measured frame time**, never by device sniffing, so no guessed hardware number is ever
  load-bearing.
- Delivery format is Streamed SOG. **VERIFIED:** SOG v2 is `meta.json` plus lossless WebP images,
  typically 15 to 20x smaller than an equivalent PLY, decoded by native WebP image decode rather than
  a per-splat JavaScript parse. PLY is a build-time archive and is never shipped. `.spz` is the
  interchange format. Source:
  https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/sog/
- `KHR_gaussian_splatting` glTF is the archival interop target once ratified and never an MVP
  dependency. **VERIFIED:** it is at Release Candidate status, not ratified. Source:
  https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_gaussian_splatting
- Containment is spline-constrained camera rigs plus authored soft boundary volumes. Splat-derived
  collision is an optional bonus only if `-K` survives a real capture.
- The DOM overlay is the primary UI layer, with manual projection into pre-allocated nodes, hard-capped
  at one focus label, six pinned callouts and four edge chevrons. **VERIFIED:** drei `<Html>` mounts a
  real DOM element per instance with a wrapper and documents blurriness in transform mode, so it is not
  used per anchor. Source: https://drei.docs.pmnd.rs/misc/html
- Canvas content is invisible to screen readers, so the DOM overlay is the accessibility surface and
  must contain real focusable labelled elements. Every entity, every evidence item and every source
  moment must be reachable from a flat keyboard-navigable list. **VERIFIED:** WCAG 2.2 SC 2.1.1
  requires all functionality to be operable through a keyboard interface. Source:
  https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html

## Deadline, and the cost of deciding late

**DECISION: this ADR must move from PROPOSED to Accepted by the end of week 3.** Counting week 1 from
2026-08-27, that is on or before **2026-09-16**.

**Rejected alternative: fold the renderer choice into the week 6 substrate decision (DP-D), where it
naturally belongs.** Rejected because by week 6 the correction is unaffordable.

**The cost of deciding late is a two-week rewrite of the interaction layer**, inside a nine-week build,
at the point in the schedule where there is least slack. The blast radius is bounded but real: the
module contract in `architecture-overview.md` section 1.1 keeps `companion-runtime`, `world-index` and
`graph-client` free of any renderer import, so a switch touches `atlas-core` and `atlas-react` only.
That contract turns a total rewrite into a two-package rewrite. It does not turn it into a cheap one,
because `atlas-core` holds the scene graph, the focus solver and the layout solver, which is most of
what makes the Atlas an Atlas.

The forcing function is therefore calendar-based, not evidence-based: **if X-R1 has not run by
2026-09-16, ship Option A on the default and stop revisiting it.** An unresolved renderer question in
week 4 costs more than picking the second-best engine in week 3.

## Consequences

**If Option A wins.** The interaction design proceeds unchanged. Accept the documented losses: WebGL2
only, a flat 2x mobile penalty against a mode that is not the mobile default, no collision-from-splats,
and `.RAD` treated as a build artifact with SOG or `.spz` kept as the archival format. Containment
rests entirely on authored boundary volumes, which the design needs anyway.

**If Option B wins.** Budget two weeks to rewrite `atlas-core` and `atlas-react`, pin the engine
version and do not upgrade it during the build, and isolate all custom shader code behind one module
because the gsplat shader API has broken twice in the last six months. The collision toolchain becomes
available but is not assumed to work until tested against a real Exulanica capture.

**Either way.** Both engines are MIT and both work. This ADR is about opportunity cost and schedule,
not about capability. Whichever loses, the other ships.

## Status of this record

**OPEN.** The evidence leans toward Option A and the default is Option A, but the substrate question
that decides it has not been measured, on this footage, on this machine. Nothing in this document
should be read as a decision until X-R1 has run and this ADR's status line reads Accepted.

---

## Update, 2026-08-27: runtime probes refute the case for PlayCanvas

Both bindings were implemented and measured against the same synthetic scene. The findings below
come from probes executed against the real engines, not from reading documentation.

### The three research claims that favoured PlayCanvas are all NOT APPLICABLE to this workload

Every advantage attributed to PlayCanvas turns out to be specific to Gaussian splats. Exulanica does
not render Gaussian splats. The corpus is photographs, which produce MoGe point maps, which are
rung 3 of the reconstruction ladder and are drawn with `PRIMITIVE_POINTS`.

| Claim | Verdict | Evidence from the running engine |
| --- | --- | --- |
| Single global sort across N independently transformed islands | **not-applicable** | PlayCanvas sorts MeshInstances by `zdist`, not primitives. Per-splat global sorting exists only inside the unified gsplat work buffer and never reaches a Mesh with `PRIMITIVE_POINTS`. The point map is drawn opaque with an alpha test, so it is depth-correct with no sort at all |
| Cross-asset splat budget that degrades distant islands first | **not-applicable** | `app.scene.gsplat.splatBudget` exists and is settable, but enforcement in `GSplatWorld._enforceBudget` reduces LOD only for `GSplatOctreeInstance` entries. Point-cloud MeshInstances are outside the gsplat world entirely, so the budget cannot degrade a distant point-map island |
| WebGPU compute path measured faster than WebGL2 | **not-applicable** | The measured speedup is the gsplat compute sorter, and a `PRIMITIVE_POINTS` draw dispatches no compute. On WebGPU this path also **loses point size**, because WGSL has no `gl_PointSize` equivalent and a point-list renders one pixel per point, and it requires hand-written WGSL since glslang and twgsl are not shipped with the engine |

This is the reason the ADR demanded verification rather than repetition. Three claims sourced from
credible research were each true of the engine and false of this project's use of it.

### The three.js side has its own verified constraint

`Spark 2.1.0` types `SparkRendererOptions.renderer` as `THREE.WebGLRenderer`, so the three.js
binding is **WebGL2 by construction**. WebGPU is unavailable to it regardless of hardware support.

Net effect: **both candidates are WebGL2 for this workload.** The WebGPU differentiator does not
exist on either side.

### Measured: three.js plus Spark, real Chrome, Apple M3 Pro, 1728x940, dpr 2

| Rung | Total points | fps mean | 1% low | Time to first render | Peak heap |
| --- | --- | --- | --- | --- | --- |
| 250k x 3 | 750,000 | 120.0 | 96.0 | 155 ms | 21 MB |
| 1M x 3 | 3,000,000 | 98.5 | 29.3 | 99 ms | 39 MB |
| 2M x 3 | 6,000,000 | 67.2 | 19.8 | 125 ms | 69 MB |
| 3M x 3 | 9,000,000 | 58.8 | 11.9 | 157 ms | 121 MB |
| 4M x 3 | 12,000,000 | 49.8 | 11.5 | 165 ms | 137 MB |

Three islands at 1M points each hold 98.5 fps, which is comfortably above the Atlas overview budget.
The 1% low degrades faster than the mean, which is the number to watch for comfort in a first-person
view, and it is the argument for streaming distant islands at a lower rung rather than loading all
five at full density.

### Still OPEN: the PlayCanvas frame rate

**Unmeasured in this section, and honestly so.** Both available browser surfaces report
`document.visibilityState === "hidden"`, which throttles `requestAnimationFrame`. The three.js
harness correctly detected this and reported `spoiled: true` with `frames: 0` rather than publishing
a fabricated number, which is the harness behaving as designed.

A valid comparison requires a foregrounded, non-minimised browser window. Until that run happens,
no frame-rate comparison between the two engines is recorded here.

### Where this leaves the decision

**Leaning strongly to three.js plus Spark**, on grounds that do not depend on the missing number:

1. Every PlayCanvas advantage in the research is splat-specific and does not apply to point maps.
2. Both are WebGL2 here, so the WebGPU argument is void on both sides.
3. three.js has measured, adequate performance across the whole ladder.
4. PlayCanvas would additionally require hand-written WGSL to reach WebGPU later, and would lose
   point size when it got there.

Status at the time of this update remained **PROPOSED** rather than Accepted, because the frame-rate
comparison the ADR itself demanded had not been run. Publishing a decision while calling it
measured would have been the kind of claim this project exists not to make.

---

## Resolution, 2026-08-28: PlayCanvas, on measurement, against the prior lean

### The controlled comparison

Both engines, 3,000,000 points across 3 islands, **1728x940 at dpr 2 on both sides**, Apple M3 Pro,
Chrome, WebGL2, foregrounded and visible. The PlayCanvas run reports `documentHidden: false` and an
empty `notes` array, meaning the harness vouches for it.

| Metric | three.js + Spark 2.1.0 | PlayCanvas 2.21.4 | Delta |
| --- | --- | --- | --- |
| fps mean | 98.5 | **108.2** | +9.8% |
| **1% low** | 29.3 | **57.8** | **+97%** |
| Frame p50 | ~10.2 ms | 8.3 ms | better |
| Frame p95 | ~10.2 ms | 16.7 ms | worse |
| Time to first render | **98.7 ms** | 202.4 ms | 2.05x worse |
| Peak heap | **39.3 MB** | 74.7 MB | 1.9x worse |
| Draw calls | n/a | 3 | one per island |

### Decision: PlayCanvas Engine 2.21.4

**Rationale, in order of weight:**

1. **The 1% low is nearly double, and it is the metric that matters most here.** Mean frame rate
   describes throughput; the 1% low describes the worst frames a person actually feels as stutter
   while walking through a scene in first person. For a product whose primary interaction is
   embodied movement through space, a 2x improvement in worst-case pacing outweighs a 2x regression
   in a 200 ms load time.
2. **PlayCanvas covers both reconstruction rungs natively.** It renders point clouds (rung 3,
   MoGe point maps, which is the primary path for a photograph corpus) and it has native Gaussian
   splat support for rung 1, the pre-baked hero scene. three.js needs Spark for splats, which is a
   second dependency and, per the probes below, a WebGL2 lock-in.
3. Mean throughput is also 10% better at matched resolution.

**Costs accepted, with mitigations:**

- **Time to first render is 2.05x worse (202 ms versus 99 ms).** In absolute terms 202 ms is still
  fast. The public landing page no longer masks this with a mock transition, so the application
  must own an honest loading/arrival treatment. Worth revisiting if it degrades at 4M points.
- **Peak heap is 1.9x higher (74.7 MB versus 39.3 MB).** This constrains how many islands can be
  resident at overview distance and makes the streaming design more important, not less.

### The reasoning error this corrects, recorded deliberately

An earlier update to this ADR leaned toward three.js on the grounds that all three of the research
claims favouring PlayCanvas (global splat sort, cross-asset splat budget, WebGPU compute path) were
verified **not applicable** to point-map rendering.

That was a non-sequitur. Those claims being inapplicable means PlayCanvas has no *special* advantage
from splat machinery. It does not mean PlayCanvas is worse. The lean substituted an argument about
advertised features for a measurement, and the measurement went the other way.

The probes remain valuable and correct: they stopped the project adopting PlayCanvas *for the wrong
reasons*, and they establish that neither engine gets a WebGPU path here. The decision rests on
numbers taken at matched resolution, which is what the ADR asked for from the start.

### One honest confound, recorded and accepted

The three.js figure is **three.js plus Spark**, and Spark is a Gaussian splat renderer being used to
draw opaque points. Some of its worse frame pacing may be splat-oriented work that a plain three.js
`Points` binding would not do. A third binding was not built.

This does not change the decision, because argument 2 stands independently: PlayCanvas handles both
point clouds and Gaussian splats natively, so it is the only single-engine answer that covers the
whole reconstruction ladder. But the comparison should not be cited as "three.js is slower than
PlayCanvas" in general. What was measured is that **this three.js plus Spark binding** has roughly
half the worst-case frame consistency of **this PlayCanvas binding** on this workload.

### Consequences

- `atlas-react` binds to PlayCanvas. `atlas-core` is unchanged, which is the point of the module
  boundary: the switch touches two packages and nothing else.
- The three.js plus Spark binding is retained in the repository as the measured alternative and as
  insurance, not deleted. It is not built or shipped.
- Streaming and island residency budgets are more important given the higher heap, and should be
  designed against the 4M-point figures rather than the 1M ones.
