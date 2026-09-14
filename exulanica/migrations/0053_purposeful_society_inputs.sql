-- Versioned inputs and transition receipts for opt-in purposeful society.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_engine_version_check;
alter table world_society add constraint world_society_engine_version_check
  check(engine_version in ('exulanica-society/v1','exulanica-society/v2'));
alter table world_society_event drop constraint world_society_event_event_kind_check;
alter table world_society_event add constraint world_society_event_event_kind_check
  check(event_kind in ('departed','arrived','need_changed','social_contact',
    'goal_selected','route_progressed','action_completed','replanned','blocked'));

-- v2 can record several same-kind decisions for one subject in a tick. Keep the
-- original uniqueness rule for legacy events and use explicit ordering for v2.
do $$ declare held record; begin
  for held in select conname from pg_constraint
    where conrelid='world_society_event'::regclass and contype='u'
  loop
    execute format('alter table world_society_event drop constraint %I',held.conname);
  end loop;
end $$;
create unique index world_society_event_legacy_unique
  on world_society_event(workspace_id,society_id,tick,subject_id,event_kind)
  where (document->>'profile') is distinct from 'exulanica-society/v2';
create unique index world_society_event_v2_order_unique
  on world_society_event(workspace_id,society_id,tick,((document->>'order')::bigint))
  where document->>'profile'='exulanica-society/v2';

create table world_society_input (
  workspace_id uuid not null,
  society_id uuid not null,
  input_seq bigint not null check(input_seq>0),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,input_seq),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  check(document->>'profile' is not distinct from 'exulanica.society-input/v1'),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check(document->>'input_seq' is not distinct from input_seq::text)
);

create table world_society_transition (
  workspace_id uuid not null,
  society_id uuid not null,
  tick bigint not null check(tick>0),
  from_input_seq bigint not null check(from_input_seq>0),
  to_input_seq bigint not null check(to_input_seq>=from_input_seq),
  previous_state_sha256 text not null check(previous_state_sha256 ~ '^[0-9a-f]{64}$'),
  state_sha256 text not null check(state_sha256 ~ '^[0-9a-f]{64}$'),
  event_ids jsonb not null check(jsonb_typeof(event_ids)='array'),
  events_sha256 text not null check(events_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,tick),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  foreign key(workspace_id,society_id,from_input_seq)
    references world_society_input(workspace_id,society_id,input_seq),
  foreign key(workspace_id,society_id,to_input_seq)
    references world_society_input(workspace_id,society_id,input_seq)
);

create function tg_world_society_input_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version<>'exulanica-society/v2' then
    raise exception 'versioned inputs require a scoped v2 society' using errcode='23514';
  end if;
  if new.document->>'world_id' is distinct from held.world_id or
     new.document->>'version_id' is distinct from held.version_id::text then
    raise exception 'society input belongs to another world version' using errcode='23514';
  end if;
  select coalesce(max(input_seq),0) into latest_seq from world_society_input
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if new.input_seq<>latest_seq+1 then
    raise exception 'society input sequence must be contiguous' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_input_binding before insert on world_society_input
  for each row execute function tg_world_society_input_binding();

create function tg_world_society_v2_event_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if not found then
    raise exception 'society event requires a scoped society' using errcode='23514';
  end if;
  if held.engine_version='exulanica-society/v2' then
    if new.document->>'profile' is distinct from held.engine_version or
       new.document->>'branch_id' is distinct from held.version_id::text or
       new.document->>'subject_id' is distinct from new.subject_id::text or
       new.document->>'tick' is distinct from new.tick::text or
       new.document->'synthetic' is distinct from 'true'::jsonb or
       coalesce(new.document->>'order','') !~ '^[0-9]+$' or
       jsonb_typeof(new.document->'summary') is distinct from 'string' then
      raise exception 'v2 event identity and order must match its document' using errcode='23514';
    end if;
  elsif new.document->>'profile'='exulanica-society/v2' then
    raise exception 'v1 society cannot emit v2 events' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_v2_event_binding before insert on world_society_event
  for each row execute function tg_world_society_v2_event_binding();

-- These histories have the same normal append-only boundary as society events.
-- Current authorization remains a read/materialization concern, not a stored grant.
create trigger tg_world_society_input_append_only before update or delete on world_society_input
  for each row execute function tg_world_society_event_append_only();
create trigger tg_world_society_transition_append_only
  before update or delete on world_society_transition
  for each row execute function tg_world_society_event_append_only();

do $$ declare t text; begin
  foreach t in array array['world_society_input','world_society_transition'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t);
  end loop;
end $$;

-- Reviewed character/object assets were added after the generic read-lock trigger list.
-- Serialize registry changes with source/asset authorization and materialization.
create trigger aaa_asset_read_mutation before insert or update or delete on world_reviewed_asset
  for each row execute function tg_asset_read_mutation();

commit;
