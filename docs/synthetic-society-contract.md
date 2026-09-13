# Synthetic society contract

Status: **IMPLEMENTED BOUNDED SIMULATION; NOT A LEARNED SOCIETY MODEL**.

Exulanica's current society is a deterministic, fictional simulation attached to the bounded owned
district. It tests stable synthetic identity, persisted state, replayable events, retrieval and
bounded rendering. It does not model real residents, infer demographic facts, or demonstrate
general social intelligence.

Implementation:

- pure transition system: `exulanica/world/society.py`;
- persistence and compare-and-swap: `exulanica/world/society_repository.py`;
- API: `exulanica/api/society.py`;
- retrieval: `exulanica/selection/executor.py`;
- rendering: `web/packages/atlas-react/src/playcanvas/owned-district-runtime.ts`; and
- controls/preview: `web/packages/app/src/composition/environment-selection.ts`.

## State and identity

The engine profile is `exulanica-society/v1`. The default population is 128 and the accepted range
is 100–512. UUIDv5 inhabitant identities are derived from the society identity and ordinal. Given
the same society ID, seed and population, initialization is deterministic.

Current inhabitant state includes:

- explicit synthetic marker, ordinal and display name;
- role, household, home node and work node;
- daily departure schedule;
- two-dimensional local position and current destination;
- one scalar need; and
- up to sixteen event references.

Society state also includes household relationships, weather and two aggregate resource values.
These fields are simulation variables only. The names, roles, households and relationships are
generated from small fixed vocabularies and arithmetic rules. They are not inferred from district
evidence or population statistics.

## Transition and event semantics

One transition advances one simulated minute. It:

1. changes a destination at the configured home/work departure minute;
2. emits a deterministic `departed` event;
3. appends that event ID to bounded inhabitant memory;
4. applies a seeded, bounded two-dimensional position delta; and
5. increments the scalar need.

The repository stores current state with its digest and persists emitted events with subject,
place, world, version, tick and document digest. Updates use compare-and-swap; stale state is
refused. The transition is deterministic and uses no wall time, random service or model call.

The event log supports audit and retrieval, but current state is stored as snapshots rather than
being reconstructed exclusively from events. Consequently this is replayable deterministic
simulation with an event history, not complete event sourcing.

## Epistemic boundary

Society rows and events occupy the simulation plane and carry `synthetic: true`. Selection emits
`synthetic_inhabitant` and `simulation_event` results under the `simulation` content truth class.
Answers must say that inhabitants are simulated and events are not real-world visits.

Synthetic identities must never be resolved to observed people merely because names, embeddings,
places or motions are similar. A later fictional character inspired by personal evidence needs an
explicit authored derivation without importing private person identity into the simulation.

Simulation events may explain what happened inside a named simulation branch. They are not evidence
for claims about historical reality. Promotion into authored canon is an explicit user action that
creates a new authored assertion while preserving simulation provenance.

## Rendering boundary

The browser renders at most 24 inhabitants. This is a representation budget, not society
population. Rendered avatar identity must remain stable while visible and selection must resolve
back to the simulation subject.

Current movement is a visualization of stored or previewed positions, not route planning on a
street graph. Home and work nodes are labels rather than spatial destinations; motion is a seeded
random walk bounded to the district. The implemented capability is therefore described as
deterministic synthetic motion, not purposeful commuting, emergent social life, or physically
grounded navigation.

## Training boundary

Current society data is useful for testing APIs, replay, retrieval, rendering budgets and
counterfactual branches. It is not valid evidence about people or cities and must not be mixed into
a factual-memory training corpus.

A future learned dynamics module may propose distributions over next simulation states. Its model
version, training-data scope, branch, horizon, uncertainty and realized-vs-predicted status must be
recorded. Generated rollouts remain generated until explicitly realized by the simulator; they do
not overwrite prior simulation events.

## Package and lifecycle gaps

Society state and events are absent from WMP 1.0 and the authored-world extension. A future package
extension must define:

- complete engine/profile compatibility;
- seed and state-digest handling;
- event-chain closure and replay expectations;
- branch and counterfactual identity;
- behavior when the referenced district or authored version is unavailable;
- privacy/deletion behavior for any evidence-linked characters; and
- a receiver capability declaration for resuming versus inspecting a simulation.

## Validation gates

Complete bounded-society validation requires:

1. deterministic initialization and transition replay across supported runtimes;
2. stale-write refusal, reload continuity and event/state lineage;
3. explicit separation from observed people and historical events in retrieval;
4. stable subject selection despite the 24-avatar representation cap;
5. route and action claims no stronger than the implemented dynamics;
6. measured frame-time and memory bounds; and
7. visible behavior evaluated from live captures.

Visual motion changes do not expand the underlying society-model capability unless spatial
destinations, walkable routes and action affordances are represented in simulation state.
