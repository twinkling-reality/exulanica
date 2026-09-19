# The corridor's five tiles, rebaked into the store at tessellator 20

Written 2026-09-19 by the draw-the-neighbours lane on `lane/draw-neighbours` at `bfa398cb`, which is
main `bfa398cb`, with NOTHING REBAKED YET. Written first so the result cannot be read back onto it.

## Why a rebake was needed at all, and it is a gap rather than a decision

THE CORRIDOR IS UNREADABLE ON MAIN AS IT STANDS. `TESSELLATOR_SOURCE_VERSION` is 20 (`e7a24623`,
the coordinate unit lane) and `decodeOwd` refuses any other version by name: "tessellator_version is
not 20; there is no upgrade on read, rebake the tile". The store the corridor API serves holds 37
containers and every one of them is older.

Measured rather than inferred, from the lane worktree, which is this tree: `decodeOwd` over all 37,
36 refused for the version and 1 for its magic, ZERO decoded. Then every `.owd` over 200 KB on this
machine, under both `/private/tmp/claude-501` and `/Users/glendonchin/dev/Technology`: the only
tessellator 20 containers anywhere are copies of the conformance fixture, world `d0219dae` tile
(0,0), 703,588 bytes. THERE IS NO TESSELLATOR 20 MULTI-TILE WORLD ON THIS MACHINE.

So the street the visual gate scored on 2026-09-18 cannot be loaded by the tree that scored it. That
run is not suspect: it ran before the rebase onto a main carrying `e7a24623`, and its record
describes a bake that happened. What is missing is anything that would have SAID SO. A tessellator
version bump invalidates every baked artefact in every store, and the merge that bumped it was
verified by unit tests, by digests on the committed fixture, by boundaries and by typecheck, all of
which pass on a tree whose store it has just made unreadable. Nothing asks whether the artefacts a
tree serves can still be read by it.

## The values as they stand, before the rebake

Read from the five containers in the store at `EXULANICA_DATA_DIR`, with a tessellator 19 reader,
because this tree's reader refuses them. That reader is the clean checkout at `04552523`, read only.

| tile | container | bytes | render_batch | triangles | nav_envelope | triangles | facades |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: |
| (0,0) | `acf1474b` | 2,481,736 | `151b3809` | 9,148 | `92311579` | 7,122 | 117 |
| (1,0) | `8f218878` | 12,294,368 | `4e029987` | 52,366 | `77cfffff` | 121,530 | 275 |
| (2,0) | `e59f6cf0` | 12,682,828 | `fd4b6ebe` | 56,388 | `35388d78` | 96,745 | 325 |
| (3,0) | `5b5225f2` | 11,630,504 | `bb7442bc` | 57,132 | `72ad87e5` | 94,890 | 250 |
| (4,0) | `cb0de495` | 2,291,492 | `5dd06e95` | 8,293 | `dd856f5e` | 6,506 | 92 |

All five state tile record version 2, city grammar version 2 at descriptor `c82ac5e7`, and a tile
record whose fields are `catalog_digest`, `city_seed`, `edit_delta_digest`, `grammar_versions`,
`halo_radius_mm`, `halo_rule`, `lod`, `ownership_rule`, `tile_size_mm`, `tile_x`, `tile_y`. There is
no `coordinate_unit` among them.

**THE ONE INPUT THAT HAS NOT MOVED, CHECKED BECAUSE IT WOULD HAVE CONFOUNDED EVERYTHING BELOW.** The
containers state `catalog_digest` `97db1e8d11f069fe1e295d2d3aac5780c67f10a4ea0f64b03772f0a732f27aad`
and this tree computes exactly that from `catalog_digest(load_city_catalogs())`. A moved catalog
would move the container and the tile inputs digest for a second reason, and a reader would have no
way to separate the two causes. It has not moved, so this rebake isolates ONE change: the city
grammar from version 2 to version 3, and the tessellator from 19 to 20.

## What that change is, read from the tree rather than assumed

`CITY_GRAMMAR_VERSION` is 3 (`descriptor.py`), so the generator now writes version 3 documents. The
coordinate unit lane already measured what that does to the conformance fixture, and it SPLIT the
two halves, which is why the prediction below can be sharp rather than a shrug:

- **the tessellator bump alone is inert on geometry.** A version 2 document baked at 20 against the
  committed 19 golden: all seven sections byte-identical, `tessellator_version` the only header key
  that differs, both triangle digests and `tile_inputs_digest` unchanged.
- **the document change is what moves things.** The tile record gains `coordinate_unit` and goes to
  version 3; its grammar pin goes to version 3 at descriptor `e771deef`; and every `city.facade`
  record carries a `grammar_version` field (`facade.py:318`) which moves 2 to 3. Facades are the only
  records in a city document with such a field.

## The prediction

**1. All five container digests MOVE.** The header carries `tessellator_version`, the tile record and
the grammar entries, and all three change.

**2. All five `tile_inputs_digest` values MOVE.** That digest is over the tile record's own canonical
payload, which gains a field and a version and a new grammar pin.

**3. All five `render_batch` triangle digests MOVE.** The triangle digest's definition puts each
record's canonical payload digest into every entry, whatever that entry's state, so the facades alone
move it: 117, 275, 325, 250 and 92 of them.

**4. ALL FIVE `nav_envelope` TRIANGLE DIGESTS MOVE TOO, and this one is worth stating because the
last corridor rebake's headline was the opposite.** Going 17 to 19, every nav digest HELD, and the
record for it says "that is the fourth version across which the navigation projection has not moved
for a facade change". It will move this time, and not because any ground changed: a facade's payload
digest reaches `nav_envelope`'s entries exactly as it reaches `render_batch`'s, through the same
clause, even though a facade draws no navigation triangle. IF A NAV DIGEST HOLDS, MY READING OF THAT
CLAUSE IS WRONG and I want to know.

**5. NOT ONE TRIANGLE MOVES, in either projection, on any of the five.** The version 2 to 3 migration
carries all 91 parameters with multiply 1 and add 0 and maps every choice to itself, so no geometry
rule and no parameter changes. Checked as the MULTISET of absolute integer triangles, hashed
order-independently, because a digest that moves for the reason in items 3 and 4 can say nothing
about this. **THIS IS THE FALSIFIABLE HALF. If a multiset moves, the bake stops here**, because that
is geometry changing under a schema change and it is not what the fixture did.

**6. `render_batch`'s triangle SEQUENCE moves on all five; `nav_envelope`'s sequence HOLDS on all
five.** `tessellate` sorts records by `(kind, sha256)`, so a record's place among its siblings is
content-addressed: the facades reorder within their own kind, and every triangle they draw travels
with them. A facade contributes no triangle to `nav_envelope`, so the reordering is visible there in
the entry list and not in the triangles. This is item 5 split by order, and it is the half the
coordinate unit lane got wrong on the fixture by predicting identical vertex sequences.

**7. Triangle and vertex COUNTS are unchanged, both projections, all five.** Item 5 implies it, and
counting is a cheaper instrument than hashing a multiset, so a disagreement between the two would be
an instrument fault rather than a finding.

**8. Every container grows by EXACTLY 32 BYTES.** The fixture went 703,556 to 703,588 for this same
document change, and the only length change is `coordinate_unit` in the tile record: version 2 to 3
and descriptor to descriptor are the same width. Section alignment could round this, in which case
the growth is the same on all five and I would rather be wrong about the number than vague about it.

**9. Both bake passes identical on every tile**, which is what the script's second pass exists to
check and what migration 0072 records a fault for.

**10. Five new rows, and the tessellator 19 rows untouched**, because a new tessellator version takes
its own `baked_tile_id`. The gate's retained records bind the tessellator 19 digests and stay
correct: a record describes a bake that happened, and nothing under `docs/evaluation/` is edited.

**11. The undressed set is unchanged in kind on every tile**: facade ground bands and the terrain,
and nothing else, as the 17 to 19 rebake recorded.

## How each will be checked

Items 1 to 4 and 7 and 8 from the containers' own headers, before and after. Items 5 and 6 from the
absolute integer triangles of both projections, hashed twice per projection: once sorted, which is
the multiset, and once in emission order, which is the sequence. Item 9 from the bake script's own
second pass. Item 10 from the rows. Item 11 from each row's receipt.
