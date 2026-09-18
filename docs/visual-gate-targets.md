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

## Which container each section's figures are about

The pinned development tile has been rebaked three times while this document was being written, and
every figure below belongs to ONE of those bakes. A triangle count or a byte size quoted out of a
section without its container is a claim about a different tile a week later, which has already
happened once: the 4,850 nav_envelope triangles in the first run's section were read, months of
rebakes later, as a fact about the tile a current run was standing on.

| container | bytes | the sections whose figures are about it |
| --- | --- | --- |
| `48a87e1ce5c7ca78...` | 531,884 | the first generated run, before tessellator 14 |
| `8b729a65...` | 553,804 | the repeat on tessellator 14, in that section's second column |
| `1ef74efa8eef6844...` | 564,788 | the run with the rings off the collision field, tessellator 17 |

The run that carried rings into the collision field states no container digest of its own. Its ring
counts match what `1ef74efa` states and the tile file had not moved between that run and this one,
which is evidence and not a binding: that run's record is the one place this document does not say
which bytes it scored, and the fix for the next one is that the run record binds the digest itself.

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

**BOTH HAVE BEEN ANSWERED, and this paragraph is the correction rather than an edit of the two
above.** Found on 2026-09-18 by reading the app for a different question, not by re-reading this
document, which is the way a stale claim is usually found. The app now reads a stated pose on the
committed golden route exactly as it does on the credentialed ones, and refuses a malformed one
rather than opening at a default; and it states the opening as DATA on the shell, `stated` or
`default` with the four integers beside it, which is what the harness reads. So the gate does check
that the page honoured the walk a committed file states: it compares the four integers the page
states against the four the file states and halts when they differ, and it halts when a file states
a walk and the page opened at its default.

What the two bullets above described was true when they were written and is no longer true of this
tree. They stay because the reason they were written down, that a check nobody can exercise is a
check nobody has seen refuse anything, is the reason it is worth recording that they were closed.

## What it would take to point this gate at the corridor's street

Written before anything is built, because the corridor is the verdict and the conformance tile is
only the machine. Scoped on 2026-09-18 by reading the app and this harness rather than by trying it.

**What is already true, and this is the load-bearing half.** Nothing in the route rule, the key
measurements or the record binding is sized to the fixture. The route length is 125 m from the rule,
walked as two legs of 62.5 m with a capture at the midpoint. The walkable field is read from the
page's own navigation world rather than from any tile's extent. The container binding reads whatever
crossed the wire and recognises it by the container's own magic. The harness already declares all
three selectors the preview route takes, and a baked street is reached by two of them: `baked_tile`
with an id, or `city` with a seed and tile coordinates.

**So the run is a URL and an environment rather than a change to this gate.** What it needs is the
API serving `/tiles`, a development token holding `tiles.materialise`, and the app started with that
token, which is the shape of the corridor lane's own launch entry and not of this lane's. The
committed golden is served from the working tree and needs none of that, which is exactly why it is
the target that can be run with no credential.

**The stated pose needs nothing either, which was not true when this document was first written.**
The corridor lane has committed the file that states its walk, and `--walk` reads it, binds it by
digest, compares the four integers against the ones in the URL and halts when they differ, then
compares them against the four the page states as data and halts again when those differ. The
harness can consume that file as it stands.

**What is NOT established.** That the corridor tile is walkable. The 32 mm hole found on the
conformance tile is a tessellator defect at a carve boundary, so the corridor's container carries the
same class of hole until it is rebaked with the fix, and nobody has measured its envelope for holes.
A gate run on the corridor before that rebake would halt the same way, one stall earlier or later.

**An open question to answer BEFORE the corridor is scored, not after a no.** The chrome fills much
of every frame: the Companion panel about a third, the development statement a quarter of the lower
left, the scene segments panel between them. The rubric names the authenticated shell, the Companion
and the reticle; it names neither of the other two. Both readings are defensible. KEEPING THEM: the
page is self-describing, and a frame that shows what the page states is the caption restored to the
picture rather than a caption compensating for a picture that says nothing. REMOVING THEM: the judge
is asked whether this is a finished, lived-in street, and answering that through half a frame is a
different question from the one the rubric asks. This lane will not decide it, because the lane whose
runs are judged must not choose what the judge sees.

**And what no amount of this proves.** The verdict is one 126 m street with fourteen buildings,
scored by the named judge. Every mechanical key measured on the conformance tile says the machine
works; none of them says anything about the street.

## The run with the rings off the collision field, predicted before it was run

Written and committed before any server was started, so these can be checked rather than fitted.

**What changed under this run, and why it needed a change here.** Route obstruction rings were taken
out of `navigationWorld.polygonObstacles`, because that field is what a movement resolver collides
against and a bench stopped a walker against it. They are stated on the loaded tile instead. That
field was also the only place this harness read rings from, so the fix cut the gate's own input: with
no change the ringless halt would have fired and the keys would have stayed unmeasured a fourth time.
The page now states the rings the runtime holds, both what it carried and what it refused, through a
development hook under the two guards the tile evaluation already sits behind, and the gate reads
them there. An absent hook and an empty set are separate halts with separate messages, because a
field emptied on purpose reading as a tile with nothing in it is the error that made this necessary.

**Measured from the container first, by tess's own reader, before the run.** The committed golden
`tile-conformance.owd`, sha256 `1ef74efa8eef6844...`, 564,788 bytes, tessellator 17, 180 records,
2,208 render_batch triangles and 5,755 nav_envelope triangles, states **16 route obstruction rings
across 9 records**: one `city.massing`, fourteen `city.street_furniture`, one `city.street_tree`.
None has fewer than three corners and none names no record, which are the runtime's two refusals, so
it should carry sixteen and refuse none. Their plan patch spans 19,110 mm by 28,370 mm.

**What has not moved since the run before this one.** Between the commit that recorded that run and
the head this run is planned from, `git diff --stat -- web/` over that range is empty: nothing under
`web/` changed, and the tile itself last moved earlier still. No hash is written here on purpose,
because a hash in prose stops being true at the next rebase while the sentence keeps its shape; the
run's own record carries the head it measured. So the route rule's three inputs, the arrival pose,
the rings and the field, are the same objects that run planned from.

**Predicted:**

- the ringless halt does NOT fire, and the absent-hook halt does not either. `routeObstacleRings`
  is **16** with **0 refused**;
- the plan is **identical, field for field**, to the one the run before reported: heading **28000**
  millidegrees, clear run **136.3 m**, `frontageBothSidesSamples` **1** of **126** samples,
  `candidatesWithFrontage` **2** of **153** qualifying headings of **720** tried. `planRoute` is a
  pure function of those three inputs and none of them moved, so any field that differs means one of
  them did move, and which field differs says which one;
- the walk passes **52.80 m**, where a bench ring stopped it, and completes its 125 m. Two parts on
  purpose: passing 52.80 m says the ring no longer stops a body, and completing says nothing else
  does. If it passes 52.80 m and stops later, the bench is answered and the new stop is a finding,
  reported as where it stopped and what the product's own surface says there;
- the eight mechanical keys do NOT all hold, and the ones that fail are named here rather than after
  the fact. `completeCapsuleClearanceVerification` **fails**, because the rule prefers a heading
  with frontage on both sides and nothing now stops the capsule, so the walk passes within the 340 mm
  radius of drawn street furniture. `continuousTexturedStreetAndFacades` **fails**, because this tile
  draws surfaces no material record dresses. `companionPresent`, `reticlePresent`,
  `authenticatedShellAndAuthoredHandlersPreserved` and `practicalBrowserBudget` **hold**: 2,208 drawn
  triangles against Melbourne's 227,173, and a container of 564,788 bytes against 28.2 MB.
  `noCutsOrFloatingGeometry` and `usefulEyeLevelMovement` are written down as QUESTIONS, because
  either answer is plausible from here and an expectation with no number behind it can be fitted to
  whatever arrives: does a bench or a tree read as a component detached from support, and does the
  drawn floor agree with the product's own support at every resampled point of a 125 m walk.

**And the thing to report whatever the keys say.** A generated target passes the keys NO prisms: a
tile states route rings, which are not building exteriors and never reach the keys. So on this target
`ringEdgesWithoutDrawnFacade`, `trianglesInsideBuildings` and `capsuleRingContactSamples` are zero
with nothing to be non-zero about, and `facadeTriangles` is zero by construction, which means the key
named for facades measures street alone here. `noCutsOrFloatingGeometry` is decided by two of four
fields and `completeCapsuleClearanceVerification` by three of its four. A key that holds on this tile
therefore says less than the same key on the owned district, and the record must say so rather
than let four green keys read alike.

## What that run did, measured, and the hole a walk came to rest against

Four predictions were committed before the server started. Three held exactly, one was half right,
and the half that failed retracts a cause this document already recorded.

| predicted | measured |
| --- | --- |
| the ringless halt does not fire, nor the absent-hook halt | neither fired |
| `routeObstacleRings` 16, 0 refused | **16**, refused **[]**, and the page's own panel says so |
| the plan is identical, field for field | every field: 28000, 136,323 mm, 1 of 126, 2 of 153 |
| the walk passes 52.80 m and completes | it stopped at **52.795 m**, where it stopped before |

**The plan was worth predicting because it could have moved.** `planRoute` is pure and its three
inputs had not moved, so identity was the falsifiable claim, and three runs on one afternoon returned
the same eight fields: heading 28000 millidegrees, clear run 136,323 mm, 1 frontage sample of 126,
mean skew 730,614 millionths, 720 headings tried, 153 qualified, 2 of them with frontage on both
sides. Frontage decided again, by one sample, over 151 qualifying headings that had none.

**The walk stopped at a hole in the navigation surface, 30 mm wide.** The walker rests at renderer
(39.2142, -46.6152), tile (39214, 46615) mm, with support 0.088 m underfoot. From 15 mm ahead to
45 mm ahead the product's own sampler returns no surface, and this walk was advancing **28 mm a
frame**, the middle of every non-zero step it walked. So its next position lands in the hole, the
resolver recovers it to where it already was, and it does that again every frame until the run gives
up after five seconds without progress. The product says so itself, in its own status line, in the
halt frame, and the last five of those messages are in the record: "Returned to the nearest safe
place; there is no walkable surface here."

**Tested against the whole route rather than the one point.** Walking the product's sampler over the
container's `nav_envelope` at 1 mm along the entire planned line: 131 m scanned, 130,969 mm
supported, 32 mm unsupported, in exactly ONE span, 343.3 mm from the ring of one street furniture
record. There is no second hole in 131 m. A 32 mm crack is all that stands between this gate and a
125 m walk.

**What the crack is made of.** The triangle under the walker and the triangle past the hole are both
1 mm slivers of about 14 mm2, they share no corner, and their outlines come no closer than 2.0 mm.
A point between them is outside every triangle in the projection. So the carve boundary is
approximated by a fan of slivers that does not tile the plane, and the envelope is not watertight
there. That is a bake question and this lane does not touch it.

**It is NOT the sampler's strict edge rule.** A known defect refuses a point lying exactly on an edge
shared by two triangles, where the weight computes to about -5.6e-17. The refused points here are
outside the nearest triangle by 6.2e-5 to 8.2e-5 barycentric units, which at this triangle's size is
millimetres. The sampler is right to refuse them. A tolerance there would hide a real hole.

**And a picture would never have shown it.** The halt frame shows continuous blue paving ahead of the
walker. The drawn surface and the walkable surface are made by different rules, and the hole is in
the one nobody can see.

### What `candidatesQualified` counted, corrected the same day it was recorded

Every figure above stands except one. `candidatesQualified` 153 is what the rule returned and it is
not what a reader takes it to mean: **36 headings genuinely qualify, and 117 of the other 153 walk
south off the tile.**

Found because a count would not reconcile. Running the rule's own `planRoute` offline over the same
rings reproduced every field of the run, heading, clear run, both frontage counts, the skew, the
headings tried and the ones with frontage, and returned 36 where the run returned 153. Identical
inputs cannot give two answers, so one input was not identical, and the halt did not say where the
route started. It does now.

    start exactly on the field's south edge, which is what the page states      qualified 153
    thirty-three micrometres north of it                                        qualified  36
    one millimetre north of it                                                  qualified  36
    every other field of the plan, in all three                                 identical

`firstContact` bounds a ray by `t = (edge - origin) / component` and keeps it only where `t > 0`. A
start lying EXACTLY on a boundary gives `t` of zero for that boundary, so the test skips it and the
ray is never bounded by the edge it stands on. All 117 point south, in one band from 151000 to 209000
millidegrees, and from the edge heading 151000 clears 132 m where one millimetre inside it clears
1.1 mm. This target meets it because the runtime's default pose is the middle of the nav_envelope's
southern edge, which is that boundary.

The chosen heading points north, so the winner, its clear run, both frontage counts and the skew are
untouched, and `candidatesWithFrontage` is 2 either way. The figure is left as the rule returned it,
with this beside it, because a record that quietly states a corrected number is a record nobody can
check against the run that made it.

**And the useful half.** Of the 36 that genuinely qualify, **35 have support at every 5 mm probe over
the whole 131 m**, and the only one with a gap is the heading the rule chose. So this tile is
walkable in almost every direction that qualifies, and the run stopped because of which heading was
preferred rather than because the tile cannot be walked. An earlier sentence of mine said no route on
this tile has support along its whole length; that was measured over one heading of thirty-six.

### The correction to the run before this one, left beside it rather than folded into it

That run's section below says a ring stopped the walker, measured at 344 mm from a bench against a
stated capsule radius of 340 mm. The mechanism was real: route obstruction rings were in
`navigationWorld.polygonObstacles` and `resolveGroundMovement` collides against that field. It was
not what stopped the walk. With that field empty the walk stops in the same place to a tenth of a
millimetre, and the numbers separate the two: the world's `cameraRadius` is the capsule radius,
0.340 m, so a collision would have rested the walker at 340 mm; the rest is at 344.1 mm and the
hole's near lip is at 343.3 mm.

Both accounts stand. The first is left exactly as it was written, because a document that quietly
becomes right teaches nobody, and the next reader needs the failure more than the fact.

**What let the wrong answer survive is the more useful half.** The stall probe sampled support every
0.25 m and reported "support for the next 10 m and rises at most 0.004 m, so neither the surface
ending nor a step it refuses stopped this walk". The hole is 30 mm wide and starts 15 mm ahead. A
probe coarser than one frame of walking measures a population that cannot contain the thing that
stops a walk, and the sentence it produced sent a reader looking for a collision, which was present
and innocent. The probe now samples every 5 mm, states where the hole starts, where the surface
resumes and how wide it is, names the nearest route obstruction ring, and reports the product's own
recovery messages, which the recorder had been keeping since the walk opened and nothing read.

**The eight mechanical keys are therefore still unmeasured on a generated page.** Not measured and
passed, and nothing was adjusted to reach them. The fourth prediction's other half, that they would
not all hold, stays untested, and so does everything the paragraph above it says about which of them
a generated target decides on partial inputs.

## A hint about the frontage tie-break, with its n beside it

**A direction, not evidence.** Over all 36 headings the rule qualifies on this tile, each sampled
every 5 mm for the whole 131 m:

| | no ground | walkable |
| --- | --- | --- |
| frontage on both sides | 1 | 1 |
| no frontage | 0 | 34 |

So the only unwalkable heading is one of the two with any both-sides frontage, and none of the
thirty-four without frontage lacks ground.

**The mechanism it is consistent with.** The tie-break prefers a line with rings close on both sides;
the clearance carve removes support within the capsule radius plus its own integer overshoot of every
ring; so the most enclosed line is by construction the likeliest to run through the band where a ring
is cleared by the rule and the ground is taken away. If that holds, the ranked walk is load bearing
rather than a safety net, and the gate will descend the rule's order routinely.

**Why this cannot establish it.** Two headings have frontage at all. One of them is walkable, a
counter-example to any strong reading, and a fixture with one massing record cannot exercise the
case. The test is a corridor street, which is far more enclosed, and there the same measurement can
fail. Recorded now so that the prediction exists before the data that could refute it.

One number worth keeping for the ranked walk: the two frontage headings are the first two in the
rule's order, and the third is already a heading with no frontage at all. On this tile the order runs
out of frontage immediately; on a street it should not.

## A key that passes on a surface declaring it has no material

**The block fails today, so nothing is wrongly passed. The risk is what happens when it stops
failing.** `continuousTexturedStreetAndFacades` held on run five over an endpoint frame that is an
empty field of magenta diagonal hatching reading UNAVAILABLE, under an empty sky, with no street, no
building and no furniture in it. If the other three keys are ever satisfied while this one still
measures what it measured here, THE WHOLE MECHANICAL BLOCK WOULD PASS ON A MAGENTA FIELD.

Two mechanisms, both measured on that run rather than argued:

**The half named for facades measured nothing.** `facadeTriangles` is zero by construction on a
generated target: `classify` marks a near-vertical triangle as facade only within a band of a PRISM
ring edge, prisms are building exteriors with a stated height, and a tile states none, so the keys
receive an empty list. The 819 triangles the key counted are walking triangles alone. A rule given no
inputs does not fail; here it returned the answer that flatters.

**The unavailable hatch is a texture.** `untexturedStreetAndFacadeTriangles` is zero while the page
states 18 surfaces drawn as unavailable, because the pattern that says a surface has no material is
itself drawn with a texture. The key cannot tell a surface a material record dresses from a surface
wearing the mark that says none exists.

**Not this lane's to fix, and the reason matters more than the rule.** A key's definition and
threshold are forbidden here because a gate that tuned the rule judging its own runs would be worth
nothing, and changing a key's definition needs a reconciliation record, which binds a named human's
calibration reply. This is written down so that whoever owns it can see exactly what it passed, with
the numbers that decided it and the frame it decided over.

## Run five: the eight mechanical keys, measured on a generated page

The first run to reach them. The walk completed 125 m, all three captures were taken, and the block
fails, which is the gate working rather than a problem to be solved.

**What changed to get here.** The route rule qualifies a heading a capsule can travel without
touching a ring or leaving the field, and it never consults support, while the clearance carve
removes support within the radius plus its own integer overshoot. So a line can qualify and have no
ground. The rule now returns its qualifying headings IN ITS OWN ORDER, nothing reorders them, and the
gate walks the first one the product's own surface supports. On this tile that refused the rule's
first choice, 28000, which loses support 52.81 m along, 343 mm from a bench the rule qualifies past
at 340 mm; the walk took 27500, the next in the rule's order.

| key | verdict | what decided it |
| --- | --- | --- |
| `continuousTexturedStreetAndFacades` | **holds** | 819 triangles, 0 untextured, 0 gaps |
| `noCutsOrFloatingGeometry` | **fails** | 62 components detached from support |
| `usefulEyeLevelMovement` | **fails** | eye height error 135 mm and support delta 135 mm, over 50 |
| `completeCapsuleClearanceVerification` | **fails** | 4 capsule triangle contacts of 2,502 checked |
| `practicalBrowserBudget` | holds | 2,208 triangles, 565 KB, 122.9 MB textures, 50 draw calls |
| `companionPresent` | holds | 3 of 3 |
| `reticlePresent` | holds | 3 of 3 |
| `authenticatedShellAndAuthoredHandlersPreserved` | holds | 3 of 3, 0 foreign listeners |

**The walk itself:** 125,009 mm walked of a 125,000 mm route, lateral deviation 0 mm, recovery events
0, harness position writes 0, 2,502 trace samples, and no sample where the drawn floor and the
product's support disagree by more than a step.

### What the three frames are of, which is not what a reader will assume

**They are a picture of the tessellator BEFORE facade openings.** The container they bind is the
fixture at tessellator 17. The same fixture has since been rebaked at 18 with the openings cut, on a
branch that has not merged, so the brick block in the start frame is a solid face and the same tile
after that merge shows holes and reveals in six gridded faces. Anyone shown these frames without that
sentence takes them as a picture of the current tessellator, and they are a picture of the previous
one.

They are also of a CONFORMANCE FIXTURE with one massing record, not of a street. The walk crosses an
empty paved plain. Nothing in them is a claim about what a corridor looks like.

The reticle is the small bracket at frame centre, visible in the midpoint and endpoint frames against
the pale ground. A key reporting three of three and a pixel being present are different claims, and
the second was checked.

### The prediction that was wrong, and it is the one worth reading

`completeCapsuleClearanceVerification` failed for the mechanism predicted: the rule prefers frontage
on both sides, nothing stops the capsule, so the walk passes within 340 mm of drawn street furniture.

`continuousTexturedStreetAndFacades` was predicted to FAIL because this tile draws surfaces no
material record dresses. **It held, and it should not be trusted.** Two reasons, both from the
numbers rather than from looking:

- `facadeTriangles` is zero BY CONSTRUCTION on a generated target, because the keys receive no
  prisms, so the 819 are walking triangles alone and the half of the key named for facades measured
  nothing at all. The vacuous-input caveat written above this section did not merely weaken the key,
  it let it pass;
- `untexturedStreetAndFacadeTriangles` is zero while the page states 18 surfaces drawn as
  unavailable, because THE UNAVAILABLE HATCH IS A TEXTURE. The key cannot tell a surface dressed by
  a material record from a surface wearing the pattern that says it has none.

The endpoint capture is an empty field of magenta diagonal hatching reading UNAVAILABLE under an
empty sky, with no street, no building and no furniture in it. That frame passed the key that exists
to ask whether surfaces look like real materials. Neither the key's definition nor its threshold is
this lane's to change, and a gate that tuned the rule judging its own runs would be worth nothing;
this is recorded so that whoever owns it can see what it passed.

### The two questions, answered

Both were written down as questions rather than predictions, because either answer was plausible and
an expectation with no number behind it can be fitted to whatever arrives.

- Does a bench or a tree read as a component detached from support? **Yes: 62 of them.**
- Does the drawn floor agree with the product's own support at every resampled point? **No: 135 mm
  at worst, against a 50 mm tolerance**, which is the two-surfaces problem this project already knows
  from the records, now measured along a walk.

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
