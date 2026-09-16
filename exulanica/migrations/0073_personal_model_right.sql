-- A personal photograph reaches a model only under a right that names the model and where the
-- bytes go. A screening receipt answers whether these bytes may be looked at or built from; this
-- answers which model may receive them and at which destination. Both must hold, neither implies
-- the other, and a capture with no right is refused. Licensed environment sources already carry
-- a model_processing operation right (0048); personal captures carried nothing equivalent.
begin;
select pg_advisory_xact_lock(119622309);

create table personal_model_right (
  workspace_id uuid not null,
  right_id uuid not null,
  capture_id uuid not null,
  source_sha256 bytea not null check(octet_length(source_sha256)=32),
  -- The personal authority under which the account holder granted this right. The right lapses
  -- with it, and the grantor must be the actor that authority names.
  authorization_id uuid not null,
  operation text not null check(operation='model_processing'),
  -- The model as the manifest states it. Hosted providers expose no per-model revision, so a
  -- hosted right carries none; a local checkpoint is always pinned to a full commit.
  model_provider text not null check(model_provider ~ '^[a-z][a-z0-9_]{0,62}$'),
  model_role text not null check(model_role ~ '^[a-z][a-z0-9_]{0,62}$'),
  model_id text not null check(model_id ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$'),
  model_revision text check(model_revision is null or model_revision ~ '^[0-9a-f]{40}$'),
  -- 'local-process', or the exact origin the egress allowlist would have to declare. Default ports
  -- are omitted, as exulanica.models.egress.Origin writes them, so one origin has one spelling.
  destination text not null check(
    destination='local-process'
    or (destination ~ '^https://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+(:[0-9]{1,5})?$'
        and destination !~ ':443$' and destination !~ '\.[0-9]+(:[0-9]{1,5})?$')
    or (destination ~ '^https?://localhost(:[0-9]{1,5})?$'
        and destination !~ '^https://localhost:443$' and destination !~ '^http://localhost:80$')),
  purpose text not null check(
    purpose=btrim(purpose) and length(purpose) between 1 and 2000 and purpose !~ '[[:cntrl:]]'),
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
  -- A local checkpoint that is not pinned is not an identity a right can name.
  check(model_provider<>'local' or model_revision is not null),
  -- Bytes that stay in this process can only reach a checkpoint loaded in this process.
  check(destination<>'local-process' or model_provider='local'),
  check(receipt_record->>'profile'='exulanica.personal-model-right/v1'),
  check(receipt_canonical=convert_to(privacy_canonical(receipt_record),'UTF8')),
  check(receipt_sha256=digest(receipt_canonical,'sha256'))
);
create index personal_model_right_model_idx
  on personal_model_right(workspace_id,capture_id,model_provider,model_role,model_id);

alter table personal_model_right enable row level security;
alter table personal_model_right force row level security;
create policy ws_isolation on personal_model_right
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- A grant or withdrawal serializes with screening decisions in its workspace, and cannot commit
-- while a final read check holds the asset read lock, so a withdrawal is either seen by that
-- check or refused until it has finished.
create trigger aa_privacy_currency_lock before insert or update on personal_model_right
for each row execute function tg_privacy_currency_lock();
create trigger aaa_asset_read_mutation before insert or update or delete on personal_model_right
for each row execute function tg_asset_read_mutation();

-- One spelling of an instant inside a receipt: UTC, microseconds, a trailing Z.
create function personal_model_right_instant(p_at timestamptz) returns text
language sql stable as $fn$
  select to_char(p_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
$fn$;

create function tg_personal_model_right_receipt() returns trigger language plpgsql as $fn$
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
    raise exception 'a model right is granted by the account holder whose personal authority over these exact bytes was current when it was granted'
      using errcode='23514';
  end if;
  if not exists(select 1 from capture c
      where c.workspace_id=new.workspace_id and c.capture_id=new.capture_id
        and c.blob_sha256=new.source_sha256 and c.deleted_at is null
        and not tombstone_blocks_capture(new.workspace_id,new.capture_id)) then
    raise exception 'a model right requires the exact live source photograph'
      using errcode='23514';
  end if;
  if new.granted_at>clock_timestamp() or new.withdrawn_at is not null then
    raise exception 'a model right is granted now or earlier and is never recorded already withdrawn'
      using errcode='23514';
  end if;
  expected:=jsonb_build_object(
    'profile','exulanica.personal-model-right/v1',
    'capture_id',new.capture_id,
    'source_sha256',encode(new.source_sha256,'hex'),
    'authorization',jsonb_build_object(
      'authorization_id',new.authorization_id,
      'evidence_sha256',encode(authority.evidence_digest,'hex')),
    'operation',new.operation,
    'model',jsonb_build_object(
      'provider',new.model_provider,'role',new.model_role,
      'model_id',new.model_id,'revision',new.model_revision),
    'destination',new.destination,
    'purpose',new.purpose,
    'granted_by',new.granted_by,
    'granted_at',personal_model_right_instant(new.granted_at),
    'valid_until',personal_model_right_instant(new.valid_until));
  if new.receipt_record is distinct from expected then
    raise exception 'model right receipt disagrees with the right it records'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_personal_model_right_receipt
before insert on personal_model_right
for each row execute function tg_personal_model_right_receipt();

-- Withdrawn, never deleted, and withdrawn once. Nothing else about a right changes after it is
-- granted: a different model, destination or term is a different right.
create function tg_personal_model_right_immutable() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    raise exception 'model rights are withdrawn, never deleted' using errcode='23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  if (to_jsonb(new)-'withdrawn_at'-'withdrawn_by')
       is distinct from (to_jsonb(old)-'withdrawn_at'-'withdrawn_by')
    or old.withdrawn_at is not null
    or new.withdrawn_at is null
    or new.withdrawn_at>clock_timestamp()
  then
    raise exception 'a model right changes only by one final withdrawal' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_personal_model_right_immutable
before update or delete on personal_model_right
for each row execute function tg_personal_model_right_immutable();

-- The predicates below are evaluated under the final read check, which holds the global asset read
-- lock, so like the 0041 asset_* family they take an explicit instant and acquire no training,
-- privacy or purge lock. A reader that waited on one while holding the read lock would make every
-- mutation in the database fail for as long as it waited.

-- privacy_screening_allows_observation, restated without the privacy currency lock: the read-time
-- screening predicate for an eligible receipt, or the same detection-only branch 0040 defines.
create function asset_observation_allows(
  p_workspace uuid,p_capture uuid,p_screening uuid,p_at timestamptz)
returns boolean language sql stable as $fn$
  select asset_screening_allows(p_workspace,p_capture,p_screening,p_at) or exists(
    select 1 from reconstruction_privacy_screening s
    join capture_reconstruction_authorization a
      on a.workspace_id=s.workspace_id and a.authorization_id=s.authorization_id
    join capture c on c.workspace_id=s.workspace_id and c.capture_id=s.capture_id
    where s.workspace_id=p_workspace and p_workspace=current_workspace()
      and s.capture_id=p_capture and s.screening_id=p_screening
      and s.screening_method='person_detection_only'
      and s.source_sha256=c.blob_sha256 and a.capture_id=s.capture_id
      and a.source_sha256=s.source_sha256 and s.authorization_scope=a.authorization_scope
      and s.policy_version=current_privacy_policy()
      and (s.valid_until is null or s.valid_until>p_at)
      and (a.valid_until is null or a.valid_until>p_at)
      and c.deleted_at is null and not asset_tombstone_capture(p_workspace,p_capture,p_at));
$fn$;

-- Whether handing these bytes to any model needs a personal model right. Deny by default: only a
-- screening issued under a synthetic or benchmark authority, over a capture that no other kind of
-- authority has ever claimed, is exempt. A capture any account holder has authorized as personal
-- stays personal whichever receipt a caller presents.
create function personal_model_right_required(p_workspace uuid,p_capture uuid,p_screening uuid)
returns boolean language sql stable as $fn$
  select coalesce(not (
    p_workspace=current_workspace()
    and exists(select 1 from reconstruction_privacy_screening s
      join capture_reconstruction_authorization a
        on a.workspace_id=s.workspace_id and a.authorization_id=s.authorization_id
      where s.workspace_id=p_workspace and s.capture_id=p_capture and s.screening_id=p_screening
        and a.capture_id=p_capture and a.corpus_class in ('synthetic','benchmark'))
    and not exists(select 1 from capture_reconstruction_authorization a
      where a.workspace_id=p_workspace and a.capture_id=p_capture
        and a.corpus_class not in ('synthetic','benchmark'))), true);
$fn$;

-- Whether one exact right still permits model_processing of this capture by this model at this
-- destination at this instant. Every term is compared; nothing is inferred from a prefix, a role
-- alone or a newer grant.
create function personal_model_right_allows(
  p_workspace uuid,p_right uuid,p_capture uuid,p_provider text,p_role text,p_model_id text,
  p_revision text,p_destination text,p_at timestamptz)
returns boolean language sql stable as $fn$
  select coalesce(p_workspace=current_workspace(),false) and exists(
    select 1 from personal_model_right r
    join capture c on c.workspace_id=r.workspace_id and c.capture_id=r.capture_id
    join capture_reconstruction_authorization a
      on a.workspace_id=r.workspace_id and a.authorization_id=r.authorization_id
    where r.workspace_id=p_workspace and r.right_id=p_right and r.capture_id=p_capture
      and r.operation='model_processing'
      and r.model_provider=p_provider and r.model_role=p_role and r.model_id=p_model_id
      and r.model_revision is not distinct from p_revision
      and r.destination=p_destination
      and r.withdrawn_at is null
      and r.granted_at<=p_at and r.valid_until>p_at
      and r.source_sha256=c.blob_sha256 and c.deleted_at is null
      and not asset_tombstone_capture(p_workspace,p_capture,p_at)
      and a.capture_id=r.capture_id and a.source_sha256=r.source_sha256
      and a.corpus_class='personal' and a.authorized_by=r.granted_by
      and a.authorized_at<=p_at and (a.valid_until is null or a.valid_until>p_at));
$fn$;

-- The newest right that permits exactly this hand-over at this instant, or null.
create function personal_model_right_current(
  p_workspace uuid,p_capture uuid,p_provider text,p_role text,p_model_id text,
  p_revision text,p_destination text,p_at timestamptz)
returns uuid language sql stable as $fn$
  select r.right_id from personal_model_right r
  where r.workspace_id=p_workspace and r.capture_id=p_capture
    and r.model_provider=p_provider and r.model_role=p_role and r.model_id=p_model_id
    and personal_model_right_allows(p_workspace,r.right_id,p_capture,p_provider,p_role,
      p_model_id,p_revision,p_destination,p_at)
  order by r.granted_at desc,r.right_id desc limit 1;
$fn$;

commit;
