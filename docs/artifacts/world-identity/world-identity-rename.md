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

**Prediction 1 held exactly.** `world-listing-before.log.txt` was taken at 0359dda3 on a clean
tree and `world-listing-after.log.txt` at de34e1ca on a clean tree. `diff` reports FOUR lines,
which is the two predicted lines on each side:

    listing method  tiles_of_city   ->  tiles_of_world
    commit          0359dda3        ->  de34e1ca

Nothing else differs. All four counts came back as predicted: 4 tiles for the world under test out
of 6 bakes recorded, 1 for another world, 3 narrowed to level of detail 0, 0 for a world nothing
was baked for, and every one of the 6 bakes still reachable by key including the two the listing
narrows away.

**Prediction 2 held by construction and was not separately measured.** No bake ran. The column is
a name; `tile_inputs_digest`, `container_sha256` and both projection digests are computed over
bytes this change does not read. Recorded as INFERRED rather than measured, because inferring it
is exactly the move this project keeps paying for, and the honest form is to say which it is.

**Prediction 3 was measured** by the route test described below, which asks the real application
through its real client over a real migrated schema.

## The falsification

`docs/artifacts/world-identity/falsification-cases.json`, run with `scripts/falsify.py` from the
committed tree de34e1ca. Six breaks, EACH APPLIED ALONE, each over both whole test files rather
than under a `-k` filter, each restored and the restored bytes compared by digest.

    the migration adds world_seed BESIDE city_seed instead of renaming it   REFUSED
    the index keeps the old word while its column carries the new one       REFUSED
    the repository asks the old column for a world                          REFUSED
    the record path reads the column's spelling out of a tile record        REFUSED
    the route drops the alias, so the wire moves with the column            REFUSED
    the route answers the new spelling in a body key nothing reads          REFUSED

Each was refused BY THE TEST THAT CLAIMS THE PROPERTY, compared by node id identity rather than by
substring. **23 tests were asked in every one of the six runs, and 23 is what those two files pass
unbroken**, so nothing was skipped, deselected or switched off in any break: the count that says
the question was put is the same count as the population.

The first break is the one worth keeping. It reproduces the failure this whole exercise was most
at risk of, and the brief named it in advance: a column ADDED beside the old one rather than
renamed leaves every row's identity behind, every listing comes back EMPTY, and an empty listing
is exactly what a world with no tiles looks like. It raises nothing. A test asserting only that
`world_seed` exists would have passed it, which is why the assertion is two-way (the new name is
present AND the old one is gone) and why it also reads the value back through the listing.

**What the falsification did NOT establish**, stated so nobody takes it wider. `tests` is a
SELECTION: these six verdicts say the property is pinned in the two files named, not that nothing
else in the repository claims it. And no break here could produce a silent wrong answer, because
every wrong spelling on this path raises: a missing column is `UndefinedColumn`, a missing mapping
key is `KeyError`. The silent case exists only for the first break, and it is covered.

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
