# Generated appearance

Status: PLAN ACCEPTED 2026-09-17. Structure capture, the four records and the model-free
measurements are BUILT AND TESTED on the operator's Mac, with the procedural look measured as the
baseline. NO MODEL HAS RUN, NO WEIGHTS HAVE BEEN DOWNLOADED AND NO GPU HAS BEEN RENTED. The code is
`ml/appearance/` ([its README](../ml/appearance/README.md)).

## 1. In plain words

A generative model can make a street look lived in: grime where rain runs, worn thresholds, light in
shop windows. This work finds out how far that goes when the model is only allowed to paint on top
of the structure the world already holds, and turns what works into versioned data. It never lets a
model decide where a wall is or what it is made of.

Two tracks, in order:

- **A. Model-made texture sets.** The procedural recipe keeps the exact relief (bricks, courses and
  joints where the catalog says); the model paints the colour on it. Candidates go to the texture
  lane with full records, and the texture lane publishes or not.
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

Accepted by the orchestrator on 2026-09-17, each weights licence read from raw Hugging Face card data
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

`capture/export-bench.ts` imports the bench's pure `test-street.ts` (lane 16's; read, never edited)
and writes its geometry as integers: positions in micrometres, normals in millionths, surface
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
land on its edges pixel for pixel at every pose (`.exulanica/appearance/before/sheets/`).

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

A baked tile replaces the bench when the corridor lane bakes a street: the same rasteriser runs over
tess's verified `render_batch` triangles, and the identity layer then names records.

## 5. Records

Every record is canonical JSON (sorted keys, no spaces, ASCII, integers only), named by the sha256
of its bytes, and read strictly: a repeated key, a fraction or a second spelling of the same
document is refused.

| Profile | Holds |
| --- | --- |
| `exulanica.appearance-weights/v1` | a repository at a 40-hex revision; the licence its card declares and the card's sha256, and where that licence is not a standard identifier the sha256 of the licence text this lane read; lineage of any component from elsewhere, with evidence and a pinned source; the selected files, each by LFS sha256 or git blob id |
| `exulanica.appearance-structure/v1` | the geometry and pose sources by digest; the camera; the legend; each layer by name, encoding and sha256 of its raw bytes; the rasteriser's parameters and a reason for each; the capture code's digest |
| `exulanica.appearance-generation/v1` | every weights component by role, and the digest of that listing (what a model-made maker names); code commit and source digest; container image by digest; every conditioning picture by pixel and file digest with the structure records it came from; prompt or parameters; seed; sampler settings; whether guardrails ran; GPU, driver, CUDA and library versions; every output by digest |
| `exulanica.appearance-gpu-run/v1` | provider, instance, GPU, listed rate and where it was read; start and deletion instants; billed seconds; cost at the listed rate rounded up to a micro-dollar; the estimate and its stop at 150 per cent; the generation records produced |
| `exulanica.appearance-texture-job/v1` | one session, fixed before it runs: the texture manifest it read, its candidates (backend, weights components, sampler, estimate per image), its targets (a pinned set, its recipe, the prompt, the conditioning roles), the seeds and their rule, the conditioning pictures by digest, and the stop |
| `exulanica.appearance-staged-inputs/v1` | every file the rented machine receives, by size, digest, kind and source |
| `exulanica.appearance-results/v1` | what one run produced: each record, output and measurement, what was verified, and whether and why it stopped |
| `exulanica.appearance-texture-candidate/v1` | what the texture lane is handed: the maker's generation block (models, seed, sampler, map sources), the maps, the measurements, CC0-1.0 and its statements, and the look record |
| `exulanica.appearance-third-party-look/v1` | every map cut into 1:1 crops covering every texel, what was looked at, what was found, and anything that might be third-party content |

Rules the readers hold:

- **Every fixed value has a reason.** A generation record must give exactly one reason for the seed,
  the inputs, the guardrails, the container, each component, each conditioning role and each
  sampler setting; a missing or unexpected reason is refused.
- **A regeneration is a new version, never a replay.** GPU generation is not bit-exact across
  hardware, drivers or library versions. The stored output bytes are the artifact, and every
  generation record carries that sentence verbatim.
- **Spend is recorded as it happened.** A run's billed seconds are its interval, its cost is the
  listed rate times those seconds, and a run past its stop must say why. The provider's billing
  page, read by the operator, is the only authoritative total.

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
  recipe's count), texel pitch, and decoded bytes as lane 16's binding uploads them.
- **Invented geometry**, when a GPU is available: MoGe-2 re-estimates geometry from a generated
  frame and it is compared with the exact depth. A measurement, never a verdict.

"Reads as an inhabited street" is the operator's judgement. No model answers, suggests or ranks it.
Mechanical checks may reject a broken candidate before the operator looks, and that is all.

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

The reports are `.exulanica/appearance/baseline/procedural-frames.json` (sha256
`42a6f3ad7976201d3a13c09ab8e5894fcf998f2df7568ef12ceba8fdeee1f188`) and
`published-textures.json` (`7bb5826245e37c244c5229ce82a449512cf0e8b93cc9fd59605330dcc329386e`);
the numbers are copied into `ml/appearance/evidence/baseline-measurements.log.txt`.

## 7. The GPU plan

- **One machine type:** an NVIDIA RTX PRO 6000 Blackwell, 96 GB, from MassedCompute through
  Shadeform on Brev, listed at $2.63 an hour on 2026-09-17 (no stop; deleted after every run). Every
  candidate fits at bf16 except Wan A14B, which runs in fp8. Fallback: an H200 141 GB on Nebius at
  $5.40 an hour.
- **Approved spend:** about 30 hours, a $150 ceiling including the fallback, a stop at 150 per cent
  of each run's estimate. Every run is an `appearance-gpu-run` record and a line in the committed
  ledger.
- **Consent:** each deploy carries a data-sharing consent with the named provider. The operator
  clicks it, and the lane messages the orchestrator before opening any deploy, every time, so that
  click stays the only way a machine is created.
- **The instance is announced twice:** its name, provider and hard deadline the moment it exists,
  and again when it is deleted. Both instants and the name are in the run record and in the
  committed ledger, because the orchestrator keeps a watchdog that outlives this session's.
- **The smoke job gates the session by machine-checkable conditions**
  (`exulanica.appearance-smoke-gate/v1`): both backends loaded, every output decoded at the size the
  job names, the seam ratio computed on each, seconds per image within 150 per cent of the estimate,
  no refusal anywhere, spend inside the smoke budget, and no fallback (every record's runtime names
  an NVIDIA device, and the backends refuse at load time a parameter that is not on the GPU, not the
  dtype the job named, or on the meta device because a weight did not load). If every check holds
  the session continues at once, so the machine never idles waiting for an answer; if any fails, or
  anything surprises the lane, the machine is deleted and the report says which branch was taken.
- **Local captures take the machine-wide GPU slot** (`.exulanica/bin/gpu-slot`), and a
  timing-sensitive capture takes both slots in order (`quiet-slot gpu-slot <command>`), because two
  lanes capturing at once blocked a page's main thread for ten minutes. Nothing about the rented
  machine changes.
- **Weights on the rented machine only**, downloaded at the pinned revisions and checked file by
  file against the manifests before a model loads. The Mac never installs torch: model libraries
  are in `ml/appearance`'s `gpu` extra, which only the container installs.
- **Nothing personal reaches the machine.** It receives one staged directory whose manifest lists
  every file's digest and the capture that produced it.

## 8. Track A: what runs, and what it hands over

The runner is `ml/appearance/exulanica_appearance/runner/`. It runs the same code on the operator's
Mac with a stub model (`runner dry-run`) and in the container on the rented machine, so the order
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
   lane, to its accepted answers (Q4, 2026-09-17):
   - the maker's generation block carries **models**: one entry per role naming the model's id, its
     revision and its weights manifest digest, so a reader sees which models ran without fetching;
   - it carries **generation_sha256** and only the fields a reader checks (models, seed, sampler,
     map sources); the code commit and the container digest live in the generation record alone, and
     `check_projection` compares the two so they cannot drift;
   - **map_sources** names, for every map of the class's procedural layout, either the recipe it
     rebakes from or the generation that made it. A Track A set keeps the recipe's normal and
     occlusion, so those stay rebakeable by anyone with the maker; only the painted colour is not;
   - the set is **CC0-1.0**, with three statements: that Apache-2.0 and MIT place no condition on
     outputs; that OpenMDW-1.1 is this lane's reading at a pinned revision, with the licence text's
     sha256 in the weights manifest; and that every map was looked at at full resolution before the
     set was pinned.
7. **The look.** `look.py` cuts every map into 1:1 crops that cover every texel exactly once and
   records what was looked at and what was found
   (`exulanica.appearance-third-party-look/v1`). A record whose crops do not cover a map, or whose
   finding is empty, is refused. Anything that might be a logo, lettering or a mark goes to the
   orchestrator, and the operator decides.

Seamless tiling is the lane's own, because no upstream method for these models is merged: before
each denoising step the latent grid and the control latents are rolled by an offset derived from the
seed and the step and rolled back after, so no position stays a grid edge; and the VAE encodes and
decodes with the input wrap-padded by 64 px and the result cropped, so its convolutions see the
tile's other edge instead of zeros. Every set is then held to the seam check; nothing is assumed.

The first session's job is `ml/appearance/jobs/track-a-session-1.json`: weathered variants of brick,
painted render, footway paving and carriageway asphalt, each conditioned on its own relief as depth
and as edges, four seeds each, on both Qwen-Image-2512 and Z-Image with their Fun union controls.
`track-a-smoke.json` is the cheap first run that asks only whether the backends load, tile and
decode.

## 9. Not verified

- Cosmos 3 transfer's memory and speed on a 96 GB card, and whether vLLM-Omni weights several
  controls at once for it: unpublished, and NVIDIA's documents disagree. Measured in the first B1
  hour.
- Seamless tiling on transformer image models: no published method is merged upstream; the lane
  builds it (cyclic latent shift, circular VAE decode) and holds every set to the seam check.
- Whether a generated look beats the procedural one on the bench says little about a whole street:
  the bench is one wall, a door and a kerb. The inhabited-street look is judged when the corridor
  bakes a street, at the gate route's own poses, as research references.
- The structure layers' digests were produced on one Mac (arm64); a cross-machine comparison of the
  rasteriser's bytes has not been run.
- The Qwen and Z-Image backends have never run: they are written against VideoX-Fun at a pinned
  commit and exercised on the Mac only through the stub, which stands in for a model and proves
  nothing about one. The smoke job is what finds out, in the first minutes of the first session.
- Whether the tiling schedule leaves a seamless tile with a real model is unmeasured. The seam check
  answers it on the first outputs, against the published sets' measured range.
