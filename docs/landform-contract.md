# Landform

Status: **IMPLEMENTED BOUNDARY: DATA, READERS AND SITE WORLDS ON LAND, DRAWN; NOT YET ASKED FOR**.
A world's land can be stated as data, realized, graded and read back in Python and in the browser,
and a site world can be made on land through its route: graded, regenerated from its receipt, its
people's places standing on the land, its drawing and its land served. The application draws such
a site on its land, to the horizon, and stands its people and things on it. No product page or
drafter asks for land, so every world anyone has made stands on level ground, as the
[world kinds contract](world-kinds-contract.md) and the [city grammar](grammar-package.md) state.

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
- [Sites on land](#sites-on-land)
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

Two catalogs in `assets/catalogs/landform/`, read through the grammar's catalog loader so each entry
carries a reason and a licence (`exulanica/grammar/landform/catalog.py`):

- `landform-feature.v1.json`: one entry per kind: `words` (what a person or a model reads),
  `domain` (`near_and_far`, or `far` for a feature drawn only), `composition` (`additive` or
  `shaping`) and `most` (how many one land may list).
- `landform-value.v1.json`: one entry per value, keyed `<feature>_<value>`: `minimum`, `maximum`,
  `default`, `required`, and for a value in words its `words` (the default indexes them). The
  feature `land` bounds the document: `ground_mm` and how many `features` it lists.

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

## Realizing a land

`H(x, y)` is the land's height in millimetres at a point east and north of the world's south-west
corner (`exulanica/grammar/landform/realize.py`). It is a pure function of the land and the
world's seed, computed with integers only: hashed value noise on integer lattices, fixed-point
smoothsteps, integer square roots. Additive features sum; then shaping features apply in a fixed
order, terraces, shores, basins, so a basin's level is set by the rim it ends with. Each recipe is
bounded to the land it was written for and fades out beyond it. Noise is sampled on the world's
own axes, so a grid of samples computes its interpolation weights once per row and column.

Within each tier of natural rise a terrace holds the lower part level, a bench, and the upper part
(`riser_share_permille` of the tier, 800 by default) is a bank climbing the whole tier, so a bank is
no steeper than the slope beneath divided by its share: on gentle land the steps are grassed
banks, on steep land they are as steep as the land demands. Behind a beach the land rises away from
the water at most at the coast grade (350 per mille by default); where the waterline wanders that
slope steepens, and a level coast with the defaults rises no steeper than 600 per mille. Both are
functions of each point alone, so the near land and the backdrop agree wherever they meet.

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
it, before it is carved, less its freeboard. Basins that overlap or share a rim are refused.

## Grading

`exulanica/grammar/landform/grading.py` grades realized near land for a layout, in order:

1. Pads with a stated level are set flat.
2. Corridors (paths, streets; rectangles graded along `x` or `y`) take the land's own profile
   brought within their grade at the least cut and fill (the midpoint of the largest and smallest
   grade-limited envelopes), held to every level already fixed under their centre line. A
   corridor is level across, except where it crosses one graded before it, which keeps the
   crossing.
3. Pads with a door are set flat at the ground's height at the door; a pad with neither takes the
   land's height at its middle.
4. Every other sample is held between the cones of the fixed samples at the bank grade (1 in 2).
   Where two fixed samples are closer than their difference allows, a retaining wall takes the
   difference and is listed with its height.
5. Ponds are carved as the ellipse inscribed in their rectangle, below a level that is the lowest
   ground on the 2 m ring outside them less a freeboard.

Then the checks: cut and fill within 8,000 mm; every water body holds (every dry sample beside a
wet one stands at or above its level); every door reachable from the entry over ground walked at 1
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
  catalog's freeboard;
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
| `landform_not_served` | Land asked of the town, or with a support declaration |

## Limits

- No product page or drafter asks for land. Towns are laid out on level ground.
- The application draws a site's land with no shadow from it: hills cast none. A pick is not
  hidden by a hill. Faces steeper than about 35 degrees are drawn in the surface catalog's stone
  colour, not a style pack's surface.
- Positions in a society stay two integers and plan distance stays the walking cost; walking uphill
  takes no longer.
- One heightfield per chunk: no overhangs, arches or passages under terraces.
- A corridor steeper than its grade is refused rather than given stairs.
- Below the datum a shore's sea covers everything; a valley carved below it floods.
- Performance is measured only on the development machine's tests; no drawing cost is stated here.
