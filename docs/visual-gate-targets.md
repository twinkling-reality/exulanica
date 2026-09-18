# Visual gate targets

The visual gate scores a page. A **target** says which page, and everything that makes two runs of
it comparable: how the page is reached, the exact title it must show, what counts as a world being
mounted, which authentication conditions it may run under, what its record binds as the inputs that
were scored, and where the route rule's inputs come from.

Targets are declared twice and held to each other by a test: `GATE_TARGETS` in
`exulanica/evaluation/gate_keys.py`, which records may state, and `TARGETS` in
`scripts/capture_visual_gate.mjs`, which the harness may run.
`tests/test_visual_gate_targets.py` asserts the two sets are equal in both directions, so neither
can gain a page the other cannot.

## The two targets

`owned-district` is the product's own shell showing an owned district. It is the page every retained
record scored, and it is the page the Flatiron baseline failed.

`generated-tile-evaluation` is the development route that draws a baked tile: `?preview=1` and
exactly one of `tile`, `baked_tile` or `city` with coordinates. A production build has no code that
reaches it.

## What a record says

A record states its target. A record that does not state one scored the owned district, and always
did: the retained records were written before any other page could be scored, and they are
immutable, so that is the only reading that keeps them true. A record of the owned district is
byte-identical to one written before targets existed.

A baseline comparison is allowed across targets only when both records were measured by the same key
set and answered against the same rubric, and it states both targets. The keys do not know which
page they measured; what they cannot survive is a different question.

## What the gate will not do

**It will not compare against a title it cannot derive.** Each target names a symbol in the
product's own source, and the harness reads the title from there. If the symbol is gone the run
halts, because a derivation that quietly yields nothing would compare an empty expectation against
an empty title and pass.

**It will not accept a pose a run chose.** A pose is admitted only when a committed file states it,
the run asks the page for that same pose, and the record binds the file by digest. The URL and the
file have to agree, and either alone is a refusal: a pose in the URL with no file is a pose this run
chose, and a file with no pose in the URL is a walk the page was never asked to take. The lane a
scored run judges must never choose where the camera starts.

The file is named by `--walk` and read strictly, because it is prose. A file that states no walk is
refused, and so is a file that states two different ones: a reader that took the first match would
score whichever paragraph came first, and a superseded example would quietly become the opening
frame. The same walk written twice is one walk.

The comparison is made in the frame the file states, integer millimetres of the city frame and an
integer facing, against the same four integers in the URL. Converting to the renderer's metres to
compare would put a frame change inside the gate's own verdict; the renderer pose is a consequence
of the stated one and the record carries it as measured, not as derived.

**It will say when the rule ran without deciding.** A record states `candidatesWithFrontage`: how
many qualifying headings had frontage on both sides at any sample. Zero means the first tie-break
was equal for every candidate and a later one chose, so the heading is the rule's fallback rather
than its preference. Nothing in the rule reads that count, and the plan it returns was measured to
be identical, field for field, to the plan it returned before the count existed.

**It will not walk a route that nothing chose.** The route rule keeps the headings a capsule can
walk and then prefers the one with frontage on both sides. Given no collision rings it does not
fail: every heading qualifies, both tie-breaks are equal for all of them, and the answer is the
lowest heading that fits. That is a default in the costume of a decision, and a record of it would
truthfully say the rule was applied. So a page with no rings halts.

**It will not derive its own rings.** When a tile carries them, the gate reads the route obstruction
rings the runtime holds. A gate that derives its own scores a walk past obstacles the world does not
have. Those rings are the plan regions a walking capsule is kept clear of: they choose a heading,
they drop anything above head height, and they are not collision solids. Nothing in them stops a
body, so a walk that goes around a bench and a walk that passes through one look the same in a still
frame.

## What the stated walk cannot yet prove

Written down because a check nobody can exercise is a check nobody has seen refuse anything.

The reader and the agreement rule are exercised by tests that run the harness itself, and each was
falsified by removing the check and watching the test fail. What is NOT exercised is a real page
opening at a stated pose, for two reasons in the product rather than in the gate:

- the committed golden route passes a literal `pose: null`, so the one target that needs no
  credential cannot take a stated pose at all. A stated pose is reachable only on the routes that
  fetch a container with a credential;
- the page states which of the two it did only as a sentence on screen, "Opened at a stated pose"
  against "Opened at this runtime's default pose". Reading that by parsing the sentence would make a
  scored verdict depend on wording, and the failure direction is the wrong one: a reworded default
  line would read as a stated pose and the gate would pass a frame nobody stated.

Both are asked of the lanes that own those files. Until they are answered the gate binds the walk it
read and the pose the page reported, and does not claim to have checked that the page honoured it.

## The run with the rings carried, predicted before it was run

Written and committed before the server was restarted, so these can be checked rather than fitted.
The first prediction of sixteen was right and the zero beside it was informative only because it was
committed first.

**Predicted:**

- the ringless halt does NOT fire;
- `routeObstacleRings` is **16**, the same sixteen `routeObstructionRings` reads from the container,
  because the runtime states `obstacles.length + refused.length === rings.length` and its refusals
  are empty on this tile. A different number is a finding and the difference is the refused list;
- `frontageBothSidesSamples` on the winner is **above zero, and I expect it high rather than low**.
  I revised this upward on reading the rule's own numbers rather than guessing from the tile: the
  frontage search is 40 m to each side, not a street's width, and the sixteen rings sit in a patch
  about 19 m by 28 m. A ray passing anywhere near that patch has something within 40 m on both
  sides for many of its 126 samples. If it comes back zero, the rings are further from every
  qualifying heading than they look in plan;
- the route length is 125 m plus a 6 m stopping margin, so a heading has to clear 131 m inside a
  tile 128 m across. **I expect no heading to clear it**, and the rule to refuse with "no heading
  from the arrival pose clears the route length". That refusal is the rule working: the tile is
  smaller than the walk the gate measures;
- the eight mechanical keys are therefore expected NOT to be reached. If the route is refused, the
  brief's expectation that they FAIL on this tile stays untested, and that is a fact about the tile
  being 128 m rather than about the keys.

**The field a generated walk is bounded by** is read from the page for the first time in this run.
The owned district states a rectangle in its artifact; a tile states none, and the product bounds a
walk on one by a circle, the navigation world's centre and `fieldRadius`. The gate passes the square
INSCRIBED in that circle, every point of which is inside the field the product bounds. Before this
change the generated target was passing `[0, 0, 0, 0]`, which bounds nothing: every heading pointing
away from the origin had an unbounded clear run. No generated run had reached the rule, so nothing
had ever used those bounds, but a record made with them would have described a walk in a field the
product never allowed.

## What that run did, measured, and where a bench stopped it

Four predictions were committed before the server started. Two held and two did not, and the two
that did not are the more useful half.

| predicted | measured |
| --- | --- |
| the ringless halt does not fire | it did not fire |
| `routeObstacleRings` is 16 | **16**, the same sixteen the container states |
| no heading clears 131 m in a 128 m tile | a heading cleared **136.3 m** |
| frontage high rather than low | `frontageBothSidesSamples` **1**, of 126 |

**Why the third was wrong.** The rule walks diagonals. The field is a 128 m square whose diagonal is
181 m, and the chosen heading, 28 degrees, is one of those. The arithmetic was about a width the walk
never had to respect.

**Why the fourth was wrong, having already been revised upward.** Rings within 40 m on BOTH sides at
the same sample is a far narrower condition than rings within 40 m: this tile's rings sit in one
patch, and a ray that passes it has it mostly on one side. Beside that 1, `candidatesWithFrontage`
is **2**, of 153 qualifying headings out of 720 tried. Frontage decided, by one sample, over 151
candidates that had none. That is what the counter is for: the record would otherwise state heading
28000 and no reader could tell a decision from a fallback.

**Then a ring stopped the walker**, at 52.80 m of 62.5 m. The halt asks the product's own navigation
surface what stands ahead, so it names a cause rather than reporting a stop: support underfoot at
0.088 m and stated for the whole next 10 m, largest rise ahead 0.004 m against the 0.18 m step this
world says it will climb, and 30.3 m inside a field of radius 90.5 m. None of the three.

The walker came to rest at tile (39214, 46615) mm, **344 mm from the nearest edge of the street
furniture record `bf14d328`**, where the city grammar states a capsule radius of **340 mm**. It is
resting against that ring.

The cause is that `navigationWorld.polygonObstacles` is collided against: atlas-core's
`resolveGroundMovement` reports a move blocked when the polygons hit it, and the path continuity
check refuses any move they touch. So route obstruction rings carried into that field ARE collision,
and "they choose which way a walk faces and stop no body" was false the moment it was wired, in the
three places it is written. Development only: `tileNavigation` is called by the generated tile
runtime and nothing else, and the owned district builds its polygon obstacles from its own buildings,
where collision is meant.

This gate's two-input split was built so route rings would not reach the KEYS and be measured as
solids. They reached the movement resolver instead. The split was watching a door somebody had
already thought about.

**So the eight mechanical keys are still unmeasured on a generated page.** A measurement taken here
would have been of the bench and not of the street.

## The run with rings, predicted before it was run

Written before the run, and before the server was started, so the numbers below can be checked
against it rather than fitted to it.

**Measured from the container first, by tess's own reader.** `routeObstructionRings` over the
committed golden states **16 rings across 9 of its 180 records**: one `city.massing`, fourteen
`city.street_furniture`, one `city.street_tree`. So the page should report 16. A different number is
a disagreement between the container and the runtime that carries it, and is worth more than the
run.

**Predicted:**

- the ringless halt stops firing, because the tile now states rings;
- `routeObstacleRings` is 16;
- the chosen heading's `frontageBothSidesSamples` is **0 or close to it**. Frontage on both sides
  wants rings either side of the walked line; this tile has one massing block and a scatter of
  street furniture. If it is zero, the rule ran on the world's own rings and still decided by a
  later tie-break, which is a finding about the rule and not a failure of the run, and it is
  reported either way;
- the eight mechanical keys FAIL, because terrain is drawn as the stated unavailable surface. That
  failure is the point: it is the proof that this gate can fail a generated page;
- the opening reads `default`, because no committed file states a walk for this tile and this lane
  will not write one for a page it scores.

## The first run of the generated target, predicted before it was run

Written and committed before the harness was pointed at the development route, so the order is a
fact in the history rather than a claim in a report.

The conformance tile draws 40 entries over 2,065 triangles and carries a nav_envelope of 4,850
triangles, so a walk on it is supported. It carries no collision rings, and no generated tile can:
the container format declares exactly two projections, `render_batch` and `nav_envelope`, and the
tile runtime builds its navigation world with an empty obstacle list.

So the prediction is that the run HALTS on the ringless route, before it measures a single
mechanical key, with the message about a rule that has nothing to choose between.

If it halts somewhere else, that halt is a finding about the system and will be reported as the
reason it gave, not worked around. If it does not halt at all, something is wrong with the check
itself, and that is the more interesting result of the two.

## What that run did, measured

It halted where the prediction said, before a single mechanical key was measured, exit 3.

The page check passed on the way, which is what makes the halt mean anything: path `/`, the preview
title derived from `config.ts`, a world mounted by the shell and the canvas, and the tile runtime
reporting `tile-conformance`. The run then bound what the page had drawn, recognised by the
container's own magic rather than by its URL:

| bound | value |
| --- | --- |
| container sha256 | `48a87e1ce5c7ca78...`, 531,884 bytes |
| tile_inputs_digest | `e91381e15083e8e2...` |
| tile | x 0, y 0, lod 0, city seed `d0219dae9563...` |
| grammar | city version 2, descriptor `c82ac5e7d39e95ab...` |
| drawn | 2,065 render_batch triangles, 9 draw batches, 12 unavailable surfaces |
| look | `exulanica.generated-tile-look` version 1 |
| route obstruction rings | **0** |

Those numbers are about THAT container. The pinned tile changes when the tessellator changes, so a
figure quoted without the digest beside it silently becomes a claim about a different tile.

**Repeated on tessellator 14**, which rebaked that tile. What moved and what did not is worth as much
as the halt:

| | before | after |
| --- | --- | --- |
| container sha256 | `48a87e1c...`, 531,884 bytes | `8b729a65...`, 553,804 bytes |
| nav_envelope | 4,850 triangles, 4,001 vertices | 5,728 triangles, 4,466 vertices |
| render_batch | 2,065 triangles, 40 drawn | **unchanged** |
| tile_inputs_digest | `e91381e15083e8e2...` | **unchanged** |
| catalog digest | `a50ce477b7612743...` | **unchanged** |
| drawn, batches, unavailable surfaces | 2,065, 9, 12 | **unchanged** |
| route obstruction rings | 0 | **0** |

So the container is a different file and the picture is the same picture: the carve landed entirely
in the navigation projection, and the header states a new tessellator version. A rerun was needed to
know that, and the digests are what say which half moved.

Three refusals were exercised on the same page, so the checks are known to fire rather than assumed
to: the owned-district target pointed at the preview page refused with `title "Exulanica", page
"Exulanica: synthetic read-only development preview"`; the generated target with no tile selector
refused for naming none of `tile`, `baked_tile`, `city`; and an undeclared target refused by name.

Two things the run found that reading had not:

**A page check that samples once races the title.** `index.html` ships `<title>Exulanica</title>`
and the app sets the real title while it starts. On the product target those agree, so nothing ever
raced; on the preview target a single early sample sees the static title and refuses a page that is
about to be correct. The refusal now names which condition failed rather than saying only that the
page was not the target, because five conditions reach that one message.

**A URL suffix is not a file type.** The development server answers a `?url` import of a tile with a
JavaScript module whose path still ends `.owd`. Read by suffix, that module decodes as a broken
container and stops the run. The scan now uses the URL only to narrow what it reads and the
container's own magic to decide, and a response that carries the magic and still fails to decode is
a broken container, which is a different fact and still stops the run.

## A definition with two readings, known and deliberately left

`completeCapsuleClearanceVerification` defines itself, in `exulanica/evaluation/gate_keys.py`, as
true only when a capsule "keeps at least 0.34 m from every drawn triangle that rises more than
0.18 m above that surface and lies outside every building exterior ring with at least 0.34 m to its
nearest edge".

That sentence has two readings:

**A.** Rings EXCLUDE triangles from the test: measure clearance only from triangles that lie outside
every building exterior ring.

**B.** Two conditions: clear of every qualifying drawn triangle, AND outside every building exterior
ring by at least 0.34 m.

**The implementation is B, and has always been B.** That can be established without reading the
implementation at all, from the key's own declared structure: its `decided_by` lists
`capsuleRingContactSamples` as one of the four values that decide it, and a pure exclusion reading
needs no ring counter whatsoever. Reading the code agrees: `measureCapsule` counts triangle contacts
against the drawn triangle table with no ring filter, and separately counts ring contacts against
the prisms, skipping any prism outside the capsule's height band.

**No retained score is affected and none moves.** The measurement has not changed, the key set
version has not changed, and the rubric digest is over `docs/visual-gate-rubric.md`, which states
nothing about capsules or clearance. Every retained record was scored by reading B, because reading
B is what the code has always done.

The sentence is left exactly as it is, on purpose. Its text is quoted verbatim by five retained,
digest-bound reconciliation records, and the gate re-checks the current text against them: changing
one word of it fails five record checks, which is those checks doing their job rather than an
obstacle. Editing it therefore needs a new reconciliation record, and a reconciliation record binds
a named human judge's calibration reply, which is a person's answer and not a thing to be
manufactured for a wording change.

This was found by building the generated-tile target, not by reviewing the product one, which is
also how the static-title hazard and the shared route-and-key ring input were found. Whoever meets
these two readings next: this was known, it was left deliberately, and the records are not suspect.
