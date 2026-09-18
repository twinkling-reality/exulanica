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
  coordinate, level of detail, container digest and size, its two triangle digests and its state.
  Metadata only, and no tile quota is spent on it.
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

Measured from the container the route served for tile (2, 0), baked by tessellator 11 at main
7c0280f2. The counts are `docs/artifacts/corridor/corridor-drawn.log.txt`, written by the script
beside it from a container and the document it was baked from, and every bake writes the same
measurement into its own row's receipt, so the number exists whether or not anybody goes to look.
Both map each entry to its record through the tessellator's own document reader, because the
container states one entry per record in its own sorted order and reading that order by eye gets it
wrong.

`render_batch` holds **32 834 triangles** across **476 drawn entries** of the tile's 4 149: 168
facades, 89 rooftop objects, 78 vitrines, 36 pieces of street furniture, 33 parcels, 32 massings,
30 street trees, 6 curb edges, 3 street segments and the terrain. Of **1 531 drawn surfaces, 1 445
are dressed** by a material record and 86 are not: 85 facade ground bands and the terrain.

**134 entries state unavailable**, and each names the expander it waits for:

| Waiting on | Entries | The records |
| --- | --- | --- |
| `facade_layout` | 126 | 75 entrances and 51 interior backings: the recessed doorways, and the plane that closes a shop window. |
| `crossing_band` | 6 | The zebras. |
| `ground_coverage` | 2 | The two blocks' own ground, where no lot covers it. |

`nav_envelope` holds **39 863 triangles**, and this is where the street is still not a street: see
section 8.

**The 85 undressed ground bands are not on the street.** At the two frontage planes what draws is
wall, fascia, shopfront frame and stall riser, every one dressed, and no ground band at all,
because the corridor's frontages are covered by bays end to end and the band role is only the part
no bay covers. All 85 are interior: 54 on party walls between neighbours, 31 on rear walls. The
north terrace is eight buildings from x 258 900 to 381 100 with no gap between any of them, so
none of those faces can be seen from the footway.

They are visible anyway, and that is worth understanding before looking at a picture of this
street. The 51 interior backings are not drawn, so a shop window has nothing behind it: looking
into a shopfront you are looking through the building at the inside of the terrace, where a 5.2 m
undressed band glows. **The caption is "you are seeing through the building", not "the frontage is
undressed"**, and every picture taken before `facade_layout` finishes its interior backings needs
that sentence to be read correctly. A picture that needs that sentence is not a picture of the
street: it is a picture of a stage.

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

**What the walk found, and what it costs.** The footway now draws, and the navigation envelope
carries it: at the stated pose the surface under the walker is the footway at 170 mm, not the
terrain below it. But **56 m of the 116 m has no walkable surface at all**. Sampling the envelope
every 500 mm along three lines across the footway's width gives seven unsupported runs of about
8 m: x 264 000 to 272 000, 277 000 to 285 000, 289 500 to 297 500, 315 000 to 323 500, 328 000 to
336 000, 353 500 to 361 500 and 366 000 to 374 500.

Seven runs, seven street trees, at x 268 089, 280 868, 293 647, 319 205, 331 984, 357 542 and
370 321, each stating a plan extent of 7 972 mm, which is its CANOPY. The tessellator carves
support clear of what the navigation table says obstructs a capsule, and for a street tree it reads
the record's whole stated plan extent rather than its parts, so each tree removes eight metres of
pavement. The grammar says the opposite in as many words: a tree's pit is drawn ground a person may
stand on, its trunk obstructs as a low part, and its canopy stands a capsule height above every
support it overhangs. The records and the tessellator disagree about what a tree is, and half the
pavement is the difference. It is tess's to resolve, by reading the parts.

The carriageway is continuous: every sample along y 64 000 is supported. A walk down the middle of
the road is not the walk this gate scores and should not be presented as one, but it is 116 m of
street with both frontages in view and nothing under the feet that is a lie.

**What the pictures must not imply.** The pale ground at the base of the frontages is the
**parcels' lot ground**, the private ground behind the frontage line, and not the footway. And the
magenta seen through every shop window is the inside of the terrace, not an undressed frontage: see
section 7. A frame that would need either sentence to be read correctly is evidence of a stage, not
a picture of a street, and should not be used where the sentence cannot travel with it.
