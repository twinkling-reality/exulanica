-- 0072_baked_tiles.sql
-- Where a baked tile is recorded, and what happens when one bakes twice into different bytes.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- A baked tile is the `.owd` container the `baked_tile` stage's Node tessellator writes from one
-- tile document. `exulanica.ingest.stages.baked_tile_id` keys it:
--   uuid5(ARTIFACT_NAMESPACE, 'baked_tile:<stage version>:<params digest>:<tile_inputs_digest>')
-- and `tile_inputs_digest` is the grammar's digest over the city seed, the grammar pins, the
-- catalog digest, the tile coordinate, the level of detail, the tile and halo sizes, the ownership
-- and halo rules and the ordered edit subsequence that targets the tile's own subjects.
--
-- TWO TABLES, AND WHY EACH IS WHERE IT IS.
--
--   baked_tile             GLOBAL. A baked tile is a pure function of the inputs above. It holds
--                          no personal data, no workspace owns it, and the same key must give the
--                          same bytes for everyone: that is exactly what makes a differing rebake
--                          a fault worth an event rather than one workspace's business. So there
--                          is one row per key for the whole deployment, as `world_texture_set`
--                          holds one row per published set, and the bytes live once in the
--                          content-addressed `tiles` namespace beside `blobs` and `materials`.
--   workspace_baked_tile   PER WORKSPACE, with forced row-level security and the `ws_isolation`
--                          policy. What belongs to a workspace is not the tile but the fact that
--                          the workspace was served it, which is what migration 0062's tile quota
--                          meters: the first delivery of a tile to a workspace inserts a row and
--                          spends one of its `tiles_limit`, in one statement; later deliveries of
--                          the same tile to the same workspace are free, so walking a street that
--                          reloads its tiles does not eat a ceiling. The row is also the audit of
--                          which workspace was served which tile.
--
-- THE BOUNDARY IS A CHECK, NOT A PROMISE. `edit_delta_digest` must be the empty subsequence's
-- digest, SHA-256 of the canonical empty list. A tile whose inputs carry a person's edits is not
-- public: it belongs to a workspace-keyed table that does not exist yet, which the edit lane adds
-- when the edit log does. Until then this constraint refuses the mistake outright rather than
-- letting a personal world's tile into a table every workspace reads.
--
-- NOTHING HERE IS AUTHORITATIVE FOR GEOMETRY. Every row is derivable from the specification, the
-- grammar and the catalogs, and a row may be dropped and rebuilt. What is not derivable is the
-- fault: that one key once produced two different containers.
--
-- THE FAULT PATH (`record_baked_tile_bake`), which is the tessellator lane's gate 5:
--   * a key with no row: the row is inserted in state `baked`, and it answers `stored`;
--   * a key whose row holds exactly these bytes: nothing changes, and it answers `identical`;
--   * a key whose row holds other bytes: the stored row is KEPT as it is, byte for byte, its
--     state becomes `nondeterminism_detected`, `fault_container_sha256` records what the rebake
--     produced, `fault_detected_at` when, and it answers `nondeterminism_detected`.
-- The guard trigger refuses every other update: a changed key, a changed container, a state going
-- back to `baked`, a fault digest equal to the stored one or cleared. A fault cannot be tidied
-- away, and a faulted tile is never served.
--
-- WRITES ARE THE OFFLINE BAKE'S. `exulanica.db.roles` lists `baked_tile` read-only for the runtime
-- role, and the trigger below refuses a non-owner write, as 0065 does for the texture sets: a
-- process that answers requests reads tiles and never publishes one. `workspace_baked_tile` the
-- runtime does write, once per tile it delivers.
--
-- Integers only for anything measured, digests as `bytea` with a 32-byte check, timestamps audit
-- only and never a digest input.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The baked tiles themselves. Global, like the published texture sets.
-- --------------------------------------------------------------------------------------------

create table baked_tile (
  baked_tile_id        uuid primary key,
  stage_key            text   not null check (stage_key = 'baked_tile'),
  stage_version        int    not null check (stage_version >= 1),
  stage_params_sha256  bytea  not null check (octet_length(stage_params_sha256) = 32),
  tile_inputs_digest   bytea  not null unique check (octet_length(tile_inputs_digest) = 32),
  city_seed            bytea  not null check (octet_length(city_seed) = 32),
  grammar_pins         jsonb  not null check (jsonb_typeof(grammar_pins) = 'array'),
  catalog_digest       bytea  not null check (octet_length(catalog_digest) = 32),
  edit_delta_digest    bytea  not null check (octet_length(edit_delta_digest) = 32),
  tile_x               int    not null,
  tile_y               int    not null,
  lod                  int    not null check (lod >= 0),
  tile_size_mm         int    not null check (tile_size_mm > 0),
  halo_radius_mm       int    not null check (halo_radius_mm >= 0),
  document_sha256      bytea  not null check (octet_length(document_sha256) = 32),
  document_bytes       bigint not null check (document_bytes > 0),
  container_sha256     bytea  not null check (octet_length(container_sha256) = 32),
  container_bytes      bigint not null check (container_bytes > 0),
  store_namespace      text   not null check (store_namespace = 'tiles'),
  render_batch_sha256  bytea  not null check (octet_length(render_batch_sha256) = 32),
  nav_envelope_sha256  bytea  not null check (octet_length(nav_envelope_sha256) = 32),
  receipt              jsonb  not null check (jsonb_typeof(receipt) = 'object'),
  state                text   not null check (state in ('baked', 'nondeterminism_detected')),
  fault_container_sha256 bytea check (octet_length(fault_container_sha256) = 32),
  baked_at             timestamptz not null default statement_timestamp(),
  fault_detected_at    timestamptz,
  constraint baked_tile_fault_is_stated check (
    (state = 'baked' and fault_container_sha256 is null and fault_detected_at is null)
    or (state = 'nondeterminism_detected'
        and fault_container_sha256 is not null
        and fault_detected_at is not null
        and fault_container_sha256 <> container_sha256)
  ),
  -- The empty ordered edit subsequence: sha256 of the canonical JSON `[]`.
  constraint baked_tile_holds_no_edits check (
    edit_delta_digest = decode(
      '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945', 'hex')
  )
);

create index baked_tile_by_city on baked_tile (city_seed, lod, tile_x, tile_y);

create function tg_baked_tile_guard() returns trigger language plpgsql as $fn$
begin
  if not pg_has_role(current_user,
                     (select c.relowner from pg_class c where c.oid = tg_relid),
                     'MEMBER') then
    raise exception 'a baked tile is published by the offline bake, not by %', current_user
      using errcode = 'insufficient_privilege';
  end if;
  if tg_op = 'DELETE' then
    return old;
  end if;
  if tg_op = 'INSERT' then
    if new.state <> 'baked' then
      raise exception 'a baked tile is stored in the baked state' using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if new.baked_tile_id is distinct from old.baked_tile_id
     or new.tile_inputs_digest is distinct from old.tile_inputs_digest
     or new.container_sha256 is distinct from old.container_sha256
     or new.container_bytes is distinct from old.container_bytes
     or new.document_sha256 is distinct from old.document_sha256
     or new.store_namespace is distinct from old.store_namespace
     or new.render_batch_sha256 is distinct from old.render_batch_sha256
     or new.nav_envelope_sha256 is distinct from old.nav_envelope_sha256
     or new.baked_at is distinct from old.baked_at then
    raise exception 'a baked tile is what it was baked as; rebake under a new key'
      using errcode = 'check_violation';
  end if;
  if old.state = 'nondeterminism_detected' then
    raise exception 'a tile that baked twice into different bytes stays that way'
      using errcode = 'check_violation';
  end if;
  if new.state <> 'nondeterminism_detected' then
    raise exception 'the only change a stored tile takes is a detected fault'
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_baked_tile_guard
  before insert or update or delete on baked_tile
  for each row execute function tg_baked_tile_guard();

-- The one way a bake reaches this table, and the one place the fault is decided.
create function record_baked_tile_bake(
  p_baked_tile_id       uuid,
  p_stage_version       int,
  p_stage_params_sha256 bytea,
  p_tile_inputs_digest  bytea,
  p_city_seed           bytea,
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
) returns text language plpgsql as $fn$
declare
  stored record;
begin
  perform pg_advisory_xact_lock(hashtextextended('baked-tile:' || p_baked_tile_id::text, 0));
  select * into stored from baked_tile where baked_tile_id = p_baked_tile_id;
  if not found then
    insert into baked_tile (
      baked_tile_id, stage_key, stage_version, stage_params_sha256, tile_inputs_digest,
      city_seed, grammar_pins, catalog_digest, edit_delta_digest, tile_x, tile_y, lod,
      tile_size_mm, halo_radius_mm, document_sha256, document_bytes, container_sha256,
      container_bytes, store_namespace, render_batch_sha256, nav_envelope_sha256, receipt, state
    ) values (
      p_baked_tile_id, 'baked_tile', p_stage_version, p_stage_params_sha256, p_tile_inputs_digest,
      p_city_seed, p_grammar_pins, p_catalog_digest, p_edit_delta_digest, p_tile_x, p_tile_y,
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
  update baked_tile
     set state = 'nondeterminism_detected',
         fault_container_sha256 = p_container_sha256,
         fault_detected_at = statement_timestamp()
   where baked_tile_id = p_baked_tile_id
     and state = 'baked';
  return 'nondeterminism_detected';
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 2. Which workspace was served which tile: the ledger 0062's ceiling is charged against.
-- --------------------------------------------------------------------------------------------

create table workspace_baked_tile (
  workspace_id  uuid not null,
  baked_tile_id uuid not null references baked_tile(baked_tile_id),
  served_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, baked_tile_id)
);

create function tg_workspace_baked_tile_guard() returns trigger language plpgsql as $fn$
declare
  quota record;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    raise exception 'a delivery is recorded once and never edited' using errcode = 'check_violation';
  end if;
  perform pg_advisory_xact_lock(
    hashtextextended('workspace-tile-quota:' || new.workspace_id::text, 0));
  select * into quota from workspace_tile_quota where workspace_id = new.workspace_id;
  if not found then
    raise exception 'this workspace has no tile quota, so it may be served no tile'
      using errcode = 'program_limit_exceeded';
  end if;
  if quota.tiles_used >= quota.tiles_limit then
    raise exception 'this workspace has been served % tiles, its limit', quota.tiles_used
      using errcode = 'program_limit_exceeded';
  end if;
  update workspace_tile_quota
     set tiles_used = tiles_used + 1
   where workspace_id = new.workspace_id;
  new.served_at := statement_timestamp();
  return new;
end $fn$;

create trigger tg_workspace_baked_tile_guard
  before insert or update on workspace_baked_tile
  for each row execute function tg_workspace_baked_tile_guard();

do $$ declare t text; begin
  foreach t in array array['workspace_baked_tile'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------------------------
-- 3. The 0041 guard: tile bytes are delivered under the asset read lock, like every other asset.
-- --------------------------------------------------------------------------------------------

do $$ declare t text; begin
  foreach t in array array['baked_tile', 'workspace_baked_tile'] loop
    execute format(
      'create trigger aaa_asset_read_mutation before insert or update or delete on %I '
      'for each row execute function tg_asset_read_mutation()', t);
  end loop;
end $$;

commit;
