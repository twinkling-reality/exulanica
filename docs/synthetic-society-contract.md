# Synthetic society contract

Status: **BOUNDED DETERMINISTIC SIMULATION; NOT A LEARNED SOCIETY MODEL**.

A society is the population of a world: the simulated people who are its agents. This contract
owns the society engines, what each reads and records, and how a society is composed, stored,
advanced, directed and replayed. How an open model a world's owner chose decides for one of its
people is the [decision roles contract](decision-roles-contract.md)'s, how people walk is the
[walking movement module](movement-modules-contract.md#walking)'s, and how the app draws them is
the [character representation contract](character-representation-contract.md#drawing-a-societys-people)'s.

Five engines exist, and the engine table below says which one a new society over each kind of
ground is created with:

- `exulanica-society/v1`, which a creation naming no engine gets, keeps seeded synthetic motion
  with no routes.
- `exulanica-society/v2`, the purposeful society, walks its people to reachable goals under a
  routine that is data, reacts to versioned authored inputs, and lets a model its world's owner
  chose decide for a person at the routine's own choice points. A person's saved world, the
  starter or one made from photographs, gets a v2 society when the person asks for one: each
  destination gives its occupants places of their own, an object the society cannot use costs
  only its own activity, and the person can send everyone away and bring them back.
- `exulanica-society/v4`, the living society, adds catalogued needs and routines, occupancy and a
  population sized to its place. The app creates it over the owned district, which it draws only
  in the development preview.
- `exulanica-society/v5`, the living town, is the living society over a town generated from a
  recipe: its people live in the town's homes, a share of them work their workplace's shifts, the
  rest run errands and keep their leisure while the town's premises are open, and the world's
  owner may choose a model for a person. A town's society made before this engine keeps its v2
  society; a new one is the living town ([the living town](#the-living-town-v5)).
- `exulanica-society/v3`, a bounded social cast that took explicitly requested model proposals, is
  retired: nothing creates one and its proposals are refused, while a stored one reads, advances
  and replays as recorded.

All profiles are fictional simulation, separate from personal evidence. They do not model real
residents, infer demographic facts or demonstrate general social intelligence.

<details>
<summary>Sections</summary>

- [Connection to the world](#connection-to-the-world)
- [Engines and what each can do](#engines-and-what-each-can-do)
- [Identity, branches and compatibility](#identity-branches-and-compatibility)
- [The purposeful society (v2)](#the-purposeful-society-v2)
  - [V2 input authority](#v2-input-authority)
  - [Goals, routes and actions](#goals-routes-and-actions)
  - [Opt-in local activity failures](#opt-in-local-activity-failures)
  - [A saved world's own ground](#a-saved-worlds-own-ground)
  - [Authored edits and inability to act](#authored-edits-and-inability-to-act)
  - [Typed user-directed actions](#typed-user-directed-actions)
  - [Sending inhabitants away](#sending-inhabitants-away)
  - [A person run by a model their world's owner chose](#a-person-run-by-a-model-their-worlds-owner-chose)
- [Storing, replaying and playing a society](#storing-replaying-and-playing-a-society)
  - [Events, persistence and replay](#events-persistence-and-replay)
  - [Versions that survive upgrades](#versions-that-survive-upgrades)
  - [Persisted playback controls and bounded host progression](#persisted-playback-controls-and-bounded-host-progression)
  - [Server integration and HTTP](#server-integration-and-http)
- [V4 living society: routines, places and occupancy](#v4-living-society-routines-places-and-occupancy)
- [The living town (v5)](#the-living-town-v5)
- [Retired and frozen engines](#retired-and-frozen-engines)
  - [The frozen first engine (v1)](#the-frozen-first-engine-v1)
  - [V3 bounded observations and communication](#v3-bounded-observations-and-communication)
  - [Explicit model proposals and exact replay](#explicit-model-proposals-and-exact-replay)
- [Validation](#validation)
- [Traffic boundary](#traffic-boundary)

</details>

## Connection to the world

The society is the product's core: the people in a world are its agents. Inhabitants interact
with permitted places and authored objects through declared affordances, so what a person brings
into and changes in their world changes what its people do. Inhabitants never impersonate
remembered people. The Companion explains what a person is doing and why from their recorded goal
and action, the places they use and the events that explain them, cited as simulation and kept
apart from personal evidence
([Companion questions](companion-question.md#questions-about-a-worlds-people)).

A society advances one simulated minute at a time: when somebody steps it, or when a host runs the
API's playback worker, which advances a saved playing society whose engine the table below lets it
play, for the workspaces its environment lists or, with account discovery, for every account
owner's workspace and each guest's while the guest is there
([deployment](deployment.md#515-society-playback)), under the bounded lease policy below. Persistence alone starts no worker.

Implementation:

- shared identity, draws, events and digests: `exulanica/world/society.py`;
- which engines exist and what each can do: `exulanica/world/society-engines.v3.json`, read by
  `exulanica/world/society_engines.py`;
- the grounds a society stands on, with what people walk, the population rule, lattice and
  declared area of each, the dependency its input names its place under, the kinds of the
  world's own records its people's activities may name and the thing kind its population is made
  of:
  `assets/catalogs/society-ground/society-ground.v5.json` (versions 1 to 4 kept beside it), read by
  `exulanica/world/society_grounds.py`;
- sending a society's people away and bringing them back:
  `exulanica/world/society_presence.py`;
- the frozen v1 engine and the fixed tables stored v1 to v3 histories depend on:
  `exulanica/world/society_legacy.py`;
- the living town: the living society's modules with its input's projection
  (`place_from_town_input`) and a person's decisions in it,
  `exulanica/world/society_living_decisions.py`;
- the v4 living society: `exulanica/world/society_living.py`, its routine catalogs
  `exulanica/world/society_catalogs.py` over `assets/catalogs/society/`, the place contract
  `exulanica/world/society_place.py`, the generated-city place `exulanica/world/society_city_place.py`
  and run measurements `exulanica/world/society_metrics.py`;
- purposeful policy and input validation: `exulanica/world/society_planner.py`;
- how people walk, for every engine but v1: the walking movement module,
  `exulanica/movement/walking.py` ([movement modules contract](movement-modules-contract.md#walking));
- the authored-object projection shared by every composition:
  `exulanica/world/society_composition.py`, and the saved-world projection over a world's own
  declared ground: `exulanica/world/society_authored_ground.py`;
- a person run by a model their world's owner chose: the modules the
  [decision roles contract](decision-roles-contract.md#implementation-and-evidence) lists;
- comparisons of models and intervention experiments: [society experiments](society-experiments.md);
- the retired social engine's observations and communication, `exulanica/world/society_social.py`,
  and its stored proposals, `exulanica/world/society_decisions.py`;
- persistence and compare-and-swap: `exulanica/world/society_repository.py`;
- typed user action policy and persistence: `exulanica/world/society_actions.py` and
  `exulanica/world/society_action_repository.py`;
- persisted playback controls and worker: `exulanica/world/society_controls.py`,
  `exulanica/world/society_control_repository.py` and
  `exulanica/api/society_control_worker.py`; and
- authenticated API: `exulanica/api/routes/society.py`,
  `exulanica/api/routes/society_actions.py` and
  `exulanica/api/routes/society_control.py`.

## Engines and what each can do

`exulanica/world/society-engines.v3.json` states which engine profiles exist and, for each,
whether a society may still be created with it, whether it consumes authorised inputs, whether the
playback worker may play it (and the refusal it gives when not), whether it takes directed actions,
model decisions or experiments, whether the world's owner may choose a model that decides for one
of its people (`owner_model_choice`), whether a comparison of the models that decide for its people
may run it, whether the person whose world it lives in may send its people away, whether it can
stand on a saved world's own ground, which state shape it writes and how many people it may hold,
with a reason per row. It also states which engine a new society over each kind of ground is
created with (`creates`: a district's, a saved world's, and a town's, a saved world whose own
records state its walking surfaces and homes), which the browser reads rather than naming an
engine, and, from its third version, the engine a saved world takes instead where its version holds
a thing its author placed and the host offers societies of things (`creates_holding_things`: the
society of things, over the society grounds it names, the ones a society of things stands on; a
world made from a world kind is lived in by the living society alone, so it is not named). A saved
world's entry and its version's capability read state that engine while the version holds no
society; a society already held keeps its engine; and a creation naming another engine for such a
world is refused by name (`409 society_engine_differs`). `model_decisions` means the engine's history may hold validated model decisions,
which the schema's decision triggers admit; `owner_model_choice` requires it, and a comparison
requires `owner_model_choice`. `exulanica/world/society_engines.py` reads and checks it, and every
list of engines derives from it: the runtime's edit hook, the repositories' dispatch and population
check, the playback control, directed actions, decisions, experiments, the creation route's choices
and default, and the selection query, which receives the lists as bound array parameters rather
than SQL text. The one other statement of engines is the decision role registry's, which names the
engines that host each role and so where the owner's model choices are recorded and the host asks;
`tests/test_decision_roles.py` holds them equal to the engines whose `owner_model_choice` the table
states. An engine the table does not state is refused by name wherever it is looked up, and a
retired one is refused by name when a creation asks for it (`409 society_engine_retired`). The
table's first shape, `society-engines.v1.json`, and its second, `society-engines.v2.json`, stay
beside it because evaluation records and the comparison drawing of their day name them, each held
to this one's rows by a test; the loader and the browser read the second as they read the third.

| Engine | Created | Inputs | Playback | Directed actions | Model decisions | Owner chooses models | Compared | Experiments | Sent away | Saved world | Population |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `exulanica-society/v1` | yes | no | no | no | no | no | no | no | no | no | 100 to 512 |
| `exulanica-society/v2` | yes | yes | yes | yes | yes | yes | yes | no | yes | yes | 1 to 512 |
| `exulanica-society/v3` | no (retired) | yes | yes | yes | yes | no | no | no | no | yes | 1 to 512 |
| `exulanica-society/v4` | yes | yes | yes | no | no | no | no | yes | no | no | 1 to 65,536 |
| `exulanica-society/v5` | yes | yes | yes | no | yes | yes | yes | no | no | yes | 1 to 512 |
| `exulanica-society/v7` | by name | yes | yes | yes | yes | yes | no | no | no | yes | 1 to 512 |

The browser reads the same file: `pnpm run society-engines:sync` writes it byte for byte, with the
union of its profiles, into `web/packages/app/src/society-engines.generated.ts`, which
`society-engines.ts` parses; the society client takes each snapshot's reader and population bounds
from it, and the engine a new society is created with from `creates`. Where a copy cannot derive,
it is held to the table by a test in `tests/test_society_engine_table.py`: every migration check,
trigger and index that names an engine is read back from the live schema and compared with the
capability it encodes, the population check is parsed engine by engine, no Python module outside
the table may restate an engine list as SQL text, and the display's own profile union in
atlas-react is held to the table's at typecheck (`web/packages/app/test/society-engines.test.ts`).
A module that asks what an engine can do asks the table: `tests/test_society_engine_capabilities.py`
fails any comparison of an engine's identity under `exulanica/` outside an engine's own
implementation and the dispatch to each engine's initializer, each listed with its count and why,
and `web/packages/app/test/society-engine-literals.test.ts` does the same for the app's source.

## Identity, branches and compatibility

The v1 to v3 population is 128 over a district; their pure initializer accepts 100 to 512 there.
A society on a saved world's own ground starts with the population its ground's entry in the
society ground catalog states, 8 for the built-in starter, or derives by its rule, one per place in
a home for a generated town (below). V4 sizes its population to its
place (below). Each engine's bounds are stated once, in the engine table (above). The population
is canonical state, independent of how many people a renderer draws. Inhabitant UUIDv5 identities derive from
society identity and ordinal. The same society ID/seed/population preserves those identities across
profiles, but a stored society's profile and seed cannot change. The society UUID derives from its
authored version UUID with the existing `exulanica-society/v1` identity domain, including for v2 and v3.

The server derives a new society's seed from its world, and no request names one
(`world_society_seed` in `exulanica/world/society.py`): the SHA-256 of the canonical document
`{profile: exulanica.society-seed/v1, workspace_id, world_id}`. It names the world by its identity,
its workspace and its id, and no version, so a world's people are the same people across its edits:
an edit is an input to the version's own society, and a new version of the world, a branch or
photographs added, starts a society again whose people draw the same roles, needs and first places
over the same ground. Two worlds start their people differently: their roles, needs and schedules
and every later draw differ, while over the same ground the initializer's spread still starts them
at the same nodes. A stored society keeps the seed it recorded, and replay reads that one. A
response never carries a seed: a snapshot, and its state and each event where the stored document
holds one, carry `seed_digest`, the SHA-256 of the seed's text, in its place, while `state_sha256`
and `document_sha256` still name the stored bytes (`served_snapshot` and `served_events`); the
first engine's state and events hold no seed, so they carry neither. Leaving the seed out is
presentation, one form of a society on the wire, not secrecy: it is derived from identifiers the
caller already holds, so anyone who knows them can compute it. A comparison commits each seed it
runs by the same digest: one function, `seed_digest` in `exulanica/world/society.py`, names a seed
wherever it is shown or committed.
`tests/test_society_world_seed.py` holds two worlds starting differently, a second version starting
the same people, an edit leaving every person as they were, and a society stored under a seed its
creation request named keeping it and replaying.

One society belongs to one workspace, world and authored version. V2/v3 `branch_id` equals that version
UUID; the authored version supplies its user-facing name. Same-named objects in two versions remain
different targets. A society's history is never forked: to opt in when a version already has
another profile, create a new authored version and a new society. No implicit migration, identity
substitution, tick reset or history rewrite occurs.

Unknown engine and input profiles are refused. WMP 1.0, the authored-world 1.0 extension and the
environment-instances 1.0 extension omit society and its input and event history; they cannot
resume this simulation.

## The purposeful society (v2)

`exulanica-society/v2` walks its people to reachable goals under the purposeful routine, over
inputs an authorised server adapter composes: a district's interpretation, or a saved world's own
ground. The sections below state what it reads, how it chooses, what edits and requests do to it,
and how a model its world's owner chose decides for one of its people. A stored v3 society reads
the same inputs and takes the same directed actions
([retired and frozen engines](#retired-and-frozen-engines)).

### V2 input authority

The policy consumes `exulanica.society-input/v1`, a validated projection from an authorized server
composition adapter. It does not compile a second district, infer navigation, or accept geometry
from browser request JSON. Inputs contain:

- `input_seq`, beginning at 1, independent of simulation ticks;
- `world_id`, authored `version_id`, `district_id`, district interpretation and base artifact digests;
- the frame the input profile declares, east/south axes and integer millimetres: `flatiron-local-mm`
  with its surveyed origin for a district projection, `authored-ground-local-mm` with no surveyed
  origin for a saved world's own ground (below);
- `authored_state: {edit_seq, delta_sha256}`;
- `bounded-sidewalk-graph/v1` nodes, undirected edges, destinations and unavailable reason;
- targets with stable `target_id`, spatial `subject_id`, `node_id`, `affordance`, `duration_ticks`
  (in an input that records a routine, the routine's `activity` in its place),
  `origin`, authored string `object_id` or null, `version_id`, and boolean `enabled`;
- digest-bound dependency references, availability and its explicit reason; and
- `document_sha256`, covering canonical no-float JSON excluding only that field.

Nodes/targets/edges are sorted by their IDs; dependencies sort by `(kind,identity,sha256)`.
Edge lengths are positive ceil Euclidean millimetres. Unknown references, duplicate IDs, wrong
frames, booleans masquerading as numbers, altered digests and unsupported actions fail closed.
Bounds are 16,384 nodes, 65,536 edges, 4,096 targets/destinations and 8,192 dependencies per input.

The adapter owns geometric clearance, accepted authored transforms, reviewed affordance assignment,
object identity and current rights. A navigation graph or stored dependency is not authorization.
It must validate all connectors and obstacles, including negative-space dependencies. Exterior
visit markers are not real doors, and the policy does not enter interiors or invent street crossings.
Initial v2 creation requires an available graph and an enabled reachable target. Initial subjects
are distributed deterministically among declared nodes in components containing enabled targets.

### Goals, routes and actions

Each tick is one simulated minute. People walk by the walking movement module
([movement modules contract](movement-modules-contract.md#walking)): shortest routes minimize
integer edge length with lexicographic node-path ties, and a walk spends its budget along its route
edge by edge, each point interpolated with integer floor division, in every profile. The travel
budget is the one the state records at creation, `movement_budget_mm_per_tick`, the walking
module's declared 60,000 mm for a new society (`MOVEMENT_BUDGET_MM`), at most one metre per
simulated second; an advance reads the state's figure, never the module's, so a stored society walks
at the budget it was created with.
What people do, how long each stay lasts and how it varies, what it relieves and how often it is
chosen are the purposeful routine's: versioned data in
`assets/catalogs/society/society-purposeful-activity.v<N>.json`, read by
`exulanica/world/society_catalogs.py`, with a reason for every figure, and no such figure in the
planner. The routine an input records selects them (`routine: {catalog_versions, sha256}`, which
`exulanica.society-input/authored-ground-v3` records and no earlier profile does); an input that
records none, every district input and every saved-world input of an earlier profile, is read under
version 1, the rules the society was released with, so nothing already recorded changes meaning. A
new routine is a new catalog version beside the old, never an edit of one an input names. A recorded
routine is read by its versions and digest alone, never against the world object catalog, so a
stored input stays readable whatever that catalog later drops; whether the kinds a routine names
are kinds that catalog states, offering the entry's affordance, is asked when an input is composed,
and a parity test holds the routine a new input records to the catalogs as they are
(`tests/test_society_purposeful_routine.py`). Every choice is a deterministic draw from the seed,
`sha256(seed:domain:tick:ordinal)`
(`exulanica/world/society.py`), so a replay makes the same choices in the same minutes. This is a
small deterministic utility policy, not learned preference or biography.

Version 1: a scalar need of at least 750 prefers rest; otherwise visit is preferred. Among
reachable candidates, the policy prefers a different target from the last completed one, then
lower route cost and target ID. `visit` takes one subsequent tick and `rest` three, and completion
reduces the need by 20 for a visit or 500 for rest, clamped at zero. A v2 history through twelve
minutes and 24 completed activities over an input that states no places is pinned by its state
digest (`tests/test_society_destination_room.py`), and a saved world's v2 society stored
before inputs recorded a routine, with a directed request, an edit, and everyone sent away and
brought back, replays byte for byte (`tests/test_society_v2_history_replay.py`).

Version 2, which a saved world's input records: a person whose need has reached 750 rests where a
rest place has room. Before anybody picks anything else in a minute, everybody else free to choose,
in ordinal order, draws once over all four activities' weights (rest 700, visit 1,000, stand 300
and talk 500 of 2,500), and that draw decides only whether they look for somebody to talk to: one
draw in five does. One who does is paired with the nearest person within 8 m who is free to choose
and not tired, or standing, the lower ordinal winning a tie. Anybody not paired, one who drew talk
and found nobody included, then picks among rest, visit and stand with room for them by those three
weights alone (700, 1,000 and 300 of 2,000 when all three have room), then among the free targets
of that activity by a draw rather than the nearest. A stay lasts a draw within its entry's range: a
kind the routine names has its own (a bench 5 to 15 minutes, the planter seat 3 to 10, the cafe
table 10 to 25, the market stall 2 to 6, the tree 1 to 4), and any other kind its affordance's
(rest 3 to 10, visit 1 to 3). Standing is a stay of 1 to 4 minutes at an open lattice node within
6 m: no place, not beside one, and nobody else's. The two people talking stand at two open nodes
joined by an edge of the lattice, so nothing stands between them, at most 2 m apart, and talk for
one shared drawn duration of 2 to 6 minutes, which runs only while both are there: the first to
arrive waits for the other with the clock stopped, and when either leaves, the other stops in the
same minute, as `partner_left`, walking over or already there. Talking has no content: no words,
topic, memory or belief is recorded or implied, and an event says only that two simulated people
stopped to talk. Rest and visit relieve what version 1's do; standing and talking relieve nothing. A
stay carries what finishing it relieves (`relief_milli` on its action), so it relieves what the
routine it began under says, whatever routine a later input records; a stay begun under an input
that records no routine carries nothing and relieves what version 1 says. Only a routine that draws
its stays states one for a target naming an activity, so an input recording a routine that picks the
nearest place is refused by name (`the recorded routine does not state every target's stay`). A
person's direct request ends a stay under this routine ("Typed user-directed actions"). Measured on
the small square with eight people over twelve seeds and 120 minutes,
against targets registered before the measurement (`docs/evaluation/2026-09-25-living-square.json`):
walking fell from 393 to 146 per mille of person-minutes, the median stay is 10 minutes on a
bench, 18 at the cafe table, 4 at the stall and 3 by the tree, standing is 40 and talking 167 per
mille, and every usable object is used in every world.

Arrival starts the action timer and does not spend its first tick. Each subsequent tick validates
availability and access position before progressing. Over an input that states no places, no
capacity, crowd avoidance, resource depletion, conversation or newly learned relationship is
implied by the v2 movement policy; over one that does, the rules under "Room at a destination"
apply. Existing role/household/relationship fields remain explicitly synthetic labels and do not
create extra supported activities.

The existing envelope and synthetic inhabitant fields remain. V2 adds:

- envelope/state `branch_id`, consumed `input_seq` and `input_sha256`;
- state `movement_budget_mm_per_tick` and `seed_sha256`;
- inhabitant `goal: {kind, target_id, reason}` or null, with the other person's `partner_id` and
  the shared `duration_ticks` for a talk;
- `route: {node_ids, edge_index, edge_progress_mm, destination_node_id, input_sha256}` or null;
- `action: {kind, status, target_id, remaining_ticks, reason}`;
- `motion_path_mm`, every segment traversed last tick, including start/end, or one stationary point;
- `explanation: {summary, event_ids}`, grounded in recorded decisions.

Additional engine state retains exact node/edge position, target binding and bounded event memory.
Rendering interpolates along `motion_path_mm`, never directly across its corners, and must retain
stable synthetic subject identity. Render motion cannot create canonical actions or events.

### Opt-in local activity failures

The `exulanica.society-composition/v1` projection keeps its original behavior, including
making the whole input unavailable when an active authored affordance has no supported access
node. Both `build_society_input` and `SocietyRuntime` retain this default. A host can explicitly
select `composition_profile="exulanica.society-composition/v2"` to enable local failure handling.
Persist this choice with the host configuration; it is not selected by browser request JSON.

Under that policy, a known reviewed stationary object's unreachable activity is omitted from
usable targets. The object's reviewed collision footprint still prunes navigation through the
same district geometry predicates. Independently validated nodes, edges, district activities and
reachable authored activities remain usable. No access node, connector, teleport or alternative
obstacle geometry is invented. An empty graph still blocks movement. Unknown active assets,
unsupported motion, invalid transforms/frames, structural overrides, invalidated sources and
withdrawn rights still produce a globally unavailable input with no materializable targets or
local records.

The `exulanica.society-input/v2` projection keeps the original fields and adds sorted
`unavailable_affordances`, each containing exactly `target_id`, `subject_id`, `object_id`,
`version_id`, `affordance` and `reason: authored_affordance_unreachable`. These identify an authored
activity without claiming an access `node_id`. Usable and unavailable target IDs are disjoint;
their combined count is bounded to 4,096. Records bind the same version and deterministic authored
subject/target identity as a reachable target. Full authored-object and reviewed-asset dependency
references remain present even when an activity is unreachable. An unavailable global input has
an empty local list, so withdrawal does not become a permission to display inaccessible data.

An inhabitant already pursuing the affected activity records a `replanned` event with reason
`authored_affordance_unreachable`, its prior target and the new input sequence/digest, then can
choose another reachable activity. Other inhabitants continue under the existing policy unless
the object's actual collision effect independently invalidates their route. A move or restoration
that supplies a valid access node returns the same target ID to the usable list. These are new
ordered inputs, never rewrites of prior failure records or completed actions.

Migration 0057 admits strict input/v1 and input/v2 profiles without modifying migrations 0053 or
0055. Engines v2/v3 accept both input profiles and replay each retained input with its original
semantics; v1 engine behavior is unchanged. V1 projection, state and event digest vectors are
pinned in tests. Historical authorization selects policy references from the stored input profile,
not from the projection policy the host selects, while still rechecking current rights and asset
bytes. The runtime binding structure and its digest do not change.

Apply the reader/schema support before opting a host into `exulanica.society-composition/v2`. Subsequent accepted
edits append the chosen projection. To recover an already paused society immediately, explicitly
append a fresh authorized projection through the runtime input-refresh/edit hook and then advance;
a configuration change alone does not rewrite the persisted state. A policy refresh can keep the
same authored edit cursor/delta digest while increasing `input_seq`. Replay therefore retains the
earlier global pause and the later locally degraded input exactly. Local records are available in the
stored input document for authorized adapters; no new browser endpoint is introduced.

### A saved world's own ground

A world a person saved has no district. Its spatial authority is the flat authored ground its own
structural snapshot states: one authored region, an elevation, a spawn point and, depending on
the ground module version, either a horizontal extent or an explicit statement that it has none.
`exulanica.society-composition/authored-ground-v3` projects that ground, and the reviewed objects
the person placed on it, into `exulanica.society-input/authored-ground-v3`, which the same v2
policy, persistence and replay consume. A society created over a world made from photographs uses
`exulanica.society-input/authored-ground-v4`: its input also pins the entry's authorized opening
region, source revision and region-local camera pose. Stored v3 inputs keep their profile and
arrival rule through later edits. The v3 projection is the
second profile's projection, which also records the purposeful routine it was composed under and
names each activity's routine entry in place of a fixed duration. The earlier saved-world pairs,
`authored-ground-v1` and `authored-ground-v2`, are never composed again and never rewritten: a
stored input of either is authorised by its stored bytes and replays with its own semantics, and a
society holding such inputs receives inputs of the newest profile from its next edit on. A
society's input profile only moves forward along that order; a successor of an earlier saved-world
profile than its predecessor is refused. There is no second engine and no second affordance
vocabulary: `visit` and `rest` remain the only activities an object offers, standing and talking
happen at no object, and the reviewed footprint, collision and reach table is the one the district
projection already uses.

Where inhabitants walk is the society's walkable area, and it is kept apart from what the ground
is, because a ground module need not state an edge.

- Ground module version 1 states a 24 m square. The society reads that extent and its input marks
  the area `source: "ground"`.
- Ground module version 2, which every new starter uses, states an endless plane with no extent.
  There is nothing to read, and a route graph over the whole plane a renderer can carry a person
  across would be tens of millions of nodes. The society therefore declares its own area: a square
  of 12,000 mm half extent about the region origin, marked `source: "declared"`. The declaration
  lives only in the society's inputs. The stored world keeps its endless ground; nothing writes an
  edge into it.
- A world made from a person's photographs (composer `atlas-world-composer`) states no ground, no
  spawn and no position for its regions: each photograph is an element nobody collides with. Its
  society stands in one of its regions, the one the creation names (`region_id`), on the plane at
  height 0 in that region's frame (an object standing at another height offers no activity, as on
  the starter), and declares the same square about the region's origin, marked
  `source: "declared"`. A v4 society starts around the saved entry's pinned opening pose, with at
  least 2,000 mm between that pose and each resident at genesis. The server selects a drawable,
  authorized region from the world's own saved source membership, by authored placement count
  then capture order, before the page's five-region display limit. It pins either a retained scene
  build, a standalone point map, or an authorized photograph and serves the pose in millimetres
  and millionths of a direction under the versioned arrival presentation policy. Earlier v3
  societies retain the region-origin arrival rule in the society ground catalog, where
  the starter's entry reads the spawn its snapshot states (`arrival: spawn`). Objects in the world's
  other regions are in another place (`objects_in_region`): they are no obstacle, activity,
  dependency or asset of this society's input, so a missing asset there leaves this region's input
  available, and an edit to one, like hiding or moving a photograph, changes nothing the society
  reads and appends no input. An object naming a region the world does not state still makes the
  input unavailable. The small square and the app's People nearby read the same region: only its
  objects stand in the square's way, and only they are listed and noticed. The lattice spacing and
  navigation profile are the entry's own. A creation that names no region, or a region the
  world does not state, and a world with an element somebody would collide with, are refused by
  name (`424 unavailable_society_input`). The ground reader dispatches on the snapshot's composer
  through the catalog, and a composer it states no ground for is refused the same way
  (`tests/test_society_made_world.py`). The same catalog entry declares that square a floor
  (`floor: declared`, where the starter's ground is `floor: stated`): the entry read serves it as
  `declared_floor`, and the app draws it in every region as a surface of its own with a visible
  edge, so a person sees what people and objects stand on and never a photograph posing as ground.
  Objects and the small square are placed on it in the region the person stands in.
- In the app, People nearby brings a made world's people into the region their society already
  lives in, else the region the world opens in (`openingIsland`, the region holding most of the
  person's placements, else the first). A v4 society's pinned region is drawn before the display
  limit and its pinned source and camera pose are checked against the geometry the page loaded.
  If the source is withdrawn or the bytes fail verification, the page names
  `arrival_source_unavailable`, draws only currently authorized geometry and withholds the society
  until its pinned source is readable again. The stored input and history are unchanged. The app
  hangs the crowd under that region's root, which every
  drawn region has whether or not anything in it was reconstructed (`hostRegionSociety`), with who
  decides for them offered as on the starter. Where this open does not draw the society's region
  the panel says nobody can be shown, where reading the society fails it says why, and the page
  never moves a crowd to another region. A region's position in the world is not stored: the page lays the
  regions out again on each open (`buildScene` with no stored placement, in
  `web/packages/app/src/main.ts`), so a region can stand somewhere else after the world gains a
  photograph, and its people move with it, because every position they have is in the region's
  own frame. The page reads a flight only for a world with an authored scene, the starter, so a
  made world has no birds (`web/packages/app/src/composition/environment-selection.ts`).
- A world generated from a recipe of the city grammar (composer `city-grammar-town`,
  [`exulanica/world/composers/city_grammar_town.py`](../exulanica/world/composers/city_grammar_town.py))
  states its ground in its own records: footways, corners, crossings and the entrances of its
  premises. Its catalog entry (`generated_town`, navigation `walking_surfaces`, navigation profile
  `city-walking-surfaces/v1`) has people walk those surfaces rather than a lattice, and
  `exulanica.society-composition/walking-surfaces-v1`
  ([`exulanica/world/society_walking_surfaces.py`](../exulanica/world/society_walking_surfaces.py))
  composes `exulanica.society-input/walking-surfaces-v1` (migration 0118) from the city place the
  living society reads a city by (`place_from_city_records`), with the world's records read
  through its receipt (`town_records` in `exulanica/world/generated_worlds.py`). Positions are
  east and south of the city's origin in plan, in the frame `generated-ground-local-mm`, whose
  altitude reference is `plan-only`: the height a person stands at stays in the records. The walkable
  area is the rectangle the world's tiles cover, a walking clearance beyond each edge, because the
  surfaces run to the edge. A person arrives at the world's spawn (`arrival: spawn`). Composer
  version 1 selects the standing spot nearest the centre of the world's extent; version 2 selects
  the nearest non-seat footway spot that is at least 2,000 mm from furniture and tree extents and
  from the home nodes where residents begin, with spot identity breaking ties. The receipt pins
  the selection policy and town routine so the spawn replays with its original rule. The
  activities are the world's own: every premises whose use class admits
  visitors is somewhere to visit, stood at at its entrance, and every piece of street furniture
  whose use class seats people is somewhere to rest, one place per seat; a place that cannot keep a
  standing spacing from another, and any object the person placed in the town, is recorded as
  unreachable (`authored_affordance_unreachable`), because the composition joins nothing a person
  placed to the world's surfaces. The population is the entry's rule, `residents`: one inhabitant
  per place in a home that is lived in, as the town's place states it for each premises under
  the routine the town was made under (below, "Its homes follow its floor"),
  recorded in the input, and a world whose homes hold nobody, or more than the entry's figure of
  128 (the town's tick budget, 200 ms at the 95th percentile, a tenth of the 2,000 ms fastest play
  interval, within which one tick of 128 people on the largest walking graph measured for the
  world specification, 962 nodes in a market town at the values whose towns hold the most places,
  took 130.4 ms at the median and 159.4 ms at the 95th percentile, measured with
  `scripts/measure_generated_world.py`), starts no
  society (`409 world_holds_no_residents`, `409 population_over_tick_budget`). The town's composer
  holds each seed candidate to the same rule before it keeps one (`refuse_population`), so a town
  is made only if its society can start. A town of several tiles is one walking graph, read from
  all its records, whose footways run on across the lines its tiles share, so its people walk from
  one tile to the next. The ground builder
  reads a ground by its entry's navigation and floor forms, never by the entry's name
  (`tests/test_generated_worlds.py`). A comparison of a town's society is held to how long reading
  one of its runs may take, which bounds how many of its people a model may decide for
  ([what a comparison can read](society-experiments.md#running-a-comparison)).

The declared figure keeps the lattice at 121 nodes, which holds one tick of 128 inhabitants near a
tenth of a second, and it equals the only bounded starter ground the product has shipped, so an
old and a new starter give a society the same lattice and the same node identities. An object
placed outside the area is still in the world and still drawn; the society records its activity
in `unavailable_affordances` as `authored_affordance_unreachable` rather than stretching its area
to meet it. The area is part of what a society is, like its seed: an edit changes what is inside
it and never where it is, and an input that moves it is refused as a successor.

What the projection reads and what it declares are kept apart, because only one of them is a fact
about the person's world.

- Read from the world: the region identity, the ground module version, kind and elevation, the
  bounded extent where the module states one, the element the ground belongs to, the structural
  snapshot digest, and every accepted authored object's asset, region, transform, origin and
  removal. A snapshot whose composer the society ground catalog states no ground for, a starter
  that is not the built-in authored starter at a supported module version, and a ground kind the
  projection has no rule for are refused with the reason rather than guessed at.
- Declared by the ground's entry in the society ground catalog
  (`assets/catalogs/society-ground/society-ground.v5.json`, read by
  `exulanica/world/society_grounds.py`): the walkable area on a ground that states none, and a
  route lattice at two metre spacing over the area, inset by the navigation clearance. A flat
  rectangle has no paths of its own, so a graph over it is a discretisation the entry fixes, not a
  shape measured from anything. Two metres keeps every point of the area within 1,415 mm of a node,
  inside the reviewed object reach, and keeps a 24 m area at 121 nodes and 220 edges; the catalog
  refuses a spacing that would leave a point beyond that reach. Each figure's reason is in its
  entry. An input records the navigation profile, spacing and area it was composed with, so another
  figure is a new entry with a new navigation profile and never changes a stored input.

The authored input's `navigation` carries `walkable_area`: `source`, `centre_mm`, `half_width_mm`
and `half_depth_mm`. Validation refuses a node that lies outside the stated area by less than the
clearance, so a stored input cannot route where the area it names would not have produced a node.

The input keeps the shape every profile shares. `district_id` is the authored region's identity
(`authored:region:starter`), `district_document_sha256` is the digest of the ground descriptor
the projection read (which carries the ground kind and the walkable area with its source, and no
ground extent for an endless ground), and `base_artifact_sha256` is the structural snapshot's own
digest. The frame
is `authored-ground-local-mm`, east/south integer millimetres about the region origin, and it
states no `origin_crs84_e7`: a saved world was never surveyed anywhere, and a coordinate reference
origin would be a claim about the Earth that nothing measured.

`navigation.destinations` is empty. A ground declares somewhere to stand, not something to do, and
calling the spawn point a visit would invent an affordance the world never declared. Every target
in a saved world comes from a reviewed object with an affordance, so a starter with nothing in it
has a walkable area and nothing to do in it, and society creation refuses by name,
`409 no_reachable_targets` (`initial society requires reachable targets`), until the person puts
something there.

A society on a saved world's own ground starts with the population its ground's catalog entry
states, 8 people for the built-in starter, where a district starts with 128: an area about 23
metres across with 121 places to stand would otherwise have people standing on top of each other
from the first minute. The repository reads the entry named by the navigation profile of the input
it creates the society over. A comparison runs the population its society recorded, and the most
people a comparison runs, derived from how long reading a run may take, is at least every stated
ground's population, so every saved world's society can be compared (`tests/test_society_grounds.py`, which also holds the starter's
descriptors, inputs and first half hour to the digests they had when these figures were code). The authored
input's `navigation` states `arrival_mm`, the point a person arrives at, read from the snapshot's
own spawn; like the walkable area it is refused as changed by a successor. Nobody starts on it or
within 2,000 mm of it: the initializer takes the reachable nodes outside that distance in node
order and spreads the population evenly across them, so the same seed always starts the same
people in the same places and replay, which rebuilds the first state from the seed, the population
and input 1, starts them there too. A district input states no arrival point and keeps its
original starting rule and its floor of 100 people.

Under the first saved-world profile a society had no capacity: with one reachable target every
idle inhabitant chose it, walked to its access node and stood there with the others. The second
profile gives every destination room (below).

#### One object at a time

The second profile decides every object on its own
(`exulanica/world/society_authored_ground.py`, `_objects_one_by_one`). An object the society cannot
use loses its own activity to `unavailable_affordances`, with the reason, and takes nothing else
with it; the rest of the world stays usable.

| An object that | Blocks walking | Offers its activity | Recorded as |
| --- | --- | --- | --- |
| is turned | its reviewed footprint, turned with it | yes | used |
| is scaled | its reviewed footprint at its scale, rounded up to the millimetre | yes | used |
| does not rest on the ground plane | its footprint where it stands on the plan | no | `authored_object_off_ground` |
| moves (`motion.bounded-path` version 1) | everywhere its motion covers: the convex hull of its footprint at both ends of the path | no | `authored_object_moves` |
| blocks nothing and carries a behaviour with no rule | nothing | no | `unsupported_active_behaviour` |
| has no access node or place it can be reached at | its footprint | no | `authored_affordance_unreachable` |

An object off the ground plane still blocks its footprint because the society does not know
whether a body passes under it; it does not ask how tall the object is. A bounded path runs along
one axis of the region from where the object was placed and back, as the renderer moves it
(`web/packages/atlas-core/src/behaviour/bounded-motion.ts`), and travel along the vertical axis
leaves the plan footprint where it is. The society holds no motion phase: an object that moves is
treated as covering its whole path at every minute.

What still makes the whole input unavailable, with the object named, is what leaves the society
unable to say where it may walk: an asset with no reviewed footprint (`unknown_active_asset`), a
behaviour with no rule on an object that blocks walking (`unsupported_active_behaviour`), an object
in another region, an origin or a transform no writer produces, and obstacles that leave no node.

An environment placement is named in the input's `unread_placements` with the reason
`environment_placement_has_no_authored_frame` and changes nothing else. A saved world's ground
states no surveyed origin to place an admitted source against, and the renderer draws such
placements only inside the owned district
(`web/packages/app/src/composition/environment-selection.ts`, `setAuthoredInstances`), never in a
saved world. The list is bounded and empty whenever the input is unavailable.

A saved world's snapshot has one element, its ground. An override that keeps the ground exactly
where the snapshot places it changes nothing the society reads; one that hides or moves the ground
changes what everyone stands on and makes the input unavailable as
`unsupported_ground_override:<element>`. No public route writes an override.

Under the first saved-world profile an object off the ground plane, in another region, carrying a
behaviour, scaled, or of an unsupported origin, any environment placement and any override made
the whole input unavailable with the object named; its stored inputs keep saying so.

#### Room at a destination

Every activity in a second-profile input states the places its occupants stand at
(`destination_places`), and a place holds one person.

| An object that | Holds | Where |
| --- | --- | --- |
| names rows of places (a furniture kind of the world object catalog, like the bench) | as many people as each row names | along the side the row names, a navigation clearance and a standing radius out from it, centred on it |
| a person can walk on (blocks nothing, like the Marker plate) | a row along its own x axis, one standing spacing apart, as many as have their centres on it | on the object |
| blocks walking (the Marker cube and pillar) | one person in front of each face | a navigation clearance and a standing radius out from the face |

The standing spacing and radius are the society-policy catalog's `standing_spacing_mm` (700) and
`standing_radius_mm` (340), the figures the living society keeps, read when the input is composed
and recorded in its `navigation.standing_spacing_mm`, so replay never reads the catalog. Places turn
and scale with their object. A place is kept only when it lies in the area, clear of every
obstacle, at least a standing spacing from every place kept before it, and within the object's
reviewed reach of a lattice node it can be walked to from in a straight clear line; it becomes a
leaf node joined by one edge to the nearest such node. Validation refuses an input whose places
stand closer than its stated spacing. A reviewed Marker plate holds two, a cube or a pillar four,
a bench three and the planter seat four, fewer where a place does not fit. The world object catalog
derives a kind's places from the figures above, read where the society reads them
(`exulanica/world/object_catalog.py`): each row stands a navigation clearance and a standing
radius out from its side of the kind's footprint, its places a standing spacing and
`TURNED_PLACE_MARGIN_MM` (2 mm) apart. Turning an object moves each coordinate of a place outward
by less than a millimetre, so two places come less than the square root of two millimetres
closer, and at the kind's own size or larger no yaw brings two of its places within a standing
spacing. Measured at each kind's own size over every microradian of yaw, the closest two places
come is 700.746 mm, the planter seat's; `tests/test_society_object_catalog.py` counts the places
the society keeps at every 997th microradian at a kind's own size and at the largest scale an
object takes. Smaller than its own size, a kind's places come together with it, and a row can
hold fewer. A kind's footprint is the least rectangle about its origin that holds every part lower
than the walker capsule the city grammar's nav envelope keeps clear (`capsule_clearance`, 1900 mm
high), so a table top blocks walking and a tree's crown or a stall's awning does not. A kind nobody
uses, like the lamp post, is an obstacle and nothing else: it blocks walking where it stands,
offers no activity and leaves no record of one.

Over such an input the v2 policy keeps room (`exulanica/world/society_planner.py`):

- a person takes an activity only where one of its places is free of anybody standing there or on
  the way there, and walks to that place;
- a person never takes up again, unasked, the activity whose place it is standing at, so somebody
  waiting gets a turn;
- a person who has finished at a place and has nothing else to do walks to the nearest node where
  nobody stands or is headed and that is not a place, the node a place is joined to, or within a
  standing spacing of a place (`goal: {kind: "make_room", target_id: null}`), and waits there;
- nobody starts on, or next to, a destination;
- a person sent somewhere by a directed request is promised its place before the minute, in
  request order, and a request to a destination with no free place is refused `destination_full`;
- when an edit moves, turns, scales or removes an object, gives it motion, or crowds out one of its
  places, whoever stood at a place that no longer stands where it did, or on a node or edge the new
  input no longer has, steps aside as the minute consumes the edit, before its walk: to the nearest
  lattice node, by distance and then node id, that is no place, has an edge, and is not where
  anybody else stands or is headed, first among those where nobody waiting would be in the way.
  The step leaves a `replanned` event (reason `place_moved`, or `standing_node_removed` off a
  place; outcome `stepped_aside`), the activity ends unfinished, and the person may take it up
  again at the object's new places;
- a position an edit left behind holds no place against anybody, and a directed request reads
  positions against the input its minute consumes;
- somebody part way through an activity at a place an edit left where it was, for the same
  activity, keeps going to its end with the time it had left, even when the edit moves the society
  to a newer routine; somebody standing or talking at an open node an edit leaves open keeps at it;
- a place an input of a newer profile only restates, naming a routine's activity where the older
  input stated a fixed duration, is the same place: nobody walking there or just finished there
  replans, a stay begun there is the newer input's, and the v3 cast's memory of it still holds.

Measured over three seeds and 240 minutes with eight people (`tests/test_society_destination_room.py`):
no two people standing still are closer than 700 mm, a destination never holds more people than
its places, and with one two-place plate every one of the eight rests, none more than twice as
often as any other. An input that states no places takes exactly the path it always took.
`tests/test_society_edits_under_people.py` rests two people at a two-place plate and then moves,
turns, scales and removes it and gives it motion: both step aside with that event, nobody stands
where the ground went in the thirty minutes after, and people rest at the moved, turned and scaled
plate's new places. An edit elsewhere lets the two finish their rest.

An object stands at whatever yaw the person placed it at, and placing one in front of yourself
turns it to face you. Its centre and its reach do not turn with it. A blocking object's obstacle
is its reviewed footprint turned about its centre by the yaw, the way the renderer turns the
object: its own x axis goes to (cos, -sin) and its z axis to (sin, cos) in the region's frame.
Each turned corner coordinate is rounded outward, away from the centre, to the whole millimetre,
so the obstacle grows by less than a millimetre on each axis and never opens a route through what
the object covers; unturned, it is exactly the reviewed rectangle. For every blocking footprint the
world object catalog states, no nonzero microradian yaw brings a turned corner within 1e-9 mm of a
whole millimetre (the least is 4e-9 mm, for the planter seat, measured by
`tests/test_society_object_catalog.py`), a thousand times more than one unit in the last place of a
cosine and of a sine moves such a corner, so that rounding does not depend on a machine's
arithmetic. The district projections
keep refusing a turned object as `unsupported_object_transform`. So does an area smaller than the navigation clearance
(`walkable_area_smaller_than_clearance`), a version whose snapshot is not the registered one
(`authored_ground_snapshot_mismatch`), an invalidated source and a structural override. An
unavailable input carries no nodes, edges, destinations, targets or local records.

A depth estimate placed from the person's own photograph takes part in the authored state digest
and in nothing else. It is personal evidence drawn in the world; it is neither ground to stand on,
an obstacle nor an activity, so the society's area, lattice and targets are the same with or
without it.

A saved world holds inhabitants only because the person asked, and saving a world never registers
it. The request is the ordinary society creation, `POST /world/versions/{id}/society` with the
saved world named as `world_id`, a v2 or v3 profile and no `place_id`. For a version whose
structural snapshot is the built-in authored starter, the server derives what the society binds
from the world itself: an `AuthoredWorldSocietyBinding` with identity
`exulanica.society-saved-world/v1:<version_id>`, the snapshot's own authored region, and the place
identity `uuid5(version_id, "exulanica-society/saved-world-place/v1")`, derived from the authored
version exactly as the society's own identity is derived under `exulanica-society/v1`. The place
names where in the workspace the society lives and claims nothing about the Earth. The place row,
the first input and the society are created in one transaction, so a refusal, such as a world with
nothing reachable in it or a v4 profile, leaves none of them behind. Asking again returns the same
society and creates nothing. A version whose snapshot is anything else derives nothing and is
refused with the reason. Because the whole binding is a function of the version and its snapshot,
a runtime built again from nothing derives it byte for byte and authorises the stored inputs.

Every instance serves this, and nothing is created, started or scheduled until somebody asks:
`/readyz` says that no world holds a society until its owner asks for one, and that without the
playback worker a society advances only when somebody advances it. A host can still register
`AuthoredWorldSocietyBinding` rows naming a workspace, saved world, authored version, that
version's structural snapshot, the authored region and the workspace place identity the society
row binds: `EXULANICA_SOCIETY_AUTHORED_WORLDS` names an `exulanica.society-authored-worlds/v1` JSON
file of them, and a registration there takes precedence for the version it names. A version
composes as a district or as an authored world, never both, and neither kind of binding supplies
bytes: an instance whose blob store lacks a reviewed asset composes an unavailable input that says
so. `GET /world/versions/{id}/society/district` answers 404 for a saved world, because there is no
district to present.

An object edit in any world reaches the runtime in its own transaction. The asset read lock is one
lock for the whole database, so the runtime takes it only for a version that holds a society whose
inputs read assets; an edit in a world with no society waits on nothing global.

`exulanica-society/v2` and `exulanica-society/v3` consume an authored ground, and typed directed
actions work over it. `exulanica-society/v4` refuses one: the living society reads streets,
occupancy and stated surface heights out of its place contract, and a flat authored rectangle
states none of them, so creation says that rather than publishing a place of empty answers.

Migration 0094 admits the third input profile and applies the bounded, availability-consistent
local-record rule 0057 wrote for `exulanica.society-input/v2` to it unchanged. Migration 0098 admits
the fourth, `exulanica.society-input/authored-ground-v2`, under the same rule, and holds its
`unread_placements` to it too. Migration 0108 admits the fifth,
`exulanica.society-input/authored-ground-v3`, holds its `unread_placements` to the same rule, and
holds that it records a routine and no earlier profile does. A check passes when its condition is
null, so each of these rules is asked whether it holds: a newest-profile row whose routine names no
catalog versions, or that omits its `unread_placements`, is refused rather than admitted by a null.
0108 also re-creates the request binding 0060 wrote, which refused a request for anybody part way
through anything: it asks `society_person_may_be_directed`, which admits exactly whom the
society may direct ("Typed user-directed actions").
Migration 0095 lets a v2 or v3 society hold 1 to 512 people, keeping
v1 at 100 to 512 and v4 as 0075 left it. A row does
not say which kind of ground its society stands on, so the district's floor of 100 is held by the
initializer that every creation and every replay passes through.

### Authored edits and inability to act

Each relevant accepted authored edit appends a full immutable input snapshot in its transaction,
even if several edits happen between simulation ticks. An edit is relevant when the input composed
after it differs from the last one in anything but its sequence number, the authored edit cursor
and the ability modules only a society's first input records: an edit that changes nothing the
society reads appends nothing (`_reads_the_same` in
`exulanica/api/society_runtime.py`), such as an object in another region of a made world, a
photograph hidden, or an environment piece moved, which an input names only as a placement it does
not read. The next committed step consumes every input
in sequence before moving or acting. The repository checks contiguous input sequences and monotonic
authored edit cursors; the adapter must ensure no relevant accepted edit is omitted. Equal authored
cursors require equal delta digests; a rights-only input can retain the cursor.

Moving, disabling or removing a current target invalidates its plan before action use; a target an
input of a newer profile only restates, naming a routine's activity for a fixed duration, is the
same target and invalidates nothing. Changed navigation conservatively invalidates plans, except
that over an input that states places somebody
performing an activity at a place the edit left where it was keeps going, and somebody standing or
talking at an open node the edit leaves open keeps at it. New enabled reachable
targets wake blocked inhabitants. Over an input that states no places, if a changed graph no longer
supports the inhabitant's current node/edge position, it stops there with
`current_position_invalidated`; there is no nearest-node snap or teleport. Over one that states
places, it steps aside instead, as "Room at a destination" states. If the same position becomes
valid after a supported restoration, planning can resume. Disconnected or absent targets
produce `no_reachable_affordance` or `no_enabled_affordance`. Unavailable dependencies pause action
with their recorded reason. Repeated unchanged blockage does not emit another event every tick.

Undo/restore is a later authored edit and input sequence. It can restore a target or route under
current authorization. It never reverses completed actions, rewinds society time, deletes events or
resurrects withdrawn sources. A move followed by undo before a tick still has two retained inputs;
replay must verify both. Earlier simulated observations remain in their original version/input scope.

### Typed user-directed actions

A person can ask one of a society's people to go to a place or do something there. Migration 0060
adds the append-only `world_society_action_request` and `world_society_transition_action` tables
for these requests: a bounded external input for v2 and stored v3 societies, separate from model
decisions and playback controls. They do not broaden the affordance registry or accept free-form
movement.

The authenticated base route is
`/world/versions/{version_id}/society/actions`:

- `POST` accepts exactly an idempotency key, base tick/state digest, synthetic subject ID and
  either `{kind: "go_to", target_id}` or
  `{kind: "perform", target_id, affordance: "visit" | "rest"}`, or, in a society of things
  running the hands module, `{kind: "hands", ability: "pick_up" | "put_down" | "give" | "take",
  thing_id, with_id}` (see below);
- `GET` returns newest-first authorized request envelopes; and
- `GET /{request_id}` returns one request and its pending or consumed status.

The client supplies no position, route, target document, workspace, actor or branch. Under the
workspace lock the server resolves the current v2/v3 society and latest consumed input, rechecks
current source authority, freezes the exact canonical target and records the requesting actor.
Requests require an idle/blocked/completed inhabitant, or one part way through a stay under a
routine that draws its stays, current available input, an enabled reachable target and no other
request for that inhabitant at the same state. The database's request binding holds a recorded
request to the same rule about the person (`society_person_may_be_directed`, migration 0108), and
`tests/test_society_request_rule_parity.py` holds the two equal. A request to go where the person
already is, part way through a stay there, is refused `inhabitant_already_there`, which the page
says in words: ending the stay would only begin it again. In a society of things that runs the
second purposeful module, a request for an activity the person's kind does not list is refused
`activity_not_offered`. Exact retries return the existing
envelope; changed reuse or stale bases fail without another write.

A hands request is recorded as `exulanica.society-action-request/v2`, read beside v1: v1's fields
without `target`, its thing in the table's `target_id` (migration 0170). It is taken only by the
rule a v1 request is taken by, and only for an act the being is offered on the state the minute
starts from, over the hands module's whole approach distance ([things
contract](things-contract.md)), checked when it is made and again by the minute that consumes it: a
society that does not run the hands module refuses it `act_not_offered`, its thing or the being it
names gone `thing_gone`, a pick-up or a take of a thing a visitor still here brought
`belongs_to_visitor` (only that visitor hands it over), and anything else the module does not offer
`act_not_offered`. At its minute it walks the being, or holds it where it stands within reach, by
the goal policy a decider's chosen act takes, marked as the owner's: the walk to stand within reach
records a request's reason (`remembered_target_selected`) and the wait `validated_user_wait`, never
a model's; a stay the request ends or a blocked goal gives way to the walk, as it does to a request
for a place. The things phase does the act once the being stands within reach, recorded with the
reason `asked_to_<ability>`; an act that no longer holds is dropped `thing_gone` or `out_of_reach`.
An asked act the being's decider replaces with a hands act of its own is recorded as left undone
(`hands_missed`, `chose_otherwise`), and so is a pending act a request replaces (`asked_otherwise`);
a `hands_missed` for an asked act states `asked`. Its `user_action_requested` event states `target`
null and the act asked. As every direct request does, an applied one sets aside the being's
decider's answer for that minute (`person_asked_directly`).

Recording a request does not advance society time. The next normal deterministic step consumes
ordered pending requests through the planner's goal-policy seam. `go_to` constrains the next goal
to the target; `perform` also binds the target's affordance. Each request receives one
`applied`, `stale`, `unavailable`, `rejected` or `superseded` disposition and a
`user_action_requested` event. The transition binding requires the exact request, previous state,
input span, tick and event digest. Replay regenerates the disposition and event from genesis using
the stored request and original inputs; it never calls a model or treats the request itself as
completed movement.

There is no cancellation or expiry. A stay drawn from a routine's range can last up to 25 minutes,
so under such a routine a request to somebody part way through one ends it in the minute the
request is consumed, before anybody chooses: a `replanned` event with reason `called_away` and
outcome `stay_ended`, no relief, and for a talk the other person stops in that same minute
(`partner_left`), whichever of the two the minute reaches first. A walk is left to arrive, and
under the rules the society was released with, which every input that records no routine is read
under, a request to anybody mid-action is refused `inhabitant_action_in_progress`
(`tests/test_society_square_requests.py`). A request can direct only the next eligible goal and
ordinary navigation/action checks remain authoritative. Over an
input that states places, a request is refused `destination_full` when every place of its target is
held by somebody else, and an applied request is promised its place before the minute, so nobody
choosing freely in the same minute takes it first. It cannot
teleport, cross unsupported space, undo completed actions or simulation history, or replace a
withdrawn target. The browser has a control on a declared visit or rest destination that issues
one typed `perform` request through this API and shows the returned pending or consumed record, or
an explicit unavailable or refused state. It re-checks its gate whenever the persisted society
refreshes. Living (v4) societies refuse it: the engine table gives v4 no directed actions.
Simulated action records stay labeled as simulation and are never presented as personal evidence.

In a person's own saved world the control is reached like this. Opening the world reads its
society and creates nothing; the People nearby panel says when nobody lives there, what
inhabitants need, and offers "Bring in inhabitants", which is the creation request above. Once
they live there, the panel lists every object with what the consumed input says of it (somewhere
to rest or visit, out of reach, or not noticed until the next simulated minute), and "Advance one
minute" performs one control step while the world is paused. A chosen inhabitant's panel carries
one request per usable place. Every request names the saved world.

The same panel holds the world's only Play, Pause and pace controls; About points to them. Play
is offered only where the control read's `host_playback.running` says this host plays the world;
otherwise the panel shows the server's own `reason` and keeps "Advance one minute". While a world
plays, the page reads the control about every two seconds (half the effective interval when that
is shorter, never more often than every 500 ms) and reads the society only when the control's
tick differs from the one drawn (`web/packages/app/src/composition/environment-selection.ts`).
Minutes the page did not read are rebuilt, for drawing only, from the paths their event
documents record (`society-unread-minutes.ts`); a minute the bounded event window cannot vouch
for is not rebuilt. After the person places or moves an object while people are there, one line
says the simulated minute that notices it: the server's current tick plus one, confirmed once a
state consumes a later input. The inspector's top lines say who the person is, what they are
doing and why, turning the engine's reason codes into words and naming places by the titles of
the person's objects (`inhabitantWords` in `web/packages/app/src/ui/world-inhabitants.ts`); a
code it has no words for is shown by name. The recorded explanation and bindings stay in its
details.

In the owned district the control is implemented and unit-tested
(`web/packages/app/test/society-directed-action.test.ts`,
`web/packages/app/test/environment-selection.test.ts`), and no shipped configuration reaches it:

| Prerequisite | What the shipped app does instead |
| --- | --- |
| The owned district's interpretation, which publishes the destinations | Saved and starter worlds open without the owned district, and its interpretation is read only by a caller that supplies current dependency resolution |
| A mounted control | The development preview (`?preview=1`) omits it |
| A held v2 or v3 society | A district needs a host district binding, and the browser creates a district society as v4 (`web/packages/app/src/composition/live-society.ts`), for which the API accepts no directed actions |

### Sending inhabitants away

The person whose world it is can send everyone away and bring them back
(`exulanica/world/society_presence.py`), in a v2 society; the engine table says which engines
allow it. Each is one recorded minute of the society, bound to the request that asked for it:

- Sending everyone away is a transition in which every person emits a `departed` event, in order,
  with where they stood; the state then holds nobody and says so,
  `presence: {status: "away", since_tick, request_id, request_sha256}`. Time goes on while they
  are away, with nobody in it.
- Bringing them back is a transition in which the same people, with the same identities and names
  derived from the society's seed, arrive at the starting places a genesis gives them over the
  world as it is then, with no goal, each emitting an `arrived` event. It is a new arrival, never an
  undo: nothing of what they did before they left is restored, and nothing about the departure is
  erased.

Every state before the departure, its events and its transitions stay where they were, so replay
rebuilds every minute on both sides of both changes from the stored request and inputs, and the
authored version they lived in is untouched by their leaving. A world reopened while they are away
has nobody in it.

`POST /world/versions/{version_id}/society/presence?world_id=W` accepts exactly
`{idempotency_key, presence: "away" | "here", base_tick, base_state_sha256}` and answers with the
society. The server resolves the world, the society, the rights and the minute under the same lock
and compare-and-swap as a step. An exact retry answers with the society as it is. A request against
a state that has moved on is `409 stale_society_state`. A request the state cannot honour is a
`409` naming why: `nobody_to_send_away`, `already_here`, `a_request_is_waiting` (a directed request
waits for the next ordinary minute), `nowhere_to_arrive` (no reachable place over the world as it
is), or `engine_keeps_its_people`. Migration 0098 adds `world_society_presence`, one append-only
row per such minute, bound to its transition, with forced row-level security; its trigger holds the
row to the minute it took and to an engine that allows it.

In a person's own saved world the People nearby panel offers "Send everyone away" while they are
there, for a society whose engine allows it, and "Bring them back" while they are not, says which
is the case and since which simulated minute, and says a refusal in words.

### A person run by a model their world's owner chose

A world's owner may choose an open model for one of a purposeful society's people, or for a group.
At the routine's own choice points, when a person has no goal or has just finished what they were
doing, the playback host asks that model before the minute to pick one of the things the routine
itself could start for them then: go to a place with room for them, wait a minute, stand a while
nearby, or stop to talk with somebody the routine could pair them with. The minute checks the
answer again and applies it as a goal policy, recording `chosen_by_their_model`, or records why it
could not; replay applies the stored receipts and calls no model. With no choice recorded, nothing
is asked or reserved and the routine decides, so a society's history reads no decision row until
its owner chooses a model. The registry of decision roles, the owner's choice, the person's
contract, the host's asking and its spend bounds, and each decision's disposition in its minute
are the [decision roles contract](decision-roles-contract.md)'s. The same hour run once per model
and scored is described under [comparisons of models](society-experiments.md#comparisons-of-models).

## Storing, replaying and playing a society

Every engine stores a society as a current snapshot with its events. An engine that takes inputs
also keeps every input and transition, immutable, and replays from its first input. The playback
controls and the HTTP routes below serve every engine the table lets them.

### Events, persistence and replay

V2 emits `goal_selected`, `route_progressed`, `action_completed`, `replanned` and `blocked`, and
`social_contact` when two people start talking under a routine that has talking; its document names
no words, only that the two stopped to talk. Event documents contain deterministic `summary`,
`synthetic: true`, profile, branch, subject, tick,
order, input sequence/digest, typed target, reason/outcome, goal/action facts, position/path and
previous-state/seed lineage. Event UUIDs bind society, tick, order and document digest. Authored
string IDs stay inside typed targets; SQL `object_id` remains null rather than coercing a string
into a UUID. Summaries are deterministic templates, never invented biographies. A summary names its
person "(simulated)" after its name, as every society of people has; in a society of things whose
first input records the crossing module's second version (`exulanica-ability/crossing/v2`, every
one made since it was built) a visitor is named by what it is instead, "(from outside, decided by
its own program)" or "(from outside, decided by this world)", in every event about it and in its
explanation, and a crossing refused before anybody arrived "(from outside)"
(`exulanica/world/society_summaries.py`). A society that recorded the first version names its
visitors as it always did, so its stored events keep their bytes.

`world_society` retains the state and digest. `world_society_event` retains events. V2 additionally
requires `world_society_input` and `world_society_transition`, supplied by the integration migration.
Inputs and transitions are append-only during normal operation with workspace isolation. Each
transition records previous/result state digests, its inclusive consumed input span, ordered event
IDs and a digest of the ordered event identities/documents. Snapshot, events and transition receipt
are committed atomically. Advances compare both base tick and digest under the shared authored
workspace lock; a stale writer changes nothing.

Replay starts from the initial seed/population and historical input 1. It checks all stored input
bindings/order, every transition's state digest and ordered events, the full persisted event set,
and final state equality. Queued but unconsumed inputs are validated too. It never substitutes
current world geometry. Historical materialization/replay still checks current authorization;
withdrawn or unavailable dependencies return unavailable rather than reviving prior geometry.

This is deterministic replay with immutable input/event/transition history and current snapshots,
not a claim that events alone reconstruct all state. Losing required input bytes prevents exact
replay and must be reported.

A read of the society, its events or its playback, and a step, load and validate only the inputs
they show or consume (`SocietyRepository._inputs`): the input the state consumed, any queued after
it, and those the events on the page name, each held to its own row's sequence and digest, after a
count confirms the stored inputs run from one with no gap. Each input was validated against the
one before it when it was recorded, the table takes no update or delete, and replay validates the
whole chain again from the first input, so nothing a read skips goes unchecked. Opening never
replays: the browser calls no replay route, and the server's reads rebuild no state.

Measured in the release build ([record](evaluation/2026-09-23-society-open-cost.json)), on a
starter world with one Marker plate and eight inhabitants whose history grew by moving the plate:
the moment a world's inhabitants are handed to the renderer, and the society and playback reads, do
not grow with the number of stored inputs (the society read's median stayed at 16 to 22 ms from 1
to 400 stored inputs, where validating every stored input took 15 to 1,094 ms). The events read
still does: it authorizes every input its page of events names (`SocietyRepository.events`), and
each authorization reads the authored version with its whole edit list
(`SocietyRuntime._authored_version`), so a page that names many inputs costs more the longer the
world's edit history (a median of 24 to 761 ms over the same range). Edits consumed in one minute
leave events naming most of those inputs; a page holds at most 256 events.

### Erasing a society

A society is erased whole, never in part: its records are bound to each other by digest (a
receipt's own digest, an event's id over its document's digest, each minute's state digest carried
by the next), so a line blanked in one of them would break every record after it.
`DELETE /world/versions/{version_id}/society` (`world.write` and `deletion.write`,
`exulanica/world/society_erasure.py`) takes the workspace's lock and writes a `society` tombstone
and a `society_erasure` row naming the society and that tombstone (migration "a society is erased
whole"). The row's trigger, a definer owned by `exulanica_definer`, withdraws the Companion's
answers that cited the society's world version, their text kept, and deletes every row that
records the society, children first: its inputs, requests, receipts, transitions and their
bindings, action requests, events, presences, choices and the answers of the people who play its
beings; its playback control and receipts; its world clock with the clock's receipts, sealed
traffic minutes and crossing occupancy; its inhabitants' appearance revisions; its asks to outside
programs with their answers and its crossings with their bindings; and the comparisons and
experiments started from it. The route answers 204, 404 `society_unavailable` for a version that
holds no society and 409 `restore_sealed` while the installation is sealed for a restore.
Afterwards every read of the society answers 404, nothing is left to replay, and the world may make
a new society, which starts at its first minute. A workspace tombstone erases every society of the
workspace the same way. Only the erasure deletes these rows: each table refuses a delete by anyone
but `exulanica_definer`. A restore carries the erasure before it replays any tombstone
(`exulanica/deletion/withdrawals.v2.json`), so a society erased after a backup is erased again.
The erasure leaves a door grant, its revisions and its program's declaration, mapping and
manifest, and the deliveries and gone notices keyed by the grant: the owner's configuration and the
things carried out, with no society text. It leaves event ids in a world project item's
references; the looks a minute recorded for visitors' arrivals (a world version's rows naming a
thing id, a crossing id and a look digest, no text, as a visitor's departure leaves them); and every
copy already sent to a hosted model provider or an outside program.

A society made again on a version after its erasure has the erased society's identity, since a
society's identity derives from its version alone. A restore from a backup taken after it was made
again holds the erasure itself, so the carried row is found present and deletes nothing, and the
society and a Companion answer given about it after the erasure stay as the backup holds them
(`tests/test_society_made_again_restore_postgres.py`).

### A living town takes in what was placed after its people came

An engine is immutable for a version's society, so a living town reads no thing placed in its
world after its people came: a knight placed there stands outside the society.
`POST /world/versions/{version_id}/society/take-in` (`world.write` and `deletion.write`, the
erasure's own pair; `take_newcomers_in` in `exulanica/api/society_making.py`) ends the version's
living society and makes a society of things on the same version, in one transaction, and answers
it as a creation does. It writes nothing of its own: the living society is erased by the erasure
above (one `society` tombstone, one `society_erasure` row, every row that records the society
deleted and the Companion's answers that cited the version withdrawn), and the society of things
is made as `POST .../society` makes one, on the engine the engine table gives the version
(`creates_holding_things`).

**The same people.** A society's identity and seed derive from its world and version alone, and a
society of things over a town is the town's own people
([a town's people](#a-towns-people-as-a-document)), so each person keeps their identity, home,
job, role and shift (`tests/test_society_take_in_postgres.py` holds each villager after to the
resident before, read from the living society's stored state and first input).

**What is not kept** is everything the erasure removes: the recorded day (every state and event, and
where each person stood); the clock's position; the playback setting (playing or paused, and its
speed); the models chosen for people; the looks a person saved for residents (their appearance
revisions, which name the society); the comparisons and experiments started from the living society;
and the Companion's answers about it. An erasure also removes whether everyone was sent away and the
requests a person directed at people, which a living town never holds (its engine takes neither).
The people's identities continue, so a look or a model can be chosen again for the same person. What
stays is the world, its version, everything placed, door grants and programs, and the world's look.
The society of things starts at its first minute. There is no way back: a society of things is not
made a living town again. Carrying the day and the clock across would need the living society's
state read into the society of things' genesis, which no engine does; the loss is this route's
behavior, stated wherever it is offered.

**Refusals,** each with nothing erased or made: 404 `society_unavailable` (the version holds no
society), 409 `society_takes_in_already` (its society is not a living one), 409
`nothing_to_take_in` (the engine table gives the version no society of things: the host offers
none, or nothing its ground admits is placed there) and 409 `restore_sealed`. A refusal of the
making is answered as a creation's (`unavailable_society_input` and the others
`society_refusal` names) and undoes the erasure with it, so the request never leaves a version
with nobody and writes no tombstone then. That is true of the request, not of a restore: a
restore from a backup taken before a take-in holds the living society, the carried erasure
deletes it again, and the society of things, made after the backup, is not in it, so the version
holds nobody until people are brought in again. The version's capability read states the route
available exactly where a request would be taken: a living society held, a society of things
given, and a first input that can be composed.

The making's place is made first, as a creation makes it, so what the first input reads is read
ahead and the asset read lock is taken in the creation's order, before the erasure's tombstone
takes that lock's shared side.

What is read before the transaction is only what a creation readies there
(`prepare_saved_world`: a site world's place, which a town has none of) and that the world is
the workspace's. Everything the request decides on is read inside the transaction, after the
workspace's lock that an edit, a playback round and an erasure take first: the held society's
engine and region, whether the engine table gives the version a society of things, and the rows
the first input is composed from.

### Versions that survive upgrades

A routine catalog is published beside the versions before it and never edited in place
(`exulanica/world/society_catalogs.py`). Schemas are keyed by catalog id and version, the directory
holds a file for every schema and no file without one, and a model reads one version of each
catalog: a society being created reads `ROUTINE_VERSIONS`, and a stored society reads the versions
it recorded, so its digest and its replay do not move when a later version is published.
`tests/test_society_versions_survive_upgrades.py` publishes a second version of a catalog beside the
first and holds a stored living society to advancing and replaying across it, and pins the digest
of every released catalog file.

A stored input names the affordance registry it was composed under by digest. The runtime keeps
every registry it composes with in its content-addressed store under that digest, and authorises a
stored input against the registry the input names, read back and held to a registry's shape, not
against the registry it holds itself (`exulanica/api/society_runtime.py`, `_recorded_registry`).
Reviewing another asset or changing the reach is a registry the stored inputs never named, and they
keep authorising; an instance whose store never held an input's registry refuses it as unavailable,
as it refuses missing asset bytes.

Every row of the registry is what the world object catalog states for one kind
(`assets/catalogs/world-objects`, `reviewed_assignment` in `exulanica/world/society_composition.py`),
under the digest the reviewed catalog generates for it. A marker's row is the six fields it has always
had, so a world of markers composes to the bytes it did before the catalog held furniture, except
for the registry's own digest, which every input records. A kind with rows of places adds the
places the catalog derives as `places_mm`, `[x, z]` in the object's own frame, each coordinate at
most `MAX_REACH_MM` (10,000 mm), the farthest reach a row may state. A kind nobody uses is an
obstacle row: its footprint and whether it blocks, and no activity, duration or reach. A recorded
registry is held to those three shapes. A reviewed asset the catalog does not state is left out of
the registry, so an instance still starts, and a placed copy of it is refused by name as
`unknown_active_asset`.

### Persisted playback controls and bounded host progression

Playback is separate from engine versions and deterministic simulation time. Migration 0059 adds
`world_society_control` and append-only `world_society_control_event`, both workspace scoped under
forced row-level security. It depends on the existing society tables and workspace guards, not
migration 0058's account tables. No stored v1/v2/v3 states, seeds, input digests or event histories
are rewritten. A missing control row means virtual paused state, revision 0. Reading, importing a
module, creating a society or configuring play never starts a worker. The API starts one when its
environment lists workspaces (`EXULANICA_SOCIETY_CONTROL_WORKSPACES`, a JSON array of workspace
ids) or opts into fresh discovery of active account-owned workspaces through the isolated account
role (`EXULANICA_SOCIETY_CONTROL_WORKER`); `docs/deployment.md` lists the settings and their
refusals. With `EXULANICA_PLAYBACK_WORKER=process` the API starts none, and
`exulanica-playback-worker` plays those workspaces in a process of its own. Account-wide discovery is off by default and refuses startup without configured
accounts and the reviewed current-input runtime. The worker asks a model only in the decision
phase before a minute of a purposeful society whose owner chose one for someone, and only for a
workspace its environment lists or, where discovery is on and spending is durable, one discovery
watches: an owner's, or a guest's while the guest is there and holds a playing place
([the host's decision phase](decision-roles-contract.md#the-hosts-decision-phase)). Each ask is
admitted against that workspace's own grant.

The authenticated base route is `/world/versions/{version_id}/society/control`:

- `GET` returns `exulanica.society-control/v1`: society/branch identity, persistence flag, revision,
  mode, speed, base interval, effective `tick_interval_ms`, simulated seconds per tick, catch-up
  cap, next due time, pause reason, lease expiry, last control event sequence, current tick and
  state digest. `interval_semantics` is `minimum_wait_after_batch_completion`;
  `last_batch_execution` is null until a completed automatic batch, then contains its event sequence,
  receipt hash, committed tick count, execution duration in whole milliseconds and completion time.
  Duration measures authorization and stepping within execution; it excludes claim/connection,
  final receipt commit and polling overhead, and is not an end-to-end delivery-rate promise.
  `play_eligible` and `play_ineligible_reason` describe engine eligibility only;
  current source authority is checked when configuring play and executing a batch.
  `host_playback` is `{running, interval_ms, reason}`: `running` is true when this instance's
  worker thread is alive and its last workspace snapshot names this workspace, whatever the saved
  mode, so a paused world reads true when Play would advance it. Where this instance leaves
  playback to a process of its own (`EXULANICA_PLAYBACK_WORKER=process`), `running` is true when a
  process holds the lock its playback configuration names and that configuration plays the
  workspace; a process whose loop hangs still holds it, so it reads true. `interval_ms` is the
  saved base divided by the speed while playing and the host's current base divided by the speed
  while paused, which is what Play adopts; `reason` is null while running and otherwise one of the
  sentences in `HOST_PLAYBACK_REFUSALS` (`exulanica/api/society_control_worker.py`), whose code is
  `host_playback_code` beside it: `guest_towns_full` for a guest's world waiting for one of the
  playing guests' worlds to stop, `workspace_not_played` for one this host does not play (a
  guest's world on a host that plays no guest's world among them). The `PUT` answer and the
  `control` inside a step answer carry it too. `model_minds_code` is `spending_cap_reached` when
  the workspace's allowance for open models is used up (its own grant, or the authority every guest
  shares): the durable spending authority would refuse the next attempt of every provider the
  workspace holds an allowance for, or its remaining USD is below the smallest reservation any of
  that provider's offered models takes (so no ask of them is made), or the society's latest
  decision receipt was refused
  `spending_limit_reached` (admission refuses once the remainder fits no attempt's reservation,
  which the spending state cannot foresee); null otherwise, and null when the spending state cannot
  be read, which leaves the rest of the read as it is; `model_minds_reason` is its sentence
  (`MODEL_MINDS_REASONS`, `exulanica/api/routes/society_control.py`). It is not a playback refusal:
  the world keeps playing, and each person whose model is refused decides by their routine, as any
  refused ask does.
- `PUT` accepts only `{base_revision, mode: "playing" | "paused", speed: 1 | 2 | 4}`. Successful
  configuration increments the control revision and cancels any pending claim. Stale revision
  returns 409. Unknown/foreign branches are indistinguishable 404s. Invalid input types are 422;
  unsupported settings or v1 play are 409. Unavailable current inputs are 424. A configuration
  that leaves the society playing sets `next_due_at` as
  [the first minute after Play](#the-first-minute-after-play) states.
- `POST /steps` accepts `{base_revision, base_tick, base_state_sha256}` and requires paused mode.
  It performs exactly one deterministic step and returns `{control, society, receipt}`. Both
  control revision and simulation tick/digest must match. First successful use persists paused
  settings; a failed step rolls back that configuration too. A v1 society is stepped by hand.
- `GET /events?limit=64` returns newest-first hash-checked scheduling receipts, capped at 128.
  These explain control changes, claimed/reclaimed leases, committed tick spans, discarded timing
  debt and failures. They are distinct from inhabitants' action/event explanations.

`POST /world/versions/{version_id}/society/steps` advances a playing or paused society by one
minute. The authenticated browser playback UI uses `/control/steps` to enforce pause-before-step
and reads the control after connection, refresh and control conflicts. It exposes play, pause,
1x/2x/4x speed and one simulated-minute advancement without deriving canonical ticks from render
frames. Control revision tracks user configuration or automatic pause, while simulation tick/digest
track progress. A normal automatic tick does not increment control revision. It uses the
simulation's compare-and-swap operation and workspace edit lock, serializing authored edits and
manual or model-decision reservations through the same domain boundary.

Speed is a playback multiplier, never a real-time claim: a simulated tick still represents 60
simulated seconds. The host default base wait is 8,000 ms; 1x/2x/4x request minimum waits of
8,000/4,000/2,000 ms after batch completion. Computation, polling and contention add time. The host
may configure a base of 1,000 to 60,000 whole milliseconds divisible by four with
`EXULANICA_SOCIETY_TICK_INTERVAL_MS`; at 60,000 ms the wait for a tick at 1x is the 60 seconds the
tick simulates. Each configuration receipt retains the chosen base; changing deployment defaults
does not silently rewrite saved controls. A subsequent user configuration adopts the host's current
base. Renderers may interpolate between committed positions, but must not fabricate future goals,
actions or positions as evidence.

How fast a walk is drawn depends on how far the tick took the person and on how long the tick is
presented: the effective wait and the reader's start lag. A renderer walks a person at their own
walking pace, and stands them where they arrive, when the tick's distance can be walked at that pace
in the presented time. A longer walk is walked evenly over the presented time, at the tick's
distance over that time, so it is drawn faster the farther the tick took the person, the higher the
speed and the shorter the base
([character representation](character-representation-contract.md#drawing-a-societys-people)).
The default was measured on saved worlds of eight people and four or eight objects on a ring 6 m
in radius (`docs/evaluation/2026-09-24-living-world-pace.json`): there a median walking minute
covers 10,045 mm, and that distance over the default's 8,000 ms is 1,256 mm/s (1.26 m/s) at 1x,
which `tests/test_living_world_pace.py` holds inside the routine policy's ordinary walking speeds.
The record names that quotient the walking pace on screen, by the rule that a path is walked over
the whole interval. It states that in those worlds a median walking minute takes about its
presented time to walk at a walking pace at 1x; it is not the speed a person is drawn at, and it
says nothing of a world whose ticks take people farther. A tick may take a person as far as the
society's recorded bound, 60 m for a new society. At the default that is 60 m in the 8 s wait and
the page's 2 s start lag, 6 m/s at 1x: a run, not a walk. With a base of 60,000 ms it is 60 m in
62 s, under 1 m/s, which a person whose own pace is 1 m/s or more walks at that pace.

A worker claims one due society per configured workspace per round, ordered by oldest due time
then stable society identity, across every world the workspace holds, which all compete for the
same claim. The claim itself names no world
(`SocietyControlRepository.claim_in_workspace`); it names the world it was taken in, and it is
executed only by a repository scoped to that world. Claims skip a workspace whose edit lock is busy. PostgreSQL
`clock_timestamp()` is authoritative; clients cannot supply deadlines. Claiming commits a random
lease token, the control revision, initiating actor and a 30-second expiry before work starts on a
fresh connection. Execution checks workspace, branch, revision, token and deadline before and after
ticks and before returning to commit. A revoked, replaced or expired claim cannot commit its batch.
At most three overdue ticks run in one transaction; a receipt records overdue/executed/skipped tick
counts, timing, speed, previous/result hashes and exact transition input ranges and event hashes.
The batch computes and writes its ticks first and then authorizes every input they read, once,
under the global asset read lock, which it holds until it commits
([asset read currency](asset-read-currency.md#society-inputs-under-the-barrier)). An input refused
there rolls the ticks back and pauses the society with `source_unavailable`, and the receipt is
the one a refusal before the ticks writes. So a withdrawal of an input made while a batch computes
is accepted, not refused busy, and that batch commits no tick. A deletion that writes a tombstone
is refused busy while the batch holds its workspace's lock
([asset read currency](asset-read-currency.md#writers-under-the-barrier)).
The next deadline is completion plus the configured wait. Excess wall-clock debt is discarded;
it is not silently replayed as unlimited offline time.

Pause uses the same workspace lock. An already executing bounded batch can finish before pause
acknowledges; after acknowledgement its previous token cannot advance again. A slow tick is not forcibly
interrupted mid-computation, but crossing the lease deadline rolls the entire batch back. Shutdown
stops new claims and lets current work reach that boundary. Unexpected exceptions roll back ticks
and leave the previously committed lease recoverable. Expiry permits replacement claims; after
three unsuccessful attempts the next recovery check persists paused `lease_recovery_limit`.
A user may resume with the new revision. A source authorization failure instead rolls back the
batch immediately and persists paused `source_unavailable`; invalid state records
`invalid_society_state`. These records claim zero committed ticks. Local unavailable affordances
under composition/v2 produce their per-action reasons and do not pause an otherwise available
district.

In a world whose clock is coupled ([world clock](world-clock-contract.md)), a society with roads
to follow commits no minute more than the clock's lead ahead of its sealed traffic: such a minute,
by a step or a playback batch, is refused `409 clock_lead_exhausted` and changes nothing, the worker
does not claim such a world, and a batch runs no more minutes than the lead allows. A presence
minute is a minute of that clock too. A configuration or a step may pin the clock's revision
(`base_clock_revision`), refused `409 stale_clock_revision` when the clock has changed.

Playback receipts reference completed engine transitions; wall timestamps and random lease tokens
are not replay inputs to the engine. Exact state replay uses the original ordered inputs, authored
edits and persisted decision receipts, including intervening input changes. It neither reads
current geometry as a substitute nor schedules new work. Control configuration and undo do not
rewind society time. Object undo and restore append an ordered authored input. Historical source
withdrawal denies historical replay even when control metadata stays readable. Stepping by hand
needs no background process.

#### The first minute after Play

A configuration that leaves a society playing (Play, or another speed while it plays) sets
`next_due_at` to one effective wait (`tick_interval_ms`) after the society's last minute was
advanced through its control, and never before the moment the configuration is saved, which is
PostgreSQL's `clock_timestamp()` then (`playing_due_at`, `exulanica/world/society_controls.py`).
The last minute's time is the one the society's newest `advanced` or `manual_step` receipt
states, whichever receipt is newer: an automatic batch's `completed_at`, which the control read
also carries as `last_batch_execution.completed_at`, or a manual step's `recorded_at`. It is read
in the transaction that saves the control, under the workspace lock a batch or a step holds until
it commits. So:

- a society whose control has advanced no minute, or whose last minute is at least a wait old,
  is due at once. The worker's next round claims it and it runs one minute, however long it stood
  paused: at a 60,000 ms base as at the default, Play is followed by a minute, not by a wait;
- a society paused and played again inside the wait after a batch is due when that wait ends:
  at an unchanged speed and base, the deadline the batch itself left;
- a society played inside the wait after a minute stepped by hand is due when that wait ends, so
  the stepped minute is presented for its whole wait before the next one begins;
- another speed while playing times the next batch from the last minute at the new wait: sooner
  when the speed rises, at once when the new wait has already passed, later when it falls.

No sequence of pausing, playing, stepping and changing speed therefore brings a batch sooner
than the chosen speed's wait after the batch or the manual step before it, so
`minimum_wait_after_batch_completion` holds across configurations and a world cannot be run
faster than its speed that way. A configuration carries no debt either: the deadline it saves is
never in the past, so the batch that follows owes one minute unless the host itself is late.
Stepping by hand stays outside the pace: a paused society is stepped as often as it is asked. A
minute advanced through `POST /world/versions/{version_id}/society/steps` writes no control
receipt and moves no deadline.

### Server integration and HTTP

The authenticated society routes (`exulanica/api/routes/society.py`) create a society, read it,
step it, list its events and replay it. Creation may name any engine the table creates with;
omission gives v1, and a retired engine is refused with
`409 society_engine_retired` before anything is written. A creation names no seed: the server
derives the world's own (above), and a body that names one is malformed (`422`). A version holds
one society: a creation for a version that already holds it reads it back with nothing composed,
and one naming another region is refused with `409 society_lives_elsewhere`. Step bodies contain
only `base_tick` and `base_state_sha256`. Extra authoritative input JSON is rejected. Every
snapshot these routes return, and the society a playback step returns, carries `seed_digest` in
place of the seed, and so does every state and event document that holds one; the first engine's
hold none.

Every society, action, playback, decision, experiment and district route requires the world as a
`world_id` query parameter, as every world route does, and a world the workspace does not hold
answers `404 unknown_reference`. The repositories scope their reads to workspace, world and version
together, so a version that does not belong to the named world reads as an unavailable version
rather than reaching another world's society.

`GET /world/versions/{id}/society?places=true` adds `places` to a society with inputs: the input
sequence and digest the current state consumed, its availability and reason, the walkable area and
clearance, the targets an inhabitant can be directed to, and each object activity the input names
as `authored_affordance_unreachable`. They are copied from that one authorised input; an input a
later edit queued is not described until a step consumes it. Without the parameter the read is
unchanged.

The application supplies `society_initial_input(connection, session, version_id, place_id, region_id,
engine)`, where `engine` is the engine the society is created with and says how a town's walking
surfaces are composed for it, and `society_input_authorizer(connection, session, document)` on
application state. The repository
accepts an `input_authorizer(document)` callback and exposes internal `record_input(version_id, doc)`
for the authored-edit transaction. The adapter must take appropriate source/asset locks and validate
current bindings. An absent authorizer/provider fails closed. The public routes report
`424 unavailable_society_input`; invalid state/replay is a `409`, malformed creation a `422`, and
stale state `409 stale_society_state`. An unknown or cross-workspace reference is a `404`.

An explicitly unavailable latest input may be authorized for recording a pause even when older
inputs have lost rights. Advance authorizes that latest input; historical state/event reads and
replay authorize what they materialize individually. That distinction allows recording withdrawal
consequences without granting permission to display withdrawn historical geometry.

The Companion answers from the same recorded goal/action/event references, labelled simulation
([society question](../exulanica/selection/society_question.py)): every citation has truth class
`simulation` and is never evidence of a personal visit, and simulated visits are never evidence of
real visits. Historical answer clauses still require personal evidence: a simulated fact is a clause
of type `simulation`, never `historical`. It answers for the purposeful profile and refuses another
by name. A `decision_applied` event records what a decision receipt did and is never one of its
lines: the person's own events say what they did, a goal their model chose by the reason
`chosen_by_their_model`, and that goal's line names the model from the one `decision_applied` event
of its minute and person that applied a choice, or names none when there is not exactly one.

## V4 living society: routines, places and occupancy

V4 is a successor profile: it changes no byte of v1, v2 or v3, whose pinned digest vectors and
replay tests hold ([retired and frozen engines](#retired-and-frozen-engines)).

**Routine as data.** Needs, activities, capacity rules, the premises use-class mapping and policy
values live in versioned catalogs under `assets/catalogs/society/`, in the city grammar's
catalog envelope, each entry with a licence and a stated reason. A society records the catalog
versions and their digest, and refuses to advance under a different digest, so a routine change
is another catalog version, published beside the one stored societies read (see "Versions that
survive upgrades"). Five needs (rest, leisure, a meal, shopping, sleep) grow each simulated
minute at their catalogued rate. Activities relieve one need each, have a duration range and an
opening window, and take place at a destination, at home, at work (a shift, which outranks every
need while due) or at any open standing spot (walking and pausing, which needs only the graph).

**The place contract.** A place hands the society `exulanica.society-place/v1` or
`exulanica.society-place/v2` (`validate_place`): an integer-millimetre navigation graph with ceil-Euclidean edge lengths,
standing spots (one person each, at distinct positions), carriageway crossings, destinations with
affordances, reviewed durations, indoor or outdoor presence, visitor, staff and resident
capacities, role, shift, address and frontage street segment, unavailable destinations, and a
sorted list of what the place cannot supply. Two producers exist:

- `place_from_society_input` projects a persisted society input exactly as it is, so v4 replay
  needs nothing beyond the stored inputs. Every graph node is one standing spot when the
  published clearance fits the catalogued standing radius, and each district or authored target
  holds one person at its access node. The input has no homes, premises, roles, street names,
  street segments or crossings, and the place says so. The Flatiron interpretation's walkable
  graph spans 32 m by 80 m of the district (93 nodes, 4 targets), so a Flatiron society holds 46
  people: half of its 93 places.
- `place_from_city_documents` holds each city grammar v2 tile document to every check the
  grammar defines, then derives a place from the records the tiles own; `place_from_city_records`
  is the same derivation over records that each pass their own shape, and the input digest covers
  only the record kinds a place is read from. A curb's footway runs beside its kerb line, the kerb
  top's width and half the footway's width away. Footways join round a block's corner only toward
  the curb a curb record names as next, following the offset corner arc to within 250 mm, so no
  path crosses a carriageway at a junction; a carriageway is crossed only on a crossing record,
  and the place's crossing keeps that record's identity and its signal. A premises unit is reached
  through the first of its entrances that opens onto a footway in the place, by a
  `premises_access` edge from the footway to the threshold. A door onto a lot is stated, and a
  unit with no door onto a footway in the place is listed as unsupported, never given one. A use
  class maps to capacities, role and shift; an unknown use class is listed as unsupported, never
  guessed. A bench seats its catalogued visitors side by side along its own direction vector,
  which runs along its seat. Every node except a corner names its street by the street record's
  identity. A street's name is presentation: `city_street_names` reads it from the city's own
  street records for a label ("a baker on Market Street"), and no name is copied into the place,
  so restyling a street never changes a society's input. Every node states the height of what it
  stands on, taken from the record it came from: a footway station stands on the footway surface
  that curb's own fields put there, a corner climbs across its arc between the two footways it
  joins, a door stands on its threshold, and a bench stands on the footway beneath it. The place
  holds each door's stated `step_height_mm` to the footway surface it derives under that door and
  states any door where the two disagree. Two footways meet at a corner only while their surfaces
  stand within one step of each other. Merging two places at one plan point into one node is
  plan-only, and the place states how many of the surfaces it merged stood at another height.
- **What a person may stand on is the city descriptor's navigation table, read as data**
  (`city_navigation`), never a list of kinds in the producer's code. A footway exists because
  `city.curb_edge` is support, and a place whose curbs are not is refused; a crossing or a door is
  walked only while its own kind is support, and a place that drops either says so. Standing spots
  keep two standing radii apart and keep the nav envelope's capsule radius (340 mm) clear of
  everything the table says obstructs: a building's base ring, and each furniture or tree part
  whose bottom is below the capsule height (1900 mm), as a box in its object's turned frame. A
  seat is clear of every obstruction but its own bench. An obstruction of a kind this producer
  does not read is stated rather than ignored. Walking lines are not routed round
  obstructions: the place counts every footway or door piece that passes within a capsule radius
  of a low part and states that count.

**Heights.** `exulanica.society-place/v2` states beside each node and spot the height of the
surface a person stands on, `support_z_mm`, in the frame's own `vertical_unit` against its stated
`datum`. `position_mm` stays two integers: `ceil_distance` zips strict, so a third component
would turn every edge length, route cost and place digest into a 3D one without a single check
complaining, and plan distance stays the walking cost. A walking edge may climb at most 180 mm,
the tallest kerb the city grammar publishes, which is also the tallest step its descriptor lets a
door's threshold stand above the footway; a crossing edge and a `premises_access` edge are exempt
because the discontinuity each carries is stated by the record that produced it, the crossing's
kerb upstand and the entrance's `step_height_mm`. A null height means there is no support surface
at that point at any height, which is what the clearance a walker keeps round a tree trunk is; it
never means the producer did not look, and a producer with no vertical data at all publishes v1.
A place may not stand a person where it states no support, so every spot and every node a
destination is reached at states a height: such a place is refused rather than snapped to the
nearest surface, because snapping is what stands a person inside a tree and reports success.
Three readers refuse rather than report what they cannot read honestly: `validate_place` refuses
that place, `measure_run` refuses a place that stands two people at two heights over one plan
point, because every measure there keys a person by their plan position, and the browser crowd
refuses an inhabitant that states a height, because it draws every walker on the ground plane. A
per-node height carries a surface and not a structure: it cannot state a step in the middle of an
edge, the floor a person indoors stands on, the fall across a footway's width or the headroom
above a walker, and it carries no level identity, so a walkway over a walkway is a v3 change.
`place_from_society_input` keeps publishing v1, because a society's state pins its place by digest
and re-deriving a stored society's place has to produce the same bytes it was created under.

**Measured on a generated street.** On the generated corridor's tile (2, 0), baked by tessellator
17 (`nav_envelope` `35388d7849`), the tile runtime's support surface carries the heights the curb
records state rather than one height for the tile. At the six walking-line points on the tile's
north-south midline the records state 123, 163, 163, 146, 146 and 96 mm, and the runtime reads each
at most 0.593 mm below, two of them exactly. Of the 284 footway stations the place states for the
tile, the runtime reads a surface at 278, none above the records and none a millimetre or more
below; the six it reads no surface at lie about 1.1 m from a bench, where the place's own
obstruction predicate already refuses the walking pieces that touch them. The records and the
runtime's reading are [walking-lines-records.log.txt](artifacts/society/walking-lines-records.log.txt)
and [walking-lines-runtime.log.txt](artifacts/society/walking-lines-runtime.log.txt), each beside the
script that wrote it. Whether a walker can walk the 40 and 50 mm steps between neighbouring curbs
was not exercised, and no test holds per-curb heights: the shared conformance fixture states one
walking-line height, 95 mm, for all six of its curbs.

**Population.** A place with homes is populated by one inhabitant per catalogued home place. A
place without homes holds the catalogued share (half) of its standing spots and indoor visitor
places, and a requested population above nine tenths of that capacity is refused. Workplace
positions go to inhabitants in seeded order. A role exists only where premises supply it; an
inhabitant without one records the reason. No state field names a person: presentation is a role
in a place, and names, if ever shown, belong to world style.

**No inhabitant may be given a workplace it cannot walk to from where it lives**, and a place
that would do so is refused at creation, naming how many pieces its walking graph is in and how
many of its inhabitants are stranded. The rule is about the assignment and never about the
graph's shape: a place may honestly be in pieces, an island is a place, and so is one tile cut
out of a city whose joining corners lie outside it, which such a place already states in its own
`unsupported`. What a society may not do is hand somebody a job across a cut and say nothing: a
shift with no reachable target would be stepped over in silence while every run measurement
reported a healthy society. `_targets` says which shortage emptied its list, because nothing here
offers it, the places that do are full and no route reaches them are three findings with three
fixes; no v4 transition consumes that reason, because a goal's `because` is canonical state and a
change to a v4 transition is a new profile.

**What a run reports.** Beside the population's own measurements, `measure_run` states what the
place OFFERED: how many destinations it publishes, which needs its inhabitants can hold at all,
and the place's own `unsupported` list, each read from the place rather than from the run, so
that a place with nothing in it reports its emptiness instead of reporting zero of nothing. A
place with nothing in it is legitimate and so is a society over one, which is why this reports
and does not refuse; what neither should do is read as a busy street. One corridor tile publishes
no destinations at all for ninety-nine inhabitants whose only modelled need is somewhere to walk,
and they score perfectly on every other measure: they never collide, never exceed a capacity
there is none of, and occupy as many distinct positions as there are people.

**Choice and occupancy.** Each minute every need grows. An inhabitant with nothing in progress
takes the most pressing reachable activity that has room: weighted need above its threshold, or
a due shift, with a seeded per-inhabitant weight spread of a tenth. When nothing is pressing it
takes the best available activity anyway, and walking to another open spot is always available.
Reservations are taken in inhabitant order within the minute: a standing spot holds one person,
an indoor destination holds its visitor capacity, and homes and workplace positions belong to
their inhabitants. An inhabitant never chooses the spot or destination it is already at, a
finished activity lowers its need by the catalogued relief, and a population never exceeds its
place's capacity. Together these rule out the absorbing state the v2 routine reaches over the
Flatiron input, where every inhabitant prefers the one visit target forever: no two stationary
people share a position, and an outdoor inhabitant moves again within a bounded number of minutes.

**Motion.** Each inhabitant walks at its own seeded speed of 66 to 84 m per simulated minute
along shortest graph routes, from spot to access node, along edges and onto its target spot; the
edges are walked by the walking movement module, as the purposeful society's are. An
indoor activity places the person at the premises' access node with `indoors: true`. Positions
are always on the graph or on a spot, so v4 needs no position bound. `motion_path_mm` records
every point passed in the minute. Weather and resources are recorded as unavailable with a reason.

**Events.** V4 emits `goal_selected`, `route_progressed`, `action_completed`, `replanned` and
`blocked` with the v2 envelope, plus the minute of day, the place digest, the inhabitant's needs
and, for each carriageway crossing entered, `{crossing_id, arrival_second, duration_seconds}`
from its recorded motion and speed. Summaries are templates naming the role or "a person".

**Persistence.** Migration 0075 admits v4 in the engine-version check, allows v4 populations of
1 to 65,536 while keeping 100 to 512 for earlier profiles, and extends the versioned event order
index and the input and event binding triggers. V4 uses the same input, event and transition
tables, playback controls and replay as v2, and takes no typed user actions or model decisions.

**Drawing.** The app draws a living society's people as it draws every society's, from their
recorded paths and actions
([drawing a society's people](character-representation-contract.md#drawing-a-societys-people)).
The development preview plays a recording made by the real engine over the committed Flatiron
input (`scripts/record_living_society.py`), with every frame bound to its state digest.

## The living town (v5)

The living town is the living engine (`exulanica/world/society_living.py`) over a saved world whose
own records state its walking surfaces and homes: a town generated from a recipe. The engine table
creates it over such a world (`creates.town`); a starter or a world made from photographs keeps the
purposeful society, and a creation that asks for the living town over a ground that carries no
homes is refused by name. A town whose society was created before the living town existed keeps
that v2 society: an engine is immutable for a version's society.

**Its input carries its place.** A town's input is `exulanica.society-input/walking-surfaces-v2`
(migration 0120): the walking-surfaces-v1 input and, beside it, the living place the town's records
make under the town's routine, with that routine's catalog versions and digest. The place is the
city place the input already names among its dependencies, by digest; the living town walks it in
the input's east and south frame (`place_from_town_input` in `exulanica/world/society_place.py`),
so its people walk the town's footways, corners, crossings and doors across tile seams, and its
society replays from its stored inputs, the catalog versions its state records and its stored
receipts, with nothing regenerated and no model asked. Standing spots within the 2,000 mm arrival
clearance of where a person arrives are left out of the place, so nobody stands in front of a
person arriving at any hour; a bench's seats there stay seats. On the largest market town a
recipe admits (92 residents in the measured run below), one input is 829,953 bytes of JSON; the
runtime writes one when the society is created and one for each edit of the world that changes
what the society reads.

A world made from a world kind is lived in the same way and by the same engine. Its input is
walking-surfaces-v2 with the navigation profile `site-walking-surfaces/v1`: the place the site's
records make, named among its dependencies under the kind its ground states (`site_place`, where
a town's states `city_place`; ground catalog version 4's `place_dependency`, with the record kinds
its activities may name, `record_subjects`), and the
town's routine binding with the kind's overlay, `exulanica.routine-overlay/v1`, which adds the
kind's own use classes and employment share and is named by its own digest. The
[world kinds contract](world-kinds-contract.md#people-in-a-site-world) owns the site place and
the overlay.

**Its day is data.** The town's routine (`TOWN_ROUTINE_VERSIONS` in
`exulanica/world/society_catalogs.py`) reads the living routine's needs, activities and
capacities with three catalogs of its own under `assets/catalogs/society/`, each entry with its
reason: `society-use-class` v3, which states each use class's opening hours, the shifts its
positions work in turn and, for a home, the floor area one dwelling takes; `society-shift` v1,
the early, day, late and evening shifts; and `society-policy` v3, which employs six in ten
residents, starts the town's day at 06:00 and states how many people a new town starts with.

**Its homes follow its floor.** A premises of homes holds one dwelling for each
`dwelling_floor_area_mm2` of the floor its premises record states (`floor_area_mm2`: the storeys
it takes, walls and shared stairs included), at least one, and a dwelling houses the use class's
`resident_capacity`. The residential entry states 50 m2 a dwelling and two residents, a default
with its source in the entry's reason (the nationally described space standard's minimum for a
one bedroom, two person, one storey dwelling, Open Government Licence v3.0), replaceable by a
world's own value and never a census claim; a storey more is homes more. How many of those
places are lived in is a chosen budget, not a limit: `town_people_default` (128, the crowd the
page's frame budget was measured with) is how many people a new town starts with, never more
than its homes hold, spread over the premises in proportion to the people each holds, by largest
remainder with ties in premises order (`_people_living` in
`exulanica/world/society_city_place.py`). The place states the result as each home's
`resident_capacity`, the people who live there, which is what both engines and
[the people's frame](#a-towns-people-as-a-document) read, so one inhabitant lives in each place
in a home that is lived in. On the shipped small town's preset the homes hold 628 people and on
the market town's 1,162 where each housed two a premises before; both start with 128
(`tests/test_town_homes_by_floor_area.py` holds each home to its record's floor, worked from the
catalogs' own figures). The ground's figure of 128 still refuses a larger town when it is
composed.

**A town keeps the routine it was made under.** A town's receipt pins the routine it was
composed under (`arrival_routine`), and a society new to that town is made under the pinned one
(`town_routine_of` in `exulanica/world/society_living.py`), whatever a new town is made under
today: the living town's place and a society of things' people frame are both made under it. A
town made under `society-use-class` v2 and `society-policy` v2
(`TOWN_ROUTINE_VERSIONS_BEFORE_FLOOR_AREA`) keeps two residents a premises and the people it
would have had, composes to the bytes it did, and a receipt from before receipts pinned a
routine names those versions. A society already held keeps the routine its own inputs record.
An arrival world is not a stored town a guest inherits: each guest's copy is composed in their own
workspace when they enter, so a new copy is a new town made under the routine a new town is made
under, with that routine's people, while a copy a workspace already holds keeps its receipt and its
people. The new copy is the same town to the eye and to the bake: the same seed and candidate, the
same records and the same input digest for every tile (`tests/test_town_homes_by_floor_area.py`,
for every entry of the arrival catalog), so no tile is baked again.

**Who works.** A seeded share of the residents takes
the town's positions workplace-first: every workplace gets one worker, in a seeded order, before
any gets a second, and each position works the shift its use class names for it. The rest keep
no job. A premises admits visitors inside its opening hours and only while one of its workers is
at work there, so a shop is open while it is staffed and a workplace nobody works at stays
closed. Every use class the city grammar can give a premises (`assets/catalogs/use-class.v1.json`)
states its hours (`tests/test_society_living_town.py`).

**It opens awake.** A living town's society is born at the start of its day with everyone at home
for 1 to 45 minutes, so its first minutes show an empty street. Where a society is made
(`make_society` in `exulanica/api/society_making.py`, which the society route and an installation's
arrival worlds both go through), the server therefore advances it at once, minute by ordinary
minute, until it is awake (`open_awake` in `exulanica/api/society_opening.py`). Each of those
minutes is the repository's own `advance`, the call the steps route makes: stored with its events,
replayed like any other, decided by the routine alone since no model is asked, and written without
a playback receipt, so a control set playing afterwards has its next minute due at once. A society
read back because its version already holds one is never advanced again, and a creation is never
undone by a minute refused afterwards: the society stands wherever it reached. A caller that makes
a society inside a transaction of its own (a living town taking newcomers in, under the workspace
lock) makes it unopened and opens it once that transaction is committed (`open_made`), so no
minute is advanced under its locks.

What awake means is read from the state. A state that says for every person whether they are
indoors (a living town) is advanced until a stated share of its people is outdoors, whatever
engine keeps it. A state that does not, but says for every being what it is doing, is advanced
until a stated share of its beings is doing something, an action whose kind is not `idle`, where
the policy states that share for the family of state its engine keeps. Version 2 of the policy
states it for a society of things, whose beings are always out on the walking graph and are born
idle with no goal: on a dressed arrival town stepped with no model asked, every being was idle at
minute 0 and all but one were not at minute 1, at 42 beings and at 130, so such a society opens
after one minute, which took 0.4 s at 42 beings and 2.6 s at 130 on a busy development machine.
In that minute a being a scene placed acts by the routine like anyone else, and may walk. A
purposeful society (a site world's) is born idle too, and is left at its first minute: its first
minutes are not measured. A place whose people already stand outdoors, or are already doing
something, is advanced by nothing.

The rule is data, `exulanica/world/society-opening-policy.v2.json`: the outdoors share (150
thousandths), the share doing something (500 thousandths) and the state families it is read for,
the least minutes (10), the most minutes (60) and the most seconds inside the request (5), each a
chosen budget with its reason, and a default of on. Version 1 of the file, which states the
outdoors share, the most minutes and the most seconds alone, stays beside it and is read by the
same loader. On two towns made from a sentence (48 and 52 people) nobody was outdoors for the first
4 minutes, 15 percent was first reached at minutes 14 and 17, and the ten minutes after held 8.1
and 8.6 people outdoors with 3.0 and 2.6 walking. The seconds are the server's clock, so a busy
host would open a town less awake than a quiet one (a town opened under a load average of 280 was
cut at minute 6 with nobody outdoors): the least minutes are advanced before the seconds are
counted, unless the share is reached first. A host changes the rule with
`EXULANICA_SOCIETY_OPENING` (`off`, `on`, or `share:minutes:seconds`, which may go on
`:least-minutes` and `:active-share`; three numbers state the seconds as the whole wait, a least
of 0); a hand-built `Services` opens nothing. What a town of 500 costs to open is not measured:
past the least minutes the seconds budget bounds it, and such a town opens partly awake
(`tests/test_society_opening.py`, `tests/test_society_opening_postgres.py`,
`tests/test_society_take_in_postgres.py`).

**A model its owner chose decides for a person** through the person role as registered
([decision roles](decision-roles-contract.md)): at the engine's own choice point, when nothing is
under way for them, the host asks the chosen model to choose among the engine's own answer set for
that person in the coming minute, one option for each activity the rule could start at the target
the rule itself picks, and waiting a minute (`exulanica/world/society_living_decisions.py`). The
minute applies the stored receipt through the engine's choice seam
(`AppliedChoices` in `exulanica/world/society_choice.py`): the people a model decided for act
first, in decision order, each taking what their model chose where their turn still offers it;
otherwise the rule decides for them and the receipt is recorded as rejected, with the reason. A
minute with no receipt is the rule's alone. A comparison of models replays the living town from
its frozen input and runs each arm through `living_step` and `LivingSeam`, scoring the supported
needs and performed activities under the fourth person score
([comparisons of models](society-experiments.md#comparisons-of-models)).

It takes no directed actions, its people are not sent away, and it runs no experiments.

**What a minute costs.** Measured with `scripts/measure_living_town.py` (market town preset at its
largest values, eight identities) on a quiet development machine (one-minute load under 8), on the
largest town it made, 92 residents on 935 walking nodes: a minute of the engine took 4.6 ms at the
median and 8.6 ms at the 95th percentile over a whole simulated day, where the district's rule
over the same town took 3.7 and 7.2 ms; with the town's homes holding the ground's bound of 128
people, 8.3 and 13.0 ms over four simulated hours; and replaying an hour from genesis, the work a
replay of an hour does, took 0.50 s at 92 people and 0.65 s at 128. A stored minute through the
steps route, which also reads, validates and authorizes the town's input and writes the minute,
took 93 ms at the median and 101 ms at the 95th percentile on the same machine (a 62-person
market town, 30 minutes, the acceptance launcher's production stack). While that town played at
the fastest cadence (1,000 ms base interval, speed 4), the API's health check took 17.3 ms at the
95th percentile, where it took 7.3 ms with the town paused: the society host shares the API
process.

## A town's people as a document

Who a town's residents are is data of the town, whichever engine its society runs.
`exulanica.town-people/v1` (`exulanica/world/town_people.py`) states it and nothing an engine
keeps for itself: each resident by ordinal with their home and household, their job or none (the
premises, the position, and the shift that position works with the person's own start), their
role by key and label, and why they hold that job or none (`works_at_premises`, `keeps_no_job`,
`no_open_position`, or `lives_at_premises` where the place offers no position at all). It names no
person: a name belongs to the world's style.

A home or a workplace is named by the subject its place states for it
(`city.premises:<identity>`, or `site.structure:<identity>` for a site's structure), never by an
engine's destination or target id, and each premises a person may live or work at is described
once: its use class, label and address number, the node its door stands at, the places in a home
it offers and its positions with the shift each works. A reader therefore says "the bakery at
number 12" from the document alone.

The document names the rule that made it, the routine it was made under by its binding (catalog
versions, digest and any overlay), the place it was made over by id and digest, and the minute
its day starts at. It holds the outcomes of the seed's draws and never the seed, and is canonical
JSON named by `document_sha256`, the SHA-256 of every other key. Its origin is `derived`: made by
a rule from the town's records and a seed. Its profile grows only by optional fields.

`exulanica.town-people-rule/v1` is the living town's assignment, draw for draw: one resident in
each place in a home that is lived in, in premises order, a seeded order of the residents cut to
the routine's employment share taking the positions workplace-first, each position working the
shift its use class names for it in turn. `tests/test_town_people.py` holds every person of the
document to the person the living town's genesis makes over shipped towns, seeds and populations,
and works a town of six from the catalogs and the draws alone. `validate_town_people` refuses, as
`malformed_people`, a document whose keys are not exactly the profile's, whose people or premises
are out of order, that houses more people in a home than it has places, that gives two people one
position or a person another position's shift, or whose digest does not name it.

**What an input carries is the frame.** `exulanica.town-people-frame/v1` (`people_frame`) is what
a town's people are made from before any draw: the rule's name, the routine binding, the place by
id and digest, the minute the day starts at, the two policy figures the rule reads (the share who
work, or none, and the shift jitter), how many of the homes' places are lived in, and every
premises that offers a place in a home or a position, in the place's destination order, each with
its destination id, the role its people take and the fields above. It holds no seed and nothing
drawn from one, so it is composed again and compared like every other part of an input.
`people_from_frame` completes a frame with a society's seed into the document, reading no catalog
and no place: a society whose first input carries a frame makes, and replays, the same people from
that input and its own seed whatever is published later. A frame names its rule by version; a
later rule is another name beside it, so a stored society never draws its people again under
another rule. `town_people` is the two together.

**Who reads it.** A society of things over a town carries the frame in its first input and is
the town's people (below, "On a town's ground"). The living town makes the same people at its
genesis and reads no frame: `tests/test_society_things_town_people.py` holds every villager of a
society of things to the resident the living town's genesis makes for the same place, seed and
society, by home, job, shift, role and reason, with one identity in either engine. `resident_of`
reads who a person of either engine's state is in their town the same way: their role by key and
label, whether they work, their shift, and their home and job as the engine keeps them (a society
of things by subject, with what each premises is called; a living town by the place's destination
id); it answers nothing for a being its author placed, a visitor, or a person of a world with no
homes.

## The society of things (v7)

The society of things (`exulanica/world/society_things.py`) is the purposeful society where
everybody is a thing of a stated kind ([things contract](things-contract.md)). A society is made
with it by name over a saved world's own lattice ground, a starter, a world made from photographs or
a generated town (`creates` does not name it, so a new world's society stays v2 unless asked for); a
world made from a world kind is lived in by the living society only, and refuses it. The route makes
one only on a host that sets `EXULANICA_SOCIETY_OF_THINGS` on, and refuses it by name elsewhere
(`society_engine_not_offered`). Its people walk, choose, stay and talk by the purposeful planner's
rules, use their hands where a decider chooses or the world's owner asks (below), and follow
another being where a person playing one chooses to (below); a person may play one of them
([decision roles](decision-roles-contract.md#a-person-playing-a-being)).
Each of them names its kind by key, version and digest (a being of a kind its workspace keeps,
by that kind's digest alone: below), and how it came: `populated` (the
people its ground's population brings, the purposeful genesis's own people with the same names and
draws, of the kind the ground's catalog entry names, `population_kind`), `placed` (a being the
world's author placed in the version) or `crossed` (a visitor from an outside program). At genesis
the author's beings are seated first, each at the open node nearest where it was placed, and only
then does anybody of the population whose starting node one took step to the open node nearest it,
so a composed scene holds from its first minute.

**Its input carries the things its author placed.** It reads
`exulanica.society-input/authored-ground-v5` (migration 0151): the fourth profile's projection, at
the opening source its version pins or, where the ground states its own arrival, none, and a
`things` list: every thing placed in the region and not removed, in id order, each with its kind's
semantics (the kind document without its looks, origin, summary and `ext`), its position and yaw
on the ground, its height above the ground where it does not rest on it, and, for a gate, the point
visitors arrive at, turned with it; and the kind its population is made of, as the ground's
catalog entry names it, so genesis and replay read it from the input. A placed object whose kind
blocks walking is an obstacle, its box turned with it; one whose kind makes an offer with places
that a purposeful ability serves (the abilities catalog: `rest` serves `rest_at` and `visit`
serves `visit`) offers that activity at its kind's places, as a target of origin `thing`
(`thing:<placed id>`), under the routine's entry for its kind; one off the ground offers none and
still blocks. A placed thing's places and obstacle are named after `thing/`, a separator no
authored object's id can hold, so they never meet an authored object's. Every placed thing is a
`placed_thing` dependency and each kind a `thing_kind` dependency by digest; a thing whose kind is
not shipped at the digest it names makes the input unavailable (`unknown_thing_kind:<placed id>`). A society's inputs keep its arrival
for its whole life and may move on to a later things composition, never back.

**A being of a kind its workspace keeps.** A thing placed by a kind its workspace keeps (a creature
drafted from a person's words, [things contract](things-contract.md#a-creature-in-a-society)) is a
being of the society like any other. Its entry in `things` states `kind` as the reference
`{"source": "workspace", "sha256"}` alone, and the input states that kind's run form once, under
`kinds`, by the same digest, in digest order: what the society runs of it (its abilities, offers,
deciders, routine weights, what it moves by, its body's figures and sockets) and its label and
summary, which are built from those figures and hold no word a person wrote. `kinds` is stated only
where the region holds such a thing, so every other input keeps its bytes, and each kind is a
`made_thing_kind` dependency named by its digest. The state names the being's kind by the same
reference and keeps the run forms of exactly the made kinds somebody here is of (`kinds`, stated
only while one is here), as the state took each when its first being came. Events, heard lines and
recollections name such a kind by that reference too. Everything that reads what a kind is reads
it through one function (`kind_here` in `exulanica/world/society_kinds.py`): a shipped kind from
the shipped library, at its digest, and a made kind from the run forms the record at hand carries;
a made reference whose run form the record no longer states (a line heard from a creature erased
since) reads as a kind that can do nothing, named by the body names catalog's noun. So a society
replays from its inputs alone, and its history holds nothing an erasure of the creature has to
remove. A placed thing whose kind its workspace no longer holds is left out of `things`, and the
input names it under `things_gone` (placed ids, each the shape of one, in order, none of them a
thing it lists; by thing,
since one placed before an erasure stays gone though the same creature is kept again and another
thing of that kind lives): a being that was one of them leaves in the things phase of the
society's next minute (`thing_departed`, `kind_erased`), putting down what it holds, as a being
its author removes does. Code from before
these fields refuses an input carrying one, so a society that has taken such a being in cannot be
read by an older release.

**The modules it runs.** A society's first input records the ability modules it runs, by version
(`modules`: sorted, each once, each a built row of
[`ability-modules.v1.json`](../exulanica/abilities/ability-modules.v1.json)), and its minutes run
exactly those for its whole life, whatever a later table adds; no later input states them. A new
society records every built module at its newest version: today purposeful
(`exulanica-ability/purposeful/v2`, below), say, crossing, hands (`exulanica-ability/hands/v2`,
below), notice (`exulanica-ability/notice/v1`) and memory (`exulanica-ability/remember/v1`), the
last two as the [minds contract](minds-contract.md) states.
A society whose first input names none, made before modules were
recorded, runs purposeful, say and crossing (`BEFORE_RECORDED`), so its people never use their
hands and its things never move, and records every minute as it did then: a line's event and its
hearers keep no model and no speaker's name, and nobody keeps what it said. Its stored minutes
replay byte for byte (`tests/test_society_things_before_modules.py`, a history recorded before
modules were).

**The routine held to each kind.** Under the purposeful module's second version
(`exulanica-ability/purposeful/v2`), a being does only the routine's activities its kind lists. The
routine never sets out for it to rest, visit, stand or talk where its kind does not list that
activity, and the options its decider is asked with leave the same out. A talk takes two beings
whose kinds both list talk, so a villager never stops to talk with a lantern spirit. A request
sending a being to an activity its kind does not list is refused `activity_not_offered`. Waiting is
everybody's: a being whose kind lists none of the four, as a lantern spirit's does, waits where it
is (`nothing_its_kind_does`) and does what its decider chooses of its other abilities, walking where
one needs it, as to a thing out of reach it chose to pick up. Only resting relieves tiredness, so a
being whose kind does not list rest is never tired: its need is 0 from the minute it comes and stays
so, and a visitor, whose kind talks but does not rest, stays free to talk. A society that recorded
the first version runs it for its whole life, every being doing all five as before, and its stored
minutes replay byte for byte (`tests/test_society_kind_gates.py`, a history the code before the
second version recorded, a spirit resting, standing, visiting and talking in it).

**On a town's ground.** A society of things over a generated town reads
`exulanica.society-input/walking-surfaces-v3` (migration 0169): the town's walking-surfaces-v1
input, its surfaces, premises and furniture, its residents and the purposeful routine, with the same
`things` list and `population_kind` (the town's catalog entry names the villager), and, in a
society's first input, the `modules` it runs and `people`, what the town's people are made from
(the frame of [a town's people](#a-towns-people-as-a-document), made over the town's place under
the routine a living town is made under, as many as the input's population). At genesis the
society completes the frame with its seed: each of the ground's population states `resident`,
who they are in the town (`home`, a premises with its household, and `job`, or null, a premises
with its position and shift; `role` by key and label; and `reason`), and takes that role's label
as their role's word, so a town's villager is "baker" because they work at its bakery; the state
records the document those people are (`people`: its profile, its rule, its digest, a record from
which nothing is ever drawn, and `premises`, what each premises of the document is called, once:
its subject, use class, label and address number, in the document's order). A resident names a
premises by its place in that list, so the state says what a premises is called once however
many live or work there. A resident keeps their name, their kind and everything a villager does:
who they are changes no choice the routine makes. A being its author placed and a visitor state
no `resident`.
The key is optional and a first input's alone: an input composed before it, and every later
input, states none, a society whose first input states none draws each villager's role word as
before, and its stored minutes replay byte for byte
(`tests/test_society_things_town_people.py`, digests read from a tree before the key). Code from
before the key refuses an input carrying it, so a society that has consumed one cannot be read by
an older release. A lattice ground's things input carries no people. A town's footways stand on its kerbs, above the
ground's plane, so a thing rests on the surface when it stands within 200 mm (`RESTS_ON_SURFACE_MM`)
of the height of the walking line nearest it, read along the town's own edges between their ends'
support heights; one that does not states its `height_mm` above that line, offers nothing
(`authored_object_off_ground`) and still blocks. A placed object whose kind blocks walking removes
every walking-line node within the walking clearance of its box turned with it, and cuts every line
that passes within that clearance: from each end that stays, the line keeps the part a person walks
clear of the thing, ending at a node of its own (`cut:`); a premises or a seat left with no node to
stand at, no place, or only places no longer reached from the rest of the town (a thing cut the
short way to them from both ends) is recorded `authored_affordance_unreachable`. An object whose
kind offers somewhere to rest or to visit offers it at its kind's places, turned with it. A place is
kept where it stands clear of every thing and of the town's own buildings, street furniture and
trees (the obstructions the town's place stands its spots clear of), a standing spacing from every
place the town still offers and every place kept before it, and not exactly on a node already there.
A step keeps a walking clearance from every other thing and the town's obstructions, and at least a
standing radius from its own thing. Each line offers its one nearest point to the place, within 4 m
(`PLACE_JOIN_REACH_MM`, the footway station spacing), and the nearest offered point a step reaches
is the join; where none is, the place steps first to a corner of its thing's box pushed out a
standing radius along both faces (`round:`) and from there to the nearest point a line offers that
corner, the shortest such way kept. A join at an end of a line is that end; any other point splits
the line at a node of its own (`join:`), or at the place itself where the place stands on the line.
Targets, subjects and places are named as on the authored ground. A premises' or a bench's target
also says what the town's place calls it, `place`: its use class, label (or null) and address number
(or null), copied from the place's destination, for the page to name it ("the bakery at number 12");
a thing's target carries none. The field is optional: an input composed before it, stored since the
town ground landed, reads as before, and the page then says only "a place". A name never moves a
destination: a person heading to a premises when the first input naming it arrives keeps their
target and route. Code from before the field refuses an input carrying it, so a society that has
consumed one cannot be read by an older release. A being neither blocks nor offers: it lives in the
society. The dependencies and the unknown-kind refusal are v5's. A town with nothing placed in it
composes v1's surfaces and targets, and a town's v1 and v2 inputs do not change. A town states its
arrival (its spawn, `navigation.arrival_mm`), so a v3 input pins no `arrival` of its own; a visitor
crosses in through a gate placed on the town, at the open node nearest the gate's arrival point. A
society of things reads only things inputs, and no other society reads one.

**What a crowded town costs.** Measured on a market town (970 place nodes) with 256 placed things,
each standing on a footway station, on commit b9030943 with the planner described here, on
2026-10-09, on an otherwise quiet machine (at least 81 percent CPU idle), 60 minutes of each: with
256 blocking wells and 96 people a minute took 53 ms at the median (70 ms at the 95th percentile),
of which the purposeful planner took 46 ms and the things phase 7 ms; with 128 wells and 128 placed
beings, 224 people, a minute took 65 ms at the median (86 ms at the 95th percentile), of which the
purposeful planner took 54 ms and the things phase 11 ms. Both are within the 200 ms tick budget at
the 95th percentile. The planner builds what depends on the minute's input alone once a minute, not
once for each person who plans a route: the digest of the navigation that every route records, the
walking graph, routes, and the standing exclusions, for which each node is held only to the places
within a standing spacing of it. On commit b9030943 itself, without that, the same minutes, state
for state and event for event, took 294 ms and 384 ms at the median (the planner 287 ms and 373 ms),
both over the budget. The planner is still most of a minute (85 and 83 percent), on walking graphs
that cut lines and joined places enlarge (2,003 and 1,523 nodes). Not measured: the judges' small
town (616 place nodes, 40 residents and six things in the town scene) is far smaller, so it is
expected, not shown, to stay well inside the budget. No cap on placed things or beings applies to a
town.

**A minute.** The planner's minute, the person's direct requests and the people's decisions come
first, unchanged, and every event they record names v7; then the things phase:

* placed beings follow the latest input: one an edit places arrives at the open node nearest where
  it was placed (`thing_arrived`, `placed_by_author`), one an edit moves is put where the edit says
  (`thing_moved`, `moved_by_author`), one an edit removes or replaces leaves (`thing_departed`,
  `removed_by_author`), and one whose kind its workspace erased leaves for that reason
  (`kind_erased`); one that cannot be placed is refused once while its placement stands
  (`arrival_refused`: `no_place_to_stand`, or `id_taken` where somebody or something here already
  has the id it would have) and tried again when it is moved; one refused because the society is
  full (`society_full`) is tried again every minute, silently, and comes when there is room; an
  unavailable input changes nobody;
* the crossings a door handed over, in the order it wrote them: a visitor arrives at the open node
  nearest a gate's arrival point, holding what it carried in, and leaves when its program calls it
  back (`sent_home`) or its grant ends (`grant_ended`), taking what it holds (in a society running
  hands, what it brought: things that move, below). An arrival is refused
  by name where the version holds no gate to arrive through or not the one named
  (`no_arrival_place`), the society holds 16 visitors already (`visitor_limit`), its kind is not
  a shipped being an outside program may decide for, or what it carries not a shipped holdable
  object (`unknown_kind`), or its id or the id of a thing it carries is already somebody's or
  something's here (`already_here`); a departure naming nobody who crossed in is
  `departure_refused`, `not_here`. A crossing whose document fails its check is refused
  (`malformed_crossing`), with an event naming the crossing and nothing from the document, so no
  crossing ever stops a society's minutes;
* what the minute's decisions do beside the planner's goals, in decision order: a line a decider
  chose to say is said (`said`, `chose_to_say`), with the request it answered, the model that
  request asked where a model decided it (`model`, in a society that records its modules), the line, whom it was said to, or none for
  everyone near, the speaker and that one each by kind and number as the minute began (so the event
  alone names both), the decider kind (a model or an outside program) and who heard it: every being
  within the hearing reach of the society of things' contract (8 m) of where the speaker stood as
  the minute began, whose kind offers hearing and who is still here; each hearer keeps it among the
  last lines it heard (at most the contract's `lines_heard_maximum`, the oldest dropped first), with
  when, who said it by kind and number, and to whom. How far a line carries and how many a being
  keeps are read from the contract a society of things' lines were first said under (version 3 of
  the person's catalogs, `LINES_CONTRACT`), never from whatever terms the registry states later, so
  every stored minute replays as it ran. A visitor that chose to leave departs (`thing_departed`,
  `chose_to_leave`), taking what it carries home as every departing visitor does. A visitor whose
  program had no live connection, gave no answer in time, whose grant was revoked or has expired, or
  that was not asked because a name the account holder saved is among the words its request would
  send (`saved_name_withheld`), counts that minute as quiet, and any other answer or a pass ends the
  count; one quiet for as many minutes
  in a row as its kind's leave ability waits (a visitor of `visitor` version 1: five) departs
  (`thing_departed`, `decider_lost`), taking what it carries home to the program that sent it. A
  program's answer refused for its line (`line_out_of_bounds`) is an answer, never a quiet minute;
* where the society runs the hands module, what each being's hands do, in the order of the beings'
  numbers. A hands act a decider chose or the world's owner asked for by a direct request (picking
  a thing up, putting it down, giving it to a being, taking it from one) is done in the minute the being stands within the module's reach (1,500 mm)
  of the thing, or within the hand-over distance of the other being: the reach, or the walking
  graph's longest step between two joined nodes where that is farther (2,000 mm on the lattice), so
  beings on neighbouring nodes can always hand over. A thing picked up or taken goes into the
  actor's free socket that fits it, one given into the other being's, and one put down rests where
  the actor stands. Each is recorded (`picked_up`, `put_down`, `gave`, `took`, reason
  `chose_to_<ability>`, or `asked_to_<ability>` for an act asked for) naming the thing, the other
  being and the socket. An act is dropped
  (`hands_missed`) when the thing or the other being is gone (`thing_gone`) or the module's three
  minutes of walking pass first (`out_of_reach`). A hands act takes no line, and the routine never
  chooses one;
* where the society runs the follow module (`exulanica-ability/follow/v2`, every society of things
  made since it was built), who follows whom, in the order of the beings' numbers, over where the
  minute's walks ended. A being whose decider chose to follow another (offered where its kind
  lists follow, toward a being within hearing reach whose kind offers `be_followed`) begins to
  (`followed`, `chose_to_follow`, naming the other by kind and number; one following somebody else
  first stops, `chose_otherwise`), and its state says whom it follows and since when. It follows
  while its decider chooses each minute to go on, as a person playing it does (a minute with no
  answer carries on; carrying on is offered at its choice point too while it follows). It stops
  (`stopped_following`) when its decider chooses to stop (`chose_to_stop_following`) or anything but
  going on or saying something (`chose_otherwise`), in a minute nobody decides for it, as when it is
  given back to its routine (`not_kept`), when the one it follows is not here (`target_gone`), or
  after the module's three minutes in a row ending more than its 2,000 mm off with no open node
  within that distance (`lost_target`). Before the planner moves anybody, each
  follower that a direct request or another choice did not take that minute is given its walk
  from where everybody stood as the minute began: within the 2,000 mm it waits where it stands
  when nothing is under way, and farther off it stands at the open node within that distance
  nearest itself, a stand under way ending for the walk as a request ends a stay. Only a person
  playing a being is offered following (the seventh action and policy catalogs,
  [decision roles](decision-roles-contract.md#a-person-playing-a-being)); the routine never follows;
* where the society runs the memory module, last: the minute's events, in the order it recorded
  them, are written into the memory of each being a model or a program decides for (one a receipt
  the minute consumed names, or a visitor its own program decides for, from that minute on), as
  the [minds contract](minds-contract.md) states. Nothing is recorded for it: a being's memory is
  part of the state, so it replays with the minute.

Each event of the things phase carries `at_ms` 0: it takes effect as the minute begins (`at_ms`
is the moment within the minute, 0 to 59,999). A hands act done after a walk is the exception: it
names the moment the later of its parties' walks ended, the length walked over the society's
recorded pace, and 0 where both stood within reach as the minute began. A minute with nothing to reconcile and no crossing
records the planner's events alone, the same documents a purposeful society records but for the
engine they name.

**Crossings.** A door fills the port `CrossingStream` (`exulanica/world/crossings.py`): the
crossings no minute has consumed, at most 32 a minute in the order the door wrote them (the rest
wait for later minutes), read on the minute's connection under the society's lock; each bound once
to the event its minute recorded, after the minute's events are written; and every bound crossing
with its minute, for replay. Its documents are an arrival, `exulanica.thing-arrival/v1` (the thing's
id, its kind, its origin record of class `crossed`, the translation manifest's digest, what it
carries, its grant and the gate, or none, and optionally `decided_by`: `program`, what an arrival
stating nothing means, or `world`), and a departure, `exulanica.thing-departure/v1`. Neither carries
a look. An arrival's origin record may carry bounded text the program states (authors, an
attribution, source references); the society copies none of it into its state or events, which hold
the visitor's id, its kind's reference, the bridge and the grant. `society_of_version` names the
society a version holds and its engine. With no stream registered, nothing crosses, and a society
that took crossings is refused replay by name. Replay reads the bound crossings back and refuses by
name a minute whose recomputed crossings differ, or a crossing bound to a minute the society never
ran.

**Lines.** A line is said only by a decider: the model the world's owner chose for a being, or the
outside program that sent a visitor; the routine never says anything. It is one plain line held to
the line rule (`exulanica/things/lines.py`), checked before it is said and refused by name when it
breaks the rule or the workspace's rules would change it
([decision roles](decision-roles-contract.md#a-society-of-things-people)). A being a line was said
to is asked the minute after, whatever is under way for it, and every being reads the lines it
heard, quoted, in its next request.

**Hands.** The hands module (`exulanica-ability/hands/v1` and `v2`) offers a being whose kind has
the ability each act within its approach distance (8,000 mm), nearest first: picking up a thing whose
kind offers `holdable` into a free socket that fits it, putting down what it holds, giving what it
holds to a being whose kind offers `receive` and has a free socket for it, and taking a thing from
a being whose kind offers `let_take`. A being is told what it holds. An act out of reach is offered
when an open node within reach of the thing or the other being remains; choosing it sends the
being to stand a while at that node, as a chosen stand does, and the act is done on arrival; an act
within reach makes it wait where it stands that minute. Under the module's second version, which
every society of things made since records, that node is the open node within reach nearest the
being itself, so it walks up on its own side and never past or through what it acts on or the being
it hands a thing to; a society that recorded the first version walks to the open node nearest the
thing or the other being for its whole life. While something is under way for a being
only acts within reach are offered, since the planner reads no new goal then. An act whose parties
stood within reach as the minute began is done where they stood then (`at_ms` 0), whichever of them
a walk that minute carries away: one chosen while the being walks on and a hand-over whose receiver
walks off alike. Such a decision is rejected
`thing_gone` or `out_of_reach` when what it was for is gone or no open node within reach is left; a
chosen act not done within the module's minutes of walking is dropped as `out_of_reach`
(`hands_missed`), which names any act that waited too long, for a free hand or a thing another
being took first as well as for distance.

**Things that move.** In a society running the hands module a placed thing states where its
author placed it (`placed_at_mm`) and, while held, the socket it is in (`socket`; its `position_mm`
is null). A placed thing its author leaves where it was stays as the society has it, held or where
a being put it down, and one nobody moved from its place takes the author's new turn or height; one
the author moves or changes is where the author put it, out of any hand; one the author removes is
gone, from any hand. What belongs to the world stays in it, and what a visitor brought goes home
with it. Each thing a visitor carries in states the visitor that brought it (`brought_by`), and
stays in the world only while its bringer is here or a being here holds it. A visitor going home
takes what it brought, in its hands or wherever it lies here, but not what a being still here
holds. A visitor whose arrival let it carry the world's things out (`may_carry_out`, kept on its
crossing record) also takes the placed things it holds, but only when it leaves by its own choice
(`chose_to_leave`) or its player calls it home (a departure stating `called_by: "player"`), never
when the world's owner sends it away, its grant ends or its program is lost; each is named in the
departure's `carried` with its `placed_id`. A carried-out placement is recorded in the state
(`carried_out`: its id, kind and place, the grant and the minute), and the thing is not put back
while the author's placement stands, so it is never in two places; an author who moves or changes
the placement makes a new one, and the thing is placed again. The visitors of one grant carry out
at most eight placed things in any sixty minutes; one past that is put down where its visitor
stood, and the departure says so (`carry_out_limited`). Where its arrival also names the kinds of
the world's things its program can take (`carries_out`, by kind key, beside `may_carry_out` only,
kept on its crossing record), it carries out only placed things of those kinds; one of another kind
is put down where it stood, named in the departure's `not_let_out`, and only what is carried out
counts against the bound; an empty list carries nothing out, and an arrival that states no list
carries out as above. Everything else a visitor holds (a placed thing it may not carry out, or a
thing another visitor brought) it puts down where it stood. A being of the world that leaves (an
author's edit removing a placed being) puts down everything it holds. A thing put down after the
visitor that brought it has left goes home to it then, but it leaves the world undelivered: its
bringer gave it away, the door tells a visitor's program only what that visitor's own departure
carried, and no later word tells it of such a thing. So the
things nobody placed are at most what the visitors here brought and what the beings here hold,
and the state check refuses any other. The departure names what it took home (`carried`), what
stayed (`left`) and what it put down that went home to a visitor gone before it (`returned`); a
`put_down` of such a thing says so (`returned: true`).

**Who decides.** The world's owner may choose a model for a person as in a purposeful society, but
only a decider the person's kind allows (`decider_not_allowed`, the kind's `deciders.allowed`), and
an author places no being only an outside program may decide for ([world objects
contract](world-objects-contract.md#14-placed-things)). A visitor is decided for by the program that
sent it, as its arrival records, unless its arrival said the world decides for it (`decided_by`
`world`, kept in its crossing record): the decision host asks its door with the decider `{external,
bridge, grant_id}` read from the state, no choice is recorded for it, and an owner's choice naming
it is refused (`decided_from_outside`). A visitor the world decides for is decided for as any being
here, where its kind allows that decider: by a choice naming it, else by the choice naming the group
of arrivals under its grant (the mind the owner named for the gate's travellers, [decision
roles](decision-roles-contract.md#who-decides-deciders-and-the-owners-choice)), else by the routine; its program is
never asked, and it never goes quiet. A visitor its program decides for takes no person's direct
request (`decided_from_outside`); one the world decides for takes one as any being here does, in
the society and in the database alike (`society_person_may_be_directed`, migrations 0151 and
0179).

**What its state may state as it grows.** A being states `mode` only where it moves by more than
walking (a walker states none), `height_mm` only while it flies, `velocity_mm_s` only while it flies
and its module states one, and `size_class_mm` only where it is not the people's size; a placed
object states `height_mm` only off the ground. A velocity is three whole millimetres a second, each
within 100,000 either way: x and y along the ground (`position_mm`'s two axes) and z up (the rate of
`height_mm`). The next minute's flight starts from it. The state check admits them from the first
state, so a stored society of walkers needs nothing rewritten when another movement module lands.
The things composition states one walking lattice, the people's. A being states `heard` only once it
heard a line (oldest first, each `{tick, from, from_kind, from_number, to, line}` and, in a society
that records its modules, the speaker's name as the page showed it, `from_name`, and, where a model
wrote it, its `model`, the line held to the line rule); in such a society a being also states `said`
once it said a line (the last as many as it keeps of what it heard, each `{tick, to, to_name,
to_kind, line}`), so its decider is shown what it already said. A visitor its program decides for states
`quiet_minutes` only while that program has been quiet, and a being states `hands` only while a
hands act its decider chose or the world's owner asked for waits to be done (`{ability, thing, with,
since}`, with `asked` true for one asked for). A society states
`modules` only where its first input recorded them, and `kinds` only while a being of a kind its
workspace keeps is here.

It runs no experiment, and its people are not sent away. A comparison of models runs an hour of it
from its genesis, where nobody has crossed in, so it compares the world's own beings, scored by the
sixth person score ([society experiments](society-experiments.md#score)); its runs are read by a
line measured on a society of things' own replay, which bounds how many of its beings a model may
decide for ([a society of things' line](society-experiments.md#running-a-comparison)). A placed
thing's footprint is its kind's whole box, so a kind whose box overhangs its base (a tree's
canopy) blocks all of it.

## Retired and frozen engines

Two engines are kept only so that what they stored still reads and replays: the first engine,
which is frozen, and the social engine, which is retired.

### The frozen first engine (v1)

`exulanica-society/v1` initialization and successful transitions stay byte-compatible, pinned by
deterministic digest vectors, and replay checks every persisted v1 event against regenerated
events. V1's home and work nodes are labels; its motion ignores them and has no obstacle or arrival
semantics. The names, roles, `home:{n}`/`work:{n}` labels, fixed weather and resources blocks and
the 300 m wander bound the v1 to v3 profiles hash live only in `society_legacy.py`, labelled as a
frozen encoding that exists so stored histories replay. No later engine changes a v1, v2 or v3
byte.

### V3 bounded observations and communication

`exulanica-society/v3` is retired: a creation that names it is refused with
`409 society_engine_retired`, and nothing records a new proposal for it. A stored v3 society still
reads, advances, takes directed actions, plays back and replays by the rules it was recorded under
(`exulanica/world/society_social.py`). It kept the whole population and the v2 navigation and
action rules; only its first three stable inhabitants form the social cast, and everybody else
follows the v2 routine. Its state adds `social: {profile, cast_ids, last_decision_seq, agents}` with
profile `exulanica.social-state/v1`: each cast member's `observations`, `beliefs` keyed by target
and `communication_ids`, each capped at 16 records, with earlier records kept in the immutable
input and event history.

A cast member stopped at a navigation node observes authored affordances within 4,000 mm of graph
travel, a synthetic graph proximity rather than vision, and can pass one fact it did not learn that
same tick to another stopped cast member within 8,000 mm. A belief records whether it was observed
or communicated, from whom and from which input, and a fact from a newer input supersedes one from
an older input. A cast member chooses an authored goal only when their own belief matches the
current target and its route is reachable, else `no_known_reachable_affordance`. Its events add
`observed` (the complete fact), `communicated` (`communication_id`, `sender_id`, `receiver_id`,
`belief` and `dialogue: null`) and `decision_applied` (`decision_seq`, `request_id`,
`decision_sha256` and `disposition`, where only `applied` means a proposal influenced the step).
Communication records the transmission of information, not a conversation. The Companion's society
answers cover the purposeful profile only and refuse a v3 society by name
(`society_profile_has_no_words`).

### Explicit model proposals and exact replay

The v3 proposal route is retired with its engine:
`POST /world/versions/{version_id}/society/decisions` resolves the world and its society and
refuses every request with `409 society_proposals_retired`, because a model decides for a person
only as the world's owner chose ([decision roles](decision-roles-contract.md)). What a stored v3
society holds still reads and replays:
`GET /world/versions/{version_id}/society/decisions/{request_id}` returns
`{request, decision: receipt-or-null, status: in_progress|completed}`.

A stored request (`exulanica.society-decision-request/v1`) is an immutable reservation, at most one
per subject and base tick: the subject, branch, base tick and state digest, the exact input
reference, the bounded context (`exulanica.society-decision-context/v1`, at most 64,000 canonical
bytes of the subject's own beliefs and observations, current goal and allowed actions) and its
hash, and the configured role, model and manifest hash or null. A request reserved and never
completed reads as pending; nothing retries or answers it. A receipt
(`exulanica.society-decision/v1`) says what its completion found: `stale`, `unavailable`,
`rejected` for a semantic or schema violation, or the validated proposal (`choose_goal` with a
known, available target, recorded as `remembered_target_selected`, or `wait` for one step) or null,
with the call's metadata where the call succeeded and no raw reasoning or prose. Migration 0055
supplies the workspace-isolated tables: `world_society_decision_request`, `world_society_decision`
and `world_society_transition_decision`, which binds each consumed receipt exactly once to a
committed transition with an `applied`, `rejected`, `unavailable`, `stale` or `superseded`
disposition. Replay uses the exact stored receipts each transition consumed, checks their context
and decision hashes and dispositions, regenerates state and events and verifies the final digest;
stepping, reading and replaying never call a model.

## Validation

Dedicated society tests distinguish pure policy fixtures from PostgreSQL scratch-schema evidence.
They cover v1 digest compatibility, reachable/disconnected routes, turn-preserving motion,
action timing, edit/undo reactions, no-snap blockage, population independence, malformed inputs,
authenticated reload, stale writes, branch/workspace isolation and event-history forgery refusal.
The database cases use real migrations and a synthetic authorized-input adapter, not production
sources or personal material. Live connected acceptance and renderer performance require the
integrated experience and explicit user evaluation.

V4 pure fixtures cover catalog refusal, place projection and sizing on the committed Flatiron
input, a 500-minute Flatiron run with no stationary collisions or over-capacity minutes, the same
properties over twelve seeds on a synthetic grid, graph-bound motion within each walking speed,
pinned state and event digests, edits without teleporting, source withdrawal, the city grammar's
hand-written v2 fixture tile as a place (doors, corners, crossings, street identities, spot
spacing and every refusal), a simulated day on that tile with five more flats behind the same
front door, and a real-engine preview recording that replays frame for frame. PostgreSQL cases
cover v4 creation, advance, reload, replay, withdrawal, playback through the worker on admitted
Flatiron inputs, and selection labels without names.

Saved-world fixtures cover per-object decisions at non-default yaw, scale, height, behaviour,
placement and override against the first profile's refusal of the same world
(`tests/test_society_saved_world_objects.py`), room at a destination over many minutes
(`tests/test_society_destination_room.py`), versions surviving a catalog bump and a registry
change on PostgreSQL (`tests/test_society_versions_survive_upgrades.py`), the engine table against
every copy of it (`tests/test_society_engine_table.py`), reads that load only what they show
(`tests/test_society_open_cost.py`), and sending everyone away and back through replay, reopening
and HTTP (`tests/test_society_send_away.py`).

V3 pure fixtures cover local information boundaries, transmission delay, remembered choices,
vacated locations, stale hearsay, wait, proposal rejection and replay (`tests/test_society_social.py`).
PostgreSQL cases refuse a v3 creation and a new proposal by name, and plant a stored v3 society and
its stored proposals as their creation wrote them (`tests/retired_society_support.py`) to hold that
they read, advance and replay and that a request never answered reads as pending
(`tests/test_society_social_postgres.py`). A person's model decisions have their own tests, listed
in the [decision roles contract](decision-roles-contract.md#implementation-and-evidence).

## Traffic boundary

Vehicles are outside the society: road movement is the movement module
`exulanica-movement/roads/v1` ([movement modules](movement-modules-contract.md#roads)), and the
traffic simulation and its served windows are the [traffic contract](traffic-contract.md)'s. A
society's walkers never read a vehicle or a signal and are never held at a kerb. In a world whose
clock is coupled ([world clock](world-clock-contract.md)), each committed minute of a living society
also records its crossing occupancy, where its walkers may stand on a crossing, and traffic yields to
it; that record is derived from the minute and changes no byte of the society's state or events.
