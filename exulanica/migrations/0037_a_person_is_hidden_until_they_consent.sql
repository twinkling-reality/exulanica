-- 0037_a_person_is_hidden_until_they_consent.sql
-- Replace the yes-or-no person gate with a confirmed region list and a consent state per person.
--
-- 0029 asked one question of a reviewer: are there any sensitive person regions? It then made the
-- only useful answer "no", three times over. `reconstruction_privacy_screening` carries
-- `check (jsonb_array_length(mask_artifacts) = 0)`, an eligible receipt must carry
-- `jsonb_array_length(sensitive_regions) = 0`, and `privacy_screening_allows_capture` repeats both
-- conditions. Under those rules an eligible receipt that NAMES a person is not merely unusual, it
-- is unrepresentable, so a reviewer looking at a photograph containing somebody had no answer
-- available except to block the photograph or to say nobody was there. MEASURED 2026-09-05: the
-- retained bowl review said "no visible people or sensitive person regions" over 51 frames
-- containing the arms, hands and clothing of diners at the edge, and it said so because the schema
-- offered no other eligible answer. This migration is what makes the honest answer expressible.
--
-- What replaces it: a region is hidden until a receipt says otherwise. `person_region` is the
-- append-only record of what a detector proposed and what a human confirmed, keyed on the
-- evidence rather than on a row id so a detector re-run cannot resurrect a deleted false positive.
-- `person_presentation_consent` is the append-only record of three separate decisions, presence,
-- naming and likeness, plus a reversible temporary hide. Nothing anywhere defaults to granted.
--
-- What this migration deliberately does NOT do: it does not narrow 0030's person-scoped
-- withdrawal, which still removes a whole photograph from reconstruction when an entity is
-- tombstoned. Allowing a masked rebuild to proceed after a withdrawal is a separate and
-- security-critical change.

begin;

select pg_advisory_xact_lock(119622309);

-- A person, as this system is allowed to know one: an identity a human asserted, carrying no
-- descriptor and no template. `entity_id` is set only when somebody has actually been named, so
-- an unnamed person in a photograph is representable, which the two retained collections need.
create table person_subject (
  subject_id     uuid primary key,
  workspace_id   uuid not null,
  entity_id      uuid references entity(entity_id),
  created_by     uuid not null,
  created_at     timestamptz not null default now(),
  unique (workspace_id, subject_id)
);
create index person_subject_ws_idx on person_subject (workspace_id);
create index person_subject_entity_idx on person_subject (entity_id) where entity_id is not null;

-- One edit to one region, and the whole history of a region is the rows sharing its key.
--
-- `region_key` is `occurrence_identity_key` over the outline's bounding box, bucketed on a 16 by
-- 16 grid, which is the same key the vision stage already gives a located person. That is what
-- makes a reviewer's work survive a detector version: a re-run that trims a box lands in the same
-- cell, finds the confirmation already recorded against it, and does not ask again.
create table person_region (
  region_edit_id  uuid primary key,
  workspace_id    uuid not null,
  capture_id      uuid not null,
  source_sha256   bytea not null check (octet_length(source_sha256) = 32),
  region_key      bytea not null check (octet_length(region_key) = 32),
  sequence        integer not null check (sequence >= 0),
  action          text not null check (action in ('detected', 'confirmed', 'added', 'deleted')),
  shape           text not null check (shape in ('box', 'polygon')),
  -- Which visible trace of a person this region covers, from the observation schema's closed
  -- vocabulary. Null for a region a human drew, who is under no obligation to classify it. It is
  -- here because a reviewer looking at an outline on a neutral field cannot otherwise tell a hand
  -- at the frame edge from a false positive, and the partial traces are the whole point.
  part            text check (part in ('full_body', 'partial_body', 'head', 'torso', 'arm',
                                       'hand', 'leg', 'foot', 'reflection', 'on_screen')),
  silhouette      jsonb not null check (jsonb_typeof(silhouette) = 'object'),
  subject_id      uuid,
  detector_id     text,
  confidence      text check (confidence in ('low', 'medium', 'high')),
  confirmed_by    uuid,
  recorded_at     timestamptz not null default now(),
  region_record   jsonb not null check (jsonb_typeof(region_record) = 'object'),
  region_canonical bytea not null,
  region_digest   bytea not null check (octet_length(region_digest) = 32),
  unique (workspace_id, capture_id, region_key, sequence),
  foreign key (workspace_id, capture_id) references capture(workspace_id, capture_id),
  foreign key (workspace_id, subject_id) references person_subject(workspace_id, subject_id),
  check (digest(region_canonical, 'sha256') = region_digest),
  check (convert_from(region_canonical, 'UTF8')::jsonb = region_record),
  -- A human edit names the human who made it; a detector proposal names the detector. Neither
  -- may be anonymous, because "somebody confirmed this" with no actor is not a receipt.
  check (
    (action = 'detected' and detector_id is not null and confirmed_by is null)
    or (action in ('confirmed', 'added', 'deleted') and confirmed_by is not null))
);
create index person_region_capture_idx on person_region (workspace_id, capture_id);
-- Supports `person_region_current`, which is read once per photograph on the ingest path. The
-- view is a `distinct on (workspace_id, capture_id, region_key) ... order by ... sequence desc`,
-- and without an index in exactly that order every read sorts the whole table. That is invisible
-- on an empty table and is a corpus-sized problem later, which is the wrong moment to find it.
create index person_region_live_idx
  on person_region (workspace_id, capture_id, region_key, sequence desc);
create index person_region_subject_idx on person_region (workspace_id, subject_id)
  where subject_id is not null;

-- One consent transition. Three scopes plus the reversible hide, and every row names an actor,
-- a time and a scope. `actor_role` carries 'subject' so that a consent set by the person in the
-- photograph is distinguishable from one set by the account holder on their behalf; no route
-- writes 'subject' yet, and the column exists so that adding one later is not a schema change.
create table person_presentation_consent (
  consent_id      uuid primary key,
  workspace_id    uuid not null,
  subject_id      uuid not null,
  region_key      bytea check (region_key is null or octet_length(region_key) = 32),
  consent_scope   text not null
    check (consent_scope in ('presence', 'naming', 'likeness', 'temporary_hide')),
  decision        text not null check (decision in ('granted', 'revoked', 'withdrawn')),
  sequence        integer not null check (sequence >= 0),
  actor_id        uuid not null,
  actor_role      text not null check (actor_role in ('owner', 'subject', 'operator')),
  effective_at    timestamptz not null default now(),
  valid_until     timestamptz,
  consent_record  jsonb not null check (jsonb_typeof(consent_record) = 'object'),
  consent_canonical bytea not null,
  consent_digest  bytea not null check (octet_length(consent_digest) = 32),
  unique (workspace_id, subject_id, consent_scope, region_key, sequence),
  foreign key (workspace_id, subject_id) references person_subject(workspace_id, subject_id),
  check (valid_until is null or valid_until > effective_at),
  check (digest(consent_canonical, 'sha256') = consent_digest),
  check (convert_from(consent_canonical, 'UTF8')::jsonb = consent_record),
  -- Withdrawal is not a scope somebody can grant back. It is recorded against likeness because
  -- that is the consent whose removal must reach the pixels.
  check (decision <> 'withdrawn' or consent_scope = 'likeness')
);
create index person_consent_subject_idx
  on person_presentation_consent (workspace_id, subject_id, consent_scope);

do $$
declare
  t text;
begin
  foreach t in array array[
    'person_subject',
    'person_region',
    'person_presentation_consent'] loop
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

-- The live state of one region: the last edit wins, and a deleted region is gone.
create view person_region_current as
select distinct on (r.workspace_id, r.capture_id, r.region_key)
       r.workspace_id, r.capture_id, r.source_sha256, r.region_key, r.action, r.shape, r.part,
       r.silhouette, r.subject_id, r.detector_id, r.confidence, r.confirmed_by, r.region_digest
  from person_region r
 order by r.workspace_id, r.capture_id, r.region_key, r.sequence desc;

-- Is one consent currently held? A region-scoped receipt overrides a subject-wide one, and an
-- expired receipt stops holding, which is how the reversible hide reverses on an append-only
-- table that permits no UPDATE.
create function person_consent_is_granted(
  p_workspace uuid, p_subject uuid, p_region bytea, p_scope text)
returns boolean
language sql stable as $fn$
  select coalesce((
    select c.decision = 'granted'
      from person_presentation_consent c
     where c.workspace_id = p_workspace
       and c.subject_id = p_subject
       and c.consent_scope = p_scope
       and (c.region_key is null or c.region_key = p_region)
       and c.effective_at <= clock_timestamp()
       and (c.valid_until is null or c.valid_until > clock_timestamp())
     order by (c.region_key is not null) desc, c.sequence desc
     limit 1), false);
$fn$;

create function person_subject_is_withdrawn(p_workspace uuid, p_subject uuid)
returns boolean
language sql stable as $fn$
  select exists (
    select 1 from person_presentation_consent c
     where c.workspace_id = p_workspace
       and c.subject_id = p_subject
       and c.decision = 'withdrawn');
$fn$;

-- The whole of default deny, in one place. A region with no subject has nobody who could have
-- consented, so it masks. `temporary_hide` is deliberately absent: that person consented to their
-- likeness and their geometry is theirs, so hiding them is a viewer-side decision and not a
-- reason to rebuild the world.
create function person_region_is_masked(p_workspace uuid, p_subject uuid, p_region bytea)
returns boolean
language sql stable as $fn$
  select p_subject is null
      or person_subject_is_withdrawn(p_workspace, p_subject)
      or not person_consent_is_granted(p_workspace, p_subject, p_region, 'likeness');
$fn$;

create function capture_requires_masking(p_workspace uuid, p_capture uuid)
returns boolean
language sql stable as $fn$
  select exists (
    select 1 from person_region_current r
     where r.workspace_id = p_workspace
       and r.capture_id = p_capture
       and r.action <> 'deleted'
       and person_region_is_masked(r.workspace_id, r.subject_id, r.region_key));
$fn$;

-- Make the honest screening answer representable. Each of these three said, in a different way,
-- that an eligible receipt names nobody.
do $$
declare
  doomed text;
begin
  for doomed in
    select conname from pg_constraint
     where conrelid = 'reconstruction_privacy_screening'::regclass
       and contype = 'c'
       and (pg_get_constraintdef(oid) like '%mask_artifacts%'
         or (pg_get_constraintdef(oid) like '%sensitive_regions%'
             and pg_get_constraintdef(oid) like '%eligibility_state%'))
  loop
    execute format(
      'alter table reconstruction_privacy_screening drop constraint %I', doomed);
  end loop;
end $$;

-- An eligible receipt may now name regions. What it may not do is be eligible while blocked, or
-- be blocked while saying nothing about why.
alter table reconstruction_privacy_screening
  add constraint a_blocked_screening_says_why check (
    (eligibility_state = 'eligible' and jsonb_array_length(blocking_reasons) = 0)
    or (eligibility_state in ('blocked', 'failed') and jsonb_array_length(blocking_reasons) > 0));

-- The bytes a stage actually read, as distinct from the capture's own bytes. Null means the
-- original, which is the truth for every artifact produced before this migration.
alter table artifact
  add column read_source_sha256 bytea
    check (read_source_sha256 is null or octet_length(read_source_sha256) = 32);

comment on column artifact.read_source_sha256 is
  'The exact bytes this stage read. Null means the capture original. A point map over a capture '
  'that requires masking must name the masked derivative here, which is what makes "mask before, '
  'not only after" a database rule rather than a convention in Python.';

-- A third screening method, and the loop it exists to break.
--
-- Finding the people in a photograph means showing the photograph to something that can find
-- them, and this deployment's detector is a hosted model. So observing needs an authorization.
-- But the region list a reviewer confirms is what an eligible screening is MADE of, and a
-- photograph containing somebody who has not consented can never produce one: an empty list
-- asserts nobody is there, and a list naming them is blocked. Vision reads the original, so
-- masking cannot break the loop either. Under version 2 as first written, a collection like the
-- retained bowl photographs could never be looked at at all.
--
-- `person_detection_only` is the narrow way out. It says: an actor authorized sending these exact
-- bytes to a detector FOR THE PURPOSE of finding the people in them, and that authorization does
-- not make the capture eligible for anything else. It is recorded as `blocked`, because blocked
-- is what it is for geometry, and the reason says so. The split is enforced by there being two
-- predicates rather than one flag: `privacy_screening_allows_capture` still gates geometry and
-- does not admit this method, and `privacy_screening_allows_observation` below admits it.
alter table reconstruction_privacy_screening
  drop constraint if exists reconstruction_privacy_screening_screening_method_check;

do $$
declare
  doomed text;
begin
  for doomed in
    select conname from pg_constraint
     where conrelid = 'reconstruction_privacy_screening'::regclass
       and contype = 'c'
       and pg_get_constraintdef(oid) like '%synthetic_exemption%'
  loop
    execute format(
      'alter table reconstruction_privacy_screening drop constraint %I', doomed);
  end loop;
end $$;

alter table reconstruction_privacy_screening
  add constraint a_screening_method_says_what_was_done check (
    (screening_method = 'synthetic_exemption'
      and model_id is null and model_revision is null
      and not human_review_required and reviewed_by is null
      and jsonb_array_length(sensitive_regions) = 0
      and eligibility_state = 'eligible')
    or
    (screening_method = 'human_review'
      and model_id is null and model_revision is null
      and human_review_required and reviewed_by is not null)
    or
    -- Nobody reviewed the image, and somebody authorized looking at it. Both halves are recorded:
    -- `human_review_required` is false because no review happened, and `reviewed_by` is the actor
    -- who authorized the detection, so the receipt never reads as a review that did not occur.
    (screening_method = 'person_detection_only'
      and model_id is null and model_revision is null
      and not human_review_required and reviewed_by is not null
      and eligibility_state = 'blocked'));

-- The policy a receipt has to have been written under to still count.
--
-- Every screening already stores `policy_version` and `policy_params_digest`, and until now
-- nothing ever compared them: a receipt written under version 1 kept passing after the policy
-- moved to version 2, so bumping the policy invalidated nothing and the invalidation existed only
-- in prose. That is the shape of bug this schema exists to prevent, recorded in a digest and
-- never checked.
--
-- A function rather than a literal inside the resolver, so there is one place to move it and one
-- place for a test to compare against `exulanica.ingest.privacy.PRIVACY_POLICY_VERSION`.
create function current_privacy_policy() returns text
language sql immutable as $fn$ select 'exulanica.reconstruction-privacy/v2' $fn$;

create or replace function privacy_screening_allows_capture(
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
       -- Written under the policy in force. A receipt recorded when "is anybody visible?" was
       -- the whole question does not carry forward to a policy whose answer is a region list
       -- with a consent state per person, and the two retained collections are exactly that
       -- case: reviewed under version 1, and not yet re-screened.
       and s.policy_version = current_privacy_policy()
       and (s.valid_until is null or s.valid_until > clock_timestamp())
       and (a.valid_until is null or a.valid_until > clock_timestamp())
       and c.deleted_at is null
       and not tombstone_blocks_capture(p_workspace, p_capture));
$fn$;

-- May this photograph be shown to a detector? A separate question from whether it may become
-- geometry, and deliberately a separate function: one predicate with a flag would eventually be
-- called with the wrong flag, and the failure would be a photograph reconstructed on the strength
-- of a receipt that only ever permitted looking at it.
--
-- An eligible receipt permits observation too, because anything admitted for geometry has already
-- cleared the higher bar. A `person_detection_only` receipt permits observation and nothing else.
create function privacy_screening_allows_observation(
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
       and s.policy_version = current_privacy_policy()
       and (s.eligibility_state = 'eligible'
            or s.screening_method = 'person_detection_only')
       and (s.valid_until is null or s.valid_until > clock_timestamp())
       and (a.valid_until is null or a.valid_until > clock_timestamp())
       and c.deleted_at is null
       and not tombstone_blocks_capture(p_workspace, p_capture));
$fn$;

-- "Mask before, not only after", enforced where Python cannot be trusted to have done it. A point
-- map is the first artifact that turns a photograph into geometry, so it is the right place to
-- refuse: if this capture contains anybody who has not consented to their likeness, the point map
-- must declare that it read the masked derivative, and the digest it names must be a real masked
-- source for this capture.
create function tg_geometry_reads_the_masked_derivative() returns trigger
language plpgsql as $fn$
declare
  capture_ref uuid;
begin
  if new.kind <> 'point_map' then
    return new;
  end if;
  select ca.capture_id into capture_ref
    from capture ca
   where ca.workspace_id = new.workspace_id
     and ca.blob_sha256 = new.source_blob_sha256
   limit 1;
  if capture_ref is null then
    return new;
  end if;
  if not capture_requires_masking(new.workspace_id, capture_ref) then
    return new;
  end if;
  if new.read_source_sha256 is null then
    raise exception
      'capture % contains a person who has not consented to their likeness, so a point map '
      'must read the masked derivative and name it in read_source_sha256', capture_ref
      using errcode = '23514';
  end if;
  if not exists (
    select 1 from artifact m
     where m.workspace_id = new.workspace_id
       and m.kind = 'masked_source'
       and m.source_blob_sha256 = new.source_blob_sha256
       and m.content_sha256 = new.read_source_sha256
       and m.purged_at is null)
  then
    raise exception
      'the bytes this point map names are not a masked source derivative of capture %',
      capture_ref
      using errcode = '23514';
  end if;
  return new;
end $fn$;

create trigger tg_geometry_reads_the_masked_derivative
  before insert on artifact
  for each row execute function tg_geometry_reads_the_masked_derivative();

commit;
