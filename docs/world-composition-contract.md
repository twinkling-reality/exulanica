# Unified world composition and retrieval

Status: **DECISION** for product and architecture direction; **PARTIAL** implementation.
Updated 2026-09-12 following the operator's Iceland selection and fantasy-world example.

## Purpose and authority

A person can build an interactive world from their memories, selected real-world
places and objects, and fictional creations; describe changes in ordinary
language; and find the resulting content through the same query and filter model.
Earth is a source of usable environmental content inside this experience, not a
separate orbital map or a navigation-only replacement for the interactive world.

This contract develops [product-direction.md](product-direction.md), which owns
product priority. It supersedes a reconstruction-only or separate-map reading of
older plans. Existing API/schema/package contracts describe what is supported
now; this document does not silently extend them. Implementation evidence is retained in scoped evaluation records, including the
[experience integration](evaluation/2026-09-12-experience-integration.json) and
[Earth scope correction](evaluation/2026-09-12-earth-experience-correction.json).
A new task must read the product direction, this contract, the relevant live
API/data contracts and the newest scoped evaluation records before writing its brief.

The World Memory Model is the system's representation and behavior across memory,
creation and interaction. It is not a claim that one trained neural network
already understands or generates an entire world. WMP is a signed projection of
authorized state, not the live database or a runnable scene by itself.

## Reference user journey

1. Select an Icelandic valley or waterfall from a source permitted for this use.
2. Bring that selection into an alternate personal world beside a memory scene.
3. Ask: "Blend this valley into my garden and put a floating castle above it."
4. Inspect the resulting placement, seam treatment and generated addition; apply
   the supported changes, reload them, and undo them without modifying originals.
5. Ask: "Show everything related to Iceland." See imported Iceland content,
   supported personal Iceland memories and Iceland-derived authored variations,
   with an explanation of each relationship and filters to narrow the results.

This is a target journey, not a demonstration completed by current fixtures.
Imported Iceland content does not prove a visit. A fantasy scene inspired by
Iceland does not prove it existed there. A moved landscape retains its source
identity while its current placement belongs to the person's created world.

## One connected representation with distinct responsibilities

Share stable identities and explicit relationships across source, meaning,
geometry, authored state and runtime. Do not flatten everything into an opaque
mesh, a caption embedding, a browser-only state object or a second Earth database.
Do not create a service per content type without a measured reason to cross the
existing authority boundary. Exact schema and API changes need scoped briefs.

| Conceptual record | Required meaning | Current basis and missing extension |
| --- | --- | --- |
| Source and asset | Provider/original identity, revision or observation time, content digest where available, permitted operations and derivation lineage | Evidence/artifact machinery exists; external Earth asset admission and operation-specific rights need contracts |
| Place and entity | Stable identity, supported names, aliases and explicit geographic containment/association | Place/entity links exist; canonical external geography resolution and containment across content kinds are not established |
| Selection and segment | Geographic boundary, existing feature ID, or supported 3D subset tied to source revision and extraction method | Photo masks and lifted scene voxels exist; reusable Earth extraction and complete editable objects do not |
| Authored instance | Source asset reference, owning world/version, local transform, role and modification history | Region-local authored objects and alternate versions exist; persistent Earth/environment anchors and extracted-content references need extensions |
| Search projection | Authorized content references with result kind, match reason, place relationship, time and lineage | Capture/entity Selection exists; unified retrieval over imported assets, scenes and authored versions is missing |
| Rendered representation | Geometry/materials, levels of detail, collision and current residency derived from those records | PlayCanvas and asset runtimes exist; detailed Earth integration remains unaccepted |

The table names responsibilities, not new SQL tables or wire field names. Preserve
current authority, transactional writes, dependency invalidation and replaceable
renderer/model interfaces. Shared public place definitions must not expose private
associations, trip history or derived personal content across workspaces.

## Geography, placement and time

Keep four different relationships explicit: captured at, depicts, derived from,
and currently placed in an authored world. They may point to different places.
A photograph taken from outside a boundary may depict a landmark inside it.
Iceland-themed generated content may be inspired by Iceland without depicting a
specific real site. Preserve uncertainty and human corrections instead of forcing
all associations to confirmed geographic facts.

Use named coordinate frames, units, scale, orientation, altitude reference and
transform lineage between geographic, reconstruction, region-local and rendering
frames. A camera's GPS position is not full scene registration. Origin rebasing
changes the rendering frame, not source geography or authored identity. Moving an
instance changes its placement, not the original asset or its source location.

Retain capture/observation time, provider revision time and edit time separately.
More observations of the same physical state, a later real-world change and a
fictional modification are different histories. Asset resolution must disclose
missing content or version drift instead of silently replacing a selected source
with today's provider tile.

## Selection and extraction

Use geographic boundaries for areas, existing feature identities where available,
and segmentation where semantic objects are not already separated. A country is
not an image mask; a tile boundary is not necessarily an object's boundary.

An image mask identifies visible pixels. Lifting it through calibrated geometry
can produce a scene subset, but does not establish complete hidden surfaces,
watertightness, usable texture, collision or editable material boundaries. Each
extracted asset must record the actual method, input revision and available
quality. Any generated completion is a separate derived contribution, never an
observed back side. Selection must remain stable across tile refinement and
retain dependencies when an object spans tiles or scenes.

Before publication as a usable world asset, validate geometry/material delivery,
coordinate alignment, streaming behavior, intended collision and visible quality.
Keep the original immutable; placement and subsequent changes belong to authored
versions. Rendering a fragment once is not proof that extraction, reuse or reload
works.

## Unified queries and filters

Extend the existing typed Selection mechanism, authorized read projections and
Companion planning path; do not add a parallel Earth-only search or let a model
write SQL. Resolve place names to permitted identities. Geographic containment,
source lineage and supported entity links establish relationships; embeddings can
help discover or rank content but cannot establish that a person visited Iceland.

For the reference example, the intended results are:

| Request | Intended selection semantics |
| --- | --- |
| Everything related to Iceland | Broad union of authorized imported geography, personal memories and derived/inspired creations; retain each match reason and content kind |
| My memories from Iceland | Supported personal capture/place associations; exclude imported content and fictional derivations as evidence of a visit |
| Iceland landscapes I brought into this world | Imported selections associated with Iceland and actually referenced by the chosen authored version |
| My fantasy versions of Iceland | Authored/generated lineage or explicit inspiration associations, labeled as such |
| Iceland memories with a named person from a chosen year | Combine authorized person/place/time constraints using the shared filter semantics |

Include origin/content kind, supported place association, world/version, people,
time, object type and availability as explicit filters when implemented. Define
time/filter applicability per kind rather than silently reusing capture dates for
imports. An unavailable asset may have an authorized metadata result without
being renderable; withdrawn/private metadata must not leak in results or counts.
Broad results need bounded paging and deduplication without erasing distinct
captures or authored variations. The current bounded capture/entity result model
does not yet provide this cross-content result contract.

## Natural-language editing

Translate a request into supported, typed operations with resolved content and
world/version references: select, place, transform, style, blend, create or attach
a reviewed behavior. These are target operation categories, not an assertion that
the current registry implements them. Reuse the existing preview/apply/rollback
pattern and reject stale bases or unsupported actions explicitly.

A compound request must expose what each operation will change. Do not quietly
substitute a color change for a castle or an appearance preset for geometric
blending. Long-running extraction/generation publishes candidate assets through
the existing job/asset boundary before an edit can refer to accepted output.
Define dependencies, failure recovery and apply semantics so partial completion
cannot leave an unexplained half-applied world. The backend validates references,
rights, parameters and version state; prose from a model is not authority.

Geometric joins, material transitions, scale/style changes, generated structures
and physical/fictional behaviors have separate compatibility requirements. A
single appearance prompt or segmentation model does not implement all of them.
The system must retain source and generated contributions through editing,
selection, reload and export. Users may choose edits freely within supported
capabilities without turning those edits into claims about their real memories.

## Data-source fitness and visual quality

Evaluate sources for the intended operations: reference display, extraction,
indexing, storage, modification, composition, redistribution/export and optional
model processing. Permission to stream a pretty map does not imply these rights.
Keep reference-only sources separate from assets admitted for reuse, including
capability checks at read, job, edit and export boundaries. No model training or
new provider purchase is authorized by this document.

Google's Map Tiles policies, checked 2026-09-12, restrict non-visualization use,
including image analysis, machine interpretation and geodata extraction, and
restrict derived overlays and indexing/storage. Under those published conditions,
that feed is not the default editable Earth corpus for this journey. A separate
applicable agreement must be verified before claiming otherwise. See the
[primary policy](https://developers.google.com/maps/documentation/tile/policies).
Choose open or appropriately licensed sources through concrete coverage, quality
and permitted-use checks; this contract selects no replacement vendor or model.

A featureless terrain material and simplified untextured building blocks do not
meet the operator's desired detailed real-world environment. Neither a successful
tile load nor mechanical interaction tests establish visual acceptance. Measure
actual ground-level views, preserved source textures/geometry, refinement,
seams, lighting and performance while existing interactions work. Compare named
locations and retain captures, source limitations and rejected outcomes. Do not
promise uniform global or street-level coverage from a city-specific sample.

## Existing implementation and staged delivery

At the reviewed main source d32d0e7c1013f3ce2d569adce59133896575a6a7:
- [Authored objects and alternate versions](world-objects-contract.md) support
  bounded editing and history; arbitrary Earth extraction and persistent geographic
  anchors are not part of that contract.
- `exulanica/selection/plan.py` and `executor.py` resolve captures/entities through
  place/entity/time/text constraints, not the unified content kinds above.
- `exulanica/selection/proposal.py` drafts bounded appearance proposals, not general
  structural creation, blending or arbitrary asset generation.
- `exulanica/ingest/scene_segments.py` and the scene-segments route support lifted
  scene segmentation; segment availability is not complete-object extraction.
- [WMP](world-memory-package.md) has an authored-world extension, but portable
  Earth selection/anchor/rights semantics need a separately versioned extension
  and receiver capability tests. Do not silently alter WMP 1.0 or imply that its
  signature supplies missing asset bytes or runtime behavior.

Implement in dependency order, with exact file ownership and evidence per stage:

1. **Source admission and shared identity.** Prove a permitted reusable real-world
   selection, canonical place association, source version and explicit frames;
   define the versioned environment/asset contract and detailed rendering target.
2. **Durable composition and retrieval.** Place that selection with a personal
   scene in an authored version, save/reload/undo, and query their shared place
   identity with distinct origin and match reasons. Establish typed cross-content
   results, permissions, withdrawal and asset availability behavior together.
3. **Assisted structural creation.** Execute one natural-language compound edit,
   including a real geometric or generated addition; preview/apply/undo with
   measurable asset quality, existing interactions and retained lineage.
4. **Transfer and expansion.** Add package compatibility and permitted asset
   resolution, test a second geography/source and expand supported operations
   through measured needs rather than a speculative universal abstraction.

The current frontend Earth lane remains bounded by its issued brief; these stages
are not permission to edit its unowned backend/query/package files. Future briefs
must name the missing contracts and resolve scope before implementation.

## Acceptance that future tasks must preserve

The first complete vertical slice uses a clearly identified permitted geographic
selection, an authorized memory scene and a derived fantasy variation. A synthetic
fixture can validate mechanics but must not be reported as that personal journey.
The Iceland query example is the semantic test case; a different supplied place
may be the first measured visual demonstration without claiming Iceland coverage.

Prove all of the following before calling that slice complete:
- Detailed environment and authored/memory content coexist with existing movement,
  reticle/object interaction and Companion interface in the production engine.
- Selection, modification, save/reload and undo preserve originals, source
  identity, authored placement and version lineage, including stale-edit recovery.
- Unified related-place queries include the intended kinds; memory-only queries
  exclude imports/fantasy; unrelated, uncertain, forbidden and withdrawn content
  behave according to explicit policies with explainable matches.
- Source-use restrictions survive extraction, indexing, editing and export;
  denial never silently creates an untracked local copy.
- Candidate generation/blending failure leaves a recoverable state; visual
  quality and actual geometry delivery are assessed separately from API success.
- Package claims state supported extensions, available asset references and
  receiver capabilities; no unsupported runnable-world or unrestricted-export claim.
