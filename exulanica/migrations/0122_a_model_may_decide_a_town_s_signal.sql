-- 0122_a_model_may_decide_a_town_s_signal.sql
-- A world owner's signal-model choice, its bounded request and receipt, and a sealed minute of
-- traffic are distinct append-only facts. A choice names its target effective second; a segment
-- records when a model actually controlled a light. An unanswered or late request receives a
-- fallback receipt, and no answer can change a segment already sealed for viewers.
begin;
select pg_advisory_xact_lock(119622309);

create table world_traffic_signal_choice (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  choice_seq bigint not null check (choice_seq > 0),
  request_id uuid not null,
  signal_id text not null check (length(signal_id) between 1 and 500),
  effective_second bigint not null check (effective_second >= 0),
  model jsonb not null check (jsonb_typeof(model) in ('object','null')),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  chosen_by uuid not null,
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id, choice_seq),
  unique (workspace_id, world_id, version_id, request_id),
  constraint world_traffic_signal_choice_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  check ((document->>'profile' = 'exulanica.junction-signal-model-choice/v1') is true),
  check ((document->>'choice_seq' = choice_seq::text) is true),
  check ((document->>'request_id' = request_id::text) is true),
  check ((document->>'signal_id' = signal_id) is true),
  check ((document->>'effective_second' = effective_second::text) is true),
  check ((document->>'chosen_by' = chosen_by::text) is true),
  check ((document->>'document_sha256' = document_sha256) is true)
);

create table world_traffic_signal_decision_request (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  roads_version text not null check (roads_version ~ '^[0-9a-f]{64}$'),
  episode bigint not null check (episode >= 0),
  segment integer not null check (segment between 0 and 19),
  choice_seq bigint not null check (choice_seq > 0),
  signal_id text not null check (length(signal_id) between 1 and 500),
  choice_second bigint not null check (choice_second >= 0),
  request_id uuid not null,
  state_sha256 text not null check (state_sha256 ~ '^[0-9a-f]{64}$'),
  deadline_at timestamptz not null,
  budget_bound_usd numeric not null check (budget_bound_usd >= 0),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id, request_id),
  unique (workspace_id, world_id, version_id, roads_version, episode, signal_id, choice_second),
  constraint world_traffic_signal_decision_request_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  foreign key (workspace_id, world_id, version_id, choice_seq)
    references world_traffic_signal_choice (workspace_id, world_id, version_id, choice_seq),
  check ((document->>'profile' = 'exulanica.junction-signal-decision-request/v1') is true),
  check ((document->>'request_id' = request_id::text) is true),
  check ((document->>'subject_id' = signal_id) is true),
  check ((document->'context'->>'choice_second' = choice_second::text) is true),
  check ((document->'context'->>'state_sha256' = state_sha256) is true),
  check ((document->>'document_sha256' = document_sha256) is true)
);

create table world_traffic_signal_decision (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  request_id uuid not null,
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id, request_id),
  constraint world_traffic_signal_decision_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id, request_id)
    references world_traffic_signal_decision_request (workspace_id, world_id, version_id, request_id),
  check ((document->>'profile' = 'exulanica.junction-signal-decision/v1') is true),
  check ((document->>'request_id' = request_id::text) is true),
  check ((document->>'document_sha256' = document_sha256) is true)
);

create table world_traffic_signal_segment (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  roads_version text not null check (roads_version ~ '^[0-9a-f]{64}$'),
  input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
  episode bigint not null check (episode >= 0),
  segment integer not null check (segment between 0 and 19),
  start_second bigint not null check (start_second >= 0),
  end_second bigint not null check (end_second > start_second),
  previous_sha256 text check (previous_sha256 ~ '^[0-9a-f]{64}$'),
  choice_seq bigint,
  active_second bigint,
  decisions_sha256 text not null check (decisions_sha256 ~ '^[0-9a-f]{64}$'),
  frames_sha256 text not null check (frames_sha256 ~ '^[0-9a-f]{64}$'),
  continuation jsonb not null check (jsonb_typeof(continuation) = 'object'),
  continuation_sha256 text not null check (continuation_sha256 ~ '^[0-9a-f]{64}$'),
  sealed_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id, episode, segment),
  constraint world_traffic_signal_segment_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  foreign key (workspace_id, world_id, version_id, choice_seq)
    references world_traffic_signal_choice (workspace_id, world_id, version_id, choice_seq),
  check ((active_second is null or
          (choice_seq is not null and active_second >= start_second and active_second < end_second))),
  check (start_second = episode * 1200 + segment * 60),
  check (end_second = start_second + 60),
  check ((segment = 0) = (previous_sha256 is null)),
  check ((continuation->>'profile' = 'exulanica.traffic-continuation/v1') is true),
  check ((continuation->>'input_sha256' = input_sha256) is true),
  check ((continuation->>'document_sha256' = continuation_sha256) is true)
);

-- Each request is for a choice that was effective when this exact world and road version reached
-- its choice point. The application checks the observation digest and role contract as well.
create function tg_world_traffic_signal_request_binding() returns trigger language plpgsql as $fn$
declare held world_traffic_signal_choice%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_traffic_signal_choice
    where workspace_id = new.workspace_id and world_id = new.world_id
      and version_id = new.version_id and choice_seq = new.choice_seq;
  if not found or held.signal_id is distinct from new.signal_id or
     held.effective_second > new.choice_second or held.model = 'null'::jsonb or
     new.deadline_at <= new.recorded_at then
    raise exception 'signal request does not bind an effective model choice and deadline'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_traffic_signal_request_binding
  before insert on world_traffic_signal_decision_request
  for each row execute function tg_world_traffic_signal_request_binding();

create function tg_world_traffic_signal_decision_binding() returns trigger language plpgsql as $fn$
declare held world_traffic_signal_decision_request%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_traffic_signal_decision_request
    where workspace_id = new.workspace_id and world_id = new.world_id
      and version_id = new.version_id and request_id = new.request_id;
  if not found or new.document->>'request_sha256' is distinct from held.document_sha256 then
    raise exception 'signal decision does not bind its exact request' using errcode = '23514';
  end if;
  if exists (
       select 1 from world_traffic_signal_segment s
       where s.workspace_id = new.workspace_id and s.world_id = new.world_id
         and s.version_id = new.version_id and s.episode = held.episode
         and s.start_second <= held.choice_second and held.choice_second < s.end_second) then
    raise exception 'signal decision arrived after its segment was sealed'
      using errcode = '23514';
  end if;
  if new.document->>'status' = 'accepted' and statement_timestamp() > held.deadline_at then
    raise exception 'signal decision arrived after its deadline' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_traffic_signal_decision_binding
  before insert on world_traffic_signal_decision
  for each row execute function tg_world_traffic_signal_decision_binding();

create function tg_world_traffic_signal_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'a sealed traffic signal fact is append-only' using errcode = '23514';
end $fn$;
create trigger world_traffic_signal_choice_append_only
  before update or delete on world_traffic_signal_choice
  for each row execute function tg_world_traffic_signal_append_only();
create trigger world_traffic_signal_decision_request_append_only
  before update or delete on world_traffic_signal_decision_request
  for each row execute function tg_world_traffic_signal_append_only();
create trigger world_traffic_signal_decision_append_only
  before update or delete on world_traffic_signal_decision
  for each row execute function tg_world_traffic_signal_append_only();
create trigger world_traffic_signal_segment_append_only
  before update or delete on world_traffic_signal_segment
  for each row execute function tg_world_traffic_signal_append_only();

alter table world_traffic_signal_choice enable row level security;
alter table world_traffic_signal_choice force row level security;
create policy ws_isolation on world_traffic_signal_choice
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table world_traffic_signal_decision_request enable row level security;
alter table world_traffic_signal_decision_request force row level security;
create policy ws_isolation on world_traffic_signal_decision_request
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table world_traffic_signal_decision enable row level security;
alter table world_traffic_signal_decision force row level security;
create policy ws_isolation on world_traffic_signal_decision
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table world_traffic_signal_segment enable row level security;
alter table world_traffic_signal_segment force row level security;
create policy ws_isolation on world_traffic_signal_segment
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

do $$ declare r text; t text; begin
  foreach t in array array[
    'world_traffic_signal_choice', 'world_traffic_signal_decision_request',
    'world_traffic_signal_decision', 'world_traffic_signal_segment'] loop
    foreach r in array array['exulanica_app','orimera_app'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select, insert on %I to %I', t, r);
      end if;
    end loop;
    foreach r in array array['exulanica_ro','orimera_ro'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on %I to %I', t, r);
      end if;
    end loop;
  end loop;
end $$;
commit;
