-- 0110_a_person_may_be_run_by_a_model_their_world_s_owner_chose.sql
-- A person in a purposeful society may be run by a model their world's owner chose.
--
-- The purposeful society (exulanica-society/v2) takes, at the planner's own choice point, a model's
-- validated choice for a person whose world's owner chose a model for them, from a stored receipt
-- asked before the minute and replayed from what it stores. Two things are stored here.
--
-- The owner's choice, world_society_model_choice: which model runs which people of one society,
-- or the built-in planner (a null model), appended in order and never changed, each row naming who
-- made it. A person's current choice is the latest row naming them; a society with no row is run
-- by its routine alone. Keyed by the world it belongs to, like every world table (0099), and by
-- the caller's idempotency key within its workspace, since a caller chooses that key. What a row
-- may name, a declared model that fits the decision contract and people the society holds, is the
-- repository's to check (exulanica/world/society_model_choice_repository.py); the table holds its
-- shape, its order and its society.
--
-- The decision tables 0055 wrote for the social society (exulanica-society/v3) now take the
-- purposeful society's person decisions as well: a v2 society records a person request
-- (exulanica.society-decision-request/v2) and receipt (exulanica.society-decision/v2), a v3 society
-- its own v1 documents, and neither the other's. The three bindings are 0055's, word for word,
-- with the engine they admit widened to both and the request's and the receipt's profile each
-- held to its engine.
-- Stored v3 rows are untouched, and a stored v2 society has no decision rows, so every stored
-- society replays as it always has.
begin;
select pg_advisory_xact_lock(119622309);

do $$ declare held text; begin
  for held in select conname from pg_constraint
      where conrelid = 'world_society_decision_request'::regclass and contype = 'c'
        and pg_get_constraintdef(oid) like '%exulanica.society-decision-request/v1%' loop
    execute format('alter table world_society_decision_request drop constraint %I', held);
  end loop;
  for held in select conname from pg_constraint
      where conrelid = 'world_society_decision'::regclass and contype = 'c'
        and pg_get_constraintdef(oid) like '%exulanica.society-decision/v1%' loop
    execute format('alter table world_society_decision drop constraint %I', held);
  end loop;
end $$;
alter table world_society_decision_request add constraint world_society_decision_request_profile_check
  check ((document->>'profile' in ('exulanica.society-decision-request/v1',
                                   'exulanica.society-decision-request/v2')) is true);
alter table world_society_decision add constraint world_society_decision_profile_check
  check ((document->>'profile' in ('exulanica.society-decision/v1',
                                   'exulanica.society-decision/v2')) is true);

-- A world's hour of decisions is counted from its receipts, as they are recorded.
create index world_society_decision_recorded_idx
  on world_society_decision (workspace_id, society_id, recorded_at);

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
  if (held.engine_version = 'exulanica-society/v2')
     <> (new.document->>'profile' = 'exulanica.society-decision-request/v2') then
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
  if (held.engine_version = 'exulanica-society/v2')
     <> (new.document->>'profile' = 'exulanica.society-decision/v2') then
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
  if not found or held.engine_version not in ('exulanica-society/v2','exulanica-society/v3') then
    raise exception 'social decision consumption requires a scoped v2 or v3 society' using errcode='23514';
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

create table world_society_model_choice (
  workspace_id    uuid not null,
  world_id        text not null,
  society_id      uuid not null,
  choice_seq      bigint not null check (choice_seq > 0),
  -- The caller's idempotency key: an exact retry reads its row back rather than choosing twice.
  request_id      uuid not null,
  document        jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  chosen_by       uuid not null,
  recorded_at     timestamptz not null default statement_timestamp(),
  primary key (workspace_id, society_id, choice_seq),
  unique (workspace_id, society_id, request_id),
  foreign key (workspace_id, society_id) references world_society (workspace_id, society_id),
  foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  check ((document->>'profile' = 'exulanica.society-model-choice/v1') is true),
  check ((document->>'choice_seq' = choice_seq::text) is true),
  check ((document->>'request_id' = request_id::text) is true),
  check ((document->>'society_id' = society_id::text) is true),
  check ((document->>'chosen_by' = chosen_by::text) is true),
  check ((document->>'document_sha256' = document_sha256) is true),
  check ((jsonb_typeof(document->'people') = 'array'
          and jsonb_array_length(document->'people') between 1 and 512) is true),
  check ((jsonb_typeof(document->'model') in ('object', 'null')) is true)
);

create function tg_world_society_model_choice_binding() returns trigger
language plpgsql as $fn$
declare held world_society%rowtype; latest_seq bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society
    where workspace_id = new.workspace_id and society_id = new.society_id for update;
  if not found or held.world_id is distinct from new.world_id then
    raise exception 'a model choice names a society of its own world' using errcode = '23514';
  end if;
  select coalesce(max(choice_seq), 0) into latest_seq from world_society_model_choice
    where workspace_id = new.workspace_id and society_id = new.society_id;
  if new.choice_seq <> latest_seq + 1 then
    raise exception 'model choices are appended in order' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_model_choice_binding
  before insert on world_society_model_choice
  for each row execute function tg_world_society_model_choice_binding();
create trigger world_society_model_choice_append_only
  before update or delete on world_society_model_choice
  for each row execute function tg_world_society_event_append_only();

alter table world_society_model_choice enable row level security;
alter table world_society_model_choice force row level security;
create policy ws_isolation on world_society_model_choice
  using (workspace_id = current_workspace())
  with check (workspace_id = current_workspace());

commit;
