-- 0105_a_world_offers_furniture_its_inhabitants_use.sql
-- The world object catalog's furniture, as reviewed assets a person can place.
--
-- assets/catalogs/world-objects/world-object.v1.json states every kind a person may place in a
-- world: its title and summary, the recipe its mesh is generated from, the CC0 texture sets that
-- dress it and what inhabitants do with it (exulanica/world/object_catalog.py reads and checks it).
-- The three grey markers 0042 pinned are entries there too, generated exactly as 0042 pinned them,
-- so this migration leaves their rows alone and adds a row for every other kind.
--
-- A row is the reviewed decision; the bytes live in the content-addressed store and are put there
-- by exulanica.world.assets.seed_reviewed_assets, as 0042 explains. Each container carries its own
-- glTF materials, with the texture maps it is drawn in embedded as images, so it is drawn as it is
-- declared and needs nothing else from the server. The licence text the rows name is the textured
-- dedication (exulanica.world.assets.CC0_TEXTURED_LICENCE_TEXT), which covers the geometry and the
-- maps; the markers keep the geometry-only text 0042 pinned.
--
-- Digests pinned from exulanica/world/assets.py, which generates these containers rather than
-- committing them. Regenerating from source reproduces these exact values; if it ever does not,
-- tests/test_world_object_catalog.py fails on the mismatch rather than the schema drifting
-- quietly. Every row is an object (0101): a person places each one on its own.
begin;
select pg_advisory_xact_lock(119622309);

insert into world_reviewed_asset
  (asset_key,title,summary,media_type,content_sha256,byte_size,licence_id,licence_sha256,kind) values
  ('cc0.bench','Bench',
   'A timber bench 1.8 metres long with a back, on painted metal legs.',
   'model/gltf-binary',
   '8ea23ec0a432a8f4fcbf58558fd34b7531698eb74089aa54ed324360082d7d09',1190308,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','object'),
  ('cc0.cafe-table','Cafe table with two chairs',
   'A round cafe table with a chair on each side, timber tops on painted metal legs.',
   'model/gltf-binary',
   '35f20a0f5b344939af79d993c06d7bb79e792a68f72f6ba5ca3cc8ec83864fe5',1208836,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','object'),
  ('cc0.planter-tree','Tree in a planter',
   'A young broadleaf tree in a square timber planter.',
   'model/gltf-binary',
   '5dea98bea3ed30dac4cdfb7704b824779993324f72d27c9767ea0f6b1d548f89',2453464,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','object'),
  ('cc0.lamp-post','Lamp post',
   'A painted metal lamp post six metres high with an arm and a lamp.',
   'model/gltf-binary',
   '2aa3788af6d6c6eee5916e606210cc600b9fccd6b84b31bc58d1adee61e80bde',597084,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','object'),
  ('cc0.market-stall','Market stall',
   'A timber serving counter under a striped canvas awning on painted metal posts.',
   'model/gltf-binary',
   '60b794c890339f0b296d9eb1b4edfc63ce6f614eda3fcc08f8e330b8ecc1d1f8',1785232,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','object'),
  ('cc0.seating-planter','Planter seat',
   'A long timber planter with a seat along its front and a low hedge along its back.',
   'model/gltf-binary',
   '385530a43f4b89a0bf2fdede6fae0666400651e8a5f20e11390b49d41fd38f61',1852036,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','object');

commit;
