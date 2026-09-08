# Product roadmap

Updated 2026-09-08. This roadmap defines delivery milestones and their acceptance criteria.
Implementation status is recorded below; API and package contracts remain authoritative for
supported capabilities.

## Product purpose

Build your own world from your life, then change what's possible inside it.

Exulanica remains a Personal World Memory Model. Personal experiences supply meaningful places,
people, objects, and context. Creation lets a person reshape that world, introduce fictional
material, and combine it with their experiences. Simulation adds movement and interaction governed by physical or fictional rules.

Memory, creation, and simulation share the same world state. The Companion provides a conversational
interface; the World Memory Package describes a portable snapshot for developers.

## Relationship to the engineering roadmap

This document supersedes narrower product definitions in product-specification.md and the
north-star framing and delivery priority in frontier-roadmap.md. Older implementation records,
acceptance evidence, and operational requirements remain valid within their stated boundaries.
roadmap-next-2026-09-08.md remains the infrastructure backlog, not the complete product roadmap.

Identity confirmation, permissions, deletion, evidence, and versioning remain foundational.
Evidence supports claims about the source world; authored changes remain distinct from that source.
Object behavior uses reviewed runtime capabilities separately from appearance recipes.

## Implementation status

The inventory below identifies existing code and the extensions required by each milestone.

| Area | Existing basis | New work for this direction |
| --- | --- | --- |
| Reconstruction and memory | Reconstruction modules, scene graph, identity decisions | Select and validate one personally meaningful place for the demonstration |
| Appearance | Reviewed capabilities and preview/apply/rollback contracts | Verify the selected look on the demonstration place; do not equate style with object creation |
| World Read | `exulanica/api/routes/world_read.py` serves scene/place bundles | Define reads for an authored world version and its created objects |
| World Write | `exulanica/api/routes/world_write.py` records generated-scene receipts | Persist actual editable object state and asset references; integrate rendering and user acceptance |
| Package | `exulanica/world_package/cli.py` and profile `exulanica-wmp-1.0` | Versioned support for creative state and behavior references after the data contract is settled |
| World versions | Existing versioned topology, placement, and appearance | Explicit alternate-world lineage; existing component snapshots do not establish complete world branching |
| Simulation | No general simulation capability established by this review | One bounded behavior first; physical and multi-entity simulation later |

World Write receipts are not payload delivery. Package verification is not runnable import.
Neither is evidence that a compatible simulation runtime exists.

## World state contract

Preserve the source reconstruction and let a person create an alternate version. The alternate
version refers to its source and stores additions, removals, transforms, and appearance changes.
Do not silently merge inventions into historical claims or mix capture times into a purported
single historical state. Keep entity references stable across a version's edits.

A created object needs an identifier, asset reference, transform, origin, and optional supported
behavior with bounded parameters. Record the world version an edit was based on. Concurrent edits
must fail clearly or be reconciled explicitly. Acceptance, undo, and reopening must operate on
persisted state, not just the current browser view. Reuse existing version machinery where it fits;
do not prescribe a migration or duplicate storage before tracing existing callers.

An anime image can be fictional source material, an appearance reference, or something associated
with a personal experience. Its upload alone establishes none of those personal associations.
For the first slice the user chooses the role; do not require an automatic reality classifier.
An interpretation of fictional art remains fictional even when rendered realistically.

## First milestone

One reconstructed place, one alternate version, one authored addition, and one reversible
interaction. The initial behavior is bounded motion with trigger, stop, and reset controls.

| Order | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1 | A usable starting place | An authorized source set reconstructs and displays; record actual coverage and failures |
| 2 | Alternate version | Create a variation, change its appearance, reload it, and return to the unchanged starting version |
| 3 | One created object | Add/place/remove one reviewed asset; accepted edits survive reload and can be undone |
| 4 | One interaction | Trigger/stop/reset its supported motion; behavior remains attached after reopening; unsupported behavior fails visibly |
| 5 | Developer proof | A small client reads the same saved version and submits the supported edit through the authenticated API |
| 6 | Package proof, only with a compatible extension | Save and verify the new state with an explicit profile/version; distinguish successful verification from successful runtime loading |

Dependencies are sequential for the demonstration; existing recovery and source-validation work
remains necessary where the chosen environment depends on it. If step 1 is blocked, a clearly
labelled fixture can support development but cannot prove the personal-source demonstration.
If motion is not complete, show a static creative edit and label simulation as future work.

Before implementation, inspect the selected renderer's asset path and choose the smallest reviewed
asset/behavior pair it can support. Schedule depends on source readiness, renderer integration, and available compute.

## Subsequent milestones

1. **Creative composition:** more editable assets, blending places into authored arrangements,
   explicit source versus created content, alternate versions, undo, and persistence. A composed
   arrangement must not imply those places were physically adjacent.
2. **Assisted creation:** model-generated additions through an asset pipeline with provenance,
   preview, acceptance, storage, and renderer compatibility. A receipt alone is insufficient.
3. **Interactive worlds:** an explicit behavior registry, triggers, runtime state, restart rules,
   and supported motion. Define what persists and what resets. Character behavior is separate work;
   recognizing someone never implies permission or capability to simulate their personality.
4. **Simulation:** scope physics, collisions, dynamic objects, and agent behavior through measured
   prototypes. Select a runtime only after those requirements are concrete. Validate physical behavior against explicit test scenarios.
5. **Developer interoperability:** document stable read/edit contracts, package compatibility,
   capability negotiation, and asset resolution. Prove a second tool can make an accepted change
   without depending on private interface state before claiming interoperability.

## Package and API boundaries

Keep `exulanica-wmp-1.0` compatible. Do not silently add required simulation fields to the current
profile. Specify a new compatible extension or new profile after the object/version contract has
been implemented and reviewed. Declare unsupported capabilities explicitly on load.

A future package may reference assets and approved behavior identifiers plus their parameters.
It need not embed runtime code. Original media remains excluded by default; include or resolve
assets only under the appropriate permissions. A signed folder guarantees neither historical truth
nor that every renderer will execute it the same way.

The API should operate on a named world/version with authenticated reads and reviewed changes.
The existing World Read/Write routes are starting points, not a promise of the final route shape.
Do not publish invented endpoints before implementing the contract.

## Evaluation

Evaluate whether a person recognizes the starting place, can make a meaningful creative change,
and can resume working with the saved result. Verify that a second client reads the same world
version and submits an accepted change. Each milestone should retain reproducible evidence for
its acceptance criteria.
