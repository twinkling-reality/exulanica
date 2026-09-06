# One place across captures and time

Design note, 2026-09-06. **Design and numeric fixture only. No real cross-capture alignment has
run, and nothing here is claimed as measured.** Roadmap Phase 10 capability 3, and experiment FR-2
made product.

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

1. A place row is created, empty, with a name the user supplied or none.
2. A joint reconstruction runs over two scenes' union and produces its own receipt: the exact
   member set, the joint model, and the per-scene similarity with its held-out residuals.
3. Each scene is bound to the place through that receipt. The scene's own artifacts, rung,
   receipts and digests are untouched.
4. A later capture joins by the same route. A place with three scenes has two accepted alignment
   receipts, each independently checkable.

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
