# Traffic simulation

Status: **TRAFFIC V1, SERVED FOR A BAKED CITY AND FOR A SAVED TOWN**. `GET /tiles/traffic`
drives a baked city's streets on shared real time and the development page draws its vehicles on the
tile it walks; `GET /world/versions/{version_id}/traffic` drives the streets a saved world's own
records state, and the application draws them in a town a person made
([Served traffic](#served-traffic)). Nothing feeds traffic the society's crossings, and nothing
reads its events.

In this simulation, cars, vans, buses and bicycles drive a generated city's streets second by second: they keep their lanes, stop at stop lines, take turns at junctions by the junction's rule,
wait for people on crosswalks, and park. The same inputs always give the same bytes. This document
is the contract for what traffic reads, what it writes, what it refuses, and the record a renderer
draws a vehicle from.

<details>
<summary>Sections</summary>

- [In plain words](#in-plain-words)
- [What a run reads](#what-a-run-reads)
- [Reading the city](#reading-the-city)
- [Derived road records](#derived-road-records)
- [The network](#the-network)
- [A second](#a-second)
- [What a run writes](#what-a-run-writes)
- [Checks](#checks)
- [Metrics](#metrics)
- [Vehicle presentation contract](#vehicle-presentation-contract)
  - [The page's reader](#the-pages-reader)
- [Catalogs](#catalogs)
- [Served traffic](#served-traffic)
- [The layer](#the-layer)
- [Limits of v1](#limits-of-v1)
- [Where to look](#where-to-look)

</details>

## In plain words

Give traffic a city tile's road records, a seed, a fleet ("ten bicycles, four buses") and a list of
trips ("this van leaves at second 40 for that loading bay"), plus the society's list of people
stepping onto crosswalks. It answers with where every vehicle is at every second, what happened
(a vehicle entered a junction, a trip arrived, a trip was blocked and why), and a receipt that chains
each second to the one before. Nothing is random at run time and nothing is a floating-point number,
so a replay on another machine or in another process reproduces the run byte for byte.

When a tile asks for something v1 cannot drive safely, such as a corner too tight for any vehicle
or a crosswalk that shows walk while the traffic across it has green, traffic refuses the tile and
says which record and why. It never approximates.

A vehicle here is always synthetic. No record, event or presentation of it is evidence of anything.

## What a run reads

| Input | What it is |
| --- | --- |
| City road records | The city grammar's street and road records (below), of one tile or of several merged by identity, with the connections and spaces [derived](#derived-road-records) from them. Only `exulanica/traffic/city_roads.py` and `city_derivation.py` read them. |
| Traffic catalogs | Seven versioned files under `assets/catalogs/traffic`: vehicle classes, right-of-way policies, signal plans, two access mappings, the road derivation rules and the signal placement (below). |
| Seed | A string. Its SHA-256 is written into the state; the only draws are the fleet's placement, body family and colour at the start. |
| Fleet | A count per vehicle class. Vehicles start parked in spaces that admit their class. |
| Trip requests | `exulanica.traffic-trip-request/v1`: a vehicle, the second it wants to leave, and a destination, either a parking space by record identity or a society destination by its `destination_id` and frontage `street_segment_ordinal`. Numbered from 1 with no gaps. |
| Crossing feed | `exulanica.traffic-crossing-feed/v1`: which crosswalk each walker steps onto, when, and for how long, as the living society's `route_progressed` events record crossings; nothing produces a feed from them. Each feed states the last second it covers. |

A step at second `t` refuses to run unless the crossing feeds cover `t + 60`: traffic runs one society
minute behind, so no pedestrian can step onto a crosswalk a vehicle has already committed to. A
pedestrian occupies the whole crosswalk from its arrival second through arrival plus duration.

## Reading the city

`road_input_from_city(records, catalogs, city_identity=...)` turns city records into a `RoadInput`
(`exulanica/traffic/road_input.py`), the only thing the network compiler reads. It checks every
record against its own shape, every identity against the city's derivation from its owner and
ordinal, and every reference traffic follows. Anything that is not a city record is refused; a city
record of a kind below is read, and every other city kind is ignored.

| City record | What traffic takes from it |
| --- | --- |
| `city.district` | `driving_side`. Every segment's district must drive on the same side, and v1 drives on the right. |
| `city.street_node`, `city.street_segment` | Plan points, segment ends and centreline, speed limit. |
| `city.lane` | Centreline, width, direction, permitted turns, and `lane_use`, mapped to vehicle classes by `lane-use-access`. A lane whose use carries no traffic (parking, buffer) must have direction `none` and is left out; one that carries traffic must run `forward` or `backward`. |
| `city.junction`, `city.junction_approach` | The junction's control key, which is a key of `right-of-way-policy`; each approach's control and rank. |
| `city.lane_connection` | The path from one traffic lane to another through a junction, and its turn. |
| `city.signal` | Plan key, offset and groups. The plan must be in `signal-plan` and the record's `plan_catalog_sha256` must be the SHA-256 of that file's bytes. The offset must be whole seconds. A signal must control a junction: v1 has no mid-block signals. |
| `city.crossing` | Where it crosses its segment, width, and control: `signalised` exactly when a signal releases it, else marked priority. |
| `city.parking_space` | `parking_kind`, mapped to vehicle classes by `parking-kind-access`; placement (`carriageway` or `footway`); `capacity`; footprint; the traffic lane it is reached from and the stretch along the segment it is reached across. |

**Positions.** Lengths along a city polyline follow the city's rule, the floor of each piece's true
length. A crossing's centre is the segment centreline point at its offset. A parking space's access
stretch, stated along the segment, becomes positions on its access lane by projecting the segment
points onto the lane; on the straight lane pieces a stretch must lie on, that is exact.

**Capacity.** A space holds up to `capacity` vehicles of the classes it admits. A carriageway bay in
the v2 vocabulary holds one; a footway cycle stand group holds its stand count times the bicycles
per stand. Each parked vehicle stands in a `slot`, the lowest free one when it arrives. A trip may
not target a space with no free slot, and a fleet that does not fit the spaces is refused.

**What the conversion refuses**, each naming the record: a non-city record; a record that breaks its
shape; an identity its rule does not derive; one identity stated twice; a reference to a record
that is not there; a lane whose use and direction disagree; a connection to a lane that carries no
traffic; a signal plan that is not in the catalog or whose catalog bytes differ; an offset that is
not whole seconds; a signal on a mid-block crossing; districts that drive on different sides; a
parking space reached from a lane that carries no traffic; a crossing or access stretch beyond its
segment's length.

## Derived road records

The city grammar's streets stage lays lanes, junctions, approaches and crossings, and writes no lane
connection, signal or parking space. `derive_road_records(records, catalogs, city_catalogs,
city_identity=...)` in `exulanica/traffic/city_derivation.py` derives connections and spaces by rule
from the records, the city's catalogs and the `road-derivation` catalog, and hands them to the
conversion beside the city's own. With `placement_key`, it also places signals by the
`signal-placement` catalog ([below](#placed-signals)); without it, the derivation is the v1 one,
byte for byte (`tests/test_traffic_signal_placement.py` holds the corridor's derived records to
the digest the derivation gave before signals were placed). A junction the city states any connection
for gets none derived, and a curb the city states any space on gets none. Every derived record has a
city record's shape and identity, owned as the city owns its kind, and is synthetic. Derived records
are not held to the city document's checks: a connection runs from its stop line, which the streets
stage sets back before the crossing, so it reaches outside the extent its junction states (on the
corridor at version 4, all 96 connections, by up to 6.1 m), which the city's `[owner_extent]` rule
refuses in a tile document.

- **Connections.** At every junction, each traffic lane flowing in makes each movement its `turns`
  permits into the one traffic lane leaving by the leg that movement reaches: straight on, a quarter
  turn right or a quarter turn left. A straight connection is the chord from the stop line to the
  lane's start. A turn runs straight to where a tangent arc begins, round the fullest arc the corner
  admits and straight to the lane's start, the arc drawn with the catalog's chord count in exact
  integers. v1 derives only where legs meet along the plan axes, which is every junction the streets
  stage lays, and refuses another leg by name, as it refuses a movement with no lane, or more than
  one, leaving by its leg.
- **Where a space may be.** Only on an access lane of the largest set of paths a class its kind
  admits can drive round, so a vehicle can both reach a space and leave it; a lane that starts or
  ends where the records stop is off that set. A parking lane off it is left out and named.
- **Kerbside bays.** Along every lane of the catalog's bay lane use, bays of its bay parking kind
  stand end to end, each the longest that kind admits and as wide as the lane, reached from the
  traffic lane beside it: clear of that lane's junction region and conflict zones, the catalog's
  crossing clearance from every crossing band on it, and its stop-line clearance before the junction
  it runs to.
- **Cycle spaces.** Every stand of the catalog's stand category is one footway space of its stand
  parking kind: the kind's shortest footprint centred on the stand, holding the bicycles the city's
  street-furniture catalog says a stand takes, reached from the traffic lane nearest its curb. A
  stand whose access stretch meets a junction region, a zone or a crossing band is left out and
  named.

On the corridor city baked at grammar version 4 this derives 59 bays and 10 cycle spaces, the 69
spaces `tests/test_traffic_city_derivation.py` holds, and leaves out five parking lanes whose access
lanes are off the round network.

### Placed signals

The city lays no signal and no signal head. The `signal-placement` entry served traffic uses,
`high_street_crossroads`, names every junction of four legs where a segment of the high street
meets another street, as a town's high street is crossed by its cross streets; a junction the city
gives a signal keeps it, and every other junction keeps the control the city gives it. At a named
junction:

- **Phases.** Its two streets must cross, two legs each. The street the city makes the major road,
  its approaches' lowest priority rank, runs the plan's first vehicle phase and the other street the
  second; every lane connection of the junction goes with the phase of the street it comes from.
- **Walks.** A crosswalk of the junction's region walks beside the phase of the street it does not
  cross, the pairing the plan's intervals state (a walk shows while one phase is green), so a
  straight movement never crosses a walking crosswalk. Each crosswalk is a society crossing
  (`crossing:<segment ordinal>:<offset>`), so the society's walkers are named on the same crossings.
- **What it is.** The signal is traffic's own control, not a city record: the junction takes the
  one right-of-way policy whose rule is `signal`, its approaches that policy's control, and its
  crosswalks become signalised, all in the road input the compiler reads. Its identity is the city's
  identity of a signal owned by the junction, and its plan and offset are the entry's
  (`fixed_two_phase_60s`, offset 0).
- **Refused by name.** A named junction where other than two streets cross, or whose city ranks no
  one street its major road, and a placed signal for a junction or crosswalk that has one.

The derivation document names the placement and each signal's groups
(`exulanica.traffic-road-derivation/v2`).

## The network

`compile_network(road_input, catalogs)` builds the network a run drives on, named by the city record
identities it came from, or refuses with the reason. Its digest, `exulanica.traffic-network/v2`, is
written into every state.

- **Paths.** Every lane and every lane connection is a path a vehicle's front follows, with the
  classes allowed on it, a speed limit, and a corridor either side of each piece: the widest
  permitted body's half-width, plus the rear axle's off-tracking at each corner, plus the design
  vehicle's turning envelope on turning pieces.
- **Corners.** A corner's radius is the smaller of the circle through the corner and its neighbours
  and the largest fillet the two pieces fit. A class whose minimum turning radius is larger than a
  path's tightest corner is dropped from that path; a path no class can drive is refused.
- **Zones.** Two paths through one junction whose corridors meet form a zone, an interval on each.
  Vehicles on the two sides may never be inside their intervals at the same time.
- **Regions.** Crossing a stop line means reserving the junction region: the connection and the
  start of the lane it leads to, as far as any conflict zone or junction crosswalk reaches on that
  lane. A vehicle is only admitted when there is room beyond the region for its whole body and no
  other vehicle stands between it and its stop line: one it cannot pass would take that room while
  its reservation kept the other out, and neither could move again.
  A lane that leaves a junction without that room for a class is kept for the classes it has room
  for: the class with the longest body and gap is left off it, recorded in the network's
  restrictions as `body and gap do not fit beyond the junction region it leaves`, and the network
  is compiled again, until every lane fits every class it keeps.
- **Bands.** A crosswalk is a band with an interval on every path it meets, exact on a straight lane
  piece and a corridor superset on a connection. A band at a junction belongs to its region; a band
  further along a lane is a mid-block band with its own gate.
- **Network edges.** A lane may start or end at a node with no junction, where the tile's records
  stop. No vehicle enters or leaves the network there.

**What v1 refuses**, each with a message naming the records: left-hand traffic; a turn of more than
a right angle; two lanes whose corridors meet; a connection that comes near another lane's stop line
or a lane away from its joint; a crossing that is not perpendicular to a lane, lies on a curved lane
piece, or reaches a stop line; a parking access stretch on a curved piece, inside a junction region,
or across a crosswalk; a signal plan that lets two conflicting movements of equal turn rank go
together, sends a straight movement through a crosswalk while it shows walk, or gives a crosswalk
too little walking time for its length; a priority junction with more than one inbound lane on a
major approach, or a stop or yield sign on one; an uncontrolled junction with conflicting movements; a u-turn; a mid-block signal; a lane too short to
leave its junction region for the one class it has left; and a path no class can drive.

## A second

`advance_traffic(state, seed, network, catalogs, inputs)` returns the next state, that second's events
and a transition receipt. It reads no clock, draws nothing, calls no model and uses no float. In
order:

1. Consume this second's trip requests: route the trip, or block it at once with its reason
   (`unknown_vehicle`, `vehicle_busy`, `unknown_space`, `space_does_not_fit_class`,
   `destination_space_taken`, `no_parking_at_destination`, `no_route`).
2. Record signal interval changes. A signal's indication is a pure function of its plan, its offset
   and the second, so nothing about a signal is stored.
3. Finish parking manoeuvres that end now and start leaving where it is safe to.
4. Release reservations whose vehicle has cleared its region; revoke those whose vehicle can still
   stop when another vehicle without a reservation of that junction stands between it and its stop
   line, its signal is no longer green or a pedestrian is due.
5. Admit vehicles at their stop lines, junction by junction, by the junction's rule, never one with
   another vehicle standing between it and its line, such as one leaving or entering a space there.
6. Move every driving vehicle at the highest speed the safety rule, the speed caps, the destination
   and the gates allow. Decisions read the state at the start of the second, so the order vehicles
   are listed in never matters.
7. Record entries and arrivals, and block a trip whose vehicle has waited 300 seconds, with the
   reason it was waiting; it is unblocked if it moves again.

**The safety rule.** A follower may choose a speed only if, braking fully from the next second on, it
would stop behind where the vehicle ahead would be if that vehicle braked fully now, with the
minimum gap to spare. Full braking always satisfies the rule if it held a second earlier, so it holds
for the whole run.

**Right of way**, from `right-of-way-policy`:

| Policy | Rule |
| --- | --- |
| `signalised` | Enter on green, or on amber only when unable to stop. A permitted left turn gives way to oncoming traffic with a 4.1 second critical headway. |
| `priority_two_way_stop` | The major street goes first; a stop approach stops at the line first; minor movements need the catalog's critical headway to every priority vehicle that could reach its line. |
| `all_way_stop` | Every approach stops; vehicles go in the order they stopped, the vehicle on the right first on a tie. |
| `uncontrolled_continuation` | Only where no two movements from different approaches conflict. |

**Pedestrians.** A vehicle is admitted into a region only if no pedestrian is due, before the vehicle
can have cleared the region, on any crosswalk its movement crosses, and it waits at a mid-block
crosswalk's gate the same way.
At a signalised junction the compiler has already checked that no straight movement has green across
a crosswalk showing walk; vehicles still wait for every pedestrian the feed puts on a crosswalk,
because the society's walkers do not wait for a signal.

## What a run writes

**State** (`exulanica-traffic/v1`): the traffic id, the seed's SHA-256, the network and catalog
digests, the second, how many trip requests and crossing feeds were consumed, every vehicle
(class, body family, colour, mode, space and slot, trip, route and position, speed, reservation,
wait reason, and the points its front passed during the last second) and every trip (status,
reason, origin and target space, the seconds it was requested, departed, arrived or was blocked).
Every vehicle and trip carries `synthetic: true`.

**Events.** `trip_requested`, `trip_routed`, `trip_departed`, `trip_arrived`, `trip_blocked`,
`trip_unblocked`, `parking_exit_started`, `parking_entry_started`, `reservation_granted`,
`reservation_released`, `reservation_revoked`, `junction_entered` (with its delay), `crossing_entered`
(with the crossing's record identity and the society's crossing id), and `signal_interval`. Each has a
uuid5 identity over the traffic id, second, order and its document's digest.

**Receipt** (`exulanica.traffic-transition/v1`): the previous and next state digests, the digest of
the inputs consumed through this second, the event ids and their digest, and `breaches`, the list of
anything the step itself found unsafe. A correct step's list is empty.

**Replay.** The recorded inputs alone reproduce every state, event and receipt byte for byte, in the
same process and in a new process under a different `PYTHONHASHSEED`.

## Checks

`exulanica/traffic/checks.py` checks every transition from the two states and the inputs, apart from
the step and without its decisions: bodies are rebuilt from positions, indications from the plan,
stops from speeds, gaps from the catalog.

| Check | What it proves |
| --- | --- |
| `overlap` | No two bodies share interior points. A body covers its route pieces with the class's half-width, off-tracking and turning envelope, and the outside of each bend. |
| `entered_without_reservation` | A vehicle crossed a stop line or crosswalk gate only holding a reservation for it. |
| `entered_on_red` | A signalised entry happened on green or amber. |
| `did_not_stop` | A stop-controlled entry came after the vehicle stood still at the line. |
| `gap_not_given` | A yielding movement went only when every conflicting priority vehicle was further than the critical headway from its line. |
| `all_way_order` | All-way stop entries went in stopping order, right first on a tie. |
| `crossing_conflict` | No body, swept over the second, met a crosswalk while a pedestrian was on it. |

The property runs (six seeds) drive a busy fleet of 10 bicycles, 4 buses, 18 cars and 8 vans on a
five-junction test network built with the city's own record classes. Trips are requested for 15
minutes, a pedestrian steps onto each crosswalk about once a minute, and the run continues until
every trip has ended. Each run must have no violation, no breach and no speed over a cap; every
junction entered and every crosswalk walked; at least 50 trips; and every trip arrived, or blocked
with its reason. Every check kind has a negative control, a planted transition that breaks its rule
and must be caught.

## Metrics

`MetricsAccumulator` (`exulanica.traffic-metrics/v1`) reads states and events and reports integers:

- per junction, its policy, vehicles that entered, entries per simulated hour, and the mean delay per
  entry (time from reaching the approach lane to crossing the stop line, less the free-flow time for
  that distance, never below zero);
- per parking kind, the number of spaces, the places they hold together, and occupancy in parts per
  million of place-seconds;
- trips requested, arrived, blocked with reasons, still in progress, and the mean door-to-door time.

## Vehicle presentation contract

This is what a renderer reads to draw traffic, and all it may rely on. Traffic owns where a vehicle
is and what class, body family and colour it has; the renderer owns what a body family looks like.

**Frame** (`exulanica.traffic-presentation-frame/v1`), one per simulated second: `traffic_id`,
`second`, `network_sha256`, and `vehicles`, one record per vehicle in vehicle id order.

**Vehicle record** (`exulanica.traffic-vehicle-presentation/v1`):

| Field | Meaning |
| --- | --- |
| `vehicle_id` | The vehicle's uuid5 identity, stable for the run. |
| `vehicle_class` | A `vehicle-class` catalog key: `bicycle`, `city_bus`, `passenger_car` or `van`. |
| `body_family`, `colour` | Presentation keys from the class entry, drawn once per vehicle from the seed and never changed. |
| `catalog_sha256` | The traffic catalogs' digest, so a reader can prove which dimensions it was given. |
| `dimensions_mm` | `length`, `width`, `height`, `wheelbase`, `front_overhang`, `rear_overhang`, copied from the class entry so a reader needs no catalog. |
| `front_axle_mm`, `rear_axle_mm` | Integer plan points in the city tile's frame (millimetres, the road records' plan). The heading is from the rear axle to the front axle; no angle is stored. |
| `motion_path_mm` | Every point the vehicle's front passed during the second that produced this record, first and last included. |
| `mode` | `parked`, `leaving`, `driving` or `arriving`. |
| `speed_mm_per_s` | The distance moved over the last second. |
| `slot` | The place of its space a parked vehicle stands in; -1 when not parked. |
| `synthetic` | Always `true`. |

**Where the axles are.**

- *Driving.* Both axle points lie on the vehicle's route, the front axle `front_overhang` behind the
  front and the rear axle `wheelbase` further back. On a curve the body is placed on the chord
  between them, so their distance is at most the wheelbase.
- *Leaving and arriving.* The vehicle stands on its access lane at the access position, stopped,
  for the class's `parking_exit_ms` or `parking_entry_ms` rounded up to whole seconds. The
  simulation treats its body as on the lane for the whole manoeuvre, and the record shows exactly
  that.
- *Parked in a carriageway bay.* Centred in the bay, facing the way its access lane runs.
- *Parked at a footway stand group.* The footprint is divided into `capacity` equal places along its
  longer side; the vehicle is centred in place `slot`, across the footprint, front away from the
  access lane.

**Rules for a reader.**

- Draw the body from the axle points and the dimensions: the front bumper is `front_overhang`
  ahead of the front axle along the heading, the rear bumper `rear_overhang` behind the rear axle.
  The body is `width` wide and `height` tall. Traffic works in plan only, so the reader stands the
  body on the road surface it draws at those plan points.
- Between two frames, move the front along `motion_path_mm`, never across its corners, and keep the
  rear axle following the path. A frame is one simulated second; any finer timing is the reader's
  interpolation and is not simulation.
- Draw the pose the record gives. Between the bay and the lane, v1 supplies no path, so a reader
  must not invent one.
- Resolve `body_family` and `colour` through the renderer's own catalog. An unknown key is an error
  the reader reports, never a silent default.

**Not supplied in v1**, and a reader must not invent them: lamps, indicators, brake lights, wheel
angles, doors, occupants, a manoeuvre path between bay and lane, and any height other than the
catalog's.

**Signals.** The window states where each signal's heads stand and what each group shows every
second, and nothing of a head's look: a reader draws a head at each point the window names, lit as
its group's code says at the second it draws, and states its own look.

The body families and colours the catalog states:

| Class | Body families | Colours |
| --- | --- | --- |
| `bicycle` | `upright_bicycle` | `black`, `blue`, `grey`, `red`, `silver`, `white` |
| `city_bus` | `rigid_city_bus` | `blue`, `red`, `white` |
| `passenger_car` | `hatchback`, `sedan` | `black`, `blue`, `grey`, `red`, `silver`, `white` |
| `van` | `minivan`, `panel_van` | `black`, `blue`, `grey`, `red`, `silver`, `white` |

### The page's reader

`@exulanica/atlas-react/traffic` (`web/packages/atlas-react/src/playcanvas/traffic/`) is the reader
both pages use. `TrafficLayer` draws each vehicle as the figure of boxes its looks
(`vehicle-looks.ts`, `exulanica.vehicle-looks/v1`) state for its body family, proportioned to the
record's own dimensions and coloured by its colour, and refuses a body family or colour the looks
do not state (`VehicleLookError`) before it draws anything; a test holds the looks to exactly the
families and colours the catalog names. Between two seconds it moves the front along the served
path by distance and places the rear axle a wheelbase back along the trail the front left. It
stands each body on the tile's walking surface at the body's centre, and keeps a vehicle it finds
no ground for undrawn and counted. A vehicle named late at an episode's end is held where that
episode left it. While a drawn vehicle moves, the page draws every frame rather than its idle cadence.
Beside the vehicles it draws each signal's heads (`signal-lights.ts`): a post at every point the
window names, topped by a lamp lit in the colour its looks (`exulanica.signal-looks/v1`) state for
what the group shows at the second drawn, and refuses an indication the looks do not state
(`SignalLookError`) before it draws anything; a head where the drawn world has no ground is not lit.

`web/packages/app/src/composition/tile-traffic.ts` attaches the layer to a walk's tiles and reads
windows through the reader it is given: the development page's baked tile walk, reached from one
call in `composition/generated-tile.ts`, reads `GET /tiles/traffic`, and a saved town
(`composition/generated-world.ts`) reads its own world's route with the world's credential. It reads
first from the server's clock, then the next minute whenever fewer than 30 served seconds are left
ahead of it; it stops on a refusal the server will keep giving, and tries again later on any other
failure. The shell's `data-tile-traffic` attribute states the vehicles served, drawn and held
without ground, the signals served and their heads lit, the clock's second and that no walker's
crossing is fed; its counts change when a
window is read, not every frame. In a saved town a refusal the server will keep giving is said in
words on the page (`trafficRefusalWords`, the `world.traffic.*` copy), never left blank, and a page
that cannot load its traffic code opens the town without vehicles and says so.

## Catalogs

Every number traffic uses about a vehicle, a rule or a signal is in a versioned file under
`assets/catalogs/traffic`; none is a constant in code.

| File | Holds |
| --- | --- |
| `vehicle-class.v1.json` | Design dimensions, turning radius and envelope, speed caps, acceleration and deceleration, minimum gap, parking manoeuvre times, body families and colours. |
| `right-of-way-policy.v1.json` | Each junction policy's rule, approach controls, turn priority, arrival order and critical headways. |
| `signal-plan.v1.json` | `fixed_two_phase_60s`: two vehicle phases of 24 seconds green, 4 amber and 2 all-red, each with a concurrent 7 second walk and 17 second clearance, and the walking speeds used to check a crosswalk's time. |
| `lane-use-access.v1.json` | Which classes a lane of each city lane use carries. |
| `parking-kind-access.v1.json` | Which classes a parking space of each city parking kind admits. |
| `road-derivation.v1.json` | The [derivation](#derived-road-records) rules: a turning connection's arc chords, the lane use and parking kind of kerbside bays with their crossing and stop-line clearances, and the furniture category and parking kind of cycle stands. |
| `signal-placement.v1.json` | Where [signals are placed](#placed-signals): the street hierarchies and legs of a named junction, and the plan and offset its signal runs. |

**Sources.** Every entry names a source for each numeric field and each key list, exactly once:
either `cited <reference>: <where>`, where the reference's full citation is in the file's
`references`, or `declared: <reason>`. A missing, extra or unparseable source is refused when the
catalogs load, so a number cannot be added without saying where it came from. The references are
AASHTO's *A Policy on Geometric Design of Highways and Streets* (2011) for the car and bus design
vehicles, with the AASHTO passenger class (which includes vans) for the van; FHWA-HRT-04-103 for the
bicycle; the *Transit Capacity and Quality of Service Manual* (2013) for bus acceleration and
deceleration; Treiber, Hennecke and Helbing (2000) for car acceleration, comfortable deceleration and
the jam gap; the *Uniform Vehicle Code* (2000) and the MUTCD (2009, Section 4D.04) for right of way;
the *Highway Capacity Manual* (2000) for critical headways; and the MUTCD (2009 Section 4E.06, 2023
Section 4F.17) for walk, clearance, amber and all-red times.

**Licence.** Entries are written for this repository: `original`, Apache-2.0. Cited facts are facts;
the citation says where they were read.

**Digest.** The catalogs' digest covers the canonical form of all seven files, references and sources
included, and is written into every state. The SHA-256 of each file's bytes is kept as well, because
a city signal record names the signal-plan catalog by those bytes.

### Declared values

A value that cites no source is declared, with its reason in its entry's `sources`.
`declared_values` in `exulanica/traffic/catalogs.py` lists every one for review, and
`tests/test_traffic_catalogs.py` holds that list to the reviewed one (`DECLARED`), so a value
cannot become declared unnoticed. They fall into a few kinds: the presentation keys (body families
and colours), which the simulation only draws from the seed; bicycle figures and the bus's jam gap,
which no source read gives (for the bicycle: overhangs, height, jam gap, turning radius and
envelope, turning speed, wheelbase and stand times); parking manoeuvre times from a study summary
whose primary paper could not be read; class speed caps set above any urban limit, so the lane's
posted limit governs; arrival orders, and the uncontrolled continuation's rule and turn priority;
the two remaining intervals of the fixed signal plan; the lane-use and parking-kind access
mappings; and the road derivation rules, whose kerbside clearances follow the *Uniform Vehicle
Code*'s 20 feet from a crosswalk and 30 feet before a stop sign or signal without quoting it.

## Served traffic

`exulanica/world/traffic_host.py` and `traffic_episodes.py` sit above the traffic simulation and
the movement package and run the roads module, `exulanica-movement/roads/v1`
([movement modules](movement-modules-contract.md#roads)), for a generated city and for a saved town.

- **The road source.** `generated_tile_roads(repository, world_seed)` reads the current bake of
  every tile of a city seed from the tile store, holds each container to the digest its row records
  and checks it again under the final read check, and merges by identity the records every header
  carries; two copies of one record must agree. The city must be of a grammar version the city
  grammar generates. The input's version is the SHA-256 over the tiles' coordinates and container
  digests, so a rebake is a new input. Tiles are read, never delivered, so no tile quota is spent.
- **A saved world's road source.** `saved_world_roads(connection, workspace_id, world_id,
  snapshot_id)` reads the records a saved world's snapshot states, by the same converter, with no
  code for any one world. A world generated from a recipe states them through its receipt
  (`town_records` in `exulanica/world/generated_worlds.py`, generated again and held to the
  receipt's output digest); any other kind of world states none and is refused as
  `roads_not_stated`, as are records that state no lane. The input's version is the receipt's
  digest, its city identity the receipt's subject identity and its grammar version the receipt's, so
  every version of one world shares its roads.
- **The clock.** Second `n` is the `n`th second since the Unix epoch, so every page showing a city
  shows its vehicles in the same places.
- **The fleet**, by rule from the home places the derived network holds: in every parking kind, the
  roads module's `fleet_share_permille` of its places, divided among the classes the kind admits in
  the catalog's order, any remainder one each to the first. No rule gives a bus a route or a layover, so no
  bus has a home and none is in a fleet. A city whose places would host more than `max_vehicles` is
  refused as `roads_world_too_large`.
- **Episodes.** Time is cut into episodes of `episode_steps` seconds, each computed whole from the
  input and its number alone, from the genesis `initial_traffic` places the fleet in, each vehicle
  at home. Every vehicle leaves home once, at a second of the first `departure_steps` drawn from the
  seed, for a space of its class that is nobody's home, has a free place and can be driven to and
  back from; stays there for a dwell drawn from the seed; and drives home. The trip requests are
  decided second by second by that rule and recorded as the run's inputs, so an episode replays
  exactly. A vehicle not home at an episode's end is named in the window's `late_home`. The seed is
  the SHA-256 of the city's world and version keys, and the draws are `traffic_host.departure`,
  `traffic_host.destination` and `traffic_host.dwell`.
- **The worker.** Episodes are computed in a worker process of their own by the episode worker the
  flight shares (`exulanica/world/episode_worker.py`), kept by the input's digest, with the episode
  after the last one read asked for ahead of need. A request's own work is its window, cut from
  them.

`GET /tiles/traffic?world_seed=<64 hex>&from_second=<n>&seconds=<1 to 60>` answers a window,
`exulanica.traffic-window/v2`: for every vehicle its class, body family, colour and dimensions and,
for every second, its front and rear axle plan points, mode (`parked`, `leaving`, `driving`,
`arriving`), speed, slot and the path its front followed during that second; for every signal
(`exulanica.traffic-signal-presentation/v1`) its identity, its junction's and each group of its
plan with its kind, the plan points its heads stand at (level with the stop line of each lane a
vehicle group releases, beside it on the driving side just outside the corridor its vehicles sweep,
and both ends of each crosswalk a pedestrian group releases) and, every second, a code naming
what the group shows among the window's `indications`, the indication the step obeyed that second;
with `crossings_fed` false, `late_home`, and the clock's second when it answered. Without `from_second` the window starts
at the clock. It requires `tiles.materialise` and charges no tile (`SELF_CHARGING_TILE_ROUTES`).
It refuses a second before the epoch or more than `clock_reach_steps` from the clock
(`traffic_second_out_of_range`) and a window of more than 60 seconds (`traffic_window_too_long`)
with 422, a seed with no stored tiles with 404 `roads_not_stated`, roads traffic cannot drive with
409 `roads_unavailable` and the compiler's reason, and an unavailable worker with 503
`traffic_worker_unavailable`. The development page draws the answer on the tile it walks with
[the page's reader](#the-pages-reader).

`GET /world/versions/{version_id}/traffic?world_id=<world>&from_second=<n>&seconds=<1 to 60>`
answers the same window for a version of a saved world, from that world's own road source, and adds
the `world_id` and `version_id` asked for and `roads_version`, the receipt's digest. It requires
`world.read` and charges nothing. It refuses a window as the tiles route does, a version the world
does not hold with 404 `unknown_reference`, a world that states no roads with 404
`roads_not_stated`, roads traffic cannot drive with 409 `roads_unavailable` or
`roads_world_too_large`, a world whose receipt no longer generates its records with 409 by the
reader's name (`generated_world_grammar_changed`, `generated_world_catalogs_changed`,
`generated_world_output_changed` or `generated_world_unreadable`), and an unavailable worker with
503 `traffic_worker_unavailable`. The application draws the answer in the saved town.

## The layer

`exulanica.traffic` sits below the database, the store and the model client in the import-linter
layers, and a forbidden contract keeps it from `psycopg`, the database and store, the evidence spine,
ingest, migrations, identity, selection, reconstruction, capture, the world package, models, the API,
`numpy` and `torch`. It may import the grammar, because the road records are grammar records, and only
`exulanica/traffic/city_roads.py` and `city_derivation.py` do. A composition above both would pass the
society's crossing events down as data; none does. A test holds that no other traffic module imports
the city grammar, so a new city version changes those two files.

## Limits of v1

- **Right-hand traffic only**, and no lane changes between junctions: a vehicle picks its lane only
  through a junction's connections.
- **Conservative pedestrian windows.** A vehicle enters a junction only if no pedestrian is due, at
  any time from now until it has cleared the whole region, on any crosswalk its movement crosses,
  even one it would already have passed; walkers never wait for vehicles. Under a busy crossing feed
  the signalised junction of the test network passes about 150 vehicles an hour with a mean delay of
  several minutes.
- **One signal plan**, fixed time, 60 seconds; no actuation, no mid-block signals, no u-turns.
- **A priority junction's major street has one inbound lane per approach**, because the catalog's
  critical headways are for a two-lane major street.
- **Parking manoeuvres are stops on the lane**, with no path between the lane and the bay.
- **Society destinations are frontage by segment ordinal**: a trip to a society destination parks in
  the first free space on that segment, in identity order, that admits its class, not the nearest.
- **Served from generated streets only.** A generated city's stored tiles and a saved town's own
  records are the road sources, and no other kind of world states roads. No store keeps a run's
  states, and nothing feeds traffic the society's crossings or reads its events. A vehicle never
  waits for a walker the page shows.
- **Connections are derived only where legs meet along the plan axes**, spaces only as kerbside
  bays and cycle stands, and signals only where the placement names a junction, with no signal head
  a renderer could draw from records; no loading bay or bus layover is derived.

## Where to look

| Module | What it is |
| --- | --- |
| `exulanica/traffic/city_roads.py`, `road_input.py` | The converter from city records and what it produces. |
| `exulanica/traffic/city_derivation.py` | The connections and spaces derived from a city's records. |
| `exulanica/traffic/catalogs.py` | Loading and checking the six catalogs. |
| `exulanica/traffic/network.py` | The compiler and its refusals. |
| `exulanica/traffic/geometry.py`, `kinematics.py`, `signals.py`, `routing.py` | Integer geometry, the safety rule, signal indications and routing. |
| `exulanica/traffic/inputs.py`, `simulation.py` | The input contracts and the step. |
| `exulanica/traffic/checks.py` | The transition checker. |
| `exulanica/traffic/metrics.py`, `presentation.py` | The metrics report and the presentation records. |
| `exulanica/world/traffic_host.py`, `traffic_episodes.py`, `episode_worker.py` | The road source, clock, fleet, trip rule, episodes, windows and their worker. |
| `exulanica/api/routes/tiles.py` | `GET /tiles/traffic`. |
| `exulanica/api/routes/world_traffic.py`, `exulanica/api/traffic_answer.py` | `GET /world/versions/{version_id}/traffic`, and the refusal statuses and vehicle encoding both routes share. |

Tests are `tests/test_traffic_*.py`, `tests/test_tile_traffic_route.py` and `tests/test_world_traffic_route.py`, with the test network in `tests/traffic_network_fixture.py` and
its scenarios in `tests/traffic_scenarios.py`. `tests/test_traffic_city_roads.py` also reads the city
vocabulary's fixture tile, `tests/fixtures/city-v2/tile-document.json`, and records what traffic
refuses in it and why.
