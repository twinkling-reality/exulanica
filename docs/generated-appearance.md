# Generated appearance

Status: research, not a product surface. Track A measured 64 model-made texture sets on exact
structure (section 9): seams sit inside the published sets' own range, structure edges are kept,
and every picked tile was looked at at 1:1. No model-made set is published or pinned, and Track B
has not run. Generated assets (section 11), static pieces a model makes for a style pack, are a
prototype: the records, the post-process and the writer run with a stub in place of the models, and
no model has made a piece. The code is `ml/appearance/` ([its README](../ml/appearance/README.md)).

## 1. In plain words

A generative model can make a street look lived in: grime where rain runs, worn thresholds, light in
shop windows. This work finds out how far that goes when the model is only allowed to paint on top
of the structure the world already holds, and turns what works into versioned data. It never lets a
model decide where a wall is or what it is made of.

Two tracks, in order:

- **A. Model-made texture sets.** The procedural recipe keeps the exact relief (bricks, courses and
  joints where the catalog says); the model paints the colour on it. Candidates are handed to the
  [texture package](texture-package.md) with full records, and publishing one is its decision.
- **B. Structure-to-photo frames.** The bench street is rendered as exact structure (depth, surface
  identity, edges) at fixed poses and along a walk, a model generates frames on that structure, and
  the frames are measured against it and against the procedural look. These are research
  references, never a shipped renderer and never gate evidence.

A third track, baking generated appearance back onto surfaces per tile, is designed only if B shows
a clear gain.

## 2. The rule that does not bend

Structure is the truth; the model supplies appearance only.

- Geometry, identity and material come from the world's records. A model is conditioned on them and
  never writes them.
- Every generated pixel is attributable: a frame is generated at a camera whose structure record
  holds a per-pixel `identity` layer, so each pixel names the surface and texture set it dresses.
- Generated appearance is invented content: every record says `truth: invented` and
  `generated: true`, and none is evidence about a real place.
- No personal photograph, and nothing derived from one, is sent to a GPU machine or a model. The
  only inputs are the bench geometry, committed tiles, committed texture sets and prompts written
  from the catalog.

## 3. Models

Each weights licence was read from raw Hugging Face card data
at a pinned revision and held to [license-matrix.md](license-matrix.md) section 6 (self-hosted
weights only under Apache-2.0, MIT, CC-BY-4.0, OpenMDW-1.1 or a public-domain dedication). The rows,
revisions and lineage evidence are in section 12 of that document; the pinned file lists are the
manifests in `ml/appearance/weights/`.

| Id | Role | Repository | Licence | Bytes pinned |
| --- | --- | --- | --- | ---: |
| B1 | frames, first | `nvidia/Cosmos3-Nano` | OpenMDW-1.1 | 34,922,407,982 |
| B2 | frames | `alibaba-pai/Wan2.2-Fun-A14B-Control` | Apache-2.0 | 69,049,460,840 |
| A1, B3 | textures, frames | `Qwen/Qwen-Image-2512` with `alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union` | Apache-2.0 | 57,704,574,910 + 3,512,432,536 |
| B4 | frames | `Tongyi-MAI/Z-Image-Turbo` with `alibaba-pai/Z-Image-Fun-Controlnet-Union-2.1` | Apache-2.0 | 32,848,305,533 + 6,712,485,600 |
| A2 | textures | `Tongyi-MAI/Z-Image` with the same union control | Apache-2.0 | 20,538,488,559 |
| A3 | weathered variants | `black-forest-labs/FLUX.2-klein-base-4B` with `DiffSynth-Studio/Template-KleinBase4B-ControlNet` | Apache-2.0 | 15,980,141,295 + 7,751,122,097 |
| M | measurement only | `Ruicheng/moge-2-vitl-normal` | MIT | 1,323,815,904 |

In total 250,343,235,256 bytes, downloaded only on the rented machine.

What decided the list:

- **Cosmos Transfer 1 and 2.5 are blocked, Cosmos 3 is not.** Transfer, Predict, the Cosmos
  DiffusionRenderer and the Cosmos guardrail models are under the NVIDIA Open Model License, which
  section 6 excludes even self-hosted. Cosmos 3's public weights are OpenMDW-1.1 and do transfer
  from edge, blur, depth and segmentation. Cosmos 3 runs with guardrails off: OpenMDW-1.1 has no
  guardrail clause, the guardrail models themselves are under the excluded licence, and the inputs
  are synthetic structure with no people. Every generation record states this.
- **No licence-clean model splits an image into material maps well** (Marigold is OpenRAIL++-M,
  CHORD research only, RGB-X non-commercial, DiffusionRenderer excluded), so track A keeps the
  recipe's relief and has the model paint colour.
- **Components are checked, not only repositories.** Z-Image's VAE is byte-identical to
  FLUX.1-schnell's Apache release; FLUX.2 klein's VAE is covered by the publisher's statement that
  the FLUX.2 autoencoder is Apache 2.0; Wan Fun's VAE and text encoder are byte-identical to
  Wan-AI's release. A component whose licence falls outside section 6 blocks its candidate.
- **Inference code** is Apache-2.0 (vLLM-Omni, diffusers, VideoX-Fun, DiffSynth-Studio).
  `NVIDIA/cosmos-framework` reports NOASSERTION on GitHub and is not used until its licence files
  are read.

## 4. Structure capture

`capture/export-bench.ts` imports the bench's pure `test-street.ts`, read and never edited, and
writes its geometry as integers: positions in micrometres, normals in millionths, surface
coordinates in millimetres. The bench's poses, eye height, camera and default sets live in
`bench.ts`, which imports PlayCanvas and cannot run in Node, so the exporter copies those lines
verbatim and `tests/test_bench_capture.py` fails when `bench.ts` stops saying any of them.

`capture/raster.py` casts a ray through every pixel centre with the bench's camera (PlayCanvas's
`lookAt` with +Y up, 70 degrees vertical, 80 mm near plane) and records, per pixel:

| Layer | Encoding | Meaning |
| --- | --- | --- |
| `depth` | uint32 | micrometres along the view axis; 0 where nothing is hit |
| `normal` | int16, 3 | world-space unit normal times 32767 |
| `identity` | uint16 | the legend index of the surface hit; the legend names each surface and its texture set |
| `surface_s`, `surface_t` | int32 | surface coordinates in micrometres, the texture placement frame |
| `edges` | uint8 | bit 1 identity change, bit 2 crease, bit 4 step (off-plane neighbour or hit next to nothing) |

The step bit uses a plane test, not a depth ratio, because ground seen at a grazing angle changes
depth quickly between rows without any step in the geometry.

Captured: the bench's six named poses at its own 1440 by 900, and a walk along the footway of 121
frames at 1280 by 720 and 24 fps (7 m in 5 s, 1 m out from the kerb line, looking 8 m ahead and
1.6 m toward the wall). The geometry digest is
`af4ddaccdf825153e867c22ea6c1c89ddb30add5a7e5aa32ae310e0df6174171`, and the capture code's
`fc44fb81785043901948c8141e517551ed1b3c84203527d5b7629a5ba086f833`.

**The structure lines up with the render.** The exact edges drawn over the bench's own GPU render
land on its edges pixel for pixel at every pose.

Conditioning pictures (`capture/encode.py`) are derived from the layers when a generation's inputs
are prepared, and each generation record names them by the sha256 of their raw pixels and of the
file the model read:

- depth: inverse depth normalised between the nearest and farthest hit over the frames conditioned
  together, so a walk has one range and does not flicker;
- segmentation: one fully saturated hue per identity, stepped by the golden angle so neighbouring
  surfaces never share a colour; the colour carries no meaning, and the material is named in the
  prompt;
- edges: the exact `edges` layer, never a Canny pass over a render, which would copy the procedural
  texture's joints into the structure;
- normals: the world normal in camera axes, for controls that read normals.

Capturing a baked tile instead of the bench, with the same rasteriser over tess's verified
`render_batch` triangles and records as the identities, is not built.

## 5. Records

Every record is canonical JSON (sorted keys, no spaces, ASCII, integers only), named by the sha256
of its bytes, and read strictly: a repeated key, a fraction or a second spelling of the same
document is refused.

| Profile | Holds |
| --- | --- |
| `exulanica.appearance-weights/v1` | a repository at a 40-hex revision; the licence its card declares and the card's sha256, and where that licence is not a standard identifier the sha256 of the licence text read; lineage of any component from elsewhere, with evidence and a pinned source; the selected files, each by LFS sha256 or git blob id |
| `exulanica.appearance-structure/v1` | the geometry and pose sources by digest; the camera; the legend; each layer by name, encoding and sha256 of its raw bytes; the rasteriser's parameters and a reason for each; the capture code's digest |
| `exulanica.appearance-generation/v1` | every weights component by role, and the digest of that listing (what a model-made maker names); code commit and source digest; container image by digest; every conditioning picture by pixel and file digest with the structure records it came from; prompt or parameters; seed; sampler settings; whether guardrails ran; GPU, driver, CUDA and library versions; every output by digest |
| `exulanica.appearance-gpu-run/v1` | the provider, instance and GPU; start and deletion instants; billed seconds and what they cost; the estimate and its stop at 150 per cent; the generation records produced |
| `exulanica.appearance-texture-job/v1` | one session, fixed before it runs: the texture manifest it read, its candidates (backend, weights components, sampler, estimate per image), its targets (a pinned set, its recipe, the prompt, the conditioning roles), the seeds and their rule, the conditioning pictures by digest, and the stop |
| `exulanica.appearance-staged-inputs/v1` | every file the rented machine receives, by size, digest, kind and source |
| `exulanica.appearance-results/v1` | what one run produced: each record, output and measurement, what was verified, and whether and why it stopped |
| `exulanica.appearance-texture-candidate/v1` | what the texture package is handed: the maker's generation block (models, seed, sampler, map sources), the maps, the measurements, CC0-1.0 and its statements, and the look record |
| `exulanica.appearance-third-party-look/v1` | every map cut into 1:1 crops covering every texel, what was looked at, what was found, and anything that might be third-party content |

Rules the readers hold:

- **Every fixed value has a reason.** A generation record must give exactly one reason for the seed,
  the inputs, the guardrails, the container, each component, each conditioning role and each
  sampler setting; a missing or unexpected reason is refused.
- **A regeneration is a new version, never a replay.** GPU generation is not bit-exact across
  hardware, drivers or library versions. The stored output bytes are the artifact, and every
  generation record carries that sentence verbatim.

Layers are stored zlib-compressed by the sha256 of their raw bytes, so the compressor never enters an
identity. PNG is written for models and people and is never an identity, for the reason
[texture-package.md](texture-package.md) section 3 gives.

## 6. Measurements, with no model

The same rules measure the procedural look and every generated look, so the numbers compare.

- **Edge agreement** (`metrics/edges.py`): picture edges by a fixed rule (Sobel on Rec. 709
  luminance, thinned, a step of 16 levels or more) against the exact edges layer, within 2 pixels.
  Recall falls when a look dissolves a kerb or a reveal. Precision falls with any texture, so it is
  read before against after, never alone.
- **Per surface** (`metrics/regions.py`): pixels, mean colour, luminance spread, and the density of
  picture edges away from any geometry edge. A window painted on a blank wall raises that density.
- **Flicker along the walk** (`metrics/stability.py`): each frame is carried into the next with the
  exact depth and both exact cameras. Where the next frame sees the same point (its depth agrees
  within 5 mm or 1 per cent and it is the same identity, away from edges), the luminance
  difference is what swims or flickers.
- **Texture sets** (`metrics/textures.py`): seam ratio (the wrap difference over the neighbour
  differences beside it), low-frequency share (luminance variance at 4 cycles per tile or fewer,
  which predicts visible repetition), dominant cycles along u and v (a set on a module must show the
  recipe's count), texel pitch, and decoded bytes as the tile runtime's binding uploads them.
- **Invented geometry**, when a GPU is available: MoGe-2 re-estimates geometry from a generated
  frame and it is compared with the exact depth. A measurement, never a verdict.

"Reads as an inhabited street" is a named human judge's judgement. No model answers, suggests or ranks it.
Mechanical checks may reject a broken candidate before that judge looks, and that is all.

### Baseline: the procedural look (bench look version 1, eight published sets)

Edge agreement at the six poses:

| Pose | Exact edge pixels | Recall | Precision |
| --- | ---: | ---: | ---: |
| cornice | 2,310 | 76.4 % | 2.2 % |
| door | 5,781 | 92.3 % | 4.9 % |
| footway | 6,316 | 86.9 % | 5.1 % |
| kerb | 8,966 | 65.9 % | 2.2 % |
| street | 4,490 | 84.6 % | 8.5 % |
| wall | 5,042 | 83.6 % | 3.0 % |

Flicker along the 121-frame walk, 120 frame pairs: the mean luminance difference averages 2.672
levels; the median pair's 95th percentile is 11.945 levels and the worst is 14.952. At the door
pose the brick wall's luminance spread is 40.6 levels and the footway's 14.8.

The eight published sets: seam ratios from 0.29 to 1.77 across every map and axis (all seamless by
construction, which is the range a candidate is compared with); brick shows its recipe's 24 courses
and a 16-cycle half bond; texel pitch 0.977 mm (storefront metal) to 2.344 mm (cast concrete and
limestone); 16,777,212 decoded bytes a 1024 set.

The numbers are in `ml/appearance/evidence/baseline-measurements.log.txt`, from reports whose
sha256 it records.

## 7. Where generation runs

- **One machine type:** an NVIDIA RTX PRO 6000 Blackwell with 96 GB, rented for a run and deleted
  after it. Every candidate fits at bf16 except Wan A14B, which runs in fp8.
- **A run has a stop.** A job states its estimate per image and stops at 150 per cent of it, and
  the container runs under a hard time limit.
- **Track B has not run.**
- **The smoke job gates the session by machine-checkable conditions**
  (`exulanica.appearance-smoke-gate/v1`): both backends loaded, every output decoded at the size the
  job names, the seam ratio computed on each, seconds per image within 150 per cent of the estimate,
  no refusal anywhere, and no fallback (every record's runtime names an NVIDIA device, and the
  backends refuse at load time a parameter that is not on the GPU, not the dtype the job named, or
  on the meta device because a weight did not load). If a check fails, the machine is deleted and
  the report says which.
- **Weights on the rented machine only**, downloaded at the pinned revisions and checked file by
  file against the manifests before a model loads. The Mac never installs torch: model libraries
  are in `ml/appearance`'s `gpu` extra, which only the container installs.
- **Nothing personal reaches the machine.** It receives one staged directory whose manifest lists
  every file's digest and the capture that produced it.

## 8. Track A: what runs, and what it hands over

The runner is `ml/appearance/exulanica_appearance/runner/`. It runs the same code locally
with a stub model (`runner dry-run`) and in the container on the rented machine, so the order
below is exercised before any GPU is rented.

1. **Staging, on the Mac.** `exulanica.appearance-staged-inputs/v1` is the only directory the
   machine receives. Staging holds each target's container to the sha256 the committed texture
   manifest pins, derives the conditioning pictures from that set's own relief, copies the weights
   manifests the job names, writes the job, and lists every file with its size, digest, kind and
   source. Three kinds exist: the job, a weights manifest, and a conditioning picture whose source
   is a committed texture set. Nothing else has a kind, so no capture, photograph or workspace file
   can be staged.
2. **Weights, on the machine's host.** `scripts/fetch-weights.py` downloads exactly the files the
   manifests name, from their pinned revisions, and checks each against its sha256 or git blob id
   as it lands. It uses the standard library only: no client, no token, no repository listing.
3. **Verification, in the container, before any model code is imported.** The staged directory must
   hold exactly its listed files with their digests; then every weights file of every candidate is
   checked, file by file. Only then is a backend built, and only then does torch load.
4. **Generation.** One generation per target, candidate, conditioning role and seed, in that fixed
   order. The seed is derived from the job's stated rule. Each output is stored as raw RGB bytes by
   sha256 (a PNG beside it for people), measured for seams and low-frequency share, and recorded.
5. **The stop.** Before each generation, if the time run so far plus that candidate's estimate per
   image would pass the job's stop at 150 per cent of its estimate, the run stops and says so. The
   container also runs under a hard `timeout`, and the instance is deleted from the Mac.
6. **The handover.** `handoff.py` builds `exulanica.appearance-texture-candidate/v1` for the texture
   package:
   - the maker's generation block carries **models**: one entry per role naming the model's id, its
     revision and its weights manifest digest, so a reader sees which models ran without fetching;
   - it carries **generation_sha256** and only the fields a reader checks (models, seed, sampler,
     map sources); the code commit and the container digest live in the generation record alone, and
     `check_projection` compares the two so they cannot drift;
   - **map_sources** names, for every map of the class's procedural layout, either the recipe it
     rebakes from or the generation that made it. A Track A set keeps the recipe's normal and
     occlusion, so those stay rebakeable by anyone with the maker; only the painted colour is not;
   - the set is **CC0-1.0**, with three statements: that Apache-2.0 and MIT place no condition on
     outputs; that OpenMDW-1.1 is the reading recorded at a pinned revision, with the licence text's
     sha256 in the weights manifest; and that every map was looked at at full resolution before the
     set was pinned.
7. **The look.** `look.py` cuts every map into 1:1 crops that cover every texel exactly once and
   records what was looked at and what was found
   (`exulanica.appearance-third-party-look/v1`). A record whose crops do not cover a map, or whose
   finding is empty, is refused. Anything that might be a logo, lettering or a mark goes to a
   human reviewer, who decides.

Seamless tiling is this package's own, because no upstream method for these models is merged: before
each denoising step the latent grid and the control latents are rolled by an offset derived from the
seed and the step and rolled back after, so no position stays a grid edge; and the VAE encodes and
decodes with the input wrap-padded by 64 px and the result cropped, so its convolutions see the
tile's other edge instead of zeros. Every set is then held to the seam check; nothing is assumed.

The first session's job is `ml/appearance/jobs/track-a-session-1.json`: weathered variants of brick,
painted render, footway paving and carriageway asphalt, each conditioned on its own relief as depth
and as edges, four seeds each, on both Qwen-Image-2512 and Z-Image with their Fun union controls.
`track-a-smoke.json` is the cheap first run that asks only whether the backends load, tile and
decode.

## 9. Session 1, measured

One RTX PRO 6000 Blackwell 96 GB machine ran it, from 2026-09-17T21:57:29Z to
2026-09-18T00:05:56Z. The machine-readable record is
[`gpu-run-a1.json`](../ml/appearance/evidence/gpu-run-a1.json), and the whole session, including
its three false starts, is in [the evidence log](../ml/appearance/evidence/track-a-session-1.log.txt).

The smoke job ran first, 2 generations at 512 px, and its gate passed all seven conditions; that is
what allowed session 1 to start. Session 1 then ran 64 generations at 1024 px in 1785 s: four
published targets, two candidates, two conditioning roles, four seeds, nothing stopped. a1 is
Qwen-Image-2512 with the Fun union control at 50 steps, 32 to 33 s an image; a2 is Z-Image with the
Fun union control at 25 steps, 20 s an image. Both fit the card with no offloading.

Measure it again from what the run wrote:

    cd ml/appearance && .venv/bin/python -m exulanica_appearance measure session \
      --repository ../.. --results OUT --staged STAGED --out session-1-measurements.json

- **Seams**: over both axes of all 64 outputs, min 756618, median 988545, max 1335650 per million,
  where 1000000 is no seam. The eight published procedural sets, seamless by construction, read
  290000 to 1770000 on the same measure, so every one of the 128 readings sits inside the range
  the eight published procedural sets occupy. This package's own tiling (the per-step cyclic roll with the wrap-padded encode and
  decode) is the only reason for that, and this is the measurement of it.
- **Structure kept**: the share of the conditioning picture's own edges that have an output edge
  within 2 px. Depth conditioning holds everywhere, 97.2 to 100 per cent. Edge conditioning holds on
  brick (97.6), asphalt (98.4 to 100) and paving (99.0 to 99.8) and fails on painted render, whose
  relief is a field of 40 small cells: a1 kept 60 per cent of it and a2 kept 0.8 per cent, because a
  smooth painted wall answers dense outlines with almost no edges. Depth is the role for cell-field
  materials; either role serves brick and paving.
- **Precision is not a pass condition**: a generated tile invents gum, grime and scuffs no
  conditioning edge asks for, which is what the track is for. It ran from 194835 (paving a1, the most
  invented detail) to 1000000 (asphalt and render, almost none).
- **Module retention**, amplitude at the period the recipe itself states, as a ratio to the published
  set's amplitude at that period, and only for the two makers whose recipes state a module
  (`loom.brick`: 8 units per course, 24 courses; `loom.paving`: a 3 by 3 flag grid). Brick a1 reads
  1025 per mille along u and 173 along v; a2 reads 480 and 755; paving reads 1952 to 5157. Read it as
  a comparison and not a pass mark: the procedural brick paints a razor-sharp mortar line at exactly
  24 cycles, so a generated tile that keeps the courses but varies their tone reads well below 1000,
  and the generated paving's joints are darker than the recipe's, so it reads above. What says the
  structure survived is the recall above. `loom.asphalt` and `loom.render` state cells and no module,
  so nothing is measured for them.
- **Low-frequency share**: every candidate is at or below its own published set (brick 5510 and 433
  against 22998; asphalt 33086 and 14217 against 35716; paving 185580 and 121600 against 211011;
  render 48781 and 34555 against 215799), so these tiles repeat no worse than what ships.

Eight outputs were picked, one per target per candidate by the seam ratio closest to 1, and every
texel of every pick was looked at at 1:1 before anything was offered onward: findings in
[`session-1-findings.json`](../ml/appearance/look/session-1-findings.json), records in
`ml/appearance/look/records/`. No lettering, numeral, logo, badge, signature, watermark, road marking
or utility mark was found in any of the 32 crops, and nothing that reads as a particular real place.
One defect was found by eye and then traced. A dark band three pixels tall crosses painted render a1
at row 616, 48 grey levels below the tile's own median, dashed. The dash period along it is exactly
8.0 px, which is the autoencoder's own latent cell pitch, at 21.6 grey levels and the strongest
period in that line; the band is centred exactly on a latent row boundary (616 = 8 x 77); it is
neutral in all three channels; the conditioning picture has no line there; and 1 of the 64 outputs
carries it. Nothing learned from photographs lands on precisely the autoencoder's cell pitch, so this
is a defect of this package's latent pipeline and not third-party content. Which stage is not
settled: the per-step roll fitted this one output (step 12 shifted the rows by 51, and 128 - 51 = 77)
and then failed over the population, where 47 per cent of strong lines sit on a boundary the seed's
schedule visited against 44 per cent expected by chance. The latents were not retained, so per-latent-row
statistics at each step remain unrecorded. That set is not offered while the defect
stands.

No candidate has been handed to the texture package, and Track B has not run.

## 10. Not verified

- Cosmos 3 transfer's memory and speed on a 96 GB card, and whether vLLM-Omni weights several
  controls at once for it: unpublished, and NVIDIA's documents disagree. It would be measured in
  Track B's first hour, and Track B has not run.
- Seamless tiling on transformer image models: no published method is merged upstream; this
  package builds it (cyclic latent shift, circular VAE decode) and holds every set to the seam check.
- Whether a generated look beats the procedural one on the bench says little about a whole street:
  the bench is one wall, a door and a kerb. The inhabited-street look has not been judged on a
  baked street at the gate route's own poses.
- The structure layers' digests were produced on one Mac (arm64); a cross-machine comparison of the
  rasteriser's bytes has not been run.
- MEASURED 2026-09-17: both backends ran, tiled and decoded on the card, and the tiling schedule
  leaves seams inside the published sets' own range (section 9). What is still unmeasured is a
  second machine: every number in section 9 comes from one instance, one driver and one image.
- Whether the appearance a model invents suits the world's other materials is unknown: four targets
  ran, and the catalog holds eight makers.
- Which stage of the latent pipeline leaves the dark 8 px-pitch band in painted render a1. It is
  traced to the latent grid and cleared of being third-party content (section 9). The runner
  measures the latent the decoder is about to read and writes where its rows and columns stand out
  beside each output (`exulanica.appearance-latent-lines/v1`, in `diagnostics/`), so outputs that
  carry that diagnostic answer it: a line whose latent row stands 8 or more robust sigma out is the
  latent's, and a line over a level latent is the decoder's or the crop's. Nothing from that set goes
  onward until it is answered.

## 11. Generated assets (prototype)

A style pack dresses a world kind's look roles (`family.leaf`, such as `prop.bench`), and each part
of a kind states its slot: a box in millimetres with a front. A generated asset is a static piece
for one look role, made by an open model and turned into a plain `exulanica.static-glb/v1`
container, so it enters the product through the
[workspace asset admission](workspace-asset-admission.md) exactly as an upload does. The rule of
section 2 holds with the slot as the structure: the kind fixes the slot and what the engine does
with the part, and the piece is appearance inside it.

**Status.** Prototype. The records, the post-process, the writer and a contact sheet run end to end
with a stub in place of the models (`python -m exulanica_appearance assets dry-run`), through the
same runner a job on a rented GPU uses, and a test
prepares every stub piece through the product's own static profile and finds it placeable at the
size its receipt states. Both routes have run on rented GPUs (Nebius AI Cloud, one RTX PRO 6000
Blackwell, Serverless AI jobs); [`docs/evaluation/2026-10-07-nebius-generated-assets-trial.json`](evaluation/2026-10-07-nebius-generated-assets-trial.json)
records every job, including each failed attempt and why, with its container times and cost, and
every piece by receipt. On the same 16 trial items, route A made 13 pieces (11 within every check)
at 8 to 10 seconds a piece; on route A's 13 cut-outs, route B made 7 (5 within every check) at about
40 seconds a mesh and was refused 6 times for a zero-area triangle. A demo job of eight thing kinds
at four variants in the cozy look made 32 pieces on route A, 27 within every check; several of them
fill only part of their kind's box, because the model draws them deeper than the box allows. A piece
made to a thing kind is now refused (`box_fill`) below 800 per mille of its box's longest side: rerun
with that check, the same 32 items gave 8 within it, and a described well filled its box where the bare
word had drawn a pillar. Words from the box's proportions in the prompt helped no kind and turned the
benches end-on, so the prompt keeps its first wording. The contain fit now also tries the piece turned
90 degrees about its up axis and keeps whichever fills the box more (post-process v2, the choice
recorded in the receipt): rerun, 10 of the 32 were within every check, three market stalls among them,
and benches drawn end-on came back to their length. Described as the thing kinds state them, cafe
tables with their chairs reached 1,332 to 1,374 mm of a 1,720 mm box and lamp posts gained their single
arm, still short of their 6 m box. The requests, jobs, results and receipts are in
`ml/appearance/evidence/generated-assets-trial-1/` and `generated-assets-demo-1/` to
`generated-assets-demo-4/`, and each rented job's record in `ml/appearance/evidence/gpu-run-aijob-*.json`. The budgets are the style
pack format's, read from [`assets/style-packs/piece-budgets.v1.json`](../assets/style-packs/piece-budgets.v1.json)
by `exulanica_pieces.budgets`, the same file the [style pack contract](style-pack-contract.md) holds
pieces to.

**Routes.** Both start from a concept picture of the piece drawn by an already-pinned image model
from a prompt the request alone determines, cut out by BiRefNet:

| Route | 3D model | Shape and colour | Weights licence |
| --- | --- | --- | --- |
| A | `microsoft/TRELLIS-image-large` | shape from the mesh decoder, colour sampled from the Gaussian decoder at each vertex | MIT; image encoder DINOv2 (Apache-2.0) |
| B | `stepfun-ai/Step1X-3D`, geometry only | watertight shape; colour from the concept picture and the palette | Apache-2.0; encoder configuration from DINOv2 with registers (Apache-2.0) |

Refused under [license-matrix.md](license-matrix.md) section 6, read 2026-10-04:
`microsoft/TRELLIS.2-4B` and `TencentARC/Pixal3D` (their pipelines condition on DINOv3, whose
licence is revocable and amendable by its publisher, and remove backgrounds with RMBG-2.0, CC
BY-NC 4.0); Step1X-3D's texture model (it runs on Stable Diffusion XL, OpenRAIL++); and the upstream
post-processing of both routes (nvdiffrast's NVIDIA Source Code License limits use to
non-commercial; a Gaussian rasteriser of the INRIA lineage; GPL mesh repair). This package's own
post-process replaces it.

**Where the code is.** The formats every side shares are one package, `exulanica_pieces` at the
repository root, which imports neither the product nor `ml/`: its records, vocabulary and colour
table are plain Python the product may read, and its `geometry` subpackage (the steps below and
the writer) needs numpy and is imported only by the GPU job and tooling. Import contracts and
`tests/test_pieces_boundary.py` hold those rules. The GPU job itself (backends, runner, Nebius
commands) stays in `ml/appearance/exulanica_appearance/assets/`.

**Post-process** (`exulanica_pieces/geometry/`), every step recorded in the receipt:

| Step | What it does |
| --- | --- |
| orient | a proper rotation taking the model's up to glTF +Y and its front to +Z |
| simplify | to the family's triangle budget (a stand-in clusterer in tests; the rented machine runs a quadric simplifier behind the same interface) |
| fit | `contain` scales uniformly into the slot; `fill` (doors, windows) also refuses a piece the page could not stretch to its slot within 0.8 to 1.25 per axis; `tile` (boundaries) fits one module; the base centre goes to the origin |
| palette | one swatch per triangle, the nearest in OKLab to the model's colour, flat shaded |
| write | `POSITION`, `NORMAL` and `COLOR_0` only; no texture, extension or compression |

`COLOR_0` is `VEC4` `UNSIGNED_SHORT` normalized: the first three channels are the swatch's sRGB
bytes through the committed table [`assets/colour/srgb8-linear16.v1.json`](../assets/colour/srgb8-linear16.v1.json)
(IEC 61966-2-1 to linear, times 65535, rounded half to even; all 256 values distinct), the fourth
65535. The page and the writer read the same table, so a stored colour names its swatch exactly.

**Records.** `exulanica.generated-asset-request/v2` (look role, slot, fit, an optional plain
description of at most 80 characters, the pack's id, version, digest, palette and style words, the
budget with the digest of the piece budgets file it came from, variants and route; a request is
read only against that file, and a `v1` request, whose budget came from an earlier built-in table,
still reads as it did), `exulanica.generated-asset-job/v2` (one batch fixed before it runs: the
prompt template's version, every prompt and seed, the weights listing, code, container and stop at
150 per cent of the estimate; a `v1` job, written before the template had a version, still reads) and `exulanica.generated-asset/v1` (one piece: every input by digest, every step, the GLB,
what was measured against the budget, origin generated, truth invented, CC0-1.0 and the
regeneration sentence). A seed is drawn from the request digest under a prefix. A request built
from a recipe catalog entry names it (`recipe`: the catalog's version and the entry's sha256) and
carries the entry's box fill bar when it states one (`box_fill_minimum_permille`).

**Recipes.** What to ask a model for when a thing kind needs a piece comes from the kind's own
document (`exulanica_pieces.recipes`, plain Python the product may read): the look role is
`prop.<kind>` for a thing a hand holds and `fixture.<kind>` for any other object, the slot is the
kind's box, the hold is its holdable offer's grip and axis with the hand's widest section from the
body plan catalog, the subject is the look role's leaf (or the kind's appearance words where it has
them), four variants, route A. So a kind nobody has written anything for, a model-drafted one
included, generates with no catalog edit. A drafted creature's recipe states route C, the creature
route, with its appearance words and its extent (length along the depth) as its box; a being with no
box of its own (a person, a light) has nothing to generate. The catalog
[`assets/catalogs/generation/piece-recipes.v1.json`](../assets/catalogs/generation/piece-recipes.v1.json)
holds only what was measured to do better for one kind version: plain words for the concept picture
(lower case, no numeral, at most 80 characters), a variant count, or a box fill bar other than 800
per mille, each entry with the measurement that justified it. Version 1 describes the well, the
lamp post and the cafe table, each measured on Nebius against the bare kind name; the gate's arch
wording was never run against the bare name, so the gate has no entry. An entry's words are catalog
content, so a piece made with them is shared across workspaces; any other description is cached
within its workspace.

**Held pieces.** A piece made for a thing a hand holds (a sword, a lantern) is made to its thing
kind: the request takes the kind's box as its slot and carries the kind's grip, a point in the
kind's slot frame (whole millimetres, x across, y deep with the front at +y, z up, from the base
centre) and the direction the thing extends from the hand, with the widest section a hand closes
around from the holder's body plan. The concept picture is posed by that direction ("standing
upright, its handle at the bottom"; "hanging from a ring or handle at its top"). After the contain
fit the receipt measures how full the box is along its longest side and the section through the
grip, a slab 10 mm either side of the plane across the direction; the piece is refused (`hold_fill`)
below 800 per mille, so a model that laid a sword down is not shrunk into a stub, and refused
(`grip_section`) when nothing crosses the grip, the section is wider than the body plan's figure, or
the grip point lies outside it. `tests/fixtures/generated-piece/sword-case.v1.json` holds one held
piece's request, job and receipt from the dry run for readers of these records elsewhere. An output is cached
under the digest of its request, weights listing and post-process version; a request that carries a
description may hold a person's words and is cached within its workspace only.

**The job.** A job runs on Nebius Serverless AI from a public Python image
pinned by digest and installs at start from a hash-locked requirements file per route
(`ml/appearance/container/assets/lock-route-a.txt` and `lock-route-b.txt`, binary wheels only), so
no image is built for it. It fetches the pinned upstream code as GitHub archives and holds each
extracted tree to its commit's tree id, computed without git; Step1X-3D's package is patched to
import only its models, and TRELLIS's to import only its image-to-3D pipeline (its text-to-3D
pipeline needs open3d, which the job does not install). Modules the upstream code imports but the job
never uses, among them plyfile (GPL-3.0), easydict (LGPL-3.0) and pymeshlab (GPL-3.0), are replaced by
small stand-ins (`container/assets/standins/`) that may be named but refuse to be used, and
nvdiffrast is never installed. The job works on the machine's own disk: weights are fetched at their
pinned revisions and every file is checked against its manifest (a Hugging Face cache snapshot within
its repository's cache folder); the DINOv2 file TRELLIS loads through torch.hub is not on Hugging
Face, so its digest is recorded on its first fetch and later jobs are held to it. TRELLIS loads from a
view of its weights that lists only the models they hold; Step1X-3D is given its cut-out as a file
and its latents are decoded in float32 over every cell of the grid (its default decoder marks the
cells it does not refine as NaN); and TRELLIS's attention runs on PyTorch's
`scaled_dot_product_attention`, because the pinned xformers dispatches some calls to a kernel built
for an earlier GPU generation that fails on Blackwell. Outputs reach the job's bucket only by plain
writes, each file once, every minute and at exit, since the bucket mount refuses a file's mode and
times. The job record's stop bounds the whole job, setup included. On the operator's machine,
`python -m exulanica_appearance assets nebius stage | submit | status | fetch | cancel | clear |
usage` drives the aws and nebius command lines; submit refuses a job whose worst case (its timeout,
at least the service's one hour, times the day's rate) exceeds the allocated bound and can validate a
job without creating it; the bucket key is read from its file in one process and handed to each aws
command in that command's environment only, never on a command line. Route A's colour comes from TRELLIS's Gaussians; route
B's is a prototype projection of the cut-out seen from the front, approximate by construction.

**The warm session** (built, not yet run on a rented machine). A cold job spends about 11 minutes
starting, installing and fetching weights before its first piece, while a piece itself takes 8 to 10
seconds. A session is one Serverless AI job (`MODE=session` in `job.sh`) that loads its route once
and serves batches from the bucket until it has had no ready batch for its idle stop (10 minutes by
default), finds a stop marker, or reaches its hard stop (at most one hour). The bucket carries data
only: a batch is a job record and its request documents in `queue/<job sha256>/`, with `ready.json`
copied last naming every other file by digest. The session reads an entry with the same strict
readers a single job uses and refuses, without running anything, an entry holding any other file, a
symbolic link, a file whose digest differs, a request its job does not name, an item that starts
from a cut-out, or a job naming another code archive than the one the session was started with and
`job.sh` checked. It takes the oldest ready entry nobody has claimed, but never one whose own stop
would carry it past its hard stop; writes `claimed/<job>.json`; runs the batch; publishes the
outputs; then writes `done/<job>.json` with each request's milliseconds. A heartbeat file is written
every 30 seconds. On this Mac, `python -m exulanica_appearance assets session record | stage |
start | submit | status | stop | fetch | charges` makes the session record, stages it, starts it
inside the allocated bound, queues a batch (refused when any of its requests already has a receipt
for every variant under the same cache key), reads the latest heartbeat, writes the stop marker,
fetches what the session wrote, and turns the done markers into charge lines. A run record of
profile `exulanica.appearance-gpu-run/v2` carries those lines: each request's milliseconds at the
listed rate, rounded up, and the account it is charged to; the rest of the session's cost is start-up,
loading and idle time. The session serves route A; the creature route joins it when that route lands.

**Planned, not built:** the operator's choice of route from the blind side-by-side pictures, route
B's zero-area refusals, pieces that fill a thin box (gates, benches, lamp posts), a shopfront
request shaped for a shallow fill slot, the admission's `generated` rights
basis, a measured session run (how soon a file written from this Mac appears in the mount's listing,
and memory with two routes loaded), the product's own writer to the queue under the spending
authority, and the Companion's offer of new pieces for a pack.

