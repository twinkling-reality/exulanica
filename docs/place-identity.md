# One place across captures and time

Design note, 2026-09-06, with the schema decision added 2026-09-07. **No real cross-capture
alignment has run. The vocabulary and the tables below are decided and the geometry is measured
against a synthetic fixture; nothing here is a measurement of two real captures.** Roadmap Phase 10
capability 3, and experiment FR-2 made product.

## What the product is missing

Every reconstruction in this repository is a **scene**: one set of photographs, taken on one
occasion, reconstructed into one recovered frame. Photograph a kitchen today and again in a month
and the system holds two scenes that share a subject and share nothing else. Their coordinate
frames are unrelated, their regions are separate, and no query can ask what changed.

That is the gap between a reconstruction pipeline and a memory. A generative world model reading
this system should be able to ask for a place and get its history, not get whichever capture
happened to be indexed. Persistence across time is the thing a stateless model most lacks and the
thing this product exists to supply.

## The one hard constraint, stated first

**Retained receipts alone cannot align two captures, and no amount of care makes them.**

`docs/scene-placement-alignment.md` records the rule: "No learned feature descriptors are
persisted." What the pose stage keeps of COLMAP's output is a bounded sample of tracks per image:
`[point id, source x, source y, world x, world y, world z, reprojection error, track length]`. Point
ids are global **within one reconstruction** and mean nothing across two. Two captures of one
kitchen produce two disjoint id spaces over two unrelated coordinate systems, and matching them
would need the descriptors that were deliberately not kept.

So cross-capture alignment is not a post-hoc computation over stored artifacts. It is a
**reconstruction**, run over the union of both capture sets, exactly as experiment FR-2 specifies:
"Jointly reconstruct two consented sets and inspect one connected model plus metric consistency."

This is not a workaround. Persisting descriptors would mean storing, per photograph, a
representation whose purpose is to recognise that same content elsewhere, which is the shape of the
thing the privacy layer refuses for people. Re-running the reconstruction is more expensive and
keeps that refusal intact.

## What a place is

A **place** is an entity that owns an ordered series of scenes and one shared coordinate frame.

- It is **not** a scene. A scene stays exactly what it is: one immutable capture set, its own
  recovered frame, its own receipts, its own rung. Nothing about an existing scene changes when it
  joins a place, because a scene's receipts are bound to their inputs and a place cannot be an
  input to a reconstruction that already happened.
- It is **not** a region. A region is the world's spatial authority, and it stays so. A place tells
  a region which scenes belong to it and how their frames relate; the region still decides what is
  drawn.
- It carries **versions by capture time**, and every version is a scene that already stands on its
  own. A place is a join, never a merge: no bytes are combined, no receipt is rewritten.

### Identity comes from a joint reconstruction, never from a name

Two scenes join a place when a joint reconstruction over their union produces one connected model
and the resulting relative transform validates. Not when a user calls them both "kitchen", and not
when their timestamps or coordinates are similar. A place asserted from a label would be a claim
the system cannot support, and the first time it were wrong it would silently show a visitor one
room labelled as another.

The user may **name** a place and may **refuse** a proposed join. The user may not assert one:
naming a thing does not make two reconstructions share a frame.

## What a place is in the schema, decided 2026-09-07

The section above says what a place is. This one says where it lives, because the word already
means something else in this schema and a durable entity has to be addressable before anything can
be built on it.

**A place is a new durable plane of three tables: `place`, `place_version` and `place_alignment`.
It is not an entity, it is not a region, and it is not a property of a scene.**

### Why not the entity table

`entity` already carries a `class` drawn from `occurrence_class`, and that enum already contains
`'place'` (`exulanica/migrations/0001_spine.sql:75`). An entity of class `'place'` is not only
expressible, it is reachable in production, so putting the durable place there would have been the
cheapest change: it inherits naming, merging, confirmation and the identity ledger, and it would
have needed no new plane at all.

It is the wrong plane, for three reasons that compound.

The identity plane establishes identity by linking **occurrences** to entities through
`entity_link`, whose `basis_digest` records "WHICH signals were shown"
(`exulanica/migrations/0001_spine.sql:560`). A place's identity comes from a joint reconstruction
over two capture **sets**. That is not an occurrence in any one photograph, so binding it through
`entity_link` would mean inventing an occurrence to stand for a fact about a set, and the invented
row would then be indistinguishable from an observed one.

Worse, the entity plane is the machinery that turns a *name* into identity: `display_name` is
"written ONLY via a 'user' assertion" (`exulanica/migrations/0001_spine.sql:544`), and
`assertion_kind` reserves `'user'` as "the only kind permitted to carry a name"
(`0001_spine.sql:69`). That machinery is correct for what it does, and the section below keeps it.
It is the wrong machinery for this: a place asserted from a label is a claim the system cannot
support, and putting the geometric place on the same table would put both identities behind one
`entity_id`, so a place that a user had merely named would be indistinguishable from one two
reconstructions had agreed on. The first time the two disagreed, the world would show a visitor one
room labelled as another with no receipt to contradict it.

Third, and smallest: a similarity transform on an entity row would be the first geometry that table
carried.

### Why not a column on the scene

Promoting `reconstruction_scene` to carry a nullable `place_id` and a version ordinal looks like the
least new surface. It is refused by the database, not by taste.

`reconstruction_scene` carries `tg_reconstruction_scene_append_only`. MEASURED 2026-09-07 by reading
`pg_proc.prosrc` on the permitted instance: the trigger permits exactly one UPDATE, advancing
`current_job_id` to a job that has already succeeded, and it identifies that case by requiring
`to_jsonb(new) - 'current_job_id' = to_jsonb(old) - 'current_job_id'`. Setting a `place_id` on an
existing scene row changes a key outside that exception and is refused. So option C is not the cheap
one: it costs the append-only guarantee that protects every scene in the repository, and it would
buy an inversion of ownership the roadmap explicitly asks against.

It is also wrong on its own terms, twice. A place needs a shared frame, an ordered series and a
series of alignment receipts, and none of those is a property of any one scene. And a scene's
identity **is** its member set: `scene_id_for` is a uuid5 over the digest of the sorted member
capture ids (`exulanica/evidence/scene.py:105-112`), so a place cannot be modelled as a scene that
grew, because adding a capture does not extend a scene, it names a different one.

### The collision with `occurrence_class`, and how it is closed

Two things named `place` in one schema is how a query silently returns the wrong one, so the word
has to resolve. The first draft of this decision closed it by refusing an `entity` row of class
`'place'` outright, on the belief that such an entity could only ever be a place recognised from a
label, which this note forbids. **That belief was wrong and the refusal is withdrawn.**

What is actually there, checked 2026-09-07: the vision stage emits a whole-image occurrence of class
`'place'` for every photograph whose model output carried a proposed place, alongside a `place_is`
assertion (`exulanica/ingest/stages/vision.py:323-343`). Naming any occurrence creates an entity
whose class is copied from it (`exulanica/identity/decisions.py:107`), and 0002's naming guard
already requires an active user assertion before any entity may carry a name
(`exulanica/migrations/0002_naming_and_admission.sql:246`). So an `entity` of class `'place'` is a
live product path: it is a place **a person named**, admitted by the same guard that admits every
other name. `tests/test_selection.py:163` has said so in a comment since long before this note
existed: "Places are entities too, and the same mechanism names them." Refusing it would have
deleted a working capability to solve a vocabulary problem, which is the wrong trade, and it would
have been made on a false premise.

So there are two real things, and they get two planes rather than one plane and a prohibition.

- An `entity` of class `'place'` is **a place a person named**. Its identity comes from a user
  assertion over an occurrence in one photograph. It has no frame, no versions and no geometry.
  The epistemic vocabulary already says as much about the predicate behind it: `place_is` is "a
  label for where a photograph was taken", a proper noun a model is permitted to propose
  (`exulanica/epistemics/vocabulary.py:94-107`). A label is the whole of what that plane claims.
- A `place` row is **a place the geometry established**. Its identity comes from a joint
  reconstruction over two capture sets, exactly as this note's identity section requires, and never
  from a name.

**Neither creates the other, and that is the invariant worth testing.** Naming a place occurrence
must not bring a `place` row into being, because a label is not a measurement. Accepting an
alignment must not mint an entity, because geometry is not a name. It is asserted both ways by
`tests/test_place_plane.py::test_naming_a_place_a_person_saw_creates_no_place_row` and
`::test_admitting_a_place_version_creates_no_entity`, the first driving the real `name_occurrence`
path rather than a raw insert.

An earlier draft of this note proposed a nullable `place.named_entity_id` linking the two planes,
and 0038 does not carry it. The link is not needed to keep them separate, which is what the tests
above establish, and a column would have been a second place to look for a place's name. When
naming a place is wanted, it belongs where every other user statement in this system belongs: an
assertion whose `subject_ref` names the place, under the guard 0002 already applies to names. That
is not built, and this note does not claim it is.

The ambiguity that remains is a reader's, not a query's, and the identifier closes it: `place_id`
names the geometric plane and nothing else, while the identity plane uses `entity_id` everywhere and
has never used `place_id`. A column called `place_id` therefore has exactly one referent, which is
the property the warning was actually about.

`region` is untouched. A region stays the world's spatial authority; a place tells a region which
scenes belong to it and how their frames relate. `person_region.region_key` is a 16x16 grid cell,
and the place plane has no grid key and no column called `region_id` or `region_key`, so none of the
three existing meanings of "region" is reused.

### The three tables

`place`. One row per durable place: `place_id`, `workspace_id`, `created_at`. That is all of it,
and the emptiness is the decision. There is no `display_name`, because naming is the identity
plane's job and it already has a guard; no `deleted_at`, because the table is append-only and a
place's liveness is derived from its anchor's; and no position, for the reasons in "Where a place
is" below. The id is allocated once and never derived, the same choice `entity` makes for the same
reason: a place's identity has to survive its member set growing, which is exactly what
`scene_id_for` cannot do.

`place_version`. One row per scene in the place: `place_id`, `scene_id`, an `ordinal` by capture
time, the `ordered_by_utc` it was ordered on with the `ordered_by_basis` that produced it,
`frame_hops`, the `admitted_by_alignment_id` that admitted it, and `created_at`.

**No transform column.** The similarity between a scene's own recovered frame and its place's frame
is a measured number with held-out residuals behind it, and this repository keeps measured numbers
in digest-bound artifacts rather than in columns nothing recomputes, exactly as
`point_map_placement` already does. A version names the receipt that measured it and the read seam
reads the transform from there, which is also what lets a receipt whose bytes are gone be reported
as `unavailable` rather than silently substituted with identity.

**The anchor is a row, not a column.** A place's shared frame is its anchor scene's own recovered
frame, so the anchor is simply the version with `frame_hops` 0 and no admitting alignment, and a
partial unique index enforces exactly one per place. Putting an `anchor_scene_id` on `place` as
well would state the same fact twice and let the two disagree.

`frame_hops` is the honesty column. It is 0 for the anchor, 1 for a scene whose transform to the
anchor was measured by a single joint run, and n for one composed through a chain of them. A place
with three scenes has two accepted alignment receipts, and the third scene's frame may have been
measured against the second rather than against the anchor. Without this column that composition is
invisible and a reader would take a composed transform for a measured one.

`unique (workspace_id, scene_id)` enforces the rule this note already states: a scene belongs to at
most one place, because two places claiming one scene would be two coordinate frames claiming one
set of photographs.

The capture time needs its own sentence, because **a scene has no capture-time column**. The only
time available is `capture.started_at` across the scene's members, which 0001 itself calls a best
estimate only and which is nullable, and `exulanica/graph/geometry.py` already treats it as a
presentation ordering rather than a fact. Ordering versions by a live join on it would make a
place's history rearrange itself when a capture's metadata is corrected, and would have no answer at
all when it is null. So the time is **recorded at bind time**, with the basis that produced it, and
the ordinal is fixed then. A version whose time could not be established is admitted with a null
time and the `unavailable` basis, which is a visible state rather than a silent guess.

`place_alignment`. The receipt of one joint reconstruction: the two scenes, the member digest of the
union, the versioned policy digest from `PLACE_ALIGNMENT_POLICY`, the digest of the joint model,
whether it was accepted, the refusal reason when it was not, and the artifact holding the numbers. A
refused alignment is a row like any other, because a measured refusal recorded as a fact is a
result. The three reasons are a check constraint rather than free text, so a refusal nobody
anticipated fails loudly. **No threshold appears in any constraint**: those numbers are versioned
engineering choices measured against a synthetic fixture, and a threshold frozen into the schema
would have to be right before anybody could measure it.

### An artifact may now name a place

`artifact` carries `an_artifact_names_one_subject`, which today reads
`CHECK ((source_blob_sha256 IS NOT NULL) <> (scene_id IS NOT NULL))` (read from the live schema,
2026-09-07). An artifact names exactly one subject: a blob or a scene.

A place alignment's subject is a **pair of scenes**, which is neither. Attaching its receipt to one
of the two scenes would be a lie about what was measured, and the lie would be invisible from the
scene side. So 0038 adds a nullable `place_id` to `artifact` and generalises the constraint to
exactly-one-of-three. The invariant is unchanged and every existing row still satisfies it; what
changes is that a place is now a subject a build may be about.

### Where a place is, decided 2026-09-07

**A place derives its position from its photographs and stores none. Migration 0038 needs no
amendment for this.**

Every capture ingested with EXIF GPS already writes a durable `gps_position_is` claim.
`exulanica/ingest/exif.py:157-167` defines `GpsFix` as latitude and longitude in integer
ten-millionths of a degree, deliberately never a float, and `exulanica/ingest/stages/intake.py:151`
writes it for every capture that has one. MEASURED 2026-09-07 on the permitted instance: the
retained corpus holds **zero** such claims, because the bowl and volcanic sets are published
datasets with EXIF stripped. The signal is real, it is already recorded, and nothing has exercised
it.

#### Why not a column on `place`

This is refused on deletion, and decisively. `place` is append-only, so a stored `lat_e7` and
`lon_e7` could never be corrected. When a member capture is withdrawn, the tombstone guards
already take its geometry and its observations out of every read; a stored position derived from
that photograph's EXIF would survive as two integers with no lineage, still saying where a
withdrawn photograph was taken. That is a retained inference over withdrawn evidence, which is what
the withdrawal machinery exists to prevent, and it would be invisible: an integer pair on a row
looks like configuration, not like a derived fact somebody has a right to remove.

`gps_position_is` is also **functional** (`exulanica/migrations/0006_functional_predicates.sql:14`),
so its claim can be superseded or retracted. A column cannot follow that; a read can.

#### Why not its own receipt

A receipt pins an answer to a moment, which is the staleness problem again wearing a digest. It is
also unearned: this reduction is one join and a median over at most a few hundred integers, not a
build, and a receipt for arithmetic that a reader can redo is ceremony.

#### What the derivation says, and what it refuses to say

A place's position block reports the member captures, how many of them carry a fix, a **bounding
box** in integer ten-millionths, and a **median** latitude and longitude in the same units, under a
versioned `basis` of `exif-capture-fixes/v1` so a changed reduction changes the name rather than
silently reinterpreting an old answer.

Median rather than centroid, for two reasons. A centroid of integers is a rational and needs a
rounding policy, which is a float in disguise, and `canonical_json` refuses floats at any depth. And
one bad handheld fix, which is the ordinary case indoors, moves a centroid and does not move a
median. The bounding box is what says whether the median means anything at all, in the same way
`track_length` sits beside `observations_held` in the observation graph: a single number with no
spread beside it invites a confidence nobody measured.

**Absence is ordinary.** A place no member of which carries a fix reports `state: "unavailable"`
with a reason. That is the only state the corpus that exists today can produce, and it is not a
degraded place, not an error, and not a gap to be filled by inference.

**What this must never be read as.** A GPS fix says where a photographer stood. It does not say
where the place is, how large it is, or which way it faces, and the position block says so in its
own text rather than leaving a reader to infer it. **The recovered frame stays ungeoreferenced.**
Georeferencing a frame needs metric scale, which needs the independent physical reference
`docs/retained-reference-workflow.md` names as an unmet dependency, and a place that quietly
attached a real-world coordinate to a scale-free COLMAP frame would be making exactly the unearned
claim the rung ladder exists to prevent.

#### The trade, stated

A derived position cannot be indexed, so "which places are near here" is a sequential scan over
assertions. That is the cost, and it is accepted for now on three grounds: nobody has asked for
that query, the roadmap explicitly defers Earth and map views to a later bridge view, and the
corpus holds zero fixes to scan. When it is wanted, the right answer is a materialized position
carrying an explicit invalidation edge, following the pattern `world_structure_invalidation`
already implements, and it will properly be a migration then, because it will need that edge. This
decision does not give it one, which is the point: a materialized column without invalidation is
the version that is wrong, and it is the version an amendment today would have shipped.

### The build, and why it needs its own queue

The joint reconstruction is a new stage, `place_alignment`, producing one artifact kind. It has to
be a stage rather than a read-time join for the reason this note opens with, and adding it moves
`pipeline_digest()`, which is computed over the whole `STAGES` registry
(`exulanica/ingest/stages/__init__.py`). That is a reason to add it once and re-record, not a reason
to avoid it.

Its inputs are the two scenes' retained pose receipts, which already hold `camera_centre_xyz` per
photograph (`exulanica/reconstruction/pose.py:196`) and are therefore the `scene_xyz` half of every
correspondence, plus the union of both capture sets, which the joint run recovers a second time to
supply the `joint_xyz` half.

The joint sparse model itself is **not** retained as citable geometry. It is a third frame in which
no scene is addressed and which could be mistaken for the place's own geometry. Its digest goes in
the receipt so the fit stays checkable, and the model stays a build intermediate, the same rule
Phase 3C states for training intermediates.

It cannot reuse the scene queue. `reconstruction_scene_job.scene_id` is `not null` and every
claim, lease and idempotency path in that queue is keyed on one scene, so a pair-subject build has
no valid row to write. Worse, routing a joint run through the `scene_pose` stage would make every
success look like a failure: `exulanica/reconstruction/pose.py:585-586` appends "joint
reconstruction has no measured metric scale" whenever a manifest declares more than one capture set
and carries no metric scale, and this frame is deliberately not metric. So the join is its own
stage, and reusing `scene_pose` for it is the single most expensive mistake available here.

**The queue is deferred, and that is a trade rather than an omission.** The build is a callable
entry point taking two scenes and an injected COLMAP executor, which is exactly how the pose path
is already structured and what makes it exercisable against the stub the reconstruction tests
already use. What is not built is a leased, claimable `place_alignment_job` queue with its own
attempt, lease-renewal and reclaim logic, which would be a fourth copy of a pattern this repository
implements three times (`job`, `reconstruction_scene_job`, `purge_job`).

The reason is verification, not effort. No joint reconstruction has ever run here, so a queue for it
would be scheduling machinery with no executed instance to validate against, and the failure modes
that machinery exists to survive, a worker dying mid-COLMAP and a lease expiring during a
45-minute job, are exactly the ones a stub cannot exercise. Building it now would trade a checkable
system for an unchecked one. What is given up in exchange is real: until the queue exists, a joint
run is an operator action rather than something a read of an unbuilt place can trigger, which is
the dispatcher the roadmap wants in the same phase.

## The alignment, and what makes it refusable

The joint reconstruction yields, for each original scene, a set of its recovered camera centres
expressed in the joint frame. The same cameras already have centres in their own scene frame. Those
two sets are the correspondences, and fitting a similarity between them is
`exulanica/reconstruction/place_alignment.py`.

The discipline copies `scene-placement-alignment.md` exactly, because that is the pattern this
repository has already shown catches real failures:

- **A held-out fold, reserved before fitting.** Every fifth correspondence by a deterministic
  ordering never enters the fit and is what the result is judged on. A fit measured on its own
  training points measures nothing.
- **A similarity, not an affine.** Rotation, uniform scale and translation. Shear or reflection
  would let a bad correspondence set produce a low residual by deforming the world, which is
  exactly the failure a residual is supposed to catch.
- **All three components in the residual.** Not distance alone, for the reason the point-map fitter
  gives: agreement on one derived quantity can hide a wrong geometry.
- **Integer policy, versioned.** Thresholds live in one policy dictionary that enters the stage
  identity, so changing a limit changes the build rather than silently reinterpreting old results.
- **Refusal is an outcome, not an error.** `place-alignment-not-connected`,
  `place-alignment-insufficient-correspondences`, `place-alignment-inconsistent`. A refused pair
  stays two places, and the world says the two captures are of related places whose frames could
  not be reconciled. The 2026-09-05 volcanic refusal is the precedent: a measured refusal recorded
  as a fact is a result.

**The scale is not metres.** The joint frame is a recovered COLMAP frame like every other frame in
this system. Two captures sharing one frame is a statement about their consistency with each other
and about nothing physical. Any metric claim still requires the independent physical reference that
`docs/retained-reference-workflow.md` names as an unmet dependency.

## Forward migration

The roadmap says forward migration, and here that means: adding a place never rewrites a scene.

1. A `place` row is created with the scene that will anchor its frame and a name the user supplied
   or none. Creating it writes nothing to the anchor scene.
2. A joint reconstruction runs over two scenes' union and writes one `place_alignment` row: the
   exact member set, the joint model's digest, and the per-scene similarity with its held-out
   residuals. A refusal writes the same row with its reason and no transform.
3. Each scene is bound to the place by a `place_version` row referencing that receipt. The scene's
   own artifacts, rung, receipts and digests are untouched, and no UPDATE is issued against
   `reconstruction_scene`, which would be refused anyway.
4. A later capture joins by the same route. A place with three scenes has two accepted alignment
   receipts, each independently checkable, and the third version records how many alignments its
   frame was composed through.

A scene may belong to at most one place, because two places claiming one scene would be two
coordinate frames claiming one set of photographs. A scene may belong to none, which is the
ordinary case and stays the ordinary case.

## What Atlas does with it

A region that holds a place shows one capture at a time and exposes time as a dimension, not as a
merge. The rules the display already follows carry over unchanged:

- One region displays one scene, as `docs/atlas-reconstruction-inspection.md` states. Choosing a
  time chooses which scene that is.
- Each version keeps its own rung and its own status. A place does not average them, and an older
  capture that only reached rung 4 stays rung 4 when a newer one reached rung 3.
- The display frame is the place's shared frame once alignment is accepted, so switching time does
  not move the world under the visitor's feet. That is the visible payoff and it is also the thing
  a bad alignment would ruin, which is why the held-out residual gates it.
- Two captures never blend. There is no cross-fade that would show a surface that existed at
  neither time.

## The exit, and why it is still open

The roadmap's exit is two consented captures of one real place, weeks apart, sharing one frame
within a measured tolerance, with the world showing both versions in place.

The repository holds one real place captured once. The bowl collection is 51 photographs of one
occasion; the volcanic set is one occasion of a sample turned over against different backdrops,
which already failed to yield a consistent up direction and would be a poor second capture even if
one existed. So the exit stays open, and this note claims a design and a numeric fixture, nothing
else.

What is buildable now, and is:

- the fitter and its refusals, measured against synthetic captures with a known ground-truth
  transform, so the geometry and the thresholds are exercised before a card is rented;
- the refusal paths, which are the ones a real capture pair is most likely to take.

What needs real data:

- a second capture of a real place, weeks apart, with its own screening and consent;
- a joint COLMAP run over both sets, which is CPU-bound and, on the 2026-09-05 measurements, about
  45 minutes for 210 photographs at exhaustive matching, so a union of two 50-photograph captures
  should be budgeted as a single job rather than assumed cheap;
- a measured tolerance, chosen from the observed residual distribution rather than declared in
  advance. The rung-3 threshold's history (`FR-3`) is the argument: a threshold declared before the
  measurement is an engineering guess, and this note does not pretend otherwise.

## Relationship to the rest of Phase 10

The World Read API addresses a scene, and says so in its own `addressing` block: a place that
persists across captures does not exist yet. When it does, the bundle gains place addressing and
time, and the scene address stays valid, because a scene is still a real thing after it joins a
place.
