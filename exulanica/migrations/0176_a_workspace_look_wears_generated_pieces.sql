-- 0176_a_workspace_look_wears_generated_pieces.sql
-- A workspace's own look may be made of generated pieces: a style pack version whose files are
-- pieces the generation worker made at a person's request, held by digest in the one shared
-- generated-pieces store rather than in the workspace's own namespace.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- The generated pieces contract's derived look is a style pack version drawn on a library pack,
-- with generated pieces in place of some of its own (exulanica/generation/looks.py builds its
-- manifest). docs/style-pack-contract.md section 11.2 is the contract; what follows records the
-- shape.
--
--   workspace_style_pack_file.source    'workspace' (the default, every row before this one: the
--                                       workspace's namespace and its inventory) or
--                                       'generated_piece' (the shared store; no inventory record, so
--                                       a workspace's tombstone enqueues nothing for it, its
--                                       completion never waits on it, and only the shared bytes
--                                       survive the erasure)
--   workspace_style_pack_version.origin 'uploaded' (the default, every row before this one) or
--                                       'generated'; a 'generated.' pack id is a generated
--                                       version's alone, and a generated version is drawn on a
--                                       library pack
--   tg_workspace_style_pack_version_guard  a person's bounds (16 live versions, 256 MiB) count
--                                       uploaded versions only; generated versions are bounded on
--                                       their own (workspace_style_pack_generated_limit, 64 live)
--   tg_workspace_style_pack_preparation_guard and workspace_style_pack_wearable
--                                       a generated piece is held while a piece_output of the
--                                       workspace names it and passed its checks (within): a
--                                       version becomes ready, and is worn, only while each file
--                                       is held
--
-- A workspace tombstone erases a generated version as it erases any other (the tombstone trigger
-- of the migration of a workspace's own style packs: documents, pack ids, file paths and receipt),
-- and the piece batch migration's trigger deletes the workspace's outputs, so the version is never
-- wearable again. The shared bytes stay, as the generated pieces contract says.

begin;

-- --------------------------------------------------------------------------------------------
-- 1. Where a file's bytes are, and who made a version.
-- --------------------------------------------------------------------------------------------

alter table workspace_style_pack_file
  add column source text not null default 'workspace'
    check (source in ('workspace', 'generated_piece'));
comment on column workspace_style_pack_file.source is
  'Where the file''s bytes are: ''workspace'', the workspace''s own namespace, named by its '
  'inventory; ''generated_piece'', the shared generated-pieces store, held while a piece_output '
  'of the workspace names the digest.';

alter table workspace_style_pack_version
  add column origin text not null default 'uploaded'
    check (origin in ('uploaded', 'generated'));
comment on column workspace_style_pack_version.origin is
  '''uploaded'', a person''s own pack; ''generated'', a look the generation worker made of pieces '
  'at a person''s request, drawn on a library pack.';
-- The "generated." ids are generated versions': a live upload never holds one, a live generated
-- version always does, and a generated version is drawn on a library pack.
alter table workspace_style_pack_version
  add constraint generated_ids_are_generated_versions
    check ((erased_at is not null or (pack_id ~ '^generated\.') = (origin = 'generated'))
           and (origin <> 'generated' or base_source = 'library'));

-- --------------------------------------------------------------------------------------------
-- 2. Bounds: a person's count their uploads; generated versions have their own.
-- --------------------------------------------------------------------------------------------

-- How many live generated versions a workspace holds at most: every distinct set of pieces a world
-- wears is one version, and taking a piece back reuses an earlier one. A declared bound.
create function workspace_style_pack_generated_limit() returns integer
language sql immutable as $fn$
  select 64;
$fn$;

create or replace function tg_workspace_style_pack_version_guard() returns trigger
language plpgsql as $fn$
declare
  live integer;
  live_bytes bigint;
  bound record;
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' then
    -- The one update a version receives: its workspace's erasure clearing everything the creator
    -- chose or wrote (both documents, the attribution, the pack ids) and the receipt.
    if (to_jsonb(new) - 'manifest_canonical' - 'declaration_canonical' - 'erased_at'
          - 'pack_id' - 'base_pack_id' - 'receipt_document' - 'licence_attribution')
         is distinct from
       (to_jsonb(old) - 'manifest_canonical' - 'declaration_canonical' - 'erased_at'
          - 'pack_id' - 'base_pack_id' - 'receipt_document' - 'licence_attribution')
       or old.erased_at is not null or new.erased_at is null
       or not workspace_style_pack_workspace_erased(new.workspace_id) then
      raise exception 'a style pack version is never rewritten; it is erased with its workspace'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  perform workspace_asset_lifecycle_lock(new.workspace_id);
  if workspace_style_pack_workspace_erased(new.workspace_id) then
    perform tombstone_refuse('workspace_style_pack_version');
  end if;
  if new.erased_at is not null then
    raise exception 'a style pack version arrives with its documents'
      using errcode = 'check_violation';
  end if;
  new.documents_byte_size := new.manifest_byte_size + octet_length(new.declaration_canonical)
                             + octet_length(new.receipt_document::text);
  select * into bound from workspace_style_pack_limits();
  select count(*), coalesce(sum(v.file_byte_size + v.documents_byte_size), 0)
    into live, live_bytes
    from workspace_style_pack_version v
   where v.workspace_id = new.workspace_id
     and v.origin = new.origin
     and not exists (select 1 from workspace_style_pack_withdrawal w
                      where w.workspace_id = v.workspace_id
                        and w.manifest_sha256 = v.manifest_sha256)
     and not exists (select 1 from workspace_style_pack_preparation p
                      where p.workspace_id = v.workspace_id
                        and p.manifest_sha256 = v.manifest_sha256
                        and p.state in ('failed', 'cancelled')
                        and p.failure_class is distinct from 'interrupted');
  -- A person's bounds count their uploads; generated versions are bounded on their own, and their
  -- pieces are bytes of the shared store, so they count toward no byte bound here.
  if new.origin = 'generated' then
    if live >= workspace_style_pack_generated_limit() then
      raise exception 'this workspace holds % generated style pack versions, its limit', live
        using errcode = 'program_limit_exceeded';
    end if;
  else
    if live >= bound.live_versions then
      raise exception 'this workspace holds % style pack versions, its limit', live
        using errcode = 'program_limit_exceeded';
    end if;
    if live_bytes + new.file_byte_size + new.documents_byte_size > bound.pack_bytes then
      raise exception 'this workspace''s style packs would exceed % bytes', bound.pack_bytes
        using errcode = 'program_limit_exceeded';
    end if;
  end if;
  if new.base_source = 'workspace' and workspace_style_pack_wearable(
       new.workspace_id, new.base_manifest_sha256) is not true then
    raise exception 'a style pack is drawn only on a workspace pack that may be worn now'
      using errcode = 'check_violation';
  end if;
  if new.base_source = 'workspace' and not exists (
       select 1 from workspace_style_pack_version b
        where b.workspace_id = new.workspace_id
          and b.manifest_sha256 = new.base_manifest_sha256
          and b.pack_id = new.base_pack_id
          and b.version = new.base_version) then
    raise exception 'a workspace base is named by its own pack id, version and digest'
      using errcode = 'check_violation';
  end if;
  -- A chain is at most eight versions deep, this one included.
  if new.base_source = 'workspace' and exists (
       select 1 from workspace_style_pack_chain(new.workspace_id, new.base_manifest_sha256) c
        where c.depth >= 7) then
    raise exception 'a style pack is drawn on a chain at most eight versions deep'
      using errcode = 'check_violation';
  end if;
  new.created_at := statement_timestamp();
  return new;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 3. A generated piece is held while a passed output of the workspace names it: a version becomes
--    ready, and is worn and served, only while each of its files is held.
-- --------------------------------------------------------------------------------------------

create or replace function tg_workspace_style_pack_preparation_guard() returns trigger
language plpgsql as $fn$
declare
  waiting integer;
  bound record;
  base text;
begin
  perform assert_workspace_context(new.workspace_id);

  if tg_op = 'INSERT' then
    if new.state <> 'requested' or new.attempts <> 0 or new.report_document is not null then
      raise exception 'a style pack preparation arrives requested, unattempted and empty'
        using errcode = 'check_violation';
    end if;
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_workspace_style_pack(new.workspace_id, new.manifest_sha256) then
      perform tombstone_refuse('workspace_style_pack_preparation');
    end if;
    select * into bound from workspace_style_pack_limits();
    select count(*) into waiting from workspace_style_pack_preparation p
     where p.workspace_id = new.workspace_id and p.state in ('requested', 'running');
    if waiting >= bound.pending_at_once then
      raise exception 'this workspace already has % style pack checks waiting, its limit', waiting
        using errcode = 'program_limit_exceeded';
    end if;
    new.requested_at := statement_timestamp();
    return new;
  end if;

  if (new.workspace_id, new.manifest_sha256) is distinct from (old.workspace_id, old.manifest_sha256)
  then
    raise exception 'a style pack preparation''s version is fixed'
      using errcode = 'check_violation';
  end if;
  -- An erasure clears what the check said and found, and changes nothing else.
  if (old.failure_message is not null or old.report_document is not null)
     and new.failure_message is null and new.report_document is null
     and (to_jsonb(new) - 'failure_message' - 'report_document')
         = (to_jsonb(old) - 'failure_message' - 'report_document') then
    if not workspace_style_pack_workspace_erased(new.workspace_id) then
      raise exception 'a check''s message is erased only with its workspace'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if old.state = 'ready' then
    raise exception 'a ready style pack stays ready; withdrawing it is a withdrawal'
      using errcode = 'check_violation';
  end if;
  if new.state is distinct from old.state then
    if not (
         (old.state = 'requested' and new.state in ('running', 'cancelled'))
      or (old.state = 'running' and new.state in ('running', 'ready', 'failed', 'cancelled'))
      or (old.state = 'failed' and old.failure_class = 'interrupted'
          and new.state in ('requested', 'cancelled'))) then
      raise exception 'a style pack preparation does not move from % to %', old.state, new.state
        using errcode = 'check_violation';
    end if;
  end if;
  -- A finished check's ending is what it found: no write turns a refusal into an interruption.
  if new.state = old.state and old.state in ('failed', 'cancelled')
     and (new.failure_class, new.failure_message, new.report_document, new.finished_at)
         is distinct from
         (old.failure_class, old.failure_message, old.report_document, old.finished_at) then
    raise exception 'a finished style pack check keeps how it ended'
      using errcode = 'check_violation';
  end if;
  -- A check asked again waits within the same bound as a new one.
  if new.state = 'requested' and old.state <> 'requested' then
    select * into bound from workspace_style_pack_limits();
    select count(*) into waiting from workspace_style_pack_preparation p
     where p.workspace_id = new.workspace_id and p.state in ('requested', 'running')
       and p.manifest_sha256 <> new.manifest_sha256;
    if waiting >= bound.pending_at_once then
      raise exception 'this workspace already has % style pack checks waiting, its limit', waiting
        using errcode = 'program_limit_exceeded';
    end if;
  end if;
  if new.state in ('requested', 'running', 'ready')
     and (new.state is distinct from old.state or new.claim_token is distinct from old.claim_token)
  then
    perform workspace_asset_lifecycle_lock(new.workspace_id);
    if tombstone_blocks_workspace_style_pack(new.workspace_id, new.manifest_sha256) then
      perform tombstone_refuse('workspace_style_pack_preparation');
    end if;
  end if;
  if new.state = 'ready' and old.state <> 'ready' then
    select v.base_manifest_sha256 into base from workspace_style_pack_version v
     where v.workspace_id = new.workspace_id and v.manifest_sha256 = new.manifest_sha256
       and v.base_source = 'workspace';
    if base is not null and workspace_style_pack_wearable(new.workspace_id, base) is not true then
      raise exception 'a style pack becomes ready only while its base may be worn'
        using errcode = 'check_violation';
    end if;
    if exists (select 1 from workspace_style_pack_file f
                where f.workspace_id = new.workspace_id
                  and f.manifest_sha256 = new.manifest_sha256
                  and not (
                    (f.source = 'workspace'
                     and exists (select 1 from workspace_style_pack_blob b
                                  where b.workspace_id = f.workspace_id
                                    and b.content_sha256 = f.content_sha256
                                    and b.purged_at is null))
                    or (f.source = 'generated_piece'
                        and exists (select 1 from piece_output o
                                     where o.workspace_id = f.workspace_id
                                       and o.piece_sha256 = f.content_sha256
                                       and o.within)))) then
      -- Held: recorded in the inventory, or a generated piece a passed output of the workspace names.
      raise exception 'a style pack becomes ready only with every file held'
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $fn$;


create or replace function workspace_style_pack_wearable(p_workspace uuid, p_manifest text)
returns boolean
language sql volatile as $fn$
  select p_workspace = current_workspace()
    and not exists (
      select 1 from workspace_style_pack_chain(p_workspace, p_manifest) c
       where c.depth = 8
          or tombstone_blocks_workspace_style_pack(p_workspace, c.manifest_sha256)
          or not exists (select 1 from workspace_style_pack_preparation p
                          where p.workspace_id = p_workspace
                            and p.manifest_sha256 = c.manifest_sha256
                            and p.state = 'ready')
          or exists (select 1 from workspace_style_pack_file f
                      where f.workspace_id = p_workspace
                        and f.manifest_sha256 = c.manifest_sha256
                        and not (
                          (f.source = 'workspace'
                           and exists (select 1 from workspace_style_pack_blob b
                                        where b.workspace_id = f.workspace_id
                                          and b.content_sha256 = f.content_sha256
                                          and b.purged_at is null))
                          or (f.source = 'generated_piece'
                              and exists (select 1 from piece_output o
                                           where o.workspace_id = f.workspace_id
                                             and o.piece_sha256 = f.content_sha256
                                             and o.within)))));
$fn$;

commit;
