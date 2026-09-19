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

**THE CATCH WAS LUCK WEARING THE CLOTHES OF A CHECK.** Nothing in the measurement would have
disagreed with the wrong reading; a number happened to be recognisable to somebody who had printed a
different table an hour before. A measurement whose only defence is that its author remembers a
number is not defended. What defends this one is the control row, open ground with nothing joining
reading 0.000 mm over 189 stations, which was added afterwards and is the reason the 49 mm means
anything.

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

## Which tiles are fetched, and what that costs on the real corridor

`walkWorldTiles` takes the list the route serves and the walk's start, and returns the tile the walk
stands on, the tiles within the route's own reach, and EVERY SQUARE WITHIN REACH THE WORLD HAS NO
GROUND FOR. The squares are enumerated rather than inferred from a shorter list, and the two kinds of
absence are kept apart: `no_row` means the store knows nothing about that square, and any other
reason is the row's own state, such as a bake fault. That is the difference between "the city is that
size" and "the bake of that tile failed", and a walk must not read one as the other.

From the gate's start at x 256,000 on tile (2,0), with reach 131,000:

    stands on   (2,0)
    neighbours  (1,0) at 0 mm, then (0,0) and (3,0) at 128,000, the tie broken by row then column
    absent      (1,-1) (2,-1) (1,1) (2,1), all `no_row`: THE CORRIDOR IS ONE ROW

WHOLE CONTAINERS ARE FETCHED, by decision, because nothing serves a container's sections and the
route supports no ranges. The slim slice stays a measured proposal: 1,969,322 bytes against
11,630,504 is a sixth of the transfer, and it needs its own contract and its own tests.

**THE REACH IS A DISK AROUND THE START, AND THAT OVER-FETCHES.** Measured on the real containers:

    the rule as stated    (2,0) + (1,0) + (0,0) + (3,0)   39,089,436 bytes
    reach along the walk  (2,0) + (3,0)                   24,313,332 bytes

Tile (0,0) is within 131,000 mm of the start and an eastbound walk can never reach it, so 14,776,104
bytes, 38 percent, are fetched for ground nobody stands on. The disk is faithful to the sentence that
was registered and it is a safe superset: it does not need the heading, so it cannot be wrong about
one. A rule taking the reach along the walk's own stated pose and heading would fetch only what the
route can touch. THAT IS A DECISION FOR WHOEVER OWNS THE BUDGET and it is named here with its number
rather than taken quietly.

**AND THE LINE RULE CANNOT BE WRITTEN TODAY, WHICH IS WHY THE DISK IS NOT MERELY THE CAUTIOUS
CHOICE.** The heading does not exist when the fetch happens. The route rule chooses a heading from
its candidates using the FIELD and the rings, and the field is the composed one, so the world must be
composed before a heading exists. A fetch narrowed to the walk's line would be reading a heading that
has not been decided: the pose's `facing` is an arrival facing rather than the route's, the rule can
and does prefer another, and on a three tile world it can prefer WESTWARD. Fetch eastward on that
assumption and the walk runs off the end going the other way, and the failure presents as missing
ground rather than as a wrong fetch. So 38 per cent over-fetched is not waste; it is the price of
computing the world from what is known at the time it must be computed.

THE LINE RULE IS RECORDED AS AVAILABLE UNDER ONE CONDITION, not as rejected: a heading known BEFORE
the world is composed, which means a walk that states its heading up front rather than deriving it.
On that day 14,776,104 bytes come back.

## What the page now does, and the two checks the wiring made necessary

The page reads the container's OWN account of where it sits (`tilePlacement`), plans its world from
the list, fetches the neighbours, and hands them to `loadGeneratedTile`. It states on screen which
container was DRAWN AND STOOD ON and which were STOOD ON ONLY, with their digests, so a record
binding several containers does not need anybody's memory of the evening to say what each was for.

**THE PAGE DOES NOT KNOW A ROUTE LENGTH AND MUST NOT INVENT ONE.** How far a walk may go arrives as
`walk_reach_mm`, stated by whoever defines the walk from their own thresholds. Absent, the world is
the one tile and the page says so; malformed, the request is refused, for the reason a malformed pose
is: a silent fallback is how a frame that is not reproducible ends up in a record looking like one
that is.

WITHOUT A STATED POSE THE REACH IS TAKEN FROM THE WHOLE SQUARE rather than from a guess at where the
walk will open, because an unstated walk opens at the runtime's default and that is decided after the
world exists. A square is the superset of every point in it, so this can only over-fetch.

**TWO INTEGRITY CHECKS THAT DID NOT EXIST BEFORE, and the wiring is what made them necessary.** A row
points at bytes; the bytes state their own identity. Until now nothing compared them, because nothing
depended on the answer. Now the NEIGHBOURS ARE CHOSEN FROM WHAT THE CONTAINER SAYS ABOUT ITSELF, so a
row pointing at the wrong container would compose a world out of another part of the city, and every
tile would arrive verified, whole, and in the wrong place. So the page refuses a row whose container
disagrees with it, and `fetchWalkWorld` refuses the same for every neighbour.

THE TEST FIXTURE WAS ONE OF THE THINGS THAT DISAGREED. The page's walk test served the committed
golden, which states city `d0219dae` tile (0,0), under an invented row saying city `23a5f107` tile
(2,0). Nothing had ever compared them. The row now states what the bytes state.

WHAT THE PAGE TEST CAN AND CANNOT PROVE, said here because it is a real limit. It exercises list,
plan, fetch and check end to end, and it ends in a REFUSAL rather than a composed world, because this
repository commits exactly one container and a second tile's bytes would have to be baked. The
neighbour it serves is that container with its `tile_x` restated, and the edit that makes it claim to
be (1,0) is the same edit that makes it not itself, so it is refused for not baking to its own
records. A container that is internally consistent and in the wrong place is covered separately, and
the wording of a composed statement is covered by a unit test of the line itself.

## Run against a real route, 2026-09-18 21:45

Both live tests have now run against a standing API and both pass. This is the FIRST EXECUTION
ANYWHERE of the composition against containers this repository did not make, and of the populated
branch of the page's world attribute.

    atlas-react, the fetch and the composition
      standing on (0,0), reach 128,000, taken from that container's own tile_size_mm
      neighbours tile (1,0) and tile (2,0); 18 absent squares, ALL no_row
      triangles 7,122 alone, 225,397 composed, which is 7,122 + 121,530 + 96,745 exactly
      transferred 24,977,196 for the neighbours, world 27,458,932, took 529 ms

    app, the page and its data attribute
      reach "stated"; drawn acf1474b71855749 at 2,481,736
      stood on only 8f2188783a8f0347 tile (1,0), e59f6cf05d0ff4e0 tile (2,0)
      transferred 24,977,196, world 27,458,932, 4 route requests, 18 absent squares

**NAME THE POPULATION BESIDE THE NUMBER.** 18 absent squares here, 4 in the gate's record, and both
are right: this run STOOD ON (0,0) WITH A REACH OF 128,000 taken from `tile_size_mm`, and the gate
STOOD ON (2,0) WITH A REACH OF 131,000 from the route rule. An end tile has more empty neighbourhood
around it than a middle one. Two correct counts set beside each other with nothing saying which set
each counted is the third instance in two days, after 2,652 against 916 and 26,406,608 against
39,089,436. None of the 18 was hard-coded; each was checked against the route's own listing.

**RE-RUN ON THE REBASE ONTO MAIN 6d9e3a58**, which landed ten changed readers in `loom-tess` core
including `decodeOwd`'s validation of a container's tile record, the call `tilePlacement` makes. Same
standing tile, same reach, same figures to the triangle and the byte: 225,397 composed, 24,977,196
transferred, 18 absent, 527 ms against 529. That merge was proved inert by digest on the conformance
fixture; it is now proved inert against a live route.

**THE ENVIRONMENT IS OWNED BY THE SESSION THAT STARTED IT.** The API and the gate's development
server were handed over as "standing and free" and both were gone within about thirty minutes; the
first run failed on ECONNREFUSED. The API was restarted through its own `corridor-api` launch entry
so that it belonged to the session that needed it. A live test's dependency is not the server being
up when the test was written.

**TWO DEFECTS IN THE TEST HARNESS, both found by running and neither by reading.** The page test's
own route calls were going through the stub it had installed for the page and answering 404. And
happy-dom enforces the same-origin policy on its `fetch`, so a page test that deliberately talks to
another origin has to go under the window through Node's HTTP client rather than relax the policy for
every test sharing that environment.

## The obstacle half, and the count that did not mean what it was read to mean

The composed world gave GROUND from its neighbours and not OBSTACLES, so the route rule ranked
headings across a field three and a half times wider than the set of rings it was given. The gate
measured `routeObstacleRings` at 311 before and after composition and read the stability as scope:
obstacles from one tile.

**IT WAS NEVER ONE TILE.** `routeObstructionRings` iterates `header.records` with no membership
filter, and a container carries its neighbours as halo, so the set already reached past its own edge:

    tile (2,0)   311 rings, of which ONLY 140 come from records it owns; 171 are halo
                 they span x 178,394 to 464,408, and its own tile ends at 384,000

So the number was right, the population was never stated, and a count stable across a change was
mistaken for a count that covered the change. The defect is real and smaller than it was written as:
obstacles reach about 80 m past the tile edge, composed ground reaches 326 m, and the ungoverned
stretch is the difference.

**MEASURED ON THE END TILE, WHERE IT IS WORST**, standing on (0,0) with reach 128,000, composing
(1,0) and (2,0):

    its own rings                                 115, reaching east to 205,250
    rings only the neighbours state                462
    rings counted separately across three tiles    700
    composed and DEDUPLICATED by record digest     418
    records two tiles state differently              0
    composed reach east                          464,408, which is 259,158 mm further

**DEDUPLICATION IS THE PART THAT IS EASY TO GET WRONG.** A tile's halo copy of a building and the
neighbour's owned copy are the same building: concatenating ring sets put 282 duplicates into the
set above, and a duplicate ring is not inert, since a building described twice is the shape that once
stopped a walker 344 mm from a bench against a 340 mm capsule. The key is the record's own `sha256`,
and the tile being walked is passed first so a shared building is attributed to the street underfoot.

**A HALO COPY IS A STAND-IN FOR A TILE YOU DO NOT HAVE**, and the rule leans on its agreeing with the
owned original. That is ASSERTED rather than assumed: a record two tiles state under one identity
with different digests is reported, and on the corridor today the count is zero. If a halo copy is
ever written as a reduced form of its original, digest equality stops firing and the duplicates
return silently, which is why the check exists rather than a comment saying it should be fine.

Every ring now carries which tile stated it. The obstacle id stays `kind:identity`, because a run
record binds the record identities a walk passed and changing that string would change what those
records mean. And none of this becomes collision: the rings decide which way a walk faces and stop no
body, for the reason `obstruction-rings.ts` gives at length.

## What is not done

- The obstacle half. Neighbours give GROUND and not OBSTACLES: the route rule ranks headings across a
  field three and a half times wider while seeing obstruction rings from one tile, so a clear run of
  294,755 mm into a neighbour is clear because nothing told the rule otherwise. Their whole
  containers are already fetched and verified, so their records are in hand; the rings must stay out
  of the navigation world, for the reason written beside `polygonObstacles`.
- Nothing serves a container's nav sections separately, so the 1,969,322 above is a measurement of
  what a slice would cost and not of a slice anybody can request today.
- No neighbour is drawn, per the statement above.
- The full web check has NOT been run: the gate held the machine. What was run is
  `packages/atlas-react/test/generated-tile-runtime.test.ts`, 32 passed, and the package typecheck,
  with a deliberate type error confirming the checker looked at the changed file.
