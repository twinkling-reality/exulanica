# Synthetic society contract

Status: **BOUNDED DETERMINISTIC SIMULATION; NOT A LEARNED SOCIETY MODEL**.

The default `exulanica-society/v1` retains seeded synthetic motion. Opt-in
`exulanica-society/v2` adds reachable goals, routes, reviewed visit/rest actions and reactions to
versioned authored inputs. Opt-in `exulanica-society/v3` adds a bounded synthetic cast with
local observations, communicated beliefs and explicitly requested, validated model proposals.
`exulanica-society/v4`, the living society, adds catalogued routines, occupancy and a
population sized to its place; the browser creates new live societies with it. All profiles are
fictional simulation, separate from personal evidence. They do not model real residents, infer
demographic facts or demonstrate general social intelligence.

## Connection to the personal world

The product direction is a persistent society inside a person's composed world. Inhabitants
interact with permitted places and authored objects through declared affordances. Personal meaning
comes from what the person brings into and changes in that world. Inhabitants never impersonate
remembered people. The Companion must explain actions from recorded goals, referenced objects and
simulation events while keeping personal evidence distinct.

The pure engine and PostgreSQL lifecycle have synthetic fixture coverage. The connected
personal-world demonstration additionally needs the server composition/rights adapter, accepted
authored edits, shared selection, renderer presentation and grounded Companion integration.
A fixture establishes mechanics, not personal relevance or visual acceptance. Default operation
remains manual. A separately hosted, explicitly enabled playback worker can advance a saved
playing v2/v3 society under the bounded lease policy below; persistence alone starts no worker.

Implementation:

- shared identity, draws, events and digests: `exulanica/world/society.py`;
- the frozen v1 engine and the fixed tables stored v1 to v3 histories depend on:
  `exulanica/world/society_legacy.py`;
- the v4 living society: `exulanica/world/society_living.py`, its routine catalogs
  `exulanica/world/society_catalogs.py` over `assets/catalogs/society/`, the place contract
  `exulanica/world/society_place.py`, the generated-city place `exulanica/world/society_city_place.py`
  and run measurements `exulanica/world/society_metrics.py`;
- purposeful policy and input validation: `exulanica/world/society_planner.py`;
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

The v1 to v3 population is 128; their pure initializer accepts 100–512. V4 sizes its
population to its place (below). The population is canonical state, independent of how many
people a renderer draws. Inhabitant UUIDv5 identities derive from
society identity and ordinal. The same society ID/seed/population preserves those identities across
profiles, but a stored society's profile and seed cannot change. The society UUID derives from its
authored version UUID with the existing `exulanica-society/v1` identity domain, including for v2 and v3.

One society belongs to one workspace, world and authored version. V2/v3 `branch_id` equals that version
UUID; the authored version supplies its user-facing name. Same-named objects in two versions remain
different targets. This slice does not fork existing simulation history. To opt in when a version
already has another profile, create a new authored version and a new society. No implicit migration,
identity substitution, tick reset or history rewrite occurs.

V1 initialization and successful transitions remain byte-compatible, pinned by deterministic digest
vectors. V1's home/work nodes are labels; its motion ignores them and has no obstacle or arrival
semantics. Replay now additionally checks every persisted v1 event against regenerated events.
Unknown engine/input profiles are refused. WMP 1.0 and the authored-world 1.0 extension still omit
society and its input/event history; they cannot resume this simulation.

## V2 input authority

The policy consumes `exulanica.society-input/v1`, a validated projection from an authorized server
composition adapter. It does not compile a second district, infer navigation, or accept geometry
from browser request JSON. Inputs contain:

- `input_seq`, beginning at 1, independent of simulation ticks;
- `world_id`, authored `version_id`, `district_id`, district interpretation and base artifact digests;
- the explicit `flatiron-local-mm` frame, east/south axes and integer millimetres;
- `authored_state: {edit_seq, delta_sha256}`;
- `bounded-sidewalk-graph/v1` nodes, undirected edges, destinations and unavailable reason;
- targets with stable `target_id`, spatial `subject_id`, `node_id`, `affordance`, `duration_ticks`,
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

Each tick is one simulated minute. Travel budget is 60,000 mm per tick, at most one metre per
simulated second. Shortest routes minimize integer edge length with lexicographic node-path ties (in every profile).
A scalar need of at least 750 prefers rest; otherwise visit is preferred. Among reachable candidates,
the policy prefers a different target from the last completed one, then lower route cost and target
ID. This is a small deterministic utility policy, not learned preference or biography.

Only two object affordances are supported: `visit` takes one subsequent tick; `rest` takes three.
Arrival starts the action timer and does not spend its first tick. Each subsequent tick validates
availability and access position before progressing. Completion reduces the scalar need by 20 for
a visit or 500 for rest, clamped at zero. No capacity, crowd avoidance, resource depletion,
conversation or newly learned relationship is implied by the v2 movement policy. Existing role/household/relationship fields
remain explicitly synthetic labels and do not create extra supported activities.

The existing envelope and synthetic inhabitant fields remain. V2 adds:

- envelope/state `branch_id`, consumed `input_seq` and `input_sha256`;
- state `movement_budget_mm_per_tick` and `seed_sha256`;
- inhabitant `goal: {kind, target_id, reason}` or null;
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

## Authored edits and inability to act

Each relevant accepted authored edit appends a full immutable input snapshot in its transaction,
even if several edits happen between simulation ticks. The next committed step consumes every input
in sequence before moving or acting. The repository checks contiguous input sequences and monotonic
authored edit cursors; the adapter must ensure no relevant accepted edit is omitted. Equal authored
cursors require equal delta digests; a rights-only input can retain the cursor.

Moving, disabling or removing a current target invalidates its plan before action use. Changed
navigation conservatively invalidates plans. New enabled reachable targets wake blocked inhabitants.
If a changed graph no longer supports the inhabitant's current node/edge position, it stops there
with `current_position_invalidated`; there is no nearest-node snap or teleport. If the same position
becomes valid after a supported restoration, planning can resume. Disconnected or absent targets
produce `no_reachable_affordance` or `no_enabled_affordance`. Unavailable dependencies pause action
with their recorded reason. Repeated unchanged blockage does not emit another event every tick.

Undo/restore is a later authored edit and input sequence. It can restore a target or route under
current authorization. It never reverses completed actions, rewinds society time, deletes events or
resurrects withdrawn sources. A move followed by undo before a tick still has two retained inputs;
replay must verify both. Earlier simulated observations remain in their original version/input scope.

## Events, persistence and replay

V2 emits `goal_selected`, `route_progressed`, `action_completed`, `replanned` and `blocked`.
Event documents contain deterministic `summary`, `synthetic: true`, profile, branch, subject, tick,
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

## Server integration and HTTP

Existing authenticated society create/read/step/events/replay routes remain. Creation optionally
selects `profile: exulanica-society/v2` or `exulanica-society/v3`; omission keeps v1. Step bodies still contain only
`base_tick` and `base_state_sha256`. Extra authoritative input JSON is rejected.

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

The Companion adapter must use the same recorded goal/action/event references, labeled simulation.
Historical answer clauses still require personal evidence; simulated visits are never evidence of
real visits. Selection/Companion integration, authored composition and live visual acceptance are
separate integration responsibilities, not capabilities inferred from a fixture.

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
these facts; they must not invent biography from a displayed label.

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
module, creating a society or configuring play never starts a worker. The host must register the
router, supply its existing input authorizer and manage worker startup/shutdown. It can explicitly
configure a fixed workspace allowlist, or opt into fresh discovery of active account-owned
workspaces through the isolated account role. Account-wide discovery is off by default and refuses
startup without configured accounts and the reviewed current-input runtime. There are no model
calls in the worker.

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
simulated seconds. The host default base wait is 1,000 ms; 1x/2x/4x request minimum waits of
1,000/500/250 ms after batch completion. Computation, polling and contention add time. The host
may configure a base of 1,000–60,000 whole milliseconds divisible by four. Each configuration
receipt retains the chosen base; changing deployment defaults does not silently rewrite saved
controls. A subsequent user configuration adopts the host's current base. Renderers may interpolate
between committed positions, but must not fabricate future goals, actions or positions as evidence.

A worker claims one due society per configured workspace per round, ordered by oldest due time
then stable society identity. Claims skip a workspace whose edit lock is busy. PostgreSQL
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
Requests require an idle/blocked/completed inhabitant, current available input, an enabled reachable
target and no other request for that inhabitant at the same state. Exact retries return the existing
envelope; changed reuse or stale bases fail without another write.

Recording a request does not advance society time. The next normal deterministic step consumes
ordered pending requests through the existing goal-policy seam. `go_to` constrains the next goal to
the target; `perform` additionally binds its existing affordance. Each request receives one
`applied`, `stale`, `unavailable`, `rejected` or `superseded` disposition and a
`user_action_requested` event. The transition binding requires the exact request, previous state,
input span, tick and event digest. Replay regenerates the disposition and event from genesis using
the stored request and original inputs; it never calls a model or treats the request itself as
completed movement.

There is no cancellation, expiry or mid-action interruption in this version. A request can direct
only the next eligible goal and ordinary navigation/action checks remain authoritative. It cannot
teleport, cross unsupported space, undo completed actions or simulation history, or replace a
withdrawn target. The current browser can inspect inhabitants and destinations but does not issue
this API, so directed-action interaction and manual acceptance remain open.

## V4 living society: routines, places and occupancy

V4 is a successor profile. It never changes v1, v2 or v3 bytes: their pinned digest vectors and
replay tests are unchanged, and the names, roles, `home:{n}`/`work:{n}` labels, fixed weather and
resources blocks and the 300 m wander bound those profiles hash now live only in
`society_legacy.py`, labelled as a frozen encoding that exists so stored histories replay.

**Routine as data.** Needs, activities, capacity rules, the premises use-class mapping and policy
values live in versioned catalogs under `assets/catalogs/society/`, in the city grammar's
catalog envelope, each entry with a licence and a stated reason. A society records the catalog
versions and their digest, and refuses to advance under a different digest, so a routine change
is a new catalog version. Five needs (rest, leisure, a meal, shopping, sleep) grow each simulated
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
along shortest graph routes, from spot to access node, along edges and onto its target spot. An
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
tables, playback controls and replay. Typed user actions and model decisions remain v2/v3 and v3
features; v4 refuses them.

**Rendering.** The app draws the whole population by distance: up to 24 nearest outdoor
inhabitants as full characters (the native character runtime's resident limit) and every other
outdoor inhabitant within 700 m as a simple instanced figure of the same identity, one draw call
per palette. Indoor inhabitants are counted, not drawn. People at the same position are all drawn
there. A v4 inhabitant walks its recorded path from the start of the interval at its recorded
speed and stops where the path ends; nothing is interpolated off the path. The development
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

## Traffic boundary

Cars likewise remain outside the pedestrian implementation. A future traffic producer must supply
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
