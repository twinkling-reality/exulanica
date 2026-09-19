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

  WHAT A FRAME COSTS IS A THIRD QUANTITY AND NOBODY HAS MEASURED IT. Bytes fetched, bytes decoded
  and verified, and triangles submitted per frame are three populations. This section settles the
  first at 102,625,116 for a three tile world, states the second as the thing the wall clock is
  actually reporting, and leaves the third to a run that opens a browser.

## An instrument note, the second of this family on this store in two nights

The record for the tessellator 19 bake ends with one: `find -newermt '-20 minutes'` over that store
reported ZERO files written moments after writing five, and the zero was nearly believed. Here is
the same family from the other side, and this time the wrong reading was the reassuring one.

Checking that this lane had not published, the orchestrator reported NO `.owd` WRITTEN SINCE
MIDNIGHT ANYWHERE OUTSIDE LANE WORKTREES. TEN WERE WRITTEN, 36.6 MB of them, at 00:48, in this
session's own scratchpad, which is not a lane worktree: the five corridor tiles at tessellator 20,
baked twice each, which are the containers every figure above is measured from.

THE CONCLUSION WAS RIGHT AND THAT CHECK IS NOT WHAT MADE IT RIGHT. Two other checks were run in the
same breath and both are sound: the corridor database still carries its rows, and the store
directory is untouched. Those ask about THE STORE, which is the thing the permission protects. The
`.owd` search asks about a FILE EXTENSION, and a file extension is not a publish: baking a container
into a private directory and recording one into a shared store are different acts that leave the
same kind of file behind.

  A CHECK THAT AGREES WITH THE TRUTH BY A ROUTE THAT COULD NOT HAVE SEEN IT IS THE WORST KIND TO
  LEAVE STANDING, because nobody investigates a check that says what they expected. Ask what the
  search could not have looked at, and ask whether its subject is the thing being protected: here
  the subject should have been rows and store paths, and it was filenames.

## Re-checked after main moved, because every figure above was taken on a tree main has left behind

Main gained fourteen commits between `bfa398cb`, which this record's figures were measured on, and
`854fd7f1`. Among them is a rename of a generated world's identity to `world_seed` and a change to
`exulanica/grammar/grammars/city/generation/tiles.py`, WHICH IS THE FILE THAT WRITES THE TILE
DOCUMENTS EVERY CONTAINER ABOVE WAS BAKED FROM. A figure measured from a document nobody will
generate again is true of a tree nobody is standing in.

The change is the positional-stamp fix: `COORDINATE_UNITS[0]`, `OWNERSHIP_RULES[0]` and
`HALO_RULES[0]` become `WRITTEN_COORDINATE_UNIT`, `ANCHOR_FLOOR_DIVISION` and
`EXTENT_MEETS_GROWN_SQUARE`, so each closed field is stamped with the value its producer NAMES
rather than with whatever sits at position zero. Intended to be inert. Measured rather than taken:

    tile     documents at bfa398cb   documents at 854fd7f1
    (0,0)    8d00b38441ff2e47        8d00b38441ff2e47        identical
    (1,0)    98d9bc0229d36873        98d9bc0229d36873        identical
    (2,0)    c6cad9240b124b6a        c6cad9240b124b6a        identical
    (3,0)    c0e8371b7443910b        c0e8371b7443910b        identical
    (4,0)    1cf3f797a16ba94f        1cf3f797a16ba94f        identical

**WITH A CONTROL, because five identical digests are exactly what a comparison that cannot fail
produces.** One byte appended to one of the regenerated documents reads DIFFERENT; removed again, it
reads identical. So the instrument can disagree and its agreement means something.

The bake's other input has not moved either: `web/packages/loom-tess/src` and `assets/textures` are
byte for byte unchanged across those fourteen commits. So every container, digest, multiset and byte
count above is still exactly what a rebake on `854fd7f1` produces, and the rename that prompted this
check left the tile record's own `city_seed` field alone, for the reason
`docs/artifacts/world-identity/tile-record-half-is-blocked.md` measures at length.

The tile record's half of that rename is the thing to watch: when it lands it needs city grammar
version 4, and a version bump alone moves every container digest again and makes everything above
historical. This record will not say so on its own.

## The corridor at tessellator 20, baked and served, against a store of this lane's own

Run 2026-09-19 morning on `lane/draw-neighbours` rebased onto main `89dbdcd8`. The prediction above
was committed before any of this and nothing above the result line has been edited since.

**A RUN AGAINST A PRIVATE STORE IS A TRUE MEASUREMENT OF A COMPOSED WORLD AND IS NOT A MEASUREMENT
OF WHAT THE PRODUCT SERVES.** The shared store is untouched and still holds tessellator 19, the
corridor is still unreadable on main, and the publish that would change either is still unanswered.
Every figure below is about a world this lane baked for itself.

Nothing shared was used, and a private DATABASE on the shared server would not have been enough.
`scripts/test_postgres.py` gives a whole private PostgreSQL server per worktree, and its own header
records why the smaller units are not private: a schema shares advisory locks, A DATABASE SHARES
ROLES CLUSTER-WIDE, measured at 40 failures in 80 runs of `provision_runtime_role` from two
databases on one server, and a server shares checkpoints, measured at a `DROP DATABASE` waiting over
six minutes. The server is keyed on `Path(__file__).parents[1]`, so it was started from THIS
worktree's copy of the script: the main checkout's copy would have made a handle two sessions could
hold.

    server        a private one for this worktree, migrated through 0082, roles provisioned
    store         a directory of this session's own
    bake          scripts/bake_corridor_tiles.py, the repository's own publish path, unmodified

**FIVE TILES, TWICE EACH, `identical` ON EVERY SECOND PASS**, which is what that script's second
pass exists to check. Then served over the product route:

    tile   container   render_batch   nav_envelope        bytes
    (0,0)  21b31c9f    b00f0eb8       3ef97d7f        2,481,768
    (1,0)  7ef4d85c    fbe4a342       6b020340       12,294,448
    (2,0)  ed9acb98    7122bd5e       86677d13       12,682,860
    (3,0)  47e6457e    1ff91767       dacc5a4b       11,630,744
    (4,0)  2676a397    f5b00dc4       abbf7af9        2,291,524

EVERY ONE OF THOSE FIFTEEN DIGESTS IS THE ONE THIS RECORD PREDICTED AND THEN MEASURED LAST NIGHT,
from a bake into a scratch directory by the pure half of that script lifted out of it. So the two
paths agree: the lifted generation on `bfa398cb` and the repository's own publish path on a tree
rebased onto `89dbdcd8` produce the same bytes, container for container. That is the second time
this corridor has been reached by two routes at once, and it is the check the 17 to 19 record called
its strong one.

**AND EQUAL SIZE IS NOT EQUAL CONTENT, so the sizes agreeing was not taken for the bytes agreeing.**
The store is content addressed, so its filenames are the digests, and those were compared rather
than the byte counts. This file already carries an entry about a container whose size was unchanged
and whose digest was not.

The route serves them: all five listed `baked` at level 0, under a token granted
`tiles.materialise` and nothing else, minted for this session and held outside the repository.

**A NOTE ON THE WIRE, because two requests were spent on it.** `GET /tiles` takes `city_seed` and
there is no `/api` prefix. Both are deliberate and the route's own header says so: migration 0081
renamed the column to `world_seed` and everything behind the wire with it, while the QUERY KEY stays
`city_seed` because two web tests assert that literal URL and renaming it is a coordinated change.
An unauthenticated or mistaken ask answers 404 rather than 401, so a wrong path and a missing
credential are the same reply from outside.

## What is still not measured

A FRAME. Everything above is bytes, rows and a listing. No page has been opened, nothing has been
drawn to a canvas, and what a composed world costs to RENDER is the third quantity this record has
twice said nobody has measured. It stays unmeasured here.

## The frame: what the camera sees at the tile edge, with the neighbours and without

Driven 2026-09-19 on main `bd4db95a`, which carries both halves of this change, against the private
server and store above. **The limit is unchanged and applies to every frame below: this is a true
measurement of a composed world and is NOT a measurement of what the product serves.**

**THE CONTROL AND THE TREATMENT ARE ONE POSE APART IN NOTHING BUT THE REACH.** Same tile, same
stated pose `pose_x_mm=381000 pose_y_mm=70300 facing_dx=1 facing_dy=0`, which stands 3,000 mm inside
tile (2,0)'s eastern edge at x 384,000 and looks east. The only difference is `walk_reach_mm`.

    WITHOUT a reach    1 container. The page says "World: this one tile. The walk stated no reach,
                       so no neighbouring ground was asked for and the ground ends at this tile's
                       own edge." 311 route obstruction rings from 217 records.
    WITH 131,000       4 containers, drawn and stood on: (2,0), (3,0), (1,0), (4,0), nearest first.
                       26,216,716 bytes for the neighbours. 508 rings from 346 records.

**WHAT IS IN THE CONTROL FRAME, in the same plain terms the gate used.** Pale sky over a bare pale
ground plane, filling almost the whole frame. A sliver of magenta hatching at the lower right corner
and a fragment of a building at the extreme left edge. NOTHING AHEAD. That is the endpoint frame
this lane exists to fix, reproduced deliberately rather than remembered.

**WHAT IS IN THE TREATMENT FRAME.** A street. Buildings on both sides receding into the distance: a
pale arcaded facade with arched openings on the left, a red brick facade with windows on the right,
and more building masses beyond them. A row of street trees in leaf down the middle distance. Paved
footway and carriageway underfoot. The view recedes to a distant haze rather than stopping at an
edge. **THE MAGENTA UNAVAILABLE HATCHING IS DRAWN ON BOTH SIDES AT GROUND BAND LEVEL**, in the
neighbours as in the tile, which is the product saying honestly which surfaces no material record
dresses. 86 surfaces of the drawn tile state it, and the panel says so.

So the street continues past the tile edge, and the thing that was undrawn world is drawn.

**AND A COUNT THAT DIFFERS FROM THE GATE'S FOR A REASON.** The gate's scored run composed FOUR
containers from a reach of 131,000, and this same reach composed THREE at the walk's opening pose
and FOUR at the edge pose. All three counts are right and they count different sets: a reach is
measured from a STATED pose when there is one and from the whole square when there is not, so
(0,0) is 134,000 mm from x 262,000 and out of reach, while from x 381,000 tile (4,0) comes in at
exactly 131,000. Say the pose beside the count.

## What a frame costs is STILL NOT MEASURED, and this is why

**THE SCREENSHOTS ARE REAL RENDERS AND THEY ARE NOT FRAMES FROM A RUNNING LOOP.** The Browser pane
this ran in reports `document.visibilityState` as `hidden` and throttles `requestAnimationFrame` to
one callback a second. Instrumenting the WebGL context's `drawElements` and `drawArrays` counted
ZERO draw calls across 21 such callbacks, so the engine is not drawing between captures; a
screenshot forces a render by another path. Fronting the tab did not change either figure.

    frames sampled        21          rAF interval median 1,007.7 ms, p95 1,008.5 ms
    draw calls per frame   0          triangles per frame 0

  A NUMBER FROM THIS INSTRUMENT WOULD HAVE BEEN ABOUT THE PANE AND NOT ABOUT THE WORLD, in the same
  way the load timings earlier in this record were about `verifyOwd` and not about drawing. The
  honest figure is the one that is not taken.

What IS measurable without a running loop, because it is a property of the containers rather than of
the renderer: TRIANGLES SUBMITTED. The tile alone draws 56,388. The four composed draw
56,388 + 57,132 + 52,366 + 8,293 = **174,179**, which is 3.09 times as many. Bytes are already
settled above and do not move: the neighbours cost no texture fetch.

Measuring milliseconds per frame needs a visible surface and a loop somebody drives on purpose,
which is what the visual gate's own harness is for.

## The gate on a composed world, predicted before the run

Written 2026-09-19 on main `bd4db95a` with the harness not yet started. The last scored run got FOUR
of eight key predictions wrong and every one failed the same way: reasoning from a quantity the key
does not measure. So each prediction below names the FIELDS the key is decided by, read from
`DECIDED_BY` and `decideMechanical` in `loom-gate/src/keys.ts`, rather than from the key's name.

The walk is `docs/visual-gate-corridor-walk.md`, pose 256,000 / 70,300 facing (1,0), which is the
walk the 2026-09-18 run scored: its `walkedDisplacementMm` of 125,010 from 256,000 ends at 381,010,
which is the 2,990 mm from the tile edge that run reported. From that pose a reach of 131,000
composes FOUR containers, (2,0) + (1,0) + (0,0) + (3,0), the same four as that run. **The one thing
that differs is that three of them are now DRAWN.**

| key | predicted | the fields it is decided by, and why |
| --- | --- | --- |
| continuousTexturedStreetAndFacades | TRUE | more street and facade triangles, all dressed from the same 13 sets |
| noCutsOrFloatingGeometry | **FALSE** | `componentsDetachedFromSupport` was 773 on one tile |
| usefulEyeLevelMovement | **FALSE** | `maxEyeHeightErrorMm` was 146; the walk and the ground are unchanged |
| completeCapsuleClearanceVerification | TRUE | see below, this is the one I am least sure of |
| practicalBrowserBudget | TRUE | see below, `maxDrawCalls` is the number at risk |
| companionPresent | TRUE | captures and the Companion, untouched by drawing |
| reticlePresent | TRUE | untouched by drawing |
| authenticatedShellAndAuthoredHandlersPreserved | TRUE | untouched by drawing |

**THE NUMBERS, WHICH ARE THE FALSIFIABLE HALF.**

    componentsDetachedFromSupport   was 773 on one tile; PREDICT 2,000 to 2,500, about three times
    maxEyeHeightErrorMm             PREDICT 146, unchanged: the composed GROUND is not new
    drawnTriangles                  PREDICT about 175,034 = 56,388 + 52,366 + 9,148 + 57,132
    environmentTransferredBytes     PREDICT about 12,682,860, ONE container, see the defect below
    capsuleTriangleContactSamples   PREDICT 0
    maxDrawCalls                    the number to watch, and I have no prior for it

**THE KEY I AM LEAST SURE OF IS THE CAPSULE ONE, and the mechanism is worth stating whichever way it
goes.** That key measures clearance from every DRAWN triangle, so its population has just tripled.
And the neighbours' records OVERHANG their squares: (1,0) draws east to x 261,950 and (3,0) draws
west from x 378,050, so the walk's first 5,950 mm and last 3,000 mm now pass through geometry that
was not drawn last run and is therefore checked for the first time. I predict TRUE anyway, because
that geometry is the same street's own frontage continued, and tile (2,0)'s equivalents gave zero
contacts over 2,502 of 2,502 samples. If it comes back FALSE, the overhang is the first place to
look and not the seam.

**AND `practicalBrowserBudget` IS THE OTHER ONE, for a different reason.** Three of its four
quantities barely move: the texture bytes are the same 13 sets, the transferred bytes read one
container, and 175,034 triangles is still under Melbourne's 227,173, though with only 52,139 to
spare where there used to be 170,785. `maxDrawCalls` against Melbourne's 87 is the exposed one: this
change gives EVERY TILE ITS OWN ROOT AND ITS OWN BATCHES, so four drawn tiles submit roughly four
times the tile's batch count. I have no figure for the last run's draw calls, so this prediction is
a direction with no number, and I am saying that rather than inventing one.

**A DEFECT IN THE HARNESS, REPORTED AND NOT TOUCHED.** `capture_visual_gate.mjs` sets
`environment = bound[0]` for a generated target, so `environmentTransferredBytes` is whichever
container happens to sit first in the list the page fetched. THAT IS A POSITION IN A LIST, and until
this change the list had one member so the position could not be wrong. It now has four. The gate's
own document already says this key "measures one artefact"; `bound[0]` is the mechanism, and which
artefact it names is now decided by fetch order. I do not own that file and have not changed it.
