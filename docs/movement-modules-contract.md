# Movement modules contract

Status: **WALKING AND FLIGHT BUILT; ROADS STATED AND NOT CONNECTED**.

Movement in a world is one engine module per kind of movement, chosen by data. A module states the
space it moves in, the catalog its agents come from, its clock, the bounded parameters every
agent's figures are checked against, and what it hands a renderer. Walking moves the people of a
society over a route graph; flight moves flying kinds through a saved world's air; roads are stated
and refused by name until a world has roads. A bird, a dragon and a plane are kinds of the flight
kind catalog, never code of their own.

This contract owns the module registry and its dispatch, the walking and flight steps, the air a
flight happens in, the flight kind catalog, the flight route and the flight renderer. The society's
goals, stays and replay are the [society contract](synthetic-society-contract.md)'s; where objects
declare perches and host flyers is the [world objects contract](world-objects-contract.md)'s; the
traffic simulation is the [traffic contract](traffic-contract.md)'s.

<details>
<summary>Sections</summary>

- [The registry and its dispatch](#the-registry-and-its-dispatch)
- [Walking](#walking)
- [Flight](#flight)
- [Roads](#roads)
- [A model choosing for a flyer](#a-model-choosing-for-a-flyer)
- [What movement modules do not do](#what-movement-modules-do-not-do)
- [Implementation and evidence](#implementation-and-evidence)

</details>

## The registry and its dispatch

[`exulanica/movement/movement-modules.v1.json`](../exulanica/movement/movement-modules.v1.json),
read by [`registry.py`](../exulanica/movement/registry.py), states every module once, in name
order. A row states:

| Field | Meaning |
| --- | --- |
| `module` | The identity, `exulanica-movement/<kind>/v<N>` |
| `space` | What it moves in: `ground-lattice`, `road-graph` or `air-volume`, with the input profiles it reads |
| `agents` | The catalog its agents come from, and which of its kinds, or all |
| `clock` | Its step length and whose clock it is: the society's persisted tick, a host's, or a page's |
| `parameters` | Integer bounds, a unit and a reason for each figure; with a `value` where the module uses one figure for every agent, without one where each kind states its own |
| `output` | The profile a renderer reads |
| `status` | `built`, or `not_connected` with the `refusal` a caller receives |

Every module lookup goes through `movement_module`, which refuses an identity the table does not
state with `UnknownMovementModule` naming it, and `built_module`, which also refuses a row that is
not built with `MovementModuleNotConnected` carrying the row's refusal. The code each built module
runs is one table in [`steps.py`](../exulanica/movement/steps.py), held to the built rows by a test;
a caller asks `step_of(module)` for it and never imports a step by hand. A kind's figure outside its
module's bounds is refused with `ParameterOutOfBounds` naming the module, the parameter and the
value. A row's status is a switch: whether a row is built is asked where the module is used, never
when it is imported, so the flight row is read at import and making or serving a flight asks for it
built; stated `not_connected`, it refuses there with its own refusal, which the flight route answers
as a 409, and the flying kinds and their reviewed parts still load.

The package is pure: it opens no database or store and imports neither the world, the traffic
simulation nor a model client, which an import contract in `pyproject.toml` holds. The world
composes each module's input and passes it down.

## Walking

Walking is the rule every society engine that routes its people over a graph walks by, written
once in [`walking.py`](../exulanica/movement/walking.py) and called by the purposeful society
(`exulanica-society/v2` and `v3`, [`society_planner.py`](../exulanica/world/society_planner.py))
and the living society (`v4`, [`society_living.py`](../exulanica/world/society_living.py)) through
`step_of`. Version 1 keeps its frozen seeded motion, which has no routes.

- `routes_from` is the shortest route from a node to every node it reaches: integer edge lengths,
  ties broken by the lexicographically least node path.
- `traverse` spends a travel budget along a route one edge at a time and yields each leg: how far
  along the edge the walker got and the point it reached, interpolated with integer floor division.
  It advances the route's position and nothing else; each engine keeps the state shape its own
  history was recorded in, including the living society's crossings.

The walking row declares the figures the society records: `new_society_budget_mm_per_tick`, 60,000
mm, the budget a new purposeful society records; `clearance_mm`, 450, how far a walker's centre
keeps from anything that blocks walking; and `budget_mm_per_tick`, from 1 to 10^9, the bound a
purposeful society's recorded budget is checked against when it advances. The living routine's
walk speeds lie inside the same bound, which a test holds rather than the routine's loader. The
walking arithmetic is the planner's
own, moved and not changed, so every stored society replays byte for byte: a saved world's v2
history (`tests/test_society_v2_history_replay.py`), the living society's genesis and minute-60
digests (`tests/test_society_living_unchanged.py`) and the recorder's minute-180 digest
(`tests/test_society_choice_seam.py`) hold, and a spy in the step table sees every walk both
engines take (`tests/test_movement_modules.py`). Every recorded history walks edges that run along
one axis, where the division is exact, so the floor division itself is held by a walk that stops
part way along a diagonal edge, in the same file.

## Flight

### The air

A flight happens in a saved world's air volume ([`air.py`](../exulanica/movement/air.py)):
horizontally the ground's own area, read where its ground module states an extent and declared where
it states none, the same area the society declares
([saved world ground](synthetic-society-contract.md#a-saved-worlds-own-ground)), reduced to whole
cells; vertically from the ground's elevation to the module's declared `ceiling_mm`, 12,000 mm, twice
the tallest placeable kind.

The volume is divided into 500 mm cells (`cell_mm`), half-open on every axis so each point belongs
to exactly one. A cell is solid when any part of any placed object touches it once the part is grown
by the air's clearance: every part of the object's catalog recipe is turned by the object's yaw with
a fixed-point integer sine and cosine, scaled and placed, its bounds rounded outward to the
millimetre and grown on every side by half the widest flying kind's span, 140 mm for the small bird,
and every cell those closed bounds meet is marked. A flyer is a point that keeps to free cells, so
its whole body keeps out of every part. That is conservative: a crown or a lamp head blocks more air
than it fills, never less. An object moving along a bounded path is solid over its whole travel. The
grid keeps, for each solid cell, the objects that touch it. Air of more than `max_cells` cells
(262,144, a 52 m square ground to the ceiling) or built from more than `max_parts` parts (2,048) is
refused as `flight_world_too_large`, before any flight is computed.

### Perches

A perch is a point a kind of the [world object catalog](world-objects-contract.md#perches-and-hosted-flyers)
declares on the upper surface of one of its parts, placed with the object. Above it runs its column:
the cells from the perch up to its approach point, `approach_height_mm` above it for a kind. The
solid cells at the foot of the column are the perch's own: touched by the perch's own object alone,
and passable only to the one flyer landing on, perching at or taking off from it. A column cell any
other object touches, a lamp head turned over a crown or a neighbouring crown whose grown cells reach
the column, refuses the perch as `perch_approach_blocked`, so no landing passes through another
object. Every
cell above the perch's own must be free, and the approach point must lie inside the volume and the
kind's altitude band. A perch a kind cannot use is kept with the reason for that kind:
`perch_too_narrow` (the kind is wider than the span the perch bears), `perch_out_of_reach`,
`perch_approach_blocked` or `perch_moves`.

### Kinds, hosts and flyers

Each flying kind is an entry of
[`assets/catalogs/movement/flight-kind.v1.json`](../assets/catalogs/movement/flight-kind.v1.json),
read by [`flight_kinds.py`](../exulanica/world/flight_kinds.py): the module it flies by (an unknown
module, or one whose agents come from another catalog, is refused by name), a value for
every parameter the module leaves to kinds, each citing the declared sentence that says why, and the
recipes of its body and one wing in the world object catalog's `parts-v1` form. The span it states
is the span its body and wings draw. The small bird, the one kind, cruises at 5 m/s, flies between 3
m and 10 m above the ground, above the society's 1.9 m walker capsule with a metre to spare, and
perches 8 to 30 seconds at a time; its figures are declared for the scale of a square, not measured
from a bird.

Which objects host flyers, and how many, is each object kind's `hosts`; the planter tree hosts three
small birds. Every placed host brings its flyers, each starting every episode on a perch of its own
on that object. An object's perches are one pool for every kind it hosts, and the widest kinds draw
from it first, since a perch wide enough for a wide kind is wide enough for a narrower one; the
catalog checks the same pool (`check_hosts`). A flyer's identity derives from the world, its host
object, its kind and its place
among that object's flyers, so the same bird lives in the same tree from one version of the world to
the next. An object whose perches cannot start the flyers it hosts hosts none, and the flight says so
under `unplaced` with `home_perch_unusable`; the rest of the world flies. A world whose objects would
host more than `max_flyers`, 24, is refused as `too_many_flyers`, never trimmed.

A flying kind's body and wing are generated from its recipes by the same CC0 mesh writer as the world
objects, dedicated to the public domain with the texture maps they embed, and published as reviewed
components by migration 0114 (`cc0.small-bird-body`, `cc0.small-bird-wing`): nobody places them, and
the renderer fetches them by key with their digests checked.

### The step

[`flight.py`](../exulanica/movement/flight.py) moves each flyer as an integer point mass in 100 ms
steps: positions in millimetres, velocities in millimetres a second, every draw
`sha256(seed:domain:step:ordinal)` and no floating point, so the same input gives the same flight on
any machine. A flyer is in one of four states:

| State | Movement |
| --- | --- |
| `perching` | At rest on its perch for a drawn time |
| `taking_off` | Straight up its perch's column to the approach point, at its take-off rate |
| `flying` | Reynolds steering: seek and arrive toward a perch's approach point, or wander on a circle ahead holding the middle of its band; containment inside the volume and band; obstacle avoidance by looking along where it wants to go and, if that is blocked, turning to the nearest clear direction of a fixed fan of 50, slowing to half its cruise speed |
| `landing` | Straight down its perch's column onto the perch, at its landing rate |

Steering proposes; a guard decides. A flyer's turning is bounded as turning acceleration, at most its
speed times its turn rate, and its acceleration, speed, climb and descent by its kind's figures.
Before a flying move is made, every cell the closed box spanning the move meets must be free and the
new position inside the volume and the band; otherwise the flyer slides, keeping only the parts of
its velocity along which it can still move, and failing those holds where it is. Each refusal is
counted in the served `held` samples. A landing or take-off moves only inside its perch's column.

Going home, a flyer follows a route instead of steering straight at its perch: the fewest steps from
its cell to its home's approach cell over free cells of its band that share a face, found by A* when
it sets off, the Manhattan distance its estimate and ties broken toward the way travelled furthest
and then by cell, so the same state finds the same route on any machine. It aims at the furthest of
its next few waypoints it can fly straight to, slows as it nears it so it enters that cell rather
than circling it, and, held by the guard for ten steps in a row, finds its way again from where it
is. The guard still has the last word on every move.

### Choices and episodes

A flyer chooses only when its perch or its wander runs out: fly to a free perch its kind can use, or
wander for a drawn time. `allowed_choices` is that list, and every choice, the seeded chooser's
included, passes `validate_choice`, which refuses with `perch_not_declared` (no such perch in this
world, on a bench for example), the perch's own reason for this kind, `perch_taken`, `already_here`,
`action_in_progress`, `homing`, `unsupported_proposal` or `invalid_proposal_fields`.

Every flyer starts each episode of `episode_steps`, five simulated minutes, perching at its home
perch, and in the episode's last minute (`homing_steps`) goes home by its route and lands. The state
at an episode's first step is a function of the input and the episode alone, so the state at any
step is at most one episode of steps from a known one, and the next episode begins where the last
one ends. A flyer not perching at home at an episode's last step is named in the `late_home` of
every window that holds that step, never moved quietly. The next episode still starts it at home,
one move a page would draw across whatever lies between, so the independent checker holds every
flyer home at every episode's end and checks the move into every episode as any other.

### Serving and drawing

`GET /world/versions/{version_id}/flight?world_id=&from_step=&steps=` (world read,
[`world_flight.py`](../exulanica/api/routes/world_flight.py)) composes the flight from the version as
the society reads it ([`flight_input.py`](../exulanica/world/flight_input.py)) and answers
`exulanica.flight-window/v1`: per flyer and step, flat integer arrays of position, velocity, signed
turning acceleration (positive to the left), state code, wingbeat and guard refusal; the ground's
elevation; the kinds with their body and wing registry rows and how they bank and beat; and
`unplaced`. A window is 1 to `max_steps_per_request` (600) steps from a step no later than
`max_from_step` (864,000, a day of page time); beyond either the route answers 422
`flight_window_too_long` or `flight_step_out_of_range` before it composes anything. A world the
flight cannot place answers 409 `flight_unavailable` naming the object (an asset with no catalog
recipe, a behaviour with no rule, a transform no writer produces or another region), a world too
large 409 `flight_world_too_large`, and a switched-off flight row 409 with its refusal. The input is
composed once for each version state, source snapshot, reviewed registry and catalogs and kept in
process, the 16 most recent; a window resumes from the state the previous window ended on, the 64
most recent; both are shared between request threads under one lock, and neither is computed under
it. A cold window computes from its episode's genesis. The route computes in Python, which holds the
interpreter's lock while it does, so while a cold window computes the other requests the same
server answers wait their turns for that lock. On the release server, beside a cold window of 24
flyers from the step before an episode ends (484 to 521 ms over the whole request, five runs), the
slowest health answer in each run took 146 to 222 ms, against at most 9 ms alone. Those runs were
made by hand at a one-minute load of 5.4, from a copy of the pre-registered measurement with one line
fixed ([record](evaluation/2026-09-25-flight-bounds-v2.json), its departures).

Nothing is stored. The clock is the page's: the first window a page reads starts its flight at step
0, so two pages opened at different times show the same flight from its beginning. The page reads
the next window while less than 30 seconds of served steps are left, and after an edit draws the
world's new flight from its own first step
([`saved-world-flight.ts`](../web/packages/app/src/composition/saved-world-flight.ts)). A refusal the
server keeps giving for the world as it stands (a 409 or a 422) or an answer the page cannot read
stops the reading until the world is edited, and the inhabitants panel says why in one line of words.
Any other failure, among them a lapsed sign-in the page's session renews (401), too many requests
(429) and a server failure (5xx), is tried again after 5 s, then twice as long each time, up to a
minute; closing the world aborts a read in flight. The page also states the flight on its canvas for
tools: `data-flight-state` (`starting`, `flying`, `retrying` or `refused`), `data-flight-flyers`,
`data-flight-unplaced`, `data-flight-undrawn` and `data-flight-failure`.

[`flock.ts`](../web/packages/atlas-react/src/playcanvas/flight/flock.ts), owned by the saved world's
region society, draws each flyer from the served steps only: its position along the segment between
two consecutive steps, its heading from its served velocity, its bank from its served turning
(`atan(turning / g)`, at most its kind's `max_bank_mrad`), its pitch from its served climb, its wings
beating while a step says it flaps, gliding in a shallow V while it does not and swept back along its
body while it perches. It runs no steering. When the page's clock passes the last served step every
flyer holds that step and the frame is counted. Windows the clock has passed are let go as new ones
arrive. Under reduced motion every flyer stands still at the step the clock had reached when the
latest window arrived, as the crowd shows each person where a minute left them. The flock asks the
page for frames only while some flyer is off its perch at the clock's step. A kind whose parts are
not in storage is named in `data-flight-undrawn` and not drawn.

## Roads

`exulanica-movement/roads/v1` is stated with status `not_connected` and refusal
`roads_not_connected`. Road movement exists as the traffic simulation
([`exulanica/traffic`](../exulanica/traffic), [traffic contract](traffic-contract.md)), which nothing
in the application calls. Connected, its space is the compiled road network, its agents the vehicle
classes of `assets/catalogs/traffic/vehicle-class.v1.json` with their cited bounds, its step
`advance_traffic`, one simulated second a call, and its output the traffic presentation frame. The
traffic package may not import the world or this package, so the adapter that connects it sits above
both. Before vehicles appear in a world, it needs road records with lane connections, parking spaces
and signals, which no generator writes and no saved world holds; a host that owns the fleet, trip
requests, states and receipts; the society's crossing feed; a vehicle renderer; and a stated relation
between the traffic's one-second step and the society's one-minute tick.

## A model choosing for a flyer

The one choice a model could make for a flyer is where it flies next when its perch or wander runs
out: one of `allowed_choices`, a free perch its kind can use or wandering. A model's answer is a
proposal, held to `validate_choice` exactly as the seeded chooser's is, the way the society holds a
person's proposed goal to its own validation; a refused proposal would leave the choice to the seeded
chooser, with the reason kept. No model chooses for a flyer: choices a model makes have to be
recorded to replay, which needs a persisted flight run advanced by a host, and a clock shared between
viewers arrives with it.

## What movement modules do not do

- Flight is not stored and has no clock shared between viewers or with the society's minute.
- Flyers do not avoid each other; two can pass through the same point in the air. A perch holds one
  flyer at a time.
- Flyers do not see people. They keep above the society's walker capsule by their band, and every
  perch the catalog declares is above it.
- A perch is a point on a surface, not an area; a kind wider than a perch's span cannot use it.
- Flight runs over a saved world's authored ground only, not a district.
- The flight renderer draws a kind's body and one wing turned for each side; there is no skeleton or
  animation clip.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Registry, dispatch | `exulanica/movement/registry.py`, `steps.py`, `movement-modules.v1.json` | `tests/test_movement_modules.py` |
| Walking | `exulanica/movement/walking.py` | `tests/test_movement_modules.py`, the society replay pins above, `tests/test_society_living_crossings_unchanged.py` |
| Air, grid, perches | `exulanica/movement/air.py`, `fixed.py` | `tests/test_flight.py` |
| Flight step, choices, episodes | `exulanica/movement/flight.py` | `tests/test_flight.py` |
| Independent check | `exulanica/movement/flight_checks.py` | `tests/test_flight.py` (with planted violations, and the moves that join one window to the next) |
| Flight kinds, assets | `exulanica/world/flight_kinds.py`, migration 0114 | `tests/test_flight_kinds.py`, `tests/test_reviewed_asset_placeability.py` |
| Perches and hosts | `exulanica/world/object_catalog.py`, `world-object.v3.json` | `tests/test_world_object_perches.py` |
| Composition, route | `exulanica/world/flight_input.py`, `exulanica/api/routes/world_flight.py` | `tests/test_world_flight_api.py` |
| Page and renderer | `web/packages/app/src/flight-api.ts`, `composition/saved-world-flight.ts`, `web/packages/atlas-react/src/playcanvas/flight/` | `flight-api.test.ts`, `saved-world-flight.test.ts`, `environment-selection-flight.test.ts`, `flight-flock.test.ts`, `authored-society-flight-assets.test.ts` |
| Measurement | `scripts/measure_flight_bounds.py` | `tests/test_flight_bounds_record.py` |

The first flight bounds registration
([pre-registration](evaluation/2026-09-25-flight-bounds-preregistration.json),
[record](evaluation/2026-09-25-flight-bounds.json)) failed. Its run reported every rule passed, but
its checker never tested whether a flyer was home when an episode ended, skipped the move into an
episode, checked each window alone and let a landing pass any solid cell its column called its own.
Judged again on the same windows by the corrected checker, 141 of 864 flyer episodes among the
crowded crowns ended with the flyer away from home, each put back at the next episode's first step
in one move through the crowns; the small square and the eight trees were clean, every window
replayed exactly, and 24 flyers were drawn within one 60 Hz frame on the release build (1,400
microseconds of main-thread work at the 95th percentile). The routes home, the grown air, the column
rule and the page's handling of refusals answer that record.

The second registration
([pre-registration](evaluation/2026-09-25-flight-bounds-v2-preregistration.json),
[record](evaluation/2026-09-25-flight-bounds-v2.json)) judged them on 12 seeds no run had used
before it, 30 simulated minutes each in four worlds: the small square, the eight trees, the crowded
crowns and a cluttered square. The crowded crowns fly 12 of the 24 flyers their trees host; the other
12 are unplaced as `home_perch_unusable`. It passed. The checker named no violation, every flyer was home at
all 4,536 episode ends, every window replayed exactly, and 24 flyers were drawn with 1,500
microseconds of main-thread work at the 95th percentile. Its request cost is process time of the
flight module alone, the median of five in one run that began at a one-minute load of 8.3: composing
the air took 3.6 ms for the eight trees and 9.6 ms for the cluttered square; a cold window from the
step before an episode ends 518 and 549 ms; a cold window from an episode's first step 93 and 95 ms;
a window resumed from the one before 102 and 92 ms. Only cold windows were judged; a page reads
resumed ones, which tests hold equal to the cold.

The checker is independent of the steering and the guard, not of where parts are placed. Its body
rule and its own-cells rule bound each part with `air._solid_bounds`, the function that also marks
the grid the flight steps in, and `entered_solid_cell` reads that grid itself. A catalog part placed
wrongly would be wrong in both, and neither record could see it.
