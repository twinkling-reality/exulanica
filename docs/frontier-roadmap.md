# Frontier roadmap: adaptive personal world memory

Status: **DECISION and IMPLEMENTATION PLAN**. This document orders existing Exulanica decisions
(the product was formerly Orimera) into one exit-gated delivery plan. It does not turn an
assumption into a shipping claim. Where the research is unresolved, the roadmap names the
experiment that must settle it.

Last reconciled: 2026-08-31.

## 1. North-star output

The current product direction is [personal worlds, creation, and later simulation](product-direction.md).
Build your own world from your life, then change what's possible inside it.
That direction supersedes the earlier reconstruction-only and competitive "stateless imagination"
framing. The numbered work below preserves the existing engineering history and dependencies;
it is not the complete creative-world delivery sequence.

The next product milestone is a reconstructed place, an alternate version, one created object,
and one bounded interaction, with saved state and a concrete developer read/edit path. See the
[new delivery gates](product-direction.md#first-milestone).
General simulation, unconstrained creation, and compatible runtime packages remain future work.

Original evidence, identity, topology, appearance, and package machinery remain foundations.
Creative changes must preserve their source history without being restricted to reproducing it.

### 1.1 Public product and runtime naming

Public entry points name the product, not its current internal runtime. The landing action is
**Enter Exulanica**. “Enter World” is not used because it is generic, and “Enter Atlas” exposes a
subsystem name as though it were a second product.

Atlas remains the internal name of the navigable world runtime for now. A future Atlas-to-Exulanica
technical migration is a separate release decision, not a landing-copy change. Before scheduling
it, inventory persisted browser keys, environment variables, routes, package names, tests, and
operator documentation; then choose either a pre-release clean cutover or an explicitly versioned
compatibility migration. Until that decision, public surfaces say Exulanica and technical runtime
documents may say Atlas.

## 2. Non-negotiable contracts

Every phase below preserves these rules.

- Historical factual claims resolve to original evidence bytes. Derived geometry, captions,
  embeddings, summaries, and world placement are not evidence.
- A model may propose. It may not silently confirm identity, rewrite protected topology, perform an
  irreversible action, or grant itself a new capability.
- Topology, layout, reconstruction, style, and package versions are immutable snapshots. Moving a
  current pointer is an atomic compare-and-swap operation.
- Missing evidence, unavailable bytes, unsupported reconstruction, stale versions, and failed
  processing remain distinct states.
- A style or interaction adaptation selects from a reviewed capability registry. It cannot provide
  CSS, markup, JavaScript, shaders, remote texture URLs, renderer programs, or interface layout.
- New visual or interaction capabilities enter through reviewed code and a versioned registry. No
  universal schema is invented for capabilities that do not yet exist.
- Raw media, credentials, biometric templates, and embeddings are excluded from export by default.
- A World Memory Package is a projection of the live store at a named instant. It is not the live
  store and cannot be recalled after a recipient downloads it.
- Deletion invalidates derived state, and recomputes the part of it that is a pure function of
  the remaining data. A model-produced artifact is **removed, not regenerated**: re-running a
  sampled generation would produce different bytes, so an exactness claim over it would be
  false in the ordinary case. See [adr/0017-exact-recomputation.md](adr/0017-exact-recomputation.md).
  It is never described as model unlearning.
- The renderer consumes published assets and manifests. It does not author canonical memory or
  topology state.

## 3. Current implementation baseline

The status terms in this table describe repository state, not aspiration.

| Capability | Status | What exists | Remaining boundary |
| --- | --- | --- | --- |
| Evidence-addressed spine | **BUILT** | Canonical source addresses, spans, assertions, artifacts, tombstones, active row-level security, and provenance ledger | Backup restore rehearsal |
| Photograph intake | **BUILT** | Idempotent intake, upright normalization, rendition, dedicated derivative worker, leases, bounded retries, durable delivery replay, and measured queue metrics | Hosted load and backpressure rehearsal |
| Vision observation | **BUILT** | Strict structured observation schema, evidence-linked inference rows, model manifest, cost and attempt provenance | Real-corpus accuracy and failure measurements |
| Semantic memory and selection | **BUILT/PARTIAL** | Occurrences, entities, confirmation boundaries, identity proposals, graph snapshots, and validated selection plans | Complete answer path, real-corpus retrieval evaluation, and long-term memory maintenance |
| Rung 4 source-first region | **BUILT/PARTIAL** | Honest source-first contract, authenticated production source delivery, and renderer fixtures | Authorized real-corpus exercise and measured envelopes |
| Rung 3 point map | **BUILT/PARTIAL** | Optional MoGe prediction, OPM/2 producer, quality gate, artifact provenance, authenticated delivery, posed multi-map scene rendering, and assertion-backed rung disclosure | Authorized real-corpus quality study and deployed operation |
| Rung 2 corridor | **PLANNED** | Product and traversal contract plus production pose and placement receipts | Physically validated scale, coverage analysis, trajectory corridor, structural-world authority, and nav artifact |
| Rung 1 splat | **PLANNED** | Production pose receipts, `gsplat` selection, deployment shape, license decision, and quality-gate concept | Reviewed resumable gsplat job, compatible GPU execution, measured scale and coverage, compression, nav proxy, and real-capture result |
| Spatial world core | **BUILT/PARTIAL** | Deterministic composition, stable identities, protected values, neighborhoods, residency planning, navigation, and renderer binding | Backend topology, layout, placement, and neighborhood authority plus physical streaming |
| Adaptive appearance | **BUILT** | Reviewed profile registry, exact frontend handshake, validated parameters, immutable global/regional versions, global preview/apply/discard/refine/rollback UI, stale recovery, authenticated source states, and audit provenance | Upstream conversational proposal service, regional renderer preview, and structural proposal path |
| Adaptive interaction | **BUILT/PARTIAL** | Reviewed capability registry, immutable versions, Settings and Companion preview paths, direct-choice apply, explicit Companion review, rollback, inspection, recommendations, and cross-device hydration | Real-participant comprehensibility and longitudinal stability evaluation |
| World Memory Package | **BUILT AND EXIT-GATED** | RO-Crate 1.2 Exulanica profile, Croissant/RAI node, honest external references, canonical manifest, signed Merkle root, append-only receipt, offline verify/inspect/diff/import-check, privacy scan, and deletion re-export | Receiver-side transactional import remains intentionally deferred |
| Evaluation | **BUILT/PARTIAL** | Deterministic corpus tooling, methodology, metrics, authorization checks, model preflight, and a generated-fixture end-to-end acceptance run | Gold labels, real reconstruction results, and an authorized personal-corpus frontier run |
| Frontier demonstration | **IMPLEMENTED/REAL RUN BLOCKED** | Strict versioned manifest, one source-to-package command, real formation/evidence/Selection/world/adaptation/export paths, clean verifier, reuse receipt, and deletion diff | User-authorized ordinary photo directory, selected real credentials/hardware modes, and user-supplied signing key |
| Hosted operation | **PARTIAL** | Container, health/readiness routes, non-owner runtime role, separate derivative worker, deployment design, and failure policy | Clean deploy, backup restore, external monitor, and production rehearsal |

Per-scene Gaussian-splat optimization is therefore already in the roadmap. It appears in the
product reconstruction ladder, deployment topology, model/service selection, license matrix, and
evaluation stages. What did not exist before this document was one dependency-ordered plan from
source media to verified export.

## 4. The state planes

Personalization must not collapse every kind of state into a single opaque “world model.” Each plane
has a different authority, version rule, and export rule.

| Plane | Canonical contents | Who may change it | Version and conflict token | Export default |
| --- | --- | --- | --- | --- |
| Evidence | Original captures and exact spans | Authenticated ingest and explicit deletion | Content digest plus capture/span identity | Metadata and digest only; bytes excluded |
| Semantic memory | Occurrences, confirmed entities, supported assertions, rejected proposals | Pipeline inference, user confirmation, deletion repair | Graph snapshot/version plus provenance | Included with epistemic class and support references |
| Reconstruction | Renditions, depth maps, point maps, poses, splats, nav proxies | Reviewed deterministic/model stages | Artifact idempotency key, input digest, stage/model version | Descriptors and digests; payload policy explicit |
| Topology and layout | Regions, ownership, transforms, sockets, destinations, collision/navigation contracts | Reviewed composer and structural transaction | Immutable topology/layout version plus cryptographic digest | Included as declarative snapshots |
| Appearance | Profile id/version and capability-backed values | User, Settings, or Companion proposal through preview/apply | Immutable style version plus topology digest | Included; no executable bindings |
| Interaction | Comfort, initiative, navigation, disclosure, and reviewed behavior parameters | User directly or Companion proposal under consequence policy | Immutable interaction-policy version plus relevant world base versions | Included when user permits; no conversation transcript by default |
| Session | Camera pose, open surface, focus, transient preview, pending choice | Runtime only | Ephemeral session/revision token | Excluded |
| Provenance | Pipeline, proposal, apply, rejection, rollback, deletion, and export events | System append path | Append-only event identity and sequence | Included after private payload scrubbing |
| Package | Projection of selected planes at one instant | Explicit export transaction | Package profile version, Merkle root, signature | The exported artifact itself |

“The world adapts to the user” therefore means a traceable change to the semantic, spatial,
appearance, or interaction planes. It does not mean silently modifying neural weights or allowing a
model to emit runtime code.

## 5. One end-to-end world-build loop

The delivery unit is a resumable world build, not a collection of disconnected demos.

```text
source media
  -> admit and address
  -> derive and observe
  -> form semantic memory
  -> reconstruct each region to its earned rung
  -> compose protected topology and layout
  -> resolve reviewed style and interaction state
  -> validate evidence, reachability, authorization, and budgets
  -> publish immutable runtime manifests and assets
  -> project and sign a World Memory Package
  -> verify, evaluate, and emit a build receipt
```

Every stage has five mandatory properties:

1. versioned inputs and parameters;
2. an idempotency key before expensive work begins;
3. explicit progress, retry, skip, failure, and cancellation events;
4. immutable outputs with provenance; and
5. a stage-specific acceptance gate or an honest fallback.

The build manifest is a narrow orchestration contract, not a universal visual schema. Its first
version records only:

- workspace and world identities;
- authorized source references;
- pipeline and model-manifest digests;
- enabled reviewed stage versions;
- the selected registered world profile/version;
- reconstruction and resource budgets;
- export inclusion policy; and
- deterministic seed only where a reviewed algorithm requires one.

It contains no credential, model-generated program, renderer binding, arbitrary schema fragment, or
UI layout. Changing an input that affects output changes the build identity.

## 6. Concrete outputs

### 6.1 Live World Runtime

The runtime publication contains immutable references to:

- the current graph snapshot;
- topology, layout, placement, and neighborhood versions;
- global and regional style versions;
- interaction-policy version;
- reconstruction rung and asset availability per region;
- evidence/source bindings;
- residency keys and declared resource costs; and
- warnings and fallback reasons.

The runtime fetches authorized content by stable local identity. It never receives remote texture
URLs or an executable world description.

### 6.2 World Build Receipt

Each completed or terminally failed build emits a machine-readable receipt containing:

- build id, parent build id, start/end time, and final state;
- exact source, stage, model, registry, and profile versions;
- input/output content digests and artifact lineage;
- stage timing, attempts, cost, cache reuse, and fallback decisions;
- reconstruction rung decisions and their measurements;
- validation and evaluation results;
- topology, style, interaction, and package version ids;
- unresolved warnings and unavailable assets; and
- the package Merkle root and signature result when export ran.

This receipt is the technical proof that a result was produced by the real pipeline rather than by a
scripted demo path.

### 6.3 World Memory Package

The package format remains the decision already made in
`domain-and-evidence-model.md`: RO-Crate 1.2 under an Exulanica profile, a Croissant 1.0 plus RAI node
in the same JSON-LD graph, BagIt-style fetch records for deliberately excluded payloads, and a signed
Merkle-root manifest.

The v1 profile must represent:

- package/profile version and parent package root;
- workspace-independent exported identities;
- semantic graph snapshot with epistemic class and evidence support;
- evidence descriptors, digests, availability, and authorization/export decision;
- reconstruction artifacts, rung, producer, model/stage version, and quality measurements;
- topology, layout, placement, neighborhood, appearance, and interaction snapshots;
- capability/profile registry references required to interpret appearance values;
- provenance and build receipt;
- consent/export policy and generated-content declarations;
- missing, unavailable, redacted, and intentionally excluded states; and
- evaluation results required by the package profile.

The default package excludes raw media, credentials, bearer paths, embeddings, biometric templates,
model caches, private conversation text, transient previews, and session state. An explicit media
export is a separate user-confirmed policy that creates a different package root.

The package contains declarative state and content-addressed artifacts. It contains no CSS, HTML,
JavaScript, shader, remote code, interface layout, service credential, or unreviewed capability.

The required tools are:

- `project`: materialize a package from one committed live-store snapshot;
- `verify`: validate the profile, file digests, Merkle root, signature, provenance closure, and
  prohibited-content rules without trusting Exulanica;
- `inspect`: produce a human-readable inventory and warnings without importing private content;
- `diff`: compare two roots by semantic, topology, style, interaction, evidence, and artifact change;
- `import-check`: establish compatibility and missing capabilities without mutating a live world;
  and
- `import`: a later explicit transaction, never an automatic side effect of inspection.

Round-trip byte identity is required for opaque included assets. Semantic identity is required for
normalized JSON-LD after canonicalization. Import does not make exported inferences true and does not
grant capabilities absent from the receiving registry.

## 7. Exit-gated implementation roadmap

The phases are dependency ordered. Work inside a phase may run in parallel when it does not share a
migration or public contract.

### Parallel frontend track: Exulanica public identity and landing system

Status: **FIRST LANDING PASS BUILT 2026-09-04; broader public-surface rollout pending**.

Deliverables:

- adopt **Exulanica** as the public product name across the landing page and other user-facing
  surfaces while preserving Atlas, Companion, and Aeroheart as named product concepts;
- translate the approved soft geometric, mesh-gradient, editorial direction into an original
  product-specific visual system rather than reproducing the reference artwork or using arbitrary
  decorative blobs;
- define interchangeable accent palettes through shared tokens while retaining one stable
  luminance, contrast, texture, and reduced-motion contract;
- make the landing composition express the product's evidence-before-geometry rule and preserve a
  clear route into Atlas;
- identify **Twinkling Reality** as the publisher on the signed-out surface, following the compact
  `© 2026 Twinkling Reality` convention used by the rest of the product family;
- replace the title menu's line selector with one non-interactive miniature Companion moving among
  four quiet registration stations; use one restrained distance-aware glide and optical colour wake,
  respond equally to pointer hover and keyboard focus, yield to focus when they conflict, and remain
  static under reduced motion;
- retain that lower-left Companion navigation on the title, Purpose, and Capabilities surfaces;
  keep Resources as one primary station whose Documentation and GitHub links appear in a
  keyboard-operable secondary disclosure rather than becoming additional Companion stations;
- move the Companion's renderer-neutral silhouette, eye-pose, palette, and state blueprint into the
  shared presentation contract before the landing uses it, so the miniature and Atlas presence are
  two presentations of one identity rather than drifting copies;
- design an original Exulanica Companion form instead of shipping the Grok-derived silhouette as a
  product identity; keep V3's shape, colour, and expression choices truthful until separately
  versioned motion and material-depth axes have implementations and migrations;
- treat genuine 3D Companion depth as a new renderer, asset-provenance, performance, and
  accessibility decision rather than relabeling SVG shading as 3D; prototype 2D, bounded relief,
  and world-rendered forms before approving that contract;
- define cross-surface preference authority before claiming that a customized Atlas Companion also
  appears on the public landing; until then the landing uses the shared default without reading or
  inventing account state;
- complete the Mode A namespace cutover recorded in ADR-0011: Exulanica is the canonical
  technical namespace for new writes, disposable fixtures, WMP v1, permalinks, headers,
  environment variables, and CLI names. Orimera survives only in historical SQL 0001 through
  0027, git history, and the ADR evidence table.

Exit gate: the supported landing-page viewports consistently present Exulanica and its Twinkling
Reality publisher signature, contain no stale public Orimera branding, and pass contrast and visual
regression review. The menu retains native link/button semantics, visible focus, a single
pointer-transparent Companion marker, focus-over-hover precedence, and a motionless reduced-motion
state. The landing and Atlas renderers consume one tested visual blueprint. New identifiers say
Exulanica. Historical compatibility remains only where ADR-0011 proved it is required.

### Phase 0: evidence and adaptive-style foundation

Status: **BUILT**.

Delivered:

- evidence spine, provenance ledger, deletion/tombstone mechanics, ingest and derivative stages;
- graph, selection, identity proposal, API, authorization, and model boundaries;
- deterministic spatial core and PlayCanvas renderer decision;
- reviewed world profile/capability registry;
- immutable style versions and isolated preview/apply/discard/rollback; and
- source-media metadata with honest missing/unavailable states.

Exit gate: the full backend suite, contract tests, import boundaries, and migration tests pass. A
style writer cannot bypass the registry or protected topology digest.

### Phase 1: production asynchronous processing

Status: **BUILT 2026-08-31**.

Deliverables:

- configure the API and workers to connect as the non-owner runtime role so row-level security is
  active in deployment;
- add the measured workspace/kind-aware derivative claim index;
- expose a dedicated derivative-worker command and a deployment job adapter;
- make startup, graceful shutdown, lease renewal, retry, reclaim, cancellation, and terminal failure
  observable;
- retain exactly-once effects through idempotent writes even though work delivery is at least once;
- add queue depth, age, attempt, duration, cost, and failure-class metrics;
- record real stage counters for formation/progress streams; and
- test two-worker contention, process death, lease loss, deletion during work, and restart from a
  clean process.

Exit gate: kill a worker at every stage boundary, restart with two workers, and obtain one canonical
artifact set, one terminal job state, no duplicate paid model result, and a complete replay ledger.

The gate is executable in `tests/test_derivative_reclaim.py`. It terminates a real worker process
after the committed intake, rendition, vision, and depth boundaries, expires the abandoned lease,
then starts two competing processes. Each case finishes with one content-addressed artifact per
stage and capture, one terminal delivery event, no open pipeline run, and one paid vision result per
capture. The same PostgreSQL suite covers live lease renewal, retry exhaustion, deletion during a
paid stage, graceful shutdown, and runtime refusal of an owner or BYPASSRLS-capable database role.
Operational behavior and the boundary of the guarantee are in
`derivative-worker-operations.md`.

### Phase 2: real corpus and evaluation baseline

Status: **NEXT; the Phase 1 event schema is settled**.

Deliverables:

- capture and consent the OGC-1 corpus defined by the evaluation methodology;
- freeze train/development/blind partitions and prevent the blind partition from training access;
- label evidence regions, entities, reconstruction suitability, and expected selection results;
- measure current vision schema accuracy, abstention, identity proposal quality, citation resolution,
  ingest timing, cost, and cache reuse;
- archive exact model and pipeline versions with each run; and
- publish baseline failures rather than tuning against an unknown denominator.

Exit gate: the evaluation harness can reproduce one versioned report from a clean database and can
prove the blind split was not read by any training or tuning path.

### Phase 3: reconstruction ladder

Status: **Production rung-3 path built 2026-09-04; representative real-corpus run blocked; rungs 1 and 2 experimental**.

#### Phase 3A: production rung 4 and rung 3

- publish authorized source-first assets and measured source-panel envelopes;
- run MoGe point-map production against the real corpus;
- validate `.opm` integrity, rung reasoning, metric/non-metric behavior, deletion cascade, and
  PlayCanvas consumption; and
- establish quality distributions before changing the existing unvalidated rung threshold.

Gate: every region produces a navigable source-first result, and every accepted point map opens at
the source camera pose with the correct evidence link and no spatial claim derived from Atlas
placement.

#### Phase 3B: camera poses and scene grouping

Implementation status: **BUILT 2026-09-04 for the production rung-3 path.** Normal scene grouping
applies a versioned selection policy, queues an immutable exact member set, and a separate leased
worker produces digest-bound pose, placement and gate receipts. The graph validates that chain and
the renderer draws every available placed OPM/2 map. Registered and unregistered outcomes remain
attached to the complete original set. A representative authorized corpus is still required to
measure registration and quality before changing any unmeasured gate.

- select dense capture groups from the user's own media;
- run COLMAP sparse reconstruction in an idempotent, checkpointed job;
- record registered-image fraction, reprojection error, camera translation, failure reason, and
  artifacts;
- test joint co-registration of two captures of the same place before allowing shared metric frames;
  and
- fall back to rung 3 when pose recovery or coverage is insufficient.

Gate: the pose artifact and quality report are reproducible from the same source/build manifest, and
no region is promoted because a semantic place label merely resembles geometric co-registration.

#### Phase 3C: per-scene Gaussian-splat optimization

- train each accepted scene with the reviewed Apache-2.0 `gsplat` path, never the blocked INRIA
  rasterizer;
- checkpoint preemptible runs and resume without restarting completed work;
- record GPU, code revision, parameters, iterations, timing, cost, and source set;
- evaluate held-out views, floaters, coverage, and browser resource size;
- compress the accepted result to the PlayCanvas delivery format; and
- keep training intermediates out of the runtime and World Memory Package by default.

Gate: a scene earns rung 1 only when its declared registration, view-quality, coverage, and artifact
integrity checks pass. Failure publishes rung 3 or rung 4 with the reason. This is scene-specific
optimization, not fine-tuning a general Exulanica model.

#### Phase 3D: corridor and navigation artifacts

- derive rung 2 camera trajectories and allowed lateral/look envelopes from real poses;
- build nav/collision proxies separately from splat pixels;
- produce rung 1 traversable surfaces from reviewed reconstruction/nav tooling;
- validate clearance, slope, required destinations, source vantage, and recovery poses; and
- bind every nav artifact to the reconstruction and topology versions it was measured against.

Gate: every published required destination is reachable for the declared agent radius, and the
renderer cannot expand the validated movement envelope.

### Phase 4: durable spatial world authority

Status: **BUILT; no production snapshot materialized without authorised real inputs**.

Deliverables:

- immutable topology, layout, placement, and neighborhood snapshots with canonical SHA-256 digests;
- a reviewed composition service that consumes graph and reconstruction snapshots;
- stable world/region/module/element identities and lineage;
- current pointers and atomic compare-and-swap against all protected base versions;
- deletion invalidation and deterministic fallback/recomposition;
- structural preview with protected-value diff and reachability/collision/evidence checks; and
- package projection for every spatial version.

Exit gate: two stale composers cannot both become current; graph changes cannot move an existing
region without a recorded migration; and an appearance transaction cannot alter any structural
value.

### Phase 5: adaptive world and interaction state

Status: **BUILT 2026-08-31; human/longitudinal evaluation blocked on real participants**.

Deliverables:

- connect Settings and Companion to the same production proposal lifecycle;
- add immutable interaction-policy versions for reviewed comfort, navigation, disclosure, and
  initiative parameters;
- keep consequence tiers and explicit confirmation for identity, structure, sharing, deletion, and
  export;
- record proposal inputs, reference ids, origin, actor, model/prompt version, capability mapping,
  acceptance, rejection, refinement, and rollback;
- bind conversational appearance proposals to inert recipe/profile versions and reviewed frontend
  module IDs without accepting CSS, markup, scripts, shaders, renderer programs, layout, remote
  texture URLs, or private media;
- derive suggestions from observed user choices without converting them into silent writes;
- separate durable preference from transient session behavior; and
- evaluate whether adaptations are understandable, reversible, stable across sessions, and free of
  protected-topology effects.

Gate: the same proposal produces the same validated candidate against the same bases; a
Companion-origin recipe proposal carries actor/origin, references, model/prompt versions, exact
module/capability mapping, and optional refinement lineage; preview is isolated; discard is
state-neutral; explicit apply records acceptance; invalid proposals record rejection; rollback
appends history; stale bases fail; unknown recipe versions/modules/capabilities/parameters fail
closed; and a user can inspect why an adaptation was proposed.

The deterministic and protected-state parts of this gate are PostgreSQL-, API-, and browser-tested.
The browser sends range motion only to transient rendering and commits the final user choice through
the production policy lifecycle. Companion-authored changes stop at an isolated preview until a
separate confirmation call applies the review handle. No real-participant study is present, so this
repository does not claim that explanation copy is understandable or that adaptations remain
desirable across repeated weeks. See [interaction-policy-backend.md](interaction-policy-backend.md).

The reviewed `55b1236` → `5c95cb3` frontend execution half is integrated with the backend through
one tested adapter. Settings and typed upstream Companion proposals use the backend lifecycle while
the local registry, modules, contrast/accessibility correction, protected geometry, and rendering
remain frontend authority. The browser does not invent the still-missing conversational proposal
service, and it refuses regional proposals until a reviewed regional renderer preview exists.

No neural fine-tuning is required for this phase. Personalization is explicit, versioned world state.

### Phase 6: physical streaming and rendering hardening

Status: **RENDERER CONTRACT BUILT 2026-08-31; production publication and hardware gate blocked**.

Deliverables:

- turn residency actions into cancelable fetch, decode, upload, downgrade, unload, and disposal;
- enforce authenticated asset availability and honest rung fallback;
- expose provenance-bearing source/evidence asset references only for available authorised media,
  never inside style recipes;
- add neighborhood origin rebasing and scalable world-field buffers;
- batch repeated modules, motes, and relationship traces;
- test context loss and recover to a complete World Index path;
- measure range-request behavior rather than assuming it; and
- drive automatic representation downgrade from frame time and resource pressure, not device
  sniffing.

Exit gate: a large fixed topology remains navigable under declared CPU, GPU, and network budgets;
cancelled/stale fetches never become current; and performance degradation lowers representation
without losing evidence access or changing world identity.

The local implementation now executes cancel-safe fetch/decode/upload/publication and physical
disposal, distinguishes asset fallback states, observes rather than assumes Range responses,
rebases GPU coordinates by durable neighborhood, sizes world-field buffers from exact topology,
opens the complete World Index on context loss, and lowers representation from measured frame and
resource pressure. Its deterministic contracts are tested. The full exit gate is not claimed:
Phase 3 produced no authorised real published asset, and no declared target hardware or deployed
asset origin is available for the required large-world and network measurements. See
[physical-streaming-runtime.md](physical-streaming-runtime.md).

### Phase 7: World Memory Package v1

Status: **BUILT AND EXIT-GATED**. See `docs/world-memory-package.md` for the frozen v1 profile,
privacy boundary, commands, transaction semantics, and executable evidence.

Deliverables:

- publish the Exulanica RO-Crate profile and its versioning rules;
- implement a transactionally consistent projector;
- canonicalize manifests, build the Merkle tree, sign the root, and retain export audit provenance;
- implement independent verify, inspect, and diff commands;
- enforce the prohibited-content scan and default exclusions;
- support honest external/fetch references for excluded media;
- include graph, reconstruction, topology, appearance, interaction, provenance, and evaluation
  snapshots with compatibility declarations;
- test export during concurrent style/topology mutation; and
- test deletion followed by re-export and a human/machine-readable package diff.

Exit gate: verification succeeds in a clean environment with no database access; one-byte payload or
manifest mutation fails; prohibited private/runtime material is absent; and a post-deletion export
has a new root whose diff names the removed and recomputed state.

### Phase 7B: training-use consent and consented dataset export

Status: **PROPOSED 2026-09-06**, sequenced after the person-region masking and presentation
consent layer (`docs/person-presentation-consent.md`), which it depends on.

Premise: labs building world models need real, diverse, rights-clean environments with camera
poses, and cannot get them cleanly. The pipeline already produces posed multi-view captures with
human screening receipts, per-person consent state, provenance digests, frozen held-out splits and a
verifiable package. Making that licensable turns the trust layer into a product, with the user, not
the platform, as the licensor. It is an option on top of the memory product, never a change to it:
default off, opt-in per package, and revocable.

Deliverables:

- a fourth consent, **training use**, recorded per package as an immutable receipt with scope
  (which model classes, which licensee, which term), separate from presence, naming and likeness;
- inheritance rules: a package is exportable for training only when every person in it has a
  training-use consent or is masked out of the export; a later withdrawal revokes the licence for
  future exports and is recorded against past ones;
- a **dataset export profile** of the World Memory Package: exact source images, recovered
  cameras and calibration, masked derivatives, sparse and trained geometry, capture metadata, the
  held-out split, and the provenance chain, all digest-bound and independently verifiable;
- a **ledger** of exports with licensee, terms, digests and attribution or payment, readable by the
  user, so licensing is auditable rather than implied;
- a prohibited-content scan and default exclusions equal to or stricter than the package's; and
- honest framing in every export manifest: recorded captures with rung labels, no simulation or
  adaptation claims.

Exit gate: an export refuses when any pictured person lacks training-use consent and is not masked;
a revocation changes the next export's root and names the removed material; a licensee can verify
an export offline; and at least two prospective licensees have evaluated a sample export and stated
in writing what they would pay for what volume (experiment FR-11). Without that demand evidence the
phase stays a design, and the memory product does not depend on it.

Risks named up front: personal captures are small and messy compared with what labs want; value
is in aggregation, which pulls against the user-as-licensor stance unless the marketplace is ours;
and the moment users believe their memories train someone else's model by default, the trust story
that makes the memory product work is at risk. Default off is not negotiable.

### Phase 8: end-to-end frontier demonstration

Status: **IMPLEMENTED AND DEVELOPMENT-EXIT-GATED; AUTHORIZED PERSONAL-CORPUS RUN PENDING**. See
[`frontier-demonstration.md`](frontier-demonstration.md) for the strict manifest, destructive
boundary, command, output contract, and executable evidence. The PostgreSQL acceptance run uses
generated photographs and a counting model fake; it proves the orchestration mechanics and does
not substitute for consented media, live model results, or real reconstruction quality.

The demonstration starts from an ordinary authorized photo directory and runs the real pipeline:

1. ingest and show real stage formation;
2. open exact evidence and its provenance;
3. show the semantic memory graph and a supported answer;
4. enter regions at the rung each actually earned;
5. create a Companion-origin inert recipe proposal, preview it, refine it, discard the draft,
   explicitly apply the refinement, inspect provenance, and roll back through immutable history;
6. show a protected-topology or stale-version rejection;
7. export a World Memory Package;
8. verify it in a clean process;
9. re-run the same build and show cache/idempotency reuse; and
10. remove one source, rebuild, and show the package-root diff and honest fallback.

The demo discloses which expensive artifacts were precomputed. It never puts a fake progress bar in
front of cached reconstruction or special-cases the scripted questions.

Exit gate: one command or one top-level task orchestrates the stages from a versioned manifest,
produces the runtime world, receipt, evaluation report, and signed package, and stops only when every
mandatory gate passes or a named honest fallback is terminal.

`exulanica-frontier demonstrate` now satisfies that mechanical gate, including exact evidence
opening, validated deterministic answer, actual-rung world composition, conversational recipe
proposal/refinement/discard/apply provenance, style and structural stale rejection, immutable style
rollback, clean-process verification, zero-call artifact reuse, and one-source deletion/re-export.
The frontier milestone itself remains open until the command is run on a user-authorized personal
directory with user-owned signing/credential/hardware decisions; none were supplied during this
implementation.

### Phase 9: post-MVP learning research

Status: **DEFERRED UNTIL EVALUATION JUSTIFIES IT**.

Possible work:

- train a task-specific detector only if the real corpus demonstrates a repeated detection gap that
  reviewed prompts/model routing cannot solve;
- learn ranking or proposal-priority functions only against consented labels and a blind split;
- investigate self-hosted embedding continuity only if frozen precomputation is inadequate; and
- evaluate preference recommendation from versioned accepted/rejected proposals without training on
  raw private conversation or media by default.

No model is fine-tuned merely because the provider advertises fine-tuning. A training proposal must
first name the failing metric, lawful/consented dataset, non-training blind set, baseline, target,
rollback, deletion closure, derived-weight export policy, and cost. Without all of them it remains a
research note, not a roadmap task.

Biometric embedding training remains blocked until the consent rule in the product and privacy
specifications is decided. Private-memory-derived weights are excluded from the World Memory Package
by default.

### Phase 10: the memory layer for world models

Status: **DECIDED 2026-09-06, STARTING**. This phase turns the north-star positioning (a persistent,
real, per-entity world that generative world models read from and write to) into interfaces and
tiers. It precedes Phase 7B, whose dataset export is this phase's read interface served as a file.

Five capabilities, in delivery order:

1. **World Read API.** For an entity, a place and a time, one authenticated route returns what a
   generative model may condition on and nothing else: posed views (masked where consent requires),
   camera calibration, point maps or trained geometry, the region graph, rung labels and consent
   state, digest-bound. Built from the existing graph payload and artifact routes in
   `exulanica/graph`. Exit: a clean client reconstructs the bundle's digests offline; a request for
   a scene containing a person without likeness consent receives that person masked, verified by
   test; nothing derived is presented as evidence.
2. **World Write API and the generated tier.** Content a world model imagines for unobserved parts
   is stored as a `generated_scene` artifact in its own tier below every recorded rung, with the
   model, version, prompt digest and the exact conditioning digests it received. It is never
   citable and never promotes a rung. Atlas renders it only under a visible label. Exit: the graph
   carries `generated_geometry` separately from recorded geometry; a generated scene cannot satisfy
   any gate; the status names the model and the seam.
3. **One place across captures and time.** Cross-scene alignment through shared sparse features
   links separate captures of the same place into one `place` entity with versions by capture time
   (forward migration). Atlas merges the regions and exposes time as a dimension. This is experiment
   FR-2 made product. Exit: two consented captures of one real place, weeks apart, share one frame
   within a measured tolerance, and the world shows both versions in place.
4. **Persistent objects.** Detections link into object entities across captures with user
   confirmation; people are excluded from automatic linking (no biometric templates). Exit: an
   object named once is found in later captures with a measured precision on a blind split, or the
   feature stays confirmation-only.
5. **Consent on every read.** The person-region and presentation-consent layer
   (`docs/person-presentation-consent.md`) gates the read API. No third party sees an export before
   this lands.

Atlas work in the same phase: a **proof lens** (colour by tier: photographed, reconstructed,
generated), **click-to-evidence** (select a surface, see the photographs that observed it, with
their consent states), and the generated tier drawn under the lens. Infrastructure in parallel: a
GPU dispatcher and an image registry so a read of an unbuilt place can trigger its build without
an operator.

First-week sequence: read API and generated tier (they define the product), proof lens and
click-to-evidence (they show it), place alignment started, dispatcher in parallel. Explicitly cut
to make room: the volcanic collection, a streamed Earth mode (kept as a later bridge view), viewer
polish, metric scale, and any training of our own models.

## 8. Experiment register

These experiments are the decision points, not optional polish.

| Id | Question | Method and recorded output | Decision on failure |
| --- | --- | --- | --- |
| FR-1 / existing X-1 | Does a real dense capture become a legible navigable splat? | Run COLMAP plus `gsplat` on OGC-1/room; record registration, reprojection, held-out quality, floaters, size, time, cost, and foreground PlayCanvas capture | Keep rung 3 as the product path; do not claim rung 1 |
| FR-2 / existing I-1 | Can two separate captures of one place share a real frame? | Jointly reconstruct two consented sets and inspect one connected model plus metric consistency | Keep regions semantically related but geometrically separate |
| FR-3 | Is the current rung-3 quality threshold valid? | Measure valid-fraction distribution and human legibility over the fixed corpus before selecting a threshold | Retain source-first rung 4 and label the threshold unvalidated |
| FR-4 | What are PlayCanvas budgets on target hardware? | Fixed camera paths per rung; record p95 frame time, 1% low, stutter fraction, memory slope, first render, and full detail | Reduce residency/detail budgets; never hide the measured result |
| FR-5 / deployment D-8 | Does the real loader use range requests usefully? | Foreground network trace over compressed scene assets | Design whole-object loading/caching if it does not |
| FR-6 | Are adaptive proposals understandable and reversible? | Predeclared user tasks for preview, explanation, apply, discard, rollback, and protected rejection | Narrow proposal scope or keep the capability Settings-only |
| FR-7 | Is a World Memory Package independently verifiable? | Build, copy to a clean environment, verify offline metadata/digests/signature, mutate one byte, and verify rejection | **Passed:** clean subprocess with database URLs removed verifies; one-byte payload and manifest mutations fail; PostgreSQL deletion/re-export changes root and names removed state |
| FR-8 | Does deletion propagate honestly into export? | Export, delete/redact, recompute, re-export, and inspect the root plus semantic diff | Export remains disabled until closure is complete |
| FR-9 | Does any fine-tuning earn its complexity? | Compare fixed baseline and candidate on untouched blind data, cost, latency, privacy, deletion, and model-lifecycle risk | Use the base model and reviewed pipeline |
| FR-10 | Does the complete build reproduce? | Run twice from the same manifest and source set; compare canonical state and enumerate expected nondeterministic provider fields | Fix nondeterminism or weaken only the precise affected claim |
| FR-12 | Does a generative world model conditioned through the read API stay inside the recorded parts, and is the seam visible? | Condition a generative model on one scene's read bundle; measure held-out agreement inside the recorded region and label agreement at the seam; record the model, version and digests | Keep the generated tier off by default and label it as unreliable fill |
| FR-11 | Will anyone pay for consented, posed, verifiable captures? | Produce a sample dataset export from the retained collections under the Phase 7B profile; put it in front of at least two world-model or spatial-AI teams; record what they would pay for what volume and format, and what they reject | Keep Phase 7B as a design; the memory product does not depend on it |

Every experiment stores its manifest, code revision, environment, raw measurements, result, and the
decision it changed. A screenshot without the run record is not an experiment.

## 9. Training policy

The word “training” covers four different activities here and must not be used without qualification.

| Activity | Roadmap status | Why |
| --- | --- | --- |
| Per-scene Gaussian-splat optimization | **YES, Phase 3C** | Produces a visual reconstruction of one observed place; never supports a historical claim |
| Base-model inference for vision, reasoning, and embeddings | **YES, already used** | Versioned model calls with schema validation and provenance; no local weight update |
| User adaptation through versioned state | **YES, Phase 5** | Safer, inspectable personalization through preferences/proposals rather than hidden weight changes |
| Fine-tuning a general or user-specific neural model | **NO CURRENT JUSTIFICATION** | No measured failure, consented training set, blind result, deletion policy, or lifecycle advantage yet |
| Licensing consented captures for a third party's model training | **PROPOSED, Phase 7B, opt-in only** | Rights-clean posed captures are what world-model labs lack; requires a separate training-use consent per person and package, a verifiable export profile and a ledger; default off |

The default technical strategy is therefore: use reviewed pretrained models as replaceable sensors,
keep durable memory in explicit versioned state, and train only the scene representation whose
purpose and source closure are known.

## 10. The Yolodex lesson and the Exulanica proof pattern

The primary Yolodex repository describes a compact autonomous loop:
collect, label, augment, train, evaluate, repeat until a declared metric passes. It uses isolated
skills, parallel worktrees for labeling, deterministic configuration, visible progress, a safety cap,
and concrete outputs including a dataset, evaluation JSON, and trained weights. Source:
<https://github.com/qtzx06/yolodex>, inspected 2026-08-31.

Exulanica should copy the proof pattern, not the specific detector architecture:

| Yolodex proof | Exulanica equivalent |
| --- | --- |
| Video URL plus classes | Authorized source set plus versioned world-build manifest |
| Collect and label | Admit evidence and produce schema-validated observations |
| Train detector | Reconstruct each scene and compose the protected world |
| mAP stop target | Evidence, provenance, reconstruction, reachability, concurrency, performance, and package gates |
| `best.pt` | Live world publication plus signed World Memory Package |
| `eval_results.json` | World build receipt plus fixed evaluation report |
| Retry labels when quality misses | Retry/reconfigure only the failed reviewed stage; otherwise publish the honest lower rung |
| Parallel worktrees | Independent stage/experiment tasks with one owner for shared migrations and contracts |

The stronger Exulanica demonstration is not “AI generated a pretty scene.” It is:

> These private source memories became a navigable, adaptive world; every claim and visual artifact
> retains its origin; every adaptation is versioned and reversible; every missing capability falls
> back honestly; and the result leaves the system as a signed package another tool can verify.

## 11. Worktree and ownership plan

Frontend UI/UX work can continue independently while the backend proceeds in separate worktrees.
Shared migrations and public schemas have one owner at a time.

1. **Backend processing task:** Phase 1 is complete on `codex/adaptive-world-backend`.
2. **Corpus/evaluation task:** Phase 2 may begin now that the worker event schema is stable; corpus artifacts stay
   outside Git when they contain personal media.
3. **Reconstruction task:** Phase 3 behind an artifact/job interface fixed by Phase 1. It does not
   modify Atlas UI.
4. **Spatial authority task:** Phase 4 after reconstruction manifest fields are measured rather than
   guessed.
5. **Package task:** profile fixtures and verifier may begin after Phase 4 snapshot shapes settle;
   exporter mutation tests require the style and topology repositories.
6. **Runtime integration task:** Phases 5 and 6 after UI/UX reconciliation, consuming the shared
   contracts rather than redesigning the interface.

Do not start simultaneous branches that each assume ownership of the next migration number, world
snapshot schema, or package profile. Parallel work is valuable only where merge order does not decide
the contract accidentally.

## 12. Critical path

The shortest credible path to the frontier demonstration is:

```text
real corpus and baseline
  -> real rung-3 and rung-1 experiment
  -> durable spatial snapshots
  -> adaptive interaction integration
  -> physical asset streaming
  -> World Memory Package projector/verifier
  -> one end-to-end build and recorded evaluation
```

Fine-tuning is not on this critical path. A universal plugin/capability schema is not on this path.
Mobile support, audio, voice identity, autonomous structural editing, and training on private user
memories are not on this path.

## 13. Definition of the frontier milestone

The milestone is achieved only when one authorized personal corpus can demonstrate all of the
following through the real implementation:

- repeatable, resumable ingestion with honest progress and no duplicate effects;
- exact source resolution for every displayed historical claim;
- a semantic memory graph that distinguishes inference, proposal, and confirmation;
- at least source-first and measured point-map regions, plus a published real splat result or an
  explicit failed experiment retaining the lower rung;
- immutable protected topology and reversible appearance/interaction adaptations;
- navigation and streaming that degrade without blocking or inventing evidence;
- a supported query whose answer opens its exact sources;
- deletion/recomputation closure over derived state;
- a signed World Memory Package with an independent verifier and semantic diff; and
- a build receipt and evaluation report sufficient for another engineer to reproduce what was
  shown and identify every fallback.

That is a frontier-level technical output even if the full-splat experiment fails. The hard result is
the trustworthy adaptive-world pipeline and portable proof artifact, not a selectively successful
render.
