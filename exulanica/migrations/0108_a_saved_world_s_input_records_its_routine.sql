-- 0108_a_saved_world_s_input_records_its_routine.sql
-- A saved world's input records the routine its inhabitants live by.
--
-- The third profile a saved world's own ground produces,
-- exulanica.society-input/authored-ground-v3, is the second one's projection, decided object by
-- object with every place stated, that also records the purposeful routine it was composed under:
-- the catalog versions in assets/catalogs/society and their digest. Each activity names the
-- routine's entry for its object's kind in place of a fixed duration, so how long a stay lasts,
-- how it varies, and whether people stand or stop to talk, are the routine's. An input that records
-- no routine is read under the rules the society was first released with, so no stored input
-- changes meaning, and a stored authored-ground-v2 input is not touched.
--
-- The profile check admits the third profile. The unread placements rule 0098 wrote for the
-- second applies to the third. Only the third records a routine: an earlier input never carries
-- one, and a third-profile input always does, so which rules an input is read under is stated by
-- the input itself.
--
-- A check passes when its condition is null, and a field a row omits reads as null, so each rule
-- below is asked whether it is true: a third-profile row whose routine names no catalog versions,
-- or which omits its unread placements, is refused rather than admitted by a null. Every stored
-- second-profile row carries its unread placements, which 0098 introduced with the profile.
--
-- A routine an input records draws its stays, and a stay drawn from its range can last many
-- minutes, so a person's direct request ends one under way (exulanica/world/society_planner.py,
-- ends_on_request). The request binding 0060 wrote refused any request for somebody part way
-- through anything, so the database would refuse what the society takes. The person rule is now
-- one function, society_person_may_be_directed, that the binding asks: somebody doing nothing,
-- whose action is over or blocked, or, under an input that records a routine, standing at a node
-- part way through a stay, which is every action but walking and idling. A walk is still left to
-- arrive, and under an input that records no routine the rule is 0060's. The planner's own rule
-- (exulanica/world/society_actions.py, may_be_directed) is held equal to it by
-- tests/test_society_request_rule_parity.py. The binding is otherwise 0060's, word for word.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_input drop constraint world_society_input_profile_check;
alter table world_society_input add constraint world_society_input_profile_check
  check ((document->>'profile' in
    ('exulanica.society-input/v1','exulanica.society-input/v2',
     'exulanica.society-input/authored-ground-v1',
     'exulanica.society-input/authored-ground-v2',
     'exulanica.society-input/authored-ground-v3')) is true);

alter table world_society_input drop constraint world_society_input_unread_placements_check;
alter table world_society_input add constraint world_society_input_unread_placements_check
  check (
    case when document->>'profile' in ('exulanica.society-input/authored-ground-v2',
                                       'exulanica.society-input/authored-ground-v3')
      then (jsonb_typeof(document->'unread_placements')='array'
        and jsonb_array_length(document->'unread_placements')<=4096
        and (document->>'availability'='available'
          or document->'unread_placements'='[]'::jsonb)) is true
    else not (document ? 'unread_placements') end
  );

create function society_person_may_be_directed(person jsonb, input jsonb) returns boolean
  language sql immutable parallel safe as $fn$
  select (person->'goal'='null'::jsonb
    or person->'action'->>'status' in ('completed','blocked')
    or (input ? 'routine'
      and person->'action'->>'status'='active'
      and person->'action'->>'kind' not in ('move','idle')
      and person->'location'->'edge'='null'::jsonb)) is true
$fn$;

create or replace function tg_world_society_action_request_binding() returns trigger
language plpgsql as $fn$
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
    or not society_person_may_be_directed(person, latest_input.document)
  then
    raise exception 'society action is not bound to the current scoped state and target'
      using errcode='23514';
  end if;
  return new;
end $fn$;

alter table world_society_input add constraint world_society_input_routine_check
  check (
    case when document->>'profile'='exulanica.society-input/authored-ground-v3'
      then (jsonb_typeof(document->'routine')='object'
        and jsonb_typeof(document->'routine'->'catalog_versions')='object'
        and document->'routine'->>'sha256' ~ '^[0-9a-f]{64}$') is true
    else not (document ? 'routine') end
  );

commit;
