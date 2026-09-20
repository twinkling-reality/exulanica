# Traffic simulation

Status: **TRAFFIC V1 ON CITY V2 ROAD RECORDS**. No runtime stores or draws a run.

Cars, vans, buses and bicycles drive a generated city's streets second by second: they keep their lanes, stop at stop lines, take turns at junctions by the junction's rule,
wait for people on crosswalks, and park. The same inputs always give the same bytes. This document
is the contract for what traffic reads, what it writes, what it refuses, and the record a renderer
draws a vehicle from.

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
| City road records | The city grammar's version 2 street and road records for one tile (below). Only `exulanica/traffic/city_roads.py` reads them. |
| Traffic catalogs | Five versioned files under `assets/catalogs/traffic`: vehicle classes, right-of-way policies, signal plans, and two access mappings (below). |
| Seed | A string. Its SHA-256 is written into the state; the only draws are the fleet's placement, body family and colour at the start. |
| Fleet | A count per vehicle class. Vehicles start parked in spaces that admit their class. |
| Trip requests | `exulanica.traffic-trip-request/v1`: a vehicle, the second it wants to leave, and a destination, either a parking space by record identity or a society destination by its `destination_id` and frontage `street_segment_ordinal`. Numbered from 1 with no gaps. |
| Crossing feed | `exulanica.traffic-crossing-feed/v1`: which crosswalk each walker steps onto, when, and for how long, taken from the society's `route_progressed` events. Each feed states the last second it covers. |

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
  lane. A vehicle is only admitted when there is room beyond the region for its whole body.
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
leave its junction region; and a path no class can drive.

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
   stop when its signal is no longer green or a pedestrian is due.
5. Admit vehicles at their stop lines, junction by junction, by the junction's rule.
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

The body families and colours in the catalog today:

| Class | Body families | Colours |
| --- | --- | --- |
| `bicycle` | `upright_bicycle` | `black`, `blue`, `grey`, `red`, `silver`, `white` |
| `city_bus` | `rigid_city_bus` | `blue`, `red`, `white` |
| `passenger_car` | `hatchback`, `sedan` | `black`, `blue`, `grey`, `red`, `silver`, `white` |
| `van` | `minivan`, `panel_van` | `black`, `blue`, `grey`, `red`, `silver`, `white` |

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

**Digest.** The catalogs' digest covers the canonical form of all five files, references and sources
included, and is written into every state. The SHA-256 of each file's bytes is kept as well, because
a city signal record names the signal-plan catalog by those bytes.

### Declared values

These 47 values cite no source. Each says why; they are listed here for review, generated from the
catalogs by `declared_values`.

| Catalog | Entry | Field | Why it is declared |
| --- | --- | --- | --- |
| vehicle-class | `bicycle` | `body_families` | presentation keys the tessellator resolves to geometry; the simulation only draws one per vehicle from the seed |
| vehicle-class | `bicycle` | `colours` | presentation keys awaiting art direction; the simulation only draws one per vehicle from the seed |
| vehicle-class | `bicycle` | `front_overhang_mm` | follows from presenting the bicycle as one rigid footprint with no overhang |
| vehicle-class | `bicycle` | `height_mm` | no bicycle-and-rider height was found in the sources read; the 85th percentile eye height of fhwa_hrt_04_103 Table 7 (150 cm) is used as the envelope height, which understates the rider's head; presentation only, the simulation never reads it |
| vehicle-class | `bicycle` | `minimum_gap_mm` | no bicycle jam distance was found in the sources read; the passenger car jam distance of thh_2000 Table I (2 m) is applied |
| vehicle-class | `bicycle` | `minimum_turning_radius_mm` | no bicycle minimum turning radius was found in the sources read; 1 m is used only so that a connector tighter than that refuses bicycles |
| vehicle-class | `bicycle` | `parking_entry_ms` | no measured time to leave a bicycle at a stand was found; 10 s is chosen |
| vehicle-class | `bicycle` | `parking_exit_ms` | no measured time to take a bicycle from a stand was found; 10 s is chosen |
| vehicle-class | `bicycle` | `rear_overhang_mm` | follows from presenting the bicycle as one rigid footprint with no overhang |
| vehicle-class | `bicycle` | `turning_inward_extent_mm` | no bicycle off-tracking was found in the sources read; the turning corridor is the body half-width, 345 mm |
| vehicle-class | `bicycle` | `turning_outward_extent_mm` | no bicycle off-tracking was found in the sources read; the turning corridor is the body half-width, 345 mm |
| vehicle-class | `bicycle` | `turning_speed_mm_per_s` | no bicycle turning speed was found in the sources read; the design-vehicle turning speed of aashto_2011 (15 km/h, 4166 mm/s) is applied |
| vehicle-class | `bicycle` | `wheelbase_mm` | no bicycle wheelbase was found in the sources read; the bicycle is presented as one rigid footprint whose axle span is its whole length |
| vehicle-class | `city_bus` | `body_families` | presentation keys the tessellator resolves to geometry; the simulation only draws one per vehicle from the seed |
| vehicle-class | `city_bus` | `colours` | presentation keys awaiting art direction; the simulation only draws one per vehicle from the seed |
| vehicle-class | `city_bus` | `minimum_gap_mm` | no bus jam distance was found in the sources read; the passenger car jam distance of thh_2000 Table I (2 m) is applied |
| vehicle-class | `city_bus` | `parking_entry_ms` | a search summary of a measured study of conventional parallel parking (295 participants, 'Impact of the additional parking space on parallel parking maneuver time') reports a mean entry time of 22.3 s; the primary paper could not be read, so the rounded value is declared rather than cited; no bus value was found, so the car value is applied to a bus pulling into a layover bay |
| vehicle-class | `city_bus` | `parking_exit_ms` | the same search summary reports a mean exit time of 10.9 s; the primary paper could not be read, so the rounded value is declared rather than cited; no bus value was found, so the car value is applied |
| vehicle-class | `city_bus` | `speed_cap_mm_per_s` | no class cap is intended below an urban posted limit, so the cap is 130 km/h (36111 mm/s, floored) and the lane's posted limit always governs |
| vehicle-class | `passenger_car` | `body_families` | presentation keys the tessellator resolves to geometry; the simulation only draws one per vehicle from the seed |
| vehicle-class | `passenger_car` | `colours` | presentation keys awaiting art direction; the simulation only draws one per vehicle from the seed |
| vehicle-class | `passenger_car` | `parking_entry_ms` | a search summary of a measured study of conventional parallel parking (295 participants, 'Impact of the additional parking space on parallel parking maneuver time') reports a mean entry time of 22.3 s; the primary paper could not be read, so the rounded value is declared rather than cited |
| vehicle-class | `passenger_car` | `parking_exit_ms` | the same search summary reports a mean exit time of 10.9 s; the primary paper could not be read, so the rounded value is declared rather than cited |
| vehicle-class | `passenger_car` | `speed_cap_mm_per_s` | no class cap is intended below an urban posted limit, so the cap is 130 km/h (36111 mm/s, floored) and the lane's posted limit always governs |
| vehicle-class | `van` | `body_families` | presentation keys the tessellator resolves to geometry; the simulation only draws one per vehicle from the seed |
| vehicle-class | `van` | `colours` | presentation keys awaiting art direction; the simulation only draws one per vehicle from the seed |
| vehicle-class | `van` | `parking_entry_ms` | a search summary of a measured study of conventional parallel parking (295 participants, 'Impact of the additional parking space on parallel parking maneuver time') reports a mean entry time of 22.3 s; the primary paper could not be read, so the rounded value is declared rather than cited |
| vehicle-class | `van` | `parking_exit_ms` | the same search summary reports a mean exit time of 10.9 s; the primary paper could not be read, so the rounded value is declared rather than cited |
| vehicle-class | `van` | `speed_cap_mm_per_s` | no class cap is intended below an urban posted limit, so the cap is 130 km/h (36111 mm/s, floored) and the lane's posted limit always governs |
| right-of-way-policy | `all_way_stop` | `arrival_order` | vehicles proceed in the order in which they came to a full stop at the line, the practice driver handbooks teach; no statute or standard giving this order was read |
| right-of-way-policy | `priority_two_way_stop` | `arrival_order` | priority rank decides order; arrival order is not used |
| right-of-way-policy | `signalised` | `arrival_order` | a signal decides order; arrival order is not used |
| right-of-way-policy | `uncontrolled_continuation` | `arrival_order` | unused, because no movements conflict |
| right-of-way-policy | `uncontrolled_continuation` | `rule` | a node where no two movements from different approaches conflict needs no control; the compiler refuses the policy anywhere two such movements conflict |
| right-of-way-policy | `uncontrolled_continuation` | `turn_priority` | unused, because no movements conflict |
| signal-plan | `fixed_two_phase_60s` | `intervals[1].duration_ms` | the rest of a 30 second phase in a fixed-time plan for the synthetic network, not an optimised timing; the compiler checks that it covers pedestrian clearance at 3.5 feet per second for every crossing the group governs |
| signal-plan | `fixed_two_phase_60s` | `intervals[5].duration_ms` | the rest of a 30 second phase in a fixed-time plan for the synthetic network, not an optimised timing; the compiler checks that it covers pedestrian clearance at 3.5 feet per second for every crossing the group governs |
| lane-use-access | `buffer` | `classes` | a painted buffer carries no traffic, as the city's lane-use catalog states, so no class may drive in it |
| lane-use-access | `bus` | `classes` | a bus lane is modelled as carrying buses only; local rules often also admit bicycles or taxis, which this mapping does not model and no source read for this catalog settles |
| lane-use-access | `cycle` | `classes` | a cycle lane carries bicycles and no motor vehicle |
| lane-use-access | `general` | `classes` | a general traffic lane carries every vehicle class this catalog knows; a class the geometry cannot carry is dropped by the network compiler with its reason, never by this mapping |
| lane-use-access | `parking` | `classes` | a parking lane carries no through traffic, as the city's lane-use catalog states; a vehicle reaches a bay in it from the traffic lane its parking space names |
| parking-kind-access | `accessible` | `classes` | an accessible bay is kept for a car or van carrying a person who needs room beside it; permits are not modelled, so either class may use it |
| parking-kind-access | `bus_layover` | `classes` | a layover is where a bus waits at the end of a trip, and no other class uses it |
| parking-kind-access | `cycle_stand` | `classes` | cycle stands hold bicycles only; how many is the space record's capacity, never this mapping |
| parking-kind-access | `general` | `classes` | a kerbside bay for one car; the van class has the passenger car's design dimensions in the vehicle-class catalog, so it fits the same bay |
| parking-kind-access | `loading` | `classes` | a loading bay is for deliveries, and of this catalog's classes only the van carries goods |

## The layer

`exulanica.traffic` sits below the database, the store and the model client in the import-linter
layers, and a forbidden contract keeps it from `psycopg`, the database and store, the evidence spine,
ingest, migrations, identity, selection, reconstruction, capture, the world package, models, the API,
`numpy` and `torch`. It may import the grammar, because the road records are grammar records, and only
`exulanica/traffic/city_roads.py` does. The society composition above both passes crossing events down
as data. A test holds that no other traffic module imports the city grammar, so a new city version
changes one file.

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
- **Nothing runs it yet.** No runtime advances it, no store keeps its states, no renderer draws its
  presentation records, and the society engine does not read its events.

## Where to look

| Module | What it is |
| --- | --- |
| `exulanica/traffic/city_roads.py`, `road_input.py` | The converter from city records and what it produces. |
| `exulanica/traffic/catalogs.py` | Loading and checking the five catalogs. |
| `exulanica/traffic/network.py` | The compiler and its refusals. |
| `exulanica/traffic/geometry.py`, `kinematics.py`, `signals.py`, `routing.py` | Integer geometry, the safety rule, signal indications and routing. |
| `exulanica/traffic/inputs.py`, `simulation.py` | The input contracts and the step. |
| `exulanica/traffic/checks.py` | The transition checker. |
| `exulanica/traffic/metrics.py`, `presentation.py` | The metrics report and the presentation records. |

Tests are `tests/test_traffic_*.py`, with the test network in `tests/traffic_network_fixture.py` and
its scenarios in `tests/traffic_scenarios.py`. `tests/test_traffic_city_roads.py` also reads the city
vocabulary's fixture tile, `tests/fixtures/city-v2/tile-document.json`, and records what traffic
refuses in it and why.
