# Synthetic society contract

Status: **BOUNDED DETERMINISTIC SIMULATION; NOT A LEARNED SOCIETY MODEL**.

The default `exulanica-society/v1` retains seeded synthetic motion. Opt-in
`exulanica-society/v2` adds reachable goals, routes, reviewed visit/rest actions and reactions to
versioned authored inputs, and lets a model its world's owner chose decide for a person at the
routine's own choice points. Opt-in `exulanica-society/v3` adds a bounded synthetic cast with
local observations, communicated beliefs and explicitly requested, validated model proposals.
`exulanica-society/v4`, the living society, adds catalogued routines, occupancy and a
population sized to its place; the browser creates live societies in the owned district with it,
and a person's own saved world gets a v2 society when the person asks for one. In a saved world
each destination gives its occupants places of their own, an object the society cannot use
costs only its own activity, and the person can send everyone away and bring them back. All
profiles are fictional simulation, separate from personal evidence. They do not model real
residents, infer demographic facts or demonstrate general social intelligence.

<details>
<summary>Sections</summary>

- [Connection to the world](#connection-to-the-world)
- [Identity, branches and compatibility](#identity-branches-and-compatibility)
- [V2 input authority](#v2-input-authority)
- [Goals, routes and actions](#goals-routes-and-actions)
- [Opt-in local activity failures](#opt-in-local-activity-failures)
- [A saved world's own ground](#a-saved-worlds-own-ground)
- [Authored edits and inability to act](#authored-edits-and-inability-to-act)
- [Events, persistence and replay](#events-persistence-and-replay)
- [Server integration and HTTP](#server-integration-and-http)
- [V3 bounded observations and communication](#v3-bounded-observations-and-communication)
- [Explicit model proposals and exact replay](#explicit-model-proposals-and-exact-replay)
- [A person run by a model their world's owner chose](#a-person-run-by-a-model-their-worlds-owner-chose)
- [Validation](#validation)
- [Persisted playback controls and bounded host progression](#persisted-playback-controls-and-bounded-host-progression)
- [Typed user-directed actions](#typed-user-directed-actions)
- [V4 living society: routines, places and occupancy](#v4-living-society-routines-places-and-occupancy)
- [The surface under a walker where the records state several heights](#the-surface-under-a-walker-where-the-records-state-several-heights)
- [Traffic boundary](#traffic-boundary)

</details>

## Connection to the world

The society is the product's core: the people in a world are its agents, and the two model paths
below are how an open model decides what one of them does: a person a world's owner chose a model
for, in a purposeful society, and the explicit proposal path of the social society. Inhabitants
interact with permitted places and authored objects through declared affordances. What a person
brings into and changes in their world changes what its people do. Inhabitants never impersonate
remembered people. The Companion explains what a person is doing and why from their recorded goal
and action, the places they use and the events that explain them, cited as simulation and kept apart
from personal evidence ([Companion
questions](companion-question.md#questions-about-a-worlds-people)).

The pure engine and PostgreSQL lifecycle have synthetic fixture coverage. The connected
personal-world demonstration additionally needs the server composition/rights adapter, accepted
authored edits, shared selection, renderer presentation and grounded Companion integration.
A fixture establishes mechanics, not personal relevance or visual acceptance. Default operation
remains manual. A host can make the API's playback worker advance a saved playing society whose
engine the table below lets it play, for the workspaces its environment lists or, with accounts,
for every account-owned workspace, under the bounded lease policy below; persistence alone starts
no worker.

Implementation:

- shared identity, draws, events and digests: `exulanica/world/society.py`;
- which engines exist and what each can do: `exulanica/world/society-engines.v1.json`, read by
  `exulanica/world/society_engines.py`;
- sending a society's people away and bringing them back:
  `exulanica/world/society_presence.py`;
- the frozen v1 engine and the fixed tables stored v1 to v3 histories depend on:
  `exulanica/world/society_legacy.py`;
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
- bounded observations and communication: `exulanica/world/society_social.py`;
- persistence and compare-and-swap: `exulanica/world/society_repository.py`;
- typed user action policy and persistence: `exulanica/world/society_actions.py` and
  `exulanica/world/society_action_repository.py`;
- persisted playback controls and worker: `exulanica/world/society_controls.py`,
  `exulanica/world/society_control_repository.py` and
  `exulanica/api/society_control_worker.py`; and
- authenticated API: `exulanica/api/routes/society.py`,
  `exulanica/api/routes/society_actions.py` and
  `exulanica/api/routes/society_control.py`.

## Identity, branches and compatibility

The v1 to v3 population is 128 over a district; their pure initializer accepts 100 to 512 there.
A society on a saved world's own ground starts with 8 (below). V4 sizes its population to its
place (below). Each engine's bounds are stated once, in the engine table (below). The population
is canonical state, independent of how many people a renderer draws. Inhabitant UUIDv5 identities derive from
society identity and ordinal. The same society ID/seed/population preserves those identities across
profiles, but a stored society's profile and seed cannot change. The society UUID derives from its
authored version UUID with the existing `exulanica-society/v1` identity domain, including for v2 and v3.

One society belongs to one workspace, world and authored version. V2/v3 `branch_id` equals that version
UUID; the authored version supplies its user-facing name. Same-named objects in two versions remain
different targets. This slice does not fork existing simulation history. To opt in when a version
already has another profile, create a new authored version and a new society. No implicit migration,
identity substitution, tick reset or history rewrite occurs.

## Engines and what each can do

`exulanica/world/society-engines.v1.json` states which engine profiles exist and, for each,
whether it consumes authorised inputs, whether the playback worker may play it (and the refusal it
gives when not), whether it takes directed actions, model decisions or experiments, whether a
comparison of the models that decide for its people may run it, whether the person whose world it
lives in may send its people away, whether it can stand on a saved world's own ground, which state
shape it writes and how many people it may hold, with a reason per row.
`exulanica/world/society_engines.py` reads and checks it, and every list of engines derives from
it: the runtime's edit hook, the repositories' dispatch and population check, the playback
control, directed actions, decisions, experiments, the creation route's choices and default, and
the selection query, which receives the lists as bound array parameters rather than SQL text.
An engine the table does not state is refused by name wherever it is looked up.

| Engine | Inputs | Playback | Directed actions | Model decisions | Compared | Sent away | Saved world | Population |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `exulanica-society/v1` | no | no | no | no | no | no | no | 100 to 512 |
| `exulanica-society/v2` | yes | yes | yes | yes | yes | yes | yes | 1 to 512 |
| `exulanica-society/v3` | yes | yes | yes | yes | no | no | yes | 1 to 512 |
| `exulanica-society/v4` | yes | yes | no | no | no | no | no | 1 to 65,536 |

The browser reads the same file: `pnpm run society-engines:sync` writes it byte for byte, with the
union of its profiles, into `web/packages/app/src/society-engines.generated.ts`, which
`society-engines.ts` parses; the society client takes each snapshot's reader and population bounds
from it. Where a copy cannot derive, it is held to the table by a test in
`tests/test_society_engine_table.py`: every migration check, trigger and index that names an
engine is read back from the live schema and compared with the capability it encodes, the
population check is parsed engine by engine, no Python module outside the table may restate an
engine list as SQL text, and the display's own profile union in atlas-react is held to the table's
at typecheck (`web/packages/app/test/society-engines.test.ts`).

V1 initialization and successful transitions remain byte-compatible, pinned by deterministic digest
vectors. V1's home/work nodes are labels; its motion ignores them and has no obstacle or arrival
semantics. Replay now additionally checks every persisted v1 event against regenerated events.
Unknown engine/input profiles are refused. WMP 1.0, the authored-world 1.0 extension and the
environment-instances 1.0 extension still omit society and its input/event history; they
cannot resume this simulation.

## V2 input authority

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

## Goals, routes and actions

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
minutes and 24 completed activities is pinned by its state digest, produced by the code before
places existed (`tests/test_society_destination_room.py`), and a saved world's v2 society stored
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

## Opt-in local activity failures

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
not the currently selected projection policy, while continuing to recheck current rights and
asset bytes. The runtime binding structure and its digest do not change.

Apply the reader/schema support before opting a host into `exulanica.society-composition/v2`. Subsequent accepted
edits append the chosen projection. To recover an already paused society immediately, explicitly
append a fresh authorized projection through the runtime input-refresh/edit hook and then advance;
a configuration change alone does not rewrite the persisted state. A policy refresh can keep the
same authored edit cursor/delta digest while increasing `input_seq`. Replay therefore retains the
earlier global pause and the later locally degraded input exactly. Local records are available in the
stored input document for authorized adapters; no new browser endpoint is introduced.

## A saved world's own ground

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
is, because the ground module no longer always states an edge.

- Ground module version 1 states a 24 m square. The society reads that extent and its input marks
  the area `source: "ground"`.
- Ground module version 2, which every new starter uses, states an endless plane with no extent.
  There is nothing to read, and a route graph over the whole plane a renderer can carry a person
  across would be tens of millions of nodes. The society therefore declares its own area: a square
  of 12,000 mm half extent about the region origin, marked `source: "declared"`. The declaration
  lives only in the society's inputs. The stored world keeps its endless ground; nothing writes an
  edge into it.

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
  removal. A snapshot that is not the built-in authored starter at a supported module version is
  refused with the reason, and so is a ground kind the projection has no rule for, rather than
  guessed at.
- Declared by the profile: the walkable area on a ground that states none, and a route lattice at
  two metre spacing over the area, inset by the navigation clearance. A flat rectangle has no
  paths of its own, so a graph over it is a discretisation this profile fixes, not a shape measured
  from anything. Two metres keeps every point of the area within 1,415 mm of a node, inside the
  reviewed object reach, and keeps a 24 m area at 121 nodes and 220 edges. The spacing and the
  declared extent are part of the profile, so changing either changes every input digest.

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

A society on a saved world's own ground starts with `AUTHORED_GROUND_POPULATION`, 8 people,
where a district starts with 128: an area about 23 metres across with 121 places to stand would
otherwise have people standing on top of each other from the first minute. The repository reads
the figure when it creates a society, so a measurement can set another in-process. The authored
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

### One object at a time

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

### Room at a destination

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
through anything: it now asks `society_person_may_be_directed`, which admits exactly whom the
society may direct ("Typed user-directed actions").
Migration 0095 lets a v2 or v3 society hold 1 to 512 people, keeping
v1 at 100 to 512 and v4 as 0075 left it. A row does
not say which kind of ground its society stands on, so the district's floor of 100 is held by the
initializer that every creation and every replay passes through.

## Authored edits and inability to act

Each relevant accepted authored edit appends a full immutable input snapshot in its transaction,
even if several edits happen between simulation ticks. The next committed step consumes every input
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

## Events, persistence and replay

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

Measured in the release build (`docs/evaluation/2026-09-23-society-open-cost.json`), the moment
a world's inhabitants are handed to the renderer, and the society and playback reads, do not grow
with the number of stored inputs. The events read still does: it authorizes every input its page
of events names (`SocietyRepository.events`), and each authorization reads the authored version
with its whole edit list (`SocietyRuntime._authored_version`), so a page that names many inputs
costs more the longer the world's edit history. Edits consumed in one minute leave events naming
most of those inputs; a page holds at most 256 events.

The record's figures are medians in milliseconds over five opens per size, on a starter world with
one Marker plate and eight inhabitants whose history grew by moving the plate, each size's edits
consumed in one minute. "World shown" runs from submitting the access form to the page handing the
society's current minute to the renderer. "Validating every stored input" is the same tree with
the read change above reversed, measured beside it to show what the change removes; at 400 inputs
its events read left no timing entry within 1.5 s of the world being shown, so it is unmeasured.

| Stored inputs | 1 | 25 | 100 | 400 |
| --- | --- | --- | --- | --- |
| World shown, reads validating every stored input | 233 | 285 | 460 | 1425 |
| World shown, reads as described | 261 | 286 | 287 | 267 |
| Society read, validating every stored input | 15 | 62 | 236 | 1094 |
| Society read, as described | 16 | 22 | 21 | 19 |
| Events read, validating every stored input | 20 | 157 | 586 | no entry 1.5 s after the world was shown |
| Events read, as described | 24 | 104 | 318 | 761 |

## Versions that survive upgrades

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

## Sending inhabitants away

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

## Server integration and HTTP

Existing authenticated society create/read/step/events/replay routes remain. Creation optionally
selects `profile: exulanica-society/v2` or `exulanica-society/v3`; omission keeps v1. Step bodies still contain only
`base_tick` and `base_state_sha256`. Extra authoritative input JSON is rejected.

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

The application supplies `society_initial_input(connection, session, version_id, place_id, region_id)`
and `society_input_authorizer(connection, session, document)` on application state. The repository
accepts an `input_authorizer(document)` callback and exposes internal `record_input(version_id, doc)`
for the authored-edit transaction. The adapter must take appropriate source/asset locks and validate
current bindings. An absent authorizer/provider fails closed. The public routes report
`424 unavailable_society_input`; invalid state/replay is a `409`, malformed creation a `422`, and
stale state remains `409 stale_society_state`. Existing unknown/cross-workspace handling remains `404`.

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
Authored composition and live visual acceptance are separate integration responsibilities, not
capabilities inferred from a fixture.

## V3 bounded observations and communication

V3 preserves the complete population and existing navigation/action enforcement. Only the first
three stable inhabitant IDs participate in the social policy. Other inhabitants retain the v2
utility policy. This is a bounded social cast, not a claim of 128 independent model agents.
Existing v1/v2 states are never upgraded in place; their transition and event bytes remain stable.

The state adds `social: {profile, cast_ids, last_decision_seq, agents}` with profile
`exulanica.social-state/v1`. Each cast member has `observations`, `beliefs` keyed by target ID,
and `communication_ids`. Each collection is capped at 16 records; a decision context includes at
most eight observations and 16 beliefs belonging to that subject. Earlier records remain in the
immutable event/input history, not an unbounded prompt. The social engine does not read wall time;
optional playback schedules calls to the unchanged deterministic step operation.

An inhabitant stopped at a declared navigation node observes authored affordances within 4,000 mm
of graph travel. This is synthetic graph proximity, not recovered vision or line of sight. Observed
facts record `fact_id`, `observer_id`, `observed_tick`, exact `input_seq`/`input_sha256`, a typed
`target`, and `available`. A removed, disabled or locally vacated target can be observed as
unavailable. Noticing a vacated location does not reveal a distant new location. Retained ordered
inputs allow multiple edits between ticks to be noticed in order at that tick's starting position;
this does not claim perception at the edits' actual wall-clock times.

A stopped cast member can communicate one retained fact per tick to another stopped cast member
within 8,000 mm of graph travel. It cannot transmit something it first learned that same tick.
Deterministic cast and target ordering chooses the interaction. A recipient's belief records
`origin: communication`, sender `source_subject_id`, original `source_fact_id`, `communication_id`,
original input sequence/digest, `learned_tick`, target and availability. Direct beliefs instead use
`origin: observation` and a null communication ID. Newer factual input sequences supersede older
ones; an existing belief wins a same-input tie. Relaying earlier information later does not make its
source newer. These are bounded records of claims, not trusted global truth or learned relationships.

Cast members know public district destinations. They can choose an authored goal only when their
own available belief matches the current authoritative target exactly and its route is reachable.
Missing or outdated knowledge can produce `no_known_reachable_affordance`. Current physical route
and action preconditions always apply, including to a mistaken or outdated belief. Undo/restore
is another input: it can produce a new observation and later communication, but does not erase
prior beliefs, interactions, completed actions or simulation time. An authorized unavailable pause
clears materialized cast memory; historical records remain rights-gated.

V3 adds `observed`, `communicated` and `decision_applied` events to the existing event envelope.
Use envelope `event_kind`, document `reason`/`outcome` and these structured fields:

- `observed`: `observation` holds the complete fact;
- `communicated`: `communication_id`, `sender_id`, `receiver_id`, `belief`, and `dialogue: null`;
- `decision_applied`: `decision_seq`, `request_id`, `decision_sha256`, and `disposition`.

`decision_applied` records consumption, including rejection/staleness; only `disposition: applied`
means a proposal influenced the step. Inhabitant `explanation.event_ids` and bounded `memory` cite
actual events. Communication records transmission of information; the implementation does not
supply dialogue or imply a model-generated conversation. All identity, goals and summaries remain
explicitly synthetic. Companion explanations must preserve observation versus hearsay and cite
these facts; they must not invent biography from a displayed label. The Companion's society answers
cover the purposeful profile only and refuse a V3 society by name (`society_profile_has_no_words`),
so it composes no V3 explanation.

## Explicit model proposals and exact replay

Models are optional and never called by stepping, reading or replaying. An explicit server
`SocietyDecisionProvider(client, role, manifest_sha256)` uses the existing `ModelClient.structured`
boundary, a fixed prompt version and strict `GoalProposal` schema. The client cannot select a role,
model, prompt or context. A missing provider produces a durable `provider_not_configured` receipt.
No production model quality or learned social behavior is established by offline transport tests.

The bounded context profile is `exulanica.society-decision-context/v1`. It contains subject/branch,
tick, position, `can_choose_goal`, that subject's `own_beliefs`/`own_observations`, current goal and
allowed actions. Canonical context bytes may not exceed 64,000. Only `choose_goal` with a known,
available target or `wait` with a null target is allowed. The validator checks the current target,
reachability and absence of an action in progress. Wait lasts one explicit step. A chosen goal
uses `remembered_target_selected`; replay revalidates the stored choice without new inference.

For a v3 society, `POST /world/versions/{version_id}/society/decisions` accepts exactly
`{idempotency_key: UUID, subject_id: UUID, base_tick: integer, base_state_sha256: SHA256}`.
`GET` at the same path plus `/{request_id}` reads the result. Both return
`{request, decision: receipt-or-null, status: in_progress|completed}`. The idempotency key is the
request ID. Queued authored inputs must first be consumed by an explicit step. A request does not
advance society time, and a completed accepted receipt affects only a subsequent explicit step.

Preparation commits an immutable reservation with profile `exulanica.society-decision-request/v1`,
subject/branch/base tick/state digest, exact input reference, full context and its hash, configured
role/primary model/manifest hash or null, and the request document hash. At most one request is
reserved per subject and base tick, even with different keys. An identical retry returns its
existing pending/completed envelope without another inference. A crash after reservation remains
honestly pending; there is no automatic retry or fabricated success.

The preparation connection closes before inference. No database transaction, workspace advisory
lock or asset lock remains held during the provider call. Completion opens a new transaction,
reauthorizes current inputs and all historical context dependencies, and compares the exact state
and input again. Changed state or input yields `stale`; withdrawn dependencies yield a persisted
`unavailable` receipt and HTTP 424 without returning the context. Semantic/schema violations yield
`rejected`. Results store validated proposal or null plus actual successful call metadata: served
model, role, manifest/prompt/schema/messages hashes, attempts/fallback/cache status, token usage and
cost. Failed calls without that metadata retain the explicit failure and null provider, not an
invented execution record. No raw reasoning or unrestricted prose is admitted.

`world_society_decision_request` stores the immutable request. `world_society_decision` stores the
contiguous receipt sequence, profile `exulanica.society-decision/v1`, request/hash binding, subject,
branch, base state/tick, input/context hashes, status/reason, proposal/provider and document hash.
`world_society_transition_decision` binds each consumed receipt exactly once to a committed
transition, with `applied`, `rejected`, `unavailable`, `stale` or `superseded` disposition. These
workspace-isolated tables and v3 guards are supplied by migration 0055. State, events, transition
and consumption bindings commit atomically. Replay uses the exact stored receipts consumed by
that transition, checks context/decision hashes and dispositions, regenerates state/events, and
verifies the final digest. A provider change cannot retroactively change replay.

## A person run by a model their world's owner chose

A purposeful society (`exulanica-society/v2`) with no choice recorded is the routine it always
was: nothing is asked or reserved, and its replay reads no decision row. From the moment its
world's owner chooses a model for one of its people, or for a group, that person's decisions at
the routine's own choice points come from that model, validated, whenever the host asks it, and
from the routine whenever it does not. Stored v2 histories have no decision rows and replay
unchanged.

**Choosing.** `POST /world/versions/{version_id}/society/models` records one choice,
`{idempotency_key, people: [subject_id, ...], model: {provider, model_id} | null}`, where null is
their own routine. It requires `world.write` and `model.invoke`, which in a browser only the
workspace's owner holds. Choices are appended in order to `world_society_model_choice`
(migration 0110), each naming who made it, and are never changed; a person's model is the latest
choice naming them. A choice names people of this society and a model the manifest offers the
`society_decision` role and the decision contract can ask, or it is refused by name
(`CHOICE_REFUSALS` in `exulanica/world/society_model_choice_repository.py`): 422 for what the body
names, 409 for a society whose engine takes no choice or a key reused for another choice. A
choice naming one person twice is refused (`person_named_twice`), and an exact retry of a key is
answered with the choice it recorded before anything else is checked, so it still returns after
its model stops being offered. At most `model_people_maximum` people are run by models at once.
`GET` at the same path, with `world.read`, returns the offered models in plain words with whether
this process can ask each; whether this host asks models for the world at all, and why not
(`host_refusal`); each person's choice, with why its model is not asked here when it is not
(`refusal`), and their latest decision; and per model the decisions asked, accepted and applied,
why the rest were not acted on, latency and cost, over the society's latest 2,000 decisions.

**The contract.** `assets/catalogs/society/society-decision-action.v1.json` and
`society-decision-policy.v1.json` state the actions and bounds, read by
`exulanica/world/society_decision_contract.py`. A person is at a choice point where the routine
itself chooses for them: when they have no goal, or their action has completed. A person blocked
on the way to a goal keeps it, as the routine keeps it for them, and is not asked. Their options
are each enabled place they
can reach with room for them, the nearest `options_maximum` less one, labelled by what it is and
how far ("resting on a bench, 5 m away"), and waiting a minute, in an order shuffled by the
society's seed, the person and the minute. The model reads a fixed instruction and that person's
situation: tiredness, what they just did and their options, and nothing of anybody else. It
answers through one function, `act`, forced by name, whose one argument, `action`, is an enum of
exactly those labels, or through a strict JSON schema of the same enum. The function's name, its
argument's and its description are fixed product values, no caller's text; the mechanism is the highest
ranked one the manifest names as verified for the model by a recorded probe. An answer that is
not an offered label is asked once more, saying so; after `answer_attempts_maximum` answers the
routine decides that turn.

**The host.** Before each minute of a playing purposeful society in a workspace its environment
lists, the playback worker's claim runs the host's decision phase
(`exulanica/api/society_person_decisions.py`). It first closes, with the reason
`unanswered_in_its_minute`, any request an earlier host reserved in the last few minutes and never
answered, one that stopped between the two; that request's minute has already run with the routine
deciding. An older one stays as it is: nothing replays or waits on a request without a receipt. What
the host cannot ask, it decides before reserving anything, and it writes nothing for it: a process
with no model client, or whose budget or share (below) leaves too little for the smallest ask of any
offered model (`HOST_REFUSALS`), and a person whose chosen model is no longer offered, is served by
another provider than the choice names, is served by a provider this process refuses, or needs more
for one ask than the budget or the share has left (`MODEL_REFUSALS`). The models route says which,
for the host and for each choice, and the page says the person follows their own routine until the
host can ask it, and why. Once a minute, before it reserves anything and with no lock held, the
host has the workspace's rules judge the function's fixed description and every label anybody it
may ask could be offered, in one pass for each chosen model. A description the rules would change,
as a saved name one of whose parts is a word of it would, asks nobody of that model and writes
nothing; the models route names it for each such choice (`question_changed_by_rules`). Each other
chosen person at a choice point is offered the places the rules send as they are, leaving out any
whose words they would change, a place a saved name happens to match; a person left no place, or
fewer than two options, is not asked and nothing is written. It reserves a request (`exulanica.society-decision-request/v2`), commits and closes its connection,
asks the models concurrently, at most `concurrent_calls_maximum` at once, and records each receipt
(`exulanica.society-decision/v2`) in its own transaction; then that claim advances one minute, so no
later choice point of a person a model runs passes unasked. Every ask of the minute ends by one
time: the contract's `decision_deadline_ms` after the phase begins, and never later than the lease
leaves the minute to commit in. A phase with no time left asks nobody, and an ask that could only
start after that time records `no_time_to_ask`. Nothing is asked for a person once the world's last
hour holds `decisions_per_world_hour_maximum` asked decisions or `spend_per_world_hour_microusd` of
their cost, counted from its receipts with an unknown cost at its bound and each ask already
admitted that minute at its bound; each such receipt names the bound (`DECISION_REASONS`). A person
whose situation is larger than `context_bytes_maximum` is not asked, and nothing is reserved for
them. The page never asks a model, and a manual step takes only receipts already recorded.

**Spend.** Two bounds hold whoever plays the world. The hourly bounds above hold each world. The
process's model budget (`EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS`) is a ceiling for the
life of the process that every model call it makes shares, the Companion, photograph ingestion,
vision and caption search among them. People's decisions may use all of it but the contract's
`process_reserve_percent`, which they leave for that other work, so a world played for hours never
leaves the Companion or ingestion refused. The budget holds each admitted call's reservation until
its usage is recorded, so calls admitted at once never cross a ceiling together. The host decides on
what the process has spent, whoever spent it, never on what calls under way hold: once what is left,
beside the part kept for other work, fits no ask, it asks nobody, and the models route and, where a
playback host plays workspaces its environment lists, `/readyz` say so (`process_share_spent`, or `process_budget_spent` when the
whole budget does not fit). Spending only grows while the process runs, so either holds until it
restarts. A person whose own model needs more for one ask than is left is not asked either, while a
cheaper model may still be asked for others, and the models route says so for their choice. An ask's
need is its bound: every answer the contract allows, each with the largest situation a request may
carry. A call under way can still leave one ask no room for its reservation, which that ask's
receipt names. The recorded choice is what authorizes this spending: a caller who may play the world
(`world.write`) starts it by playing, without holding `model.invoke`, and never beyond these bounds.

**Sending everyone away.** `POST .../society/presence` waits while a model decides: it is refused
with `a_request_is_waiting` while a person's request exists at the current minute or a receipt is
unconsumed, as it is while a direct request waits, and the next minute consumes it. A receipt for
somebody no longer here, one closed after its minute for a person sent away since, is consumed by
their id alone and moves nobody.

**The minute.** An accepted receipt is checked again against the minute. Asked over another state
or input it is `stale`; a person's own direct request that minute supersedes it
(`person_asked_directly`), as a second receipt for somebody already decided does
(`subject_already_decided`). When the chosen place can no longer be reached or used, or another
choice or request was promised it first this minute, the receipt is `rejected` with that reason.
Otherwise it is `applied`, as a goal policy: a chosen place is the planner's goal with the reason
`chosen_by_their_model`, and a chosen wait keeps the person where they are for the minute, which
the planner records as blocked with the reason `validated_model_wait`. A receipt that is not
accepted leaves the turn to the routine and keeps its status. Every consumed receipt
appends one `decision_applied` event after the minute's other events, naming its `request_id`,
`decision_seq`, `decision_sha256`, disposition and reason, the model as `{provider, model_id}` and
the chosen label; `GET /world/versions/{version_id}/society/decisions/{request_id}` reads the
request and its receipt, which names the calls, tokens and cost.

**Replay.** Replay applies each transition's bound receipts exactly as they were recorded and
calls no model, so the receipts, not the provider, determine the history. A model or provider
that changes or is withdrawn later changes nothing already recorded.

**Comparing models.** The same hour of such a society can be run once per model, beside its routine
and waiting, from one genesis and one seed, and scored from what the engine recorded; each run is
asked as this host asks, save where the comparison states otherwise, and replayed from its own
receipts, and none changes the society it ran over.
[Comparisons of models](society-experiments.md#comparisons-of-models) states the records, the
score, the claim and the Compare view.

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
front door, and a real-engine preview recording that replays frame for frame. PostgreSQL cases cover v4 creation, advance, reload, replay, withdrawal,
playback through the worker on admitted Flatiron inputs, and selection labels without names.

Saved-world fixtures cover per-object decisions at non-default yaw, scale, height, behaviour,
placement and override against the first profile's refusal of the same world
(`tests/test_society_saved_world_objects.py`), room at a destination over many minutes
(`tests/test_society_destination_room.py`), versions surviving a catalog bump and a registry
change on PostgreSQL (`tests/test_society_versions_survive_upgrades.py`), the engine table against
every copy of it (`tests/test_society_engine_table.py`), reads that load only what they show
(`tests/test_society_open_cost.py`), and sending everyone away and back through replay, reopening
and HTTP (`tests/test_society_send_away.py`).

V3 pure fixtures cover local information boundaries, transmission delay, remembered choices,
vacated locations, stale hearsay, wait, proposal rejection and replay. Authenticated PostgreSQL
cases exercise committed reservations, pending/completed retries, stale input/state admission,
withdrawal, provider absence, transition consumption and reload/replay. Those HTTP operations use
a provisioned nonowner role with neither superuser nor BYPASSRLS privileges. The model path uses
the real client adapter with a scripted offline transport; this is not live-provider quality
evidence, admitted personal-scene evidence or browser acceptance.


## Persisted playback controls and bounded host progression

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
([A person run by a model their world's owner chose](#a-person-run-by-a-model-their-worlds-owner-chose)).

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
  It performs exactly one existing deterministic step and returns `{control, society, receipt}`.
  Both control revision and simulation tick/digest must match. First successful use persists
  paused settings; a failed step rolls back that configuration too. V1 remains manually usable.
- `GET /events?limit=64` returns newest-first hash-checked scheduling receipts, capped at 128.
  These explain control changes, claimed/reclaimed leases, committed tick spans, discarded timing
  debt and failures. They are distinct from inhabitants' action/event explanations.

The older `/society/steps` endpoint retains its existing semantics and can explicitly advance a
playing or paused society. The authenticated browser playback UI uses `/control/steps` to enforce
pause-before-step and reads the control after connection, refresh and control conflicts. It exposes
play, pause, 1x/2x/4x speed and one simulated-minute advancement without deriving canonical ticks
from render frames.
Control revision tracks user configuration or automatic pause, while simulation tick/digest track
progress. A normal automatic tick does not increment control revision. It still uses the existing
simulation compare-and-swap operation and workspace edit lock, serializing authored edits and
manual or model-decision reservations through the existing domain boundary.

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
under composition/v2 continue to produce their existing per-action reasons and do not pause an
otherwise available district.

Playback receipts reference completed engine transitions; wall timestamps and random lease tokens
are not replay inputs to the engine. Exact state replay still uses the original ordered district
inputs, authored edits and optional persisted decision receipts, including intervening input
changes. It neither reads current geometry as a substitute nor schedules new work. Control
configuration and undo do not rewind society time. Object undo/restore continues to append an
ordered authored input under the existing supported version semantics. Historical source withdrawal
continues to deny historical replay even when control metadata remains readable. No sleeping
process is required for default/manual use, and no production rollout is implied by these modules.

## Typed user-directed actions

Migration 0060 adds append-only `world_society_action_request` and
`world_society_transition_action`. This is a bounded external-input foundation for v2/v3 societies,
separate from optional model decisions and playback controls. It does not broaden the affordance
registry or accept free-form movement.

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
ordered pending requests through the existing goal-policy seam. `go_to` constrains the next goal to
the target; `perform` additionally binds its existing affordance. Each request receives one
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
under, a request to anybody mid-action is refused `inhabitant_action_in_progress` as it always was
(`tests/test_society_square_requests.py`). A request can direct only the next eligible goal and
ordinary navigation/action checks remain authoritative. Over an
input that states places, a request is refused `destination_full` when every place of its target is
held by somebody else, and an applied request is promised its place before the minute, so nobody
choosing freely in the same minute takes it first. It cannot
teleport, cross unsupported space, undo completed actions or simulation history, or replace a
withdrawn target. The browser has a control on a declared visit or rest destination that issues
one typed `perform` request through this API and shows the returned pending or consumed record, or
an explicit unavailable or refused state. It re-checks its gate whenever the persisted society
refreshes. Living (v4) societies refuse it because directed actions are a v2/v3 foundation.
Simulated action records stay labeled as simulation and are never presented as personal evidence.

In a person's own saved world the control is reached like this. Opening the world reads its
society and creates nothing; the People nearby panel says when nobody lives there yet, what
inhabitants need, and offers "Bring in inhabitants", which is the creation request above. Once
they live there, the panel lists every object with what the consumed input says of it (somewhere
to rest or visit, out of reach, or not yet noticed until the next simulated minute), and "Advance
one minute" performs one control step while the world is paused. A chosen inhabitant's panel
carries one request per usable place. Every request names the saved world. The placement of this
panel is provisional.

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

## V4 living society: routines, places and occupancy

V4 is a successor profile. It never changes v1, v2 or v3 bytes: their pinned digest vectors and
replay tests are unchanged, and the names, roles, `home:{n}`/`work:{n}` labels, fixed weather and
resources blocks and the 300 m wander bound those profiles hash now live only in
`society_legacy.py`, labelled as a frozen encoding that exists so stored histories replay.

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
  (`city_navigation`), never a list of kinds in this lane's code. A footway exists because
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
`unsupported`. What a society may not do is hand somebody a job across a cut and then say
nothing, which is what it did until 2026-09-19: the shift found no reachable target, the choice
stepped over it in silence, and on one corridor tile 37 of 64 inhabitants spent a simulated day
unable to reach work while every run measurement reported a healthy society. `_targets` now says
which shortage emptied its list, since nothing here offers it, the places that do are full, and
no route reaches them are three findings with three fixes; no v4 transition consumes that reason,
because a goal's `because` is canonical state and a change to a v4 transition is a new profile.

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
place's capacity. Together these rule out the absorbing state v2 reached on Flatiron, where
every inhabitant preferred the one visit target forever: no two stationary people share a
position, and an outdoor inhabitant moves again within a bounded number of minutes.

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
index and the input and event binding triggers. V4 uses the existing input, event and transition
tables, playback controls and replay. Typed user actions and model decisions remain v2 and v3
features; v4 refuses them.

**Rendering.** A saved world's inhabitants are drawn by the same crowd, hung from the authored
region's root, which is the frame their input states positions in and the frame the person's
objects are placed in. A resting inhabitant is one whose `action.kind` is `rest` with
`action.status` `active`, and it rests at its own place, a standing spacing from anybody else. The
crowd hands the kind of an action under way to whatever draws the person, as `activity` in
`CrowdPose` (`web/packages/atlas-react/src/playcanvas/society/types.ts`), once the path recorded for
the minute has been walked. With each state the page hands the crowd a seating layout
([`society/seating.ts`](../web/packages/atlas-react/src/playcanvas/society/seating.ts)): each kind's
use as `GET /world/assets` serves it from the world object catalog, the drawn version's objects, and
the object each target of the consumed input belongs to. A person whose action, under way or just
completed, names a target holds the catalog place whose position, carried into the object's frame,
lies within the turn's outward rounding of their recorded position (`PLACE_MATCH_MM`, the square
root of two millimetres and a micrometre). They face as their activity's rule says
([`society/activity-facing.ts`](../web/packages/atlas-react/src/playcanvas/society/activity-facing.ts)):
`rest` and `visit` face the object across the place, so a visitor at the market stall faces its
counter and one at the tree faces the tree, also in the minute after a visit completes, while the
visitor still stands there; `talk` faces the partner the goal names; the rest keep the way they last
walked. Where the place has a seat and the character catalog declares a seat posture for the
activity (`seatPostures`, `rest` to `perched`), the person sits on it: they walk at their own pace
to stand before the seat (in front of it, or beside it when their place is off to its side, as at
the cafe chairs, so the walk does not pass through the table), then turn and lower onto it over the
posture's 0.8 s blend, pelvis on the seat at its height and facing: a full character with its feet
planted on the ground below, a far figure lifted to the same height. Getting up runs the same way
back, feet planted as they rise, before they walk on. Moved without walking (a named jump), they
leave the seat at once rather than glide from it. After an object is moved or taken away the page
hands the crowd a new layout at once, so a person whose seat is gone gets up without waiting for the
next minute. The move from the place to the seat is presentation, and the person's recorded position
stays the place. A place with no seat, such as a marker plate's, keeps the ground rule: resting is
drawn sitting on the ground in front of it. A person matched to no place, or performing an activity
with no facing rule, is drawn as everyone else is and named with its reason
(`SocietyCrowd.seatingMisses`, which the page records on the canvas as
`data-society-seating-misses`); the owned district hands no layout. An activity with no declared
posture, such as making room, is drawn standing, and so is everybody drawn by a renderable with no
postures, which also stays standing at its place rather than being lifted onto a seat. While
everyone is away the state holds nobody, so the crowd draws nobody.

The app draws the whole population by distance: up to 24 nearest outdoor
inhabitants as full characters (the native character runtime's resident limit) and every other
outdoor inhabitant within 700 m as a simple instanced figure of the same identity, one draw call
per palette. Indoor inhabitants are counted, not drawn. People at the same position are all drawn
there. A v4 inhabitant walks the recorded path at its recorded `walk_speed_mm_per_tick`, one
tick's worth per interval, and stops where the path ends. A v2 state records only a bound,
`movement_budget_mm_per_tick`, which is usually far longer than the path a person walks in a
tick; a v2 person therefore walks what they have left evenly until the next tick is expected (the
interval plus the caller's start lag), never faster than 1.5 times the bound's own pace, so
nobody sprints and then stands. A v2 person whose newly read tick adds nothing to walk finishes what
is left at no slower than their own walking pace, the walk clip's measured ground speed at their
height: a remainder spread again at every tick would shrink by the same share each time and never
end (measured with host playback: ticks read every 8.1 s against 10 s of spreading left a fifth each
tick, and nobody ever arrived to rest or face anything). Nothing is interpolated off the path. Each
later tick's path is
appended to what the person has still to walk when it starts where that ends, so a walk through
several minutes does not stop between them, and a caller that learns of ticks late passes that
delay as a start lag. A v4 person behind catches up along the path at most 1.5 times their speed;
anyone moved without walking (a path that starts elsewhere, unread minutes, more than two ticks
of walking waiting, no recorded path, or an older state) is named with its reason rather than
moved silently (`CrowdJump` in `web/packages/atlas-react/src/playcanvas/society/types.ts`). A
state without a pace is eased along its path over the interval. The development
preview plays a recording made by the real engine over the committed Flatiron input
(`scripts/record_living_society.py`), with every frame bound to its state digest.

**Detail by distance applies to time too.** Solving and skinning one full character costs about
0.53 ms of main-thread time, so the crowd poses the 4 nearest every frame, the next 8 every second
frame and the rest every third, 12 poses a frame instead of 24, and carries each character to its
recorded point on every frame in between. A selected inhabitant, and anyone whose snapshot jumped,
is posed at once. Measured in the preview at 1440x900 in headless Chrome on an M3 Pro, over the
debug PlayCanvas build a development server serves: main-thread work per frame is 9.4 ms at p50
and 9.9 ms at p95 with the cadence, against 15.9 ms and 16.6 ms posing every character every
frame, and at most 2 frames in 1,199 passed 16.7 ms. A steady 16.7 ms frame interval is not proof
of a met budget: the browser stamps each frame on schedule while its callbacks run late, so the
figures above are main-thread work, not intervals.

## The surface under a walker where the records state several heights

`exulanica.society-place/v2` states beside each node the height of the surface a person stands on,
taken from the records. The corridor's records state many heights: eleven distinct footway walking
lines from 96 to 167 mm across its 46 curbs, no curb's line varying along its own length, and the
two curbs of one street segment differing on all 23 segments, by 2 mm at the closest and 63 mm at
the widest. The only walk whose parameters this repository states runs east ALONG one curb's
footway, at a constant height, so nothing measured before this separates a runtime whose surface
carries the heights the records state from one that stands a walker at a single height the records
do not state anywhere.

The parameters, the expected heights and the response to each outcome below are committed before
the container is baked and before anything is sampled, so that what is reported afterwards has
something to be checked against rather than something to be chosen to fit.

**The line.** Tile (2, 0)'s own north-south midline: x `320000`, the midpoint of the tile's x span
256,000 to 384,000, from y `0` to y `128000`. It is the same x the east-west walk already captures
a frame at, so the two lines cross at that frame. Six curbs state a footway across it: the tile
carries six east-west kerb lines whose x span covers the tile's midline, their shared x span is
261,950 to 378,050, and the midpoint of that span is also 320,000, so the line meets no curb near
its end.

| | |
| --- | --- |
| line | x `320000`, y `0` to `128000`, in the records' own `city_local` frame, integer millimetres |
| step | 50 mm, which is `SUPPORT_SAMPLE_SPACING_M`, the spacing the runtime resamples support at |
| samples | 2,561 along the line, plus the six walking-line points exactly |
| what is asked | `navEnvelopeSupport(nav_envelope).surface.sample(...)`, the runtime's own support sampler, over the tile's own container |
| frame of the ask | renderer metres, `tileToRenderer(x, y, 0)`, and the height it returns in metres multiplied by 1,000 to compare with the records' millimetres |
| what it is compared with | `_Kerb.surface_z`, the society place's own reading of the curb record, in millimetres |
| container | baked from the tile (2, 0) document by `pnpm tess bake`; both triangle digests recorded beside the result |

**What the records state on that line**, south to north, read from the curb records of this tree
by [walking-lines-records.py.txt](artifacts/society/walking-lines-records.py.txt), which reads the
city's records and no container, and whose
[log](artifacts/society/walking-lines-records.log.txt) is the table below:

| curb | kerb line y | footway strip | walking line y | walking line z |
| --- | --- | --- | --- | --- |
| Linden Terrace 2 right | 4,450 | 1,000 to 4,450 | 2,575 | **123** |
| Linden Terrace 2 left | 11,550 | 11,550 to 15,300 | 13,500 | **163** |
| Harbour Way 7 right | 60,450 | 56,700 to 60,450 | 58,500 | **163** |
| Harbour Way 7 left | 67,550 | 67,550 to 72,900 | 70,300 | **146** |
| Foundry Street 12 right | 116,450 | 111,100 to 116,450 | 113,700 | **146** |
| Foundry Street 12 left | 123,550 | 123,550 to 125,750 | 124,800 | **96** |

Four of the eleven heights the street states, and the differences between neighbours along the line
are +40, 0, -17, 0, -50 millimetres. The seven the line does not reach are 125, 137, 151, 155, 158,
159 and 167.

**The two-part signature, decided here so a partial match reads as a partial match.**

| outcome | signature |
| --- | --- |
| steps with the records | the six heights are 123, 163, 163, 146, 146 and 96, each within 1 mm, AND their differences are +40, 0, -17, 0, -50, each within 1 mm |
| stays flat | the six heights are equal to one another within 1 mm |
| neither | anything else, reported as the six numbers it is |
| no surface | the sampler returns null at a walking-line point |

The millimetre is not a judgement about what is acceptable; it is what the carve can lose. Support
triangles are cut with their heights taken from the source triangle's own plane and floored, so a
sample between two carved vertices can read up to a millimetre below the plane the records state.
Where the two agree exactly, that is reported as exact rather than as within tolerance.

**What each outcome is answered with, fixed before the run.**

- *Steps.* Report the distribution of differences over every footway station the place states inside
  the tile, not only the six, so one lucky line cannot decide it. Then state what is still untested:
  whether a walker can WALK a 40 mm and a 50 mm step, which is the controller's rule and not the
  surface's, and the seven walking lines this line does not reach.
- *Flat.* Report the constant, and then ask the container which triangle covers each of the six
  points and print its three vertices. A constant is a circumstance; the triangle is the cause, and
  this project has paid for the difference more than once.
- *Neither.* Report the six numbers and the covering triangles, and name no mechanism that is not
  read out of the container.
- *No surface.* Report which points, and what record covers that plan point by extent. An absence
  has at least two explanations and the records can say which.

**What is not predicted.** What the line reads over the two carriageways and the two blocks of
buildings between the streets. The nav envelope is carved to keep a capsule clear of what obstructs
it and the records' footway strips stop at the frontage, so the two are not measuring the same
surface there; that stretch is reported as a profile and not as an agreement or a disagreement.

**What this line cannot answer.** Whether a person could walk it. It crosses two carriageways and
two blocks, so it is a line through a surface, not a route. It also passes 795 mm east of one tree
trunk at y 68,549 and 795 mm west of another at y 115,451, and 18 mm east of the first one's pit, so
a gap in support near those two y values is the tree carve and is expected. Both walking-line points
on those two curbs are 1,923 mm from the nearer trunk, which is clear of the 1,153 mm the record
states as that tree's exclusion radius even before a capsule radius is added to it.

**Two sentences of this section's opening paragraph were corrected after the run, and neither is a
parameter.**
It said the two curbs of a segment "can differ by 50 mm", which is what this line crosses and not
what the street states: all 23 segments differ, from 2 mm to 63 mm. And it said every walk taken on
this city had run along one curb, which is not something this lane can produce; what it can produce
is that the only walk whose parameters the repository states does. The line, the step, the six
heights, the signature and the responses are as committed.

**Which tree these numbers are true of.** They were first produced on the tree this lane branched
from, and then produced again, unchanged to the byte in both logs, on each later tree the work moved
through: a main that had carried a tile's route obstruction rings into the navigation world and
added a descriptor pin to the container reader, a main that had added the lettering catalog's
two-way check, and the tree this section was merged into. The middle of those was reproduced by the
orchestrator's own run rather than by this lane, which had inspected which paths those commits
touched and said that inspection was all it had. Neither log moves at any of them, the container's
own sha256 does not move, and the tessellator stays at 17: none of that work changes what a walk
stands on.

**What it read. The surface steps with the records.** Both halves of the signature hold. Measured by
[walking-lines-runtime.py.txt](artifacts/society/walking-lines-runtime.py.txt), whose
[log](artifacts/society/walking-lines-runtime.log.txt) is where these numbers are read from, over a
container it bakes: 11,153,540 bytes, sha256 `93df0715f5`, tessellator 17, `nav_envelope`
`35388d7849`, 96,745 walkable triangles.

| curb | walking line y | records | the runtime | difference |
| --- | --- | --- | --- | --- |
| Linden Terrace 2 right | 2,575 | 123 | 123 | 0 |
| Linden Terrace 2 left | 13,500 | 163 | 162.440 | -0.560 |
| Harbour Way 7 right | 58,500 | 163 | 162.407 | -0.593 |
| Harbour Way 7 left | 70,300 | 146 | 145.809 | -0.191 |
| Foundry Street 12 right | 113,700 | 146 | 145.809 | -0.191 |
| Foundry Street 12 left | 124,800 | 96 | 96 | 0 |

The records' differences between neighbours are 40, 0, -17, 0, -50; the runtime's are 39.44, -0.03,
-16.60, 0.00, -49.81. Every height and every difference is inside the millimetre the signature
allowed, so the runtime is not standing a walker at one height the records do not state: it carries
the step at each street and the level stretch across each block.

**The population, so one line cannot decide it.** All 284 footway stations the place states for this
tile, over six curbs and four stated heights. The runtime reads a surface at 278 of them. Counted at
a nanometre, which is far below anything the geometry means: 76 equal, 202 below by under a
millimetre, none above, none differing by a millimetre or more, furthest below 0.593 mm.

**Where the fraction of a millimetre comes from, read out of the container rather than assumed.** The
log names the triangle each of the six heights comes from and asks the records what the footway
surface is at each of its corners. Fifteen of the eighteen corners carry exactly the height the
records state at that corner's own distance across the footway; the other three are a millimetre
below, and all three belong to the two small triangles the carve left beside an obstruction, whose
heights the carve floors. So the deficit is interpolation between floored integers and nothing else.
Where the covering triangle spans the strip's own two edges, and the walking line is the middle of
the strip, the arithmetic lands on an integer and the two readings are equal rather than close: that
is the 123 and the 96.

**Six stations the runtime reads no surface at, and the place says so first.** All six are on the two
curbs whose walking line is 163, each about 1.1 m from a bench. The place's own obstruction predicate
refuses 12 walking pieces; the 16 nodes those pieces touch include all six, and no station the
runtime refuses is outside that set. None of the six carries a standing spot, so the
place already walks through them rather than standing anybody there, which is what the contract says
it does. Two implementations in two languages, sharing the grammar's numbers and no code, put the
same six points out of reach of a body.

**The gap this line was told to expect did not appear.** The parameters said a break in support near
y 68,549 and y 115,451 would be the tree carve. There is none: support runs unbroken from y 57,050 to
y 72,550 and from y 111,450 to y 126,500 at the 50 mm step, and the millimetre pass finds no stretch
without support anywhere between y 1,000 and y 125,750. The line passes 795 mm from each of those two
trunks and 18 mm outside the nearer one's pit, so it misses the carve rather than showing there is
none. An expectation written down and not met is reported here because it was written down.

**What else the line shows.** The camber crowns at z 0 at y 8,000, 64,000 and 120,000, which is
where the three street segment records put their own centrelines, each at z 0. Support stops 344 mm
inside the strip's far edge at each of the four edges a building frontage stands on, and 0 mm at the
two that are not frontages, where open ground carries on. 344 is the capsule's 340 mm radius plus
the carve's integer stepping, measured here from a second direction. The vertex that ends the north
footway of Harbour Way 7 left carries z 170 at y 72,556, and the records' own surface 5,006 mm out
across that strip is 170 as well, so both halves of the 170 that took three readings to settle are
reproduced here from one line.

**A defect in the sampler, found on the way, which is not about heights.** At a plan point lying
exactly on an edge two envelope triangles share, `navEnvelopeSupport` returns no surface: the
barycentric weight comes out at -5.551e-17 instead of 0 and both triangles are refused. Its own
comment says that a point on an edge belongs to the triangle. At 1 mm this line has 260 such
stretches, all 1 or 2 mm wide, every one refused by that same weight, all on flat ground at z 0 and
none between y 1,000 and y 125,750, which is every footway and carriageway the line crosses. The
count is a property of THIS line: x 320,000 is a terrain grid line, so the line lies along a shared
edge for its whole length. It is not only this line's problem, because `tileNavigation` picks a
tile's opening stance by probing the middle of the envelope's x span, which for this tile is that
same 320,000; it does not bite there today, since the first probe is at y 0 and y 0 has support. It
belongs to the tile runtime rather than to this producer, and it is recorded here rather than
changed here.

**Why no test holds this, and what it would take.** The shared conformance fixture carries six
curbs and its two footway shapes, 4,000 mm at 20,000 millionths and 3,500 mm at 22,858, put their
walking line at the same 95 mm: `_Kerb.footway_z` reads 95 for all six, which the records log above
prints from the fixture itself. A guard written over that
fixture would pass whether the runtime carried a height per curb or one height for the tile, which
is the shape of test this project has learned to distrust. Either the fixture gains a curb whose
walking line differs from its neighbour's, which moves the golden digests every consumer pins, or
the guard runs against a generated tile and pays for a bake. That is a decision across the
tessellator, the corridor and this producer rather than one this section should take.

**What this does not answer.** Whether a walker can WALK the steps. 40 mm and 50 mm are inside the
180 mm a walking edge may climb and inside the 0.18 m the movement rule allows, but neither number
was exercised by a moving body here; this is the surface, not the controller. And the seven walking
lines this line does not reach, 125, 137, 151, 155, 158, 159 and 167, are still only stated.

## Traffic boundary

Cars likewise remain outside the pedestrian implementation. Road movement is stated as the movement
module `exulanica-movement/roads/v1`, not connected and refused by name as `roads_not_connected`
([movement modules contract](movement-modules-contract.md#roads)). A traffic producer must supply
a separate versioned road input contract: stable road/lane/junction and movement IDs, directional
lane connectivity, permitted turns and vehicle classes, lane geometry and clearance envelopes in
the agreed coordinate frame, speed limits, right-of-way/signal rules and their effective ordering,
plus rights/source provenance and exact per-edit input digests. A vehicle policy would additionally
need explicit spawn/removal rules, stable synthetic vehicle identities, collision/occupancy and
headway rules, bounded routing, intersection arbitration, gridlock/failure reasons and deterministic
branch/seed lineage. Playback clocks must declare how pedestrian and vehicle ticks synchronize;
shared rendered coordinates alone do not establish collision safety. Historical road geometry,
rule changes and interventions must be retained for replay. Neither the pedestrian graph nor a
visual road mesh is an adequate traffic contract, and this slice supplies no vehicle simulation.
