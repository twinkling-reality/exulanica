-- 0218_a_saved_world_keeps_one_picture.sql
-- A saved world keeps one picture of itself, so every browser shows it on the world's card.
--
-- WHAT IT IS. A frame of the world's own first view as a page drew it: a JPEG or WebP of at most
-- 512 KiB, from 320 by 180 to 1280 by 720, walked whole by the server before it is kept (no
-- metadata, no embedded thumbnail, nothing after the picture; exulanica/world/saved_entry_pictures.py).
-- One per entry: a new picture replaces the old. It names what it shows (the entry's authored
-- version, the state the entry is saved at and the style version it was drawn in), so a page shows it
-- only while the world is still that. The server cannot draw a world; a page that may change the
-- world puts it after drawing.
--
-- NO PHOTOGRAPH. A world that holds a photograph (a personal source's, or any source attached to
-- an authored world) is refused a picture by the server's rules; this table holds renders of made
-- geometry and drawn figures only.
--
-- BYTES IN THE ROW. One bounded picture per held world is small beside the database, so it stays
-- in its row: a world's erasure removes it with the world's other rows, and no object store
-- namespace, stored kind or purge job is added.
--
-- ERASURE. The picture hangs from its entry. world_erase_rows (0195, last made again in 0213) deletes
-- the entry; a BEFORE DELETE trigger on saved_world_entry runs saved_world_entry_picture_erase, a
-- definer owned by exulanica_definer, which deletes the entry's picture first. The picture carries
-- 0195's guard, so nobody but the definers' owner deletes it. world_erase_rows is not made again
-- here.

begin;
select pg_advisory_xact_lock(119622309);

create table saved_world_entry_picture (
  workspace_id uuid not null,
  entry_id uuid not null,
  media_type text not null check(media_type in ('image/jpeg','image/webp')),
  bytes bytea not null,
  byte_size integer not null check(byte_size between 1 and 524288 and byte_size = octet_length(bytes)),
  sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
  width integer not null check(width between 320 and 1280),
  height integer not null check(height between 180 and 720),
  -- What it shows: the entry's authored version, the state the entry is saved at, and its look.
  authored_version_id uuid not null,
  authored_state_sha256 text not null check(authored_state_sha256 ~ '^[0-9a-f]{64}$'),
  style_version_id uuid not null,
  taken_by uuid not null,
  taken_at timestamptz not null default statement_timestamp(),
  primary key(workspace_id,entry_id),
  foreign key(workspace_id,entry_id) references saved_world_entry(workspace_id,entry_id)
);

comment on table saved_world_entry_picture is
  'One picture of a saved world''s own first view, for its card; deleted with its entry.';

-- Deleted only by the definers' owner, when its world is erased whole (0195's rule).
create trigger tg_world_record_erased_whole
before delete on saved_world_entry_picture
for each row execute function tg_world_record_erased_whole();

alter table saved_world_entry_picture enable row level security;
alter table saved_world_entry_picture force row level security;
create policy ws_isolation on saved_world_entry_picture
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

-- The entry takes its picture with it: run before the entry's own delete, by the definers' owner.
create function saved_world_entry_picture_erase() returns trigger
language plpgsql security definer as $fn$
begin
  delete from saved_world_entry_picture p
   where p.workspace_id = old.workspace_id and p.entry_id = old.entry_id;
  return old;
end $fn$;

do $$ begin
  execute format('alter function saved_world_entry_picture_erase() '
                 'set search_path = pg_catalog, %I, pg_temp', current_schema());
end $$;
revoke all on function saved_world_entry_picture_erase() from public;
grant select, delete on saved_world_entry_picture to exulanica_definer;
alter function saved_world_entry_picture_erase() owner to exulanica_definer;

create trigger tg_saved_world_entry_takes_its_picture
before delete on saved_world_entry
for each row execute function saved_world_entry_picture_erase();

do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on saved_world_entry_picture to %I', r);
      if r in ('exulanica_app','orimera_app') then
        execute format('grant insert,update on saved_world_entry_picture to %I', r);
      else
        execute format('revoke insert,update,delete on saved_world_entry_picture from %I', r);
      end if;
    end if;
  end loop;
end $$;

commit;
