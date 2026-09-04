-- 0029_reconstruction_privacy_admission.sql
-- Fail closed before photograph geometry is produced or an exact scene set is queued.

begin;

select pg_advisory_xact_lock(119622309);

create table capture_reconstruction_authorization (
  authorization_id       uuid primary key,
  workspace_id           uuid not null,
  capture_id             uuid not null,
  source_sha256          bytea not null check (octet_length(source_sha256) = 32),
  corpus_class           text not null
    check (corpus_class in ('synthetic', 'benchmark', 'personal')),
  purpose                text not null check (length(trim(purpose)) > 0),
  authorization_scope    jsonb not null check (jsonb_typeof(authorization_scope) = 'object'),
  authorization_evidence jsonb not null check (jsonb_typeof(authorization_evidence) = 'object'),
  authorization_record   jsonb not null check (jsonb_typeof(authorization_record) = 'object'),
  authorization_canonical bytea not null,
  evidence_digest        bytea not null check (octet_length(evidence_digest) = 32),
  synthetic_manifest_digest bytea check (
    synthetic_manifest_digest is null or octet_length(synthetic_manifest_digest) = 32),
  authorized_by          uuid not null,
  authorized_at          timestamptz not null default now(),
  valid_until            timestamptz,
  unique (workspace_id, authorization_id),
  foreign key (workspace_id, capture_id)
    references capture(workspace_id, capture_id),
  check (valid_until is null or valid_until > authorized_at),
  check (digest(authorization_canonical, 'sha256') = evidence_digest),
  check (convert_from(authorization_canonical, 'UTF8')::jsonb = authorization_record),
  check (
    (corpus_class = 'synthetic'
      and synthetic_manifest_digest is not null
      and authorization_evidence ? 'generator_profile')
    or
    (corpus_class = 'benchmark'
      and synthetic_manifest_digest is null
      and authorization_evidence ? 'official_source_url'
      and authorization_evidence ? 'retrieval_date'
      and authorization_evidence ? 'license_document_sha256'
      and authorization_evidence ? 'permitted_use')
    or
    (corpus_class = 'personal'
      and synthetic_manifest_digest is null
      and authorization_evidence ? 'account_authority_basis'))
);

create table reconstruction_privacy_screening (
  screening_id           uuid primary key,
  workspace_id           uuid not null,
  authorization_id       uuid not null,
  capture_id             uuid not null,
  source_sha256          bytea not null check (octet_length(source_sha256) = 32),
  screening_method       text not null
    check (screening_method in ('synthetic_exemption', 'human_review')),
  model_id               text,
  model_revision         text,
  human_review_required  boolean not null,
  reviewed_by            uuid,
  sensitive_regions      jsonb not null default '[]'::jsonb
    check (jsonb_typeof(sensitive_regions) = 'array'),
  mask_artifacts         jsonb not null default '[]'::jsonb
    check (jsonb_typeof(mask_artifacts) = 'array'),
  eligibility_state      text not null
    check (eligibility_state in ('eligible', 'blocked', 'failed')),
  blocking_reasons       jsonb not null default '[]'::jsonb
    check (jsonb_typeof(blocking_reasons) = 'array'),
  policy_version         text not null,
  policy_params_digest   bytea not null check (octet_length(policy_params_digest) = 32),
  authorization_scope    jsonb not null check (jsonb_typeof(authorization_scope) = 'object'),
  screened_at            timestamptz not null default now(),
  valid_until            timestamptz,
  receipt_record         jsonb not null check (jsonb_typeof(receipt_record) = 'object'),
  receipt_canonical      bytea not null,
  receipt_digest         bytea not null check (octet_length(receipt_digest) = 32),
  unique (workspace_id, screening_id),
  unique (workspace_id, receipt_digest),
  foreign key (workspace_id, authorization_id)
    references capture_reconstruction_authorization(workspace_id, authorization_id),
  foreign key (workspace_id, capture_id)
    references capture(workspace_id, capture_id),
  check (valid_until is null or valid_until > screened_at),
  check (digest(receipt_canonical, 'sha256') = receipt_digest),
  check (convert_from(receipt_canonical, 'UTF8')::jsonb = receipt_record),
  check (jsonb_array_length(mask_artifacts) = 0),
  check (
    (screening_method = 'synthetic_exemption'
      and model_id is null and model_revision is null
      and not human_review_required and reviewed_by is null
      and jsonb_array_length(sensitive_regions) = 0
      and eligibility_state = 'eligible')
    or
    (screening_method = 'human_review'
      and model_id is null and model_revision is null
      and human_review_required and reviewed_by is not null)),
  check (
    (eligibility_state = 'eligible'
      and jsonb_array_length(sensitive_regions) = 0
      and jsonb_array_length(blocking_reasons) = 0)
    or
    (eligibility_state in ('blocked', 'failed')
      and jsonb_array_length(blocking_reasons) > 0))
);

create table reconstruction_privacy_admission (
  admission_id           uuid primary key,
  workspace_id           uuid not null,
  scene_id               uuid not null,
  member_digest          bytea not null check (octet_length(member_digest) = 32),
  corpus_class           text not null
    check (corpus_class in ('synthetic', 'benchmark', 'personal', 'mixed', 'unknown')),
  eligibility_state      text not null
    check (eligibility_state in ('eligible', 'blocked')),
  blocking_reasons       jsonb not null default '[]'::jsonb
    check (jsonb_typeof(blocking_reasons) = 'array'),
  policy_version         text not null,
  policy_params_digest   bytea not null check (octet_length(policy_params_digest) = 32),
  authorization_scope    jsonb not null check (jsonb_typeof(authorization_scope) = 'object'),
  admitted_at            timestamptz not null default now(),
  valid_until            timestamptz,
  admission_record       jsonb not null check (jsonb_typeof(admission_record) = 'object'),
  admission_canonical    bytea not null,
  admission_digest       bytea not null check (octet_length(admission_digest) = 32),
  unique (workspace_id, admission_id),
  unique (workspace_id, admission_digest),
  check (valid_until is null or valid_until > admitted_at),
  check (digest(admission_canonical, 'sha256') = admission_digest),
  check (convert_from(admission_canonical, 'UTF8')::jsonb = admission_record),
  check (
    (eligibility_state = 'eligible' and jsonb_array_length(blocking_reasons) = 0)
    or
    (eligibility_state = 'blocked' and jsonb_array_length(blocking_reasons) > 0))
);

create table reconstruction_privacy_admission_member (
  workspace_id       uuid not null,
  admission_id       uuid not null,
  capture_id         uuid not null,
  ordinal            int not null check (ordinal >= 0),
  source_sha256      bytea not null check (octet_length(source_sha256) = 32),
  authorization_id   uuid,
  screening_id       uuid,
  primary key (workspace_id, admission_id, capture_id),
  unique (workspace_id, admission_id, ordinal),
  foreign key (workspace_id, admission_id)
    references reconstruction_privacy_admission(workspace_id, admission_id),
  foreign key (workspace_id, capture_id)
    references capture(workspace_id, capture_id),
  foreign key (workspace_id, authorization_id)
    references capture_reconstruction_authorization(workspace_id, authorization_id),
  foreign key (workspace_id, screening_id)
    references reconstruction_privacy_screening(workspace_id, screening_id)
);

create function tg_reconstruction_privacy_append_only() returns trigger
language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

create function tg_capture_reconstruction_authorization_valid() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not exists (
    select 1 from capture c
     where c.workspace_id = new.workspace_id
       and c.capture_id = new.capture_id
       and c.blob_sha256 = new.source_sha256
       and c.deleted_at is null
       and not tombstone_blocks_capture(c.workspace_id, c.capture_id)) then
    raise exception 'reconstruction authorization requires the exact live source photograph'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_capture_reconstruction_authorization_valid
  before insert on capture_reconstruction_authorization
  for each row execute function tg_capture_reconstruction_authorization_valid();

create function tg_reconstruction_privacy_screening_valid() returns trigger
language plpgsql as $fn$
declare
  auth_row capture_reconstruction_authorization%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into auth_row
    from capture_reconstruction_authorization a
   where a.workspace_id = new.workspace_id
     and a.authorization_id = new.authorization_id;
  if not found
     or auth_row.capture_id <> new.capture_id
     or auth_row.source_sha256 <> new.source_sha256
     or auth_row.authorization_scope <> new.authorization_scope then
    raise exception 'privacy screening does not match its exact authorization and source'
      using errcode = 'integrity_constraint_violation';
  end if;
  if auth_row.valid_until is not null
     and auth_row.valid_until <= new.screened_at then
    raise exception 'privacy screening uses an expired authorization'
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.screening_method = 'synthetic_exemption'
     and auth_row.corpus_class <> 'synthetic' then
    raise exception 'synthetic exemption requires an explicitly synthetic authorization'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_reconstruction_privacy_screening_valid
  before insert on reconstruction_privacy_screening
  for each row execute function tg_reconstruction_privacy_screening_valid();

create function privacy_screening_allows_capture(
  p_workspace uuid,
  p_capture uuid,
  p_screening uuid)
returns boolean
language sql volatile as $fn$
  select exists (
    select 1
      from reconstruction_privacy_screening s
      join capture_reconstruction_authorization a
        on a.workspace_id = s.workspace_id
       and a.authorization_id = s.authorization_id
      join capture c
        on c.workspace_id = s.workspace_id
       and c.capture_id = s.capture_id
     where s.workspace_id = p_workspace
       and s.capture_id = p_capture
       and s.screening_id = p_screening
       and s.source_sha256 = c.blob_sha256
       and a.capture_id = s.capture_id
       and a.source_sha256 = s.source_sha256
       and a.authorization_scope = s.authorization_scope
       and s.eligibility_state = 'eligible'
       and jsonb_array_length(s.sensitive_regions) = 0
       and jsonb_array_length(s.mask_artifacts) = 0
       and (s.valid_until is null or s.valid_until > clock_timestamp())
       and (a.valid_until is null or a.valid_until > clock_timestamp())
       and c.deleted_at is null
       and not tombstone_blocks_capture(p_workspace, p_capture));
$fn$;

create function tg_reconstruction_privacy_admission_member_valid() returns trigger
language plpgsql as $fn$
declare
  auth_row capture_reconstruction_authorization%rowtype;
  screening_row reconstruction_privacy_screening%rowtype;
  admission_row reconstruction_privacy_admission%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into auth_row
    from capture_reconstruction_authorization a
   where a.workspace_id = new.workspace_id
     and a.authorization_id = new.authorization_id;
  select * into screening_row
    from reconstruction_privacy_screening s
   where s.workspace_id = new.workspace_id
     and s.screening_id = new.screening_id;
  select * into admission_row
    from reconstruction_privacy_admission a
   where a.workspace_id = new.workspace_id
     and a.admission_id = new.admission_id;
  if not exists (
       select 1 from capture c
        where c.workspace_id = new.workspace_id
          and c.capture_id = new.capture_id
          and c.blob_sha256 = new.source_sha256) then
    raise exception 'privacy admission member does not match its exact source photograph'
      using errcode = 'integrity_constraint_violation';
  end if;
  if admission_row.eligibility_state = 'eligible'
     and (new.authorization_id is null
       or new.screening_id is null
       or auth_row.capture_id is distinct from new.capture_id
       or auth_row.source_sha256 is distinct from new.source_sha256
       or screening_row.authorization_id is distinct from new.authorization_id
       or screening_row.capture_id is distinct from new.capture_id
       or screening_row.source_sha256 is distinct from new.source_sha256
       or admission_row.corpus_class is distinct from auth_row.corpus_class
       or admission_row.authorization_scope is distinct from auth_row.authorization_scope
       or screening_row.authorization_scope is distinct from auth_row.authorization_scope
       or not privacy_screening_allows_capture(
         new.workspace_id, new.capture_id, new.screening_id)) then
    raise exception 'privacy admission member is not an eligible exact authorized source'
      using errcode = 'integrity_constraint_violation';
  end if;
  if admission_row.eligibility_state = 'blocked'
     and new.screening_id is not null
     and (screening_row.capture_id is distinct from new.capture_id
       or screening_row.source_sha256 is distinct from new.source_sha256) then
    raise exception 'blocked privacy admission names a screening for another source'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_reconstruction_privacy_admission_member_valid
  before insert on reconstruction_privacy_admission_member
  for each row execute function tg_reconstruction_privacy_admission_member_valid();

do $$
declare
  t text;
begin
  foreach t in array array[
    'capture_reconstruction_authorization',
    'reconstruction_privacy_screening',
    'reconstruction_privacy_admission',
    'reconstruction_privacy_admission_member'] loop
    execute format(
      'create trigger %I before update or delete on %I '
      'for each row execute function tg_reconstruction_privacy_append_only()',
      'tg_' || t || '_append_only', t);
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

alter table artifact
  add column privacy_screening_id uuid,
  add foreign key (workspace_id, privacy_screening_id)
    references reconstruction_privacy_screening(workspace_id, screening_id);

create function tg_point_map_requires_privacy_screening() returns trigger
language plpgsql as $fn$
declare
  capture_ref uuid;
begin
  if new.kind <> 'point_map' then
    return new;
  end if;
  select c.capture_id into capture_ref
    from capture c
   where c.workspace_id = new.workspace_id
     and c.blob_sha256 = new.source_blob_sha256
     and c.deleted_at is null;
  if capture_ref is null
     or new.privacy_screening_id is null
     or not privacy_screening_allows_capture(
       new.workspace_id, capture_ref, new.privacy_screening_id) then
    raise exception 'point-map production requires a current eligible privacy screening'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_point_map_requires_privacy_screening
  before insert on artifact
  for each row execute function tg_point_map_requires_privacy_screening();

alter table reconstruction_scene_job
  add column privacy_admission_id uuid,
  add column privacy_admission_digest bytea
    check (privacy_admission_digest is null or octet_length(privacy_admission_digest) = 32),
  add foreign key (workspace_id, privacy_admission_id)
    references reconstruction_privacy_admission(workspace_id, admission_id);

do $$
declare
  old_constraint text;
begin
  select conname
    into old_constraint
    from pg_constraint
   where conrelid = 'reconstruction_scene_job'::regclass
     and contype = 'u'
     and pg_get_constraintdef(oid) =
       'UNIQUE (workspace_id, scene_id, selection_policy_digest, build_input_digest)';
  if old_constraint is not null then
    execute format(
      'alter table reconstruction_scene_job drop constraint %I',
      old_constraint);
  end if;
end $$;

alter table reconstruction_scene_job
  add unique (
    workspace_id,
    scene_id,
    selection_policy_digest,
    build_input_digest,
    privacy_admission_digest);

create function privacy_admission_allows_job(p_workspace uuid, p_job uuid)
returns boolean
language sql volatile as $fn$
  select exists (
    select 1
      from reconstruction_scene_job j
      join reconstruction_privacy_admission a
        on a.workspace_id = j.workspace_id
       and a.admission_id = j.privacy_admission_id
     where j.workspace_id = p_workspace
       and j.job_id = p_job
       and a.scene_id = j.scene_id
       and a.member_digest = j.member_digest
       and a.admission_digest = j.privacy_admission_digest
       and a.eligibility_state = 'eligible'
       and (a.valid_until is null or a.valid_until > clock_timestamp())
       and (select count(*) from reconstruction_scene_job_member jm
             where jm.workspace_id = j.workspace_id and jm.job_id = j.job_id)
           =
           (select count(*) from reconstruction_privacy_admission_member am
             where am.workspace_id = a.workspace_id and am.admission_id = a.admission_id)
       and not exists (
         select 1
           from reconstruction_scene_job_member jm
           left join reconstruction_privacy_admission_member am
             on am.workspace_id = jm.workspace_id
            and am.admission_id = a.admission_id
            and am.capture_id = jm.capture_id
            and am.ordinal = jm.ordinal
          where jm.workspace_id = j.workspace_id
            and jm.job_id = j.job_id
            and am.capture_id is null)
       and not exists (
         select 1
           from reconstruction_privacy_admission_member am
           left join reconstruction_scene_job_member jm
             on jm.workspace_id = am.workspace_id
            and jm.job_id = j.job_id
            and jm.capture_id = am.capture_id
            and jm.ordinal = am.ordinal
          where am.workspace_id = a.workspace_id
            and am.admission_id = a.admission_id
            and jm.capture_id is null)
       and not exists (
         select 1 from reconstruction_privacy_admission_member am
          where am.workspace_id = a.workspace_id
            and am.admission_id = a.admission_id
            and not privacy_screening_allows_capture(
              am.workspace_id, am.capture_id, am.screening_id)));
$fn$;

create function tg_reconstruction_scene_job_privacy_valid() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if new.privacy_admission_id is null or new.privacy_admission_digest is null
     or not exists (
       select 1 from reconstruction_privacy_admission a
        where a.workspace_id = new.workspace_id
          and a.admission_id = new.privacy_admission_id
          and a.scene_id = new.scene_id
          and a.member_digest = new.member_digest
          and a.admission_digest = new.privacy_admission_digest
          and a.eligibility_state = 'eligible'
          and (a.valid_until is null or a.valid_until > clock_timestamp())) then
    raise exception 'scene queueing requires an eligible exact-set privacy admission'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_reconstruction_scene_job_privacy_valid
  before insert on reconstruction_scene_job
  for each row execute function tg_reconstruction_scene_job_privacy_valid();

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
  if tombstone_blocks_capture(new.workspace_id, new.capture_id) then
    perform tombstone_refuse('reconstruction_scene_job_member');
  end if;
  if not exists (
    select 1
      from reconstruction_scene_job j
      join reconstruction_privacy_admission_member am
        on am.workspace_id = j.workspace_id
       and am.admission_id = j.privacy_admission_id
       and am.capture_id = new.capture_id
       and am.ordinal = new.ordinal
     where j.workspace_id = new.workspace_id
       and j.job_id = new.job_id) then
    raise exception 'scene job member is absent from its exact privacy admission'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create or replace function tg_reconstruction_scene_job_inputs_immutable() returns trigger
language plpgsql as $fn$
begin
  if new.job_id is distinct from old.job_id
     or new.workspace_id is distinct from old.workspace_id
     or new.scene_id is distinct from old.scene_id
     or new.member_digest is distinct from old.member_digest
     or new.selection_policy is distinct from old.selection_policy
     or new.selection_policy_digest is distinct from old.selection_policy_digest
     or new.build_inputs is distinct from old.build_inputs
     or new.build_input_digest is distinct from old.build_input_digest
     or new.privacy_admission_id is distinct from old.privacy_admission_id
     or new.privacy_admission_digest is distinct from old.privacy_admission_digest
     or new.created_at is distinct from old.created_at then
    raise exception 'reconstruction scene job inputs are immutable'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

comment on table capture_reconstruction_authorization is
  'Why exact photograph bytes may be used for one declared reconstruction purpose.';
comment on table reconstruction_privacy_screening is
  'Fail-closed per-capture screening receipt bound to authorization and exact source bytes.';
comment on table reconstruction_privacy_admission is
  'Versioned privacy decision over one exact ordered scene set.';
comment on column artifact.privacy_screening_id is
  'Exact eligible receipt that permitted point-map bytes to be produced.';
comment on column reconstruction_scene_job.privacy_admission_id is
  'Exact-set privacy admission that permitted this immutable build question.';

commit;
