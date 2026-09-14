-- Typed, append-only user action requests and exact transition replay bindings.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_event drop constraint world_society_event_event_kind_check;
alter table world_society_event add constraint world_society_event_event_kind_check
  check(event_kind in ('departed','arrived','need_changed','social_contact',
    'goal_selected','route_progressed','action_completed','replanned','blocked',
    'observed','communicated','decision_applied','user_action_requested'));

create table world_society_action_request (
  workspace_id uuid not null,
  society_id uuid not null,
  action_seq bigint not null check(action_seq>0),
  request_id uuid not null,
  requested_by uuid not null,
  subject_id uuid not null,
  target_id text not null check(length(target_id) between 1 and 1000),
  base_tick bigint not null check(base_tick>=0),
  input_seq bigint not null check(input_seq>0),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,action_seq),
  unique(workspace_id,society_id,request_id),
  unique(workspace_id,society_id,base_tick,subject_id),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  foreign key(workspace_id,society_id,input_seq)
    references world_society_input(workspace_id,society_id,input_seq),
  check(document->>'profile' is not distinct from 'exulanica.society-action-request/v1'),
  check(document->>'request_id' is not distinct from request_id::text),
  check(document->>'requested_by' is not distinct from requested_by::text),
  check(document->>'subject_id' is not distinct from subject_id::text),
  check(document->>'base_tick' is not distinct from base_tick::text),
  check(document->>'input_seq' is not distinct from input_seq::text),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check(document->'intent'->>'target_id' is not distinct from target_id),
  check((document->'intent'->>'kind' in ('go_to','perform')) is true),
  check((document->>'base_state_sha256' ~ '^[0-9a-f]{64}$') is true),
  check((document->>'input_sha256' ~ '^[0-9a-f]{64}$') is true),
  check(jsonb_typeof(document->'intent') is not distinct from 'object'),
  check(jsonb_typeof(document->'target') is not distinct from 'object')
);

create table world_society_transition_action (
  workspace_id uuid not null,
  society_id uuid not null,
  tick bigint not null check(tick>0),
  action_seq bigint not null check(action_seq>0),
  disposition text not null
    check(disposition in ('applied','stale','unavailable','rejected','superseded')),
  event_id uuid not null,
  primary key(workspace_id,society_id,action_seq),
  foreign key(workspace_id,society_id,tick)
    references world_society_transition(workspace_id,society_id,tick),
  foreign key(workspace_id,society_id,action_seq)
    references world_society_action_request(workspace_id,society_id,action_seq),
  foreign key(workspace_id,society_id,event_id)
    references world_society_event(workspace_id,society_id,event_id)
);

create function tg_world_society_action_request_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
  target jsonb; person jsonb; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3') then
    raise exception 'user actions require a scoped v2 or v3 society' using errcode='23514';
  end if;
  select * into latest_input from world_society_input
    where workspace_id=new.workspace_id and society_id=new.society_id
    order by input_seq desc limit 1;
  select value into target from jsonb_array_elements(latest_input.document->'targets')
    where value->>'target_id'=new.target_id;
  select value into person from jsonb_array_elements(held.state->'inhabitants')
    where value->>'id'=new.subject_id::text;
  select coalesce(max(action_seq),0) into latest_seq from world_society_action_request
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if new.action_seq<>latest_seq+1
    or new.document->>'branch_id' is distinct from held.version_id::text
    or new.base_tick<>held.current_tick
    or new.document->>'base_state_sha256' is distinct from held.state_sha256
    or new.input_seq is distinct from latest_input.input_seq
    or new.document->>'input_sha256' is distinct from latest_input.document_sha256
    or held.state->>'input_seq' is distinct from new.input_seq::text
    or held.state->>'input_sha256' is distinct from latest_input.document_sha256
    or latest_input.document->>'availability' is distinct from 'available'
    or latest_input.document->'navigation'->>'unavailable_reason' is not null
    or target is null or target is distinct from new.document->'target'
    or target->'enabled' is distinct from 'true'::jsonb
    or person is null
    or not (person->'goal'='null'::jsonb or person->'action'->>'status' in ('completed','blocked'))
  then
    raise exception 'society action is not bound to the current scoped state and target'
      using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_action_request_binding
  before insert on world_society_action_request
  for each row execute function tg_world_society_action_request_binding();

create function tg_world_society_transition_action_binding() returns trigger language plpgsql as $fn$
declare request world_society_action_request%rowtype;
  transition world_society_transition%rowtype; event world_society_event%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select * into request from world_society_action_request
    where workspace_id=new.workspace_id and society_id=new.society_id
      and action_seq=new.action_seq;
  select * into transition from world_society_transition
    where workspace_id=new.workspace_id and society_id=new.society_id and tick=new.tick;
  if not found or request.action_seq is null
    or new.tick<>request.base_tick+1
    or request.document->>'base_state_sha256' is distinct from transition.previous_state_sha256
    or request.input_seq<>transition.from_input_seq
  then
    raise exception 'society action consumption does not match its transition' using errcode='23514';
  end if;
  select * into event from world_society_event
    where workspace_id=new.workspace_id and society_id=new.society_id
      and event_id=new.event_id;
  if not found or event.tick<>new.tick or event.event_kind<>'user_action_requested'
    or event.subject_id<>request.subject_id
    or event.document->>'action_request_id' is distinct from request.request_id::text
    or event.document->>'action_request_sha256' is distinct from request.document_sha256
    or event.document->>'disposition' is distinct from new.disposition
  then
    raise exception 'society action consumption requires its exact simulation event'
      using errcode='23514';
  end if;
  if new.disposition='applied' and request.input_seq<>transition.to_input_seq then
    raise exception 'an action cannot apply after its simulation input changed' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_transition_action_binding
  before insert on world_society_transition_action
  for each row execute function tg_world_society_transition_action_binding();

do $$ declare t text; begin
  foreach t in array array['world_society_action_request','world_society_transition_action'] loop
    execute format('create trigger %I before update or delete on %I '
      'for each row execute function tg_world_society_event_append_only()',t||'_append_only',t);
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t);
  end loop;
end $$;

commit;
