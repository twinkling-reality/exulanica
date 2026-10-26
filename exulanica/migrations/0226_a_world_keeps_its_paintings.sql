-- 0226_a_world_keeps_its_paintings.sql
-- A made world can be painted: an open picture model paints the world's own views from the person's words, held by
-- depth to the world's exact layout, so each world looks like itself and unlike every other.
--
-- WHAT THEY ARE. Pictures a model made, not frames a page drew: invented appearance on exact structure. Each is a
-- JPEG or WebP walked whole by the server before it is kept (no metadata, no embedded thumbnail, nothing after the
-- picture; exulanica/world/world_paintings.py), of at most 512 KiB, from 320 by 180 to 1280 by 720, as a saved
-- world's card picture (0218). Beside the bytes a painting keeps what it is of and how it was made: the view's name
-- and its camera (the lens and the camera-to-world matrix the structure was drawn from), the words it was painted
-- from (the prompt written from the world's sentence and notes, the words kept out, the seed), the painter (each
-- model's repository, revision and licence, the steps and the control), the share of the structure's edges the
-- painting kept, and its share of the run's cost.
--
-- WHO KEEPS THEM. The operator's painting run, which captures the structure through the install's own page, paints
-- it on a GPU and keeps what passes its hold. No route writes a painting; the API reads them.
--
-- NO PHOTOGRAPH. A world that holds or held a photograph (a personal source's, or any source attached to an
-- authored world now or before) is given no painting: nothing derived from a photograph is sent to a GPU or kept
-- here (the repository refuses it, as 0223's pictures).
--
-- BYTES IN THE ROW. As 0218 and 0223: bounded pictures stay in their rows, so a world's erasure removes them with its
-- other rows, and no object store namespace, stored kind or purge job is added.
--
-- ERASURE. world_erase_rows (0195, last made again in 0219) deletes the world's world_identity row last, and the
-- identity's BEFORE DELETE trigger (0223) runs world_history_pictures_erase, a definer owned by exulanica_definer,
-- made again here to delete the world's paintings too, with its History's pictures, first; so a world's erasure
-- and a workspace tombstone reach them, and world_erase_rows is not made again here. The table carries 0195's
-- guard, so nobody but the definers' owner deletes it.

begin;
select pg_advisory_xact_lock(119622309);

create table world_painting (
  workspace_id uuid not null,
  world_id text not null,
  -- The view's name within the world's painting: its first view, or a heading from it.
  view text not null check(view ~ '^[a-z][a-z0-9-]{0,31}$'),
  -- The painting recipe, a name and a version, as the run states it.
  recipe text not null check(recipe ~ '^[a-z][a-z0-9-]{0,47}/v[1-9][0-9]{0,5}$'),
  media_type text not null check(media_type in ('image/jpeg','image/webp')),
  bytes bytea not null,
  byte_size integer not null check(byte_size between 1 and 524288 and byte_size = octet_length(bytes)),
  sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
  width integer not null check(width between 320 and 1280),
  height integer not null check(height between 180 and 720),
  camera jsonb not null check(jsonb_typeof(camera) = 'object' and octet_length(camera::text) <= 4096),
  words jsonb not null check(jsonb_typeof(words) = 'object' and octet_length(words::text) <= 8192),
  painter jsonb not null check(jsonb_typeof(painter) = 'object' and octet_length(painter::text) <= 8192),
  held_permille integer not null check(held_permille between 0 and 1000),
  cost_microusd bigint not null check(cost_microusd >= 0),
  run_id text not null check(run_id ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
  made_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,world_id,sha256),
  foreign key(workspace_id,world_id) references world_identity(workspace_id,world_id)
);
create index world_painting_by_view on world_painting(workspace_id,world_id,view,made_at desc);

comment on table world_painting is
  'A picture an open model painted of a world''s own view from its words, held to its layout; deleted with its world.';

-- Deleted only by the definers' owner, when its world is erased whole (0195's rule).
create trigger tg_world_record_erased_whole
before delete on world_painting
for each row execute function tg_world_record_erased_whole();

alter table world_painting enable row level security;
alter table world_painting force row level security;
create policy ws_isolation on world_painting using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- The world takes its History's pictures and its paintings with it: run before its identity's own delete, by the
-- definers' owner (0223's function, made again with one statement more).
create or replace function world_history_pictures_erase() returns trigger
language plpgsql security definer as $fn$
begin
  delete from world_moment_picture p
   where p.workspace_id = old.workspace_id and p.world_id = old.world_id;
  delete from world_look_portrait p
   where p.workspace_id = old.workspace_id and p.world_id = old.world_id;
  delete from world_painting p
   where p.workspace_id = old.workspace_id and p.world_id = old.world_id;
  return old;
end $fn$;

do $$ begin
  execute format('alter function world_history_pictures_erase() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function world_history_pictures_erase() from public;
grant select, delete on world_painting to exulanica_definer;
alter function world_history_pictures_erase() owner to exulanica_definer;

-- Kept once: the operator's run inserts and every reader reads; nothing updates or deletes.
do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on world_painting to %I', r);
      if r in ('exulanica_app','orimera_app') then
        execute format('grant insert on world_painting to %I', r);
      else
        execute format('revoke insert,update,delete on world_painting from %I', r);
      end if;
    end if;
  end loop;
end $$;

commit;
