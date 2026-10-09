-- A person asks one being of a society of things for a hands act: pick a thing up, put it down,
-- give it or take it (exulanica.society-action-request/v2, read beside v1).
--
-- A strict superset of what 0060, 0108 and 0151 hold of a direct request. A v1 request (go_to,
-- perform) is held exactly as before: its intent names a target of the input its society
-- consumed, its frozen target is an object, and the binding checks the target against that input.
-- A v2 request names no target: its intent is exactly {kind: hands, ability, thing_id, with_id},
-- with_id a string exactly for a give or a take, the table's target_id holds its thing, and the
-- binding checks the society runs the hands module, the thing is one of its things and any other
-- being it names is here and is not the subject. Whether the act is offered to the
-- being now is the minute's rule (exulanica.world.society_actions), as a v1 target's reachability
-- is. No row stored before this migration is a v2 request, so every stored minute replays as it ran.
begin;
select pg_advisory_xact_lock(119622309);

-- 0060 declared four of the table's checks inline, so they carry the names PostgreSQL gave them:
-- found by what they say as PostgreSQL stores it (``is not distinct from`` reads back as
-- ``NOT (... IS DISTINCT FROM ...)``), and refused unless exactly those four are there to replace.
do $$ declare held record; dropped integer := 0; begin
  for held in select conname from pg_constraint
    where conrelid='world_society_action_request'::regclass and contype='c'
      and (pg_get_constraintdef(oid) like '%society-action-request/v1%'
        or pg_get_constraintdef(oid) like '%go_to%'
        or pg_get_constraintdef(oid) like '%''target_id''::text) IS DISTINCT FROM target_id)%'
        or pg_get_constraintdef(oid) like '%(document -> ''target''::text)%')
  loop
    execute format('alter table world_society_action_request drop constraint %I', held.conname);
    dropped := dropped + 1;
  end loop;
  if dropped <> 4 then
    raise exception 'expected the four request checks 0060 declared, found %', dropped;
  end if;
end $$;

alter table world_society_action_request add constraint world_society_action_request_profile_check
  check ((document->>'profile' in ('exulanica.society-action-request/v1',
    'exulanica.society-action-request/v2')) is true);
alter table world_society_action_request add constraint world_society_action_request_intent_check
  check (
    case when document->>'profile'='exulanica.society-action-request/v1'
      then ((document->'intent'->>'kind' in ('go_to','perform'))
        and document->'intent'->>'target_id' is not distinct from target_id
        and jsonb_typeof(document->'target') is not distinct from 'object') is true
    else ((document->'intent'->>'kind' = 'hands')
        and (document->'intent'->>'ability' in ('pick_up','put_down','give','take'))
        -- exactly its four keys, as the code reads them
        and (document->'intent') ?& array['kind','ability','thing_id','with_id']
        and ((document->'intent') - array['kind','ability','thing_id','with_id']) = '{}'::jsonb
        and jsonb_typeof(document->'intent'->'thing_id') = 'string'
        and document->'intent'->>'thing_id' is not distinct from target_id
        -- the other being, a string exactly for a give or a take, and null otherwise
        and jsonb_typeof(document->'intent'->'with_id')
          = case when document->'intent'->>'ability' in ('give','take') then 'string' else 'null' end
        and not (document ? 'target')) is true
    end
  );

-- The directed request binding: 0151's for a v1 request, and for a v2 request the same bindings
-- to the society's current state and input, its hands module, its thing and the being it names.
create or replace function tg_world_society_action_request_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
  target jsonb; person jsonb; latest_seq bigint; hands boolean;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(new.workspace_id::text,880024));
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3',
      'exulanica-society/v7') then
    raise exception 'user actions require a scoped society that takes them' using errcode='23514';
  end if;
  hands := new.document->>'profile' = 'exulanica.society-action-request/v2';
  select * into latest_input from world_society_input
    where workspace_id=new.workspace_id and society_id=new.society_id
    order by input_seq desc limit 1;
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
    or person is null
    or not society_person_may_be_directed(person, latest_input.document)
  then
    raise exception 'society action is not bound to the current scoped state and target'
      using errcode='23514';
  end if;
  if hands then
    if held.engine_version <> 'exulanica-society/v7'
      or not coalesce(held.state->'modules' ? 'exulanica-ability/hands/v1', false)
      or not exists (select 1 from jsonb_array_elements(held.state->'things') thing
        where thing->>'id'=new.target_id)
      or (new.document->'intent'->>'with_id' is not null and not exists (
        select 1 from jsonb_array_elements(held.state->'inhabitants') other
        where other->>'id'=new.document->'intent'->>'with_id'))
      or new.document->'intent'->>'with_id' = new.subject_id::text
    then
      raise exception 'a hands request names a thing and a being of a society running hands'
        using errcode='23514';
    end if;
    return new;
  end if;
  select value into target from jsonb_array_elements(latest_input.document->'targets')
    where value->>'target_id'=new.target_id;
  if target is null or target is distinct from new.document->'target'
    or target->'enabled' is distinct from 'true'::jsonb
  then
    raise exception 'society action is not bound to the current scoped state and target'
      using errcode='23514';
  end if;
  return new;
end $fn$;

commit;
