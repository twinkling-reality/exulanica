-- 0189_a_world_states_its_own_setting.sql
-- A world's style version may state the world's own setting, drawn over the style pack it names:
-- the hour and sky, colours restated, what lies on roofs and ground, and the ground beyond
-- (exulanica.world-setting/v1, exulanica/world/world_settings.py). Like the pack it states no
-- structure, so it is an appearance value: set when a version is inserted, by Apply from a preview
-- or by Rollback from an earlier version, and history is never rewritten. What a setting may say is
-- the domain's, checked against the named pack's own manifests whenever a version is written, so
-- the column holds a document and no foreign key. A version written before this column, and every
-- version of a world drawn as its pack states, holds none.
--
-- A setting is drawn over a pack, so a version naming no pack states none. The size bound is a
-- safety bound of storage: the reader's own bounds (64 roles, 64 upward faces, 64 swatches, one
-- light of 26 values, 8 parts) hold a setting well under it, and every read of a world's
-- appearance sends the document.
--
-- Touches: world_style_version (one nullable column and one check). A proposal already records the
-- pack it asked for as {"pack": {...}} in world_style_proposal.style_pack (0141), and the setting
-- it asked for rides inside that object, so that table is not altered.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_style_version
  add column style_pack_setting jsonb;

-- Written so a NULL cannot make it pass: each term is explicit.
alter table world_style_version add constraint world_style_version_setting_is_a_setting check (
  style_pack_setting is null or (
    style_pack_id is not null
    and jsonb_typeof(style_pack_setting) = 'object'
    and style_pack_setting ->> 'profile' is not null
    and style_pack_setting ->> 'profile' = 'exulanica.world-setting/v1'
    and octet_length(style_pack_setting::text) <= 32768)
);

commit;
