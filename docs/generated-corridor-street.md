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

- **6 310 records** of 23 kinds, in five tiles along one row. The corridor's own tile, (2, 0),
  owns 2 005 of them and carries 1 987 more in its halo; its document is 3 294 470 bytes.
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
answer, and these are the counts across the city:

| Role | Surfaces | Waiting on |
| --- | --- | --- |
| `door` | 228 | The painted-timber set, texture batch 3. |
| `crossing` | 40 | Road paint, texture batch 3. |
| tree pit | 118 | The soil set, texture batch 3. |

Glazing, transoms, shopfront frames, bark and foliage were on that list this morning and are not
now: `material.v3.json` dresses them from the published `cc0.float-glazing`, `cc0.tree-bark` and
`cc0.broadleaf-foliage` sets. The count above is measured against the material records the city
actually holds, so it falls on its own as sets are published and nothing has to remember to edit a
list.

Two strips of terrain are also bare: 1.0 m along the district's south edge and 2.3 m along its
north edge, where the outermost footway stops and the city ends. They total 422 m², 2.6 per cent
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

Refusals, each meaning one thing: 404 `unknown_reference` for a key nothing stored, which is also
what a credential without the permission is told, so neither answer says whether the other was the
reason; 409 `nondeterminism_detected` for a key that once baked into two different containers,
which is never served; 409 `bytes_missing` for a row whose bytes are not in the store, which is an
operator's problem rather than a client's; 429 `tile_quota_exceeded` for a workspace past its
ceiling or with none declared, which is never retried.

A loader is better off listing first and fetching only the digests it does not already hold: one
small request for a whole city, rather than a revalidation per tile.
