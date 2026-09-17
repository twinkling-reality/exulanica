-- 0077_one_bake_per_tessellator.sql
-- A tile document may be baked by more than one tessellator, and 0072 forbade it by accident.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- WHAT WAS WRONG. Migration 0072 made `tile_inputs_digest` unique on its own. That digest is the
-- grammar's, over the tile RECORD: the city seed, the grammar pins, the catalog digest, the
-- coordinate, the level of detail, the tile and halo sizes, the ownership and halo rules and the
-- ordered edit subsequence. It says nothing about the tessellator, by design, because it is a
-- statement about the inputs a bake reads and not about the program that reads them.
--
-- But a baked tile's key is
--   uuid5(ARTIFACT_NAMESPACE, 'baked_tile:<stage version>:<params digest>:<tile_inputs_digest>')
-- so the key deliberately DOES move when the tessellator's stated version moves, which is how the
-- same tile document baked by a new tessellator becomes a new row instead of a fault. The unique
-- constraint contradicted that: one tile document, one row, whatever baked it. The two rules could
-- not both hold, and the first bake after a tessellator bump failed with a unique violation on a
-- key that had correctly moved.
--
-- That is exactly the case the key design exists for, so the constraint was forbidding the thing
-- it was meant to permit. Found on 2026-09-17 by rebaking the corridor after the tessellator
-- gained its navigation carve.
--
-- WHY IT SURVIVED TO BE MERGED, since the next reader of 0072's constraint will wonder: nothing
-- could reach it before a tessellator version moved WITH A TILE ALREADY STORED. Until that pair of
-- facts held together, every bake was either the first under its key, which inserts, or a repeat
-- of one, which compares bytes and answers identical. The corridor's rebake was the first time
-- anything in this repository had both.
--
-- WHAT IS RIGHT. Uniqueness belongs over the triple the key is derived from:
-- (stage_version, stage_params_sha256, tile_inputs_digest). That says what 0072 meant, one row per
-- bake of one tile document by one tessellator, and it says one more thing the old constraint did
-- not: two different `baked_tile_id` values can no longer claim the same derivation. The primary
-- key is a uuid5 the CALLER computes, so the database had no way to check it was computed from
-- what the row states; now a second row claiming one triple is refused whatever uuid it arrives
-- under. A caller whose uuid5 is wrong is caught by the constraint rather than by a reader noticing
-- two rows that should be one.
--
-- WHAT THIS DOES NOT CHANGE. Nothing stored moves: no row is rewritten, no digest is recomputed,
-- and every key already in the table keeps its value. A tile faulted by a genuine nondeterminism
-- stays faulted, because the fault path is about two bakes under ONE key and this is about two keys.

begin;
select pg_advisory_xact_lock(119622309);

alter table baked_tile drop constraint baked_tile_tile_inputs_digest_key;

alter table baked_tile add constraint baked_tile_one_bake_per_tessellator
  unique (stage_version, stage_params_sha256, tile_inputs_digest);

commit;
