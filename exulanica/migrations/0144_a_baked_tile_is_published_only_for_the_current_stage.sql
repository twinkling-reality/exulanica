-- A baked tile is published only for the stage the installation runs, and a fault is cleared by a
-- recorded decision, never by changing a stored tile.
--
-- 0138 gave the tile role `record_baked_tile_bake` and nothing else, but the function accepted any
-- stage version and parameter digest its caller named. A bake published under a stage the code
-- does not run would be stored, and a reader choosing the newest row for a tile's inputs could
-- serve it. Two changes close that:
--
--   1. `baked_tile_stage` holds the bake stage this installation runs: its version and parameter
--      digest, exactly one row current. The function refuses any bake whose stage is not the
--      current one, and refuses a key whose stored row is a bake of another stage or another
--      tile rather than marking that row. A stage is a schema fact, as a table is: this migration
--      states the stage the code runs (`STAGES["baked_tile"]` in exulanica/ingest/stages, version
--      3), and a code change to the stage comes with a migration that retires it and states the
--      next, which tests/test_baked_tile_stage_postgres.py holds by comparing the two.
--   2. Readers select a tile's bake by its inputs under the current stage, the columns its key is
--      derived from (`baked_tile_id(spec, tile)`), not by the newest row for its inputs, so a row
--      of any other stage is listed and reused only under the current stage; any stored bake stays
--      reachable by its key (exulanica/world/baked_tiles.py).
--
-- `baked_tile_fault_clearance` records the owner's decision to serve a faulted tile's stored first
-- bake: a tile whose second bake differed is marked `nondeterminism_detected` (0072) and is never
-- served, which on a shared arrival world fails it for every copy. The owner's command
-- (`exulanica-tile-fault clear`) records which tile and why; readers then serve the stored bytes the
-- row names, and its failed jobs no longer fail the world. The stored row is never updated or
-- deleted: its guard trigger (0072) is unchanged, and a clearance is itself never changed.

begin;
select pg_advisory_xact_lock(119622309);

create table baked_tile_stage (
  stage_version       int         not null check (stage_version >= 1),
  stage_params_sha256 bytea       not null check (octet_length(stage_params_sha256) = 32),
  published_at        timestamptz not null default statement_timestamp(),
  retired_at          timestamptz,
  primary key (stage_version, stage_params_sha256)
);
create unique index baked_tile_stage_one_current on baked_tile_stage ((true))
  where retired_at is null;
insert into baked_tile_stage (stage_version, stage_params_sha256)
values (3, decode('57d3f6eb9c4ff5a59e981afb4919c658d1308bf749bd13ccf7b4b9cb7384c595', 'hex'));

create table baked_tile_fault_clearance (
  baked_tile_id uuid primary key references baked_tile(baked_tile_id),
  cleared_by    text not null check (cleared_by ~ '^[a-z0-9][a-z0-9:._-]{0,95}$'),
  reason        text not null check (char_length(reason) between 1 and 500),
  cleared_at    timestamptz not null default statement_timestamp()
);

create function tg_baked_tile_record_kept() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a % row is kept', tg_table_name using errcode = '23514';
  end if;
  -- Nested, not joined with AND: a record's field is resolved when its expression runs, and the
  -- clearance table has no retired_at. A stage is retired once and nothing else of it changes.
  if tg_table_name = 'baked_tile_stage' then
    if (to_jsonb(new) - 'retired_at') is not distinct from (to_jsonb(old) - 'retired_at')
       and to_jsonb(old) -> 'retired_at' = 'null'::jsonb then
      return new;
    end if;
  end if;
  raise exception 'a % row never changes', tg_table_name using errcode = '23514';
end $fn$;
create trigger tg_baked_tile_record_kept before update or delete on baked_tile_stage
  for each row execute function tg_baked_tile_record_kept();
create trigger tg_baked_tile_record_kept before update or delete on baked_tile_fault_clearance
  for each row execute function tg_baked_tile_record_kept();

-- A clearance names a faulted tile: a stored bake that agreed with itself needs none.
create function tg_baked_tile_fault_clearance_names_a_fault() returns trigger
language plpgsql as $fn$
begin
  if not exists (select 1 from baked_tile b
                  where b.baked_tile_id = new.baked_tile_id
                    and b.state = 'nondeterminism_detected') then
    raise exception 'only a tile whose bakes disagreed has a fault to clear'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_baked_tile_fault_clearance_names_a_fault before insert
  on baked_tile_fault_clearance
  for each row execute function tg_baked_tile_fault_clearance_names_a_fault();

-- 0138's function with two refusals added before anything is written: a bake for any stage but
-- the current one, and a key whose stored row is not the bake the arguments describe. `create or replace` keeps the function's grants (the tile role's EXECUTE, PUBLIC
-- none); every name stays schema-qualified and the search path stays pg_catalog and pg_temp.
do $create$
begin
  execute format($body$
create or replace function %1$I.record_baked_tile_bake(
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
  if not exists (select 1 from %1$I.baked_tile_stage s
                  where s.retired_at is null
                    and s.stage_version = p_stage_version
                    and s.stage_params_sha256 = p_stage_params_sha256) then
    raise exception 'a bake is published only for the stage this installation runs'
      using errcode = '22023';
  end if;
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
  -- The stored row is the bake these arguments describe, or it is left alone: current-stage
  -- arguments naming the key of another stage's row, or of another tile, fault nothing.
  if stored.stage_version <> p_stage_version
     or stored.stage_params_sha256 <> p_stage_params_sha256
     or stored.tile_inputs_digest <> p_tile_inputs_digest then
    raise exception 'that key names a stored bake of another stage or tile'
      using errcode = '22023';
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

do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('tg_baked_tile_record_kept',
                         'tg_baked_tile_fault_clearance_names_a_fault')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

-- Owner-written, as baked_tile is: no role but the owner writes either table, whatever a
-- provisioner's default privileges gave. Provisioning grants the runtime and read-only roles
-- SELECT (exulanica/db/roles.py READ_ONLY_TABLES): readers ask which stage is current and whether
-- a fault is cleared.
do $$ declare held record; begin
  for held in select distinct c.relname, a.grantee from pg_class c
    join pg_namespace n on n.oid = c.relnamespace,
    lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    where n.nspname = current_schema()
      and c.relname in ('baked_tile_stage', 'baked_tile_fault_clearance')
      and a.grantee <> c.relowner
  loop
    execute format('revoke insert, update, delete, truncate, references, trigger on table %I '
                   'from %s', held.relname,
      case when held.grantee = 0 then 'public' else quote_ident(pg_get_userbyid(held.grantee)) end);
  end loop;
end $$;

commit;
