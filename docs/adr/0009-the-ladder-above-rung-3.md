# ADR-0009: How the ladder earns rungs 1 and 2, and what a posed rung 3 is

- Status: **ACCEPTED; production rung 3 implemented 2026-09-04.** D1, D4, D6, D9, D10, D11 and
  D12 now run end to end through the normal ingest and separate scene-worker path. D2, D3, D5,
  D7 and D8 remain decisions for future rung-2 and rung-1 producers. No authorized real dense
  capture set was available, so no representative registration or quality result is claimed.
- Date: 2026-09-03
- Deciders: Exulanica build. Four independent proposals were scored by judges on honesty, on the
  metric frame and query path, and on what could be implemented now on this machine.
- Supersedes: nothing wholesale. It corrects two sentences in place, named in D2 and D3.
- Related: [product-specification.md](../product-specification.md) section 5;
  [reconstruction-findings.md](../reconstruction-findings.md);
  [scene-reconstruction-operations.md](../scene-reconstruction-operations.md);
  [corridor-navigation-artifacts.md](../corridor-navigation-artifacts.md);
  [gsplat-scene-jobs.md](../gsplat-scene-jobs.md);
  [adr/0008-generated-geometry.md](0008-generated-geometry.md);
  [adr/0010-opm-2.md](0010-opm-2.md).

## Context

The ladder has four rungs and, until this work, one producer. `decide_rung` awards rung 3 or rung
4 from one photograph. The controllers for the rungs above it exist and are contract tested, and
until now none of them had a backend: `pose` shelled out to a `colmap` binary that is not
installed anywhere in this project, and `splat` delegates to a container entrypoint nobody has
built. Nothing in `exulanica.ingest` calls any of them, so no rung above 3 has ever been published.

Three measurements from [reconstruction-findings.md](../reconstruction-findings.md) shape every
decision below.

**Pose recovery is cheap and local.** Eight views register in 3 to 4.5 seconds on this laptop's
CPU, with no CUDA. Three adjacent frames are the minimum that registers under COLMAP's defaults.
So the expensive-sounding half of the ladder is the affordable half, and it runs where the
photographs already are.

**Scale is the hard part, not pose.** COLMAP's frame is scale ambiguous, and the pose controller
requires a measured scale that nothing produces. MoGe-2 recovers metric depth per image, so it is
the obvious candidate. Measured against a known scale it was 9.0 percent high using MoGe's own
field of view and 18.1 percent low when the true field of view was supplied, while the spread
across images stayed near 3 percent in both cases. **Agreement between views is precision, not
accuracy.** A spread gate would have passed an estimate that was a fifth wrong.

**One viewpoint covers about three quarters of its own box and fills most of what it sees.** The
answer to an empty region is another photograph, not a better renderer and not a generator
(ADR-0008).

## Decision

**D1. The gate is layered, and `decide_rung` does not grow branches.** It sees one prediction from
one photograph and keeps awarding 3 or 4. Rungs 1 and 2 are facts about a set of photographs and
cannot be read off a single frame however the branches are written, so a separate pure scene gate
composes the pose receipt, the scale receipt, the coverage analysis, the corridor receipt and the
splat receipt where one exists into 1, 2 or 3, recording every reason. It stores its own decision
as a digested artifact naming every receipt digest it read, so a rung can be re-evaluated from
stored receipts without re-running COLMAP.

**D2. Rung 2 does not require a splat, and this is a correction to the specification rather than a
new ladder.** The specification's rung 2 row describes the producer as "the same splat" with thin
coverage. The code already disagrees with it in the right direction: `navigation.py` publishes
`published_rung = 2` whenever the corridor artifact's own measurements are accepted, and a splat
appears nowhere in its inputs. What defines the rung is its fourth column, what the user gets: a
camera move along the path actually walked, with real parallax and freedom to look around. Two
substrates deliver that column, and the artifact records which:

| Substrate | What is drawn | What the corridor binds to |
| --- | --- | --- |
| `splat` | An accepted rung 1 splat whose coverage is one sided or thin | the SOG delivery digest |
| `posed-relief` | The posed monocular point maps of D6 at their recovered cameras | the placement record digest |

This matters because it is the difference between rung 2 needing a GPU that has never been
provisioned and rung 2 running on a laptop in seconds. The substrate is carried into the displayed
sentence so that nobody is told posed relief is photoreal. `SplatQuality.fallback_rung` stays
`Literal[3]`: a failed splat does not become a corridor by falling over, it becomes a corridor only
if a corridor was measured.

**D3. A scene-level threshold that changes only the label leaves the idempotency key. A
per-capture one does not, and this distinction is the whole decision.** Today every tunable number
lives in stage params, so editing one regenerates every artifact. That is right for a parameter
that changes the bytes, such as the silhouette threshold. It is also right, today, for the rung 3
threshold, and moving that one would be a mistake: the per-capture rung is a persisted assertion
written once during ingest, and the stage returns early when it reuses an artifact, so a threshold
outside the key would change no stored rung at all and the displayed rung would silently disagree
with the profile that supposedly set it. **The rung 3 threshold stays in stage params until a
recompute path exists for the assertion.** Only the scene gate's own thresholds, which are read at
derivation time from stored receipts, move into a frozen digested profile that the gate records
alongside its decision, so a scene threshold change is a named re-label rather than a silent one.

**D4. An unmeasured threshold is `None`, and `None` blocks the rung it guards.** This is the rule
`quality.py` already applies to observations, applied to thresholds: a missing measurement is not
a missing check. The gate refuses with a reason naming the field. It converts the anti-guessing
protocol from a convention that a reader must honour into a structure that fails. Every threshold
this design needs is unmeasured today, so on the day it is built it publishes rung 3 with reasons,
which is the honest state of a pipeline whose numbers do not exist yet.

**D5. The metric scale is its own receipt, it never opens the query path, and it does not relax
the splat gate.** The scale receipt binds to the pose receipt's digests and records its method by
name, so a human-measured scale and a model-derived one are distinguishable facts rather than one
number. A model-derived scale may size corridors, agent radii and clearance, where a 10 percent
error widens a corridor by 10 percent and is capped and reviewable. It may not answer a spatial
question: `scaleIsMetric` stays false and `asMetricLocal` keeps returning null until a scale is
validated against a distance somebody physically measured. Precision is not accuracy, and R-48 is
about what may be measured across, not about how confident the model sounded.

Two things follow that are easy to get wrong, so they are stated rather than implied.

- **The splat controller's requirement for a reviewed positive measured scale is not relaxed.** It
  is the single place that requirement is enforced, and a scale receipt may substitute for the
  manifest scale there only when the receipt records a physical reference. A model-derived receipt
  never promotes a scene to a shared metric frame.
- **Agreement between views is not the acceptance test.** The measurement that motivates this
  decision had a three percent spread around a nine to eighteen percent error, so a spread gate
  would have accepted it. A model-derived receipt is accepted for corridor sizing on the basis
  that its error is bounded and its effect is capped, and it is recorded as unvalidated. Making
  spread the criterion would reintroduce, as the gate, the exact inference this decision rejects.

**D6. A posed multi-view set is a rung 3 sub-state over unchanged member files.** *Written as
"unchanged OPM/1 files"; ADR-0010 was built on 2026-09-03 and the container is now OPM/2. The
decision is unaffected, because what it turns on is that placement does not change the FILE, and
OPM/2 D7 keeps placement out of the container for the same reason.* The specification
already says rung 3 point maps are "placed at recovered poses where they exist". Placement is
therefore not a container change: the files stay byte identical with their origin viewpoints, and
a separate digest-bound placement record names its members by content hash and says where each
stands. Each shell is rescaled to the scene consensus, because per-view scale differed by up to
20 percent in measurement, and a shell that disagrees with its neighbours is left on its anchor
rather than drawn twice. The cross-language fixture is not regenerated by this decision.

**D7. Coverage is measured, and every coverage number carries the convention that produced it.**
The same committed point map yields 27.1, 35.4, 36.1 or 51.4 percent at a 12x12 grid depending
only on the support floor and the bounds rule. A number whose definition travels separately from
it is a number that will be compared with the wrong thing, so the grid, the bounds rule and the
support floor are recorded fields of the coverage record rather than constants in a module. The
analysis reads the sparse model and the scale receipt and never splat pixels or opacity, which is
the rule the corridor document already states.

**D8. Corridor inputs are measured from triangulated geometry, per side of the path, and
monocular geometry may only narrow a corridor.** Clearance at a sample is evaluated separately in
the left and right sector of the camera forward, as the smaller of the distance to the nearest
well-tracked sparse point and the distance to the nearest supported monocular point, and **a
sector with too few supported points is assigned clearance zero.** Unseen space therefore
contributes no width at all. That is the designed void enforced in the artifact rather than in the
shader. Slope is centreline slope between consecutive camera centres and is named as such, because
no ground surface is identified anywhere in this pipeline and relief never becomes an invented
floor. The look envelope is derived from the members, half the smallest horizontal and vertical
field of view across registered cameras, so the envelope provably never leaves what the cameras
saw and needs no unvalidated constant.

**D9. A fact about a set needs a subject, and deletion has to reach it.** Every artifact today is
keyed to exactly one source blob, which is what the purge cascade and the export projector join
on. A pose receipt, a splat and a placement record are facts about N photographs and have no home
in that scheme. They get one: a scene identity with an explicit many-to-many source relation, a
scene-level rung assertion whose support spans are the whole-image spans of every registered
member, and a tombstone path that reaches a scene artifact through any of its members. **No
scene-level artifact ships before the test that deletes one of N members and asserts the bytes are
released and the export changes.** *BUILT 2026-09-03. The identity is migration 0024's
`reconstruction_scene` and `reconstruction_scene_member`, both append-only because a membership that
could be edited afterwards is a deletion that could be undone by an UPDATE. The tombstone path is
`tombstone_blocks_scene`, one predicate in SQL, reaching a scene through ANY member. The no-ship
test is in `tests/test_scene_identity.py`. What is NOT built is the scene-level rung assertion,
which is the remaining clause of this decision, and no producer writes a scene, so nothing ships one
yet.* The reduction over a group changes with it: worst-first stays
right for panels, because a hole is a hole, and is wrong for a scene, because four unregistered
photographs are not holes in a corridor, they are photographs that open as photographs.

*BUILT 2026-09-04. The preceding "not built" state is now closed. Migration 0025 seeds
`reconstruction_scene_rung_is` without the per-frame `valid_fraction` carried by
`reconstruction_rung_is`. `record_scene_rung` publishes rung 3 as an inference supported by the
whole-image spans of the registered members, records the complete member count and both reasons
the receipt gate cannot yet award rungs 1 or 2, and relies on the existing support rule to refuse
a scene nobody registered. The assertion guard and the read both ask `tombstone_blocks_scene`, so
deleting an unregistered member withdraws the claim even though that member supplied no support
span. The world-package projector filters scene assertions from both copies at the same source,
and its `rung_claims` subject resolves to the same pseudonym as the exported scene.*

*BUILT 2026-09-04. The remaining producer clause is now closed. Migration 0026 adds an immutable
ordered job-member set, deterministic scene and job identities, a recorded selection-policy
digest, and renewable leases. Normal `run_scene_grouping` applies the explicit
`exulanica.scene-group-pose-selection/v1` policy and queues every group of at least three members.
The scene worker records registration as an outcome, prepares the completed scene and artifacts
behind tombstone guards, flushes receipt bytes under purge-compatible session locks, then
atomically publishes the rung assertion and successful job state. Graph and package readers hide
the retryable prepared state. The policy records its unvalidated limits rather than presenting
scene grouping as a geometric fact.*

*CORRECTED 2026-09-04. Automatic selection now waits until every member has a current point map.
Migration 0027 binds each job to those exact artifact ids and content digests plus all scene-stage
versions. A changed point map or stage binding creates a new immutable build under the same stable
scene identity. Per-build registration rows retain both outcomes, while `current_job_id` advances
only with successful publication. The graph and package no longer select a successful job by
timestamp. They follow the explicit pointer. The production derivative-worker image now contains
MoGe and Compose configures it, closing the deployment path that previously queued pose before the
depth artifacts it was meant to place existed.*

**D10. Nothing above rung 3 reaches a viewer until something serves geometry at all. BUILT
2026-09-03.** The paragraph is left in the tense it was written in, and what was built follows
it. There is no
production path by which any point map reaches the renderer: no route serves artifact bytes, and
the only loader in the workspace is a development preview, while the app's own comment claiming
that production reads point maps from an API describes an implementation that does not exist. So a
posed set, a corridor and a designed void would all be built against nothing. **The delivery route
is the first item of work, before any of the above**, and it carries the authentication and digest
rules that the residency design already assumes: bytes in hand, a bearer in the header, and the
content hash verified against the descriptor that named it.

*What was built.* `GET /geometry` is a descriptor list keyed by capture, carrying the container,
the byte size and the SHA-256; `GET /geometry/{artifact_id}` is the bytes. The client fetches with
the bearer in the header, hashes what arrived, and compares it to the descriptor rather than to
the response's own `ETag`, which would be checking the response against itself. Neither route
ships an island id, because ADR-0005 leaves that to the client, and neither ships a rung, because
the recorded claim already arrives on the graph payload and a second copy on the wire is the
divergence D11 objects to.

Three properties the route has that this record did not ask for, each forced by the clause about
the digest. It refuses range requests, because a client cannot check a fragment against a digest
of the whole, and it is the only byte route in this API that does. It answers **410** rather than
404 for something the user deleted, asking `tombstone_blocks_capture` rather than
`artifact.purged_at`, so a deletion reaches the read before the purger reaches the bytes. And a
page without `SubtleCrypto` loads no geometry at all, because the third clause of this decision is
not a preference.

*What it did not settle, and two things it changed the shape of.* A region attempts one point map
and any others it holds are counted as `unplaced`, because D6's placement record does not exist.
That is the first thing this now unblocks.

**D6 and ADR-0010 have an ordering constraint that neither record names, and this route is what
makes it visible.** D6 binds a placement record to its members by content hash. ADR-0010 D9 is
"refuse and regenerate", and the container string lives in the depth stage's params, which are
inside `params_digest` and therefore inside the idempotency key, so an OPM/2 bump writes a new
artifact row with a new `content_sha256` for every capture. Any placement record written between
D6 and OPM/2 would then name hashes no descriptor list will ever return, and D9 offers no
regeneration path for a record it did not anticipate. **Either OPM/2 goes first, or D6's record
carries a regeneration path.** What the delivery route contributes is that the by-id byte route
deliberately does NOT filter `superseded_by`, so an old row stays fetchable; that is the only
reason a stale record would degrade rather than break, and it is documented in
`exulanica/graph/geometry.py` as a decision rather than left as an omission.

*DISCHARGED 2026-09-03. OPM/2 went first.* ADR-0010 is built, the depth stage's params now read
`"container": "opm/2"`, and every point map an existing corpus held is refused by name and
rewritten under a new idempotency key. So D6 may be built without a regeneration path for a
record written before the bump, because no such record exists: nothing has ever written one. The
constraint is retired rather than solved, which is the cheapest of the two outcomes it offered,
and it is retired only for this bump. **A third container version would recreate it**, and at
that point D6's records WILL exist and the regeneration path becomes the only option left.

*BUILT 2026-09-04. D6 now has its production delivery contract. `GET /graph` includes one
validated reconstruction-scene record with the exact member order, registration outcomes, receipt
digests, per-map descriptors and transforms, recorded and displayed rung fields, substrate, and
exclusions. It is read in the graph's repeatable-read snapshot. The server reproduces the gate and
validates the placement against the live artifact rows before any transform crosses the boundary.
The browser authenticates and verifies each point map separately and the PlayCanvas binding draws
one transformed cloud per accepted map under one scene root.*

**D11 is now larger than it was, not smaller.** `buildScene` already lets loaded geometry outrank
the recorded rung, on the stated grounds that "a region holding a decoded point map is standing in
rung 3 geometry right now". That was true of one preview fixture and is now true of every
production region that gains geometry, and `Island.rung` is a mode switch rather than a label: it
selects the world recipe, the movement model, the arrival pose and whether the source-first grove
is built. So the scene graph's rung is what the renderer draws, and the rung D11 has to display is
what the region earned, worst-first across its captures. **Those are two different numbers and
D11 has to name both**, which the record does not yet do.

**D11. The rung is displayed, from the recorded claim rather than from the container.**
Specification 5.1 says the rung is shown as part of a region's identity and calls it the honesty
feature. It is not shown anywhere: the four rung sentences in the app's copy table are referenced
by no render site, a second and divergent copy table exists in the formation package, and the
server's terminal formation event hardcodes rung 4.

**The deeper problem is not the missing render site, it is where the rung comes from.** The app
derives a region's rung by reading the field off the decoded point map, and that field is pinned
to 3 by the container. So the client can only ever conclude rung 3 for a region with geometry, no
matter what the pipeline measured, and a scene gate that awarded rung 1 or 2 would change nothing
a viewer sees. The rung has to arrive as the recorded claim, which is where the gate writes it.
**This is the prerequisite for every other decision here**, because a ladder that earns a rung
nobody sees has added a claim without adding the honesty that justifies it. One copy table, one
render site, the recorded assertion rather than the container constant, and the measurements shown
beside the label.

*BUILT 2026-09-04. The one render site is the Atlas reconstruction disclosure. Its authoritative
copy names the scene's `recordedSceneRung`, the client's `displayedRung`, and the current
`renderingSubstrate` separately. It obtains the recorded value and withholding reasons from the
assertion-backed graph record. Geometry load success changes only substrate availability and the
displayed fallback. It cannot promote the recorded rung.*

**D12. A pose job directory holds photographic derivatives outside the deletion cascade, and this
is a gap the pose backend just made real.** A COLMAP job writes a working database holding SIFT
descriptors of every image it was given, alongside the sparse model, in a directory keyed by the
manifest digest and known to nothing else in the system. Nothing registers it as an artifact, so
no tombstone reaches it, and descriptors of a photograph containing a person are exactly the kind
of derivative the privacy model expects to be destroyed. **The job directory is deleted when the
receipt is accepted, and until a scene artifact exists to carry it, no pose job may run over a
capture set outside a scratch location that is purged on a timer.** This is stated as a decision
rather than a future concern because the executor that makes those directories now exists and
runs.

*One detail found while building D10, recorded here because it changes what implementing D12
means.* "The job directory is deleted when the receipt is accepted" is not implementable as
written: `receipt.json` and `manifest.json` live **inside** the job directory, and they are what
lets a completed manifest "return its verified report without invoking COLMAP again". Deleting
the directory would destroy the resumption and reuse path along with the descriptors. The
separation a fix has to keep is between the working database, which is a derivative of
photographs, and the receipt, which is a statement about a computation;
`tests/test_geometry_delivery.py` pins that they are still two different files and fails if
either moves. The rest of D12 stands: nothing registers the directory as an artifact, so no
tombstone reaches it.

*BUILT 2026-09-04. Durable pose, placement and gate receipts now live in the content-addressed
store, while staged images, descriptors, the COLMAP database and sparse working files live only in
locked scratch. Handled success, failure and cancellation remove scratch. Process death retains
checkpoints for lease reclaim; an age-gated startup sweep removes only inactive, unprotected,
canonical workspace/job directories. Tombstoning any job member cancels the row and the running
controller. A process death on the final allowed claim is terminalized as `claim_exhausted` before
cleanup, closing the expired-running edge without deleting resumable work from an eligible retry.*

## Alternatives rejected

- **Grow `decide_rung` with rung 1 and 2 branches.** Its input is one prediction; it would have to
  take receipts it cannot relate to the photograph, and the test that pins it to `{3, 4}` would be
  broken by design rather than by evidence.
- **Flip the splat gate's fallback so a thin splat publishes rung 2.** Quickest, and it awards
  movement that no corridor validated. The corridor is what measures the envelope; a splat's
  failure to be good enough for rung 1 says nothing about where a walker may stand.
- **Derive the rung at read time from raw facts, with no stored gate decision.** Attractive because
  a threshold change re-labels without regenerating, which D3 adopts for label-only thresholds. As
  a whole design it was rejected because a rung with no stored derivation cannot be verified from a
  package by a third party, which is what the World Memory Package is for.
- **One artifact row per contributing capture, all sharing a content digest.** Deletion closure
  becomes free and the identity scheme is untouched. Rejected because the count of rows becomes the
  count of photographs times the count of scene artifacts, and because a set with no identity has
  no subject for a scene rung claim; the many-to-many relation is the thing that is still right at
  a hundred thousand photographs.
- **Let MoGe-2's metric scale set `scaleIsMetric` once views agree.** Rejected by the measurement
  that motivated it: agreement was 3 percent while the error was 9 to 18 percent.

## Consequences

- Rung 2 becomes reachable on a laptop, from three or more overlapping photographs, with no GPU
  and no trained splat. Rung 1 stays blocked on a GPU job that has never run and on a resumable
  trainer that does not exist.
- The scale of the world this is designed for is not the scale the interface currently admits. The
  layout solver refuses more than five islands, and this record does not lift that: a design that
  is right at a hundred regions is being chosen deliberately while the cap stays where it is,
  because lifting it needs a layout measurement that nobody has made.
- Every rung above 3 published on the day this is built is published as rung 3 with reasons,
  because every threshold it needs is unmeasured. That is the design working, not failing.
- The fraction of a real library that can reach rung 2 is unknown and is the number the product
  most needs. Published proxies bracket it between 1.6 and 25 percent.
- Displaying the rung is now on the critical path rather than beside it.

## What must be measured before this is final

- The MoGe-2 to COLMAP scale ratio on photographs rather than renders, per image and across
  images, which decides whether a scale receipt can ever be more than an ordering hint.
- pycolmap on real photographs on this machine: registration rate, the minimum image count that
  registers under defaults, and wall time at full resolution for 8, 20 and 50 images.
- The filled fraction of the frustum union for a real multi-photograph capture, against the
  single-photograph decomposition already measured.
- Every threshold named in D3 and D4, each against a corpus that does not exist yet.
- ~~The deletion test of D9, before any scene-level artifact ships.~~ **BUILT 2026-09-03**, both
  halves, in `tests/test_scene_identity.py`: three photographs, one scene over them, and the middle
  one deleted through `insert_tombstone`. The bytes half asserts the receipt is enqueued, that
  `purge_releases_bytes` releases it, that the purger destroys it and the store agrees, and that the
  two surviving photographs keep everything of their own. The export half asserts the receipt and
  its scene are in `reconstruction/artifacts.json` BEFORE the deletion and absent after, on the
  component payload rather than on the Merkle root, because any tombstone moves the root by itself.
  Two controls sit beside them: a second scene the deleted photograph was never in survives both,
  and a second workspace standing behind the same receipt bytes stops them being destroyed until it
  deletes too.
