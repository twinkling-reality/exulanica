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
and 2.3 m along its north edge, where the outermost footway stops and the city ends. They total 422 m², 2.6 per cent
of the corridor tile, and they are 64 m from the walked street behind two rows of buildings.
Nothing between them is bare: the street lattice tiles the district exactly, block frontage to
kerb line, with no verge and no forecourt. They are a known unavailable, not a defect, and they
are revisited only if a capture ever looks down a cross street.

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
status and code for every key when the caller's grant does not hold the permission, so a credential
that is short cannot learn which keys exist (the two bodies are not identical: the floor refuses
before the route runs, with its own detail and none of the route's headers, which tells a caller
only what its own grant is); 409 `nondeterminism_detected` for a key that once baked into two different containers,
which is never served; 409 `bytes_missing` for a row whose bytes are not in the store, which is an
operator's problem rather than a client's; 429 `tile_quota_exceeded` for a workspace past its
ceiling or with none declared, which is never retried.

A loader is better off listing first and fetching only the digests it does not already hold: one
small request for a whole city, rather than a revalidation per tile.

## 7. What draws today, and what does not

Measured from the container the route served for tile (2, 0), baked by tessellator 5 at main
dee8567d, not from what any lane expects to be true. The counts below map each entry to its record
through the tessellator's own document reader, because the container states one entry per record
in its own sorted order and reading that order by eye gets it wrong. The tessellator lane has
massing and facades built on its branch, unmerged, so most of this table is queued rather than
unwritten.

`render_batch` holds **596 triangles** across **4 drawn entries** of the tile's 4 149: three street
segments, each drawing its carriageway and its gutter dressed by their material records, 8
triangles apiece, and the tile's terrain, 572 triangles drawn as the unavailable state because no
material dresses it. **850 entries state unavailable**, and each one names the expander it waits
for:

| Waiting on | Entries | The records, and what a person would see when it lands |
| --- | --- | --- |
| `facade_layout` | 538 | 244 ground bays, 168 facades, 75 entrances, 51 interior backings: the frontages, their bays, stall risers, glazing and doors, and the room behind the glass. |
| `form_parts` | 233 | 89 rooftop objects, 78 vitrines, 36 pieces of street furniture, 30 street trees: the lamps, benches, bins, shopfronts and trees. |
| `ring_triangulation` | 65 | 33 parcels, 30 street trees (their pits), 2 blocks: the ground people walk on between the kerb and the frontage. |
| `massing_faces` | 32 | 32 massings: the building volumes behind the frontages. |
| `crossing_band` | 6 | 6 crossings: the zebras. |
| `kerb_offset` | 6 | 6 curb edges: the kerb line and the footways beside it. |

The column sums to 880 and there are 850 entries, because thirty of them name two. They are the
street trees: a tree waits on `form_parts` for its trunk and canopy and on `ring_triangulation`
for its pit, and it says both rather than picking one.

`nav_envelope` holds **37 052 triangles** over **31 517 vertices**, so the street is already
walkable: a capsule can stand on it and walk the 126 m along a carriageway with bare ground either
side of it. That asymmetry is the honest state of this lane. The records are complete and gated;
the tessellator draws four of the tile's 4 149 entries; and the question this lane exists to
answer, whether the street reads as inhabited, cannot be asked of a picture until `facade_layout`
lands, because it alone holds 538 of the 850 entries that are waiting.

Nothing here is a defect of the records. Every unavailable entry names a reason, and a reader can
tell a surface nobody has dressed from a surface nobody has yet triangulated.
