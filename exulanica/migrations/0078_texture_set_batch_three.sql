-- 0078_texture_set_batch_three.sql
-- Six more pinned texture sets: the shopfront's painted timber, awning canvas and fascia panel, the
-- road's white and yellow marking paint, and the soil of a tree pit.
--
-- Pinned exactly as 0065 pins and as 0076 pinned batch 1, from assets/textures/manifest.json, which
-- loom-texture bakes from source: rebaking reproduces these bytes, and
-- web/packages/loom-texture's published test and tests/test_texture_set_class_migration.py fail on
-- any mismatch.  Each set's class and container profile go in the companion table 0076 created, in
-- the same transaction, because that table's deferred trigger refuses a pinned set with no class.
--
-- Two of these are the first pinned sets of the DECAL class: a marking is drawn over the
-- carriageway and blended by its coverage, so its colour map carries four components and the
-- renderer writes no depth for it.  They are also the first pinned sets whose tile is not square in
-- the v2 container, though not the first that is not square at all: cc0.kerb-stone has been 1024 by
-- 256 texels over 1800 by 450 mm since 0065, so these columns have carried a tile longer than it is
-- wide from the start, and each axis is stated on its own here as it is there.
--
-- Every number is an integer in the unit its column names, and every name is one the texture
-- package's readers already refuse any other spelling of.

begin;

select pg_advisory_xact_lock(119622310);

-- --------------------------------------------------------------------------------------------
-- 1. The sets.
-- --------------------------------------------------------------------------------------------

insert into world_texture_set
  (set_id,version,title,summary,media_type,truth,content_sha256,byte_size,width,height,
   extent_u_mm,extent_v_mm,channels,licence_id,licence_sha256)
select v.set_id,v.version,v.title,v.summary,'application/vnd.exulanica.texture-set','invented',
       v.content_sha256,v.byte_size,v.width,v.height,v.extent_u_mm,v.extent_v_mm,v.channels,
       'CC0-1.0',
       'd51d213f1f5d94acb27403d616b29007802618979c106b075fdbd399fa86310f'
from (values

  ('cc0.awning-canvas',1,'Awning canvas',
   'Striped woven canvas for a shop awning, sagging between its rafters, faded by the sun and streaked where rain runs down the slope.',
   'b94be437c837a7afc8529995f99271b8a5f17287a04b04bcc30ce0122d703c32',2099088,512,512,1000,1000,
   '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb),
  ('cc0.painted-timber',1,'Painted timber',
   'Painted wood for shopfront doors, frames and stall boards, with grain showing through the paint, brush marks, chips and grime.',
   '2554cb0f6da638364776806faaaf46dc1e021a02905ecd85083776c474304157',2099040,512,512,1000,1000,
   '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb),
  ('cc0.road-paint-white',1,'Road paint, white',
   'White thermoplastic road marking for lane lines, stop bars and crossings, worn through in the tracks where tyres run.',
   '43678e7000744cf366957c82371078cfa77f9897f920b94f86d2d77a6d2e2035',149536,256,64,1000,250,
   '[{"components":4,"holds":["red","green","blue","coverage"],"map":"base_color_coverage","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb),
  ('cc0.road-paint-yellow',1,'Road paint, yellow',
   'Yellow thermoplastic road marking for centre lines, worn through in the tracks where tyres run.',
   'e97e4abe1ed7ea48af15c53dbccb01a1925eb12ecd66e7f887bda12789a3d01e',149520,256,64,1000,250,
   '[{"components":4,"holds":["red","green","blue","coverage"],"map":"base_color_coverage","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb),
  ('cc0.sign-panel',1,'Sign panel',
   'A sprayed sheet panel for a shopfront fascia: an even ground for lettering, with the joint between sheets and light weathering, and no lettering of its own.',
   'e2733280fa6813f7fbd66358d16a325f514cd4684621f16bc18c9e8088fac23e',2099136,512,512,1000,1000,
   '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb),
  ('cc0.tree-pit-soil',1,'Tree pit soil',
   'The dug bed of a street tree pit: clods of damp earth with the stones the digging left, darker in the hollows where water sits.',
   'e721fbad53136668c61af04bc717f5f904559ea5a17593b505a897090cec517b',2099088,512,512,900,900,
   '[{"components":3,"holds":["red","green","blue"],"map":"base_color","srgb":true},
     {"components":2,"holds":["normal_x","normal_y"],"map":"normal","srgb":false},
     {"components":3,"holds":["occlusion","roughness","metalness"],"map":"orm","srgb":false}]'::jsonb)
) as v (set_id,version,title,summary,content_sha256,byte_size,width,height,
        extent_u_mm,extent_v_mm,channels);

-- --------------------------------------------------------------------------------------------
-- 2. What kind of surface each one is.
-- --------------------------------------------------------------------------------------------

insert into world_texture_set_class (set_id, version, container_profile, material_class) values
  ('cc0.awning-canvas', 1, 'exulanica.texture-set/v2', 'opaque'),
  ('cc0.painted-timber', 1, 'exulanica.texture-set/v2', 'opaque'),
  ('cc0.road-paint-white', 1, 'exulanica.texture-set/v2', 'decal'),
  ('cc0.road-paint-yellow', 1, 'exulanica.texture-set/v2', 'decal'),
  ('cc0.sign-panel', 1, 'exulanica.texture-set/v2', 'opaque'),
  ('cc0.tree-pit-soil', 1, 'exulanica.texture-set/v2', 'opaque');

commit;
