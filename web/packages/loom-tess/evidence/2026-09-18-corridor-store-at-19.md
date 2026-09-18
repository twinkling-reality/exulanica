# The corridor's five tiles, baked into the store at tessellator 19

Run 2026-09-18 from `scripts/bake_corridor_tiles.py`, which is the repository's own publish path, on
main `163c6efb`. Predicted before the bake, in the message that asked whether it could be done.

## What was predicted and what happened

THE STRONG ONE: tile (2, 0) had already been baked locally at 19, so the store's bake had to
reproduce it exactly. It did, to the digest and to the byte: container
`e59f6cf05d0ff4e09c5f06a8b5c90e4c3e4ea2bc4a9fb0ff62d02b491e6be5f8`, render `fd4b6ebe...`, nav
`35388d7849...`, 12,682,828 bytes. Two paths to one artefact, agreeing.

THE OTHER FOUR: each render digest had to MOVE and each nav digest had to HOLD, because a facade's
navigation row is ground `none`. All five held.

    tile   container 17 -> 19       render 17 -> 19        nav, which did not move
    0,0    ea59fba4 -> acf1474b     db152b36 -> 151b3809   92311579
    1,0    73fefe33 -> 8f218878     ca8b2ad6 -> 4e029987   77cfffff
    2,0    93df0715 -> e59f6cf0     91350a90 -> fd4b6ebe   35388d78
    3,0    b6183ee2 -> 5b5225f2     95494b3f -> bb7442bc   72ad87e5
    4,0    91a4f590 -> cb0de495     6514a77b -> 5dd06e95   dd856f5e

That is the fourth version across which the navigation projection has not moved for a facade change,
now on five tiles rather than two.

BOTH PASSES IDENTICAL on every tile, which is what the script's two passes exist to check and what
migration 0072 records a fault for. Thirty-one rows now against twenty-six before, zero not in state
`baked`, and the seventeen rows untouched: a new tessellator version takes its own `baked_tile_id`.

What each tile draws, from its own receipt: the undressed set is unchanged in kind on every one of
the five, still facade ground bands and the terrain and nothing else.

## Where the bytes are, and why that is fragile

The containers are in the store the RUNNING API reads, confirmed against that process's own
environment before the first bake rather than after the fifth, because rows pointing at bytes the API
cannot find is the failure worth checking for in advance. All five are present at their
content-addressed paths with byte counts matching their rows, and the store went from 178 MB to
217 MB.

THAT STORE IS IN A DEAD SESSION'S SCRATCHPAD. The lane that made it is closed, so the whole street's
bytes sit in a temporary directory belonging to nobody while the rows that name them sit in a real
database. If that directory is ever cleaned the rows survive and the bytes do not, and the failure
will present as a corrupt store rather than a missing one. Recorded as a fact about the setup; it is
not this lane's to fix.

## An instrument note, because the zero was nearly believed

`find -newermt '-20 minutes'` over that store reported ZERO files written in the last twenty minutes,
moments after writing five. Checking each container directly by its digest path showed all five, with
times of 18:15 to 18:17 against a clock reading 18:19. The zero was the instrument. Had it been read
as a result it would have said the bake wrote nothing, which is exactly the shape of absence a
limited query produces most convincingly.
