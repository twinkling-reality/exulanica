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
`'place'` (`exulanica/migrations/0001_spine.sql:75`). So an entity of class `'place'` is expressible
today, and putting the durable place there would have been the cheapest change: it inherits naming,
merging, confirmation and the identity ledger.

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
(`0001_spine.sql:69`). This note has already refused that route: a place asserted from a label is a
claim the system cannot support. Modelling a place as an entity would make the forbidden path the
cheapest one available, and the first time somebody took it the system would show a visitor one room
labelled as another with no receipt to contradict it.

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

It is also wrong on its own terms. A place needs a name, a shared frame and a series of alignment
receipts, and none of those is a property of any one scene.

### The collision with `occurrence_class`, and how it is closed

Two things named `place` in one schema is how a query silently returns the wrong one. The fix is not
to rename the durable thing, because the roadmap, this note and the product all say `place` and a
third word would have to be reconciled by every reader forever. The fix is to make the schema
single-valued for the word.

`occurrence_class` keeps its `'place'` value with the meaning it has always had: a place **observed
in one photograph**. Migration 0038 refuses an `entity` row of class `'place'` with a named check
constraint, so the ambiguous row cannot exist and the attempt to create one fails with a constraint
name that says why.

That is not a capability being removed. An entity of class `'place'` could only be a place whose
identity came from recognising a label or a likeness across photographs, which is the thing this
note forbids in its own identity section and the same shape the privacy layer refuses for people.
MEASURED 2026-09-07 on the permitted instance: `select class, count(*) from entity` returns
`person|1` and `select class, count(*) from occurrence` returns `person|1`, so no existing row is
affected and the constraint applies to an empty set.

After 0038 the word resolves without a lookup. A place you can select from a table is a `place`. A
place in a photograph is an `occurrence`, and it never becomes an identity.

`region` is untouched. A region stays the world's spatial authority; a place tells a region which
scenes belong to it and how their frames relate. `person_region.region_key` is a 16x16 grid cell and
the place plane has no grid key, so the word is not reused.

### The three tables

`place`. One row per durable place: `place_id`, `workspace_id`, an optional `display_name` the user
supplied, an `anchor_scene_id`, and the usual `created_at` and `deleted_at`.

The anchor is the part worth arguing about. **A place's shared frame is its anchor scene's own
recovered frame**, not a new frame of its own. A joint reconstruction produces a third frame, and
adopting that as the place frame would mean every version's geometry is expressed in a frame no
retained artifact was measured in, and that nothing else in the system addresses. Anchoring on a
real scene keeps the place frame a frame that already exists, makes the anchor's own transform
exactly identity, and makes "the world does not move under the visitor's feet when they change time"
a property of the anchor rather than of a build.

`place_version`. One row per scene in the place: `place_id`, `scene_id`, an `ordinal` by capture
time, the `captured_at` it was ordered by, the `place_from_scene` similarity as a row-major 4x4 with
its scale carried separately the way `PlaceAlignmentResult` already does, the alignment receipt that
admitted it, and `frame_hops`.

`frame_hops` is the honesty field. It is 0 for the anchor, 1 for a scene whose transform to the
anchor was measured by a single joint run, and n for one composed through a chain of them. A place
with three scenes has two accepted alignment receipts, and the third scene's frame may have been
measured against the second rather than against the anchor. Without this field that composition is
invisible and a reader would take a composed transform for a measured one. With it, "measured
directly" is a machine-readable property rather than a footnote somebody has to find.

`unique (workspace_id, scene_id)` enforces the rule this note already states: a scene belongs to at
most one place, because two places claiming one scene would be two coordinate frames claiming one
set of photographs.

`place_alignment`. The receipt of one joint reconstruction: the two scenes, the member digest of the
union, the versioned policy from `PLACE_ALIGNMENT_POLICY`, the digest of the joint model, whether it
was accepted, the refusal reason when it was not, and the held-out residuals and correspondence
counts as integers. A refused alignment is a row like any other, because a measured refusal recorded
as a fact is a result.

### An artifact may now name a place

`artifact` carries `an_artifact_names_one_subject`, which today reads
`CHECK ((source_blob_sha256 IS NOT NULL) <> (scene_id IS NOT NULL))` (read from the live schema,
2026-09-07). An artifact names exactly one subject: a blob or a scene.

A place alignment's subject is a **pair of scenes**, which is neither. Attaching its receipt to one
of the two scenes would be a lie about what was measured, and the lie would be invisible from the
scene side. So 0038 adds a nullable `place_id` to `artifact` and generalises the constraint to
exactly-one-of-three. The invariant is unchanged and every existing row still satisfies it; what
changes is that a place is now a subject a build may be about.

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

The queue is a new table. `reconstruction_scene_job.scene_id` is `not null` and every claim, lease
and idempotency path in that queue is keyed on one scene, so a pair-subject build has no valid row
to write. This repository already runs one queue per subject kind: `job` for per-capture
derivatives, `reconstruction_scene_job` for scenes, and `purge_job`. A fourth for a pair follows
that precedent rather than widening a table 222 commits of code addresses.

**The trade, stated.** A fourth queue duplicates claim, lease, attempt and reclaim logic that
already exists twice. That is a deliberate cost paid for modularity and for cheap verification: the
existing queues keep their invariants unchanged and untouched, and the new one is checkable on its
own. The alternative, a generic subject-polymorphic queue, would be less code and a much larger
blast radius across every path that currently reads `scene_id` from a job row, and it would have to
be got right for the two existing queues before it could be got right for the new one.

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
