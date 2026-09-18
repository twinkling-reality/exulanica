# The generated corridor: one street, from a seed

Status: **GENERATED, VALIDATED AND GATED; NOT YET BAKED INTO THE STORE OR SCORED**. Updated
2026-09-17.

This is the first street the city grammar generates: 126 m of high street with two facing
frontages, produced from one seed by the eleven stages of city version 2, cut into tiles, and held
to every check the grammar has. Nothing in it is drawn by hand and nothing in it is a fallback: a
surface no published texture set dresses is drawn unavailable, and this document says how many
there are.

**It is generated content.** It is evidence of what the generator does and of nothing else. It
reaches no person's world until the governance decision is accepted in writing.

## 1. What the specification states, and what it leaves to the seed

`exulanica.grammar.grammars.city.generation.corridor` holds the whole specification as integers.
The seed is the SHA-256 of a sentence naming this specification, `75832ac5...`, and the city's
identity is a uuid5 under the invalid documentation domain. Neither is evidence of anything.

Eleven values are bound; everything else is derived per subject from the seed:

| Bound | Value | Why it is bound rather than derived |
| --- | --- | --- |
| `driving_side` | right | Required: the side of the road is a convention a world states. |
| `city_extent_x_mm`, `city_extent_y_mm` | 640 000 × 128 000 | Five whole tiles by one. |
| `terrain_relief_mm` | 0 | This terrain stage generates level ground only. |
| `block_length_mm` | 140 000 | Leaves a frontage of about 126 m, the route the gate compares. |
| `block_depth_mm` | 56 000 | Two rows of lots about 20 m deep. |
| `gutter_width_mm` | 300 | One gutter runs along a whole street. |
| `front_setback_mm` | 0 | A high street builds to its frontage line. |
| `storey_band_low`, `storey_band_high` | 3, 6 | The street wall is the district's decision. |
| `memory_precinct_lots` | 1 | The reserved lot the target architecture requires. |

Everything else -- every kerb height, footway width, bay pitch, door size, shop use, tree spacing,
material and texture offset -- is derived by the stage that reads it, per subject, from the seed.

## 2. What it comes out as

Measured from the records, not remembered. The evidence is
[docs/artifacts/corridor/corridor-tiles.log.txt](artifacts/corridor/corridor-tiles.log.txt),
written by the script beside it.

- **6 566 records** of 23 kinds, in five tiles along one row. The corridor's own tile, (2, 0),
  owns 2 073 of them and carries 2 076 more in its halo; its document is 3 381 852 bytes.
- **98 buildings**, 3 to 6 storeys, frontages 10.5 m to 25.8 m tall, median 17.4 m.
- **228 premises**: 98 residential, and on the ground floor 52 cafes, 20 grocers, 19 restaurants,
  18 workshops and 17 offices, each with a name drawn from the signage lexicon.
- **The walked block**: 140 m between cross streets, a 7.1 m carriageway, footways of 3.6 m and
  5.2 m, kerbs 167 and 168 mm high. Frontage to frontage it is **16.2 m**.
- **On that block**: 15 street trees, 5 lamps, 5 litter bins, 4 benches, 2 cycle stands, 2 sign
  posts and 2 zebra crossings.

## 3. What holds it up

Every check runs on every tile, and the evidence log records all of them.

- **The grammar's own document check**: every record's validator, then every rule across records
  (owners, membership, streets, roads, buildings, materials, streetlife, vitrines, what lies
  behind glazing, walk groups, premises, terrain). A failure names the check in brackets.
- **Reference closure over the whole city**: every identity any tile names is carried by some tile
  of the same city.
- **Seven mechanical gates**, measured from records: bay pitch in band, facade coverage, furniture
  outside footprints, the ground band, kerb height, materials naming published texture sets, and
  the six section 5.1 fields on every facade. All seven pass on the whole city and on the
  corridor tile's owned records alone.
- **Determinism**: generating the city twice in one process and in two processes gives the same
  bytes, and the float-injection tests refuse a float anywhere in the emitted set.

## 4. What is drawn unavailable, and why

A surface no published texture set dresses is drawn as the unavailable hatch. That is the honest
answer, and this is the count across the city:

| Role | Surfaces | Waiting on |
| --- | --- | --- |
| `terrain` | 5 | Bare ground, which no set depicts and none is asked for. |

Doors (228), crossing bands (40), tree pits (118), awnings, glazing, transoms, shopfront frames,
bark and foliage were on that list earlier today and are not now: `material.v4.json` dresses them
from the sixteen published sets it holds, six of which arrived with texture batch 3. The count is
measured against the material records the city actually holds, so it falls on its own as sets are
published and nothing has to remember to edit a list. It counts surfaces, not area: five terrain
records, one per tile, each of them a whole tile's ground grid that the blocks, streets, kerbs and
junctions draw over almost entirely.

Where a terrain grid is not drawn over, it is two strips: 1.0 m along the district's south edge
and 2.3 m along its north edge, where the outermost footway stops and the city ends. They total
422 m², 2.6 per cent of the corridor tile, and they are 64 m from the walked street behind two
rows of buildings. Nothing between them is bare: the street lattice tiles the district exactly,
block frontage to kerb line, with no verge and no forecourt. They are a known unavailable, not a
defect, and they are revisited only if a capture ever looks down a cross street.

## 5. How to generate it again

From the repository root, with the project's virtual environment:

```bash
uv run python docs/artifacts/corridor/corridor-tiles.py.txt
```

That writes the evidence log above. It reads no clock and no network: the log carries the commit
it was generated at, from git, and nothing else that varies between runs. The targeted tests are
`tests/test_corridor_generation.py`, `tests/test_corridor_gates.py` and
`tests/test_corridor_tile_digests.py`.

Baking the tiles through the tessellator and recording them through migration 0072 is a separate,
offline step: `scripts/bake_corridor_tiles.py`, which bakes every tile twice under one key and
requires the second bake to be byte-identical. Nothing bakes inside a request.

## 6. How the street is served

Two routes, and neither of them bakes. Both require the `tiles.materialise` permission, which
nothing holds by default: a generated world reaches no person's world until the governance
decision is accepted in writing, so only a token whose grant names the permission is served a
generated tile.

- `GET /tiles?city_seed=<64 hex>[&lod=<int>]` lists what is stored for one city: each tile's key,
  coordinate, level of detail, **the stage version and stage params digest its key was derived
  from**, container digest and size, its two triangle digests and its state. Metadata only, and no
  tile quota is spent on it. The stage fields are what tell two rows for one tile apart: a tile
  document may be baked by more than one tessellator, so a listing can carry rows agreeing on
  coordinate, level of detail and `tile_inputs_digest` and differing only in the program that baked
  them. A caller reading by coordinate alone takes whichever came first, which on 2026-09-18 made a
  loader draw a container its runtime then refused, and the failure read as a missing tile rather
  than as an ambiguous listing.
- `GET /tiles/{baked_tile_id}/bytes` serves one container, as
  `application/vnd.exulanica.owd`, with the container digest as its `ETag`. A caller that already
  holds the bytes sends `If-None-Match` and is answered 304 with no body. **The caller hashes what
  it received and refuses to draw anything whose digest is not the one the listing states**: the
  route checks its own bytes before sending them, and that check is not a substitute for the
  caller's.

What a tile costs: the first delivery of a tile to a workspace spends one of its migration 0062
tile quota, and delivering the same tile to that workspace again is free, because the ceiling
limits how many distinct tiles a workspace materialises and not how often a walk reloads one. A
revalidation costs nothing, and neither does a delivery that fails: the quota is charged after the
bytes are in hand and held to their digest, never before.

Refusals, each meaning one thing: 404 `unknown_reference` for a key nothing stored, and the same
status and code for every key when the caller's grant does not hold the permission, so a
credential that is short cannot learn which keys exist (the two bodies are not identical: the
floor refuses before the route runs, with its own detail and none of the route's headers, which
tells a caller only what its own grant is); 409 `nondeterminism_detected` for a key that once
baked into two different containers, which is never served; 409 `bytes_missing` for a row whose
bytes are not in the store, which is an operator's problem rather than a client's; 429
`tile_quota_exceeded` for a workspace past its ceiling or with none declared, which is never
retried.

A loader is better off listing first and fetching only the digests it does not already hold: one
small request for a whole city, rather than a revalidation per tile.

## 7. What draws today, and what does not

Measured from the container the route serves for tile (2, 0), baked by tessellator 17 at main
de0ccbd4, container sha256 `93df0715f5...`. The counts are
`docs/artifacts/corridor/corridor-drawn.log.txt`, which names the container it read by DIGEST
rather than by file name, so it cannot be read against a different container without the mismatch
showing. Every bake writes the same measurement into its own row's receipt and onto
[corridor-bake.log.txt](artifacts/corridor/corridor-bake.log.txt).

`render_batch` holds **34 954 triangles** across **527 drawn entries** of the tile's 4 149: 168
facades, 89 rooftop objects, 78 vitrines, 51 interior backings, 36 pieces of street furniture, 33
parcels, 32 massings, 30 street trees, 6 curb edges, 3 street segments and the terrain. Of **1 582
drawn surfaces, 1 496 are dressed** by a material record and 86 are not: 85 facade ground bands and
the terrain.

**83 entries state unavailable**, and each names the expander it waits for:

| Waiting on | Entries | The records |
| --- | --- | --- |
| `facade_layout` | 75 | 75 entrances: the recessed doorways, which wait on openings being cut. |
| `crossing_band` | 6 | The zebras. |
| `ground_coverage` | 2 | The two blocks' own ground, where lots cover all of it. |

`nav_envelope` holds **96 745 triangles**.

**Where the 85 undressed ground bands are, and what is not known about them.** Measured: all 85 are
interior faces, 54 on party walls between neighbours and 31 on rear walls, and the north terrace is
eight buildings from x 258 900 to 381 100 with no gap between any of them.

Not known: whether those bands are what appears as the magenta unavailable state in a picture of
this street. This document said until 2026-09-18 that they were, and that a viewer was looking
through the buildings at them because the upper glazing had nothing behind it. That was wrong twice
over and is retracted. There is no upper glazing at all: the glazing on this frontage spans z 556
to 3404, which is the shopfront band. And the claim rested on a reading of this lane's own that was
an artefact of its query rather than a fact about the street: asking which surfaces lie ON a
frontage plane, by selecting those whose y is constant, silently drops every RECESSED surface, and
a shopfront's ground band, glazing and door are recessed, spanning y 56 700 to 55 253. The filter
removed the six dressed surfaces in front of the viewer and left the interior bands as the only
candidate. An artefact that removes the evidence for the alternative is the worst kind, because
everything that survives it agrees.

Read without that filter, the south frontage in the column in front of the walked pose draws wall,
ground band, fascia, glazing, shopfront frame and stall riser, and every one is dressed by a
material record. In that ten metre column there is no undressed surface at all except the terrain.

The interior backings now draw, as of tessellator 16, which makes the question testable: the
experiment is written down, unrun, in
[magenta-comparison.md](artifacts/corridor/magenta-comparison.md). Until it is run, a caption for
any picture of this street should say the magenta is an unavailable surface and stop there.

## 8. The walk, and the pose it starts from

The gate scores pictures of a walk, so the walk states where it begins and which way it faces
rather than taking whatever the runtime would default to. These are measured from the records of
tile (2, 0), not chosen for the look of them.

The corridor is Harbour Way's segment from x 250 000 to x 390 000, centreline at y 64 000, a
7100 mm carriageway with a 300 mm gutter each side. Its two kerbs are 150 mm wide and 167 and
168 mm tall, and its footways are unequal by the seed's own draw: 3600 mm on the south, 5200 mm on
the north. That puts the south frontage line at y 56 700 and the north at y 72 900, so the street
is **16 200 mm frontage to frontage**, and the frontages themselves run from x 261 700 to
x 378 300, **116 600 mm** of built street.

The walk starts on the wider footway, in the middle of it, at the western end of the frontage:

| | |
| --- | --- |
| `pose_x_mm` | `262000` |
| `pose_y_mm` | `70300` (the north footway spans 67 700 to 72 900) |
| `facing_dx`, `facing_dy` | `1`, `0`, east along the street |
| ends at | x 378 000, so the walk is 116 m |
| midpoint | x 320 000 |

Read into the development evaluation route, that is
`?preview=1&city=<seed>&tile_x=2&tile_y=0&pose_x_mm=262000&pose_y_mm=70300&facing_dx=1&facing_dy=0`.

**The walk itself, stated before it is taken.** The pose says where a picture starts; these say
what the walk does, and they are written here before the tessellator 14 rebake so that the numbers
this lane reports afterwards have something to be checked against rather than to be chosen to fit.
The tile runtime lane is running the same walk from its own side, so both halves of the experiment
name the same parameters.

| | |
| --- | --- |
| path | east along the footway centre line, y `70300`, from x `262000` to x `378000` |
| distance | 116 000 mm |
| captures | at the start, at x `320000`, and at the end |
| movement | the product's own walking, a held W key through its movement and support resolution |
| never | no camera override (it renders a quarter frame) and no writing of a position: a walk that teleports proves nothing about support |
| viewport | 960 px wide or more, because the app serves its boundary page below 60rem and would film an apology |

**What I expect it to do, so that a surprise is legible as one.** Tess's carve now leaves the
footway supported along the walked line, with fourteen gaps of about a metre where a 151 mm trunk
plus the 340 mm a body needs interrupt it. The tile carries no `collision_proxy`, so nothing stops
a walker entering one; what happens when a walker meets a metre of unsupported footway is the open
question of this walk, and the honest answers include stopping, dropping to the terrain 170 mm
below, and stepping over it. I do not know which, and I would rather record the question in advance
than discover the answer and call it the expected behaviour.

**What the walk found, measured on the served container at 100 mm along the walked line.** The
footway is continuous: 1 161 samples from x 262 000 to 378 000, every one supported, at a constant
**146 mm**. On the tessellator 13 bake the same line had seven unsupported runs totalling 60.7 m,
one under each street tree, because the carve then read a tree's whole stated plan extent, which is
its canopy at 7 972 mm across, rather than its parts. Tessellator 14 moved the carve onto the
parts, and the runtime says the same thing from the other side: the pose at x 320 000 used to print
"where the tile states no walkable surface" and no longer does.

The gaps did not vanish, they moved to where a tree actually is. Sampling across the footway's
width on the served container:

| line | support | runs that are not footway |
| --- | --- | --- |
| y 68 549, the tree row | 127 mm | 14, about a metre each |
| y 70 300, the walked line | 146 mm | none |
| y 72 000, nearer the frontage | 164 mm | none |

The support height differs by line because the footway drains to the gutter at 10 864 millionths,
56 mm of fall across its 5 200 mm. That matters for anyone comparing a runtime's eye height against
this: a standing eye is support plus the capsule's stated 1 620, so 1 766 mm on the walked line and
between about 1 747 and 1 784 elsewhere on the footway. The tile runtime lane measured 1 766 while
walking, which is 146 + 1 620 exactly.

**What is past the end of the line.** The walk stops at x 378 000 and the curb it is on ends at
378 300. Beyond that is a junction, and a walker who keeps going steps off the pavement onto
terrain at z 0, which is a 146 mm fall. That was measured by the tile runtime lane at x 378 334 and
is a different question from a hole in the footway; it has no parameters written for it yet, and
the walk was deliberately NOT extended to cover it, because a line chosen to include a known event
is not a walk, it is an illustration of that event.

**What the pictures must not imply.** The pale ground at the base of the frontages is the
**parcels' lot ground**, the private ground behind the frontage line, and not the footway. And the
magenta seen through every shop window is an unavailable surface whose visibility is not yet
explained: see section 7, and the experiment written down in
[magenta-comparison.md](artifacts/corridor/magenta-comparison.md). A frame that would need either
sentence to be read correctly is evidence of a stage, not a picture of a street, and should not be
used where the sentence cannot travel with it.

## 9. Six bakes of one street, and what each digest said

One tile document, baked by six tessellators in one night, every bake stored beside the others
under migration 0077 and each keyed by `uuid5(stage version, stage params digest, tile inputs
digest)`. Nothing here was decided by anybody: each digest is a function of the bytes, and the
table is what they came out as.

| params digest | bytes | container | render_batch | nav_envelope | what moved |
| --- | --- | --- | --- | --- | --- |
| `fc70ae79` | 5 607 448 | `ab6023d8c7` | `297d744723` | `09ec20f943` | tessellator 5 |
| `dc305256` | 9 483 132 | `8194a31e44` | `adef2300b7` | `550f0d4b75` | 11: the expanders |
| `c252f533` | 9 483 132 | `dfd922bfee` | `adef2300b7` | `550f0d4b75` | 13: neither projection |
| `e90cfd76` | 11 014 812 | `2adf282b94` | `adef2300b7` | `9d59577a5d` | 14: navigation only, the tree carve |
| `00353a17` | 11 235 848 | `b323810ae9` | `749e317efe` | `3a3dc8abe9` | 16: both, the interior backings |
| `33d663f8` | 11 153 540 | `93df0715f5` | `91350a9045` | `35388d7849` | 17: both, the mitre and the corner carve |

**What the table is evidence of.** Two versions changed nothing that draws and their render_batch
digests are identical; one changed only what a person can walk on and only `nav_envelope` moved;
one drew something new and both moved. The digests said which each time, and nobody decided what
they should say.

**Two of those rows are the same size and not the same bytes.** 11 and 13 are both 9 483 132, with
different container digests and identical triangle digests: the geometry was untouched and only the
header moved, because it states which tessellator made it. A reader comparing byte counts would
have concluded nothing changed between them, and a reader comparing container digests alone would
have concluded something had. Only the pair of triangle digests says which it was.

**Five of the six keys are predictions, not records.** The tessellator 11, 13, 14, 16 and 17 keys
were each computed from the stage parameters BEFORE the bake ran, with the bake to be refused if it
disagreed, and each matched. The tessellator 5 key was computed after its bake, which makes it a
record of what happened rather than a test of whether the key derivation is what it claims to be.
Five predictions, five matches.

**The last row shrank.** Tessellator 17 writes 82 308 fewer bytes than 16 while both its triangle
digests move, because its corner rule stops a footway short of a frontage that no carried block
marks: at a tile edge, where the block belongs to the neighbouring tile, the old rule drew the
whole slice and the footway ran through where a building stands. Less geometry and more correct,
which is a combination a byte count alone would report as a loss.

