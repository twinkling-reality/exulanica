# Atlas spatial architecture

Status: **DECISION** for the long-term spatial grammar and engine boundaries; **ACTIVE
IMPLEMENTATION** for the frontend/core work described in section 8. This record does not claim
that backend persistence, reconstructed traversal artifacts, physical asset streaming, or
full-library production scale are complete.

## 1. World decision

The Atlas is a **grounded memory archipelago**.

It is one logical semantic world, viewed at three scales:

1. **Atlas**: the complete personal library and its stable semantic organization.
2. **Neighborhood**: a bounded local memory field containing a comprehensible working set of
   regions and routes to other neighborhoods.
3. **Region**: a soft footprint whose interior presentation and movement model are determined by
   the reconstruction rung it actually earned.

Ground view is walking on one continuous, low-frequency memory field. The field supplies contact,
eye height, a horizon, between-space, and recovery. Regions rise from it and dissolve back into it;
they do not sit on platforms, acquire rims, or become disconnected levels. The Atlas Map remains the
elevated overview and direct-navigation surface.

Atlas placement is presentational. Proximity and paths may express **confirmed** semantic
relationships. They never imply where a memory happened, real distance, or geography. Proposed and
provisional identity links may change emphasis or appear as explicitly speculative traces; they
never change a placement or neighborhood.

## 2. Rejected grammars

### Free flight

Rejected. The information architecture has no vertical-reach problem: anchors are authored into an
eye-height band and the Map already provides an overview with semantic context. Flight removes the
contact, scale, and approach cues the current preview lacks, adds avoidable optic flow, and implies a
vertical information axis that does not exist.

### Hard islands and circular platforms

Rejected. Rims, drops, glowing discs, and explicit platform edges imply discrete game levels,
platforming, and literal territory. They conflict with the documented dissolve boundary and create
comfort and collision problems without encoding any true property of a memory.

### Disconnected scenes

Rejected. Loading a region as another scene breaks the visible continuity between occurrences in
different memories, creates a false enter/return boundary, and makes Map/ground correspondence a
reconstruction instead of a camera change.

### An infinite undifferentiated plane

Rejected. It offers no hierarchy or recovery, turns a large library into unbounded walking time,
and eventually creates renderer-precision and residency problems. One logical world does not mean
that every detailed asset is resident or that every region is traversable in one flat working set.

## 3. Spatial grammar

The continuous memory field is a subtly legible navigation surface. It uses restrained directional
variation, a field/sky convergence volume, source-coloured reflection, sparse confirmed
relationship seams, and low-frequency optical interference. It does not use grass, tiles, a
generic grid, noisy terrain, decorative gradient blobs, or glowing circles. Renderer geometry
extends beyond the camera envelope; field colour then converges analytically to the sky haze at
distance and grazing angles, so a local terrain rise cannot draw a false platform edge.

Every region footprint has four bands derived from one signed-distance definition:

- **between**: outside the approach band;
- **approach**: the region is becoming the likely destination;
- **dissolve**: the outer fifth, where region and field are both partially present;
- **interior**: the reconstruction-honest local presentation.

That same footprint drives visual dissolve, streaming priority, tier distance, entry state, and
navigation constraints. A circle remains a valid broad-phase fallback for the foundational slice;
long-term footprints are authored or derived polygons, unions, or signed-distance fields. Detection
count must not determine recovered spatial coverage.

Standing and walking are communicated first through optic flow and source parallax, not permanent
labels. Approach and entry are communicated through the shared footprint transition, relationship
seam, and source-aperture registration. Text is reserved for capability truth, arrival/recovery,
focused evidence actions, and the permanent non-geographic disclosure. The rejected rounded
onboarding surface is absent from the architecture-only opening; first-use instruction is an
explicit next UX slice rather than a renderer prop.

## 4. Engine-neutral navigation

`atlas-core` owns the rules. A renderer binding supplies input and realizes the result.

The core navigation contract contains:

- a field surface sampler returning height and normal;
- a walker state with pose, horizontal velocity, vertical spring velocity, active region, and last
  safe pose;
- a camera capsule and coarse obstacle proxies;
- region footprints and reconstruction-rung traversal policies;
- a soft neighborhood envelope and deterministic recovery pose;
- Map presentation state and the saved ground pose.

One step accepts intended planar motion and returns a resolved pose, velocity, spatial phase,
collision/recovery result, and next safe pose. There is no vertical movement input and no jump.
Camera Y is sampled surface height plus eye height, approached through a bounded spring when the
surface is not flat. Small steps are automatic; steep or missing surfaces are not traversable.

Point clouds and splats are visual assets, never collision geometry. PlayCanvas supplies capsule
sweeps, height samples, and rays against coarse proxies. The same proxy layer is used by movement,
focus occlusion, and Locate vantage validation so those systems cannot disagree about whether a
surface blocks sight or travel.

## 5. Reconstruction-rung traversal

- **Rung 1: free region.** Walking is free inside a trusted coarse navigation surface and honest
  coverage boundary. The photoreal asset does not define collision directly.
- **Rung 2: constrained corridor.** Position is projected into the recovered camera-trajectory
  tube with an authored lateral envelope and look cone. Its endpoints and unseen sides dissolve;
  they do not become invisible walls pretending to be captured space.
- **Rung 3: photographic panels.** The common field connects panel viewpoints. Each panel allows
  only its measured micro-parallax; relief never becomes an invented walkable floor, and unseen
  backs are blocked by coarse panel proxies.
- **Rung 4: evidence-card grove.** Evidence surfaces and focus stops are arranged on the common
  field. The cards are citations, not reconstructed geometry. Missing or preview-unavailable media
  is visibly an archive placeholder rather than a fabricated photograph.

Between regions, every rung returns to the same field and eye-height model.

## 6. Persistent layout and large libraries

Determinism is not persistence. A versioned `AtlasLayoutSnapshot` is the authority for neighborhood
membership and full region transforms. It contains a monotonic region-creation ordinal distinct from
capture time. Existing position, yaw, and scale remain fixed by default; adding content places only
new regions. A rare explicit compaction produces a new version and reports both translation and
rotation.

Only confirmed semantic edges influence placement. Reliable time/place grouping may organize
capture groups, but Atlas coordinates never become factual coordinates.

The current five-region solver is retained as a local MVP/neighborhood layout kernel, not treated as
a library maximum. Long-term runtime state is split into:

- a lightweight full-library Atlas index;
- neighborhood sigils and stable placements;
- one resident neighborhood plus an adjacent halo;
- per-region representation states from stub to proxy to coarse to full;
- a residency planner with memory budgets, hysteresis, target pinning, and cancellation.

One scene means one logical root, camera, selection state, and placement identity. Detailed child
representations may stream in and out without moving a region or the user. Renderer-local origin
rebasing is permitted inside the binding; logical Atlas placements remain stable.

## 7. Map correspondence, direct navigation, and recovery

The Map consumes the exact same layout IDs, transforms, selection emphasis, and confirmed edges as
ground view. It forces region representation to overview tiers, shows neighborhood/region sigils,
the saved ground pose and view cone, and retains the permanent caption:

> Positions show how these memories relate, not where they happened.

Opening Map snapshots the complete ground navigation state. Closing without a target restores it
exactly. Selecting a region or Index result resolves a safe entry or anchor-vantage pose, pins the
target in residency, loads at least its proxy, and ends at one deterministic pose whether the visual
transition is motion or reduced-motion fade.

Recovery is concentric rather than an invisible hard wall:

1. beyond meaningful content, field detail and traces diminish and inward route cues strengthen;
2. a transient action offers return to the nearest memory or Map;
3. an invalid surface, fall, or hard-envelope crossing restores the last safe pose with a factual
   arrival caption.

The World Index and Map remain direct-navigation escape routes. Recovery does not add permanent
dashboard chrome.

## 8. Implemented frontend/core slice

The implementation establishes the long-term contract without fabricating reconstruction or
backend state:

- engine-neutral flat-field surface sampling, eye-height resolution, spatial phases, coarse circular
  collision, bounded full-path surface sampling, slope/step rejection, corridor constraint, soft
  envelope, last-safe recovery, semantic traces, and Map pose stack in `atlas-core`;
- immutable versioned module and recipe catalogs plus a deterministic world composer that emits
  stable IDs, element provenance, attachments, honest reconstruction fallbacks, navigation
  destinations, streaming keys, diagnostics and a validated draft topology digest;
- an appearance customization controller with isolated preview, validation, discard, immutable
  apply/rollback history, optimistic style/topology conflict checks, regional scope, and safe
  fallback for removed profiles; structural proposals fail closed pending recomposition support;
- a protected preview/apply/discard boundary shared by Settings and future Companion-origin
  proposals; Options generates Aeroheart controls from the active capability-backed manifest while
  withholding incomplete renderer fixtures, and the separately owned Companion interface is unchanged;
- a JSON-safe, versioned `AtlasLayoutSnapshot` validator carrying complete transforms, monotonic
  creation ordinals, lineage and migration reason; explicit present/missing/stale coverage; and an
  app adapter that consumes the artifact without making graph transport own Atlas layout;
- full-transform pin preservation in the layout solver, stable creation-ordinal ordering, and
  deterministic draft ordinals for newly observed regions that remain explicitly reported as
  unpersisted;
- confirmed-only placement relationships;
- deterministic semantic neighborhood partitioning for hundreds of regions, bounded chronological
  packing when no semantic relation exists, explicit semantic versus index-only routes, stable
  sigil IDs, adjacency, and a lightweight full-library index; plus a separate JSON-safe,
  versioned membership snapshot with layout-version coupling and present/missing/stale coverage;
- bounded neighborhood composition for large high-fanout corpora: ubiquitous entities cease acting
  as layout discriminators, semantic route degree is capped, and a 10,000-region regression fixture
  guards the former quadratic path;
- a pure budgeted residency planner with stub/proxy/coarse/full stages, target pinning, current and
  adjacent-neighborhood demand, cancellation, stale-completion rejection, hysteresis and release;
- a PlayCanvas continuity field with low-frequency optical interference, source reflection, soft
  region presence, confirmed relationship seams, field/sky convergence, Map ground marker, and
  source apertures for the current no-geometry state;
- PlayCanvas realization of the composed artifact using shared meshes/materials, with Aeroheart as
  the only complete user-facing identity and Survey Relief retained as an internal
  topology-compatibility regression fixture;
- a PlayCanvas residency/action seam and representation gating for the preconstructed present
  assets; physical fetch/disposal remains the loader's job rather than being simulated;
- WASD resolution through the core field instead of forcing camera Y independently;
- overview tier forcing and exact Map pose restoration;
- safe deterministic region-entry and anchor-vantage resolution through the same surface, blocker
  and line-of-sight rules as walking and focus; one exact 1.2-second transition sampler plus the
  reduced-motion zero-duration path. The renderer preserves the validated rung-4 arrival position
  and turns only its presentation orientation toward the canonical source body;
- projected, keyboard-focusable Map region sigils derived from live region transforms, with Map to
  ground travel; citation-level “Locate in Atlas” with exact anchor arrival and refocus;
- one-shot last-safe recovery events and contextual, truthful arrival/failure feedback with no
  permanent recovery chrome;
- removal of ambient generic anchor callouts so attention remains single-valued; place, object, and
  event motes now have distinct hard silhouettes, while people remain paired presence brackets;
- tests for surface-derived eye height, spatial bands, collision, recovery, corridor limits, Map
  restoration, confirmed-only layout, durable layout parsing/coverage, full-transform pinning,
  hundreds-region neighborhoods, budget/cancellation/hysteresis, direct navigation, Map targets,
  citation navigation and the app persistence seam.

Not completed in this slice: backend authority for topology/style/placement/neighborhood versions,
canonical cryptographic digests, reconstructed navmeshes, camera-trajectory ingestion, measured
panel envelopes and media, structural customization previews, asynchronous physical asset
fetch/disposal, origin rebasing, a full-library app adapter beyond the current five-region local
solver kernel, GPU batching of module realizations, scalable world-field buffers, or a GPU
ray/capsule acceleration structure. Those remain phased work and are not represented as shipped
behavior.

## 9. Repository audit

| State | Grounded finding |
| --- | --- |
| Decided and kept | One semantic scene, pointer-lock WASD plus Interact/Summon, distance tiers, soft dissolve bands, Map as a camera presentation, presentation-only coordinates, single-valued focus, reconstruction rungs, and the permanent non-geographic disclosure. |
| Implemented but contradictory | Movement was planar X/Z with camera Y reset to 1.62, but there was no surface, contact, collision, step, boundary, or recovery. Map altitude passed through ground distance tiers. Pointer unlock cleared keys but allowed residual velocity. A “pinned” layout preserved X/Z while silently recomputing yaw and scale. |
| Missing at audit; core/frontend contract now implemented | Persistent-layout schema and consumption, distinct region-creation ordinal, deterministic neighborhood index, residency budgets, safe direct-navigation poses, last-safe recovery feedback, Map marker and region targets, and a spatial test suite. Durable storage, authored rung artifacts, real streaming and view-cone polish remain open. |
| Unsuitable at target scale | The app sliced the first five records and the solver rejected more than five; all detail was described as resident; a graph write disposed and rebuilt the rendered world; footprints were estimated from anchor count; ambient neutral labels competed with focus; and capture time stood in for region creation order. |
| Honest present constraint | The app supplies no point maps. The correct current rung is source-bearing apertures, unavailable-evidence contours, and semantic motes on the shared field, not fabricated terrain or reconstructed shells. |

## 10. Phased roadmap and ownership

### Phase A: spatial authority

**Frontend/core status: implemented; backend durability pending.**

Define and persist `AtlasLayoutSnapshot`, region creation ordinals, authored/derived footprint data,
safe entry poses, and layout migrations. `atlas-core` owns validation and deterministic transforms;
the graph/backend owns durable storage and version conflicts; the app only adapts snapshots. Exit
criterion: adding or confirming unrelated graph data cannot move an existing region without an
explicit layout migration.

### Phase B: neighborhoods and residency

**Core planner/index status: implemented; physical streaming and production full-library adapter
pending.**

Partition the full-library index into stable semantic neighborhoods, add sigils and adjacency, and
implement a budgeted residency planner with target pinning and cancellation. `atlas-core` owns the
planner and state machine; PlayCanvas owns assets, origin rebasing, and disposal; the app owns no
parallel world model. Exit criterion: a library much larger than five regions remains navigable
without loading every detailed asset or changing logical coordinates.

### Phase C: rung traversal

**Status: foundational policies only; measured pipeline artifacts pending.**

Ingest trusted nav surfaces for rung 1, trajectory corridors for rung 2, measured panel envelopes
for rung 3, and real source media for rung 4. The reconstruction pipeline supplies measured
artifacts; `atlas-core` validates capability and resolves movement; PlayCanvas builds only the
coarse proxies and visuals the rung allows. Exit criterion: collision, focus occlusion, Locate, and
visual coverage agree under every rung fixture.

### Phase D: direct navigation and recovery

**Frontend/core status: region and citation travel, reduced motion, Map targets, and recovery
feedback implemented; residency-aware asynchronous arrival and far-field action cues pending.**

Add Map/Index target travel, residency-aware safe-vantage resolution, reduced-motion transitions,
soft far-field cues, and explicit last-safe recovery feedback. `atlas-core` owns target resolution
and invariant state; the app owns commands and truthful captions; PlayCanvas realizes the camera
transition. Exit criterion: Map cancel restores bit-for-bit ground state and every target either
arrives at a validated pose or reports why it cannot.

### Phase E: scale and comfort hardening

**Status: pending representative production assets and profiling.**

Profile streaming churn, large-coordinate rebasing, collision broad phase, focus rays, frame pacing,
and the authored daylight/contrast modes across representative large libraries. Exit criterion: movement and
Map transitions meet the performance budget without reducing evidence legibility or introducing
permanent dashboard chrome.
