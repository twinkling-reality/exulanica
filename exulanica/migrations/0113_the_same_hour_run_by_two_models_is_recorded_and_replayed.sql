-- 0113_the_same_hour_run_by_two_models_is_recorded_and_replayed.sql
-- The same hour of a saved world, run with each arm of a comparison, recorded and replayed.
--
-- A comparison runs one simulated hour of a world's purposeful society (exulanica-society/v2)
-- several times from the same start: the society's genesis over its first input with a seed, and
-- its later inputs, up to one the comparison froze, consumed in the first minute. Each arm names
-- who decides for the society's people: their routine, nobody (they wait), or a model. Four
-- records:
--
-- society_comparison, the definition: the world, version and society it runs, the frozen input by
-- sequence and digest, and a document naming the window, the people, the arms, its phase, the
-- digests of the seeds it committed to and everything it is scored and judged under. Keyed by the
-- caller's id within its workspace (a caller chooses that id), and by its world, like every world
-- table. Each of the four names a registered world by <table>_world_is_registered, as every world
-- table does.
-- society_comparison_run, one arm on one seed, reserved before anything is asked. It holds the
-- seed itself, which a replay needs, beside the digest the definition committed; no route returns
-- the seed.
-- society_comparison_decision, every receipt a run's model was asked for, as the host's person
-- decisions are receipted (exulanica.society-decision/v2), with the request it answers.
-- society_comparison_outcome, a run's one terminal fact: completed, with the digest of every
-- minute's state, of its events and of its receipts and the score's integer terms, or failed.
--
-- All four are appended and never changed. A run's receipts are appended while it has no outcome,
-- so a recorded run is exactly what its outcome describes. A run is its own: nothing here writes
-- the society it ran over, and replaying a run asks nothing (exulanica/world/society_comparison.py).
begin;
select pg_advisory_xact_lock(119622309);

create table society_comparison (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  version_id uuid not null,
  society_id uuid not null,
  input_seq bigint not null check (input_seq > 0),
  input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, comparison_id),
  unique (workspace_id, world_id, comparison_id),
  constraint society_comparison_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  foreign key (workspace_id, society_id) references world_society (workspace_id, society_id),
  foreign key (workspace_id, society_id, input_seq)
    references world_society_input (workspace_id, society_id, input_seq),
  check ((document->>'profile' = 'exulanica.society-comparison/v1') is true),
  check ((document->>'phase' in ('development', 'held_out')) is true),
  check ((jsonb_typeof(document->'seeds') = 'array'
          and jsonb_array_length(document->'seeds') between 1 and 64) is true),
  check ((jsonb_typeof(document->'arms') = 'object') is true),
  -- A held-out comparison is judged, so it names the pre-registration it was run under.
  check (((document->>'phase' = 'held_out')
          = (jsonb_typeof(document->'preregistration') = 'object')) is true),
  check (document->>'document_sha256' is not distinct from document_sha256),
  check (document->>'world_id' is not distinct from world_id),
  check (document->>'version_id' is not distinct from version_id::text),
  check (document->>'society_id' is not distinct from society_id::text),
  check (document->'input'->>'input_seq' is not distinct from input_seq::text),
  check (document->'input'->>'document_sha256' is not distinct from input_sha256)
);

create table society_comparison_run (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  arm text not null check (arm ~ '^[a-z][a-z0-9_]*$'),
  seed text not null check (seed ~ '^[0-9a-f]{64}$'),
  -- The seed is committed by the SHA-256 of its text, the digest its comparison names.
  seed_digest text not null
    check (seed_digest = encode(sha256(convert_to(seed, 'UTF8')), 'hex')),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id),
  unique (workspace_id, world_id, comparison_id, run_id),
  unique (workspace_id, comparison_id, arm, seed_digest),
  constraint society_comparison_run_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id)
    references society_comparison (workspace_id, world_id, comparison_id)
);

create table society_comparison_decision (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  decision_seq bigint not null check (decision_seq > 0),
  request_id uuid not null,
  subject_id uuid not null,
  base_tick bigint not null check (base_tick >= 0),
  request jsonb not null check (jsonb_typeof(request) = 'object'),
  request_sha256 text not null check (request_sha256 ~ '^[0-9a-f]{64}$'),
  receipt jsonb not null check (jsonb_typeof(receipt) = 'object'),
  receipt_sha256 text not null check (receipt_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id, decision_seq),
  unique (workspace_id, run_id, request_id),
  unique (workspace_id, run_id, subject_id, base_tick),
  constraint society_comparison_decision_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id, run_id)
    references society_comparison_run (workspace_id, world_id, comparison_id, run_id),
  check ((request->>'profile' = 'exulanica.society-decision-request/v2') is true),
  check ((receipt->>'profile' = 'exulanica.society-decision/v2') is true),
  check (request->>'document_sha256' is not distinct from request_sha256),
  check (receipt->>'document_sha256' is not distinct from receipt_sha256),
  check (receipt->>'request_sha256' is not distinct from request_sha256),
  check (request->>'request_id' is not distinct from request_id::text),
  check (receipt->>'request_id' is not distinct from request_id::text),
  check (receipt->>'decision_seq' is not distinct from decision_seq::text),
  check (request->>'subject_id' is not distinct from subject_id::text),
  check (request->>'base_tick' is not distinct from base_tick::text)
);

create table society_comparison_outcome (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  status text not null check (status in ('completed', 'failed')),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id),
  constraint society_comparison_outcome_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id, run_id)
    references society_comparison_run (workspace_id, world_id, comparison_id, run_id),
  check (document->>'document_sha256' is not distinct from document_sha256),
  check (document->>'status' is not distinct from status),
  check (document->>'run_id' is not distinct from run_id::text),
  check ((status = 'completed' and document->>'profile' = 'exulanica.society-comparison-run/v1')
      or (status = 'failed' and document->>'profile' = 'exulanica.society-comparison-failure/v1'))
);

-- A definition names the society of its own world and version, and that society's stored input.
-- Which engines a comparison may run is the engine table's to say, read where it is created.
create function tg_society_comparison_binding() returns trigger language plpgsql as $fn$
declare held world_society%rowtype; frozen world_society_input%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from world_society where workspace_id = new.workspace_id
    and society_id = new.society_id;
  select * into frozen from world_society_input where workspace_id = new.workspace_id
    and society_id = new.society_id and input_seq = new.input_seq;
  if held.society_id is null or held.world_id is distinct from new.world_id
     or held.version_id is distinct from new.version_id
     or frozen.document_sha256 is distinct from new.input_sha256 then
    raise exception 'comparison definition binding mismatch' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_binding before insert on society_comparison
  for each row execute function tg_society_comparison_binding();

-- A run names one of its comparison's arms and a seed its comparison committed to.
create function tg_society_comparison_run_binding() returns trigger language plpgsql as $fn$
declare held society_comparison%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from society_comparison
    where workspace_id = new.workspace_id and world_id = new.world_id
      and comparison_id = new.comparison_id;
  if not found
     or not (held.document->'arms') ? new.arm
     or not exists (
       select 1 from jsonb_array_elements_text(held.document->'seeds') seed
       where seed.value = new.seed_digest) then
    raise exception 'comparison run names an arm and a committed seed of its comparison'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_run_binding before insert on society_comparison_run
  for each row execute function tg_society_comparison_run_binding();

-- A receipt is appended to a run that has no outcome yet, in contiguous order.
create function tg_society_comparison_decision_binding() returns trigger language plpgsql as $fn$
declare latest bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended(new.workspace_id::text || ':' || new.run_id::text, 880113));
  if exists (select 1 from society_comparison_outcome where workspace_id = new.workspace_id
             and world_id = new.world_id and run_id = new.run_id) then
    raise exception 'a finished comparison run takes no further receipts' using errcode = '23514';
  end if;
  select coalesce(max(decision_seq), 0) into latest from society_comparison_decision
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  if new.decision_seq <> latest + 1 then
    raise exception 'comparison receipts are appended in contiguous order' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_decision_binding before insert on society_comparison_decision
  for each row execute function tg_society_comparison_decision_binding();

-- An outcome binds its definition, arm and seed digest; a completed one counts exactly the
-- receipts its run holds.
create function tg_society_comparison_outcome_binding() returns trigger language plpgsql as $fn$
declare held society_comparison%rowtype; run society_comparison_run%rowtype; receipts bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended(new.workspace_id::text || ':' || new.run_id::text, 880113));
  select * into run from society_comparison_run where workspace_id = new.workspace_id
    and world_id = new.world_id and run_id = new.run_id;
  select * into held from society_comparison where workspace_id = new.workspace_id
    and world_id = new.world_id and comparison_id = new.comparison_id;
  select count(*) into receipts from society_comparison_decision
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  if run.run_id is null or held.comparison_id is null
     or new.document->>'definition_sha256' is distinct from held.document_sha256
     or new.document->>'arm' is distinct from run.arm
     or new.document->>'seed_digest' is distinct from run.seed_digest
     or (new.status = 'completed'
         and (new.document->'receipts'->>'count') is distinct from receipts::text) then
    raise exception 'comparison outcome binding mismatch' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_outcome_binding before insert on society_comparison_outcome
  for each row execute function tg_society_comparison_outcome_binding();

create function tg_society_comparison_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'comparison records are appended, never changed' using errcode = '23514';
end $fn$;

do $$ declare t text; begin
  foreach t in array array['society_comparison','society_comparison_run',
      'society_comparison_decision','society_comparison_outcome'] loop
    execute format('create trigger %I before update or delete on %I for each row '
      'execute function tg_society_comparison_append_only()', t || '_append_only', t);
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- The application appends and reads the records; read-only roles only read them. Provisioning
-- applies the same shape through exulanica.db.roles, where each of these tables is insert-only.
do $$ declare r text; t text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['society_comparison','society_comparison_run',
          'society_comparison_decision','society_comparison_outcome'] loop
        execute format('grant select, insert on %I to %I', t, r);
      end loop;
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['society_comparison','society_comparison_run',
          'society_comparison_decision','society_comparison_outcome'] loop
        execute format('grant select on %I to %I', t, r);
      end loop;
    end if;
  end loop;
end $$;

commit;
