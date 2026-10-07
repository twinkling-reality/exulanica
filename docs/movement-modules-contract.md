# Movement modules contract

Status: **WALKING, FLIGHT, FLIGHT FOR BEINGS AND ROADS BUILT; ROADS SERVED FOR A BAKED CITY ON THE DEVELOPMENT PREVIEW**.
No engine calls flight for beings; its air is composed from a saved world's own ground, not yet
from a town's.

Movement in a world is one engine module per kind of movement, chosen by data. A module states the
space it moves in, the catalog its agents come from, its clock, the bounded parameters every agent's
figures are checked against, and what it hands a renderer. Walking moves the people of a society
over a route graph; flight moves flying kinds through a saved world's air; flight for beings flies a
world's flying things, one society minute at a time, through its air columns; roads drive vehicles
over a generated city's streets, served for a baked city on the development preview. A bird, a
dragon and a plane are kinds of the flight kind catalog, or thing kinds whose moves name flight for
beings, never code of their own.

This contract owns the module registry and its dispatch, the walking and flight steps, the air a
flight happens in, the flight kind catalog, the flight route and the flight renderer, and the flight
for beings step and the air columns it reads. The society's goals, stays and replay are the
[society contract](synthetic-society-contract.md)'s; where objects declare perches and host flyers
is the [world objects contract](world-objects-contract.md)'s; the traffic simulation is the
[traffic contract](traffic-contract.md)'s.

<details>
<summary>Sections</summary>

- [The registry and its dispatch](#the-registry-and-its-dispatch)
- [Walking](#walking)
- [Flight](#flight)
- [Flight for beings (v2)](#flight-for-beings-v2)
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
| `space` | What it moves in: `ground-lattice`, `road-graph`, `air-volume` or `air-columns`, with the input profiles it reads |
| `agents` | The catalog its agents come from, and which of its kinds, or all |
| `clock` | Its step length and whose clock it is: the society's persisted tick, a host's, or shared real time (`wall`) |
| `parameters` | Integer bounds, a unit and a reason for each figure; with a `value` where the module uses one figure for every agent, without one where each kind states its own |
| `output` | The profile a renderer reads |
| `status` | `built`, or `not_connected` with the `refusal` a caller receives |

Every module lookup goes through `movement_module`, which refuses an identity the table does not
state with `UnknownMovementModule` naming it, and `built_module`, which also refuses a row that is
not built with `MovementModuleNotConnected` carrying the row's refusal. The code each built module
runs is one table in [`steps.py`](../exulanica/movement/steps.py); a built module whose step runs in
a host above this package, as roads' does, is named in its `HOSTED` table with that host instead,
and a test holds the two tables together to exactly the built rows. A caller asks `step_of(module)`
for a step and never imports one by hand; a hosted module is refused there by name,
`movement_step_hosted`, with its host. A kind's figure outside its module's bounds is refused with
`ParameterOutOfBounds` naming the module, the parameter and the value. A row's status is a switch:
whether a row is built is asked where the module is used, never when it is imported, so the flight
row is read at import and making or serving a flight asks for it built; stated `not_connected`, it
refuses there with its own refusal, which the flight route answers as a 409, and the flying kinds
and their reviewed parts still load.

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
is. The guard still has the last word on every move. Its searches are bounded: a flyer searches
at most `route_searches` (3) times an episode, and one search settles at most `route_cells` (4,096)
cells, else it ends with no route. Without a route a flyer steers for its home's approach point as
the rest of its flight does, and one not home when its episode ends is named. Over twelve
development seeds in the four measured worlds no flyer searched more than twice in an episode and
no search settled more than 119 cells, so the bounds change no flight there. Unbounded, a flyer the
guard held again and again searched up to 61 times in one homing minute
(`tests/test_flight_search_bounds.py`), and a search that finds no route on the largest grid the
module admits settles every free cell of its band first.

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
every window that holds that step, never moved quietly. The next episode still starts it at home.
The page never draws that move, which may cross anything: the flyer holds where its late step left
it until the next step is due, then stands at home. The independent checker holds every flyer home
at every episode's end and checks the move into every episode as any other.

### Serving and drawing

`GET /world/versions/{version_id}/flight?world_id=&from_step=&steps=` (world read,
[`world_flight.py`](../exulanica/api/routes/world_flight.py)) composes the flight from the version as
the society reads it ([`flight_input.py`](../exulanica/world/flight_input.py)) and answers
`exulanica.flight-window/v1`: per flyer and step, flat integer arrays of position, velocity, signed
turning acceleration (positive to the left), state code, wingbeat and guard refusal; the ground's
elevation; the kinds with their body and wing registry rows and how they bank and beat; `unplaced`;
and `clock_step`, the flight's clock as the server answered. A window is 1 to
`max_steps_per_request` (600) steps from a step no more than `clock_reach_steps` (3,000, one
episode) from the flight's clock either way; a read that names no `from_step` starts at the clock's
step. Beyond either the route answers 422 `flight_window_too_long` or `flight_step_out_of_range`
before it composes anything. A world the flight cannot place answers 409 `flight_unavailable`
naming the object (an asset with no catalog recipe, a behaviour with no rule, a transform no writer
produces or another region), a world too large 409 `flight_world_too_large`, and a switched-off
flight row 409 with its refusal.

The input is composed once for each version state, source snapshot, reviewed registry and catalogs
and kept in process, the 16 most recent, shared between request threads under one lock and never
composed under it. No step is computed on a request's thread: Python runs one thread at a time, so
a flight computed there would make every other request the server answers wait. One worker process
(the episode worker, [`episode_worker.py`](../exulanica/world/episode_worker.py), bound to the
flight in [`flight_worker.py`](../exulanica/world/flight_worker.py)), started by a server's first
flight read (the standard library's process pool, spawned, importing the movement package and nothing of
the server), computes whole episodes from their genesis and hands them back packed as 32-bit
integers ([`flight_episodes.py`](../exulanica/movement/flight_episodes.py)); it rebuilds each input
from a plain wire form and refuses one whose digest differs from the server's, and ends itself when
the server's process is gone, however that ended. Episodes wait for it in the server, not in the
pool, which is handed one at a time: an episode a read waits for goes before one asked for ahead of
need, the one asked for first before a later one, and at most `QUEUE_LIMIT` (8) wait. Work ahead of
need is not queued past that bound, and a read's episode pushes out the oldest of it or, with none
to push out, is refused. A read names its version's edit sequence, and a later one for the same
world version supersedes every earlier input of it: episodes of a superseded input still waiting
are dropped and the reads waiting on them refused, its kept episodes are let go, and one being
computed as it was superseded goes to whoever waits for it and is not kept. The server keeps the 8
most recently used episodes by input digest and episode, and asks for the next episode ahead of need
whenever it serves a window, so a page reading ahead waits only on its first read. Kept episodes are
computed bytes keyed by content and grant nothing: every read still reads its world through the
database first. A request's own work is its window, cut from at most two packed episodes and encoded
by the standard library's JSON encoder one flyer to a call. A read has one deadline, 30 s after it
began, however many episodes it spans; a read whose episodes are not done by then, or whose worker
dies, is refused as 503 `flight_worker_unavailable`, which the page tries again, and the next read
starts another worker. The server's lifespan stops the worker. The server's lifespan also collects
what startup made and freezes it: a full garbage collection walks every tracked object, holding the
interpreter's lock, so no request moves while it runs, and a frozen object is never walked again.
Over about 172,000 objects once the application is imported a full collection took 33 to 36 ms in
a development measurement, named among the earlier measurements of the
[third timing registration](evaluation/2026-09-26-flight-worker-v3-preregistration.json).
Measured on the release server with 24 flyers
([record](evaluation/2026-09-26-flight-worker-v3.json)): beside a cold flight read (0.58 to 0.62 s,
the worker computing an episode), the slowest health answer in each of five runs took 2.9 to 7.7 ms,
and reading the same window again took 15.6 to 19.0 ms. With the flight computed on the request's
thread instead, the same measurement found 136 to 197 ms beside cold reads of 0.55 to 0.64 s
([record](evaluation/2026-09-26-flight-worker.json)). The worker spawns in 0.24 to
0.38 s at a server's first flight read and computes a cold 24-flyer episode in 0.46 to 1.33 s. With
the freeze, the API process's resident memory 10 s after startup was 184,464 to 203,056 KiB, and
189,008 to 203,392 KiB without it, three starts each.

Nothing is stored. Under a legacy clock the flight keeps shared real time: step n is the nth 100 ms
since the Unix epoch, and birds keep flying at normal speed while the people are paused or sped up.
Every page showing a world shows its birds in the same places at the same moment, and one computation
of an episode serves them all. A world whose clock is coupled reads the same flight on its own
timeline, `exulanica.flight-window/v2`, so its birds stop when its people stop
([world clock](world-clock-contract.md#coupled-flight)). The page's first read names no step, and its copy of the clock starts where the answer
says the server's was; every later answer sets it again when the two differ by more than two steps,
as after a sleep that stopped the page's own clock. It reads the next window while less than 30
seconds of served steps are left, from where the served steps end or, when its clock has passed
them, as in a page left in the background, from the clock; a read the server refuses as too far from
its clock (`flight_step_out_of_range`) is read again from the clock rather than taken as a refusal
([`saved-world-flight.ts`](../web/packages/app/src/composition/saved-world-flight.ts)). An edit made
on the page aborts a read in flight and draws none of the old flight, whose birds may cross what the
edit put in their way, and reads the edited world's flight at once; an answer from before the edit
is never drawn. A refusal the server keeps giving for the world as it stands (a 409, or another 422)
or an answer the page cannot read stops the reading until the world is edited, and the inhabitants
panel says why in one line of words. Any other failure, among them a lapsed sign-in the page's
session renews (401), too many requests (429) and a server failure (5xx), is tried again after 5 s,
then twice as long each time, up to a minute; closing the world aborts a read in flight. The page
also states the flight on its canvas for tools: `data-flight-state` (`starting`, `flying`,
`retrying` or `refused`), `data-flight-flyers`, `data-flight-unplaced`, `data-flight-undrawn` and
`data-flight-failure`. Flyers an object hosts that the flight could not home, listed under
`unplaced`, are said on a line of their own, built from the answer alone: for each flying kind and
reason, the kind's served title, how many, and why, as in "Small bird: 3 cannot live here; the
object meant to host them has too few usable perches." The answer names no kind of object, so
neither does the line. Every refusal code and every `unplaced` reason the server can give has words
on the page, and no other ([`test_flight_page_words.py`](../tests/test_flight_page_words.py)); one
the page does not know is shown as its code.

[`flock.ts`](../web/packages/atlas-react/src/playcanvas/flight/flock.ts), owned by the saved world's
region society, draws each flyer from the served steps only: its position along the segment between
two consecutive steps, its heading from its served velocity, its bank from its served turning
(`atan(turning / g)`, at most its kind's `max_bank_mrad`), its pitch from its served climb, its wings
beating while a step says it flaps, gliding in a shallow V while it does not and swept back along its
body while it perches. It runs no steering. A flyer a window names late is not drawn moving into the
next episode: it holds where its late step left it until the next step is due, then stands at home.
When the page's clock passes the last served step every flyer holds that step and the frame is
counted. Windows the clock has passed are let go as new ones
arrive. Under reduced motion every flyer stands still at the step the clock had reached when the
latest window arrived, as the crowd shows each person where a minute left them. The flock asks the
page for frames only while some flyer is off its perch at the clock's step. A kind whose parts are
not in storage is named in `data-flight-undrawn` and not drawn.

## Flight for beings (v2)

`exulanica-movement/flight/v2` ([`flight_v2.py`](../exulanica/movement/flight_v2.py)) flies one
flying thing of a world, a being of the things catalog, through one society minute at a time. Its
agents are the thing kinds whose `moves` name it; its clock is the society's persisted minute, inside
which it takes `steps_per_minute` (120) steps of `step_ms` (500 ms); its output is
`exulanica.flight-minute/v1`, the payload of the minute's `flew` event. It is pure and exact as
flight is: integer millimetres, millimetres a second and fixed-point turns, and no floating point, so
the same input flies the same minute on any machine.

### Air columns

The air (`exulanica.air-columns/v1`, read by `air_columns`) is a world's ground divided into square
columns, `{profile, origin_mm: [x0, y0], column_mm, columns_x, columns_y, ceiling_mm, tops_mm}`:
each column the height above the ground of the tallest solid in it, 0 where it is open, row by row
from the least corner, and each half-open so every point of the ground lies in exactly one. The
ceiling is at most the module's `ceiling_mm` (200,000 mm), and a column's side lies between
`column_minimum_mm` (2,000) and `column_maximum_mm` (8,000); `column_mm_for` gives the side for an
air from its widest flyer's span, half the span rounded up to 500 mm and held between the two. An
air of more than `max_columns` (262,144) columns is refused as
`flight_world_too_large` before any top is read, and any other document the profile does not state
as `invalid_air_columns`. Its digest is the SHA-256 of its canonical document, and every minute's
outcome names the air it was flown in by it.

A column is flyable for a kind when its top and the kind's clearance are at most the ceiling. A
flyer's body is the square of half its span, rounded up, around its position; the columns that square
meets are the columns under it.

### A flying thing's figures and state

Each kind states its own value, inside the row's bounds, for `cruise_mm_per_s`, `climb_mm_per_s`,
`descent_mm_per_s`, `turn_rate_mrad_per_s`, `acceleration_mm_per_s2`, `clearance_mm` (above the tops
of the columns under it), `band_minimum_mm` (the lowest it cruises above the ground), `span_mm` and
`hovers`: 1 for a kind that can hold still in the air, 0 for a winged kind. `flyer_figures` refuses a
value outside the bounds with `ParameterOutOfBounds` naming the module, the parameter and the value,
and figures that do not state exactly these as `invalid_flight_figures`. A kind's smallest turn is its
cruise speed over its turn rate.

A flying being's state is the things engine's, with optional fields only: `position_mm` `[x, y]`
along the ground, `mode` (`flight` while airborne, `walking` on the ground), and while in flight
`height_mm` above the ground and `velocity_mm_s` `[vx, vy, vz]`, `z` up, absent at rest. Its
`thing_id` names its draw. A minute replaces the movement fields and keeps every other field of the
state as it was. A state that does not have this
shape is refused as `invalid_flyer`, and one standing outside the air as `flyer_outside_air`.

### A minute's steps

`fly_minute(air, flyer, goal, figures, seed, tick, ordinal)` answers the flyer's state after the
minute, a waypoint `[x, y, height]` at the end of each simulated second (60 of them, every second
step) and the minute's outcome. Each step steers by Reynolds steering, as flight does: the goal gives
a desired velocity, and the step changes the velocity toward it. The part of the change along the
heading changes the speed by at most the kind's acceleration over the step; the part across turns the
heading toward the desired one by at most its turn rate over the step, never past it, so the turning
acceleration is at most speed times turn rate; the speed is at most the cruise speed. From rest the
velocity sets off toward the desired one within the acceleration.

The height a flyer aims at is what its goal asks, its band for cruising, or its clearance above the
tallest flyable column under its body now and in the next three seconds along its heading and along
the way it wants to go, where that is higher, and never above the ceiling. Columns it cannot fly over
are left to its route and the guard. Where a column ahead on the way it wants to go needs it higher
than it is, it slows so that it climbs that far before it gets there. Its vertical speed moves
toward the height within its climb and descent rates, by at most its acceleration a step and never
faster than it can stop at the height.

**The guard has the last word.** A step is taken whole only when the box its body sweeps, from where
it starts to where it ends, lies inside the air, under the ceiling and, at the lower of its two
heights, at least its clearance above every top the box meets; while a flyer lands or takes off, open
ground asks for no clearance. Otherwise the flyer slides, keeping only the parts of its move that
stay legal, level first, then vertical, then along each axis of the ground; failing those it holds
where it is, at rest. Each such step is counted in the outcome's `held_steps`. A flyer that starts a
step where it may not be, as when a column was placed under it since its last minute, takes its
steered move only where it ends where the flyer may be, and otherwise climbs straight up toward its
clearance where the ceiling leaves room, comes straight down under the ceiling, or moves out from
under the columns it cannot fly over and in from the air's sides; each of those steps is held.

### Routes over columns

Where the straight way from the flyer to where it first meets its goal, the point where its way
touches a circle or a landing point, crosses a column it cannot fly over or leaves the air, it
follows a route: an A* search over the columns a body centred on lies over flyable columns only, from
its own column to the goal's, four neighbours, the Manhattan distance to the goal's column its
estimate, ties broken toward the way travelled and then by column. A route to a circle ends at
any such column whose centre lies within a column of the circle; a route to a landing ends at the
landing point's own column. A search that settles `route_cells` (16,384) columns without arriving
ends with none, and the goal is refused as `no_route`. The flyer passes each waypoint, a column's
centre, whose column it reaches, and aims at the furthest of its next eight it can fly straight to,
slowing to as little as a quarter of its cruise speed where it must turn a right angle or more. A
route is found again at each minute's start from the state, and never stored.

### Goals

The goals are the things engine's primitives, each a document naming its `kind`:

| Goal | Fields | Flight |
| --- | --- | --- |
| `go_near` | `point_mm`, `within_mm` | Flies at its band to the point and circles it at the larger of `within_mm` and its smallest turn |
| `keep_near` | `target_id`, `point_mm`, `within_mm` | The same around the target's position this minute; `point_mm` null when the target is gone |
| `circle` | `point_mm`, `radius_mm` | An orbit at its band at the larger of `radius_mm` and its smallest turn, entered toward the point where its way touches the circle |
| `land` | `point_mm` | Comes down onto the point and becomes `walking` at height 0 |
| `take_off` | none | Climbs from the ground to its band, then stays there |
| `stay` | none | Circles where it is, or, for a kind that hovers, slows to rest where it is |

A flyer goes round a circle the way it is already going round its centre, at nine tenths of the
fastest speed its turn holds on the circle, so its turning keeps a tenth in hand to hold the radius.
A circle that, as wide as the flyer's body, leaves the air or crosses a column the kind cannot fly
over is refused as `circle_blocked`, for `go_near` and `keep_near` as for `circle`. A goal near a
point is reached when the flyer ends the minute within its circle's radius and a slack, a quarter of
the radius and at least a column, and a circle when it ends the minute within that slack of it.

A landing is refused as `no_room_to_land` unless every column within half the flyer's span of the
point lies in the air and is open. It follows a glide path toward the point, its height its descent
over its cruise speed for each millimetre beyond 250 mm from the point and never above its band,
slowing as it nears the point so that its turn can follow it. A winged flyer within two of its
smallest turns of the point and above the glide path there circles the point at its smallest turn,
descending, where every column under that circle is open; elsewhere, and for a kind that hovers, it
comes to the point and down. Within 250 mm of the point and one step's descent of the ground it
touches down on the point: its mode becomes `walking`, its height and velocity go, and a `landed`
event carries the millisecond of the minute at which the step it touched down in began, 0 to
59,500, as every event of a minute falls from 0 to 59,999.

A flyer on the ground given any goal but `stay` takes off first. A take-off is refused as
`no_room_to_rise` unless every column within half its span of where it stands lies in the air and is
open and its clearance is under the ceiling; it leaves the ground at the minute's start, with a
`took_off` event at 0 ms. It climbs to its band, a winged kind around the circle of its smallest turn
through where it stood where every column under that circle is open and straight up otherwise, a
kind that hovers straight up; a flyer that starts a minute below its clearance over open ground is
still taking off. While landing or taking off it may be lower than its clearance over open ground,
and nowhere else.

A winged flyer told to stay circles where it is: around the circle of its smallest turn through its
position, to its left where it can fly over every column under that circle, else to its right, else
at three quarters, a half and a quarter of that radius, flown as much slower; where no circle fits it
slows to rest. A kind that hovers slows to rest at its height, and a flyer on the ground stays there.
A goal of any other kind is refused as `not_served_by_module`; `keep_near` with no point as
`target_gone`, and with a point outside the air as `lost_target`; `go_near` to a point outside the air
as `no_route`. A refused goal's minute is flown as `stay`. A goal document its primitive does not
state is refused, raised as `invalid_flight_goal`.

### The outcome

| Field | Meaning |
| --- | --- |
| `profile`, `module` | `exulanica.flight-minute/v1` and `exulanica-movement/flight/v2` |
| `goal` | The goal's kind, as given |
| `status` | `reached` where the goal holds at the minute's end, `under_way` where it does not yet, or `refused` |
| `refusal` | The refusal's name, or null |
| `waypoints_mm` | The 60 waypoints, as the minute also answers them |
| `events` | `took_off` and `landed`, each with `at_ms`, the millisecond of the minute it happened at |
| `held_steps` | Steps the guard took less of than steering proposed |
| `air_sha256` | The digest of the air the minute was flown in |

The minute's one draw is `sha256(seed:flight:<thing_id>:tick:ordinal)`: the heading a flyer at rest
sets off along, and the way it turns where its goal lies straight behind it or it cannot tell which
way it goes round a circle's centre. Steering needs no other. `check_flyers` refuses a world's minute
of more than `max_flyers` (24) flyers as `too_many_flyers`, for the engine that moves them to call.

### What flight for beings does not do

- No engine calls the step, and no shipped thing kind names the module: the engine that moves a
  world's things is to call it once a minute for each flying being, and a body plan that flies is to
  name it.
- No composer builds a town's air from its massing footprints and heights, and a saved world's air
  holds its placed objects but not its placed things' boxes. A saved world's air is composed by
  [`flight_air.py`](../exulanica/world/flight_air.py) `compose_air_columns`: the society's walking
  area in columns of the side the widest flyer's span gives, each the highest any part of a placed
  object reaching into it stands above the ground, the parts read as flight's input reads them
  (`placed_solids`), and an object whose geometry it cannot state refused by name as
  `flight_unavailable`.
- Flyers do not avoid each other, and they do not see people; a flyer keeps its clearance above the
  tallest solid in each column under it, however small the solid.
- A column's top stands for its whole area: a flyer keeps above the tallest thing anywhere in a
  column, and a landing or take-off needs every column within half its span open.

## Roads

`exulanica-movement/roads/v1` is built. Its space is the road network the traffic simulation
([`exulanica/traffic`](../exulanica/traffic), [traffic contract](traffic-contract.md)) compiles from a
city's street and road records and the connections and spaces it derives from them; its agents are
the vehicle classes of `assets/catalogs/traffic/vehicle-class.v1.json` with their cited bounds; its
clock is shared real time, one second a step, under a legacy world clock, and a coupled world's own
traffic timeline under a coupled one ([world clock](world-clock-contract.md)); and its output is
`exulanica.traffic-window/v2`, or `exulanica.traffic-window/v3` for a coupled world, the
traffic presentation frames of a window's seconds grouped by vehicle, and what each signal shows each
second. Its step is the simulation's
`advance_traffic`, which this package may not import, so the step runs in its host,
[`traffic_episodes.py`](../exulanica/world/traffic_episodes.py), named in `steps.HOSTED`.

Each parameter holds one value:

| Parameter | Value | What it bounds |
| --- | --- | --- |
| `episode_steps` | 1,200 | Seconds in an episode, each computed whole from the fleet parked at home |
| `departure_steps` | 600 | The first seconds of an episode, in which each vehicle leaves home once; measured so that no town's traffic locks at a junction and every vehicle is home before the episode ends |
| `dwell_steps_minimum`, `dwell_steps_maximum` | 30, 90 | How long a vehicle stays where it drove before it drives home |
| `fleet_share_permille` | 500 | The share of each parking kind's places that hosts a vehicle |
| `max_vehicles` | 120 | The most vehicles one city's traffic drives; more is refused, never trimmed |
| `max_steps_per_request` | 60 | The longest window a read answers |
| `clock_reach_steps` | 1,200 | How far from the clock, either way, a window may start |

The host, its road source, fleet and trip rules, the route and the page's reader are the traffic
contract's ([served traffic](traffic-contract.md#served-traffic)). Its episodes are computed in a
worker process by the episode worker the flight's serving uses
([`episode_worker.py`](../exulanica/world/episode_worker.py)). A saved town's own roads are
served as a baked city's are. Under a legacy clock the society's crossings are not fed to traffic,
and vehicles keep driving at normal speed while the people are paused or sped up; under a coupled
clock both follow the society's minutes.

## A model choosing for a flyer

No model chooses for a flyer. The one choice a model could make for one is where it flies next
when its perch or wander runs out: one of `allowed_choices`, a free perch its kind can use or
wandering, held to `validate_choice` exactly as the seeded chooser's is, with a refused answer
leaving the choice to the seeded chooser and its reason kept. A flyer would be a decision role
([decision roles](decision-roles-contract.md#adding-a-role)), and a role needs an engine that
stores its receipts and consumes them in its minutes, so that they replay. The flight is derived
and never stored, and viewers share its clock because its choices are drawn from its seed; a
model's choices would have to be recorded, by a persisted flight run a host advances, before
viewers could share them.

## What movement modules do not do

- Flight is not stored. Under a legacy clock it keeps shared real time, not the society's minute:
  birds keep flying at normal speed while the people are paused or sped up.
- Flyers do not avoid each other; two can pass through the same point in the air. A perch holds one
  flyer at a time.
- Flyers do not see people. They keep above the society's walker capsule by their band, and every
  perch the catalog declares is above it.
- A perch is a point on a surface, not an area; a kind wider than a perch's span cannot use it.
- Flight runs over a saved world's authored ground only: the page reads no flight for the district
  or for a world made from photographs, which has no authored scene.
- The flight renderer draws a kind's body and one wing turned for each side; there is no skeleton or
  animation clip.
- Vehicles see people only in a world whose clock is coupled, and there only as the crossing
  occupancy the society records: walkers never see vehicles.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Registry, dispatch | `exulanica/movement/registry.py`, `steps.py`, `movement-modules.v1.json` | `tests/test_movement_modules.py` |
| Walking | `exulanica/movement/walking.py` | `tests/test_movement_modules.py`, the society replay pins above, `tests/test_society_living_crossings_unchanged.py` |
| Air, grid, perches | `exulanica/movement/air.py`, `fixed.py` | `tests/test_flight.py` |
| Flight step, choices, episodes, search bounds | `exulanica/movement/flight.py` | `tests/test_flight.py`, `tests/test_flight_search_bounds.py` |
| Episodes and their worker | `exulanica/movement/flight_episodes.py`, `exulanica/world/episode_worker.py`, `exulanica/world/flight_worker.py` | `tests/test_flight_worker.py` (a real worker process, killed), `tests/test_world_flight_api.py` |
| Independent check | `exulanica/world/flight_checks.py` | `tests/test_flight_checks.py` (positive controls, the moves that join one window to the next, a placement error planted in the flight's composer, the rule that it imports nothing of the flight, and the two placements' parity) |
| Flight kinds, assets | `exulanica/world/flight_kinds.py`, migration 0114 | `tests/test_flight_kinds.py`, `tests/test_reviewed_asset_placeability.py` |
| Flight for beings: a saved world's air | `exulanica/world/flight_air.py`, `placed_solids` in `exulanica/world/flight_input.py` | `tests/test_flight_air.py` (each column's top against the independent checker's own parts over flight's four bounds worlds, the same version giving the same air, an unplaceable object and a ground too wide refused by name) |
| Flight for beings: air columns, figures, steps, guard, routes, goals | `exulanica/movement/flight_v2.py`, its row in `movement-modules.v1.json` and its step in `steps.py` | `tests/test_flight_v2.py` (every flight judged by a checker in the file that derives the columns under a body and the height it needs from the air's document alone, positive controls beside every refusal, the guard taken away and caught flying through a tower, a minute replayed in another interpreter, and a minute of 24 flyers timed and not asserted) |
| Perches and hosts | `exulanica/world/object_catalog.py`, `world-object.v3.json` | `tests/test_world_object_perches.py` |
| Composition, route | `exulanica/world/flight_input.py`, `exulanica/api/routes/world_flight.py` | `tests/test_world_flight_api.py` |
| Page and renderer | `web/packages/app/src/flight-api.ts`, `composition/saved-world-flight.ts`, `web/packages/atlas-react/src/playcanvas/flight/` | `flight-api.test.ts`, `saved-world-flight.test.ts`, `environment-selection-flight.test.ts`, `flight-flock.test.ts`, `authored-society-flight-assets.test.ts`, `tests/test_flight_page_words.py` (the page's words against the server's codes) |
| Roads host, route and page | `exulanica/world/traffic_episodes.py`, `traffic_host.py`, `exulanica/api/routes/tiles.py`, `exulanica/api/routes/world_traffic.py`, `web/packages/app/src/traffic-api.ts`, `composition/tile-traffic.ts`, `composition/generated-world.ts`, `web/packages/atlas-react/src/playcanvas/traffic/` | `tests/test_traffic_episodes.py` (a real worker process), `tests/test_tile_traffic_route.py`, `tests/test_world_traffic_route.py`, `traffic-api.test.ts`, `tile-traffic.test.ts`, `generated-world-traffic.test.ts`, `traffic-layer.test.ts`, `traffic-looks.test.ts`, `binding/tile-animating.test.ts` |
| Measurement | `scripts/measure_flight_bounds.py` | `tests/test_flight_bounds_record.py`, `tests/test_flight_worker_record.py` |

**Evidence.** Each flight record was pre-registered before its seeds were run:

| Record | What it found |
| --- | --- |
| [Flight bounds](evaluation/2026-09-25-flight-bounds.json) ([pre-registration](evaluation/2026-09-25-flight-bounds-preregistration.json)) | Failed. Its checker did not test that a flyer was home when an episode ended, skipped the move into an episode, checked each window alone and let a landing pass any solid cell its column called its own; judged again by the corrected checker, 141 of 864 flyer episodes among the crowded crowns ended with the flyer away from home. The routes home, the grown air, the column rule and the page's handling of refusals answer it. |
| [Flight bounds, second registration](evaluation/2026-09-25-flight-bounds-v2.json) ([pre-registration](evaluation/2026-09-25-flight-bounds-v2-preregistration.json)) | Passed on 12 new seeds, 30 simulated minutes each in four worlds (the small square, the eight trees, the crowded crowns and a cluttered square): no violation, every flyer home at all 4,536 episode ends, every window replayed exactly, and 24 flyers drawn with 1,500 microseconds of main-thread work at the 95th percentile. Composing the air took 3.6 to 9.6 ms, and a cold window 93 to 549 ms of the flight module's process time. |
| [Independent check](evaluation/2026-09-26-flight-independent-check.json) | The checker in `flight_checks.py`, which derives every part box, perch and cell on its own, found no violation on the second registration's seeds, and the worker served exactly the windows that registration judged, in all 48 runs. Those seeds were spent, so this is a re-judgment, not a held-out test. |
| [Flight worker](evaluation/2026-09-26-flight-worker.json) ([pre-registration](evaluation/2026-09-26-flight-worker-preregistration.json)) and its [second registration](evaluation/2026-09-26-flight-worker-v2.json) ([pre-registration](evaluation/2026-09-26-flight-worker-v2-preregistration.json)) | The flight served from its worker was correct on 12 new seeds, and both failed their timing rule: one run in five answered a health request in 30.9 ms against the rule's 25 ms, a pause inferred, not measured per run, to be the server's full garbage collection. |
| [Flight worker, third registration](evaluation/2026-09-26-flight-worker-v3.json) ([pre-registration](evaluation/2026-09-26-flight-worker-v3-preregistration.json), [erratum](evaluation/2026-09-26-flight-worker-erratum.json)) | Passed with what startup made frozen: the slowest health answer beside a cold flight read took 2.9 to 7.7 ms in all five runs. A route search that finds no route on the largest grid ends in 12 to 22 ms bounded, against 424 to 444 ms unbounded. The erratum records that the timing scripts discarded no run for machine load, and none fell below the idle rule. |
