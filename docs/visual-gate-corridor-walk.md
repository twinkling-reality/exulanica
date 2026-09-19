# A second stated walk of the corridor street, from the tile's western edge

The corridor lane's own walk is stated in `docs/generated-corridor-street.md` and **is not touched by
this file**. It was pre-registered before a rebake so that nobody could fit a pose to what they saw,
and that discipline is worth more than any number in it. It stands, and it cannot be scored:

    the route rule needs 125,000 + 6,000        131,000 mm
    its pose leaves, due east                   125,067 mm
    so no heading from it clears the route, which is what the gate measured on 2026-09-18

This file states a SECOND walk, beside it, with its own parameters and its own reason.

    http://127.0.0.1:5322/?preview=1&city=75832ac54dcfd499219752e6385149c73624b8c674f9ebb0c1fa0af2bb70b3d1&tile_x=2&tile_y=0&pose_x_mm=256000&pose_y_mm=70300&facing_dx=1&facing_dy=0

## Why this start, and what would make it illegitimate

**The start is the tile's western edge: the westernmost pose at which this tile has any geometry at
all.** That is the principle. West of 256,000 the tile states nothing, so a walk beginning there
would begin off the end of the thing being looked at. The y and the heading are the corridor lane's
own, unchanged.

**THE 67 MM IS A CONSEQUENCE AND NOT THE AIM, and saying so is the point of this section.** Starting
at the tile's edge happens to leave 131,067 mm due east against the 131,000 the rule requires. Had it
left 130,900 this file would still state this pose and the gate would still refuse it, because a
start chosen to clear a threshold is a route picked to flatter what it looks at, which is the single
thing this gate exists to prevent.

**A correction to the reason I was given, made before the run rather than after.** This start was
described to me as "the westernmost pose the field admits". IT IS NOT. The product states a field
whose inscribed square reaches to 252,933, which is 3,067 mm further west than the tile's edge, and
starting there would leave 134,134 mm and clear the rule by 3,134 mm instead of 67 mm. That start is
available and is DELIBERATELY NOT TAKEN: it would begin three metres before this tile's surface
exists, and choosing it over the tile edge for its extra margin would be fitting the pose to the
threshold. The same 3,067 mm is what made the earlier arithmetic on this street four times too
generous, so it is written down here rather than left to be rediscovered.

## What this walk is expected to run into

**A pose exactly on a boundary may read as unsupported.** A point exactly on a shared edge between
nav envelope triangles reads as no surface in this product, against its own comment, and 256,000 is
exactly a tile boundary. If the start has no ground under it, that is a finding about the boundary
and not a reason to move the pose inward: moving it would be fitting again. The pre-walk ground check
will say so in the record either way.
