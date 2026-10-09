-- A being walks up to act with its hands on its own side: exulanica-ability/hands/v2.
--
-- The hands module's second version (exulanica/abilities/ability-modules.v1.json) serves the same
-- acts as the first, with the same figures and events, and walks a being to the open node within
-- reach of what it acts on that is nearest the being itself (exulanica/world/society_hands.py). A
-- new society of things records it; one that recorded the first keeps it for its whole life. 0170's
-- binding of a person's hands request admitted a society that recorded the first version only; it
-- is restated here, unchanged but for admitting either version, so a person may ask a being of a
-- society made since for a hands act as before. No stored row changes.
begin;
select pg_advisory_xact_lock(119622309);

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
      or not coalesce(held.state->'modules' ?| array['exulanica-ability/hands/v1',
        'exulanica-ability/hands/v2'], false)
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
