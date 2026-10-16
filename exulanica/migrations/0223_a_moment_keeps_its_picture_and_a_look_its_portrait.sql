-- 0223_a_moment_keeps_its_picture_and_a_look_its_portrait.sql
-- A world's History shows each moment as a picture of the world then, framed on who was in it, and
-- each person in it as a small round portrait of their look.
--
-- WHAT THEY ARE. Frames a page drew: the server cannot draw a world. A moment's picture is the world
-- at the moment's version with the moment's people placed as the moment recorded them, seen from the
-- camera a framing recipe gives; a portrait is one look drawn alone. Each is a JPEG or WebP walked
-- whole by the server before it is kept (no metadata, no embedded thumbnail, nothing after the
-- picture; exulanica/world/moment_pictures.py): a moment's picture of at most 512 KiB, from 320 by
-- 180 to 1280 by 720; a portrait square, from 128 to 512 pixels, of at most 128 KiB.
--
-- KEPT ONCE. A picture is named by what it is of and the recipe it was drawn by: a moment's by the
-- moment and its recipe, a portrait by the look's digest and its recipe, within the world. The first
-- picture kept under a name stays; another under the same name is refused, so every page shows the
-- same picture and none is drawn twice. A new recipe (another framing, another renderer) is a new
-- name, kept beside the old.
--
-- NO PHOTOGRAPH. A world that holds a photograph (a personal source's, or any source attached to an
-- authored world now or before) is refused both by the server's rules; these tables hold renders of
-- made geometry and drawn figures only.
--
-- BYTES IN THE ROW. As 0218: bounded pictures stay in their rows, so a world's erasure removes them
-- with its other rows, and no object store namespace, stored kind or purge job is added.
--
-- A MOMENT THAT EXISTS. A moment's picture names a moment of world_society_moment (0221), by the
-- workspace and the moment's id, so no picture is kept for a moment nobody recorded.
--
-- ERASURE. A moment's picture goes with its moment: a BEFORE DELETE trigger on world_society_moment
-- runs world_moment_pictures_erase, a definer owned by exulanica_definer, which deletes that moment's
-- pictures (every recipe) first, so a society's erasure (society_erase_rows deletes its moments), a
-- world's and a workspace tombstone all reach them through the moment, and neither society_erase_rows
-- nor world_erase_rows is made again here. Both tables also hang from their world: world_erase_rows
-- (0195, last made again in 0219) deletes the world's world_identity row last, and a BEFORE DELETE
-- trigger on world_identity runs world_history_pictures_erase, a definer owned by exulanica_definer,
-- which deletes the world's moment pictures and portraits first. Both tables carry 0195's guard, so
-- nobody but the definers' owner deletes them.

begin;
select pg_advisory_xact_lock(119622309);

create table world_moment_picture (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  moment_id uuid not null,
  -- The recipe it was drawn by, as moment-framing.v1.json names it: a name and a version.
  recipe text not null check(recipe ~ '^[a-z][a-z0-9-]{0,47}/v[1-9][0-9]{0,5}$'),
  media_type text not null check(media_type in ('image/jpeg','image/webp')),
  bytes bytea not null,
  byte_size integer not null check(byte_size between 1 and 524288 and byte_size = octet_length(bytes)),
  sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
  width integer not null check(width between 320 and 1280),
  height integer not null check(height between 180 and 720),
  taken_by uuid not null,
  taken_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,moment_id,recipe),
  foreign key(workspace_id,world_id) references world_identity(workspace_id,world_id),
  foreign key(workspace_id,moment_id) references world_society_moment(workspace_id,moment_id)
);
create index world_moment_picture_by_digest on world_moment_picture(workspace_id,world_id,sha256);

comment on table world_moment_picture is
  'One picture of a moment of a world''s History, kept by the moment and its recipe; deleted with its moment or its world.';

create table world_look_portrait (
  workspace_id uuid not null,
  world_id text not null,
  look_sha256 text not null check(look_sha256 ~ '^[0-9a-f]{64}$'),
  recipe text not null check(recipe ~ '^[a-z][a-z0-9-]{0,47}/v[1-9][0-9]{0,5}$'),
  media_type text not null check(media_type in ('image/jpeg','image/webp')),
  bytes bytea not null,
  byte_size integer not null check(byte_size between 1 and 131072 and byte_size = octet_length(bytes)),
  sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
  width integer not null check(width between 128 and 512),
  height integer not null check(height = width),
  taken_by uuid not null,
  taken_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,world_id,look_sha256,recipe),
  foreign key(workspace_id,world_id) references world_identity(workspace_id,world_id)
);
create index world_look_portrait_by_digest on world_look_portrait(workspace_id,world_id,sha256);

comment on table world_look_portrait is
  'One round portrait of a look in a world, kept by the look''s digest and its recipe; deleted with its world.';

-- Deleted only by the definers' owner, when their world is erased whole (0195's rule).
create trigger tg_world_record_erased_whole
before delete on world_moment_picture
for each row execute function tg_world_record_erased_whole();
create trigger tg_world_record_erased_whole
before delete on world_look_portrait
for each row execute function tg_world_record_erased_whole();

do $$ declare t text; begin
  foreach t in array array['world_moment_picture', 'world_look_portrait'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using(workspace_id=current_workspace()) '
      'with check(workspace_id=current_workspace())', t
    );
  end loop;
end $$;

-- The world takes its History's pictures with it: run before its identity's own delete, by the
-- definers' owner.
create function world_history_pictures_erase() returns trigger
language plpgsql security definer as $fn$
begin
  delete from world_moment_picture p
   where p.workspace_id = old.workspace_id and p.world_id = old.world_id;
  delete from world_look_portrait p
   where p.workspace_id = old.workspace_id and p.world_id = old.world_id;
  return old;
end $fn$;

do $$ begin
  execute format('alter function world_history_pictures_erase() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function world_history_pictures_erase() from public;
grant select, delete on world_moment_picture to exulanica_definer;
grant select, delete on world_look_portrait to exulanica_definer;
alter function world_history_pictures_erase() owner to exulanica_definer;

create trigger tg_world_identity_takes_its_history_pictures
before delete on world_identity
for each row execute function world_history_pictures_erase();

-- A moment takes its pictures with it: run before the moment's own delete (a society's erasure, a
-- world's, a workspace tombstone), by the definers' owner.
create function world_moment_pictures_erase() returns trigger
language plpgsql security definer as $fn$
begin
  delete from world_moment_picture p
   where p.workspace_id = old.workspace_id and p.moment_id = old.moment_id;
  return old;
end $fn$;

do $$ begin
  execute format('alter function world_moment_pictures_erase() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function world_moment_pictures_erase() from public;
alter function world_moment_pictures_erase() owner to exulanica_definer;

create trigger tg_world_society_moment_takes_its_pictures
before delete on world_society_moment
for each row execute function world_moment_pictures_erase();

-- Kept once: the runtime inserts and reads, and never updates or deletes.
do $$
declare
  r text;
  t text;
begin
  foreach t in array array['world_moment_picture', 'world_look_portrait'] loop
    foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on %I to %I', t, r);
        if r in ('exulanica_app','orimera_app') then
          execute format('grant insert on %I to %I', t, r);
        else
          execute format('revoke insert,update,delete on %I from %I', t, r);
        end if;
      end if;
    end loop;
  end loop;
end $$;

commit;
