-- Training permissions have package, counterparty and term boundaries, not presentation states.
-- The scope decision is recorded in docs/person-presentation-consent.md before this migration.
begin;
select pg_advisory_xact_lock(119622309);

create table training_use_consent (
  receipt_id uuid primary key,
  workspace_id uuid not null,
  subject_id text not null check (length(subject_id) > 0),
  package_id text not null check (length(package_id) > 0),
  licensee text not null check (length(licensee) > 0),
  sequence bigint not null check (sequence >= 0),
  decision text not null check (decision in ('granted', 'revoked', 'withdrawn')),
  terms_digest bytea not null check (octet_length(terms_digest) = 32),
  receipt_record jsonb not null check (jsonb_typeof(receipt_record) = 'object'),
  receipt_canonical bytea not null,
  receipt_digest bytea not null check (octet_length(receipt_digest) = 32),
  actor uuid not null,
  decided_at timestamptz not null,
  unique (workspace_id, package_id, licensee, subject_id, sequence),
  check (digest(receipt_canonical, 'sha256') = receipt_digest),
  check (convert_from(receipt_canonical, 'UTF8')::jsonb = receipt_record),
  check ((receipt_record->>'subject_id') is not distinct from subject_id),
  check ((receipt_record->'terms'->>'package_id') is not distinct from package_id),
  check ((receipt_record->'terms'->>'licensee') is not distinct from licensee),
  check ((receipt_record->>'decision') is not distinct from decision),
  check ((receipt_record->>'sequence')::bigint is not distinct from sequence),
  check ((receipt_record->>'actor') is not distinct from actor::text),
  check ((receipt_record->>'decided_at')::timestamptz is not distinct from decided_at)
);
-- Every receipt insertion shares the export lock, including direct SQL writers.
create function tg_training_use_consent_lock() returns trigger language plpgsql as $fn$
begin
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text || ':' || new.package_id, 0));
  return new;
end $fn$;
create trigger tg_training_use_consent_lock before insert on training_use_consent
  for each row execute function tg_training_use_consent_lock();
create index training_use_consent_relationship_idx
  on training_use_consent (workspace_id, package_id, licensee, subject_id, sequence desc);
create trigger tg_training_use_consent_append_only
  before update or delete on training_use_consent
  for each row execute function tg_reconstruction_privacy_append_only();
alter table training_use_consent enable row level security;
alter table training_use_consent force row level security;
create policy ws_isolation on training_use_consent
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

-- Old exports keep their profile and their original signed bytes. Licensing metadata exists only
-- on the explicitly selected dataset profile; a memory export cannot silently become training.
alter table world_package_export drop constraint world_package_export_profile_version_check;
alter table world_package_export add constraint world_package_export_profile_version_check
  check (profile_version in ('exulanica-wmp-1.0', 'exulanica-wmp-training-1.1'));
alter table world_package_export add column training_terms jsonb;
alter table world_package_export add constraint training_profile_requires_terms
  check ((profile_version = 'exulanica-wmp-training-1.1') = (training_terms is not null));
alter table world_package_export add constraint training_terms_are_an_object
  check (training_terms is null or jsonb_typeof(training_terms) = 'object');
-- Exports take the exclusive counterpart before reading source authority through publication.
-- Source mutations share their workspace lock, so ordinary ingest and concurrent withdrawals
-- can coexist. Only dataset publication briefly serializes source changes in its workspace.
create function tg_training_source_mutation_lock() returns trigger language plpgsql as $fn$
declare
  old_workspace uuid;
  new_workspace uuid;
  target_workspace uuid;
begin
  if tg_op <> 'INSERT' then old_workspace := old.workspace_id; end if;
  if tg_op <> 'DELETE' then new_workspace := new.workspace_id; end if;
  for target_workspace in
    select distinct value from unnest(array[old_workspace, new_workspace]) value
     where value is not null order by value
  loop
    perform pg_advisory_xact_lock_shared(hashtextextended('training-source:' || target_workspace::text, 0));
  end loop;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $fn$;

do $$
declare
  target_table text;
begin
  foreach target_table in array array[
    'tombstone', 'person_region', 'person_presentation_consent', 'person_subject', 'capture',
    'artifact', 'reconstruction_scene', 'reconstruction_scene_member',
    'reconstruction_scene_job', 'reconstruction_scene_job_member',
    'reconstruction_privacy_screening']
  loop
    execute format(
      'create trigger tg_training_source_mutation_lock before insert or update or delete on %I '
      'for each row execute function tg_training_source_mutation_lock()', target_table);
  end loop;
end $$;

commit;
