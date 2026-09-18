# Two gaps the entrance half cannot be built through, and one beside them

Written 2026-09-18 by the tess lane, at the orchestrator's request, to be taken to the operator. Both
are VOCABULARY questions that move digests, and neither is a tessellator decision. Nothing here
chooses between the options; the options are named so somebody who can choose has them in one place.

Every measurement is from the corridor city generated at `7f155bcc`, which is local main plus this
lane's evidence commits, and from the files cited by path and line.

## Gap one: the grammar says an entrance's floor is stood on, and says a capsule cannot be there

THE TWO ROWS, from `exulanica/grammar/grammars/city/city.v2.json`, `navigation`:

    city.entrance   ground "support"        "The floor of a recessed entrance, from the face line to
                                             the door, is drawn and stood on."
    city.massing    ground "cover"           cover "base_ring", obstruction "base_ring"
                                            "The ground under a building's base ring is neither
                                             drawn nor stood on, and a standing capsule keeps its
                                             radius clear of that ring."

AND WHAT THE CLEARANCE RULE DOES WITH THE SECOND, `web/packages/loom-tess/src/core/ring-clearance.ts`
line 10, its own first piece:

    "1. THE RING itself, cut into triangles by the ring rule: what stands inside it."

So the clearance region is the ring's INTERIOR as well as a disk of the radius around it. A recessed
doorway is inside the footprint by construction, so the floor the first row calls "stood on" is
ground the second row clears.

MEASURED, on the corridor tile:

    porch floors inside their building's base ring          75 of 75
    recess_mm                                              32 to 1,791, median 726
    PORCHES RECESSED AT OR UNDER ONE CAPSULE RADIUS        18 of 75

The 75 of 75 is taken at the MIDDLE of each porch, half the recess in from the face along the tier
edge's inward normal. Taken at the THRESHOLD instead it reads 38 inside and 37 outside, which is not
a fact about the city: a threshold sits on the edge its facade is laid out on, so a winding test of
it is a coin flip on which way that edge runs. A result that close to half is an instrument.

THE EIGHTEEN ARE WHAT DECIDES THE SHAPE OF ANY ANSWER. A rule that spared only the part of a porch
deeper than one capsule radius leaves those eighteen with nothing at all, so "make the clearance
smarter" is not by itself a solution.

### The options, not chosen between

1. GIVE `city.entrance` GROUND `none`. Its floor then draws and nobody stands on it. Costs: a person
   cannot step into a doorway, and the row's own sentence has to change, since it is the sentence
   that makes the claim.
2. NARROW THE MASSING'S OBSTRUCTION so it excludes the part of its interior a doorway recesses into.
   Costs: a building's obstruction becomes a function of records from a later stage, which is a new
   dependency between stages; and the eighteen above are still unreachable.
3. LEAVE BOTH AND LET THE TESSELLATOR SAY SO. The floor draws in `render_batch`, the carve removes
   all of it in `nav_envelope`, and 75 entries state `ground_coverage`, the existing need meaning
   every part of the surface is ground another record takes or a capsule clearance, so none is left.
   Costs: a row that says "stood on" produces a refusal, and every reader has to learn why.

## Gap two: an entrance's surfaces are undressable, not undressed

`city.entrance` appears in NO tuple of `SURFACE_ROLE_OWNERS`
(`exulanica/grammar/grammars/city/material.py`), and `_role_owner` in that file refuses a material
record whose `surface_kind` is not among a role's owners. The thirteen kinds that do own a role are
block, crossing, curb_edge, facade, interior_backing, junction, massing, parcel, road_marking,
street_segment, street_tree, surface_material and terrain.

So a surface an entrance draws cannot be dressed by any record anybody writes today. It is not
undressed pending a material. It is undressable by construction, and it would show as new permanent
magenta at the foot of every door on the street this project's stop condition is about.

AND THERE IS NO ROLE FOR A PORCH FLOOR AT ALL. Every horizontal role the grammar states is owned by
something else: `footway` and `kerb` by a curb, `lot` by a parcel or a block, `carriageway` by a
segment or a junction, `crossing` by a crossing, `terrain` by terrain, `tree_pit` by a tree, `roof`
by a massing. A facade owns ten roles and every one of them is a face.

### The options, not chosen between

1. ADD `city.entrance` TO AN EXISTING ROLE'S OWNERS. `trim` would carry the returns into a doorway.
   It does not solve the floor, because no horizontal role fits a porch.
2. ADD A NEW SURFACE ROLE for a threshold or porch floor. `SURFACE_ROLE_CODES` is append-only and a
   new role needs an entry in `ROLE_CLASSES` too, which refuses a role it has not been taught, by
   the decision already recorded there.
3. DRAW AN ENTRANCE'S GEOMETRY ON ITS FACADE'S ENTRY, so it takes facade roles. `trim` then covers
   the returns without any vocabulary change. The floor still has no role, so this is option 2 for
   the floor and nothing for the returns.

## Beside them, the same class: the ground band

Measured from the containers, by kind and role:

    corridor tile (2,0), 1,633 drawn surfaces, 86 undressed
        city.facade ground_band   85
        city.terrain terrain       1

That is the whole of what the street leaves bare. Its interior backings, its glazing and its doors
are all dressed. `ground_band` is a role `city.facade` owns, so unlike the two gaps above this one
needs no vocabulary change: it is an assignment, and the texture piece's own census rule decides
whether the role needs a new set or only a material record. Terrain is bare by a decision already
recorded: no published set depicts bare ground and none is asked for.

It is here because it arrived by the same route, a picture of undressed geometry, and because the
answer is different in kind: one of these three is a materials job and two are vocabulary.

## What is NOT blocked by any of this

The returns between a ground bay's own panels, which the facade draws in its own `trim` role. 525
pairs of panels on the corridor tile share an edge at different recesses with nothing drawn across
the step, in exactly the 75 bays that have a door, which is why a door set back as much as 1.79 m
reads as a rectangle floating behind a wall. Every face that would draw one already carries a trim
material record: 32 of 32 on the tile and 98 of 98 in the city, so it adds no undressed surface
anywhere.
