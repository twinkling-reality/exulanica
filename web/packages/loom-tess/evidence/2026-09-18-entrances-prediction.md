# Facade openings, the entrance half: what should move, written before the code

Written before a line of the entrance rule exists and before any bake, so it can fail. Tessellator
18 to 19. Tree: `lane/tess-support-carve-wip` at `3f9092b5`, which is local main.

## What the record states, and the one thing that decides this

`city.entrance` states a door a person can reach: its centre along the face, its width, height and
recess, a step height, a threshold point on the face line at the building's base level, and the curb
whose footway it opens onto. The grammar's navigation table gives it ground `support`, with the
reason "The floor of a recessed entrance, from the face line to the door, is drawn and stood on".

MEASURED, on the corridor tile, before predicting anything: all 75 porch floors lie INSIDE their
building's base ring. Taken at the middle of each porch, half the recess in from the face along the
tier edge's inward normal, 75 of 75. Measuring the THRESHOLD instead gives 38 inside and 37 outside,
which is not a fact about the city: a threshold sits ON the edge the facade is laid out on, so a
winding test of it is a coin flip on a boundary point, and the split is my instrument reading which
way each edge runs. Recesses run 32 to 1,791 mm, median 726, and 18 of the 75 are at or under the
capsule's own 340 mm radius.

## The prediction, in parts, so a partial match reads as a partial match

1. `render_batch` MOVES. The entrance draws its floor and the returns into its recess.
2. `nav_envelope` MOVES, and NOT BY GAINING TRIANGLES. Its triangle count should be UNCHANGED and
   its digest should move, because 75 entries change their stated reason.
3. THE REASON THEY CHANGE TO IS `ground_coverage`, not a drawn state. `city.massing` obstructs by
   `base_ring`, and `ring-clearance.ts` clears the ring AND ITS INTERIOR, its own first piece being
   "THE RING itself, cut into triangles: what stands inside it". Every porch floor is inside that
   ring. So support drawn there is carved away entirely, and `ground_coverage` is the existing need
   that says exactly this: every part of the surface is ground another record takes, or a capsule
   clearance, so none is left.
4. TERRAIN DOES NOT MOVE, in either projection. Terrain yields to what covers the ground, and a
   massing's row is ground `cover` by `base_ring`, so the ground under every porch is already given
   up. A porch floor outside its base ring would move it; there are none.
5. BAKE TIME does not jump. Nothing here reaches plan arrangement that the base ring did not reach
   already.

## What this predicts that the orchestrator's expectation does not

I was asked to expect that `nav_envelope` must move "by the 75 porch floors and the terrain that
yields to them". I predict the opposite mechanism: nav_envelope moves by 75 REFUSALS rather than 75
floors, its triangle count does not change, and terrain does not move at all. If instead the triangle
count rises by about 150, then either the porch floors are not inside the base ring after all, or the
carve is not clearing a ring's interior, and both would be findings larger than this piece.

## THE CONTRADICTION THIS EXPOSES, which is not mine to resolve

The grammar's navigation table says two things that cannot both hold:

    city.entrance  ground "support"       "The floor of a recessed entrance, from the face line to
                                           the door, is drawn and stood on."
    city.massing   obstruction "base_ring" a capsule keeps its radius clear of that ring, and the
                                           clearance region includes the ring's interior

A recessed doorway is inside the footprint by construction. So the floor the first row says is
"stood on" is ground the second row says a capsule cannot occupy. Measured rather than argued: 75 of
75 on this tile, and 18 of them are recessed less than one capsule radius, so even a rule that spared
the part of a porch deeper than the radius would leave those with nothing.

I am building what the tessellator can honestly say, which is that the floor draws in `render_batch`
and is carved to nothing in `nav_envelope`, and reporting the contradiction rather than choosing
between the two rows. Choosing would mean either drawing support a capsule cannot use, or silently
dropping a row the grammar states.
