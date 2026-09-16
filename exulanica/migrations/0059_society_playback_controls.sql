-- Explicit opt-in playback, durable leases and immutable scheduling receipts.
begin;
select pg_advisory_xact_lock(119622309);

create table world_society_control (
  workspace_id uuid not null,
  society_id uuid not null,
  revision bigint not null check(revision>0),
  mode text not null check(mode in ('paused','playing')),
  speed integer not null check(speed in (1,2,4)),
  base_tick_interval_ms integer not null
    check(base_tick_interval_ms between 1000 and 60000 and base_tick_interval_ms%4=0),
  next_due_at timestamptz,
  reason text,
  changed_by uuid not null,
  lease_token uuid,
  claimed_at timestamptz,
  lease_expires_at timestamptz,
  claim_attempts integer not null default 0 check(claim_attempts between 0 and 3),
  last_event_seq bigint not null default 0 check(last_event_seq>=0),
  primary key(workspace_id,society_id),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  check((mode='playing')=(next_due_at is not null)),
  check((lease_token is null and claimed_at is null and lease_expires_at is null)
    or (lease_token is not null and claimed_at is not null and lease_expires_at is not null
      and mode='playing'))
);
create index world_society_control_due on world_society_control(workspace_id,next_due_at,society_id)
  where mode='playing';

create table world_society_control_event (
  workspace_id uuid not null,
  society_id uuid not null,
  event_seq bigint not null check(event_seq>0),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  primary key(workspace_id,society_id,event_seq),
  foreign key(workspace_id,society_id) references world_society_control(workspace_id,society_id),
  check(document->>'profile' is not distinct from 'exulanica.society-control-event/v1'),
  check(document->>'event_seq' is not distinct from event_seq::text),
  check(document->>'society_id' is not distinct from society_id::text),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check((document->>'kind' in ('configured','claimed','reclaimed','advanced','manual_step',
    'paused_due_to_error','lease_recovery_exhausted')) is true)
);

create index world_society_control_last_advance on world_society_control_event
  (workspace_id,society_id,event_seq desc) where document->>'kind'='advanced';

create function tg_society_control_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op='DELETE' then
    raise exception 'society control history cannot be deleted' using errcode='23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  if tg_op='UPDATE' and (new.workspace_id<>old.workspace_id or new.society_id<>old.society_id
    or new.revision not between old.revision and old.revision+1
    or new.last_event_seq not between old.last_event_seq and old.last_event_seq+1) then
    raise exception 'invalid society control identity or revision change' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger society_control_guard before insert or update or delete on world_society_control
  for each row execute function tg_society_control_guard();

create function tg_society_control_event_guard() returns trigger language plpgsql as $fn$
declare expected bigint; expected_branch uuid; expected_revision bigint;
begin
  if tg_op<>'INSERT' then
    raise exception 'society scheduling receipts are append-only' using errcode='23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select last_event_seq+1 into expected from world_society_control
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if expected is null or new.event_seq<>expected then
    raise exception 'society scheduling receipt sequence must be contiguous' using errcode='23514';
  end if;
  select s.version_id,c.revision into expected_branch,expected_revision
    from world_society_control c join world_society s using(workspace_id,society_id)
    where c.workspace_id=new.workspace_id and c.society_id=new.society_id;
  if new.document->>'branch_id' is distinct from expected_branch::text
    or new.document->>'revision' is distinct from expected_revision::text then
    raise exception 'society scheduling receipt branch or revision mismatch' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger society_control_event_guard before insert or update or delete
  on world_society_control_event for each row execute function tg_society_control_event_guard();

alter table world_society_control enable row level security;
alter table world_society_control force row level security;
create policy ws_isolation on world_society_control
  using(workspace_id=current_workspace()) with check(workspace_id=current_workspace());
alter table world_society_control_event enable row level security;
alter table world_society_control_event force row level security;
create policy ws_isolation on world_society_control_event
  using(workspace_id=current_workspace()) with check(workspace_id=current_workspace());
commit;
