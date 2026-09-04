-- 0030_person_scoped_derivative_withdrawal.sql
-- A confirmed identity decision creates durable edges from a person to every derivative that
-- contains or describes that occurrence. Entity withdrawal follows those recorded edges. It
-- never reruns a recognizer at deletion time and it never deletes the source photograph.

begin;

select pg_advisory_xact_lock(119622309);

alter table entity add constraint entity_workspace_entity_uniq unique (workspace_id, entity_id);

create table person_derivative_dependency (
  dependency_id uuid primary key default uuidv7(),
  workspace_id  uuid not null,
  entity_id     uuid not null,
  occurrence_id uuid not null,
  capture_id    uuid not null,
  link_id       uuid not null,
  target_kind   text not null check (target_kind in
    ('artifact','scene','scene_job','embedding','derived_artifact','assertion')),
  target_id     uuid not null,
  basis         text not null default 'confirmed_identity_link'
    check (basis = 'confirmed_identity_link'),
  created_at    timestamptz not null default now(),
  foreign key (workspace_id, entity_id) references entity(workspace_id, entity_id),
  foreign key (link_id) references entity_link(link_id),
  foreign key (occurrence_id) references occurrence(occurrence_id),
  foreign key (workspace_id, capture_id) references capture(workspace_id, capture_id),
  unique (workspace_id, entity_id, occurrence_id, target_kind, target_id)
);

create index person_derivative_dependency_entity_idx
  on person_derivative_dependency (workspace_id, entity_id, target_kind, target_id);
create index person_derivative_dependency_target_idx
  on person_derivative_dependency (workspace_id, target_kind, target_id);

create table person_withdrawal_receipt (
  receipt_id       uuid primary key default uuidv7(),
  workspace_id    uuid not null,
  tombstone_id    uuid not null unique references tombstone(tombstone_id),
  entity_id       uuid not null,
  record          jsonb not null,
  canonical_bytes bytea not null,
  record_digest   bytea not null check (octet_length(record_digest) = 32),
  created_at      timestamptz not null default now(),
  foreign key (workspace_id, entity_id) references entity(workspace_id, entity_id),
  check (convert_from(canonical_bytes, 'UTF8')::jsonb = record),
  check (digest(canonical_bytes, 'sha256') = record_digest)
);

create function tg_person_withdrawal_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

create trigger tg_person_dependency_append_only
  before update or delete on person_derivative_dependency
  for each row execute function tg_person_withdrawal_append_only();
create trigger tg_person_receipt_append_only
  before update or delete on person_withdrawal_receipt
  for each row execute function tg_person_withdrawal_append_only();

create function record_person_dependency(
  p_workspace uuid,
  p_capture uuid,
  p_kind text,
  p_target uuid
) returns void
language sql volatile as $fn$
  insert into person_derivative_dependency (
    workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
  select l.workspace_id, l.entity_id, o.occurrence_id, o.capture_id, l.link_id,
         p_kind, p_target
    from occurrence o
    join entity_link l on l.workspace_id = o.workspace_id
                      and l.occurrence_id = o.occurrence_id
                      and l.state = 'confirmed'
   where o.workspace_id = p_workspace
     and o.capture_id = p_capture
  on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
$fn$;

create function record_person_dependencies_for_link(p_link uuid) returns void
language plpgsql volatile as $fn$
declare
  v_link entity_link%rowtype;
  v_capture capture%rowtype;
begin
  select * into v_link from entity_link where link_id = p_link and state = 'confirmed';
  if not found then
    return;
  end if;
  select c.* into strict v_capture
    from occurrence o join capture c on c.capture_id = o.capture_id
   where o.occurrence_id = v_link.occurrence_id;

  insert into person_derivative_dependency (
    workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
  select v_link.workspace_id, v_link.entity_id, v_link.occurrence_id, v_capture.capture_id,
         v_link.link_id, targets.target_kind, targets.target_id
    from (
      select 'artifact'::text, a.artifact_id
        from artifact a
       where a.workspace_id = v_link.workspace_id
         and ((a.kind = 'point_map' and a.source_blob_sha256 = v_capture.blob_sha256)
              or (a.scene_id is not null and exists (
                    select 1 from reconstruction_scene_member m
                     where m.workspace_id = v_link.workspace_id
                       and m.scene_id = a.scene_id
                       and m.capture_id = v_capture.capture_id)))
      union all
      select 'scene', m.scene_id from reconstruction_scene_member m
       where m.workspace_id = v_link.workspace_id and m.capture_id = v_capture.capture_id
      union all
      select 'scene_job', m.job_id from reconstruction_scene_job_member m
       where m.workspace_id = v_link.workspace_id and m.capture_id = v_capture.capture_id
      union all
      select 'embedding', e.embedding_id from embedding e
       where e.workspace_id = v_link.workspace_id
         and ((e.ref_type = 'entity' and e.ref_id = v_link.entity_id)
              or (e.ref_type = 'occurrence' and e.ref_id = v_link.occurrence_id))
      union all
      select 'derived_artifact', d.derived_id from derived_artifact d
       where d.workspace_id = v_link.workspace_id
         and (('entity:' || v_link.entity_id::text) = any(d.dep_index)
              or ('occurrence:' || v_link.occurrence_id::text) = any(d.dep_index)
              or ('capture:' || v_capture.capture_id::text) = any(d.dep_index))
      union all
      select 'assertion', a.assertion_id from assertion a
       where a.workspace_id = v_link.workspace_id
         and ((a.subject_ref->>'type' = 'entity'
               and a.subject_ref->>'id' = v_link.entity_id::text)
              or (a.subject_ref->>'type' = 'scene' and exists (
                    select 1 from reconstruction_scene_member m
                     where m.workspace_id = v_link.workspace_id
                       and m.capture_id = v_capture.capture_id
                       and m.scene_id::text = a.subject_ref->>'id')))
    ) as targets(target_kind, target_id)
  on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
end $fn$;

create function tg_record_person_dependencies_from_link() returns trigger
language plpgsql as $fn$
begin
  if new.state = 'confirmed' then
    perform record_person_dependencies_for_link(new.link_id);
  end if;
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_link
  after insert or update of state on entity_link
  for each row execute function tg_record_person_dependencies_from_link();

create function tg_record_person_dependencies_from_artifact() returns trigger
language plpgsql as $fn$
declare
  v_capture uuid;
begin
  if new.kind = 'point_map' then
    for v_capture in
      select c.capture_id from capture c
       where c.workspace_id = new.workspace_id
         and c.blob_sha256 = new.source_blob_sha256
    loop
      perform record_person_dependency(new.workspace_id, v_capture, 'artifact', new.artifact_id);
    end loop;
  elsif new.scene_id is not null then
    for v_capture in
      select m.capture_id from reconstruction_scene_member m
       where m.workspace_id = new.workspace_id and m.scene_id = new.scene_id
    loop
      perform record_person_dependency(new.workspace_id, v_capture, 'artifact', new.artifact_id);
    end loop;
  end if;
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_artifact
  after insert on artifact
  for each row execute function tg_record_person_dependencies_from_artifact();

create function tg_record_person_dependencies_from_scene_member() returns trigger
language plpgsql as $fn$
begin
  perform record_person_dependency(new.workspace_id, new.capture_id, 'scene', new.scene_id);
  insert into person_derivative_dependency (
    workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
  select d.workspace_id, d.entity_id, d.occurrence_id, d.capture_id, d.link_id,
         'artifact', a.artifact_id
    from person_derivative_dependency d
    join artifact a on a.workspace_id = d.workspace_id and a.scene_id = new.scene_id
   where d.workspace_id = new.workspace_id
     and d.target_kind = 'scene' and d.target_id = new.scene_id
  on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_scene_member
  after insert on reconstruction_scene_member
  for each row execute function tg_record_person_dependencies_from_scene_member();

create function tg_record_person_dependencies_from_job_member() returns trigger
language plpgsql as $fn$
begin
  perform record_person_dependency(new.workspace_id, new.capture_id, 'scene_job', new.job_id);
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_job_member
  after insert on reconstruction_scene_job_member
  for each row execute function tg_record_person_dependencies_from_job_member();

create function tg_record_person_dependencies_from_embedding() returns trigger
language plpgsql as $fn$
declare
  v_capture uuid;
begin
  if new.ref_type = 'occurrence' then
    select o.capture_id into v_capture from occurrence o where o.occurrence_id = new.ref_id;
    if v_capture is not null then
      perform record_person_dependency(new.workspace_id, v_capture, 'embedding', new.embedding_id);
    end if;
  elsif new.ref_type = 'entity' then
    insert into person_derivative_dependency (
      workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
    select l.workspace_id, l.entity_id, l.occurrence_id, o.capture_id, l.link_id,
           'embedding', new.embedding_id
      from entity_link l join occurrence o on o.occurrence_id = l.occurrence_id
     where l.workspace_id = new.workspace_id and l.entity_id = new.ref_id
       and l.state = 'confirmed'
    on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
  end if;
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_embedding
  after insert on embedding
  for each row execute function tg_record_person_dependencies_from_embedding();

create function tg_record_person_dependencies_from_derived() returns trigger
language plpgsql as $fn$
begin
  insert into person_derivative_dependency (
    workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
  select l.workspace_id, l.entity_id, l.occurrence_id, o.capture_id, l.link_id,
         'derived_artifact', new.derived_id
    from entity_link l join occurrence o on o.occurrence_id = l.occurrence_id
   where l.workspace_id = new.workspace_id and l.state = 'confirmed'
     and (('entity:' || l.entity_id::text) = any(new.dep_index)
          or ('occurrence:' || l.occurrence_id::text) = any(new.dep_index)
          or ('capture:' || o.capture_id::text) = any(new.dep_index))
  on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_derived
  after insert on derived_artifact
  for each row execute function tg_record_person_dependencies_from_derived();

create function tg_record_person_dependencies_from_assertion() returns trigger
language plpgsql as $fn$
begin
  if new.subject_ref->>'type' = 'entity' then
    insert into person_derivative_dependency (
      workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
    select l.workspace_id, l.entity_id, l.occurrence_id, o.capture_id, l.link_id,
           'assertion', new.assertion_id
      from entity_link l join occurrence o on o.occurrence_id = l.occurrence_id
     where l.workspace_id = new.workspace_id and l.state = 'confirmed'
       and l.entity_id::text = new.subject_ref->>'id'
    on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
  elsif new.subject_ref->>'type' = 'scene' then
    insert into person_derivative_dependency (
      workspace_id, entity_id, occurrence_id, capture_id, link_id, target_kind, target_id)
    select d.workspace_id, d.entity_id, d.occurrence_id, d.capture_id, d.link_id,
           'assertion', new.assertion_id
      from person_derivative_dependency d
     where d.workspace_id = new.workspace_id and d.target_kind = 'scene'
       and d.target_id::text = new.subject_ref->>'id'
    on conflict (workspace_id, entity_id, occurrence_id, target_kind, target_id) do nothing;
  end if;
  return new;
end $fn$;

create trigger tg_record_person_dependencies_from_assertion
  after insert on assertion
  for each row execute function tg_record_person_dependencies_from_assertion();

-- Record the dependency graph that already exists before this migration.
select record_person_dependencies_for_link(link_id)
  from entity_link where state = 'confirmed';

create function person_withdrawal_blocks_capture(p_workspace uuid, p_capture uuid)
returns boolean
language sql volatile as $fn$
  select exists (
    select 1 from occurrence o
    join entity_link l on l.workspace_id = o.workspace_id
                      and l.occurrence_id = o.occurrence_id
                      and l.state = 'confirmed'
   where o.workspace_id = p_workspace and o.capture_id = p_capture
     and tombstone_blocks_entity(p_workspace, l.entity_id));
$fn$;

create function person_withdrawal_blocks_artifact(p_workspace uuid, p_artifact uuid)
returns boolean
language sql volatile as $fn$
  select exists (
    select 1 from person_derivative_dependency d
     where d.workspace_id = p_workspace and d.target_kind = 'artifact'
       and d.target_id = p_artifact
       and tombstone_blocks_entity(p_workspace, d.entity_id));
$fn$;

create or replace function tombstone_blocks_scene(p_workspace uuid, p_scene uuid)
returns boolean
language sql volatile as $fn$
  select
    not exists (select 1 from reconstruction_scene_member m
                 where m.workspace_id = p_workspace and m.scene_id = p_scene)
    or exists (
      select 1 from reconstruction_scene_member m
      join capture c on c.capture_id = m.capture_id
       where m.workspace_id = p_workspace and m.scene_id = p_scene
         and (c.deleted_at is not null
              or tombstone_blocks_capture(p_workspace, m.capture_id)
              or person_withdrawal_blocks_capture(p_workspace, m.capture_id)));
$fn$;

create or replace function tombstone_blocks_reconstruction_job(p_workspace uuid, p_job uuid)
returns boolean
language sql volatile as $fn$
  select
    not exists (select 1 from reconstruction_scene_job_member m
                 where m.workspace_id = p_workspace and m.job_id = p_job)
    or exists (
      select 1 from reconstruction_scene_job_member m
      join capture c on c.workspace_id = m.workspace_id and c.capture_id = m.capture_id
       where m.workspace_id = p_workspace and m.job_id = p_job
         and (c.deleted_at is not null
              or tombstone_blocks_capture(p_workspace, m.capture_id)
              or person_withdrawal_blocks_capture(p_workspace, m.capture_id)));
$fn$;

create or replace function tg_tombstone_guard_artifact() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if new.scene_id is not null then
    if tombstone_blocks_scene(new.workspace_id, new.scene_id) then
      perform tombstone_refuse('artifact');
    end if;
  elsif tombstone_blocks_derivative(new.workspace_id, new.source_blob_sha256)
        or (new.kind = 'point_map' and exists (
              select 1 from capture c
               where c.workspace_id = new.workspace_id
                 and c.blob_sha256 = new.source_blob_sha256
                 and person_withdrawal_blocks_capture(new.workspace_id, c.capture_id))) then
    perform tombstone_refuse('artifact');
  end if;
  return new;
end $fn$;

create or replace function tg_reconstruction_scene_member_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from capture c
                  where c.workspace_id = new.workspace_id
                    and c.capture_id = new.capture_id
                    and c.deleted_at is null) then
    raise exception 'a scene member names an absent or deleted photograph'
      using errcode = 'foreign_key_violation';
  end if;
  if tombstone_blocks_capture(new.workspace_id, new.capture_id)
     or person_withdrawal_blocks_capture(new.workspace_id, new.capture_id) then
    perform tombstone_refuse('reconstruction_scene_member');
  end if;
  return new;
end $fn$;

create or replace function tg_reconstruction_job_member_live() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists (select 1 from capture c
                  where c.workspace_id = new.workspace_id
                    and c.capture_id = new.capture_id
                    and c.deleted_at is null) then
    raise exception 'a reconstruction job member names an absent or deleted photograph'
      using errcode = 'foreign_key_violation';
  end if;
  if tombstone_blocks_capture(new.workspace_id, new.capture_id)
     or person_withdrawal_blocks_capture(new.workspace_id, new.capture_id) then
    perform tombstone_refuse('reconstruction_scene_job_member');
  end if;
  return new;
end $fn$;

create or replace function tg_tombstone_guard_embedding() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if new.ref_type = 'span' and tombstone_blocks_any_span(new.workspace_id, array[new.ref_id]) then
    perform tombstone_refuse('embedding');
  end if;
  if new.ref_type = 'entity' and tombstone_blocks_entity(new.workspace_id, new.ref_id) then
    perform tombstone_refuse('embedding');
  end if;
  if new.ref_type = 'occurrence' and exists (
       select 1 from occurrence o
        where o.occurrence_id = new.ref_id
          and (tombstone_blocks_capture(o.workspace_id, o.capture_id)
               or tombstone_blocks_any_span(o.workspace_id, o.span_ids)
               or exists (select 1 from entity_link l
                           where l.workspace_id = o.workspace_id
                             and l.occurrence_id = o.occurrence_id
                             and l.state = 'confirmed'
                             and tombstone_blocks_entity(o.workspace_id, l.entity_id)))) then
    perform tombstone_refuse('embedding');
  end if;
  if exists (select 1 from tombstone t
              where t.workspace_id = new.workspace_id
                and t.effective_at <= clock_timestamp()
                and t.scope = 'workspace') then
    perform tombstone_refuse('embedding');
  end if;
  return new;
end $fn$;

create function tg_entity_tombstone_names_local_entity() returns trigger
language plpgsql as $fn$
begin
  if new.scope = 'entity' then
    perform assert_workspace_context(new.workspace_id);
    if not exists (select 1 from entity e
                    where e.workspace_id = new.workspace_id and e.entity_id = new.entity_id) then
      raise exception 'an entity tombstone names an absent or foreign entity'
        using errcode = 'foreign_key_violation';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_entity_tombstone_names_local_entity
  before insert on tombstone
  for each row execute function tg_entity_tombstone_names_local_entity();

create function tg_person_withdrawal_cascade() returns trigger
language plpgsql as $fn$
declare
  v_record jsonb;
  v_canonical bytea;
begin
  if new.scope <> 'entity' then
    return new;
  end if;

  update entity set display_name = null, deleted_at = coalesce(deleted_at, new.effective_at)
   where workspace_id = new.workspace_id and entity_id = new.entity_id;

  update derived_artifact d set stale = true
   where d.workspace_id = new.workspace_id and not d.stale
     and exists (select 1 from person_derivative_dependency p
                  where p.workspace_id = d.workspace_id and p.entity_id = new.entity_id
                    and p.target_kind = 'derived_artifact' and p.target_id = d.derived_id);

  update assertion a set status = 'retracted'
   where a.workspace_id = new.workspace_id and a.status = 'active'
     and exists (select 1 from person_derivative_dependency p
                  where p.workspace_id = a.workspace_id and p.entity_id = new.entity_id
                    and p.target_kind = 'assertion' and p.target_id = a.assertion_id);

  update reconstruction_scene_job j
     set status = 'cancelled', claim_token = null, claimed_by = null,
         lease_expires_at = null, completed_at = coalesce(j.completed_at, new.effective_at),
         updated_at = clock_timestamp(), failure_class = 'person_withdrawn',
         failure_message = 'a confirmed person in one member withdrew'
   where j.workspace_id = new.workspace_id and j.status in ('queued','running','failed')
     and exists (select 1 from person_derivative_dependency p
                  where p.workspace_id = j.workspace_id and p.entity_id = new.entity_id
                    and p.target_kind = 'scene_job' and p.target_id = j.job_id);

  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select distinct new.tombstone_id, new.workspace_id, 'artifact',
         encode(a.content_sha256, 'hex')
    from person_derivative_dependency p
    join artifact a on a.workspace_id = p.workspace_id and a.artifact_id = p.target_id
   where p.workspace_id = new.workspace_id and p.entity_id = new.entity_id
     and p.target_kind = 'artifact' and a.content_sha256 is not null and a.purged_at is null
  on conflict (tombstone_id, target_kind, target_ref) do nothing;

  insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref)
  select distinct new.tombstone_id, new.workspace_id, 'embedding', p.target_id::text
    from person_derivative_dependency p
    join embedding e on e.workspace_id = p.workspace_id and e.embedding_id = p.target_id
   where p.workspace_id = new.workspace_id and p.entity_id = new.entity_id
     and p.target_kind = 'embedding'
  on conflict (tombstone_id, target_kind, target_ref) do nothing;

  v_record := jsonb_build_object(
    'profile', 'exulanica.person-withdrawal-receipt/v1',
    'tombstone_id', new.tombstone_id,
    'workspace_id', new.workspace_id,
    'entity_id', new.entity_id,
    'effective_at', new.effective_at,
    'dependency_count', (select count(*) from person_derivative_dependency p
                          where p.workspace_id = new.workspace_id
                            and p.entity_id = new.entity_id),
    'purge_job_count', (select count(*) from purge_job p
                        where p.tombstone_id = new.tombstone_id),
    'cancelled_scene_job_count', (select count(*) from reconstruction_scene_job j
                                  where j.workspace_id = new.workspace_id
                                    and j.failure_class = 'person_withdrawn'
                                    and exists (select 1 from person_derivative_dependency p
                                      where p.workspace_id = j.workspace_id
                                        and p.entity_id = new.entity_id
                                        and p.target_kind = 'scene_job'
                                        and p.target_id = j.job_id)),
    'retracted_assertion_count', (select count(*) from assertion a
                                  where a.workspace_id = new.workspace_id
                                    and a.status = 'retracted'
                                    and exists (select 1 from person_derivative_dependency p
                                      where p.workspace_id = a.workspace_id
                                        and p.entity_id = new.entity_id
                                        and p.target_kind = 'assertion'
                                        and p.target_id = a.assertion_id)),
    'source_capture_policy', 'retained');
  v_canonical := convert_to(v_record::text, 'UTF8');
  insert into person_withdrawal_receipt (
    workspace_id, tombstone_id, entity_id, record, canonical_bytes, record_digest)
  values (new.workspace_id, new.tombstone_id, new.entity_id, v_record, v_canonical,
          digest(v_canonical, 'sha256'));
  return new;
end $fn$;

create trigger tg_person_withdrawal_cascade
  after insert on tombstone
  for each row execute function tg_person_withdrawal_cascade();

create function person_withdrawal_releases_artifact(p_tombstone uuid, p_bytes bytea)
returns boolean
language plpgsql volatile as $fn$
declare
  v_workspace uuid;
  v_entity uuid;
begin
  if p_bytes is null then
    raise exception 'person withdrawal was asked to release an absent content hash'
      using errcode = 'null_value_not_allowed';
  end if;
  select t.workspace_id, t.entity_id into v_workspace, v_entity
    from tombstone t where t.tombstone_id = p_tombstone and t.scope = 'entity';
  if v_entity is null then
    return false;
  end if;
  return
    not exists (select 1 from capture c
                 where c.blob_sha256 = p_bytes and c.deleted_at is null)
    and not exists (
      select 1 from artifact a
       where a.content_sha256 = p_bytes and a.purged_at is null
         and not exists (
           select 1 from person_derivative_dependency d
            where d.workspace_id = a.workspace_id
              and d.entity_id = v_entity
              and d.target_kind = 'artifact'
              and d.target_id = a.artifact_id));
end $fn$;

create or replace function tombstone_purge_is_complete(p_tombstone uuid) returns boolean
language plpgsql volatile as $fn$
declare
  v_scope text;
  v_workspace uuid;
begin
  select t.scope::text, t.workspace_id into v_scope, v_workspace
    from tombstone t where t.tombstone_id = p_tombstone;
  if v_scope is null then
    return false;
  end if;
  if exists (
    select 1 from purge_job pj
     where pj.tombstone_id = p_tombstone
       and (pj.state <> 'done'
            or (pj.target_kind = 'blob' and exists (
                  select 1 from blob b
                   where b.blob_sha256 = decode(pj.target_ref, 'hex') and b.purged_at is null))
            or (pj.target_kind = 'artifact' and exists (
                  select 1 from artifact a
                   where a.workspace_id = pj.workspace_id
                     and a.content_sha256 = decode(pj.target_ref, 'hex')
                     and a.purged_at is null))
            or (pj.target_kind = 'embedding' and exists (
                  select 1 from embedding e
                   where e.workspace_id = pj.workspace_id
                     and e.embedding_id = pj.target_ref::uuid)))) then
    return false;
  end if;
  if v_scope = 'workspace' then
    return not exists (
      select 1 from capture c join blob b on b.blob_sha256 = c.blob_sha256
       where c.workspace_id = v_workspace and b.purged_at is null)
      and not exists (
      select 1 from artifact a where a.workspace_id = v_workspace
       and a.content_sha256 is not null and a.purged_at is null)
      and not exists (
      select 1 from embedding e where e.workspace_id = v_workspace);
  end if;
  return true;
end $fn$;

do $$
declare
  t text;
begin
  foreach t in array array['person_derivative_dependency', 'person_withdrawal_receipt'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

commit;
