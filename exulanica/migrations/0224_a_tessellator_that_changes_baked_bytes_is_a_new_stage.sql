-- 0224_a_tessellator_that_changes_baked_bytes_is_a_new_stage.sql
-- The bake stage moves to tessellator 21, so every tile is baked again once under it.
--
-- WHY. A tessellator change that moves the bytes it bakes is a new stage (migration 0144: a stage is
-- a schema fact, and a bake is published only for the current one). The lot steps' crossing cut
-- changed the bytes of a tile whose footway crosses a lot's grade, but the source version stayed at
-- 20, so the stage did not move: a tile stored before it, whose two faces cancelled at a shared
-- corner and which the browser therefore refuses, kept being served as that stage's bake and was
-- never baked again. Tessellator 21 also lets a street the next tile owns take its ground from this
-- tile's terrain in every town, not only on land: on a level town the terrain stood over that
-- carriageway's camber across the seam, and people walked it. tests/test_baked_tile_goldens.py now
-- holds every source version to the digests it bakes, so bytes that move under an unchanged version
-- fail before they land.
--
-- WHAT IT DOES. It retires stage (3, 57d3f6eb...), the stage of tessellator 20, and states stage
-- (3, af552d36...), `STAGES["baked_tile"]` with `"tessellator": 21`, as current;
-- tests/test_baked_tile_stage_postgres.py holds the two equal.
--
-- WHAT IT DOES NOT DO. No stored bake is changed or deleted: a tessellator 20 bake stays under its
-- own stage and key, never read as current again and still reachable by its key (0144). Nothing is
-- queued here: the tile worker, at its start, queues one bake for each tile of each generated world
-- of the workspaces it serves, and for each tile its versions' building changes alter, that has no
-- bake under the current stage and no job waiting (exulanica/world/generated_worlds.py
-- queue_workspace_bakes).

begin;
select pg_advisory_xact_lock(119622309);

update baked_tile_stage set retired_at = now() where retired_at is null;
insert into baked_tile_stage (stage_version, stage_params_sha256)
values (3, decode('af552d36d3f79fe31698b5295d12dc1a7113ebf1c353df78812bb28b650a5d08', 'hex'));

commit;
