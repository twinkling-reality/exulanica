-- A personal photograph reaches a GPU trainer only under a right that names where the bytes go,
-- and the artefact that run produces is bound to that right at the moment it is published.
--
-- Migration 0073 answers WHICH MODEL MAY RECEIVE A PERSON'S OWN PHOTOGRAPH AND WHERE THE BYTES GO,
-- and it is rechecked at the instant of every read, so a withdrawal is either seen or the read is
-- refused until the check finishes. That works because showing bytes to a model is a TRANSIENT act.
-- Training is not. You cannot un-train weights: a Gaussian splat trained on somebody's photographs
-- of their home IS a reconstruction of their home, and it persists after the photographs are
-- withdrawn, deleted or re-screened. A right that named only its INPUTS would repeat, in a new
-- place, the failure exulanica/ingest/privacy.py records for privacy version 1: a rule whose only
-- available answer is the one that loses the collection. So this right names its inputs AND the
-- artefacts the run produced, and withdrawal acts on both.
--
-- WHAT THIS IS NOT. Migration 0039 creates training_use_consent, keyed
-- (subject_id, package_id, licensee, sequence). That is a person-subject consenting to their
-- likeness travelling to a named counterparty inside an exported dataset package, and it gates
-- world_package_export's exulanica-wmp-training-1.1 profile. It says nothing about whether a
-- trainer here may read the account holder's own photographs, and nothing here says anything about
-- a licensee. Two different questions that share one English word, so this one is spelled
-- scene_training throughout and never plain 'training'.
begin;
select pg_advisory_xact_lock(119622309);

-- ------------------------------------------------------------------------------------------------
-- The right
-- ------------------------------------------------------------------------------------------------
-- Shaped on personal_model_right (0073). Each DIFFERENCE from it is justified where it appears;
-- everything unremarked is 0073's decision kept deliberately rather than by inheritance.
create table scene_training_right (
  workspace_id uuid not null,
  right_id uuid not null,
  -- ONE RIGHT PER PHOTOGRAPH, not one per scene, which is the first difference from what a
  -- set-shaped operation invites. A training run consumes a set, but the personal authority in
  -- capture_reconstruction_authorization is per capture, so a set-shaped right would have to name
  -- N authorities and would go stale the moment the scene gained a member. Per capture also makes
  -- withdrawal mean what a person means by it: take THAT photograph out, not revoke the scene.
  capture_id uuid not null,
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  -- The personal authority under which the account holder granted this right. The right lapses
  -- with it, and the grantor must be the actor that authority names.
  authorization_id uuid not null,
  operation text not null check(operation='scene_training'),
  -- NO MODEL IDENTITY, which is the second difference from 0073. A model right names the model
  -- because the bytes are handed to one named thing that gives an answer back. A training run
  -- hands them to a trainer that produces an artefact, and it is the ARTEFACT that outlives the
  -- grant, so that is what scene_training_artifact below binds. Naming a trainer revision here
  -- would look like the same protection and would protect nothing after the run.
  --
  -- 'local-process', an https origin the egress allowlist could declare, or a rented host named as
  -- one. THE LOCALHOST FORMS 0073 ACCEPTS ARE REFUSED HERE, and that is the third difference and
  -- the one most worth reading. The reference compute for this work is a rented GPU VM reached
  -- over a tunnel, so http://localhost:PORT is exactly how such a machine presents itself, and a
  -- right recording that spelling would state that the bytes never left this machine when they
  -- did. A genuinely local run is 'local-process'. Anything reached at a loopback address over a
  -- tunnel must name the host it actually reaches, and a provider that will not give a stable
  -- instance name is a provider this right cannot honestly describe.
  destination text not null check(
    length(destination)<=270
    and (destination='local-process'
      or (destination ~ '^https://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+(:[1-9][0-9]{0,4})?$'
          and destination !~ '\.([0-9]+|0x[0-9a-f]*)(:[0-9]+)?$')
      or destination ~ '^rented-host:[a-z][a-z0-9_-]{0,31}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')
    and destination !~ '^https://[^/]*:443$'
    and coalesce(substring(destination from ':([0-9]+)$')::integer,1) between 1 and 65535),
  -- The control characters named explicitly rather than as [[:cntrl:]], whose meaning follows the
  -- database's character classification; Python refuses exactly this set.
  purpose text not null check(
    purpose=btrim(purpose) and length(purpose) between 1 and 2000
    and purpose !~ '[\x01-\x1f\x7f-\x9f]'),
  granted_by uuid not null,
  granted_at timestamptz not null,
  valid_until timestamptz not null,
  withdrawn_at timestamptz,
  withdrawn_by uuid,
  receipt_record jsonb not null check(jsonb_typeof(receipt_record)='object'),
  receipt_canonical bytea not null,
  receipt_sha256 bytea not null check(octet_length(receipt_sha256)=32),
  primary key(workspace_id,right_id),
  unique(workspace_id,receipt_sha256),
  foreign key(workspace_id,capture_id) references capture(workspace_id,capture_id),
  foreign key(workspace_id,authorization_id)
    references capture_reconstruction_authorization(workspace_id,authorization_id),
  check(valid_until>granted_at),
  check((withdrawn_at is null)=(withdrawn_by is null)),
  check(withdrawn_at is null or withdrawn_at>=granted_at),
  check(receipt_record->>'profile'='exulanica.scene-training-right/v1'),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
create index scene_training_right_capture_idx
  on scene_training_right(workspace_id,capture_id,destination);

alter table scene_training_right enable row level security;
alter table scene_training_right force row level security;
create policy ws_isolation on scene_training_right
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- A grant or withdrawal serializes with screening decisions in its workspace and cannot commit
-- while a final read check holds the asset read lock, so a withdrawal is either seen by that check
-- or refused until it has finished. Same pair 0073 uses, for the same reason.
create trigger aa_privacy_currency_lock before insert or update on scene_training_right
for each row execute function tg_privacy_currency_lock();
create trigger aaa_asset_read_mutation before insert or update or delete on scene_training_right
for each row execute function tg_asset_read_mutation();

-- ------------------------------------------------------------------------------------------------
-- What the run produced
-- ------------------------------------------------------------------------------------------------
-- THE RIGHT CANNOT NAME THE ARTEFACT AT GRANT TIME, because the artefact does not exist until the
-- run finishes. It is named here instead, at publication, in the same transaction as the insert the
-- gate below already allowed. So "which photographs was this artefact trained from" is answered
-- from a record rather than from a memory, and a withdrawal has something to act on.
--
-- Written BY A TRIGGER, never by a caller. A GPU runner invoked from a script is exactly the future
-- caller migration 0037 had in mind when it said a rule that lives only in Python is a rule a
-- caller can route around, and a binding a caller must remember to write is a binding that will be
-- missing on the run that matters.
create table scene_training_artifact (
  workspace_id uuid not null,
  artifact_id uuid not null,
  capture_id uuid not null,
  right_id uuid not null,
  bound_at timestamptz not null,
  primary key(workspace_id,artifact_id,capture_id),
  foreign key(artifact_id) references artifact(artifact_id),
  foreign key(workspace_id,capture_id) references capture(workspace_id,capture_id),
  foreign key(workspace_id,right_id) references scene_training_right(workspace_id,right_id)
);
create index scene_training_artifact_right_idx
  on scene_training_artifact(workspace_id,right_id);
alter table scene_training_artifact enable row level security;
alter table scene_training_artifact force row level security;
create policy ws_isolation on scene_training_artifact
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- ------------------------------------------------------------------------------------------------
-- Receipts and immutability
-- ------------------------------------------------------------------------------------------------
create function tg_scene_training_right_receipt() returns trigger language plpgsql as $fn$
declare authority capture_reconstruction_authorization%rowtype; expected jsonb;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into authority from capture_reconstruction_authorization a
    where a.workspace_id=new.workspace_id and a.authorization_id=new.authorization_id;
  if not found or authority.corpus_class<>'personal'
    or authority.capture_id<>new.capture_id
    or authority.source_sha256<>new.source_sha256
    or authority.authorized_by<>new.granted_by
    or authority.authorized_at>new.granted_at
    or (authority.valid_until is not null and authority.valid_until<=new.granted_at)
  then
    raise exception 'a training right is granted by the account holder whose personal authority over these exact bytes was current when it was granted'
      using errcode='23514';
  end if;
  if not exists(select 1 from capture c
      where c.workspace_id=new.workspace_id and c.capture_id=new.capture_id
        and c.blob_sha256=new.source_sha256 and c.deleted_at is null
        and not tombstone_blocks_capture(new.workspace_id,new.capture_id)) then
    raise exception 'a training right requires the exact live source photograph'
      using errcode='23514';
  end if;
  if new.granted_at>clock_timestamp() or new.withdrawn_at is not null then
    raise exception 'a training right is granted now or earlier and is never recorded already withdrawn'
      using errcode='23514';
  end if;
  -- personal_model_right_instant is reused rather than restated: one spelling of an instant in a
  -- receipt, defined once in 0073. A second copy here would be a second source of truth for a
  -- format, with nothing holding the two in step.
  expected:=jsonb_build_object(
    'profile','exulanica.scene-training-right/v1',
    'capture_id',new.capture_id,
    'source_sha256',encode(new.source_sha256,'hex'),
    'authorization',jsonb_build_object(
      'authorization_id',new.authorization_id,
      'evidence_sha256',encode(authority.evidence_digest,'hex')),
    'operation',new.operation,
    'destination',new.destination,
    'purpose',new.purpose,
    'granted_by',new.granted_by,
    'granted_at',personal_model_right_instant(new.granted_at),
    'valid_until',personal_model_right_instant(new.valid_until));
  if new.receipt_record is distinct from expected then
    raise exception 'training right receipt disagrees with the right it records'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_scene_training_right_receipt
before insert on scene_training_right
for each row execute function tg_scene_training_right_receipt();

-- Withdrawn, never deleted, and withdrawn once. Nothing else about a right changes after it is
-- granted: a different destination or term is a different right.
create function tg_scene_training_right_immutable() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    raise exception 'training rights are withdrawn, never deleted' using errcode='23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  if (to_jsonb(new)-'withdrawn_at'-'withdrawn_by')
       is distinct from (to_jsonb(old)-'withdrawn_at'-'withdrawn_by')
    or old.withdrawn_at is not null
    or new.withdrawn_at is null
    or new.withdrawn_at>clock_timestamp()
  then
    raise exception 'a training right changes only by one final withdrawal' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_scene_training_right_immutable
before update or delete on scene_training_right
for each row execute function tg_scene_training_right_immutable();

-- A binding is a fact about a publication that already happened. It is never rewritten and never
-- deleted, because the withdrawal path reads it to learn what a withdrawal has to reach, and a
-- binding that can be removed is a reconstruction that can be quietly orphaned from its right.
create trigger tg_scene_training_artifact_append_only
before update or delete on scene_training_artifact
for each row execute function tg_reconstruction_privacy_append_only();

-- ------------------------------------------------------------------------------------------------
-- The predicates
-- ------------------------------------------------------------------------------------------------
-- Evaluated under the final read check, which holds the global asset read lock, so like the 0041
-- asset_* family and 0073's own predicates they take an explicit instant and acquire no training,
-- privacy or purge lock.

-- Whether training over this capture needs a right at all. DENY BY DEFAULT, and unknown is
-- required. Only a capture whose authority is synthetic or benchmark, over bytes that no other kind
-- of authority in this workspace has ever claimed, is exempt. 0073 asks this of a screening; a
-- training run presents no per-capture screening at publication, so this asks it of the capture.
create function scene_training_right_required(p_workspace uuid,p_capture uuid)
returns boolean language sql stable as $fn$
  select coalesce(not (
    p_workspace=current_workspace()
    and exists(select 1 from capture_reconstruction_authorization a
      where a.workspace_id=p_workspace and a.capture_id=p_capture
        and a.corpus_class in ('synthetic','benchmark'))
    and not exists(select 1 from capture c
      join capture_reconstruction_authorization a
        on a.workspace_id=c.workspace_id and a.source_sha256=c.blob_sha256
      where c.workspace_id=p_workspace and c.capture_id=p_capture
        and a.corpus_class not in ('synthetic','benchmark'))), true);
$fn$;

-- Whether one exact right still permits scene_training of this capture at this destination at this
-- instant. Every term is compared; nothing is inferred from a newer grant or a nearby destination.
create function scene_training_right_allows(
  p_workspace uuid,p_right uuid,p_capture uuid,p_destination text,p_at timestamptz)
returns boolean language sql stable as $fn$
  select coalesce(p_workspace=current_workspace(),false) and exists(
    select 1 from scene_training_right r
    join capture c on c.workspace_id=r.workspace_id and c.capture_id=r.capture_id
    join capture_reconstruction_authorization a
      on a.workspace_id=r.workspace_id and a.authorization_id=r.authorization_id
    where r.workspace_id=p_workspace and r.right_id=p_right and r.capture_id=p_capture
      and r.operation='scene_training'
      and r.destination=p_destination
      and r.withdrawn_at is null
      and r.granted_at<=p_at and r.valid_until>p_at
      and r.source_sha256=c.blob_sha256 and c.deleted_at is null
      and not asset_tombstone_capture(p_workspace,p_capture,p_at)
      and a.capture_id=r.capture_id and a.source_sha256=r.source_sha256
      and a.corpus_class='personal' and a.authorized_by=r.granted_by
      and a.authorized_at<=p_at and (a.valid_until is null or a.valid_until>p_at));
$fn$;

-- The newest right that permits exactly this training at this instant, or null.
create function scene_training_right_current(
  p_workspace uuid,p_capture uuid,p_destination text,p_at timestamptz)
returns uuid language sql stable as $fn$
  select r.right_id from scene_training_right r
  where r.workspace_id=p_workspace and r.capture_id=p_capture
    and scene_training_right_allows(p_workspace,r.right_id,p_capture,p_destination,p_at)
  order by r.granted_at desc,r.right_id desc limit 1;
$fn$;

-- Where a job says it will send the bytes. A job declares what it will do in its own immutable
-- build_inputs, so the gate reads the job rather than carrying a list of destinations beside it.
create function scene_training_destination(p_build_inputs jsonb)
returns text language sql immutable as $fn$
  select nullif(p_build_inputs->>'scene_training_destination','');
$fn$;

-- Why this training job may not run over this capture, or null when it may. A REASON RATHER THAN A
-- BOOLEAN, because one message reached by several causes is a category and the reader picks
-- whichever member of it they saw last. Every branch here names the term that failed.
create function scene_training_job_refusal(
  p_workspace uuid,p_job uuid,p_capture uuid,p_at timestamptz)
returns text language plpgsql stable as $fn$
declare v_inputs jsonb; v_destination text;
begin
  select j.build_inputs into v_inputs from reconstruction_scene_job j
    where j.workspace_id=p_workspace and j.job_id=p_job;
  if v_inputs is null or not (v_inputs ? 'splat_training') then
    return null;  -- not a training run; pose recovery is governed by the 0029 admission alone
  end if;
  if not scene_training_right_required(p_workspace,p_capture) then
    return null;
  end if;
  v_destination:=scene_training_destination(v_inputs);
  if v_destination is null then
    return 'a training run over a personal photograph must state where the bytes go, in '
      || 'build_inputs.scene_training_destination';
  end if;
  if scene_training_right_current(p_workspace,p_capture,v_destination,p_at) is not null then
    return null;
  end if;
  if exists(select 1 from scene_training_right r where r.workspace_id=p_workspace
      and r.capture_id=p_capture and r.destination=v_destination
      and r.withdrawn_at is not null) then
    return format('the training right for %s over this photograph was withdrawn',v_destination);
  end if;
  if exists(select 1 from scene_training_right r where r.workspace_id=p_workspace
      and r.capture_id=p_capture and r.destination=v_destination
      and r.valid_until<=p_at) then
    return format('the training right for %s over this photograph has expired',v_destination);
  end if;
  if exists(select 1 from scene_training_right r where r.workspace_id=p_workspace
      and r.capture_id=p_capture and r.destination=v_destination) then
    return format('the training right for %s is not current: its personal authority lapsed, the '
      || 'photograph changed, or its term has not begun',v_destination);
  end if;
  if exists(select 1 from scene_training_right r where r.workspace_id=p_workspace
      and r.capture_id=p_capture) then
    return format('this photograph''s training rights name another destination, not %s',
      v_destination);
  end if;
  return format('no training right lets this photograph be trained at %s',v_destination);
end $fn$;

-- ------------------------------------------------------------------------------------------------
-- The gate, in the two places a run can be stopped
-- ------------------------------------------------------------------------------------------------
-- CAN THIS RULE LIVE ONLY IN PYTHON? No, for the reason migration 0037 gives about the masked
-- derivative: a GPU runner invoked from a script is exactly the future caller that routes around a
-- Python check. It cannot route around these, because it still has to write rows to publish
-- anything, and both writes are where the two disagreeing facts actually meet.
--
-- The member trigger stops a run being QUEUED. It is on the member rather than the job because
-- members are inserted after the job row, so a job-level trigger has no members to check yet.
create function tg_scene_training_member_right() returns trigger language plpgsql as $fn$
declare v_reason text;
begin
  v_reason:=scene_training_job_refusal(
    new.workspace_id,new.job_id,new.capture_id,clock_timestamp());
  if v_reason is not null then
    raise exception 'this scene may not be trained: %',v_reason using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_scene_training_member_right
before insert on reconstruction_scene_job_member
for each row execute function tg_scene_training_member_right();

-- And the publication trigger stops a run PUBLISHING. This is the one a mid-run withdrawal hits.
-- A training run takes a long time, so the check that matters is the one at the moment the run
-- produces something, not the one at the moment it was asked for: a right that was current when
-- the job was queued says nothing about whether it is current an hour later.
--
-- IT REFUSES MORE THAN THE MINIMUM, DELIBERATELY. The condition is that the artefact names a scene
-- some job declared it would train, not that the artefact's own kind is one of the splat kinds. A
-- list of kinds is a claim about the pipeline sitting where nothing compares the two, and it would
-- already be wrong: an unmerged branch adds gaussian_splat_master as a fourth. This catches the
-- pose artefact of a trained scene too, which is derived from the same photographs and which
-- nobody has argued should escape. Under-covering is the failure that matters here.
--
-- AND A LIST OF KINDS WOULD HAVE BEEN WRONG ABOUT THE WEIGHTS TOO, which is the measured reason
-- rather than the anticipated one. One run publishes three artifacts in scene_reconstruction.py
-- _train_splat, and only scene_splat_delivery sits inside the `if quality.accepted:` branch.
-- scene_splat_evaluation is appended BEFORE it, so A RUN THE QUALITY GATE REJECTS PUBLISHES NO
-- WEIGHTS AND STILL PUBLISHES RENDERED VIEWS OF THE PLACE, plus, whenever rectification changes
-- the pixels, the frames it was trained on under training/undistorted/images. Those frames are the
-- MASKED derivative wherever a mask applies, traced through _manifest's apply_masked_sources and
-- the staged source directory it hands to _train_splat, so a person who never consented is already
-- hidden in them. They are still the account holder's own photographs of their own place, and they
-- outlive a run that produced nothing anybody wanted.
create function tg_scene_training_publication_right() returns trigger language plpgsql as $fn$
declare v_reason text; v_capture uuid; v_job uuid;
begin
  if new.scene_id is null then
    return new;
  end if;
  for v_job,v_capture in
    select m.job_id,m.capture_id from reconstruction_scene_job j
    join reconstruction_scene_job_member m
      on m.workspace_id=j.workspace_id and m.job_id=j.job_id
    where j.workspace_id=new.workspace_id and j.scene_id=new.scene_id
      and j.build_inputs ? 'splat_training'
    order by m.job_id,m.ordinal
  loop
    v_reason:=scene_training_job_refusal(
      new.workspace_id,v_job,v_capture,clock_timestamp());
    if v_reason is not null then
      raise exception 'this trained artefact may not be published: %',v_reason
        using errcode='23514';
    end if;
  end loop;
  return new;
end $fn$;
create trigger tg_scene_training_publication_right
before insert on artifact
for each row execute function tg_scene_training_publication_right();

-- The binding, written from the artefact rather than by whoever produced it.
create function tg_scene_training_artifact_binds() returns trigger language plpgsql as $fn$
begin
  if new.scene_id is null then
    return new;
  end if;
  insert into scene_training_artifact (
    workspace_id,artifact_id,capture_id,right_id,bound_at)
  select distinct on (m.capture_id)
    new.workspace_id,new.artifact_id,m.capture_id,
    scene_training_right_current(new.workspace_id,m.capture_id,
      scene_training_destination(j.build_inputs),clock_timestamp()),
    clock_timestamp()
  from reconstruction_scene_job j
  join reconstruction_scene_job_member m
    on m.workspace_id=j.workspace_id and m.job_id=j.job_id
  where j.workspace_id=new.workspace_id and j.scene_id=new.scene_id
    and j.build_inputs ? 'splat_training'
    and scene_training_right_required(new.workspace_id,m.capture_id)
    and scene_training_right_current(new.workspace_id,m.capture_id,
      scene_training_destination(j.build_inputs),clock_timestamp()) is not null
  order by m.capture_id,m.job_id
  on conflict do nothing;
  return new;
end $fn$;
create trigger tg_scene_training_artifact_binds
after insert on artifact
for each row execute function tg_scene_training_artifact_binds();

-- ------------------------------------------------------------------------------------------------
-- What a withdrawal reaches
-- ------------------------------------------------------------------------------------------------
-- THE DECISION, stated here because the brief that asked for this right said that choosing without
-- saying which is not choosing. Withdrawal REFUSES EVERY FURTHER READ OF THE ARTEFACT AT ONCE, and
-- the binding above records exactly which artefacts a destruction has to reach.
--
-- Why not "recorded as impossible": it would be false. exulanica/deletion/worker.py destroys bytes
-- through an authorised purger and then asks the store to confirm they are gone, so this system CAN
-- destroy a trained artefact and saying otherwise would be a claim not produced from the data.
--
-- Why the refusal is not merely a weaker substitute for destruction: destruction here cannot be
-- synchronous. The purger is a separate process and it correctly SKIPS bytes another live capture
-- still holds. So between a withdrawal committing and a purge completing there is an interval, of
-- unbounded length and sometimes of infinite length, in which the artefact still exists. The
-- refusal is what covers that interval, and any design that enqueues destruction without it has a
-- window in which a withdrawn reconstruction is still readable.
--
-- WHAT THIS MIGRATION DOES NOT DO, said plainly rather than left to be discovered: it does not
-- enqueue destruction. That reaches into the tombstone and purge-queue invariants of 0013 and 0015
-- and is its own piece of work. This predicate and the binding table are what that work will read.
-- The boundary is deliberate and not unfinished: A CORRECT HALF, NAMED, BEATS A PLAUSIBLE WHOLE.
create function scene_training_artifact_withdrawn(
  p_workspace uuid,p_artifact uuid,p_at timestamptz)
returns boolean language sql stable as $fn$
  select coalesce(p_workspace=current_workspace(),false) and exists(
    select 1 from scene_training_artifact b
    where b.workspace_id=p_workspace and b.artifact_id=p_artifact
      and not scene_training_right_allows(
        p_workspace,b.right_id,b.capture_id,
        (select r.destination from scene_training_right r
          where r.workspace_id=b.workspace_id and r.right_id=b.right_id),
        p_at));
$fn$;

-- Every photograph a given artefact was trained from, with whether its right still stands. This is
-- the question the brief said must be answerable from a record rather than from a memory.
create function scene_training_artifact_sources(p_workspace uuid,p_artifact uuid)
returns table(capture_id uuid,right_id uuid,destination text,withdrawn_at timestamptz,
  current boolean)
language sql stable as $fn$
  select b.capture_id,b.right_id,r.destination,r.withdrawn_at,
    scene_training_right_allows(
      p_workspace,b.right_id,b.capture_id,r.destination,clock_timestamp())
  from scene_training_artifact b
  join scene_training_right r
    on r.workspace_id=b.workspace_id and r.right_id=b.right_id
  where b.workspace_id=p_workspace and b.artifact_id=p_artifact
  order by b.capture_id;
$fn$;

-- A WITHDRAWAL CANCELS THE RUN, and this is what stops a photograph reaching a GPU after its
-- owner has taken the right away. Without it, a job queued while the right stood is claimed later
-- and its bytes are staged and handed to the trainer; the publication trigger would refuse what
-- came back, but the photographs would already have gone. The shape is migration 0030's, which
-- cancels a scene job when a confirmed person withdraws, with its own failure_class so a reader is
-- never asked which of two causes a shared message meant. It reaches 'running' as well as 'queued',
-- so the worker's own cancellation check ends a run in progress rather than letting it finish work
-- nothing would accept.
create function tg_scene_training_right_withdrawn() returns trigger language plpgsql as $fn$
begin
  if new.withdrawn_at is null then
    return new;
  end if;
  update reconstruction_scene_job j
     set status='cancelled', claim_token=null, claimed_by=null, lease_expires_at=null,
         completed_at=coalesce(j.completed_at,new.withdrawn_at), updated_at=clock_timestamp(),
         failure_class='training_right_withdrawn',
         failure_message='a training right over one of this run''s photographs was withdrawn'
   where j.workspace_id=new.workspace_id and j.status in ('queued','running','failed')
     and j.build_inputs ? 'splat_training'
     and exists (select 1 from reconstruction_scene_job_member m
                  where m.workspace_id=j.workspace_id and m.job_id=j.job_id
                    and m.capture_id=new.capture_id);
  return new;
end $fn$;
create trigger tg_scene_training_right_withdrawn
after update on scene_training_right
for each row execute function tg_scene_training_right_withdrawn();

comment on table scene_training_right is
  'Which of an account holder''s photographs a trainer may read, and where the bytes go.';
comment on table scene_training_artifact is
  'Which photographs a trained artefact was produced from, bound at publication by trigger.';

commit;
