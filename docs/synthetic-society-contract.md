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
play, for the workspaces its environment lists or, with accounts, for every account-owned
workspace, under the bounded lease policy below. Persistence alone starts no worker.

Implementation:

- shared identity, draws, events and digests: `exulanica/world/society.py`;
- which engines exist and what each can do: `exulanica/world/society-engines.v2.json`, read by
  `exulanica/world/society_engines.py`;
- the grounds a society stands on, with what people walk, the population rule, lattice and
  declared area of each: `assets/catalogs/society-ground/society-ground.v2.json` (version 1 kept
  beside it), read by `exulanica/world/society_grounds.py`;
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

`exulanica/world/society-engines.v2.json` states which engine profiles exist and, for each,
whether a society may still be created with it, whether it consumes authorised inputs, whether the
playback worker may play it (and the refusal it gives when not), whether it takes directed actions,
model decisions or experiments, whether the world's owner may choose a model that decides for one
of its people (`owner_model_choice`), whether a comparison of the models that decide for its people
may run it, whether the person whose world it lives in may send its people away, whether it can
stand on a saved world's own ground, which state shape it writes and how many people it may hold,
with a reason per row. It also states which engine a new society over each kind of ground is
created with (`creates`: a district's, a saved world's, and a town's, a saved world whose own
records state its walking surfaces and homes), which the browser reads rather than naming an
engine. `model_decisions` means the engine's history may hold validated model decisions,
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
table's first shape, `society-engines.v1.json`, stays beside it because evaluation records name it,
held to this one's rows by a test.

| Engine | Created | Inputs | Playback | Directed actions | Model decisions | Owner chooses models | Compared | Experiments | Sent away | Saved world | Population |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `exulanica-society/v1` | yes | no | no | no | no | no | no | no | no | no | 100 to 512 |
| `exulanica-society/v2` | yes | yes | yes | yes | yes | yes | yes | no | yes | yes | 1 to 512 |
| `exulanica-society/v3` | no (retired) | yes | yes | yes | yes | no | no | no | no | yes | 1 to 512 |
| `exulanica-society/v4` | yes | yes | yes | no | no | no | no | yes | no | no | 1 to 65,536 |
| `exulanica-society/v5` | yes | yes | yes | no | yes | yes | yes | no | no | yes | 1 to 512 |

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
policy, persistence and replay consume. Every input composed for a saved world uses it. It is the
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
  `source: "declared"`. A person arrives at the region origin: the rule its entry in the society
  ground catalog states (`arrival: region_origin`), which needs nothing authored per world, where
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
  person's placements, else the first), and hangs the crowd under that region's root, which every
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
  per place in a home the world's premises offer (each premises' use class's resident capacity),
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
  (`assets/catalogs/society-ground/society-ground.v2.json`, read by
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
after it differs from the last one in anything but its sequence number and the authored edit
cursor: an edit that changes nothing the society reads appends nothing (`_reads_the_same` in
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
  `{kind: "perform", target_id, affordance: "visit" | "rest"}`;
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
says in words: ending the stay would only begin it again. Exact retries return the existing
envelope; changed reuse or stale bases fail without another write.

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
into a UUID. Summaries are deterministic templates, never invented biographies.

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
refusals. Account-wide discovery is off by default and refuses startup without configured
accounts and the reviewed current-input runtime. The worker asks a model only in the decision
phase before a minute of a purposeful society whose owner chose one for someone, and only for a
workspace its environment lists
([the host's decision phase](decision-roles-contract.md#the-hosts-decision-phase)).

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
  mode, so a paused world reads true when Play would advance it; `interval_ms` is the saved base
  divided by the speed while playing and the host's current base divided by the speed while
  paused, which is what Play adopts; `reason` is null while running and otherwise one of the
  sentences in `HOST_PLAYBACK_REFUSALS` (`exulanica/api/society_control_worker.py`). The `PUT`
  answer and the `control` inside a step answer carry it too.
- `PUT` accepts only `{base_revision, mode: "playing" | "paused", speed: 1 | 2 | 4}`. Successful
  configuration increments the control revision and cancels any pending claim. Stale revision
  returns 409. Unknown/foreign branches are indistinguishable 404s. Invalid input types are 422;
  unsupported settings or v1 play are 409. Unavailable current inputs are 424.
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
8,000/4,000/2,000 ms after batch completion. Computation, polling and contention add time. The
default is measured (`docs/evaluation/2026-09-24-living-world-pace.json`): at it a median walking
minute shows as 1.26 m/s at 1x. The host may configure a base of 1,000 to 60,000 whole
milliseconds divisible by four with `EXULANICA_SOCIETY_TICK_INTERVAL_MS`. Each configuration
receipt retains the chosen base; changing deployment defaults does not silently rewrite saved
controls. A subsequent user configuration adopts the host's current base. Renderers may interpolate
between committed positions, but must not fabricate future goals, actions or positions as evidence.

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

Playback receipts reference completed engine transitions; wall timestamps and random lease tokens
are not replay inputs to the engine. Exact state replay uses the original ordered inputs, authored
edits and persisted decision receipts, including intervening input changes. It neither reads
current geometry as a substitute nor schedules new work. Control configuration and undo do not
rewind society time. Object undo and restore append an ordered authored input. Historical source
withdrawal denies historical replay even when control metadata stays readable. Stepping by hand
needs no background process.

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

**Its day is data.** The town's routine (`TOWN_ROUTINE_VERSIONS` in
`exulanica/world/society_catalogs.py`) reads the living routine's needs, activities and
capacities with three catalogs of its own under `assets/catalogs/society/`, each entry with its
reason: `society-use-class` v2, which states each use class's opening hours and the shifts its
positions work in turn; `society-shift` v1, the early, day, late and evening shifts; and
`society-policy` v2, which employs six in ten residents and starts the town's day at 06:00. One
inhabitant lives in each place in a home the town's premises offer. A seeded share of them takes
the town's positions workplace-first: every workplace gets one worker, in a seeded order, before
any gets a second, and each position works the shift its use class names for it. The rest keep
no job. A premises admits visitors inside its opening hours and only while one of its workers is
at work there, so a shop is open while it is staffed and a workplace nobody works at stays
closed. Every use class the city grammar can give a premises (`assets/catalogs/use-class.v1.json`)
states its hours (`tests/test_society_living_town.py`).

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
`exulanica-movement/roads/v1`, stated and refused as `roads_not_connected`
([movement modules](movement-modules-contract.md#roads)), and the traffic simulation, which nothing
in the application calls, is the [traffic contract](traffic-contract.md)'s.
