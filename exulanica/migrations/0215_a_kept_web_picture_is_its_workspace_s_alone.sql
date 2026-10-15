-- 0215_a_kept_web_picture_is_its_workspace_s_alone.sql
-- A picture a person picked from a picture search and kept, with where it came from.
--
-- NEVER A CAPTURE. A kept web picture is a stranger's photograph, not the person's own. Every reader
-- of `capture` treats a capture as the person's own photograph (their library, their admissions,
-- scene grouping, a world's inputs, the World Memory Package, the judge seed, and the admissions
-- that open hosted models to it), so a kept picture is held apart, the way a creature's look
-- (0172) and a workspace's style pack (0173) are: its bytes in the workspace's own `web-pictures`
-- namespace of the content store, by digest; its inventory in `web_picture_object`; its record in
-- `web_picture`. Nothing that reads captures can see one, and no hosted model ever receives one
-- (docs/reference-notes-contract.md).
--
-- WHAT IS KEPT. The kept bytes are the fetched picture decoded and written again without its
-- metadata (exulanica/references/kept_pictures.py). The record holds the digest of what was kept
-- and of what was fetched, its media type, size and pixel size, the picture's address and its
-- website, the licence where its source states one, the person's answer to whether they may use
-- it, who answered, the picture search it came from, and when. Never the source's words about it.
-- Records and inventory are appended and never changed, but for a purge's mark.
--
-- ERASURE. A person erases a kept picture with a tombstone of its own scope (`web_picture`) and,
-- in the same transaction, a row of `web_picture_erasure` naming the picture, its bytes' digest
-- and that tombstone. The row's trigger, as the definers' owner, deletes the record and enqueues
-- the bytes' purge on the tombstone, unless another kept picture of the workspace holds the same
-- bytes. A workspace's tombstone deletes every record (a definer) and enqueues every object the
-- namespace still holds. `web_picture_purge_is_authorized` holds a purge to its tombstone: a
-- workspace's, or a picture's while no kept picture names the bytes. The erasure row stays: an
-- immutable record of what was erased, naming no address and no words.
--
-- RESTORE. A restore carries the erasure rows (exulanica/deletion/withdrawals.v2.json) before it
-- replays tombstones: written again, an erasure deletes the restored record, and its tombstone,
-- replayed after it, enqueues the bytes' purge (the tombstone's trigger below).
begin;
select pg_advisory_xact_lock(119622309);
alter type tombstone_scope add value if not exists 'web_picture';

-- --------------------------------------------------------------------------------------------
-- 1. The namespace's inventory.
-- --------------------------------------------------------------------------------------------

create table web_picture_object (
  workspace_id   uuid not null,
  object_id      uuid not null default uuidv7(),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size      bigint not null check (byte_size > 0),
  recorded_at    timestamptz not null default statement_timestamp(),
  -- Set by the purger, after the bytes are gone, and only when a tombstone asked for them.
  purged_at      timestamptz,
  primary key (workspace_id, object_id)
);

-- One live record per object: bytes written again after a purge are a new record.
create unique index web_picture_object_live on web_picture_object (workspace_id, content_sha256)
  where purged_at is null;

comment on table web_picture_object is
  'Every object a workspace''s web pictures namespace holds, recorded before its bytes; never '
  'deleted, so a tombstone finds the objects of pictures erased before it. Only the purger sets '
  'purged_at.';

-- --------------------------------------------------------------------------------------------
-- 2. The record.
-- --------------------------------------------------------------------------------------------

create table web_picture (
  workspace_id   uuid not null,
  picture_id     uuid not null default uuidv7(),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  fetched_sha256 text not null check (fetched_sha256 ~ '^[0-9a-f]{64}$'),
  media_type     text not null check (media_type in ('image/jpeg', 'image/png', 'image/webp')),
  byte_size      bigint not null check (byte_size between 1 and 10485760),
  width          integer not null check (width between 1 and 16384),
  height         integer not null check (height between 1 and 16384),
  address        text not null check (
    char_length(address) between 12 and 2048 and address ~ '^https://[!-~]+$'),
  website        text not null check (website ~ '^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$'),
  licence        text check (licence is null or char_length(licence) between 1 and 200),
  answer         text not null check (
    answer in ('made_or_permitted', 'licence_allows', 'private_world_only')),
  answered_by    uuid not null,
  reference_id   uuid,
  kept_at        timestamptz not null default statement_timestamp(),
  primary key (workspace_id, picture_id),
  constraint web_picture_licence_answer check (answer <> 'licence_allows' or licence is not null)
);

comment on table web_picture is
  'A picture a person picked from a picture search and kept for their own world: where it came '
  'from, what was kept, and their answer to whether they may use it. Never a capture. Deleted only '
  'by its erasure or its workspace''s, as the definers'' owner.';

create function tg_web_picture_object_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.purged_at is not null then
      raise exception 'a web picture object arrives unpurged' using errcode = 'check_violation';
    end if;
    -- The workspace's lock, which every tombstone takes without waiting (0137).
    perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024));
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp()) then
      perform tombstone_refuse('web_picture_object');
    end if;
    new.recorded_at := statement_timestamp();
    return new;
  end if;
  if old.purged_at is not null then
    if new is distinct from old then
      raise exception 'a purged web picture object does not change again'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if (to_jsonb(new) - 'purged_at') is distinct from (to_jsonb(old) - 'purged_at')
     or new.purged_at is null then
    raise exception 'only the purger writes a web picture object, and only its purge'
      using errcode = 'check_violation';
  end if;
  if not exists (
       select 1 from purge_job pj
        where pj.workspace_id = new.workspace_id
          and pj.target_kind = 'web_picture'
          and pj.target_ref = new.content_sha256
          and web_picture_purge_is_authorized(new.workspace_id, pj.tombstone_id,
                                              new.content_sha256)) then
    raise exception 'a web picture object is marked purged only when a tombstone asked for it'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create function tg_web_picture_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024));
  if exists (select 1 from tombstone t
              where t.workspace_id = new.workspace_id
                and t.scope = 'workspace'
                and t.effective_at <= clock_timestamp()) then
    perform tombstone_refuse('web_picture');
  end if;
  if not exists (select 1 from web_picture_object o
                  where o.workspace_id = new.workspace_id
                    and o.content_sha256 = new.content_sha256
                    and o.purged_at is null) then
    raise exception 'a kept web picture names bytes its namespace holds'
      using errcode = 'foreign_key_violation';
  end if;
  new.kept_at := statement_timestamp();
  return new;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 3. The erasure.
-- --------------------------------------------------------------------------------------------

create table web_picture_erasure (
  workspace_id   uuid not null,
  erasure_id     uuid not null default uuidv7(),
  picture_id     uuid not null,
  -- The erased picture's kept bytes, which its purge names.
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  -- The web picture tombstone written beside it, which its purge job names; one each.
  tombstone_id   uuid not null,
  erased_by      uuid not null,
  erased_at      timestamptz not null default statement_timestamp(),
  primary key (workspace_id, erasure_id),
  constraint web_picture_erasure_has_its_own_tombstone unique (tombstone_id),
  constraint web_picture_erasure_once unique (workspace_id, picture_id)
);

comment on table web_picture_erasure is
  'A workspace''s erasure of a kept web picture, naming the picture, its bytes'' digest and the '
  'web picture tombstone written with it; its trigger deletes the record and enqueues the bytes'' '
  'purge on that tombstone, and a restore carries it. Appended; never updated or deleted by the '
  'runtime. Holds no address and no words.';

create trigger tg_web_picture_erasure_append_only before update or delete on web_picture_erasure
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on web_picture_erasure
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();

-- Whether a tombstone may destroy these bytes from its workspace's web pictures namespace. A
-- workspace tombstone may destroy anything in it, whether or not a row still names it: the
-- namespace is the workspace's alone, and all of it goes (0126's rule). A web picture tombstone
-- may destroy bytes no picture the workspace still keeps names. No other scope reaches it.
create function web_picture_purge_is_authorized(
  p_workspace uuid, p_tombstone uuid, p_content text
) returns boolean
language sql volatile security definer as $fn$
  select p_workspace = current_workspace() and p_content ~ '^[0-9a-f]{64}$' and exists (
    select 1 from tombstone t
     where t.workspace_id = p_workspace
       and t.tombstone_id = p_tombstone
       and t.effective_at <= now()
       and (t.scope::text = 'workspace'
            or (t.scope::text = 'web_picture'
                and not exists (select 1 from web_picture p
                                 where p.workspace_id = p_workspace
                                   and p.content_sha256 = p_content))));
$fn$;

comment on function web_picture_purge_is_authorized(uuid, uuid, text) is
  'May this tombstone destroy these bytes from its workspace''s web pictures namespace: it is '
  'effective and in this session''s workspace, and it is the workspace''s tombstone, or a web '
  'picture''s while no kept picture names the bytes. For the purge role.';

create trigger tg_web_picture_object_guard before insert or update on web_picture_object
  for each row execute function tg_web_picture_object_guard();
create trigger tg_web_picture_object_no_delete before delete on web_picture_object
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_web_picture_guard before insert on web_picture
  for each row execute function tg_web_picture_guard();
-- Never changed; deleted only as the definers' owner (0172's rule for the thing store).
create trigger tg_web_picture_append_only before update or delete on web_picture
  for each row execute function tg_thing_store_append_only();

create function tg_web_picture_erasure_erases() returns trigger
language plpgsql security definer as $fn$
declare
  v_anchor text;
  v_content text;
begin
  perform assert_workspace_context(new.workspace_id);
  -- The product writes the tombstone first, in this transaction. A restore carries the erasure
  -- before it replays tombstones, so there it is not yet held, and the tombstone, replayed after
  -- it, enqueues the purge instead (tg_web_picture_purge_on_tombstone).
  select case when t.workspace_id = new.workspace_id and t.scope::text = 'web_picture'
                   and t.requested_by = new.erased_by
              then 'held' else 'another' end
    into v_anchor
    from tombstone t
   where t.tombstone_id = new.tombstone_id;
  if v_anchor = 'another' then
    raise exception 'an erasure is written beside a web picture tombstone of its own workspace'
      using errcode = 'check_violation';
  end if;
  if v_anchor is null
     and not exists (select 1 from restore_control r where r.state = 'replaying') then
    raise exception 'an erasure names a tombstone it holds, unless a restore''s replay carries it'
      using errcode = 'check_violation';
  end if;
  delete from web_picture p
   where p.workspace_id = new.workspace_id and p.picture_id = new.picture_id
  returning p.content_sha256 into v_content;
  if v_content is null and v_anchor = 'held' then
    raise exception 'an erasure names a picture its workspace keeps' using errcode = 'check_violation';
  end if;
  if v_content is not null and v_content <> new.content_sha256 then
    raise exception 'an erasure names the bytes its picture kept' using errcode = 'check_violation';
  end if;
  if v_anchor = 'held' and not exists (
       select 1 from web_picture p
        where p.workspace_id = new.workspace_id and p.content_sha256 = new.content_sha256) then
    -- No conflict target: naming one needs SELECT on the queue, which this owner does not hold.
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    values (new.tombstone_id, new.workspace_id, 'web_picture', new.content_sha256)
    on conflict do nothing;
  end if;
  return null;
end $fn$;

comment on function tg_web_picture_erasure_erases() is
  'An erasure''s deletes: the kept picture''s record, and its bytes enqueued on its web picture '
  'tombstone unless another kept picture names them. Runs as exulanica_definer, in the erasure''s '
  'own workspace.';

create trigger tg_web_picture_erasure_erases after insert on web_picture_erasure
  for each row execute function tg_web_picture_erasure_erases();

-- A workspace tombstone erases every picture the workspace keeps, in its own workspace.
create function tg_web_picture_erases_on_tombstone() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope::text <> 'workspace' then
    return new;
  end if;
  -- Row-level security binds this owner, so the tombstone's workspace must be the session's.
  perform assert_workspace_context(new.workspace_id);
  delete from web_picture p where p.workspace_id = new.workspace_id;
  return new;
end $fn$;

comment on function tg_web_picture_erases_on_tombstone() is
  'A workspace tombstone''s erasure of every web picture the workspace keeps, at once. Runs as '
  'exulanica_definer, in the tombstone''s own workspace.';

create trigger tg_web_picture_erases_on_tombstone
  after insert on tombstone
  for each row execute function tg_web_picture_erases_on_tombstone();

-- A workspace tombstone enqueues every object the namespace still holds; a web picture tombstone,
-- replayed by a restore after the erasure it names, enqueues that erasure's bytes unless a kept
-- picture names them. Its order among the tombstone's AFTER triggers does not matter: it reads the
-- inventory and the erasures, which no other trigger deletes.
create function tg_web_picture_purge_on_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope::text = 'workspace' then
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    select new.tombstone_id, new.workspace_id, 'web_picture', o.content_sha256
      from web_picture_object o
     where o.workspace_id = new.workspace_id
       and o.purged_at is null
    on conflict (tombstone_id, target_kind, target_ref) do nothing;
  elsif new.scope::text = 'web_picture' then
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    select new.tombstone_id, e.workspace_id, 'web_picture', e.content_sha256
      from web_picture_erasure e
     where e.workspace_id = new.workspace_id
       and e.tombstone_id = new.tombstone_id
       and not exists (select 1 from web_picture p
                        where p.workspace_id = e.workspace_id
                          and p.content_sha256 = e.content_sha256)
    on conflict (tombstone_id, target_kind, target_ref) do nothing;
  end if;
  return new;
end $fn$;

create trigger tg_web_picture_purge_on_tombstone
  after insert on tombstone
  for each row execute function tg_web_picture_purge_on_tombstone();

-- --------------------------------------------------------------------------------------------
-- 4. The purge: its target kind, and when a tombstone's purge is complete.
-- --------------------------------------------------------------------------------------------

alter table purge_job drop constraint purge_job_target_kind_check;
alter table purge_job add constraint purge_job_target_kind_check
  check (target_kind in ('blob', 'artifact', 'embedding', 'text_chunk', 'material_bake',
                         'workspace_asset', 'look', 'workspace_style_pack', 'web_picture'));

-- Re-stated from the style pack migration (0173) with two clauses added: a web picture job whose
-- object is not yet marked purged, and, for a workspace tombstone, any web picture object still
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
             and w.purged_at is null)))) then
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
                        and w.purged_at is null);
  end if;
  return true;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 5. Row-level security, and the definers: their owner, path and grants.
-- --------------------------------------------------------------------------------------------

do $$ declare t text; begin
  foreach t in array array['web_picture_object', 'web_picture', 'web_picture_erasure'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

do $$ begin
  execute format('alter function tg_web_picture_erasure_erases() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_web_picture_erases_on_tombstone() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function web_picture_purge_is_authorized(uuid,uuid,text) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function tg_web_picture_erasure_erases() from public;
revoke all on function tg_web_picture_erases_on_tombstone() from public;
revoke all on function web_picture_purge_is_authorized(uuid, uuid, text) from public;

-- The erasures' reads and deletes of the records; an erasure's job on its tombstone is 0172's
-- INSERT on the queue. The tombstone and the restore control they read are 0161's grants.
grant select, delete on web_picture to exulanica_definer;
alter function tg_web_picture_erasure_erases() owner to exulanica_definer;
alter function tg_web_picture_erases_on_tombstone() owner to exulanica_definer;
alter function web_picture_purge_is_authorized(uuid, uuid, text) owner to exulanica_definer;

commit;
