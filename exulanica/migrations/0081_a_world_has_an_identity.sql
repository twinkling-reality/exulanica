-- 0081_a_world_has_an_identity.sql
-- `city_seed` was the name of a concept that is not a city. It is the identity of a generated
-- world instance, and a city is one kind of world.
--
-- Target: PostgreSQL 18, same as 0001. Forward-only, same as 0001.
--
-- WHY THIS IS A CONVENTION RATHER THAN A CITY'S BUSINESS. A grammar already declares its own
-- nature as data: `box.v1.json` states `grammar_id: box`, `subject_kind: box` and two cascade
-- levels, against the city's six, and nothing in `exulanica/grammar/` compares a grammar id to
-- "city". The generation layer is genuinely plural already. What was not plural is the layer
-- underneath it, where every world kind's tiles are stored, listed and served, and that layer
-- spelled the identity after one of the kinds.
--
-- THE LOAD-BEARING ARGUMENT IS THE CROSS-GRAMMAR ONE. This column holds a value the grammar's
-- tile record states, so it is tempting to call it content and let a forest name its own. IT MUST
-- NOT. Code that composes a world out of neighbouring tiles is generic over grammars: it asks a
-- row for the world it belongs to and compares that against what a container states. If the city
-- says `city_seed` and a forest says `forest_seed`, that code needs a case per grammar, which is
-- a gate that enumerates and goes silent about the kind nobody thought of. The identity has ONE
-- NAME ACROSS EVERY GRAMMAR or composition cannot be written once.
--
-- The kind of world is NOT carried by a second column, and that is the point rather than an
-- omission. It is already carried by the grammar the tile pins, in `grammar_pins`. A city is a
-- world whose records are in the city grammar, which is what makes city one kind among many
-- rather than the name of the container.
--
-- WHAT MOVES AND WHAT DOES NOT.
--
--   nothing stored moves.  Every row keeps every value, every key, every digest. A rename of a
--                          column is a rename of a name, and `tile_inputs_digest`,
--                          `container_sha256` and both projection digests are computed over
--                          bytes this migration does not touch. Nothing is rebaked.
--   the index is renamed   with the column it leads on, because an index called `by_city` on a
--                          column called `world_seed` is a second place the old word survives to
--                          be read as authoritative by whoever meets it first.
--   the function is        `create or replace function` cannot rename an input parameter, so the
--   dropped and made      function is dropped and recreated. Its body, its lock, its outcomes and
--   again                  its refusals are 0072's, unchanged, and only the parameter's spelling
--                          and the column it writes differ. The trigger on `baked_tile` names
--                          `tg_baked_tile_guard` and is not touched by this.
--
-- WHAT THIS DELIBERATELY DOES NOT REACH, so nobody reads its absence as an oversight.
--
--   THE TILE RECORD'S OWN FIELD IS STILL `city_seed`. A column is a name inside this database; a
--   key in a baked record is a fact about bytes, and changing it moves every digest and needs a
--   grammar version. That change is city grammar version 4 and it is not this migration. Until it
--   lands, `BakedTileRepository.record` reads the grammar's spelling out of the tile record it is
--   handed and writes it into the column named here, and it says so where it does it.
--
--   THE ROUTE STILL ANSWERS `city_seed` ON THE WIRE, in its query parameter and in its response
--   body, because one line of production code in `web/packages/atlas-react` builds that parameter
--   and renaming a wire is a coordinated release rather than a migration.
--   `tests/test_corridor_tile_route.py` holds the route to both spellings so that decision is
--   checked rather than merely written down.

begin;
select pg_advisory_xact_lock(119622309);

alter table baked_tile rename column city_seed to world_seed;
alter index baked_tile_by_city rename to baked_tile_by_world;

drop function record_baked_tile_bake(
  uuid, int, bytea, bytea, bytea, jsonb, bytea, bytea, int, int, int, int, int,
  bytea, bigint, bytea, bigint, bytea, bytea, jsonb
);

-- 0072's function, with one parameter renamed and the column it writes renamed with it.
create function record_baked_tile_bake(
  p_baked_tile_id       uuid,
  p_stage_version       int,
  p_stage_params_sha256 bytea,
  p_tile_inputs_digest  bytea,
  p_world_seed          bytea,
  p_grammar_pins        jsonb,
  p_catalog_digest      bytea,
  p_edit_delta_digest   bytea,
  p_tile_x              int,
  p_tile_y              int,
  p_lod                 int,
  p_tile_size_mm        int,
  p_halo_radius_mm      int,
  p_document_sha256     bytea,
  p_document_bytes      bigint,
  p_container_sha256    bytea,
  p_container_bytes     bigint,
  p_render_batch_sha256 bytea,
  p_nav_envelope_sha256 bytea,
  p_receipt             jsonb
) returns text language plpgsql as $fn$
declare
  stored record;
begin
  perform pg_advisory_xact_lock(hashtextextended('baked-tile:' || p_baked_tile_id::text, 0));
  select * into stored from baked_tile where baked_tile_id = p_baked_tile_id;
  if not found then
    insert into baked_tile (
      baked_tile_id, stage_key, stage_version, stage_params_sha256, tile_inputs_digest,
      world_seed, grammar_pins, catalog_digest, edit_delta_digest, tile_x, tile_y, lod,
      tile_size_mm, halo_radius_mm, document_sha256, document_bytes, container_sha256,
      container_bytes, store_namespace, render_batch_sha256, nav_envelope_sha256, receipt, state
    ) values (
      p_baked_tile_id, 'baked_tile', p_stage_version, p_stage_params_sha256, p_tile_inputs_digest,
      p_world_seed, p_grammar_pins, p_catalog_digest, p_edit_delta_digest, p_tile_x, p_tile_y,
      p_lod, p_tile_size_mm, p_halo_radius_mm, p_document_sha256, p_document_bytes,
      p_container_sha256, p_container_bytes, 'tiles', p_render_batch_sha256, p_nav_envelope_sha256,
      p_receipt, 'baked'
    );
    return 'stored';
  end if;
  if stored.container_sha256 = p_container_sha256 then
    if stored.state = 'nondeterminism_detected' then
      return 'nondeterminism_detected';
    end if;
    return 'identical';
  end if;
  update baked_tile
     set state = 'nondeterminism_detected',
         fault_container_sha256 = p_container_sha256,
         fault_detected_at = statement_timestamp()
   where baked_tile_id = p_baked_tile_id
     and state = 'baked';
  return 'nondeterminism_detected';
end $fn$;

commit;
