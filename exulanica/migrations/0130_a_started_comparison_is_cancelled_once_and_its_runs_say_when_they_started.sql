-- 0130_a_started_comparison_is_cancelled_once_and_its_runs_say_when_they_started.sql
-- A comparison started from the application can be cancelled, once, and a host records when it
-- starts playing each run.
--
-- comparison_cancellation, one row per cancelled comparison: which kind of comparison (a society
-- comparison of people's deciders, or a signal comparison of a town's lights, whose records a later
-- migration adds), its id, who cancelled it and when. A host playing the comparison reads it before
-- each dispatch and stops asking; a start nobody holds is closed by the cancellation itself. It is
-- appended once and never changed, so a repeated cancel finds the first and changes nothing.
-- comparison_run_start, one row each time a host starts playing a run under its claim's lease: what
-- makes a run with no outcome running rather than waiting for its turn. Appended, never changed.
--
-- Both name a registered world (<table>_world_is_registered) and bind their comparison: a
-- cancellation names a comparison started from the application, and a run start names a run of
-- one that has no outcome yet. Row-level security keeps each to its workspace, and the application
-- only appends and reads them.
begin;
select pg_advisory_xact_lock(119622309);

create table comparison_cancellation (
  workspace_id uuid not null,
  world_id text not null,
  kind text not null check (kind in ('society', 'signal')),
  comparison_id uuid not null,
  requested_by uuid not null,
  requested_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, kind, comparison_id),
  constraint comparison_cancellation_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id)
);

create table comparison_run_start (
  workspace_id uuid not null,
  world_id text not null,
  kind text not null check (kind in ('society', 'signal')),
  comparison_id uuid not null,
  run_id uuid not null,
  lease_token uuid not null,
  started_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, kind, run_id, lease_token),
  constraint comparison_run_start_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id)
);
-- A read of a comparison's progress finds its runs' starts by comparison.
create index comparison_run_start_by_comparison
  on comparison_run_start (workspace_id, kind, comparison_id);

-- A cancellation names a comparison of its world that was started from the application. A signal
-- comparison's start is bound when its records exist; until then a signal cancellation is refused.
create function tg_comparison_cancellation_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if new.kind <> 'society' or not exists (
    select 1 from society_comparison_start
    where workspace_id = new.workspace_id and world_id = new.world_id
      and comparison_id = new.comparison_id) then
    raise exception 'a cancellation names a comparison of its world started from the application'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_comparison_cancellation_binding before insert on comparison_cancellation
  for each row execute function tg_comparison_cancellation_binding();

-- A run start names a run of that comparison, in its world, that has no outcome yet.
create function tg_comparison_run_start_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if new.kind <> 'society'
     or not exists (
       select 1 from society_comparison_run
       where workspace_id = new.workspace_id and world_id = new.world_id
         and comparison_id = new.comparison_id and run_id = new.run_id)
     or exists (
       select 1 from society_comparison_outcome
       where workspace_id = new.workspace_id and world_id = new.world_id
         and run_id = new.run_id) then
    raise exception 'a run start names an unfinished run of its comparison' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_comparison_run_start_binding before insert on comparison_run_start
  for each row execute function tg_comparison_run_start_binding();

create function tg_comparison_fact_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'a comparison''s cancellation and run starts are appended, never changed'
    using errcode = '23514';
end $fn$;

do $$ declare t text; begin
  foreach t in array array['comparison_cancellation','comparison_run_start'] loop
    execute format('create trigger %I before update or delete on %I for each row '
      'execute function tg_comparison_fact_append_only()', t || '_append_only', t);
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- The application appends and reads both; read-only roles only read them. Provisioning applies
-- the same shape through exulanica.db.roles, where each is insert-only.
do $$ declare r text; t text; begin
  foreach t in array array['comparison_cancellation','comparison_run_start'] loop
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
