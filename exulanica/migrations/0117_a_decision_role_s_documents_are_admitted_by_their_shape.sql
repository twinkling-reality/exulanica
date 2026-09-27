-- 0117_a_decision_role_s_documents_are_admitted_by_their_shape.sql
-- Every decision role's requests, receipts and model choices are admitted by their shape.
--
-- A decision role is a kind of thing in a world a chosen open model may decide for, declared as
-- data by the decision role registry (assets/catalogs/roles, read by
-- exulanica/world/decision_roles.py), a person in a purposeful society first. Each role's documents
-- name the role by their own profile: its requests (<name>-decision-request/vN), its receipts
-- (<name>-decision/vN) and its model choices (<name>-model-choice/vN), the person's being
-- exulanica.society-decision-request/v2, exulanica.society-decision/v2 and
-- exulanica.society-model-choice/v1. Migrations 0055 and 0110 admitted exactly the profiles they
-- knew, so a new role would have needed a migration of its own. This one admits every profile of
-- a role's shape instead, spelled by the same expressions the registry reads a role's profiles by
-- (PROFILE_PATTERNS in decision_roles.py, held to this schema by a test), and nothing else: which
-- role a profile names, and whether it is registered, stays the application's to check, and a
-- stored document of a profile no registered role writes is refused by name when it is read.
--
-- world_society_decision_request and world_society_decision: the profile checks 0110 wrote admit
-- any request or receipt profile of a role's shape, the social society's own v1 among them. The
-- two binding triggers are 0110's with one condition restated: the social society's profile
-- belongs to its engine (exulanica-society/v3) and every other decision profile to the engine
-- that hosts roles (exulanica-society/v2), where 0110 named the person's profile alone.
-- world_society_model_choice: the profile check admits any choice profile of a role's shape, and a
-- choice names its subjects, 1 to 512 of them, under the one field its role's registry entry
-- names, people or subjects (CHOICE_SUBJECT_FIELDS in decision_roles.py), where 0110 read people
-- alone.
--
-- Nothing stored is rewritten: every stored document already has a profile of these shapes and
-- the fields they read, so every stored society replays as it always has.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_society_decision_request
  drop constraint world_society_decision_request_profile_check;
alter table world_society_decision_request add constraint world_society_decision_request_profile_check
  check ((document->>'profile'
          ~ '^exulanica\.[a-z][a-z0-9-]*-decision-request/v[1-9][0-9]{0,5}$') is true);
alter table world_society_decision drop constraint world_society_decision_profile_check;
alter table world_society_decision add constraint world_society_decision_profile_check
  check ((document->>'profile'
          ~ '^exulanica\.[a-z][a-z0-9-]*-decision/v[1-9][0-9]{0,5}$') is true);

create or replace function tg_world_society_decision_request_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; latest_input world_society_input%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id=new.workspace_id and society_id=new.society_id for update;
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3') then
    raise exception 'social decisions require a scoped v2 or v3 society' using errcode='23514';
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
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3') then
    raise exception 'social decision receipt requires a scoped v2 or v3 society' using errcode='23514';
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

-- 0110 stated the choice table's profile and people checks inline, so PostgreSQL named them; they
-- are found here by what they check rather than by a name this file would have to guess.
do $$ declare held text; begin
  for held in select conname from pg_constraint
      where conrelid = 'world_society_model_choice'::regclass and contype = 'c'
        and (pg_get_constraintdef(oid) like '%exulanica.society-model-choice/v1%'
             or pg_get_constraintdef(oid) like '%''people''%') loop
    execute format('alter table world_society_model_choice drop constraint %I', held);
  end loop;
end $$;
alter table world_society_model_choice add constraint world_society_model_choice_profile_check
  check ((document->>'profile'
          ~ '^exulanica\.[a-z][a-z0-9-]*-model-choice/v[1-9][0-9]{0,5}$') is true);
alter table world_society_model_choice add constraint world_society_model_choice_names_its_subjects
  check (((jsonb_typeof(document->'people') = 'array'
           and jsonb_array_length(document->'people') between 1 and 512
           and not document ? 'subjects')
          or (jsonb_typeof(document->'subjects') = 'array'
              and jsonb_array_length(document->'subjects') between 1 and 512
              and not document ? 'people')) is true);

commit;
