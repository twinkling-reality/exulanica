-- 0119_a_comparison_is_started_from_the_application_and_claimed_by_a_host.sql
-- A comparison a world's owner starts from the application, claimed and played by a host.
--
-- Migration 0113 records a comparison's definition, its runs, their receipts and outcomes; a local
-- command defined and played every one of them. A world's owner now starts one from the
-- application: the route defines the comparison, reserves every run and records its start in one
-- transaction, and a host's comparison worker claims the start and plays its runs off the request
-- path, as the playback worker claims a playing society (exulanica/api/society_comparison_worker.py).
--
-- society_comparison_start, one row per comparison started from the application: who started it,
-- the bound its asks may spend and the most calls they may make, how many runs it planned, and the
-- claim a host holds while it plays them: a lease token that expires unless the host renews it
-- each simulated minute, when it was claimed and how many claims in a row finished no run, and what
-- claims that took the start over from a host whose lease ran out presumed it spent and never
-- recorded, which only grows. It is keyed within its workspace by the comparison's own id, and
-- names its comparison and a registered world. What it records of the start is never changed and a
-- start is never deleted; a host changes only its claim and what it presumes, and once, when every
-- run has an outcome or the start was closed, the time it finished and why it was closed. A world has at most one start not yet finished, so a second
-- start while one plays is refused rather than queued behind it.
begin;
select pg_advisory_xact_lock(119622309);

create table society_comparison_start (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  requested_by uuid not null,
  -- The most the comparison's asks may spend, in US dollars, as the person stated it.
  bound_usd numeric(20, 8) not null check (bound_usd > 0),
  -- The most calls they may make: every ask the comparison can make, as often as each is answered.
  bound_calls integer not null check (bound_calls > 0),
  runs_planned integer not null check (runs_planned > 0),
  created_at timestamptz not null default statement_timestamp(),
  lease_token uuid,
  claimed_at timestamptz,
  lease_expires_at timestamptz,
  claim_attempts integer not null default 0 check (claim_attempts >= 0),
  -- The most the minutes hosts whose lease ran out may have been asking can have cost, in US
  -- dollars: paid for, perhaps, and never recorded, so every later claim deducts it from the bound.
  presumed_usd numeric(20, 8) not null default 0 check (presumed_usd >= 0),
  finished_at timestamptz,
  closed_reason text check (closed_reason ~ '^[a-z][a-z0-9_]*$'),
  primary key (workspace_id, comparison_id),
  constraint society_comparison_start_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id)
    references society_comparison (workspace_id, world_id, comparison_id),
  check ((lease_token is null) = (lease_expires_at is null)),
  check ((lease_token is null) = (claimed_at is null)),
  check (finished_at is null or lease_token is null),
  check (closed_reason is null or finished_at is not null)
);

-- A world plays one comparison started from the application at a time.
create unique index society_comparison_start_one_unfinished_per_world
  on society_comparison_start (workspace_id, world_id) where finished_at is null;
-- A claim reads a workspace's unfinished starts, oldest first.
create index society_comparison_start_unfinished
  on society_comparison_start (workspace_id, created_at, comparison_id) where finished_at is null;

create function tg_society_comparison_start_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a comparison start is never deleted' using errcode = '23514';
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
      'a comparison start keeps what it recorded, its presumed spend only grows, and a finished one is not changed'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_start_guard before update or delete
  on society_comparison_start for each row execute function tg_society_comparison_start_guard();

alter table society_comparison_start enable row level security;
alter table society_comparison_start force row level security;
create policy ws_isolation on society_comparison_start
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

-- The application records a start and changes only its claim; read-only roles only read it.
do $$ declare r text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert, update on society_comparison_start to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on society_comparison_start to %I', r);
    end if;
  end loop;
end $$;

commit;
