# The readers that took one answer out of the whole table list

Measured 2026-09-18 on `lane/coordinate-unit`, cut from local main at `06d09267`. Both trees ran
with `web/node_modules` installed offline, so nothing here was measured against a missing toolchain.

Main moved while this lane was open, so the measurement was taken twice rather than relabelled. The
first pass compared `06d09267` against the change at `574a569a`. Main then reached `4b237488`, whose
four new commits touch nothing in this package but one evidence file, and after rebasing the lane
to `bfd8924c` the same bake was taken again on both `4b237488` and `bfd8924c`. Every figure below is
the same in all four readings. The digests in the table are quoted from the rebased pair.

## What was wrong

`GRAMMAR_TABLES` holds one grammar table, and ten places in `src/core` were correct only because of
that. Two were indices: `document.ts` and `owd.ts` each read the tile record's shape out of
`GRAMMAR_TABLES[0]`, so a second table would have been used for every document whatever version the
document pinned. Four more were bound to `CITY_V2` by name (`TILE_SHAPE`, `SEMANTICS_SHAPE`, and
`PROJECTIONS` and `PLANE` derived from the second). Two were in `bake.ts`, where a map keyed by
record kind would have taken whichever table came last and a fixed bound would have taken whichever
came first. One passed an entry's own table alongside another table's semantics shape. One printed
a single plane and projection list for every grammar.

`test/grammar-table.test.ts` asserted `GRAMMAR_TABLES` equals `[CITY_V2]`, so adding a table does
fail a test. That alarm is on the list's CONTENTS, and the cheapest way to quiet it leaves every
reader of the list exactly as wrong as it was.

## What the change does

A tile record is read against the table its own grammar pin names (`document.tileTableOf`), in both
the document reader and the container header reader. A shape a table declares is reached through
that table (`tileShapeOf`, `semanticsShapeOf`). A value that belongs to the contract rather than to
a version is held equal across every table before being stated once (`agreedAcrossTables`, and in
`bake.ts` the fixed bounds and the record versions).

## Proved inert, by measurement

The conformance fixture baked in both trees through `packages/loom-tess/src/node/cli.ts`:

| | before, main `4b237488` | after, lane `bfd8924c` |
| --- | --- | --- |
| container sha256 | `bd07246dbeb9b1116498a233ede7790da2cbcf8eeef1024b4e33682460f351c1` | same |
| container bytes | 703556 | same |
| `tile_inputs_digest` | `5dd2dcb5de5b684fc485e4c2ad3b25bdc89c0f9ce3a73e4af043e13ec4b75b22` | same |
| `render_batch` triangle digest | `3aee7162da258e98e1de96ba73a551d0b578a97263eda013d9a7608fb0b1cd7e` | same |
| `nav_envelope` triangle digest | `dcd548bde8d8ca988c1e3b433c9515fe6531c95d7a5f4085d627e1b54e7eb811` | same |
| `BAKE_PARAMETERS` | canonical JSON compared whole | same |

A length is not an identity, so the sizes agreeing is recorded and the digests were compared anyway.
The digest is known to be capable of moving: `triangle-digest-conformance.test.ts` holds a case that
moves it when one integer of the fixture moves, and it passes.

## Falsified: seven breaks, each alone, on a committed tree

Each break was planted alone at `574a569a`, the lane's pre-rebase head, the WHOLE
`packages/loom-tess` suite was run rather than
a filtered selection, the failing test names were read, and the tree was restored with
`reset --hard` plus `clean` and the restored state printed. 278 tests in the package.

| Break | Tests failed | Which |
| --- | --- | --- |
| `readTileDocument` takes `GRAMMAR_TABLES[0]` | 2 | both document version refusals |
| `decodeOwd` takes `GRAMMAR_TABLES[0]` | 1 | the container version refusal |
| `agreedAcrossTables` returns the first, no check | 1 | the agreement test |
| `recordShapeVersions` overwrites a repeated kind | 1 | the one-version-a-kind test |
| `boundOf` returns the first bound | 1 | the fixed bound test |
| `tileTableOf` takes the first of two pins | 1 | the two-pins refusal |
| `tileTableOf` does not check a pin exists | 1 | the no-pin refusal |

No break passed. The count is not zero for any of them.

**The most useful line in the logs** is from the first break. With the positional read restored, a
document pinning city version 9 is refused with

    tile.fields: missing keys ["lod"]

rather than with anything about the version. That is ADR-0024's failure in miniature: the reader read
a document of one version against another version's shape, and reported a FIELD as the fault.

## What these breaks establish, and what they cannot yet

They establish that the selection function addresses by identity (reversing a two-table list does not
change its answer), that both readers call it, and that each refusal fires and names the right thing.

They do NOT yet establish that a document of a second version is read against that version's own
table END TO END, because `GRAMMAR_TABLES` still holds one table: with one table there is no wrong
table to pick, so the positional break is caught by the refusal MESSAGE rather than by a wrong shape
being used. The two-table list in `grammar-table.test.ts` is built from `CITY_V2` itself with one
field moved, which is the real table rather than this test's idea of one, but it reaches the
selection function directly and not through `readTileDocument`. That last step becomes measurable
when a second table is actually read.
