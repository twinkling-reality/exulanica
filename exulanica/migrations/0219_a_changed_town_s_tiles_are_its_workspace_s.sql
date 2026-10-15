-- 0219_a_changed_town_s_tiles_are_its_workspace_s.sql
-- A made town's tiles baked with a version's changes to its buildings: its workspace's alone.
--
-- WHY A TABLE OF ITS OWN. A public bake (0072) is global and content-addressed, and holds no edit:
-- baked_tile_holds_no_edits refuses a tile whose edit delta digest is not the empty fold, because a
-- tile carrying a person's change is not public. A version of a made town whose buildings a person
-- removed or stood taller (0217, exulanica/world/town_parts.py) is drawn from tiles baked with those
-- changes, so those tiles are kept here, by workspace, and their bytes in the workspace's own
-- `version-tiles` namespace of the content store. A tile the changes leave as it was is still the
-- public bake (exulanica/world/version_tiles.py).
--
-- THE KEY. A changed tile's key folds the version's changes to its buildings, in identity order,
-- into the tile record's edit delta digest (exulanica/world/version_tiles.py): the same changes give
-- the same key however many undos led there, and a version whose changes leave a tile's document as
-- it was keeps that tile's public key.
--
-- WHO WRITES IT. The tile worker bakes a version's tile for a `bake_version_tile` job, claimed as
-- the runtime role in the job's workspace (exulanica/ingest/generated_tiles.py). It records the
-- bytes in the namespace's inventory first, as the runtime role, then puts them, then publishes the
-- bake through record_version_baked_tile as exulanica_tiles, which holds EXECUTE on it and on
-- record_baked_tile_bake and nothing else (exulanica/db/tiles_role.py). The function runs as
-- exulanica_definer, so row-level security binds it to the session's workspace; it writes only for
-- a `bake_version_tile` job of that workspace that is running under the claim token it is given and
-- names this version, tile and key, and the row's workspace and world are the job's, never the
-- caller's. No role holds a direct grant to write the table.
--
-- ERASURE. The rows are a world's: world_erase_rows (0195, last made again in 0213) is made again
-- here with one statement more, deleting them before the world's registration, so a world's
-- erasure (0197) and a workspace's tombstone take them. A world's erasure also cancels the world's
-- queued and running `bake_version_tile` jobs and enqueues the purge of the bytes its rows named,
-- on its own tombstone, unless a row of another world still names them; a workspace's tombstone
-- enqueues every object the namespace still holds. The inventory is never deleted, so a tombstone
-- finds the objects of rows erased before it; only the purger marks one purged.
-- version_tile_purge_is_authorized holds a purge to its tombstone.
--
-- RESTORE. A restore carries world_erasure (0197) before it replays tombstones: written again, an
-- erasure deletes the restored rows, and its world tombstone, replayed after it, enqueues the bytes'
-- purge (tg_version_tile_purge_on_tombstone below).
begin;
select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The namespace's inventory.
-- --------------------------------------------------------------------------------------------

create table world_version_tile_object (
  workspace_id   uuid not null,
  object_id      uuid not null default uuidv7(),
  -- The world whose version's bake the bytes are, so the world's erasure finds them.
  world_id       text not null check (length(world_id) between 1 and 200),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size      bigint not null check (byte_size > 0),
  recorded_at    timestamptz not null default statement_timestamp(),
  -- Set by the purger, after the bytes are gone, and only when a tombstone asked for them.
  purged_at      timestamptz,
  primary key (workspace_id, object_id)
);

-- One live record per object: bytes written again after a purge are a new record.
create unique index world_version_tile_object_live
  on world_version_tile_object (workspace_id, content_sha256) where purged_at is null;
create index world_version_tile_object_by_world
  on world_version_tile_object (workspace_id, world_id) where purged_at is null;

comment on table world_version_tile_object is
  'Every object a workspace''s version tiles namespace holds, recorded before its bytes and named '
  'by the world whose version they were baked for; never deleted, so a tombstone finds the '
  'objects of rows erased before it. Only the purger sets purged_at.';

-- --------------------------------------------------------------------------------------------
-- 2. A version's baked tiles.
-- --------------------------------------------------------------------------------------------

create table world_version_baked_tile (
  workspace_id         uuid   not null,
  world_id             text   not null,
  baked_tile_id        uuid   not null,
  stage_key            text   not null check (stage_key = 'baked_tile'),
  stage_version        int    not null check (stage_version >= 1),
  stage_params_sha256  bytea  not null check (octet_length(stage_params_sha256) = 32),
  tile_inputs_digest   bytea  not null check (octet_length(tile_inputs_digest) = 32),
  edit_delta_digest    bytea  not null check (octet_length(edit_delta_digest) = 32),
  tile_x               int    not null,
  tile_y               int    not null,
  lod                  int    not null check (lod >= 0),
  document_sha256      bytea  not null check (octet_length(document_sha256) = 32),
  document_bytes       bigint not null check (document_bytes > 0),
  container_sha256     bytea  not null check (octet_length(container_sha256) = 32),
  container_bytes      bigint not null check (container_bytes > 0),
  store_namespace      text   not null check (store_namespace = 'version-tiles'),
  render_batch_sha256  bytea  not null check (octet_length(render_batch_sha256) = 32),
  nav_envelope_sha256  bytea  not null check (octet_length(nav_envelope_sha256) = 32),
  receipt              jsonb  not null check (jsonb_typeof(receipt) = 'object'),
  state                text   not null check (state in ('baked', 'nondeterminism_detected')),
  fault_container_sha256 bytea check (octet_length(fault_container_sha256) = 32),
  baked_at             timestamptz not null default statement_timestamp(),
  fault_detected_at    timestamptz,
  primary key (workspace_id, baked_tile_id),
  unique (workspace_id, stage_version, stage_params_sha256, tile_inputs_digest),
  foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  constraint world_version_baked_tile_fault_is_stated check (
    (state = 'baked' and fault_container_sha256 is null and fault_detected_at is null)
    or (state = 'nondeterminism_detected'
        and fault_container_sha256 is not null
        and fault_detected_at is not null
        and fault_container_sha256 <> container_sha256)
  ),
  -- A tile carrying no change is the public bake (0072), never a workspace's: the empty fold, the
  -- sha256 of the canonical JSON `[]`, is refused here as 0072 requires it there.
  constraint world_version_baked_tile_holds_changes check (
    edit_delta_digest <> decode(
      '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945', 'hex')
  )
);

comment on table world_version_baked_tile is
  'A made town''s tile baked with a version''s changes to its buildings, its workspace''s alone, '
  'its bytes in the workspace''s version tiles namespace. Written only by '
  'record_version_baked_tile for a claimed bake_version_tile job; deleted only when its world is '
  'erased whole.';

create function tg_world_version_tile_object_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.purged_at is not null then
      raise exception 'a version tile object arrives unpurged' using errcode = 'check_violation';
    end if;
    -- The workspace's lock, which every tombstone takes without waiting (0137).
    perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024));
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp()) then
      perform tombstone_refuse('world_version_tile_object');
    end if;
    if not exists (select 1 from world_identity w
                    where w.workspace_id = new.workspace_id and w.world_id = new.world_id) then
      raise exception 'a version tile object names a world its workspace holds'
        using errcode = 'foreign_key_violation';
    end if;
    new.recorded_at := statement_timestamp();
    return new;
  end if;
  if old.purged_at is not null then
    if new is distinct from old then
      raise exception 'a purged version tile object does not change again'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if (to_jsonb(new) - 'purged_at') is distinct from (to_jsonb(old) - 'purged_at')
     or new.purged_at is null then
    raise exception 'only the purger writes a version tile object, and only its purge'
      using errcode = 'check_violation';
  end if;
  if not exists (
       select 1 from purge_job pj
        where pj.workspace_id = new.workspace_id
          and pj.target_kind = 'version_tile'
          and pj.target_ref = new.content_sha256
          and version_tile_purge_is_authorized(new.workspace_id, pj.tombstone_id,
                                               new.content_sha256)) then
    raise exception 'a version tile object is marked purged only when a tombstone asked for it'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create function tg_world_version_baked_tile_guard() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    return old;
  end if;
  perform assert_workspace_context(new.workspace_id);
  if current_user <> 'exulanica_definer' then
    raise exception 'a version''s baked tile is published through record_version_baked_tile, not by %',
      current_user using errcode = 'insufficient_privilege';
  end if;
  if tg_op = 'INSERT' then
    if new.state <> 'baked' then
      raise exception 'a version''s baked tile is stored in the baked state'
        using errcode = 'check_violation';
    end if;
    new.baked_at := statement_timestamp();
    return new;
  end if;
  if (to_jsonb(new) - 'state' - 'fault_container_sha256' - 'fault_detected_at')
       is distinct from (to_jsonb(old) - 'state' - 'fault_container_sha256' - 'fault_detected_at') then
    raise exception 'a version''s baked tile is what it was baked as; rebake under a new key'
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

create trigger tg_world_version_tile_object_guard
  before insert or update on world_version_tile_object
  for each row execute function tg_world_version_tile_object_guard();
create trigger tg_world_version_tile_object_no_delete before delete on world_version_tile_object
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_world_version_baked_tile_guard
  before insert or update on world_version_baked_tile
  for each row execute function tg_world_version_baked_tile_guard();
-- Deleted only by the definers' owner, when its world is erased whole (0195's rule).
create trigger tg_world_record_erased_whole before delete on world_version_baked_tile
  for each row execute function tg_world_record_erased_whole();
-- Tile bytes are delivered under the asset read lock, like every other asset (0041, 0072).
create trigger aaa_asset_read_mutation before insert or update or delete on world_version_baked_tile
  for each row execute function tg_asset_read_mutation();

-- --------------------------------------------------------------------------------------------
-- 3. The one way a bake is published: for a claimed job of the session's workspace.
-- --------------------------------------------------------------------------------------------

-- 0144's publish with the job in place of trust: the session's workspace, a running
-- `bake_version_tile` job of it under this claim token, and that job naming this version, tile,
-- inputs digest and fold; the bake's id must be the key those inputs give. The bytes must be in the
-- inventory, unpurged, under the lock the purger takes for them, so a purge and a publish of the
-- same bytes never cross.
do $create$
begin
  execute format($body$
create function %1$I.record_version_baked_tile(
  p_job_id              uuid,
  p_claim_token         uuid,
  p_version_id          uuid,
  p_baked_tile_id       uuid,
  p_stage_version       int,
  p_stage_params_sha256 bytea,
  p_tile_inputs_digest  bytea,
  p_edit_delta_digest   bytea,
  p_tile_x              int,
  p_tile_y              int,
  p_lod                 int,
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
  v_workspace uuid := %1$I.current_workspace();
  v_job record;
  v_content text := pg_catalog.encode(p_container_sha256, 'hex');
  v_key bytea;
  stored record;
begin
  if v_workspace is null then
    raise exception 'a version''s bake is published in its job''s workspace: set the workspace first'
      using errcode = '42501';
  end if;
  select j.workspace_id, j.payload into v_job
    from %1$I.job j
   where j.job_id = p_job_id
     and j.workspace_id = v_workspace
     and j.kind = 'bake_version_tile'
     and j.state = 'running'
     and j.claim_token = p_claim_token;
  if not found then
    raise exception 'no claimed bake_version_tile job of this workspace publishes this bake'
      using errcode = '42501';
  end if;
  if v_job.payload ->> 'version_id' is distinct from p_version_id::text
     or v_job.payload ->> 'tile_inputs_digest'
          is distinct from pg_catalog.encode(p_tile_inputs_digest, 'hex')
     or v_job.payload ->> 'edit_delta_digest'
          is distinct from pg_catalog.encode(p_edit_delta_digest, 'hex')
     or v_job.payload -> 'tile' is distinct from pg_catalog.jsonb_build_array(p_tile_x, p_tile_y) then
    raise exception 'the claimed job names another version or tile than this bake'
      using errcode = '22023';
  end if;
  if not exists (select 1 from %1$I.baked_tile_stage s
                  where s.retired_at is null
                    and s.stage_version = p_stage_version
                    and s.stage_params_sha256 = p_stage_params_sha256) then
    raise exception 'a bake is published only for the stage this installation runs'
      using errcode = '22023';
  end if;
  -- The bake's id is its tile's key, derived from the stage and the inputs digest as the tile
  -- worker derives it (exulanica/ingest/stages baked_tile_id: uuid5 of the artifact namespace and
  -- "baked_tile:<version>:<params digest>:<inputs digest>"), so no caller files a bake under
  -- another tile's id.
  v_key := public.digest(
    pg_catalog.decode('6f3d5b2e8a415c6b9d0e1f2a3b4c5d6e', 'hex')
      || pg_catalog.convert_to('baked_tile:' || p_stage_version::text || ':'
           || pg_catalog.encode(p_stage_params_sha256, 'hex') || ':'
           || pg_catalog.encode(p_tile_inputs_digest, 'hex'), 'UTF8'),
    'sha1');
  v_key := pg_catalog.set_byte(v_key, 6, (pg_catalog.get_byte(v_key, 6) & 15) | 80);
  v_key := pg_catalog.set_byte(v_key, 8, (pg_catalog.get_byte(v_key, 8) & 63) | 128);
  if pg_catalog.encode(pg_catalog.substr(v_key, 1, 16), 'hex')::uuid
       <> p_baked_tile_id then
    raise exception 'a bake''s id is its tile''s key, which these inputs do not give'
      using errcode = '22023';
  end if;
  -- The purger's lock for these bytes (exulanica/store/namespaces.py version_tile_lock_key).
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'version-tile:' || v_workspace::text || ':' || v_content, 0));
  if not exists (select 1 from %1$I.world_version_tile_object o
                  where o.workspace_id = v_workspace
                    and o.world_id = v_job.payload ->> 'world_id'
                    and o.content_sha256 = v_content
                    and o.purged_at is null) then
    raise exception 'a version''s bake names bytes its namespace''s inventory holds for its world'
      using errcode = '23503';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'version-baked-tile:' || v_workspace::text || ':' || p_baked_tile_id::text, 0));
  select * into stored from %1$I.world_version_baked_tile b
   where b.workspace_id = v_workspace and b.baked_tile_id = p_baked_tile_id;
  if not found then
    insert into %1$I.world_version_baked_tile (
      workspace_id, world_id, baked_tile_id, stage_key, stage_version, stage_params_sha256,
      tile_inputs_digest, edit_delta_digest, tile_x, tile_y, lod, document_sha256, document_bytes,
      container_sha256, container_bytes, store_namespace, render_batch_sha256,
      nav_envelope_sha256, receipt, state
    ) values (
      v_workspace, v_job.payload ->> 'world_id', p_baked_tile_id, 'baked_tile', p_stage_version,
      p_stage_params_sha256, p_tile_inputs_digest, p_edit_delta_digest, p_tile_x, p_tile_y, p_lod,
      p_document_sha256, p_document_bytes, p_container_sha256, p_container_bytes, 'version-tiles',
      p_render_batch_sha256, p_nav_envelope_sha256, p_receipt, 'baked'
    );
    return 'stored';
  end if;
  if stored.world_id <> v_job.payload ->> 'world_id'
     or stored.stage_version <> p_stage_version
     or stored.stage_params_sha256 <> p_stage_params_sha256
     or stored.tile_inputs_digest <> p_tile_inputs_digest then
    raise exception 'that key names a stored bake of another world, stage or tile'
      using errcode = '22023';
  end if;
  if stored.container_sha256 = p_container_sha256 then
    if stored.state = 'nondeterminism_detected' then
      return 'nondeterminism_detected';
    end if;
    return 'identical';
  end if;
  update %1$I.world_version_baked_tile
     set state = 'nondeterminism_detected',
         fault_container_sha256 = p_container_sha256,
         fault_detected_at = pg_catalog.statement_timestamp()
   where workspace_id = v_workspace
     and baked_tile_id = p_baked_tile_id
     and state = 'baked';
  return 'nondeterminism_detected';
end $fn$
$body$, current_schema());
end $create$;

comment on function record_version_baked_tile(uuid, uuid, uuid, uuid, int, bytea, bytea, bytea,
  int, int, int, bytea, bigint, bytea, bigint, bytea, bytea, jsonb) is
  'Publish one bake of a version''s changed tile for the running bake_version_tile job of the '
  'session''s workspace that names it: stored, identical, or nondeterminism_detected. Runs as '
  'exulanica_definer; the tile role alone may execute it.';

-- --------------------------------------------------------------------------------------------
-- 4. Erasure: a world's and a workspace's, and the purge of the bytes.
-- --------------------------------------------------------------------------------------------

-- Whether a tombstone may destroy these bytes from its workspace's version tiles namespace. A
-- workspace tombstone may destroy anything in it: the namespace is the workspace's alone, and all
-- of it goes (0126's rule). A world tombstone may destroy the bytes of its world's bakes that no
-- stored bake still names. No other scope reaches it.
create function version_tile_purge_is_authorized(
  p_workspace uuid, p_tombstone uuid, p_content text
) returns boolean
language sql volatile security definer as $fn$
  select p_workspace = current_workspace() and p_content ~ '^[0-9a-f]{64}$' and exists (
    select 1 from tombstone t
     where t.workspace_id = p_workspace
       and t.tombstone_id = p_tombstone
       and t.effective_at <= now()
       and (t.scope::text = 'workspace'
            or (t.scope::text = 'world'
                and exists (select 1 from world_erasure e
                              join world_version_tile_object o
                                on o.workspace_id = e.workspace_id and o.world_id = e.world_id
                             where e.workspace_id = p_workspace
                               and e.tombstone_id = p_tombstone
                               and o.content_sha256 = p_content)
                and not exists (select 1 from world_version_baked_tile b
                                 where b.workspace_id = p_workspace
                                   and (b.container_sha256 = decode(p_content, 'hex')
                                        or b.fault_container_sha256 = decode(p_content, 'hex'))))));
$fn$;

comment on function version_tile_purge_is_authorized(uuid, uuid, text) is
  'May this tombstone destroy these bytes from its workspace''s version tiles namespace: it is '
  'effective and in this session''s workspace, and it is the workspace''s tombstone, or the '
  'erasure tombstone of the world the bytes were baked for while no stored bake names them. For '
  'the purge role.';

-- A world's erasure stops its version bakes and enqueues the purge of its bakes' bytes on its own
-- tombstone, unless another world's stored bake names them. Its order among world_erasure's AFTER
-- triggers does not matter: the inventory names the world, and no other trigger deletes it. A
-- restore carries the erasure before it replays tombstones, so there the tombstone is not yet held
-- and the tombstone, replayed after it, enqueues the purge instead.
create function tg_world_erasure_takes_version_tiles() returns trigger
language plpgsql security definer as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  update job set state = 'cancelled', completed_at = statement_timestamp(),
    lease_expires_at = null, claim_token = null, claimed_by = null,
    last_error = 'world_removed', failure_class = 'world_removed'
   where workspace_id = new.workspace_id and kind = 'bake_version_tile'
     and payload->>'world_id' = new.world_id and state in ('queued', 'running');
  if exists (select 1 from tombstone t
              where t.tombstone_id = new.tombstone_id and t.workspace_id = new.workspace_id) then
    -- No conflict target: naming one needs SELECT on the queue, which this owner does not hold.
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    select distinct new.tombstone_id, new.workspace_id, 'version_tile', o.content_sha256
      from world_version_tile_object o
     where o.workspace_id = new.workspace_id
       and o.world_id = new.world_id
       and o.purged_at is null
       and not exists (select 1 from world_version_baked_tile b
                        where b.workspace_id = o.workspace_id
                          and b.world_id <> new.world_id
                          and (b.container_sha256 = decode(o.content_sha256, 'hex')
                               or b.fault_container_sha256 = decode(o.content_sha256, 'hex')))
    on conflict do nothing;
  end if;
  return null;
end $fn$;

comment on function tg_world_erasure_takes_version_tiles() is
  'A world erasure''s cancel of the world''s version bakes and the purge of their bytes on its '
  'tombstone. Runs as exulanica_definer, in the erasure''s own workspace.';

create trigger tg_world_erasure_takes_version_tiles after insert on world_erasure
  for each row execute function tg_world_erasure_takes_version_tiles();

-- A workspace tombstone enqueues every object the namespace still holds; a world tombstone,
-- replayed by a restore after the erasure it names, enqueues that world's objects no stored bake
-- of another world names. Its order among the tombstone's AFTER triggers does not matter: it
-- reads the inventory, which no trigger deletes.
create function tg_version_tile_purge_on_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope::text = 'workspace' then
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    select new.tombstone_id, new.workspace_id, 'version_tile', o.content_sha256
      from world_version_tile_object o
     where o.workspace_id = new.workspace_id
       and o.purged_at is null
    on conflict (tombstone_id, target_kind, target_ref) do nothing;
  elsif new.scope::text = 'world' then
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    select distinct new.tombstone_id, e.workspace_id, 'version_tile', o.content_sha256
      from world_erasure e
      join world_version_tile_object o
        on o.workspace_id = e.workspace_id and o.world_id = e.world_id
     where e.workspace_id = new.workspace_id
       and e.tombstone_id = new.tombstone_id
       and o.purged_at is null
       and not exists (select 1 from world_version_baked_tile b
                        where b.workspace_id = o.workspace_id
                          and b.world_id <> e.world_id
                          and (b.container_sha256 = decode(o.content_sha256, 'hex')
                               or b.fault_container_sha256 = decode(o.content_sha256, 'hex')))
    on conflict (tombstone_id, target_kind, target_ref) do nothing;
  end if;
  return new;
end $fn$;

create trigger tg_version_tile_purge_on_tombstone
  after insert on tombstone
  for each row execute function tg_version_tile_purge_on_tombstone();

-- --------------------------------------------------------------------------------------------
-- 5. The purge: its target kind, and when a tombstone's purge is complete.
-- --------------------------------------------------------------------------------------------

alter table purge_job drop constraint purge_job_target_kind_check;
alter table purge_job add constraint purge_job_target_kind_check
  check (target_kind in ('blob', 'artifact', 'embedding', 'text_chunk', 'material_bake',
                         'workspace_asset', 'look', 'workspace_style_pack', 'web_picture',
                         'version_tile'));

-- Re-stated from the web pictures migration (0215) with two clauses added: a version tile job whose
-- object is not yet marked purged, and, for a workspace tombstone, any version tile object still
-- holding bytes. Everything it asks is asked unchanged.
create or replace function tombstone_purge_is_complete(p_tombstone uuid) returns boolean
language plpgsql volatile as $fn$
declare v_scope text; v_workspace uuid;
begin
  select t.scope::text, t.workspace_id into v_scope, v_workspace
    from tombstone t where t.tombstone_id=p_tombstone;
  if v_scope is null then return false; end if;
  if not caption_vector_purge_is_complete(v_workspace, p_tombstone) then return false; end if;
  if exists (
    select 1 from purge_job pj where pj.tombstone_id=p_tombstone and (
      pj.state <> 'done'
      or (pj.target_kind='blob' and exists (select 1 from blob b
          where b.blob_sha256=decode(pj.target_ref,'hex') and b.purged_at is null))
      or (pj.target_kind='artifact' and exists (select 1 from artifact a
          where a.workspace_id=pj.workspace_id and a.content_sha256=decode(pj.target_ref,'hex')
            and a.purged_at is null))
      or (pj.target_kind='embedding' and exists (select 1 from embedding e
          where e.workspace_id=pj.workspace_id and e.embedding_id=pj.target_ref::uuid))
      or (pj.target_kind='material_bake' and exists (select 1 from material_bake m
          where m.workspace_id=pj.workspace_id and m.content_sha256=decode(pj.target_ref,'hex')
            and m.purged_at is null))
      or (pj.target_kind='workspace_asset' and exists (select 1 from workspace_asset_blob w
          where w.workspace_id=pj.workspace_id and w.content_sha256=pj.target_ref
            and w.purged_at is null))
      or (pj.target_kind='look' and exists (select 1 from look_object o
          where o.workspace_id=pj.workspace_id and o.content_sha256=pj.target_ref
            and o.purged_at is null))
      or (pj.target_kind='workspace_style_pack' and exists (
          select 1 from workspace_style_pack_blob s
           where s.workspace_id=pj.workspace_id and s.content_sha256=pj.target_ref
             and s.purged_at is null))
      or (pj.target_kind='web_picture' and exists (
          select 1 from web_picture_object w
           where w.workspace_id=pj.workspace_id and w.content_sha256=pj.target_ref
             and w.purged_at is null))
      or (pj.target_kind='version_tile' and exists (
          select 1 from world_version_tile_object v
           where v.workspace_id=pj.workspace_id and v.content_sha256=pj.target_ref
             and v.purged_at is null)))) then
    return false;
  end if;
  if v_scope='workspace' then
    return not exists (select 1 from capture c join blob b on b.blob_sha256=c.blob_sha256
                        where c.workspace_id=v_workspace and b.purged_at is null)
       and not exists (select 1 from artifact a where a.workspace_id=v_workspace
                        and a.content_sha256 is not null and a.purged_at is null)
       and not exists (select 1 from embedding e where e.workspace_id=v_workspace)
       and not exists (select 1 from material_bake m where m.workspace_id=v_workspace
                        and m.content_sha256 is not null and m.purged_at is null)
       and not exists (select 1 from workspace_asset_blob w where w.workspace_id=v_workspace
                        and w.purged_at is null)
       and not exists (select 1 from look_object o where o.workspace_id=v_workspace
                        and o.purged_at is null)
       and not exists (select 1 from workspace_style_pack_blob s where s.workspace_id=v_workspace
                        and s.purged_at is null)
       and not exists (select 1 from web_picture_object w where w.workspace_id=v_workspace
                        and w.purged_at is null)
       and not exists (select 1 from world_version_tile_object v where v.workspace_id=v_workspace
                        and v.purged_at is null);
  end if;
  return true;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 6. world_erase_rows, made again with one statement more.
-- --------------------------------------------------------------------------------------------

-- 0213's body with the version's baked tiles deleted beside the world's other records, before its
-- registration. Its name, signature, owner, path and grants stay as they were (0183's way of
-- replacing a definer).
create or replace function world_erase_rows(p_workspace uuid, p_world text) returns void
language plpgsql security definer as $fn$
declare
  v_society uuid;
begin
  perform assert_workspace_context(p_workspace);
  -- Every parent a writer without the workspace lock adds to or changes, before the first
  -- delete, in the order those writers take them (LOCKS).
  perform pg_advisory_xact_lock(hashtextextended('world_project:' || p_workspace::text, 0));
  perform 1 from world_project x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.project_id for update;
  perform 1 from world_project_item x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.item_id for update;
  perform 1 from saved_world_entry x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.entry_id for update;
  perform 1 from world_alternate_version x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.version_id for update;
  perform 1 from world_style_state x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  perform 1 from world_style_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.preview_id for update;
  perform 1 from world_structure_state x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  perform 1 from world_structure_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.preview_id for update;
  perform 1 from world_interaction_policy_state x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  perform 1 from world_interaction_policy_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.preview_id for update;
  perform 1 from piece_request x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.piece_request_id for update;
  perform 1 from signal_comparison_start x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.comparison_id for update;
  perform 1 from signal_comparison_run x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.run_id for update;
  -- The world's societies, each whole and with its own locks (0183).
  for v_society in
    select s.society_id from world_society s
     where s.workspace_id = p_workspace and s.world_id = p_world
     order by s.society_id
  loop
    perform society_erase_rows(p_workspace, v_society);
  end loop;
  perform 1 from door_grant x
   where x.workspace_id = p_workspace and x.world_id = p_world
   order by x.grant_id for update;
  -- Every world table references the registration: from here no row is added under the world.
  perform 1 from world_identity x
   where x.workspace_id = p_workspace and x.world_id = p_world for update;
  insert into piece_erasure_settlement
    (workspace_id,piece_request_id,reservation_id,reservation_authority_id,reservation_holder,
     piece_batch_id,worst_case_usd,basis,usd)
    select p.workspace_id,p.piece_request_id,p.reservation_id,p.reservation_authority_id,
           p.reservation_holder,p.piece_batch_id,p.worst_case_usd,s.basis,s.usd
      from piece_request p left join piece_settlement s
        on s.workspace_id = p.workspace_id and s.piece_request_id = p.piece_request_id
     where p.workspace_id = p_workspace and p.world_id = p_world
       and p.reservation_id is not null and s.settled_at is null
    on conflict (workspace_id,piece_request_id) do nothing;
  -- Every table that names the world, in the order its foreign keys allow.
  -- Layer 0.
  -- A label is the name or the spot a placeholder stood for in a Companion answer, and has no
  -- key to a world (0127): the labels of the answers that cite this world, and any that names
  -- one of its versions.
  delete from companion_answer_simulation_label x
   where x.workspace_id = p_workspace
     and (x.answer_id in (select c.answer_id from companion_answer_simulation_citation c
                           where c.workspace_id = p_workspace and c.world_id = p_world)
          or x.version_id in (select k.version_id from world_alternate_version k
                               where k.workspace_id = p_workspace and k.world_id = p_world));
  delete from companion_answer_simulation_citation x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from comparison_cancellation x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from comparison_run_start x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from door_answer x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_crossing_binding x
   using door_crossing c
   where x.workspace_id = p_workspace and c.workspace_id = p_workspace
     and c.society_id = x.society_id and c.crossing_id = x.crossing_id
     and c.grant_id in (select k.grant_id from door_grant k
                         where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_delivery x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_grant_revision x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_grant_revocation x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_presence x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_secret x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_visitor_gone x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from piece_look_step x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from piece_output x
   where x.workspace_id = p_workspace
     and x.piece_request_id in (select k.piece_request_id from piece_request k
                              where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from piece_settlement x
   where x.workspace_id = p_workspace
     and x.piece_request_id in (select k.piece_request_id from piece_request k
                              where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from saved_world_source_current_membership x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from saved_world_source_detach x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from signal_comparison_decision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from signal_comparison_outcome x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from signal_comparison_start x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_decision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_hour x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_outcome x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_replay x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_start x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_experiment_checkpoint x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select k.experiment_id from society_experiment_definition k
                           where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from society_experiment_outcome x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select k.experiment_id from society_experiment_definition k
                           where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from world_alternate_element_override x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_environment_instance x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_object x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_point_map_instance x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_alternate_version_edit x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_character_appearance_revision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_clock x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_clock_event x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_clock_traffic_minute x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_crossing_occupancy x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_generation_receipt x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_audit_event x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_state x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_minds_budget x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_package_export x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project_binding x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project_item_revision x
   where x.workspace_id = p_workspace
     and x.item_id in (select k.item_id from world_project_item k
                     where k.workspace_id = p_workspace and k.world_id = p_world);
  -- A source link names its own item and, where it was copied from one, that item too; either
  -- may be this world's.
  delete from world_project_item_source x
   where x.workspace_id = p_workspace
     and (x.item_id in (select k.item_id from world_project_item k
                         where k.workspace_id = p_workspace and k.world_id = p_world)
          or x.source_item_id in (select k.item_id from world_project_item k
                                   where k.workspace_id = p_workspace and k.world_id = p_world));
  delete from world_project_share x
   where x.workspace_id = p_workspace
     and x.project_id in (select k.project_id from world_project k
                        where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from world_region_style_version x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_society_model_choice x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_society_person_answer x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_audit_event x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_dependency x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_invalidation x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_placement_migration x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_state x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_audit_event x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_state x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_thing_look x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_thing_character x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_topology_source x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_decision x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_segment x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_version_baked_tile x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 1.
  delete from door_ask x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from door_crossing x
   where x.workspace_id = p_workspace
     and x.grant_id in (select k.grant_id from door_grant k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from piece_request x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from saved_world_source_attachment x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from saved_world_source_detach_operation x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from signal_comparison_run x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison_run x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_experiment_attempt x
   where x.workspace_id = p_workspace
     and x.experiment_id in (select k.experiment_id from society_experiment_definition k
                           where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from world_alternate_thing x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_preview x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_version x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project_item x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_preview x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_snapshot_element x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_preview x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_topology_region x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_decision_request x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 2.
  delete from door_grant x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from saved_world_source_attachment_operation x
   where x.workspace_id = p_workspace
     and x.entry_id in (select k.entry_id from saved_world_entry k
                      where k.workspace_id = p_workspace and k.world_id = p_world);
  delete from signal_comparison x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_comparison x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from society_experiment_definition x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_interaction_policy_proposal x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_project x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_element_identity x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_structure_snapshot_region x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_traffic_signal_choice x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 3.
  delete from saved_world_entry x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 4.
  delete from world_society x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 5.
  delete from world_alternate_version x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 6.
  delete from world_structure_snapshot x
   where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_style_version x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 7.
  delete from world_style_proposal x where x.workspace_id = p_workspace and x.world_id = p_world;
  delete from world_topology_contract x where x.workspace_id = p_workspace and x.world_id = p_world;
  -- Layer 8.
  delete from world_identity x where x.workspace_id = p_workspace and x.world_id = p_world;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 7. Row-level security, and the definers: their owner, path and grants.
-- --------------------------------------------------------------------------------------------

do $$ declare t text; begin
  foreach t in array array['world_version_tile_object', 'world_version_baked_tile'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

-- The guards fire inside record_version_baked_tile and world_erase_rows, whose search path is
-- pg_catalog first, so each names this schema in its own path (0144's way for its triggers).
do $pin$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature from pg_proc p
     where p.pronamespace = current_schema()::regnamespace
       and p.proname in ('tg_world_version_tile_object_guard',
                         'tg_world_version_baked_tile_guard',
                         'tg_version_tile_purge_on_tombstone')
  loop
    execute format('alter function %s set search_path = %I, pg_catalog, pg_temp',
                   f.signature, current_schema());
    execute format('revoke all on function %s from public', f.signature);
  end loop;
end $pin$;

do $$ begin
  execute format('alter function tg_world_erasure_takes_version_tiles() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function version_tile_purge_is_authorized(uuid,uuid,text) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function world_erase_rows(uuid, text) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function record_version_baked_tile(uuid, uuid, uuid, uuid, int, bytea, bytea, bytea,
  int, int, int, bytea, bigint, bytea, bigint, bytea, bytea, jsonb) from public;
revoke all on function tg_world_erasure_takes_version_tiles() from public;
revoke all on function version_tile_purge_is_authorized(uuid, uuid, text) from public;
revoke all on function world_erase_rows(uuid, text) from public;

-- The publish's reads and writes of the bakes and its read of the inventory; the erasures' reads
-- and deletes of the bakes and their read of the inventory. The job (its read and the columns a
-- cancel writes) and world_erasure are 0197's grants, the stage 0161's, and the queue's INSERT
-- 0172's.
grant select, insert, update, delete on world_version_baked_tile to exulanica_definer;
grant select on world_version_tile_object to exulanica_definer;
alter function record_version_baked_tile(uuid, uuid, uuid, uuid, int, bytea, bytea, bytea,
  int, int, int, bytea, bigint, bytea, bigint, bytea, bytea, jsonb) owner to exulanica_definer;
alter function tg_world_erasure_takes_version_tiles() owner to exulanica_definer;
alter function version_tile_purge_is_authorized(uuid, uuid, text) owner to exulanica_definer;
alter function world_erase_rows(uuid, text) owner to exulanica_definer;

commit;
