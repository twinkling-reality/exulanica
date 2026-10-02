-- 0136_a_comparison_s_day_is_sealed_hour_by_hour.sql
-- A comparison over a living town's day seals each run hour by hour.
--
-- Migration 0113 records a comparison's definition, its runs, their receipts and each run's one
-- outcome, and 0116 a second version of the definition and the completed outcome. A comparison
-- whose window is a day (exulanica/world/society_comparison_day.py) plays each run one hour at a
-- time, from where the hour before it ended, so a host that takes over a run stopped part way
-- goes on from the last hour sealed, answering every minute recorded after it from what it
-- recorded, and every read is one hour. Two changes, nothing a recorded row relied on dropped:
--
-- society_comparison_hour, one sealed hour of a run: its document
-- (exulanica.society-comparison-hour/v1: the hour's minute digests, its events and receipts by
-- digest, the score's terms for the hour, what its asking took and each person's minutes), the
-- decision sequence of the last receipt it holds, and the state the hour ended in, as the
-- canonical bytes whose SHA-256 is the hour's last minute's digest, which the database computes.
-- A run's hours are appended in order, from its first, while it has no outcome, each holding
-- exactly the receipts recorded since the hour before it, and only for a run whose definition's
-- window is longer than an hour. They are appended and never changed, under forced row-level
-- security, and name a registered world (society_comparison_hour_world_is_registered).
-- society_comparison_outcome: the completed profiles admit exulanica.society-comparison-run/v3,
-- a completed day, and its binding trigger, 0116's with one condition more, holds it to a
-- definition whose window is longer than an hour and to every hour of that window sealed, its
-- last holding the run's every receipt.
begin;
select pg_advisory_xact_lock(119622309);

create table society_comparison_hour (
  workspace_id uuid not null,
  world_id text not null,
  comparison_id uuid not null,
  run_id uuid not null,
  hour integer not null check (hour >= 0),
  decision_seq_end bigint not null check (decision_seq_end >= 0),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  end_state bytea not null check (octet_length(end_state) > 0),
  end_state_sha256 text not null check (end_state_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, run_id, hour),
  constraint society_comparison_hour_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, comparison_id, run_id)
    references society_comparison_run (workspace_id, world_id, comparison_id, run_id),
  check ((document->>'profile' = 'exulanica.society-comparison-hour/v1') is true),
  check (document->>'document_sha256' is not distinct from document_sha256),
  check (document->>'run_id' is not distinct from run_id::text),
  check (document->>'hour' is not distinct from hour::text),
  -- The state an hour ended in is the state its last minute's digest names.
  constraint society_comparison_hour_state_digest
    check (end_state_sha256 = encode(sha256(end_state), 'hex')),
  constraint society_comparison_hour_state_is_its_last_minute
    check (document->'minutes'->'state_sha256'->>-1 is not distinct from end_state_sha256)
);

-- An hour is appended to a run of a day's comparison that has no outcome yet, after the hour
-- before it, holding exactly the receipts recorded since that hour, every one recorded so far.
create function tg_society_comparison_hour_binding() returns trigger language plpgsql as $fn$
declare
  held society_comparison%rowtype; run society_comparison_run%rowtype;
  previous society_comparison_hour%rowtype; latest bigint; window_ticks integer;
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(
    hashtextextended(new.workspace_id::text || ':' || new.run_id::text, 880113));
  select * into run from society_comparison_run where workspace_id = new.workspace_id
    and world_id = new.world_id and run_id = new.run_id;
  select * into held from society_comparison where workspace_id = new.workspace_id
    and world_id = new.world_id and comparison_id = new.comparison_id;
  window_ticks := (held.document->>'window_ticks')::integer;
  if run.run_id is null or held.comparison_id is null or window_ticks is null
     or window_ticks <= 60 or new.hour * 60 >= window_ticks then
    raise exception 'an hour is sealed only of a day''s run, inside its window'
      using errcode = '23514';
  end if;
  if exists (select 1 from society_comparison_outcome where workspace_id = new.workspace_id
             and world_id = new.world_id and run_id = new.run_id) then
    raise exception 'a finished comparison run seals no further hour' using errcode = '23514';
  end if;
  if new.document->>'definition_sha256' is distinct from held.document_sha256
     or new.document->>'arm' is distinct from run.arm
     or new.document->>'seed_digest' is distinct from run.seed_digest
     or (new.document->>'first_tick')::bigint is distinct from new.hour::bigint * 60 then
    raise exception 'a sealed hour names its own run, arm, seed and minutes' using errcode = '23514';
  end if;
  select * into previous from society_comparison_hour where workspace_id = new.workspace_id
    and world_id = new.world_id and run_id = new.run_id order by hour desc limit 1;
  if (previous.run_id is null and new.hour <> 0)
     or (previous.run_id is not null and new.hour <> previous.hour + 1) then
    raise exception 'a run''s hours are sealed in order, from its first' using errcode = '23514';
  end if;
  select coalesce(max(decision_seq), 0) into latest from society_comparison_decision
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  if new.decision_seq_end <> latest
     or (new.document->'receipts'->>'first_sequence')::bigint
        is distinct from coalesce(previous.decision_seq_end, 0)
     or (new.document->'receipts'->>'count')::bigint
        is distinct from new.decision_seq_end - coalesce(previous.decision_seq_end, 0) then
    raise exception 'a sealed hour holds exactly the receipts recorded since the hour before it'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger tg_society_comparison_hour_binding before insert on society_comparison_hour
  for each row execute function tg_society_comparison_hour_binding();

create trigger society_comparison_hour_append_only before update or delete
  on society_comparison_hour for each row execute function tg_society_comparison_append_only();

alter table society_comparison_hour enable row level security;
alter table society_comparison_hour force row level security;
create policy ws_isolation on society_comparison_hour
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

alter table society_comparison_outcome drop constraint society_comparison_outcome_check3;
alter table society_comparison_outcome add constraint society_comparison_outcome_check3
  check ((status = 'completed'
          and document->>'profile' in ('exulanica.society-comparison-run/v1',
                                       'exulanica.society-comparison-run/v2',
                                       'exulanica.society-comparison-run/v3'))
      or (status = 'failed' and document->>'profile' = 'exulanica.society-comparison-failure/v1'));

-- 0116's outcome binding, with one condition more: a completed day is a run of a comparison whose
-- window is longer than an hour, with every hour of that window sealed and its last holding every
-- receipt the run recorded; a run of such a window completes only as a day.
create or replace function tg_society_comparison_outcome_binding() returns trigger
language plpgsql as $fn$
declare
  held society_comparison%rowtype; run society_comparison_run%rowtype; receipts bigint;
  hours bigint; last_end bigint; window_ticks integer;
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
  select count(*), max(decision_seq_end) into hours, last_end from society_comparison_hour
    where workspace_id = new.workspace_id and world_id = new.world_id and run_id = new.run_id;
  window_ticks := (held.document->>'window_ticks')::integer;
  if run.run_id is null or held.comparison_id is null
     or new.document->>'definition_sha256' is distinct from held.document_sha256
     or new.document->>'arm' is distinct from run.arm
     or new.document->>'seed_digest' is distinct from run.seed_digest
     or (new.status = 'completed'
         and (new.document->'receipts'->>'count') is distinct from receipts::text)
     or (new.status = 'completed'
         and (held.document->>'profile', new.document->>'profile') not in (
           ('exulanica.society-comparison/v1', 'exulanica.society-comparison-run/v1'),
           ('exulanica.society-comparison/v2', 'exulanica.society-comparison-run/v2'),
           ('exulanica.society-comparison/v2', 'exulanica.society-comparison-run/v3')))
     or (new.status = 'completed'
         and new.document->>'profile' = 'exulanica.society-comparison-run/v3'
         and (window_ticks is null or window_ticks <= 60 or hours * 60 <> window_ticks
              or last_end is distinct from receipts))
     or (new.status = 'completed'
         and new.document->>'profile' = 'exulanica.society-comparison-run/v2'
         and window_ticks > 60) then
    raise exception 'comparison outcome binding mismatch' using errcode = '23514';
  end if;
  return new;
end $fn$;

-- The application appends and reads sealed hours; read-only roles only read them. Provisioning
-- applies the same shape through exulanica.db.roles, where the table is insert-only.
do $$ declare r text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert on society_comparison_hour to %I', r);
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on society_comparison_hour to %I', r);
    end if;
  end loop;
end $$;

commit;
