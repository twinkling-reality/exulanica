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

Canonical JSON, integers and printable ASCII only, in the grammar's record vocabulary
(`src/core/document.ts` has the full shape). It holds:

- the `city.tile` record;
- one entry per grammar the tile names, each with its descriptor digest, its declared semantics
  and its records.

The reader refuses anything that is not already canonical, as well as:

- an unknown or missing key;
- an integer outside its grammar bound;
- an unknown record kind;
- a repeated record;
- a tile at a level of detail this version does not draw.

`src/core/record-shapes.ts` transcribes the grammar's record shapes. The Python suite
(`tests/test_bake_determinism.py`) compares them, field by field and bound by bound, with
`exulanica/grammar/grammars/city`.

A projection is emitted for a record only when its grammar's declared semantics admit it. City
version 1 admits none, so a real city tile draws nothing today.

Two projections are materialised, each built from the records by its own rules:

- `render_batch` is what is drawn. Its ranges carry a material reference, an orientation and
  surface coordinates.
- `nav_envelope` is what a person is supported by. Its only admissible use is sampling support
  height.

Each carries a representation contract in the header (`PROJECTION_DEFINITIONS` in
`src/core/expand.ts`). Navigation is never read back out of the render mesh.

`collision_proxy` and `pick_geometry` wait for contracts of their own.

## The triangle digest

`src/core/triangle-digest.ts` defines it and was written before either build.

**What enters.** There is one digest per projection. SHA-256 is taken over these
length-framed fields:

1. the domain `exulanica/owd-triangle-digest`;
2. the version `1`;
3. the projection name;
4. the number of entries, followed by one entry per record in canonical order.

Each entry has eight fields:

1. the record kind;
2. the record digest, SHA-256 of `canonical_record`;
3. the identity the record states, or `not-stated`;
4. the state (`drawn`, `unavailable`, `not_admitted` or `not_in_projection`);
5. the material reference (drawn entries in `render_batch` only);
6. the surface orientation (drawn entries in `render_batch` only);
7. for a drawn entry, the triangles, as nine signed 64-bit big-endian millimetre integers each;
   for an unavailable entry, what the record kind lacks;
8. the surface coordinates, as six signed 64-bit integers per triangle (drawn entries in
   `render_batch` only).

Empty fields are still framed.

**Surface coordinates** are millimetres in the frames the city vocabulary lane fixed on
2026-09-16. A texture's physical extent scales them.

- **Horizontal faces.** `t` is always to the left of `s`.
  - Terrain, lot and roof use the plan: `s = x`, `t = y`.
  - Street surfaces run along their segment's centreline from its start node.
- **Vertical faces.** `s` runs along the run from its start, and `t = base - z` points down.

Only terrain draws today.

**What does not enter:** the float32 payload, the index buffer (triangles are digested
de-indexed), texture bytes, header layout and padding, and any time.

**Order.** Entries sort by record kind, then record digest. A document never repeats a record,
so the order is total. Triangles keep the expander's emission order, which is a loop over the
record's own fields. There is no spatial sort.

**Framing.** Every field is prefixed with its length as an unsigned 64-bit big-endian integer,
as `idempotency_key` does, because unframed concatenation is not injective.

## The `.owd` container

`src/core/owd.ts` is the only writer and holds the only reader. It is laid out like this:

1. `OWD1`;
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
- the grammars;
- every record with its digest and stated identity;
- per projection, its contract, the triangle digest, the origins, the counts and one entry per
  record.

A drawn entry is a contiguous range with its integer extent. So one lookup answers "which record
does this triangle belong to" and "what is that record's extent".

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
version. `evidence/2026-09-16-determinism.log.txt` records five runs of the Node entry and the
browser entry, on Node 20 (arm64, and x86_64 under Rosetta), 24 and 26. It compares the
containers byte for byte and the digests against the golden literals.

## What it does not do yet

- Draw anything but terrain. Everything else waits on record fields the grammar does not carry
  (`src/core/expand.ts`, `NEEDS`), routed to the city vocabulary lane.
- Materialise `collision_proxy` or `pick_geometry`. Each needs a representation contract first.
- Refuse unwalkable slopes in `nav_envelope`. No record states a slope limit, and the contract
  says so.
- Check that a subject lies in its tile, or that a record belongs to a stage of the grammar it is
  listed under. The Python side checks the second for the fixture.
- Persist a bake or report a differing rebake. The table and its fault path arrive with
  migration 0072.
