# Product direction

Exulanica: Worlds for AI Agents. A person builds a world, and open models run what happens inside
it, each doing what it is good at; the person can swap one model for another and see the
difference. This document owns product scope, delivery order and acceptance criteria. Living
contracts describe supported operations; scoped evaluation records establish what a particular
execution demonstrated.

<details>
<summary>Sections</summary>

- [Product purpose](#product-purpose)
- [Implementation status](#implementation-status)
- [First milestone](#first-milestone)
- [Delivery gates for the first demonstration](#delivery-gates-for-the-first-demonstration)
- [Subsequent milestones](#subsequent-milestones)
- [Inspectable representations and durable worlds](#inspectable-representations-and-durable-worlds)
- [Living-world experience requirements](#living-world-experience-requirements)
- [Worlds as project foundations](#worlds-as-project-foundations)
- [Modular simulation and scientific tooling](#modular-simulation-and-scientific-tooling)
- [Configurable world rules](#configurable-world-rules)
- [Architecture and implementation boundaries](#architecture-and-implementation-boundaries)
- [How a world is made](#how-a-world-is-made)
- [Synthetic life](#synthetic-life)
- [Optional Earth content](#optional-earth-content)
- [World state contract](#world-state-contract)
- [Model selection and compute priorities](#model-selection-and-compute-priorities)
- [Improvement over time and training boundaries](#improvement-over-time-and-training-boundaries)
- [Package and API boundaries](#package-and-api-boundaries)
- [Evaluation](#evaluation)

</details>

## Product purpose

Build a world. Let open models run what happens in it. Swap one and see the difference.

A person builds a world exactly how they want it: a small town, a familiar place, a fantasy city.
The things in it that act are its agents: the people in the world, animals, vehicles and
decision-makers such as a shopkeeper or a traffic system. Streets, benches and buildings do not
act; they are the world the agents act in. Open models run the agents, each model in a role it is
good at, side by side in one world the person controls. Swapping the model behind a role and
running the same starting world again shows what each model does differently.

Hugging Face's "State of Open Models: Summer 2026" (published 2026-08-14) counts about 2.96 million
public model repositories and reports that roughly 85.6% of models have fewer than 200 lifetime
downloads. Exulanica gives open models a place to work: a person gets hands-on exposure to models
they would not otherwise try, and model makers get their models used. Whether people want to
discover models through a world rather than a list or a leaderboard is the hypothesis the
[first milestone](#first-milestone) tests.

World models generate how a world looks. Exulanica is the world AI models live in: structured,
versioned state with fixed engine rules, in which models decide what agents do and the engine
validates every decision before it takes effect. Exulanica does not generate a world's appearance
with a learned model, and it is not a learned predictor of what happens next.

A world has three layers, and each is replaceable on its own:

| Layer | What it holds | Who makes it |
| --- | --- | --- |
| Engine | General rules of movement and interaction, one module per kind of movement | Written once per kind of movement, never per thing |
| Content | What exists: kinds of places, people, vehicles and objects, their sizes, looks and abilities | Versioned catalogs, authored by hand or imported with their origin, validated before admission |
| Decisions | What each agent does from moment to moment | Models and deterministic planners while the world runs; decisions are stored so a run replays without calling a model |

Other capabilities are features and ways to build a world, not the product's identity:

- **The Companion** is an AI partner within the world that helps a person explore, create and
  understand events. Conversation and direct controls operate on the same supported capabilities;
  using a world does not require a conversational interface ([Companion](capabilities/companion.md)).
- **Personal photographs and memory** are one way to build a world and one source of its content.
  Photographs of a real place can be reconstructed into a scene
  ([scene reconstruction](capabilities/scene-reconstruction.md)); rights and consent govern every use.
- **Hand building** places pieces from the catalogs; **imported content**, including output of
  external generators, is admitted with its origin labelled.

Plausible scenery or moving characters alone do not establish a living, usable world; each
capability needs its own acceptance evidence.

These foundations sit beneath every milestone:

| Foundation | Where it sits |
| --- | --- |
| Inspectable representations | Inspection extends to agents: each stored decision keeps what the agent observed and the validated action, for a person to inspect. [Inspectable representations and durable worlds](#inspectable-representations-and-durable-worlds) |
| Durable, versioned worlds | A run starts from an exact saved version, so two models are compared from the same starting world. [World state contract](#world-state-contract) |
| Rights and consent | A model receives only what the person's rights permit, through one hosted policy boundary. [Privacy and consent](privacy-consent-threat-model.md) |
| Replay | Stored decisions replay a run exactly without calling a model, which makes side-by-side comparison fair and inspectable. [Society contract](synthetic-society-contract.md#explicit-model-proposals-and-exact-replay) |

The foundation is **structured, addressable world state**: meaningful subjects have identities,
geometry, properties, relationships and recorded changes. Meshes, points, splats and rendered
images are representations. They do not automatically provide complete segmentation, reusable
objects or physics. The [world state architecture](world-memory-model.md) defines this distinction:
everything consequential is addressable; not everything rendered is canonical data.

Observations, interpretations, authored alternatives and simulated events share identity and
spatial context while retaining distinct meanings. An imported landscape does not prove a visit;
a generated room does not prove its layout was observed; synthetic behavior does not predict a
real person's choices. Exulanica implements structured, descriptive world state with bounded
behavior and model integrations. A general learned predictive capability requires separate
evaluation.

The [composition contract](world-composition-contract.md) specifies the relationships between
sources, creations and representations. The [Companion guide](capabilities/companion.md) defines
its role. **World Memory Package** is the technical name of the signed, partial portable
snapshot format; it is one output of a world.

## Implementation status

Capability guides and living contracts own detailed inventories. This map says what exists and
where each boundary lies, without competing copies of runtime flags, model selections or
deployment prerequisites.

The people in a saved world follow a deterministic planner
([`society_planner.py`](../exulanica/world/society_planner.py)) unless its owner chooses an open
model for one person or a group; each such choice is validated, stored and replayed without calling
the model again. A person is the only role a model decides for. Several open models serve hosted
roles through one policy boundary (the [model manifest](../exulanica/models/models.manifest.json)).
Walking and flight are movement modules chosen by data, and road movement exists as a module that
nothing in the application calls ([`exulanica/traffic`](../exulanica/traffic)). Objects, vehicles
and society activities are versioned catalogs under [`assets/catalogs`](../assets/catalogs).

| Surface | Contract and acceptance boundary |
| --- | --- |
| Models deciding | [Decision roles](decision-roles-contract.md) and the [society contract](synthetic-society-contract.md#a-person-run-by-a-model-their-worlds-owner-chose): a world's owner chooses an open model for a person or a group, and each choice is validated, receipted and replayed without a call. A role is registry data with one adapter module; the person is the only registered role. |
| Comparisons | [Comparisons of models](society-experiments.md#comparisons-of-models): the same simulated hour once per model for one group, scored against the routine and waiting, bounded by a same-model control and shown side by side in the application's Compare view, where the world's owner starts one within a spending bound they state; a local command defines and runs one by the same definition. |
| Movement | [Movement modules](movement-modules-contract.md): walking, and flight for small birds on a clock every viewer shares. Road movement is built and connected to nothing. |
| Worlds made from photographs | [Saved-world entry](saved-world-entry.md#which-photographs-a-personal-source-world-is-composed-from): a world composed from the person's reviewed photographs, one region per place, with later photographs added on confirmation. Each region has a declared floor, and the world hosts eight people on one of them, whose models its owner can choose. |
| World entry and persistence | [Saved-world entry](saved-world-entry.md): owned authored starters, saved versions and reference photographs. Attaching a photograph does not create recovered scene geometry. |
| Creation and editing | [World objects](world-objects-contract.md), [appearance](atlas-world-customization-contract.md) and [composition](world-composition-contract.md): supported assets, edits, versions and explicit gaps in general structural creation. |
| Reconstruction and inspection | [Reconstruction guide](capabilities/scene-reconstruction.md), [scene segments](scene-segments.md) and [inspection](atlas-reconstruction-inspection.md): usable representations depend on actual source coverage and published artifacts. |
| Synthetic life | [Society contract](synthetic-society-contract.md): deterministic profiles, the ground each kind of saved world states, routines as data, actions, replay, worker configuration and representation limits. Rich social behavior requires additional evidence. |
| Experiments | [Society experiments](society-experiments.md): bounded paired runs and supported interventions. This does not implement arbitrary world rules. |
| Characters | [Character representation](character-representation-contract.md): identity bindings, reusable appearance, movement and visual acceptance. Recognizing a person does not authorize a simulated personality. |
| Models | [Model and service selection](model-and-service-selection.md#0-implemented-stack-and-selection-decision): implemented callers, chosen models and measured comparisons. Provider configuration does not prove application deployment. |
| Developer access | [World API](capabilities/world-api.md), [developer client](capabilities/developer-client.md) and [World Memory Package](world-memory-package.md): authenticated operations, demonstrated client use and partial portable projections. A world's society, its stored decisions and its comparisons are readable through the same API. |

A fixture, test or recorded run establishes its stated boundary. Package verification is not
runnable import; a successful upload is not a reconstructed place; a renderer is not a simulator.

Not built: model roles other than a person, traffic, weather or an economy run by models, a model
choice in the owned district's living society, and a retraining loop.

## First milestone

**Open models run a world; swap one and see the difference.** One small town, built from the
catalogs. Its people are run by two different open models. The same day runs twice from the same
saved version with one model swapped, and the application shows the two runs side by side and
what each model's people did differently. This milestone is a delivery target; the table states
what accepts it and where the implementation stands.

| Deliverable | Acceptance evidence | Status |
| --- | --- | --- |
| A world to run | A small town from the catalogs opens as a saved version in the application, with its people visible and moving under the deterministic planner. | Implemented for towns two and three tiles long. A person makes a small town or a market town from the presets of a specification and changes its values within the ranges the served schema states, its street mix and the shares of its kinds of building and shop included (World menu, Create); the server holds the values to the schema, generates the town from the city grammar, saves it as a generated world, bakes its tiles off the request, and the application draws the town once its tiles are baked, with its vehicles driving its streets ([ADR-0027](adr/0027-a-generated-world-is-drawn-in-its-own-world.md)). Its people, one per place in a home its premises offer (30 to 56 in 20 small towns and 56 to 98 in 20 market towns), walk its footways from tile to tile and visit its shops and benches under the deterministic planner, and the owner can choose a model for a group of them. The [living-world rehearsal](evaluation/2026-09-25-rehearsal-living-world.json) passed the small square's version of this deliverable in part. |
| A model per group | The people are split into named groups, and each group's decisions come from the open model chosen for it, through the one hosted policy boundary. The engine validates every proposed action; an invalid proposal is refused with its reason and the person keeps a valid state. | Implemented. The owner chooses a model for a person or a group, asked through the policy boundary; an answer the engine refuses is recorded with its reason, and the routine decides that turn. |
| Recorded decisions | Every decision stores the model that served it, the observation it saw and the validated action. A run replays exactly from those records without calling a model. | Implemented. Every request and receipt is stored with the model that served it, and replay reads them without a call. |
| Swap and compare | Two runs start from the same saved version and differ only in one group's model. The application shows them side by side, with the people and events that differ. | Implemented for one simulated hour, started from the application's Compare view within a bound its owner states, or from a local command, for a small town's group as for the small square. The Compare view shows the runs finishing, then the verdict and numbers, then one seed's hour from above on each side with what each person did minute by minute, the group first and the people whose hours differed most at the top. |
| Honest difference | A control pair with the same model in both arms bounds the difference that run-to-run variation alone produces; a reported difference between models exceeds that bound, or the comparison says it does not. | Implemented. A control arm runs one model twice, and the verdict says whether a difference between models exceeds what that pair shows. |
| Independent reading | The runs, their decisions and the models that served them can be read through the authenticated API by a client other than the browser. | Recorded. The [developer client](capabilities/developer-client.md#reading-a-comparison-of-models) reads a comparison started from the application, its runs and every stored decision through the authenticated API with `world.read` alone ([record](evaluation/2026-09-29-developer-client-comparison.json)). |

The gap between the implementation and the milestone as stated: a town's people are compared from
the Compare view, but in one comparison a model decides for only part of a large town (at most 24
of a 56-person small town and 11 of an 86-person market town, fewer the more people a town holds,
derived from how long reading a run may take;
[what a comparison can read](society-experiments.md#running-a-comparison)), the judged comparisons
ran over the small square, and a comparison covers one simulated hour rather than a day.

Two judged comparisons found no measured difference in how people fared between Qwen3 235B
Instruct and Nemotron 3.5 Lightning, first for all eight people of the small square and then for a
group of four, while in the second the group spent its time visibly differently under each model
([first record](evaluation/2026-09-26-society-model-comparison.json),
[second record](evaluation/2026-09-26-society-group-comparison.json)).
[Comparisons of models](society-experiments.md#comparisons-of-models) owns the rules, the score and
these results. The Companion, personal photographs and reconstruction are not part of this
milestone.

### Saved-world foundation

The milestone runs on a saved world. These gates keep that foundation honest. The Companion and
personal-media rows are features beside the milestone, which does not depend on them. World
creation and personal-source reconstruction have separate acceptance paths; a source-independent
authored starter is a valid world, not evidence of reconstruction.

| Deliverable | Acceptance evidence |
| --- | --- |
| World entry | An empty account enters its owned starter space; a returning user opens the saved world. Naming and media intake are available inside the workspace. |
| Durable creation | Place one reviewed asset, edit its appearance or transform, reload and undo the accepted change under the supported version semantics. |
| Inspection | Select that subject and inspect its available geometry, structured properties and origin. Missing representations remain explicit. |
| Bounded interaction | Trigger, stop and reset a supported object behavior, preserving its definition across reopening. Refuse unsupported actions with a useful explanation. |
| Companion interaction | Use the actual model path to answer a grounded question or prepare a supported change against the same world context. Inspect sources or events and record the executed model, task, latency and output; Nemotron use must be functional in that interaction if claimed, with the actual executed variant recorded rather than inferred from configuration. |
| Developer proof | An independent client reads the same saved version, discovers supported capabilities and submits an accepted edit through the authenticated API. The [developer client](capabilities/developer-client.md) has a [recorded synthetic-starter demonstration](evaluation/2026-09-23-developer-client.json); that evidence does not cover a reconstructed personal place. |
| Personal-media path | Admit authorized sources, produce usable scene geometry, inspect actual coverage, integrate the supported result and reopen it without losing authored changes. Photo attachment alone does not pass this gate. |

The source-independent path can progress while reconstruction quality is unresolved. A fixture
may establish mechanics but must be identified as such. A complete personal-media demonstration
requires the actual source-to-browser path and source-grounded interaction.

## Delivery gates for the first demonstration

Release scope follows the first milestone's journey, with claims limited to executed capabilities.

1. **Usable world:** open the town in the real application and watch its people move. Diagnose
   world, simulation and rendering failures separately.
2. **Models in their roles:** each group's decisions come from its named model through the policy
   boundary; the engine refuses an invalid action with its reason. Record the served model for
   every decision and record missing evidence honestly.
3. **Swap and compare:** run the same saved version twice with one group's model swapped, show
   both runs side by side in the application, and run the same-model control pair beside them.
4. **Persistence and replay:** reopen the world, replay both runs exactly from their stored
   decisions without calling a model, and verify the saved world is unchanged by either run.
5. **Independent use:** read the runs and decisions through the developer interface.
   Export only declared capabilities; package verification and runnable loading are separate gates.
6. **Release rehearsal:** repeat from a clean start, observe a person using the experience and
   verify setup, access, failure behavior and demonstration footage.

Validation covers the permissions, deletion and integrity boundaries exercised by the journey.
Use focused checks for changed behavior and integrated checks for the connected path. Test volume
or a completed training job cannot substitute for a usable world or visual acceptance.

## Subsequent milestones

The product's core is movement in the world and models controlling it, not graphics. The
milestones after the first follow that order. Each is a delivery target with its own scoped
acceptance criterion, accepted only when its measured evidence exists.

| Milestone | What exists | What remains | Acceptance |
| --- | --- | --- | --- |
| 1. People move convincingly | Routines as data (rest, visit, stand, talk), furniture people use and sit on, and a living society over the owned district. The small square passed its declared targets for walking share, stays, standing and talking ([record](evaluation/2026-09-25-living-square.json)). | A simulated day against a declared bound, and a person judging it in the application | People go to distinct places for their own reasons and do not gather on the same points: where they are and what they do over a simulated day, against a declared bound, judged by a person watching the world in the application |
| 2. The control loop | Decision roles as registry data with one adapter module each and one decision path; providers as data in the [model manifest](../exulanica/models/models.manifest.json) (address, credential variable and catalog); a model chosen per person or group through the one policy boundary | Roles other than a person; adapters per model family beyond language models, such as vision-language models and driving or robot policies; a per-provider egress declaration and budget, where egress is derived from each provider's address and the budget is one per process | Each acting kind declares what it observes and which actions it may take, each model declares its inputs and outputs, and the engine validates every action; a second role runs through the same path |
| 3. Movement modules | Walking and flight, each one engine module driven by catalog data ([movement modules contract](movement-modules-contract.md)); small birds fly and perch on the objects that host them | Road movement: [`exulanica/traffic`](../exulanica/traffic) is complete and has no caller; flying kinds beyond the small bird | A dragon, a plane and a bird are content that use the flight module, not code written for each; a world that needs vehicles runs roads through the module |
| 4. Measured results per model | The person's score, computed exactly from what the engine recorded and declared as reviewed catalog data; judged comparisons pre-registered on held-out seeds | Scores for any role other than the person | Each role's result is computed exactly from world data, with what counts as good declared per role as reviewed data; comparisons use a pre-registered held-out set, as the [model selection](#model-selection-and-compute-priorities) rules require |
| 5. The retraining loop | No export of runs for training | Runs exported in an existing open environment format, for example Prime Intellect's verifiers, so that existing open training tools retrain a model; Exulanica does not build a trainer. Running uses a hosted API; retraining needs a model's open weights on a GPU. Reward design per role and guards against reward gaming are the hard part. | One role, one score, one retraining and a measured improvement on held-out runs |

Content generation (concept images, image-to-3D) comes later and is not a pipeline Exulanica
builds. Generated content is imported from existing tools with its origin labelled generated,
through the admission path in [how a world is made](#how-a-world-is-made).

Work beside the milestones continues on its own contracts:

- **Creative composition:** the [composition delivery sequence](#composition-delivery-sequence)
  covers editable assets, blending places into authored arrangements, explicit source versus
  created content, alternate versions, undo and persistence. A composed arrangement must not imply
  those places were physically adjacent.
- **Interactive objects:** an explicit behavior registry, triggers, runtime state, restart rules
  and supported motion. Recognizing someone never implies permission or capability to simulate
  their personality.
- **Scene segments:** lift per-photograph people and object regions into per-entity 3D segments
  through the recovered cameras, so a world made from photographs has separate pieces that roles
  can apply to; models and ownership in [scene-segments.md](scene-segments.md).
- **Developer interoperability:** stable read/edit contracts, package compatibility, capability
  negotiation and asset resolution. A second tool must make an accepted change without depending
  on private interface state before interoperability is claimed; the
  [project delivery sequence](#project-delivery-sequence) extends that proof to reproducible
  comparisons and task-specific datasets with independent consumers.

### Composition delivery sequence

Optional Earth composition is delivered in dependency order, each stage with its own evidence:

1. **Source admission and shared identity.** A permitted, reusable real-world selection with a
   canonical place association, source version and explicit frames; a versioned environment and
   asset contract; and a detailed rendering target.
2. **Durable composition and retrieval.** The selection placed beside a scene made from personal
   photographs in an authored version, saved, reloaded and undone, and queried by shared place
   identity with distinct origins and match reasons. `Intent.CONTENT` unions its kinds over a
   confirmed place bridge ([world composition](world-composition-contract.md#unified-queries-and-filters));
   the Iceland-class journey, authored objects as a `CONTENT` kind, and isolated imported-only,
   fantasy-only or person and time request shapes are not built.
3. **Assisted structural creation.** One natural-language compound edit, including a real
   geometric or generated addition, previewed, applied and undone, with measurable asset quality,
   the existing interactions and retained lineage.
4. **Transfer and expansion.** Package compatibility and permitted asset resolution, a second
   geography or source, and further operations added for measured needs rather than a speculative
   universal abstraction.

## Inspectable representations and durable worlds

The inspection control should expose a spatial-detail slider for compatible rendered surfaces
and point representations, with separate overlays for supported bounds, segmentation, labels
and stable identifiers. A selected item can open its structured records, source references and
bounded authorized artifact-byte inspection. Semantic records are not the final geometric rung
of a slider. A binary or Matrix-like visual treatment must be labeled as a visualization unless
it directly encodes identified artifact bytes. It does not establish additional scene evidence.
Pixels, splats and meshes do not imply complete segmentation or reusable object extraction.
Available views therefore depend on each scene or subject's actual representations and current
source authority. These controls are a delivery gate, not a delivered global
view switch.

The intended world interface offers rendered appearance, available point geometry and semantic
structure/data views for the same selected subjects, place, time and branch. This is a product
requirement, not a claim that the distance-based representation tiers implement a global
view switch. A continuous blend/density slider can accompany compatible spatial representations;
semantic records remain an inspectable layer rather than pretending to be a geometric endpoint.
A missing point map is shown as unavailable. Sampling an authored or generated mesh into points
must retain that origin and must never be labeled a recovered measurement. Changing the view
preserves subject selection, camera position, navigation authority and current source permissions.

Worlds are retained assets and state, not continuously regenerated experiences. Preserve sources,
versioned derived geometry/textures/rigs, source lineage and authored changes in content-addressed
storage; retain identities, simulation snapshots and ordered events in the database. Build expensive
representations asynchronously, reuse unchanged content, and stream/cache only what a view needs.
Private personal worlds require authenticated delivery and deletion propagation through derived
assets and caches. Explicitly public showcase artifacts can use a separate public delivery path.

The runtime uses local content-addressed storage and PostgreSQL; a shared cloud object-store
backend and retained hosted world are additional delivery work, not established by the local
preview. The [deployment plan](deployment.md) and [model stack review](model-and-service-selection.md)
distinguish proposals from running services. Measure storage, egress, build/inference and active
simulation costs separately before selecting a hosted scale target. Reconstruction and asset
creation use scheduled compute; a stored world does not require a permanently running GPU.

## Living-world experience requirements

The long-term product is a persistent world that a person builds and open models run: agents
whose decisions come from the model chosen for their role, recorded so that runs replay and
compare. A person can inspect and reshape the world directly or with the Companion and use it
for projects and controlled experiments. Personal sources, permitted imports and synthetic
creation are independent entry paths. Returning users open their saved world; users without one begin in an owned starter space.
These are product requirements, not claims of complete implementation or visual acceptance.

People should be able to choose first-person exploration or a third-person view of their own
character, sharing position, movement constraints and interactions. Walking, running, turning and
camera obstruction handling need live visual and movement acceptance. Camera choice changes the
view, not the world or simulation identity.

The player, synthetic inhabitants and people represented from sources share a character foundation
with coherent form, materials, movement and stable subject bindings. Appearance, identity and
agency remain separate. The [character contract](character-representation-contract.md) defines
the abstract base, reusable representations and later source-linked likeness requirements;
visual fidelity must not imply confirmed identity or simulated personality.

### Entry and first-world setup

Creation stays inside the world workspace. A returning user resumes their saved world; a
first-time user enters a minimal owned starter space with one clear way to begin building, an
optional and editable name, an Add photos control and contextual help from the Companion, with
direct controls available when no model is configured. Uploading media, choosing a creation
approach and reviewing a proposed change belong alongside the canvas rather than in a mandatory
introductory form. The interface shows actual progress and actionable failures where they occur;
a successful upload does not promise a finished scene.

A starter space has its own persistent authored identity and does not imply an observed place, a
completed reconstruction or a generated environment. A world is made from photographs through the
personal-source path: the server composes the person's reviewed photographs into a world of its
own, and photographs reviewed later join its places only when the person confirms. Reviewed
photographs can also be attached to any saved world as persistent references, which reopen in the
photo drawer, preserve the world's edits, undo history and appearance, and produce no
reconstruction or scene geometry. [Saved-world entry](saved-world-entry.md) specifies both paths.

Acceptance covers an empty account entering its own space, a saved name and supported edit, exact
reopening, and opening and closing photo intake without losing that world.

Creation establishes a starting point. Continued usefulness comes from resuming a meaningful
project, remembering its decisions, discovering consequences and investigating alternatives.
The following requirements define that continuity:

| Capability | Required experience |
| --- | --- |
| Functional objects | Objects expose supported actions and consequences. A usable chair has a sitting affordance; an operating shop has relevant hours, capacity and resources. Appearance and labels alone do not establish function. |
| Time and change | People can revisit history, retain corrections, branch authored alternatives and compare simulated outcomes. A later observation, an imagined renovation and a simulation remain distinguishable even when they concern the same place. |
| Uncertainty and correction | Ambiguous identity, incomplete geometry and competing interpretations remain inspectable. A correction updates affected representations without silently rewriting sources or unrelated state. Useful creation does not depend on perfect automatic extraction. |
| Personal continuity | The Companion retains authorized project context, preferences, accepted decisions and unresolved questions. People can inspect, correct and delete that memory and control which changes the Companion may perform. |
| Model interaction | A compatible model receives declared observations and proposes supported actions under explicit timing, validation and resource budgets. Generation, social planning, prediction and vehicle control have distinct capability requirements. |
| Life between visits | A world declares whether simulation pauses, continues under a budget or advances through bounded catch-up. Returning users can inspect intervening events. Durable assets do not require repeated generation or continuous expensive inference. |
| Ownership and collaboration | Visiting, editing, contributing content and running experiments have distinct permissions. Shared world content does not grant access to its private sources. Transfer declares which identities, assets, rules and history a receiver can use. |

The society and the models that decide for its people are the product's core; experiments
compare their runs. Both build on the shared identity, spatial, temporal, edit and event
foundations. A personal studio, fictional garden and traffic experiment can require different
capabilities without becoming unrelated world formats. Collaboration and scientific simulation
do not become prerequisites for the saved-world experience.

Controlled model evaluation belongs to the long-term product. Creative simulation explores
consequences under declared rules. Scientific prediction additionally requires domain-specific
calibration and validation against independent observations; believable inhabitants and detailed
graphics do not establish that validity. Training requires a specified task, authorized data,
feedback, held-out evaluation and measured benefit over an inference or deterministic baseline.

A connected acceptance sequence creates a place, makes a consequential edit, shows an inhabitant
responding through a declared affordance, and asks the Companion to explain the recorded cause.
Inspection exposes the supporting state and events. Reopening preserves the result, and an
alternative branch permits comparison without replacing the original history. A synthetic fixture
can establish these mechanics; personal-source usefulness needs its own acceptance evidence.

## Worlds as project foundations

A world is both a place to inhabit and an environment to build with. The Companion helps a person
define a project, select the relevant world content and supported capabilities, prepare changes,
and inspect results. A project binds its work to explicit world versions, inputs and rules so that
reopening, comparing and sharing results does not depend on one browser session. This is intended
product scope; the API and package contracts determine which operations and outputs are supported.

| Project use | Intended output | Required proof |
| --- | --- | --- |
| Build inside a world | An interactive place, activity or authored scenario with supported objects and behaviors | Accepted edits and behavior bindings survive reopening, and unsupported actions remain explicit |
| Build on world state | An application or external tool that reads selected subjects and proposes authorized changes | An independent client uses the same identities and versions without relying on browser-private state |
| Experiment with a world | Paired scenarios, recorded interventions and inspectable comparisons | Both runs bind exact starting conditions; controls, failures, raw outcomes and replay are retained |
| Produce data from a world | Task-specific observations and annotations for permitted training or evaluation | Labels match the rendered observations, lineage and splits are explicit, and usefulness is measured on held-out cases |

For example, a perception project can vary lighting, object placement and camera views in a
declared scene, produce images with supported labels, and compare a detector across held-out
conditions. A society project can change one supported amenity or rule and examine the recorded
effects on synthetic inhabitants. These examples describe project capabilities to establish;
they do not assert a delivered dataset generator, general rule editor or validated human-behavior
predictor. Using a world does not require training a model.

### Project delivery sequence

| Dependency order | Deliverable | Acceptance |
| --- | --- | --- |
| Saved world | Create or select a supported world, inspect it, make a supported edit and reopen it | World identity, authored state and source availability remain consistent across sessions |
| Bounded project | Bind one supported interaction or controlled comparison to that saved state | Recorded inputs explain the result; a no-op control and invalid-input case test the claimed behavior |
| Independent consumer | Read the supported state or result through an authenticated API or compatible export | A second client reproduces the declared interpretation and reports unsupported content |
| Dataset workflow | Export one task-specific observation/annotation format for an external training or evaluation tool | Independent annotation checks and a held-out baseline comparison establish correctness and task benefit |

These dependencies sequence the project capability without adding every output to the minimum
release candidate. The saved-world and bounded-experiment implementations can advance independently
where their contracts permit, then require a connected acceptance check. Dataset training and
general simulation do not block the first milestone. Model generation, reconstruction and policy
providers remain replaceable; no single provider or downstream application defines the world format.

## Modular simulation and scientific tooling

Established simulation and geometry tools are evaluated through replaceable adapters over world
state. This is an evaluation program, not an implemented physics backend or a dependency of
ordinary saved-world use. A simulator consumes a bounded projection and returns validated results;
it does not become the authority for personal evidence, permissions or persistent entity identity.
The modular monolith, the existing job and storage boundaries and the production renderer stay as
they are.

| Candidate | Role to evaluate | Adoption gate |
| --- | --- | --- |
| [NVIDIA Warp](https://github.com/NVIDIA/warp) | Accelerated geometry kernels and numerical simulation where profiling identifies a costly operation | Compare a pinned implementation with the existing or simplest suitable CPU baseline on correctness, memory, cold/warm latency and representative batch sizes |
| [Newton](https://github.com/newton-physics/newton) | Physics-engine adapter for rigid bodies, contacts and supported articulated interactions | One bounded world project passes state mapping, contact/constraint checks, save/reopen and an independent result-consumer check; document supported solver features and numerical limits |
| [OpenUSD](https://openusd.org/release/intro.html) | Optional scene and physics-description interchange with an external authoring or simulation tool | A named consumer preserves declared geometry, units, transforms and identity mappings; omissions and unsupported behavior are explicit |

Warp provides compute primitives; Newton builds a physics engine on Warp, and its maintained
interfaces are evaluated rather than the deprecated `warp.sim` interface. Neither supplies memory,
general segmentation or social intelligence. OpenUSD is a projection option, not a replacement for
world authority or the World Memory Package; scene paths alone do not supply persistent Exulanica
entity identifiers. An evaluation pins the exact release, dependencies, license, hardware and
solver settings. Warp on macOS runs on the CPU, so local results do not establish CUDA throughput,
and GPU unavailability leaves a saved world usable with the affected operation's availability
explicit.

The first bounded physical project is a small rigid-body scene with explicit mass, collision shape,
gravity, initial conditions and one supported intervention: checked against a simple analytic case,
repeated, compared with its control, and read back by a separate client that distinguishes playback
from re-execution. Vehicle controllers, robotics, fluid dynamics and configurable fictional physics
each need their own capability and validation scope. The
[simulation adapter boundary](world-memory-model.md#simulation-adapter-boundary) states the
identity, units, clock mapping, authority and reproducibility requirements every adapter meets, and
the [architecture overview](architecture-overview.md#10-performance-and-language-evaluation) owns
how a compiled or accelerated implementation is measured before adoption.

## Configurable world rules

Fantasy creation includes architecture, appearance and the rules under which a world operates.
A visual style does not silently select a calendar, physical law or social behavior. A person
can combine compatible appearance and rule choices, with coherent presets providing starting
points and supported parameters providing customization. Real-world statistics are one basis for
rules; fictional worlds can use explicitly authored mechanisms instead.

The intended rules are typed, versioned data bound to compatible runtime implementations.
The customization surface has separate dimensions:

| Dimension | Examples and consequences |
| --- | --- |
| Architecture and appearance | Building forms, materials, clothing and visual treatment. A form edit can affect navigation or affordances; changing a color does not implicitly change behavior. |
| Calendar | Names and lengths of days, weeks, months and years; recurring occasions. Calendar changes can affect schedules that explicitly depend on those boundaries. |
| World time and playback | World-time progression, pause and playback rate. Changing how quickly a run executes is distinct from changing the duration or meaning of a world day. |
| Environment | Day/night cycles, seasons, weather and fictional celestial arrangements. A permanent-day world need not give its inhabitants perpetual wakefulness. |
| Physical and fictional mechanisms | Gravity, traversal, growth, resource production or bounded fictional actions. Each requires an implementation that defines valid inputs, effects and interactions. |
| Inhabitant and institutional rules | Sleep needs, work patterns, opening hours, transport and resource exchange, tied to the relevant world clock, environmental conditions or events. |

Customization exposes supported parameters and validated combinations. A request for an unsupported
mechanism produces an explicit capability gap, not a cosmetic substitute or a model-invented
runtime behavior. The Companion can explain dependencies and prepare a reviewed proposal before
applying a change. A broader vocabulary of rules extends through replaceable implementations;
arbitrary executable rules are not implied by natural-language creation.

For example, a world can request a thirty-hour day, a ten-day week and shops that open at dusk.
Its calendar display, lighting and affected schedules must agree on the accepted definitions.
If another edit removes dusk by making daylight permanent, the dependent opening rule needs an
explicit replacement or a reported incompatibility. A moon count or calendar label alone cannot
supply the missing environmental or behavioral mechanism.

Rule changes name their effective simulation position and retain the version needed to replay
earlier events. Changes that invalidate state require an explicit migration or an alternative
branch. Rewinding playback does not erase recorded history. Personal capture dates and source
chronology remain intact regardless of a world's fictional calendar. External models and package
receivers must declare compatibility with the rules they consume.

These requirements do not establish a configurable calendar, fictional physics engine or universal
simulation runtime. Delivery proceeds through bounded compatible rule sets, with save/reopen,
replay, dependency checks and visible behavior as acceptance criteria. They do not expand the
release schedule into a requirement to implement every fictional mechanism.

## Architecture and implementation boundaries

Product direction governs scope. The [architecture overview](architecture-overview.md) describes
system structure, source-code entry points and how a language or accelerator is adopted; the
[product research archive](product-specification.md) and [engineering archive](frontier-roadmap.md)
retain earlier reasoning and dependencies. Their historical sequences do not redefine the product
or require every world to begin with media.

Reuse the modular monolith, PostgreSQL consistency domain, asynchronous jobs and existing provider
boundaries. Identity, source rights, deletion and versioning apply across creation paths. A change
to this direction does not add an API operation, admit a model or alter package compatibility.

## How a world is made

Different creation methods produce contributions to the same persistent world. Authored starter
spaces, reconstructed places, generated environments and admitted imports have different origins
and different evidence requirements. A user need not reconstruct a place before creating one.

| Contribution | Responsibility |
| --- | --- |
| Vocabulary and assets | Reusable object kinds, materials, character assets and declared affordances provide inputs for creation. Admit external assets and datasets with their permitted uses. |
| Rules | Versioned generation and simulation mechanisms define supported behavior, time and dependencies. Realistic and fictional rule sets declare their own assumptions. |
| Generated content | Deterministic generators or learned models produce candidates with retained inputs, versions and origin. Validate geometry, identity mapping and supported operations before admission. |
| Decisions | Rules, people and models choose within declared actions. Record accepted inputs and outcomes; replay consumes those records rather than repeating model inference. |
| Appearance | Representations bind to identified subjects and retained assets. A texture or rendered image does not establish collision, semantics or behavior. |
| Edits | Accepted changes reference their base version, persist independently of the browser and support the declared undo and conflict rules. |

Generative models may supply geometry as well as appearance. Editable, inspectable output requires
an admission path that maps it to world subjects and declares which operations the result supports.
An opaque generated image or video does not by itself satisfy that contract. Deterministic seeds
reproduce only the components whose contracts guarantee determinism; learned outputs must be
retained for replay. Avoid a universal claim of byte-identical generation across providers.

## Synthetic life

The delivery target is inhabitants with purposeful activity, remembered interactions, evolving
relationships and responses to changes in the world. The bounded implementation and exact
profile differences belong to the [society contract](synthetic-society-contract.md).

Research and delivery preserve these requirements:

- Inhabitants convert needs and relationships into goals and typed actions. Authored objects
  declare affordances such as sit, open, carry, visit or cultivate; labels alone do not supply them.
- Movement, activities and visible consequences follow authoritative state. Rendering may
  interpolate snapshots but cannot create canonical positions or events.
- Models receive only permitted observations, propose valid actions and retain decision records.
  Use rules and bounded planners where sufficient; measure model quality and runtime budgets
  before increasing population or inference frequency.
- Remembered interactions and conversations affect later choices through explicit state. A role,
  biography or generated explanation does not prove memory or an evolving relationship.
- Synthetic identities and events remain distinct from real people and personal evidence.
  Persistent shared history does not grant permission to recreate a real person's personality.
- The canonical population remains queryable and persisted regardless of how many detailed
  characters the renderer can display. Model-facing state cannot depend on a camera's draw limit.

Acceptance introduces a place, object or event, shows an inhabitant noticing it and another
learning about it, then observes a later activity affected by those interactions. Inspect the
supporting events, reopen the world and ask the Companion what changed. Check information
boundaries, coherent choices, memory and repeatability before claiming social depth. A separate
scenario may compare an intervention while retaining the original history. These results do not
establish sentience or predictive accuracy about real people.

## Optional Earth content

Real-world geography is an optional source of content. Admitted landscapes and objects can join
personal media and fictional creations while retaining origin, rights and source coordinates.
World placement does not rewrite real geographic relationships. The
[composition contract](world-composition-contract.md) defines the Iceland target journey;
[owned district and admission](owned-district-and-admission.md) specifies the bounded implemented
source path. A globe, map or attractive imported scene does not establish reusable extraction,
permission to remix, unified retrieval or interactive behavior.

## World state contract

A person can create an alternate version of a world without rewriting its sources. The version
stores additions, removals, transforms and appearance changes, never silently merges inventions
into historical claims or mixes capture times into one purported historical state, and keeps entity
references stable across its edits. A created object has an identifier, an asset reference, a
transform, an origin the person chooses and optional supported behavior with bounded parameters.
Every edit records the version it was based on; concurrent edits fail clearly or reconcile
explicitly, and acceptance, undo and reopening operate on persisted state rather than the browser
view. An upload alone never establishes whether an image is fictional, a reference or a personal
experience. The [world objects contract](world-objects-contract.md) owns these operations and
[saved-world entry](saved-world-entry.md) owns reopening.

## Model selection and compute priorities

Optimize for demonstrated task quality, correctness, efficiency and maintainability. Prefer NVIDIA
models, Nebius and open-source infrastructure where they meet the task; keep implementations
replaceable through existing contracts. The authoritative selection and evidence are in
[model and service selection](model-and-service-selection.md#0-implemented-stack-and-selection-decision).

### Required model-selection work

Diagnose a product failure before adding a candidate or changing languages or frameworks. Compare
models on the task they would actually perform: grounded answers, structured editing proposals,
scene perception, reconstruction, inhabitant decisions or control. These roles need different
observations, validators and performance measurements. A chatbot model switch does not integrate
a controller into a world.

Larger reasoning models are candidates for difficult tasks only when paired evaluations establish
a benefit within the interaction budget. Segmentation, pose, generated-view and reconstruction
alternatives need source-grounded quality checks before downstream training. Generated views
remain generated content, never evidence for unseen surfaces. A model call using personal media
requires the applicable model and host rights.

### Promotion, compute reuse and rollback

Freeze candidate revisions, permitted inputs, development and held-out splits, task metrics,
practical improvement thresholds and runtime budgets before scoring outputs. Compare paired inputs
and record uncertainty. Repeated calls over one scene are not independent examples; a rephrased
query is not an unseen-scene evaluation. Preserve the baseline when results are inconclusive.

Evaluate false claims, invented identities, source withdrawal and permission handling separately.
Missing evidence still requires abstention. Escalation to a larger model cannot create supporting
sources, and provider-error fallback is not a task-routing policy.

Reuse valid stage outputs and compatible checkpoints under version and permission-aware cache
keys. Record cold and warm costs, memory, latency and recovery. A model or preprocessing change
invalidates affected descendants; an embedding-space change needs compatible re-embedding.
Promote a candidate only through the same user-facing workflow and retain a rollback path that
cannot resurrect withdrawn data. Fine-tuning needs a measured gap, authorized data and an explicit
evaluation plan.

Infrastructure improvements follow measured bottlenecks. A useful result can be a reproducible
scene pipeline, checkpoint recovery or an upstream fix demonstrated against an unchanged baseline.
Vendor usage alone is not an infrastructure contribution. Nebius Token Factory inference and a
GPU run on a different host do not establish Nebius GPU or Serverless deployment.

## Improvement over time and training boundaries

Improvement over time has four distinct mechanisms, and none of them is a general learned
capability:

| Mechanism | Existing basis | Required proof |
| --- | --- | --- |
| Retain and resume scene training | Saved Gaussian output and complete checkpoints bound to the run's exact identity | Preserve the useful scene and recover compatible interrupted work; neither operation learns a general reconstruction model |
| Improve a particular world | Source, placement and publication lineage; same-input resume does not accept arbitrary new inputs | Add authorized observations and publish a measurably improved candidate version while preserving historical meaning |
| Develop Companion continuity | Existing evidence/context and reviewed interaction machinery | Persist approved memory, retrieve it across sessions, and support correction and deletion; this is not model weight training |
| Improve shared reconstruction or language models | Existing model/stage integration and evaluation machinery | A separately approved experiment must outperform a relevant baseline on unseen examples before promotion; ongoing cross-world learning and Nemotron fine-tuning are not established |

Retraining the models that decide in a world is the fifth
[subsequent milestone](#subsequent-milestones), not one of these mechanisms.

Improving a particular world from later photographs starts from a full rebuild as the correctness
and cost baseline. A later physical change stays a new historical state, separate from extra
coverage of the same state and from authored edits, and uncertain alignment or time association
stays unresolved rather than silently fused. A candidate is compared with the previous version on
evaluation views excluded from training and fitting and in a browser inspection, must improve the
targeted deficiency without unacceptable regression, and leaves the last valid version usable when
an update fails. Continuing from an earlier scene's parameters with changed inputs is a distinct
capability from resuming an interrupted run and is introduced only with explicit compatibility,
alignment and input-lineage checks. [Scene reconstruction operations](scene-reconstruction-operations.md)
owns that path.

The permissions in force govern every version and checkpoint reuse. Removing training sources
invalidates affected artifacts under the existing deletion contracts; rebuilding from the remaining
authorized sources produces a new artifact, not exact restoration or proof of model unlearning, and
historical versioning never resurrects removed data.

For Companion quality, first establish a small representative failure set and compare context,
retrieval, prompts and model selection. Fine-tuning requires authorized training data, separation
of training and evaluation examples, a measured advantage over that baseline, versioned deployment
and a rollback policy. Private user memories are not automatically pooled into shared training.
Choose broader learned reconstruction or language-model work only when these measurements justify
it. This direction does not authorize training runs, collect new data or assign a migration.

## Package and API boundaries

Keep `exulanica-wmp-1.0` compatible. Do not silently add required simulation fields to the
`exulanica-wmp-1.0` profile. Specify a new compatible extension or new profile after the object/version contract has
been implemented and reviewed. Declare unsupported capabilities explicitly on load.

A future package may reference assets and approved behavior identifiers plus their parameters.
It need not embed runtime code. Original media remains excluded by default; include or resolve
assets only under the appropriate permissions. A signed folder guarantees neither historical truth
nor that every renderer will execute it the same way.

The API should operate on a named world/version with authenticated reads and reviewed changes.
The existing World Read/Write routes are starting points, not a promise of the final route shape.
Do not publish invented endpoints before implementing the contract. Every route, schema and
permission rule is pinned in `tests/snapshots/api-routes.json` and `tests/snapshots/api-openapi.json`,
so a change to the surface a client depends on reaches review as a diff rather than as a side effect.
A world's society, its stored decisions and its comparisons are read through the same authenticated
API ([World API](capabilities/world-api.md#people-and-models)); no package carries them.

Project outputs use capability-declared projections: a scene asset, annotated dataset, experiment
result and portable world snapshot serve different consumers. Each declares the source world and
version, relevant rules and coordinate/time semantics, permitted uses, and information omitted or
approximated. A geometry export does not transfer behavior or personal history. An external
generator's returned geometry requires validation and explicit identity mapping before it can
replace a representation of an existing subject. Bidirectional transfer is an acceptance claim
only for the capabilities and formats demonstrated by both participants.

## Evaluation

Evaluate whether a person can see what each model does differently in their world, and whether
people discover and try models this way rather than from a list or a leaderboard. Evaluate whether
people can create a meaningful place, customize it, understand its available data
and resume from the saved result. For reconstructed places, additionally measure source fidelity
and coverage. Verify that a second client reads the same version and submits a supported change.
Each milestone retains reproducible evidence for its acceptance criteria.

For projects, measure whether an independent builder obtains a useful result with less setup or
annotation effort than a simpler baseline. Check correctness, reproducibility, runtime cost and
usability. A valid export alone does not demonstrate useful training data; a synthetic result
does not establish transfer to real-world conditions. Scientific prediction requires independent
domain validation beyond the world's internal consistency.
