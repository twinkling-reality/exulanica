-- A thing placed in an authored version by its kind: a knight by the well, a sword on the ground,
-- the gate visitors arrive through.
--
-- WHAT IS PLACED IS A KIND, NOT AN ASSET. A placed thing names a shipped thing kind by key, version
-- and the SHA-256 of its canonical document (exulanica/things/kinds.py), never a look and never a
-- mesh: how it is drawn is a look chosen for it, and what it does is its kind's and the
-- simulation's. Which kinds are shipped is the repository's catalog, which a database cannot read,
-- so the application checks the kind at its digest before it writes; this table holds the shape
-- and holds the kind fixed once placed.
--
-- AT ITS KIND'S OWN SIZE. A kind's figures are its own (a knight's height, a sword's box), so a
-- placed thing's pose has no scale: x, y, z and yaw, region-local as every authored object's.
--
-- Its id is the author's, unique within the version, and every key here includes workspace_id, so
-- one workspace's ids say nothing about another's. Shaped on world_alternate_point_map_instance
-- (0093) and its undo columns (0088); the edit log gains a thing_id subject column, and both edit
-- CHECKs are restated from 0096 with the three thing kinds added.
begin;
select pg_advisory_xact_lock(119622309);

create table world_alternate_thing (
  workspace_id uuid not null,
  world_id text not null,
  version_id uuid not null,
  thing_id text not null
    check(thing_id ~ '^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$'),
  kind text not null check(kind ~ '^[a-z][a-z0-9_]{0,47}$'),
  kind_version integer not null check(kind_version between 1 and 10000),
  kind_sha256 bytea not null check(octet_length(kind_sha256)=32),
  region_id text not null check(length(region_id) between 1 and 500),
  x_mm bigint not null check(abs(x_mm)<=1000000000),
  y_mm bigint not null check(abs(y_mm)<=1000000000),
  z_mm bigint not null check(abs(z_mm)<=1000000000),
  yaw_microradians bigint not null check(yaw_microradians between 0 and 6283185),
  origin_kind text not null check(origin_kind='authored'),
  origin_role text not null check(origin_role in ('fictional','personal')),
  removed boolean not null default false,
  addition_undone boolean not null default false,
  created_edit_id uuid not null,
  last_edit_id uuid not null,
  -- 0088's rule for an undone addition: the row is retained rather than deleted, and a retained
  -- row is always removed and always names the edit that reversed it.
  constraint world_alternate_thing_undone_addition_is_removed check (
    not addition_undone or (removed and created_edit_id <> last_edit_id)
  ),
  primary key(workspace_id,world_id,version_id,thing_id),
  foreign key(workspace_id,world_id,version_id)
    references world_alternate_version(workspace_id,world_id,version_id)
);

-- What a placed thing IS never changes after it is placed: a move changes its pose and region, a
-- removal and an undo change whether it is there. The one other update is a same-id re-add over a
-- retained undone row (0088's rule), which is a new placement and may name any kind.
create function tg_world_thing_binding() returns trigger language plpgsql as $fn$
begin
  if tg_op='UPDATE' and not (old.addition_undone and not new.addition_undone) then
    if (to_jsonb(new)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'removed' - 'addition_undone' - 'last_edit_id')
       is distinct from
       (to_jsonb(old)
          - 'region_id' - 'x_mm' - 'y_mm' - 'z_mm' - 'yaw_microradians'
          - 'removed' - 'addition_undone' - 'last_edit_id')
    then
      raise exception 'a placed thing keeps the kind and origin it was placed with'
        using errcode='23514';
    end if;
  end if;
  return new;
end $fn$;

create trigger tg_world_thing_binding
before update on world_alternate_thing
for each row execute function tg_world_thing_binding();

alter table world_alternate_thing enable row level security;
alter table world_alternate_thing force row level security;
create policy ws_isolation on world_alternate_thing
  using(workspace_id=current_workspace())
  with check(workspace_id=current_workspace());

create index world_alternate_thing_live_idx
  on world_alternate_thing(workspace_id,world_id,version_id)
  where not removed;

alter table world_alternate_version_edit
  add column thing_id text;
alter table world_alternate_version_edit
  drop constraint world_alternate_version_edit_kind_check;
alter table world_alternate_version_edit
  add constraint world_alternate_version_edit_kind_check check(
    kind in ('add_object','move_object','remove_object','set_object_behaviour',
             'suppress_element','transform_element',
             'add_environment','move_environment','remove_environment',
             'add_point_map','move_point_map','remove_point_map',
             'add_thing','move_thing','remove_thing','undo')
  );
alter table world_alternate_version_edit
  drop constraint world_alternate_edit_names_its_subject;
alter table world_alternate_version_edit
  add constraint world_alternate_edit_names_its_subject check(
    (kind in ('add_object','move_object','remove_object','set_object_behaviour')
      and object_id is not null and element_id is null and environment_instance_id is null
      and point_map_instance_id is null and thing_id is null)
    or
    (kind in ('suppress_element','transform_element')
      and element_id is not null and object_id is null and environment_instance_id is null
      and point_map_instance_id is null and thing_id is null)
    or
    (kind in ('add_environment','move_environment','remove_environment')
      and environment_instance_id is not null and object_id is null and element_id is null
      and point_map_instance_id is null and thing_id is null)
    or
    (kind in ('add_point_map','move_point_map','remove_point_map')
      and point_map_instance_id is not null and object_id is null and element_id is null
      and environment_instance_id is null and thing_id is null)
    or
    (kind in ('add_thing','move_thing','remove_thing')
      and thing_id is not null and object_id is null and element_id is null
      and environment_instance_id is null and point_map_instance_id is null)
    or kind='undo'
  );

comment on table world_alternate_thing is
  'A thing an author placed in an authored version, by a shipped kind''s key, version and digest, '
  'at the kind''s own size. What it looks like and what it does are not stored here.';

commit;
