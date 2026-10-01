-- 0125_a_world_version_keeps_one_clock.sql
-- A world version whose clock is coupled keeps one simulated timeline. The society's tick is its
-- only authority. Every committed society minute of the coupled era records where walkers stood on
-- crossings, and traffic seals each minute once, after the society has committed the minute after
-- it. A version with no clock row keeps its legacy timing: the society's own minutes, and shared
-- real time for traffic and flight.
--
-- Every writer of the clock row holds the workspace edit lock before it locks that row, and
-- nothing locks the clock row without it, so a society minute, a transition and a traffic seal
-- never wait for each other in a cycle. A transition, a traffic seal and a traffic hold then lock
-- the version row and then the clock row; a society minute locks its society row and then the
-- clock row, and touches the version row only as the share its foreign keys take. The one receipt
-- written without the edit lock, a legacy version's skipped signal minutes, holds the version row
-- and locks no clock row. The lead a society may keep over sealed traffic is a check on the clock
-- row itself, so a minute committed past it is refused by the database as well as by the host.
begin;
select pg_advisory_xact_lock(119622309);

create table world_clock (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  society_id uuid not null,
  revision bigint not null check (revision > 0),
  profile text not null check (profile = 'exulanica.world-clock/coupled-v1'),
  era integer not null check (era > 0),
  era_start_tick bigint not null check (era_start_tick >= 0),
  seconds_per_tick integer not null check (seconds_per_tick = 60),
  lead_ticks integer not null check (lead_ticks >= 2),
  timeline_origin_second bigint not null
    check (timeline_origin_second > 0 and timeline_origin_second % 1200 = 0),
  roads_version text check (roads_version ~ '^[0-9a-f]{64}$'),
  input_sha256 text check (input_sha256 ~ '^[0-9a-f]{64}$'),
  society_tick bigint not null,
  society_state_sha256 text not null check (society_state_sha256 ~ '^[0-9a-f]{64}$'),
  traffic_sealed_through_tick bigint,
  traffic_state text check (traffic_state in ('running', 'blocked', 'unavailable')),
  traffic_code text check (length(traffic_code) between 1 and 200),
  presented_through_tick bigint not null,
  presented_at timestamptz not null,
  last_event_seq bigint not null check (last_event_seq > 0),
  changed_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id),
  unique (workspace_id, society_id),
  constraint world_clock_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  foreign key (workspace_id, society_id) references world_society (workspace_id, society_id),
  check (society_tick >= era_start_tick),
  -- Traffic takes part exactly when the version's roads were stated at the transition.
  check ((roads_version is null) = (input_sha256 is null)
    and (roads_version is null) = (traffic_sealed_through_tick is null)
    and (roads_version is null) = (traffic_state is null)),
  check ((traffic_state in ('blocked', 'unavailable')) is not distinct from (traffic_code is not null)
    or (traffic_state is null and traffic_code is null)),
  check (traffic_sealed_through_tick is null
    or traffic_sealed_through_tick between era_start_tick and society_tick),
  -- The lead: a society minute past it is refused here, whoever commits it.
  check (traffic_state is null or traffic_state = 'unavailable'
    or society_tick - traffic_sealed_through_tick <= lead_ticks),
  -- What a reader is shown: sealed traffic while traffic takes part, else the society's head.
  check (presented_through_tick = case
    when traffic_state is null or traffic_state = 'unavailable' then society_tick
    else traffic_sealed_through_tick end)
);

create table world_clock_event (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  event_seq bigint not null check (event_seq > 0),
  kind text not null check (kind in (
    'transitioned', 'traffic_blocked', 'traffic_unavailable', 'legacy_signal_gap')),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id, event_seq),
  constraint world_clock_event_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  check ((document->>'profile' = 'exulanica.world-clock-event/v1') is true),
  check ((document->>'event_seq' = event_seq::text) is true),
  check ((document->>'kind' = kind) is true),
  check ((document->>'version_id' = version_id::text) is true),
  check ((document->>'world_id' = world_id) is true),
  check ((document->>'document_sha256' = document_sha256) is true)
);

create table world_crossing_occupancy (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  society_id uuid not null,
  era integer not null check (era > 0),
  tick bigint not null check (tick > 0),
  previous_state_sha256 text not null check (previous_state_sha256 ~ '^[0-9a-f]{64}$'),
  state_sha256 text not null check (state_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, society_id, tick),
  constraint world_crossing_occupancy_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  foreign key (workspace_id, society_id, tick)
    references world_society_transition (workspace_id, society_id, tick),
  check ((document->>'profile' = 'exulanica.crossing-occupancy/v1') is true),
  check ((document->>'society_id' = society_id::text) is true),
  check ((document->>'era' = era::text) is true),
  check ((document->>'tick' = tick::text) is true),
  check ((document->>'previous_state_sha256' = previous_state_sha256) is true),
  check ((document->>'state_sha256' = state_sha256) is true),
  check ((document->>'document_sha256' = document_sha256) is true)
);

create table world_clock_traffic_minute (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  era integer not null check (era > 0),
  world_tick bigint not null check (world_tick > 0),
  roads_version text not null check (roads_version ~ '^[0-9a-f]{64}$'),
  input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
  episode bigint not null check (episode >= 0),
  segment integer not null check (segment between 0 and 19),
  start_second bigint not null check (start_second >= 0),
  end_second bigint not null,
  occupancy_through_tick bigint not null,
  choice_seq bigint,
  active_second bigint,
  previous_sha256 text check (previous_sha256 ~ '^[0-9a-f]{64}$'),
  feed_sha256 text not null check (feed_sha256 ~ '^[0-9a-f]{64}$'),
  decisions_sha256 text not null check (decisions_sha256 ~ '^[0-9a-f]{64}$'),
  frames_sha256 text not null check (frames_sha256 ~ '^[0-9a-f]{64}$'),
  continuation_sha256 text not null check (continuation_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  document_sha256 text not null check (document_sha256 ~ '^[0-9a-f]{64}$'),
  sealed_at timestamptz not null default statement_timestamp(),
  primary key (workspace_id, world_id, version_id, era, world_tick),
  unique (workspace_id, world_id, version_id, episode, segment),
  constraint world_clock_traffic_minute_world_is_registered
    foreign key (workspace_id, world_id) references world_identity (workspace_id, world_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version (workspace_id, world_id, version_id),
  foreign key (workspace_id, world_id, version_id, choice_seq)
    references world_traffic_signal_choice (workspace_id, world_id, version_id, choice_seq),
  check (start_second = episode * 1200 + segment * 60),
  check (end_second = start_second + 60),
  check (occupancy_through_tick > world_tick),
  check (active_second is null
    or (choice_seq is not null and active_second >= start_second and active_second < end_second)),
  check ((document->>'profile' = 'exulanica.world-traffic-minute/v1') is true),
  check ((document->>'era' = era::text) is true),
  check ((document->>'world_tick' = world_tick::text) is true),
  check ((document->>'start_second' = start_second::text) is true),
  check ((document->>'world_id' = world_id) is true),
  check ((document->>'version_id' = version_id::text) is true),
  check ((document->>'roads_version' = roads_version) is true),
  check ((document->>'input_sha256' = input_sha256) is true),
  check ((document->>'episode' = episode::text) is true),
  check ((document->>'segment' = segment::text) is true),
  check ((document->>'occupancy_through_tick' = occupancy_through_tick::text) is true),
  check ((document->'choice_seq' = coalesce(to_jsonb(choice_seq), 'null'::jsonb)) is true),
  check ((document->'active_second' = coalesce(to_jsonb(active_second), 'null'::jsonb)) is true),
  check ((document->'previous_sha256' = coalesce(to_jsonb(previous_sha256), 'null'::jsonb))
    is true),
  check ((document->>'feed_sha256' = feed_sha256) is true),
  check ((document->>'decisions_sha256' = decisions_sha256) is true),
  check ((document->>'frames_sha256' = frames_sha256) is true),
  check ((document->>'continuation_sha256' = continuation_sha256) is true),
  check ((document->>'document_sha256' = document_sha256) is true)
);

-- The clock row moves forward only: its identity, era origin and society stay, positions never go
-- back, and a revision or era moves by one at a time. Nothing deletes it.
create function tg_world_clock_guard() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'DELETE' then
    raise exception 'a world clock is never deleted' using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  if tg_op = 'UPDATE' and (
       new.world_id <> old.world_id or new.version_id <> old.version_id
    or new.society_id <> old.society_id or new.profile <> old.profile
    or new.revision not between old.revision and old.revision + 1
    or new.era not between old.era and old.era + 1
    or (new.era = old.era and (new.era_start_tick <> old.era_start_tick
      or new.timeline_origin_second <> old.timeline_origin_second
      or new.roads_version is distinct from old.roads_version
      or new.input_sha256 is distinct from old.input_sha256))
    or (new.era <> old.era and new.timeline_origin_second <= old.timeline_origin_second)
    or new.society_tick < old.society_tick
    or (new.era = old.era and new.traffic_sealed_through_tick < old.traffic_sealed_through_tick)
    or (old.traffic_state = 'unavailable' and new.era = old.era
      and new.traffic_state is distinct from 'unavailable')
    or new.last_event_seq < old.last_event_seq) then
    raise exception 'a world clock only moves forward' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger world_clock_guard before insert or update or delete on world_clock
  for each row execute function tg_world_clock_guard();

-- Clock receipts are contiguous per version, whether or not the version's clock is coupled: a
-- legacy version records the gaps its signal skipped.
create function tg_world_clock_event_guard() returns trigger language plpgsql as $fn$
declare expected bigint;
begin
  if tg_op <> 'INSERT' then
    raise exception 'world clock receipts are append-only' using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  select coalesce(max(event_seq), 0) + 1 into expected from world_clock_event
    where workspace_id = new.workspace_id and world_id = new.world_id
      and version_id = new.version_id;
  if new.event_seq <> expected then
    raise exception 'world clock receipts are contiguous' using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger world_clock_event_guard before insert or update or delete on world_clock_event
  for each row execute function tg_world_clock_event_guard();

-- A minute's occupancy names the committed transition it was read from, in the coupled era of
-- the society's own version, after the era began.
create function tg_world_crossing_occupancy_binding() returns trigger language plpgsql as $fn$
declare held_clock world_clock%rowtype; held_transition world_society_transition%rowtype;
begin
  if tg_op <> 'INSERT' then
    raise exception 'crossing occupancy is append-only' using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  select * into held_clock from world_clock
    where workspace_id = new.workspace_id and world_id = new.world_id
      and version_id = new.version_id;
  select * into held_transition from world_society_transition
    where workspace_id = new.workspace_id and society_id = new.society_id and tick = new.tick;
  if held_clock.society_id is distinct from new.society_id or held_clock.era is distinct from new.era
     or new.tick <= held_clock.era_start_tick
     or held_transition.previous_state_sha256 is distinct from new.previous_state_sha256
     or held_transition.state_sha256 is distinct from new.state_sha256 then
    raise exception 'crossing occupancy does not bind a committed minute of its coupled era'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger world_crossing_occupancy_binding before insert or update or delete
  on world_crossing_occupancy for each row execute function tg_world_crossing_occupancy_binding();

-- A sealed traffic minute follows the one before it in its era, and the society has committed
-- every minute of occupancy it reads, through the minute after it.
create function tg_world_clock_traffic_minute_binding() returns trigger language plpgsql as $fn$
declare held_clock world_clock%rowtype; previous text; reached bigint;
begin
  if tg_op <> 'INSERT' then
    raise exception 'a sealed traffic minute is append-only' using errcode = '23514';
  end if;
  perform assert_workspace_context(new.workspace_id);
  select * into held_clock from world_clock
    where workspace_id = new.workspace_id and world_id = new.world_id
      and version_id = new.version_id;
  if held_clock.era is distinct from new.era or new.world_tick <= held_clock.era_start_tick
     or held_clock.roads_version is distinct from new.roads_version
     or held_clock.input_sha256 is distinct from new.input_sha256
     or new.start_second <> held_clock.timeline_origin_second
       + (new.world_tick - 1 - held_clock.era_start_tick) * 60 then
    raise exception 'a sealed traffic minute does not bind its coupled era' using errcode = '23514';
  end if;
  if new.world_tick = held_clock.era_start_tick + 1 then
    if new.previous_sha256 is not null then
      raise exception 'an era''s first traffic minute follows nothing' using errcode = '23514';
    end if;
  else
    select document_sha256 into previous from world_clock_traffic_minute
      where workspace_id = new.workspace_id and world_id = new.world_id
        and version_id = new.version_id and era = new.era and world_tick = new.world_tick - 1;
    if previous is null or previous is distinct from new.previous_sha256 then
      raise exception 'a sealed traffic minute follows the minute before it'
        using errcode = '23514';
    end if;
  end if;
  select count(*) into reached from world_crossing_occupancy
    where workspace_id = new.workspace_id and society_id = held_clock.society_id
      and era = new.era and tick > held_clock.era_start_tick
      and tick <= new.occupancy_through_tick;
  if reached <> new.occupancy_through_tick - held_clock.era_start_tick then
    raise exception 'a sealed traffic minute reads occupancy the society has not committed'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger world_clock_traffic_minute_binding before insert or update or delete
  on world_clock_traffic_minute for each row
  execute function tg_world_clock_traffic_minute_binding();

-- A legacy segment never enters the timeline a coupled era took.
create function tg_world_traffic_signal_segment_clock() returns trigger language plpgsql as $fn$
begin
  if exists (
       select 1 from world_clock c
       where c.workspace_id = new.workspace_id and c.world_id = new.world_id
         and c.version_id = new.version_id and new.end_second > c.timeline_origin_second) then
    raise exception 'a legacy traffic segment enters a coupled clock''s timeline'
      using errcode = '23514';
  end if;
  return new;
end $fn$;
create trigger world_traffic_signal_segment_clock before insert on world_traffic_signal_segment
  for each row execute function tg_world_traffic_signal_segment_clock();

-- 0122's decision binding, with one more refusal: a decision arriving after the coupled minute
-- that holds its choice point was sealed, as one arriving after its legacy segment already is.
create or replace function tg_world_traffic_signal_decision_binding() returns trigger
language plpgsql as $fn$
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
         and s.start_second <= held.choice_second and held.choice_second < s.end_second)
     or exists (
       select 1 from world_clock_traffic_minute m
       where m.workspace_id = new.workspace_id and m.world_id = new.world_id
         and m.version_id = new.version_id and m.episode = held.episode
         and m.start_second <= held.choice_second and held.choice_second < m.end_second) then
    raise exception 'signal decision arrived after its segment was sealed'
      using errcode = '23514';
  end if;
  if new.document->>'status' = 'accepted' and statement_timestamp() > held.deadline_at then
    raise exception 'signal decision arrived after its deadline' using errcode = '23514';
  end if;
  return new;
end $fn$;

create index world_crossing_occupancy_era on world_crossing_occupancy
  (workspace_id, society_id, era, tick);

alter table world_clock enable row level security;
alter table world_clock force row level security;
create policy ws_isolation on world_clock
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table world_clock_event enable row level security;
alter table world_clock_event force row level security;
create policy ws_isolation on world_clock_event
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table world_crossing_occupancy enable row level security;
alter table world_crossing_occupancy force row level security;
create policy ws_isolation on world_crossing_occupancy
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());
alter table world_clock_traffic_minute enable row level security;
alter table world_clock_traffic_minute force row level security;
create policy ws_isolation on world_clock_traffic_minute
  using (workspace_id = current_workspace()) with check (workspace_id = current_workspace());

do $$ declare r text; t text; begin
  foreach r in array array['exulanica_app','orimera_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select, insert, update on world_clock to %I', r);
      foreach t in array array[
        'world_clock_event', 'world_crossing_occupancy', 'world_clock_traffic_minute'] loop
        execute format('grant select, insert on %I to %I', t, r);
      end loop;
    end if;
  end loop;
  foreach r in array array['exulanica_ro','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array[
        'world_clock', 'world_clock_event', 'world_crossing_occupancy',
        'world_clock_traffic_minute'] loop
        execute format('grant select on %I to %I', t, r);
      end loop;
    end if;
  end loop;
end $$;
commit;
