# Refactor Earth into an owned, editable world and artificial society

Status: **PRODUCT CORRECTION AND END-TO-END IMPLEMENTATION PLAN**
Date: 2026-09-13

## Decision

Orimera will not use Google Maps, Apple Maps, or any other visualization-only
service as the corpus for walking, collision, extraction, modification, model
processing, training, persistence, or export.

The product target is an Orimera-owned runtime representation generated from
open or expressly licensed geographic sources whose exact permitted operations
have been verified before ingestion. The first complete slice must let a person:

1. walk through a recognizable real place on continuous collision;
2. interact with a building or object through independently sourced identity;
3. bring that permitted object into an alternate personal world;
4. modify the authored instance without changing its immutable source;
5. reload and undo the change;
6. encounter a bounded synthetic society whose state the Companion can explain.

Changing from NYC to another city does not solve a source-rights problem. Source
fitness, not visual attractiveness, determines whether a place can become an
editable world.

## Correction to prior Earth work

The Google Photorealistic 3D Tiles integration is a read-only visualization
adapter. It may remain isolated behind an optional reference flag, with required
attribution, but it is not an accepted implementation of the editable Earth
journey. It must never supply:

- collision or terrain queries;
- selected building or object identity;
- copied geometry, textures, point clouds, splats, or generated assets;
- model or agent input;
- persistent geographic content;
- training or evaluation data.

Do not spend more time improving that adapter unless a separately approved
reference-view requirement needs it. Do not delete it reflexively: first identify
tests, frame math, residency code, semantic selection, and Companion wiring that
are reusable without retaining a Google dependency in the owned-world path.

This correction does not erase useful work. The existing source-admission,
operation-rights, content-addressed asset, geographic-frame, semantic feature,
authored-version, unified Selection, Companion, PlayCanvas, and residency
foundations should be reused after their current behavior is verified.

## Product and visual north star

The world is a **living atlas**:

- geography is physically reliable and editable;
- memories appear as point clouds, splats, or other evidence-bound media;
- authored and fantasy changes are visually expressive but never presented as
  observations of reality;
- synthetic inhabitants produce persistent movement, relationships, needs,
  events, and history;
- the Companion explains source facts, authored changes, simulation state, and
  uncertainty without flattening them into one kind of truth.

The owned city should use a hybrid representation rather than one universal
point cloud:

| Layer | Preferred representation | Reason |
| --- | --- | --- |
| Terrain, roads, sidewalks | Tiled solid meshes | Continuous collision and navigation |
| Buildings | Procedural or licensed meshes with PBR materials | Editability, instancing, LOD, and interiors |
| Distant city | Simplified massing, impostors, and shared materials | City-scale coverage |
| Memories | Point clouds or Gaussian splats where source rights allow | Preserve Orimera's memory language |
| Fantasy additions | Original meshes, particles, vegetation, light, and behaviors | Clearly authored transformation |
| Society | Structured agents with bounded visible avatars | Persistent simulation independent of rendering |

Do not choose photorealism at the cost of holes, false identity, unusable
collision, or prohibited derivatives. Coherent stylized realism with strong
lighting, atmosphere, sound, movement, and district-specific materials is
preferred over an exact-looking but non-editable map.

## Architectural rule

**Persistent world meaning must be independent of its rendered representation.**

The same building identity may render as a distant mass, a procedural mesh, a
memory splat, or a later higher-quality licensed asset without changing source
identity, simulation identity, authored placement, or history.

Keep these layers explicit:

1. **Source records**
   Provider identity, revision, bytes or stable reference, geographic frame,
   attribution, and operation-specific rights.
2. **Semantic world**
   Places, parcels, roads, buildings, transit, containment, and supported
   relationships.
3. **Derived assets**
   Content-addressed terrain, navigation, mesh, material, collision, and LOD
   artifacts with derivation lineage.
4. **Authored world**
   Versioned instances, transforms, modifications, fantasy additions, and undo.
5. **Simulation**
   Synthetic agents, schedules, resources, events, and persistent state.
6. **Representation**
   Replaceable PlayCanvas renderers selected by distance, device budget, and
   source capability.

Agents and the Companion reason over authorized semantic and simulation state,
not pixels or provider meshes.

## Source-rights gate

No source enters implementation because an agent, demo, article, or viewer says
it is open. Read the governing primary license and record exact permission for:

- runtime display;
- local storage and backups;
- coordinate conversion and retiling;
- geometry and texture derivation;
- indexing and semantic crosswalks;
- collision and navigation generation;
- modification and composition;
- commercial use;
- model inference and training, separately;
- screenshots, video, user-created output, and export;
- redistribution or non-extractable streaming;
- retention after provider or contract termination;
- required attribution and modified-content notices.

Every source receives an operation-rights matrix. Unknown means denied. Conflicts
between combined sources must be resolved before asset generation. A public
download URL is not a license.

Candidate discovery may examine official open-data portals, government terrain
and LiDAR, road and building datasets, transit feeds, commissioned captures, and
commercial datasets with amended rights. This brief selects no provider. The
next implementation must verify coverage, current availability, quality, and
license terms from primary sources.

Real residents must not be reconstructed or simulated from private or sensitive
data. Society inhabitants are synthetic. Aggregated public statistics may shape
population-level parameters only when their license and privacy use are valid.

## First vertical slice

Choose one bounded district only after the source gate. NYC remains eligible if
its verified sources are fit; another city may be chosen if it provides a better
rights and quality package.

Target a district large enough to demonstrate continuous traversal and city
composition, but small enough to rebuild deterministically. Record the exact
geographic boundary, source revisions, coordinate frame, vertical datum, and
quality limitations.

The slice includes:

- terrain or an explicitly authored ground surface;
- roads and sidewalks with navigation topology;
- procedural or licensed building geometry;
- original or permitted materials;
- collision and clearance;
- stable semantic selection;
- one source-backed building copied into an alternate world as an authored
  instance;
- at least one visible modification and one fantasy addition;
- persistent reload and undo;
- a minimum of 100 logical synthetic inhabitants, with a measured device-based
  cap on visible avatars;
- deterministic schedules and a persistent event log;
- Companion questions grounded in place, authored, memory, and simulation state.

An invented height, facade, interior, resident, or event must be labeled as
generated or simulated. It must not be presented as an observed real-world fact.

## Refactor plan

### Phase 0: Protect and inventory

1. Start from clean main and record the baseline commit.
2. Read `docs/product-direction.md`,
   `docs/world-composition-contract.md`, this brief, current source-admission
   contracts, world-object contracts, Selection, Companion, and PlayCanvas code.
3. Inventory the Google-specific commits and classify each changed symbol as:
   reusable, optional reference-only, superseded, or remove.
4. Preserve tests and negative evidence. Do not rewrite history or destroy
   unrelated work.
5. Confirm protected databases, credentials, processes, worktrees, and current
   cloud state before mutation.

### Phase 1: Source and quality decision

Use parallel research lanes for:

- terrain and elevation;
- roads, sidewalks, parcels, and transit;
- buildings and attributes;
- imagery, materials, LiDAR, and 3D assets;
- license compatibility and commercial/export rights;
- measured visual and geometric samples.

Produce a source matrix and reject candidates lacking mandatory rights or a
representative sample. Compare at least two viable district/source packages.
Do not contact vendors, purchase data, provision GPUs, or accept new terms
without explicit operator approval.

### Phase 2: Contracts and canonical world

Trace existing implementation before adding schema:

- `EnvironmentRepository` and operation rights;
- environment feature indexes and geographic frames;
- durable environment instances;
- place bridges and unified content Selection;
- world versions, receipts, undo, and asset withdrawal.

Extend only missing contracts. The canonical world needs stable source and
feature identities, containment, source revision, operation rights, geographic
frame, and derivation lineage. It must not depend on PlayCanvas entities or a
particular procedural generator.

### Phase 3: Deterministic district compiler

Build an engine-neutral pipeline that converts admitted sources into immutable,
content-addressed runtime artifacts:

- tiled terrain and ground;
- road and sidewalk surfaces;
- navigation graph and collision;
- building massing and modular facade parameters;
- PBR material references;
- spatial and semantic indexes;
- multiple LODs and bounds;
- attribution and modification manifests.

Generation must be deterministic from source digests, generator version, seed,
and configuration. Original source remains immutable. Generated completion is a
separate authored contribution.

### Phase 4: PlayCanvas owned-world runtime

Generalize the useful environment streaming and residency behavior behind a
provider-neutral interface. Keep `AtlasBinding` as the graphics owner.

Implement:

- local geographic frame and coherent origin rebasing;
- camera-aware tile traversal and bounded residency;
- atomic parent/child LOD handoff;
- continuous ground and capsule movement;
- walls, steps, slopes, and clearance;
- safe stopping when support is unavailable;
- semantic reticle selection independent of render LOD;
- device budgets and lifecycle cleanup.

Never hide missing support with an invisible floor. Loading, decode, or source
withdrawal failures must be visible and recoverable.

### Phase 5: Select, bring, modify, reload

The defining interaction is:

1. Walk to or search for a source-backed building.
2. Select its independent semantic identity.
3. Ask the Companion what is known, generated, and permitted.
4. Choose **Bring into my world**.
5. Create a preview referencing the source and accepted derived asset.
6. Modify a supported property or add a fantasy component.
7. Apply through the existing typed proposal and version gate.
8. Reload the version and verify the instance.
9. Undo without modifying or deleting the source asset.

The UI must distinguish source geography from destination placement and must
show why an operation is allowed or refused.

### Phase 6: Artificial society

Start with a deterministic, inspectable simulation. Do not call an LLM for every
agent on every frame.

Use:

- fixed simulation ticks;
- synthetic identities and households;
- needs, roles, schedules, destinations, and relationships;
- path planning over the owned navigation graph;
- persistent events and bounded memory;
- aggregate systems such as time, weather, transit, and resources;
- deterministic replay from seed and event log.

Use models selectively for high-level planning, dialogue, summarization, and
authored proposals. Model output is never direct authority over canonical state.
All writes pass typed validation and versioning. Training is a later measured
option, not a prerequisite for the first society.

### Phase 7: Companion and retrieval

Extend the existing unified Selection path rather than creating a simulation-only
query service. The Companion must be able to answer:

- What building is this, and which source supports that identity?
- What did I bring into this alternate world?
- Which memories are explicitly connected to this place?
- What modifications are authored rather than observed?
- Which synthetic inhabitants are here, and why?
- What happened here during the simulation?

Answers disclose source, authored, memory, and simulated clauses separately.
No imported city or generated resident implies a personal visit or real person.

### Phase 8: Visual bakeoff and scale

Before city-wide generation, render the same small area in three treatments:

1. cinematic stylized realism;
2. solid procedural city with point-cloud memory overlays;
3. more surreal or painterly composition.

Evaluate recognizable form, emotional quality, editability, frame pacing,
material repetition, night/day behavior, memory integration, and Companion UI.
The expected default is treatment 2, but evidence decides.

After the district passes, scale in this order:

1. larger district;
2. one complete city;
3. several source-diverse cities;
4. global low-detail coverage with selected high-detail cities.

Do not process all Earth before proving source compatibility, tile economics,
simulation partitioning, and visual quality in one city.

## GPU and cloud policy

GPU rental is not the first step. GIS ingestion, topology, deterministic
procedural generation, and the initial society are primarily CPU, RAM, storage,
and engineering problems.

Use the current machine for the smallest district benchmark. Provision Brev or
another GPU only for an identified workload with an input, expected output,
budget, timeout, and cleanup plan, such as:

- reconstruction from licensed captures;
- texture or asset generation;
- point-cloud or splat processing;
- measured self-hosted inference;
- later fine-tuning from permitted simulation data.

Persist outputs outside ephemeral instances, record actual cost, and delete the
instance immediately after the bounded job. No GPU purchase, rental, or training
run is authorized by this brief alone.

## Acceptance gates

Do not call the vertical slice complete until recorded evidence shows:

### Source and lineage

- Every input has a primary-source license and operation-rights record.
- Every runtime asset binds source digest, generator version, parameters, and
  attribution.
- Visualization-only content contributes no derived asset or model input.

### Walking and streaming

- A person spawns at a measured eye height on visible support.
- They traverse the named district continuously for at least five minutes.
- Collision handles ground, walls, steps, slopes, and LOD transitions.
- Unknown support stops safely and visibly.
- Origin rebasing does not move semantics, collision, or authored instances out
  of alignment.

### Interaction and editing

- A selected building resolves to the same semantic identity across LOD changes.
- **Bring into my world** creates a source-linked authored instance.
- A supported modification previews, applies, reloads, and undoes.
- The immutable source remains unchanged.
- Unsupported rights or operations fail before generation or write.

### Society

- At least 100 logical synthetic inhabitants advance deterministically.
- Visible avatars stay within a measured frame budget.
- Schedules, paths, relationships, and events survive reload.
- No synthetic identity is represented as a real resident.

### Companion

- Answers distinguish sourced facts, personal memories, authored changes, and
  simulation events.
- Unified place retrieval shows match reasons and no false visit claims.
- A model cannot bypass operation rights, proposal validation, or version checks.

### Visual quality and performance

- Ground-level screenshots and video show coherent terrain, buildings, materials,
  inhabitants, memory layers, and authored changes.
- No large holes, floating blocks, invisible collision, or repeated material
  grid dominates the accepted route.
- Frame time, draw calls, resident bytes, tile requests, generation time, and
  simulation cost are measured on named hardware.
- The app remains usable when optional reference providers, models, or cloud
  services are disabled.

## Stop conditions

Stop and report before further spending or implementation if:

- no candidate source grants a mandatory operation;
- representative data cannot meet pedestrian quality;
- two required source licenses are incompatible;
- an exact visual target would require tracing or deriving a prohibited source;
- collision cannot be generated from admitted data;
- the proposed architecture duplicates existing authority without evidence;
- a GPU workload lacks valid input, measurable output, or cleanup;
- the district cannot meet bounded browser budgets.

Failure at a gate changes the source or scope. It must not be relabeled as
acceptance.

## Required handoff

The implementation chat must maintain a task list, use parallel agents for
independent audits, and integrate changes only after reviewing their evidence.
Commit messages are one line, contain no em dash, and contain no co-author
trailer. Do not push, deploy, purchase data, contact vendors, or provision paid
compute without explicit permission.

At completion, report:

- source and rights decision;
- architecture and migrations;
- generated asset lineage;
- live visual and interaction evidence;
- walking and simulation measurements;
- Companion and retrieval behavior;
- tests, failures, costs, and remaining gates;
- exact commits, with a clean working tree.

## Copy-ready prompt for a new chat

```text
Continue Orimera from the current clean main containing
docs/briefs/2026-09-13-owned-world-society-refactor.md. Read that brief,
docs/product-direction.md, docs/world-composition-contract.md, and the current
source-admission, world-object, Selection, Companion, PlayCanvas, and simulation
implementations before planning.

Use a team of agents. Do not guess. Verify source licenses and implementation
claims from primary sources and actual code. The corrected goal is an
Orimera-owned, editable, walkable real-place representation and bounded
artificial society generated only from open or expressly licensed inputs.
Google and Apple content are not editable corpora and may not supply collision,
selection identity, extraction, derivatives, model input, persistence, training,
or export.

First inventory and classify the existing Google/NYC work as reusable,
reference-only, superseded, or removable. Then execute the brief end to end:
source-rights and quality matrix, one bounded district decision, any minimal
contract repairs, deterministic district compiler, PlayCanvas streaming and
collision, semantic selection, Bring into my world, supported modification,
reload and undo, at least 100 logical synthetic inhabitants, and grounded
Companion retrieval across source, memory, authored, and simulated state.

The visual target is a hybrid living atlas: solid terrain, roads, sidewalks and
editable procedural or licensed buildings; original PBR materials; bounded
avatars; point clouds or splats for authorized memories; and clearly authored
fantasy changes. Persistent world meaning must remain independent of rendering.

Do not rent GPUs, purchase data, contact vendors, deploy, or push without my
explicit approval. Use the current machine for the smallest benchmark first.
Preserve protected databases, credentials, worktrees, history, and negative
evidence. Do not call anything accepted until live evidence proves continuous
walking, stable source-backed selection, source-linked extraction into an
alternate world, modification, reload, undo, society persistence, grounded
Companion answers, visual quality, and measured browser budgets.

Commit completed work with one-line messages containing no em dash and no
co-author trailer. Do not push.
```
