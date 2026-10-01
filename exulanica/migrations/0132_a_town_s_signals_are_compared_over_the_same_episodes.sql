-- 0132_a_town_s_signals_are_compared_over_the_same_episodes.sql
-- The same episodes of a saved town's traffic, its signals decided by each arm of a comparison,
-- recorded and replayed.
--
-- A signal comparison plays one episode of a saved world's roads per run: the traffic step's own
-- episode, whose departures and dwells its index draws from the roads' seed, so every arm of one
-- seed starts from the same departures. An arm names who decides for the comparison's group of
-- signals: the plan's fixed timing, or a model asked at every choice point the step offers. Five
-- records:
--
-- signal_comparison, the definition: the world and version, the roads it runs by version and
-- digest, and a document naming the group, the arms, the seeds it committed to by digest, the
-- protocol and catalogs it is run and judged under and the decision role's contract. Keyed by the
-- caller's id within its workspace, and by its world.
-- signal_comparison_run, one arm on one seed, reserved before anything is asked, holding the seed
-- beside the digest the definition committed; no route returns the seed.
-- signal_comparison_decision, every request and receipt of a run's choice points, in the junction
-- signal role's profiles, contiguous and appended while the run has no outcome.
-- signal_comparison_outcome, a run's one terminal fact: completed, with its episode's last
-- continuation digest, its receipts' digest and the traffic measure's integer terms, or failed by
-- a code.
-- signal_comparison_start, a comparison started from the application and the claim a host holds
-- while it plays it: migration 0119's society comparison start, for signals.
--
-- All are appended and never changed, save a start's claim, what it presumes and its finishing, as
-- 0119 allows a society start's. Nothing here writes the world's traffic, its choices or its
-- sealed minutes. Migration 0130's cancellation and run start facts bind signal comparisons from
-- here.
begin;
select pg_advisory_xact_lock(119622309);

create table signal_comparison (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  version_id uuid not null,
  roads_version text not null check (roads_version ~ '^[0-9a-f]{64}$'),
  roads_sha256 text not null check (roads_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, comparison_id),
  unique (workspace_id, world_id, comparison_id),
  constraint signal_comparison_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  check ((document->>'profile' = 'exulanica.signal-comparison/v1') is true),
  check ((document->>'phase' in ('development', 'held_out')) is true),
  check ((jsonb_typeof(document->'seeds') = 'array'
          and jsonb_array_length(document->'seeds') between 1 and 64) is true),
  check ((jsonb_typeof(document->'arms') = 'object') is true),
  check ((jsonb_typeof(document->'group') = 'array'
          and jsonb_array_length(document->'group') between 1 and 64) is true),
  check (((document->>'phase' = 'held_out')
          = (jsonb_typeof(document->'preregistration') = 'object')) is true),
  check (document->>'document_sha256' is not distinct from document_sha256),
  check (document->>'world_id' is not distinct from world_id),
  check (document->>'version_id' is not distinct from version_id::text),
  check (document->'roads'->>'roads_version' is not distinct from roads_version),
  check (document->'roads'->>'input_sha256' is not distinct from roads_sha256)
);

create table signal_comparison_run (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  arm text not null check (arm ~ '^[a-z][a-z0-9_]*$'),
  seed text not null check (seed ~ '^[0-9a-f]{64}$'),
  seed_digest text not null
    check (seed_digest = encode(sha256(convert_to(seed, 'UTF8')), 'hex')),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id),
  unique (workspace_id, world_id, comparison_id, run_id),
  unique (workspace_id, comparison_id, arm, seed_digest),
  constraint signal_comparison_run_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id)
    references signal_comparison (workspace_id, world_id, comparison_id)
);

create table signal_comparison_decision (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  decision_seq bigint not null check (decision_seq > 0),
  request_id uuid not null,
  signal_id text not null check (length(signal_id) between 1 and 500),
  choice_second bigint not null check (choice_second >= 0),
  request jsonb not null check (jsonb_typeof(request) = 'object'),
  request_sha256 text not null check (request_sha256 ~ '^[0-9a-f]{64}$'),
  receipt jsonb not null check (jsonb_typeof(receipt) = 'object'),
  receipt_sha256 text not null check (receipt_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id, decision_seq),
  unique (workspace_id, run_id, request_id),
  unique (workspace_id, run_id, signal_id, choice_second),
  constraint signal_comparison_decision_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id, run_id)
    references signal_comparison_run (workspace_id, world_id, comparison_id, run_id),
  check ((request->>'profile' = 'exulanica.junction-signal-decision-request/v1') is true),
  check ((receipt->>'profile' = 'exulanica.junction-signal-decision/v1') is true),
  check (request->>'document_sha256' is not distinct from request_sha256),
  check (receipt->>'document_sha256' is not distinct from receipt_sha256),
  check (receipt->>'request_sha256' is not distinct from request_sha256),
  check (request->>'request_id' is not distinct from request_id::text),
  check (receipt->>'request_id' is not distinct from request_id::text),
  check (receipt->>'decision_seq' is not distinct from decision_seq::text),
  check (request->>'subject_id' is not distinct from signal_id),
  check (request->'context'->>'choice_second' is not distinct from choice_second::text)
);

create table signal_comparison_outcome (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  status text not null check (status in ('completed', 'failed')),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id),
  constraint signal_comparison_outcome_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id, run_id)
    references signal_comparison_run (workspace_id, world_id, comparison_id, run_id),
  check (document->>'document_sha256' is not distinct from document_sha256),
  check (document->>'status' is not distinct from status),
  check (document->>'run_id' is not distinct from run_id::text),
  check ((status = 'completed' and document->>'profile' = 'exulanica.signal-comparison-run/v1')
      or (status = 'failed' and document->>'profile' = 'exulanica.signal-comparison-failure/v1'))
);

create table signal_comparison_start (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  requested_by uuid not null,
  bound_usd numeric(20, 8) not null check (bound_usd > 0),
  bound_calls integer not null check (bound_calls > 0),
  runs_planned integer not null check (runs_planned > 0),
  created_at timestamptz not null default statement_timestamp(),
  lease_token uuid,
  claimed_at timestamptz,
  lease_expires_at timestamptz,
  claim_attempts integer not null default 0 check (claim_attempts >= 0),
  presumed_usd numeric(20, 8) not null default 0 check (presumed_usd >= 0),
  finished_at timestamptz,
  closed_reason text check (closed_reason ~ '^[a-z][a-z0-9_]*$'),
  primary key (workspace_id, comparison_id),
  constraint signal_comparison_start_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id)
    references signal_comparison (workspace_id, world_id, comparison_id),
  check ((lease_token is null) = (lease_expires_at is null)),
  check ((lease_token is null) = (claimed_at is null)),
  check (finished_at is null or lease_token is null),
  check (closed_reason is null or finished_at is not null)
);
create unique index signal_comparison_start_one_unfinished_per_world
  on signal_comparison_start (workspace_id, world_id) where finished_at is null;
create index signal_comparison_start_unfinished
  on signal_comparison_start (workspace_id, created_at, comparison_id) where finished_at is null;

-- A run names one of its comparison's arms and a seed its comparison committed to.
create function tg_signal_comparison_run_binding() returns trigger language plpgsql as $fn$
declare held signal_comparison%rowtype;
begin
  perform assert_workspace_context(new.workspace_id);
  select * into held from signal_comparison
    where workspace_id = new.workspace_id and world_id = new.world_id
      and comparison_id = new.comparison_id;
  if not found
     or not (held.document->'arms') ? new.arm
     or not exists (
       select 1 from jsonb_array_elements_text(held.document->'seeds') seed
       where seed.value = new.seed_digest) then
    raise exception 'signal comparison run names an arm and a committed seed of its comparison'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_signal_comparison_run_binding before insert on signal_comparison_run
  for each row execute function tg_signal_comparison_run_binding();

-- A receipt is appended to a run that has no outcome yet, in contiguous order.
create function tg_signal_comparison_decision_binding() returns trigger language plpgsql as $fn$
declare latest bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended(new.workspace_id::text || ':' || new.run_id::text, 880132));
  if exists (select 1 from signal_comparison_outcome where workspace_id = new.workspace_id
             and world_id = new.world_id and run_id = new.run_id) then
    raise exception 'a finished signal comparison run takes no further receipts'
      using errcode = '23514';
  end if;
  select coalesce(max(decision_seq), 0) into latest from signal_comparison_decision
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  if new.decision_seq <> latest + 1 then
    raise exception 'signal comparison receipts are appended in contiguous order'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_signal_comparison_decision_binding before insert on signal_comparison_decision
  for each row execute function tg_signal_comparison_decision_binding();

-- An outcome binds its definition, arm and seed digest; a completed one counts exactly the
-- receipts its run holds.
create function tg_signal_comparison_outcome_binding() returns trigger language plpgsql as $fn$
declare held signal_comparison%rowtype; run signal_comparison_run%rowtype; receipts bigint;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended(new.workspace_id::text || ':' || new.run_id::text, 880132));
  select * into run from signal_comparison_run where workspace_id = new.workspace_id
    and world_id = new.world_id and run_id = new.run_id;
  select * into held from signal_comparison where workspace_id = new.workspace_id
    and world_id = new.world_id and comparison_id = new.comparison_id;
  select count(*) into receipts from signal_comparison_decision
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  if run.run_id is null or held.comparison_id is null
     or new.document->>'definition_sha256' is distinct from held.document_sha256
     or new.document->>'arm' is distinct from run.arm
     or new.document->>'seed_digest' is distinct from run.seed_digest
     or (new.status = 'completed'
         and (new.document->'receipts'->>'count') is distinct from receipts::text) then
    raise exception 'signal comparison outcome binding mismatch' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_signal_comparison_outcome_binding before insert on signal_comparison_outcome
  for each row execute function tg_signal_comparison_outcome_binding();

create function tg_signal_comparison_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'signal comparison records are appended, never changed' using errcode = '23514';
end $fn$;

-- A start keeps what it recorded; its presumed spend only grows; a finished one is not changed.
create function tg_signal_comparison_start_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a signal comparison start is never deleted' using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  if (new.workspace_id, new.world_id, new.comparison_id, new.requested_by, new.bound_usd,
      new.bound_calls, new.runs_planned, new.created_at)
     is distinct from
     (old.workspace_id, old.world_id, old.comparison_id, old.requested_by, old.bound_usd,
      old.bound_calls, old.runs_planned, old.created_at)
     or new.presumed_usd < old.presumed_usd
     or old.finished_at is not null then
    raise exception
      'a signal comparison start keeps what it recorded, its presumed spend only grows, and a finished one is not changed'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_signal_comparison_start_guard before update or delete
  on signal_comparison_start for each row execute function tg_signal_comparison_start_guard();

do $$ declare t text; begin
  foreach t in array array['signal_comparison','signal_comparison_run',
      'signal_comparison_decision','signal_comparison_outcome'] loop
    execute format('create trigger %I before update or delete on %I for each row '
      'execute function tg_signal_comparison_append_only()', t || '_append_only', t);
  end loop;
  foreach t in array array['signal_comparison','signal_comparison_run',
      'signal_comparison_decision','signal_comparison_outcome','signal_comparison_start'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- Migration 0130's cancellation and run start facts now bind a signal comparison as they bind a
-- society comparison: a cancellation names one started from the application, and a run start an
-- unfinished run of one.
create or replace function tg_comparison_cancellation_binding() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not (
    (new.kind = 'society' and exists (
      select 1 from society_comparison_start
      where workspace_id = new.workspace_id and world_id = new.world_id
        and comparison_id = new.comparison_id))
    or (new.kind = 'signal' and exists (
      select 1 from signal_comparison_start
      where workspace_id = new.workspace_id and world_id = new.world_id
        and comparison_id = new.comparison_id))) then
    raise exception 'a cancellation names a comparison of its world started from the application'
      using errcode = '23514';
  end if;
  return new;
end $fn$;

create or replace function tg_comparison_run_start_binding() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if not (
    (new.kind = 'society'
     and exists (
       select 1 from society_comparison_run
       where workspace_id = new.workspace_id and world_id = new.world_id
         and comparison_id = new.comparison_id and run_id = new.run_id)
     and not exists (
       select 1 from society_comparison_outcome
       where workspace_id = new.workspace_id and world_id = new.world_id
         and run_id = new.run_id))
    or (new.kind = 'signal'
     and exists (
       select 1 from signal_comparison_run
       where workspace_id = new.workspace_id and world_id = new.world_id
         and comparison_id = new.comparison_id and run_id = new.run_id)
     and not exists (
       select 1 from signal_comparison_outcome
       where workspace_id = new.workspace_id and world_id = new.world_id
         and run_id = new.run_id))) then
    raise exception 'a run start names an unfinished run of its comparison' using errcode = '23514';
  end if;
  return new;
end $fn$;

-- The application appends and reads the records and changes only a start's claim; read-only
-- roles only read them. Provisioning applies the same shape through exulanica.db.roles.
do $$ declare r text; t text; begin
  foreach t in array array['signal_comparison','signal_comparison_run',
      'signal_comparison_decision','signal_comparison_outcome'] loop
    foreach r in array array['exulanica_app','orimera_app'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select, insert on %I to %I', t, r);
      end if;
    end loop;
  end loop;
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert, update on signal_comparison_start to %I', r);
    end if;
  end loop;
  foreach t in array array['signal_comparison','signal_comparison_run',
      'signal_comparison_decision','signal_comparison_outcome','signal_comparison_start'] loop
    foreach r in array array['exulanica_ro','orimera_ro'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on %I to %I', t, r);
      end if;
    end loop;
  end loop;
end $$;

commit;
