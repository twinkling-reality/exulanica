-- 0114_a_tree_s_birds_are_reviewed_components.sql
-- The flight kind catalog's bodies, as reviewed components the flight renderer draws.
--
-- assets/catalogs/movement/flight-kind.v1.json states every kind that flies: the movement module
-- it flies by, its figures, and the recipes its body and one wing are generated from
-- (exulanica/world/flight_kinds.py reads and checks it). A world object that hosts a kind, the
-- planter tree hosting three small birds (world-object.v3.json), brings its flyers into a saved
-- world's flight, and the renderer draws each one from these two containers: the body once and
-- the wing on each side.
--
-- A row is the reviewed decision; the bytes live in the content-addressed store and are put there
-- by exulanica.world.assets.seed_reviewed_assets, as 0042 explains. Each container carries its own
-- glTF materials with the texture maps it is drawn in embedded, and the licence text the rows name
-- is the textured dedication (exulanica.world.assets.CC0_TEXTURED_LICENCE_TEXT), as 0105's rows do.
--
-- Digests pinned from exulanica/world/flight_kinds.py, which generates these containers rather
-- than committing them. Regenerating from source reproduces these exact values; if it ever does
-- not, tests/test_flight_kinds.py fails on the mismatch. Both rows are components (0101): nobody
-- places a bird's body as an object, and placing one is refused by name.
begin;
select pg_advisory_xact_lock(119622309);

insert into world_reviewed_asset
  (asset_key,title,summary,media_type,content_sha256,byte_size,licence_id,licence_sha256,kind) values
  ('cc0.small-bird-body','Small bird: body',
   'The body of a small bird, drawn by the flight renderer.',
   'model/gltf-binary',
   'eeb4a5eedff73a0e94ddb993715cd9464da945592fc0500779fc5372e085c798',99496,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','component'),
  ('cc0.small-bird-wing','Small bird: wing',
   'One wing of a small bird, drawn on both sides of its body.',
   'model/gltf-binary',
   '878a1dcb8a1f77e807c60749a9056ef88ec066295d3e4758531bab0036cdc658',40504,'CC0-1.0',
   '3ada8de3b91df178fae9ca03e7aca4af4cee19ec3dfe454d9811640157d6668b','component');

commit;
