-- 0065_texture_set_digests.sql
-- The reviewed texture set catalog: every baked set, pinned by version and content digest.
--
-- web/packages/loom-texture bakes each set offline into a self-describing container and publishes
-- it content-addressed under assets/textures/, with manifest.json as the one index.  This file is
-- the reviewed decision about those bytes, in the shape 0042 gives world_reviewed_asset: the row
-- names a digest, and the bytes live somewhere else.
--
-- The id names the set, the version is a bake input, and the digest names the bytes.  So the key
-- is (set_id, version) and the digest is unique on its own.  A rebake that changes bytes is a new
-- version, in a new row, in a new migration; a pinned (set_id, version) never names other bytes,
-- and the trigger below is what makes that a property rather than a promise.  The grammar's
-- catalog digest covers the pin {set_id, version, content_sha256} it reads from the same manifest
-- these rows were copied from, so these three columns are replay inputs.
--
-- Every number here is an integer, in texels, bytes or whole millimetres: exulanica.canonical
-- refuses IEEE-754 in digest inputs, and every container header is canonical JSON.

begin;

select pg_advisory_xact_lock(119622309);

-- --------------------------------------------------------------------------------------------
-- 1. The catalog.  Global reviewed data, not tenant rows.
-- --------------------------------------------------------------------------------------------

-- The registry row is the reviewed decision.  The BYTES live in the content-addressed store and
-- are put there by exulanica.world.texture_assets.seed_texture_sets, because a migration cannot
-- write to an object store and a schema that pretended otherwise would be claiming a texture is
-- present on the strength of a row.  A read reports the texture unavailable when the row is here
-- and the bytes are not; it never substitutes a default map or a flat colour.
--
-- A global catalog, exactly like world_reviewed_asset: no workspace_id, no ws_isolation policy and
-- no forced row-level security, because every workspace reads the same pinned sets and no
-- workspace may own, hide or alter one.
--
-- These sets are generated, never observed.  The table is their own, and it says so in a column,
-- rather than borrowing a recorded artifact's truth status or a flag on a shared row.
--
-- extent_u_mm and extent_v_mm are the physical size one tile covers.  They are what lets a surface
-- carry a UV scale derived from a real dimension: a wall w mm wide repeats the tile w / extent_u_mm
-- times.
create table world_texture_set (
  set_id          text not null check (set_id ~ '^[a-z][a-z0-9.-]*$'),
  version         int not null check (version >= 1),
  title           text not null check (length(btrim(title)) > 0),
  summary         text not null check (length(btrim(summary)) > 0),
  media_type      text not null check (media_type = 'application/vnd.exulanica.texture-set'),
  truth           text not null check (truth = 'invented'),
  content_sha256  text not null unique check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size       int not null check (byte_size > 0),
  width           int not null check (width > 0),
  height          int not null check (height > 0),
  extent_u_mm     int not null check (extent_u_mm > 0),
  extent_v_mm     int not null check (extent_v_mm > 0),
  channels        jsonb not null check (jsonb_typeof(channels) = 'array'),
  licence_id      text not null check (licence_id = 'CC0-1.0'),
  licence_sha256  text not null check (licence_sha256 ~ '^[0-9a-f]{64}$'),
  reviewed_at     timestamptz not null default now(),
  primary key (set_id, version)
);

-- Digests pinned from assets/textures/manifest.json, which loom-texture bakes from source.
-- Rebaking reproduces these exact values; if it ever does not, web/packages/loom-texture's
-- published test and tests/test_texture_set_migration.py fail on the mismatch rather than the
-- schema drifting quietly.  Every set packs the same four maps and carries the same dedication.
insert into world_texture_set
  (set_id,version,title,summary,media_type,truth,content_sha256,byte_size,width,height,
   extent_u_mm,extent_v_mm,channels,licence_id,licence_sha256)
select v.set_id,v.version,v.title,v.summary,'application/vnd.exulanica.texture-set','invented',
       v.content_sha256,v.byte_size,v.width,v.height,v.extent_u_mm,v.extent_v_mm,
       '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
         {"components":3,"holds":["normal_x","normal_y","normal_z"],"map":"normal","srgb":false},
         {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false},
         {"components":1,"holds":["height"],"map":"height","srgb":false}]'::jsonb,
       'CC0-1.0',
       'd51d213f1f5d94acb27403d616b29007802618979c106b075fdbd399fa86310f'
from (values
  ('cc0.brick-running-bond',1,'Brick, running bond',
   'Red to brown fired clay brick in running bond, 215 x 65 mm faces with 10 mm recessed joints.',
   '91791b17a705e45919e38aa42f2dacba961f01c51675efa443bf4a1934650499',10488032,1024,1024,1800,1800),
  ('cc0.carriageway-asphalt',1,'Carriageway asphalt',
   'Worn asphalt with exposed coarse aggregate, oil staining and sparse cracking.',
   '3ed5d23aa14dac2f373cc834c6e98dacf6abcc9b2a484580db6e169b1e280a78',10487904,1024,1024,2000,2000),
  ('cc0.cast-concrete',1,'Cast concrete',
   'Plywood-formed concrete on 1200 x 600 mm panels, with form-tie holes and bug holes.',
   'e2903a77e5841cd5b97d788fb503e8d2faf3fdd09b5eb62ab062e1ded6223c43',10488000,1024,1024,2400,2400),
  ('cc0.footway-paving',1,'Footway paving',
   'Precast concrete flags, 600 x 600 mm, stack bond, 6 mm grit joints, gum spotted.',
   '3c0df2400f0eae3e7a7f6440217762f8eb51e7e7f2c4f8e4f2ebe2919e0707ef',10487936,1024,1024,1800,1800),
  ('cc0.kerb-stone',1,'Kerb stone',
   'Flame-textured grey granite kerb units, 900 mm long with 6 mm joints.',
   '495906d226fb50f827afa0f9b55e386be65adb53e4c2e1fac8a92188f9355bb3',2623520,1024,256,1800,450),
  ('cc0.limestone-ashlar',1,'Limestone ashlar',
   'Buff limestone blocks on a 600 x 300 mm module, half bond, with 5 mm lime joints.',
   '4d7b009dcf2280b1ecff7febc97da6ee584211983d85e5399fe7dfb78d73b60b',10488032,1024,1024,2400,2400),
  ('cc0.painted-render',1,'Painted render',
   'Warm off-white paint over a dashed render finish, flaking on a few raised dashes.',
   '986e2119f33818d7cacf368a7a70fa22766bc9a1922eea35a46c3590ef43ac6d',10487824,1024,1024,2000,2000),
  ('cc0.storefront-metal',1,'Storefront metal',
   'Brushed clear-anodised aluminium with the brushing along u and light smudging.',
   '7178431b117baaef8b2b6de2416631539237bda296a00bb3305071397fb9b41a',10487776,1024,1024,1000,1000)
) as v(set_id,version,title,summary,content_sha256,byte_size,width,height,extent_u_mm,extent_v_mm);

-- --------------------------------------------------------------------------------------------
-- 2. Immutability.  A pinned row is a fact about bytes.
-- --------------------------------------------------------------------------------------------

-- No role updates or deletes a pinned row, and only the role that owns the table, which is the
-- role that runs migrations, adds one.  The ownership test is not decoration.
-- exulanica.db.roles.provision_runtime_role grants insert and update on every table in the schema
-- and revokes them from the tables its READ_ONLY_TABLES names, which include world_texture_set, so
-- a provisioned runtime role holds SELECT here and nothing more.  This trigger is the second wall:
-- a role that is ever handed INSERT or UPDATE on this table by mistake is still refused.
create function tg_world_texture_set_is_migration_data() returns trigger language plpgsql as $fn$
begin
  if tg_op <> 'INSERT' then
    raise exception
      'world_texture_set rows are pinned digests; a rebake is a new version in a new migration'
      using errcode = 'integrity_constraint_violation';
  end if;
  if not pg_has_role(current_user,
                     (select c.relowner from pg_class c where c.oid = tg_relid),
                     'MEMBER') then
    raise exception 'world_texture_set is written by migrations, not by %', current_user
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end $fn$;

create trigger tg_world_texture_set_is_migration_data
  before insert or update or delete on world_texture_set
  for each row execute function tg_world_texture_set_is_migration_data();

-- --------------------------------------------------------------------------------------------
-- 3. Read-only for the runtime.
-- --------------------------------------------------------------------------------------------

-- Reviewed catalogs are migration data.  The runtime reads them and cannot write them, the same
-- rule 0042 applies to world_reviewed_asset, for the two runtime roles exulanica.db.roles
-- provisions.  A role this cluster does not have is skipped rather than failing the migration.
do $$
declare
  r text;
begin
  foreach r in array array['exulanica_app','exulanica_ro'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke insert,update,delete on %I from %I', 'world_texture_set', r);
      execute format('grant select on %I to %I', 'world_texture_set', r);
    end if;
  end loop;
end $$;

commit;
