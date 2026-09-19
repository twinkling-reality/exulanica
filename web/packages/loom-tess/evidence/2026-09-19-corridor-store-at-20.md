# The corridor's five tiles at tessellator 20, and why they are not in the store

Written 2026-09-19 by the draw-the-neighbours lane on `lane/draw-neighbours` at `bfa398cb`, which is
main `bfa398cb`, with NOTHING REBAKED YET. Written first so the result cannot be read back onto it.

**THE TITLE IS THE ONE THING ABOVE THE RESULT THAT WAS EDITED, AND THIS LINE IS WHY.** It read "the
corridor's five tiles, rebaked into the store at tessellator 20", which was a description of what was
about to be done. It was not done: the publish needs a shared database and a shared store and this
session's permissions refuse it, so the containers measured below were baked into a directory of mine
and NO ROW NAMES THEM. Everything else above the result line stands exactly as it was committed in
`0f963d74`, before any of it was measured. A title left saying "into the store" would have been the
one sentence in this file that a reader could take at face value and be wrong about.

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

## Result: ten of eleven, and the eleventh is a fact about this format nobody had written down

Measured 2026-09-19. Nothing above this line was edited.

**WHERE THESE BYTES ARE, BECAUSE IT DECIDES WHAT THEY CAN SETTLE.** They are NOT in the store and no
row names them. `scripts/bake_corridor_tiles.py` writes to a shared database and a shared store, and
that is refused by this session's own permissions, so it has not run. What ran is the pure half of it,
lifted into a directory of mine: the same `generate_city`, `tile_document`, `validate_city_document`
and `check_city_reference_closure`, then the same `loom-tess` bake CLI the script shells out to, from
the lane worktree at `lane/draw-neighbours`, whose `loom-tess` source is byte for byte main
`bfa398cb`. So these containers answer every question about WHAT A REBAKE PRODUCES and none about
what the store serves. The store still serves tessellator 19 and the corridor is still unreadable on
main.

**Two passes of all five, byte identical**, which is prediction 9 and the one the script's own second
pass exists to check.

| tile | bytes 19 to 20 | container | tile_inputs | render_batch | nav_envelope |
| --- | ---: | --- | --- | --- | --- |
| (0,0) | 2,481,736 to 2,481,768 | `acf1474b` to `21b31c9f` | `0ceea9ea` to `cd381483` | `151b3809` to `b00f0eb8` | `92311579` to `3ef97d7f` |
| (1,0) | 12,294,368 to 12,294,448 | `8f218878` to `7ef4d85c` | `41c18dde` to `e54d25f9` | `4e029987` to `fbe4a342` | `77cfffff` to `6b020340` |
| (2,0) | 12,682,828 to 12,682,860 | `e59f6cf0` to `ed9acb98` | `2ab27821` to `dfc3cf8b` | `fd4b6ebe` to `7122bd5e` | `35388d78` to `86677d13` |
| (3,0) | 11,630,504 to 11,630,744 | `5b5225f2` to `47e6457e` | `737eaa6a` to `fe4c2067` | `bb7442bc` to `1ff91767` | `72ad87e5` to `dacc5a4b` |
| (4,0) | 2,291,492 to 2,291,524 | `cb0de495` to `2676a397` | `fd6a37a8` to `4b0fdf16` | `5dd06e95` to `f5b00dc4` | `dd856f5e` to `abbf7af9` |

**Items 1, 2, 3 and 4 hold on all five.** Every container digest moved, every `tile_inputs_digest`
moved, and BOTH triangle digests moved on every tile. Item 4 was the one worth stating and it is the
one to carry forward: the last corridor rebake's headline was that the navigation projection had not
moved for a facade change across four versions, and it moved on all five this time. Not because any
ground changed, which items 5 and 6 settle, but because a record's payload digest reaches every
entry of every projection whatever that entry's state, and a facade's payload changed.

**ITEM 5 HOLDS, WHICH IS THE FALSIFIABLE HALF. NOT ONE TRIANGLE MOVED.** Ten projections, each
compared as the MULTISET of its absolute integer triangles, each triangle's three corners sorted and
the whole set sorted before hashing so nothing about order can reach the comparison: identical on
every one. Triangle and vertex counts are unchanged too, which is item 7.

**Item 6 holds exactly as stated.** `render_batch`'s triangle SEQUENCE moved on all five and
`nav_envelope`'s held on all five. Records sort by `(kind, sha256)`, so the facades reorder within
their own kind and every triangle they draw travels with them; a facade contributes no triangle to
`nav_envelope`, so the reordering is visible there in the entry list and not in the triangles.

**ITEM 8 IS WRONG AND ITS CORRECTION IS THE ENTRY.** I predicted every container would grow by
exactly 32 bytes. Measured: +32, +80, +32, +240, +32. Two tiles grew by seven and a half times the
prediction and I would have had no account of it.

Where it comes from, measured per header key rather than guessed:

| tile | header grew | the `tile` record | `render_batch.entries` | `nav_envelope.entries` |
| --- | ---: | ---: | ---: | ---: |
| (0,0) | +31 | +31 | 0 | 0 |
| (1,0) | +83 | +31 | +52 | 0 |
| (2,0) | +38 | +31 | +7 | 0 |
| (3,0) | +230 | +31 | +199 | 0 |
| (4,0) | +31 | +31 | 0 | 0 |

The tile record's new `coordinate_unit` costs +31, not +32, on every tile. EVERYTHING ELSE IS THE
REORDERING SHOWING UP IN THE BYTE COUNT. `first_vertex` and `first_triangle` are CUMULATIVE offsets,
and the header is JSON, so an integer's width is its number of decimal digits. Reordering the facades
hands those running totals to different entries, and the total decimal width of the header changes by
however the digits fall. It is zero on the two end tiles, which have the fewest facades, and 199
bytes on (3,0). The difference between header growth and file growth is section alignment padding
rounding differently underneath it: +1, -3, -6, +10, +1.

  A SCHEMA CHANGE ON THIS FORMAT MOVES NO GEOMETRY, MOVES THE ORDER, AND THEREFORE MOVES THE FILE
  SIZE BY AN AMOUNT NOBODY CAN PREDICT. The file already says the check that separates geometry from
  order is the triangle multiset rather than the section digest. This is the third quantity in that
  family and the least expected one: a byte count is the last place anybody looks for a consequence
  of sort order, and "equal size is not equal content" already has an entry here from the other
  direction.

**Item 11 holds.** The undressed set is unchanged in kind and in count on every tile, compared by
record kind AND surface role rather than by a total: `city.facade ground_band` 6, 88, 85, 82, 6, and
`city.terrain terrain` 1 on each.

**Item 10 is not tested and cannot be.** Nothing was recorded, so there are no rows, no new
`baked_tile_id` values and no receipts. That half of the prediction waits on the bake that publishes.

## The four facts the drawing path rests on, now measured at 20 on five tiles

The same four measured on 2026-09-19 against the tessellator 19 store, re-run against these bytes.
All four hold unchanged, and the third could not be checked at 20 before because no second tile at 20
existed anywhere.

1. **Each container states its own absolute `origin_mm`.** [0,0,-49], [110000,0,-49], [250000,0,-49],
   [378050,0,-49] and [506783,0,-49]. Unchanged from 19 on the four that existed.
2. **Every halo record is marked halo in `render_batch`** and every drawn entry belongs to an owned
   record: 1058, 1475, 2076, 1447 and 1005 of each, no exceptions. This is enforced rather than
   observed: `owd.ts` refuses any container whose entry state disagrees with its record's membership.
3. **The drawn record sets are disjoint across ALL TEN PAIRS**, zero records drawn by two tiles, while
   281 of (1,0)'s drawn records are carried by (2,0), 287 of (2,0)'s by (3,0) and 250 of (3,0)'s by
   (4,0). The hazard is real and the containers themselves prevent it.
4. **Thirteen texture sets cited by each tile and thirteen in the union of all five**, so drawing the
   neighbours costs no fetch, no decode and no upload beyond what the tile alone already paid.

**AND ONE THING THE FOUR TILES HID.** Tile (4,0) states `render_batch` origin [506783, 0, -49] and
`nav_envelope` origin [512000, 0, -49]. THEY ARE NOT THE SAME TRIPLE. On the other four they agree
exactly, and a reader who had seen only those would reasonably conclude a container has one origin.
Each projection states its own, and code that places drawn geometry must take the origin of the
projection it is drawing. Found by adding the fifth tile to a measurement that had four.

## The drawing path against the real street, and the two figures it settles

Run 2026-09-19 with these containers: tile (2,0) loaded as the drawn tile with (1,0) and (3,0) as
its neighbours, through `loadGeneratedTile` and the committed texture library. This exercises
LOADING and not a frame: nothing was attached, no mesh was built and no pixel was drawn.

    worldTiles          all three drawn and stood on
    own tile's ranges   610 listed, 527 drawn, 56,388 triangles, which is the DRAWN TILE ALONE
    stated triangles    own 56,388, (1,0) 52,366, (3,0) 57,132, sum 165,886
    texture sets        13 distinct, 13 requests, for three tiles
    composed ground     313,165 triangles = 96,745 + 121,530 + 94,890 exactly
    obstruction rings   508 composed and deduplicated across the three, 0 refused

**DRAWING THE NEIGHBOURS COSTS NO BYTES, MEASURED ON BOTH TREES RATHER THAN DERIVED.** The same
world loaded on main `bfa398cb`, where a neighbour is read for navigation and never drawn, and on
this lane at `014db258`, where all three are drawn:

    tree bfa398cb   tiles drawn 1   transferredBytes 102,625,116
    tree 014db258   tiles drawn 3   transferredBytes 102,625,116

Identical. The container is 12,682,860 of that and the rest is the thirteen texture sets, which are
the same thirteen whether one tile is drawn or three, because neighbouring tiles of one city draw
one street with one set of materials. Each arm REFUSES TO RUN unless the tree it imports from is at
the sha it was told to measure and is clean, and it writes nothing into either tree, because a
control that labels its arms rather than asserting them measured one tree twice in this project on
2026-09-18 across ten consistent green runs. Both refusals fired on the first attempt, one because
main had moved under me and one because my own probe file had made the worktree dirty.

**AND THE TIME IS NOT A MEASUREMENT OF THIS CHANGE, WHICH IS WHY IT IS REPORTED RATHER THAN
QUOTED.** Two runs on each arm:

    bfa398cb   120,209 ms   111,750 ms      and a later single run at 82,035 ms
    014db258    98,976 ms    83,225 ms      and a later single run at 84,221 ms

The AFTER arm is faster than the BEFORE arm on every pairing, which cannot mean that drawing three
tiles is cheaper than drawing one. The spread within one arm is larger than the difference between
them, so this instrument cannot resolve the change at all, and there is a structural reason it never
could: the load is `verifyOwd` REBAKING three containers totalling 36.6 MB from their own records
and comparing every byte, which both arms pay in full, while the work this change adds at load is
planning about 6,700 more entries, and the work it adds at DRAW time is in `attach`, which this
probe never calls. One tile alone loaded in 20,540 ms against 87,744 ms for three, which is the
verification and not the drawing.

  WHAT THE FRAME COSTS IS A THIRD QUANTITY AND NOBODY HAS MEASURED IT. Bytes fetched, bytes decoded
  and verified, and triangles submitted per frame are three populations. This section settles the
  first at 102,625,116 for a three tile world, states the second as the thing the wall clock is
  actually reporting, and leaves the third to a run that opens a browser.
