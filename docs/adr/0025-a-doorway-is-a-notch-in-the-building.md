# ADR-0025: A recessed doorway is a notch in the building, not a hollow inside it

- Status: Accepted
- Date: 2026-09-18
- Deciders: Exulanica build, on the operator's decision
- Supersedes: nothing
- Related: `web/packages/loom-tess/evidence/2026-09-18-entrance-vocabulary-decisions.md`, ADR-0024

## Context

The city grammar states two things about a recessed entrance that cannot both hold.

From `exulanica/grammar/grammars/city/city.v2.json`, the `navigation` table:

    city.entrance   ground "support"         "The floor of a recessed entrance, from the face line
                                              to the door, is drawn and stood on."
    city.massing    ground "cover"            cover "base_ring", obstruction "base_ring"
                                             "The ground under a building's base ring is neither
                                              drawn nor stood on, and a standing capsule keeps its
                                              radius clear of that ring."

And from `web/packages/loom-tess/src/core/ring-clearance.ts`, the clearance rule's own first piece:

    "1. THE RING itself, cut into triangles by the ring rule: what stands inside it."

So the region a capsule is kept out of is the base ring's INTERIOR as well as a disk of the capsule's
radius around it. A doorway recesses INTO the footprint, so the floor the first row calls "stood on"
is ground the second row clears.

### Measured, on the corridor tile

| Quantity | Value |
| --- | --- |
| Porch floors inside their building's base ring | 75 of 75 |
| `recess_mm` | 32 to 1,791, median 726 |
| **Porches recessed at or under one capsule radius of 340 mm** | **18 of 75** |

The 75 of 75 is taken at the MIDDLE of each porch, half the recess in from the face along the tier
edge's inward normal. Taken at the THRESHOLD it reads 38 inside and 37 outside, which is not a fact
about the city: a threshold sits on the edge its facade is laid out on, so a winding test of it is a
coin flip on which way that edge runs. A result that close to half is an instrument.

**The eighteen decide the shape of any answer.** A rule that spared only the part of a porch deeper
than one capsule radius leaves those eighteen with nothing at all, so "make the clearance smarter" is
not by itself a solution.

### Why the cheap answer was refused

The cheap answer is to give `city.entrance` ground `none`, so the grammar stops claiming a person can
stand in a doorway. It costs nothing today, because nothing walks into a shop today. It would have to
be undone the first time anything does, and the record of why the claim was dropped would by then
read as a limitation of the world rather than as a decision about a footprint.

The operator's steer was: whatever is better long term, no matter the work it takes, and no
hardcoding that will not scale.

## Decision

**A building's base ring states the volume the building actually occupies, and a recessed entrance is
a notch in it.**

1. **The footprint gains the notch.** Where a bay recesses, the massing's base ring turns in and back
   out again, so the ring traces the wall the building actually has rather than the line its facade
   would have if nothing were set back.

2. **The clearance rule needs no change at all.** It already clears a ring and its interior, and a
   recess is no longer interior. Its own tests already cover a ring with a reflex corner and a
   slanted edge, so a non-convex footprint is not new ground for it.

3. **A person standing in a doorway is standing OUTSIDE the building.** That is what is physically
   true, and it is the sentence the rest of this follows from.

4. **The eighteen shallow doorways still refuse, and that is now correct.** A person does not fit in a
   32 mm recess, and a rule that says so is stating a fact rather than losing one. Under the old
   reading their refusal was a contradiction; under this one it is an answer.

5. **Every tile rebakes and every digest moves.** The base ring is an input to the massing rule, the
   terrain yield, the clearance carve and the navigation projection, so this moves `render_batch` and
   `nav_envelope` on every tile that has a building.

## What this assumes

- That a recess is a property of the BUILDING and not only of its facade. This ADR asserts it: a wall
  set back a metre and a half is a wall the building does not have there, and a footprint that says
  otherwise is stating a volume nobody built.
- That the generator can state the notch. The recess is already stated, in `city.ground_bay`'s
  panels, so the fact exists; what changes is which record carries it into the footprint.
- That a non-convex base ring is admissible everywhere a base ring is read. The clearance rule is
  covered by its own tests. Every other reader of `tiers[0].ring_mm` needs checking before the change
  is made, and that check has NOT been run.

## What would force this to change

- A reader of a base ring that requires convexity and cannot be made not to. That would be a reason
  to carry the notch as a separate field rather than in the ring itself, not a reason to go back to
  the hollow.
- A measurement showing the notch makes a footprint self-intersect for a real record, for instance
  two doorways whose recesses meet behind a thin pier.
- Evidence that a doorway floor needs to read differently from the ground outside it, which is a
  looks question and is decided by an eye rather than by this document.

## What a producer must now do

- A massing's `tiers[0].ring_mm` traces the recesses its facades' ground bays state. The ring stays
  simple and counter-clockwise, as it already must.
- A recess too shallow to admit a capsule is still a notch. The footprint states the building, not
  what fits in it; whether a person fits is the clearance rule's answer and not the generator's.
- `city.entrance` continues to state where a door is. It does not gain geometry by this decision.

## The option that may make the vocabulary question disappear, NOT YET CHECKED

`city.entrance` owns no surface role. It is in no tuple of `SURFACE_ROLE_OWNERS`, and no horizontal
role fits a porch floor: every one is owned by a curb, a parcel, a block, a segment, a junction, a
crossing, a tree or the terrain, and a facade's ten roles are all faces. So under the old reading an
entrance that drew a floor would draw something no material record could ever dress.

The notch may remove that question rather than answer it. A massing's row is ground `cover` by
`base_ring`, which is why the ground under every porch is given up today. Cut the notch and that cover
shrinks, and the PARCEL'S OWN `lot` surface, a role `city.parcel` and `city.block` already own and
which the corridor already dresses, would cover the recess as ordinary plot ground. The floor a person
stands on in a doorway would then be the ground they were standing on outside it: continuous, already
dressed, already standable, and drawn by nobody new.

**Three checks decide it and NONE HAS BEEN RUN:**

1. Does a parcel's `lot` surface extend under its own massing, or is it generated already clipped to
   the massing's outline? If it is clipped at generation rather than covered at draw time, shrinking
   the cover reveals nothing.
2. Do all 75 porches sit inside their own parcel? The 75 of 75 above is against the BASE RING, not
   against a parcel, and some may sit over a curb's footway or a junction.
3. Does a doorway floor dressed as plot ground look right, or does a shop threshold want to read
   differently from the yard behind the building? That one is a looks question and belongs to an eye.

They are named here unrun so that nobody rediscovers this option after inventing a role.

## What this ADR does not do

It changes no code. The notch is a generation change in the city grammar, a rebake of every tile, and
a re-measurement of everything keyed to a base ring, and it waits for the corridor street to be
judged: the critical path is one street and a verdict, and "no matter the work it takes" is a steer
about which design is right rather than a licence to start the largest change in the tree before the
thing it would invalidate has been scored.

It does not settle whether `city.entrance` ever owns a surface role. If the three checks above hold,
it needs none. If they do not, the question returns with the notch already decided, which is a better
position to answer it from than the one this document was written in.
