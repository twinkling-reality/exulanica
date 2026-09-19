# What holds a component up, and what 322 was a count of

The composed corridor run scored `noCutsOrFloatingGeometry` FALSE on
`componentsDetachedFromSupport` 322, against 773 on the same tile drawn alone, and against a
committed prediction of 2,000 to 2,500. This measures why, on the run's own containers.

Measured on `lane/what-holds-a-component-up` off main `15e8198c`, tessellator source version 20.

## The prediction, found and quoted

It is one line, in this directory, added by commit `05312991` and reading in full:

    componentsDetachedFromSupport   was 773 on one tile; PREDICT 2,000 to 2,500, about three times

So the prediction is a SCALING ARGUMENT AND NOTHING ELSE: one tile gave 773, four tiles are about
three times as much drawing, so about three times as many. It names no mechanism, and the section
around it names the fields every other key is decided by.

**Its arithmetic was right and its subject was wrong.** What scaled by about three was the
POPULATION, not the detached part of it:

| run | components | supportComponents | detached | detachedTriangles | drawnTriangles | walking |
| --- | --- | --- | --- | --- | --- | --- |
| fixture, run 5 | 62 | 0 | 62 | 2,208 | 2,208 | 819 |
| fixture, run 6, openings cut | 62 | 0 | 62 | 4,042 | 4,042 | 819 |
| scored, one tile | 774 | 1 | 773 | 56,356 | 56,388 | 1,727 |
| scored, four tiles composed | 2,243 | 3 | **322** | 11,896 | 175,034 | 7,799 |
| Flatiron owned district | 11,382 | 44 | 9,323 | 19,244 | 63,730 | 23,993 |

Components went 774 to 2,243, which is 2.90 times, and **2,243 falls inside the predicted 2,000 to
2,500.** The prediction would have been very nearly exact had it been a prediction of `components`.

What it carried forward unexamined is the ratio. On one tile, 773 of 774 components were detached,
which is 99.87 per cent, and `detachedTriangles` 56,356 of `drawnTriangles` 56,388 is 99.94 per
cent: EVERYTHING WAS DETACHED, the same degenerate signature the fixture had at 62 of 62 with
`supportComponents` 0. Predicting "three times as many detached" is that ratio held fixed. On the
composed world the ratio is 322 of 2,243, 14.4 per cent, which is the first time a generated target
has produced the kind of partial figure this key exists to produce.

**So the answer to "which of the three is it" is the first, with a correction.** The prediction was
right about the quantity it actually computed and wrong about which population that quantity
belonged to. It is not the third possibility: the change did nothing nobody expected. What nobody
had is a model of the key in which the count can fall while the world grows, and that model is
below.

## The key still counts what it counted, and the population grew

    components         774  ->  2,243        2.90 times
    drawnTriangles  56,388  -> 175,034       3.10 times

Nothing narrowed. The check was applied to three times as much geometry and returned a smaller
number, so 773 to 322 is not an artefact of a shrinking population.

**But two of that key's four inputs cannot fire on a generated target at all**, which is worth
saying beside its verdict. `noCutsOrFloatingGeometry` is decided by four fields being zero, and the
run records `ringEdges` 0, because the gate hands a generated target no obstacle prisms. With no
prisms there can be no `ringEdgesWithoutDrawnFacade` and no `trianglesInsideBuildings`, and
`routeSupportGapSamples` was 0. On a generated target this is a ONE NUMBER KEY, and that number is
the one below.

## The world, rebaked offline, byte for byte

The run was against a private store that no longer exists. The corridor is generated from its
specification in code, so it was regenerated and rebaked here with no database at all, and all four
containers came back identical to the ones the scored run binds:

    tile-0-0     2,481,768 bytes  21b31c9f9ab9904104a319ddee8aaa5ea87f9cb361da39a793c48a123d0dace9
    tile-1-0    12,294,448 bytes  7ef4d85c1413f4cc0e6ac289a9e23634896658d2dc8ddf322f4f890c64029507
    tile-2-0    12,682,860 bytes  ed9acb98268d80fc7b0bf856b682c95c15f59e50bf9c70aef1c2258cd713e999
    tile-3-0    11,630,744 bytes  47e6457e74812f8f84f923a222bf70966cf26b8a513ebc1e86f02233fe61818c

Four of four are bound by `docs/evaluation/2026-09-19-corridor-composed-world-private-store.json`.
Every digest above was read from the file it names in the same command that compared it.

**How, so this is repeatable.** `scripts/bake_corridor_tiles.py` needs a database and a data
directory only for its RECORDING half. Its generating half, `load_city_catalogs`, `generate_city`,
`city_records` and `tile_document` over `CORRIDOR_TILES`, and its baking half, the tessellator's own
`bake` through `web/packages/loom-tess/src/node/cli.ts`, both run before it opens a connection and
need neither. Running those two and stopping there writes the four containers above. The
measurement then decodes them, groups each tile's drawn entries by the texture set their surfaces
cite, composes the four `nav_envelope` projections with `composedSupport`, and calls the gate's own
`components`, `classify` and `integrity`. It is the shipped code throughout; the only thing written
for this was the grouping the renderer would otherwise do.

## THE NUMBER IS PARTLY A PROPERTY OF THE ARITHMETIC

Recomputing the measurement on those containers, through `composedSupport` and `integrity`
themselves rather than a second reader, reproduces the geometry exactly and the count only roughly:

| vertices held as | supportComponents | detached | detachedTriangles | walkingTriangles |
| --- | --- | --- | --- | --- |
| float64, the container exactly | 3 | **490** | 18,872 | 7,798 |
| float32, as the renderer holds them | 3 | **351** | 13,048 | **7,799** |
| float32 of the coordinate less `renderOrigin` | 4 | **586** | 22,156 | 7,799 |
| what the page measured | 3 | **322** | 11,896 | 7,799 |

`drawnTriangles` is 175,034 and `components` is 2,243 in every row, matching the run, and all 56
meshes match the run's per-mesh triangle counts by name. All twelve components the run lists as
detached are found in the recomputation by their exact lowest point.

**The harness reads `new Float32Array(...)` from the renderer's own vertex buffer.** So the triangles
the gate measures are not the container's integers, they are those integers after a round trip
through single precision, which at 300 m is about 0.03 mm. Quantising to float32 moves the count
from 490 to 351 and fixes `walkingTriangles` on the nose. The residual 351 against 322 is the part
of the renderer's arithmetic this model does not reproduce: its actual world matrix and local
origin, which are not in the record. The middle row is not offered as the truth; it is offered as
evidence that A THIRD OF THIS NUMBER IS DECIDED BY ROUNDING, and the third row shows a differently
plausible model of the same arithmetic giving 586.

**Why it is that sensitive** is in the next section, and it is not a general fact about the check.

## The 351, classified

Every detached component was taken from the measurement itself, by lifting its twelve-example cap
for the analysis only, so the set classified is the set `integrity` counted and not a second
reader's re-derivation. Counts are of the recomputation's 351; the run's 322 has the same three
populations and the same three record kinds.

### 251 are shop vitrines standing exactly the contact tolerance off their own facade

    city.vitrine                              251 components, 9,272 triangles
    nearest REACHED geometry                  city.facade, in all 251
    distance to it                            min 50.000 mm, median 50.018 mm, max 260.010 mm
    the navigation envelope under them        answers for 0 of 251
    lowest vertex above the datum             560 to 1,940 mm

`THRESHOLDS.contactToleranceMm` is **50**. The gap between a vitrine and the facade it belongs to is
**50**. The measured spread, 49.988 to 50.018 mm, is a single float32 step at these coordinates.

  A TOLERANCE THAT EQUALS THE CLEARANCE IT IS TESTING DECIDES NOTHING. It reports which side of an
  exact tie the last bit of a float32 fell on.

128 of the 351 sit within 0.1 mm of that 50.000 mm threshold, at three distinct distances: 50.000,
50.003 and 50.018 mm. That is the whole of the 490 against 351 against 322 spread above.

**And the coincidence is not one.** `exulanica/grammar/grammars/city/generation/streets.py` states
it in a named constant:

    #: The module every street dimension this stage derives is a multiple of.
    DIMENSION_MODULE_MM: Final = 50

THE CITY IS DIMENSIONED ON A 50 MM MODULE. So the smallest gap the generator can put between two
parts is 50 mm, which makes 50 mm the commonest gap in the world, and the gate tests contact at
exactly 50 mm. This is not a quirk of vitrines and it will recur wherever two parts sit one module
apart. Neither number appears as a literal in the tessellator core or in the city grammar table,
which is why nothing connected them before: the token 50 occurs nowhere in either.

**This is the check, not a fault.** Nothing is floating: the vitrines are fitted where the generator
puts them, one module off the facade.

### 82 are objects on roofs, and the rule asks for ground under them

    city.rooftop_object                       82 components, 3,690 triangles
    lowest vertex above the datum             14,735 to 32,996 mm, median 22,408 mm
    nearest REACHED geometry                  another rooftop object (78) or the massing (4)
    distance to it                            215 mm to 4,003 mm
    the navigation envelope under them        answers for 0 of 82

A component becomes a support root only if the product's NAVIGATION SURFACE answers within 50 mm of
its lowest vertex. The navigation surface is the walkable envelope, which is ground. A thing 22 m up
on a roof will never satisfy that, and should not be expected to. It reaches support only by
touching something that does, and a rooftop object 215 mm clear of the roof touches nothing.

**This is the check.** The rule has no notion of standing on a roof.

### 18 are terrain slivers, and these are the only geometry question

    city.terrain                              18 components, 86 triangles
    lowest vertex above the datum             0 mm, all of them
    nearest REACHED geometry                  city.curb_edge, 97 to 222 mm
    the navigation envelope under them        answers for 10 of 18, and in all ten the envelope is
                                              97 to 212 mm ABOVE the component
    by tile                                   6 each on (1,0), (0,0) and (3,0), none on (2,0)

Six per tile on exactly the three tiles that were not the scored one. They are 86 triangles in all,
they lie on the datum, and the nearest thing the gate reached is a kerb edge a hundred millimetres
or two away. This is the population worth looking at as geometry, and it is 18 of 322.

### Nothing is floating over ground that holds it

No component in the 351 has the envelope answering BELOW it. The ten where the envelope answers at
all are terrain pieces sitting 97 to 212 mm UNDER the surface, not above it.

  OF 322, NONE IS THE THING THE KEY'S NAME DESCRIBES. 333 of the 351 recomputed here are the check
  asking a question the geometry cannot answer, and 18 are slivers of ground.

## Why composition more than halved it, stated as a mechanism

Drawing the neighbours added no support roots worth the name: `supportComponents` went 1 to 3. What
it added was ADJACENCY. Detachment is reachability over a graph whose edges are "within 50 mm of",
so every triangle drawn is a potential edge, and a component that continued into a tile nobody drew
had nothing on that side to touch. The count fell because the graph got better connected, not
because anything was repaired, and the lane that measured it said so and labelled its reading
fitted. It is now measured: components did not move, edges did.

  DRAWING MORE OF THE WORLD LOWERS THIS NUMBER WITHOUT CHANGING THE WORLD. It is not a quality
  measure of a tile; it is a measure of a tile and everything that happened to be loaded beside it.

## What the tests now hold

`web/packages/loom-gate/test/support-reachability.test.ts`, six tests:

- a genuinely floating component raises the count by exactly one, against a baseline already at one,
  and `detachedByMesh` names both, so a rise of one cannot be a substitution;
- one component spanning two meshes is counted once and named twice, which is why `detachedByMesh`
  totals 339 where the run counted 322;
- a component supported only by a neighbouring tile is NOT detached while that neighbour is drawn,
  and IS detached when it is not, on identical geometry with identical support answers. That is the
  composition question decided, and the current behaviour is the right one;
- one refused support sample, at the single plan point the root rule asks about, detaches a ground
  plane that is otherwise entirely walkable, and carries that to everything standing on it.

The last two were break tested: reverting the root rule's null check makes exactly those two fail
and **leaves all ten existing `scene.test.ts` tests passing**, so nothing before now exercised the
refused-sample branch. `web/packages/loom-gate/src/scene.ts` was restored afterwards and its digest
re-read: `9366119258eabcb86ba848381fcaac68ee19d6ba098e61ad000d36c1e355e8e7`.

## What is not changed here, and why

Nothing in the measurement. Every repair worth making moves the gate's headline number:

1. **The root rule probes one plan point per component,** its lowest vertex, and believes a refusal.
   A component's lowest vertex is the worst available probe for a component that is not a ground
   plane, and for a rooftop object it is meaningless.
2. **The contact tolerance equals the module the world is dimensioned on,** 50 mm against
   `DIMENSION_MODULE_MM`, so 128 components are decided by the renderer's last bit. Whichever way
   this is settled, the two numbers should not be equal and neither should be chosen without
   knowing about the other.
3. **The measurement names twelve of its detached components.** Classifying 322 required patching
   that cap three times. A key whose verdict is one number should be able to say which things it
   counted.

The third is additive and changes no verdict, but it would put a long array into every record, so it
is a shape decision rather than a lane's. The first two change what the gate says. All three are
recorded for the orchestrator and none is taken.
