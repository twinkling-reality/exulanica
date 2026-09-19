# loom-tess fixtures

These files are for tests. No stage emits them, and none may be served.

## `tile-conformance.json`

This is the conformance tile. The golden triangle digests in
`../triangle-digest-conformance.test.ts` are computed over it.

It is a byte copy of the city grammar's hand-written tile,
`tests/fixtures/city-v2/tile-document.json`, which the city vocabulary lane writes with
`tests/fixtures/city-v2/build_fixture.py` and the grammar's own `validate_city_document` admits.
The builder writes it at whatever city grammar version this tree states, which is version 3; the
directory it lives in keeps the name it was created under, and that name is historical.
`tests/test_bake_determinism.py` fails if the copy and its source differ. When the source moves:

```bash
cp tests/fixtures/city-v2/tile-document.json web/packages/loom-tess/test/fixtures/tile-conformance.json
```

Then update the golden literals in the same commit.

The tile is one T-junction with a signalised crossing on two arms, a block with two lots, a
four-storey building with a chamfered corner under 1.2 m, a set-back top storey and a light well,
ground bays with vitrines behind their glazing, 81 surface materials bound to pinned texture sets,
street furniture, a tree, and a terrain patch covering the tile. Every value comes from the
grammar's records and catalogs, and none is a placeholder.

## `tile-city-v2.json`

A tile document at city grammar VERSION 2, which states no `coordinate_unit`: ADR-0024 put that
field in the tile record at version 3, and a reader must go on reading what was written before it.

It is not built by any test. It is `tile-conformance.json` exactly as the version 2 Python grammar
wrote it, frozen at the commit the grammar moved on, so a misreading of the document format on the
TypeScript side could not have produced it. That is the whole point of keeping it: a version 2
document this package built from its own idea of version 2 would share any such misreading with the
reader under test.

It is never regenerated. If version 2 ever needs a different version 2 document, take it from this
repository's history rather than from a builder that no longer describes that version.

Tests that need a drawn `render_batch` range add one material record dressing the terrain
(`dressedTerrainObject` in `../support.ts`). That variant is test only: the grammar admits no
terrain material in version 2, so its own validator refuses it.
