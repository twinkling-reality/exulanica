-- 0141_a_world_style_version_names_its_style_pack.sql
-- A world's style version names the style pack it is drawn in: a pack of the host's committed
-- library, by id, version and the SHA-256 of its manifest, or none, when the page's default look
-- draws it. A pack states no structure, so the binding is an appearance value like the profile's
-- parameters: it is set when a version is inserted, by Apply from a preview or by Rollback from an
-- earlier version, and history is never rewritten. Which packs exist is the library's
-- (exulanica/world/style_pack_library.py), checked by the domain whenever a version is written,
-- so the binding is a value and not a foreign key. A version written before this column names no
-- pack.
--
-- A proposal records the pack it asked for as the request stated it: SQL NULL when the request
-- named none, so its preview keeps its base version's pack; {"pack": null} when it asked for no
-- pack; {"pack": {"pack_id", "version", "manifest_sha256"}} when it asked for one. Like the
-- profile and parameters beside it, a refused request is kept as sent.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_style_version
  add column style_pack_id text,
  add column style_pack_version int,
  add column style_pack_manifest_sha256 text;

-- Every comparison is written so a NULL cannot make it pass: a check whose value is NULL holds,
-- so a version naming only part of a pack is refused by the explicit "is not null" terms.
alter table world_style_version add constraint world_style_version_style_pack_is_whole check (
  (style_pack_id is null and style_pack_version is null and style_pack_manifest_sha256 is null) or
  (style_pack_id is not null and style_pack_version is not null
    and style_pack_manifest_sha256 is not null
    and style_pack_id ~ '^[a-z][a-z0-9-]{0,31}(\.[a-z][a-z0-9-]{0,31}){1,3}$'
    and style_pack_version between 1 and 1000000
    and style_pack_manifest_sha256 ~ '^[0-9a-f]{64}$')
);

alter table world_style_proposal
  add column style_pack jsonb check (
    style_pack is null or (jsonb_typeof(style_pack) = 'object' and style_pack ? 'pack'));

commit;
