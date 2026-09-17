-- 0076_texture_set_classes.sql
-- What kind of surface each pinned texture set is: its container profile and its material class.
--
-- A renderer draws a texture set by the class it declares (opaque, cutout, decal or glazing), and
-- a container's profile says how its maps are laid out, so both are reviewed facts about pinned
-- bytes, like the digest 0065 pins.  They are stated here, in a table of their own keyed by the
-- same (set_id, version), rather than as columns added to world_texture_set: adding a column that
-- the eight 0065 rows must fill would mean updating pinned rows, and a pinned row's wall is never
-- lowered, not even inside a migration and not for one statement.  A reader joins the two tables.
--
-- The eight sets 0065 pinned are exulanica.texture-set/v1 containers, which are opaque by
-- definition, with the four-map v1 layout.  Every later set states its own profile and class here,
-- in the migration that pins it.
--
-- Every number here is an integer, and every name is one the texture package's readers already
-- refuse any other spelling of (exulanica/materials/classes.py and
-- web/packages/loom-texture/src/classes.ts).

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The layouts a profile and class allow.
-- --------------------------------------------------------------------------------------------

-- Every channel layout a pinned set of this profile and class may have, as the manifest states
-- channels: an array of layouts, each an array of maps in stored order.  A v1 container is opaque
-- with the four-map v1 layout, or nothing.  A v2 container of a class has the layout a procedural
-- maker bakes, or one a model-made maker ships: the colour map, the normal with its z if the model
-- produced one, the class's surface map, and the height if the model produced one.  An unknown
-- profile or class allows nothing.  Immutable, so the answer is a property of the two names; the
-- readers' own tables must agree with it, and tests/test_texture_set_class_migration.py compares
-- them for every pair.
create function texture_set_layouts(container_profile text, material_class text)
returns jsonb language sql immutable parallel safe as $fn$
  with maps as (
    select
      '{"map":"base_color","components":3,"holds":["red","green","blue"],"srgb":true}'::jsonb
        as base_color,
      '{"map":"base_color_coverage","components":4,"holds":["red","green","blue","coverage"],"srgb":true}'::jsonb
        as base_color_coverage,
      '{"map":"normal","components":3,"holds":["normal_x","normal_y","normal_z"],"srgb":false}'::jsonb
        as normal_xyz,
      '{"map":"normal","components":2,"holds":["normal_x","normal_y"],"srgb":false}'::jsonb
        as normal_xy,
      '{"map":"orm","components":3,"holds":["occlusion","roughness","metalness"],"srgb":false}'::jsonb
        as orm,
      '{"map":"transmission_roughness","components":2,"holds":["transmission","roughness"],"srgb":false}'::jsonb
        as transmission_roughness,
      '{"map":"height","components":1,"holds":["height"],"srgb":false}'::jsonb
        as height
  ),
  class_maps as (
    select
      case when material_class in ('cutout', 'decal') then base_color_coverage else base_color end
        as colour,
      case when material_class = 'glazing' then transmission_roughness else orm end
        as surface,
      normal_xy, normal_xyz, height
    from maps
  ),
  candidates (ordinal, layout) as (
    -- What a procedural maker bakes: glazing has no normal, every other class a two-component one.
    select 0, case when material_class = 'glazing'
                   then jsonb_build_array(colour, surface)
                   else jsonb_build_array(colour, normal_xy, surface) end
    from class_maps
    union all
    -- What a model-made maker ships, by whether it produced a normal and a height.
    select 1, jsonb_build_array(colour, surface) from class_maps
    union all
    select 2, jsonb_build_array(colour, surface, height) from class_maps
    union all
    select 3, jsonb_build_array(colour, normal_xyz, surface) from class_maps
    union all
    select 4, jsonb_build_array(colour, normal_xyz, surface, height) from class_maps
  )
  select case
    when container_profile = 'exulanica.texture-set/v1' and material_class = 'opaque' then
      (select jsonb_build_array(jsonb_build_array(base_color, normal_xyz, orm, height)) from maps)
    when container_profile = 'exulanica.texture-set/v2'
         and material_class in ('opaque', 'cutout', 'decal', 'glazing') then
      (select jsonb_agg(layout order by first)
       from (select layout, min(ordinal) as first from candidates group by layout) as distinct_layouts)
    else '[]'::jsonb
  end
$fn$;

-- --------------------------------------------------------------------------------------------
-- 2. The classes.  Global reviewed data, like the pins it describes.
-- --------------------------------------------------------------------------------------------

-- A global catalog, exactly like world_texture_set: no workspace_id, no isolation policy and no
-- forced row-level security, because every workspace reads the same pinned sets.
create table world_texture_set_class (
  set_id             text not null,
  version            int not null,
  container_profile  text not null
    check (container_profile in ('exulanica.texture-set/v1', 'exulanica.texture-set/v2')),
  material_class     text not null
    check (material_class in ('opaque', 'cutout', 'decal', 'glazing')),
  primary key (set_id, version),
  foreign key (set_id, version) references world_texture_set (set_id, version),
  -- A v1 container is the opaque four-map layout by definition.
  check (container_profile = 'exulanica.texture-set/v2' or material_class = 'opaque')
);

-- A row is a fact about pinned bytes, so like the pin it never changes or disappears, and only the
-- role that owns the table (the role that runs migrations) adds one.  On insert the set's pinned
-- channels must be one of the layouts its profile and class allow: a class that does not describe
-- the bytes is refused, whoever states it.
create function tg_world_texture_set_class_is_migration_data() returns trigger language plpgsql as $fn$
declare
  pinned jsonb;
begin
  if tg_op <> 'INSERT' then
    raise exception
      'world_texture_set_class rows state what pinned bytes are; a set that changes is a new version'
      using errcode = 'integrity_constraint_violation';
  end if;
  if not pg_has_role(current_user,
                     (select c.relowner from pg_class c where c.oid = tg_relid),
                     'MEMBER') then
    raise exception 'world_texture_set_class is written by migrations, not by %', current_user
      using errcode = 'insufficient_privilege';
  end if;
  select s.channels into pinned
  from world_texture_set s
  where s.set_id = new.set_id and s.version = new.version;
  if pinned is null or not exists (
    select 1 from jsonb_array_elements(texture_set_layouts(new.container_profile, new.material_class))
      as allowed(layout)
    where allowed.layout = pinned
  ) then
    raise exception 'the channels pinned for % version % are not a layout of % class %',
      new.set_id, new.version, new.container_profile, new.material_class
      using errcode = 'check_violation';
  end if;
  return new;
end $fn$;

create trigger tg_world_texture_set_class_is_migration_data
  before insert or update or delete on world_texture_set_class
  for each row execute function tg_world_texture_set_class_is_migration_data();

-- --------------------------------------------------------------------------------------------
-- 3. No set is pinned without its class.
-- --------------------------------------------------------------------------------------------

-- A migration that pins a set states its profile and class in the same transaction.  Checked at
-- commit, so the set's row and its class row may be inserted in either order; a transaction that
-- pins a set and states nothing about it does not commit.  This adds a wall to world_texture_set
-- and lowers none: 0065's trigger still refuses every update, delete and non-owner insert.
create function tg_world_texture_set_states_its_class() returns trigger language plpgsql as $fn$
begin
  if not exists (
    select 1 from world_texture_set_class c
    where c.set_id = new.set_id and c.version = new.version
  ) then
    raise exception
      'texture set % version % is pinned without its container profile and material class',
      new.set_id, new.version
      using errcode = 'integrity_constraint_violation';
  end if;
  return null;
end $fn$;

create constraint trigger tg_world_texture_set_states_its_class
  after insert on world_texture_set
  deferrable initially deferred
  for each row execute function tg_world_texture_set_states_its_class();

-- --------------------------------------------------------------------------------------------
-- 4. The sets pinned so far.
-- --------------------------------------------------------------------------------------------

-- Batch 1 of the texture lane's Tier C: the first sets that state a class, pinned as 0065 pins,
-- from assets/textures/manifest.json, which loom-texture bakes from source.  Rebaking reproduces
-- these exact values; web/packages/loom-texture's published test and
-- tests/test_texture_set_class_migration.py fail on a mismatch.  Each packs its class's maps.
insert into world_texture_set
  (set_id,version,title,summary,media_type,truth,content_sha256,byte_size,width,height,
   extent_u_mm,extent_v_mm,channels,licence_id,licence_sha256)
select v.set_id,v.version,v.title,v.summary,'application/vnd.exulanica.texture-set','invented',
       v.content_sha256,v.byte_size,v.width,v.height,v.extent_u_mm,v.extent_v_mm,v.channels,
       'CC0-1.0',
       'd51d213f1f5d94acb27403d616b29007802618979c106b075fdbd399fa86310f'
from (values
  ('cc0.broadleaf-foliage',1,'Broadleaf foliage',
   'The outer leaves of a broadleaf street tree, in clumps with gaps between them, for a canopy seen from the street.',
   '62c58628a7059ea546565a29c1fde6f9b393de3be3fa3ddaaa28d60e7dd4ace2',2361424,512,512,2000,2000,
   '[{"components":4,"holds":["red","green","blue","coverage"],"map":"base_color_coverage","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb),
  ('cc0.float-glazing',1,'Float glazing',
   'Clear soda-lime float glass, mostly clean, with patches of fine dust, occasional rain streaks and rare handling marks.',
   '8f8f6663e238e2e40d9f61a98d434ef4aa8323e33c65447c4201b8ee571a6708',5244576,1024,1024,2000,2000,
   '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
     {"components":2,"holds":["transmission","roughness"],"map":"transmission_roughness","srgb":false}]'::jsonb),
  ('cc0.tree-bark',1,'Tree bark',
   'The furrowed bark of a mature broadleaf street tree, with interlacing furrows, cracked plates and patches of lichen.',
   '97fe363dbb2bc398b9be7956deb1b272698363f723d91028b04f56f91e9e0c62',2099104,512,512,1000,1000,
   '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb)
) as v(set_id,version,title,summary,content_sha256,byte_size,width,height,extent_u_mm,extent_v_mm,
       channels);

-- Every set's class: the eight 0065 pinned are v1 containers, opaque, and batch 1's are v2.
insert into world_texture_set_class (set_id, version, container_profile, material_class) values
  ('cc0.brick-running-bond', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.broadleaf-foliage', 1, 'exulanica.texture-set/v2', 'cutout'),
  ('cc0.carriageway-asphalt', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.cast-concrete', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.float-glazing', 1, 'exulanica.texture-set/v2', 'glazing'),
  ('cc0.footway-paving', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.kerb-stone', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.limestone-ashlar', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.painted-render', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.storefront-metal', 1, 'exulanica.texture-set/v1', 'opaque'),
  ('cc0.tree-bark', 1, 'exulanica.texture-set/v2', 'opaque');

-- --------------------------------------------------------------------------------------------
-- 5. Read-only for the runtime.
-- --------------------------------------------------------------------------------------------

-- The same rule 0065 applies to world_texture_set, for the two runtime roles exulanica.db.roles
-- provisions.  A role this cluster does not have is skipped rather than failing the migration.
do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke insert,update,delete on %I from %I', 'world_texture_set_class', r);
      execute format('grant select on %I to %I', 'world_texture_set_class', r);
    end if;
  end loop;
end $$;

commit;
