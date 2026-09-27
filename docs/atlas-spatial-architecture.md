# Atlas spatial architecture

This contract owns how the Atlas, the browser world runtime ([interaction model](interaction-model.md)),
lays out a world's regions and moves a person through them: the spatial grammar of regions over one
continuous field, engine-neutral navigation in `@exulanica/atlas-core`, reconstruction-rung
traversal, persistent layout and neighborhoods, Map correspondence and recovery, how grounds, sky
and fog are drawn, and residency and renderer hardening. Regions come from the photographs a world
holds; an authored starter and the owned district present their own grounds on the same navigation
rules. Reconstructed traversal artifacts, physical asset streaming in the application and
full-library production scale are not built.

## 1. World decision

A world with regions is one logical semantic world, viewed at three scales:

1. **World**: all of its regions and their stable semantic organization.
2. **Neighborhood**: a bounded local field containing a comprehensible working set of
   regions and routes to other neighborhoods.
3. **Region**: a soft footprint whose interior presentation and movement model are determined by
   the reconstruction rung it actually earned.

Ground view is walking on one continuous, low-frequency field. The field supplies contact,
eye height, a horizon, between-space, and recovery. Regions rise from it and dissolve back into it;
they do not sit on platforms, acquire rims, or become disconnected levels. The Atlas Map remains the
elevated overview and direct-navigation surface.

Atlas placement is presentational. Proximity and paths may express **confirmed** semantic
relationships. They never imply where a photograph was taken, real distance, or geography. Proposed and
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
comfort and collision problems without encoding any true property of a region. A world made from
photographs draws one declared floor under each region, with its edge, because its people and
objects stand there ([saved-world entry](saved-world-entry.md#structural-rendering-boundary)); that
floor states where standing is supported, not a level.

### Disconnected scenes

Rejected. Loading a region as another scene breaks the visible continuity between occurrences in
different memories, creates a false enter/return boundary, and makes Map/ground correspondence a
reconstruction instead of a camera change.

### An infinite undifferentiated plane

Rejected. It offers no hierarchy or recovery, turns a large library into unbounded walking time,
and eventually creates renderer-precision and residency problems. One logical world does not mean
that every detailed asset is resident or that every region is traversable in one flat working set.

## 3. Spatial grammar

The continuous field is a subtly legible navigation surface. It uses restrained directional
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
labels. Approach and entry are communicated through the shared footprint transition and
relationship seam. Text is reserved for capability truth, arrival/recovery, focused evidence
actions, and the permanent non-geographic disclosure. First-use instruction belongs to the
interface, not to a renderer prop.

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
- **Rung 4: anchor motes.** A region with no reconstructed geometry draws one mote per anchor on
  the common field (`web/packages/atlas-react/src/playcanvas/anchor-motes.ts`), and people only as
  presence markers. Original photographs open in the source gallery and the Companion; none is
  drawn in the world as a card or veil standing in for geometry.

Between regions, every rung returns to the same field and eye-height model.

## 6. Persistent layout and large libraries

Determinism is not persistence. A versioned `AtlasLayoutSnapshot` is the authority for neighborhood
membership and full region transforms. It contains a monotonic region-creation ordinal distinct from
capture time. Existing position, yaw, and scale remain fixed by default; adding content places only
new regions. A rare explicit compaction produces a new version and reports both translation and
rotation.

Only confirmed semantic edges influence placement. Reliable time/place grouping may organize
capture groups, but Atlas coordinates never become factual coordinates.

The layout solver refuses more than five regions and is a local neighborhood kernel, not a
library maximum. Runtime state is split into:

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
2. a transient action offers return to the nearest region or Map;
3. an invalid surface, fall, or hard-envelope crossing restores the last safe pose with a factual
   arrival caption.

The World Index and Map remain direct-navigation escape routes. Recovery does not add permanent
dashboard chrome.

## Grounds, sky and fog

The field and the sky share one horizon value: at grazing angles and distance the field converges
analytically to the sky's haze colour, so a local rise disappears into air instead of drawing a
hard ground and sky cut, and on the Map the sky shell is hidden and the camera clears to the
field's colour. The palette roots are the active profile's
([customization contract](atlas-world-customization-contract.md#4-profile-compatibility-and-programmable-controls)).
ACES tone mapping is on, and exposure and fog are per-world presets in
`web/packages/atlas-react/src/playcanvas/atmosphere.ts`.

- **The sky is a direction rather than a place.** `composed-world.ts` draws it around the eye at the
  far plane, so no walk leaves it; a sky placed where the world opened was measured going flat from
  one kilometre ([world scale record](evaluation/2026-09-22-world-scale-baseline.json)).
- **Shadows.** The engine fits a directional shadow's depth range to the casters in view and offsets
  every receiver by a fixed ten-thousandth of that range, too little for one half-metre cube. The
  sun of every world that is not a city therefore carries a shadow bias of 0.2
  (`COMPOSED_WORLD_ATMOSPHERE`), which grows with a caster's slope to the light, and the sky casts
  no shadow. This was measured on one cube in a starter world; other shapes and photo-built worlds
  were not measured.
- **The endless walking face** of an authored starter is a grid of cells no wider than the camera's
  reach, drawn out to the recovery radius plus that reach, with its depth offset behind anything
  lying on it (`world-field.ts`), so a plate placed flat on the ground draws whole at the origin and
  at 8 kilometres. How far such a ground holds is in
  [saved-world entry](saved-world-entry.md#how-far-an-endless-ground-holds).
- **Fog order.** The sky is written to the screen as authored while lit surfaces are tone-mapped, so
  lit materials are fogged after tone mapping, toward the colour the sky shows at eye level: paper
  for the default look's sky, the camera's clear colour where no sky sphere is drawn, as in Survey
  Relief and the city. Fully fogged ground therefore reaches the screen as the sky beside it. The
  generated-tile preview fogs before tone mapping, because its skybox is tone-mapped too; particles
  and Gaussian splats also fog before tone mapping, so a splat's far fade is greyer than the sky
  around it. `web/packages/atlas-react/test/display-space-fog.test.ts` checks the fog order and the
  eye-level sky colour for each look.

On a release build the [render at distance record](evaluation/2026-09-23-render-at-distance.json)
measured, at 40 and 80 metres and at 1, 4 and 8 kilometres, a sky that keeps its arrival gradient,
a placed cube whose lit face differs from arrival by more than eight levels in none of the 11,328
pixels measured, and a frame that otherwise differs from arrival by at most three levels.

## Residency and renderer hardening

**Measurement-driven downgrade.** `RepresentationPressureController`
(`web/packages/atlas-core/src/performance-pressure.ts`) reads rolling 95th-percentile frame time,
and resident bytes over a declared budget when a caller supplies them; the binding supplies frame
time only, and hidden-tab and non-positive samples are ignored. Two overloaded windows lower the
maximum residency stage and budget; five healthy windows restore one level. It receives no device
name, user agent, GPU model or hardware allowlist.

**Precision.** `renderOriginForNeighborhood` (`web/packages/atlas-core/src/render-origin.ts`)
chooses a stable, quantized GPU origin from the active neighborhood. The binding shifts one render
root and the camera by that origin, overlays and the field apply the inverse translation, and
canonical Atlas positions never change. A world with no regions has no neighborhood, so its origin
never moves. The world field's shader capacity and typed buffers are generated from the exact
topology counts, and `web/packages/atlas-react/test/world-field-buffers.test.ts` checks that 120
regions all reach the buffer.

**Physical residency executor.** `PhysicalResidencyRuntime`
(`web/packages/atlas-react/src/playcanvas/physical-residency.ts`) executes the planner's `load`,
`cancel` and `release` actions as authenticated fetch, decode, GPU upload and publication, checking a
monotonic generation after every asynchronous step so a stale fetch can never become current;
`missing`, `unavailable`, `unsupported` and `deleted` descriptors settle as fallbacks without a
fetch, and context loss keeps decoded state, disposes GPU state and re-uploads.
`fetchAuthenticatedAsset` puts the bearer in a header, never the path, checks an expected SHA-256,
and records whether a requested byte range came back as `206` with `Content-Range` or as a whole
object. The binding's seam is `AtlasBinding.onResidencyActions`. **The application installs no
executor**: already decoded maps settle at once, and the authenticated point-map and splat routes
serve whole objects `no-store`, so useful range streaming, deployed object-store behaviour and a
target-hardware trace are not established.

**Context loss.** A WebGL context-loss event opens the complete World Index and says the 3D surface
is unavailable (`web/packages/app/src/composition/input-modes.ts`).

Not built: reconstructed navmeshes, camera-trajectory ingestion, measured panel envelopes, structural
customization previews, asynchronous physical asset fetch and disposal in the application, a
full-library adapter beyond the five-region solver, GPU batching of module realizations, and a GPU
ray or capsule acceleration structure.
