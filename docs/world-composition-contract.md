# Unified world composition and retrieval

Status: **DECISION** for product and architecture direction; **PARTIAL** implementation.
Existing API, schema, and package contracts describe the supported surface; this document
does not extend them.
The Iceland journey is the product example: import a permitted
place, combine it with personal memories, and create a fantasy variation.

## Purpose and authority

A person can build an interactive world from their memories, selected real-world
places and objects, and fictional creations; describe changes in ordinary
language; and find the resulting content through the same query and filter model.
Earth is a source of usable environmental content inside this experience, not a
separate orbital map or a navigation-only replacement for the interactive world.

This contract develops [product-direction.md](product-direction.md), which owns
product priority. It supersedes a reconstruction-only or separate-map reading of
prior product plans. Existing API/schema/package contracts describe the supported
surface; this document does not silently extend them. Implementation evidence is retained in scoped evaluation records, including the
[experience integration](evaluation/2026-09-12-experience-integration.json) and
[Earth scope correction](evaluation/2026-09-12-earth-experience-correction.json).
A new task must read the product direction, this contract, the relevant live
API/data contracts and the scoped evaluation records before writing its brief.

The World Memory Model is the system's representation and behavior across memory,
creation and interaction. It is not a claim that one trained neural network
already understands or generates an entire world. WMP is a signed projection of
authorized state, not the live database or a runnable scene by itself.
The canonical technical doctrine is
[world-memory-model.md](world-memory-model.md): every consequential feature is
addressable, but disposable render primitives are not promoted to world entities.

## Reference user journey

1. Select an Icelandic valley or waterfall from a source permitted for this use.
2. Bring that selection into an alternate personal world beside a memory scene.
3. Ask: "Blend this valley into my garden and put a floating castle above it."
4. Inspect the resulting placement, seam treatment and generated addition; apply
   the supported changes, reload them, and undo them without modifying originals.
5. Ask: "Show everything related to Iceland." See imported Iceland content,
   supported personal Iceland memories and Iceland-derived authored variations,
   with an explanation of each relationship and filters to narrow the results.

This is a target journey, not a demonstration completed by fixtures.
Imported Iceland content does not prove a visit. A fantasy scene inspired by
Iceland does not prove it existed there. A moved landscape retains its source
identity while its current placement belongs to the person's created world.

## One connected representation with distinct responsibilities

Share stable identities and explicit relationships across source, meaning,
geometry, authored state and runtime. Do not flatten everything into an opaque
mesh, a caption embedding, a browser-only state object or a second Earth database.
Do not create a service per content type without a measured reason to cross the
existing authority boundary. Exact schema and API changes need scoped briefs.

| Conceptual record | Required meaning | Existing basis and missing extension |
| --- | --- | --- |
| Source and asset | Provider/original identity, revision or observation time, content digest where available, permitted operations and derivation lineage | Evidence/artifact machinery exists; external Earth asset admission and operation-specific rights need contracts |
| Place and entity | Stable identity, supported names, aliases and explicit geographic containment/association | Place/entity links exist; canonical external geography resolution and containment across content kinds are not established |
| Selection and segment | Geographic boundary, existing feature ID, or supported 3D subset tied to source revision and extraction method | Photo masks and lifted scene voxels exist; reusable Earth extraction and complete editable objects do not |
| Authored instance | Source asset reference, owning world/version, local transform, role and modification history | Region-local authored objects, alternate versions, and backend durable placement of exact admitted environment assets or indexed features with persistent geographic anchors exist. Arbitrary Earth extraction and rendering remain outside that contract |
| Search projection | Authorized content references with result kind, match reason, place relationship, time and lineage | `Intent.CONTENT` in [plan.py](../exulanica/selection/plan.py) and [executor.py](../exulanica/selection/executor.py) projects those references for the kinds in [Unified queries and filters](#unified-queries-and-filters). Capture and entity Selection remain the photograph path. Authored objects, reconstructed scenes, and the Iceland-class journey are not part of that projection |
| Rendered representation | Geometry/materials, levels of detail, collision and current residency derived from those records | PlayCanvas and asset runtimes exist; detailed Earth integration remains unaccepted |

The table names responsibilities, not new SQL tables or wire field names. Preserve
existing authority, transactional writes, dependency invalidation and replaceable
renderer/model interfaces. Shared public place definitions must not expose private
associations, trip history or derived personal content across workspaces.

[Saved-world reference attachments](saved-world-entry.md#reference-photographs) provide a durable
relationship between an owned project and reviewed personal photographs. They retain exact source
and admission lineage without changing structural snapshots, authored edit history or appearance.
This relationship is a source collection for the project; it does not implement extraction,
reconstruction or placement. Optional reference availability remains separate from the invalidation
of sources that actually determine a structural snapshot.

A rendered representation must declare which properties it preserves and which
operations it supports. Visual fidelity does not authorize collision; a semantic
graph does not establish free space; an embedding does not establish identity; and
a generated completion does not establish observation. Roads, vegetation, street
furniture, facade elements and inhabitants that are selectable, editable,
simulated, queryable or promised to persist require shared subject identities or a
versioned parametric interpretation record. They may not exist only as browser mesh
loops.

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

`Intent.CONTENT` is the typed Selection for place-related content. It uses the
existing Selection mechanism, authorized read projections and Companion planning
path. It does not add a parallel Earth-only search or let a model write SQL.
Resolve place names to permitted identities. Geographic containment, source
lineage and supported entity links establish relationships. Embeddings can help
discover or rank capture content but cannot establish that a person visited
Iceland, and CONTENT refuses a semantic-text field.

A CONTENT plan requires a place selector and a content selector. It refuses
entity, time, and capture filters, and it refuses `semantic_query`. Capture and
entity intents remain the photograph and who-is-here path; they still accept
those dimensions.

`ContentScope.RELATED` unions the kinds below over a confirmed place-entity
bridge. `ContentScope.MEMORIES_ONLY` returns only confirmed memory captures at
the named place entity and does not traverse the canonical place.

| `result_kind` | `origin_kind` | `content_kind` | `place_relationship` | `match_reason` | `personal_visit_evidence` |
| --- | --- | --- | --- | --- | --- |
| `memory_capture` | `personal` | `capture` | `captured_at` | `confirmed_memory_place` | true |
| `admitted_environment_source` | `imported` | `environment_source` | `admitted_for` | `canonical_place_bridge` | false |
| `admitted_environment_feature` | `imported` | `environment_feature` | `admitted_for` | `canonical_place_bridge` | false |
| `authored_environment_instance` | `authored` | `environment_instance` | `derived_from` | `authored_from_canonical_place` | false |
| `synthetic_inhabitant` | `simulated` | `inhabitant` | `simulated_at` | `scheduled_presence` | false |
| `simulation_event` | `simulated` | `event` | `simulated_at` | `recorded_simulation_event` | false |

Those kinds are the literals [executor.py](../exulanica/selection/executor.py)
selects. Society inhabitant and event rows appear when the society is the v1
engine or its input history is authorized. That projection is not a living-world
loop.

An undone environment addition is absent. A revoked or never-confirmed bridge
leaves imported and authored environment rows out of the union; memory captures
at the place entity remain. Withdrawn source or asset metadata does not appear
in results or counts. An authorized row whose bytes are missing is labeled
`unavailable_bytes` when a store is supplied. Pages are bounded keysets;
distinct captures and authored environment instances are not collapsed.

Authored objects from [world-objects-contract.md](world-objects-contract.md) are
not a CONTENT kind. Reconstructed scenes and lifted scene segments are not
CONTENT kinds.

For the reference example, the request shapes and what CONTENT does:

| Request | CONTENT behavior |
| --- | --- |
| Everything related to Iceland | `related` union of the kinds above at the confirmed place |
| My memories from Iceland | `memories_only`; imported, authored, and simulated rows excluded |
| Iceland landscapes I brought into this world | No isolated scope; imported kinds appear only inside `related` |
| My fantasy versions of Iceland | No isolated scope; authored environment instances carry `authored_role`; authored objects do not appear |
| Iceland memories with a named person from a chosen year | Refused: entity and time filters do not apply |

The Iceland-class journey (permitted import, personal memory scene, fantasy
variation, and that query set as a completed personal demonstration) is the
product example, not a completed demonstration. Visual acceptance is a separate
assessment and is not a retrieval claim.

Origin, content kind, supported place association, world/version, match reason,
lineage and availability are fields on each CONTENT row. People, capture time,
processing state and semantic text are not CONTENT filters. Time-filter
applicability is defined per intent rather than silently reusing capture dates
for imports.

## Natural-language editing

Translate a request into supported, typed operations with resolved content and
world/version references: select, place, transform, style, blend, create or attach
a reviewed behavior. These are target operation categories, not an assertion that
the appearance-proposal registry implements them. Reuse the existing preview/apply/rollback
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

What the tree implements, and what this contract names as absent from the completed journey:

- [Authored objects and alternate versions](world-objects-contract.md) support
  bounded editing and history. Migration 0050 also supports backend-only durable placement of
  exact admitted environment assets or indexed features with persistent geographic anchors,
  availability states and the same version history. Arbitrary Earth extraction and rendering
  remain outside that contract.
- `Intent.CONTENT` in `exulanica/selection/plan.py` and `executor.py` returns the
  kinds in [Unified queries and filters](#unified-queries-and-filters) over a
  confirmed place. Capture and entity intents still resolve photographs and
  entities through place, entity, time and text constraints.
- `exulanica/selection/proposal.py` drafts bounded appearance proposals, not general
  structural creation, blending or arbitrary asset generation.
- `exulanica/ingest/scene_segments.py` and the scene-segments route support lifted
  scene segmentation; segment availability is not complete-object extraction.
- [WMP](world-memory-package.md) has authored-world and environment-instances
  extensions. Dual export is lineage-closed: a parent pointer resolves in the
  directory that holds the child, schema-v1 ancestors may appear in both
  directories, the environment directory verifies alone, and dual export omits
  an authored-world directory when every kept version is environment-bearing.
  Portable Earth selection, source-use-rights semantics and a runnable import
  are not part of WMP 1.0, authored-world 1.0, or environment-instances 1.0. Do
  not silently alter WMP 1.0 or imply that its signature supplies missing asset
  bytes, source-use rights or runtime behavior.

Implement in dependency order, with exact file ownership and evidence per stage:

1. **Source admission and shared identity.** Prove a permitted reusable real-world
   selection, canonical place association, source version and explicit frames;
   define the versioned environment/asset contract and detailed rendering target.
2. **Durable composition and retrieval.** Place that selection with a personal
   scene in an authored version, save/reload/undo, and query their shared place
   identity with distinct origin and match reasons. `Intent.CONTENT` unions the
   kinds named above over a confirmed place bridge, with memories-only
   exclusion, paging, withdrawal hiding and byte-availability labels. This stage
   names, and CONTENT does not provide, the Iceland-class personal journey,
   authored objects as a CONTENT kind, and isolated imported-only, fantasy-only,
   or person/time request shapes.
3. **Assisted structural creation.** Execute one natural-language compound edit,
   including a real geometric or generated addition; preview/apply/undo with
   measurable asset quality, existing interactions and retained lineage.
4. **Transfer and expansion.** Add package compatibility and permitted asset
   resolution, test a second geography/source and expand supported operations
   through measured needs rather than a speculative universal abstraction.

The frontend Earth lane remains bounded by its issued brief; these stages
are not permission to edit its unowned backend/query/package files. Briefs
must name the missing contracts and resolve scope before implementation.

## Acceptance that arriving tasks must preserve

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

Saved-world source reads are snapshot-addressed: reopening resolves source media through the
entry’s stored structural snapshot, independently of the global topology pointer. Attachment
membership is a project-reference write. It does not compose geometry, activate sourced topology
on an authored starter, or rewrite style.

Structural snapshots and composed style versions are different planes. Compatibility is the
decision of `classify_structure_style_compatibility`, which takes typed plane identities and
returns `compatible`, `preview_required`, or `refuse`. `compatibility_key` is profile-family
binding only. Digest-string equality across planes is not the reason for compatibility; live
typed identities may still agree when hex strings collide. `preview_required` /
`style_topology_drift` is a CLASSIFY-family result. Family-matched digest change on
`register_topology` is the composer handoff. COMPOSE tokens are latent; there is no compose
write. Historical style may be displayed; appearance writes and rollback use the live
composed digest. Reviewed-source composition into geometry is absent.
