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

<details>
<summary>Sections</summary>

- [Which container each section's figures are about](#which-container-each-sections-figures-are-about)
- [The two targets](#the-two-targets)
- [What a record says](#what-a-record-says)
- [What the gate will not do](#what-the-gate-will-not-do)
- [What the stated walk cannot yet prove](#what-the-stated-walk-cannot-yet-prove)
- [What it would take to point this gate at the corridor's street](#what-it-would-take-to-point-this-gate-at-the-corridors-street)
- [The run with the rings off the collision field, predicted before it was run](#the-run-with-the-rings-off-the-collision-field-predicted-before-it-was-run)
- [What that run did, measured, and the hole a walk came to rest against](#what-that-run-did-measured-and-the-hole-a-walk-came-to-rest-against)
- [The openings run, predicted before it was run](#the-openings-run-predicted-before-it-was-run)
- [What the openings run did, measured](#what-the-openings-run-did-measured)
- [Why no component is ever seeded as support, measured](#why-no-component-is-ever-seeded-as-support-measured)
- [The corridor run, predicted before it was run](#the-corridor-run-predicted-before-it-was-run)
- [What the corridor run did, measured, and the halt that fired first](#what-the-corridor-run-did-measured-and-the-halt-that-fired-first)
- [The walk from the tile's edge, predicted before the server was asked for a frame](#the-walk-from-the-tiles-edge-predicted-before-the-server-was-asked-for-a-frame)
- [What the retained baseline's frames carry, and what the generated ones carry](#what-the-retained-baselines-frames-carry-and-what-the-generated-ones-carry)
- [The first scored run of a real street, measured](#the-first-scored-run-of-a-real-street-measured)
- [The first scored run of a real street, predicted before the server was restarted](#the-first-scored-run-of-a-real-street-predicted-before-the-server-was-restarted)
- [A third authentication condition, `preview-shell-credentialed-tiles`](#a-third-authentication-condition-preview-shell-credentialed-tiles)
- [What the first walk of a composed world did, measured](#what-the-first-walk-of-a-composed-world-did-measured)
- [The first walk of a composed world, predicted before the server was restarted](#the-first-walk-of-a-composed-world-predicted-before-the-server-was-restarted)
- [Making the falsification rule a mechanism, and what it found in the first minute](#making-the-falsification-rule-a-mechanism-and-what-it-found-in-the-first-minute)
- [Why the neighbour fetch asks for a disk, and why that is not waste](#why-the-neighbour-fetch-asks-for-a-disk-and-why-that-is-not-waste)
- [What the walk from the tile's edge did, measured](#what-the-walk-from-the-tiles-edge-did-measured)
- [What the corridor run did, measured, once the gate could reach the street](#what-the-corridor-run-did-measured-once-the-gate-could-reach-the-street)
- [The reason the product gave, now in the record, and the wrong fix that came first](#the-reason-the-product-gave-now-in-the-record-and-the-wrong-fix-that-came-first)
- [A hint about the frontage tie-break, with its n beside it](#a-hint-about-the-frontage-tie-break-with-its-n-beside-it)
- [A key that passes on a surface declaring it has no material](#a-key-that-passes-on-a-surface-declaring-it-has-no-material)
- [Run five: the eight mechanical keys, measured on a generated page](#run-five-the-eight-mechanical-keys-measured-on-a-generated-page)
- [The run with the rings carried, predicted before it was run](#the-run-with-the-rings-carried-predicted-before-it-was-run)
- [What that run did, measured, and where a bench stopped it](#what-that-run-did-measured-and-where-a-bench-stopped-it)
- [The run with rings, predicted before it was run](#the-run-with-rings-predicted-before-it-was-run)
- [The first run of the generated target, predicted before it was run](#the-first-run-of-the-generated-target-predicted-before-it-was-run)
- [What that run did, measured](#what-that-run-did-measured)
- [A definition with two readings, known and deliberately left](#a-definition-with-two-readings-known-and-deliberately-left)

</details>

## Which container each section's figures are about

The pinned development tile has been rebaked FIVE times while this document was being written, and
every figure below belongs to ONE of those bakes. None of them belongs to the bake the development
server serves today. A triangle count or a byte size quoted out of a
section without its container is a claim about a different tile a week later, which has already
happened once: the 4,850 nav_envelope triangles in the first run's section were read, months of
rebakes later, as a fact about the tile a current run was standing on.

| container | bytes | the sections whose figures are about it |
| --- | --- | --- |
| `48a87e1ce5c7ca78...` | 531,884 | the first generated run, before tessellator 14 |
| `8b729a65...` | 553,804 | the repeat on tessellator 14, in that section's second column |
| `1ef74efa8eef6844...` | 564,788 | the run with the rings off the collision field, tessellator 17 |
| `3a2fd58d76f4d40f...` | 701,276 | the openings run, tessellator 18 |
| `bd07246d...` | 703,556 | **NO SECTION IS ABOUT IT.** The current golden, with the ground bay |

**The last row is the point of this table.** A reader on a later tree finds several digests here and
none of them is what the server serves, which is the state this table exists to make visible rather
than to hide. Every figure below is true of the bake its section names and of no other.

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

## The openings run, predicted before it was run

Tess cut facade openings and rebaked the fixture. Written and committed before the server was
started, so these can be checked rather than fitted.

**Measured from the new container first, by tess's own reader.** `3a2fd58d76f4d40f...`, 701,276
bytes, tessellator 18, 180 records. What moved and what did not is the basis of the prediction:

| | before | after |
| --- | --- | --- |
| render_batch triangles | 2,208 | **4,042** |
| nav_envelope triangles | 5,755 | **5,755** |
| route obstruction rings | 16 across 9 records | **16 across 9 records**, same patch |
| tile_inputs_digest | `5dd2dcb5...` | **unchanged** |

The openings are cut in vertical faces. The navigation projection did not move at all, and neither
did a single ring.

**Predicted:**

- the ROUTE IS IDENTICAL, every field, because its three inputs are the arrival pose, the rings and
  the field, and the nav_envelope those come from is unchanged: 36 qualified, the rule prefers 28000,
  the ground refuses it 52.81 m along, and the walk takes 27500 with frontage 1 of 126 and
  `candidatesWithFrontage` 2. If any of that moves, the envelope moved and the triangle count did not
  say so;
- `continuousTexturedStreetAndFacades` **still holds**, for the same wrong reason: openings are in
  vertical faces, the facade half of the key measures nothing on a generated target whatever the
  facades do, and the walked line crosses an empty plain rather than passing a building;
- `noCutsOrFloatingGeometry` **still fails**, and this is the one key I expect to MOVE: cutting an
  opening changes what counts as a connected component, so 62 detached components should go up. If it
  goes down, my reading of what that number counts is wrong;
- `usefulEyeLevelMovement` **still fails** at the same 135 mm, because it is decided by the walk and
  the surface under it, and neither moved;
- `completeCapsuleClearanceVerification` **still fails**, and its contact count should stay at 4:
  the walk is unchanged and it passes no building;
- `practicalBrowserBudget` **still holds** at 4,042 drawn triangles against Melbourne's 227,173;
- the unavailable surfaces go from 18 to **20**, all still for no material record, because the trim
  surfaces the openings introduce are undressed on two of the six gridded faces.

**And the frames of THIS FIXTURE will look worse, not better.** Its openings should read bright
magenta, because the holes are cut and, ON THIS TILE, nothing dresses the interior backing, the
glazing or the doors behind them: 20 undressed surfaces, of which interior_backing 6, door 3,
glazing 2 and trim 2. That is the fixture's AGE rather than a gap in the grammar. It is hand
written and older than the material catalog.

**Scoped deliberately, because the unscoped version is false of the street.** The corridor tile
draws 1,633 surfaces of which 1,547 are dressed, and its 86 undressed ones are 85 facade ground
bands and the terrain, AND NOTHING ELSE. Every interior backing, all the glazing and all the doors
are dressed there. A sentence about magenta openings belongs to this fixture and would be wrong
about the thing this project is actually building.

So: a run that makes a generated street look more finished is not what this is, and neither is a run
that says generated streets have bare openings. Recorded so the frames are read against a statement
rather than against an expectation formed while looking at them.

## What the openings run did, measured

Every key unchanged. Five hold, three fail, the same three, and only two deciding numbers moved in
the whole set.

| predicted | measured |
| --- | --- |
| the route is identical, every field | identical: 27500 walked, 28000 refused, 36 qualified |
| `continuousTexturedStreetAndFacades` still holds | it held, with the same three numbers |
| `noCutsOrFloatingGeometry` fails AND its count moves up | it failed, and the count DID NOT MOVE |
| `usefulEyeLevelMovement` still fails at 135 mm | 135 mm |
| `completeCapsuleClearanceVerification` fails with 4 | 4 |
| `practicalBrowserBudget` holds at 4,042 triangles | held, 4,042 |
| unavailable surfaces 18 to 20 | 20, all for no material record |

The only deciding numbers that moved are `environmentTransferredBytes` 565,048 to 701,536 and
`drawnTriangles` 2,208 to 4,042, both inside the budget key, which holds either way.

**The route being identical to the millidegree is the prediction with a mechanism paying off.** The
rule reads the arrival pose, the rings and the field; all three come from the `nav_envelope`; the
rebake moved 1,834 drawn triangles and not one envelope triangle or one ring. So the route could not
move, and if it had, something would have moved that the triangle count did not report.

### The prediction that was wrong, and what the record says instead

`componentsDetachedFromSupport` was predicted to RISE from 62 because cutting an opening changes what
counts as a connected component. It is 62 either side. The record says where the triangles went:

    components                     62  ->  62
    supportComponents               0  ->   0
    componentsDetachedFromSupport  62  ->  62
    detachedTriangles           2,208  -> 4,042
    the first detached component  149 triangles -> 1,983, at the same lowest point

The openings added 1,834 triangles to an EXISTING component and created none. A hole cut in a
connected surface leaves it connected, and a reveal attaches to the face it is cut into, so nothing
is separated and nothing new appears. The reasoning was backwards: cutting is precisely the operation
that does not change membership.

**And the number means something other than its name.** `detachedTriangles` equals `drawnTriangles`
exactly in both runs, with `supportComponents` zero. So the key is not reporting 62 stray objects on
an otherwise sound tile. It is reporting that EVERY drawn component is detached, because none is
classified as support at all, on a tile a walker crosses for 125 m. That is the same shape as the
textured key: a number correct about its own definition and saying something quite different from
what its name suggests. The counts are measured; the account of why is a reading.

**Second evidence for the textured key's section, and this time it is a test rather than a
prediction.** Facades are the most changed thing in the frame and `facadeTriangles` is still zero, so
the key that names them measured nothing again.

## Why no component is ever seeded as support, measured

`noCutsOrFloatingGeometry` reports 62 components detached from support, which reads as sixty-two
objects floating over a sound street. What it reports is that EVERY drawn component is detached, and
the reason is in the seeding condition rather than in the world.

A component is seeded as support only when it holds a walking-classified triangle AND THE WHOLE
COMPONENT'S LOWEST POINT sits within the 50 mm contact tolerance of the product's support height at
that plan position. Both clauses measured on the openings run:

- the walking classification FIRES: 819 triangles. So this is not the textured key's defect, where an
  input is empty by construction;
- the height comparison NEVER HAPPENS. Sampling the product's own surface at each detached
  component's lowest plan position, ELEVEN OF THE TWELVE the record lists return NO SURFACE AT ALL.
  There is nothing to be 50 mm from, so `height !== null` fails and the tolerance is never reached.

**A component's lowest point is exactly where support is absent by design.** The largest component is
1,983 triangles spanning five meshes, brick, cast concrete, limestone ashlar, painted render and the
unavailable surfaces: the whole building is one component, and its lowest point is its own footprint
corner, where the carve removed the walkable surface because the massing obstructs. The test asks
whether there is ground under the lowest corner of a thing whose lowest corner is inside the
obstruction the ground was carved away from.

So the key's verdict is right and its number is not what a reader takes it for. That is the second
key on this page in that condition, and neither is this lane's to change.

**The twelfth row, and an inference marked as one.** One component of 2 triangles has its lowest at
69 mm with support at 80.1 mm, 11.1 mm apart, inside the tolerance. It satisfies the height clause
and nothing was seeded, so it must hold no walking triangle. The record does not carry per-component
walking membership and that was not measured.

**That open question is CLOSED, and it goes the other way.** This lane asked whether the same test
fails identically on the owned district, in which case the key would have reported the same thing on
every retained record. Read from the retained baseline record itself rather than reasoned about:

    supportComponents               44      not zero
    componentsDetachedFromSupport   9,323
    detachedTriangles               19,244
    drawnTriangles                  63,730  so detached is about 30 per cent, not all
    walkingTriangles                23,993

So on the owned district the key's model works: it finds support components and reports a partial
figure of the kind the key exists to produce. The signature found here, detached EXACTLY equal to
drawn with support at zero, belongs to the generated target. **The baseline failed this key for a
real reason and its record stands.** What remains inferred, by whoever measured the above and not by
this lane, is that the district's ground extends under its buildings where the generated tile's does
not; settling that needs the product target run.

**And the pattern these two keys belong to, which no lane can see from inside itself.** This is the
third component in the tree to assume the ground is continuous where the clearance carve, behaving
exactly as its own contract states, has removed it: the route rule qualifies a heading at the capsule
radius from a ring while the carve reaches past it; a porch floor is stated as drawn and stood on
while the massing's clearance removes support inside its base ring; and this key seeds support from a
component's lowest point, which for a building is inside its own footprint. Each is correct by its
own contract. What is missing is that nothing states WHERE SUPPORT HAS BEEN REMOVED in a form these
readers can consult, so each models it differently and each is wrong in its own way. The carve is the
defect in none of them.

## The corridor run, predicted before it was run

The first run of this gate against the street the project's stop condition is about. Written and
committed before the API, the page or the harness was started.

**THREE HALTS ARE PREDICTED, FROM THREE LAYERS, and the run meets them in the order the page does
its work.** Recording the order is worth as much as the halts: each belongs to a different part of
the system, and only the first one reached says anything.

1. **THE DECODE, before anything else.** The store's newest bake of tile (2, 0) is tessellator 17;
   this tree's source is 19; and the container reader refuses a version mismatch outright, "there is
   no upgrade on read, rebake the tile". Until that tile is rebaked at 19 the page never mounts it
   and the run learns nothing about the street. THIS IS THE ONE I EXPECT TO REACH FIRST, and while
   it stands the other two are unreachable and therefore untested.
2. **THE ROUTE RULE**, on the arithmetic below.
3. **THE AUTHENTICATION CONDITION**, in this gate, described further down.

**The arithmetic that dominates everything below.** The rule needs its route length plus a stopping
margin, 125,000 plus 6,000 mm, CLEAR. The committed walk starts at tile x 262,000, which is 6,000 mm
inside tile (2, 0)'s western edge at 256,000, so a heading due east has 122,000 mm to the tile edge.
**122 m is less than 131 m, so the heading the corridor's own walk states CANNOT QUALIFY.** The built
street is 116,600 mm frontage to frontage and the committed walk is 116,000 mm; the gate's route is
longer than the street it was built to score.

**THE WINDOW, COMPUTED RATHER THAN INFERRED, because shortening the route does not rescue it.** A
fourth number decides this and it is a KEY THRESHOLD rather than harness configuration:
`minimumWalkedMm` is 120,000 and `usefulEyeLevelMovement` requires at least that much walked.

    due east from the committed pose
      room                        122,000
      so a route must fit         <= 116,000   (122,000 less the 6,000 margin)
      and the key demands         >= 120,000
      WINDOW                      [120,000 .. 116,000]   EMPTY, the two cross by 4,000 mm

    due east from the tile's western edge instead
      room                        128,000
      WINDOW                      [120,000 .. 122,000]   OPEN, 2,000 mm wide
      and such a walk runs        3,400 to 5,400 mm past the 116,600 mm frontage

So there is NO route length that both fits east from the committed pose and satisfies the key's
minimum walk. **The binding constraint is the pose's 6,000 mm inset from the tile edge, not the
street's length.** And at the western edge the window that opens is 2,000 mm wide and every walk in
it ends past the frontage, which is where a walker steps off the pavement onto a junction.

**Four numbers, and only some are free.** The route length is harness configuration that the rubric
calls "roughly 125 m" and never names as a constant, so changing it needs no rubric change; it is
nonetheless written twice, in `keys.ts` and again in `gate_keys.py`, which is two sources for one
number. The stopping margin is harness configuration. THE MINIMUM WALK IS A KEY THRESHOLD and
changing it needs a reconciliation record. The pose is the corridor lane's committed walk, chosen
before any of this was known and deliberately left alone by that lane once it learned something
interesting sat past its end.

This is arithmetic and not a recommendation. Nothing here proposes moving any of the four, and this
lane will not: three of them are somebody else's and the fourth is a key.

**So the single most likely outcome is a refusal**, and it is the rule's own: "no heading from the
arrival pose clears the route length; the route cannot be walked". Rays to the far corners are 140.8
and 135.0 m, so the field alone admits some diagonals, but a diagonal from a footway crosses the
carriageway into the opposite frontage within about 16 m, and this tile carries 32 massings, 36
pieces of street furniture and 30 street trees, every one of them an obstruction ring. For a diagonal
to qualify it must thread 131 m past all of them.

**Predicted, in order of confidence:**

- the run does NOT walk the corridor's stated line, because that line cannot qualify. This is the
  prediction I would be most surprised to lose;
- most likely the route rule REFUSES outright, and the gate halts on its message rather than mine;
- if it does plan, the heading is NOT due east and the walk crosses the street rather than running
  along it, which is the failure the rule's own header names and the frontage tie-break exists to
  prevent. That would be the rule working as written on a street too short for it;
- `routeObstacleRings` is in the low hundreds, not 16. Ninety-eight records obstruct here against
  nine on the fixture, and the fixture averaged 1.8 rings per record, so 150 to 250 is my range;
- `candidatesQualified` is FEWER than the fixture's 36 despite a far richer tile, because rings block
  most directions on a street where the fixture had an empty plain. `candidatesWithFrontage` is a
  larger share of whatever qualifies than the fixture's 2 of 36;
- **`facadeTriangles` STAYS ZERO**, on a street with 168 facades and 32 massings. This is not about
  the tile: the gate never hands a generated target any prisms, by design, because a tile's rings are
  plan regions with no height and the keys measure solids. So the half of that key named for facades
  measures nothing on EVERY generated target, however real its buildings, and the fixture was not a
  special case;
- if the keys are reached at all, the split stays five and three, with the same three failing;
- the frames show a street with buildings either side, 85 undressed facade ground bands reading
  magenta at the base of the frontages, and terrain undressed. Not an empty plain.

**A SECOND HALT PREDICTED, in this gate rather than in the world, and it is my own defect.** Added
after reading the launch entries and the tile route, still before anything was started. A run names
its authentication condition from two declared members: `credentialed-api` needs NO preview requests,
and `vite-preview-api` needs NO `/api/` requests. The preview runs so far were the second, with
`/preview-api/graph`, `/preview-api/formation` and the rest. But a corridor tile is fetched from the
PRODUCT route, `GET /api/tiles` and `GET /api/tiles/{id}/bytes` against `window.location.origin` plus
`/api`. So the corridor page makes BOTH kinds of request and satisfies NEITHER condition.

So I expect the run to halt with "the authentication condition cannot be named", and to do it LATE,
after the walk and all three captures, because the condition is computed near the end. The corridor
is a third kind of page, a preview shell that fetches a credentialed tile from the real API, and the
declared list has two members. That list is a closed list on purpose and it is the right shape; what
is wrong is that it is missing the member this target needs, and I will not widen it during a run I
am scoring. If this fires, the fix is a declared third condition with its own rule, proposed and
reviewed, not a loosened check.

**And a revision to this document's own hint, made before the data rather than after.** The section
below predicts that the tie-break which prefers enclosure will thread the clearance band routinely on
a street. I now expect the opposite here: a line down a 16.2 m wide street runs metres from every
ring, where the fixture's preferred line passed a bench at 343 mm. If the ranked walk is not
exercised on the corridor, that hint is weakened rather than confirmed, and the honest reading is
that it was formed on a tile whose only frontage was a furniture cluster.

## What the corridor run did, measured, and the halt that fired first

The gate was pointed at the corridor's street three times. It has still never walked it, and every
number this run exists to report is UNMEASURED. Saying which is the point of the section.

**The first attempt died inside the harness rather than in the world.** `--walk` resolves its path
against the process working directory and the harness is started from `web/`, so a path written as
`docs/generated-corridor-street.md` was looked for at `web/docs/...` and nothing started. My defect,
in my own file, and it says nothing about the corridor. The run was repeated with an absolute path.

**The second attempt halted at the decode, in the predicted position, in the product's own words.**
Served by the corridor lane's entry on 5321, which serves that lane's app package at 77ca6bb5 where
`TESSELLATOR_SOURCE_VERSION` is 17:

    Atlas could not open Tile 7ce4b90f-675b-52dc-b71b-7264aeb00786 refused: .owd refused:
    tessellator_version is not 17; there is no upgrade on read, rebake the tile

**The third attempt halted the same way at a different version, and the PAIR is the finding.** Served
by `corridor-walk-gate` on 5322, a new entry serving this worktree's app package at source version 19,
same city, same tile coordinates, same pose:

    page built at 17     Tile 7ce4b90f refused: tessellator_version is not 17
    page built at 19     Tile 7ce4b90f refused: tessellator_version is not 19

SAME ROW BOTH TIMES. **The container the page receives does not depend on the page at all**, which is
a stronger statement than either refusal alone and stronger than the argument the second run was made
to test. That 7ce4b90f is the OLDEST of seven bakes of this tile, at tessellator 5, was measured by
an independent store check rather than by this lane.

**So the prediction's premise was right about the store and irrelevant to the page.** The prediction
said the store's newest bake is 17 and this tree is 19; both true, and neither decided anything. The
page is never handed the newest bake, 5 is not 17 either, and the refusal would have fired at any
source version this tree could hold. The halt fired exactly where predicted, for a reason the
prediction did not contain.

**AND MY READING OF THE FIRST REFUSAL WAS WRONG IN A WAY WORTH KEEPING.** I wrote that the page
"resolved the seed and coordinates to the NEWEST row". It resolved to the oldest. The correction
matters less than why the claim was unsupportable: A REFUSAL NAMING A VERSION THE PAGE DID NOT EXPECT
IS CONSISTENT WITH ANY ROW THAT IS NOT THE PAGE'S OWN VERSION. The evidence had no power to separate
newest from oldest in either direction, so had the row happened to be the newest the same reasoning
would have read as confirmed. That is the failure worth recording: not a wrong answer, an inference
whose evidence could not have produced a different one.

**What the halt record does NOT carry.** The product's sentence above was read from the page's console
while the run was live. The record says only "the product shell to mount a world: the product failed
to start". So the reason the product gave for refusing is not bound by the record and is quoted here
on the running session's word. That is a gap in my own file and a candidate for repair.

**What the record does carry now, and exactly how much it is worth.** The third run's record states:

    servedBy: { entry: "corridor-walk-gate",
                worktree: "exulanica-gate-target at c6f312b1",
                stated: true, bound: false }

A record binds its containers, its artifact, the renderer path and this harness BY DIGEST. It says
nothing about the tree the application was built from, and these two fields do not change that: they
carry what the runner claimed. `stated: true, bound: false` is the whole reason to write them, and
anywhere else a record carries a runner's claim it should say so the same way. Binding it would need
the page to state its own build commit as data, the way it already states its opening pose, so the
harness can read it and bind it. That is an app file, so it is a proposal and not a change.

**The absolute path was measured not to reach any record.** The harness stores
`relative(ROOT, resolve(--walk))`, so both halt records above say `docs/generated-corridor-street.md`,
and a search for `/Users/` across a halt record and a completed run record returns ZERO. The
working-directory resolution is therefore a defect to propose after the run, not a fix to slip into
one.

**Still unmeasured, which is the list that matters:** whether the ringless halt fires,
`routeObstacleRings`, `frontageBothSidesSamples` on the winning heading with `candidatesWithFrontage`
beside it, all eight mechanical keys, and both remaining predicted halts. The route rule and the
authentication condition were never reached, so the arithmetic above stands untested and nothing in
this section is evidence for or against it.

## The walk from the tile's edge, predicted before the server was asked for a frame

The second stated walk, from `docs/visual-gate-corridor-walk.md`, starting at the tile's western edge
at 256,000 with the corridor lane's own y and heading. Committed before this run. The page on 5322
was already serving from the previous run, so this is pre-registration against the RUN rather than
against the server, and saying which is the honest form.

**DUE EAST SHOULD NOW QUALIFY, BY 67 MM.** 131,067 mm of room against the 131,000 the rule requires.
That is the least interesting of these predictions and the easiest to be right about.

**QUALIFYING IS NOT WINNING, AND THIS IS THE ONE WORTH READING.** The rule ranks by both-sides
frontage, then least skew, then smallest angle, so due east has to WIN rather than merely fit.

- **I predict the rule picks due east, 270,000 millidegrees**, and that it wins on the FIRST
  criterion rather than on a tie-break: a line down the middle of a street keeps frontage on both
  sides for nearly its whole length, and any heading tilted off it drifts toward one side and loses
  both-sides samples near the end.
- **I predict FEW headings qualify: between 1 and 15, most likely under 10.** A heading tilted more
  than about 3.5 degrees off east crosses the 16.2 m street into a frontage inside 131 m, and of the
  fifteen or so headings within that cone, most should meet one of the 311 rings.
- **THE FAILURE MODE THAT WOULD BE A BIGGER FINDING THAN LAST RUN:** if the rule picks a DIAGONAL on
  a street this dense, the frontage tie-break is not doing what it was written for. I do not expect
  it here, and I expect it less than I did on the fixture, where the preferred line passed a bench at
  343 mm.
- **And the outcome I would be most surprised by: NOTHING qualifies.** Due east down the carriageway
  has to thread 131 m past 311 rings. One tree or bollard on the centre line refuses it, and then a
  street built to be walked cannot be walked in any direction.

**THE RANKED WALK: I predict the FIRST candidate has ground and none is refused.** On a 16.2 m street
the chosen line should run metres from every ring, where the fixture's preferred line passed one at
343 mm and lost its support to the clearance carve. If a heading IS refused for no ground here, the
carve is reaching further than a street's own geometry explains.

**THE THREE NUMBERS.**

- the ringless halt does not fire, and `routeObstacleRings` is **311 again, exactly**: same tile, same
  bake, same digest. A different number would mean the rings are not a function of the container.
- **`frontageBothSidesSamples` between 100 and 120 of 126.** The route is 125,000 mm and the street is
  116,600 mm, so about 6,000 mm at the start and 2,400 mm at the end run past the frontage into the
  junction, which is eight or nine samples with nothing on one side or both.
- `candidatesWithFrontage` beside it: I expect it to equal or nearly equal the qualifying count,
  unlike the fixture's 2 of 36, because every line down this street has buildings either side.

**THE EIGHT KEYS: I PREDICT NONE OF THEM IS MEASURED.** The authentication condition halts this run
after the walk and after all three captures, because the corridor page is a preview shell that
fetches a credentialed tile from the product API and satisfies neither declared condition. That was
pre-registered before the first corridor run and has never yet been reached. If the walk completes,
this is the halt that ends the run, and the captures exist but no key does.

**If the keys ARE reached**, then: `usefulEyeLevelMovement` passes for the first time, because the
walk finally exceeds the minimum; `continuousTexturedStreetAndFacades` fails, on 86 surfaces stating
no material and on facade triangles that are zero by construction; `completeCapsuleClearanceVerification`
fails; and **`practicalBrowserBudget` is the one I would watch**, because this tile moved 102.6 MB
across the wire and decoded 149.6 MB of texture, where the fixture that passed moved a fraction of
that. A key that passed on a fixture and fails on a street is the gate working.

## What the retained baseline's frames carry, and what the generated ones carry

**Measured by opening all six frames**, the three retained Flatiron captures and the three from this
run, rather than reasoning from which target each belongs to.

    THE RETAINED BASELINE, all three frames
      the Companion panel, about a quarter of the frame at the right
      "Press P to add an object to this world", a small hint, on the START frame only
      NOTHING ELSE

    THIS RUN, all three frames
      the Companion panel, the same panel in the same place
      A DEVELOPMENT EVALUATION PANEL, about an eighth of the frame at the left
      a scene segments card, below it
      magenta UNAVAILABLE hatching across ground and facades

**THE BASELINE CARRIES NO EVALUATION PANEL.** So this is the second of the two cases: every
generated frame carries a caption the baseline never had, and that caption tells the reader what to
conclude about the thing being judged. It reads, in part, "Development evaluation of generated tile
503afcb6... **NOT PART OF ANY WORLD**", followed by the container digest, "527 of 610 records drawn;
86 surfaces drawn as unavailable", and "Unavailable or not drawn (169)".

**AND THE HANDICAP HAS NEVER REACHED A JUDGEMENT, which is the part that matters.** The judged key
on every generated run in this record reads `awaiting-named-judge`. No generated frame has ever been
put to the judge, so the comparison has not yet been made unfairly: THIS IS CAUGHT BEFORE THE FIRST
JUDGEMENT RATHER THAN AFTER IT. Nor was it anybody's doing: the baseline is the product shell, which
has no preview furniture to show, and the generated target is the development preview, which does.
The two pages differ and nobody chose the difference.

**A DISTINCTION THE FIX MUST NOT BLUR.** Three things sit on these frames and only two are furniture.

- The **evaluation panel** and the **segments card** are about THE RUN. They belong in the record,
  which already states the condition, the digests, what was drawn and what was not.
- The **magenta hatching is not furniture. It is the world.** It is the product drawing, honestly,
  the surfaces it has no material for, and a judge deciding whether a street reads as inhabited
  SHOULD SEE IT. Hiding it would be the fallback-imagery fault inverted: dressing an absence so it
  photographs better. The baseline has no such marks because its district has nothing undressed, not
  because it was cleaned.

**BUILT AND VERIFIED BY LOOKING, at 97d8caa1.** The harness hides the two selectors before every
frame and names them in every frame's record; the run's captures each carry
`furnitureHidden: ['.generated-tile-evaluation', '.scene-segments']`. Opening the new midpoint frame:
the panel and the card are gone, the Companion is where it was, AND THE MAGENTA IS STILL THERE on the
facades and the ground. The instrument was altered and the subject was not.

Three breaks, each refused: the panel surviving into a frame, the hiding reaching the world and
taking the hatching with it, and the refusal itself ceasing to name what it refuses. The second is
the one that matters in a year.

**WHY A CAPTION IS WORSE THAN AN OCCLUSION.** The Companion covers more of the frame than the
evaluation panel does, and it stays: it is the product, `companionPresent` counts it in three of
three captures, and a frame without it would not be a frame of this product. The evaluation panel is
different in kind rather than in size, because it does not merely cover the street, IT MAKES A CLAIM
ABOUT IT. A record is read by someone asking what this run was. A frame is looked at by someone
asking whether it looks like a street. Putting the first inside the second contaminates the only
measurement in this project a machine cannot take.

## The first scored run of a real street, measured

**The gate scored a generated street.** Eight mechanical keys measured, the ninth left for the named
judge, three captures taken, and the condition that admitted it named in the record.

    condition   preview-shell-credentialed-tiles
    probe       { path: /api/graph, status: 403, asked: true, gateInitiated: true }
    anonymous   401

**SIX TRUE, TWO FALSE, AND I PREDICTED FOUR AND FOUR.** Four of my eight key predictions were wrong,
which is the worst prediction record of any run in this document, and every one failed the same way:
I reasoned from a quantity the key does not measure.

    continuousTexturedStreetAndFacades             TRUE    I predicted FALSE
    noCutsOrFloatingGeometry                       FALSE   I predicted FALSE
    usefulEyeLevelMovement                         FALSE   I predicted TRUE
    completeCapsuleClearanceVerification           TRUE    I predicted FALSE
    practicalBrowserBudget                         TRUE    I predicted FALSE
    companionPresent, reticlePresent               TRUE    I predicted TRUE
    authenticatedShellAndAuthoredHandlersPreserved TRUE    I predicted TRUE
    readsAsInhabitedStreet                         awaiting the named judge

**WHY EACH MISS WAS THE SAME MISTAKE.**

- **Texture.** I predicted failure from "86 surfaces state no material". The key counts
  `untexturedStreetAndFacadeTriangles`, which is **0**. Surfaces stating no material and triangles
  drawn untextured are different populations, and I substituted one for the other.
- **Movement.** I predicted a pass because the walk finally exceeded the minimum, and it did:
  `walkedDisplacementMm` is 125,010 against 120,000. It fails on `maxEyeHeightErrorMm` 146. I read
  the key's name, remembered the distance, and never looked at what else it requires.
- **Budget.** I predicted failure from the four containers' 39,089,436 bytes. The key reads
  `environmentTransferredBytes`, which is **12,683,265**: THE ENVIRONMENT ARTIFACT ALONE, not the
  walk's world. The neighbours a walk stands on are not in the budget this key measures.
- **Capsule.** I predicted failure from the fixture's history. Measured: 2,502 of 2,502 samples
  checked, 0 contacts of either kind.

**The one failing key, and its single cause:** `componentsDetachedFromSupport` is **773**, against 62
on the fixture. Nothing else in that key is non-zero: no support gaps, no ring edges without a drawn
facade, no triangles inside buildings.

**THE WORLD, BOUND AND CROSS-CHECKED IN THE SCORED RECORD.** Reach stated, the page's 26,406,608
bytes for the three tiles it only stood on equal to what this run decoded for exactly those three,
and each container named by what it was for.

**THE TWO HORIZONS, AND THE PREDICTION THAT COULD NOT BE TESTED.** I predicted the obstacle reach
would extend to about x 525,997 and the ungoverned stretch shrink to about 24,758 mm once the
neighbours' obstacles were composed. **That composition is not on main**, so:

    ground reaches x   89,245 to 550,755      four tiles
    obstacles reach x 178,394 to 464,408      unchanged
    rings                            311      unchanged
    obstaclesCoverTheGround        false
    ungoverned                    86,347 mm   unchanged

The prediction is neither confirmed nor refused. It was made against a tree that does not exist yet,
and saying so is the only honest reading.

**AND THE RECORD ALMOST DID NOT SAY ANY OF IT.** The first scored record stated `horizons: null` and
`walkWorld: null` while every halt record that evening had carried both, because a halt spreads what
was observed and A SCORED RECORD IS WRITTEN FIELD BY FIELD: the builder enumerates what it carries,
was handed both, and dropped them in silence. That is this project's most-repeated defect, in the
first record it would have mattered in. Both are now carried and a test refuses their removal.

## The first scored run of a real street, predicted before the server was restarted

The condition is on main and not on the branch that wrote it, so a run may now be scored. Committed
before the page was reloaded onto the merged tree.

**THE OBSTACLE REACH, WHICH IS THE PREDICTION WITH A NUMBER IN IT.** The composed world now carries
the neighbours' obstacles as well as their ground, so the stretch the rule ranks over while knowing
of nothing standing should SHRINK:

    before, obstacles from the walked container alone   x 178,394 to 464,408
    ground, unchanged, four tiles                       x  89,245 to 550,755
    ungoverned before                                      86,347 mm

    PREDICTED after composing the neighbours' rings
      east reach          about x 525,997, the figure the tess lane measured for (3,0)
      ungoverned          about 24,758 mm, the last stretch no loaded tile covers at all
      west reach          BELOW x 178,394, because tiles (1,0) and (0,0) lie west of the walk and
                          (0,0) reaches from the world's own western edge

**`routeObstacleRings` RISES FROM 311, AND BY LESS THAN THE SUM.** Rings are deduplicated by record
digest, and a halo copy of a neighbour's building is the same record the neighbour states, so most of
what composition adds is already described. The tess lane measured 700 counted separately against 418
deduplicated over three tiles. Over four I predict **between 400 and 800, most likely 450 to 650**,
and `disagreed` EMPTY: no record stated differently by two tiles.

**THE EIGHT MECHANICAL KEYS, AND I EXPECT FOUR AND FOUR.** Run five scored five true and three false
on the committed fixture. On a real street:

- `usefulEyeLevelMovement` PASSES FOR THE FIRST TIME, because the walk completes 125,010 mm against
  a minimum of 120,000. It has never passed on a generated target;
- **`practicalBrowserBudget` FLIPS TO FALSE, and this is the prediction I care about.** It passed on
  a fixture that moved a fraction of this. This tile moved 102,625,084 bytes across the wire and
  decoded 149,596,816 bytes of texture, and the walk's world now fetches four containers totalling
  39,089,436 bytes before any texture. A key that passes on a fixture and fails on a street is the
  gate working, not a defect in the street;
- `continuousTexturedStreetAndFacades` FAILS, on 86 surfaces stating no material and on facade
  triangles that are zero by construction because the gate hands a generated target no prisms;
- `noCutsOrFloatingGeometry` FAILS and `completeCapsuleClearanceVerification` FAILS, as on the
  fixture;
- `companionPresent`, `reticlePresent` and `authenticatedShellAndAuthoredHandlersPreserved` all
  PASS, the last of them for the first time on this page, because the condition now names it.

So **four true, four false**, against the fixture's five and three, with the movement key gained and
the budget key lost.

**AND THE NINTH KEY IS NOT PRODUCED, NOT DRAFTED AND NOT SIMULATED.** It is judged by the named
human judge. The endpoint capture will exist and goes to nobody: the composed
world is walkable and now obstacle-aware past the edge, and STILL NOT DRAWN past it, so the endpoint
camera faces undrawn world. That commitment stands.

## A third authentication condition, `preview-shell-credentialed-tiles`

`AUTHENTICATION_CONDITIONS` in `exulanica/evaluation/gate_keys.py` lists it.
`authenticationConditionOf` in `scripts/capture_visual_gate.mjs` assigns it from one run's traffic.
`tests/test_visual_gate_targets.py` assigns that name from corridor traffic. The credential question
underneath it is a deployment decision this document does not settle.

**THE HALT THIS IS ABOUT**, which was predicted before the first corridor run and reached for the
first time on the composed walk, after the walk and all three captures and before any key:

    the authentication condition cannot be named: preview requests 6, graph read false,
    anonymous status 401

**THE RULE, WRITTEN OUT.** A run satisfies `preview-shell-credentialed-tiles` when ALL of:

1. it made at least one `/preview-api/` request, so it IS a preview shell;
2. every `/api/` response it was served with status 200 is under `/api/tiles`, so nothing outside
   tiles was served to it;
3. it asked `/api/graph` and was NOT served it, so the credential it holds does not carry the graph;
4. an anonymous read of the API is refused, which is the same evidence `credentialed-api` rests on.

**MEASURED, AND THE MEASUREMENT CHANGED THE RULE.** I drafted clause 3 as "it never reads the graph"
and then looked:

    GET /api/graph                403 Forbidden
    GET /api/tiles?city_seed=...  200
    GET /api/tiles/{id}/bytes     200, four times
    anonymous read of the API     401

**The page DOES ask for the graph and is refused.** Written from the draft, the condition would never
have matched the page it was written for and the run would have halted again. And the pair is better
evidence than the absence would have been: 401 to a caller with no credential and 403 to this
caller's credential means the API distinguishes NO CREDENTIAL from A CREDENTIAL THAT DOES NOT CARRY
THIS, which is the property an authentication condition exists to assert.

**WHAT CLAUSE 3 DEPENDS ON, stated in the condition's own definition rather than discovered later.**
It rests on the page's INCIDENTAL BEHAVIOUR: the page asks for the graph because that is what it
does today, not because anything requires it to. If it ever stops asking, the property is still true
and THE EVIDENCE FOR IT VANISHES, and a run then halts for a reason that looks nothing like its
cause. It fails closed, which is the safe direction. The durable answer is for the harness to probe
with the page's own credential rather than wait for the page to do it out of habit, and that is a
credential question this document does not settle.

**WHY NEITHER EXISTING CONDITION CAN BE WIDENED TO COVER IT.**

- `credentialed-api` requires NO preview requests at all. That is what makes it mean "this is the
  product shell". This page made six.
- `vite-preview-api` requires NO `/api/` requests at all. That is what makes it mean "this page never
  touched the product API". Melbourne's retained record was scored under it, so loosening it would
  change what a retained record asserts, retroactively, about a run nobody can re-run.

**IT COSTS NO NEW RECORD SHAPE.** Every fact the rule needs is already written: the record's
`authentication` block carries the condition, the anonymous status, the API responses by route and
status, and the preview requests. A reader can check the condition was named on evidence today.

**AND THE GAP THAT IS NOT ABOUT CREDENTIALS AT ALL**, closed at 582eb60b before any of this is
decided. `AUTHENTICATION_CONDITIONS` is described as a closed list, and it was closed by prose only:
appending a third member was noticed by NOTHING over 230 tests across all three gate test files. The
neighbouring test asserts a SUBSET and admits it in its own docstring. A record naming an unlisted
condition IS refused when it is verified, so the runtime check was real; what was missing was
anything that noticed the LIST growing. The harness's condition names are now held against the
record's list both ways, and the exact break that nothing noticed is refused by the test that claims
it, of 231 asked.

## What the first walk of a composed world did, measured

The run at 4b2e02b0, served by `corridor-walk-gate` from this worktree, quiet slot then GPU slot.
**The gate walked a real street end to end for the first time**, took all three captures, and stopped
exactly where it was predicted to stop.

**THE BYTES, EXACT.** Four containers, read off the wire and bound by digest:

    503afcb6  e59f6cf05d0ff4e0   12,682,828   drawn and stood on
    db1de1de  8f2188783a8f0347   12,294,368   tile (1,0), stood on only
    26e25f5c  acf1474b71855749    2,481,736   tile (0,0), stood on only
    79fd317d  5b5225f2404fbd1b   11,630,504   tile (3,0), stood on only
                                 ----------
                                 39,089,436   predicted 39,089,436
                  neighbours     26,406,608   the page states 26,406,608

**THE PAGE'S WORLD WAS CHECKED, NOT READ.** The page states its world as data, and its prose line
beside it says the same thing; BOTH ARE DERIVED FROM ONE OBJECT, so their agreeing would prove only
that neither mapping has a typo. The record binds the statement only after holding it against the
containers this run read from the protocol's own log: same digests both ways, in both directions, and
the page's 26,406,608 equals the bytes this run decoded for exactly those three. That is a genuinely
separate observation of the same fact. Four squares have no ground at all, each stating its own kind
of absence, `no_row` for all four: the corridor is a single ROW of tiles, so this is the edge of the
loaded world and not a defect.

**EIGHT PREDICTIONS HELD AND ONE FAILED.** Due east qualified and THE RULE PREFERRED IT at 270000
millidegrees. The pre-walk ground check passed on the FIRST candidate where all three were refused
before, `headingsRefusedForNoGround` is 0, and the walked line's steepest rise is 0.2 mm at 3.15 m,
so the 192.987 mm kerb was never crossed, as predicted. The walk reached 125.01 m of 125 m. All three
captures exist. And the authentication condition halted the run with NO KEY MEASURED, which has been
the standing prediction since before the first corridor run and is the first time anything reached
it.

**WHAT FAILED: `frontageBothSidesSamples` is 123 of 126 and I predicted 100 to 120.** The reasoning
was that about 8,400 mm of the 125,000 mm route runs past the frontage into the junction, which would
be eight or nine samples. Only THREE lack frontage on both sides. **The reasoning was right about the
street and wrong about the world**: with neighbours composed, the frontage continues past the tile
edge, so a route running off the end of this street arrives at the start of the next one.

**AND THE NUMBER I SHOULD NOT HAVE CLAIMED AT ALL.** I predicted a second run of the same walk would
fetch 0 new bytes, because a neighbour already held at its digest costs no request. Every run here
opens a FRESH BROWSER PROFILE, so nothing is held between runs and this one fetched the same
39,089,436. That prediction was about a reload inside one session and my runs cannot test it. It is
untested, not confirmed and not refuted.

**A FINDING THE RUN TURNED UP, which belongs to the rule rather than to this walk.** The field grew
with composition and the obstacle set did not:

    field radius, one tile      94.847 m        composed   326.337 m
    routeObstacleRings          311             composed   311, unchanged

The neighbours contribute their navigation envelope and not their records, so the rule now ranks 720
headings across a field three and a half times wider WHILE SEEING OBSTACLES FROM ONE TILE ONLY.

> **CORRECTED, and the correction is mine to carry.** "Obstacles from one tile only" is wrong, and so
> was the 64,000 mm obstacle horizon I wrote from `tile_size_mm` into an append-only record on a
> figure I was given. MEASURED SINCE, twice and independently, from the page's own hook and from the
> harness in a walk: the 311 rings reach x 178,394 to 464,408 while the walked tile ends at 384,000,
> so they extend about 80 m past its edge. The set is one tile's records PLUS THE HALO IT CARRIES FOR
> CARVING, which nothing filters out. The defect survives and shrinks: the ground reaches x 550,755,
> so the stretch the rule ranks over while knowing of nothing standing is about 86,347 mm at this
> walk's eastern end, not most of a street. Superseded in
> `docs/evaluation/2026-09-18-obstacle-reach-measured-from-the-rings.json`; the earlier record stands
> unedited. The lesson is the count: 311 was stable across composition, and I read stability as
> scope.
>
> **Who measured which half.** The EXTENT is this lane's, taken twice: from the page's own hook and
> from the harness during a walk. The MEMBERSHIP, 140 owned against 171 halo with no filter applied,
> was reported from the tessellation records and then verified independently against the route
> rings source. This lane has not read that code and does not restate it as its own measurement. The
chosen heading reports a clear run of 294,755 mm, which reaches well into tile (3,0), through
buildings the rule cannot see. **This walk is unaffected**: it ran from x 256,000 to 381,000 and never
left tile (2,0). But `candidatesQualified` rose from 3 to 68 on a world whose obstacles did not
change, and some of those 68 are clear only because nothing told the rule otherwise.

**THE ENDPOINT CAPTURE IS NOT JUDGEABLE AND THIS IS SAID BEFORE ANYONE LOOKS AT IT.** The composed
world is walkable past the edge and NOT DRAWN past it: only the neighbours' navigation envelope is
loaded, none of their render batch. The endpoint frame stands at x 381,000 on ground that continues
and sees no street beyond the tile edge. That limit is recorded here, with the frames, rather than in
anyone's memory of the evening.

**Three transport defects of mine were spent getting here**, and the third is the one worth keeping:
opening a body stream from a network EVENT is a race against a localhost response that can finish
inside the round trip. It lost on the smallest container of four, then on a larger one, and the run
before those had read all four and WAS SIMPLY LUCKY. Pausing the request before it is sent removes
the race: measured 4 of 4 streams opened, 0 refused. The harness supplies nothing and continues the
request untouched, so the bytes are still the ones the server sent to the page.

## The first walk of a composed world, predicted before the server was restarted

The first run against a world of more than one tile, and the first LIVE exercise of that path
anywhere: the live route test covers transport for ONE tile and contains no reference to the
neighbour fetch, so nothing automated has ever asked a real server for a composed world. **A failure
here is an untested path and not a regression**, and it is written down before the run so that
distinction is not made afterwards by whoever is disappointed.

**THE BYTES, WHICH ARE THE FIGURE ONLY THIS SEAT CAN TAKE.** The two numbers in circulation are one
number: 26,406,608 is the neighbours alone and 12,682,828 is the tile the page already fetched today,
and they sum to exactly the 39,089,436 predicted. I predict the measured total matches that sum, and
that a second run of the same walk fetches **0 new bytes**, because a neighbour already held at the
digest its row names costs no request. I have NO prediction for the time; that is the number I said I
would bring rather than guess at.

**FOUR CONTAINERS, NOT FIVE.** An earlier count of five was an assumption; the
page's own statement says four, one drawn and stood on plus three stood on only. **Correcting that
number before the run rather than after it.**

**THE WALK.** Due east should qualify again and the rule should prefer it, as it did at 270000
millidegrees with three qualifying. The pre-walk ground check should now pass on the FIRST candidate,
where all three were refused before, because the ground no longer stops at x 384,000.

**THEN THE KERB, AND I EXPECT IT NOT TO FIRE.** Tile (2,0) steps 192.987 mm where its terrain meets
its street, against the 180 mm the walker states it will climb. A walk ALONG the street should never
cross that join, which is at the street's edge rather than down its middle. If it does fire, the halt
now says which of the two it is, with the position and the nearest ring beside it.

**AND THE HALT I HAVE PREDICTED THREE TIMES AND NEVER REACHED: the authentication condition.** The
corridor page is a preview shell fetching a credentialed tile from the product API, satisfying
neither declared condition. I predict the run WALKS 125 m, TAKES ALL THREE CAPTURES, and then halts
on "the authentication condition cannot be named" with NO KEY MEASURED. That has been the standing
prediction since before the first corridor run and this is the first run that can reach it.

**The endpoint capture will exist and must not be judged.** The composed world is walkable past the
edge and not drawn past it: only the neighbours' nav envelope is loaded, none of their render batch.
The endpoint frame stands on ground that continues and sees no street beyond the edge. That is stated
here, before the frame exists, so the limit travels with the evidence rather than with anyone's
memory of tonight.

## Making the falsification rule a mechanism, and what it found in the first minute

Two falsifications in one evening ASKED NOTHING and both reported success: one over a fixture whose
values made the right answer and the wrong answer the same number, one over a `-k` expression that
selected tests named after the code while the test that mattered was named after the property. Both
runs were real. The tree was committed, the break was applied, pytest ran and passed.

`scripts/falsify.py` refuses that result. It applies one break, names the tests it put the question
to, and REFUSES TO REPORT A PASS WHEN THE SELECTION WAS ZERO. It restores from bytes it held rather
than from git, and compares the digest afterwards, because a restore that cannot prove it restored is
the same fault one layer down; anything a break leaves behind is NAMED rather than silently cleaned.
Its three verdicts, each produced against a real case before this was written down:

    REFUSED by test_a_drop_is_not_a_step_up, of 36 selected
    NOTHING NOTICED over 35 tests, so the harness is the first suspect
    ASKED NOTHING: no test was selected

**AND IT CAUGHT ITS OWN FIRST VERSION.** Its counter looked for pytest's `=` banner, which this
project never prints because `-q` is already in addopts, so it read every run as having selected zero
and reported a genuine refusal as having asked nothing. The tool's whole purpose failing in its own
first use is the sharpest argument for running it rather than reading it.

**WHAT THE SECOND VERDICT FOUND, which is why this was worth building.** The break "coarsen the
ground probe spacing" was noticed by NOTHING over 35 tests. That constant is the one whose coarseness
already cost this project a run: at 0.25 m it reported "support for the next 10 m" over a 30 mm hole
15 mm ahead of a stalled walker, and misdirected run three's diagnosis entirely. It had been fixed
and never pinned, so it could have drifted back at any time without a single test objecting.

It is now held to a RELATIONSHIP rather than to a number: at least two samples must land inside the
hole that was missed. Retyping 0.005 in a test would have made the test a copy of the code, and a
copy can never refuse anything. The two probes also had two separate copies of the same 0.005, and
now share one.

**AND THE REPLACEMENT QUIETLY LOST A PROPERTY THE THING IT REPLACED HAD.** The prose parser counted
`passed|failed|errors?|xfailed|xpassed`, and its docstring said "deselected is deliberately not one
of the words counted"; SKIPPED WAS NOT IN THAT LIST EITHER, and that exclusion was a decision. The
plugin that replaced it read `session.testscollected`, which counts everything pytest gathered
INCLUDING what then skipped without running. Measured on a file of two skipping tests:

    pytest   2 skipped in 0.00s
    plugin   {"collected": 2, "asked": 0}
    before   NOTHING NOTICED over 2 tests          <- zero questions asked, reported as a measurement
    after    ASKED NOTHING: no test answered, though 2 were collected and skipped

So the more robust mechanism was, for one case, WRONG IN EXACTLY THE WAY THE TOOL EXISTS TO PREVENT.
And this repository already held the other view: `tests/conftest.py` prints UNVERIFIED INVARIANT in
red when the postgres tests skip, calling them the only executable proof of what the database
guarantees, across 66 marked files. Two mechanisms in one repository disagreeing about what a skip
means, with the newer one wrong.

A test is now ASKED when it reported an outcome of its own: it failed in any phase, which is also how
a setup error arrives, or it reached the call phase and passed. Both numbers are kept, because the
GAP between collected and asked is itself the measurement that tells a reader the database was down
rather than that a property is unpinned:

    refused, but NOT by <the expected test>, of 2 asked (1 of 3 collected never answered)

## Why the neighbour fetch asks for a disk, and why that is not waste

Recorded before the wiring lands, because the number invites the wrong edit. Fetching every tile
within reach of the start costs **39,089,436 bytes** for four containers against the 12,682,828 this
gate moves today, and fetching only along the walk's own line would cost **24,313,332**. A reader who
meets those two figures cold will compute 38 per cent unused and narrow it.

**THE NARROW RULE CANNOT BE WRITTEN AT ALL, and this is the load-bearing reason:**

    the route rule chooses a heading from 720 candidates
    it chooses using the FIELD and the RINGS
    the field is the COMPOSED one, by the tess lane's own design decision
    so THE WORLD MUST BE COMPOSED BEFORE A HEADING EXISTS

A fetch along the walk's line would be reading a heading that has not been decided yet. On a three
tile row the rule may legitimately choose WEST, and a fetch that guessed east then fails as MISSING
GROUND rather than as a wrong guess about which way a person would go. **That is the expensive
failure mode: it looks like a hole in the pavement**, and this record already carries four separate
evenings of that misreading. The over-fetch is not a tolerance. It is the only rule computable from
what is known at fetch time.

**A second reason, weaker, and marked weaker on purpose.** This lane declined to narrow on transport
grounds: what broke was ONE MESSAGE and not total bytes, streaming bounds the message, and four
containers is three times the work of the same shape. That is true and it is REVISABLE: one
measurement of 39 MB through that path could overturn it, and this lane has not yet made that
measurement. The composition argument cannot be overturned by any measurement, so it is the one a
later reader should find first.

**And four squares on this street have no ground at all**, which the tess lane's piece enumerates
rather than leaving to be discovered. The corridor is a single ROW of tiles, so a walk along it is
four squares from ground that does not exist, north and south. **That is the edge of the world and
not a defect**, and the distinction did not exist before 2026-09-18: without it, a sampler returning
nothing reads as a fault in the pavement, which is the single most expensive misreading this record
has accumulated.

## What the walk from the tile's edge did, measured

The run at a423835d, load 5.27 before and 5.26 after. Due east qualified, the rule chose it, and the
product's own navigation surface refused it. **Five predictions held, one failed, and the one that
failed is the finding.**

**Held:** due east qualified, by the predicted 67 mm. The rule PREFERRED it, on the first criterion
rather than a tie-break. Few headings qualified: **3**, inside the predicted 1 to 15 and under the
predicted 10. None was a diagonal: all three are within one degree of east. `routeObstacleRings` came
back **311 again, exactly**, from the same container, so the rings are a function of the bake.

**FAILED: I predicted the first candidate would have ground and that none would be refused. ALL THREE
WERE REFUSED**, and my reason for the prediction, that a line down a 16.2 m street runs metres from
every ring, was CORRECT AND IRRELEVANT. The nearest ring is 4.2 m away. Distance from rings was never
what mattered here.

    heading   loses support at      position              nearest ring   unsupported
    270000    128.405 m of 131      (384.405, -70.300)      4.205 m       520 probes
    270500    129.245 m of 131      (385.240, -71.428)      4.394 m       352 probes
    271000    129.845 m of 131      (385.825, -72.566)      4.737 m       232 probes

**THE TILE'S EASTERN EDGE IS AT 384.000.** Every one of those positions is past it, and in every case
the unsupported probe count is exactly the remainder of the route: 520 probes at 5 mm is 2.600 m and
131 less 128.405 is 2.595. **SUPPORT DOES NOT RESUME. It ends.** This is not a hole in a street, it
is the end of the ground.

**And here is the structural fact underneath it, which no pose can escape:**

    a tile is                                  128,000 mm across
    the rule requires length plus margin       131,000 mm
    so an east-west route inside ONE TILE can never have ground for its whole length

The gate's field is the inscribed square of a field circle that reaches **3,067 mm beyond the tile**,
and that overhang is precisely what lets the rule qualify a route running off the end of the loaded
world. The rule reads rings and the field. Neither of those is the ground. This is the same 3,067 mm
that made the earlier arithmetic four times too generous, arriving a second time in a different
costume, and it is now the reason the street cannot be walked rather than a rounding error in a
prediction.

**A DEFECT OF MINE, CAUGHT BY ITS OWN NUMBERS.** The halt message I wrote for this case ended: "every
line it offers can still cross ground the carve took away." IT NAMED THE CARVE, and this run's own
figures put the nearest ring 4.2 m away, where the carve acts within about 344 mm. The message
asserted a mechanism the measurement in the same sentence contradicted, and it would have sent the
next reader hunting a clearance bug. Fixed at 83043847: the message now states the position and the
distance to the nearest ring and NAMES NO CAUSE, and the record carries the point where support ends
so a reader can tell a carve from ground that simply stops without redoing the trigonometry.

**Not measured, and not to be inferred from this run:** `frontageBothSidesSamples`, every key, and the
authentication condition, which has still never been reached. I predicted no key would be measured
and was right for the wrong reason: I expected the authentication halt after three captures, and the
run stopped before a single frame was taken.

## What the corridor run did, measured, once the gate could reach the street

The run at cd1d4848, served by `corridor-walk-gate` from this worktree, quiet slot then GPU slot, load
5.07 before and 5.46 after. It reached the street and the street refused it.

**THE THREE NUMBERS THIS LANE OWES, and one of them does not exist.**

- **The ringless halt DID NOT FIRE.** The page was asked and it answered: `routeObstacleRingsRefused`
  is empty and the rings came back.
- **`routeObstacleRings` is 311.** Predicted "low hundreds, not 16", with a stated range of 150 to
  250. THE CLASS WAS RIGHT AND THE RANGE WAS WRONG: 311 is a quarter above the top of it. The
  fixture's 16 was never the scale of a street.
- **`frontageBothSidesSamples` on the winning heading HAS NO VALUE, because there is no winning
  heading.** The rule refused every one of them. Writing 0 here would be a claim about a route that
  was never planned; the honest entry is that the number does not exist for this run.

**The rule's own sentence, which is the result:**

    no heading from the arrival pose clears the route length; the route cannot be walked

That is prediction 2, in the rule's words rather than mine, and it is the outcome the prediction
called most likely. Prediction 1, the decode halt I was most confident in, did not fire: the page
mounted a world at 14.0 s and the Atlas binding was reached at 17.4 s. Prediction 3, the
authentication condition, was NEVER REACHED and remains untested, as the prediction's own ordering
said it would be if an earlier layer refused.

**THE ARITHMETIC SURVIVED AND ONE OF ITS NUMBERS DID NOT, by a factor of four.** I predicted the room
due east from the committed pose as 122,000 mm, reasoning from the tile's eastern edge at 384,000 mm.
The product does not bound the walk by the tile. It states a field, and the gate uses that field's
inscribed square:

    field centre           (320, -64) m, the tile's own centre
    field radius           94.847245611035 m
    inscribed half side    67.06713054842885 m
    east bound             387.06713054842885 m, which is 3,067 mm BEYOND the tile's edge

    room due east from the committed pose    125,067 mm   (I predicted 122,000)
    the rule requires 125,000 + 6,000        131,000 mm
    short by                                   5,933 mm   (I predicted 9,000)

    longest route that would fit             119,067 mm
    minimumWalkedMm demands                  120,000 mm
    WINDOW                                      EMPTY, crossing by 933 mm   (I predicted 4,000)

So the conclusion holds exactly as written, and every margin in it was four times narrower than I
said. The prediction was right for a reason that was only mostly right, and a reader who trusted my
122,000 would have a wrong picture of how close this is. **933 mm is the whole story of this run.**
The gate's route is longer than the street it was built to score, and the shortfall is under a metre.

**What else the record carries.** The container is bound now:
`e59f6cf05d0ff4e09c5f06a8b5c90e4c3e4ea2bc4a9fb0ff62d02b491e6be5f8`, 12,682,828 bytes, tile (2, 0) at
lod 0, city grammar version 2, 56,388 triangles in the render batch, fetched from
`/api/tiles/503afcb6-bfc8-500c-a03b-5b58b01e5e3e/bytes`. `buildingPrisms` is 0, as predicted and for
the predicted reason: the gate hands a generated target no prisms at all. The page states 86 surfaces
with one reason between them, in the product's own words, "No surface_material record dresses this
surface: the tile states that none exists." I predicted 85 undressed facade ground bands; 86 surfaces
share that reason, and I am NOT claiming the two sets are the same one.

**What this run does not say.** No key was measured, because no walk happened. No capture was taken.
Nothing here bears on the ninth key, and nothing here is a corridor result: it is a measurement of
the rule against a pose, and the rule refused.

## The reason the product gave, now in the record, and the wrong fix that came first

The gap above was closed the same evening, while the page that reliably refuses still existed. That
timing is the whole argument for doing it then: the refusal comes from a tile route defect that is
being fixed, and once it is, nothing here shows an error surface on demand. A repair to a path whose
only fixture has gone is a repair nobody can watch work.

**THE FIRST ATTEMPT WAS WRONG AND THE RERUN SAID SO.** I attached the three error lists a completed
record already writes, `exceptions`, `consoleErrors` and `networkLogErrors`, expecting the container
refusal to be among them. It was not. The rerun halted with both `exceptions` and `consoleErrors`
EMPTY while the page was displaying the refusal in front of anyone looking at it:

    "errors": { "exceptions": [], "consoleErrors": [],
                "networkLogErrors": ["network: Failed to load resource: ... 404 (Not Found)"] }

A PRODUCT STATES A REFUSAL TO THE PERSON IN FRONT OF IT, not to a console. I had reasoned about
where a message of that kind usually goes instead of looking at where this product puts it, which is
the same error as reading a copy rather than the code. The empty lists are KEPT rather than removed,
because an empty list is the measurement that says the console carries nothing.

**What the halt record carries now**, read out of the record rather than off a console:

    "productSurface": {
      "worldState": "error",
      "text": "Atlas could not open\n\nTile 7ce4b90f-675b-52dc-b71b-7264aeb00786 refused: .owd
               refused: tessellator_version is not 19; there is no upgrade on read, rebake the tile
               \n\nRetry opening Atlas",
      "textCharacters": 183
    }

The tile, the version the page wanted, and the product's own instruction, in the product's own words.

**Four decisions in it, each one a thing this record has been caught on before.**

- **The gate's words and the product's words stay in separate fields.** `reason` remains the gate's
  sentence, "the product shell to mount a world: the product failed to start"; `productSurface.text`
  is the product's. A record that runs the two together cannot afterwards be asked which half the
  product actually said.
- **Verbatim, with no categories of mine over it.** No parsing, no matching for "tessellator", no
  classification into a kind of failure. The reader records what a person would have read.
- **NULL IS NOT EMPTY.** A missing shell element returns null; a shell showing nothing returns an
  empty text. Those are different failures and a run that reported them alike would hide one.
- **It never throws.** It runs inside the failure handler of the mount wait, so an error escaping it
  would leave the run reporting why the SURFACE could not be read instead of why the PRODUCT would
  not start, destroying the one thing it exists to preserve. An unreadable page records that it was
  unreadable and the halt keeps its own reason. It also runs on a TIMEOUT, because a wait that ran
  out while the page was showing something is a different fact from one that ran out on a blank page.

**The check does not depend on the fixture, and it was falsified rather than trusted.** The tests run
the harness's OWN page-side expression against a faked document, so the slice, the character count
and the absent-shell branch under test are the ones a run sends to a real page; a test that rebuilt
that shape itself would have been checking its own arithmetic. Six deliberate breaks, each restored
from a committed tree and each refused by the test that claims that property: no cut at all; a
character count that reports the cut length rather than the true one; an absent shell reported as a
shell showing nothing; a category of the gate's own added beside the product's words; the reader
throwing instead of recording; and the sanitiser skipped, which is the one that would put this
machine's paths into a record.

**What this does not touch.** A halt record is written only when a run halts, and a run that halts
scores nothing, so nothing here can reach a scored run. The three numbers this lane owes are still
unmeasured and the corridor is still blocked on the route defect.

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
  expectation that they FAIL on this tile stays untested, and that is a fact about the tile
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
