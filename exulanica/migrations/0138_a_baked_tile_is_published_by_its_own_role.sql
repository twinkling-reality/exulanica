-- A baked tile is published by its own role, through one function, never by the owner's connection.
--
-- Until now the generated-tile worker published each bake through the owner's connection, because
-- `tg_baked_tile_guard` (0072) refuses a write by any role that is not a member of the table's
-- owner. On a public server that worker runs for as long as the server does, beside a Node child
-- and the web package's dependencies, holding a credential that can alter and drop every table.
--
-- This migration makes `record_baked_tile_bake` (0072, renamed in 0081) run with its owner's
-- rights, so the guard's owner check passes inside it and nowhere else, and leaves exactly one
-- role able to call it: `exulanica_tiles`, which `exulanica-db` provisions after the migrations
-- with no other privilege (exulanica/db/tiles_role.py). The API's role, the read-only role and
-- PUBLIC cannot execute it. What it does is unchanged: store a bake once, answer `identical` for
-- the same bytes, and mark a fault for different bytes. A stored tile is never overwritten.
--
-- Every name inside the function is schema-qualified, and its search_path is pinned to pg_catalog
-- and pg_temp, so no object a caller creates can stand in for one it names. The schema is the one
-- this migration runs in, written into the body when it is created.

begin;
select pg_advisory_xact_lock(119622309);

drop function record_baked_tile_bake(
  uuid, int, bytea, bytea, bytea, jsonb, bytea, bytea, int, int, int, int, int,
  bytea, bigint, bytea, bigint, bytea, bytea, jsonb
);

do $create$
begin
  execute format($body$
create function %1$I.record_baked_tile_bake(
  p_baked_tile_id       uuid,
  p_stage_version       int,
  p_stage_params_sha256 bytea,
  p_tile_inputs_digest  bytea,
  p_world_seed          bytea,
  p_grammar_pins        jsonb,
  p_catalog_digest      bytea,
  p_edit_delta_digest   bytea,
  p_tile_x              int,
  p_tile_y              int,
  p_lod                 int,
  p_tile_size_mm        int,
  p_halo_radius_mm      int,
  p_document_sha256     bytea,
  p_document_bytes      bigint,
  p_container_sha256    bytea,
  p_container_bytes     bigint,
  p_render_batch_sha256 bytea,
  p_nav_envelope_sha256 bytea,
  p_receipt             jsonb
) returns text
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $fn$
declare
  stored record;
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('baked-tile:' || p_baked_tile_id::text, 0));
  select * into stored from %1$I.baked_tile where baked_tile_id = p_baked_tile_id;
  if not found then
    insert into %1$I.baked_tile (
      baked_tile_id, stage_key, stage_version, stage_params_sha256, tile_inputs_digest,
      world_seed, grammar_pins, catalog_digest, edit_delta_digest, tile_x, tile_y, lod,
      tile_size_mm, halo_radius_mm, document_sha256, document_bytes, container_sha256,
      container_bytes, store_namespace, render_batch_sha256, nav_envelope_sha256, receipt, state
    ) values (
      p_baked_tile_id, 'baked_tile', p_stage_version, p_stage_params_sha256, p_tile_inputs_digest,
      p_world_seed, p_grammar_pins, p_catalog_digest, p_edit_delta_digest, p_tile_x, p_tile_y,
      p_lod, p_tile_size_mm, p_halo_radius_mm, p_document_sha256, p_document_bytes,
      p_container_sha256, p_container_bytes, 'tiles', p_render_batch_sha256, p_nav_envelope_sha256,
      p_receipt, 'baked'
    );
    return 'stored';
  end if;
  if stored.container_sha256 = p_container_sha256 then
    if stored.state = 'nondeterminism_detected' then
      return 'nondeterminism_detected';
    end if;
    return 'identical';
  end if;
  update %1$I.baked_tile
     set state = 'nondeterminism_detected',
         fault_container_sha256 = p_container_sha256,
         fault_detected_at = pg_catalog.statement_timestamp()
   where baked_tile_id = p_baked_tile_id
     and state = 'baked';
  return 'nondeterminism_detected';
end $fn$
$body$, current_schema());
end $create$;

-- PostgreSQL gives EXECUTE on a new function to PUBLIC. This one writes a global table with its
-- owner's rights, so nobody holds it until provisioning grants it to `exulanica_tiles` alone.
revoke all on function record_baked_tile_bake(
  uuid, int, bytea, bytea, bytea, jsonb, bytea, bytea, int, int, int, int, int,
  bytea, bigint, bytea, bigint, bytea, bytea, jsonb
) from public;

commit;
