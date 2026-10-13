# The PlayCanvas renderer binding

The shipping renderer binding for `@exulanica/atlas-react`, selected in
[ADR-0003](../../../../../docs/adr/0003-renderer-selection.md). Engine: PlayCanvas 2.21.4, pinned.
The Three.js binding was removed. The harness in this directory remains so the PlayCanvas
measurements can be reproduced.

```
pnpm --filter @exulanica/atlas-react bakeoff:playcanvas
open http://localhost:5183/playcanvas-bakeoff.html?points=1000000&islands=3
```

Fixtures are served from `web/fixtures`. Regenerate them with `pnpm synth --out ./fixtures`.

---

## What is here

| File | Contains |
| --- | --- |
| `opm.ts` | Reads the `.opm` container. Header parse plus three typed-array views; no per-point JavaScript |
| `semantics.ts` | Segment class to epistemic state, and the vec4 table the shader indexes |
| `point-shader.ts` | The point-map shader, GLSL for WebGL2 and WGSL for WebGPU |
| `point-cloud.ts` | Vertex format, vertex buffer, mesh and material for one island's shell |
| `controls.ts` | Pointer-lock mouse-look, WASD, reticle targeting |
| `anchor-overlay.ts` | Manual projection into pre-allocated DOM nodes, with the overlay caps |
| `atlas-binding.ts` | Wires atlas-core's tier, focus and emphasis answers to PlayCanvas objects |
| `probes.ts` | Runtime probes for the three ADR-0003 claims |
| `harness.ts` | The bake-off harness |

Nothing here decides what the world should look like. Tier selection, focus resolution, view
manifest application, layout and the coordinate frames all live in `@exulanica/atlas-core`. If a
product rule is being decided in this directory, it is in the wrong package.

---

## The harness contract

Both bindings must answer the identical question or the ADR is decided by whichever harness was
kinder. This is the contract, in full.

### URL parameters

| Parameter | Values | Default | Meaning |
| --- | --- | --- | --- |
| `points` | 250000, 1000000, 2000000, 3000000, 4000000 | 1000000 | Points **per island** |
| `islands` | 1 to 8 | 1 | Independently transformed islands in one canvas |
| `device` | `webgl2`, `webgpu` | `webgl2` | Requested backend; the actual one is reported |
| `driver` | `raf`, `timer` | `raf` | How frames are driven. See below |
| `warmup` | seconds | 3 | Discarded before measuring |
| `measure` | seconds | 15 | Length of the measurement window |
| `width`, `height` | CSS pixels | 1600, 900 | Canvas CSS size |
| `dpr` | 1 to 3 | `devicePixelRatio` | **Pin this.** See the warning below |
| `overlay` | 1, 0 | 1 | Anchor overlay and focus solver live |
| `path` | `orbit`, `static` | `orbit` | Deterministic camera path |
| `blend` | 1, 0 | 0 | Alpha blending instead of the alpha-tested opaque path |
| `size` | metres | 0.05 | Point sprite world size |
| `fov` | degrees | 70 | Vertical field of view |
| `fixtures` | URL | `/` | Base URL for the `.opm` files |
| `autorun` | 1, 0 | 1 | Start immediately |

Scene point total is `points * islands` and is reported as `scenePoints`, so a three-island run at
1M is directly comparable to a one-island run at 3M.

**Pin `dpr`.** It defaults to the window's `devicePixelRatio`, which changes when the window moves
between displays or the zoom changes. This workload is fill-rate bound, so a dpr change from 1 to 2
quadruples the frame time and looks exactly like a renderer regression. Every result records the
dpr and the resulting `canvasPixels`; compare those two before comparing anything else.

### Console output

One line per record: the literal `EXULANICA-BAKEOFF`, a space, then JSON. Grep the prefix, `JSON.parse`
the remainder. Records in emission order: `config`, `load`, `tfmr`, `claim` (one per ADR claim),
`result`, and `error` if the run failed. `window.__exulanicaBakeoff` resolves to the `result` record.

### Metric definitions

| Field | Definition |
| --- | --- |
| frame time | Interval between consecutive frames, unclamped. Not the render call's own duration: what the user feels is the interval |
| `fpsMean` | `1000 / mean(frame time)` |
| `fpsP1Low` | `1000 / p99(frame time)`. The number that decides whether it stutters |
| `heapMB` | `performance.memory.usedJSHeapSize`, Chrome only, sampled at the end. `null` where absent, never estimated |
| `gpuUploadedMB` | The **engine's own** accounting of bytes it uploaded. Neither WebGL2 nor WebGPU exposes a driver allocation figure, so this is a lower bound on VRAM and is named `uploaded` rather than "GPU memory" |
| `tfmrMs` | Harness start to the end of the first frame in which every island's cloud is resident and drawn at full count |
| `sampledPixels` | Non-background pixels in a 512x64 patch at screen centre, sampled once after the last measured frame. WebGL2 only |
| `emptyFrameMs` | Cost of a frame with all island geometry disabled. The floor the environment imposes |
| `renderValid` | False if the GPU raised a validation error, or nothing was drawn, or the run hit an environment cap |

### `driver=raf` versus `driver=timer`

`raf` is the metric that matters and the one ADR-0003 asks for. It **requires a visible, foreground
window**: Chrome suspends `requestAnimationFrame` in an occluded tab, and a background run collects
zero frames.

`timer` drives update and render from a `MessageChannel` loop and blocks on the GPU each frame
(one-pixel `readPixels` on WebGL2, `queue.onSubmittedWorkDone()` on WebGPU). It runs in a hidden tab
and in CI, but it measures frame **cost** rather than presented frame **rate**: uncapped by vsync,
excluding compositing. A `timer` number and a `raf` number are not interchangeable, which is why
`driver` is in every result.

### Three ways this harness refuses to lie

Each of these was added because it actually fired during development. The three.js binding should
carry all three, because none of them is engine-specific.

1. **A broken renderer is the fastest renderer.** A WGSL shader that fails to parse is rejected by
   the WebGPU pipeline, and in the *release* engine build that rejection is silent: the shader is
   marked ready, a draw call is issued every frame, and the canvas stays blank. This harness
   reported **1100 fps at 1M points against a scene that drew nothing**. Now an `uncapturederror`
   hook and a centre-patch pixel count set `renderValid: false`.
2. **A capped environment reports a flat ladder.** A backgrounded tab keeps executing explicit draw
   calls but rate-limits them, and every rung from 250k to 4M then reports the same frame time,
   which reads as "scales perfectly" rather than "measured nothing". `emptyFrameMs` measures a
   geometry-free frame; when it accounts for most of the measured time, `throttleSuspected` is set.
3. **A validity check must not change the number it validates.** The pixel sample was originally a
   full-width strip taken on the first frame. On the ANGLE Metal backend that forces a resolve and
   slowed every subsequent frame; the same configuration read 17 ms before and 63 ms after. It now
   runs once, on a bounded patch, after the last measured frame.

### Engine build

The `playcanvas` package declares a `development` export condition resolving to `build/playcanvas.dbg`,
and Vite's dev server applies it by default. The debug build keeps every assert and none of the
dead-code elimination. `vite.config.ts` aliases the release ESM build in both dev and production, so
the number the dev server prints is the number a build would print. Do not report numbers taken with
the alias pointed at `.dbg`.

---

## What the ADR-0003 claims actually do on this workload

All three PlayCanvas advantages named in the ADR are real, and all three are **Gaussian splat**
advantages that do not reach a rung 3 monocular point map. The probes in `probes.ts` establish this
at runtime, and the engine source establishes why.

**Cross-asset splat budget.** `app.scene.gsplat.splatBudget` exists and is settable. Enforcement is
`GSplatWorld._enforceBudget`, which sums every non-octree placement into a `fixedSplats` total it
cannot reduce, then calls `GSplatBudgetBalancer.balance(octreeInstances, budget)` over the map of
`GSplatOctreeInstance` only. The degradation mechanism is per-node LOD selection inside a streamed
SOG octree. A plain gsplat is a fixed cost; a point-cloud `MeshInstance` is not in the gsplat world
at all. **It cannot degrade a distant point-map island.**

**Single global sort across N islands.** True for gsplats, where the unified renderer bakes every
component into one work buffer and sorts the whole buffer per frame. For ordinary geometry
PlayCanvas sorts `MeshInstance`s by `zdist`; there is no per-primitive ordering pass outside the
gsplat path in either engine. **A point map does not need one**: rendered opaque with an alpha test
it is depth-correct and order-independent, so neither engine is penalised for lacking it.

**WebGPU compute path.** The compute path is the gsplat *sorter*. A `PRIMITIVE_POINTS` draw
dispatches no compute, so the published speedup has no mechanism to arrive through. Measured on this
workload, WebGPU is **slower**, and getting it to render at all took three fixes:

- WGSL has no point-size output. `point-list` rasterises exactly one pixel per point, and
  PlayCanvas's only reference to `gl_PointSize` in its whole shader library sets it to 1.0. The
  WebGL2 image and the WebGPU image are not the same picture.
- Custom GLSL is not transpiled unless the app supplies `glslangUrl` and `twgslUrl`. Those WASM
  transpilers are not in the npm package, so a custom shader means hand-written WGSL.
- The `.opm` planar layout **cannot be bound on WebGPU at all**. `segment` is one uint16 per point,
  so the stream's `arrayStride` is 2, and WebGPU requires a multiple of 4:
  `Vertex buffer arrayStride (2) is not a multiple of 4`. PlayCanvas's debug build calls this a
  performance hint; WebGPU calls it invalid. `padSegmentChannel` widens the channel, which costs one
  CPU pass over every point and 2 extra bytes per point of VRAM. **The container should store
  `segment` as 4 bytes.**

There is a fourth divergence with no ADR claim attached, and it is the one most likely to waste a
day. The same vertex format yields a **float** attribute on WebGL2 (`vertexAttribPointer` converts)
and an **integer** attribute on WebGPU, and PlayCanvas rewrites the WGSL input struct field while
emitting a private variable of the declared type. So the WGSL body must read the bare attribute name
and never `input.<name>`, and the declared type must be one the engine's float-to-int map covers.
Getting it wrong emits `aSegment: null` into the generated struct and fails to parse, silently.

---

## Measured, 2026-08-27

Apple M3 Pro, Chrome, PlayCanvas 2.21.4 release build, 1600x900 at dpr 1, `driver=timer`,
`path=orbit`, overlay live, 2 s warmup, 4 s measured. Every row has `renderValid: true` and an
`emptyFrameMs` under 2 ms, so none of them is an environment cap.

**These are frame COST numbers, not presented frame rate.** They were taken with `driver=timer`
because Chrome would not give this session a foreground window, and `driver=raf` collects nothing
without one. They are internally consistent and comparable to another `timer` run; they are not the
number ADR-0003 asked for. **The `raf` run in a real foreground window is still owed.**

| Scene points | Islands | Frame mean | p99 | fps mean | fps 1% low | Heap | Uploaded | TFMR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 250k | 1 | 2.04 ms | 4.1 | 490.7 | 243.9 | 298 MB | 4.3 MB | 43 ms |
| 1M | 1 | 7.93 ms | 12.2 | 126.2 | 82.0 | 222 MB | 17.2 MB | 107 ms |
| 2M | 1 | 15.55 ms | 20.2 | 64.3 | 49.5 | 239 MB | 34.4 MB | 152 ms |
| 3M | 1 | 20.77 ms | 27.9 | 48.1 | 35.8 | 285 MB | 51.5 MB | 233 ms |
| 4M | 1 | 26.16 ms | 30.7 | 38.2 | 32.6 | 335 MB | 68.7 MB | 407 ms |
| 3M | **3** | 10.85 ms | 18.7 | 92.1 | 53.5 | 277 MB | 51.5 MB | 74 ms |

Reading these:

- **Cost is close to linear in point count** and there is no cliff up to 4M. The ADR's standing
  assumption that a browser can carry 1 to 4M primitives on desktop survives for point maps.
- **The 1.5M scene budget is comfortable.** 1M costs 7.9 ms, 2M costs 15.6 ms, so 1.5M lands near
  12 ms with the overlay and focus solver live.
- **Three islands at 3M beat one island at 3M**, 10.85 ms against 20.77 ms, at the same point count
  and three draw calls instead of one. Per-island draw-call cost is negligible; what dominates is
  how much of the scene is on screen, and three spread islands cover less of it than one near one.
  A single number for "3M points" is therefore meaningless without the pose, which is why the
  camera path is deterministic in elapsed time.
- **Uploaded bytes are exactly 18 bytes per point** plus change, matching the container. There is
  no hidden engine-side duplication.

### WebGL2 against WebGPU, at 1M

| Backend | Point size | Frame mean | Note |
| --- | --- | --- | --- |
| WebGL2 | 0.05 m sprites | 7.93 ms | The image the product wants |
| WebGL2 | forced 1 px | 6.91 ms | Matched to what WebGPU can draw |
| WebGPU | 1 px, forced by WGSL | 3.95 ms | Cannot draw anything else |

On matched one-pixel rasterisation WebGPU is about **1.75x faster**. That is a real advantage and it
is **not the advantage the ADR claims**: no compute shader runs on this path, so it is lower
submission and driver overhead on the same draw, not the gsplat compute sorter. It also arrives only
after the three fixes listed above, and it buys a picture the product cannot use, because one pixel
per point is not a surface. Rebuilding the cloud as expanded quads to recover point size would
multiply vertex work by six, which is very likely to spend the entire 1.75x and more.

---

## Engine constraints worth knowing before extending this

- **One `VertexBuffer` per `Mesh`.** There is no equivalent of three.js's independent
  `BufferAttribute` per channel, and the only second stream a mesh can carry is the hardware
  instancing one. A planar point map must arrive as one contiguous run of position, colour, segment,
  in that order with no padding, or be repacked on the CPU. `.opm` satisfies this for every count on
  the ladder; `packedVertexBytes` reports when it does not.
- **`ShaderDesc` is documented but not exported** from the engine's type surface, so `point-cloud.ts`
  restates it.
- **The gsplat shader API has broken twice in six months** (`gsplatCustomizeVS` deprecated in 2.15,
  removed in 2.16; the unified renderer landed in 2.19). The version is pinned exactly, not with a
  caret, and all custom shader code is in one file.
