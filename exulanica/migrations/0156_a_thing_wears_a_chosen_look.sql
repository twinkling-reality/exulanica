-- 0156_a_thing_wears_a_chosen_look.sql
-- The look a thing wears in a version: the world's owner choosing one of its kind's looks, or a
-- visitor's look riding beside its crossing.
--
-- A LOOK IS CHOSEN BESIDE A THING, NEVER IN IT. What a thing is and does is its kind's and the
-- society's; how it is drawn is a look chosen for it. So a choice lives here, apart from every
-- society input, state and decision context, and nothing a society reads names this table. A
-- renderer reads the latest choice per thing; a thing with none wears its kind's first look.
--
-- WHAT IS CHOSEN IS A SHIPPED LOOK. A choice names a look by key, version and the SHA-256 of its
-- canonical document (exulanica/things/looks.py). Which looks are shipped, and whether a look's
-- body plan fits the thing's kind, is the repository's catalog, which a database cannot read, so
-- the application checks both before it writes (exulanica/world/thing_looks.py); this table holds
-- the shape.
--
-- WHO CHOSE IT. A crossing's look names the arrival it rode beside, and one arrival records one
-- look however often its door repeats it; an owner's choice names the actor who made it. Choices
-- are appended and never changed: the latest per thing is the one worn, and the history stays.
--
-- A thing is named by the id a society of things gives it (thing_id: a placed being's is derived
-- from its world and placed id, a visitor's is its arrival's), and a placed thing also by the id
-- its author placed it under, which must be a thing placed in this version (0152).
--
-- EVERY ROW NAMES A REGISTERED WORLD. Each table carrying a world names a world of the registry
-- (0099) by key, this one and 0152's placed things, which named only their version until now.
begin;
select pg_advisory_xact_lock(119622309);

create table world_thing_look (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  choice_id bigint generated always as identity,
  thing_id uuid not null,
  placed_id text check(placed_id ~ '^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$'),
  look text not null check(look ~ '^[a-z][a-z0-9-]{0,47}$'),
  look_version integer not null check(look_version between 1 and 10000),
  look_sha256 bytea not null check(octet_length(look_sha256)=32),
  chosen_by text not null check(chosen_by in ('owner','crossing')),
  crossing_id uuid,
  actor uuid,
  chosen_at timestamptz not null default statement_timestamp(),
  constraint world_thing_look_chooser check (
    ((chosen_by='crossing') = (crossing_id is not null)) is true
    and ((chosen_by='owner') = (actor is not null)) is true
  ),
  primary key(workspace_id,choice_id),
  foreign key(workspace_id,world_id) references world_identity(workspace_id,world_id),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id),
  foreign key(workspace_id,world_id,version_id,placed_id)
    references world_alternate_thing(workspace_id,world_id,version_id,thing_id)
);

alter table world_alternate_thing add constraint world_alternate_thing_world_fkey
  foreign key(workspace_id,world_id) references world_identity(workspace_id,world_id);

-- One arrival records one look, however often its door hands the arrival over.
create unique index world_thing_look_one_per_crossing
  on world_thing_look(workspace_id,world_id,version_id,crossing_id)
  where crossing_id is not null;

-- The latest choice per thing, read by a version.
create index world_thing_look_latest
  on world_thing_look(workspace_id,world_id,version_id,thing_id,choice_id desc);

create function tg_world_thing_look_binding() returns trigger language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  return new;
end $fn$;

create trigger tg_world_thing_look_binding
before insert on world_thing_look
for each row execute function tg_world_thing_look_binding();

create function tg_world_thing_look_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception 'a look choice is appended and never changed' using errcode='23514';
end $fn$;

create trigger tg_world_thing_look_append_only
before update or delete on world_thing_look
for each row execute function tg_world_thing_look_append_only();

alter table world_thing_look enable row level security;
alter table world_thing_look force row level security;
create policy ws_isolation on world_thing_look
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

commit;
