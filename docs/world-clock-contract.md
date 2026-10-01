# World clock

Status: **LEGACY TIMING FOR EVERY WORLD VERSION; COUPLED TIMING BY AN EXPLICIT TRANSITION**.

A world version's clock says which timeline each of its systems runs on: its society, its traffic
and its flight. This contract owns the clock's profiles and their catalog, the one-way transition,
the eras and timelines a coupled version keeps, the ordering between a walker's minute and
traffic's seconds, the crossing occupancy a society minute records, the feed traffic reads from it,
how coupled traffic is sealed and read, what pausing, speed, stepping, resuming and catching up mean
under each profile, and the clock's reads and routes. The society's engines and playback controls
are the [synthetic society contract](synthetic-society-contract.md)'s; the traffic simulation, its
crossing input and its served windows are the [traffic contract](traffic-contract.md)'s; flight is
the [movement modules contract](movement-modules-contract.md#flight)'s; a model deciding for a
signal is the [decision roles contract](decision-roles-contract.md)'s.

<details>
<summary>Sections</summary>

- [In plain words](#in-plain-words)
- [Profiles](#profiles)
- [World seconds, eras and timelines](#world-seconds-eras-and-timelines)
- [The transition](#the-transition)
- [Walkers first, traffic after](#walkers-first-traffic-after)
- [Crossing occupancy](#crossing-occupancy)
- [The crossing feed](#the-crossing-feed)
- [Coupled traffic](#coupled-traffic)
- [Coupled flight](#coupled-flight)
- [Pause, speed, step, resume and catching up](#pause-speed-step-resume-and-catching-up)
- [Reads and routes](#reads-and-routes)
- [What the database holds and refuses](#what-the-database-holds-and-refuses)
- [Demand and progress](#demand-and-progress)
- [Interactions not supported](#interactions-not-supported)
- [Implementation and evidence](#implementation-and-evidence)

</details>

## In plain words

Until someone couples it, a world keeps the timing it has always had: its people live their
simulated minutes, as fast as the playback plays them or one at a time, while its cars and birds
keep the wall clock, and no car sees a person crossing the street. Coupling puts all three on one
timeline, the people's. Pause the people and the cars and birds stop too; step one minute and all
three move one minute. Cars then see the people: every car yields to every person the society
recorded on a crossing, because traffic is only ever computed after the people's minutes it
depends on are committed. Nobody waits for a car; cars wait for people.

## Profiles

Two profiles are stated in [`world-clock-profile.v1.json`](../assets/catalogs/world-clock/world-clock-profile.v1.json)
and read by `clock_profiles` in [`world_clock.py`](../exulanica/world/world_clock.py), which
checks that each profile restates the society's tick, traffic's lookahead and the playback's
catch-up bound exactly as those systems define them.

| | `exulanica.world-clock/legacy-v1` | `exulanica.world-clock/coupled-v1` |
| --- | --- | --- |
| Which versions | Every version without a clock row, which is every version until a transition | A version after its transition, for good |
| Time authority | Each system its own: the society's tick, and shared real time for traffic and flight | The society's tick alone |
| Traffic | Unix seconds, windows `exulanica.traffic-window/v2`, no crossing fed | The version's traffic timeline, windows `exulanica.traffic-window/v3`, the society's crossings fed |
| Flight | Unix 100 ms steps, windows `exulanica.flight-window/v1` | The version's flight timeline, windows `exulanica.flight-window/v2` |
| Lead | None | 2 society minutes over sealed traffic, with roads; none without |
| Crossings | Vehicles do not see walkers | Vehicles yield to the society's recorded crossing occupancy |

The lead is the least that lets traffic advance: a traffic minute needs the society's minute after
it (below), and sealing it needs room for one more.

## World seconds, eras and timelines

**World seconds.** The society state at tick `N` stands at world second `60 N`, and the minute that
produces tick `N` covers world seconds `[60 (N - 1), 60 N)`. A crossing a walker entered in that
minute, `arrival_second` into it, is at world second `60 (N - 1) + arrival_second`.

**Eras.** A transition opens era 1 at the society's tick `T0`, world second `W0 = 60 T0`.

**Timelines.** Traffic's sealed minutes, its episodes and its signal choices are keyed by the
version's traffic timeline: Unix seconds while the version is legacy, and `U0 + (w - W0)` in a
coupled era. `U0` (`timeline_origin`) is the first whole 1,200-second traffic episode strictly after
both the database clock at the transition and the end of the version's last sealed legacy
segment, so the timeline never runs backwards within a version and a legacy row can never share a
second with a coupled one. The first coupled minute is traffic's first minute of an episode. A
flight step is a tenth of a traffic timeline second: `10 U0 + 10 (w - W0)`, and flight's
five-minute episodes divide traffic's twenty.

## The transition

`PUT /world/versions/{version_id}/clock` with `{base_revision, profile: "coupled"}` couples the
version from its society's current tick. It is one-way: to have legacy timing again, make a new
version, which starts a new society anyway. A version with no roads couples its society and its
flight. A version whose records state roads also couples its traffic, after the roads are
compiled in the traffic worker and before the transition's transaction takes any lock.

Refused, with nothing written, as 409 unless stated:

| Code | When |
| --- | --- |
| `stale_clock_revision` | `base_revision` is not the clock's revision (0 while legacy) |
| `clock_already_coupled` | The version's clock is coupled |
| `clock_requires_society` | The version holds no society |
| `clock_society_not_playable` | The society's engine is advanced by hand only |
| `clock_tick_seconds_unsupported` | The society's tick is not sixty simulated seconds |
| `clock_transition_requires_pause` | The society is playing, or a playback claim still holds its lease |
| `clock_crossings_unsupported` | The world states roads and its society's engine records no crossing its people make: a purposeful society over a town |
| `clock_crossings_unmapped` | A crossing the society's place walks is no band of the compiled roads, by record identity |
| `roads_unavailable`, `roads_world_too_large`, `generated_world_*` | The traffic compiler's or the reader's refusal: a world cannot couple traffic it cannot drive |
| `clock_transition_unsupported` (422) | Another profile |

On the small town preset's development identity 0, the living town's place walks exactly the
crossings its compiled roads carry as bands, all of them crosswalks at junctions
(`tests/test_world_clock.py`).

## Walkers first, traffic after

The traffic step admits a vehicle only when no walker is due on its crossings before it can clear
them, and refuses a clearance longer than sixty seconds; a step at second `t` needs the crossing
feed to reach `t + 60` ([traffic contract](traffic-contract.md#a-second)). In a coupled era:

1. A society minute commits its crossing occupancy (below) and moves the clock's society head in
   the minute's own transaction.
2. Traffic may complete second `t` only when the committed occupancy reaches `t + 60`: traffic's
   minute `k` needs the society's minute `k + 1`.
3. Traffic seals its minutes in order, each exactly once, each binding the occupancy it consumed.
   What the clock presents, `presented_through_tick`, is the last sealed traffic minute.
4. The society commits its minute `N` only while `N` minus the last sealed traffic minute is at most
   the lead. A minute past it is refused, 409 `clock_lead_exhausted`, by the host and by the
   database; the playback worker does not claim such a world.
5. **Late data waits.** Traffic stays at its sealed minute until the society commits the next one,
   and nothing is guessed.
6. **Missing or inconsistent data blocks.** A gap in the occupancy's minutes, an occupancy that is
   not what its committed minute makes, a crossing no band carries or two that claim one edge, a
   rebuilt minute that does not digest to what was sealed, a minute sealed differently, or roads
   whose input is no longer the era's, holds traffic `blocked` with its code
   (`crossing_occupancy_missing`, `crossing_occupancy_mismatch`, `crossing_occupancy_unmapped`,
   `crossing_edge_ambiguous`, `traffic_replay_mismatch`, `traffic_minute_sealed_differently`,
   `coupled_roads_changed`); the society waits at the lead. A block lasts for the rest of the era:
   no request lifts it, and its receipt names the code for an operator. A deployment that changes
   the traffic step or the roads compiler blocks every coupled world whose sealed minutes it can no
   longer rebuild.
7. **A lasting refusal of the roads suspends traffic for the era.** Roads the compiler refuses, or a
   world whose records no longer generate, holds traffic `unavailable` with its code; the society
   plays on without it, the clock presents the society's head, and a traffic read answers the code.
   A worker that stopped is not lasting: traffic waits and tries again.

**Walkers are never held.** The living engine's walkers do not read vehicles or signals, and a
coupled world changes no byte of what a society records. A walker held at a kerb would need traffic
computed before its minute, which the lookahead needs after it; that circle is not closed here.

## Crossing occupancy

`exulanica.crossing-occupancy/v1` (`minute_occupancy`) is recorded for every committed minute of a
coupled era whose society records crossings: a pure function of the state before the minute, the
state after it, the minute's events and the crossings of the places it read. It is every interval
in which a walker may stand on a crossing, in world seconds, inclusive, each naming the crossing
record, the person and its basis. An interval `[s, e]` protects real time `(s - 1, e + 1)`, which
is exactly what the traffic step's pedestrian rule and the independent checker's
`crossing_conflict` rule protect.

| Basis | Interval |
| --- | --- |
| `entered` | Each crossing a walker recorded entering in the minute: its recorded arrival, the floor of the true start, through its arrival plus its recorded duration, the ceiling of the walk across |
| `on_crossing_at_minute_start` | Each walker whose location at the minute's start is on a crossing edge: from the minute's start until the floor of the time the rest of the edge takes at its own speed, or through the minute when it is still on that edge at its end |

A walker always goes on forward from where it stands on an edge, from the minute's start, so the
second basis is exact. The recorded entries alone are not enough: an entry is recorded only when a
walking leg begins at a crossing's near node, so a walker that stands on a crossing, its plan
abandoned or a model having chosen that it wait, is on no entry. For walkers who keep walking the
second basis restates what the entries already cover, which the development town's minutes hold
(`tests/test_world_clock.py`).

## The crossing feed

`exulanica.crossing-feed-projection/v1` (`crossing_feeds`) turns the occupancy into one traffic
episode's `exulanica.traffic-crossing-feed/v1` input. Walkers name crossings by the city crossing
record's identity; traffic's bands name the society's crossing as `crossing:<segment ordinal>:<offset>`
and keep the record identity, so the projection maps one to the other through the compiled network
(`compute_band_identities`), and refuses a crossing no band carries. Feed `q` covers the episode's
local seconds through `60 q + 59` (feed 1 its first two minutes) and holds exactly the intervals
that begin in that span, those begun before the episode clipped to its start. What a feed holds
depends only on the occupancy, so it is the same however much of the episode is sealed; a sealed
minute `j` binds the digest of feeds 1 to `j + 1`, the ones it consumed.

## Coupled traffic

The traffic signal controller ([`traffic_signal_controller.py`](../exulanica/api/traffic_signal_controller.py))
rotates the coupled worlds with roads beside the legacy worlds with a signal choice, at most the
timing catalog's pending bound a turn, and seals at most two minutes of each a turn. For a minute
it reads the occupancy, projects the feed, runs the minute in its pure worker process from the
continuation it keeps (or, after a restart, from the episode's genesis, checking every sealed
digest on the way), asks a chosen signal model at each choice point as a legacy world does, and
seals the minute (`world_clock_traffic_minute`): its episode and segment, the occupancy it read,
the feed, decisions, frames and continuation digests, and the signal choices and phase cursors. It
stores no continuation, which runs to tens of kilobytes a minute, and it asks no model while it
holds a connection, a transaction or a lock.

A coupled minute is never late by the wall clock, because nobody is shown it before it is sealed;
a choice point is asked within the role's own deadline and the world's hourly caps, and falls back
to fixed timing, recorded, when the answer does not come. A new owner choice takes effect one
minute of preparation after the traffic already sealed, on the traffic timeline. The models read
states each signal choice's `timebase`, `world` here and `unix` in a legacy version, and judges
whether it is pending, preparing or active by the traffic the version has sealed
(`TrafficSignalRepository.present`); an accepted answer counts as active once the coupled minute
that applied it is sealed.

A window (`replay_coupled_window`) rebuilds only sealed minutes in the worker and serves them when
every digest matches: `exulanica.traffic-window/v3`, `timebase: "world"`, `crossings_fed: true`,
the sealed minutes' facts, and `clock_second` where sealed traffic ends. A read that names no
`from_second` starts at the last sealed minute, or at the era's first minute while none is sealed;
a second not yet sealed answers 409 `traffic_not_yet_sealed`.

## Coupled flight

A coupled version's flight is the same function of its step, read on the version's flight timeline:
`exulanica.flight-window/v2`, `timebase: "world"`, `clock_step` the step at the end of the minute
the clock presents. A read that names no `from_step` starts a minute before it and no earlier than
the era's first step; a window before the era or more than a minute past it answers 422
`flight_step_out_of_range`. Its birds stop when the
people stop, because the presented step moves only when a minute is committed.

## Pause, speed, step, resume and catching up

The society's playback controls stay the only controls
([persisted playback controls](synthetic-society-contract.md#persisted-playback-controls-and-bounded-host-progression)).

| | Legacy | Coupled |
| --- | --- | --- |
| Pause | The people pause; traffic and birds keep the wall clock | Every system stops: traffic seals what the society let through, and the presented minute holds |
| Speed | 1x, 2x or 4x of the host's base wait between the people's minutes | The same, for all three: a pace, never a real-time claim |
| Step | One simulated minute of the people | One minute of every system; past the lead, 409 `clock_lead_exhausted` |
| Resume | The next minute is due one interval from now | The same; paused time is never replayed |
| Catching up after downtime | The people run at most three overdue minutes a claim and discard the rest (existing). A model-controlled signal catches up at most one episode: a longer gap is left unsealed, recorded once as a `legacy_signal_gap` receipt, and the chain starts again at the current episode, every minute sealed before it unchanged. Fixed traffic and flight hold no state | The people run at most three overdue minutes a claim, and no more than the lead allows; the rest is discarded. Traffic is never further behind than the lead |
| Reopening | The people's state from its row; traffic and birds from the wall clock | The clock, the occupancy and the sealed minutes from their rows; traffic rebuilt and checked |

A playback configuration or step may pin the clock's revision (`base_clock_revision`); another
revision is refused, 409 `stale_clock_revision`, under the workspace edit lock and in the
transaction of the change it pins.

## Reads and routes

| Route | Permission | Answers |
| --- | --- | --- |
| `GET /world/versions/{version_id}/clock` | `world.read` | `exulanica.world-clock/v1`, from one snapshot: the profile, revision and era, each system's timebase, the era mapping, the society's head with its control revision, mode, speed and interval, traffic's state and sealed minute, and the minute presented with when it was presented. A legacy version answers revision 0 |
| `PUT /world/versions/{version_id}/clock` | `world.write` | The transition, [above](#the-transition) |
| `GET /world/versions/{version_id}/clock/events` | `world.read` | The clock's receipts, newest first, each held to its digest: `transitioned`, `traffic_blocked`, `traffic_unavailable`, `legacy_signal_gap` |
| `GET /world/versions/{version_id}/clock/verify?from_tick=&to_tick=` | `world.read` | `exulanica.world-clock-verification/v1`: the society replayed from its genesis, the only earlier state stored, while its whole history is within the profile's 720 ticks, every occupancy of the span rebuilt and compared; and the span's sealed traffic minutes, at most 60, rebuilt from each episode's genesis and compared. It holds no model client |

A version's capability read (`GET /world/versions/{version_id}/capabilities`) lists the coupling
write with the state and code the write itself would answer, from the same check
(`WorldClockRepository.transition_refusal`): the version's state first, and the roads compiled
only when that passes. The society's step and playback writes name the clock's `revision` as the
base their `base_clock_revision` pins.

The world states of the read are `playing`, `paused`, `waiting` (playing, and the society waits for
its traffic) and `blocked`; traffic's are `following`, `waiting_for_society`, `blocked` and
`unavailable`. A world the workspace does not hold, or a version the world does not hold, is 404
`unknown_reference`.

## What the database holds and refuses

Migration 0125 adds four workspace-scoped tables under forced row-level security. `world_clock`
holds one row per coupled version and moves only forward; `world_clock_event`,
`world_crossing_occupancy` and `world_clock_traffic_minute` are append-only. Every writer of the
clock row holds the workspace edit lock first, and nothing locks the clock row without it: the
transition, a seal and a hold then lock the version row and the clock row, and a society minute
its society row and the clock row. The database refuses on its own:

- a society head past the lead over sealed traffic, and a clock that moves back;
- an occupancy that names no committed transition of its era, or other states than it committed;
- a traffic minute out of order, off the era's timeline, or reading occupancy not yet committed;
- a legacy segment that enters a coupled era's timeline;
- a signal decision that arrives after the coupled minute holding its choice point was sealed.

## Demand and progress

**Requirement.** No transition of coupled traffic breaks the checker's `crossing_conflict` rule, or
any other, against the committed occupancy, whatever the demand. Progress is claimed only inside a
declared envelope: every window of `W` seconds holds, on each crossing, a run of at least `G` seconds
with no walker on it; inside it, no vehicle waits more than `B` seconds in a row for walkers and no
trip is blocked for them. Outside it, waits and blocked trips are reported per crossing, and no
progress is promised under unbounded pedestrian demand. `W`, `G` and `B` are 180, 62 and 240
seconds, frozen with the held-out identities in a pre-registration
([`2026-09-30-world-clock-crossings-preregistration.json`](evaluation/2026-09-30-world-clock-crossings-preregistration.json))
before any held-out run.

**Measured** ([`2026-09-30-world-clock-crossings.json`](evaluation/2026-09-30-world-clock-crossings.json),
bound to the pre-registration by digest): twelve held-out generated towns, six small and six
market towns, none excluded. Each lived 120 minutes from 06:00 and then a 120-minute coupled era,
every second of its traffic judged by the independent checker. No rule was broken under the
towns' own demand, nor under a stress that keeps every crossing occupied 15 seconds in every 20
through the first episode of two identities of each preset. Inside the envelope vehicles waited
for walkers 330 times, the longest 29 seconds, and no trip was blocked for them. Outside it they
waited 450 times, the longest 26 seconds. Under the stress 56 of 66 trips were blocked and the
longest wait was 1,100 seconds: starvation, reported and not promised against. Every crossing
the people walked is a band of their roads.

The record measures mechanics through the pure chain the coupled follower runs: the society's
minute, its occupancy, the feed, the traffic step and the checker. It measures no timing. The
database path (ordering, exactly-once seals, restart, two clients reading the same frames)
rests on the PostgreSQL tests on development towns; the held-out towns were not driven through
the database. A walker standing on a crossing, the second occupancy basis, is held by a
synthetic projection test: the living engine re-plans an abandoned walk forward at once, so no
engine case plants one.

## Interactions not supported

- Walkers obeying walk signals, or waiting for vehicles: they cross on any indication, and vehicles
  yield.
- A walker held at a kerb.
- A purposeful society over a town: it records no crossing, and coupling with roads is refused.
- A baked city's tiles (`GET /tiles/traffic`): no world version or society, so shared real time.
- Mid-block crossings: the traffic step and the projection handle them, and no town the grammar
  generates on the development identities lays one.
- Parked bicycles at footway stands and walkers.
- Flyers and anything else: the flight contract's own boundary.
- Buses, which no fleet holds; weather, economy and calendars; speeds past 4x or a real-time claim.
- Returning a coupled version to legacy timing.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Profiles, eras, occupancy, feed, envelope | [`world_clock.py`](../exulanica/world/world_clock.py), [`world-clock-profile.v1.json`](../assets/catalogs/world-clock/world-clock-profile.v1.json) | `tests/test_world_clock.py` |
| The clock's rows, transition, society minute and seal | [`world_clock_repository.py`](../exulanica/world/world_clock_repository.py), migration 0125 | `tests/test_world_clock_postgres.py` |
| The society minute's hook | `SocietyRepository.advance`, `change_presence` ([`society_repository.py`](../exulanica/world/society_repository.py)); `claim_in_workspace`, `execute` ([`society_control_repository.py`](../exulanica/world/society_control_repository.py)) | `tests/test_world_clock_postgres.py` |
| Coupled traffic and the legacy bound | [`traffic_signal_controller.py`](../exulanica/api/traffic_signal_controller.py), [`traffic_episodes.py`](../exulanica/world/traffic_episodes.py), [`traffic_signal_repository.py`](../exulanica/world/traffic_signal_repository.py) | `tests/test_world_clock_postgres.py`, `tests/test_world_clock_legacy_catchup_postgres.py`, `tests/test_signal_unreachable_point_postgres.py`, `tests/test_world_clock_asks_outside_locks.py` |
| Routes | [`world_clock.py`](../exulanica/api/routes/world_clock.py), [`world_traffic.py`](../exulanica/api/routes/world_traffic.py), [`world_flight.py`](../exulanica/api/routes/world_flight.py) | `tests/test_world_clock_postgres.py`, `tests/test_world_clock_flight_postgres.py` |
| The held-out crossing check | [`measure_world_clock_crossings.py`](../scripts/measure_world_clock_crossings.py) | [`2026-09-30-world-clock-crossings.json`](evaluation/2026-09-30-world-clock-crossings.json) |
