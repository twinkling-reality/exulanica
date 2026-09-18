# Facade openings, stage 1: what should move and what should not

Written BEFORE any digest was read or any tile baked, so it can fail. Tessellator 17 to 18.

Tree: worktree `exulanica-personal-admission`, branch `lane/tess-support-carve-wip`, based on local
main `782ab758`. Every figure below is predicted, not measured; the measurements are in the log
beside this file.

## The change

`city.facade` cuts its openings out of the wall instead of drawing the wall whole, and returns the
wall `reveal_depth_mm` into each opening in the `trim` role. Nothing else changes. Entrances are
NOT in this change; they are their own commit with their own prediction, for the reason the split
was made: `city.entrance` carries navigation ground `support` and a facade carries `none`, so
landing them together would make a moved navigation digest unreadable.

## What must move

- `render_batch` triangle digest, on any tile carrying a facade whose grid states an opening.
- The container digest and byte count of any such tile, since the header states the tessellator
  version whether or not a triangle moves.
- The container digest of EVERY tile, opening or not, for that same reason: 17 to 18 is stated in
  the header. A tile with no opening moves its container digest and NOT its triangle digests.

## What must not move

- `nav_envelope`, on every tile, byte for byte in its triangle digest. A facade's navigation row is
  ground `none`, so no surface it makes is support and none is ground another record yields to,
  whichever way that surface faces. If `nav_envelope` moves, the carve has reached something it
  should not have, and the fault is mine rather than the prediction's.
- The terrain the tile draws, in `render_batch` and in `nav_envelope` alike, for the same reason:
  terrain yields to what covers the ground, and an opening is a hole in a wall.
- Plan arrangement: no opening reaches it. The carve that cuts a face runs in the face's own
  `(u, z)` plane, which shares no code path with the ground carve beyond `piece-carve` itself.

## Bake time

It should rise, by the cost of carving 51 faces on the corridor tile rather than drawing them as
one rectangle each, and it should not rise the way 121 s did at tessellator 11. That rise was
terrain yielding to a holed strip, which is a navigation-side cost this change cannot incur at all.
A jump of that shape here means the carve has escaped the face's own plane.

I have no number to predict for bake time, so I am recording the question rather than inventing an
expectation: does carving 51 faces cost more or less than one second on this tile.

## The two golden artefacts this moves, and the one it may not

1. `test/fixtures/tile-conformance.json` and the `GOLDEN` literal in
   `test/triangle-digest-conformance.test.ts`. The fixture states six faces with opening grids, four
   of them arched, 38 openings in all, so its `render_batch` golden must move and its `nav_envelope`
   golden must not. That pair is the sharpest test in this change: one literal changes and the other
   does not, in a file where both sit two lines apart.
2. The tile runtime lane's development golden,
   `web/packages/app/src/dev/tiles/tile-conformance.owd`, with the sha256 and digest its README and
   golden test state. Approved as an outside edit in the tess handoff, to be rebaked in the same
   commit that moves the fixture.

If any OTHER test expectation of another lane moves, I stop and report rather than editing it.

## The counts the fixture should show

From the fixture's own records, counted before the rule ran: six faces carry a grid, and their bays
times their listed storeys are 10, 4, 4, 4, 8 and 8, so 38 openings. Four of the six grids state
`head_rise_mm` 250 over `width_mm` 1200 and two state a flat head. So 26 of the 38 openings are
arched and 12 are not. The fixture's `city.facade` entries must gain a `trim` surface on exactly
those six and on no other face.
