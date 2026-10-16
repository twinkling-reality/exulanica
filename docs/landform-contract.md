# Landform

Status: **IMPLEMENTED BOUNDARY: DATA, READERS AND SITE WORLDS ON LAND, DRAWN; ASKED FOR WHERE A
DEPLOYMENT TURNS IT ON**. A world's land can be stated as data, realized, graded and read back in
Python and in the browser, and a site world can be made on land through its route: graded,
regenerated from its receipt, its people's places standing on the land, its drawing and its land
served. The application draws such a site on its land, to the horizon, and stands its people and
things on it. A place drafted from a person's words stands on land chosen from what was said where
the deployment turns that on (`EXULANICA_WORLDS_ON_LAND`, off by default); elsewhere, and for every
town, worlds stand on level ground, as the [world kinds contract](world-kinds-contract.md) and the
[city grammar](grammar-package.md) state.

This document owns the land document (`exulanica.landform/v1`), the landform catalogs, the pure
function that realizes a land, the grading a layout applies to it, and the chunk and backdrop
documents a reader receives. The exact contact predicates a chunk is read with belong to the
[composition contract](world-composition-contract.md#heightfield-geometry-and-contact).

<details>
<summary>Sections</summary>

- [In plain words](#in-plain-words)
- [The land document](#the-land-document)
- [The catalogs](#the-catalogs)
- [Realizing a land](#realizing-a-land)
- [Near land in chunks](#near-land-in-chunks)
- [The backdrop](#the-backdrop)
- [Water](#water)
- [Grading](#grading)
- [Readers in the browser](#readers-in-the-browser)
- [The land's look](#the-lands-look)
- [Sites on land](#sites-on-land)
- [Towns on land](#towns-on-land)
- [A world's land rules](#a-worlds-land-rules)
- [Land for a world made from a sentence](#land-for-a-world-made-from-a-sentence)
- [Refusals](#refusals)
- [Limits](#limits)

</details>

## In plain words

A world can say what its land is like: hills, a slope, a valley, small unevenness, a shore with a
beach and a sea, a basin holding a lake, terraces stepping up a hillside, and mountains on the
horizon. Each is a feature from a catalog with bounded values, placed in words (a compass side of
the world, how far beyond its edge). Code turns the features into heights, in the same way every
time. A layout then cuts level platforms for its buildings, grades its paths, banks the ground
round them or gives it a retaining wall, and carves its ponds, and the result is checked: nothing
cut or filled too deep, every water body holding its water, every door reachable from the entry.

## The land document

`exulanica.landform/v1` is a closed JSON object (`exulanica/grammar/landform/document.py`):

| Key | Meaning |
| --- | --- |
| `profile` | `exulanica.landform/v1` |
| `ground_mm` | The height of the world's level ground above the datum, the sea's level |
| `features` | A list of features, each with `id` (a lowercase key, unique), `kind` and the values its kind's catalog entries name |

Every integer is held to its catalog bound and every word value to its words; a required value
must be stated; unknown keys are refused. The canonical document carries every value of every
feature, defaults written in at reading, so a later catalog default never changes a land that was
read before it. A land's identity is the SHA-256 of its canonical JSON. A shore needs level ground
at or above its beach's top. A land with no features is level: one height everywhere; every world
without a land document reads as level land at height 0.

Placement words resolve against the world's extent, from its south-west corner (x east, y north):
a side's line lies `distance_mm` beyond the world's edge on that side (negative reaches into the
world) and `offset_mm` along it from the middle of that side; `centre` is the world's middle,
offset east by `offset_mm` and north by `distance_mm`.

## The catalogs

Two catalogs in `assets/catalogs/landform/` shape land, read through the grammar's catalog loader so
each entry carries a reason and a licence (`exulanica/grammar/landform/catalog.py`). Beside them,
`landform-surface.v1.json` states [the land's look](#the-lands-look) and `landform-recipe.vN.json`
the [land a place made from a sentence stands on](#land-for-a-world-made-from-a-sentence):

- `landform-feature.vN.json`: one entry per kind: `words` (what a person or a model reads),
  `domain` (`near_and_far`, or `far` for a feature drawn only), `composition` (`additive` or
  `shaping`) and `most` (how many one land may list).
- `landform-value.vN.json`: one entry per value, keyed `<feature>_<value>`: `minimum`, `maximum`,
  `default`, `required`, and for a value in words its `words` (the default indexes them). The
  feature `land` bounds the document: `ground_mm` and how many `features` it lists.

Both change only by a new version, and a version keeps every entry of the one before it unchanged
and adds to it: version 2 adds the `cascade`, version 3 its `course` and `least_fall_mm`. New land
is read against the newest version, and a world's land against the version its
[land rules](#a-worlds-land-rules) name.

| Kind | What it makes |
| --- | --- |
| `tilt` | The land rising toward a side, held level beyond its reach |
| `rise` | A hill, round or long, smooth or rough |
| `valley` | A long hollow with a flat floor |
| `undulation` | Small seeded unevenness everywhere |
| `range` | Mountains or hills on the horizon, drawn only |
| `shore` | The land falling to a beach and a sea floor below the datum, rising behind the beach no faster than its coast grade |
| `basin` | A bowl; filled, a lake whose level is its rim less a freeboard |
| `terraces` | Level benches stepping up a slope, each joined to the next by a bank, fading at their ends |
| `cascade` | Water stepping down a straight channel toward a main side, from level pool to level pool over falls no higher than its step, into the sea or onto level land (version 2); in equal falls, or falling where the land falls (version 3) |

## Realizing a land

`H(x, y)` is the land's height in millimetres at a point east and north of the world's south-west
corner (`exulanica/grammar/landform/realize.py`). It is a pure function of the land and the
world's seed, computed with integers only: hashed value noise on integer lattices, fixed-point
smoothsteps, integer square roots. Additive features sum; then shaping features apply in a fixed
order, terraces, shores, basins, cascades, so a basin's level is set by the rim it ends with. Each
recipe is bounded to the land it was written for and fades out beyond it. Noise is sampled on the
world's own axes, so a grid of samples computes its interpolation weights once per row and column.

Within each tier of natural rise a terrace holds the lower part level, a bench, and the upper part
(`riser_share_permille` of the tier, 800 by default) is a bank climbing the whole tier, so a bank is
no steeper than the slope beneath divided by its share: on gentle land the steps are grassed
banks, on steep land they are as steep as the land demands. Behind a beach the land rises away from
the water at most at the coast grade (350 per mille by default); where the waterline wanders that
slope steepens, and a level coast with the defaults rises no steeper than 600 per mille. Both are
functions of each point alone, so the near land and the backdrop agree wherever they meet.

A cascade runs toward north, east, south or west, `offset_mm` across from the world's middle, from
`from_mm` to `to_mm` beyond the world's edge on that side (negative reaches in). Its top is the
land's height at its source, before the cascade, less its freeboard. Its `course` says where its
water falls:

- `equal` (the default, and every cascade written before courses existed): its bottom is the sea's
  level where its end lies in the sea, else the land's height at its end less the freeboard; the
  drop is split into the fewest equal falls no higher than `step_mm`, and the channel into as many
  equal pools (one more where it ends on land), each at least 4 m long. On sloping land a pool is
  level for a long stretch, so its lip may stand metres above the ground.
- `follow`: the cascade reads the land before it along its middle, cell by cell, and falls where the
  land falls. A pool ends where the land ahead lies `least_fall_mm` (1 m by default) or more below
  its water, at least 4 m from where it began and from the channel's end; the next pool lies at the
  land there less the freeboard, never more than `step_mm` below. Where the land meets the sea the
  channel stops at the waterline and its last fall pours into the sea, never more than a step high.
  Along the channel's middle a pool stands at most its least fall above the land, past the
  freeboard, except within 4 m of where the pool began; the course reads the land there only, so
  on land that also slopes across the channel a lip's far edge may stand higher.

Within the channel the land is cut to each pool's level less its `depth_mm`; each pool ends in a 2 m
sill at its own level, over which the water falls to the next; a lip of `wall_mm` (at least 1 m, the
lattice) beside the channel and at its head is raised to the water's level and the freeboard where
the land is lower, and closes the last pool of a cascade that ends on land. Its levels and where its
pools end are read once per land and world, so every point is then computed alone. A cascade lies
within the near land.

## Near land in chunks

The walkable land is the world's extent plus one ring of chunks, sampled every 1,000 mm. Chunks lie
on the city's 128 m tile grid: chunk `(i, j)` covers east `i * 128 m` to `(i + 1) * 128 m` and north
the same, 129 samples a side, neighbours sharing their edge samples. A chunk has the city's
`TerrainRecord` shape (rows from the south-west, the exact slope field, each cell split along its
south-west to north-east diagonal) and validates as one. Near heights lie within 64,000 mm of the
datum either way, the exact sheet's bound.

`exulanica.landform-chunk/v1` carries `chunk`, `cell_mm`, `samples_per_side` and `height_mm`; its
identity is the SHA-256 of its canonical JSON. `exulanica/world/landform_contact.py` gives a chunk
as `exulanica.heightfield-geometry/v1` in its own frame (east from its west edge, south from minus
128 m at its north edge to 0 at its south edge), the same triangles, so the exact contact predicates
apply to the land unchanged; its exact height at a point (`chunk_height_at`) equals the exact
contact's. The realizer itself stays in the grammar package's rules: integers only, no floats,
fractions or clock, and nothing imported from a particular grammar.

## The backdrop

`exulanica.landform-backdrop/v1` is the same function on a coarse grid out to the horizon (8 km
from the world's middle): 16 m apart across the near land, growing outward by 15 percent a step to
96 m apart. It is drawn only: never walked, never collided with, and not held to the near bound.
Its samples on the near land's edge are the near land's own, so the two meet. It states the near
land's rectangle (`near_mm`), its axes, its heights and the land's water. A range whose foot would
rise inside the walkable land is refused.

## Water

The datum is the sea's level, the same level the exact contact treats as wet below 350 mm. A shore
states a sea at level 0 on its side; a filled basin states a lake (centre, radius, level); a layout
grades ponds (rectangle, level). A lake's level is the lowest sample on the 2 m ring just outside
it, before it is carved, less its freeboard. Basins that overlap or share a rim are refused. In the
browser the sea and lakes wear the look's water as a pack dresses it: the look's own depth water
where the look states one, otherwise the surface finish's water with its depth taken from the land
under the surface and its edge faded in at the shore
(`assets/catalogs/world-kinds/surface-finish.v2.json`); where no pack dresses the site they are
drawn in one plain colour.

A cascade states its pools (`pool`: a rectangle and its level), and between them its falls (`fall`:
a line across the channel, `rect_mm` with no depth, from `level_mm` down to `bottom_mm`, falling
toward `side`); the last fall of a cascade that reaches the sea drops to level 0. The near land, the
backdrop and a site's drawing list them with the land's other water.

## Grading

`exulanica/grammar/landform/grading.py` grades realized near land for a layout, in order:

1. Pads with a stated level are set flat.
2. Corridors (paths, streets; rectangles graded along `x` or `y`) take the land's own profile
   brought within their grade at the least cut and fill (the midpoint of the largest and smallest
   grade-limited envelopes), held to every level already fixed under their centre line. A
   corridor is level across, except where it crosses one graded before it, which keeps the
   crossing. A corridor that states its levels at its two ends (a ramp) takes the straight line
   between them instead, along its axis.
3. Pads with a door are set flat at the ground's height at the door; a pad with neither takes the
   land's height at its middle.
4. Every other sample is held between the cones of the fixed samples at the bank grade (1 in 2).
   Where two fixed samples are closer than their difference allows, a retaining wall takes the
   difference and is listed with its height.
5. Ponds are carved as the ellipse inscribed in their rectangle, below a level that is the lowest
   ground on the 2 m ring outside them less a freeboard.

Before any of these, a layout whose pads or corridors would cross a cascade's pools or falls is
refused: a layout stands beside a cascade, and the next layout candidate is tried.

Then the checks: cut and fill within 8,000 mm; every water body holds (every dry sample beside a
wet one stands at or above its level; a fall is a cascade's drop and is not held); every door
reachable from the entry over ground walked at 1
in 4 or less, never through a wall or within 350 mm of a water's level; heights within the near
bound. Grading never changes the land it was given.

## Readers in the browser

`web/packages/atlas-core/src/landform.ts` reads chunk and backdrop documents by their digests.
`NearLand.groundHeightMm` gives the land's height under a point in floating point, for standing
people and things on the ground; `landChunkGeometry` gives the exact heightfield for contact;
`backdropMeshData` gives the backdrop as upward-facing triangle blocks a renderer can cull, its
samples under the near land sunk below it. `tests/fixtures/landform/conformance.json` holds one
chunk, a backdrop and exact heights at points; the Python realizer is held to the file, and the
browser readers are held to the same heights, exact through the heightfield and within float
precision through `groundHeightMm`.

## The land's look

What the land wears where it is not the site's own ground is land data:
[`landform-surface.v1.json`](../assets/catalogs/landform/landform-surface.v1.json) states bands,
each with a colour and a reason, worn by slope and height above the sea: sand by the sea, planting
on banks too steep to mow and rock on faces too steep to hold soil on the near land; on the
backdrop, sand, a darker wooded band on hillsides, rock and pale scree high up, over the site's
ground colour. Every threshold is moved by noise in the world's metres at two scales, so a band's
edge wanders and never follows the land's one-metre grid. On the near land the bands are laid over
the base ground as it is dressed (a pack's swatch, pattern or texture, and the ground finish),
wrapping its colour function rather than replacing it (`generated-site/land-slope.ts`), with the
slope read from the land's own surface; on a WebGPU device the near land wears its ground alone.
The backdrop is coloured by vertex with the same rule (`landBackdropColour`), and whatever reads the band
the land is drawn in at a point on the CPU, such as a look's land cover, asks `landBandAt`, the same rule
with the same noise (`valueNoise`), so it agrees with the shader except inside a band's ramp. Far ranges read as
mountains only through the look's haze, which a world wears from its style pack.

## Sites on land

`POST /worlds/kinds/{kind}/worlds` takes an optional `land` (`exulanica.landform/v1`) for any kind
but the town; land with a support declaration is not served. The site grammar lays the site out
exactly as on level ground, then, per layout candidate, the layout grades the land
([`site_land.py`](../exulanica/world/site_land.py)) so that everything the site's society walks
stays within the place contract's one kerb step per edge (180 mm), with no new edge kind and no
change to walking cost:

- every **zone** is a level terrace at the height of its path where the zone's gate meets it;
- every **path** is graded no steeper than one step over its longest station spacing (the place
  lays a station every `footway_station_spacing_mm` or a little more), less a 2 mm rounding
  margin; a path ending within a lattice cell of the site's edge is graded to the edge;
- every **water area** is a pond carved into its zone's terrace, its level the rim less the
  catalog's freeboard, its id its zone's number then its area's number in the zone
  (`zone 1 pond 0`), so no two ponds of a site share one; under land rules 1 to 3 the id is the
  area's number alone (`pond 0`), and two zones' first ponds share it;
- the place's nodes and spots stand at the graded land's height, its frame's datum the sea's
  level, and a join that would climb more than the step is not made.

A candidate whose layout the land cannot take is refused with the grading's sentence and the next
candidate tried; the kind's needs are checked on the graded place. The land is realized with a seed
from the world's identity and the land's digest, so it is the same land whichever layout is kept.

The receipt names composer `site-plan` version 5 and carries the canonical land document and its
digest; the records, plan and output digest are the level layout's. The drawing is
`exulanica.site-drawing/v5` ([world kinds contract](world-kinds-contract.md#the-drawing)); the chunks
and the backdrop are made with the drawing in the kind worker and served by the digests it names,
`GET /world/versions/{version_id}/land/chunks/{chunk_x}/{chunk_y}` and `.../land/backdrop` (world
read). In the drawing the site's ground, zones, paths, dry areas and boundary walls follow the land
(`drape`: each point as far above the land under it as the slot's base stands above the land under
its base's centre), since a terrace is level only inside its edges, where it meets sloping paths and
terraces at other levels; a building and its rooms stand level on their terrace, and water at its
level. A world made without land is the level world it always was, byte for byte.

## Towns on land

City grammar version 6 ([the generator system](grammar-package.md#7-the-city-stages)) lays a town
on a land document and grades the land for it
([`city/land.py`](../exulanica/grammar/grammars/city/land.py), `town_land_plan`):

- each street node stands at a level read over the whole network from the natural land (the
  midpoint of the highest and lowest levels the network's climbs allow), so no street climbs more
  than one walking step over its footway station spacing, less a 2 mm rounding margin;
- each junction is level at its node's level: a pad for each leg, from the node out to that leg's
  mouth and across its street's carriageway and footways, but only as far across as the mouths of
  the legs leaving the node the other way, so no junction holds level ground where a crossing
  street has begun to climb;
- each segment is a ramp between its mouths, its end levels its nodes' levels;
- each lot is a pad level at its grade, the highest its footway reaches along its frontage, and its
  door stands on its street's centre line opposite its threshold;
- the entry is the first street node; every door must be reached from it over ground no steeper
  than the steepest street.

The graded land is sampled at a 1 m cell in the town's terrain records. A layout the land cannot
take is refused with the grading's code, and the next candidate is tried. The town's walking place
reads the street records the land raised, and a door's step is its threshold above the footway under
it.

The town composer's version 3
([`city_grammar_town.py`](../exulanica/world/composers/city_grammar_town.py), `on_land`) makes such
a town from a level town's recipe and a land document. It generates the recipe's specification
carried to city grammar version 6 by that version's migration, with the land, and a person arrives
on the graded footway as version 2 arrives. The receipt keeps the land document, its digest and the
land rules. The recipe's reference names the land's digest and rules, so a town's seeds, the land's
noise drawn from them and each tile's bake key are that land's own. A stored town is generated
again only after its land reads again under the rules its receipt names and to the digest it names
(`generated_world_land_changed`, `generated_world_land_rules_changed`). Where the deployment makes
worlds on land, a town drafted from a sentence ([below](#land-for-a-world-made-from-a-sentence)) and
`POST /worlds/kinds/town/worlds` with `land` make one, trying one identity; elsewhere the route
answers 422 `landform_not_served`. The tessellator bakes a town on land: its street lines bend in
height at the mouths, and its terrain closes the steps round lots at other heights than their
footways and their neighbours ([loom-tess](../web/packages/loom-tess/README.md)). Where a
corner's footways reach past its radius, the two meet on a mitre at the junction's level a
little back along both streets; a footway that climbs or falls stands on its own kerb line's
heights up to a ramp into that corner, as long again as the mitre reaches back. A footway over a
tile seam is drawn whole by the tile that owns its curb, and the other tile's terrain yields to
it.

The land round a town on land is served as a site's is. `GET /world/versions/{version_id}/land`
(world read) answers its land section (`exulanica.town-land/v1`): the land document's digest, every
near chunk (the town's tiles and one ring round them) and the backdrop by their digests, and the
land's own water. It is made in the kind worker from the town's receipt, graded for its records as
its terrain stage graded them (`city_grammar_town.graded_land`), and kept by the receipt alone,
since a town's land is graded before its buildings and no change to them moves it; the chunks under
the tiles are the town's terrain records' heights. The chunk and backdrop routes serve its documents
by those digests, and the saved entry's `generated_ground.land_sha256` names its land. A town on
level ground answers 404 `land_unavailable`; a site states its land in its drawing, and the section
route answers it 404 `unknown_reference`.

The page draws a town on land with its land round it
([`town-land.ts`](../web/packages/app/src/composition/town-land.ts)). It reads the land section,
held to its entity tag, its world and the digest the entry names, and every chunk and the backdrop
by the digests the section names, and draws the near chunks no tile covers (chunk (x, y) lies under
tile (x, y)), the backdrop and the water, in place of the look's flat plane beyond the tiles. Land
that cannot be read is not stood in for: the world does not open. The town's people stand on the
ground its tiles walk, and on the land where they walk none. A person walks the town's tiles; the
land round them is seen, not walked.

## A world's land rules

A world made on land keeps its land document, and its land is realized and graded again from that
document whenever it is drawn, served or walked. The same document under other rules would be other
land, so the receipt also names the rules that made it, `land_rules`
([`rules.py`](../exulanica/grammar/landform/rules.py)):

```json
{"version": 4, "catalogs": {"landform-feature.v3": "<sha256>", "landform-value.v3": "<sha256>"}}
```

- `version` stands for the realizer, its grading and the grading plan a site's layout asks of its
  land. A change to any of them that moves land, or what a site's drawing states of it, is the next
  version.
- `catalogs` names each catalog that shapes land by the digest of its canonical entries. A catalog
  changes by a new file (`landform-value.v3.json`), never by an edit of a shipped one.

A receipt that names other rules than the server's is refused by name before its layout is
generated again (`generated_world_land_rules_changed`, saying both rules); its world is never drawn
as other land, and its saved entry is listed unavailable by the same name
([saved world entry](saved-world-entry.md)). A level world's receipt names no land rules, and one
that does is refused the same way.

Every rules version this code makes the same land by is served: versions 1 to 4, each reading the
catalog version `SERVED_LAND_RULES` names (versions 1 to 3 their own, version 4 version 3's, since
it changes no catalog). The realizer and grading are one code for all; version 2 only adds the
`cascade` and version 3 its `follow` course, so land an earlier version admits is the same land
under a later one. Version 4 moves no height and changes what a site's drawing states: a site's
grading plan names each pond by its zone and its area's number in the zone (`zone 1 pond 0`) where
versions 1 to 3 name it by that number alone (`pond 0`), so two zones' ponds no longer share an id.
The grading plan takes the rules version the receipt names, so a world made under an earlier
version regenerates byte for byte, its ponds named as they were. New worlds name version 4. The
tests pin every shipped landform catalog byte for byte, and each served version with the catalogs
it names and the graded land of its own golden site, its water's ids among it
([`test_landform_rules.py`](../tests/test_landform_rules.py)), so a change that would move a served
version's land or what its drawing states fails until that version is no longer served.

The land's look is not part of the rules: `landform-surface.v1.json` colours land and shapes none
of it. A world's appearance should change only when its look does, so the surface catalog version a
world wears is to be named by its look (its style pack or style version), as its other choices of
appearance are; that naming is planned, not built (see [Limits](#limits)).

## Land for a world made from a sentence

Where the deployment turns it on (`EXULANICA_WORLDS_ON_LAND=on`, [deployment](deployment.md)), a
place or a town drafted from a person's words (`POST /worlds/drafts`,
[world kinds](world-kinds-contract.md#a-world-made-from-a-sentence)) stands on one of the land
recipes in [`landform-recipe.v2.json`](../assets/catalogs/landform/landform-recipe.v2.json), read by
[`recipes.py`](../exulanica/grammar/landform/recipes.py). Each recipe is a whole land document, read
by the landform reader as the catalog is read, with the words a made world's card says of it, the
whole words that name it in a sentence, the setting's ground parts that bring it, and a reason:

| Recipe | Named by words such as | Brought by the setting | What it is |
| --- | --- | --- | --- |
| `coast` | sea, coast, beach, shore, bay | By the sea | A beach and the sea below, a terraced hill behind, and a cascade stepping down from the place's sea-facing edge into the sea |
| `valley` | valley, dale, glen | | A broad floor between two long ridges, ranges at both ends |
| `upland` | mountains, peaks, highlands, fells | Snowfields | Rough fells and crags, peaks 1.5 to 2 km away on three sides |
| `hillside` | hillside, hill, slope | | Rising ground under a terraced hillside, a mountain behind |
| `rolling` | meadows, countryside, downs | Desert sand, Wheat fields | The default: gentle hills, far hills and ranges in haze |

The land is chosen without a model ([`land_choice.py`](../exulanica/world/land_choice.py)): first a
recipe a word of the sentence names, in the catalog's order (a word right after "no", "not",
"without", "far from" or "away from", an article between them aside, is not taken, nor a word inside
a saved name), then the recipe the setting chooser's ground part brings, then the default. The
place is composed on that land as `POST /worlds/kinds/{kind}/worlds` composes one, its receipt
keeping the recipe's land document and naming the land rules; a town is laid on it by the town
composer's version 3 ([towns on land](#towns-on-land)). Where no layout candidate of the place or
the town fits the land, it is composed once more on level ground. The draft states the land either
way (`land`: the recipe, what chose it, the person's own words that did, and `fell_back` where the
world was made level). A phrase the drafter reported it could not make is answered by the land only
where every word of it but the small joining words is one of the recipe's ("in a valley"; never
"sea with flying boats"). A draft's making waits up to 60 s for a place on land, since no request
waits on it; a town on land tries one identity's seed candidates, each about 8 to 11 s on the
development machine, before it is made level.

The recipes are data: a new or changed recipe is a new catalog version, and a world keeps the land
document it was made with, so a later recipe never moves it. New worlds read the newest version.
Version 2 differs from version 1 only in the coast, which gains its cascade: it starts 5 m beyond
the place's south edge, centred, and falls in steps of at most 2 m to the sea 80 m out. A cascade's
reach along its side is measured from the place's edge, so it clears a layout of any width and
lies in its near land. Where the coast drops faster than the pools step, the cascade's lips stand
as walls up to about 4 m.

## Refusals

| Code | When |
| --- | --- |
| `landform_invalid` | A document breaks its shape or a bound; the refusal names the path and the bound |
| `landform_near_out_of_bounds` | Near land, before or after grading, beyond 64,000 mm either way |
| `landform_range_too_near` | A range would begin to rise inside the walkable land |
| `landform_basins_overlap` | Two basins overlap or share a rim |
| `landform_corridor_too_steep` | A corridor cannot join two fixed levels within its grade |
| `landform_cut_too_deep` | A pad, corridor or bank would cut or fill beyond its bound |
| `landform_basin_over_locked` | A pond would be carved over a pad or a corridor |
| `landform_water_spills` | Water would stand above the ground beside it |
| `landform_unreachable` | A door cannot be reached from the entry |
| `landform_digest_mismatch` | A chunk is not the one its digest names |
| `landform_rules_changed` | A receipt names other land rules than the server's; the world is refused as `generated_world_land_rules_changed` |
| `landform_not_served` | Land asked of the town, or with a support declaration |
| `landform_cascade_beyond_near` | A cascade, its lips included, would reach beyond the near land |
| `landform_cascade_rises` | A cascade's end lies as high as its source or higher; a following cascade's land never falls its least fall, or its source stands at or below the sea |
| `landform_cascade_too_steep` | A cascade's pools would be shorter than 4 m for its drop and length; a following cascade would fall more than a step into the sea with no room for another pool |
| `landform_cascade_crossed` | A layout's pad or corridor would cross a cascade's pool or fall |

## Limits

- Only a place drafted from words stands on land, and only where the deployment turns it on; no
  page asks for land otherwise. A town is made on land only there too, and a person walks its
  tiles alone: the land round them is seen, not walked.
- Walkable land stays within 64 m above or below the sea, so "high ground" cannot be high: an
  upland is a place among peaks, not a place on a high plateau. Raising the bound is a change to
  the land rules.
- Mountains read as mountains from about 1.5 km away or more; nearer, they fill the sky as a pale
  wall. The recipes keep their ranges that far out.
- The land is chosen from listed words, the setting and a default, not by reading the sentence:
  a "not" more than a word before a land word is not seen, and land the recipes do not hold (an
  island, a canyon) cannot be asked for. Two worlds on one recipe differ only in the land's noise,
  which their seeds draw; sides and offsets are the recipe's.
- Making a place on land takes longer than on level ground: 6 to 11 s a world on the development
  machine's copy, and once more than the route's 15 s under heavy load.
- The application draws a site's land with no shadow from it: hills cast none. A pick is not
  hidden by a hill. Faces steeper than about 35 degrees are drawn in the surface catalog's stone
  colour, not a style pack's surface.
- Positions in a society stay two integers and plan distance stays the walking cost; walking uphill
  takes no longer.
- One heightfield per chunk: no overhangs, arches or passages under terraces.
- In a town on land, where a corner's footways reach past its radius on a street that climbs or
  falls, the footway is drawn ramping into the corner's level while the walking graph reads the
  street's own slope up to the corner: near the corner the two differ, by up to 121 mm at the
  mitre's frontage point over 20 measured towns (median about 30 mm).
- A corridor steeper than its grade is refused rather than given stairs.
- Below the datum a shore's sea covers everything; a valley carved below it floods.
- Performance is measured only on the development machine's tests; no drawing cost is stated here.
- The server serves land rules versions 1 to 4. A world made under any other is refused, not
  realized by the rules it names. A world made under versions 1 to 3 keeps its ponds' ids, so two
  of its zones' ponds may share one.
- A world does not name the land surface catalog it wears: a newer land look reaches every world on
  land. Naming it by the world's look is planned.
- A cascade is straight, along one of the four main sides, and its water stands still: level pools
  and fixed falls. No stream meanders, and nobody walks in the water or behind a fall.
