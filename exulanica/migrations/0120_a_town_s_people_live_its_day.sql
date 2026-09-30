-- 0120_a_town_s_people_live_its_day.sql
-- The living town, exulanica-society/v5, over the existing society tables, and the input it reads.
--
-- The living town is the living society's catalogued needs, routines and occupancy over a saved
-- world whose own records state its walking surfaces and homes: a town generated from a recipe.
-- Its people live in the town's homes, work the shifts their workplace's use class names and run
-- errands while its premises are open, and the world's owner may choose a model for a person, as
-- in a purposeful society. So it consumes versioned inputs and records transition receipts, as v2,
-- v3 and v4 do, and its history holds validated model decisions, as v2's does: each check,
-- trigger and index that names the engines of those capabilities names it too, and its
-- population is one to 512, a saved world's bounds (exulanica/world/society-engines.v2.json, held
-- to this schema by tests/test_society_engine_table.py).
--
-- Its input is exulanica.society-input/walking-surfaces-v2: the walking-surfaces-v1 input and
-- the living place the town's records make under a living routine, with that routine's catalog
-- versions and digest (`living`), so the town's society replays from its stored inputs alone. An
-- unavailable input carries no place. Every earlier profile's rules are unchanged, and no stored
-- row is rewritten: every stored society replays as it always has.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society drop constraint world_society_engine_version_check;
alter table world_society add constraint world_society_engine_version_check
  check(engine_version in ('exulanica-society/v1','exulanica-society/v2','exulanica-society/v3',
    'exulanica-society/v4','exulanica-society/v5'));
alter table world_society drop constraint world_society_population_size_check;
alter table world_society add constraint world_society_population_size_check
  check((engine_version='exulanica-society/v4' and population_size between 1 and 65536)
    or (engine_version in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5')
        and population_size between 1 and 512)
    or (engine_version='exulanica-society/v1' and population_size between 100 and 512));

drop index world_society_event_legacy_unique;
drop index world_society_event_versioned_order_unique;
create unique index world_society_event_legacy_unique
  on world_society_event(workspace_id,society_id,tick,subject_id,event_kind)
  where coalesce(document->>'profile','') not in
    ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4','exulanica-society/v5');
create unique index world_society_event_versioned_order_unique
  on world_society_event(workspace_id,society_id,tick,((document->>'order')::bigint))
  where document->>'profile' in
    ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4','exulanica-society/v5');

create or replace function tg_world_society_input_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in
      ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4',
       'exulanica-society/v5') then
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
      'exulanica-society/v5') then
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
      'exulanica-society/v5') then
    raise exception 'v1 society cannot emit versioned events' using errcode='23514';
  end if;
  return new;
end $fn$;

create or replace function tg_world_society_decision_request_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5') then
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
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5') then
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
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3','exulanica-society/v5') then
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

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2',
     'exulanica.society-input/authored-ground-v3',
     'exulanica.society-input/walking-surfaces-v1',
     'exulanica.society-input/walking-surfaces-v2')) is true);

alter table world_society_input drop constraint world_society_input_unread_placements_check;
alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v2',
                                       'exulanica.society-input/authored-ground-v3',
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
                                       'exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2')
      then (jsonb_typeof(document->'routine')='object'
        and jsonb_typeof(document->'routine'->'catalog_versions')='object'
        and document->'routine'->>'sha256' ~ '^[0-9a-f]{64}$') is true
    else not (document ? 'routine') end
  );

alter table world_society_input drop constraint world_society_input_population_check;
alter table world_society_input add constraint world_society_input_population_check
  check (
    case when document->>'profile' in ('exulanica.society-input/walking-surfaces-v1',
                                       'exulanica.society-input/walking-surfaces-v2')
      then (jsonb_typeof(document->'population')='object'
        and ((document->'population') - 'rule' - 'size') = '{}'::jsonb
        and jsonb_typeof(document->'population'->'rule')='string'
        and length(document->'population'->>'rule') between 1 and 1000
        and case when jsonb_typeof(document->'population'->'size')='number'
              then (document->'population'->>'size') ~ '^[0-9]+$'
                and (document->'population'->>'size')::numeric between 0 and 512
              else false end) is true
    else not (document ? 'population') end
  );

-- Only the walking-surfaces-v2 input carries a living place, and it always states the routine it
-- was made under: a place sealed by its digest where the input is available, and none where it
-- is not.
alter table world_society_input add constraint world_society_input_living_check
  check (
    case when document->>'profile'='exulanica.society-input/walking-surfaces-v2'
      then (jsonb_typeof(document->'living')='object'
        and ((document->'living') - 'routine' - 'place') = '{}'::jsonb
        and jsonb_typeof(document->'living'->'routine'->'catalog_versions')='object'
        and document->'living'->'routine'->>'sha256' ~ '^[0-9a-f]{64}$'
        and case when document->>'availability'='available'
              then jsonb_typeof(document->'living'->'place')='object'
                and document->'living'->'place'->>'document_sha256' ~ '^[0-9a-f]{64}$'
              else jsonb_typeof(document->'living'->'place')='null' end) is true
    else not (document ? 'living') end
  );

commit;
