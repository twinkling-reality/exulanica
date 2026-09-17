# loom-tess fixtures

These files are for tests. No stage emits them, and none may be served.

## `tile-conformance.json`

This is the conformance tile. The golden triangle digests in
`../triangle-digest-conformance.test.ts` are computed over it.

It is a byte copy of the city grammar's hand-written version 2 tile,
`tests/fixtures/city-v2/tile-document.json`, which the city vocabulary lane writes with
`tests/fixtures/city-v2/build_fixture.py` and the grammar's own `validate_city_document` admits.
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

Tests that need a drawn `render_batch` range add one material record dressing the terrain
(`dressedTerrainObject` in `../support.ts`). That variant is test only: the grammar admits no
terrain material in version 2, so its own validator refuses it.
