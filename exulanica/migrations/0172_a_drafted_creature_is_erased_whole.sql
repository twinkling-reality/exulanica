-- 0172_a_drafted_creature_is_erased_whole.sql
-- A workspace erases a creature drafted from a person's words, whole, and the workspace's own
-- erasure reaches every container its looks namespace records.
--
-- WHAT A PERSON'S WORDS REACH. A creature drafted from words is kept
-- (exulanica/world/thing_store.py) as four documents, each appended once and bound by its digest:
-- the body recipe; the body plan built from it; the sketch drawn on that plan; and the thing kind,
-- whose label and summary are drafted from the words. Every key is made from the label. None can be
-- blanked in place, so erasure removes the rows. The recipe row's words digest column (0159) is
-- emptied and held empty by a check (a migration only adds, so the column stays): nothing reads it,
-- the digest sits in the plan's and the kind's origin, which an erasure deletes, and a recipe two
-- creatures share would otherwise keep the first one's digest after it is erased. A recipe holds
-- figures, colours and the appearance drafted with it; one another plan still names stays.
--
-- AN ERASURE WRITES A TOMBSTONE, for 0082's and 0104's reasons: every destroyed byte traces to a
-- tombstone, the purge reads its actor and reason there, and its completion is recorded on it. The
-- new scope is `creature`, and the sentence it makes true is:
--
--   A CREATURE TOMBSTONE ERASES ONE CREATURE DRAFTED FROM A PERSON'S WORDS: ITS KIND AND, WITH
--   ITS DRAFTED PLAN, THE LOOKS DRAWN ON IT AND THEIR CONTAINERS, THE PLAN AND ITS RECIPE, AND
--   NOTHING ANOTHER CREATURE STILL HOLDS OR ANOTHER SCOPE'S SUBJECT IS.
--
-- Its subject is not a tombstone column. thing_erasure names the kind by its document's digest
-- (sha256) and the tombstone written beside it (tombstone_id), and nothing a person wrote. A
-- column on tombstone would be the first since 0001, and a restore compares each restored
-- tombstone with its checkpoint's record of it whole. Every scope test in this schema is an
-- inclusion test on a named value (0082 measured six and read the rest, 0104 read them again, and
-- every test since names its scopes), so the new value reaches nothing else. NOTHING IN THIS FILE
-- USES IT AS AN ENUM, for 0082's measured reason: every reference is inside a plpgsql body or
-- compares `scope::text`.
--
-- The erasure's after-insert trigger, tg_thing_erasure_erases, a SECURITY DEFINER owned by
-- exulanica_definer, works in the row's own workspace, which it asserts first. It deletes the kind
-- version at that digest and, when no other kind names the drafted plan it was built on, every
-- look drawn on that plan with its withdrawals, the plan, and the recipe when no other plan names
-- it; and it enqueues the container of every look it deleted, unless a look still held names the
-- same bytes, as a 'look' purge job of its tombstone, so a sculpted or imported look's file goes
-- as the sketch's does. A workspace tombstone erases every creature the workspace holds:
-- tg_thing_store_erases_on_tombstone, a definer with the same owner, deletes all five tables' rows
-- of the workspace. Each deletes what exists and nothing else. The five store tables refuse every
-- update and every delete except a delete made as exulanica_definer, which holds DELETE on them
-- for these two bodies alone.
--
-- A RESTORE carries the erasure (exulanica/deletion/withdrawals.v2.json) before it replays any
-- tombstone, so the carried row deletes the creature's rows from an older backup while its
-- tombstone is not yet held there; it enqueues nothing then, and the replayed tombstone's copy
-- enqueues the checkpoint's own record of the containers, as every scope's does. That order is why
-- thing_erasure.tombstone_id names its tombstone without a foreign key. Where the tombstone is
-- held, it must be this workspace's and a creature's; where it is not, a restore's replay must be
-- under way (restore_control replaying), so no other writer erases without a tombstone.
--
-- WORKSPACES ERASED BEFORE THIS MIGRATION. A workspace tombstone written before it erased none of
-- the store's rows, since no trigger did then. Here every workspace with an effective workspace
-- tombstone loses them, as that tombstone's trigger below now takes them; the containers its looks
-- named, which the backfill records, are enqueued as look jobs of each such tombstone, and its
-- purge completion is cleared (0044 reopened false completion markers this way), so it completes
-- again only once they are destroyed. Bytes that a keep wrote before this migration and that no
-- look row names were never recorded, and no tombstone reaches them: a known limit.
--
-- THE CONTAINERS. look_object records each object the store writes in a workspace's looks
-- namespace: one live record per container, recorded and committed before its bytes are written,
-- under a session lock on the object that the purger also takes, and never deleted. A workspace
-- tombstone enqueues every live record (0126's rule: the namespace is the workspace's alone).
-- look_purge_is_authorized answers a workspace tombstone for any of them and a creature tombstone
-- for bytes no held look names, so a creature kept again with the same file keeps it, and its job
-- waits unclaimed until that creature or the workspace is erased. tombstone_purge_is_complete
-- counts a live record as work left, as 0126 does for a workspace's own assets. The record's guard
-- takes the workspace's lock, which a tombstone takes without waiting (0137), so a record is made
-- before a workspace tombstone's jobs are enqueued, or refused once the tombstone is effective.
-- Containers kept before this migration are recorded here from their look rows.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true.

begin;

select pg_advisory_xact_lock(119622309);

alter type tombstone_scope add value if not exists 'creature';

-- --------------------------------------------------------------------------------------------
-- 1. The erasure.
-- --------------------------------------------------------------------------------------------

create table thing_erasure (
  workspace_id  uuid not null,
  erasure_id    uuid not null default uuidv7(),
  -- The erased kind's document digest: the name its restore matches the kind by.
  sha256        text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  -- The creature tombstone written beside it, which its purge jobs name; one each.
  tombstone_id  uuid not null,
  erased_by     uuid not null,
  erased_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, erasure_id),
  constraint thing_erasure_has_its_own_tombstone unique (tombstone_id)
);

comment on table thing_erasure is
  'A workspace''s erasure of a creature drafted from a person''s words, naming its kind by digest '
  'and the creature tombstone written with it; its trigger deletes the creature''s rows and '
  'enqueues their containers'' purge on that tombstone, and a restore carries it. Appended; never '
  'updated or deleted by the runtime.';

create trigger tg_thing_erasure_append_only before update or delete on thing_erasure
  for each row execute function tg_reconstruction_privacy_append_only();
create trigger tg_thing_erasure_binding before insert on thing_erasure
  for each row execute function tg_thing_store_binding();
create trigger tg_sealed_checkpoint_refuses_withdrawals before insert on thing_erasure
  for each row execute function tg_sealed_checkpoint_refuses_withdrawals();
alter table thing_erasure enable row level security;
alter table thing_erasure force row level security;
create policy ws_isolation on thing_erasure
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

-- The store's tables refuse every update and delete, but a delete made as the definers' owner.
-- Every SECURITY DEFINER body runs as that owner, and only the two below delete these tables; the
-- owner's DELETE on them is this migration's grant (0161's rule for every definer).
create function tg_thing_store_append_only() returns trigger
language plpgsql as $fn$
begin
  if tg_op = 'DELETE' and current_user = 'exulanica_definer' then
    return old;
  end if;
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

-- Each table's earlier append-only trigger goes first, so the recipe rows lose their words digest
-- below before the new trigger, which refuses every update, takes its place.
do $$ declare t text; begin
  foreach t in array array[
    'body_recipe_version', 'body_plan_version', 'thing_kind_version', 'look_version',
    'look_withdrawal'
  ] loop
    execute format('drop trigger tg_%s_append_only on %I', t, t);
  end loop;
end $$;

-- The recipe row keeps no digest of the words (above). The column stays, emptied here and held
-- empty by a check. The update reads every workspace's rows: a migration role subject to row-level
-- security would update nothing under FORCE with no workspace set, so FORCE is lifted for it, and
-- row_security=off turns any remaining filtering into an error instead (0090's and 0099's way, as
-- the inventory's backfill below).
set local row_security = off;
alter table body_recipe_version no force row level security;
update body_recipe_version set words_sha256 = null where words_sha256 is not null;
alter table body_recipe_version force row level security;
set local row_security = on;
alter table body_recipe_version add constraint body_recipe_version_holds_no_words
  check (words_sha256 is null);
comment on column body_recipe_version.words_sha256 is
  'Empty: the digest of the words a creature was drafted from is held only in its plan''s and its '
  'kind''s origin, which an erasure deletes, never in a recipe two creatures may share.';

do $$ declare t text; begin
  foreach t in array array[
    'body_recipe_version', 'body_plan_version', 'thing_kind_version', 'look_version',
    'look_withdrawal'
  ] loop
    execute format('create trigger tg_%s_append_only before update or delete on %I '
      'for each row execute function tg_thing_store_append_only()', t, t);
  end loop;
end $$;

-- --------------------------------------------------------------------------------------------
-- 2. The looks namespace's inventory.
-- --------------------------------------------------------------------------------------------

create table look_object (
  workspace_id   uuid not null,
  object_id      uuid not null default uuidv7(),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size      bigint not null check (byte_size > 0),
  recorded_at    timestamptz not null default statement_timestamp(),
  -- Set by the purger, after the bytes are gone, and only when a tombstone asked for them.
  purged_at      timestamptz,
  primary key (workspace_id, object_id)
);

-- One live record per container: bytes written again after a purge are a new record.
create unique index look_object_live on look_object (workspace_id, content_sha256)
  where purged_at is null;

comment on table look_object is
  'Every object a workspace''s looks namespace holds, recorded before its bytes; never deleted, so '
  'a tombstone finds the containers of looks erased before it. Only the purger sets purged_at.';

-- Containers kept before this migration, recorded from their looks before the guard exists. The
-- backfill reads every workspace: a migration role subject to row-level security would read
-- nothing under FORCE with no workspace set, so FORCE is lifted on look_version for this statement,
-- which exempts its owner, and row_security=off turns any remaining filtering into an error
-- instead of an empty result (0090's and 0099's way).
set local row_security = off;
alter table look_version no force row level security;
insert into look_object (workspace_id, content_sha256, byte_size, recorded_at)
select distinct on (l.workspace_id, l.container_sha256)
       l.workspace_id, l.container_sha256, l.container_bytes, l.created_at
  from look_version l
 where l.container_sha256 is not null
 order by l.workspace_id, l.container_sha256, l.created_at;
alter table look_version force row level security;
set local row_security = on;

alter table purge_job drop constraint purge_job_target_kind_check;
alter table purge_job add constraint purge_job_target_kind_check
  check (target_kind in ('blob', 'artifact', 'embedding', 'text_chunk', 'material_bake',
                         'workspace_asset', 'look'));

-- Whether a tombstone may destroy these bytes from its workspace's looks namespace. A workspace
-- tombstone may destroy anything in it, whether or not a row still names it: the namespace is the
-- workspace's alone, and all of it goes (0126's rule). A creature tombstone may destroy bytes no
-- look the workspace still holds names. No other scope reaches it.
create function look_purge_is_authorized(
  p_workspace uuid, p_tombstone uuid, p_content text
) returns boolean
language sql volatile security definer as $fn$
  select p_workspace = current_workspace() and p_content ~ '^[0-9a-f]{64}$' and exists (
    select 1 from tombstone t
     where t.workspace_id = p_workspace
       and t.tombstone_id = p_tombstone
       and t.effective_at <= now()
       and (t.scope = 'workspace'
            or (t.scope::text = 'creature'
                and not exists (select 1 from look_version l
                                 where l.workspace_id = p_workspace
                                   and l.container_sha256 = p_content))));
$fn$;

comment on function look_purge_is_authorized(uuid, uuid, text) is
  'May this tombstone destroy these bytes from its workspace''s looks namespace: it is effective '
  'and in this session''s workspace, and it is the workspace''s tombstone, or a creature''s while '
  'no held look names the bytes. For the purge role.';

create function tg_look_object_guard() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'INSERT' then
    if new.purged_at is not null then
      raise exception 'a looks object arrives unpurged' using errcode = 'check_violation';
    end if;
    -- The workspace's lock, which every tombstone takes without waiting (0137).
    perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text, 880024));
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id
                  and t.scope = 'workspace'
                  and t.effective_at <= clock_timestamp()) then
      perform tombstone_refuse('look_object');
    end if;
    new.recorded_at := statement_timestamp();
    return new;
  end if;
  if old.purged_at is not null then
    if new is distinct from old then
      raise exception 'a purged looks object does not change again'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  if (to_jsonb(new) - 'purged_at') is distinct from (to_jsonb(old) - 'purged_at')
     or new.purged_at is null then
    raise exception 'only the purger writes a looks object, and only its purge'
      using errcode = 'check_violation';
  end if;
  if not exists (
       select 1 from purge_job pj
        where pj.workspace_id = new.workspace_id
          and pj.target_kind = 'look'
          and pj.target_ref = new.content_sha256
          and look_purge_is_authorized(new.workspace_id, pj.tombstone_id, new.content_sha256)) then
    raise exception 'a looks object is marked purged only when a tombstone asked for it'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create trigger tg_look_object_guard before insert or update on look_object
  for each row execute function tg_look_object_guard();
create trigger tg_look_object_no_delete before delete on look_object
  for each row execute function tg_reconstruction_privacy_append_only();
alter table look_object enable row level security;
alter table look_object force row level security;
create policy ws_isolation on look_object
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

-- --------------------------------------------------------------------------------------------
-- 2a. Workspaces erased before this migration (above).
-- --------------------------------------------------------------------------------------------

-- These statements read every workspace: FORCE is lifted on each table they touch and
-- row_security is off, so filtering would raise rather than skip a row, and the store's
-- append-only triggers are disabled for the deletes alone.
set local row_security = off;
alter table tombstone no force row level security;
do $$ declare t text; begin
  foreach t in array array[
    'look_withdrawal', 'look_version', 'thing_kind_version', 'body_plan_version',
    'body_recipe_version'
  ] loop
    execute format('alter table %I no force row level security', t);
    execute format('alter table %I disable trigger tg_%s_append_only', t, t);
    execute format(
      'delete from %I x where exists (select 1 from tombstone tb '
      'where tb.workspace_id = x.workspace_id and tb.scope = ''workspace'' '
      'and tb.effective_at <= now())', t);
    execute format('alter table %I enable trigger tg_%s_append_only', t, t);
    execute format('alter table %I force row level security', t);
  end loop;
end $$;
alter table look_object no force row level security;
alter table purge_job no force row level security;
insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
select tb.tombstone_id, o.workspace_id, 'look', o.content_sha256
  from look_object o
  join tombstone tb
    on tb.workspace_id = o.workspace_id and tb.scope = 'workspace' and tb.effective_at <= now()
 where o.purged_at is null
on conflict (tombstone_id, target_kind, target_ref) do nothing;
update tombstone tb set purge_completed_at = null
 where tb.scope = 'workspace' and tb.purge_completed_at is not null
   and exists (select 1 from look_object o
                where o.workspace_id = tb.workspace_id and o.purged_at is null);
alter table purge_job force row level security;
alter table look_object force row level security;
alter table tombstone force row level security;
set local row_security = on;

-- --------------------------------------------------------------------------------------------
-- 3. The erasure's deletes, and a workspace tombstone's.
-- --------------------------------------------------------------------------------------------

create function tg_thing_erasure_erases() returns trigger
language plpgsql security definer as $fn$
declare
  v_anchor text;
  v_plan text;
  v_recipe text;
  v_containers text[];
begin
  perform assert_workspace_context(new.workspace_id);
  -- The product writes the tombstone first, in this transaction. A restore carries the erasure
  -- before it replays tombstones, so there it is not yet held, and the replay enqueues instead.
  select case when t.workspace_id = new.workspace_id and t.scope::text = 'creature'
              then 'held' else 'another' end
    into v_anchor
    from tombstone t
   where t.tombstone_id = new.tombstone_id;
  if v_anchor = 'another' then
    raise exception 'an erasure is written beside a creature tombstone of its own workspace'
      using errcode = 'check_violation';
  end if;
  if v_anchor is null
     and not exists (select 1 from restore_control r where r.state = 'replaying') then
    raise exception 'an erasure names a tombstone it holds, unless a restore''s replay carries it'
      using errcode = 'check_violation';
  end if;
  delete from thing_kind_version k
   where k.workspace_id = new.workspace_id and k.sha256 = new.sha256
  returning k.plan_sha256 into v_plan;
  if v_plan is null or exists (
       select 1 from thing_kind_version k
        where k.workspace_id = new.workspace_id and k.plan_sha256 = v_plan) then
    return null;
  end if;
  delete from look_withdrawal w
   using look_version l
   where w.workspace_id = new.workspace_id and l.workspace_id = new.workspace_id
     and w.key = l.key and w.version = l.version and l.plan_sha256 = v_plan;
  with deleted as (
    delete from look_version l where l.workspace_id = new.workspace_id and l.plan_sha256 = v_plan
    returning l.container_sha256
  )
  select coalesce(array_agg(distinct d.container_sha256)
                    filter (where d.container_sha256 is not null), '{}')
    into v_containers
    from deleted d;
  -- Each deleted look's container, unless a look the workspace still holds names the same bytes.
  if v_anchor = 'held' then
    insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
    select new.tombstone_id, new.workspace_id, 'look', c
      from unnest(v_containers) c
     where not exists (select 1 from look_version l
                        where l.workspace_id = new.workspace_id and l.container_sha256 = c);
  end if;
  delete from body_plan_version p where p.workspace_id = new.workspace_id and p.sha256 = v_plan
  returning p.recipe_sha256 into v_recipe;
  if v_recipe is not null and not exists (
       select 1 from body_plan_version p
        where p.workspace_id = new.workspace_id and p.recipe_sha256 = v_recipe) then
    delete from body_recipe_version r
     where r.workspace_id = new.workspace_id and r.sha256 = v_recipe;
  end if;
  return null;
end $fn$;

comment on function tg_thing_erasure_erases() is
  'An erasure''s deletes: the kind at its digest, and when no other kind names its drafted plan, '
  'the looks drawn on it with their withdrawals, the plan and its recipe, and those looks'' '
  'containers enqueued on its creature tombstone. Runs as exulanica_definer, in the erasure''s '
  'own workspace.';

create trigger tg_thing_erasure_erases after insert on thing_erasure
  for each row execute function tg_thing_erasure_erases();

-- A workspace tombstone erases every creature the workspace holds, in its own workspace.
create function tg_thing_store_erases_on_tombstone() returns trigger
language plpgsql security definer as $fn$
begin
  if new.scope <> 'workspace' then
    return new;
  end if;
  -- Row-level security binds this owner, so the tombstone's workspace must be the session's.
  perform assert_workspace_context(new.workspace_id);
  delete from look_withdrawal w where w.workspace_id = new.workspace_id;
  delete from look_version l where l.workspace_id = new.workspace_id;
  delete from thing_kind_version k where k.workspace_id = new.workspace_id;
  delete from body_plan_version p where p.workspace_id = new.workspace_id;
  delete from body_recipe_version r where r.workspace_id = new.workspace_id;
  return new;
end $fn$;

comment on function tg_thing_store_erases_on_tombstone() is
  'A workspace tombstone''s erasure of every creature and look the workspace keeps, at once. Runs '
  'as exulanica_definer, in the tombstone''s own workspace.';

create trigger tg_thing_store_erases_on_tombstone
  after insert on tombstone
  for each row execute function tg_thing_store_erases_on_tombstone();

-- Its order among the tombstone's AFTER triggers does not matter: it acts on workspace scope only,
-- after 0137's, which sorts first and holds the workspace's lock.
create function tg_look_purge_on_tombstone() returns trigger
language plpgsql as $fn$
begin
  if new.scope <> 'workspace' then
    return new;
  end if;
  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select new.tombstone_id, new.workspace_id, 'look', o.content_sha256
    from look_object o
   where o.workspace_id = new.workspace_id
     and o.purged_at is null
  on conflict (tombstone_id, target_kind, target_ref) do nothing;
  return new;
end $fn$;

create trigger tg_look_purge_on_tombstone
  after insert on tombstone
  for each row execute function tg_look_purge_on_tombstone();

-- Re-stated from 0126 with two clauses added: a look job whose object is not yet marked purged,
-- and, for a workspace tombstone, any looks object still holding bytes. Everything 0126 asks is
-- asked unchanged, and a creature tombstone is asked the first clause as every scope is.
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
            and o.purged_at is null)))) then
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
                        and o.purged_at is null);
  end if;
  return true;
end $fn$;

-- --------------------------------------------------------------------------------------------
-- 4. The three definers: their owner, path and grants.
-- --------------------------------------------------------------------------------------------

do $$ begin
  execute format('alter function tg_thing_erasure_erases() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function look_purge_is_authorized(uuid,uuid,text) '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
  execute format('alter function tg_thing_store_erases_on_tombstone() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function tg_thing_erasure_erases() from public;
revoke all on function tg_thing_store_erases_on_tombstone() from public;
revoke all on function look_purge_is_authorized(uuid, uuid, text) from public;

-- The erasures' deletes and reads; an erasure's jobs on its tombstone, inserted with no conflict
-- target, so INSERT alone. The tombstone they read is 0161's grant.
grant select, delete on body_recipe_version, body_plan_version, thing_kind_version, look_version,
  look_withdrawal to exulanica_definer;
grant insert on purge_job to exulanica_definer;
alter function tg_thing_erasure_erases() owner to exulanica_definer;
alter function tg_thing_store_erases_on_tombstone() owner to exulanica_definer;
alter function look_purge_is_authorized(uuid, uuid, text) owner to exulanica_definer;

commit;
