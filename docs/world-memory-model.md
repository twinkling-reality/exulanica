# The Exulanica world-memory model

Status: **DECISION AND RESEARCH PROGRAM**. Existing evidence, graph, reconstruction,
spatial-authority, authored-version, World Read, generated-receipt, and package contracts implement
parts of this architecture. Exulanica does not yet claim a learned general world model, reliable
physical prediction, autonomous open-world simulation, or complete object-level scene memory.

Updated 2026-09-13. This document is the canonical technical meaning of **Personal World Memory
Model**. Product priority remains in [product-direction.md](product-direction.md); exact wire,
database, and package behavior remains in the corresponding implementation contracts.

## 1. The research position

Exulanica is not one neural network and should not be redesigned to imitate one.

The term *world model* currently names at least three different systems:

1. a **descriptive world model** stores an estimate of what exists, where it is, how it is related,
   and how that estimate changed;
2. a **predictive world model** estimates future state or observations conditioned on actions; and
3. a **generative world model** synthesizes plausible observations or environments from prompts and
   controls.

Exulanica currently implements a substantial part of the first, bounded deterministic behavior,
and interfaces through which the second and third may read and propose changes. It has not earned a
claim to the second or third as a general capability.

That distinction is material. V-JEPA 2 predicts latent future representations and demonstrates
action-conditioned robot planning, but reports camera sensitivity and error accumulation during
long rollouts. Genie 3 generates interactive video at 720p and 24 fps with consistency measured in
minutes and visual memory described on approximately a one-minute horizon. Marble generates and
edits persistent 3D worlds and exports meshes or Gaussian splats, while its own documentation warns
that image-conditioned unseen space is plausible generation rather than the source floor plan.
None of those properties, by itself, provides durable personal identity, exact source citation,
consent withdrawal, editable historical alternatives, or a signed account of what changed.

Exulanica's research hypothesis is therefore:

> A personal world becomes more useful to people and models when observations, interpretations,
> authored alternatives, and simulated consequences share stable identity and spatial context
> without sharing an epistemic status.

This is a systems hypothesis, not a novelty claim already proved. It becomes a research result only
if the experiments in section 10 beat simpler baselines.

Primary references retrieved 2026-09-13:

- [Genie 3](https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/), Google DeepMind,
  2025: autoregressive interactive visual worlds and their stated time horizon.
- [Marble](https://www.worldlabs.ai/blog/marble-world-model), World Labs, 2025: persistent
  generated 3D worlds, multimodal conditioning, editing, composition, and export.
- [V-JEPA 2](https://arxiv.org/abs/2506.09985), Meta AI, 2025: latent physical prediction and
  action-conditioned planning, including reported limitations.
- [Learning 3D Persistent Embodied World Models](https://proceedings.neurips.cc/paper_files/paper/2025/file/970f59b22f4c72aec75174aae63c7459-Paper-Conference.pdf),
  NeurIPS 2025: action-conditioned video prediction coupled to persistent 3D feature memory.
- [3D-Mem](https://openaccess.thecvf.com/content/CVPR2025/papers/Yang_3D-Mem_3D_Scene_Memory_for_Embodied_Exploration_and_Reasoning_CVPR_2025_paper.pdf),
  CVPR 2025: complementary snapshot and dense representations for embodied scene memory.
- [ConceptGraphs](https://arxiv.org/abs/2309.16650), ICRA 2024: compact open-vocabulary,
  object-centric 3D scene graphs and the limitations of dense feature maps.
- [DynaMem](https://arxiv.org/abs/2411.04999), 2024: online dynamic spatio-semantic voxel memory.
- [PROV-DM](https://www.w3.org/TR/prov-dm/), W3C Recommendation: entities, activities, agents, and
  derivation as an interoperable provenance model.

## 2. The central invariant

**Everything consequential is addressable; not everything rendered is canonical data.**

A state is consequential when it can affect any of:

- a factual or uncertain claim;
- stable identity, query, selection, or accessibility;
- geometry a person may measure, enter, collide with, or navigate on;
- an object's affordances, behavior, or simulated outcome;
- persistence, undo, branch comparison, package export, or model conditioning;
- source rights, consent, withdrawal, or deletion closure; or
- a visual feature the product promises to preserve or let a person edit.

Every consequential state requires a stable identity, declared authority, time/branch scope,
provenance, and version or event position. A model may propose such state; it does not silently make
it authoritative.

GPU vertices, triangulation, batch membership, mip levels, culling structures, antialiasing,
interpolation frames, tone mapping, and other disposable realizations need not become durable
entities. They must be reproducible from a declared input and compiler/runtime version when their
exact realization matters.

This corrects both bad extremes:

- **opaque-world extreme:** treating a mesh, splat, video generator, or latent tensor as the world;
- **database-of-every-vertex extreme:** assigning durable semantic identity to implementation detail
  that has no independent meaning.

## 3. One world, several epistemically distinct planes

The model is a composition of planes, not a flattened universal scene blob.

| Plane | Canonical meaning | Examples | Authority |
| --- | --- | --- | --- |
| Observation | What source bytes or sensors recorded | photographs, regions, camera metadata, admitted geographic records | content-addressed evidence and source records |
| Interpretation | What an actor or model believes the observations mean | entities, assertions, object hypotheses, place links, confidence and alternatives | append-only assertion and decision history |
| Spatial state | Metric or non-metric organization the system has earned | frames, poses, topology, occupancy, surfaces, attachments, navigation envelopes | validated immutable spatial snapshots |
| Authored state | What a person chose to add, move, suppress, or restyle | alternate versions, fictional objects, compositional edits | branch-local deltas with compare-and-swap |
| Generated state | What a model synthesized rather than observed | completed geometry, generated assets, imagined appearances | separate generated artifacts and proposals |
| Simulation | What happened inside a synthetic or counterfactual branch | actions, goals, schedules, interactions, state transitions | event log plus deterministic state snapshots |
| Representation | How another system currently consumes a plane | mesh, splat, point map, voxel map, semantic graph, embedding, thumbnail | derived artifact with a representation contract |
| Session | What this client is doing now | camera, focus, open panel, interpolation | ephemeral runtime only |
| Governance | What may be read, derived, changed, trained on, or exported | source rights, consent, retention, capability policy | policy evaluated at every materialization boundary |

The planes may refer to the same stable entity or place. They may not borrow one another's truth
status. A simulated visit does not become a memory. A generated back side does not become an
observation. A user correction may supersede an inference without rewriting the original output.

### 3.1 Provenance class, content truth class, and world plane are different axes

Three existing vocabularies answer different questions:

| Axis | Current values | Question answered |
| --- | --- | --- |
| Assertion provenance | `capture`, `inference`, `user`, `external` | Who or what supports this assertion? |
| Content truth class | `authorized_memory`, `admitted_source`, `authored_version`, `simulation` | What kind of world content is this result? |
| World plane | observation, interpretation, spatial, authored, generated, simulation, representation, session, governance | Which authority and lifecycle owns this state? |

They must not be collapsed. An admitted-source building may carry a user correction. An authored
object may have a model-produced representation. A simulation event may be generated
deterministically rather than by a learned model. `inference` does not mean fictional, and
`authored` does not mean false; each term is meaningful only on its own axis.

Historical answer clauses cite evidence spans through the evidence packet. Typed content handles
may explain imported, authored, or simulated material, but their existence does not convert them
into historical evidence. Simulation events explain a synthetic branch and must state that scope.

## 4. The world state is hybrid, temporal, and partially observed

Neither an object graph nor a dense field is sufficient.

Object-centric scene graphs are efficient for identity, relations, language queries, and dynamic
updates, but reduce shape, free space, uncertainty, and view-dependent appearance too aggressively.
Dense points, voxels, neural fields, and Gaussians preserve spatial and visual detail, but are
expensive, difficult to update semantically, and poor as sole authorities for identity or events.
Current research reaches the same conclusion from different directions: ConceptGraphs favors
object-level structure; DynaMem favors dynamic voxel memory; 3D-Mem explicitly combines
complementary representations; persistent embodied world models couple predictive models to a 3D
memory.

Exulanica therefore uses:

- stable **entities and relations** for identity and semantics;
- **events and assertions** for time, correction, and causal explanation;
- **coordinate frames, occupancy, surfaces, and fields** for metric spatial questions;
- **content-addressed observations** for evidence;
- **derived visual representations** for fidelity; and
- explicit **unknown space and competing hypotheses** where observations do not settle an answer.

Absence of a record is not evidence of absence. Occluded, unobserved, unavailable, withdrawn,
generated, disputed, and unsupported are distinct states.

Time is at least bitemporal:

- **valid/observation time:** when a condition was observed or is claimed to have held; and
- **record/transaction time:** when Exulanica learned, inferred, corrected, or accepted it.

Authored and simulated branches add a third coordinate: the world/version in which the condition
holds. No query may silently collapse those axes.

## 5. Materialization and representation contracts

Every derived spatial or visual artifact declares a machine-readable representation contract:

```text
representation_id and version
subject identities and branch
input artifact/state digests
producer, code/model version, parameters, and seed when applicable
coordinate frame, units, time scope, and resolution
preserved properties
lossy or unsupported properties
admissible uses
source/consent dependencies
quality measurements and uncertainty
content digest and availability
supersession and invalidation state
```

`preserved properties` and `admissible uses` are separate. A detailed mesh may preserve visible
shape well and still be inadmissible for collision. A semantic graph may preserve object identity
and still be unable to answer whether a table fits in a gap. An embedding may support recall and
still be inadmissible for membership or identity.

Representations form a lattice of task-specific projections, not a single quality ladder. The
existing reconstruction rung remains useful for observed visual/spatial recovery, but it does not
rank semantic completeness, editability, simulation fidelity, or predictive accuracy.

### 5.1 Parametric and procedural detail

Procedural construction is not inherently dishonest. Unrecorded procedural meaning is.

A facade grammar may emit thousands of window vertices without storing every vertex or even every
window as an entity. Its durable record must contain the admitted building identity, grammar
version, parameters, seed, output digest, and declared semantics. If windows become selectable,
editable, simulated, or individually persistent, they cross the materialization threshold and
receive stable element identities.

Trees, lamps, inhabitants, doors, traffic controls, and other objects that a person can reasonably
query or modify should not exist only as renderer-side loops. They require interpreted, source, or
authored records. Pure tessellation and shading detail may remain renderer-owned.

## 6. Observation, belief, and intervention

The update loop is:

```text
observe -> derive -> propose interpretations -> validate/confirm
        -> update a world branch -> materialize task views
        -> act or simulate -> record events -> compare with later observation
```

The architecture must retain both the prior and the correction. It should eventually support
multiple live hypotheses for ambiguous identity, place, geometry, and causality rather than forcing
one premature state. Confidence is attached to a claim and calibration method, not used as a
substitute for epistemic class.

An intervention is different from an observation. Moving a real object in a later photograph,
moving its authored counterpart in a fantasy branch, and predicting where it would move after an
action are three different transitions. Their shared entity relationship is useful; merging their
histories is false.

## 7. Dynamics and the claim to prediction

Simulation state is canonical only inside the branch and runtime contract that produced it.
Rendering interpolates simulation snapshots but does not invent canonical positions or actions.

The ordinary synthetic population should use bounded, inspectable transition systems: needs,
goals, plans, affordances, actions, resources, relationships, and events. A language or predictive
model may propose a plan or estimate an outcome, but the result carries its model receipt and is
validated against allowed actions and state constraints.

Exulanica earns a **predictive world-model** claim only after it demonstrates all of:

1. action-conditioned predictions over a declared state or observation space;
2. evaluation on future observations excluded from fitting and prompt selection;
3. calibrated uncertainty or useful abstention;
4. improvement over deterministic, retrieval, and no-memory baselines;
5. error measurement over increasing horizons, including compounding failures; and
6. no authority transfer from prediction into observed history.

A scripted schedule, plausible animation, or LLM narration does not meet this bar.

## 8. Read, write, inspect, and train

### World Read

World Read returns a query-scoped, rights-scoped bundle rather than dumping a database or selecting
one privileged representation. A caller requests subjects, time/branch, modalities,
representations, quality, and intended operation. The response carries stable identities, exact
digests, coordinate frames, epistemic classes, uncertainty, dependencies, and unavailable reasons.

### World Write

World Write accepts typed proposals:

- assertion or identity proposal;
- spatial interpretation proposal;
- authored branch edit;
- generated artifact publication;
- simulation action or rule update; or
- user correction, dispute, supersession, or withdrawal.

Each proposal names its base versions and intended plane. The backend validates authority, rights,
capabilities, topology, collision, and stale bases. A raw renderer scene is not a write format.

### Inspection

For every visible consequential feature, the system should answer:

- What is it?
- Which world and time does it belong to?
- Was it observed, inferred, authored, generated, or simulated?
- What inputs and transformation produced it?
- What can it safely be used for?
- What contradicts or supersedes it?
- What disappears if a source or consent is withdrawn?

The proof lens is one presentation of this interface, not the interface itself.

### Training

Trainability does not mean that all state is training data by default. A training projection must
declare task, subjects, features/targets, split, rights, people masking/consent, lineage, and
evaluation exclusions. It should export representation contracts and provenance alongside bytes.

Private world state never silently updates shared weights. A learned artifact derived from private
state needs its own deletion, retention, export, and model-unlearning position; if those cannot be
stated honestly, that training path is refused.

### 8.1 Current export coverage

Export is intentionally partial and capability-declared:

| Plane/content | Current package status |
| --- | --- |
| Evidence descriptors, semantic graph, reconstruction descriptors, structure, appearance, interaction, provenance | WMP 1.0 |
| Alternate versions, authored objects, reviewed assets and behaviors | Optional authored-world 1.0 extension |
| Durable environment instances | Not exported; authored delta schema v2 needs a versioned extension update |
| Owned-district source/interpretation | Not exported as a reusable district contract |
| Society state and simulation events | Not exported |
| Raw private media | Excluded by default |
| Training dataset | Separate opt-in profile and consent boundary |

A receiver that loads only supported planes must report the omitted planes. Signature verification
does not imply complete world transfer, asset availability, simulation compatibility, or runtime
behavior.

## 9. What is distinct—and what is not

The individual ingredients are not novel:

- temporal knowledge graphs retain changing facts;
- scene graphs retain object identity and relations;
- neural fields and Gaussian splats retain view synthesis;
- SLAM and voxel maps retain spatial memory;
- event sourcing retains transitions and replay;
- OpenUSD demonstrates non-destructive scene composition; and
- W3C PROV standardizes derivation records.

The potentially distinctive contribution is their **epistemically typed composition for personal
worlds**:

1. exact personal evidence remains reachable underneath semantic and spatial interpretations;
2. observed, inferred, authored, generated, and simulated states coexist without flattening;
3. every model-facing representation declares task affordances and losses;
4. edits and counterfactuals branch without rewriting memory;
5. source rights and person consent constrain reads, derivatives, training, and export transitively;
6. a generative or predictive model can read from and write back to the same governed memory; and
7. the result can be inspected and projected into a signed portable package.

This is a credible research direction. It is not yet evidence that Exulanica is better than a
temporal graph plus asset store, an OpenUSD stage, or a generative-world service. Section 10 is how
that claim is earned or rejected.

## 10. Falsifiable research program

| ID | Question | Comparison and measurement | Failure decision |
| --- | --- | --- | --- |
| WMM-1 | Does hybrid memory answer more useful spatial-semantic questions? | Compare graph-only, dense-only, retrieval-only, and hybrid views on held-out identity, relation, free-space, temporal, and source questions | Keep the simplest representation that matches the hybrid result |
| WMM-2 | Do stable identities survive representation changes? | Select and edit the same subjects through source, points, splat, mesh, semantic, and low-LOD views; measure identity agreement and lost operations | Refuse interchangeability for failing representations |
| WMM-3 | Is every consequential visible feature explainable? | Sample visible features and require complete plane, subject, producer, input, use, and withdrawal traces | Remove or demote untraceable features |
| WMM-4 | Does memory improve prediction? | Evaluate action-conditioned prediction with and without persistent 3D/event memory on held-out futures and increasing horizons | Do not claim a predictive world model |
| WMM-5 | Are branches semantically isolated? | Run memory, authored, generated, and simulated variants of the same place; test query leakage and source-claim contamination | Disable mixed-plane query/render paths |
| WMM-6 | Does correction remain coherent? | Correct identity, pose, geometry, and time; measure invalidation, rematerialization, old-link resolution, and untouched-state stability | Narrow automatic recomputation |
| WMM-7 | Does provenance remain usable at scale? | Have independent users and clients answer origin/use/withdrawal questions under realistic scene size and latency budgets | Reduce or redesign the provenance surface |
| WMM-8 | Does representation plurality justify its cost? | Measure storage, build time, frame time, query latency, and task benefit for each retained projection | Delete projections without unique measured value |
| WMM-9 | Do synthetic inhabitants exhibit purposeful behavior? | Compare random walk, schedule, utility planner, and bounded model planner on goal completion, explanation accuracy, replay, and human legibility | Keep deterministic schedules or remove inhabitants |
| WMM-10 | Can another system reconstruct meaning, not merely bytes? | Export a signed package; have an independent client recover identities, planes, lineage, branch diffs, and declared unsupported uses | Do not claim interoperability |

Before each experiment, freeze the corpus, rights, train/development/held-out split, baselines,
metrics, practical effect threshold, and failure action. A visual demonstration is evidence for
appearance only. A fixture proves mechanics only. A benchmark score does not establish personal
usefulness.

## 11. Immediate architecture consequences

1. The owned district's admitted building and sidewalk records remain valid source-derived spatial
   inputs. Browser-only storefronts, windows, trees, lamps, furniture, and pedestrian routes are
   not promoted to world state.
2. District interpretation moves to a versioned compiler that emits semantic/interpreted elements,
   parametric facade and ground records, source dependencies, uncertainty, and a materialization
   receipt. The renderer consumes that output.
3. Roads require an admitted or explicitly derived road representation. “Asphalt everywhere not
   occupied by a building” is a visual fallback, not road data.
4. Synthetic inhabitants require durable goals, routes, actions, and events. The 24-avatar limit
   remains a representation budget over a larger population, never a population limit.
5. Semantic selection, collision, simulation, and rendering resolve through shared stable subjects
   but may consume different validated projections.
6. No visual work is accepted if its meaningful content exists only in PlayCanvas entity names or
   mesh-generation loops.
7. Renderer-only detail remains permitted when it is demonstrably non-consequential and covered by
   a declared style/runtime version.

## 12. Non-goals

- one universal tensor, ontology, scene format, or database table;
- storing every render primitive as semantic state;
- claiming observed truth for generated completion;
- requiring a neural model for deterministic composition or ordinary simulation;
- making OpenUSD, a knowledge graph, Gaussian splats, or an LLM the sole world authority;
- training on private memories by default;
- autonomous model writes to protected world state; or
- calling a coherent demo a general world-model result.
