-- Durable span-vector deletion, without enlarging the purge role's table privileges.
begin;
select pg_advisory_xact_lock(119622309);

-- Keep the authorization after the vector is gone, so retries can report already absent.
create table tombstone_embedding_target (
  workspace_id uuid not null,
  tombstone_id uuid not null references tombstone(tombstone_id),
  embedding_id uuid not null,
  primary key (workspace_id, tombstone_id, embedding_id)
);
alter table tombstone_embedding_target enable row level security;
alter table tombstone_embedding_target force row level security;
create policy ws_isolation on tombstone_embedding_target
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

-- Serialize vector INSERT with the tombstone snapshot. A paid call does not hold this lock:
-- it is taken only when its result reaches the database, before the existing tombstone guard.
create function tg_caption_vector_lifecycle_lock() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(
    'caption-vector-lifecycle:' || new.workspace_id::text, 0));
  if tg_table_name <> 'tombstone' then
    if exists (select 1 from tombstone_embedding_target d
               where d.workspace_id=new.workspace_id and d.embedding_id=new.embedding_id) then
      perform tombstone_refuse('embedding');
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_caption_vector_lifecycle_lock before insert on embedding
  for each row execute function tg_caption_vector_lifecycle_lock();
create trigger tg_caption_vector_lifecycle_lock before insert on tombstone
  for each row execute function tg_caption_vector_lifecycle_lock();

create function tg_tombstone_records_embedding_targets() returns trigger
language plpgsql as $fn$
begin
  if new.scope not in ('capture', 'workspace') then return new; end if;
  insert into tombstone_embedding_target (workspace_id, tombstone_id, embedding_id)
  select new.workspace_id, new.tombstone_id, e.embedding_id from embedding e
  where e.workspace_id=new.workspace_id and (
    new.scope='workspace' or (e.ref_type='span' and exists (
      select 1 from evidence_span s join capture c
        on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256
      where s.workspace_id=e.workspace_id and s.span_id=e.ref_id
        and c.capture_id=new.capture_id)));
  insert into purge_job (workspace_id, tombstone_id, target_kind, target_ref)
  select workspace_id, tombstone_id, 'embedding', embedding_id::text
    from tombstone_embedding_target where tombstone_id=new.tombstone_id
      and workspace_id=new.workspace_id
  on conflict (tombstone_id, target_kind, target_ref) do nothing;
  return new;
end $fn$;
create trigger tg_tombstone_records_embedding_targets after insert on tombstone
  for each row execute function tg_tombstone_records_embedding_targets();

-- Repair pre-0044 orphaned rows and reopen false completion markers. Intentional reimports
-- after a capture deletion may own new vectors on the same span; keep those when the existing
-- span predicate releases them. Older vectors that predate deletion remain deletion targets.
insert into tombstone_embedding_target (workspace_id, tombstone_id, embedding_id)
select t.workspace_id, t.tombstone_id, e.embedding_id
from tombstone t join embedding e on e.workspace_id=t.workspace_id
where t.scope='workspace' or (t.scope='capture' and e.ref_type='span' and exists (
  select 1 from evidence_span s join capture c
    on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256
  where s.workspace_id=e.workspace_id and s.span_id=e.ref_id and c.capture_id=t.capture_id
    and (e.created_at <= t.requested_at
         or tombstone_blocks_any_span(e.workspace_id, array[e.ref_id]))));
insert into purge_job (workspace_id, tombstone_id, target_kind, target_ref)
select workspace_id, tombstone_id, 'embedding', embedding_id::text
  from tombstone_embedding_target
on conflict (tombstone_id, target_kind, target_ref) do update
  set state='queued', attempts=0, attempted_at=null, completed_at=null, last_error=null;
update tombstone t set purge_completed_at=null where exists (
  select 1 from tombstone_embedding_target d where d.tombstone_id=t.tombstone_id);

-- A runtime writer can create a tombstone, not forge or rewrite its durable vector targets.
-- Administrative TRUNCATE is intentionally left to the table owner, as for other derived data.
create function tg_embedding_target_is_trigger_owned() returns trigger
language plpgsql as $fn$
begin
  if tg_op <> 'INSERT' or pg_trigger_depth() < 2 then
    raise exception 'embedding deletion targets are owned by the tombstone trigger'
      using errcode='42501';
  end if;
  return new;
end $fn$;
create trigger tg_embedding_target_is_trigger_owned
  before insert or update or delete on tombstone_embedding_target
  for each row execute function tg_embedding_target_is_trigger_owned();

-- Narrow boolean capabilities avoid granting the purge role general span or target-table
-- reads. They cannot authorize a target in a different session workspace. The person-dependent
-- arm preserves the existing 0030 authorization; a missing vector remains an authorized retry.
create function caption_vector_purge_is_authorized(
  p_workspace uuid, p_tombstone uuid, p_embedding uuid
) returns boolean language sql volatile security definer as $fn$
  select p_workspace=current_workspace() and exists (
    select 1 from tombstone t where t.workspace_id=p_workspace
      and t.tombstone_id=p_tombstone and t.effective_at <= now() and (
        exists (select 1 from tombstone_embedding_target d
          where d.workspace_id=t.workspace_id and d.tombstone_id=t.tombstone_id
            and d.embedding_id=p_embedding)
        or (t.scope='entity' and exists (select 1 from person_derivative_dependency d
          where d.workspace_id=t.workspace_id and d.entity_id=t.entity_id
            and d.target_kind='embedding' and d.target_id=p_embedding))));
$fn$;
create function caption_vector_purge_is_complete(p_workspace uuid, p_tombstone uuid)
returns boolean language sql volatile security definer as $fn$
  select p_workspace=current_workspace() and not exists (
    select 1 from tombstone_embedding_target d join embedding e
      on e.workspace_id=d.workspace_id and e.embedding_id=d.embedding_id
    where d.workspace_id=p_workspace and d.tombstone_id=p_tombstone);
$fn$;
-- Pin trusted resolution, including pg_temp last, before exposing either capability.
do $$ begin
  execute format('alter function caption_vector_purge_is_authorized(uuid,uuid,uuid) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
  execute format('alter function caption_vector_purge_is_complete(uuid,uuid) '
                 'set search_path = %I, pg_catalog, pg_temp', current_schema());
end $$;

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
          where e.workspace_id=pj.workspace_id and e.embedding_id=pj.target_ref::uuid)))) then
    return false;
  end if;
  if v_scope='workspace' then
    return not exists (select 1 from capture c join blob b on b.blob_sha256=c.blob_sha256
                        where c.workspace_id=v_workspace and b.purged_at is null)
       and not exists (select 1 from artifact a where a.workspace_id=v_workspace
                        and a.content_sha256 is not null and a.purged_at is null)
       and not exists (select 1 from embedding e where e.workspace_id=v_workspace);
  end if;
  return true;
end $fn$;
commit;
