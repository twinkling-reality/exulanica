-- 0042_authored_world_objects.sql
-- Alternate world versions, authored objects, and the reviewed asset and behaviour catalogs.
--
-- This is a delta plane over the immutable structural snapshot, not an extension of it.  The
-- reasoning is in docs/world-objects-contract.md section 1 and it reduces to four facts about
-- 0020: the topology element schema is closed by `_exact_keys`, element identity is permanent,
-- snapshot history is append-only with one linear revision per world, and there is deliberately
-- no public topology mutation route.  A person's edit is none of those things.
--
-- Coordinates here are the same fixed-point integers migration 0020 uses, for the same reason:
-- exulanica.canonical refuses IEEE-754 in digest inputs, so the state token this plane compares
-- and swaps on is bytes an independent verifier can rebuild.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. Reviewed catalogs.  Global reviewed data, not tenant rows.
-- --------------------------------------------------------------------------------------------

-- The registry row is the reviewed decision.  The BYTES live in the content-addressed store and
-- are put there by exulanica.world.assets.seed_reviewed_assets, because a migration cannot write
-- to an object store and a schema that pretended otherwise would be claiming an asset is present
-- on the strength of a row.  A read reports `unavailable_asset` when the row is here and the
-- bytes are not; it never substitutes geometry.
create table world_reviewed_asset (
  asset_key       text primary key check (asset_key ~ '^[a-z][a-z0-9.-]*$'),
  title           text not null check (length(btrim(title)) > 0),
  summary         text not null check (length(btrim(summary)) > 0),
  media_type      text not null check (media_type = 'model/gltf-binary'),
  content_sha256  text not null unique check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size       int not null check (byte_size > 0),
  licence_id      text not null check (licence_id = 'CC0-1.0'),
  licence_sha256  text not null check (licence_sha256 ~ '^[0-9a-f]{64}$'),
  reviewed_at     timestamptz not null default now()
);

-- Digests pinned from exulanica/world/assets.py, which generates these meshes rather than
-- committing them.  Regenerating from source reproduces these exact values; if it ever does not,
-- tests/test_world_objects.py fails on the mismatch rather than the schema drifting quietly.
insert into world_reviewed_asset
  (asset_key,title,summary,media_type,content_sha256,byte_size,licence_id,licence_sha256) values
  ('cc0.marker-cube','Marker cube','A half-metre cube resting on the ground plane.',
   'model/gltf-binary',
   'b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9',780,'CC0-1.0',
   '6f89ee797a8cb18ff880d0d38840884953b437230709a84dfa94cf2a5869ea6f'),
  ('cc0.marker-pillar','Marker pillar','A two-metre square pillar resting on the ground plane.',
   'model/gltf-binary',
   'b960af0f1c85f6c41a38ce09727cd19bc2bbc0e21bb8f3f111707af9b90b2737',784,'CC0-1.0',
   '6f89ee797a8cb18ff880d0d38840884953b437230709a84dfa94cf2a5869ea6f'),
  ('cc0.marker-plate','Marker plate','A one-metre flat square lying on the ground plane.',
   'model/gltf-binary',
   '19425a058c19d4009392093e770c7f115a68d020b67e0bdce83abdad4b5a2f6e',684,'CC0-1.0',
   '6f89ee797a8cb18ff880d0d38840884953b437230709a84dfa94cf2a5869ea6f');

-- Shaped like interaction_capability_registry and deliberately NOT that table.  Its category
-- check admits only comfort/navigation/disclosure/initiative and its values are one per world;
-- an object behaviour is per object, and two objects in one version may hold different bounds.
create table world_object_behaviour_registry (
  behaviour_key      text not null check (behaviour_key ~ '^[a-z][a-z0-9.-]*$'),
  behaviour_version  int not null check (behaviour_version >= 1),
  summary            text not null check (length(btrim(summary)) > 0),
  parameters         jsonb not null check (jsonb_typeof(parameters) = 'object'),
  registered_at      timestamptz not null default now(),
  primary key (behaviour_key, behaviour_version)
);

-- The one behaviour the first milestone names: bounded motion.  Trigger, stop and reset are the
-- renderer's controls over this motion, not stored parameters; what the registry owns is the
-- bound, so an unsupported or out-of-range request fails before it is persisted.
insert into world_object_behaviour_registry (behaviour_key,behaviour_version,summary,parameters)
values ('motion.bounded-path',1,
  'Bounded reversing travel along one axis, with renderer trigger, stop and reset controls.',
  '{"travel_mm":{"kind":"integer","minimum":100,"maximum":10000,"default":1000},
    "period_milliseconds":{"kind":"integer","minimum":500,"maximum":60000,"default":4000},
    "axis":{"kind":"choice","choices":["x","y","z"],"default":"x"},
    "easing":{"kind":"choice","choices":["linear","smooth"],"default":"smooth"}}');

-- --------------------------------------------------------------------------------------------
-- 2. The alternate version.
-- --------------------------------------------------------------------------------------------

create table world_alternate_version (
  version_id          uuid primary key default uuidv7(),
  workspace_id        uuid not null,
  world_id            text not null check (length(world_id) between 1 and 200),
  source_snapshot_id  uuid not null,
  parent_version_id   uuid,
  title               text not null check (length(btrim(title)) between 1 and 200),
  origin              text not null check (origin = 'authored'),
  style_version_id    uuid,
  -- The optimistic concurrency token.  Content-derived rather than a counter, so two edits that
  -- produce identical state are the identical base, matching base_topology_digest's behaviour.
  state_sha256        text not null check (state_sha256 ~ '^[0-9a-f]{64}$'),
  edit_seq            bigint not null default 0 check (edit_seq >= 0),
  created_by          uuid not null,
  created_at          timestamptz not null default now(),
  unique (workspace_id, world_id, version_id),
  -- The composite key is the isolation.  A version cannot name another workspace's snapshot,
  -- and it cannot name a snapshot of a different world, because both are in the referenced key.
  foreign key (workspace_id, world_id, source_snapshot_id)
    references world_structure_snapshot(workspace_id, world_id, snapshot_id),
  foreign key (workspace_id, world_id, parent_version_id)
    references world_alternate_version(workspace_id, world_id, version_id),
  foreign key (workspace_id, world_id, style_version_id)
    references world_style_version(workspace_id, world_id, version_id)
);

-- --------------------------------------------------------------------------------------------
-- 3. The delta.  Additions and their removals, and overrides of source elements.
-- --------------------------------------------------------------------------------------------

create table world_alternate_object (
  workspace_id        uuid not null,
  world_id            text not null,
  version_id          uuid not null,
  -- Exactly exulanica.world.objects.OBJECT_ID_PATTERN.  A test compares the two strings,
  -- because a caller whose id passes Python and fails here gets a 500 where the surface
  -- promises a 422.
  object_id           text not null
                        check (object_id ~ '^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$'),
  asset_key           text not null references world_reviewed_asset(asset_key),
  region_id           text not null check (length(region_id) between 1 and 500),
  x_mm                bigint not null,
  y_mm                bigint not null,
  z_mm                bigint not null,
  yaw_microradians    bigint not null check (yaw_microradians between 0 and 6283185),
  scale_milli         bigint not null check (scale_milli between 1 and 1000000),
  origin_kind         text not null check (origin_kind = 'authored'),
  -- Chosen by the person, never inferred.  Product direction is explicit that upload alone
  -- establishes no personal association and that the first slice asks rather than classifies.
  origin_role         text not null check (origin_role in ('fictional','personal')),
  behaviour_key       text,
  behaviour_version   int,
  behaviour_parameters jsonb check (
                        behaviour_parameters is null
                        or jsonb_typeof(behaviour_parameters) = 'object'),
  -- A removal is stored, not executed, so the id stays stable and undo restores rather than
  -- resurrects.
  removed             boolean not null default false,
  created_edit_id     uuid not null,
  last_edit_id        uuid not null,
  primary key (workspace_id, world_id, version_id, object_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version(workspace_id, world_id, version_id),
  foreign key (behaviour_key, behaviour_version)
    references world_object_behaviour_registry(behaviour_key, behaviour_version),
  constraint world_alternate_object_behaviour_is_complete check (
    (behaviour_key is null and behaviour_version is null and behaviour_parameters is null) or
    (behaviour_key is not null and behaviour_version is not null
                               and behaviour_parameters is not null))
);

-- Suppressing or moving a SOURCE element.  Stored, digested and read back, because the World
-- state contract requires an alternate version to store removals and transforms of its source
-- and the package extension cannot be specified against half a delta.  No public mutation route
-- writes this yet: hiding a structural element changes what a person can reach, which is a
-- protected-value review rather than an object edit.
create table world_alternate_element_override (
  workspace_id      uuid not null,
  world_id          text not null,
  version_id        uuid not null,
  element_id        text not null check (length(element_id) between 1 and 500),
  suppressed        boolean not null default false,
  x_mm              bigint,
  y_mm              bigint,
  z_mm              bigint,
  yaw_microradians  bigint check (yaw_microradians between 0 and 6283185),
  scale_milli       bigint check (scale_milli between 1 and 1000000),
  last_edit_id      uuid not null,
  primary key (workspace_id, world_id, version_id, element_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version(workspace_id, world_id, version_id),
  constraint world_alternate_override_transform_is_complete check (
    (x_mm is null and y_mm is null and z_mm is null
                  and yaw_microradians is null and scale_milli is null) or
    (x_mm is not null and y_mm is not null and z_mm is not null
                      and yaw_microradians is not null and scale_milli is not null)),
  -- An override that neither suppresses nor moves is a row with no meaning.
  constraint world_alternate_override_says_something check (
    suppressed or x_mm is not null)
);

-- --------------------------------------------------------------------------------------------
-- 4. The edit log.  Append-only, and the reason undo is a stored fact.
-- --------------------------------------------------------------------------------------------

create table world_alternate_version_edit (
  edit_id             uuid primary key default uuidv7(),
  workspace_id        uuid not null,
  world_id            text not null,
  version_id          uuid not null,
  edit_seq            bigint not null check (edit_seq >= 1),
  kind                text not null check (
                        kind in ('add_object','move_object','remove_object',
                                 'suppress_element','transform_element','undo')),
  object_id           text,
  element_id          text,
  undone_edit_id      uuid,
  base_state_sha256   text not null check (base_state_sha256 ~ '^[0-9a-f]{64}$'),
  result_state_sha256 text not null check (result_state_sha256 ~ '^[0-9a-f]{64}$'),
  -- The documents on either side of the edit.  This is what makes undo a persisted fact rather
  -- than the client's memory of one.
  before_document     jsonb check (before_document is null
                                   or jsonb_typeof(before_document) = 'object'),
  after_document      jsonb check (after_document is null
                                   or jsonb_typeof(after_document) = 'object'),
  actor               uuid not null,
  recorded_at         timestamptz not null default now(),
  unique (workspace_id, world_id, version_id, edit_seq),
  unique (workspace_id, world_id, edit_id),
  foreign key (workspace_id, world_id, version_id)
    references world_alternate_version(workspace_id, world_id, version_id),
  foreign key (workspace_id, world_id, undone_edit_id)
    references world_alternate_version_edit(workspace_id, world_id, edit_id),
  constraint world_alternate_edit_undo_names_its_target check (
    (kind = 'undo') = (undone_edit_id is not null)),
  constraint world_alternate_edit_names_its_subject check (
    (kind in ('add_object','move_object','remove_object') and object_id is not null
                                                          and element_id is null) or
    (kind in ('suppress_element','transform_element') and element_id is not null
                                                      and object_id is null) or
    (kind = 'undo'))
);

-- --------------------------------------------------------------------------------------------
-- 5. Immutability.  History never changes; current state is the intentional exception.
-- --------------------------------------------------------------------------------------------

create function tg_world_alternate_append_only() returns trigger language plpgsql as $fn$
begin
  raise exception '% is append-only', tg_table_name
    using errcode = 'integrity_constraint_violation';
end $fn$;

create trigger tg_world_alternate_version_edit_append_only
  before update or delete on world_alternate_version_edit
  for each row execute function tg_world_alternate_append_only();

-- A version's identity, source and lineage are fixed at creation.  Only the state token, the
-- edit counter and the appearance reference move, and they move together with an appended edit.
create function tg_world_alternate_version_state_only() returns trigger language plpgsql as $fn$
begin
  if (to_jsonb(new) - 'state_sha256' - 'edit_seq' - 'style_version_id') is distinct from
     (to_jsonb(old) - 'state_sha256' - 'edit_seq' - 'style_version_id') then
    raise exception 'alternate version identity, source and lineage are immutable'
      using errcode = 'integrity_constraint_violation';
  end if;
  if new.edit_seq < old.edit_seq then
    raise exception 'alternate version edit sequence cannot move backwards'
      using errcode = 'integrity_constraint_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_alternate_version_state_only
  before update on world_alternate_version
  for each row execute function tg_world_alternate_version_state_only();

create function tg_world_alternate_version_no_delete() returns trigger language plpgsql as $fn$
begin
  raise exception 'an alternate version is never deleted; deletion invalidates its source'
    using errcode = 'integrity_constraint_violation';
end $fn$;

create trigger tg_world_alternate_version_no_delete
  before delete on world_alternate_version
  for each row execute function tg_world_alternate_version_no_delete();

-- --------------------------------------------------------------------------------------------
-- 6. Workspace isolation, and read-only reviewed catalogs.
-- --------------------------------------------------------------------------------------------

do $$
declare
  t text;
begin
  foreach t in array array[
    'world_alternate_version','world_alternate_object',
    'world_alternate_element_override','world_alternate_version_edit'
  ] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy ws_isolation on %I using (workspace_id = current_workspace()) '
      'with check (workspace_id = current_workspace())', t);
  end loop;
end $$;

-- Reviewed catalogs are migration data.  The runtime reads them and cannot write them, the same
-- rule 0017 and 0021 apply to their own registries.
do $$
declare
  r text;
  t text;
begin
  foreach r in array array['exulanica_app','exulanica_ro','orimera_app','orimera_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      foreach t in array array['world_reviewed_asset','world_object_behaviour_registry'] loop
        execute format('revoke insert,update,delete on %I from %I', t, r);
        execute format('grant select on %I to %I', t, r);
      end loop;
    end if;
  end loop;
end $$;

create index world_alternate_version_history_idx
  on world_alternate_version (workspace_id, world_id, created_at desc, version_id);
create index world_alternate_version_source_idx
  on world_alternate_version (workspace_id, world_id, source_snapshot_id);
create index world_alternate_object_live_idx
  on world_alternate_object (workspace_id, world_id, version_id) where not removed;
create index world_alternate_edit_order_idx
  on world_alternate_version_edit (workspace_id, world_id, version_id, edit_seq desc);

commit;
