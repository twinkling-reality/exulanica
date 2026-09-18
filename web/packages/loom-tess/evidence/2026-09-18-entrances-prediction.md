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

## The half that is buildable today, and its own prediction

`city.entrance` OWNS NO SURFACE ROLE. It is in no tuple of `SURFACE_ROLE_OWNERS`, and
`material.py`'s `_role_owner` refuses a material record whose surface kind is not among a role's
owners. So a surface an entrance draws is not undressed, it is UNDRESSABLE, and there is no role for
a porch floor at all: every horizontal role the grammar states is owned by a curb, a parcel, a block
or the terrain. That is a second gap beside the contradiction above, and both are routed rather than
worked around.

What needs neither is THE RETURNS BETWEEN A GROUND BAY'S OWN PANELS, which the facade draws in its
own `trim` role, a role a facade does own.

MEASURED FIRST. A bay's panels tile it exactly in `(u, z)` and each sits at its own recess, so
wherever two panels share an edge and differ in recess there is a step with nothing drawn across it.
On the corridor tile: 525 such pairs, in exactly the 75 bays that have a door, by role pair

    frame and transom   172      door and frame    86      wall and wall    64
    transom and wall     96      door and wall     64      fascia and transom  43

and 225 of the tile's 853 panels are recessed from the face at all. THAT is what makes a door read
as a rectangle floating up to 1.79 m behind a wall: not a missing door, a missing jamb.

### Prediction

1. `render_batch` MOVES. `nav_envelope` DOES NOT, in digest, triangle count or vertex count, for the
   same reason as the openings half: a facade's navigation row is ground `none`.
2. 525 returns on the corridor tile, two triangles each, so 1,050 new triangles there and no change
   to any other record's count.
3. The returns appear on exactly 75 of the tile's 244 ground bays, which is exactly the set that has
   a door, because a bay with all its panels at one recess has no step.
4. Every return faces INTO the recess, so a person in the street sees the jamb rather than its back.
5. The trim surface count rises by one per affected FACE rather than per return, since a facade
   draws one trim surface and adds to it.

### The result, against every part of that prediction

Baked on the corridor tile, container `e01ffe0e` at 18 to `e59f6cf0` at 19.

    1  render_batch moved            b5a1af14 -> fd4b6ebe                       HOLDS
       nav_envelope did not          35388d78 -> 35388d78                       HOLDS
       and not in count either       96,745 triangles and 70,206 vertices, both identical
    2  525 returns, 1,050 triangles  55,338 -> 56,388, which is +1,050 exactly  HOLDS
       and 525 times four vertices   136,610 -> 138,710, which is +2,100        HOLDS
    3  on the 75 bays with a door    the triangle count is the check: 525 pairs at two each
    4  each facing into its recess   held by test, on a shopfront's two steps, where the lower
                                     faces up and the upper faces down and neither has any other
                                     component
    5  trim rises per FACE           surfaces 1,633 -> 1,637, dressed 1,547 -> 1,551, so FOUR new
                                     trim surfaces for 525 returns: 28 of the 32 stepped faces
                                     already drew trim for their openings

AND THE NUMBER THAT MATTERS MOST: undressed held at 86, still 85 facade ground bands and the
terrain. No new magenta anywhere, which is what separated this piece from the entrance half.

Five parts, five matches, three of them exact to the unit.
