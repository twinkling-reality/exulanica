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
  identity derives from, and two sorted lists of records: `owned` and `halo`.

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
(`tests/fixtures/city-v2/record-shapes.json`) and the descriptor's frame. It is generated, not
transcribed:

```bash
pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts
```

`test/grammar-table.test.ts` and `tests/test_bake_determinism.py` fail when it differs from
either source.

A projection is emitted for a record only when its grammar's declared semantics admit it. City
version 2 admits `render_batch` and `nav_envelope`, among others.

Two projections are materialised, each built from the records by its own rules:

- `render_batch` is what is drawn. Every drawn range is dressed by the surface material record
  that names the range's record and role, and carries its orientation and surface coordinates. A
  surface nothing dresses is unavailable, not drawn plain.
- `nav_envelope` is what a person is supported by. Its only admissible use is sampling support
  height.

Each carries a representation contract in the header (`PROJECTION_DEFINITIONS` in
`src/core/expand.ts`). Navigation is never read back out of the render mesh.

`collision_proxy` and `pick_geometry` wait for contracts of their own.

## What draws today

Only terrain, and only where nothing covers it.

The grammar says terrain is not a surface where a street, a block or a lot covers it, and that no
published texture set dresses terrain. So:

- in `render_batch`, the fixture's terrain is unavailable, needing `surface_material`;
- in `nav_envelope`, a terrain cell is drawn when its closed plan square meets the stated extent
  of no record that covers the ground (every kind with an extent but terrain and districts). An
  extent contains everything its record generates, so a kept cell is one nothing covers.

Every other record kind states the rule it waits on (`NEEDS` in `src/core/expand.ts`):
`ring_triangulation`, `massing_faces`, `facade_layout`, `segment_surface`, `kerb_offset`,
`junction_fill`, `crossing_band`, `marking_stripes` or `form_parts`. Relations, occupancies,
lanes, nodes and dressings are not surfaces of their own, and say so.

Every vertex of a drawn range must lie inside the extent its record states, or the tile is
refused.

## The triangle digest

`src/core/triangle-digest.ts` defines it. Version 1 was written before either build; version 2
changes it only where city grammar version 2 changed what a record is.

**What enters.** There is one digest per projection. SHA-256 is taken over these
length-framed fields:

1. the domain `exulanica/owd-triangle-digest`;
2. the version `2`;
3. the projection name;
4. the number of entries, followed by one entry per record, owned or halo, in canonical order.

Each entry has eight fields:

1. the record kind;
2. the record digest, SHA-256 of `canonical_record`;
3. the identity the record states, or `not-stated` for a kind that declares none;
4. the state (`drawn`, `unavailable`, `not_admitted`, `not_in_projection` or `halo`);
5. the record digest of the dressing material (drawn entries in `render_batch` only);
6. the surface orientation (drawn entries in `render_batch` only);
7. for a drawn entry, the triangles, as nine signed 64-bit big-endian millimetre integers each;
   for an unavailable entry, what it needs;
8. the surface coordinates, as six signed 64-bit integers per triangle (drawn entries in
   `render_batch` only).

Empty fields are still framed.

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

1. `OWD2`;
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
- the grammars, each with its pin, declared semantics, frame (`city_local` for city version 2)
  and subject identity;
- every record with its digest, stated identity, membership and grammar;
- per projection, its contract, the triangle digest, the origins, the counts and one entry per
  record.

A drawn entry is a contiguous range with its integer extent. So one lookup answers "which record
does this triangle belong to" and "what is that record's extent".

A version 1 container is refused at its magic. There is no upgrade on read: rebake the tile.

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

- Draw any surface but exposed terrain in `nav_envelope`. Every other kind waits on a named rule.
- Materialise `collision_proxy` or `pick_geometry`. Each needs a representation contract first.
  The city descriptor's `nav_envelope` contract also names capsule clearance, which this
  `nav_envelope` does not carve; its contract says so.
- Refuse unwalkable slopes in `nav_envelope`. No record states a slope limit, and the contract
  says so.
- Recompute membership from anchors, check named rules, or resolve references and catalog keys.
  The grammar's document validator does.
- See a record that covers this tile's ground but is neither owned nor halo. Terrain coverage is
  read from the records the document carries.
- Persist a bake or report a differing rebake. The table and its fault path arrive with
  migration 0072.
