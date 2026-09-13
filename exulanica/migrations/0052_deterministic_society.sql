-- Deterministic synthetic society bound to an authored world version.
begin;
select pg_advisory_xact_lock(119622309);

create table world_society (
  workspace_id uuid not null,
  society_id uuid not null default uuidv7(),
  world_id text not null,
  version_id uuid not null,
  place_id uuid not null,
  region_id text not null check(length(region_id) between 1 and 500),
  engine_version text not null check(engine_version='exulanica-society/v1'),
  seed text not null check(seed ~ '^[0-9a-f]{64}$'),
  population_size integer not null check(population_size>=100 and population_size<=512),
  tick_seconds integer not null check(tick_seconds=60),
  current_tick bigint not null default 0 check(current_tick>=0),
  state jsonb not null check(jsonb_typeof(state)='object'),
  state_sha256 text not null check(state_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id),
  unique(workspace_id,world_id,version_id),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,place_id) references place(workspace_id,place_id)
);

create table world_society_event (
  workspace_id uuid not null,
  society_id uuid not null,
  event_id uuid not null,
  tick bigint not null check(tick>0),
  event_kind text not null
    check(event_kind in ('departed','arrived','need_changed','social_contact')),
  subject_id uuid not null,
  object_id uuid,
  place_id uuid not null,
  document jsonb not null check(jsonb_typeof(document)='object'),
  document_sha256 text not null check(document_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,society_id,event_id),
  unique(workspace_id,society_id,tick,subject_id,event_kind),
  foreign key(workspace_id,society_id) references world_society(workspace_id,society_id),
  foreign key(workspace_id,place_id) references place(workspace_id,place_id)
);
create index world_society_event_tick_idx
  on world_society_event(workspace_id,society_id,tick,event_id);

create function tg_world_society_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  if tg_op='UPDATE' and
     (to_jsonb(new)-'current_tick'-'state'-'state_sha256')
       is distinct from
     (to_jsonb(old)-'current_tick'-'state'-'state_sha256')
  then
    raise exception 'society identity and seed are immutable' using errcode='23514';
  end if;
  return new;
end $fn$;
create trigger tg_world_society_binding
before insert or update on world_society
for each row execute function tg_world_society_binding();

create function tg_world_society_event_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'society events are append-only' using errcode='23514';
end $fn$;
create trigger tg_world_society_event_append_only
before update or delete on world_society_event
for each row execute function tg_world_society_event_append_only();

do $$ declare t text; begin
  foreach t in array array['world_society','world_society_event'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())',t
    );
  end loop;
end $$;

commit;
