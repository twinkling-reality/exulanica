# Product roadmap

Updated 2026-09-12. This roadmap defines delivery milestones and their acceptance criteria.
Implementation status is recorded below; API and package contracts remain authoritative for
supported capabilities.

## Product purpose

Build your own world from your life, then change what's possible inside it.

Exulanica remains a Personal World Memory Model. Personal experiences supply meaningful places,
people, objects, and context. Creation lets a person reshape that world, introduce fictional
material, and combine it with their experiences. Simulation adds movement and interaction governed by physical or fictional rules.

Memory, creation, and simulation share the same world state. The Companion provides a conversational
interface; the World Memory Package describes a portable snapshot for developers.

Real-world places selected from permitted external sources join those memories
and creations as reusable world content. A person should be able to bring an
Icelandic landscape into their own world, combine it with their Iceland memories,
and ask for a fantasy variation while retaining source identity and undoable
history. "Show everything related to Iceland" should find the imported landscape,
supported personal memories and derived creations together, with origin/place/time
filters and explicit match reasons. Moving content into a fictional arrangement
must not rewrite where it originated or imply a personal visit.

The [unified world composition and retrieval contract](world-composition-contract.md)
defines the required relationships, source-use rights, typed queries and edits,
visual acceptance and implementation gaps. Future Earth, memory, creation, search
and package briefs must follow that contract. This is the intended product, not a
claim that extraction, unified content search or general NLP scene editing already
works. The World Memory Model is the system architecture and world representation;
it does not imply an already-trained universal world-generation model.

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
| Reconstruction and memory | Reconstruction modules, scene graph, identity decisions and lifted scene segments | Validate a personal scene; reusable complete-object extraction and cross-source alignment remain separate work |
| Appearance and language | Reviewed appearance capabilities and bounded conversational preview/apply/rollback proposals | General structural edits, geometry blending and generated-asset creation through typed operations |
| World Read and Selection | Scene/place reads and capture/entity Selection with place, time and text constraints | Unified authorized reads/queries for memories, imported geography, assets and authored versions with explainable matches |
| Authored objects and versions | Source snapshots, alternate-version lineage, object add/move/remove/undo and bounded motion; synthetic browser acceptance recorded below | Reusable Earth selections, persistent environment/anchor contracts and real-scene acceptance; arbitrary world branching is not established |
| Earth and source admission | Experimental frontend environment work; current visual result unaccepted | Detailed usable sources permitted for extraction/indexing/remix, explicit geographic identity and first-person coexistence |
| Package | WMP 1.0 and opt-in authored-world extension describe existing state | Versioned geographic selection/anchor/rights support and permitted asset resolution; no automatic runnable import |
| Simulation | Reviewed bounded object behaviors; no general simulation capability established | Supported physics and fictional rules through measured scenarios |

World Write receipts are not payload delivery. Package verification is not runnable import.
Neither is evidence that a compatible simulation runtime exists.

### Measured experience work on September 12

The four experience lanes are integrated on main. The
[integration record](evaluation/2026-09-12-experience-integration.json) retains 2,974 passing
backend tests, 3 skips and 1,238 passing web tests, including the initial failures and repairs.
The [local activation record](evaluation/2026-09-12-experience-activation.json) verifies the
copy at migration 0047 and the preview running from main on ports 8001 and 5182. The retained
database remains unchanged at 0038. The dated reports distinguish implemented contracts,
executed fixture checks and remaining personal-source acceptance.

- [Personal browser intake](evaluation/2026-09-12-personal-browser.json) implements original
  upload, explicit batch selection, person linking, region correction and atomic request
  recovery. The corrected selection path was exercised against an inventory of 201 images.
  Real-photo admission with actual human review and inference remains pending.
- [Saved world controls](evaluation/2026-09-12-world-browser.json) passed authenticated browser
  version creation, appearance changes, object add/move/remove/undo, bounded motion, reload and
  second-client conflict recovery using explicitly synthetic geometry. Appearance remains
  workspace-wide, not isolated per alternate version. Personal-place registration remains
  unproved. Desktop controls were checked at 1280 and 1000 pixels; mobile retains its existing
  desktop-only boundary, and a narrow-screen segment-panel overlap remains.
- [Companion quality preparation](evaluation/2026-09-12-companion-quality.json) adds evidence
  currency checks and a digest-bound evaluation corpus. Scripted retrieval tests passed;
  actual model answers, accessible citations and human quality judgments are still pending.

The operator authorized necessary Brev GPU work on September 12. The
[trainer validation](evaluation/2026-09-12-place-compute-readiness.json) passed production
image decoding and eight generated-data CUDA rendering/backward steps on an L40S. The instance
was deleted; the provider posted a $0.23 total. This establishes trainer packaging and execution,
not a usable walk-around capture or place coverage. The first personal-place demonstration and the complete
scene-to-Companion rehearsal remain acceptance gates before calling the experience complete.

## Optional Earth foundation and September demo scope

Corrected 2026-09-12 after the operator rejected the orbital viewer. The
[experience correction](briefs/2026-09-12-earth-experience-correction.md) supersedes
the globe-navigation and separate-handoff outcome in the original
[Earth wave](briefs/2026-09-12-earth-wave.md) and lane brief. That original scope
misunderstood the requested product. The orbital implementation is not accepted
or integrated.

The subsequent ground-level native prototype was also rejected for visual quality.
An untextured block city and a synthetic interaction marker do not satisfy the
requested rendered world. Assess detailed ground-level appearance and reuse rights
alongside integration, geometry and performance; a reference-only photorealistic
feed cannot silently become the editable corpus. Neither rejected prototype has
been accepted as completion of the Earth product requirement.

Earth is an optional environment inside Exulanica's interactive world. The person
stands on its streamed terrain, moves with the existing first-person controls,
and continues using the world's interaction system while terrain and buildings
are visible. The production renderer remains PlayCanvas. A separate map, a camera
lowered into a globe viewer, or a shared canvas that replaces the interactive
world with a navigation-only experience does not satisfy this outcome.

Implement Earth as an environmental layer within the shared rendering and
interaction architecture. Keep geographic coordinates distinct from semantic
Atlas layout and region-local authored poses, with explicit transforms between
compatible frames. Earth geometry and existing interactive content must coexist;
an explicit local placement for a labeled fixture does not establish the real
geographic location of any personal reconstruction. Persistent Earth anchoring
or edits require the appropriate versioned contract before they can be claimed.
Existing authenticated access, consent, source identity and withdrawal remain
authoritative. An optional public Earth entry must not expose personal content.

The implementation must establish terrain support, collision behavior, streamed
coverage boundaries, bounded resource ownership and origin precision through
measurements. Network-served buildings do not establish full interiors, traffic
or general simulation. A proposed adapter or synthetic triangle probe is not
proof of a usable city. Live ground exploration and existing interaction must be
tested together, including a second geographically different destination.

Streaming suitably licensed terrain and buildings does not inherently require
training a model. Personal-place reconstruction remains a separate scene run.
Assess rights for the actual chosen provider and use, including runtime geometry
processing, separately from renderer licensing. Preserve provider attribution,
keep provider credentials and private memories separate, and preserve the
UI/composition boundary for the operator's later interface redesign. Ordinary
personal use must remain available when Earth is disabled or unavailable.
September18 may limit exposed features, but does not justify substituting a
different experience or weakening long-term integration contracts.

The Product Hunt page lists September 18, 2026. This is an additional proposed
submission window, not a replacement for the October schedule below. Exact
submission requirements and cutoff still need verification. Demonstration scope
is one destination and one complete useful interaction, with recording/access
checks protected. Prepared work and a passing renderer test are not a submission
or proof of live Companion quality.

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

## Model selection and compute priorities

Decision dated 2026-09-12, following the operator's request for the strongest justified stack.
Add the work below to delivery planning; retain current runtime models as the baseline until a
candidate passes its comparison. The [current stack review](model-and-service-selection.md#0-current-stack-and-selection-decision)
separates implemented roles from reserved configurations and historical plans. This is a
quality-first selection process within actual hardware and interaction constraints, not a rule
to use the smallest or cheapest model. No comparative results are claimed by this roadmap update.

### Required next work

| Priority and stage | Concrete work | Evidence required to change production |
| --- | --- | --- |
| P0: inputs and diagnosis | Obtain the already-required eligible place capture and human review. Separate source coverage, detection, masks, depth, pose, training and display failures. Trace the complete Companion classification/planning/retrieval/composition path. | A reproducible failure assigned to a stage, with source/consent boundaries recorded. Missing viewpoints or missing evidence are not proof that a larger model is needed. |
| P1: Companion quality and routing | Reuse the September 12 corpus and evaluator; expand beyond its three related photographs with authorized, scene-disjoint held-out examples. Compare Nano with Super on hard grounded answers; include Ultra on the same difficult subset where measured quality remains inadequate. Compare Qwen 235B with Nano for classification and structured planning separately. | Human-reviewed factual support, usable citations, appropriate abstention, correct plans and safe proposed edits; per-stage and end-to-end latency and cost, including repairs. Existing Lightning-era planning latency does not establish Nano's planning performance. Preserve Qwen until a replacement passes. |
| P1: photo observations and masks | Compare M3 with the configured MiniCPM fallback on caption omissions and unsupported observations using identical approved image renditions. Separate box errors from mask errors; compare SAM 2.1 Tiny with Base+/Large using the same validated prompts. | Held-out observation correctness and completeness; masks compared with human-reviewed reference outlines, including missed objects, boundary errors, occlusion and people. Record peak memory, cold/warm latency and host. A model's predicted mask score is not measured IoU. Promote a larger segmenter only for a demonstrated task benefit. |
| P2: visual retrieval addition | If relevant visual details are absent from captions, evaluate a separate SigLIP 2 image/text retrieval arm against existing lexical/Qwen-caption retrieval. If the right evidence is present but poorly ordered, test a Qwen3 reranker instead of treating both failures as the same problem. | Relevance judgments made before ranking, recall@k/nDCG@k, false matches and end-to-end answer impact on the same held-out queries. Apply existing permissions before evidence reaches the answer model; preserve deletion/lineage for new vectors. No visual embedding establishes a person's identity. |
| P2: pose or depth improvement | If a sufficiently overlapping capture still fails COLMAP, compare the Apache MapAnything variant through the existing pose boundary. If the defect is single-image surface detail, compare MoGe-2 with MoGe-3 on Linux instead. | Independent pose/reprojection and held-out-view checks, geometry/scale checks and coverage inspection, plus memory/time. Run downstream scene training only after pose gates pass. A predicted pose or detailed single view cannot establish unseen backs or usable place coverage. |
| P3: additional architecture | Consider SAM 3 only if concept-driven detection/segmentation is a measured unmet requirement. Evaluate shared object storage, retrieval indexes, worker concurrency or multi-GPU execution only when measured load or host limits require them. | Compatibility with existing outputs, license/dependency review for the exact artifact, quality/recovery tests and measured operational benefit. No framework rewrite, new face-recognition stack or model fine-tuning is selected by this review. |

The P1 comparisons are the next model-selection work, with scene readiness still the prerequisite
for place claims. P2/P3 are conditional branches after diagnosing failures, not a requirement to
install every candidate. Existing retained examples can support preparation, but the current tiny,
related-image corpus cannot establish broad generalization. A rephrased query over the same scene
is not an unseen-scene evaluation.

### Promotion, compute reuse and rollback

Before running each comparison, freeze its baseline/candidate revisions, permitted inputs,
development/held-out split, human rubric, primary task metric, practical minimum improvement,
and latency/memory ceilings derived from the intended interaction and actual hardware. These
ceilings and improvement thresholds are not yet measured or numerically selected; set them before
examining candidate outputs. Use paired inputs, record denominators and uncertainty, and keep
repeated calls from being misreported as additional independent examples. Define difficult-task
subsets and routing rules on development examples before scoring held-out cases. Refresh the
live provider catalog and candidate shortlist before execution; the listed models are supported
comparison candidates, not an exhaustive ranking of available intelligence. If evidence is too
small or inconclusive, keep the baseline and report that limitation.

Inspect false claims, invented identities, stale evidence, permission handling and deletion as
separate regression gates. Model self-confidence is not the routing trigger. Missing evidence
continues to require abstention; escalation cannot create supporting sources. If Super/Ultra earns
a role, implement an explicit, tested task-routing policy behind the existing role interface.
The current provider-error fallback is not that policy. Measure both difficult-task benefit and
the full user-visible response time before widening the route.

Reuse valid authorized stage outputs for fair comparisons: caption/index artifacts, reviewed
masks, prepared poses and immutable dependency builds where compatible. Keep source, version and
permission identity in cache keys and invalidate affected descendants after model or input changes.
Use staged small comparisons before full scene runs. Cache prepared model weights on approved
storage where useful, record cold and warm timings, and avoid idle rented GPUs. Higher compute is
justified by measured task improvement or a verified hardware requirement, not by model size alone.
Existing operator Brev authorization remains in force within its scope; it does not extend to
hosted model spending, new private inputs or additional data rights through this document.

A promotion binds the tested source/model/input versions and results, passes the same user-facing
workflow, and retains the previous route/output version for rollback without resurrecting removed
private data. Model identity and preprocessing changes must version affected caches and derived
artifacts; an embedding-space change requires compatible re-embedding. Never tune registry
thresholds on held-out examples to manufacture a pass.

By the September 25 baseline checkpoint, record the diagnosed bottlenecks, completed comparisons
and chosen routes, or name the missing inputs and preserve the working baseline. Integrate any
winning candidate before the October 16 feature freeze. Incomplete experiments remain roadmap
items; no model migration should consume the October 23 rehearsal buffer. These dates govern
the submission build, not the long-term architecture or the depth of subsequent evaluation.

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

The [composition delivery sequence](world-composition-contract.md#existing-implementation-and-staged-delivery)
connects these milestones: permitted source admission and shared identity, durable
composition with unified retrieval, natural-language structural creation, then
compatible transfer and expansion. Frontend Earth rendering is one dependency;
it does not complete extraction, searchable world integration or persistent edits.
Each stage needs an exact scoped brief and measured acceptance, without changing
active tasks' ownership through roadmap prose.

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
