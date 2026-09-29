# ADR-0027: A world generated from a reviewed recipe is drawn in its person's own world

- Status: Accepted
- Date: 2026-09-29
- Deciders: the product owner
- Supersedes: the sentences that bar a generated tile from a person's world, and nothing else:
  - `web/packages/app/src/config.ts`, the documentation of `generatedTileEvaluationName`: "A
    generated tile may not appear in any person's world until a superseding governance ADR is
    accepted in writing." and of `bakedTileRequest`: "a generated tile may not appear in any
    person's world until a superseding governance ADR is accepted in writing."
  - `web/packages/app/src/composition/generated-tile.ts`, its module documentation: "A generated
    tile may not appear in any person's world until a superseding governance ADR is accepted in
    writing."
  - `web/packages/atlas-react/src/playcanvas/generated-tile/binding-contract.ts`, the
    documentation of `GeneratedTileMount`: "A generated tile may not appear in any person's world
    until a superseding governance ADR is accepted."
  - [Generated tile runtime](../generated-tile-runtime.md), its status: "The app draws a generated
    tile only in the development preview, never in a saved world."
- Related: [ADR-0008](0008-generated-geometry.md), [world creation](../capabilities/world-creation.md),
  [generated tile runtime](../generated-tile-runtime.md),
  [synthetic society contract](../synthetic-society-contract.md#a-saved-worlds-own-ground)

## Context

The city grammar generates a city from a seed, a specification and its catalogs: streets, blocks,
lots, buildings, premises with use classes, street furniture and the walking surfaces between them.
None of it is observed; every record carries the `invented_world` truth class, and the grammar's
forbidden import contract makes a generated record structurally unable to name evidence. A baked
tile is that city's drawing, made offline by the tessellator and stored by the digest over its
inputs.

The web code kept every generated tile out of a person's world. Its documentation cited the
governance of [ADR-0008](0008-generated-geometry.md), which refuses generatively completed geometry
from the reconstruction ladder and keeps generated geometry bytes unserved and undrawn until a later
record supersedes it. A tile could therefore be drawn only on the development preview route.

A world a person makes from a recipe of the catalogs (`POST /worlds/generated`) is a generated city
of its own: the server generates it for the world's identity, saves it as a `generated` world with a
receipt that says how, and bakes its tiles off the request. The world has no photograph in it and
claims no place on the Earth. Drawing it is what makes it a world a person can open, and what the
first milestone's town needs.

## Decision

A world of a kind whose entry in `WORLD_KINDS` (`exulanica/world/worlds.py`) states
`draws_generated_tiles` is drawn in its own person's world from the baked tiles its structural
snapshot names. Its saved entry declares what the page draws (`generated_ground`: each tile with its
stored bake, the region its people live in and where a person arrives), and the page follows that
declaration (`web/packages/app/src/composition/generated-world.ts`). The world kind the server
registers is the gate; no build flag and no page branch decides it.

What stays as it was: ADR-0008's refusal holds for reconstruction, the point-map container,
navigation derived from photographs, citation and the World Memory Package. No generated record,
receipt or tile enters any of them. The development evaluation entry (`?preview=1` with a tile name
or a baked tile key) stays development only, as `web/packages/app/src/config.ts` states.

## Guarantees

Each is held by a test that fails without it.

1. **Served only to the world whose snapshot names the tile.**
   `GET /world/versions/{version_id}/tiles/{baked_tile_id}/bytes` serves a baked tile only when the
   version's own snapshot names it (its receipt's tiles, by the digest over each tile's bake inputs),
   holds the bytes to their digest under the final read check, and answers a stranger as it answers
   a world nobody registered. Another world's stored tile is refused like a tile that does not
   exist. `tests/test_generated_worlds.py::test_a_generated_world_s_tile_is_baked_off_the_request_and_served_only_to_its_world`.
2. **Never citable.** Generated content cannot name a citation: the forbidden import contract on
   `exulanica.grammar` ("Generated content cannot name a citation, because it cannot name one", in
   `pyproject.toml`) and `tests/test_grammar_layering.py`, which makes it fail on purpose. A generated
   world holds no photograph (guarantee 4), so no answer about it can cite one.
3. **Labelled as generated on the page.** The About panel says the world is generated from the
   city grammar's catalogs and not recorded from a real place, and the saved worlds list names it a
   generated world with its recipe. `web/packages/app/test/world-about.test.ts` ("generated-tile:
   generated from the catalogs, not recorded from a real place").
4. **Never composed with photographs.** A photograph reaches a world's geometry only through its
   saved entry's attachments, and a world whose kind states `takes_photographs` false refuses one by
   name (`world_takes_no_photographs`). `tests/test_generated_worlds.py::test_a_generated_world_takes_no_photographs`.

## Consequences

A production build carries the tile runtime and the committed texture library, which it fetches
only for a tile it draws. The development evaluation markers stay out of it
(`web/packages/app/test/generated-tile-evaluation.test.ts`). A generated world is bounded by the
world-count policy's `generated` limit and its recipe's stated tile count, not by the workspace tile
quota, and a browser session still holds no `tiles.materialise` (`exulanica/api/permissions.py`).
