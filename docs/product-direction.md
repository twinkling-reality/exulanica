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
infrastructure-backlog.md remains the infrastructure backlog, not the complete product roadmap.

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

## Delivery gates for the first demonstration

The sequence above is the full first product milestone, not a promise that all six steps fit
one submission window. The October 30 deadline now bounds the working schedule below; available
compute budget and scene feasibility remain unresolved. Do not convert the old package inventory
into a delivery commitment. Use these gates to make progress visible and bound unfinished work.

| Gate | Required demonstration | Scheduling consequence |
| --- | --- | --- |
| Scene viability | Existing trained output opens in the real app; inspect coverage, navigation and visible defects | Diagnose the limiting stage before commissioning training or dispatching dependent renderer work. A small object scan is a pipeline check, not proof of a reconstructed place. |
| Memory and useful model interaction | Ask about the selected place through the actual Companion; ground the answer in available evidence and show missing information honestly | Verify the existing runtime path and record the executed model, task, latency and output. Persistent Companion shared history remains separate planned work. |
| Small complete experience | Explore the place, ask the grounded question, accept one supported appearance change, reload and restore the original state | This is the minimum release candidate. Existing appearance persistence may support it; it must be executed, and it must not be called complete alternate-world branching. |
| Creative extension | Add one persistent authored object, then its bounded motion, following the first-milestone contracts | Admit these extensions only with enough time to integrate, rehearse and fix them. Preserve them in the product roadmap if they miss the submission window. |
| Release rehearsal | Repeat the complete experience from a clean start; capture actual footage and verify setup, supported claims and failure behavior | Freeze feature additions before submission. Protect the rehearsal, recording and upload buffer in the dated schedule below. |

The memory interaction is essential to the world-memory demonstration; reconstruction and editing
alone do not establish that experience. Nemotron use must be functional in that interaction if
claimed, with the actual executed variant recorded rather than inferred from configuration.

One owner should integrate the scene-to-browser path. A second bounded task may validate the
existing Companion/model path against the same source contract once its inputs are available.
Assign disjoint writable files, migration ownership if needed, and a merge order before dispatch;
serialize shared app entry-point changes and database suites. More concurrent tasks are useful
only when their outputs can be integrated into the same demonstration.

At each handoff, require a runnable result and a short visual check before expanding scope.
Use focused tests for changed behavior; run the applicable integrated gates once for the executable
candidate and reuse valid results for documentation-only changes. Permission, deletion and byte
integrity checks still apply where the demonstration exercises those boundaries.

The infrastructure contribution follows the scene's measured bottleneck. A reproducible workflow
or an upstream fix can be a useful result without a novel algorithm. Full simulation, a new package
profile, a second developer client and broader infrastructure work do not block the minimum release
candidate unless the chosen demonstration actually depends on them. Hosting and recovery become
release dependencies if a live retained-data deployment is selected.

## Working delivery schedule through October 2026

These are decision checkpoints, not measured duration estimates or promises of completion.
The operator supplied an October 30 deadline. Plan to submit on October 28 and freeze features
on October 16. All working dates use America/New_York. Reassess feasibility after the first
scene inspection; no paid run or deployment is authorized by this schedule.

| Checkpoint | Required outcome | If the gate fails |
| --- | --- | --- |
| September 11 | Inspect the retained trained output in the real app, identify the limiting stage, and choose an authorized place source plus a compute plan | Resolve source, renderer or compute readiness before expanding implementation. Record a revised scene target; do not spend the remaining weeks blindly retraining. |
| September 18 | One coherent place is explorable and reopens; an existing Companion path is traced against its actual evidence | Concentrate implementation on the failing path and defer creative extensions. Inspect geometry earlier than this checkpoint whenever output becomes available. |
| September 25 | Complete the minimum experience: explore, grounded model interaction, accepted appearance edit, reload and restore | Re-plan extension scope immediately. Choose how judges will access the working build, with an owner and any hosting cost identified. |
| October 9 | Target one authored object and bounded interaction; reproduce the useful infrastructure result on another run or input | Keep incomplete extensions out of the release candidate. Finish the baseline and document actual infrastructure findings without claiming an unproved improvement. |
| October 16 | Freeze features; integrate the selected experience and test its judge-access path | Cut unfinished additions from the demonstration, keeping them in the longer-term roadmap. Fix core failures rather than concealing them. |
| October 23 | Rehearse from a clean start, complete focused usability checks, record the demonstration, and prepare setup and submission material | Use the remaining buffer for fixes, recording and access issues. No new architecture or model migration. |
| October 28 | Submit and verify links and access | October 29 and the time before the October 30 cutoff are contingency, not scheduled feature development. |

Begin usability observation at the September 25 baseline and fix confusion before the freeze.
Do not wait until recording to learn whether someone understands the place, the Companion's
answer, or how to undo a change. Keep evidence of useful model behavior and shortcomings during
these same sessions. Model variant choices should follow observed quality, response time and
cost; a larger model is not an acceptance criterion.

Open-source work remains attached to the product path. Select its bounded target after the
September 11 diagnosis, compare against the baseline during development, and aim to have a
reproducible result by October 9. An upstream submission can be prepared from that result;
acceptance by maintainers is external and must not be promised by the release date.

This schedule deliberately does not require completing every product milestone within 52 days.
Source readiness, authorized compute, reviewer availability and integration discoveries can
change capacity. Keep the dates as explicit points to narrow scope or revise the forecast.

## Immediate scene and infrastructure exit

First inspect the previously trained Gaussian output in the actual application. Identify whether
any failure comes from source coverage, camera registration, training, conversion, or rendering.
The single-photo depth preview does not establish a coherent reconstructed place. Reuse existing
outputs before proposing another paid run, then select an authorized source set appropriate to
one usable place. Scope implementation with a file set and branch before dispatch.

The product exit is a recognizable place that can be explored and reopened, with observed
coverage and failures recorded. Visual acceptance is required; unit tests and a completed
training job alone do not satisfy it.

Attach a reusable infrastructure result to this same work: reproducible inputs and camera data,
pinned execution dependencies, checkpoint recovery where supported, and measured quality,
GPU time and memory use. Compare any proposed optimization with an unchanged baseline on the
same inputs. Demonstrate reuse outside the original run before claiming generality; propose an
upstream fix or contribution when a reproduced limitation belongs to an upstream project.
Do not describe vendor usage alone as an upstream improvement or frontier advance.

Existing vendor integration is bounded: the model manifest configures Nebius Token Factory
inference, including Nemotron roles; the recorded GPU reconstruction used an NVIDIA L40S through
Brev/MassedCompute. That run does not establish Nebius GPU deployment. See
[compute findings](reference-gpu-compute.md). Choosing additional reconstruction or simulation
systems requires checking compatibility, licensing and measured benefit. This milestone does
not mandate a new runtime, an infrastructure framework, or a benchmark campaign unrelated to
the scene's observed bottleneck.

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
5. **Scene segments:** lift per-photograph people and object regions into per-entity 3D
   segments through the recovered cameras, show them in the scene, and name them there;
   models and ownership in [briefs/2026-09-11-scene-segments.md](briefs/2026-09-11-scene-segments.md).
6. **Developer interoperability:** document stable read/edit contracts, package compatibility,
   capability negotiation, and asset resolution. Prove a second tool can make an accepted change
   without depending on private interface state before claiming interoperability.

## Improvement over time and training boundaries

This is planned longitudinal work after the usable-scene baseline, not an additional October
release requirement. It complements the existing place-alignment and two-capture backlog rather
than creating a second competing pipeline. Trace those contracts before scoping implementation.
Capture dates and alignment do not alone establish successful incremental reconstruction.

Distinguish four mechanisms:

| Mechanism | Existing basis | Next proof |
| --- | --- | --- |
| Retain and resume scene training | Saved Gaussian output and complete checkpoints bound to the run's exact identity | Preserve the useful scene and recover compatible interrupted work; neither operation learns a general reconstruction model |
| Improve a particular world | Source, placement and publication lineage; same-input resume does not accept arbitrary new inputs | Add authorized observations and publish a measurably improved candidate version while preserving historical meaning |
| Develop Companion continuity | Existing evidence/context and reviewed interaction machinery | Persist approved memory, retrieve it across sessions, and support correction and deletion; this is not model weight training |
| Improve shared reconstruction or language models | Existing model/stage integration and evaluation machinery | A separately approved experiment must outperform a relevant baseline on unseen examples before promotion; ongoing cross-world learning and Nemotron fine-tuning are not established |

### First longitudinal exit

Use one authorized place with an initial source set and additional observations. Separate extra
coverage of the same state from a later physical change. A later room arrangement must remain a
new historical state; an authored edit must remain separate from both. Uncertain alignment or
time association must remain unresolved rather than silently fused.

Produce a new candidate through the existing reconstruction/publication boundaries. Start with
a full rebuild as the correctness and cost baseline. Continuing from an earlier scene's parameters
with changed inputs is a distinct capability from resuming an interrupted run: introduce it only
with explicit compatibility, alignment and input-lineage checks, never by weakening checkpoint
identity validation. Compare it with the rebuild before calling it an optimization.

Evaluate both old and new coverage using evaluation views excluded from training and fitting,
plus a browser inspection of navigation, holes and visible artifacts. Record quality regressions,
GPU time, peak memory and storage growth. A candidate must improve the targeted deficiency without
unacceptable regression in previously supported views; define the task's thresholds before running.
Preview, accept, reopen and, where still authorized, return to the previous version. A failed update
must leave the last valid version usable unless withdrawal or deletion makes it unavailable.

Current permissions govern all versions and checkpoint reuse. Removal of training sources must
invalidate affected artifacts according to existing deletion contracts. Rebuilding from remaining
authorized sources, if separately requested, produces a new artifact; it is not exact restoration
or proof of model unlearning. Historical versioning never authorizes resurrection of removed data.

### Modularity and scale

Reuse the existing separation between source/pose preparation, training, evaluation, publication
and rendering. Keep provider-specific GPU launch behavior behind the existing compute boundary;
the renderer consumes published assets rather than trainer internals. New implementations need
explicit input/output compatibility and capability reporting, not a speculative universal framework.

Measure growing input counts and retained versions before choosing selective recomputation,
scene partitioning, storage retention or multi-GPU execution. Retain reusable valid intermediate
artifacts only within their lineage and permission boundaries. Demonstrate that an update avoids
unnecessary work without stale outputs; measure concurrency, recovery and resource limits before
claiming scalable operation. Reuse existing job leases and recovery mechanisms where they fit.

For Companion quality, first establish a small representative failure set and compare context,
retrieval, prompts and model selection. Fine-tuning requires authorized training data, separation
of training and evaluation examples, a measured advantage over that baseline, versioned deployment
and a rollback policy. Private user memories are not automatically pooled into shared training.
Choose broader learned reconstruction or language-model work only when these measurements justify
it. This roadmap does not authorize training runs, collect new data or assign a migration.

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
