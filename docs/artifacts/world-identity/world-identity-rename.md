# A generated world has an identity, and `city_seed` was not its name

The identity of a generated world instance was spelled `city_seed` in the storage and routing
layers every world kind must pass through. A city is one kind of world, so the spelling made the
container's name the name of one of its contents. This record is what the backend half of the
rename measured.

## The prediction, written before the rename

Stated here before a line of it was written, so it cannot be fitted to the result afterwards.

1. **The listing is unchanged.** `docs/artifacts/world-identity/world-listing-control.py.txt` run
   as `tiles_of_city` before the rename and as `tiles_of_world` after it produces two logs that
   differ on EXACTLY TWO LINES, `listing method` and `commit`, and nowhere else. Every baked tile
   id, coordinate, level of detail, digest, byte count and state is identical, and so are the
   four counts: 4 tiles for the world under test, 1 for another world, 3 narrowed to level of
   detail 0, 0 for a world nothing was baked for.
2. **No digest of anything baked moves.** The column is a fact about a row. The tile record's own
   field is untouched tonight, so `tile_inputs_digest`, `container_sha256` and both projection
   digests are computed over the same bytes as before. Nothing is rebaked and nothing needs to be.
3. **The route's answers are byte-identical.** Both of its wire spellings are kept deliberately,
   so a client sees no change at all.

The prediction that would have been easy to make and would have been wrong: that renaming the
column moves `walk-world.ts`. It does not. That reader takes the identity from
`decodeOwd(bytes).header.tile`, THE CONTAINER'S OWN BYTES, and the container is moved by the tile
record's version, not by a column. The two are different artefacts and the lane brief conflated
them; the orchestrator verified the correction before this work started.

## The result

Answered after the rename landed.

## What the route does, and why it is not a mistake

The route keeps BOTH of its public spellings: it is still asked
`GET /tiles?city_seed=<64 hex>` and it still answers a body whose top-level key is `city_seed`.
Everything behind them says `world_seed`.

That is a decision rather than an omission, and the reason is that a column and a wire name are
different objects with different costs. Renaming the column costs one migration inside this
repository. Renaming the wire costs a coordinated change in `web/packages/atlas-react`, which one
line of production code reads:

    web/packages/atlas-react/src/playcanvas/generated-tile/tile-route.ts   builds ?city_seed=
    web/packages/atlas-react/test/generated-tile-route.test.ts             asserts the literal URL
    web/packages/app/test/generated-tile-walk.test.ts                      asserts the literal URL

The response's top-level key is a third case and it is worth stating separately: it is written by
this route and READ BY NOBODY. `summaryOf` in `tile-route.ts` takes ten keys out of each entry of
the `tiles` array and never looks at the body's own key, and the three places that spelling appears
in web tests are all stubs BUILDING a fake response rather than reading a real one. So renaming it
would have been free and it was still not done, because half a renamed wire is harder to read than
either whole one.

`tests/test_corridor_tile_route.py` holds the route to both spellings on purpose. Without that,
this paragraph would be prose sitting where nothing checks it, and the next reader could not tell
a decision from an oversight. With it, the wire rename cannot happen by accident either: that test
is what a later commit has to change deliberately.

The route was NOT made to accept both spellings. A parameter admitting two names is a gate that
enumerates, and a reader here refuses an unrecognised name rather than widening to admit it.

## What is left, and it is not small

The tile record's own field is still `city_seed`, so the container still states that spelling and
`walk-world.ts` still reads it. Renaming it is a schema change at city grammar version 4, decided
by the orchestrator on 2026-09-18 to ride with nothing else, because the rebake is cheap (1.35 s
per tile) and a version carrying two schema changes makes a moved digest impossible to attribute.
