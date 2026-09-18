# Facade openings stage 1, and what the navigation envelope turned out to be doing

Measured 2026-09-18. Prediction written first, in `2026-09-18-facade-openings-prediction.md`, before
any digest was read. Every figure here was produced on the tree named beside it.

## The tree

Branch `lane/tess-support-carve-wip`, based on local main `ead159a3`. The tessellator 17 figures were
produced from a `git archive` of main run through the same pipeline, so the before and after are two
measurements rather than one measurement and one pin.

## The scope, re-measured from the documents rather than inherited

Generated from `exulanica.grammar.grammars.city.generation.corridor`, counting an opening as the sum
over grids of bays times listed storeys, which is what the grammar's own repeat rule means.

    whole corridor city, 6,566 records   512 facades, 151 opening grids, 2,652 openings,
                                         38 grids with an arch (707 arched openings),
                                         123 string courses, 73 cornice boxes, 228 entrances,
                                         151 interior backings, 228 door panels
    corridor tile (2,0) owned, 2,073     168 facades, 51 grids, 916 openings,
                                         9 grids with an arch (182 arched openings),
                                         43 string courses, 24 cornice boxes, 75 entrances,
                                         51 interior backings, 75 door panels

Both populations are recorded because the brief named figures from each as though they were one set.

Two claims checked rather than repeated. Every face with openings and every face with mouldings has
a `trim` material record: 151 of 151 and 125 of 125 city wide, their union 166, which is exactly the
number of trim dressings, and no trim dressing belongs to a face with neither. And all 75 entrances
on the corridor tile are the SAME rectangle as a door panel in their own bay, agreeing on centre,
width, height and recess, 75 of 75 with zero partial matches.

## What moved, against what was predicted

Predicted before baking: `render_batch` moves, `nav_envelope` does not, because the grammar's
navigation table gives `city.facade` ground `none` and `tessellate.ts` gathers coverings by that row
rather than by a surface's orientation.

    conformance fixture      17                     18
    bytes                    564,788                701,276
    container                1ef74efa               3a2fd58d
    render_batch             e906150d               15129ce5      MOVED
    nav_envelope             dcd548bd               dcd548bd      unchanged
    tile_inputs_digest       5dd2dcb5               5dd2dcb5      unchanged

    corridor tile (2,0)      17                     18
    bytes                    11,153,540             12,602,292
    container                93df0715f5             e01ffe0e51
    render_batch             91350a9045             b5a1af14b8    MOVED
    nav_envelope             35388d7849             35388d7849    unchanged
    tile_inputs_digest       2ab27821               2ab27821      unchanged

The 17 row of the corridor reproduces the corridor lane's own digest table exactly, which is the
control that makes the 18 row mean anything.

FIFTY TRIANGLES OF NO AREA REACHED A CONTAINER BEFORE THIS WAS RIGHT, and 1,650 on the corridor
tile. The carve keeps the points along a walk's edges so that neighbours meet vertex to vertex, so a
walk has runs of collinear points; the first version of `walkOn` cut a walk into a FAN from one
corner, which turns every such run into a triangle with no area. A triangle with no area has no
normal, and `pnpm run check` failed with "A surface batch holds a value that is not finite" in the
tile runtime. Every other caller of the carve already cut its walks with the ring rule; this one now
does too, and the triangle counts are identical either way, 4,042 and 55,338.

An earlier pair of digests for that fanned version is not recorded here, because nothing should be
able to cite them. What is worth recording is that the corridor container was 12,602,292 bytes
BEFORE AND AFTER the fix, identical to the byte, while its container digest moved from 01890c42 to
e01ffe0e and its render digest from 0fc066d4 to b5a1af14. A length is not an identity.

## Bake time

Through the machine-wide slot, two passes each, both clocks. Both passes of each version wrote
byte-identical containers.

    17   wall 17.22 / 17.13 s   cpu 18.26 / 18.14   load 16.2 falling to 11.9
    18   wall 18.19 / 17.98 s   cpu 19.27 / 19.07   load 14.4 falling to 10.8

Carving 51 faces on that tile costs about one second, five per cent. The question was recorded
before the run rather than a number predicted, because there was no basis for one. An earlier pair
at 16.78 and 17.74 s of wall, taken before the degenerate triangles were fixed, agreed to within a
second; the pair above is the one to quote, because it was measured on the code that shipped.

An earlier pair taken under load 24 to 29 read 33.24 s and 48.23 s of wall against 25.53 and 28.25
of cpu, ratios 1.30 and 1.71. Kept here because the wall figures are useless and the ratios say so.

## The dimensions the rule reads, for the coordinate quantum question

From the records, over the 151 grids: `reveal_depth_mm` 120 to 250, `sill_projection_mm` 0 to 150,
`sill_thickness_mm` 0 to 199, `head_rise_mm` 0 to 772 over widths 613 to 2,083. Nothing a record
states is under 100 mm. The shallowest arch is a rise of 5 mm over a width of 758 mm, whose whole
span holds at most five distinct integer heights.

WHAT THE ARCH RULE DERIVES, measured over all 38 arched heads in the city rather than reasoned
about. Segment counts chosen: 2 twice, 4 twice, 8 eleven times, 16 sixteen times, 32 seven times.

    width  rise  radius   segments  shortest chord  smallest step in u  in z
     1258     8   24731          2          629.05                 629     8
      758     5   14366          2          379.03                 379     5
     1552    25   12056          4          387.42                 387     7
      613    56     866          8           77.79                  74     4
     2026   165    3192         16          127.78                 122     3
      982   465     491         16           92.36                  13     9
     1541   658     780         32           68.25                  13     4
     1056   516     528         32           50.09                   3     3

    shortest chord anywhere in the corpus   50.090 mm
    smallest step on either axis anywhere    3 mm, on the steepest head, 1056 wide rising 516

So nothing this rule derives is smaller than 3 mm, and no chord is shorter than 50 mm. The two
shallowest heads are drawn as TWO straight chords meeting at the crown, because a chord of half the
span sits 1.25 mm from the circle and the tolerance is the projection's 1 mm resolution plus the
2 mm the flooring of a point to millimetres is allowed. That is a consequence of the millimetre
rather than of the rule: a 5 mm bulge over 758 mm has no smoother integer form.

The record-stated dimensions are all above 100 mm; the derived ones reach 3 mm; nothing reaches the
fraction of a millimetre where a quantum of 1 mm would misstate rather than coarsen.

## The navigation envelope, which is where the day went

The visual gate's walk stopped on the conformance fixture at 52.795 m and could not pass. Three
explanations were reached honestly from real measurements and two of them died.

MEASURED, on the container the page serves, `1ef74efa`:

- The mesh has NO interior gap narrower than a clearance arc can be. Every line of constant x and
  constant y at 1 mm, solved from each triangle's edges: 1,824 gaps, narrowest 50 to 60 mm, every
  one between two triangles of a single curb record, with a width distribution that is the chord
  distribution of a disk of the capsule's own 340 mm radius. That is the clearance carve working.
- The walk leaves the OUTLINE rather than falling into a hole. From the middle of the uncovered run,
  perpendicular to the walk: ground at 1.0 mm on one side, nothing within 200 mm on the other. A
  hole has ground on both sides.
- The outline there is the capsule clearance arc around a BENCH, `city.street_furniture` at
  (38000, 46250), whose four box parts give a footprint of (37100, 46020) to (38900, 46475).
  Distances from its nearest corner, against a capsule radius of 340 mm:

        mesh boundary vertices      344.530  344.308  343.535  344.193  344.061
        the chords between them     343.971  343.565  343.432  343.717
        last supported before       343.470
        first unsupported           343.466
        last unsupported            343.930
        first supported after       343.936
        where the walker rested     344.108

  The walk and the boundary occupy the same band. The walk has 3.47 mm of true clearance to spare
  and is refused because the integer clearance carve reaches 3.4 to 4.5 mm past the true disk, which
  `ring-clearance.ts` states in its own header that it does, bounded at five.

So the carve is behaving as documented and there is nothing here to fix in it. What is worth
recording is that the gate's route rule qualifies a heading at 340 mm from a ring while the carve
removes support to 344.5 mm, so a path whose closest approach falls in that band qualifies and has
no ground under it. Narrowing the overshoot narrows the band and cannot close it.

## A retraction, kept because a clean result reads as if it went smoothly

An earlier version of the gap scan reported 79 narrow interior gaps in the corridor tile, up to
56 mm, recurring at fixed y across many x, eleven of them on street segments. IT WAS AN ARTEFACT AND
ALL OF IT WAS WRONG. A scan line running along a ragged boundary reads as covered, uncovered,
covered, because the boundary juts past the line in two places and falls back between them; the
uncovered part is outside the surface rather than missing from it. The widest sat at exactly one
value of x between two 1 mm slivers, with no gap at all one millimetre either way.

It was caught by going to look at the widest one rather than at the class, and drawing the coverage
of the plane at 1 mm there: a clean edge with solid ground behind it.

A SECOND DISCARDED FILTER, for the same reason. The first attempt at separating a graze from a gap
asked whether the plane was covered one millimetre to either side of the gap's midpoint. That point
is inside a clearance hole of the capsule's radius, so the filter deleted all 1,824 real holes. It
was caught by the count going to zero, which a clearance carve cannot do, and not by reading it.

The filter that stands requires a gap to PERSIST: an overlapping gap on a neighbouring line. Three
controls, in both directions: it keeps 1,824 real clearance holes, it keeps 71 gaps planted by
moving one triangle 32 mm aside including eight under 10 mm, and it destroys all 79 grazes.

## The one real crack, recorded and left alone

Corridor tile (2,0), scanned at 1 mm: 715 narrow single-line gaps, 46 with area. All 46 are under
one millimetre wide, the widest 0.6557 mm, all between triangles 596 and 25852/25853 of one record,
`city.curb_edge#26`, along y 111,091 to 111,100 at x about 4,204. So they are 46 crossings of one
crack about 10 mm long and two thirds of a millimetre wide.

It cannot be the cause of anything the gate has seen. What it is: proof that this carve can produce
a crack at all, measured, with a location.

## Four module headers that had become false

`ring-clearance.ts`, `ring-triangulation.ts`, `streets.ts` and `fillet-arc.ts` each said "Not yet
wired into a bake. It changes no container until an expander calls it." All four were imported and
reaching containers; `ring-triangulation.ts` by eight modules including the tessellator itself. Each
sentence was true when written and became false when somebody else wired the module up.

The four no longer make the claim. `facing.ts` keeps it, because it is still true, and
`test/core-headers.test.ts` now reads the import graph and fails if a module claiming to be unwired
is imported by anything in core. That test was broken on purpose before being trusted: planting the
sentence in `streets.ts` failed it naming streets.ts and expand.ts.

## The development golden's pinned counts, and one field whose name was checked rather than assumed

Moving the golden moved seven pinned values in `packages/atlas-react/test/generated-tile-runtime.test.ts`,
which belongs to a lane that is closed. The orchestrator asked for the edit to be made here and in
its own commit. Every value is derived from the rebaked golden, container `3a2fd58d`:

    city.facade's triangle range     368 to 482      becomes  368 to 2316
    every range after it             shifts by 1,834, no kind or order changes
    terrain firstVertex              3419            becomes  6961
    terrain firstTriangle            1401            becomes  3235
    terrain vertexCount 478 and triangleCount 495 do NOT move: only its offset in a shared buffer did
    render triangles                 2,208           becomes  4,042
    render vertices                  4,833           becomes  8,375
    unavailableSurfaces              118             becomes  124

THE LAST OF THOSE WAS FLAGGED RATHER THAN WRITTEN, because 124 is also the number of DRAWN surfaces
and a metric that equals the drawn count may be a metric that is not measuring what its name says.
Measured through the runtime's own loader, on the fixture, with the same stub the test uses:

    drawn surfaces   124
    textured           0
    unavailable      124, of which 20 say no surface_material record dresses them and 104 say a
                     texture set could not be read

So the field is correctly named and 124 is right. The equality with the drawn count is an artefact
of THE TEST rather than of the fixture: it passes a `fetchSet` that throws, so no set is ever
prepared and every surface carrying a material reference is unavailable for that reason. The
fixture's sets are real published ones. A run that fetched them would report a smaller number, and
anybody reading 124 as "how much of this tile has no material" would be wrong by a factor of six.

## A picture, predicted before the server started

Written before any frame was captured, so it can be wrong. The route is the app's development
preview, `?preview=1&tile=tile-conformance`, which serves the golden rebaked at tessellator 18,
container `3a2fd58d`.

WHAT THE FIXTURE STATES, counted from its records and not from the picture: nine facades, six of
which carry an opening grid, 38 openings in all, 26 of them with an arched head rising 250 mm over
a 1,200 mm width and 12 with a flat head. The six gridded faces belong to ONE building, whose tier
0 ring runs (41050, 48950) to (53050, 62950) and whose tier 1 sits above part of it.

THE PREDICTION.

1. Holes are visible. At least one face shows a row of openings cut through it, and above a ground
   band rather than in it, since the grammar puts every opening on an upper storey.
2. An arched head is distinguishable from a flat one. Four of the six gridded faces state
   `head_treatment` arch with a 250 mm rise, which at a 1,200 mm width is a segmental curve of
   about 845 mm radius drawn in 8 chords. If every head looks flat, either the arch rule is not
   reaching the container or the rise is too small to see at this distance, and I will say which.
3. A reveal is visible as a returned edge, 180 mm deep on every grid in this fixture, so an
   opening should read as a hole in a wall with thickness rather than as a dark rectangle.
4. Through the holes, on the four faces that have one, an INTERIOR BACKING should close the view
   rather than the far side of the building. The fixture states six.
5. THE SURFACES SHOULD DRAW TEXTURED, not as unavailable. The 104 unavailable surfaces I measured
   this afternoon came from the TEST's `fetchSet` stub, which throws; the development page is a
   different caller and fetches its sets over HTTP. So I expect the page to report a non-zero
   `decodedTextureBytes` and far fewer than 124 unavailable surfaces, and I expect the trim
   returns to be dressed on four of the six faces and undressed on two, which is what the fixture
   states.

WHAT A PICTURE OF THIS CANNOT SHOW, decided now rather than after looking: it is the CONFORMANCE
FIXTURE and not the corridor street. It can prove the holes are drawn. It cannot say whether they
look right, which is a judgement, and it says nothing about the corridor beyond the fact that the
two tiles are cut by one rule.

### What the frame showed, looked at rather than inferred

Captured from the development preview at `?preview=1&tile=tile-conformance`, container `3a2fd58d`,
which the page names on screen. Five of five predictions hold.

1. HOLES ARE CUT. The dark brick face shows three rows of openings through the wall, above the
   ground band and not in it.
2. THE ARCHED HEADS ARE ARCHES. Every opening on that face has a visibly rounded top. A flat head
   would have been indistinguishable from a rectangle and was the failure this predicted.
3. THE REVEALS ARE VISIBLE. Each opening carries a pale return at its head and side, catching light
   differently from the face, so a hole reads as cut through a wall with thickness.
4. THE BACKING CLOSES THE VIEW. What shows through each opening is the interior backing, and it is
   MAGENTA because nothing dresses it, which the fixture states and this package's pinned undressed
   set records as `("city.interior_backing", "wall"): 6`. Not the sky, and not the far side of the
   building, which is what a face without openings and without backings would have shown.
5. THE SURFACES DRAW TEXTURED. The page reports 20 surfaces drawn as unavailable, not 124. So the
   development page does fetch its sets, the 104 I measured were the test stub's, and the brick,
   the roof and the parapets draw with their published materials. The 20 are exactly the pinned
   undressed set of this fixture.

WHAT THIS FRAME IS NOT. It is the conformance fixture and not the corridor street. It shows that
the holes are drawn; it says nothing about whether they look right, which is a judgement and not
this lane's to make. The magenta is the runtime saying a surface has no material record, not a
colour anybody chose.
