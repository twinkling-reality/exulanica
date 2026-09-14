-- Recorded social decisions, with explicit reservations and replay consumption.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_engine_version_check;
alter table world_society add constraint world_society_engine_version_check
  check(engine_version in ('exulanica-society/v1','exulanica-society/v2','exulanica-society/v3'));
alter table world_society_event drop constraint world_society_event_event_kind_check;
alter table world_society_event add constraint world_society_event_event_kind_check
  check(event_kind in ('departed','arrived','need_changed','social_contact',
    'goal_selected','route_progressed','action_completed','replanned','blocked',
    'observed','communicated','decision_applied'));

drop index world_society_event_legacy_unique;
drop index world_society_event_v2_order_unique;
create unique index world_society_event_legacy_unique
  on world_society_event(workspace_id,society_id,tick,subject_id,event_kind)
  where coalesce(document->>'profile','') not in ('exulanica-society/v2','exulanica-society/v3');
create unique index world_society_event_versioned_order_unique
  on world_society_event(workspace_id,society_id,tick,((document->>'order')::bigint))
  where document->>'profile' in ('exulanica-society/v2','exulanica-society/v3');

create or replace function tg_world_society_input_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3') then
    raise exception 'versioned inputs require a scoped versioned society' using errcode='23514';
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

create table world_society_decision_request (
  workspace_id uuid not null,
  society_id uuid not null,
  request_id uuid not null,
  subject_id uuid not null,
  base_tick bigint not null check(base_tick>=0),
  input_seq bigint not null check(input_seq>0),
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,request_id),
  unique(workspace_id,society_id,base_tick,subject_id),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  foreign key(workspace_id,society_id,input_seq)
    references world_society_input(workspace_id,society_id,input_seq),
  check(document->>'profile' is not distinct from 'exulanica.society-decision-request/v1'),
  check(document->>'request_id' is not distinct from request_id::text),
  check(document->>'subject_id' is not distinct from subject_id::text),
  check(document->>'base_tick' is not distinct from base_tick::text),
  check(document->>'input_seq' is not distinct from input_seq::text),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check((document->>'base_state_sha256' ~ '^[0-9a-f]{64}$') is true),
  check((document->>'input_sha256' ~ '^[0-9a-f]{64}$') is true),
  check((document->>'context_sha256' ~ '^[0-9a-f]{64}$') is true),
  check(jsonb_typeof(document->'context') is not distinct from 'object'),
  check((jsonb_typeof(document->'provider_config') in ('object','null')) is true)
);

create table world_society_decision (
  workspace_id uuid not null,
  society_id uuid not null,
  decision_seq bigint not null check(decision_seq>0),
  request_id uuid not null,
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,decision_seq),
  unique(workspace_id,society_id,request_id),
  foreign key(workspace_id,society_id,request_id)
    references world_society_decision_request(workspace_id,society_id,request_id),
  check(document->>'profile' is not distinct from 'exulanica.society-decision/v1'),
  check(document->>'decision_seq' is not distinct from decision_seq::text),
  check(document->>'request_id' is not distinct from request_id::text),
  check(document->>'document_sha256' is not distinct from document_sha256),
  check((document->>'status' in ('accepted','rejected','unavailable','stale')) is true),
  check(jsonb_typeof(document->'reason') is not distinct from 'string'),
  check((jsonb_typeof(document->'proposal') in ('object','null')) is true),
  check((jsonb_typeof(document->'provider') in ('object','null')) is true)
);

create table world_society_transition_decision (
  workspace_id uuid not null,
  society_id uuid not null,
  tick bigint not null,
  decision_seq bigint not null,
  disposition text not null
    check(disposition in ('applied','rejected','unavailable','stale','superseded')),
  primary key(workspace_id,society_id,decision_seq),
  foreign key(workspace_id,society_id,tick)
    references world_society_transition(workspace_id,society_id,tick),
  foreign key(workspace_id,society_id,decision_seq)
    references world_society_decision(workspace_id,society_id,decision_seq)
);

-- Reservations commit before inference. A retry cannot reserve another request for
-- the same subject and base tick, including when the original worker is interrupted.
create function tg_world_society_decision_request_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version<>'exulanica-society/v3' then
    raise exception 'social decisions require a scoped v3 society' using errcode='23514';
  end if;
  select * into latest_input from world_society_input
    where workspace_id=new.workspace_id and society_id=new.society_id
    order by input_seq desc limit 1;
  if new.document->>'branch_id' is distinct from held.version_id::text or
     new.base_tick<>held.current_tick or
     new.document->>'base_state_sha256' is distinct from held.state_sha256 or
     new.input_seq is distinct from latest_input.input_seq or
     new.document->>'input_sha256' is distinct from latest_input.document_sha256 then
    raise exception 'social decision reservation is not the current scoped state' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_decision_request_binding
  before insert on world_society_decision_request
  for each row execute function tg_world_society_decision_request_binding();

create function tg_world_society_decision_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; request world_society_decision_request%rowtype;
  latest_input world_society_input%rowtype; latest_seq bigint; field text;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version<>'exulanica-society/v3' then
    raise exception 'social decision receipt requires a scoped v3 society' using errcode='23514';
  end if;
  select * into request from world_society_decision_request
    where workspace_id=new.workspace_id and society_id=new.society_id
      and request_id=new.request_id;
  if not found or new.document->>'request_sha256' is distinct from request.document_sha256 then
    raise exception 'social decision receipt requires its exact request' using errcode='23514';
  end if;
  foreach field in array array['subject_id','branch_id','base_tick','base_state_sha256',
      'input_seq','input_sha256','context_sha256'] loop
    if new.document->field is distinct from request.document->field then
      raise exception 'social decision receipt request binding mismatch: %',field using errcode='23514';
    end if;
  end loop;
  select coalesce(max(decision_seq),0) into latest_seq from world_society_decision
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if new.decision_seq<>latest_seq+1 then
    raise exception 'social decision sequence must be contiguous' using errcode='23514';
  end if;
  if new.document->>'status'='accepted' then
    select * into latest_input from world_society_input
      where workspace_id=new.workspace_id and society_id=new.society_id
      order by input_seq desc limit 1;
    if request.base_tick<>held.current_tick or
       request.document->>'base_state_sha256' is distinct from held.state_sha256 or
       request.input_seq is distinct from latest_input.input_seq or
       request.document->>'input_sha256' is distinct from latest_input.document_sha256 then
      raise exception 'accepted social decision is stale' using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;
create trigger tg_world_society_decision_binding before insert on world_society_decision
  for each row execute function tg_world_society_decision_binding();

create function tg_world_society_transition_decision_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; receipt world_society_decision%rowtype;
  transition world_society_transition%rowtype; latest_seq bigint; latest_tick bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version<>'exulanica-society/v3' then
    raise exception 'social decision consumption requires a scoped v3 society' using errcode='23514';
  end if;
  select * into receipt from world_society_decision
    where workspace_id=new.workspace_id and society_id=new.society_id
      and decision_seq=new.decision_seq;
  if not found then
    raise exception 'social decision consumption requires a scoped receipt' using errcode='23514';
  end if;
  select * into transition from world_society_transition
    where workspace_id=new.workspace_id and society_id=new.society_id and tick=new.tick;
  if not found then
    raise exception 'social decision consumption requires a scoped transition' using errcode='23514';
  end if;
  select coalesce(max(decision_seq),0),coalesce(max(tick),0) into latest_seq,latest_tick
    from world_society_transition_decision
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if new.decision_seq<>latest_seq+1 or new.tick<latest_tick or
     new.tick<=(receipt.document->>'base_tick')::bigint then
    raise exception 'social decisions must be consumed once in sequence after reservation' using errcode='23514';
  end if;
  if new.disposition='applied' then
    if receipt.document->>'status' is distinct from 'accepted' or
       (receipt.document->>'base_tick')::bigint<>new.tick-1 or
       receipt.document->>'base_state_sha256' is distinct from transition.previous_state_sha256 or
       (receipt.document->>'input_seq')::bigint<>transition.to_input_seq or
       exists(select 1 from world_society_transition_decision b join world_society_decision d
         using(workspace_id,society_id,decision_seq)
         where b.workspace_id=new.workspace_id and b.society_id=new.society_id
           and b.tick=new.tick and b.disposition='applied'
           and d.document->>'subject_id'=receipt.document->>'subject_id') then
      raise exception 'social decision cannot apply to this transition' using errcode='23514';
    end if;
  elsif receipt.document->>'status'<>'accepted' and
        new.disposition is distinct from receipt.document->>'status' then
    raise exception 'unaccepted decision disposition must retain its status' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_transition_decision_binding
  before insert on world_society_transition_decision
  for each row execute function tg_world_society_transition_decision_binding();

do $$ declare t text; begin
  foreach t in array array['world_society_decision_request','world_society_decision',
      'world_society_transition_decision'] loop
    execute format('create trigger %I before update or delete on %I '
      'for each row execute function tg_world_society_event_append_only()',t||'_append_only',t);
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t);
  end loop;
end $$;

create or replace function tg_world_society_v2_event_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if not found then
    raise exception 'society event requires a scoped society' using errcode='23514';
  end if;
  if held.engine_version in ('exulanica-society/v2','exulanica-society/v3') then
    if new.document->>'profile' is distinct from held.engine_version or
       new.document->>'branch_id' is distinct from held.version_id::text or
       new.document->>'subject_id' is distinct from new.subject_id::text or
       new.document->>'tick' is distinct from new.tick::text or
       new.document->'synthetic' is distinct from 'true'::jsonb or
       coalesce(new.document->>'order','') !~ '^[0-9]+$' or
       jsonb_typeof(new.document->'summary') is distinct from 'string' then
      raise exception 'versioned event identity and order must match its document' using errcode='23514';
    end if;
  elsif new.document->>'profile' in ('exulanica-society/v2','exulanica-society/v3') then
    raise exception 'v1 society cannot emit versioned events' using errcode='23514';
  end if;
  return new;
end $fn$;

commit;
