# Landscape and volumes

Status: **IMPLEMENTED BOUNDARY: DATA, REALIZATION AND A SITE WORLD ON A LANDSCAPE THROUGH ITS
ROUTE; NOT DRAWN OR WALKED YET**. A volume (rock that overhangs, a sea stack, an arch, a spire) can
be stated as data, read against its catalogs, evaluated as an exact integer field, meshed by chunk
and searched for walkable tops in Python; a landscape places volumes on an unchanged land and
realizes each under a seed of its own. A site world can be laid out on a landscape through its
route, kept under the receipt check every site world meets, and its landscape's drawing, chunks and
tops are served by digest. The application does not draw volumes yet, people do not walk on them,
and a world made from a person's words never stands on a landscape.

This document owns the volume document (`exulanica.volume/v1`), the landscape document
(`exulanica.landscape/v1`), their catalogs, the volume field, the chunk (`exulanica.volume-chunk/v1`)
and top (`exulanica.volume-sheet/v1`) documents, the volume rules and the landscape rules. The land a
landscape carries belongs to the [landform contract](landform-contract.md); a site laid out on land
belongs to the [world kinds contract](world-kinds-contract.md).

<details>
<summary>Sections</summary>

- [In plain words](#in-plain-words)
- [The volume document](#the-volume-document)
- [The volume catalogs](#the-volume-catalogs)
- [The field](#the-field)
- [Chunks](#chunks)
- [Walkable tops](#walkable-tops)
- [The landscape document](#the-landscape-document)
- [Realizing a landscape's volumes](#realizing-a-landscapes-volumes)
- [Volume rules and landscape rules](#volume-rules-and-landscape-rules)
- [A site on a landscape](#a-site-on-a-landscape)
- [Refusals](#refusals)
- [Limits](#limits)

</details>

## In plain words

The land is one height at every point, so it cannot say a cliff that overhangs, a sea stack with an
arch through it, or a spire. A volume can. It is a short list of parts (a ball, a box, a limb from
one point to another, a round column whose top may be wider than its base, an arch through the
mass, and a level the mass is cut at), each placed, turned and leaned, joined to what comes before
it with a stated blend, then weathered and bedded. Code turns the parts into a solid the same way
every time, in whole numbers, meshes its surface for drawing at several levels of detail, and
finds the tops a person could stand on. A landscape is a world's land with volumes placed on it;
the land and the volumes inside it are the same documents they are alone.

## The volume document

`exulanica.volume/v1` (`exulanica/grammar/volumes/document.py`) is a closed object in whole
millimetres and millidegrees, in the volume's own frame (east, north, up):

| Key | Meaning |
| --- | --- |
| `profile`, `id` | The profile and a lowercase key |
| `look`, `top_look` | Catalog words for its faces (`rock`, `wall`) and its upward faces (`moss`, `grass`, `rock`, `sand`) |
| `walk` | `tops` (its walkable tops are found) or `none` (scenery) |
| `erosion` | `amplitude_mm`, `wavelength_mm`, `octaves`, `ridged` |
| `strata` | `amplitude_mm`, `period_mm` |
| `parts` | 1 to 32 parts, each `id`, `shape`, `op` and the values its shape and every part state |

A part states `at_mm` (three numbers), `yaw_mdeg`, `tilt_mdeg`, `toward_mdeg`, `blend_mm` and `look`,
and its shape's own values; a `cap` states only its height, blend and look. Defaults are written in
at reading, so a later default never changes a volume made before it, and the volume's identity is
the SHA-256 of its canonical JSON. A volume holds no free text: its parts are named by keys.

## The volume catalogs

Two entry-shaped files in `assets/catalogs/volumes`, read through the grammar's catalog loader so
every entry carries a reason and a licence: `volume-shape.v1.json` (each shape's words, the
operations it performs, the first its default, and whether it has a placement) and
`volume-value.v1.json` (every value's bounds, default, whether it is required, and whether it is one
number, three numbers or a word). A catalog changes only by a new version.

## The field

`VolumeField` (`exulanica/grammar/volumes/field.py`) gives the signed distance to the volume's
surface at any point: negative inside, zero on the surface, positive outside. It is computed with
integers only (no float, no `math`, no `numpy`, as the grammar package requires):

1. Solid parts in the document's order, an `add` by a polynomial smooth union and a `carve` by a
   smooth subtraction, each with its blend. A turned part takes a point into its own frame by the
   transpose of an integer turn matrix (sine and cosine of whole millidegrees by an integer Taylor
   series at 2^62, `turns.py`).
2. Erosion: three-dimensional integer value noise on the volume's own axes (`noise3.py`), lattice
   values from SHA-256 of a seed drawn under the volume profile's prefix, times the amplitude.
3. Strata: a triangle wave in height, so beds are level.
4. Caps in order, each a smooth intersection with the half-space below its level, so a capped top
   stays level whatever the weathering below it.

A part is evaluated only inside its bounds grown by a margin, and weathering only where it can
reach the surface; the margin is chosen so that every value within 4 m of a surface (`EXACT_MM`) is
the value the whole field gives and every sign is the whole field's sign everywhere. Every solid
point lies within the field's `extent`. `air_reach` states how far round a point every point is
certainly air, from the parts' slope bound and the weathering amplitudes.

## Chunks

`exulanica.volume-chunk/v1` (`exulanica/grammar/volumes/realize.py`) is one cube of a volume's
surface 32 m a side, in the volume's own frame, at a cell of 500, 1000, 2000 or 4000 mm. The field
is sampled one cell beyond each face and meshed by surface nets in whole numbers: a vertex in each
cell the surface crosses (the mean of its edge crossings, each kept a millimetre inside its edge),
one quad for each grid edge the surface crosses, turned from solid to air, owned by the chunk that
holds its lower end. Neighbouring chunks therefore meet without a seam. A vertex carries its normal
(the gradient over its cell, at 32767) and the look of the nearest added part.

A chunk names the volume's digest and the digest of what it is a function of (`input_sha256`: the
volume, the seed and the volume rules); its own identity is the SHA-256 of its canonical JSON. The
reader refuses a chunk by path and, given a digest, any chunk but the one it names.

## Walkable tops

`exulanica.volume-sheet/v1` (`exulanica/grammar/volumes/sheets.py`) is one walkable top of a volume
whose `walk` is `tops`, on the 1 m lattice of its frame. Only the topmost face of each column is
walked; undersides, cliff faces and the soffits of overhangs never are. A column's top is searched
from above, each step as long as the air round the point is certain and never shorter than 250 mm,
then halved to the millimetre. A cell is walkable when its four corners have tops, no edge climbs
more than 1 in 4 (the land's walking grade), and the field 1.2 m above each corner is at least 1 m.
Each 4-connected set of walkable cells is a surface `top:<n>`, numbered in the order its first cell
comes from the south-west; it holds heights over its rectangle and its walkable cells as runs.

## The landscape document

`exulanica.landscape/v1` (`exulanica/grammar/landscape/document.py`):

| Key | Meaning |
| --- | --- |
| `profile` | The profile |
| `extent_mm` | The world's extent east and north from its south-west corner |
| `land` | An unchanged `exulanica.landform/v1` document |
| `volumes` | Placements: `id`, an unchanged `volume` document, `at_mm` (its origin in the world), `yaw_mdeg`, and in the canonical form `volume_sha256` |
| `finest_cell_mm` | The finest cell its volumes are meshed at (2000 by default); every coarser one is meshed too |

Values are bounded by `assets/catalogs/landscape/landscape-value.v1.json`. The land and each volume
are read by their own readers; a refusal of either is passed on with its path inside the landscape
(`volumes[1].volume.parts[0].radius_mm`) and its own code. A placement's origin lies on the land near
the world: the extent and the ring of land chunks round it that the land realizer realizes, so a sea
stack may stand in the bay beyond a site's edge. One volume may be placed many times.

## Realizing a landscape's volumes

`compose_volumes` (`exulanica/grammar/landscape/compose.py`) realizes each placement in order: a
seed of its own, drawn from the landscape's seed and its id under the prefix
`exulanica.landscape-volume/v1`; its chunks at every stated level, coarsest first; its walkable tops.
Chunks and tops stay in the volume's own frame, and the placement's origin and turn place them in
the world, so the drawing's `volumes` section names each placement and the digests of its chunks
and tops, and the documents those digests name are kept and served by digest. The land is realized
by its own realizer under its own rules.

## Volume rules and landscape rules

`volume_rules()` (`exulanica/grammar/volumes/rules.py`) names the volume rules version, which stands
for the field, the chunk realizer and the top search, and the digest of each volume catalog.
`landscape_rules()` (`exulanica/grammar/landscape/rules.py`) names the landscape rules version (the
composition), the volume rules it realizes by, and the landscape catalog's digest. A change that
moves any value, vertex or top is a new version; rules a server does not serve are refused by name
(`volume_rules_changed`, `landscape_rules_changed`), never realized as other geometry. The tests pin
each served version's catalogs, golden field, chunks, tops and composition.

## A site on a landscape

`POST /worlds/kinds/{kind}/worlds` takes a `landscape` instead of `land`
([world kinds contract](world-kinds-contract.md)). The site is laid out on the landscape's land
exactly as on that land alone (site-plan composer version 6, `exulanica/world/composers/site_plan.py`),
so its receipt carries version 5's `land`, `land_sha256` and `land_rules` (the landscape's land), and
beside them `landscape`, `landscape_sha256` and `landscape_rules`; its site drawing, land routes,
grading and the place its people walk are version 5's. The landscape's extent is the site's (the
land's frame is the site's extent), and every placed volume stands off the site: its whole extent,
turned by its yaw and moved to its origin, reaches no part of the site's rectangle, so a site's
people never meet rock their place does not know. Volumes stand on the land beyond the site's edge.

`exulanica.landscape-drawing/v1` (`exulanica/world/landscape_drawing.py`) names the world, its
receipt's digest, its site drawing's digest, its land's and its landscape's digests, the landscape
rules version, and the `volumes` section; it is made with the site's drawing in the kind worker
from a seed drawn from the world's identity and the landscape's digest, and kept with it. A reader
places a point `p` of a placed volume's chunk or top at `at_mm + R(yaw) p`, `R` the turn
counterclockwise seen from above. The drawing, each chunk and each top are served by digest
(`GET /world/versions/{version_id}/landscape`, `.../landscape/chunk?sha256=`,
`.../landscape/top?sha256=`, world read). A receipt whose landscape no longer reads under the rules it
names, or is not the one its digest and land name, is refused by name and listed unavailable.

## Refusals

| Code | When |
| --- | --- |
| `volume_invalid` | A volume document, chunk or top breaks its shape or a bound (by path) |
| `volume_part_wrong_op` | A part performs an operation its shape does not, or a cap states a placement |
| `volume_rounding_too_large` | A box's or a column's rounding is larger than its shape allows |
| `volume_too_many_parts` | More parts than the catalog allows |
| `volume_digest_mismatch` | A chunk or top is not the one its digest names |
| `volume_rules_changed` | A chunk, top or receipt names volume rules this server does not serve |
| `landscape_invalid` | A landscape document breaks its shape or a bound (by path) |
| `landscape_outside_near_land` | A placement's origin lies off the land near the world |
| `landscape_digest_mismatch` | A placement's `volume_sha256` is not its volume's digest |
| `landscape_rules_changed` | A receipt names landscape rules this server does not serve |
| `landscape_extent_not_site` | A site's landscape states another extent than the site's |
| `landscape_volume_on_site` | A placed volume reaches onto the site it is placed round |
| `landscape_not_served` | A landscape asked of the town, or beside land or a support declaration |
| `landscape_unavailable` | A landscape route asked of a world on no landscape (404) |
| `landscape_document_unavailable` | A chunk or top the world's landscape drawing does not name (404) |
| `generated_world_landscape_rules_changed` | A receipt names landscape rules this server does not serve, or names them on a world on no landscape; the world is listed unavailable |
| `generated_world_landscape_changed` | A receipt's landscape no longer reads, or is not the one its digest and land name |

## Limits

- Pure Python integers: a stack's surface takes about a second at 4 m, a few seconds at 2 m, tens of
  seconds at 1 m and minutes at 0.5 m on one core, so fine levels are for chunks near where people
  stand and every chunk is kept by its digest.
- Surface nets round sharp edges and thin parts under about two cells; a few edges where two sheets
  touch in one cell border four triangles.
- A solid thinner than 250 mm can be stepped over by the top search; tops are of one volume alone,
  and where placed volumes meet, which top is walked is not decided yet.
- Volumes are not drawn by the application and not walked by people yet, and stand only off a site;
  sky islands, spans, landmark flora and far layers are not part of `exulanica.landscape/v1`.
- Realized chunks and tops are kept in the kind worker's memory with the site's drawing, as a site's
  land chunks are, not in a store; a world read again later realizes them again.
- A world made from a person's words never stands on a landscape: no world tool names one.
