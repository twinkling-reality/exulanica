# Landscape and volumes

Status: **IMPLEMENTED BOUNDARY: DATA, REALIZATION, A SITE WORLD ON A LANDSCAPE THROUGH ITS ROUTE,
AND ITS VOLUMES DRAWN IN ROCK; NOT WALKED YET**. A volume (rock that overhangs, a sea stack, an arch, a spire) can
be stated as data, read against its catalogs, evaluated as an exact integer field, meshed by chunk
and searched for walkable tops in Python; a landscape places volumes on an unchanged land and
realizes each under a seed of its own. A site world can be laid out on a landscape through its
route, kept under the receipt check every site world meets, and its landscape's drawing, chunks and
tops are served by digest. A site world can also be laid out on a placed volume's top, a sky
island's, kept and drawn there by its site drawing; the application draws it on the island, over
the landscape's land below.
The application draws a site's volumes round it in rock; people do not walk on them, and a world
made from a person's words never stands on a landscape.

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
- [Walkable surfaces and reach](#walkable-surfaces-and-reach)
- [Volume rules and landscape rules](#volume-rules-and-landscape-rules)
- [A site on a landscape](#a-site-on-a-landscape)
- [Grading a site on a volume's top](#grading-a-site-on-a-volumes-top)
- [A site on a volume's top](#a-site-on-a-volumes-top)
- [Settings](#settings)
- [Readers in the browser](#readers-in-the-browser)
- [Sky islands](#sky-islands)
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
| `strata` | `amplitude_mm`, `period_mm`, and from catalog version 2 `spread_mm`, `relief_permille`, `offset_permille`, `tilt_mdeg`, `toward_mdeg` (how the beds vary) |
| `parts` | 1 to 32 parts, each `id`, `shape`, `op` and the values its shape and every part state |
| `top_land` | From catalog version 3, optional: a land its top follows instead of a level, `land` (an unchanged `exulanica.landform/v1` document), `side_mm` and `blend_mm` |

A part states `at_mm` (three numbers), `yaw_mdeg`, `tilt_mdeg`, `toward_mdeg`, `blend_mm` and `look`,
and its shape's own values; a `cap` states only its height, blend and look. Defaults are written in
at reading, so a later default never changes a volume made before it, and the volume's identity is
the SHA-256 of its canonical JSON. A volume holds no free text: its parts are named by keys. A bed
is at least 1 m, so the strata's spread is at most the period less 1 m.

A top land's `land` is read by the land reader against the landform catalog version the volume
catalog names (version 3 for volume catalog version 3), unchanged and with its defaults written in,
and refused by its path under `top_land.land`. It covers a square of side `side_mm` centred on the
volume's own origin, in whole 2 m so the square's corners and middle lie on the land's 1 m lattice;
the square's south-west corner is the land's origin and the volume's level 0 is the land's datum.
A volume that states no top land has the canonical bytes and identity it had under version 2.

## The volume catalogs

Two entry-shaped files at each version in `assets/catalogs/volumes`, read through the grammar's
catalog loader so every entry carries a reason and a licence: `volume-shape.vN.json` (each shape's
words, the operations it performs, the first its default, and whether it has a placement) and
`volume-value.vN.json` (every value's bounds, default, whether it is required, and whether it is one
number, three numbers or a word). A catalog changes only by a new version, which keeps every entry
of the one before it. Version 2 adds the five strata values that vary the beds, each defaulting to
level, even beds; its shapes are version 1's. Version 3 adds the top land's two values, the side of
its square (2 m to 128 m) and the blend of its cut (0 to 30 m, by default none); its shapes and
every other value are version 2's. A volume is read against one version (the newest,
unless a world's rules name another) and records it.

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
3. Strata: a triangle wave across each bed, standing out at its middle and cut back at its joins.
   Stated plainly the beds are level, each the period thick and standing out by the amplitude. The
   version 2 values vary them: beds alternate thicker and thinner than the period, each by a drawn
   amount from a quarter of the spread to all of it, so no two in a row are equal; each steps out by
   a drawn share of the amplitude (`relief_permille` less at most) and is set proud or recessed
   within what is left; each stands proud on one drawn side of the volume's own vertical axis and
   recessed on the other (`offset_permille` of the amplitude); and the bedding planes lean by
   `tilt_mdeg` toward the bearing `toward_mdeg`. Each bed is drawn from the seed and its index, bed
   0 lying on the volume's own level 0, and its whole contribution stays within the amplitude, so
   the culling margin, the extent and `air_reach` hold as they are. The relief and the offset fade
   to nothing over the lowest quarter of the volume's height, so a recessed bed never pinches the
   narrow foot of an island or a stack into a neck.
4. Caps in order, each a smooth intersection with the half-space below its level, so a capped top
   stays level whatever the weathering below it.
5. The top land, where the volume states one, the same way below its surface: the land is realized
   once for the field by the land realizer on its own 1 m lattice over its square, the frame's seed
   drawn from the volume's id alone, so the same document has the same top wherever and under
   whatever seed it is placed. Between lattice points the surface is the floor of the bilinear blend
   of the four heights round the point, in whole numbers; beyond the square it is the height of the
   square's nearest edge point. A land the realizer refuses (beyond 64 m of its datum, a range rising
   inside the square, a cascade beyond it) is refused when the field is made, by its path under
   `top_land.land`; a site world on a landscape is refused so when it is made, before any receipt
   is written (`volume_invalid`, by its path in the request). A field may instead be given heights
   for its top on the same lattice (`TopHeights`: the top graded for a site laid out on it), which
   cap the rock in place of the land's own and are read between and beyond lattice points as they
   are; heights not one per point of the square's lattice, or given for a volume with no top land,
   are refused (`volume_top_heights_invalid`, path `top_land`).

A part is evaluated only inside its bounds grown by a margin, and weathering only where it can
reach the surface; the margin is chosen so that every value within 4 m of a surface (`EXACT_MM`) is
the value the whole field gives and every sign is the whole field's sign everywhere. Every solid
point lies within the field's `extent`, which stops at the lowest cap and at the top land's highest
height, realized or given. `air_reach` states how far round a point every point is certainly air, from the
parts' slope bound and the weathering amplitudes; a cap and a top land only raise a value, so they
change no bound below them.

## Chunks

`exulanica.volume-chunk/v1` (`exulanica/grammar/volumes/realize.py`) is one cube of a volume's
surface 32 m a side, in the volume's own frame, at a cell of 500, 1000, 2000 or 4000 mm. The field
is sampled one cell beyond each face and meshed by surface nets in whole numbers: a vertex in each
cell the surface crosses (the mean of its edge crossings, each kept a millimetre inside its edge),
one quad for each grid edge the surface crosses, turned from solid to air, owned by the chunk that
holds its lower end. Neighbouring chunks therefore meet without a seam. A vertex carries its normal
(the gradient over its cell, at 32767) and the look of the nearest added part.

A chunk names the volume's digest, the volume rules version its field was evaluated by
(`rules_version`), and the digest of what it is a function of (`input_sha256`: the volume, the seed,
the volume rules and, only where they are given, the digest of the heights its top is capped by,
so a chunk of a field capped by its own land names what it always named); its own identity is the SHA-256 of its canonical JSON. The reader reads a
chunk of any served rules version and refuses a chunk by path and, given a digest, any chunk but
the one it names. A top names its rules the same way.

## Walkable tops

`exulanica.volume-sheet/v1` (`exulanica/grammar/volumes/sheets.py`) is one walkable top of a volume
whose `walk` is `tops`, on the 1 m lattice of its frame. Only the topmost face of each column is
walked; undersides, cliff faces and the soffits of overhangs never are. A column's top is searched
from above, each step as long as the air round the point is certain and never shorter than 250 mm,
then halved to the millimetre. A cell is walkable when its four corners have tops, no edge climbs
more than 1 in 4 (the land's walking grade), and the field 1.2 m above each corner is at least 1 m.
Each 4-connected set of walkable cells is a surface `top:<n>`, numbered in the order its first cell
comes from the south-west; it holds heights over its rectangle and its walkable cells as runs.
Under a top land whose rock reaches above it, a top is the land itself, within a quarter of the
cut's blend below it and never above it, and its cells are walked where the land is no steeper than
1 in 4.

## The landscape document

`exulanica.landscape/v1` (`exulanica/grammar/landscape/document.py`):

| Key | Meaning |
| --- | --- |
| `profile` | The profile |
| `extent_mm` | The world's extent east and north from its south-west corner |
| `land` | An unchanged `exulanica.landform/v1` document |
| `volumes` | Placements: `id`, an unchanged `volume` document, `at_mm` (its origin in the world), `yaw_mdeg`, and in the canonical form `volume_sha256` |
| `finest_cell_mm` | The finest cell its volumes are meshed at (2000 by default); every coarser one is meshed too |
| `site` | From catalog version 2, optional: a site laid out on a placed volume's top, `on` (the placement's id), `at_mm` (the site's south-west corner in that volume's own frame) and `cut_fill_mm` (the deepest its grading may cut or fill, 0.5 to 4 m, 2 m by default) |

Values are bounded by `assets/catalogs/landscape/landscape-value.v1.json` and
`assets/catalogs/landscape/landscape-value.v2.json`; version 2 keeps every entry of version 1 and
adds the site's two values. The land and each volume
are read by their own readers; a refusal of either is passed on with its path inside the landscape
(`volumes[1].volume.parts[0].radius_mm`) and its own code. A placement's origin lies on the land near
the world: the extent and the ring of land chunks round it that the land realizer realizes, so a sea
stack may stand in the bay beyond a site's edge. One volume may be placed many times.

A `site` names a placement whose volume states a top land (`landscape_site_unknown_placement`,
`landscape_site_no_top_land`), and its corner stands at whole metres inside that top land's square
(`landscape_site_outside_top`), each refused by its path under `site`. The canonical form writes
`site`, with its bound, only where it is stated, so a landscape without one keeps the identity it
had under version 1. A landscape that states a site makes a world on that volume's top
([a site on a volume's top](#a-site-on-a-volumes-top)).

## Realizing a landscape's volumes

`compose_volumes` (`exulanica/grammar/landscape/compose.py`) realizes each placement in order: a
seed of its own, drawn from the landscape's seed and its id under the prefix
`exulanica.landscape-volume/v1`; its chunks at every stated level, coarsest first; its walkable tops.
Chunks and tops stay in the volume's own frame, and the placement's origin and turn place them in
the world, so the drawing's `volumes` section names each placement and the digests of its chunks
and tops, and the documents those digests name are kept and served by digest. The land is realized
by its own realizer under its own rules. The process that composes keeps the volumes its last
composition realized, by each field's `input_sha256` and the levels, and the ground below a site on a
volume's top by its land's digest and frame: a world's landscape drawn again after a part edit
realizes only the volume whose top was regraded, if any, and from landscape rules 6, whose ground
below takes the landscape's own seed, every other world made on that landscape stands over the
ground realized once. In the kind worker that process is its child, which erasing a world ends. An
API that warms the settings' ground (`EXULANICA_WARM_SETTING_GROUNDS`, on for a personal install)
asks that child, as it starts and without waiting, to realize the ground below each shipped
setting's landscape under the newest landscape rules, so the first world made on a setting after a
restart stands over ground already realized too; the child keeps one ground, so of several settings
the last warmed is kept. The warming yields to a person's work: a job asked before it finishes ends
it and runs at once ([world kinds](world-kinds-contract.md#checks)), and that world's ground is realized
with it, as without the warming.

## Sea stacks

`exulanica.sea-stack/v1` (`exulanica/grammar/stacks/document.py`) states one sea stack by a few
values in its own frame, whose level 0 is the sea's surface where it is placed; the maker
(`exulanica/grammar/stacks/maker.py`) turns a stack and a seed into an unchanged
`exulanica.volume/v1` document with the stack's id. Nothing reads a sea stack yet.

| Key | Meaning |
| --- | --- |
| `profile`, `id` | The profile and a lowercase key |
| `height_mm` | How high its level top stands above level 0, 6 to 150 m |
| `foot_mm` | How far its trunk reaches below level 0 to the sea floor, 2 to 64 m: a stack never ends in open water |
| `base_radius_mm`, `top_radius_mm` | The trunk's radius at its foot and at its top; a wider top overhangs, at most twice the base |
| `lean` | `tilt_mdeg` (at most 10 degrees) toward the compass bearing `toward_mdeg` |
| `shoulders` | 0 to 4 rounded masses on its flanks |
| `arch` | `none` (the default), or a passage: `width_mm`, `rise_mm` (its crown above the water), `floor_mm` (below the water, at least 6 m, 7 m by default) and `bearing_mdeg` (the bearing it runs along, below 180 degrees) |
| `erosion`, `strata` | A volume's own sections, bounded by the volume catalogs at version 2 |
| `look`, `top_look`, `walk` | `rock`; `grass` by default, or `rock`, `moss`, `sand`; `none` by default (nobody stands on a sea stack), or `tops` |

Its values are bounded by `assets/catalogs/stacks/sea-stack-value.v1.json`, read with the volume
value schema so every entry carries a reason and a licence; a look, top look or walk word must be
one a volume admits. Defaults are written in, and its identity is the SHA-256 of its canonical JSON.
Beyond its bounds a stack is held to four rules, each refused by its own code: the trunk's flank
away from its lean faces up by at most 1 in 4 (about 14 degrees), its taper and its lean together;
a passage is at most the trunk's radius wide where it passes, and its round head fits within its
floor depth and rise; the rock over its crown is at least its width; and its floor lies at least
the weathering (the erosion's and the strata's amplitudes) and 3 m above the foot.

The maker's parts, in order, at most seven:

1. A trunk column, rims rounded 1 m, leaned by the stack's lean with its axis crossing level 0 at
   the origin. It reaches the weathering and 1 m below the foot, so weathering never lifts the foot
   off the sea floor and the field is solid on its axis just above `-foot_mm`; its radius runs from
   `base_radius_mm` at the foot to `top_radius_mm` at the top.
2. Its shoulders: spheres blended 4 m into the trunk, a turn over their number apart from a drawn
   first bearing, centred on the trunk's axis at a drawn 30 to 75 percent of its height, each 45 to
   75 percent of the trunk's radius there.
3. The passage: an arch carved along its bearing, centred on the trunk's axis at its floor, through
   the whole stack.
4. A cap at `height_mm`, so the top is level whatever the weathering below it.

Its draws come from SHA-256 of the seed under the sea stack profile's prefix, the stack's id, what
is drawn and its index, in whole numbers, so the same stack and seed make the same volume, digest
for digest. The volume is read against volume catalog version 2 and its erosion and strata are the
stack's own: beds varied every way read as rock, even beds read as rings, and no beds as soft clay.
Shallow rock that faces up reads as a bright block in the bay's water, which is why a passage's
floor lies at least 6 m under, shoulders swell above the water and the flank rule holds. The field
lays bed 0 on level 0 with a recessed join, so the upper half of the bed below it faces up just
under the water: across eight seeds, between 4 and 33 percent of a stack's rock in the top 3 m of
water faced up by more than 17 degrees at the 2 m cell, a hand-made stack of the same sizes between
3 and 29 percent. The tests hold the stacks they make to under 15 percent under their seed.

## Walkable surfaces and reach

`exulanica.landscape-surfaces/v1` (`exulanica/grammar/landscape/surfaces.py`) names every surface a
person can stand on in a landscape, the joins a person steps between them, and what the arrival
reaches. It is made from the landscape, its volumes as `compose_volumes` realized them under the
landscape's seed, and its land under the land's own seed; nothing the composition realized is
realized again. Nothing reads it yet; it is what the walking layer is to stand people on.

- **Surfaces.** `ground` is the land's walkable dry surface; `volume:<placement id>/top:<n>` is each
  placed volume's walkable top, placements in the document's order. Each states its frame (the
  world's for the ground, the placement's origin and turn for a top), its walkable cells and the
  lowest and highest height of their corners in the world.
- **Points on the world plan.** A surface's walkable points are the corners of its walkable cells.
  A point `(x, y)` of a top's sheet lies `(c x - s y) // 2^30` east and `(s x + c y) // 2^30` north
  of its placement's origin, `s` and `c` the yaw's sine and cosine at 2^30, floored once as the
  spacing rule turns a volume's extent, and its height is raised by the origin's. A turned sheet's
  lattice is not the world's, so its points are compared where they fall on the world plan, never
  by their lattice indices.
- **The ground** is walked in the 1 m cells of the land near the world (beyond it the land is
  backdrop) whose four corners are dry and whose edges climb at most 1 in 4, the land's own walking
  rule. A point is dry unless it lies within a water body less than 350 mm above its level; a
  shore's sea lies everywhere at level 0. Only the ground near tops is realized: for each top, the
  box on the world lattice holding every point within one cell of its walkable points, grown by a
  cell for the cells round them. The ground states the walkable cells realized there, not the whole
  land's.
- **Joins.** Two surfaces join where a walkable point of one and a walkable point of the other lie
  within one cell on the world plan (east and north each at most 1000 mm apart) and within 180 mm
  in height, the place contract's step. A top joins the ground the same way. Each join is stated by
  the pair of points with the least climb (the lowest points on a tie).
- **Reach.** From the arrival, a stated point in a walkable ground cell or the ground as a whole
  when none is stated, every surface reached through joins is listed, and every walkable surface
  nothing reaches is listed as reached only by flight: a sea stack's top far above the water, an
  island with no join. An arrival outside a walkable ground cell is refused
  (`landscape_arrival_not_ground`, by `arrival_mm`).

| Key | Meaning |
| --- | --- |
| `profile` | `exulanica.landscape-surfaces/v1` |
| `landscape_sha256` | The landscape's digest |
| `cell_mm`, `step_mm` | The lattice cell (1000) and the step a join climbs at most (180) |
| `arrival_mm` | The stated arrival, east and north, or `null` for the ground as a whole |
| `surfaces` | Each surface: `surface`, `sheet_sha256` (its top's digest, `null` for the ground), `at_mm`, `yaw_mdeg`, `cells`, `height_mm` (lowest and highest in the world, `null` with no cells) |
| `joins` | Each join: `surfaces` (two, in the surfaces' order), `from_mm` and `to_mm` (its points in the world, on the first surface and the second), `climb_mm`, and `pairs` (how many pairs of points meet the rule) |
| `reached`, `flight_only` | Surface names, in the surfaces' order |

Every number is a whole number in millimetres, and the document's identity is the SHA-256 of its
canonical JSON, the same in every interpreter. Points are kept in buckets of a cell on the world
plan, so each is compared only with the points of the nine buckets round it. Measured result (15
October 2026, one process, under a load average of 52 to 69 on 18 cores): on a bay with two stacks
and three weathered sky islands holding fifteen tops, interleaved three times with the composition
of its volumes, the surfaces took 0.06 to 0.12 s and the composition 9.0 to 9.2 s.

The ground is one surface: two stretches of it divided by water or a cliff count as one, since the
land's own reach is the site's grading's to judge. Ground under a volume's rock is not taken out,
and land or water over a top is not checked. A join names a place to step, not a proven movement:
the exact contact decides each step.

## Volume rules and landscape rules

`volume_rules()` (`exulanica/grammar/volumes/rules.py`) names the volume rules version, which stands
for the field, the chunk realizer and the top search, and the digest of each volume catalog.
`landscape_rules()` (`exulanica/grammar/landscape/rules.py`) names the landscape rules version (the
composition), the volume rules it realizes by, and the landscape catalog's digest. A change that
moves any value, vertex or top is a new version; rules a server does not serve are refused by name
(`volume_rules_changed`, `landscape_rules_changed`), never realized as other geometry. The tests pin
each served version's catalogs, golden field, chunks, tops and composition.

| Landscape rules | Volume rules | Volume catalogs | Beds |
| --- | --- | --- | --- |
| 1 | 1 | version 1 | Level and even |
| 2 | 2 | version 2 | Level and even unless the strata vary them |
| 3 | 3 | version 3 | As version 2; a volume may state a top land |
| 4 | 3 | version 3 | As version 3; the landscape may state a site on a volume's top (landscape catalog version 2) |
| 5 | 4 | version 3 | As version 4; a site on a top grades its banks eased at their crest and toe (land rules 7) |
| 6 | 4 | version 3 | As version 5; the ground below a site on a top is realized under the landscape's own seed |

Volume rules 3 also name the land rules a top land is realized by (land rules 3, with their
catalogs' digests), fixed for that version so a later land rules version never moves a served
volume; volume rules 4 name land rules 7, whose banks ease at their crest and toe, and are volume
rules 3's rock vertex for vertex, their chunks and tops naming 4. A version 3 volume with no top
land is the same rock under volume rules 2, 3 and 4.

New worlds are made by the newest rules. A receipt is read back under the rules it names: its
volumes against the catalogs those name and realized by them, so a world made by landscape rules 1
rebuilds the same volume documents, chunks and tops, each naming rules 1. A volume whose strata
state no variation is the same rock under either volume rules version.

## A site on a landscape

`POST /worlds/kinds/{kind}/worlds` takes a `landscape` instead of `land`
([world kinds contract](world-kinds-contract.md)). The site is laid out on the landscape's land
exactly as on that land alone (site-plan composer version 6, `exulanica/world/composers/site_plan.py`),
so its receipt carries version 5's `land`, `land_sha256` and `land_rules` (the landscape's land), and
beside them `landscape`, `landscape_sha256` and `landscape_rules`; its site drawing, land routes,
grading and the place its people walk are version 5's. The landscape's extent is the site's (the
land's frame is the site's extent), and every placed volume stands off the site: its whole extent,
turned by its yaw and moved to its origin, reaches no part of the site's rectangle, so a site's
people never meet rock their place does not know. A new world's placed volumes also stand apart
(`exulanica/grammar/landscape/spacing.py`): where two reaches, each a volume's extent turned and
moved the same way, meet, the box they share is sampled every 2 m and a point that is rock in both
volumes, weathered as the drawing realizes them, is refused; a sliver of shared rock thinner than
the cell can pass, the check costs at most two field evaluations a point, and a receipt is never
held to it, so a world made before still reads and draws.
Volumes stand on the land beyond the site's edge.

`exulanica.landscape-drawing/v1` (`exulanica/world/landscape_drawing.py`) names the world, its
receipt's digest, its site drawing's digest, its land's and its landscape's digests, the landscape
rules version, and the `volumes` section, which also names each placed volume's `look` and
`top_look` from its volume document; it is made in the kind worker, in a job of its own after the
site's drawing it names, from a seed drawn from the world's identity and the landscape's digest,
and kept by the world's receipt. A reader
places a point `p` of a placed volume's chunk or top at `at_mm + R(yaw) p`, `R` the turn
counterclockwise seen from above. The drawing, each chunk and each top are served by digest
(`GET /world/versions/{version_id}/landscape`, `.../landscape/chunk?sha256=`,
`.../landscape/top?sha256=`, world read). A receipt whose landscape no longer reads under the rules it
names, or is not the one its digest and land name, is refused by name and listed unavailable.

## Grading a site on a volume's top

`site_top` (`exulanica/world/site_top.py`) grades a volume's top land for a site laid out on it, as
a site's land is graded. The
site keeps its own frame: its south-west corner stands at a whole-metre point of the volume's
frame, and its height zero is the volume's level 0, the top land's datum, whatever the volume's
altitude. The natural top is the same realization the field caps the rock by
(`realize_top_land`), moved into the site's frame on the same 1 m lattice. The site's records grade
it with the land's grader over the whole square, so banks run out to the rim, every zone is a level
pad and every walking edge stays within one step, as on land; the deepest cut or fill is the bound
the site states. A top is graded under the land rules the volume rules name for a top land (land
rules 3 under volume rules 3, land rules 7 under volume rules 4), never the newest land rules, so a
later land version never moves a graded top. `compose_site` takes the top in place of land. Heights between lattice points
follow the graded land's triangle rule. The graded top is a document, `exulanica.site-top/v1`: the
graded heights from the south-west corner, rows from the south, and the water standing on them.

A site that does not lie inside the square, or not at whole metres, is refused
(`landscape_site_outside_top`), and so is a top whose land has a shore
(`landscape_site_top_has_sea`: the sea is the ground's); every refusal of the grader holds as on
land. Whether the rock under a graded top holds it is the world's check below.

## A site on a volume's top

`POST /worlds/kinds/{kind}/worlds` with a `landscape` that states a `site` makes the world on that
placed volume's top (site-plan composer version 7, `exulanica/world/site_on_top.py`). The site
keeps its own frame, which is the world's: its height zero is the volume's level 0, so the volume's
altitude enters no height the world states, and the place its people walk says so in its frame's
datum. In order:

1. A kind whose people come in from homes off the site is refused
   (`landscape_site_offsite_homes`): nothing lies beyond a top for them to come from.
2. The site the kind's plan states must lie inside the top's square (`landscape_site_outside_top`)
   and, grown by 1 m, have rock 1 m under the natural top at every lattice point
   (`landscape_site_not_on_rock`), both before any candidate is laid out. The field is the
   volume's as the landscape realizes it: the placement's seed under the world's landscape seed.
3. Each candidate is laid out and graded on the top as `site_top` grades it; the kept candidate's
   graded top caps the volume's field in place of its land's own (given heights, as the volume
   field takes them), and the same rock rule is held on it.
4. A person arrives on the open top outside the site's gate in its south edge, between the gate
   and the rim: the first of 3, 2.5, 2 and 1.5 m beyond the gate with rock 1 m under the top there
   and a metre either side and beyond, or in the gate's opening where the site fills the top. They
   face the site through its gate, north into it, so the first view holds the hamlet: its track
   through the gate between its houses, with the island's other volumes beyond. On a top this
   small no spot holds both the houses and a third of the view in sea, so the first view is the
   hamlet's. Both are stored with the arrival, and a world keeps the arrival its receipt states.

The receipt is version 6's with the land the volume's top land, its digest and the land rules the
volume rules name for a top land (land rules 3), never the newest; the landscape and its rules
beside them, and the landscape states the site. A receipt reads its top back from the landscape
and is refused by name (`generated_world_landscape_changed`) where its landscape's site and its
composer disagree or its land is not the named volume's top land. The landscape's other volumes
stand apart as for version 6; the volume the site stands on is the world's ground and no other
check of extent or of volumes off the site applies.

The world's drawing is `exulanica.site-drawing/v6` ([world kinds
contract](world-kinds-contract.md)): version 5's slots, drape and arrival standing on the graded
top, with a `top` section in place of `land`: the graded top's digest, the landscape's digest, the
placement and the site's corner in the volume's frame, the water on the top, and `rock_cells`, the
graded lattice's cells (rows from the south, from its south-west corner, as runs `[row, first,
last]`) whose four corners have rock 1 m under the top, and, where the top's grading lists them
(land rules from version 5, so a top under volume rules 4), `walls`, the retaining walls where its
levels meet, stated and drawn as a site on land's. The graded top itself
(`exulanica.site-top/v1`) is kept with the drawing and served by its digest
(`GET /world/versions/{version_id}/land/top`); such a world has no land chunks or backdrop. A part
change that leaves the graded top off the rock is refused as a grading refusal is
(`landscape_site_not_on_rock`).

Its landscape is drawn as `exulanica.landscape-drawing/v2` (version 1 stays for a site on the
landscape's land), in the same job and under the same seed: version 1's fields and `volumes`, the
volume the site stands on realized with the graded top as its cap (read from the site's kept
`exulanica.site-top/v1` and held to its digest, which the drawing names as `top_sha256`, so each of
that volume's chunks and tops names it in its `input_sha256`; its land is the top land, as the
receipt's is), `site_frame` (the placement, the site's south-west corner in the landscape's frame,
`at_mm + R(yaw) (site corner)`, and the placement's turn: a page whose frame is the site's places the
landscape at its inverse), and `ground`: the landscape's own land, ungraded, in the landscape's
frame over its extent and one ring of chunks, realized under the landscape's own seed (from its
land's digest alone; `ground_seed`) from landscape rules 6, so every world made on one landscape
stands over the same ground, and under the seed a world's land is before them, as 128 m
land chunks, a backdrop and the water on it, the ground or sea the volume floats over. Its chunks
and backdrop are served by digest (`GET /world/versions/{version_id}/landscape/ground?sha256=`). The
application draws such a world as [readers in the browser](#readers-in-the-browser) says.

## Settings

The settings catalog (`assets/catalogs/landscape-settings/landscape-setting.v2.json`, read by
`exulanica/grammar/landscape/settings.py`; version 1 stays at its path and is not read) names
landscapes a world of a kind can stand in. Each entry states a `key`, a `label`, a whole
`exulanica.landscape/v1` document read and held as every landscape is, the shipped kinds whose worlds
start on it (`starters`, each a kind's key and version), and a reason and a licence, and may state
`setting_parts`, a part's key for each axis of the setting parts catalog it names, which a world
started on it is drawn in ([world kinds contract](world-kinds-contract.md)). Keys are unique and a
kind starts on one setting at most; a catalog that breaks a rule is refused where it broke it, and a
part the setting parts catalog does not hold is refused where a world is drawn in it. Version 2 holds
`island_over_the_bay`: a sky island 40 m across with a gentle hill for its top, 95 m over a bay with
two sea stacks and two smaller islands, its site's corner 11 m west and south of the island's middle,
so a site up to 22 m square stands on its top, under a clear noon sky. Its one starter is the shipped
kind `island_hamlet`, "Hamlet on a sky island".

A world of a starter made with no land, landscape or support of its own, as Create a world's card for
it makes one, is composed on its setting's landscape exactly as any world on a volume's top is
([a site on a volume's top](#a-site-on-a-volumes-top)); its receipt keeps that landscape, so a later
settings version never moves a world already made. Only the shipped document itself starts there: a
workspace's kind of the same key and version is its own kind
([world kinds contract](world-kinds-contract.md)). Settings are not offered to choose between.

## Readers in the browser

`readLandscapeDrawing` and `readVolumeChunk` (`web/packages/atlas-core/src/landscape.ts`) read the
landscape drawing and a volume chunk with the server's bounds, each held to the digest its route and
its drawing name; a chunk of either served volume rules version reads, since both share one chunk
format. The page asks every site on land for its landscape; a 404 `landscape_unavailable`
means it has none. The landscape drawing must name the site's own drawing, world and land. Each
placed volume is drawn at one level: the finest it names that is not finer than 2 m (the
landscape's default finest cell), else the coarsest it names (`volumeDrawnCellMm`), and only that
level's chunks are fetched (`readSiteVolumes`, `web/packages/atlas-react/src/playcanvas/generated-site/site-volumes.ts`).
A volume's chunks are placed at its origin and turned about the renderer's up axis; a point
`(x, y, z)` of its own frame is the renderer's `(x, z, -y) / 1000` metres, which keeps every face
turned from solid toward air. Each is drawn in the look's `ground.rock` (the surface material
catalog's rock and its grain pattern, or the pack's own surface), else the engine's rock colour,
and its upward faces (within about 44 degrees of level) in the look's ground for its top look
(`ground.grass` for `grass`) where the look has one; rock that takes a top takes no grain pattern,
as every surface that colours its upward faces apart, and a drawing that names no looks draws its
volumes in rock throughout (`wearEach`, `volumeLook` in `style-pack/site-dresser.ts`). Volumes
cast and receive shadows and are counted in the site's triangles and draws. A landscape that
cannot be read does not stop the site: it opens without its volumes and the page keeps the reason.

A world on a volume's top is read the same way and drawn in the site's frame, which stays the
page's. `readSiteTop` (`web/packages/atlas-core/src/site-top.ts`) reads the graded top
(`exulanica.site-top/v1`) held to the digest the site drawing (`exulanica.site-drawing/v6`) names,
and `siteTopHeightMm` gives its height at any point by the server's own triangle rule, so the page
stands slots, people and things where the server's place stands them (pinned by
`tests/fixtures/landform/site-top-conformance.json`). The top is the site's land to every reader
that asks a height, a dry point or its water, with no chunks and no backdrop
(`readSiteTopLand`, `web/packages/atlas-react/src/playcanvas/generated-site/site-land.ts`); it is
drawn as one mesh of the cells its drawing lists in `rock_cells`, 3 mm over the island's rock,
worn in the site's base ground with the land's slope bands. Its rim follows the rock, not the grid:
a cell beside the listed ones draws, as marching squares do, the part of it round its corners on
rock out to points on its edges that lead off the rock, so the edge takes no square bites. Each
point lies where the share of rock round the edge's two ends (each end and its eight neighbours)
crosses one half, between a quarter and three quarters along it, at the height rule's value there,
so a stair of cells draws one sloping edge, not a stair of half points.
Under those cells the island's own upward faces are not drawn, and its rock there is drawn at least
5 cm under the graded top, so its coarser mesh never shows through the land; its faces beyond them that lie within 0.5 m of the graded top, above or below,
inside the top's square, whichever way they face, are drawn with the top in its ground (the same
mesh's material, surface coordinates and bands, a step's side given the ground's up) and not as
rock, so the top is one ground to the rock's edge with no seam; the island's rock draws the rim's
face below and the underside.
Land cover grows only on chunks, so none grows on a top, and no scenery stands beyond it. `readLandscapeDrawing` reads version 2, and the page holds it to the site's top,
landscape and placement; its whole landscape (the volumes and the land below, read from
`landscape/ground` by `readLandscapeGround` and drawn as a site's land is) stands under one root at
the inverse of `site_frame` (`landscapePlacementM`), so the island is where the site stands and
everything else is where the landscape puts it. The slope bands of the top and of the land below
add the island's altitude (`site_frame.at_mm`'s height) to each height, so their heights stay above
the sea. A landscape that cannot be read leaves the island in the sky alone, with the reason kept.

## Sky islands

`exulanica.sky-island/v1` (`exulanica/grammar/islands/document.py`) is a floating island stated as
a closed object in whole millimetres, made into an unchanged `exulanica.volume/v1` document by rule.
Nothing reads a sky island yet: a landscape does not place one.

| Key | Meaning |
| --- | --- |
| `profile`, `id` | The profile and a lowercase key |
| `radius_mm`, `lobes` | The top outline: how far it reaches from its centre (8 to 20 m), and 1 to 5 overlapping lobes |
| `rim_mm` | The rim slab's thickness below the top, at most the radius and half the depth |
| `depth_mm` | How far the underside hangs below the top, at most three times the radius |
| `underside` | `cone` (one leaning keel ending in a blunt toe), `bowl` (a shallow, wide underside) or `spires` (several narrow keels) |
| `fingers` | 0 to 4 thick, blunt rock limbs hanging from the underside |
| `look`, `top_look`, `walk` | As a volume's: `rock` or `wall`; `grass`, `moss`, `rock` or `sand`; `tops` or `none` |
| `erosion`, `strata` | A volume's sections exactly, read by the volume reader against the volume catalog version its island catalog names |
| `top` | From island catalog version 2, optional: the land the top follows, an unchanged `exulanica.landform/v1` document |
| `top_fill_mm` | From island catalog version 3, with a `top` only: how far the rock reaches above the land's highest point for a site's fills, 0 to 4 m, 4 m by default |

Bounds, defaults and words are read from `assets/catalogs/islands/sky-island-value.v1.json`,
`sky-island-value.v2.json` and `sky-island-value.v3.json`, entry-shaped catalogs with a reason and
a licence on every entry, read with the volume value schema.
Version 1 names volume catalog version 2; version 2 keeps every entry of version 1, adds `top`
(`level`, the flat top version 1 makes, or `land`) and names volume catalog version 3, which admits
a top land. Defaults are written in at reading, and the island's identity is the SHA-256 of its
canonical JSON; an island without a top has the same identity and makes the same volume under
either version. A top is read by the land reader against the landform catalog its volume catalog
names and refused by its path under `top`; under version 1 a top is refused as a later version.
Version 3 keeps every entry of version 2, adds `top_fill_mm` and names volume catalog version 3: an
island with a top states it, its default written in, and an island without one may not; an island
without a top has the same identity and volume as under version 2. Under versions 1 and 2 a fill is
refused as a later version. A site, hangings and falls belong to later versions and are refused if
stated.

`make_island_volume` (`exulanica/grammar/islands/maker.py`) turns an island and a seed into a volume
whose id is the island's: a slab whose top overhangs its base and smaller slabs for the further
lobes, blended 1.5 to 2.5 m so their joins crease; the underside's parts; the fingers; and a cap at
height 0, the top outline centred on the origin. Every value is a whole number drawn from SHA-256 of
the seed under the island profile's prefix, one stream for each part, so the same island and seed
make the same volume byte for byte. The rules the maker follows, from looking at volumes drawn in
the application:

- The underside narrows downward and never widens again below the slab: each part's top lies inside
  the slab or the part it hangs from, and each part leans outward going up or tapers faster than it
  leans. A part reaching past the slab's edge below it reads as a skirt or a pot.
- A cone's keel hangs with its top under the slab's centre, inside the slab's base, its base
  radius at least half its toe's width, leaned a few degrees, and ends in a blunt, flattened toe
  block set slightly off its axis and blended into it over 2.5 to 3 m, its corners within the
  foot's radius; two leaning roots and two lumps tilted 18 to 30 degrees sit inside the taper. A
  narrow keel ending in a rounded part reads as a drop or a knob, and so does a toe reaching past
  the keel's foot, which weathering narrows into a neck above it. A small island reads floating with a keel about 1.3 to 1.5 times its top
  width deep.
- A bowl is one wide, upright column rounded at its foot, with the two tilted lumps; spires are
  three to five narrow keels, the first under the slab's centre to the full depth, each ending in
  its own flat foot.
- Fingers are thick, blunt columns, never thin tapering limbs, which read as melted drips. Keel
  and spire feet and finger tops are at least three quarters of the weathering's amplitude and a
  metre in radius wherever the island is wide enough, so weathering does not eat through one and
  leave its end floating.
- The slab reaches above the cap by its rounding and the weathering's amplitude, so the top is level
  at 0 wherever rock lies under it.
- An island that states a top is capped by its land instead of a level: the volume's `top_land` is
  the island's land over the square round the top's discs grown by a tenth, in whole 2 m, its
  datum the top height 0, cut with the cap's blend. The maker realizes that land as the field will,
  makes the island as if its top were level at the land's lowest height (or 0, where the land never
  falls below it), so the rim and the underside hang below the lowest point, and raises the slab and
  the lobes by the land's relief and the island's `top_fill_mm`, so they reach above its highest
  point, and above any fill up to `top_fill_mm` over it, as they reach above a level cap. Under
  island catalog version 2 a raised slab keeps its base and widest radius and leans less, so its
  top outline shrinks; from version 3 it keeps its lean, so the outline at the land's lowest height
  is the one the island states. Every point of the top is then the land, the walkable top climbs it
  where it is no steeper than 1 in 4, and a site graded on it may fill up to `top_fill_mm` and still
  stand on rock that reaches its graded top. A cut gets no extra rock, since a thicker rim would
  change the island's look.

The maker reads the volume under the volume catalog version the island's catalog names, so the
volume reader admits it; it lists at most 16 parts, within the volume catalog's limit. The radius is
held to 20 m and the fingers to four so the costliest island the catalog admits, weathered as
islands read well, realizes at the 2 m cell in about 5 s, within the share one island may take of a
landscape's limit; the catalog's reasons state the measurement. The tests pin the catalog and two
made volumes by digest.

## Refusals

| Code | When |
| --- | --- |
| `volume_invalid` | A volume document, chunk or top breaks its shape or a bound (by path) |
| `volume_part_wrong_op` | A part performs an operation its shape does not, or a cap states a placement |
| `volume_rounding_too_large` | A box's or a column's rounding is larger than its shape allows |
| `volume_too_many_parts` | More parts than the catalog allows |
| `volume_digest_mismatch` | A chunk or top is not the one its digest names |
| `volume_rules_changed` | A chunk, top or receipt names volume rules this server does not serve |
| `volume_top_heights_invalid` | Heights given for a volume's top are not one per point of its top land's square lattice, or the volume states no top land (path `top_land`) |
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
| `stack_invalid` | A sea stack document breaks its shape or a bound (by path) |
| `stack_flank_faces_up` | A trunk's flank away from its lean faces up by more than 1 in 4, its taper and its lean together |
| `stack_arch_too_wide` | A passage wider than the trunk's radius where it passes, or whose round head outgrows its floor depth and rise |
| `stack_arch_too_high` | Less rock over a passage's crown than the passage is wide |
| `stack_arch_below_foot` | A passage's floor less than the weathering and 3 m above the foot |
| `landscape_volumes_overlap` | Two of a new site world's placed volumes are both rock at a sampled point where their reaches meet (by the later placement's path, naming both and the point) |
| `island_invalid` | A sky-island document breaks its shape or a bound, its erosion and strata included (by path) |
| `island_too_deep` | An island's depth is more than three times its radius |
| `island_rim_too_thick` | An island's rim slab is thicker than its radius or half its depth |
| `island_later_version` | An island states a site, hangings or falls, which later versions state, a top under island catalog version 1, or a top fill under versions 1 and 2 |
| `landscape_site_unknown_placement` | A landscape's site names no placement it holds (path `site.on`) |
| `landscape_site_no_top_land` | A landscape's site names a placement whose volume states no top land (path `site.on`) |
| `landscape_site_outside_top` | A site on a volume's top does not lie inside its square, or not at whole metres (path `site.at_mm` in a landscape) |
| `landscape_site_top_has_sea` | A site is graded on a top whose land has a shore |
| `landscape_site_offsite_homes` | A world on a volume's top is asked of a kind whose people come in from homes off the site (path `landscape.site`) |
| `landscape_site_not_on_rock` | A site on a volume's top, grown by 1 m, has no rock 1 m under its natural or graded top somewhere, or a part change would leave it so (path `landscape.site`) |
| `landscape_arrival_not_ground` | The arrival a landscape's surfaces are reached from is not walkable ground |

## Limits

- Pure Python integers: a stack's surface takes about a second at 4 m, a few seconds at 2 m, tens of
  seconds at 1 m and minutes at 0.5 m on one core, so fine levels are for chunks near where people
  stand and every chunk is kept by its digest.
- Surface nets round sharp edges and thin parts under about two cells; a few edges where two sheets
  touch in one cell border four triangles.
- A solid thinner than 250 mm can be stepped over by the top search; tops are of one volume alone,
  and where placed volumes meet, which top is walked is not decided yet.
- Volumes are drawn at one level each, in the look's rock with their upward faces in their top
  look's ground, with no texture yet (the surface material catalog has no moss: a moss top takes
  what the look gives a ground it has no material for, or the rock where it gives none), and are
  not walked by
  people; they stand off a site, or carry it on their top;
  spans, landmark flora and far layers are not part of `exulanica.landscape/v1`.
- A world on a volume's top stands on one volume's top, its people held to the site's rectangle;
  only kinds whose people all live on the site can stand there. Where the island's own top falls
  more than 0.5 m from the graded top before the rock's edge, the island's rock shows there in its
  top look.
  Its landscape drawing realizes the ground below as a site's land is realized, a few seconds more
  than a site on land's.
- Realized chunks and tops are kept in the kind worker's memory with the landscape's drawing, in a
  keep of their own beside the site drawings, not in a store; a world read again after they are
  let go realizes them again.
- A site world on a landscape is made within the kind worker's limit for making one world (15 s,
  `COMPOSE_SECONDS`) without realizing its volumes. Its landscape's drawing is made when first read,
  within a request's wait for it (40 s, `LANDSCAPE_SECONDS`); a drawing past that is answered
  `kind_work_overran` and read once finished, and one still running past the worker's stuck bound
  (160 s) has its process replaced at the next request, so that bound limits how much rock one
  world can show.
- A world made from a person's words never stands on a landscape: no world tool names one.
