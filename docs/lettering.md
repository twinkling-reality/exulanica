# Lettering

Status: IMPLEMENTED for the four glyph catalogs, the conversion tool, the catalog reader and the
layout rule in both languages, and their shared cases. NOTHING DRAWS A LETTER YET: no grammar field
carries a sign's typeface or cap height, no tess expander turns a placed sign into triangles, and no
tile has been baked with lettering, so the appearance of raised letters on a fascia is UNVERIFIED.
The kerning rule is UNVERIFIED against a shaper (section 4). The lettering fields the city grammar
needs and the expander tess needs are specified in the lettering design note, which is kept with
the lane briefs outside this repository and was handed to those two lanes to build.

## What a person gets

A shop in a generated street whose fascia says what the shop is: raised letters, sharp up close,
casting small shadows, in a typeface that suits the building's era. Every premises record already
carries its sign text from the reviewed signage lexicon
(`assets/catalogs/signage-lexicon.v2.json`: generic words such as "Bakery", never a brand), and a
blank fascia does not read as a shop.

## 1. The shape of it

Letters are exact geometry, not runtime text.

- A **glyph catalog** holds every letter's outline as integer rings with holes, in the source font's
  own units. `assets/catalogs/lettering/<key>.v1.json`, canonical JSON.
- The **conversion tool**, `tools/lettering`, makes the catalogs once from the four committed fonts
  under `assets/fonts/`. It has its own environment and its own lock, because fontTools must never
  enter the product's `uv.lock`: every lane runs `uv sync --locked --offline`, so one new root
  dependency breaks all of them. `tests/test_lettering_boundary.py` and two import contracts in
  `pyproject.toml` keep the tool and fontTools out of the product.
- The **reader and the layout rule** are one rule in two languages: `exulanica/lettering/` (Python,
  for the city grammar's validator, which must know a sign fits its fascia) and
  `web/packages/loom-lettering/` (TypeScript, for tess, which places the letters and cuts them into
  triangles). `web/packages/loom-lettering/test/lettering-cases.json` holds the two to the same
  answers: the same placements to the millimetre, and the same one reason for every refusal.
- The product never parses a font. Only the tool does, once.

Scope: Latin text, one line, left or centred. No shaping, no ligatures, no right-to-left, no emoji.
A character outside the catalog's set is refused by name, never substituted.

## 2. The four typefaces

All four are static TrueType from the `google/fonts` repository at commit
`a54f7446f84a1125ef6bf08baa46f3639e8905e0`, under the SIL Open Font License 1.1, and none declares a
Reserved Font Name: converting outlines may count as modification, and a Reserved Font Name would
forbid the result from carrying the family's name. The catalog keys name the ROLE, not the font, and
each catalog records the family, the style, the licence and the file's SHA-256 in its source block,
so a catalog cannot be taken for the font.

| Key | Family, style | Era it serves | What it is |
|---|---|---|---|
| `grotesque` | Barlow SemiBold | contemporary, postwar | A low-contrast grotesk drawn from California public signage |
| `condensed` | Francois One | postwar; any era's long name on a narrow fascia | A reworking of traditional gothic display forms |
| `slab` | Bevan | interwar | A reworking of a 1930s slab display face by Heinrich Jost |
| `modern_serif` | Old Standard Bold | prewar masonry | A Modern (classicist) serif of the late 19th and early 20th century |

**There is no script face, and that is a measurement rather than a taste.** Pacifico, the
best-licensed candidate, touches its neighbour in 99 adjacent letter pairs across the 18 lexicon
texts at a 300 mm cap height with no tracking. Two letters that share a point have coplanar front
faces at the same depth, which z-fight, so the layout rule refuses them (section 4); a joined script
would be refused almost always. Other candidates were rejected for a Reserved Font Name (eighteen
of them, among them Abril Fatface, Alfa Slab One, Limelight, Pathway Gothic One, Arvo and Rye), for
shipping only a variable font at that commit (Work Sans, Archivo, Oswald, Playfair Display, IBM Plex
Sans and others), for mixed winding (Libre Caslon Display: 22 of 67 glyphs fill counter-clockwise,
and i and j wind both ways), for small capitals only (Holtwood One SC), or for a smallest safe cap
height above the promise: Gloock 142 mm (edges of `K` meet at 141) and Coustard Regular 129 mm (a
spike in `M` at 128), both measured with this minimum edge and a coarser tolerance than the one
settled on, `cap / 667`.

## 3. The catalog, and how a font becomes one

Coordinates are the font's own integer units. The tool's steps, each exact:

1. **Curves.** A TrueType quadratic `P0 P1 P2`, with implied on-curve points kept as exact
   rationals, is cut into `n` equal parameter steps, `n` the smallest integer with
   `|P0 - 2 P1 + P2|² ≤ 16 n⁴ t²`, which is the exact bound on a chord's distance from the curve.
   The tolerance `t` is `cap height / 1200` font units: at the largest promised cap height, 1200 mm,
   no chord strays further from the curve than the 1 mm grid the layout rounds to. Points are
   rounded to whole font units, halves toward +infinity.
2. **The minimum edge.** Every edge is at least `E = ceil(cap height / 100)` font units long in
   Chebyshev distance, which is one millimetre at the smallest promised cap height, 100 mm. Shorter
   edges are removed: the shortest edge first (ties by squared length, then ring position), dropping
   whichever of its two ends has the smaller cross product with its neighbours, the later one on a
   tie. Exactly collinear same-direction vertices are dropped, which changes no shape. The catalog
   records `E`, how many vertices went, and the largest distance any pre-merge vertex ended up from
   the final ring.
3. **The checks.** Every ring must pass the ring rule tess triangulates by (at least three
   vertices, no zero-length edge, no spike, a positive counter-clockwise area, and no two edges
   touching except where adjacent edges share a vertex), every hole must lie strictly inside its
   outer ring, no two holes and no two parts may share a point, and the nesting depth of a contour,
   found by exact containment, must agree with TrueType's clockwise fill. A glyph that fails refuses
   the whole catalog, by name. Nothing is repaired quietly.
4. **How a ring is stored.** Counter-clockwise, because tess takes holes counter-clockwise and
   reverses them itself; as a flat integer array `[x0, y0, x1, y1, ...]`; starting at its lowest then
   leftmost vertex; parts and holes ordered by that start. The reader checks all of it, so a catalog
   is in one form only.
5. **Metrics.** The cap height is the top of `H`, the x-height the top of `x`, the ascender and
   descender the extremes over the set, all measured from the stored rings rather than from the
   font's declared values, which disagree: Coustard's OS/2 table says 1489 and its `H` reaches 1503.
   The reader re-measures and refuses a catalog whose metrics do not match its rings.

### Why the minimum edge exists

Rounding an outline to whole millimetres collapses a short edge to nothing, and without a minimum
edge that happens far into the useful range, not just at tiny sizes. Measured, with the outlines as
drawn and a one font unit tolerance, the smallest cap height at which every glyph survives:

| Family | Smallest safe cap height, as drawn |
|---|---|
| Bevan | 151 mm |
| Old Standard Bold | 346 mm |
| Barlow SemiBold | 646 mm (`y` collapses at 645) |
| Francois One | 674 mm |
| Anton, Archivo Black, Fjalla One, Coustard Black | 222, 327, 1201, 1193 mm |

With the minimum edge at `ceil(cap / 100)`, a collapse is impossible at or above 100 mm by
construction: an edge one millimetre long at 100 mm cannot round to zero, and rounding halves toward
+infinity rather than toward zero so that the map is translation-invariant (the canonical
`round_half_down` would send both -0.5 and +0.5 to the same millimetre, closing a gap of a whole
millimetre). The other ways rounding breaks a ring, a spike or two edges touching, are not ruled out
by construction, so the tool scans.

## 4. The cap-height promise, and the scan behind it

Each catalog promises 100 to 1200 mm. 1200 is the city grammar's `fascia_height_mm` maximum: a cap
height cannot exceed the fascia it sits in. 100 is a choice; what it trades is outline fidelity
against the smallest sign available, and the grammar has room either way (the tallest lexicon ink,
descenders included, is 1.27 to 1.36 cap heights, so the smallest fascia at 300 mm holds cap heights
up to about 220 mm, and "Public Library", the widest text at 7.6 to 10.5 cap heights, fits the
narrowest 2400 mm bay at up to about 229 mm).

Before it writes a catalog the tool **scans**: from 1200 mm downward, every integer cap height, every
glyph, the ring rule and the hole and part rules at millimetre scale, stopping at the first size that
fails. That size and the glyph that failed go into the catalog, so the promise can be checked without
rerunning the scan, and the tool refuses to write if the failure is inside the promise. About 90
seconds for the four catalogs on six processes.

| Catalog | Cap height (font units) | Minimum edge | Vertices | Largest shift | Scan: largest failing size | Kerning pairs | Bytes |
|---|---|---|---|---|---|---|---|
| `grotesque` | 700 | 7 | 3,846 | 7 units | 97 mm (`j` collapses) | 713 | 44,864 |
| `condensed` | 750 | 8 | 3,267 | 2 units | 89 mm (`m` collapses) | 181 | 33,472 |
| `slab` | 1592 | 16 | 3,619 | 5 units | 83 mm (`s` collapses) | 925 | 49,088 |
| `modern_serif` | 712 | 8 | 5,603 | 7 units | 86 mm (`J` collapses) | 187 | 51,352 |

`tests/test_lettering_catalog.py` re-checks the promise with the product's own reader at the two
ends and every 97th millimetre between, and re-checks that the recorded failing size really fails.

### Kerning

Kerning comes from GPOS pair positioning, flattened to a table of pairs within the character set:
the lookups of the `kern` feature in the `latn` script's default language system, in ascending
lookup index; within a lookup the first subtable that matches applies and the rest are skipped (a
format 1 subtable matches only when it holds the pair, a format 2 subtable whenever its coverage
holds the left glyph, class 0 included); the value is the sum over lookups of the first glyph's
x-advance adjustment. Anything outside that refuses the catalog rather than being approximated: a
lookup that is not pair positioning, a value that moves anything else, a legacy `kern` table, or a
glyph in the set that GDEF calls a mark.

**UNVERIFIED:** this follows HarfBuzz's semantics as read, not as tested. No shaper is installed and
none is approved for download, so there is no comparison against one. All four families use the
simplest form (pair positioning, x-advance on the first glyph only), which is the case least likely
to differ.

### The character set

Space, `& ' , - .`, the digits, the capitals and the small letters: 68 characters, the same set in
every catalog, so the grammar may pair any typeface with any text. The lexicon needs only letters and
the space today; the digits and the five marks are for street numbers and names such as
"Bread & Coffee". No accented letters in version 1: a catalog names its set and a character outside
it is refused, never substituted.

## 5. The layout rule

Inputs: the text, a catalog, a cap height in millimetres, tracking in millimetres, an alignment,
and the box the letters may occupy (width and height, in millimetres). Output: one placement per
non-space character, in integer millimetres, and the ink box, in box coordinates with the origin at
the bottom left.

With `C` the catalog's cap height in font units and `H` the cap height in millimetres:

- `scale(v) = floor((2 v H + C) / (2 C))`: nearest millimetre, halves toward +infinity.
- The pen advances in exact font units: `pen[0] = 0`,
  `pen[i + 1] = pen[i] + advance(c[i]) + kern(c[i], c[i + 1])`.
- Character `i`'s origin is `scale(pen[i]) + i × tracking`, and its outline is scaled relative to
  that origin, so every copy of a letter at one size is the same geometry, and tess can triangulate
  each distinct letter once.
- The ink box is the extent of every non-space glyph's scaled outline. `left` puts the ink's left
  edge at 0; `centre` puts it at `floor((width - ink width) / 2)`.
- The baseline sits at `floor((height - H) / 2)`, centring the cap height as a sign writer sets
  capitals, with descenders below it.

Refusals, one reason each, in this order: `alignment` (not `left` or `centre`); `cap_height` (not an
integer inside the catalog's promise); `tracking` (not an integer of zero or more, since below zero
letters crowd past the typeface's own spacing, and nothing bounds it above but the fit);
`box` (a width or height below one); `text` (empty, or a space at either end or two together,
because an edge space would move the alignment by an invisible glyph); `character` (the first
character outside the set, named by code point); `fit`; `touch`.

**A sign that does not fit is refused, never squeezed**, and two letters that share a point are
refused too. Touching matters because two solids that share a face z-fight, and it is not a rare
edge: measured over all 4,489 ordered pairs of the set at every size from 100 to 1200 mm in steps of
seven, `condensed` has five pairs that touch in the font's own units (`XX`, `Xx`, `YY`, `gy`, `xX`)
and two more that only the rounding brings together, `slab` has `fY` and two more, and
`modern_serif` has `fb` and four more. `grotesque` has none at any size. Rounding-driven touching
flickers with size: `Qj` in `modern_serif` touches from 101 to 110 mm, is apart at 111 to 116, and
touches again from 117 to 122. No text in the signage lexicon touches, in any of the four catalogs, at any
cap height in the promise: measured exhaustively, 79,272 layouts (18 texts, 4 catalogs, every
integer cap height from 100 to 1200 mm), no refusal of any kind, 23 s in one process. So a refusal
here means the grammar picked an unusual pairing, and its answer is another cap height, some
tracking, or another typeface.

## 6. What a sign costs

Triangle counts do not depend on the size: the catalog holds one outline per glyph and scales it.
"Bookshop", by way of a typical sign:

| Catalog | Vertices | Front faces | Walls | Front and walls | Closed solid |
|---|---|---|---|---|---|
| `grotesque` | 667 | 663 | 1,334 | 1,997 | 2,660 |
| `condensed` | 581 | 577 | 1,162 | 1,739 | 2,316 |
| `slab` | 576 | 572 | 1,152 | 1,724 | 2,296 |
| `modern_serif` | 708 | 704 | 1,416 | 2,120 | 2,824 |

Front faces are `vertices + 2 holes - 2 parts`; a wall is two triangles per ring edge; a closed
solid adds a back face. Fourteen signs of this size, one per building in the corridor, are 24,136 to
29,680 triangles as front and walls, which is 10.6 to 13.1 per cent of Melbourne's 227,173-face
envelope; painted lettering, depth 0, is 8,008 to 9,856 (3.5 to 4.3 per cent). The levers, for tess
and the grammar to set, are in the design note: painted against raised by typology, walls only above
a stated depth, and a back face only where a standoff could show one.

## 7. Rebuilding, and the boundaries

    uv run --directory tools/lettering --locked --offline python -m exulanica_lettering_tool check
    uv run --directory tools/lettering --locked --offline pytest
    uv run python scripts/generate_lettering_cases.py --check
    uv run pytest tests/test_lettering_catalog.py tests/test_lettering_cases.py tests/test_lettering_boundary.py
    pnpm --filter @exulanica/loom-lettering typecheck && pnpm vitest run packages/loom-lettering

- `exulanica.lettering` sits below `exulanica.grammar` in the import contract, as
  `materials | lettering`, and may import only canonical JSON and the error types: a forbidden
  contract stops it naming an evidence address, opening a database or reaching the pipeline, so the
  grammar's validator can lay out a sign in a process with no server and no credentials.
- `@exulanica/loom-lettering` is core only, reachable from another package through
  `@exulanica/loom-lettering/core` and nothing else, and its core may import no host module: it
  writes out its own UTF-8 codec rather than reaching for `TextDecoder`.
- The fonts are committed byte for byte with their `OFL.txt` and a `SOURCE.json` recording each
  file's URL at the pinned commit and its SHA-256. `THIRD_PARTY_NOTICES.md` names every one, and
  `tests/test_lettering_catalog.py` fails if it stops doing so.
