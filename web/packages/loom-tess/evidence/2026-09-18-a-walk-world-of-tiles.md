# A walk's world is more than one tile, and what that costs

Written 2026-09-18 by the tess lane. Every number here is measured from the five corridor containers
in the store at tessellator 19, or from the code by path, and the prediction was registered with the
orchestrator before the composition existed.

## Why one tile cannot hold a route

    a tile is                        128,000 mm across   (city.tile `tile_size_mm`)
    the route rule asks for          125,000 mm          (loom-gate/src/keys.ts `routeLengthMm`)
    plus a stopping margin of          6,000 mm          (loom-gate/src/route.ts `stopMarginMm`)

So an east-west route can never have ground for its whole length inside one tile, whatever pose is
chosen. This is not a hole in a street. It is the end of the loaded world.

## The composed world is walkable past the edge and not drawn past it

**THE COMPOSED WORLD IS WALKABLE PAST THE EDGE AND NOT DRAWN PAST IT, AND THE ENDPOINT FRAME IS
THEREFORE NOT JUDGEABLE.** Only the neighbours' `nav_envelope` projections are composed. Nothing of a
neighbour's `render_batch` is loaded, so a camera at the end of a route looks east at ground it can
stand on and at no street at all. A person scoring that frame would be answering a question about the
edge of the loaded world while believing they were answering one about a city. Drawing the neighbour
is a separate piece, it costs 5,064,464 bytes for tile (3,0), and it must exist before any capture is
put to a judge.

## The frame was already one frame

Tile coordinates are absolute city millimetres, not tile local. The five terrains:

    (0,0)        0 to 128,000        (1,0)  128,000 to 256,000       (2,0)  256,000 to 384,000
    (3,0)  384,000 to 512,000        (4,0)  512,000 to 640,000

They abut exactly, no gap and no overlap, 640,000 mm of continuous ground. There is no transform to
agree and no offset to negotiate. This was the part expected to be hard and it does not exist.

## The halo was already there, and drawing it would have been wrong

`halo_radius_mm` is 64,000 and tile (2,0) carries 2,073 owned records against 2,076 HALO records,
which is why its header is 4,721,551 bytes of which 4,034,820 is the records list. In both
projections every one of those 2,076 has state `halo`: carried, never tessellated. That is exactly
why the ground stops at 384,000, since `nav_envelope`'s ten drawn entries are six curb_edges, three
street_segments and ONE terrain whose extent is the tile square.

Drawing them would need no fetch at all and would clear the route length. It was refused. It moves
every `nav_envelope` digest and needs every tile rebaked, and worse, it would put the same ground in
the world twice, the neighbour's halo copy and the neighbour's own owned copy, with two supports at
one plan point and nothing to say which is the answer. **Halo exists so a tile can know its
neighbours in order to carve against them, not in order to draw them.**

## The seam is not a special place

Step across a line, sampled 2 mm either side, 250 mm apart, measured the same way in four places:

| Where | stations | largest step | mean | over 1 mm |
| --- | ---: | ---: | ---: | ---: |
| The seam x 384,000, composed union of (2,0) and (3,0) | 513 | **49.000 mm** | 10.16 | 126 |
| Inside (2,0): its terrain meets its own street | 189 | **192.987 mm** | 18.48 | 69 |
| Inside (2,0): the street's other end | 189 | 192.987 mm | 18.48 | 69 |
| Inside (2,0): open ground, nothing joins | 189 | **0.000 mm** | 0.0000 | 0 |

A join inside one tile steps four times as far as the seam does, and the gate's own step limit is
180 mm (`THRESHOLDS.stepHeightMm`), which the INSIDE join exceeds and the seam does not. The last row
is the control: the instrument can return zero, so a reading that is not zero means something.

A first version of this measurement read 207.000 mm at the seam and was wrong. It compared the west
tile's view at x 383,999 with the east tile's at x 384,001, which is two tiles' partial views and not
the composed world: each tile draws only what it owns, so the west tile's curb overhanging its own
edge was being compared against the east tile's bare ground under it. 207 was recognisable as a curb
height from the extents, which is the only reason it was caught.

## What it costs

    tile      container      header      render    nav bin   nav tris
    (0,0)     2,481,736   1,524,741     736,784    220,200      7,122
    (1,0)    12,294,368   3,963,499   4,753,576  3,577,272    121,530
    (2,0)    12,682,828   4,721,551   5,115,376  2,845,884     96,745
    (3,0)    11,630,504   3,775,523   5,064,464  2,790,504     94,890
    (4,0)     2,291,492   1,409,798     676,892    204,792      6,506
    totals   41,380,928  15,395,112  16,347,092  9,638,652    326,793

The walk crosses one edge, so what it needs is tile (3,0)'s navigation:

    (3,0) whole container                        11,630,504
      nav binary, all three sections              2,790,504
      position_mm and index only                  1,964,592
      plus a slim nav header, 19 drawn entries    1,969,322

1,969,322 against 11,630,504 is 5.9 times smaller and 17 percent of the container. The float
`position` section need not be sent: its contract says it is `fround((mm - origin_mm) / 1000)`, and
checked over all 206,478 float components of (3,0), ZERO differ. The slim header is 4,730 bytes
because a nav projection has 19 drawn entries out of 3,301; the other 3,282 say why nothing is drawn
and a neighbour's walk does not need them.

## The prediction, and the one part of it that missed

Registered before the composition existed: every container digest holds, every triangle digest holds,
and the composed nav triangle count equals the arithmetic sum of its tiles. The count is the half
that can fail, because a held digest passes if nothing is composed at all.

    PREDICTED  stated 96,745 + 94,890 = 191,635, walkable the same, extent x 250,000 to 512,000
    MEASURED   stated 96,745 + 94,890 = 191,635
               walkable 96,745 + 94,890 = 191,635
               composed == (2,0) alone + (3,0) alone: true
               extent x 250,000 to 530,000

**The extent missed and the reason is that the prediction was about the wrong thing.** 512,000 is tile
(3,0)'s TERRAIN edge; 530,000 is its envelope's, because its curbs overhang 18,000 mm past its own
square, as (2,0)'s overhang 6,000 mm past its. A tile's records are not bounded by its tile.

Ground across the seam, through the runtime's own code, in metres:

    y  15,500   west alone: 0.207 / 0.207    composed: 0.207 / 0.207     (a curb already overhung)
    y  64,000   west alone: 0     / null     composed: 0     / -0.033    (this is the piece working)
    y 115,250   west alone: 0     / null     composed: 0     / -0.049

## What is not done

- No neighbour is FETCHED by anything yet: `loadGeneratedTile` accepts neighbour containers and
  verifies them, and choosing which tiles to ask the store for is not written.
- Nothing serves a container's nav sections separately, so the 1,969,322 above is a measurement of
  what a slice would cost and not of a slice anybody can request today.
- No neighbour is drawn, per the statement above.
- The full web check has NOT been run: the gate held the machine. What was run is
  `packages/atlas-react/test/generated-tile-runtime.test.ts`, 32 passed, and the package typecheck,
  with a deliberate type error confirming the checker looked at the changed file.
