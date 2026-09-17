# loom-tess

One tessellator, compiled twice. The Node build is the bake the `baked_tile` stage runs, so the
served `.owd` bytes are the bytes that stage digests. The browser build is an edit-time preview
only: it never writes an artifact, nothing it returns is served, and CI holds it to the same
triangle digest as the Node build.

The tessellator expands grammar records into integer triangles and nothing else. It has no role
list, no material table, no window loop and no fallback. A record whose fields do not determine
its geometry becomes a stated unavailable entry that names what it lacks.

## The fence

Three source trees, each a TypeScript project with its own `lib` and `types`. That makes a
forbidden global or import a compile error, not a review comment.

| Tree | `lib` | `types` | May name | Holds |
| --- | --- | --- | --- | --- |
| `src/core/` | ES2022 | none | nothing from any host | the tessellator, the container, the pure decoder |
| `src/node/` | ES2022 | node | `node:fs`, `node:crypto` | the CLI and the bake entry; no tessellation |
| `src/browser/` | ES2022, DOM | none | Web Crypto | the preview entry; no tessellation |

Core cannot hash, because `crypto` is a host API. Each entry passes its own SHA-256 into core.
Everything else, from the first byte of the document to the last byte of the container, is one
code path.

`web/.dependency-cruiser.cjs` adds the module half:

- another package may import `@exulanica/loom-tess/core` and nothing else from this package: not
  the node entry, not the browser preview, not a core module by path, not a test;
- the package imports no other workspace package;
- core imports nothing outside `src/core`, not even a `node:` module under another name;
- the node entry and the browser entry never import each other.

`test/fence.test.ts` compiles probes against the three real tsconfigs. The deliberate violations
of every rule are in `evidence/2026-09-16-fences.log.txt`, including a run with the dependency
declared, as a consuming package will declare it.

The renderer ban (`engine-specific-code-stays-behind-the-binding`) already covers this package,
which names no engine.

`test/vocabulary-emptiness.test.ts` is the mechanical proof that core holds no vocabulary. It
fails if core contains any of these:

- a word from the repository's vocabulary sources;
- a numeric literal outside a short, justified list;
- a `||` or `??` fallback;
- a `default:` branch or a default parameter;
- a clock, a random source, locale or `Intl` code, or a transcendental `Math` call.

## The tile document

The city grammar owns the envelope, `exulanica.tile-document/v2`
(`exulanica/grammar/grammars/city/document.py`). It is canonical JSON, integers and printable
ASCII only, in the grammar's record vocabulary (`src/core/document.ts` has the full shape). It
holds:

- the `city.tile` record, whose grammar pins name each grammar's id, version and descriptor
  digest;
- one entry per pinned grammar, with its declared semantics, the subject identity every record
  identity derives from, two sorted lists of records, `owned` and `halo`, and `external`: the
  identities and kinds of subjects a carried record names that the tile does not carry. No
  reference is required to resolve inside the document.

A bake draws owned records only. Halo records are context: each gets a `halo` entry and nothing
is drawn for it.

The reader refuses anything that is not already canonical, as well as:

- an unknown or missing key, at any depth;
- a value its field does not admit: an integer outside its bound, a choice that is not one, a
  sequence of the wrong length, a repeated item, a point with the wrong number of coordinates;
- an unknown record kind or grammar version;
- a list out of order, or an identity stated twice;
- grammars that are not the tile's pins;
- a tile at a level of detail this version does not draw.

Core does not check the grammar's named rules, whether a ring is simple, whether references
resolve or identities derive, catalog keys or membership. The grammar's `validate_city_document`
checks all of them, against the descriptor and catalogs the tile pins.

`src/core/city-v2.ts` is the grammar's own table: `describe_shapes` over the city's record shapes
(`tests/fixtures/city-v2/record-shapes.json`), and the descriptor's frame, contract measures and
navigation table (each kind's ground, cover and obstruction, without the row's prose reason). It is
generated, not transcribed:

```bash
pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts
```

`test/grammar-table.test.ts` and `tests/test_bake_determinism.py` fail when it differs from
either source.

A projection is emitted for a record only when its grammar's declared semantics admit it. City
version 2 admits `render_batch` and `nav_envelope`, among others.

Two projections are materialised, each built from the records by its own rules:

- `render_batch` is what is drawn. A drawn entry is made of **surfaces**, one per face group the
  record has. A surface's **role** is the grammar's surface role (a closed value of
  `city.surface_material.role`, which the grammar also codes for material identities), stated by
  the expander and never inferred from geometry. Its **material** is the `city.surface_material`
  record for (the entry's record identity, role), or the statement that none exists
  (`none-exists`), as the grammar's render_batch contract requires. Each surface carries its
  orientation and surface coordinates. Exact geometry nothing dresses is drawn, not withheld.
- `nav_envelope` is what a person is supported by. Its only admissible use is sampling support
  height.

Each carries a representation contract in the header (`PROJECTION_DEFINITIONS` in
`src/core/expand.ts`). Navigation is never read back out of the render mesh.

`collision_proxy` and `pick_geometry` wait for contracts of their own.

## What draws today

Terrain, and a street segment's carriageway and gutters.

- In `render_batch`, the patch is drawn less what drawn covering surfaces cover, by the terrain
  yield rule below. Nothing drawn covers the ground yet, so today that is the whole patch. No
  published texture set dresses terrain, so its one surface (role `terrain`, horizontal) states
  `none-exists`.
- A street segment draws its carriageway and its gutters by the street rules
  (`src/core/streets.ts`), between the kerb lines of the two curbs the tile carries for it, each a
  horizontal surface dressed by the material record for its role. Terrain yields to both. A segment
  whose centreline or kerb lines are bent, or whose curbs the tile does not carry, waits on
  `bent_street` or `street_curbs`. In `nav_envelope` a segment waits on `support_clearance`: what a
  person is supported by is the ground partition carved clear of obstructions, which comes with the
  navigation table's obstruction axis.
- In `nav_envelope`, for now, a terrain cell is drawn when its closed plan square meets no stated
  extent of a record that covers or stands on the ground (every kind with an extent but terrain and
  districts, an interim list in `src/core/expand.ts`), each grown by the capsule radius. It goes
  when support reads the same ground partition as render, carved by exact clearance from the
  navigation table's obstruction axis. An extent contains everything its record
  generates, so a kept cell is one nothing covers, and a capsule stood anywhere on it meets none of
  those records in plan, at any height. That is the city descriptor's capsule clearance claim. The
  radius is the `radius_mm` measure the descriptor's nav_envelope contract states for
  `capsule_clearance` (340 mm for city version 2), carried into the generated table; core restates
  no number.

Every other record kind states the rule it waits on (`NEEDS` in `src/core/expand.ts`):
`ring_triangulation`, `massing_faces`, `facade_layout`, `bent_street`, `street_curbs`,
`kerb_offset`, `junction_fill`, `crossing_band`, `marking_stripes`, `form_parts` or
`support_clearance`. Relations, occupancies,
lanes, nodes and dressings are not surfaces of their own, and say so.

Every vertex of a drawn range must lie inside the extent its record states, or the tile is
refused.

### Terrain yield

The grammar says terrain is not a surface where a street, a block or a lot covers it.
`src/core/terrain-yield.ts` makes terrain give way to the ground the city descriptor's navigation
table says drawn records take (`navigation` in the generated table): the horizontal surfaces a
`support` kind has drawn, and the base ring a `cover` kind stands on, once that record is drawn. A
building stands on its lowest tier's ring, as the grammar reads its footprint. A record not drawn
yet takes no ground, so the world shows no hole where it will stand, and no stated extent ever
removes terrain, since that would cut holes nothing fills. Every record whose expander does not read
coverings is expanded first; entries are still written in record order. A cell no covering meets is
drawn exactly as the grid draws it.

Yielding costs vertices, and that is the price of the boundary being exact: on the conformance
tile, where three segments draw their carriageways and gutters, terrain goes from the grid's 289
vertices and 512 triangles to 483 and 572. A cell no covering meets keeps its two triangles.

A met cell is cut into pieces that each lie on one plane of the terrain. Each piece, less the union
of the coverings, is found exactly by a rational plan arrangement (`src/core/plan-arrangement.ts`)
and cut into convex faces along the rows of the covering vertices inside it. Each face is drawn as
the convex hull of the integer points round its vertices, cut by the ring rule, at the piece's
floored plane heights. The rule holds four claims, and `test/terrain-yield.test.ts` holds its
cases to each, in arithmetic of its own (`test/terrain-yield-claims.ts`):

- **No gap at all.** Every point of the patch that no covering's closed outline holds lies in a
  terrain triangle. That is stronger than any bound on a gap's size.
- **Bounded entry.** Every terrain point inside a covering lies within a millimetre of that
  covering's outline on each axis.
- **Watertight between cells.** Where a covering edge crosses a line two cells share, both cells
  take the same integer vertices there.
- **Heights.** Every vertex's height is the grammar's terrain surface there, floored.

No gap and no entry cannot both hold exactly with integer vertices. Two coverings can leave a
channel a millimetre square fits in whose integer points all lie on one line, so no terrain with
area fits inside it. The test keeps such a channel as a regression case. The rule chooses no gap:
a crack shows the background as a bright line, and a sliver of terrain under a millimetre inside a
covering is hidden where the covering is higher or lower than the terrain. **Known and not
measured:** where a covering is coplanar with the terrain, such as a parcel at grade, the sliver may
flicker in a band under a pixel. It is a runtime depth matter, to measure once such a covering is
drawn.

## Building blocks not yet wired

These are exact, tested and called by no bake yet, so they change no container. Each is wired in
by the expander that needs it, with a new tessellator version.

- `src/core/integer-math.ts` has checked integer arithmetic. It refuses any result a double would
  round, and gives floor division and the floor square root with no `Math`.
- `src/core/facing.ts` has the facing rule. It turns a local offset by an integer direction
  vector, scaled toward the grammar's direction bound and then floored.
- `src/core/ring-triangulation.ts` has the ring rule. It checks a ring by the grammar's own tests,
  then cuts it by ear clipping into counter-clockwise triangles on the ring's own vertices, in a
  stated order. A ring with holes, a tier with its light wells, is first joined to each hole by an
  exact bridge from the hole's greatest-x vertex to the nearest outer vertex it can see.
- `src/core/fillet-arc.ts` has the fillet arc rule. It builds the corner between two kerb lines
  by integer chord bisection. Centres and arc points follow the grammar's own corner rule
  (`document._corner_centre`), in BigInt. The segment count will come from the projection
  contract's `resolution_mm`: `filletSegmentsWithin` finds the least power of two whose chords keep
  within it. No number is chosen here.
- `src/core/streets.ts` has the street rules, in straight pieces only, and the segment rule is
  wired (see "What draws today"). A curb's straight part is a vertical kerb face, a kerb top and a
  footway rising by its crossfall. A junction's carriageway fill is one ring over each leg's strip
  mouth, the kerb lines back to the node and the corner arcs between legs, cut by the ring rule.
  Every point is placed by the grammar's corner rule measure. A bent street, a curb its tile does
  not carry or a leg it cannot find draws nothing and names the rule it waits on.
- `src/core/ring-clearance.ts` has the ring clearance rule. It covers everywhere a capsule of a
  given radius meets a ring with convex integer pieces: the ring itself, a band along each edge, and
  a hull round each corner that holds the corner's disk, its points bisected from the four axes as
  the fillet arc rule bisects, doubling until every chord is checked to clear the radius. It leaves
  nothing out and takes under five millimetres beyond, whatever the radius, which is what covering
  an arc with integer points costs. It is what support clearance will carve a building's base ring
  by, so no ring falls back to its plan box, which could close a footway that is open.
- `src/core/support-clearance.ts` has the support clearance rule. It carves support triangles
  away from obstruction boxes grown by the capsule radius. Each box is removed by clipping on the
  integer lines a millimetre outside it, so the pieces kept meet without cracks. Crossings are
  rounded inward, and heights are floored onto the support's own plane. No point kept is within
  the radius of an obstruction or outside its support. Which kinds are support and which obstruct
  is for the city descriptor to state per kind; the rule takes the boxes it is given.

`test/geometry-blocks.test.ts`, `test/streets.test.ts` and `test/support-clearance.test.ts` hold
each to its stated properties and pin outputs.

## The triangle digest

`src/core/triangle-digest.ts` defines it. Version 1 was written before either build; version 2
changes it only where city grammar version 2 changed what a record is.

**What enters.** There is one digest per projection. SHA-256 is taken over these
length-framed fields:

1. the domain `exulanica/owd-triangle-digest`;
2. the version `3`;
3. the projection name;
4. the number of entries, followed by one entry per record, owned or halo, in canonical order.

Each entry starts with four fields:

1. the record kind;
2. the record digest, SHA-256 of `canonical_record`;
3. the identity the record states, or `not-stated` for a kind that declares none;
4. the state (`drawn`, `unavailable`, `not_admitted`, `not_in_projection` or `halo`).

Its body follows. A drawn entry in `render_batch` gives the number of surfaces, as a signed 64-bit
integer, then five fields per surface, in the entry's order:

1. the role;
2. the record digest of the dressing material, or `none-exists`;
3. the orientation;
4. the triangles, as nine signed 64-bit big-endian millimetre integers each;
5. the surface coordinates, as six signed 64-bit integers per triangle.

Every other entry gives four fields: empty, empty, then the triangles for a drawn `nav_envelope`
entry, what it needs for an unavailable entry, or empty; then empty. Empty fields are still
framed.

**Surface coordinates** are millimetres in the frames the city grammar fixes
(`exulanica/grammar/grammars/city/common.py`). A texture's physical extent scales them.

- **Horizontal faces.** `t` is always to the left of `s`.
  - Terrain, lot, roof, a junction's carriageway, an awning, a tree pit and a part top use the
    plan: `s = x`, `t = y`.
  - A segment's carriageway and gutter, a kerb top, a footway, a crossing and a marking run along
    their segment's centreline.
- **Vertical faces.** `s` runs along the run from its start, and `t = base - z` points down.

**What does not enter:** the float32 payload, the index buffer (triangles are digested
de-indexed), texture bytes, header layout and padding, the frame and subject identity, and any
time.

**Order.** Entries sort by record kind, then record digest. A document never states an identity
twice, so it never repeats a record and the order is total. Triangles keep the expander's
emission order, which is a loop over the record's own fields. There is no spatial sort.

**Framing.** Every field is prefixed with its length as an unsigned 64-bit big-endian integer,
as `idempotency_key` does, because unframed concatenation is not injective.

## The `.owd` container

`src/core/owd.ts` is the only writer and holds the only reader. It is laid out like this:

1. `OWD3`;
2. a little-endian uint32 header length;
3. the header as canonical JSON;
4. space padding to a 16-byte boundary;
5. for each projection, contiguous sections:
   - `position_mm`: int32, offset from `origin_mm`;
   - `position`: float32 metres, payload;
   - in `render_batch` only, `surface_mm`: int32, offset from `surface_origin_mm`;
   - `index`: uint32.

Only the start of the data is aligned. Every element is four bytes wide, so no section needs
padding. This is ADR-0010's correction, carried over from OPM.

The header carries:

- the tile record and its inputs digest;
- the grammars, each with its pin, declared semantics, frame (`city_local` for city version 2),
  subject identity and external references;
- every record with its digest, stated identity, membership and grammar;
- per projection, its contract, the triangle digest, the origins, the counts and one entry per
  record.

A drawn entry is a contiguous range with its integer extent. So one lookup answers "which record
does this triangle belong to" and "what is that record's extent". In `render_batch` the range is
divided into surfaces: contiguous sub-ranges in the expander's order that cover it exactly, share
no vertex, and each state a role, a material and an orientation. A record repeats a role only on
another orientation (a kerb's vertical face and horizontal top). The decoder refuses surfaces that
overlap, leave a gap, share a vertex, repeat a role on one orientation, name a role their grammar
does not state, or cite a material for another record or role.

An earlier container is refused at its magic. There is no upgrade on read: rebake the tile.

Runtimes import two functions from `@exulanica/loom-tess/core`:

- `decodeOwd` checks the layout and returns typed-array views;
- `verifyOwd` rebakes the header's own records and compares every byte.

## Use

```bash
pnpm tess bake packages/loom-tess/test/fixtures/tile-conformance.json /tmp/tile.owd
```

```bash
pnpm tess verify /tmp/tile.owd
```

```bash
pnpm tess params
```

```bash
pnpm tess shapes
```

The bake is deterministic: the same document gives the same bytes on any machine and any Node
version. `evidence/2026-09-16-determinism.log.txt` records five runs of the version 1 Node entry
and browser entry, on Node 20 (arm64, and x86_64 under Rosetta), 24 and 26. It compares the
containers byte for byte and the digests against the version 1 golden literals. No such record
has been made for version 2 yet.

## What it does not do yet

- Draw any surface but terrain. Every other kind waits on a named rule.
- Materialise `collision_proxy` or `pick_geometry`. Each needs a representation contract first.
- Refuse unwalkable slopes in `nav_envelope`. No record states a slope limit, and the contract
  says so.
- Recompute membership from anchors, check named rules, or resolve references and catalog keys.
  The grammar's document validator does.
- See a record that covers this tile's ground but is neither owned nor halo. Terrain coverage is
  read from the records the document carries.
- Persist a bake or report a differing rebake. The table and its fault path arrive with
  migration 0072.
