-- 0151_a_society_of_things.sql
-- The society of things, exulanica-society/v7, over the existing society tables, and the input it
-- reads.
--
-- A society of things is the purposeful society where everybody is a thing of a stated kind: the
-- villagers its ground's population brings, the beings the world's author placed, and visitors
-- that cross in from an outside program through a gate the author placed. It consumes versioned
-- inputs and records transition receipts, takes directed actions, and its history holds validated
-- model decisions, as v2 does: each check, trigger and index that names the engines of those
-- capabilities names it too, and its population is one to 512, a saved world's bounds
-- (exulanica/world/society-engines.v2.json, held to this schema by
-- tests/test_society_engine_table.py). Its people are not sent away and no experiment runs it, so
-- the presence and experiment bindings do not name it.
--
-- Its input is exulanica.society-input/authored-ground-v5: the fourth profile's projection, with
-- the opening source its version pins or none where the ground states its own arrival, and the
-- things the author placed in the region, each with its kind's semantics (never a look). Every
-- earlier profile's rules are unchanged, and no stored row is rewritten.
--
-- Its events add five kinds: a thing arrived (placed by an edit, or crossed in), a placed being
-- moved by an edit, a thing departed (removed by an edit, sent away, its grant ended), an arrival
-- refused and a departure refused (nobody of that id here); and somebody said a line.
--
-- Nobody who came in from outside may be directed by a person's request: their own program
-- decides for them. society_person_may_be_directed refuses a person whose state says they came by
-- crossing, as exulanica/world/society_actions.py's may_be_directed does
-- (tests/test_society_request_rule_parity.py holds the two equal).
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_engine_version_check;
alter table world_society add constraint world_society_engine_version_check
  check(engine_version in ('exulanica-society/v1','exulanica-society/v2','exulanica-society/v3',
    'exulanica-society/v4','exulanica-society/v5','exulanica-society/v7'));
alter table world_society drop constraint world_society_population_size_check;
alter table world_society add constraint world_society_population_size_check
  check((engine_version='exulanica-society/v4' and population_size between 1 and 65536)
    or (engine_version in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5',
        'exulanica-society/v7') and population_size between 1 and 512)
    or (engine_version='exulanica-society/v1' and population_size between 100 and 512));

alter table world_society_event drop constraint world_society_event_event_kind_check;
alter table world_society_event add constraint world_society_event_event_kind_check
  check(event_kind in ('departed','arrived','need_changed','social_contact',
    'goal_selected','route_progressed','action_completed','replanned','blocked',
    'observed','communicated','decision_applied','user_action_requested',
    'thing_arrived','thing_moved','thing_departed','arrival_refused','departure_refused',
    'said'));

drop index world_society_event_legacy_unique;
drop index world_society_event_versioned_order_unique;
create unique index world_society_event_legacy_unique
  on world_society_event(workspace_id,society_id,tick,subject_id,event_kind)
  where coalesce(document->>'profile','') not in
    ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4','exulanica-society/v5',
     'exulanica-society/v7');
create unique index world_society_event_versioned_order_unique
  on world_society_event(workspace_id,society_id,tick,((document->>'order')::bigint))
  where document->>'profile' in
    ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4','exulanica-society/v5',
     'exulanica-society/v7');

create or replace function tg_world_society_input_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in
      ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4',
       'exulanica-society/v5','exulanica-society/v7') then
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

create or replace function tg_world_society_v2_event_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id;
  if not found then
    raise exception 'society event requires a scoped society' using errcode='23514';
  end if;
  if held.engine_version in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4',
      'exulanica-society/v5','exulanica-society/v7') then
    if new.document->>'profile' is distinct from held.engine_version or
       new.document->>'branch_id' is distinct from held.version_id::text or
       new.document->>'subject_id' is distinct from new.subject_id::text or
       new.document->>'tick' is distinct from new.tick::text or
       new.document->'synthetic' is distinct from 'true'::jsonb or
       coalesce(new.document->>'order','') !~ '^[0-9]+$' or
       jsonb_typeof(new.document->'summary') is distinct from 'string' then
      raise exception 'versioned event identity and order must match its document' using errcode='23514';
    end if;
  elsif new.document->>'profile' in
      ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4',
      'exulanica-society/v5','exulanica-society/v7') then
    raise exception 'v1 society cannot emit versioned events' using errcode='23514';
  end if;
  return new;
end $fn$;

-- The decision bindings, 0120's word for word with v7 in each engine list.
create or replace function tg_world_society_decision_request_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5',
      'exulanica-society/v7') then
    raise exception 'decisions require a scoped society whose engine takes them' using errcode='23514';
  end if;
  if (held.engine_version = 'exulanica-society/v3')
     <> (new.document->>'profile' = 'exulanica.society-decision-request/v1') then
    raise exception 'a society records the decision requests of its own engine' using errcode='23514';
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

create or replace function tg_world_society_decision_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; request world_society_decision_request%rowtype;
  latest_input world_society_input%rowtype; latest_seq bigint; field text;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5',
      'exulanica-society/v7') then
    raise exception 'a decision receipt requires a scoped society whose engine takes decisions' using errcode='23514';
  end if;
  if (held.engine_version = 'exulanica-society/v3')
     <> (new.document->>'profile' = 'exulanica.society-decision/v1') then
    raise exception 'a society records the decision receipts of its own engine' using errcode='23514';
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

create or replace function tg_world_society_transition_decision_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; receipt world_society_decision%rowtype;
  transition world_society_transition%rowtype; latest_seq bigint; latest_tick bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5',
      'exulanica-society/v7') then
    raise exception 'decision consumption requires a scoped society whose engine takes decisions' using errcode='23514';
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

create or replace function society_person_may_be_directed(person jsonb, input jsonb) returns boolean
  language sql immutable parallel safe as $fn$
  select (coalesce(person->>'came_by','') <> 'crossed'
    and (person->'goal'='null'::jsonb
      or person->'action'->>'status' in ('completed','blocked')
      or (input ? 'routine'
        and person->'action'->>'status'='active'
        and person->'action'->>'kind' not in ('move','idle')
        and person->'location'->'edge'='null'::jsonb))) is true
$fn$;

-- The directed request binding, 0108's with v7 in its engine list.
create or replace function tg_world_society_action_request_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
  target jsonb; person jsonb; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3',
      'exulanica-society/v7') then
    raise exception 'user actions require a scoped society that takes them' using errcode='23514';
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
    or not society_person_may_be_directed(person, latest_input.document)
  then
    raise exception 'society action is not bound to the current scoped state and target'
      using errcode='23514';
  end if;
  return new;
end $fn$;

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2',
     'exulanica.society-input/authored-ground-v3',
     'exulanica.society-input/authored-ground-v4',
     'exulanica.society-input/authored-ground-v5',
     'exulanica.society-input/walking-surfaces-v1',
     'exulanica.society-input/walking-surfaces-v2')) is true);

alter table world_society_input drop constraint world_society_input_unread_placements_check;
alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v2',
                                       'exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/authored-ground-v4',
                                       'exulanica.society-input/authored-ground-v5',
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2')
      then (jsonb_typeof(document->'unread_placements')='array'
        and jsonb_array_length(document->'unread_placements')<=4096
        and (document->>'availability'='available'
          or document->'unread_placements'='[]'::jsonb)) is true
    else not (document ? 'unread_placements') end
  );

alter table world_society_input drop constraint world_society_input_routine_check;
alter table world_society_input add constraint world_society_input_routine_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v3',
                                       'exulanica.society-input/authored-ground-v4',
                                       'exulanica.society-input/authored-ground-v5',
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2')
      then (jsonb_typeof(document->'routine')='object'
        and jsonb_typeof(document->'routine'->'catalog_versions')='object'
        and document->'routine'->>'sha256' ~ '^[0-9a-f]{64}$') is true
    else not (document ? 'routine') end
  );

-- The things composition states its arrival either way: the pinned descriptor, held to v4's rule,
-- or null where the ground states its own.
alter table world_society_input drop constraint world_society_input_arrival_check;
alter table world_society_input add constraint world_society_input_arrival_check
  check (
    case when document->>'profile'='exulanica.society-input/authored-ground-v4'
           or (document->>'profile'='exulanica.society-input/authored-ground-v5'
               and jsonb_typeof(document->'arrival') is distinct from 'null')
      then (jsonb_typeof(document->'arrival')='object'
        and document->'arrival'->>'profile'='exulanica.arrival-descriptor/v1'
        and document->'arrival'->>'presentation_policy'='exulanica.arrival-presentation/v1'
        and document->'arrival'->>'region_id' is not null
        and jsonb_typeof(document->'arrival'->'position_local_mm')='array'
        and jsonb_array_length(document->'arrival'->'position_local_mm')=3
        and jsonb_typeof(document->'arrival'->'forward_local_millionths')='array'
        and jsonb_array_length(document->'arrival'->'forward_local_millionths')=3
        and jsonb_typeof(document->'arrival'->'source')='object'
        and document->'arrival'->'source'->>'world_id'=document->>'world_id'
        and document->'arrival'->'source'->>'version_id'=document->>'version_id') is true
    when document->>'profile'='exulanica.society-input/authored-ground-v5'
      then true
    else not (document ? 'arrival') end
  );

-- Only the things composition lists placed things, and an unavailable input lists none.
alter table world_society_input add constraint world_society_input_things_check
  check (
    case when document->>'profile'='exulanica.society-input/authored-ground-v5'
      then (jsonb_typeof(document->'things')='array'
        and jsonb_array_length(document->'things')<=4096
        and (document->>'availability'='available'
          or document->'things'='[]'::jsonb)) is true
    else not (document ? 'things') end
  );

commit;
